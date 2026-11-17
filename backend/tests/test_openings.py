import copy
import json
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.games import router
from app.domain.openings import SCENARIOS, choose_opening, opening_effect, initial_conditions, advance_conditions, relevant
from app.domain.models import GameState
from app.llm.base import ModelOutputInvalid
from app.llm.emperor_review import EmperorReview, validate_review
from app.llm.opening_briefing import generate_briefing
from app.services.game_service import GameService, ServiceError
from conftest import ScriptedAdapter, make_accepted, set_state
from test_emperor import valid_review


def fixed(monkeypatch, profile):
    monkeypatch.setattr("app.services.game_service.choose_opening", lambda: copy.deepcopy(profile))


@pytest.mark.parametrize("profile", SCENARIOS, ids=lambda p: p["id"])
def test_six_budget_equal_openings_can_win_same_reference_route(db, monkeypatch, profile):
    fixed(monkeypatch, profile)
    adapter = ScriptedAdapter(default=make_accepted())
    svc = GameService(db, adapter); game = svc.create_game()["game"]
    assert game["schema_version"] == 3 and game["opening"]["id"] == profile["id"]
    assert game["people"] == 50 and game["treasury"] + game["grain"] == 120
    assert min(game["treasury"], game["grain"]) >= 50
    for t in range(4):
        adapter.default = make_accepted(normalized_goal=f"不同目标{t}", policy_effect={"people":8,"treasury":-5,"grain":-5})
        result = svc.submit_turn(game["id"], str(t), t, f"办理不同民生事项{t}")
    assert result["game"]["status"] == "won" and result["game"]["people"] == 82
    assert result["game"]["opening"] == game["opening"]


def test_random_selection_is_copied_and_saved_not_rerolled(db, monkeypatch):
    monkeypatch.setattr("app.domain.openings.secrets.choice", lambda options: options[1])
    picked = choose_opening(); picked["initial"]["grain"] = 0
    assert SCENARIOS[1]["initial"]["grain"] == 50
    fixed(monkeypatch, SCENARIOS[1]); svc = GameService(db, ScriptedAdapter())
    game = svc.create_game()["game"]
    fixed(monkeypatch, SCENARIOS[0])
    assert svc.get_game_detail(game["id"])["game"]["opening"] == game["opening"]


@pytest.mark.parametrize("profile", SCENARIOS, ids=lambda p: p["id"])
def test_early_effect_is_bounded_one_use_and_expires(profile):
    c = initial_conditions(profile); effect = {"people":3,"treasury":-4,"grain":0}
    state = GameState(**profile["initial"]); intent = {"category":profile["categories"][0],"action":"enact"}
    adjusted, notes = opening_effect(profile,c,intent,profile["words"][0],1,state,effect)
    assert adjusted["people"] == 4 and adjusted[profile["cost_resource"]] == effect[profile["cost_resource"]] - 1
    assert notes and c == initial_conditions(profile)
    c["bonus_used"] = True
    assert opening_effect(profile,c,intent,"",2,state,effect) == (effect,[])
    assert opening_effect(profile,initial_conditions(profile),intent,"",3,state,effect) == (effect,[])


def test_issue_can_be_resolved_late_without_expired_penalty(db, monkeypatch):
    fixed(monkeypatch, SCENARIOS[0]); a = ScriptedAdapter(default=make_accepted())
    svc = GameService(db,a); g = svc.create_game()["game"]
    for t in range(2): svc.submit_turn(g["id"],str(t),t,"整理文书")
    a.default = make_accepted(policy_effect={"people":3,"treasury":-4,"grain":0})
    result = svc.submit_turn(g["id"],"fix",2,"雇工修城西水渠")
    assert result["game"]["conditions"]["resolved"]
    assert result["game"]["conditions"]["resolved_turn"] == 3
    assert result["result"]["applied_effects"]["people"] == 3
    assert result["result"]["applied_effects"]["treasury"] == -4
    assert result["game"] == svc.get_game_detail(g["id"])["game"]
    assert a.calls[-1].game["opening"] == g["opening"]


def test_blocked_or_harmful_action_does_not_resolve_old_issue():
    p = SCENARIOS[0]; i = {"category":"water","action":"enact"}; c = initial_conditions(p)
    assert not advance_conditions(p,c,i,"修水渠",{"people":3,"treasury":0,"grain":0},True,1,False)["resolved"]
    assert not advance_conditions(p,c,i,"焚毁水渠",{"people":-3,"treasury":0,"grain":0},False,1,False)["resolved"]
    fiscal = SCENARIOS[3]
    assert not advance_conditions(fiscal,initial_conditions(fiscal),{"category":"tax"},"免去田赋",{"people":4,"treasury":-5,"grain":0},False,1,False)["resolved"]
    assert not relevant(p, i, "不许再修渠")
    assert relevant(SCENARIOS[4], {"category":"justice","action":"enact"}, "禁止官吏贪墨")


