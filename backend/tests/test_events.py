"""Schema-4 acceptance: pure rules, persistence, API, adversarial model output."""
import copy
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.games import router
from app.domain import events
from app.domain.models import GameState
from app.llm.schema import parse_candidate
from app.services.game_service import GameService, ServiceError
from conftest import ScriptedAdapter, make_accepted


def new_engine(seed='event-test'):
    opening=events.seeded_opening(seed)
    return events.initial_events(seed,opening),opening['initial'].copy()


def forced_pending(id='flood_breach'):
    engine,state=new_engine(); definition=events.CATALOG[id]
    engine['records']=[dict(instance_id='2:'+id,event_id=id,announced_turn=2,respond_by_turn=3,
        category=definition['category'],polarity=definition['polarity'],tier=definition['tier'],
        status='pending_response',outcome='pending',escalation_count=0,immediate_effects={'people':-1,'treasury':0,'grain':-3})]
    engine['pending']=['2:'+id]; engine['schedule']=[]
    return engine,state


def test_catalog_schema_rejects_resource_probability_and_huge_impacts():
    assert len(events.CATALOG)==20
    data=json.loads((events.DATA/'events.json').read_text(encoding='utf8'))
    data['events'][0]['probabilityModifiers']=[{'when':'food<30','multiplier':5}]
    with pytest.raises(ValueError): events.load_catalog(data)
    del data['events'][0]['probabilityModifiers']
    data['events'][0]['immediate']['grain']=-7
    with pytest.raises(ValueError): events.load_catalog(data)


def test_next_turn_response_and_single_escalation():
    engine,state=forced_pending()
    unchanged=copy.deepcopy(engine)
    intent=events.validated_intent('赈济灾民并修堤',{})
    handled,after,report=events.advance_events(engine,3,state,intent,'赈济灾民并修堤')
    assert engine==unchanged
    assert handled['records'][0]['outcome']=='well_handled'
    assert not handled['pending'] and len(report['responses'])==1
    ignored,_,_=events.advance_events(engine,3,state,events.validated_intent('兴学',{}),'兴学')
    assert ignored['records'][0]['escalation_count']==1
    again,_,report=events.advance_events(ignored,4,state,events.validated_intent('兴学',{}),'兴学')
    assert again['records'][0]['escalation_count']==1 and not report['responses']


def test_partial_and_resource_limited_response():
    engine,state=forced_pending()
    intent=events.validated_intent('减轻田赋',{})
    updated,_,_=events.advance_events(engine,3,state,intent,'减轻田赋')
    assert updated['records'][0]['outcome']=='mitigated'
    state['treasury']=0
    updated,_,_=events.advance_events(engine,3,state,events.validated_intent('赈济灾民',{}),'赈济灾民')
    assert updated['records'][0]['outcome']=='mitigated'
    # A blocked policy does not claim a successful event response.
    updated,_,_=events.advance_events(engine,3,state,intent,'减轻田赋',True)
    assert updated['records'][0]['outcome']=='escalated'


def test_revoke_and_negation_cannot_create_protection():
    intent=events.validated_intent('不得修渠，不准赈济灾民',{})
    assert not events.policy_tags(intent,'不得修渠，不准赈济灾民')
    intent=events.validated_intent('撤销赈济旧令',{})
    assert not events.policy_tags(intent,'撤销赈济旧令')


@pytest.mark.parametrize(('text','category'),[('清查贪墨','justice'),('开放通商','trade'),('兴学育才','education'),('兴修水利','water'),('购粮补仓','grain_supply')])
def test_raw_policy_domain_overrides_wrong_model_tax_candidate(text,category):
    assert events.validated_intent(text,{'category':'tax','project':'land_tax'})['category']==category


def test_event_never_zeroes_positive_resource_and_damage_is_bounded():
    engine,state=forced_pending()
    state={k:1 for k in events.DIMS}
    updated,after,report=events.advance_events(engine,3,state,events.validated_intent('兴学',{}),'兴学')
    assert min(after.model_dump().values())>=1
    assert any(d['source']=='clamp' for d in report['state_diff'])


def test_low_grain_increases_unhandled_disaster_vulnerability():
    engine,state=forced_pending();state['grain']=30
    intent=events.validated_intent('兴学',{})
    _,high,_=events.advance_events(engine,3,state,intent,'兴学')
    state['grain']=20
    _,low,_=events.advance_events(engine,3,state,intent,'兴学')
    assert low.people==high.people-1


