import json
import pytest
from app.domain import treaties,events
from app.domain.emperors import EMPERORS,EMPEROR_BY_ID
from app.domain.emperor_matching import matching_candidates
from app.domain.policy_tradeoffs import considerations,retain_analysis
from app.llm.live import LiveAdapter
from app.llm.base import ModelContext
from app.llm.schema import candidate_to_dict
from conftest import make_accepted
from test_treaties import start

@pytest.mark.parametrize('decision,offered,expected',[('accepted',12,'accepted'),('accepted',8,'counter'),('counter',8,'counter'),('rejected',8,'rejected')])
def test_counter_reply_distinguishes_agreement_from_lower_terms(db,decision,offered,expected):
    svc,adapter,first=start(db,outcome='victory');gid=first['game']['id'];previous=first['game']['diplomacy']['pending']
    adapter.propose_treaty=lambda *a:{'decision':decision,'cities':1,'treasury':offered,'grain':4,'reason':'对方按本次要求表态。'}
    result=svc.negotiate(gid,'counter-explicit',1,'counter','要求国库12，其他照旧')
    reply=result['session']['reply']
    assert reply['decision']==expected and reply['previous_terms']['treasury']==5
    assert reply['requested_terms']=={'cities':1,'treasury':12,'grain':4}
    assert result['session']['state_diff']==dict.fromkeys(events.DIMS,0)
    assert result['game']['accepted_turns']==1
    if decision=='rejected':assert result['game']['diplomacy']['pending']==previous
    else:assert result['game']['diplomacy']['pending']['terms']['treasury']==offered
    assert svc.negotiate(gid,'counter-explicit',1,'counter','要求国库12，其他照旧')==result

def test_numeral_terms_preserve_omitted_fields():
    assert treaties.requested_terms('国库改为二十，粮草六',{'cities':2,'treasury':10,'grain':4})=={'cities':2,'treasury':20,'grain':6}
    assert treaties.requested_terms('不割城，赔款3',{'cities':2,'treasury':10,'grain':4})=={'cities':0,'treasury':3,'grain':4}

def detail_for(texts):
    return {'game':{'schema_version':4,'people':70,'treasury':55,'grain':55,'opening':{'initial':dict(people=50,treasury=60,grain=60)}},
            'history':[{'turn_no':i+1,'raw_text':t} for i,t in enumerate(texts)]}

def test_catalog_expanded_and_all_have_profiles_and_sources():
    from app.domain.emperor_matching import PROFILES
    assert len(EMPERORS)==len(EMPEROR_BY_ID)==24
    assert set(PROFILES)==set(EMPEROR_BY_ID)
    assert all(e['facts'] and e['sources'] and e['themes'] for e in EMPERORS)

@pytest.mark.parametrize('texts,expected',[
    (['允许女子为官，考试择优录用']*3,'wu_zetian'),
    (['开放边境互市，议和通商']*3,'ming_longqing'),
    (['兴学育才','严明科举','广开言路，听取进谏'],'song_renzong'),
    (['大赦天下','休养生息','节俭用度，停止营建宫殿'],'ming_hongxi'),
    (['整顿税制财政','推行改革','清查贪污'],'qing_yongzheng'),
])
def test_specialized_routes_make_alternative_emperors_reachable(texts,expected):
    matching=matching_candidates(detail_for(texts))
    assert expected in [r['id'] for r in matching['candidates']]
    assert matching==matching_candidates(detail_for(texts))

def test_negated_inclusion_is_not_reform():
    assert events.validated_intent('允许女子为官',{})['category']=='reform'
    assert events.validated_intent('不得允许女子为官',{})['category']=='inaction'

def test_inactive_policy_does_not_get_emperor_style_credit():
    detail=detail_for(['允许女子为官']);detail['history'][0]['policy_intent']={'category':'inaction'}
    assert matching_candidates(detail)['features'].get('inclusion',0)==0

def test_amnesty_and_women_have_conditional_risks_without_forcing_bad_outcome():
    all_pardon=considerations('大赦天下',{'category':'justice'})
    limited=considerations('仅赦轻罪，重犯不赦',{'category':'justice'})
    assert all_pardon['conditional_risks'][0]['likelihood']=='medium'
    assert limited['conditional_risks'][0]['likelihood']=='low'
    female=considerations('允许女子为官',{'category':'reform'})
    result=retain_analysis({'benefits':['扩大人才来源'],'costs':[],'risks':[],'effect_basis':'试行取士。'},female)
    assert '礼法' in result['risks'][0]['condition'] and '可能' in result['risks'][0]['consequence']
    assert not retain_analysis({'risks':[]},female,True)['risks']

def test_event_narration_retains_substantive_analysis_instead_of_only_resource_lines():
    adapter=LiveAdapter('unused','unused','test')
    analysis={'benefits':['轻罪者归家谋生'],'costs':['核查罪籍需要支出'],
              'risks':[{'condition':'若重犯一并获释且无人安置','consequence':'可能再犯并扰乱治安','likelihood':'medium','horizon':'delayed'}],
              'effect_basis':'赦免与核办各有得失。'}
    raw={'advisor':'陛下，赦令已行，臣已核办，若重犯缺乏安置，恐扰治安。','summary':'赦令已颁，民心有所改善，核办耗费库款。',
         'tian_bo':'家人得归自是好事。','song_zhiyuan':'愿行旅仍得安稳。','gu_tingzhang':'地方须兼顾受害者的公道。','tradeoff':'赦令使家人团聚，也须支用核办费用。','policy_analysis':analysis}
    adapter._call=lambda *a:json.dumps(raw,ensure_ascii=False)
    data=candidate_to_dict(make_accepted(policy_effect={'people':2,'treasury':-2,'grain':0}))
    context=ModelContext(game={'schema_version':4},turn_no=1,period='承和元年至三年',player_policy='大赦天下')
    facts={'intent':events.validated_intent('大赦天下',{}),'blocked':False,'before':dict(people=50,treasury=60,grain=60),
           'after':dict(people=52,treasury=58,grain=60),'actual_policy_effect':data['policy_effect'],'actual_echo_effects':[],
           'event_report':None,'constraint_notes':[],'history':[]}
    output=adapter.narrate(context,data,facts)
    assert output['policy_analysis']['benefits']==analysis['benefits']
    assert output['policy_analysis']['risks']==analysis['risks']
    assert output['policy_effect']==data['policy_effect']
