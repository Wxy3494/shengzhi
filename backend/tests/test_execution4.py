import json
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api.games import router
from app.domain import events
from app.domain.policy_actions import action_categories
from app.domain.narration import narration_errors
from app.services.game_service import GameService
from app.llm.schema import candidate_to_dict
from conftest import ScriptedAdapter,make_accepted,set_state
from test_roles_and_tradeoffs import role_texts

@pytest.mark.parametrize('text',['把粮食都发给百姓','粮食分给灾民','将官粮发给饥民','分发粮食','发粮救济百姓'])
def test_relief_synonyms_are_executed_and_can_respond_to_disaster(text):
    intent=events.validated_intent(text,{})
    assert intent['category']=='relief'
    assert events.policy_effect(intent,text)['people']>0
    assert 'relief_reserves' in events.policy_tags(intent,text)

@pytest.mark.parametrize('text',['不把粮食发给百姓','不得将粮食发给灾民','听闻修建长城','不修建长城'])
def test_negated_and_reference_actions_not_executed(text):
    # "不把" is a negation too; no fabricated relief actions.
    assert not set(action_categories(text)) & {'relief','defense'}

@pytest.mark.parametrize('turn',[1,8])
def test_great_wall_has_real_work_and_cost_even_at_final_turn(db,turn):
    svc=GameService(db,ScriptedAdapter(default=make_accepted()),events_enabled=True)
    gid=svc.create_game(seed='execution-wall')['game']['id']
    if turn==8:
        for t in range(1,8):svc.submit_turn(gid,'setup'+str(t),t-1,'休养生息',t)
    set_state(db,gid,treasury=80,grain=80)
    preview=svc.preview_order(gid,turn-1,'修建长城')
    assert '边防' in preview['execution']
    response=svc.submit_turn(gid,'wall',turn-1,'修建长城',turn)
    assert response['result']['policy_intent']['category']=='defense'
    assert response['result']['execution']['actual_policy_effect']['treasury']<0
    assert response['result']['execution']['execution_required']
    assert not response['result']['execution']['blocked']
    assert svc.submit_turn(gid,'wall',turn-1,'修建长城',turn)==response

def test_public_catalog_is_complete_and_requires_no_game(db):
    app=FastAPI();app.include_router(router)
    with TestClient(app) as client:
        result=client.get('/api/emperors')
        assert result.status_code==200
        body=result.json();assert body['count']==len(body['emperors'])==24
        assert len({e['id'] for e in body['emperors']})==24
        assert all(e['facts'] and e['sources'] for e in body['emperors'])

@pytest.mark.parametrize('line',['官仓既空，乡里须另筹粮源。','地方仓储亦随之告罄。'])
def test_remaining_grain_cannot_be_narrated_as_empty(line):
    data=candidate_to_dict(make_accepted(advisor=line,reactions=role_texts()))
    errors=narration_errors(data,{'intent':{'category':'relief'},'before':{'people':50,'treasury':60,'grain':94},'after':{'people':53,'treasury':58,'grain':90}})
    assert any('实际粮储仍有留存' in e for e in errors)
