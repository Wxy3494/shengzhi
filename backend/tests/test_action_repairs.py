import pytest
from app.domain import events
from app.domain.narration import prose_errors
from test_events import forced_pending
from app.services.game_service import GameService
from conftest import ScriptedAdapter,make_accepted


@pytest.mark.parametrize(('text','category'),[
 ('雇工修渠，不强征、不搜刮、不夺种粮','water'),
 ('雇工修城西水渠，不强征、不搜刮、不夺种粮','water'),
 ('不强征民夫，但雇工修渠','water'),
 ('开放通商，商税照旧，不增税','trade'),
 ('允许沿堤集市经营','trade'),
 ('加固河堤','dike'),
 ('禁言，拘押批评者，没收家产','repression'),
 ('禁止百姓议论朝政','repression'),
 ('禁止拘押批评者','inaction'),
 ('不拨款、不发粮、不作新政','inaction'),
 ('决口交地方自理，修完宫殿再问灾情','inaction'),
])
def test_actual_actions_override_misleading_model_category(text,category):
    intent=events.validated_intent(text,{'category':'relief','magnitude':'full'})
    assert intent['category']==category
    effect=events.policy_effect(intent,text)
    if category in ('water','dike','trade'):assert effect['people']>0
    if category=='repression':assert effect['people']<0 and not events.policy_tags(intent,text)
    if category=='inaction':
        assert not any(effect.values()) and not events.policy_tags(intent,text)
        assert not events.policy_echoes(intent,False,1)
        assert not any(events.echo_effect({'raw_text':text}).values())


@pytest.mark.parametrize(('text','outcome'),[
 ('决口交地方自理，修完宫殿再问灾情','escalated'),
 ('不拨款、不发粮、不修堤，只问决口情况','escalated'),
 ('只提到修堤，暂缓处理','escalated'),
 ('本次不拨款，修堤交地方自理','escalated'),
 ('允许沿堤集市经营','escalated'),
 ('拨款抢修决口，不强征民夫','well_handled'),
 ('开仓赈济灾民，不许官吏侵吞','well_handled'),
])
def test_event_response_requires_executed_relevant_action(text,outcome):
    engine,state=forced_pending()
    intent=events.validated_intent(text,{'category':'relief'})
    updated,_,_=events.advance_events(engine,3,state,intent,text)
    assert updated['records'][0]['outcome']==outcome


@pytest.mark.parametrize('text',['民心增加三成。','人口增长三成。','人丁增加了。'])
def test_no_population_or_percent_invented_from_support(text):
    assert prose_errors({'advisor':text,'summary':'','reactions':[],'echo_effects':[],'new_echoes':[]},{'category':'other'})


def test_winning_fallback_is_never_failure_title():
    engine,_=forced_pending();engine['records']=[]
    result=events.appraise(engine,{'people':90,'treasury':40,'grain':40})
    assert result['won'] and result['title']=='民心归附' and result['handling_score']==0


def test_no_action_route_cannot_farm_support_or_handling(db):
    for seed in range(30):
        svc=GameService(db,ScriptedAdapter(default=make_accepted(policy_effect={'people':99,'treasury':99,'grain':99})),events_enabled=True)
        game=svc.create_game(seed='inaction-'+str(seed))['game']
        for turn in range(1,9):
            game=svc.submit_turn(game['id'],str(turn),turn-1,'不拨款、不发粮、不作新政',turn)['game']
        assert game['status']=='lost'
        assert game['events']['appraisal']['handling_score']==0
        assert game['events']['appraisal']['title']!='中兴之主'
