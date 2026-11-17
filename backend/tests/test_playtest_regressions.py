"""Regressions from the 2026-11-03 exploratory playtest (no provider calls)."""
import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.domain.policies import identify
from app.domain.narration import prose_is_safe
from app.llm.base import ModelOutputInvalid
from app.llm.live import LiveAdapter
from app.llm.base import ModelContext
from app.llm.schema import candidate_to_dict
from app.services.game_service import GameService, ServiceError
from app.storage.sqlite import Database, SCHEMA
from conftest import ScriptedAdapter, make_accepted, set_state


def test_22_no_grain_success_in_any_prose_or_future_echo(db):
    candidate = make_accepted(
        policy_effect={"people": 8, "treasury": -10, "grain": -20},
        advisor="邻州常平余仓已调粮，每户足额领粮。",
        reactions=[{"speaker": "tian_bo", "text": "又领到了粮，可以熬过冬春。"}, {"speaker": "gu_tingzhang", "text": "已全额办成。"}],
        new_echoes=[{"delay": 1, "reason": "赈粮足额发放后民心增长"}],
    )
    svc = GameService(db, ScriptedAdapter(default=candidate))
    game = svc.create_game()["game"]
    set_state(db, game["id"], grain=0)
    result = svc.submit_turn(game["id"], "empty", 0, "继续开仓，每户再领一百石粮，不准借粮买粮，也不得征粮")["result"]
    assert result["execution"]["blocked"]
    assert result["applied_effects"] == {"people": 0, "treasury": 0, "grain": 0}
    assert result["new_echoes"] == []
    prose = result["advisor"] + result["summary"] + "".join(r["text"] for r in result["reactions"])
    assert "未发出赈粮" in prose
    assert not any(word in prose for word in ("邻州", "又领到了", "足额", "熬过冬春"))
    assert svc.get_game_detail(game["id"])["history"][0]["summary"] == result["summary"]


@pytest.mark.parametrize("kind,people", [("execution", 0), ("consequence", 2)])
def test_24_27_revocation_blocks_execution_but_preserves_existing_consequences(db, kind, people):
    def later(context):
        return make_accepted(policy_effect={"people": 4, "treasury": -5, "grain": -10},
            advisor="免灾州一年田赋并将封存粮重新拨去赈济。",
            echo_effects=[{"echo_id": e["id"], "people": 2, "treasury": -2, "grain": -8, "explanation": "继续发粮成功"} for e in context.due_echoes])
    svc = GameService(db, ScriptedAdapter(responses=[
        make_accepted(policy_effect={"people": 5, "treasury": -4, "grain": -14}, new_echoes=[{"delay": 2, "reason": "灾州赈济后效", "effect_kind": kind}]),
        make_accepted(policy_effect={"people": -2, "treasury": 0, "grain": 5}), later,
    ]))
    game = svc.create_game()["game"]
    first = svc.submit_turn(game["id"], "relief", 0, "开仓赈济灾州")
    second = svc.submit_turn(game["id"], "stop", 1, "撤销上一道灾州赈灾令，封存余粮，不得继续赈济")
    assert second["game"]["grain"] == first["game"]["grain"]
    third = svc.submit_turn(game["id"], "tax", 2, "灾州少收点田税，别折腾他们")
    assert third["game"]["grain"] == first["game"]["grain"]
    assert third["result"]["echo_effects"][0]["people"] == people
    assert third["result"]["echo_effects"][0]["grain"] == 0
    assert "重新拨去" not in third["result"]["advisor"]
    history = svc.get_game_detail(game["id"])["history"]
    assert history[0]["policy_status"] == "revoked"
    assert history[2]["policy_intent"]["magnitude"] == "moderate"


def test_44_46_synonym_repeat_same_canal_and_region(db):
    svc = GameService(db, ScriptedAdapter(responses=[make_accepted(normalized_goal=f"不同措辞{i}", policy_effect={"people": 6, "treasury": -8, "grain": 0}) for i in range(3)]))
    game = svc.create_game()["game"]
    texts = ["雇工修城西水渠", "疏浚西郊灌溉沟渠，让水流回田里", "不新增工程，只把同一段城西水渠再疏浚一遍"]
    gains = [svc.submit_turn(game["id"], f"canal{i}", i, text)["result"]["applied_effects"]["people"] for i, text in enumerate(texts)]
    assert gains == [6, 3, 2]


def test_different_regions_and_tax_objects_are_not_repeats(db):
    svc = GameService(db, ScriptedAdapter(default=make_accepted(normalized_goal="修渠", policy_effect={"people": 6, "treasury": -8, "grain": 0})))
    game = svc.create_game()["game"]
    svc.submit_turn(game["id"], "west", 0, "修城西水渠")
    # Same generic generated goal must not override distinct structured scope.
    other = svc.submit_turn(game["id"], "east", 1, "修城东水渠")
    assert other["result"]["applied_effects"]["people"] == 6
    assert identify("减田赋")["project"] != identify("减商税")["project"]
    assert identify("整顿京畿治安，不增税赋", {"category": "justice"})["category"] == "justice"
    assert identify("只减田税，不得恢复赈济", {"action": "enact"})["action"] != "resume"


