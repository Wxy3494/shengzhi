import ast,inspect,json
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api.games import router
from app.services.game_service import GameService,ServiceError
from conftest import ScriptedAdapter,make_accepted,set_state
from test_treaties import start

def test_no_duplicate_preview_and_legacy_copy_removed(db):
    tree=ast.parse(inspect.getsource(GameService))
    assert sum(isinstance(n,ast.FunctionDef) and n.name=='preview_order' for n in tree.body[0].body)==1
    svc=GameService(db,ScriptedAdapter(default=make_accepted()),events_enabled=False)
    game=svc.create_game()['game'];plan=svc.preview_order(game['id'],0,'开仓放粮')
    assert plan['execution'] is None
    assert '旧版存档按原有' not in json.dumps(plan,ensure_ascii=False)

def test_repeat_counteroffers_and_accept_do_not_advance_policy_turn(db):
    svc,adapter,first=start(db);gid=first['game']['id']
    engine=json.loads(db.get_game(gid)['events_json']);schedule=engine['schedule'];event_records=engine['records']
    for revision in range(1,4):
        result=svc.negotiate(gid,f'counter-{revision}',revision,'counter','请降低赔款')
        assert result['game']['accepted_turns']==1 and result['game']['revision']==revision+1
        assert result['session']['proposal']['status']=='pending'
    accepted=svc.negotiate(gid,'accept-now',4,'accept',proposal_id=result['session']['proposal']['id'])
    assert accepted['game']['accepted_turns']==1 and accepted['game']['revision']==5
    for _ in range(3):assert svc.negotiate(gid,'accept-now',4,'accept',proposal_id=result['session']['proposal']['id'])==accepted
    fresh=json.loads(db.get_game(gid)['events_json'])
    assert fresh['records']==event_records and fresh['schedule']==schedule and len(db.get_history(gid))==1
    policy=svc.submit_turn(gid,'governance',5,'开仓放粮',2)
    assert policy['kind']=='accepted' and policy['game']['accepted_turns']==2 and policy['game']['revision']==6

def test_combined_decree_handles_diplomacy_and_preserves_only_one_goal(db):
    svc,adapter,first=start(db);gid=first['game']['id'];calls=len(adapter.calls)
    text='接受议和条件并开仓放粮'
    handled=svc.submit_turn(gid,'combined',1,text,2)
    assert handled['kind']=='diplomacy' and handled['session']['proposal']['status']=='accepted'
    assert handled['remaining_policy']=='开仓放粮' and handled['game']['accepted_turns']==1
    assert len(adapter.calls)==calls
    assert svc.submit_turn(gid,'combined',1,text,2)==handled
    result=svc.submit_turn(gid,'remaining',2,handled['remaining_policy'],2)
    assert result['result']['policy_intent']['category']=='relief' and result['game']['accepted_turns']==2

def test_legacy_combined_order_does_not_trigger_multiple_goals(db):
    svc=GameService(db,ScriptedAdapter(default=make_accepted()),events_enabled=False)
    game=svc.create_game()['game'];gid=game['id']
    response=svc.submit_turn(gid,'legacy-combined',0,'接受议和条件并开仓放粮')
    assert response['kind']=='diplomacy' and response['game']['accepted_turns']==0
    assert response['remaining_policy']=='开仓放粮' and response['game']['diplomacy']['pending']
    accepted=svc.negotiate(gid,'legacy-sign',1,'accept')
    assert accepted['game']['accepted_turns']==0
    normal=svc.submit_turn(gid,'legacy-policy',2,'开仓放粮',1)
    assert normal['kind']=='accepted' and normal['game']['accepted_turns']==1

def test_stale_offer_cannot_be_accepted(db):
    svc,adapter,first=start(db);gid=first['game']['id'];old=first['game']['diplomacy']['pending']['id']
    svc.negotiate(gid,'counter',1,'counter','还价')
    with pytest.raises(ServiceError,match='当前条款'):svc.negotiate(gid,'stale',2,'accept',proposal_id=old)
    assert db.get_game(gid)['revision']==2 and db.get_game(gid)['accepted_turns']==1

