import json
import pytest

from app.domain.crises import initial_realm, advance_realm
from app.domain.models import GameState
from app.llm.base import ModelOutputInvalid
from app.services.game_service import GameService, ServiceError
from app.storage.sqlite import Database
from conftest import ScriptedAdapter, make_accepted


def advance(realm=None, people=50, treasury=60, grain=60, text="治理民生", intent=None, turn=1, base="playing", blocked=False, notes=None):
    return advance_realm(realm or initial_realm(), GameState(people=people, treasury=treasury, grain=grain),
        intent or {"category": "other", "action": "enact"}, text, blocked, notes or [], turn, base)


@pytest.mark.parametrize("key,kwargs", [
    ("civil", {"people": 10}),
    ("bankruptcy", {"treasury": 0}),
    ("army", {"treasury": 5, "grain": 5, "intent": {"category": "military", "action": "enact"}, "text": "整编禁军"}),
    ("border", {"treasury": 15, "grain": 15, "intent": {"category": "military", "action": "enact"}, "text": "加强边疆驻防"}),
])
def test_all_four_crises_need_accumulation_then_end(key, kwargs):
    r = initial_realm()
    for turn in range(1, 4):
        r = advance(r, turn=turn, **kwargs)
        if turn == 1:
            assert r["ending"] is None
    assert r["ending"]["kind"] == key
    assert r["ending"]["status"] == "lost" and r["ending"]["source_turns"] == [1, 2, 3]


def test_zero_resource_once_is_not_a_defeat():
    r = advance(treasury=0, grain=0)
    assert r["ending"] is None
    assert r["pressures"]["bankruptcy"] == 35


def test_recovery_reduces_pressures_and_clears_sources_at_zero():
    r = advance(treasury=0, people=10)
    old = json.loads(json.dumps(r))
    fixed = advance(r, turn=2)
    assert r == old  # Computing a candidate transition cannot mutate committed state.
    assert fixed["pressures"]["civil"] < old["pressures"]["civil"]
    assert fixed["pressures"]["bankruptcy"] == 10
    fixed = advance(fixed, turn=3)
    assert fixed["pressures"]["bankruptcy"] == 0 and fixed["sources"]["bankruptcy"] == []


def test_warning_thresholds_and_independent_sources():
    r = advance(treasury=0)
    r = advance(r, treasury=0, turn=2)
    assert r["pressures"]["bankruptcy"] == 70 and not r["warnings"]
    r = advance(r, treasury=0, turn=3)
    assert [w["threshold"] for w in r["warnings"]] == [75, 90]
    assert all(w["id"] == "bankruptcy" for w in r["warnings"])


def test_alerts_fire_once_across_recovery_and_rebound():
    r = initial_realm(); r["pressures"]["bankruptcy"] = 55
    r = advance(r, treasury=5)
    assert [w["threshold"] for w in r["warnings"]] == [75]
    r = advance(r, treasury=60, turn=2)
    assert not r["warnings"]
    r = advance(r, treasury=5, turn=3)
    assert not r["warnings"]
    r = advance(r, treasury=5, turn=4)
    assert [w["threshold"] for w in r["warnings"]] == [90]
    r = advance(r, treasury=60, turn=5)
    r = advance(r, treasury=5, turn=6)
    assert not r["warnings"] and r["notified"]["bankruptcy"] == [75, 90]


def test_old_realm_without_notice_flags_can_alert():
    r = initial_realm(); del r["notified"]; r["version"] = 1
    r["pressures"]["bankruptcy"] = 55
    assert advance(r, treasury=5)["warnings"][0]["threshold"] == 75


def test_military_must_be_implemented_and_border_requires_relevant_commitment():
    i = {"category": "military", "action": "enact"}
    blocked = advance(intent=i, text="远征边疆", blocked=True, treasury=0, grain=0)
    assert not blocked["military_engaged"] and not blocked["border_engaged"]
    domestic = advance(intent=i, text="整编禁军", treasury=15, grain=15)
    assert domestic["military_engaged"] and not domestic["border_engaged"]
    stopped = advance(domestic, intent={**i, "action": "revoke"}, text="撤销禁军动员令", treasury=0)
    assert not stopped["military_engaged"] and stopped["pressures"]["army"] == 0


@pytest.mark.parametrize("blocked,notes,steps", [(False, [], 1), (True, [], 0), (False, ["与第1回合属于同一政策"], 0)])
def test_reform_steps_only_count_nonrepeat_implementation(blocked, notes, steps):
    r = advance(intent={"category": "reform", "action": "enact"}, text="改革考课", blocked=blocked, notes=notes)
    assert r["reform_steps"] == steps
    assert r["ending"] is None


def test_reform_endings_and_default_outcomes():
    r = advance(intent={"category": "reform", "action": "enact"}, text="改革考课", turn=8, base="lost")
    assert r["ending"]["kind"] == "unfinished_reform"
    r = initial_realm(); r["reform_steps"] = 3; r["reform_started"] = True
    assert advance(r, people=80, base="won")["ending"]["kind"] == "reform_success"
    assert advance(people=80, base="won")["ending"]["kind"] == "peace"
    assert advance(turn=8, base="lost")["ending"]["kind"] == "mandate_lost"


