import json
import pytest
from app.domain import events
from app.domain.historical_policies import is_order
from app.llm.live import LiveAdapter,validate_history_clarification
from app.llm.schema import ClarificationCandidate
from app.llm.base import ModelContext
from app.services.game_service import GameService
from conftest import ScriptedAdapter,make_accepted

@pytest.mark.parametrize('text,category',[
 ('焚书坑儒','repression'),('实行文字狱','repression'),('实施推恩令','administration'),
 ('摊丁入亩','finance'),('推行均田制','reform'),('实行商鞅变法','reform'),('实行科举制','education'),
 ('实行明治维新','reform'),('效仿改革开放','reform')])
def test_historical_shorthand_is_real_policy(text,category):
    assert is_order(text) and events.validated_intent(text,{})['category']==category

@pytest.mark.parametrize('text',['介绍焚书坑儒','焚书坑儒是什么','不要焚书坑儒','不得实行文字狱'])
def test_questions_and_prohibitions_are_not_positive_historical_orders(text):
    assert not is_order(text)
    assert events.validated_intent(text,{})['category']=='inaction'

@pytest.mark.parametrize('warning',['anachronism','not_policy','unclear','multiple_goals'])
def test_history_rejection_is_repaired_not_returned_to_player(warning):
    candidate=ClarificationCandidate(kind='clarification',warning_type=warning,message='本朝无此制，臣不敢奉诏。')
    with pytest.raises(ValueError,match='历史事件名称'):validate_history_clarification(candidate,'焚书坑儒')

def test_model_retries_false_history_rejection_then_accepts():
    adapter=LiveAdapter('unused','unused','test');calls=[]
    def call(messages,*args):
        calls.append(messages)
        if len(calls)==1:return json.dumps({'kind':'clarification','warning_type':'anachronism','message':'秦代暴政，本朝并无此制。'})
        return json.dumps({'kind':'accepted','normalized_goal':'焚书坑儒','policy_intent':{'category':'repression'},
            'policy_analysis':{'benefits':['控制言论'],'costs':['损害文化与信任'],'risks':[],'effect_basis':'统治控制不等于民众受益。'}},ensure_ascii=False)
    adapter._call=call
    result=adapter.evaluate(ModelContext(game={'schema_version':4},turn_no=1,period='承和元年至三年',player_policy='焚书坑儒'))
    assert result.kind=='accepted' and len(calls)==2

def test_harmful_historical_policy_executes_with_cost_and_no_history_replay(db):
    svc=GameService(db,ScriptedAdapter(default=make_accepted()),events_enabled=True)
    game=svc.create_game(seed='history6')['game'];gid=game['id']
    assert '文化压制' in svc.preview_order(gid,0,'焚书坑儒')['execution']
    response=svc.submit_turn(gid,'historical',0,'焚书坑儒',1)
    assert response['kind']=='accepted' and response['game']['accepted_turns']==1
    assert response['result']['policy_intent']['category']=='repression'
    assert response['result']['execution']['actual_policy_effect']['people']<0
    assert response['game']['status']=='playing'
    assert svc.submit_turn(gid,'historical',0,'焚书坑儒',1)==response