def test_legacy_new_war_after_peace_can_negotiate_again(db):
    svc=GameService(db,ScriptedAdapter(default=make_accepted()),events_enabled=False)
    gid=svc.create_game()['game']['id']
    svc.negotiate(gid,'first-offer',0,'counter','开始议和')
    svc.negotiate(gid,'first-peace',1,'accept')
    with pytest.raises(ServiceError,match='没有未结束'):svc.negotiate(gid,'no-war',2,'counter','再谈判')
    svc.submit_turn(gid,'new-war',2,'出兵迎敌',1)
    reopened=svc.negotiate(gid,'new-offer',3,'counter','议和')
    assert reopened['session']['proposal']['status']=='pending'
    assert reopened['game']['accepted_turns']==1

def test_rejected_talk_has_immediate_battle_with_no_year_advance(db):
    svc,adapter,first=start(db);gid=first['game']['id'];set_state(db,gid,people=90,treasury=90,grain=90)
    result=svc.negotiate(gid,'refuse-now',1,'reject')
    assert result['session']['battle']['attack_reason']=='refused_negotiation'
    assert result['game']['accepted_turns']==1 and len(db.get_history(gid))==1
    assert result['session']['state_diff']['treasury']!=0 or result['session']['battle']['paid_cost']['treasury']>0

def test_invalid_counteroffer_is_atomic(db):
    svc,adapter,first=start(db);gid=first['game']['id'];before=db.get_game(gid)
    adapter.propose_treaty=lambda *a:{'cities':1000,'treasury':1000,'grain':1,'reason':'invalid'}
    with pytest.raises(ServiceError):svc.negotiate(gid,'invalid',1,'counter','索取')
    assert db.get_game(gid)==before and svc.db.find_request_record(gid,'invalid') is None

@pytest.mark.parametrize('text',['',' ','\n\t','　'])
def test_empty_counteroffer_rejected_without_model_or_mutation(db,text):
    svc,adapter,first=start(db);gid=first['game']['id'];before=db.get_game(gid)
    adapter.propose_treaty=lambda *a:pytest.fail('empty counteroffer must not invoke model')
    with pytest.raises(ServiceError) as exc:svc.negotiate(gid,'empty-counter',1,'counter',text)
    assert exc.value.code=='EMPTY_COUNTEROFFER' and exc.value.status_code==422
    assert db.get_game(gid)==before and svc.db.find_request_record(gid,'empty-counter') is None

def test_api_diplomacy_idempotency_alias_and_policy_turn_are_separate(db):
    svc,adapter,first=start(db);gid=first['game']['id'];app=FastAPI();app.state.game_service=svc;app.include_router(router)
    with TestClient(app) as client:
        body={'idempotencyKey':'api-counter','expected_revision':1,'action':'counter','text':'还价'}
        response=client.post(f'/api/games/{gid}/diplomacy',json=body)
        assert response.status_code==200 and response.json()['game']['accepted_turns']==1
        assert client.post(f'/api/games/{gid}/diplomacy',json=body).json()==response.json()
        policy=client.post(f'/api/games/{gid}/turns',json={'idempotencyKey':'after-talk','expected_revision':2,'expectedTurn':2,'policy_text':'兴学'})
        assert policy.status_code==200 and policy.json()['game']['accepted_turns']==2

def test_eighth_policy_can_finish_its_pending_diplomacy_without_ninth_policy(db):
    svc,adapter,first=start(db);gid=first['game']['id'];set_state(db,gid,accepted_turns=7,revision=7,people=80,treasury=80,grain=80)
    final_policy=svc.submit_turn(gid,'eighth',7,'出兵迎敌',8)
    assert final_policy['game']['accepted_turns']==8 and final_policy['game']['status']=='playing'
    proposal=final_policy['game']['diplomacy']['pending'];assert proposal
    with pytest.raises(ServiceError):svc.submit_turn(gid,'ninth',8,'兴学',None)
    final=svc.negotiate(gid,'final-sign',8,'accept',proposal_id=proposal['id'])
    assert final['game']['accepted_turns']==8 and final['game']['status'] in ('won','lost')
    assert final['game']['diplomacy']['pending'] is None