@pytest.mark.parametrize("text,magnitude", [("少收一点田税", "moderate"), ("Reduce land taxes for one year", "moderate"), ("田赋减半", "half"), ("全免田赋", "full"), ("不再减田赋", "unchanged"), ("降低田赋，不得全免", "moderate")])
def test_tax_magnitude_pairs(text, magnitude):
    assert identify(text)["magnitude"] == magnitude


@pytest.mark.parametrize("text", ["去岁修渠，来年见效。", "拨钱十二万贯，发粮六万石。", "民心可增六分。"])
def test_reject_false_time_and_units(text):
    data = candidate_to_dict(make_accepted(advisor=text))
    assert not prose_is_safe(data, identify("修渠"))


def test_narration_observes_settlement_and_cannot_change_numbers(db):
    class Narrator(ScriptedAdapter):
        def narrate(self, context, data, facts):
            assert facts["after"] == {"people": 53, "treasury": 54, "grain": 60}
            return {**data, "advisor": "陛下，官道已按核定范围修整。", "summary": "官道修整，通行渐便。", "reactions": [*data["reactions"], {"speaker": "song_zhiyuan", "text": "官道平了，货车少误行期。"}]}
    svc = GameService(db, Narrator(default=make_accepted(policy_effect={"people": 3, "treasury": -6, "grain": 0})))
    game = svc.create_game()["game"]
    result = svc.submit_turn(game["id"], "narration", 0, "整修官道")["result"]
    assert "核定范围" in result["advisor"]
    assert result["after"]["people"] == 53


def test_narration_failure_preserves_turn_instead_of_canned_roles(db):
    class BrokenNarrator(ScriptedAdapter):
        def narrate(self, *args):
            raise ModelOutputInvalid("bad narrative")
    svc = GameService(db, BrokenNarrator(default=make_accepted(policy_effect={"people": 3, "treasury": -6, "grain": 0})))
    game = svc.create_game()["game"]
    with pytest.raises(ServiceError) as error:
        svc.submit_turn(game["id"], "narration", 0, "整修官道")
    assert error.value.code == "MODEL_OUTPUT_INVALID" and error.value.retryable
    assert db.get_game(game["id"])["revision"] == 0
    assert db.get_history(game["id"]) == []


def test_policy_ledger_survives_reopen_and_old_schema_migration(tmp_path):
    path = tmp_path / "legacy.db"
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    conn.close()
    db = Database(str(path))
    svc = GameService(db, ScriptedAdapter(default=make_accepted()))
    game = svc.create_game()["game"]
    svc.submit_turn(game["id"], "one", 0, "赈济灾州")
    svc.submit_turn(game["id"], "two", 1, "撤销灾州赈灾令")
    db.close()
    reopened = Database(str(path))
    assert reopened.get_history(game["id"])[0]["policy_status"] == "revoked"
    reopened.close()


def test_text_only_narration_rejects_effect_injection():
    adapter = LiveAdapter("https://example.invalid", "unused", "test")
    context = ModelContext(game={}, turn_no=1, period="承和元年至三年")
    data = candidate_to_dict(make_accepted())
    narrative = {"advisor": "陛下，已按核定范围办理。", "summary": "照章办理。", "policy_analysis": data["policy_analysis"], "reactions": [*data["reactions"], {"speaker": "song_zhiyuan", "text": "货路尚安。"}], "echo_explanations": {}, "new_echo_reasons": []}
    adapter._call = lambda *args, **kwargs: json.dumps(narrative, ensure_ascii=False)
    facts = {"intent": identify("修渠"), "blocked": False, "history": [], "constraint_notes": []}
    output = adapter.narrate(context, data, facts)
    assert output["policy_effect"] == data["policy_effect"]
    narrative["policy_effect"] = {"people": 100}
    with pytest.raises(ModelOutputInvalid):
        adapter.narrate(context, data, facts)


def test_concurrent_identical_request_replays_one_commit(db):
    barrier = threading.Barrier(2)
    class ConcurrentAdapter(ScriptedAdapter):
        def evaluate(self, context):
            barrier.wait(timeout=5)
            return make_accepted(policy_effect={"people": 2, "treasury": -1, "grain": 0})
    svc = GameService(db, ConcurrentAdapter())
    game = svc.create_game()["game"]
    def submit():
        return svc.submit_turn(game["id"], "same-request", 0, "整顿京畿治安")
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: submit(), range(2)))
    assert results[0] == results[1]
    assert len(db.get_history(game["id"])) == 1
    assert db.get_game(game["id"])["revision"] == 1


def test_all_resources_request_reports_actual_cap_and_remainder(db):
    svc = GameService(db, ScriptedAdapter(default=make_accepted(
        policy_effect={"people": -4, "treasury": -20, "grain": -20}, advisor="钱粮尽数解赴军前。")))
    game = svc.create_game()["game"]
    result = svc.submit_turn(game["id"], "all", 0, "将剩余钱粮全部作军需")["result"]
    assert result["after"]["treasury"] == 40 and result["after"]["grain"] == 40
    assert any("留存钱粮未解付" in note for note in result["constraint_notes"])
    assert "尽数解赴" not in result["advisor"]
