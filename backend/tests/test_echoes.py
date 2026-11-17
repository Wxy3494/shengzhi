"""M4 跨回合政策回声测试:E01-E08。"""

import pytest

from app.services.game_service import GameService, ServiceError

from conftest import ScriptedAdapter, insert_echo, make_accepted, set_state

RELIEF_TEXT = "今夏旱情频仍,着户部拨银赈济灾民,开仓放粮。"
WATER_TEXT = "着工部征调民夫,兴修水利,加固河堤。"


def _submit(service, game_id, revision, request_id, text):
    return service.submit_turn(game_id, request_id, revision, text)


# ---------- E01 第一回合 delay=1 回声 → 第二回合到期,引用正确 policy_id ----------


def test_e01_echo_due_next_turn_with_policy_link(service, db):
    game = service.create_game()["game"]
    first = _submit(service, game["id"], 0, "e01-1", RELIEF_TEXT)
    assert first["kind"] == "accepted"
    policy_id = first["result"]["policy_id"]

    detail = service.get_game_detail(game["id"])
    pending = [e for e in detail["echoes"] if e["status"] == "pending"]
    assert len(pending) == 1
    echo = pending[0]
    assert echo["source_policy_id"] == policy_id
    assert echo["created_turn"] == 1
    assert echo["due_turn"] == 2

    second = _submit(service, game["id"], 1, "e01-2", WATER_TEXT)
    assert second["kind"] == "accepted"
    assert len(second["result"]["echo_effects"]) == 1
    effect = second["result"]["echo_effects"][0]
    assert effect["echo_id"] == echo["id"]
    assert effect["source_policy_id"] == policy_id
    assert effect["created_turn"] == 1
    assert effect["reason"] == echo["reason"]

    detail = service.get_game_detail(game["id"])
    resolved = [e for e in detail["echoes"] if e["status"] == "resolved"]
    assert len(resolved) == 1
    assert resolved[0]["resolved_turn"] == 2


# ---------- E02 已结算回声第三回合再次返回 → 拒绝,不二次扣分 ----------


def test_e02_resolved_echo_rejected(service, db):
    game = service.create_game()["game"]
    _submit(service, game["id"], 0, "e02-1", RELIEF_TEXT)
    second = _submit(service, game["id"], 1, "e02-2", WATER_TEXT)
    resolved_echo_id = second["result"]["echo_effects"][0]["echo_id"]

    svc = GameService(
        db,
        ScriptedAdapter(
            default=make_accepted(
                echo_effects=[
                    {
                        "echo_id": resolved_echo_id,
                        "people": 2,
                        "treasury": 0,
                        "grain": 0,
                        "explanation": "重复结算",
                    }
                ]
            )
        ),
    )
    with pytest.raises(ServiceError) as exc:
        svc.submit_turn(game["id"], "e02-3", 2, RELIEF_TEXT)
    assert exc.value.code == "MODEL_OUTPUT_INVALID"
    assert exc.value.status_code == 502
    after = db.get_game(game["id"])
    assert after["revision"] == 2
    assert after["people"] == second["game"]["people"]


# ---------- E03 第七回合返回 delay=2 → 拒绝 ----------


def test_e03_turn7_delay2_rejected(service, db):
    game = service.create_game()["game"]
    set_state(db, game["id"], accepted_turns=6, revision=6)
    bad = make_accepted(new_echoes=[{"delay": 2, "reason": "两回合后才能验证"}])
    svc = GameService(db, ScriptedAdapter(default=bad))
    with pytest.raises(ServiceError) as exc:
        svc.submit_turn(game["id"], "e03-1", 6, RELIEF_TEXT)
    assert exc.value.code == "MODEL_OUTPUT_INVALID"
    assert exc.value.status_code == 502
    assert db.get_game(game["id"])["revision"] == 6


def test_e03_turn7_delay1_accepted(service, db):
    game = service.create_game()["game"]
    set_state(db, game["id"], accepted_turns=6, revision=6)
    ok = make_accepted(new_echoes=[{"delay": 1, "reason": "第八回合核验"}])
    svc = GameService(db, ScriptedAdapter(default=ok))
    resp = svc.submit_turn(game["id"], "e03-2", 6, RELIEF_TEXT)
    assert resp["kind"] == "accepted"
    assert resp["result"]["new_echoes"][0]["due_turn"] == 8


