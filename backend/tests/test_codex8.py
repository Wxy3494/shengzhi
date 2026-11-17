import copy,json
from collections import Counter
import pytest
from app.domain.emperor_matching import matching_candidates,model_comparison
from app.domain.emperors import EMPEROR_BY_ID
from app.llm.emperor_review import generate_emperor_review
from test_codex_and_negotiation import detail_for

def seeded(texts,seed='codex8'):
    detail=detail_for(texts);detail['matching_seed']=seed
    return detail

def test_same_seed_is_stable_and_does_not_mutate_evidence():
    detail=seeded(['休养生息']*8);before=copy.deepcopy(detail)
    assert matching_candidates(detail)==matching_candidates(detail)
    assert detail==before

def test_similar_routes_have_more_than_one_emperor_without_unrelated_candidates():
    inclusion=Counter()
    for n in range(300):
        matching=matching_candidates(seeded(['休养生息']*8,str(n)))
        assert len(matching['candidates'])==2
        assert len({e['id'] for e in matching['candidates']})==2
        best=max(e['score'] for e in matching['selection']['pool'])
        assert all(e['score']>=best*.45 for e in matching['candidates'])
        inclusion.update(e['id'] for e in matching['candidates'])
    assert len(inclusion)>=5
    assert max(inclusion.values())<210 # no one available in >=70% of this seeded sample
    assert 'sui_yangdi' not in inclusion and 'han_wudi' not in inclusion

@pytest.mark.parametrize('texts',[
 ['允许女子为官']*4,['开放互市，议和通商']*4,['削减军费开支','轻徭薄赋','大赦天下'],
 ['兴学育才','严明科举','广开言路'],['攻打敌国']*4,['不作新政']*8,
])
def test_draws_are_auditable_and_candidates_stay_in_compatible_pool(texts):
    matching=matching_candidates(seeded(texts))
    pool={r['id'] for r in matching['selection']['pool']}
    assert {r['id'] for r in matching['candidates']}<=pool
    for draw in matching['selection']['draws']:
        assert 0<=draw['roll']<draw['total_weight'] and draw['chosen'] in pool
    assert len(matching['candidates'])==min(2,len(pool))

def test_tax_relief_and_tax_increase_have_different_style_features():
    assert matching_candidates(seeded(['减轻田赋']))['features']['care']==1
    increased=matching_candidates(seeded(['提高田赋']))['features']
    assert increased.get('care',0)==0 and increased['finance']==1

def test_model_cannot_read_random_rolls_seed_or_score_ordering():
    view=model_comparison(matching_candidates(seeded(['休养生息']*8)))
    assert set(view)=={'version','features','evidence','candidates'}
    assert all(set(e)=={'id','themes'} for e in view['candidates'])

def test_no_saved_seed_keeps_legacy_candidate_path():
    assert matching_candidates(detail_for(['休养生息']))['selection']['mode']=='legacy_ranking'

def test_profile_list_order_does_not_bias_draw(monkeypatch):
    import app.domain.emperor_matching as m
    detail=seeded(['休养生息']*8);before=m.matching_candidates(detail)
    monkeypatch.setattr(m,'EMPERORS',list(reversed(m.EMPERORS)))
    assert before==m.matching_candidates(detail)

def test_provider_must_use_seeded_candidates_and_biography_only(db):
    from app.services.game_service import GameService
    from conftest import ScriptedAdapter,make_accepted,set_state
    svc=GameService(db,ScriptedAdapter(default=make_accepted()),events_enabled=True)
    gid=svc.create_game(seed='codex8-review')['game']['id']
    for turn in range(1,9):svc.submit_turn(gid,'setup-'+str(turn),turn-1,'休养生息',turn)
    detail=svc.get_game_detail(gid);detail['matching_seed']='codex8-review'
    matching=matching_candidates(detail);chosen=EMPEROR_BY_ID[matching['candidates'][0]['id']]
    biography=chosen['name']+'是'+chosen['dynasty']+'皇帝，'+chosen['era']+'。'+''.join(chosen['facts'])
    wrong=next(i for i in EMPEROR_BY_ID if i not in {r['id'] for r in matching['candidates']})
    class Provider:
        timeout=20
        def __init__(self):self.calls=[]
        def _call(self,messages,*args):
            self.calls.append(copy.deepcopy(messages))
            return json.dumps({'emperor_id':wrong if len(self.calls)==1 else chosen['id'],'biography':biography},ensure_ascii=False)
    provider=Provider();review=generate_emperor_review(provider,detail)
    assert review.emperor_id==chosen['id'] and len(provider.calls)==2
    payload=json.loads(provider.calls[0][1]['content'])
    assert 'selection' not in payload['style_comparison']

def test_matching_audit_is_cached_with_portrait_without_reroll(db):
    from app.services.game_service import GameService
    from test_emperor import Historian
    from conftest import set_state
    svc=GameService(db,Historian(),events_enabled=True)
    gid=svc.create_game(seed='codex8-cache')['game']['id']
    for turn in range(1,9):svc.submit_turn(gid,'setup-'+str(turn),turn-1,'休养生息',turn)
    result=svc.generate_emperor_review(gid)
    assert result['matching_audit']['selection']['seed']=='codex8-cache'
    assert svc.generate_emperor_review(gid)==result and svc.adapter.reviews==1
