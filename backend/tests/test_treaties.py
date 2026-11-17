import json
import pytest
from app.domain import events,war,treaties
from app.services.game_service import GameService,ServiceError
from conftest import ScriptedAdapter,make_accepted,set_state

class TreatyAdapter(ScriptedAdapter):
    def __init__(self):super().__init__(default=make_accepted());self.offers=[]
    def propose_treaty(self,context,facts):
        self.offers.append(facts)
        return {'cities':1,'treasury':5 if len(self.offers)==1 else 3,'grain':4,'reason':'按战局与国力拟定，尚待玩家确认。'}

def start(db,outcome='defeat'):
    for i in range(100):
        seed=f'treaty-test-{i}';opening=events.seeded_opening(seed);engine=events.initial_events(seed,opening)
        if war.resolve(engine,1,opening['initial'],opening['initial'])[2]['outcome']==outcome:break
    adapter=TreatyAdapter();svc=GameService(db,adapter,events_enabled=True)
    game=svc.create_game(seed=seed)['game']
    battle=svc.submit_turn(game['id'],'battle',0,'严旨督战',1)
    return svc,adapter,battle

def test_defeat_only_proposes_and_unrelated_order_does_not_consent(db):
    svc,adapter,first=start(db)
    assert first['result']['events']['war']['ceded_city'] is False
    assert first['game']['events']['war']['cities_lost']==0
    proposal=first['result']['events']['treaty']
    assert proposal['status']=='pending' and proposal['source']=='model'
    assert '被迫割让' not in first['result']['events']['war']['text']
    second=svc.submit_turn(first['game']['id'],'unrelated',1,'修建运河',2)
    assert second['game']['events']['war']['pending_treaty']==proposal
    assert second['game']['events']['war']['cities_lost']==0
    assert len(adapter.offers)==1

def test_accept_is_once_only_and_city_transfer_matches_confirmed_offer(db):
    svc,adapter,first=start(db);gid=first['game']['id']
    second=svc.submit_turn(gid,'consent',1,'同意上述条件',2)
    treaty=second['session']['proposal']
    assert treaty['status']=='accepted' and treaty['effects']['treasury']==-5 and treaty['effects']['grain']==-4
    assert second['game']['events']['war']['cities_lost']==1
    assert second['game']['events']['war']['pending_treaty'] is None
    assert not second['game']['events']['war']['active']
    for _ in range(3):assert svc.submit_turn(gid,'consent',1,'同意上述条件',2)==second
    assert db.get_game(gid)['revision']==2 and len(adapter.offers)==1
    assert treaties.action('再次议和索要赔款',second['game']['events']) is None

def test_reject_continues_war_without_ceding(db):
    svc,adapter,first=start(db)
    result=svc.submit_turn(first['game']['id'],'refuse',1,'拒绝割地赔款，继续战争',2)
    assert result['session']['battle']['paid_cost']['treasury']>0
    assert result['game']['events']['war']['cities_lost']==0
    assert len(result['game']['events']['war']['records'])==2

def test_counteroffer_requires_fresh_consent(db):
    svc,adapter,first=start(db);gid=first['game']['id']
    result=svc.submit_turn(gid,'counter',1,'重新谈判，要求减少赔款',2)
    assert result['session'].get('battle') is None
    assert result['session']['proposal']['terms']['treasury']==3
    assert result['session']['proposal']['status']=='pending'
    assert result['game']['events']['war']['cities_lost']==0
    third=svc.submit_turn(gid,'accept-counter',2,'接受当前议和条件',2)
    assert third['session']['proposal']['effects']['treasury']==-3
    assert third['game']['accepted_turns']==1

def test_winner_must_confirm_before_receiving_indemnity(db):
    svc,adapter,first=start(db,'victory');gid=first['game']['id']
    assert first['result']['events']['treaty']['direction']=='receive'
    assert first['game']['events']['war'].get('cities_gained',0)==0
    second=svc.submit_turn(gid,'accept-payment',1,'接受议和条件',2)
    assert second['session']['proposal']['effects']['treasury']==5
    assert second['session']['proposal']['effects']['grain']==4
    assert second['game']['events']['war']['cities_gained']==1

def test_unfunded_acceptance_never_partially_pays_or_cedes(db):
    svc,adapter,first=start(db);gid=first['game']['id'];set_state(db,gid,treasury=0,grain=50)
    result=svc.submit_turn(gid,'unfunded',1,'同意上述条件',2)
    assert result['session']['proposal']['status']=='unfunded'
    assert result['session']['proposal']['effects']==dict.fromkeys(events.DIMS,0)
    assert result['game']['events']['war']['cities_lost']==0
    assert result['game']['events']['war']['pending_treaty']

def test_invalid_model_terms_rollback_entire_battle(db):
    adapter=TreatyAdapter();adapter.propose_treaty=lambda *a:{'cities':999,'treasury':999,'grain':0,'reason':'invalid'}
    svc=GameService(db,adapter,events_enabled=True);game=svc.create_game(seed='invalid-terms')['game']
    with pytest.raises(ServiceError,match='议和条件拟定失败'):svc.submit_turn(game['id'],'bad',0,'出兵迎敌',1)
    saved=db.get_game(game['id'])
    assert saved['revision']==0 and not json.loads(saved['events_json']).get('war')
    assert not db.get_history(game['id'])

@pytest.mark.parametrize('text',['如果同意条件会怎样','是否接受条件','考虑接受条件','同意沈砚建议，修建运河','接受人才，兴学育才'])
def test_conditional_wording_never_consents(text):
    assert treaties.action(text,{'war':{'pending_treaty':{'id':'test'}}}) is None

def test_last_turn_cannot_create_unsigned_transfer():
    engine={'war':{'version':2,'records':[],'cities_lost':0}}
    result=treaties.propose(engine,8,'defeat',{'cities':1,'treasury':5,'grain':4,'reason':'未签约。'})
    assert result['status']=='expired' and engine['war']['pending_treaty'] is None
    assert engine['war']['cities_lost']==0 and engine['war']['active']

def test_legacy_war_can_negotiate_future_terms_without_rewriting_history():
    legacy={'war':{'version':1,'records':[{'outcome':'defeat'}],'cities_lost':1}}
    assert treaties.action('与对方谈判议和',legacy)=='negotiate'
    assert legacy['war']['version']==1 and legacy['war']['cities_lost']==1

def test_unfunded_diplomacy_does_not_advance_to_last_turn(db):
    svc,adapter,first=start(db);gid=first['game']['id']
    set_state(db,gid,accepted_turns=7,revision=7,treasury=0,grain=50)
    final=svc.submit_turn(gid,'last-unfunded',7,'同意上述条件',8)
    assert final['session']['proposal']['status']=='unfunded'
    assert final['game']['accepted_turns']==7
    assert final['game']['events']['war']['pending_treaty']
    assert final['game']['events']['war']['cities_lost']==0