# ---------- E04 第八回合新建回声 → 拒绝 ----------


def test_e04_turn8_new_echo_rejected(service, db):
    game = service.create_game()["game"]
    set_state(db, game["id"], accepted_turns=7, revision=7)
    bad = make_accepted(new_echoes=[{"delay": 1, "reason": "机械回声"}])
    svc = GameService(db, ScriptedAdapter(default=bad))
    with pytest.raises(ServiceError) as exc:
        svc.submit_turn(game["id"], "e04-1", 7, RELIEF_TEXT)
    assert exc.value.code == "MODEL_OUTPUT_INVALID"
    assert exc.value.status_code == 502
    assert db.get_game(game["id"])["revision"] == 7


def test_e04_fixture_turn8_returns_empty_echoes(service, db):
    game = service.create_game()["game"]
    set_state(db, game["id"], accepted_turns=7, revision=7, people=50)
    resp = _submit(service, game["id"], 7, "e04-2", RELIEF_TEXT)
    assert resp["kind"] == "accepted"
    assert resp["result"]["new_echoes"] == []


# ---------- E05 返回其他游戏或未知 echo_id → 拒绝,状态不变 ----------


@pytest.mark.parametrize("echo_id", ["other-game-echo", "future-echo-999"])
def test_e05_unknown_echo_id_rejected(service, db, echo_id):
    game = service.create_game()["game"]
    bad = make_accepted(
        echo_effects=[
            {"echo_id": echo_id, "people": 1, "treasury": 0, "grain": 0, "explanation": "凭空回声"}
        ]
    )
    svc = GameService(db, ScriptedAdapter(default=bad))
    with pytest.raises(ServiceError) as exc:
        svc.submit_turn(game["id"], "e05-1", 0, RELIEF_TEXT)
    assert exc.value.code == "MODEL_OUTPUT_INVALID"
    assert exc.value.status_code == 502
    after = db.get_game(game["id"])
    assert after["revision"] == 0
    assert after["people"] == 50


# ---------- E06 到期回声漏项、重复项或未知项 → 拒绝 ----------


def _game_with_due_echo(db, service):
    game = service.create_game()["game"]
    insert_echo(db, game["id"], "due-1", "policy-0", 0, 1, "回声一")
    insert_echo(db, game["id"], "due-2", "policy-0", 0, 1, "回声二")
    return game


def test_e06_missing_echo_rejected(service, db):
    game = _game_with_due_echo(db, service)
    bad = make_accepted(
        echo_effects=[
            {"echo_id": "due-1", "people": 1, "treasury": 0, "grain": 0, "explanation": "只覆盖一条"}
        ]
    )
    svc = GameService(db, ScriptedAdapter(default=bad))
    with pytest.raises(ServiceError) as exc:
        svc.submit_turn(game["id"], "e06-1", 0, RELIEF_TEXT)
    assert exc.value.code == "MODEL_OUTPUT_INVALID"
    assert db.get_game(game["id"])["revision"] == 0


def test_e06_duplicate_echo_rejected(service, db):
    game = _game_with_due_echo(db, service)
    bad = make_accepted(
        echo_effects=[
            {"echo_id": "due-1", "people": 1, "treasury": 0, "grain": 0, "explanation": "一次"},
            {"echo_id": "due-1", "people": 1, "treasury": 0, "grain": 0, "explanation": "又一次"},
        ]
    )
    svc = GameService(db, ScriptedAdapter(default=bad))
    with pytest.raises(ServiceError) as exc:
        svc.submit_turn(game["id"], "e06-2", 0, RELIEF_TEXT)
    assert exc.value.code == "MODEL_OUTPUT_INVALID"


