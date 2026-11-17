import json
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api.games import router
from app.domain import events,treaties
from app.domain.narration import narration_errors,prose_errors
from app.services.game_service import GameService,ServiceError
from conftest import ScriptedAdapter,make_accepted,set_state
from test_treaties import start
from test_events import forced_pending

@pytest.mark.parametrize('text',[
 '同意，割让一城，赔款5，粮储4',
 '接受原条款，城池1座，国库五，粮草四',
 '同意按原条件赔款5、粮草4并割让1城',
])
def test_restatement_accepts_same_offer_in_one_turn(db,text):
    svc,adapter,first=start(db);gid=first['game']['id']
    preview=svc.preview_order(gid,1,text)
    assert '当前回合处理议和' in preview['execution']
    result=svc.submit_turn(gid,'same-numbers',1,text,2)
    assert result['session']['proposal']['status']=='accepted'
    assert result['session']['proposal']['effects']['treasury']==-5
    assert result['game']['accepted_turns']==1
    assert len(adapter.offers)==1

@pytest.mark.parametrize('text',['同意，但赔款改为3','同意割让两城，赔款5，粮储4','同意赔款三，粮储4'])
def test_changed_terms_need_new_consent(text):
    engine={'war':{'pending_treaty':{'terms':{'cities':1,'treasury':5,'grain':4}}}}
    assert treaties.action(text,engine)=='negotiate'

@pytest.mark.parametrize('text,category',[
 ('大兴宫殿、无偿征役','coercive'),('营建行宫','coercive'),
 ('平粜官粮，使贫户买粮','trade'),('平粜粮食，百姓向官仓购粮','trade'),
 ('朝廷购粮补仓，并令贫户买粮','grain_supply'),
 ('不得大兴宫殿，不准无偿征役','inaction'),
])
def test_actor_and_synonym_plan_matches_settlement(db,text,category):
    adapter=ScriptedAdapter(default=make_accepted());svc=GameService(db,adapter,events_enabled=True)
    game=svc.create_game(seed='preflight-action')['game']
    plan=svc.preview_order(game['id'],0,text)
    assert plan['intent']['category']==category and not adapter.calls
    if text=='营建行宫':assert '征役' not in plan['execution']
    assert db.get_game(game['id'])['revision']==0 and not db.get_history(game['id'])
    result=svc.submit_turn(game['id'],'execute',0,text,1)
    assert result['result']['policy_intent']['category']==plan['intent']['category']
    if category=='coercive':assert result['result']['execution']['actual_policy_effect']['treasury']<0

def test_preview_due_events_read_only_and_revision_bound(db):
    svc=GameService(db,ScriptedAdapter(default=make_accepted()),events_enabled=True)
    game=svc.create_game(seed='preview-due')['game'];engine,_=forced_pending()
    db._conn.execute('UPDATE games SET accepted_turns=2,revision=2,events_json=? WHERE id=?',(json.dumps(engine),game['id']))
    app=FastAPI();app.include_router(router);app.state.game_service=svc
    before=db.get_game(game['id'])
    with TestClient(app) as client:
        for _ in range(3):
            result=client.post(f"/api/games/{game['id']}/preview",json={'expected_revision':2,'policy_text':'修堤，不强征民夫'})
            assert result.status_code==200
            preview=result.json()
            assert preview['due_events'][0]['turn']==3 and preview['due_events'][0]['name']
            assert preview['prohibitions']==['不强征民夫']
        stale=client.post(f"/api/games/{game['id']}/preview",json={'expected_revision':1,'policy_text':'修堤'})
        assert stale.status_code==409
    assert before==db.get_game(game['id']) and not svc.adapter.calls

def test_condition_status_has_one_basis(db):
    svc=GameService(db,ScriptedAdapter(default=make_accepted()),events_enabled=True)
    game=svc.create_game(seed='condition-basis')['game'];gid=game['id']
    set_state(db,gid,people=80,treasury=80,grain=80)
    detail=svc.get_game_detail(gid)
    assert detail['game']['conditions']['resolved']
    set_state(db,gid,people=10,treasury=10,grain=10)
    assert not svc.get_game_detail(gid)['game']['conditions']['resolved']

@pytest.mark.parametrize('text',['若政令得行，人口便会增长','民心就是人口','人丁渐多，民心稳固'])
def test_population_is_not_morale_even_after_condition(text):
    data=make_accepted(advisor=text).model_dump()
    assert any('人口' in e for e in prose_errors(data,{}))

def test_war_and_repair_prose_must_match_facts():
    data=make_accepted(summary='此役战败，天下平稳，旧患未化解。').model_dump()
    facts={'intent':{'category':'military','action':'enact'},'war':{'outcome':'defeat','ceded_city':False,'collapsed':False},
        'opening_repair':True,'history':[],'constraint_notes':[]}
    errors=narration_errors(data,facts)
    assert any('天下平稳' in e for e in errors) and any('修复叙事' in e for e in errors)
