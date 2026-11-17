import pytest
from app.domain import war,events
from app.services.game_service import GameService
from conftest import ScriptedAdapter,make_accepted,set_state
from test_treaties import start

@pytest.mark.parametrize('text',['继续反击','反攻敌军','还击','迎战敌军','应战','继续进攻','突袭敌营','击退敌军','收复失地'])
def test_counterattacks_are_real_battles(db,text):
    svc=GameService(db,ScriptedAdapter(default=make_accepted()),events_enabled=True)
    game=svc.create_game(seed='counterattack')['game']
    result=svc.submit_turn(game['id'],'counter',0,text,1)
    assert result['result']['policy_intent']['category']=='military'
    battle=result['result']['events']['war']
    assert battle['outcome'] in ('victory','defeat')
    assert battle['paid_cost']['treasury']>0 and battle['paid_cost']['grain']>0
    assert svc.submit_turn(game['id'],'counter',0,text,1)==result

@pytest.mark.parametrize('text',['不反击','不得反攻','不要还击','暂缓反击','只提到继续进攻','不进军','不攻击邻国'])
def test_negated_counterattacks_do_not_order_combat(text):
    assert not war.is_combat(text,events.validated_intent(text,{}))

@pytest.mark.parametrize('state,expected',[
    ({'people':19,'treasury':19,'grain':50},True),
    ({'people':19,'treasury':50,'grain':19},True),
    ({'people':50,'treasury':19,'grain':19},True),
    ({'people':19,'treasury':20,'grain':50},False),
    ({'people':20,'treasury':20,'grain':20},False),
])
def test_two_dimensions_strictly_below_twenty(state,expected):
    assert war.weak(state) is expected
    ongoing={'war':{'active':True,'records':[{}]}}
    assert bool(war.enemy_attack(ongoing,state)) is expected
    assert war.enemy_attack({'war':{'active':False,'records':[{}]}},state) is None
    assert war.enemy_attack({},state) is None

def test_refusal_causes_enemy_attack_and_no_new_offer(db):
    svc,adapter,first=start(db);gid=first['game']['id']
    result=svc.submit_turn(gid,'refuse-talk',1,'拒绝谈判',2)
    battle=result['session']['battle']
    assert battle['attack_reason']=='refused_negotiation'
    assert result['session'].get('proposal') is None
    assert result['game']['events']['war']['pending_treaty'] is None
    assert len(adapter.offers)==1

@pytest.mark.parametrize('policy',['同意上述条件','重新谈判','兴学育才'])
def test_two_weak_dimensions_prevent_terms_and_trigger_attack(db,policy):
    svc,adapter,first=start(db);gid=first['game']['id']
    set_state(db,gid,people=40,treasury=19,grain=19)
    result=svc.submit_turn(gid,'weak',1,policy,2)
    battle=result['session']['battle'] if result['kind']=='diplomacy' else result['result']['events']['war']
    assert battle['attack_reason']=='two_weak_dimensions'
    assert (result['session'].get('proposal') if result['kind']=='diplomacy' else result['result']['events'].get('treaty')) is None
    assert result['game']['events']['war']['cities_lost']==0
    assert not result['game']['events']['war']['pending_treaty']
    assert len(adapter.offers)==1
    if policy=='兴学育才':assert result['result']['execution']['actual_policy_effect']['treasury']<0
    assert svc.submit_turn(gid,'weak',1,policy,2)==result

def test_battle_exhaustion_stops_new_treaty_proposal(db):
    state=dict(people=40,treasury=32,grain=32)
    for i in range(100):
        seed=f'exhaustion-{i}';engine=events.initial_events(seed,events.seeded_opening(seed))
        _,after,battle=war.resolve(engine,1,state,state)
        if after['treasury']<16 and after['grain']<16:break
    class NoTerms(ScriptedAdapter):
        def propose_treaty(self,*args):raise AssertionError('No terms allowed after exhaustion')
    svc=GameService(db,NoTerms(default=make_accepted()),events_enabled=True)
    game=svc.create_game(seed=seed)['game'];set_state(db,game['id'],**state)
    result=svc.submit_turn(game['id'],'exhaust',0,'继续反击',1)
    assert result['result']['events'].get('treaty') is None
    assert not result['game']['events']['war']['pending_treaty']
    assert result['result']['events']['war']['negotiation_status']=='enemy_attacking'
