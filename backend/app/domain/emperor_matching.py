"""Evidence-based candidate guidance; the model still selects the historical figure."""
from collections import Counter
import re
from .emperors import EMPERORS
from .policy_actions import operative_text,action_categories

MATCHING_VERSION=2
COMPATIBILITY_RATIO=0.45
COMPARISON_SIZE=2

PROFILES={
 'qin_shihuang':{'central':4,'construction':3,'coercion':3},
 'han_wendi':{'care':3,'frugal':4,'pardon':2},
 'han_wudi':{'war':4,'central':2,'finance':2},
 'sui_yangdi':{'construction':4,'coercion':4,'war':2,'distress':2},
 'tang_taizong':{'consult':4,'care':2,'defense':2,'education':2},
 'song_shenzong':{'reform':4,'finance':4,'defense':2},
 'ming_hongwu':{'discipline':4,'central':3,'coercion':2,'recovery':2},
 'ming_yongle':{'construction':3,'war':3,'culture':4},
 'qing_kangxi':{'water':4,'defense':3,'care':2,'recovery':2},
 'qing_yongzheng':{'finance':4,'discipline':3,'reform':3},
 'qing_qianlong':{'culture':4,'construction':2,'central':2,'war':1},
 'han_guangwu':{'recovery':4,'care':2,'pardon':2,'discipline':1},
 'wu_zetian':{'inclusion':8,'education':3,'reform':3,'central':1},
 'song_renzong':{'education':4,'consult':4,'pardon':2,'care':1},
 'yuan_shizu':{'trade':3,'war':3,'central':3,'road':2},
 'ming_hongxi':{'pardon':4,'frugal':4,'peace':3,'care':2},
 'ming_xuande':{'peace':5,'care':2,'consult':2,'defense':2},
 'ming_hongzhi':{'discipline':3,'consult':3,'finance':2,'care':2},
 'ming_jiajing':{'ritual':7,'central':3,'coercion':2},
 'ming_longqing':{'trade':5,'peace':5,'reform':2},
 'ming_chongzhen':{'distress':5,'discipline':3,'defense':2,'finance':1},
 'qing_shunzhi':{'institution':5,'inclusion':2,'central':2,'education':2},
 'qing_jiaqing':{'discipline':4,'frugal':3,'distress':2},
 'qing_daoguang':{'distress':4,'frugal':4,'peace':2},
}

def matching_candidates(detail):
    features=Counter();evidence=[]
    for row in detail.get('history',[]):
        intent=row.get('policy_intent') or {}
        if intent.get('category')=='inaction' or intent.get('action') in ('revoke','suspend'):continue
        text=operative_text(row.get('raw_text',''))
        if not text:continue
        categories=set(action_categories(row.get('raw_text','')))
        mapping={'relief':'care','water':'water','dike':'water','rest':'care','reform':'reform',
                 'education':'education','trade':'trade','justice':'discipline','oversight':'discipline',
                 'administration':'institution','defense':'defense','finance':'finance','road':'road','repression':'coercion','coercive':'coercion'}
        traits={mapping[c] for c in categories if c in mapping}
        if 'tax' in categories:
            from .policies import identify
            magnitude=intent.get('magnitude') or identify(text).get('magnitude')
            traits.add('care' if magnitude in ('moderate','half','full') else 'finance')
        patterns={'war':r'出兵|征伐|远征|攻打|亲征|反击|进兵|北伐|征战',
          'defense':r'边防|军备|守边|防御|军饷|守城', 'pardon':r'大赦|赦免|宽刑',
          'frugal':r'节俭|节用|裁减宫|削减宫|停建宫|停止营建|轻徭薄赋',
          'peace':r'议和|休兵|撤军|互市|停止战争|停战|休战',
          'consult':r'纳谏|进谏|听取|谏官|广开言路|咨议',
          'inclusion':r'(?:女子|女性|妇女|寒门).{0,12}(?:为官|入仕|科举|取士|任官|选官)|不拘.{0,5}(?:出身|门第)',
          'culture':r'修书|编书|典籍|文献|书院|藏书|大典',
          'institution':r'行政制度|官制|吸纳汉官|选用汉官|调整统治机构',
          'central':r'集权|中央|郡县|统一法|废丞相|皇权',
          'construction':r'运河|宫殿|宫室|行宫|大兴土木',
          'ritual':r'礼制|祭祀|宗庙|修道|道教|大礼',
          'finance':r'税制|盐法|财政|税额|税收|国库|清丈|摊丁|耗羡'}
        traits|={k for k,p in patterns.items() if re.search(p,text)}
        if 'water' in traits:traits.add('care')
        features.update(traits);evidence.append({'turn':row['turn_no'],'traits':sorted(traits)})
    game=detail['game'];initial=(game.get('opening') or {}).get('initial') or {}
    if initial and game.get('people',0)-initial.get('people',0)>=15 and game.get('grain',0)>=initial.get('grain',0):features['recovery']+=2
    if sum(game.get(k,50)<25 for k in ('people','treasury','grain'))>=2:features['distress']+=2
    if (game.get('ending') or {}).get('kind')=='conquest':features['distress']+=2
    peace=sum(r.get('action')=='accept' and (r.get('proposal') or {}).get('status')=='accepted' for r in (game.get('diplomacy') or {}).get('records',[]))
    features['peace']+=min(peace,2)
    ranked=[]
    for emperor in EMPERORS:
        profile=PROFILES[emperor['id']]
        score=sum(min(features[k],4)*weight for k,weight in profile.items())
        ranked.append({'id':emperor['id'],'score':score,'themes':emperor['themes']})
    ranked.sort(key=lambda r:(-r['score'],r['id']))
    seed=detail.get('matching_seed')
    if seed is None:
        # Compatibility for legacy/tool callers without a saved random seed.
        shortlist=ranked[:5] if ranked[0]['score'] else ranked
        return {'version':MATCHING_VERSION,'features':dict(features),'evidence':evidence,'candidates':shortlist,
                'selection':{'mode':'legacy_ranking'}}
    best=ranked[0]['score']
    pool=[{**r,'weight':round(1+(r['score']/best)**1.5,6) if best else 1.0}
          for r in ranked if not best or r['score']>=best*COMPATIBILITY_RATIO]
    from .events import rng
    lane=f'emperor_matching:v{MATCHING_VERSION}'
    random=rng(str(seed),lane)
    remaining=sorted(pool,key=lambda r:r['id']);shortlist=[];draws=[]
    for _ in range(min(COMPARISON_SIZE,len(remaining))):
        total=sum(r['weight'] for r in remaining);roll=random.random()*total;cursor=0
        for index,row in enumerate(remaining):
            cursor+=row['weight']
            if roll<cursor:break
        chosen=remaining.pop(index);shortlist.append({k:v for k,v in chosen.items() if k!='weight'})
        draws.append({'roll':roll,'total_weight':total,'chosen':chosen['id']})
    return {'version':MATCHING_VERSION,'features':dict(features),'evidence':evidence,'candidates':shortlist,
            'selection':{'mode':'seeded_compatible_pool','seed':str(seed),'lane':lane,
                'compatibility_ratio':COMPATIBILITY_RATIO,'pool':pool,'draws':draws}}


def model_comparison(matching):
    """Send comparable styles, keeping selection rolls and score ordering in audit."""
    return {'version':matching['version'],'features':matching['features'],'evidence':matching['evidence'],
            'candidates':[{k:r[k] for k in ('id','themes')} for r in matching['candidates']]}
