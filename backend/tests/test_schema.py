"""M3 契约与真实模型适配器测试:J01-J05,S12 及 live 适配器行为。"""

import json

import httpx
import pytest

from app.config import Settings
from app.domain import settlement
from app.llm.base import ModelContext, ModelOutputInvalid, ModelTimeout, ModelUnavailable, build_adapter
from app.llm.live import SYSTEM_RULES, LiveAdapter, build_user_prompt
from app.llm.schema import OUTPUT_SCHEMA_TEXT, AcceptedCandidate, Candidate, parse_candidate
from app.services.game_service import GameService, ServiceError

from conftest import ScriptedAdapter

VALID_ACCEPTED = {
    "kind": "accepted",
    "normalized_goal": "赈济灾州",
    "tags": ["relief"],
    "policy_analysis": {"benefits": ["灾民得食，饥情缓解"], "costs": ["官仓减少，需要保留后续口粮"], "risks": [], "effect_basis": "赈粮带来的安民收益高于当下转运负担，但消耗库存"},
    "policy_effect": {"people": 5, "treasury": -6, "grain": -8},
    "echo_effects": [],
    "advisor": "陛下,赈灾诏令已传至各州。",
    "reactions": [
        {"speaker": "tian_bo", "text": "乡亲们都念着陛下的恩德!"},
        {"speaker": "gu_tingzhang", "text": "赈灾诚是仁政。"},
    ],
    "new_echoes": [{"delay": 1, "reason": "核验赈粮送达情况"}],
    "summary": "饥情缓解,粮储承压。",
}

VALID_CLARIFICATION = {
    "kind": "clarification",
    "warning_type": "unclear",
    "message": "此诏语义无法辨认,请陛下重新明诏。",
}


def parse_json(payload):
    return parse_candidate(json.dumps(payload, ensure_ascii=False))


# ---------- J01 非JSON、额外字段、缺少advisor ----------


def test_j01_non_json_rejected():
    with pytest.raises(ValueError):
        parse_candidate("这不是JSON")


def test_j01_markdown_fence_rejected():
    with pytest.raises(ValueError):
        parse_candidate("```json\n" + json.dumps(VALID_ACCEPTED) + "\n```")


def test_j01_extra_field_rejected():
    payload = dict(VALID_ACCEPTED, final_people=80)
    with pytest.raises(ValueError):
        parse_json(payload)


def test_j01_missing_advisor_rejected():
    payload = {k: v for k, v in VALID_ACCEPTED.items() if k != "advisor"}
    with pytest.raises(ValueError):
        parse_json(payload)


# ---------- J02 people 为 true、3.5 或字符串"5" → 严格拒绝 ----------


@pytest.mark.parametrize("bad_people", [True, 3.5, "5"])
def test_j02_strict_int_rejected(bad_people):
    payload = dict(VALID_ACCEPTED)
    payload["policy_effect"] = {"people": bad_people, "treasury": 0, "grain": 0}
    with pytest.raises(ValueError):
        parse_json(payload)


# ---------- J03 单政策 people=99 → 拒绝而非静默改为 8 ----------


def test_j03_policy_99_rejected_by_semantics():
    payload = dict(VALID_ACCEPTED)
    payload["policy_effect"] = {"people": 99, "treasury": 0, "grain": 0}
    candidate = parse_json(payload)
    assert isinstance(candidate, AcceptedCandidate)
    errors = settlement.validate_candidate_semantics(
        {
            "kind": "accepted",
            "normalized_goal": candidate.normalized_goal,
            "tags": candidate.tags,
            "policy_effect": {
                "people": 99,
                "treasury": 0,
                "grain": 0,
            },
            "echo_effects": [],
            "advisor": candidate.advisor,
            "reactions": [r.model_dump() for r in candidate.reactions],
            "new_echoes": [],
            "summary": candidate.summary,
        },
        [],
        1,
    )
    assert any("people=99" in e for e in errors)


# ---------- J04 重复角色、未知角色、反应不足 2 条 ----------


def test_j04_too_few_reactions_rejected():
    payload = dict(VALID_ACCEPTED)
    payload["reactions"] = [VALID_ACCEPTED["reactions"][0]]
    with pytest.raises(ValueError):
        parse_json(payload)


def test_j04_duplicate_speakers_rejected_by_semantics():
    payload = dict(VALID_ACCEPTED)
    payload["reactions"] = [
        {"speaker": "tian_bo", "text": "一说。"},
        {"speaker": "tian_bo", "text": "又说。"},
    ]
    candidate = parse_json(payload)
    errors = settlement.validate_candidate_semantics(
        {
            "kind": "accepted",
            "normalized_goal": candidate.normalized_goal,
            "tags": candidate.tags,
            "policy_effect": {"people": 0, "treasury": 0, "grain": 0},
            "echo_effects": [],
            "advisor": candidate.advisor,
            "reactions": [r.model_dump() for r in candidate.reactions],
            "new_echoes": [],
            "summary": candidate.summary,
        },
        [],
        1,
    )
    assert any("重复角色" in e for e in errors)