def test_pardon_has_bounded_conditional_program_echo():
    assert events.echo_effect({'raw_text':'大赦天下'})['people']==-2
    assert events.echo_effect({'raw_text':'大赦天下，重犯不赦'})['people']==1


def run_engine(seed):
    engine,state=new_engine(seed); frozen=json.dumps(engine['initial_state'],sort_keys=True)
    for turn in range(1,9):
        intent=events.validated_intent('兴修水利',{'category':'water'})
        engine,after,_=events.advance_events(engine,turn,state,intent,'兴修水利')
        state=after.model_dump()
        assert len(engine['pending'])<=2
        assert json.dumps(engine['initial_state'],sort_keys=True)==frozen
        assert all(0<=v<=100 for v in [*state.values(),*engine['class_support'].values()])
    return engine,state


def test_fixed_seed_and_1000_game_properties():
    assert run_engine('replay')==run_engine('replay')
    for n in range(1000):
        engine,_=run_engine(str(n))
        records=engine['records']
        assert 4<=len(records)<=6
        assert len({r['announced_turn'] for r in records})==len(records)
        assert len({r['event_id'] for r in records})==len(records)
        assert sum(r['tier']=='major' for r in records)<=1
        assert any(r['polarity'] in ('positive','opportunity') for r in records)
        assert not engine['pending']
        assert all(r['respond_by_turn'] is None or r['respond_by_turn']<=8 for r in records)
        for a,b in zip(records,records[1:]):
            if b['announced_turn']==a['announced_turn']+1:
                assert a['category']!=b['category']
                assert not a['polarity']==b['polarity']=='negative'
        for audit in engine['audit']:
            if audit['chosen']!='peaceful_season':
                assert any(c['event_id']==audit['chosen'] and c['weight']>0 for c in audit['candidates'])


def disaster_sequence(seed,grain):
    engine,state=new_engine(seed); state['grain']=grain
    disaster=[]
    # The same policy/season history, but other-lane social selection may differ.
    for turn in range(1,9):
        event=events.select_event(engine,turn,state)
        if event['id']=='peaceful_season': continue
        if event['category']=='disaster': disaster.append((turn,event['id']))
        engine['records'].append({'event_id':event['id'],'announced_turn':turn,'category':event['category'],
            'tier':event['tier'],'polarity':event['polarity'],'outcome':'escalated'})
        if turn>=2: engine['forewarnings']=[{'turn':2}]
    return disaster


def test_10000_paired_grain_levels_raise_drought_and_locust_frequency():
    from collections import Counter
    low=Counter();high=Counter()
    for n in range(10000):
        low.update(e for _,e in disaster_sequence(str(n),30))
        high.update(e for _,e in disaster_sequence(str(n),70))
    assert low['drought_local']>high['drought_local']
    assert low['locust_plague']>high['locust_plague']
    assert disaster_sequence('repeat',30)==disaster_sequence('repeat',30)


def test_title_priority_and_recovery():
    engine,_=new_engine()
    engine['initial_state']={'people':46,'treasury':58,'grain':56}
    engine['records']=[{'respond_by_turn':3,'tier':'medium','outcome':'well_handled'}]
    assert events.appraise(engine,{'people':85,'treasury':60,'grain':25})['title']=='盛名之下'
    assert events.appraise(engine,{'people':85,'treasury':60,'grain':60})['title']=='中兴之主'
    engine['initial_state']={'people':52,'treasury':54,'grain':54}
    assert events.appraise(engine,{'people':85,'treasury':60,'grain':60})['title']=='守成明君'
    assert events.appraise(engine,{'people':65,'treasury':60,'grain':60})['title']=='未竟之君'
    assert events.appraise(engine,{'people':50,'treasury':54,'grain':54})['title']=='治世未成'


