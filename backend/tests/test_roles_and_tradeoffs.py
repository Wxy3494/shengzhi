"""Model orchestration and atomicity, with isolated scripted provider responses."""
import json

import pytest

from app.domain.narration import narration_errors, prose_is_safe
from app.domain.policies import identify
from app.llm.base import ModelContext, ModelOutputInvalid, ModelTimeout
from app.llm.live import LiveAdapter, parse_evaluation
from app.llm.schema import candidate_to_dict
from app.services.game_service import GameService, ServiceError
from conftest import ScriptedAdapter, make_accepted, set_state


ANALYSIS = {
    "benefits": ["轻罪者返乡，与家人重新谋生，积案得减"],
    "costs": ["受害者可能感到不公，地方须重新核对罪籍"],
    "risks": [{"condition": "重犯一并获释且安置不足", "consequence": "再犯增加，行旅和乡里受扰", "likelihood": "medium", "horizon": "delayed"}],
    "effect_basis": "释囚缓和部分民怨，但受害者不满抵消部分收益，治安后患待返乡后查考",
}


def role_texts(turn=1):
    return [
        {"speaker": "tian_bo", "text": f"这道诏令到了乡里，俺们最关心田里生计。此番第{turn}次施行，还得看乡亲实际得了什么。"},
        {"speaker": "song_zhiyuan", "text": f"第{turn}次办理此事，商队赶路是否安稳、货期能否守住，是行商眼前的牵挂。"},
        {"speaker": "gu_tingzhang", "text": f"第{turn}次施行，地方既须承接善意，也须顾及受损人家的公道与乡里秩序。"},
    ]


class Narrator(ScriptedAdapter):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.narrations = []

    def narrate(self, context, data, facts):
        self.narrations.append(facts)
        return {**data, "advisor": "陛下，仓中无粮，此诏未能施行，饥户仍须另寻生计。" if facts["blocked"] else "陛下，此诏的益处与地方所担之累，应一并看待。", "summary": "仓粮不足，赈济未能实施。" if facts["blocked"] else "善意有所及，地方亦有取舍。", "reactions": role_texts(context.turn_no)}


@pytest.mark.parametrize("scenario", ["zero", "repeat", "tax", "revoked"])
def test_constrained_turn_always_calls_narrator_without_template(db, monkeypatch, scenario):
    def forbidden(*args):
        raise AssertionError("model-backed turns must never call a canned fallback")
    monkeypatch.setattr("app.services.game_service.factual_narration", forbidden)
    adapter = Narrator(default=make_accepted(policy_effect={"people": 6, "treasury": -5, "grain": -8}))
    svc = GameService(db, adapter)
    game = svc.create_game()["game"]
    if scenario == "zero":
        set_state(db, game["id"], grain=0)
        text = "开仓赈济灾州"
    elif scenario == "repeat":
        game = svc.submit_turn(game["id"], "first", 0, "修城西水渠")["game"]
        text = "疏浚西郊沟渠"
    elif scenario == "revoked":
        game = svc.submit_turn(game["id"], "first", 0, "开仓赈济灾州")["game"]
        game = svc.submit_turn(game["id"], "stop", 1, "撤销灾州赈济令")["game"]
        text = "灾州少收些田税"
    else:
        text = "田税少收一点"
    result = svc.submit_turn(game["id"], "target", game["revision"], text)["result"]
    assert adapter.narrations[-1]["constraint_notes"]
    assert result["narration_source"] == "model"
    assert len(result["reactions"]) == 3
    assert result["reactions"] == role_texts(result["turn_no"])
    assert svc.get_game_detail(game["id"])["history"][-1]["reactions"] == result["reactions"]


def test_tradeoffs_and_causal_risk_survive_storage_and_next_turn_context(db):
    adapter = Narrator(default=make_accepted(policy_analysis=ANALYSIS, new_echoes=[{"delay": 1, "reason": "赦免者返乡后，安置不足可能使再犯增加"}]))
    svc = GameService(db, adapter)
    game = svc.create_game()["game"]
    first = svc.submit_turn(game["id"], "amnesty", 0, "大赦天下")
    saved = svc.get_game_detail(game["id"])["history"][0]
    assert saved["policy_analysis"] == ANALYSIS
    echo_id = first["result"]["new_echoes"][0]["id"]
    adapter.default = make_accepted(echo_effects=[{"echo_id": echo_id, "people": -2, "treasury": -1, "grain": 0, "explanation": "部分释囚无着，再犯使行旅不安"}])
    second = svc.submit_turn(game["id"], "road", 1, "整修官道")
    assert second["result"]["echo_effects"][0]["source_policy_id"] == first["result"]["policy_id"]
    assert adapter.calls[-1].due_echoes[0]["reason"] == first["result"]["new_echoes"][0]["reason"]
    assert adapter.calls[-1].history[0]["reactions"] == first["result"]["reactions"]