def test_j04_unknown_speaker_rejected():
    payload = dict(VALID_ACCEPTED)
    payload["reactions"] = [
        {"speaker": "shen_yan", "text": "臣附议。"},
        {"speaker": "tian_bo", "text": "乡野之见。"},
    ]
    with pytest.raises(ValueError):
        parse_json(payload)


# ---------- J05 模型直接返回 status、turn_no 或最终分数 → 结构拒绝 ----------


@pytest.mark.parametrize(
    "extra",
    [{"status": "won"}, {"turn_no": 9}, {"final_people": 80}, {"kind": "won"}],
)
def test_j05_rule_fields_rejected(extra):
    payload = dict(VALID_ACCEPTED)
    payload.update(extra)
    with pytest.raises(ValueError):
        parse_json(payload)


# ---------- 有效输出解析 ----------


def test_parse_valid_accepted_and_clarification():
    accepted = parse_json(VALID_ACCEPTED)
    assert isinstance(accepted, AcceptedCandidate)
    assert accepted.policy_effect.people == 5
    clarified = parse_json(VALID_CLARIFICATION)
    assert clarified.kind == "clarification"


# ---------- live 适配器:调用、修复、失败与不降级 ----------


class FakePost:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def ok_response(payload):
    return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(payload, ensure_ascii=False)}}]})


@pytest.fixture()
def live():
    return LiveAdapter(base_url="http://model.local/v1", api_key="test-key", model="test-model", timeout_seconds=5.0)


def _context():
    return ModelContext(
        game={"people": 50, "treasury": 60, "grain": 60},
        turn_no=1,
        period="承和元年至三年",
        history=[],
        due_echoes=[],
        player_policy="赈济灾民。",
    )


def test_live_valid_response(live, monkeypatch):
    fake = FakePost([ok_response(VALID_ACCEPTED)])
    monkeypatch.setattr("app.llm.live.httpx.post", fake)
    candidate = live.evaluate(_context())
    assert candidate.kind == "accepted"
    assert len(fake.calls) == 1
    assert fake.calls[0]["url"] == "http://model.local/v1/chat/completions"
    assert fake.calls[0]["json"]["response_format"] == {"type": "json_object"}


def test_live_repair_once_then_valid(live, monkeypatch):
    fake = FakePost(
        [
            httpx.Response(200, json={"choices": [{"message": {"content": "坏输出"}}]}),
            ok_response(VALID_ACCEPTED),
        ]
    )
    monkeypatch.setattr("app.llm.live.httpx.post", fake)
    candidate = live.evaluate(_context())
    assert candidate.kind == "accepted"
    assert len(fake.calls) == 2
    assert fake.calls[1]["json"]["temperature"] == 0.2


def test_live_twice_invalid_raises(live, monkeypatch):
    fake = FakePost(
        [
            httpx.Response(200, json={"choices": [{"message": {"content": "坏输出"}}]}),
            httpx.Response(200, json={"choices": [{"message": {"content": "还是坏"}}]}),
        ]
    )
    monkeypatch.setattr("app.llm.live.httpx.post", fake)
    with pytest.raises(ModelOutputInvalid) as exc:
        live.evaluate(_context())
    assert "两次均不符合契约" in str(exc.value)


def test_live_repair_shares_total_timeout_budget(live, monkeypatch):
    fake = FakePost(
        [
            httpx.Response(200, json={"choices": [{"message": {"content": "坏输出"}}]}),
            ok_response(VALID_ACCEPTED),
        ]
    )
    monkeypatch.setattr("app.llm.live.httpx.post", fake)
    monkeypatch.setattr("app.llm.live.time.monotonic", iter([0.0, 1.0, 6.0]).__next__)
    with pytest.raises(ModelTimeout):
        live.evaluate(_context())
    assert len(fake.calls) == 1
    assert fake.calls[0]["timeout"] == 4.0


def test_live_http_500_unavailable(live, monkeypatch):
    fake = FakePost([httpx.Response(500, json={"error": "boom"})])
    monkeypatch.setattr("app.llm.live.httpx.post", fake)
    with pytest.raises(ModelUnavailable):
        live.evaluate(_context())


def test_live_timeout(live, monkeypatch):
    fake = FakePost([httpx.TimeoutException("慢")])
    monkeypatch.setattr("app.llm.live.httpx.post", fake)
    with pytest.raises(ModelTimeout):
        live.evaluate(_context())


def test_live_connect_error_unavailable(live, monkeypatch):
    fake = FakePost([httpx.ConnectError("拒绝连接")])
    monkeypatch.setattr("app.llm.live.httpx.post", fake)
    with pytest.raises(ModelUnavailable):
        live.evaluate(_context())