def test_api_8_turns_idempotency_and_reload(db):
    adapter=ScriptedAdapter(default=make_accepted(policy_effect={'people':99,'treasury':99,'grain':99}))
    service=GameService(db,adapter,events_enabled=True)
    app=FastAPI();app.include_router(router);app.state.game_service=service
    client=TestClient(app);game=client.post('/api/games').json()['game'];gid=game['id']
    initial=db.get_game(gid)['opening_json']
    for turn in range(1,9):
        body={'idempotencyKey':f't{turn}','expectedTurn':turn,'expected_revision':turn-1,'policy_text':f'兴修城西水渠，查验第{turn}段'}
        response=client.post(f'/api/games/{gid}/turns',json=body)
        assert response.status_code==200,response.text
        first=response.json()
        assert first['game']['status']=='playing' if turn<8 else first['game']['status'] in ('won','lost')
        assert client.post(f'/api/games/{gid}/turns',json=body).json()==first
        assert db.get_game(gid)['opening_json']==initial
        detail=client.get(f'/api/games/{gid}').json()
        assert detail['history'][-1]['events']==first['result']['events']
        assert detail['game']['events']==first['game']['events']
        assert abs(first['result']['execution']['actual_policy_effect']['people'])<=8
        r=first['result'];event_delta=r['events']
        for dim in events.DIMS:
            components=r['execution']['actual_policy_effect'][dim]+sum(e[dim] for e in r['echo_effects'])
            components+=sum(e['response_effects'][dim] for e in event_delta['responses'])
            if event_delta['announcement']: components+=event_delta['announcement']['immediate_effects'][dim]
            assert r['after'][dim]-r['before'][dim]==components
    assert not detail['game']['events']['pending']
    assert detail['game']['events']['appraisal']['title']==detail['game']['ending']['title']
    assert db.get_game(gid)['revision']==8
    with pytest.raises(ValueError):
        raw=make_accepted().model_dump();raw['stateDelta']={'support':99};parse_candidate(json.dumps(raw))


def test_expected_turn_required_and_conflict_no_model_or_state_change(db):
    adapter=ScriptedAdapter(default=make_accepted());svc=GameService(db,adapter,events_enabled=True)
    game=svc.create_game()['game']
    for expected in (None,2):
        with pytest.raises(ServiceError): svc.submit_turn(game['id'],'bad',0,'修渠',expected)
    assert not adapter.calls and db.get_game(game['id'])['revision']==0


def test_no_early_win_or_resource_loss_ending_for_schema4(db):
    svc=GameService(db,ScriptedAdapter(default=make_accepted()),events_enabled=True)
    game=svc.create_game()['game']
    db._conn.execute('UPDATE games SET people=95, treasury=0, grain=0 WHERE id=?',(game['id'],))
    response=svc.submit_turn(game['id'],'first',0,'恢复原税额',1)
    assert response['game']['people']>=80
    assert response['game']['status']=='playing' and response['game']['ending'] is None
    assert response['game']['realm']['version']==3
    assert 'pressures' not in response['game']['realm']


def test_disaster_weights_independent_of_non_grain_resources_and_class_values():
    engine,_=new_engine('weight-test')
    engine['forewarnings']=[{'turn':2}]
    a=events._weights(engine,4,'disaster',{'negative'},dict(people=0,treasury=0,grain=30))
    engine['class_support']=dict.fromkeys(events.CLASSES,0)
    b=events._weights(engine,4,'disaster',{'negative'},dict(people=100,treasury=100,grain=30))
    assert [r for r in a if events.CATALOG[r['event_id']]['category']=='disaster']==[r for r in b if events.CATALOG[r['event_id']]['category']=='disaster']


def test_config_schema_and_major_forewarning_and_positive_pity():
    for n in range(200):
        engine,_=run_engine('watch-'+str(n))
        for r in engine['records']:
            if r['tier']=='major':
                assert 3<=r['announced_turn']<=6
                assert engine['forewarnings'][0]['turn']<r['announced_turn']
        negative=0
        for audit in engine['audit']:
            if not audit['scheduled']: continue
            if negative==2:
                assert audit['positive_or_quiet_weight_share']>=0.4
            event=events.CATALOG[audit['chosen']]
            negative=negative+1 if event['polarity']=='negative' else 0


def test_transaction_failure_rolls_back_event_audit_and_policy(db,monkeypatch):
    svc=GameService(db,ScriptedAdapter(default=make_accepted()),events_enabled=True)
    game=svc.create_game()['game'];before=db.get_game(game['id'])
    def fail(*args): raise RuntimeError('injected write failure')
    monkeypatch.setattr(db,'insert_request_record',fail)
    with pytest.raises(ServiceError): svc.submit_turn(game['id'],'r',0,'修渠',1)
    assert db.get_game(game['id'])==before
    assert not db.get_history(game['id']) and not db.find_request_record(game['id'],'r')