def test_disaster_precedes_victory_and_tie_order_is_fixed():
    r = initial_realm(); r["pressures"]["bankruptcy"] = 90
    assert advance(r, people=80, treasury=0, base="won")["ending"]["kind"] == "bankruptcy"
    r = initial_realm(); r["pressures"].update(civil=95, army=95); r["military_engaged"] = True
    assert advance(r, people=10, treasury=5, grain=5)["ending"]["kind"] == "civil"


def test_three_turn_bankruptcy_persists_and_replays_without_advancing(db):
    svc = GameService(db, ScriptedAdapter(default=make_accepted()))
    game = svc.create_game()["game"]
    assert game["schema_version"] == 2 and game["realm"]["pressures"]["civil"] == 0
    db._conn.execute("UPDATE games SET treasury=0 WHERE id=?", (game["id"],))
    for turn in range(3):
        response = svc.submit_turn(game["id"], f"turn-{turn}", turn, "整理吏治")
    assert response["game"]["status"] == "lost" and response["game"]["ending"]["kind"] == "bankruptcy"
    assert response["game"]["accepted_turns"] == 3
    assert svc.submit_turn(game["id"], "turn-2", 2, "整理吏治") == response
    with pytest.raises(ServiceError) as exc:
        svc.submit_turn(game["id"], "another", 3, "再整吏治")
    assert exc.value.code == "GAME_FINISHED"
    path = db._conn.execute("PRAGMA database_list").fetchone()[2]
    reopened = Database(path)
    try:
        assert GameService(reopened, ScriptedAdapter()).get_game_detail(game["id"])["game"] == response["game"]
    finally:
        reopened.close()


def test_narration_failure_rolls_back_pressure_and_turn(db):
    class Bad(ScriptedAdapter):
        def narrate(self, *args):
            raise ModelOutputInvalid("failed")
    svc = GameService(db, Bad(default=make_accepted()))
    game = svc.create_game()["game"]
    db._conn.execute("UPDATE games SET treasury=0 WHERE id=?", (game["id"],))
    with pytest.raises(ServiceError):
        svc.submit_turn(game["id"], "bad", 0, "整理吏治")
    restored = svc.get_game_detail(game["id"])
    assert restored["game"]["realm"]["pressures"]["bankruptcy"] == 0
    assert restored["game"]["revision"] == 0 and not restored["history"]


def test_legacy_save_keeps_legacy_resource_rules(db):
    svc = GameService(db, ScriptedAdapter(default=make_accepted()))
    game = svc.create_game()["game"]
    db._conn.execute("UPDATE games SET schema_version=1,treasury=0 WHERE id=?", (game["id"],))
    for turn in range(4):
        response = svc.submit_turn(game["id"], f"old-{turn}", turn, "整理吏治")
    assert response["game"]["status"] == "playing" and response["game"]["realm"] is None


def test_model_cannot_declare_unconfirmed_disaster():
    from app.domain.narration import narration_errors
    from app.llm.schema import candidate_to_dict
    from test_roles_and_tradeoffs import role_texts
    data = candidate_to_dict(make_accepted(summary="民变已起，本朝倾覆。", reactions=role_texts()))
    facts = {"intent": {"category": "other"}, "realm": initial_realm(), "ending": None}
    assert any("灾变" in e for e in narration_errors(data, facts))
    facts["ending"] = {"kind": "civil"}
    assert not narration_errors(data, facts)


@pytest.mark.parametrize("kind,setup,intent,text,turns", [
    ("civil", {}, {"category": "other"}, "继续重役", 5),
    ("army", {"treasury": 5, "grain": 5}, {"category": "military"}, "整编禁军", 3),
    ("border", {"treasury": 15, "grain": 15}, {"category": "military"}, "加强边疆驻防", 3),
])
def test_service_crisis_paths_have_correct_persisted_endings(db, kind, setup, intent, text, turns):
    effect = {"people": -12 if kind == "civil" else 0, "treasury": 0, "grain": 0}
    svc = GameService(db, ScriptedAdapter(default=make_accepted(policy_intent=intent, policy_effect=effect)))
    game = svc.create_game()["game"]
    for key, value in setup.items():
        db._conn.execute(f"UPDATE games SET {key}=? WHERE id=?", (value, game["id"]))
    for t in range(turns):
        result = svc.submit_turn(game["id"], f"case-{t}", t, text)
    assert result["game"]["ending"]["kind"] == kind and result["game"]["accepted_turns"] == turns
    assert svc.get_game_detail(game["id"])["game"] == result["game"]
    assert svc.get_game_detail(game["id"])["history"][-1]["realm"]["ending"]["kind"] == kind


def test_service_unfinished_reform_at_eighth_turn(db):
    adapter = ScriptedAdapter(default=make_accepted())
    svc = GameService(db, adapter); game = svc.create_game()["game"]
    for t in range(8):
        text = "改革考课" if t == 0 else "整理旧政文书"
        r = svc.submit_turn(game["id"], str(t), t, text)
    assert r["game"]["ending"]["kind"] == "unfinished_reform"
    assert r["game"]["ending"]["source_turns"] == [1]
