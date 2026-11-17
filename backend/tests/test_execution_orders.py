import pytest
from app.domain import events
from app.domain.narration import narration_errors
from app.services.game_service import GameService
from conftest import ScriptedAdapter, make_accepted


@pytest.mark.parametrize('text,category', [
    ('修建运河','water'), ('开凿运河，不强征民夫','water'),
    ('御驾亲征','military'), ('率军出征','military'),
])
def test_orders_have_execution_costs_and_are_not_inaction(db, text, category):
    svc=GameService(db,ScriptedAdapter(default=make_accepted()),events_enabled=True)
    game=svc.create_game(seed='execution-orders')['game']
    result=svc.submit_turn(game['id'],'execute',0,text,1)
    assert result['kind']=='accepted'
    turn=result['result']
    assert turn['policy_intent']['category']==category
    if turn.get('events',{}).get('war'):
        assert turn['events']['war']['paid_cost']['treasury']>0
        assert turn['events']['war']['paid_cost']['grain']>0
    else:
        assert turn['execution']['actual_policy_effect']['treasury']<0
        assert turn['execution']['actual_policy_effect']['grain']<0
    assert svc.submit_turn(game['id'],'execute',0,text,1)==result
    assert db.get_game(game['id'])['revision']==1


@pytest.mark.parametrize('text',['不御驾亲征','不得修建运河','暂缓御驾亲征','只是提到修建运河','不出兵迎敌'])
def test_prohibitions_and_mentions_do_not_execute(text):
    assert events.validated_intent(text,{})['category']=='inaction'


@pytest.mark.parametrize('line', ['运河之议已下，然未动工。','臣请亲征之议宜缓。'])
def test_model_cannot_veto_an_executable_order(line):
    data=make_accepted().model_dump()
    data['advisor']=line
    facts={'intent':events.validated_intent('修建运河',{}), 'execution_required':True,
           'blocked':False,'history':[], 'constraint_notes':[]}
    assert any('人物不能擅自' in error for error in narration_errors(data,facts))
    facts['execution_required']=False
    assert not any('人物不能擅自' in error for error in narration_errors(data,facts))