def test_six_string_narration_preserves_state_and_rejects_injection():
    from app.llm.live import LiveAdapter
    from app.llm.base import ModelContext, ModelOutputInvalid
    from app.llm.schema import candidate_to_dict
    adapter=LiveAdapter('unused','unused','test')
    raw={'advisor':'陛下，臣已按原诏修渠，支用库款，以利农田。','summary':'修渠支出库款，田间用水渐畅。',
         'tian_bo':'田头得水，乡亲们愿把田亩照料好。','song_zhiyuan':'运粮的水道仍需照料，商帮愿配合。',
         'gu_tingzhang':'地方田产受益，也当按账分摊工费。','tradeoff':'修渠有益田间供水，也占用库款。'}
    adapter._call=lambda *args:json.dumps(raw)
    context=ModelContext(game={'schema_version':4},turn_no=1,period='承和元年至三年',player_policy='修渠')
    data=candidate_to_dict(make_accepted(policy_effect={'people':6,'treasury':-7,'grain':-1}))
    facts={'intent':events.validated_intent('修渠',{}),'blocked':False,'before':dict(people=50,treasury=60,grain=60),
           'after':dict(people=56,treasury=53,grain=59),'actual_policy_effect':data['policy_effect'],
           'actual_echo_effects':[],'event_report':None,'constraint_notes':[],'history':[]}
    result=adapter.narrate(context,data,facts)
    assert result['policy_effect']==data['policy_effect']
    assert {r['speaker'] for r in result['reactions']}=={'tian_bo','song_zhiyuan','gu_tingzhang'}
    raw['stateDelta']={'support':99}
    with pytest.raises(ModelOutputInvalid): adapter.narrate(context,data,facts)


def test_concurrent_retry_only_commits_one_event_audit(db):
    import threading
    from concurrent.futures import ThreadPoolExecutor
    barrier=threading.Barrier(2)
    class RacingAdapter:
        def evaluate(self,context):
            barrier.wait(timeout=5)
            return make_accepted()
    svc=GameService(db,RacingAdapter(),events_enabled=True)
    game=svc.create_game(seed='race')['game']
    with ThreadPoolExecutor(max_workers=2) as pool:
        calls=[pool.submit(svc.submit_turn,game['id'],'same',0,'修渠',1) for _ in range(2)]
        responses=[call.result() for call in calls]
    assert responses[0]==responses[1]
    stored=json.loads(db.get_game(game['id'])['events_json'])
    assert len(stored['audit'])==1 and len(stored['records'])==1
    assert len(db.get_history(game['id']))==1


def test_same_seed_same_orders_same_entire_engine_state(db):
    svc=GameService(db,ScriptedAdapter(default=make_accepted()),events_enabled=True)
    states=[]
    for _ in range(2):
        game=svc.create_game(seed='full-replay')['game']
        for turn,text in enumerate(['修渠','购粮补仓','赈济灾民','清查贪墨','开放通商','兴学','修路','恢复原税额'],1):
            game=svc.submit_turn(game['id'],f'r{turn}',turn-1,text,turn)['game']
        states.append((json.loads(db.get_game(game['id'])['events_json']),[game[k] for k in events.DIMS],game['status']))
    assert states[0]==states[1]


def test_model_cannot_override_rule_title_or_historian_facts(db):
    from test_emperor import Historian, valid_review
    class TamperedHistorian(Historian):
        def assess_emperor(self,detail):
            return {**valid_review(),'reign_title':'模型伪造称号','historian_comment':'伪造事迹'*30,'referenced_turns':[99]}
    svc=GameService(db,TamperedHistorian(),events_enabled=True)
    game=svc.create_game(seed='title-test')['game']
    for turn in range(1,9): game=svc.submit_turn(game['id'],str(turn),turn-1,'修渠',turn)['game']
    portrait=svc.generate_emperor_review(game['id'])
    assert portrait['review']['reign_title']==game['events']['appraisal']['title']
    assert '伪造' not in portrait['review']['historian_comment']
    assert portrait['review']['referenced_turns']==[1,2]


def test_non_object_intent_model_output_rejected_cleanly():
    from app.llm.live import LiveAdapter
    from app.llm.base import ModelContext, ModelOutputInvalid
    adapter=LiveAdapter('unused','unused','test');adapter._call=lambda *args:'[]'
    context=ModelContext(game={'schema_version':4},turn_no=1,period='承和元年至三年',player_policy='修渠')
    with pytest.raises(ModelOutputInvalid): adapter.evaluate(context)
