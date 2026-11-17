"""New configuration acceptance; all saves here are isolated test data."""
import copy
import json
import pytest
from app.domain import events
from app.llm.live import LiveAdapter, HISTORICAL_LORE, validate_history_clarification
from app.llm.base import ModelContext
from app.llm.schema import ClarificationCandidate
from conftest import make_accepted


def engine(version=3):
    e=events.initial_events('fortune3',events.seeded_opening('fortune3'))
    e['config_version']=version;e['schedule']=[1,2,3,4,5,6]
    return e


def weights(e,state):
    return {x['event_id']:x for x in events._weights(e,4,'disaster',{'negative'},state)}


def test_low_grain_boundary_and_disaster_whitelist():
    e=engine();low=weights(e,dict(people=50,treasury=60,grain=44))
    high=weights(e,dict(people=50,treasury=60,grain=45))
    for id in ('drought_local','locust_plague'):
        assert low[id]['weight']==pytest.approx(high[id]['weight']*1.6)
        assert low[id]['modifiers']==['resource:grain']
    assert low['flood_breach']==high['flood_breach']
    assert low['earthquake_damage']==high['earthquake_damage']
    for id in ('flood_breach','earthquake_damage'):
        bad=copy.deepcopy(events.CATALOG[id]);bad['resource_weight']={'resource':'grain','below':45,'multiplier':1.6}
        with pytest.raises(ValueError):events.EventDefinition.model_validate(bad)
    bad=copy.deepcopy(events.CATALOG['drought_local']);bad['resource_weight']['multiplier']=4.0
    with pytest.raises(ValueError):events.EventDefinition.model_validate(bad)
    bad=copy.deepcopy(events.CATALOG['drought_local']);bad['resource_weight']['resource']='people'
    with pytest.raises(ValueError):events.EventDefinition.model_validate(bad)


def test_legacy_config_is_pinned_and_has_no_low_grain_modifier():
    e=engine(2)
    a=weights(e,dict(people=0,treasury=0,grain=0));b=weights(e,dict(people=100,treasury=100,grain=100))
    assert {k:v for k,v in a.items() if events.CATALOG[k]['category']=='disaster'}=={k:v for k,v in b.items() if events.CATALOG[k]['category']=='disaster'}
    e.pop('config_version')
    events.select_event(e,2,dict(people=50,treasury=60,grain=20))
    assert e['audit'][-1]['config_version']==2
    assert events.public_events(e)['config_version']==2


def test_executed_history_changes_border_and_trade_weights():
    e=engine();state=dict(people=50,treasury=70,grain=60)
    def other():return {r['event_id']:r for r in events._weights(e,4,'other',{'negative','opportunity'},state)}
    baseline=other()
    e['policy_tags']=[dict(tag='border_defense',expires_after_turn=5),dict(tag='market_opening',expires_after_turn=5)]
    active=other()
    assert active['border_raids']['weight']<baseline['border_raids']['weight']
    assert active['trade_envoy']['weight']>baseline['trade_envoy']['weight']
    assert 'resource:treasury' in active['trade_envoy']['modifiers']
    e['policy_tags'][0]['expires_after_turn']=3
    assert other()['border_raids']['weight']==baseline['border_raids']['weight']


def test_commerce_benefits_and_heavy_tax_cost_are_configured():
    event=events.CATALOG['trade_envoy'];base=dict(people=1,treasury=5,grain=0)
    assert events._benefits(event,base,{'market_opening'})['treasury']==7
    assert events._benefits(event,base,{'heavy_trade_tax'})['treasury']==2
    assert events._benefits(events.LEGACY_CATALOG['trade_envoy'],base,{'market_opening'})==base
    assert events.policy_tags(events.validated_intent('提高商税',{}),'提高商税')==['heavy_trade_tax']
    assert 'heavy_trade_tax' not in events.policy_tags(events.validated_intent('不得提高商税',{}),'不得提高商税')


def test_ancient_education_is_real_action_but_negated_policy_is_not():
    assert events.validated_intent('按宋朝制度严明科举',{})['category']=='education'
    assert events.validated_intent('不得按宋朝制度严明科举',{})['category']=='inaction'
    assert events.policy_effect(events.validated_intent('按宋朝制度严明科举',{}),'按宋朝制度严明科举')['treasury']<0


def test_false_ancient_rejection_requests_model_repair_without_canned_acceptance():
    adapter=LiveAdapter('unused','unused','deepseek-chat')
    candidate=make_accepted().model_dump()
    accepted={k:candidate[k] for k in ('kind','normalized_goal','policy_intent','policy_analysis')}
    accepted['policy_intent']['category']='education'
    outputs=iter([json.dumps(dict(kind='clarification',warning_type='anachronism',message='未听闻宋朝')),json.dumps(accepted)])
    seen=[]
    def call(messages,*args):
        seen.append(copy.deepcopy(messages));return next(outputs)
    adapter._call=call
    context=ModelContext(game={'schema_version':4},turn_no=1,period='承和元年至三年',player_policy='按宋朝制度严明科举')
    assert adapter.evaluate(context).kind=='accepted'
    assert '知晓中国古代史' in seen[-1][-1]['content']
    modern=ClarificationCandidate(kind='clarification',warning_type='anachronism',message='手机非本朝可行')
    assert validate_history_clarification(modern,'参考宋朝科举，用手机考试')==modern


def test_all_live_provider_paths_include_the_same_history_lore(monkeypatch):
    import httpx
    sent=[]
    def post(url,**kwargs):
        sent.append(kwargs['json']);return httpx.Response(200,json={'choices':[{'message':{'content':'{}'}}]})
    monkeypatch.setattr(httpx,'post',post)
    adapter=LiveAdapter('https://example.invalid','unused','deepseek-chat')
    source=[{'role':'system','content':'intent'},{'role':'user','content':'policy'}]
    assert adapter._call(source,0.2,10)=='{}'
    assert sent[0]['messages'][0]['content'].endswith(HISTORICAL_LORE)
    assert source[0]['content']=='intent'


@pytest.mark.parametrize('text',['人口增四人','人口升五点至九十五','民数增三','民力增三分','民望升五点','库银减四','仓储由五十一增至六十一'])
def test_metric_alias_and_unit_loopholes_are_rejected(text):
    from app.domain.narration import prose_errors
    data=make_accepted().model_dump();data['summary']=text
    assert prose_errors(data,{'category':'water'})


def test_qualitative_population_context_and_labor_cost_remain_valid():
    from app.domain.narration import prose_errors
    data=make_accepted().model_dump();data['summary']='流民安置渐有着落，雇工领酬，地方民力得以休息。'
    assert not prose_errors(data,{'category':'water'})


def test_low_grain_boost_preserves_other_disasters_marginal_probability():
    e=engine();state=dict(people=50,treasury=60,grain=45)
    high_gate,high=events.disaster_gate(e,4,state)
    low_gate,low=events.disaster_gate(e,4,{**state,'grain':44})
    high_total=sum(c['weight'] for c in high);low_total=sum(c['weight'] for c in low)
    high={c['event_id']:c['weight']*high_gate/high_total for c in high}
    low={c['event_id']:c['weight']*low_gate/low_total for c in low}
    assert low['flood_breach']==pytest.approx(high['flood_breach'])
    assert low['earthquake_damage']==pytest.approx(high['earthquake_damage'])
    assert low['drought_local']==pytest.approx(high['drought_local']*1.6)
    assert low['locust_plague']==pytest.approx(high['locust_plague']*1.6)
    assert 0<high_gate<=low_gate<1
