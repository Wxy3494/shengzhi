import json
import pytest
from app.domain.crisis_v3 import initial_crisis,advance_crisis
from app.domain.models import GameState
from app.services.game_service import GameService,ServiceError
from app.llm.base import ModelOutputInvalid
from conftest import ScriptedAdapter,make_accepted

@pytest.mark.parametrize('kind,state,text,intent',[
 ('civil',(10,60,40),'继续施政',{'category':'other'}),
 ('army',(40,5,5),'整编军队',{'category':'military'}),
 ('border',(40,15,15),'加强边疆驻防',{'category':'military'}),
 ('bankruptcy',(50,0,40),'继续施政',{'category':'other'})])
def test_each_crisis_has_two_distinct_warning_turns_before_ending(kind,state,text,intent):
    realm=initial_crisis();notices=[]
    for turn in range(1,9):
        realm=advance_crisis(realm,GameState(people=state[0],treasury=state[1],grain=state[2]),intent,text,False,[],turn)
        notices += [(turn,w['threshold']) for w in realm['warnings'] if w['id']==kind]
        if realm['ending']:break
    assert [n[1] for n in notices]==[75,90]
    assert notices[0][0]<notices[1][0]<turn
    assert realm['ending']['kind']==kind and turn<8

def test_relief_recovery_and_no_repeat_warning_after_rebound():
    realm=initial_crisis();realm['pressures']['bankruptcy']=70
    def advance(r,t,money):return advance_crisis(r,GameState(people=50,treasury=money,grain=50),{'category':'other'},'整理政务',False,[],t)
    realm=advance(realm,1,0);assert realm['pressures']['bankruptcy']==75
    realm=advance(realm,2,60);assert realm['pressures']['bankruptcy']==50 and not realm['warnings']
    realm=advance(realm,3,0);assert not realm['warnings']
    realm=advance(realm,4,0);assert [w['threshold'] for w in realm['warnings']]==[90]

def test_schema4_crisis_persists_atomically_and_overrides_high_morale_win(db):
    svc=GameService(db,ScriptedAdapter(default=make_accepted()),events_enabled=True);gid=svc.create_game(seed='crisis-integration')['game']['id']
    realm=initial_crisis();realm['pressures']['bankruptcy']=90;realm['notified']['bankruptcy']=[75,90]
    db._conn.execute('UPDATE games SET treasury=0,people=95,realm_json=? WHERE id=?',(json.dumps(realm),gid))
    response=svc.submit_turn(gid,'end',0,'不拨款，不发粮，不作新政',1)
    assert response['game']['status']=='lost' and response['game']['ending']['kind']=='bankruptcy'
    assert response['game']['accepted_turns']==1 and response['game']['people']>=80
    assert response['game']['events']['appraisal']['title']=='破产'
    assert not response['game']['events']['pending'] and not response['result']['new_echoes']
    assert 'pressures' not in response['game']['realm']
    assert svc.get_game_detail(gid)['game']==response['game']
    assert svc.submit_turn(gid,'end',0,'不拨款，不发粮，不作新政',1)==response
    with pytest.raises(ServiceError):svc.submit_turn(gid,'later',1,'兴学',2)

def test_existing_schema4_activates_forward_only_and_narration_failure_rolls_back(db):
    svc=GameService(db,ScriptedAdapter(default=make_accepted()),events_enabled=True);gid=svc.create_game(seed='forward')['game']['id']
    svc.submit_turn(gid,'first',0,'修渠',1)
    db._conn.execute('UPDATE games SET realm_json=? WHERE id=?',(json.dumps({'version':2}),gid))
    history=db.get_history(gid)
    class Broken(ScriptedAdapter):
        def narrate(self,*a):raise ModelOutputInvalid('injected')
    svc.adapter=Broken(default=make_accepted());before=db.get_game(gid)
    with pytest.raises(ServiceError):svc.submit_turn(gid,'bad',1,'修渠',2)
    assert db.get_game(gid)==before and db.get_history(gid)==history
    svc.adapter=ScriptedAdapter(default=make_accepted())
    result=svc.submit_turn(gid,'good',1,'修渠',2)
    assert result['game']['realm']['activated_turn']==2 and db.get_history(gid)[0]==history[0]

def test_same_round_negotiation_does_not_accumulate_crisis(db):
    from test_treaties import start
    svc,adapter,first=start(db);gid=first['game']['id'];before=db.get_game(gid)['realm_json']
    for rev in range(1,4):svc.negotiate(gid,'talk'+str(rev),rev,'counter','减少赔款')
    assert db.get_game(gid)['realm_json']==before

def test_blocked_narration_does_not_confuse_decree_issued_with_relief_completed():
    from app.domain.narration import narration_errors
    from app.llm.schema import candidate_to_dict
    from test_roles_and_tradeoffs import role_texts
    data=candidate_to_dict(make_accepted(advisor='陛下，诏令已颁，然财力不足，赈济尚未落实。',
        summary='财力不足，救济未能落实。',reactions=role_texts()))
    errors=narration_errors(data,{'intent':{'category':'other'},'blocked':True})
    assert not any('不得声称本次发粮' in e for e in errors)
