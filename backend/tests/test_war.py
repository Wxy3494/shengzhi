import copy
import json
import pytest
from app.domain import war,events
from app.services.game_service import GameService,ServiceError
from conftest import ScriptedAdapter,make_accepted,set_state

def engine(seed='war-test'):
    opening=events.seeded_opening(seed)
    return events.initial_events(seed,opening)

@pytest.mark.parametrize('text',['严旨督战','命诸将进兵','御驾亲征','出兵迎敌','攻打邻国'])
def test_combat_detection(text):
    intent=events.validated_intent(text,{})
    assert intent['category']!='inaction'
    assert war.is_combat(text,intent)

@pytest.mark.parametrize('text',['召集士兵','加强边防','发放军饷','不得出兵','暂缓亲征','只提到督战'])
def test_preparation_or_negated_combat_is_not_a_battle(text):
    assert not war.is_combat(text,events.validated_intent(text,{}))

def test_chance_monotonic_but_never_guaranteed():
    baseline=dict(people=50,treasury=50,grain=50)
    for key in baseline:
        stronger={**baseline,key:80}
        assert war.chance(stronger)>war.chance(baseline)
    assert 0<war.chance(dict.fromkeys(baseline,0))<war.chance(dict.fromkeys(baseline,100))<100

def test_seed_replay_costs_and_victory_returns():
    counts={'victory':0,'defeat':0}; signs=set()
    for seed in range(500):
        state=dict(people=80,treasury=80,grain=80); start=engine(str(seed)); frozen=copy.deepcopy(start)
        result=war.resolve(start,1,state,state)
        assert result==war.resolve(start,1,state,state) and start==frozen
        _,after,battle=result
        counts[battle['outcome']]+=1
        assert battle['paid_cost']['treasury']>=14 and battle['paid_cost']['grain']>=12
        assert all(type(v) is int and 0<=v<=100 for v in after.values())
        assert all(after[k]-state[k]==battle['effects'][k] for k in state)
        if battle['outcome']=='victory': signs.add(battle['effects']['treasury']>0)
    assert all(counts.values()) and signs=={True,False}

def test_repeated_orders_spend_each_turn_and_atomic_replay(db):
    svc=GameService(db,ScriptedAdapter(default=make_accepted()),events_enabled=True)
    game=svc.create_game(seed='war-repeat')['game']
    for turn in range(1,4):
        result=svc.submit_turn(game['id'],f'war-{turn}',turn-1,'严旨督战',turn)
        assert result['result']['events']['war']['paid_cost']['treasury']>0
        assert svc.submit_turn(game['id'],f'war-{turn}',turn-1,'严旨督战',turn)==result
        assert db.get_game(game['id'])['revision']==turn
        if result['game']['status']!='playing':break
    saved=json.loads(db.get_game(game['id'])['events_json'])
    assert len(saved['war']['records'])==turn

def test_catastrophic_loss_can_end_before_eight(db):
    state=dict(people=10,treasury=10,grain=10)
    seed=next(str(i) for i in range(100) if war.resolve(engine(str(i)),1,state,state)[2]['collapsed'])
    svc=GameService(db,ScriptedAdapter(default=make_accepted()),events_enabled=True)
    game=svc.create_game(seed=seed)['game'];set_state(db,game['id'],**state)
    result=svc.submit_turn(game['id'],'fatal',0,'御驾亲征',1)
    assert result['game']['status']=='lost'
    assert result['game']['ending']['kind']=='conquest'
    assert result['game']['accepted_turns']==1 and result['game']['events']['pending']==[]
    with pytest.raises(ServiceError):svc.submit_turn(game['id'],'after-death',1,'休养生息',2)

def test_legacy_save_does_not_gain_war_rules(db):
    svc=GameService(db,ScriptedAdapter(default=make_accepted()),events_enabled=False)
    game=svc.create_game()['game']
    result=svc.submit_turn(game['id'],'legacy-war',0,'御驾亲征')
    assert result['result'].get('events') is None