def test_e06_unknown_extra_echo_rejected(service, db):
    game = _game_with_due_echo(db, service)
    bad = make_accepted(
        echo_effects=[
            {"echo_id": "due-1", "people": 1, "treasury": 0, "grain": 0, "explanation": "到期"},
            {"echo_id": "due-2", "people": 1, "treasury": 0, "grain": 0, "explanation": "到期"},
            {"echo_id": "due-3", "people": 1, "treasury": 0, "grain": 0, "explanation": "多余"},
        ]
    )
    svc = GameService(db, ScriptedAdapter(default=bad))
    with pytest.raises(ServiceError) as exc:
        svc.submit_turn(game["id"], "e06-3", 0, RELIEF_TEXT)
    assert exc.value.code == "MODEL_OUTPUT_INVALID"


# ---------- E07 policy +8、两项 echo 各 +4 → 合并封顶 +8,存档与响应一致 ----------


def test_e07_total_cap_storage_consistency(service, db):
    game = _game_with_due_echo(db, service)
    set_state(db, game["id"], people=70)
    candidate = make_accepted(
        policy_effect={"people": 8, "treasury": 0, "grain": 0},
        echo_effects=[
            {"echo_id": "due-1", "people": 4, "treasury": 0, "grain": 0, "explanation": "回声一影响"},
            {"echo_id": "due-2", "people": 4, "treasury": 0, "grain": 0, "explanation": "回声二影响"},
        ],
    )
    svc = GameService(db, ScriptedAdapter(default=candidate))
    resp = svc.submit_turn(game["id"], "e07-1", 0, RELIEF_TEXT)
    assert resp["result"]["applied_effects"]["people"] == 8
    assert resp["game"]["people"] == 78

    detail = service.get_game_detail(game["id"])
    stored = detail["history"][0]
    assert stored["applied_effects"]["people"] == resp["result"]["applied_effects"]["people"]
    assert stored["after"]["people"] == resp["result"]["after"]["people"]
    per_echo = {e["echo_id"]: e["people"] for e in stored["echo_effects"]}
    # The display now stores actually credited components after the total cap.
    assert per_echo == {"due-1": 0, "due-2": 0}
    assert stored["execution"]["actual_policy_effect"]["people"] + sum(per_echo.values()) == 8


# ---------- E08 三条新回声或 delay=0 → 拒绝 ----------


def test_e08_three_new_echoes_rejected(service, db):
    # 三条新回声在 schema 层即被拒绝(live 模式:解析失败 → 一次修复 → 仍错 → 502)
    import json

    from app.llm.schema import parse_candidate

    payload = {
        "kind": "accepted",
        "normalized_goal": "测试",
        "tags": [],
        "policy_effect": {"people": 0, "treasury": 0, "grain": 0},
        "echo_effects": [],
        "advisor": "可行。",
        "reactions": [
            {"speaker": "tian_bo", "text": "一。"},
            {"speaker": "gu_tingzhang", "text": "二。"},
        ],
        "summary": "小结。",
        "new_echoes": [
            {"delay": 1, "reason": "一"},
            {"delay": 1, "reason": "二"},
            {"delay": 2, "reason": "三"},
        ],
    }
    with pytest.raises(ValueError):
        parse_candidate(json.dumps(payload, ensure_ascii=False))


def test_e08_delay_zero_rejected(service, db):
    game = service.create_game()["game"]
    bad = make_accepted(new_echoes=[{"delay": 0, "reason": "立即"}])
    svc = GameService(db, ScriptedAdapter(default=bad))
    with pytest.raises(ServiceError) as exc:
        svc.submit_turn(game["id"], "e08-2", 0, RELIEF_TEXT)
    assert exc.value.code == "MODEL_OUTPUT_INVALID"
    assert db.get_game(game["id"])["revision"] == 0


def test_fixture_echo_effects_are_deterministic_across_games(service):
    effects = []
    for run in range(2):
        game = service.create_game()["game"]
        _submit(service, game["id"], 0, f"deterministic-{run}-1", RELIEF_TEXT)
        second = _submit(service, game["id"], 1, f"deterministic-{run}-2", WATER_TEXT)
        effect = second["result"]["echo_effects"][0]
        effects.append({key: effect[key] for key in ("people", "treasury", "grain", "explanation")})
    assert effects[0] == effects[1]