def test_failed_narration_does_not_consume_opportunity(db, monkeypatch):
    fixed(monkeypatch,SCENARIOS[0])
    class Broken(ScriptedAdapter):
        def narrate(self,*args): raise ModelOutputInvalid("bad")
    svc=GameService(db,Broken(default=make_accepted(policy_effect={"people":3,"treasury":-4,"grain":0})))
    g=svc.create_game()["game"]
    with pytest.raises(ServiceError): svc.submit_turn(g["id"],"bad",0,"修城西水渠")
    assert svc.get_game_detail(g["id"])["game"] == g


def test_briefing_is_cached_and_never_changes_game_or_draw(db, monkeypatch):
    fixed(monkeypatch,SCENARIOS[0])
    class Speaker(ScriptedAdapter):
        brief_calls = 0
        def brief_opening(self, opening):
            self.brief_calls += 1; return "陛下，臣谨奏旱后国情。" * 10
    a=Speaker();svc=GameService(db,a);g=svc.create_game()["game"]
    first=svc.generate_opening_briefing(g["id"])
    assert svc.generate_opening_briefing(g["id"]) == first and a.brief_calls == 1
    assert svc.get_game_detail(g["id"])["game"] == g
    app=FastAPI(); app.include_router(router);app.state.game_service=svc
    with TestClient(app) as client:
        assert client.post(f"/api/games/{g['id']}/opening").json() == first


def test_failed_live_briefing_keeps_selected_opening_and_allows_retry(db,monkeypatch):
    fixed(monkeypatch,SCENARIOS[0])
    a=ScriptedAdapter()
    def fail(opening): raise ModelOutputInvalid("bad")
    a.brief_opening=fail;svc=GameService(db,a);g=svc.create_game()["game"]
    with pytest.raises(ServiceError): svc.generate_opening_briefing(g["id"])
    assert svc.get_game_detail(g["id"])["game"] == g
    a.brief_opening=lambda opening:"陛下，臣谨奏国情。"*10
    assert svc.generate_opening_briefing(g["id"])["source"] == "model"


def test_briefing_repairs_unit_or_identity_error_once():
    class Provider:
        timeout=10
        budgets=[]
        def _call(self,messages,temperature,budget):
            self.budgets.append(budget)
            return json.dumps({"briefing":("陛下，臣用八万两银。" if len(self.budgets)==1 else "陛下，臣谨奏，旧渠尚待整修，库款可供调度，乡里愿意协力，宜量力修渠，恢复农时。")*4})
    a=Provider();assert "八万" not in generate_briefing(a,SCENARIOS[0]);assert len(a.budgets)==2 and a.budgets[1]<=a.budgets[0]<=10


def test_new_appraisal_requires_title_comment_and_real_turns(db,monkeypatch):
    fixed(monkeypatch,SCENARIOS[0]);a=ScriptedAdapter(default=make_accepted());svc=GameService(db,a);g=svc.create_game()["game"]
    for t in range(2):svc.submit_turn(g["id"],str(t),t,"整理文书")
    set_state(db,g["id"],status="lost");detail=svc.get_game_detail(g["id"])
    with pytest.raises(ValueError):validate_review(EmperorReview.model_validate(valid_review()),detail)
    appraisal={**valid_review(),"reign_title":"持盈守业之君","historian_comment":"登基时钱粮尚有基础，旧渠却待整修；两回合均整理文书，未见针对农渠的实际改善。终局民心与钱粮基本维持，未新增已确认的灾变，却也不能将前期协作机会消退当作旧患已经消除。施政留有余地，未解之事仍须后来者查考。","referenced_turns":[1,2]}
    validate_review(EmperorReview.model_validate(appraisal),detail)
    a.assess_emperor=lambda detail:appraisal
    r=svc.generate_emperor_review(g["id"])
    assert svc.get_emperor_review(g["id"]) == r and r["review"]["reign_title"]=="持盈守业之君"
    appraisal["referenced_turns"]=[7,8]
    with pytest.raises(ValueError):validate_review(EmperorReview.model_validate(appraisal),detail)
    appraisal["referenced_turns"]=[1,2];appraisal["reign_title"]="承和"
    with pytest.raises(ValueError):validate_review(EmperorReview.model_validate(appraisal),detail)
    appraisal["reign_title"]="兴农之君";appraisal["historian_comment"] += "民力从五十升至八十二。"
    with pytest.raises(ValueError):validate_review(EmperorReview.model_validate(appraisal),detail)