@pytest.mark.parametrize("failure,status", [(ModelTimeout("slow"), 504), (ModelOutputInvalid("bad"), 502)])
def test_narration_failure_does_not_commit_or_resolve_echo(db, failure, status):
    adapter = Narrator(default=make_accepted(new_echoes=[{"delay": 1, "reason": "旧令后效"}]))
    svc = GameService(db, adapter)
    game = svc.create_game()["game"]
    first = svc.submit_turn(game["id"], "first", 0, "修城西水渠")
    echo = first["result"]["new_echoes"][0]
    adapter.default = make_accepted(echo_effects=[{"echo_id": echo["id"], "people": 2, "treasury": 0, "grain": 0, "explanation": "旧渠灌溉见效"}])
    def broken(*args):
        raise failure
    adapter.narrate = broken
    with pytest.raises(ServiceError) as error:
        svc.submit_turn(game["id"], "failed", 1, "疏浚西郊沟渠")
    assert error.value.status_code == status and error.value.retryable
    assert db.get_game(game["id"])["revision"] == 1
    assert len(db.get_history(game["id"])) == 1
    assert db.get_due_echoes(game["id"], 2)[0]["id"] == echo["id"]
    assert db.find_request_record(game["id"], "failed") is None


def test_narrator_repairs_false_success_and_stays_within_original_budget(monkeypatch):
    adapter = LiveAdapter("https://example.invalid", "unused", "test", 10)
    data = candidate_to_dict(make_accepted())
    facts = {"intent": identify("开仓赈灾"), "blocked": True, "history": [], "constraint_notes": []}
    wrong = {"advisor": "粮已发出，乡人领到赈粮。", "summary": "粮已发。", "policy_analysis": data["policy_analysis"], "reactions": role_texts(), "echo_explanations": {}, "new_echo_reasons": []}
    repaired = {**wrong, "advisor": "陛下，官仓无粮，赈济未能施行。", "summary": "无粮可发，饥情未解。"}
    responses = iter([json.dumps(wrong, ensure_ascii=False), json.dumps(repaired, ensure_ascii=False)])
    budgets = []
    def call(messages, temperature, timeout):
        budgets.append(timeout)
        return next(responses)
    adapter._call = call
    monkeypatch.setattr("app.llm.live.time.monotonic", iter([1.0, 3.0]).__next__)
    context = ModelContext(game={}, turn_no=1, period="承和元年至三年", deadline=9.0)
    result = adapter.narrate(context, data, facts)
    assert narration_errors(result, facts) == []
    assert budgets == [8.0, 6.0]


def test_live_requires_substantive_tradeoffs_and_delayed_risk_echo():
    context = ModelContext(game={}, turn_no=1, period="承和元年至三年")
    payload = candidate_to_dict(make_accepted())
    with pytest.raises(ValueError, match="受益"):
        parse_evaluation(json.dumps(payload), context)
    payload["policy_analysis"] = ANALYSIS
    with pytest.raises(ValueError, match="回声"):
        parse_evaluation(json.dumps(payload), context)
    payload["new_echoes"] = [{"delay": 1, "reason": "释囚安置不足可能再犯"}]
    assert parse_evaluation(json.dumps(payload), context).kind == "accepted"


def test_canned_or_copied_replies_are_rejected():
    data = candidate_to_dict(make_accepted(reactions=role_texts()))
    facts = {"intent": identify("修渠"), "history": [{"reactions": role_texts()}]}
    assert any("照抄" in error for error in narration_errors(data, facts))


def test_withdrawing_criminal_sentences_is_not_revoking_an_old_edict():
    intent = identify("大赦天下，所有在押之人不分罪类一律释放，撤销未执行的刑罚。", {"category": "justice", "action": "enact"})
    assert intent["action"] == "enact"
    assert identify("撤销上一道灾州赈灾令")["action"] == "revoke"


def test_rhetorical_fen_is_not_an_abstract_score():
    data = candidate_to_dict(make_accepted(advisor="臣十分安心，乡里也多了几分生机。"))
    assert prose_is_safe(data, identify("修渠"))
    data["advisor"] = "此诏使民心增加六分。"
    assert not prose_is_safe(data, identify("修渠"))


def test_blocked_policy_cannot_hide_fictional_grain_in_analysis():
    data = candidate_to_dict(make_accepted(advisor="仓中无粮，未能施行。", summary="无粮可发。", reactions=role_texts(), policy_analysis={"benefits": ["赈济尚未实现"], "costs": ["先用仓底余粮酌量散给"], "effect_basis": "粮源不足"}))
    facts = {"intent": identify("开仓赈灾"), "blocked": True, "history": [], "constraint_notes": []}
    assert any("虚构外部仓粮" in error for error in narration_errors(data, facts))
    data["policy_analysis"]["costs"] = ["仓底无粮，未能发放。"]
    assert not narration_errors(data, facts)
