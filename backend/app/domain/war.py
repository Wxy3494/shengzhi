"""Seeded decisive campaigns. Numbers never come from model narration."""
import copy
import json
import re
from pathlib import Path
from .events import rng, DIMS

RULES = json.loads((Path(__file__).with_name('event_data')/'war_rules_v1.json').read_text(encoding='utf8'))
PRESSURE=json.loads((Path(__file__).with_name('event_data')/'war_pressure_v3.json').read_text(encoding='utf8'))
if PRESSURE!={'version':3,'weak_below':20,'weak_dimensions':2,'attack_on_refusal':True}:
    raise ValueError('Invalid war pressure v3 configuration')
if not (RULES['version']==1
    and all(0<lo<=hi<=30 for lo,hi in RULES['cost'].values())
    and all(0<=lo<=hi<=30 for lo,hi in RULES['victory_returns'].values())
    and 0<=RULES['chance']['min']<RULES['chance']['max']<=100
    and all(RULES['chance'][key]>0 for key in DIMS)
    and 0<=RULES['cession_chance']<=100 and 0<=RULES['collapse']['chance']<=100):
    raise ValueError('Invalid war v1 configuration')

def is_combat(text, intent):
    from .policy_actions import operative_text,COMBAT_PATTERN
    return intent.get('action') not in ('revoke','suspend') and bool(re.search(
        COMBAT_PATTERN, operative_text(text)))

def weak(state):
    return sum(state[d]<PRESSURE['weak_below'] for d in DIMS)>=PRESSURE['weak_dimensions']

def active(engine):
    current=engine.get('war',{})
    return bool(current.get('records')) and current.get('active',True) and not current.get('ending')

def enemy_attack(engine,state,refused=False):
    if not active(engine):return None
    if refused:return 'refused_negotiation'
    if weak(state):return 'two_weak_dimensions'
    return None

def suspend_negotiation(engine,reason,state,turn):
    current=engine['war']
    proposal=current.get('pending_treaty')
    if proposal:
        current.setdefault('treaties',[]).append({**copy.deepcopy(proposal),'status':'withdrawn_by_enemy','decision_turn':turn,'reason':reason})
    current['pending_treaty']=None
    current['negotiation_suspended']={'version':3,'reason':reason,'state':dict(state),'turn':turn}

def chance(state):
    spec=RULES['chance']
    return round(max(spec['min'],min(spec['max'],spec['base']+sum(state[d]*spec[d] for d in DIMS))),2)

def resolve(previous, turn, state, preparation, attack_reason=None,random_key=None):
    engine=copy.deepcopy(previous)
    war=engine.setdefault('war',{'version':2,'records':[],'cities_lost':0,'ending':None})
    if war['version'] not in (1,2,3): raise ValueError('Unsupported war configuration')
    if war.get('pending_treaty'):
        war.setdefault('treaties',[]).append({**copy.deepcopy(war['pending_treaty']),'status':'superseded_by_combat','decision_turn':turn})
    war['version']=3;war['active']=True;war['pending_treaty']=None
    lane='war:v1' if random_key is None else 'war:v1:diplomacy:'+str(random_key)
    random=rng(engine['seed'],lane,turn)
    before=state.copy(); state=state.copy()
    costs={k:random.randint(*v) for k,v in RULES['cost'].items()}
    paid={k:min(state[k],v) for k,v in costs.items()}
    probability=chance(preparation)
    roll=random.random()*100
    victory=roll<probability
    requested={d:0 for d in DIMS}
    for k,v in paid.items(): state[k]-=v
    returned={k:0 for k in costs}; extra={k:0 for k in costs}
    ceded=False; collapsed=False; cession_roll=None; collapse_roll=None
    if victory:
        requested['people']=random.randint(*RULES['victory_people'])
        returned={k:random.randint(*v) for k,v in RULES['victory_returns'].items()}
        for k,v in returned.items(): state[k]=min(100,state[k]+v)
    else:
        requested['people']=random.randint(*RULES['defeat_people'])
        extra={k:min(state[k],random.randint(*v)) for k,v in RULES['defeat_extra'].items()}
        for k,v in extra.items(): state[k]-=v
        cession_roll=random.random()*100
        # A defeat may invite demands, but never authorizes ceding a city.
        ceded=False
        spec=RULES['collapse']
        vulnerable=min(preparation['treasury'],preparation['grain'])<spec['resource_below'] or war['cities_lost']>=spec['cessions_at_least']
        if vulnerable: collapse_roll=random.random()*100
        collapsed=vulnerable and collapse_roll<spec['chance']
    state['people']=max(0,min(100,state['people']+requested['people']))
    report={'version':1,'turn':turn,'outcome':'victory' if victory else 'defeat',
        'win_chance':probability,'roll':roll,'cession_roll':cession_roll,'collapse_roll':collapse_roll,'seed':engine['seed'],'lane':lane,'preparation':dict(preparation),
        'treaty_version':2,'pressure_version':3,'attack_reason':attack_reason,'planned_cost':costs,'paid_cost':paid,'returns':returned,'extra_loss':extra,
        'ceded_city':ceded,'cities_lost':war['cities_lost'],'collapsed':collapsed,
        'before':before,'after':state.copy(),'effects':{d:state[d]-before[d] for d in DIMS}}
    report['text']=('此役获胜，敌军退却；缴获与军需损耗已逐项结清。' if victory else
        '此役战败，军队败退，军需损失已结清。')
    if attack_reason:
        report['text']=('我方拒绝议和，敌军随即进攻。' if attack_reason=='refused_negotiation' else '我朝两项国力低于戒线，敌军放弃议和、直接进攻。')+report['text']
    if collapsed:
        report['text']+='朝廷已无力维持抵抗，敌军破都，本朝覆亡。'
        war['ending']={'kind':'conquest','title':'兵败国亡','text':report['text'],'status':'lost',
                       'turn_no':turn,'source_turns':[turn]}
    war['records'].append(report)
    return engine,state,report
