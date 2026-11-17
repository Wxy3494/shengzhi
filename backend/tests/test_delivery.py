import pytest
from app.domain import events
from app.services.game_service import GameService
from conftest import ScriptedAdapter,make_accepted
from test_events import forced_pending

@pytest.mark.parametrize('text',['召集士兵','集结军队','招募军士','征兵'])
def test_mobilization_is_military_action(text):
    intent=events.validated_intent(text,{})
    assert intent['category']=='military'
    assert events.policy_tags(intent,text)==['border_defense']

@pytest.mark.parametrize('text',['不得召集士兵','不准征兵','只提到召集士兵，暂缓处理'])
def test_negated_or_deferred_mobilization_has_no_response_reward(text):
    intent=events.validated_intent(text,{})
    assert intent['category']=='inaction'
    assert not events.policy_tags(intent,text)


def test_mobilization_responds_to_border_event_once():
    engine,state=forced_pending('border_raids')
    updated,_,report=events.advance_events(engine,3,state,events.validated_intent('召集士兵',{}),'召集士兵')
    assert updated['records'][0]['outcome']=='well_handled' and len(report['responses'])==1
    _,_,again=events.advance_events(updated,4,state,events.validated_intent('兴学',{}),'兴学')
    assert not again['responses']


def test_three_retries_of_same_request_never_spend_another_turn(db):
    adapter=ScriptedAdapter(default=make_accepted())
    svc=GameService(db,adapter,events_enabled=True)
    game=svc.create_game(seed='delivery-replay')['game']
    result=svc.submit_turn(game['id'],'same-delivery',0,'召集士兵',1)
    for _ in range(3):assert svc.submit_turn(game['id'],'same-delivery',0,'召集士兵',1)==result
    assert db.get_game(game['id'])['revision']==1 and len(db.get_history(game['id']))==1
    assert len(adapter.calls)==1
