import json
import pytest
from pydantic import ValidationError
from app.domain import events,treaties
from app.domain.crisis_v3 import initial_crisis,advance_crisis,public_crisis
from app.domain.models import GameState
from app.domain.narration import narration_errors
from app.llm.schema import candidate_to_dict
from app.llm.base import ModelOutputInvalid
from app.services.game_service import GameService,ServiceError
from conftest import ScriptedAdapter,make_accepted
from test_treaties import start
from test_roles_and_tradeoffs import role_texts

@pytest.mark.parametrize('text',['不准议和','不得与敌国议和','禁止谈判','绝不求和','不许和谈','不准议和，继续战争'])
def test_explicit_refusal_reaches_immediate_enemy_attack(db,text):
    svc,adapter,first=start(db);gid=first['game']['id'];calls=len(adapter.offers)
    result=svc.submit_turn(gid,'refusal',1,text,2)
    assert result['session']['action']=='reject'
    assert result['session']['battle']['attack_reason']=='refused_negotiation'
    assert len(adapter.offers)==calls and result['game']['accepted_turns']==1
    assert result['remaining_policy']==''

@pytest.mark.parametrize('text,category',[
 ('鼓励通商，并降低商税','trade'),('开放互市，商税减半','trade'),('降低商税以鼓励通商','tax'),
 ('凡议论朝政者依法治罪','repression'),('非议朝政者皆以诽谤罪论处','repression'),
 ('不得将批评朝廷者治罪','inaction')])
def test_main_goal_and_speech_prohibition(text,category):
    assert events.validated_intent(text,{})['category']==category

@pytest.mark.parametrize('line',['洪灾已获缓解，朝廷已发粮赈济。','灾民已得到安置。','朝廷已赈济灾民，若再遇洪水仍须留意。'])
def test_tax_response_cannot_fabricate_relief(line):
    data=candidate_to_dict(make_accepted(advisor=line,reactions=role_texts()))
    errors=narration_errors(data,{'intent':{'category':'tax'},'original_goal':'减轻灾区田赋'})
    assert any('未授权发粮或安置' in e for e in errors)

@pytest.mark.parametrize('reason',['赔粮六石','粮草10石','赔银三十贯'])
def test_treaty_index_cannot_gain_physical_units(reason):
    with pytest.raises(ValidationError):treaties.Terms(cities=1,treasury=5,grain=6,reason=reason)

def test_crisis_trends_are_qualitative_and_do_not_change_threshold_behavior():
    realm=initial_crisis()
    bad=advance_crisis(realm,GameState(people=50,treasury=0,grain=60),{'category':'other'},'施政',False,[],1)
    entry=next(t for t in public_crisis(bad)['trends'] if t['id']=='bankruptcy')
    assert entry['trend']=='worsening' and not bad['warnings']
    better=advance_crisis(bad,GameState(people=50,treasury=60,grain=60),{'category':'other'},'施政',False,[],2)
    assert next(t for t in better['trends'] if t['id']=='bankruptcy')['trend']=='easing'
    assert 'pressures' not in public_crisis(better)
    assert not any(type(v) is int for t in public_crisis(better)['trends'] for v in t.values())

def test_retry_reuses_only_validated_intent_without_committing_partial_state(db):
    class Cached(ScriptedAdapter):
        retry_cache_safe=True
        def narrate(self,context,data,facts):raise ModelOutputInvalid('injected')
    adapter=Cached(default=make_accepted());svc=GameService(db,adapter,events_enabled=True)
    gid=svc.create_game(seed='retry-cache')['game']['id'];before=db.get_game(gid)
    for _ in range(2):
        with pytest.raises(ServiceError):svc.submit_turn(gid,'same',0,'修渠',1)
    assert len(adapter.calls)==1 and db.get_game(gid)==before and not db.get_history(gid)
    with pytest.raises(ServiceError):svc.submit_turn(gid,'different',0,'修渠',1)
    assert len(adapter.calls)==2