def test_build_user_prompt_sections():
    context = _context()
    context.due_echoes = [{"id": "echo-1", "source_policy_id": "policy-1", "reason": "核验"}]
    prompt = build_user_prompt(context)
    for section in ("【当前状态】", "【已结算历史】", "【本回合到期回声】", "【玩家圣旨】", "【输出契约】"):
        assert section in prompt
    assert "echo-1" in prompt
    assert "民心 50" in prompt
    assert "第 1 / 8 回合" in prompt
    assert "每回合三年" in prompt
    assert "承和元年至三年" in prompt


# ---------- S12 live 故障不降级为 fixture ----------


class _FakeSettings:
    llm_mode = "live"
    llm_base_url = ""
    llm_api_key = ""
    llm_model = ""
    llm_timeout_seconds = 5.0


def test_s12_live_mode_missing_config_refuses_startup():
    with pytest.raises(RuntimeError) as exc:
        build_adapter(_FakeSettings())
    assert "LLM_BASE_URL" in str(exc.value)
    assert "LLM_API_KEY" in str(exc.value)
    assert "LLM_MODEL" in str(exc.value)


def test_s12_service_never_falls_back_to_fixture(db):
    adapter = ScriptedAdapter(default=ModelUnavailable("模型挂了"))
    service = GameService(db, adapter)
    game = service.create_game()["game"]
    for i in range(2):
        with pytest.raises(ServiceError) as exc:
            service.submit_turn(game["id"], f"s12-{i}", 0, "今夏旱情频仍,着户部拨银赈济灾民,开仓放粮。")
        assert exc.value.code == "MODEL_OUTPUT_INVALID"
        assert exc.value.status_code == 502
    assert db.get_game(game["id"])["accepted_turns"] == 0


# ---------- 时代与语义警告、古代角色沉浸 ----------


def test_output_schema_limits_clarification_to_four_warning_types():
    assert "只有时代错位、多个独立目标、非政令或语义不明这四类情况允许输出警告" in OUTPUT_SCHEMA_TEXT
    for warning_type in ("anachronism", "multiple_goals", "not_policy", "unclear"):
        assert f'"warning_type":"{warning_type}"' in OUTPUT_SCHEMA_TEXT
    assert '"kind":"accepted"' in OUTPUT_SCHEMA_TEXT
    assert "一个明确治理目标可以含配套措施" in OUTPUT_SCHEMA_TEXT
    assert "忠实玩家原意" in OUTPUT_SCHEMA_TEXT
    assert "完全以对应古代人物身份" in OUTPUT_SCHEMA_TEXT


def test_system_rules_require_immersion_semantics_and_natural_reactions():
    assert "除上述四类外不得澄清" in SYSTEM_RULES
    assert "每回合代表三年,共八回合、二十四年" in SYSTEM_RULES
    assert "delay=1表示三年后,delay=2表示六年后" in SYSTEM_RULES
    for warning_type in ("anachronism", "multiple_goals", "not_policy", "unclear"):
        assert f"warning_type={warning_type}" in SYSTEM_RULES
    assert "只要有一个清楚治理方向,就必须接受并结算" in SYSTEM_RULES
    assert "不得擅自猜成政策" in SYSTEM_RULES
    assert "生活在架空大晟朝" in SYSTEM_RULES
    assert "人物知晓真实历史事件、制度和做法" in SYSTEM_RULES
    assert "不向陛下提及模型、程序、游戏、玩家或任务指令" in SYSTEM_RULES
    assert "沈砚是御前辅臣" in SYSTEM_RULES
    assert "田伯是种了一辈子地的乡老" in SYSTEM_RULES
    assert "宋知远是奔走南北的商帮会首" in SYSTEM_RULES
    assert "顾廷章是地方士绅代表" in SYSTEM_RULES
    assert "不得每次都怀疑官差、加派或摊派" in SYSTEM_RULES
    assert "不要让人物固定质疑或对抗圣旨" in SYSTEM_RULES
    assert "不得预设政策一定出错" in SYSTEM_RULES
    assert "忠实转述有效圣旨的原意" in SYSTEM_RULES
    assert "可以自动补全谁去办、怎么办、钱粮从哪儿出" in SYSTEM_RULES
    assert "禁止因为有效诏书不够详细而判定失误或失败" in SYSTEM_RULES


def test_invalid_llm_mode_refuses_startup(monkeypatch):
    monkeypatch.setenv("LLM_MODE", "invalid")
    with pytest.raises(ValueError, match="LLM_MODE"):
        Settings()


def test_unknown_adapter_mode_never_defaults_to_fixture():
    settings = _FakeSettings()
    settings.llm_mode = "invalid"
    with pytest.raises(RuntimeError, match="未知 LLM_MODE"):
        build_adapter(settings)
