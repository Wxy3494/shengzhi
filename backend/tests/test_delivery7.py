import pytest
from app.domain.narration import unapproved_burden_claims
from app.domain import events
from app.domain.order_plan import plan_order
from app.domain import war
from app.services.game_service import GameService
from conftest import ScriptedAdapter,make_accepted

@pytest.mark.parametrize('text',[
 '未向商民乡里另加军需摊派，民间免增一层负担。',
 '未向商民乡里加派军需，民间免增一层负担。',
 '没有要求商贾代垫军饷。','无需民间另行代垫。','不曾向地方加派钱粮。',
 '未加派钱粮。','若国库不继，可能向地方加派。','禁止向地方加派。',
])
def test_denial_or_conditional_burden_is_not_fabricated_cost(text):
    assert not unapproved_burden_claims('减少军费开支',{'benefits':[text],'costs':[]})

@pytest.mark.parametrize('text',[
 '地方加派军需，百姓负担加重。','商贾代垫了军饷。',
 '未向商民加派军需，但商贾代垫军饷。','可能节省军费，地方已加派钱粮。',
 '并非未向商民加派军需。','不是没有要求商贾代垫。',
])
def test_real_new_burden_is_still_rejected(text):
    assert unapproved_burden_claims('减少军费开支',{'benefits':[],'costs':[text]})

@pytest.mark.parametrize('policy',['不加派军需','不得向百姓加派军需','不向百姓加派军需'])
def test_protection_is_not_permission_to_add_a_levy(policy):
    assert unapproved_burden_claims(policy,{'costs':['向百姓加派军需。']})

def test_explicit_levy_authorization_still_allows_levy_narrative():
    assert not unapproved_burden_claims('向百姓加派军需',{'costs':['地方加派军需。']})

@pytest.mark.parametrize('text',['减少军费开支','削减军费','压减军需开支','军费开支减少'])
def test_military_saving_is_finance_without_a_new_battle(text):
    intent=events.validated_intent(text,{})
    assert intent['category']=='finance' and not war.is_combat(text,intent)
    plan=plan_order(text,{},dict(people=53,treasury=6,grain=29))
    assert plan['intent']['category']=='finance' and plan['effect']['treasury']>0

@pytest.mark.parametrize('text',['不减少军费开支','不削减军费','禁止削减军费'])
def test_no_cut_is_not_a_finance_cut(text):
    assert events.validated_intent(text,{})['category']=='inaction'

def test_cut_military_spending_commits_once_on_low_treasury(db):
    svc=GameService(db,ScriptedAdapter(default=make_accepted()),events_enabled=True)
    gid=svc.create_game(seed='delivery7-cut')['game']['id']
    db._conn.execute('UPDATE games SET people=53,treasury=6,grain=29 WHERE id=?',(gid,))
    result=svc.submit_turn(gid,'cut',0,'减少军费开支',1)
    assert result['kind']=='accepted'
    assert result['result']['policy_intent']['category']=='finance'
    assert result['result']['execution']['actual_policy_effect']['treasury']>0
    assert svc.submit_turn(gid,'cut',0,'减少军费开支',1)==result
