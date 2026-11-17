import json
import pytest

from app.domain.narration import narration_errors, prose_errors
from app.domain.policies import identify, limit_monitoring_echoes
from app.llm.live import LiveAdapter
from app.llm.schema import candidate_to_dict
from app.services.game_service import GameService, ServiceError
from conftest import ScriptedAdapter, make_accepted, set_state
from test_roles_and_tradeoffs import role_texts


def facts():
    return {"intent": identify("整顿吏治"), "blocked": False, "history": [], "constraint_notes": [],
            "before": {"people": 60, "treasury": 50, "grain": 75},
            "after": {"people": 57, "treasury": 48, "grain": 67}}


def prose(text):
    return {**candidate_to_dict(make_accepted()), "summary": text, "reactions": role_texts()}


@pytest.mark.parametrize("text", ["民心略升。", "民心略升，若以后施行得当还有好处。", "民心稍有回升。", "粮储增加。", "国库持平。", "官仓无粮。", "官仓无粮，若另筹粮食便可救急。", "仓中无粮，未能发赈。", "国库减少八万。", "粮储耗去8万。"])
def test_reject_contradictory_narration(text):
    assert narration_errors(prose(text), facts())


@pytest.mark.parametrize("text", ["民心略降，粮储减少。", "粮储不足以覆盖全部需求。", "若来日官仓无粮，须先筹措。", "新政使民心略升，旧患抵消后民心净下降。", "此前官仓无粮，此次补给后尚有留存。"])
def test_preserve_truthful_qualified_prose(text):
    assert not narration_errors(prose(text), facts())


def test_echo_explanation_uses_own_delta_not_total():
    data = prose("民心略降。")
    data["echo_effects"] = [{"echo_id": "old", "explanation": "民心略升。"}]
    f = facts(); f["actual_echo_effects"] = [{"echo_id": "old", "people": 2, "treasury": 0, "grain": 0}]
    assert not narration_errors(data, f)
    f["actual_echo_effects"][0]["people"] = -2
    assert narration_errors(data, f)


@pytest.mark.parametrize("text", ["恢复原税额", "停止减免，恢复原定田赋征收", "按原额征收田税"])
def test_restore_tax_overrides_bad_model_intent(text):
    intent = identify(text, {"category": "tax", "magnitude": "full", "action": "resume", "project": "land_tax"})
    assert intent["magnitude"] == "restore" and intent["action"] == "enact"
    assert prose_errors(prose("本次免除税赋。"), intent)
    assert not prose_errors(prose("取消免税，恢复原额征收。"), intent)


def test_purchase_from_empty_store_is_not_relief_or_repeat(db):
    adapter = ScriptedAdapter(default=make_accepted(policy_effect={"people": 5, "treasury": -4, "grain": -6}))
    svc = GameService(db, adapter); game = svc.create_game()["game"]
    svc.submit_turn(game["id"], "relief", 0, "开仓赈济灾州")
    set_state(db, game["id"], grain=0)
    adapter.default = make_accepted(policy_intent={"category": "relief", "project": "relief"}, policy_effect={"people": 5, "treasury": -4, "grain": 8})
    result = svc.submit_turn(game["id"], "buy", 1, "购粮补仓，粮食入库储备")["result"]
    assert result["policy_intent"]["category"] == "grain_supply"
    assert result["after"]["grain"] == 8 and not result["execution"]["blocked"]
    assert not any("同一政策" in n for n in result["constraint_notes"])


@pytest.mark.parametrize("text", ["停止田赋减免，恢复田赋征收。", "不再享受免税，仍按原税额办理。", "由免税恢复原额征收。"])
def test_cancelling_exemption_is_not_granting_exemption(text):
    assert not prose_errors(prose(text), identify("恢复原税额"))


