"""Versioned, seeded rules for schema-4 saves. No model output is state authority.

The disaster gate is seeded. Configuration v3 permits low grain to increase
drought/locust weights, as explicitly requested; all other disasters stay isolated.
"""
import copy
import hashlib
import json
import random
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .models import GameState
from .openings import SCENARIOS

DATA = Path(__file__).with_name('event_data')
CONFIG_VERSION = 3
DIMS = ('people', 'treasury', 'grain')
CLASSES = ('commoners', 'gentry', 'merchants', 'borderArmy')
TAGS = {'waterworks', 'relief_reserves', 'grain_procurement', 'tax_relief',
        'market_opening', 'trade_regulation', 'border_defense', 'diplomacy',
        'anti_corruption', 'consultation', 'heavy_trade_tax'}


class StrictConfig(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class Effects(StrictConfig):
    people: int = Field(ge=-10, le=10)
    treasury: int = Field(ge=-10, le=10)
    grain: int = Field(ge=-10, le=10)


class ResponseRule(StrictConfig):
    requires_any: list[str]
    result: Literal['well_handled', 'mitigated']
    effects: Effects
    cost: dict[str, int]

    @model_validator(mode='after')
    def whitelist(self):
        if not set(self.requires_any) <= TAGS or not set(self.cost) <= {'treasury', 'grain'} or any(v < 0 or v > 10 for v in self.cost.values()):
            raise ValueError('invalid response tags/costs')
        return self


class ResourceWeight(StrictConfig):
    resource: Literal['grain','treasury','people']
    below: int | None = Field(default=None,ge=0,le=100)
    above: int | None = Field(default=None,ge=0,le=100)
    multiplier: float = Field(gt=0,le=4)

    @model_validator(mode='after')
    def one_boundary(self):
        if (self.below is None) == (self.above is None):
            raise ValueError('exactly one resource boundary required')
        return self


class HistoryWeight(StrictConfig):
    tag: str
    present: float = Field(gt=0,le=4)
    absent: float = Field(default=1.0,gt=0,le=4)
    from_turn: int = Field(default=1,ge=1,le=8)

    @model_validator(mode='after')
    def whitelist(self):
        if self.tag not in TAGS: raise ValueError('invalid history tag')
        return self


class BenefitRule(StrictConfig):
    tag: str
    effects: Effects

    @model_validator(mode='after')
    def whitelist(self):
        if self.tag not in TAGS: raise ValueError('invalid benefit tag')
        return self


class EventDefinition(StrictConfig):
    id: str
    category: Literal['disaster', 'harvest', 'diplomacy', 'border', 'social', 'finance', 'commerce', 'works', 'governance', 'politics', 'quiet']
    polarity: Literal['negative', 'positive', 'opportunity', 'mixed', 'neutral']
    tier: Literal['small', 'medium', 'major']
    base_weight: int = Field(gt=0, le=100)
    turn_range: list[int] = Field(min_length=2, max_length=2)
    narrative_key: str
    immediate: Effects
    class_effects: dict[str, int]
    pending: bool
    unresolved: Effects
    response_rules: list[ResponseRule]
    protection: str | None
    season_multipliers: dict[str,float] = Field(default_factory=dict)
    resource_weight: ResourceWeight | None = None
    history_weights: list[HistoryWeight] = Field(default_factory=list)
    benefit_rules: list[BenefitRule] = Field(default_factory=list)

    @model_validator(mode='after')
    def invariants(self):
        if not 1 <= self.turn_range[0] <= self.turn_range[1] <= 8:
            raise ValueError('invalid event turns')
        if min(self.immediate.model_dump().values()) < -6:
            raise ValueError('instant impact too severe')
        if not set(self.class_effects) <= set(CLASSES) or any(abs(v) > 10 for v in self.class_effects.values()):
            raise ValueError('invalid class effects')
        if self.protection is not None and self.protection not in TAGS:
            raise ValueError('invalid protection')
        if self.pending and self.turn_range[1] >= 8:
            raise ValueError('must leave a response turn')
        if self.category=='disaster':
            if self.history_weights: raise ValueError('disaster probability must not read policy history')
            if self.resource_weight is not None and not (
                self.id in ('drought_local','locust_plague') and self.resource_weight.resource=='grain'
                and self.resource_weight.below==45 and self.resource_weight.above is None
                and 1<=self.resource_weight.multiplier<=1.8):
                raise ValueError('only low grain drought/locust modifier authorized')
        if not set(self.season_multipliers)<=set('0123') or any(v<=0 or v>4 for v in self.season_multipliers.values()):
            raise ValueError('invalid season-only weights')
        return self


def load_catalog(data=None):
    data = data or json.loads((DATA / 'events.json').read_text(encoding='utf8'))
    if data['version'] not in (2, CONFIG_VERSION) or set(data) != {'version', 'events'}:
        raise ValueError('unknown event schema')
    catalog = [EventDefinition.model_validate(e).model_dump() for e in data['events']]
    if len({e['id'] for e in catalog}) != len(catalog):
        raise ValueError('duplicate event id')
    return {e['id']: e for e in catalog}


CATALOG = load_catalog()
LEGACY_CATALOG = load_catalog(json.loads((DATA / 'archive/v2/events.json').read_text(encoding='utf8')))
TEXTS = json.loads((DATA / 'texts.json').read_text(encoding='utf8'))


def catalog_for(engine):
    return CATALOG if engine.get('config_version',2)>=3 else LEGACY_CATALOG


class PolicyCatalog(StrictConfig):
    version: Literal[3]
    effects: dict[str, Effects]
    tax: dict[str, list[int]]
    echo: Effects
    coercive: Effects
    pardon: Effects
    pardon_risk_echo: Effects
    inaction_echo: Effects
    harmful_echo: Effects

    @model_validator(mode='after')
    def valid_tax(self):
        if set(self.tax) != {'moderate','half','full','restore','unchanged','unspecified'}:
            raise ValueError('invalid tax directions')
        for value in self.tax.values():
            if len(value)!=3: raise ValueError('invalid tax effect')
            Effects.model_validate(dict(zip(DIMS,value)))
        return self


POLICIES = PolicyCatalog.model_validate_json((DATA / 'policy_rules.json').read_text(encoding='utf8')).model_dump()


def rng(seed, lane, turn=0):
    digest = hashlib.sha256(f'{seed}:{lane}:{turn}'.encode()).digest()
    return random.Random(int.from_bytes(digest, 'big'))


def seeded_opening(seed):
    # Existing briefing fields are reused; new snapshots never alter old saves.
    specs = [
        ('treasury_rich_food_low', '库盈仓薄', (50,64,46), 0),
        ('granary_rich_treasury_low', '仓盈库紧', (50,46,64), 3),
        ('people_weary_recovering', '家底待兴', (46,58,56), 4),
        ('balanced_cautious', '守成之局', (52,54,54), 5),
        ('frontier_strained', '边陲承压', (48,56,52), 2),
        ('commerce_rising', '市井初兴', (54,52,48), 1),
    ]
    id, name, values, old = specs[rng(seed, 'opening').randrange(6)]
    opening = copy.deepcopy(SCENARIOS[old])
    opening.update(id=id, name=name, initial=dict(zip(DIMS, values)), active_until_turn=0)
    return opening


def initial_events(seed, opening):
    count = rng(seed, 'count').randint(4,6)
    schedule = sorted([1, *rng(seed, 'schedule').sample(range(2,8), count-1)])
    return {'version':1, 'config_version':CONFIG_VERSION, 'seed':seed, 'initial_state':copy.deepcopy(opening['initial']),
            'schedule':schedule, 'class_support':dict.fromkeys(CLASSES,50),
            'records':[], 'pending':[], 'audit':[], 'policy_tags':[],
            'forewarnings':[], 'policy_history':[], 'appraisal':None}


def validated_intent(text, proposed):
    from .policies import identify
    from .policy_actions import operative_text, action_categories,primary_category
    operative=operative_text(text)
    categories=action_categories(text)
    intent=identify(operative)
    category=primary_category(text,categories)
    if category=='consultation': category='administration'
    intent['category']=category
    intent['project']='canal' if category=='water' else category
    if category=='tax':
        intent=identify(operative, intent)
    intent.setdefault('region','全境')
    return intent


def policy_tags(intent, text):
    from .policy_actions import action_categories, operative_text
    if intent.get('action') in ('revoke','suspend') or intent['category'] in ('inaction','repression','coercive'):
        return []
    categories=action_categories(text)
    mapping={'water':'waterworks','dike':'waterworks','relief':'relief_reserves',
        'grain_supply':'grain_procurement','trade':'market_opening','justice':'anti_corruption',
        'military':'border_defense','defense':'border_defense','diplomacy':'diplomacy','consultation':'consultation'}
    tags={mapping[c] for c in categories if c in mapping}
    if 'tax' in categories and intent.get('magnitude') in ('moderate','half','full'):tags.add('tax_relief')
    if re.search('平粜|平抑|规市|监管.{0,5}(?:市场|互市|商路)',operative_text(text)):tags.add('trade_regulation')
    if re.search(r'(?:加征|提高|加重|增收).{0,5}商税|商税.{0,5}(?:加倍|提高)',operative_text(text)):
        tags.add('heavy_trade_tax')
    return sorted(tags)


def policy_effect(intent, text):
    if intent.get('action') in ('revoke','suspend'):
        return dict.fromkeys(DIMS,0)
    category = intent['category']
    if category=='coercive':
        return copy.deepcopy(POLICIES['coercive'])
    if category=='tax':
        values=POLICIES['tax'].get(intent.get('magnitude'),POLICIES['tax']['unspecified'])
        return dict(zip(DIMS, values))
    result=copy.deepcopy(POLICIES['effects'].get(category,POLICIES['effects']['other']))
    from .policy_actions import operative_text
    if re.search('大赦|赦免|赦轻罪|赦罪',operative_text(text)):
        result=copy.deepcopy(POLICIES['pardon'])
    return result


def echo_effect(source):
    raw=source.get('raw_text','')
    intent=validated_intent(raw,{})
    if intent['category'] in ('inaction','repression','coercive'):
        return copy.deepcopy(POLICIES['inaction_echo'] if intent['category']=='inaction' else POLICIES['harmful_echo'])
    if '大赦' in raw and not re.search('排除重犯|不赦重犯|重犯不赦|仅赦轻罪',raw):
        return copy.deepcopy(POLICIES['pardon_risk_echo'])
    return copy.deepcopy(POLICIES['echo'])


def policy_echoes(intent, blocked, turn):
    return [] if blocked or turn>=8 or intent.get('action') in ('revoke','suspend') or intent.get('category') in ('inaction','repression','coercive') else [
        {'delay':1,'reason':'查考本次实际施政的一次后效，不追加拨付。','effect_kind':'consequence'}]


def _apply(state, effects, source, diffs, event=False):
    before=state.copy()
    requested={k:effects.get(k,0) for k in DIMS}
    bounded={k:max(1 if event and before[k]>0 else 0,min(100,before[k]+requested[k])) for k in DIMS}
    applied={k:bounded[k]-before[k] for k in DIMS}
    state.update(bounded)
    diffs.append({'source':source,'requested':requested,'applied':applied,'before':before,'after':bounded.copy()})
    if applied!=requested:
        diffs.append({'source':'clamp','parent':source,'difference':{k:applied[k]-requested[k] for k in DIMS}})
    return applied


def _weights(engine, turn, lane, polarity, state):
    records=engine['records']; seen={r['event_id'] for r in records}
    previous=next((r for r in reversed(records) if r['announced_turn']==turn-1),None)
    candidates=[]
    major_turns=[t for t in engine['schedule'][1::2] if 3<=t<=6]
    major_turn=rng(engine['seed'],'major_turn').choice(major_turns) if major_turns else None
    major_lane=rng(engine['seed'],'major_lane').choice(['disaster','border'])
    active_tags={t['tag'] for t in engine['policy_tags'] if t['expires_after_turn']>=turn}
    for id,e in catalog_for(engine).items():
        reasons=[]; weight=float(e['base_weight'])
        if id=='peaceful_season': reasons.append('quiet_only')
        if id in seen: reasons.append('already_seen')
        if not e['turn_range'][0]<=turn<=e['turn_range'][1]: reasons.append('turn_range')
        if turn==1 and e['tier']!='small': reasons.append('first_small_only')
        if (e['category']=='disaster') != (lane=='disaster'): reasons.append('isolated_lane')
        if e['polarity'] not in polarity: reasons.append('polarity_pacing')
        if previous and previous['category']==e['category']: reasons.append('category_cooldown')
        if previous and previous['polarity']=='negative' and e['polarity']=='negative': reasons.append('negative_guard')
        if e['tier']=='major':
            if turn!=major_turn or e['category']!=major_lane: reasons.append('reserved_major_slot')
            if not 3<=turn<=6 or any(r['tier']=='major' for r in records): reasons.append('major_limit')
            if id=='earthquake_damage' and not any(w['turn']<turn for w in engine['forewarnings']): reasons.append('no_prior_watch')
            if id=='foreign_incursion' and 'border_raids' not in seen: reasons.append('no_border_warning')
        modifiers=[]
        if e['category']=='disaster':
            weight*=e['season_multipliers'].get(str(turn%4),1.0)
        modifier=e['resource_weight']
        if modifier and ((modifier['below'] is not None and state[modifier['resource']]<modifier['below']) or
                         (modifier['above'] is not None and state[modifier['resource']]>modifier['above'])):
            weight*=modifier['multiplier'];modifiers.append('resource:'+modifier['resource'])
        for history in e['history_weights']:
            if turn>=history['from_turn']:
                factor=history['present'] if history['tag'] in active_tags else history['absent']
                weight*=factor
                if factor!=1: modifiers.append('history:'+history['tag'])
        if e['category']!='disaster':
            if id=='refugee_pressure' and not (state['people']<45 or any(r['category']=='disaster' and r['outcome']!='well_handled' for r in records)): reasons.append('no_social_cause')
            if id=='banditry_rises' and state['people']>=45: reasons.append('no_social_cause')
            if id=='trade_envoy' and engine['class_support']['merchants']<45: reasons.append('merchant_support')
            if id=='craft_boom' and engine['class_support']['merchants']<55: reasons.append('merchant_support')
        candidates.append({'event_id':id,'weight':0 if reasons else round(weight,4),'filters':reasons,'modifiers':modifiers})
    return candidates


def disaster_gate(engine, turn, state):
    candidates=_weights(engine,turn,'disaster',{'negative'},state)
    if engine.get('config_version',2)<3:
        return 0.55,candidates
    reference=_weights(engine,turn,'disaster',{'negative'},{**state,'grain':45})
    base=sum(c['weight'] for c in reference)
    total=sum(c['weight'] for c in candidates)
    # Compensate the lane gate: a drought/locust boost must not lower the
    # marginal draw probability of flood/earthquake at the same history.
    probability=0.55*total/base if base else 0.55
    return probability,candidates


def select_event(engine, turn, state):
    planned=turn in engine['schedule']
    index=engine['schedule'].index(turn) if planned else -1
    # First event is positive; alternate crises with breathing space/opportunities.
    negative=index%2==1
    gate_probability,disaster_candidates=disaster_gate(engine,turn,state) if planned and negative else (0.0,[])
    gate_roll=rng(engine['seed'],'disaster_gate',turn).random()
    disaster=negative and gate_roll<gate_probability
    lane='disaster' if disaster else 'other'
    polarity={'negative'} if negative else {'positive','opportunity','mixed'}
    if index==0: polarity={'positive'}
    elif not negative and engine.get('config_version',2)>=3:
        # With 4/5/6 slots, keep one good opening and about one quarter opportunities.
        opportunity=index==2 or rng(engine['seed'],'opportunity_slot',turn).random()<0.5
        polarity={'opportunity','mixed'} if opportunity else {'positive'}
    candidates=(disaster_candidates if disaster else _weights(engine,turn,lane,polarity,state)) if planned else []
    total=sum(c['weight'] for c in candidates)
    roll=rng(engine['seed'],'selection',turn).random()*total
    chosen='peaceful_season'
    if planned and total:
        remaining=roll
        for candidate in candidates:
            remaining-=candidate['weight']
            if candidate['weight'] and remaining<0:
                chosen=candidate['event_id'];break
    engine['audit'].append({'turn':turn,'seed':engine['seed'],'config_version':engine.get('config_version',2),'scheduled':planned,
        'lane':lane,'roll':roll,'candidates':candidates,'chosen':chosen,
        'disaster_gate_probability':gate_probability,'disaster_gate_roll':gate_roll,
        'reason':'seeded slot and isolated disaster lane' if planned else 'quiet: schedule/final boundary',
        'positive_or_quiet_weight_share':1.0 if not negative else 0.0})
    return catalog_for(engine)[chosen]


def _public_record(record):
    text=TEXTS[record['event_id']]
    return {**copy.deepcopy(record),'name':text['name'],'announcement':text['announcement'],
            'response_hint':text['response_hint']}


def _benefits(event, effects, active_tags):
    adjusted=effects.copy()
    for rule in event['benefit_rules']:
        if rule['tag'] in active_tags:
            adjusted={k:max(-10,min(10,adjusted[k]+rule['effects'][k])) for k in DIMS}
    return adjusted


def advance_events(previous, turn, after_policy, intent, text, blocked=False):
    engine=copy.deepcopy(previous); state=dict(after_policy); diffs=[]; updates=[]
    tags=[] if blocked else policy_tags(intent,text)
    engine['policy_history'].append({'turn':turn,'intent':copy.deepcopy(intent),'tags':tags,'blocked':blocked})
    class_before=engine['class_support'].copy()
    for tag,group in [('relief_reserves','commoners'),('tax_relief','commoners'),('market_opening','merchants'),('border_defense','borderArmy'),('consultation','gentry')]:
        if tag in tags:
            engine['class_support'][group]=min(100,engine['class_support'][group]+1)
    # Policy echoes expire after three turns. Revocation removes matching scope.
    engine['policy_tags']=[t for t in engine['policy_tags'] if t['expires_after_turn']>=turn]
    if intent.get('action') in ('revoke','suspend'):
        engine['policy_tags']=[t for t in engine['policy_tags'] if t['category']!=intent['category'] or t['region']!=intent.get('region','全境')]
    else:
        for tag in tags:
            engine['policy_tags'].append({'tag':tag,'source_turn':turn,'expires_after_turn':turn+2,
                'strength':1,'category':intent['category'],'region':intent.get('region','全境')})
    active_tags={t['tag'] for t in engine['policy_tags']}
    for instance in list(engine['pending']):
        record=next(r for r in engine['records'] if r['instance_id']==instance)
        if record['respond_by_turn']>turn: continue
        event=catalog_for(engine)[record['event_id']]; outcome='expired' if event['polarity'] in ('positive','opportunity') else 'escalated'
        effects=event['unresolved'].copy(); matched=False
        for rule in event['response_rules']:
            if set(rule['requires_any']) & set(tags):
                matched=True
                feasible=all(state[k]>=v for k,v in rule['cost'].items())
                outcome=rule['result'] if feasible else 'mitigated'
                effects=rule['effects'].copy() if feasible else {'people':1,'treasury':0,'grain':0}
                if feasible and outcome=='well_handled':
                    effects=_benefits(event,effects,active_tags)
                break
        if not matched and event['polarity']=='positive': effects=dict.fromkeys(DIMS,0)
        if outcome=='escalated' and event['category']=='disaster' and state['grain']<30:
            effects['people']=max(-10,effects['people']-1)
        actual=_apply(state,effects,('event_escalation:' if outcome=='escalated' else 'event_response:')+instance,diffs,event=True)
        record.update(status='resolved' if outcome in ('well_handled','mitigated') else outcome,
                      outcome=outcome,resolved_turn=turn,response_tags=tags.copy(),response_effects=actual,
                      escalation_count=1 if outcome=='escalated' else 0)
        engine['pending'].remove(instance); updates.append(_public_record(record))
    if turn==2:
        engine['forewarnings'].append({'turn':2,'text':'山川巡检请朝廷留意房舍与堤防修缮。此为常例戒备，并非灾害已发生。'})
    event=select_event(engine,turn,state)
    announcement=None
    if event['id']!='peaceful_season':
        immediate=_benefits(event,event['immediate'],active_tags) if not event['pending'] else event['immediate'].copy()
        if event['protection'] in active_tags:
            immediate={k:int(v/2) if v<0 else v for k,v in immediate.items()}
        actual=_apply(state,immediate,'event_announcement:'+event['id'],diffs,event=True)
        for k,v in event['class_effects'].items():
            engine['class_support'][k]=max(0,min(100,engine['class_support'][k]+v))
        record={'instance_id':f"{turn}:{event['id']}",'event_id':event['id'],'category':event['category'],
                'polarity':event['polarity'],'tier':event['tier'],'announced_turn':turn,
                'respond_by_turn':turn+1 if event['pending'] else None,
                'status':'pending_response' if event['pending'] else 'resolved',
                'outcome':'pending' if event['pending'] else 'closed', 'escalation_count':0,
                'immediate_effects':actual,'protected':event['protection'] in active_tags}
        engine['records'].append(record)
        if event['pending']: engine['pending'].append(record['instance_id'])
        announcement=_public_record(record)
    if turn==8:
        engine['appraisal']=appraise(engine,state)
    diffs.append({'source':'class_support','before':class_before,'after':engine['class_support'].copy()})
    report={'announcement':announcement,'responses':updates,'state_diff':diffs,
            'watch':engine['forewarnings'][-1]['text'] if turn==2 else None,
            'quiet':TEXTS['peaceful_season']['announcement'] if event['id']=='peaceful_season' else None}
    return engine,GameState(**state),report


def repaired_weakness(initial,final):
    lowest=min(initial.values())
    return any(final[k]-initial[k]>=8 or initial[k]<50 and final[k]>=55 for k in DIMS if initial[k]==lowest)

def appraise(engine, final):
    responded=[r for r in engine['records'] if r.get('respond_by_turn')]
    severity={'small':1,'medium':2,'major':3}
    denominator=sum(severity[r['tier']] for r in responded)
    points=sum(severity[r['tier']]*{'well_handled':1,'mitigated':0.5,'escalated':-0.5}.get(r['outcome'],0) for r in responded)
    score=round(max(0,min(100,100*points/denominator))) if denominator else 0
    initial=engine['initial_state']; lowest=min(initial.values())
    repaired=repaired_weakness(initial,final)
    significant=any(final[k]-initial[k]>=8 for k in DIMS)
    won=final['people']>=80
    legacy=min(final['treasury'],final['grain'])<35 or any(r['tier']=='major' and r['outcome']=='escalated' for r in engine['records'])
    war=engine.get('war',{})
    legacy=legacy or war.get('cities_lost',0)>0 or war.get('active',False)
    if war.get('ending'): won=False
    difficult=min(initial.values())<50
    title='盛名之下' if won and legacy else '中兴之主' if won and difficult and repaired and score>=70 else '守成明君' if won and min(final['treasury'],final['grain'])>=50 and score>=50 else '民心归附' if won else '未竟之君' if not won and significant else '治世未成'
    if war.get('ending'): title='兵败国亡'
    crisis=(engine.get('crisis') or {}).get('ending')
    if crisis and not war.get('ending'):title=crisis['title'];won=False;legacy=True
    return {'title':title,'handling_score':score,'won':won,'repaired_weakness':repaired,
            'legacy_issues':legacy,'initial':initial.copy(),'final':dict(final),
            'delta':{k:final[k]-initial[k] for k in DIMS},
            'event_count':len(engine['records']),'resolved_count':sum(r['outcome']=='well_handled' for r in responded),
            'escalated_count':sum(r['outcome']=='escalated' for r in responded),
            'war_count':len(war.get('records',[])), 'war_wins':sum(r['outcome']=='victory' for r in war.get('records',[])),
            'war_losses':sum(r['outcome']=='defeat' for r in war.get('records',[])), 'cities_lost':war.get('cities_lost',0)}


def public_events(engine):
    if not engine: return None
    return {'version':engine['version'],'config_version':engine.get('config_version',2),'records':[_public_record(r) for r in engine['records']],
            'pending':[_public_record(r) for r in engine['records'] if r['instance_id'] in engine['pending']],
            'forewarnings':engine['forewarnings'],'appraisal':engine['appraisal'], 'war':engine.get('war')}


def historian_facts(detail):
    """Fact-only fallback, also locks the rule title against any model override."""
    game=detail['game']; a=game['events']['appraisal']
    opening=game['opening']; labels={'people':'民心','treasury':'国库','grain':'粮储'}
    numbers='，'.join(f"{labels[k]}由{a['initial'][k]}至{a['final'][k]}" for k in DIMS)
    policy='；'.join(f"第{r['turn_no']}回合办理{r['normalized_goal'][:50]}" for r in detail['history'][:2])
    war_note=f"共交战{a.get('war_count',0)}役，胜{a.get('war_wins',0)}役，败{a.get('war_losses',0)}役，割让{a.get('cities_lost',0)}城。" if a.get('war_count') else ''
    return {'reign_title':a['title'],'historian_comment':f"本朝起于{opening['name']}。在位{game['accepted_turns']}回合间，{numbers}，均为抽象国情指数。{policy}。{war_note}一朝经历主事件{a['event_count']}件，妥善回应{a['resolved_count']}件，未应而升级{a['escalated_count']}件；应天处变记为{a['handling_score']}。{'开局短板已有修复。' if a['repaired_weakness'] else '开局短板尚未达到修复标准。'}{'钱粮、战争或事件仍有遗留问题，盛名之下仍须警醒。' if a['legacy_issues'] else '终局未触发钱粮短缺或未解大事的留患条件，仍须量入为出。'}未触发的政策回声不作已发生后果。",
        'referenced_turns':[r['turn_no'] for r in detail['history'][:2]]}