def test_tax_restore_record_is_not_exemption_or_old_policy_resume(db):
    adapter = ScriptedAdapter(default=make_accepted(policy_intent={"category": "tax", "magnitude": "full"}))
    svc = GameService(db, adapter); game = svc.create_game()["game"]
    svc.submit_turn(game["id"], "waive", 0, "免除田赋")
    result = svc.submit_turn(game["id"], "restore", 1, "恢复原税额")["result"]
    assert "恢复原定税额" in result["normalized_goal"]
    assert result["policy_intent"]["action"] == "enact"
    assert not any("同一政策" in n for n in result["constraint_notes"])


def test_same_monitoring_failure_cannot_spawn_again_but_other_risks_survive(db):
    failure = {"delay": 2, "reason": "赈粮监督流于形式，吏员徇私瞒报"}
    adapter = ScriptedAdapter(default=make_accepted(new_echoes=[failure]))
    svc = GameService(db, adapter); game = svc.create_game()["game"]
    first = svc.submit_turn(game["id"], "audit", 0, "设置赈粮监督，核验领取名册")
    adapter.default = make_accepted(new_echoes=[failure, {"delay": 1, "reason": "定期轮换人员需要交接成本"}])
    second = svc.submit_turn(game["id"], "repair", 1, "更换赈粮监督人员，轮换核验账册")
    assert len(second["result"]["new_echoes"]) == 1
    assert second["result"]["new_echoes"][0]["reason"].find("监督流于形式") == -1
    assert svc.db.get_due_echoes(game["id"], 3)  # Original consequences still exist.
    assert adapter.calls[-1].history[0]["new_echoes"][0]["id"] == first["result"]["new_echoes"][0]["id"]
    _, notes = limit_monitoring_echoes([], identify("监督粮仓"), "监督粮仓", [failure])
    assert not notes


def test_invalid_live_narration_does_not_commit(db):
    class Narrator(ScriptedAdapter):
        def narrate(self, context, data, f):
            return {**data, "summary": "民心略升。", "reactions": role_texts()}
    svc = GameService(db, Narrator(default=make_accepted(policy_effect={"people": -3, "treasury": 0, "grain": 0})))
    game = svc.create_game()["game"]
    with pytest.raises(ServiceError):
        svc.submit_turn(game["id"], "bad", 0, "严整吏治")
    assert svc.get_game_detail(game["id"]) ["history"] == []
    assert svc.db.get_game(game["id"])["revision"] == 0


def test_successful_supervision_is_not_treated_as_breakdown():
    good = {"delay": 1, "reason": "粮仓监督有效防止舞弊，仓粮得以妥善保管"}
    intent = identify("监督粮仓")
    history = [{"raw_text": "监督粮仓", "policy_intent": intent, "new_echoes": [good]}]
    kept, notes = limit_monitoring_echoes(history, intent, "监督粮仓", [good])
    assert kept == [good] and not notes


def test_final_narrator_cannot_reintroduce_removed_monitoring_failure():
    failure = {"delay": 1, "reason": "粮仓监督失灵，吏员瞒报"}
    f = facts(); f["intent"] = identify("监督粮仓"); f["original_goal"] = "轮换粮仓监督人员"
    f["history"] = [{"raw_text": "监督粮仓", "policy_intent": f["intent"], "new_echoes": [failure]}]
    data = prose("据实查核，旧患渐解。"); data["new_echoes"] = [failure]
    assert any("同因" in e for e in narration_errors(data, f))


def test_live_narrator_repairs_direction_once():
    adapter = LiveAdapter("https://example.invalid", "unused", "test", 10)
    data = prose("候选文案")
    response = {"advisor": "陛下，地方负担有所增加，须据实查考。", "summary": "民心略升。", "reactions": role_texts(), "policy_analysis": data["policy_analysis"], "echo_explanations": {}, "new_echo_reasons": []}
    responses = iter([json.dumps(response), json.dumps({**response, "summary": "民心略降，国库与粮储减少。"})])
    calls = []
    def call(messages, temperature, timeout):
        calls.append(timeout); return next(responses)
    adapter._call = call
    from app.llm.base import ModelContext
    result = adapter.narrate(ModelContext(game={}, turn_no=1, period="承和元年至三年"), data, facts())
    assert result["summary"].startswith("民心略降") and len(calls) == 2
    assert calls[1] <= calls[0] <= 10
