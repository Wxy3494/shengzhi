"""Model-proposed terms become effects only after explicit player consent."""
import copy,json,re
from pathlib import Path
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field,StrictInt,field_validator
from .events import DIMS

RULES=json.loads((Path(__file__).with_name('event_data')/'treaty_rules_v2.json').read_text(encoding='utf8'))
if RULES['version']!=2 or not all(type(RULES[k]) is int and 0<RULES[k]<=limit for k,limit in [('max_cities',3),('max_treasury',30),('max_grain',30)]):
    raise ValueError('Invalid treaty v2 bounds')
class Terms(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    cities: StrictInt=Field(ge=0,le=RULES['max_cities'])
    treasury: StrictInt=Field(ge=0,le=RULES['max_treasury'])
    grain: StrictInt=Field(ge=0,le=RULES['max_grain'])
    reason: str=Field(min_length=1,max_length=180)

    @field_validator('reason')
    @classmethod
    def no_fictional_units(cls,value):
        if re.search(r'[\d零一二三四五六七八九十百千万两]+\s*(?:石|贯|银两|两银)',value):
            raise ValueError('条约钱粮是抽象指数，不得写成石、贯或银两')
        return value

class NegotiationReply(Terms):
    decision: Literal['accepted','rejected','counter']

def requested_terms(text,current):
    """Only explicit quantities override the previous offer; omitted items stay."""
    result={k:current[k] for k in ('cities','treasury','grain')} if current else {}
    digits={'零':0,'〇':0,'一':1,'二':2,'两':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9}
    def number(value):
        if value.isdigit():return int(value)
        if '十' in value:
            left,right=value.split('十',1);return digits.get(left,1)*10+digits.get(right,0)
        return digits.get(value)
    numeral=r'[0-9零〇一二两三四五六七八九十]+'
    found=False
    for key,pattern in {
        'cities':rf'(?:城池|割城|割让|索取城池)\s*(?:为|到|至|改为|增加到|减少到)?\s*({numeral})|({numeral})\s*(?:座|个)?城(?:池)?',
        'treasury':rf'(?:国库|赔款|赔银|赔钱|财物)\s*(?:为|到|至|改为|增加到|减少到)?\s*({numeral})',
        'grain':rf'(?:粮储|粮草|赔粮)\s*(?:为|到|至|改为|增加到|减少到)?\s*({numeral})',
    }.items():
        match=re.search(pattern,text)
        if match:
            value=number(next(g for g in match.groups() if g is not None))
            if value is not None:result[key]=value;found=True
    if re.search(r'不割城|不割地|不要城池|无需割城|免割城',text):result['cities']=0;found=True
    return result if found else None

def interpret_reply(raw,text,current):
    """A counterproposal is not agreement and never signs or transfers assets."""
    raw=dict(raw);decision=raw.pop('decision','counter')
    if decision not in ('accepted','rejected','counter'):raise ValueError('invalid negotiation decision')
    terms=Terms.model_validate(raw).model_dump()
    previous={k:current['terms'][k] for k in ('cities','treasury','grain')} if current else None
    requested=requested_terms(text,previous)
    if decision=='accepted' and requested and any(terms[k]!=v for k,v in requested.items()):decision='counter'
    offered=previous if decision=='rejected' and previous else {k:terms[k] for k in ('cities','treasury','grain')}
    reply={'decision':decision,'reason':terms['reason'],'previous_terms':previous,'requested_terms':requested,
           'offered_terms':offered,'changes':{k:offered[k]-previous[k] for k in previous} if previous else None}
    return terms,reply

def restates_terms(text,terms):
    number=r'[0-9零〇一二两三四五六七八九十百千万]+'
    def parse(raw):
        if raw.isdigit():return int(raw)
        digits={'零':0,'〇':0,'一':1,'二':2,'两':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9}
        if raw in digits:return digits[raw]
        if '百' in raw or '千' in raw or '万' in raw:return -1
        if '十' in raw:
            left,right=raw.split('十',1)
            return digits.get(left,1)*10+digits.get(right,0)
        return -1
    patterns={
        'cities':[rf'({number})\s*(?:座|个)?城(?:池)?',rf'城池\s*({number})'],
        'treasury':[rf'(?:赔款|国库|赔银|赔钱|财物)\s*({number})',rf'({number})\s*(?:点)?(?:国库|赔款)'],
        'grain':[rf'(?:粮储|粮草|赔粮|粮)\s*({number})',rf'({number})\s*(?:点)?(?:粮草|粮储)'],
    }
    remainder=text;seen=False
    for key,group in patterns.items():
        for pattern in group:
            matches=list(re.finditer(pattern,remainder))
            if any(parse(m[1])!=terms[key] for m in matches):return False
            if matches:seen=True;remainder=re.sub(pattern,'',remainder)
    return seen and not re.search(number,remainder)

def action(text,engine):
    from .war import active
    if active(engine) and refuses_negotiation(text):return 'reject'
    if active(engine) and re.search(r'拒绝(?:任何|继续|此次)?(?:议和|谈判|和谈)|不(?:再)?(?:议和|谈判)|拒和',text):return 'reject'
    pending=engine.get('war',{}).get('pending_treaty')
    if not pending:
        history=engine.get('war',{}).get('records',[])
        return 'negotiate' if history and engine['war'].get('active',True) and re.search(r'谈判|议和|协商|索要|索取|求和',text) and not re.search(r'拒绝|不议和|不谈判|不同意',text) else None
    if re.search(r'如果|若|除非|是否|能否|考虑|询问',text):return 'negotiate' if re.search(r'谈判|协商|还价',text) else None
    if re.search(r'拒绝|不同意|未同意|不接受|不答应|不批准|不割|不得割|绝不割|不赔|不得赔',text):
        return 'negotiate' if re.search(r'谈判|协商|还价|改为|改议|另议|但|只赔|仅赔',text) else 'reject'
    consent=bool(re.search(r'同意|接受|答应|批准|准奏|签订.{0,5}和约|签署.{0,5}和约|照此议和|准予议和',text))
    if re.search(r'还价|索要|索取|要求.{0,8}(?:赔|割)|改为|改议|重新(?:谈判|议和)|降低|减少|加价',text):return 'negotiate'
    if re.search(r'[0-9零〇一二两三四五六七八九十百千万]+',text) and re.search(r'城|赔|粮|银|钱',text):
        return 'accept' if consent and restates_terms(text,pending['terms']) else 'negotiate'
    if re.fullmatch(r'\s*(?:同意|接受|答应|批准|准奏)[。！!\s]*',text) or re.search(r'(?:同意|接受|答应|批准).{0,12}(?:上述条件|当前条件|对方条件|条件|条款|议和|和约|割地|割城|赔款)|签订.{0,5}和约|签署.{0,5}和约|照此议和|准予议和',text):return 'accept'
    if re.search(r'谈判|协商',text):return 'negotiate'
    return None

def refuses_negotiation(text):
    for clause in re.split(r'[，,。；;]',text):
        if re.search(r'如果|若|是否|考虑|询问|不禁止|不拒绝|不得禁止',clause):continue
        if re.search(r'(?:不准|不许|不得|禁止|严禁|绝不|决不|拒绝)(?:再|继续|任何)?(?:与敌国|同敌国|与对方)?(?:议和|求和|谈判|和谈)|拒和|不(?:再)?(?:议和|谈判)',clause):return True
    return False

def propose(engine,turn,outcome,raw_terms,source='model',same_round=False):
    terms=Terms.model_validate(raw_terms).model_dump()
    war=engine['war'];war['version']=max(2,war.get('version',2));war['active']=True
    proposal={'id':f'{turn}:{len(war.setdefault("treaties",[]))+1}', 'turn':turn,
        'direction':'receive' if outcome=='victory' else 'pay','terms':terms,
        'status':'pending' if turn<8 or same_round else 'expired', 'source':source, 'outcome':outcome}
    war['treaties'].append(copy.deepcopy(proposal))
    war['pending_treaty']=copy.deepcopy(proposal) if proposal['status']=='pending' else None
    return proposal

def split_order(text):
    """Separate diplomacy from the one governance objective, retaining safeguards."""
    from .policy_actions import action_categories,COMBAT_PATTERN
    expanded=re.sub(r'(?:并且|并|同时|另外|另)(?=(?:开仓|放粮|赈|修|减|免|征|兴|清查|平粜|接受|同意))','，',text)
    clauses=[s.strip() for s in re.split(r'[，,。；;]+',expanded) if s.strip()]
    deal=[];governance=[];safeguards=[]
    for clause in clauses:
        if refuses_negotiation(clause):deal.append(clause)
        elif re.match(r'不得|不许|禁止|严禁|不强征|不搜刮',clause):safeguards.append(clause)
        elif (refuses_negotiation(text) or re.search(r'拒绝|拒和|不同意',text)) and re.search(COMBAT_PATTERN,clause):deal.append(clause)
        elif re.search(r'议和|和约|谈判|赔款|割地|割让|条件|接受|同意',clause):deal.append(clause)
        elif set(action_categories(clause))-{'diplomacy','consultation'}:governance.append(clause)
        else:deal.append(clause)
    if governance:governance+=safeguards
    else:deal+=safeguards
    return '，'.join(deal),'，'.join(governance)

def accept(engine,turn,state):
    war=engine['war'];proposal=copy.deepcopy(war['pending_treaty']);terms=proposal['terms']
    before=state.copy();state=state.copy()
    if proposal['direction']=='pay' and any(state[d]<terms[d] for d in ('treasury','grain')):
        proposal.update(status='unfunded',decision_turn=turn,effects=dict.fromkeys(DIMS,0))
        return state,proposal
    sign=-1 if proposal['direction']=='pay' else 1
    for d in ('treasury','grain'):state[d]=max(0,min(100,state[d]+sign*terms[d]))
    key='cities_lost' if sign<0 else 'cities_gained'
    war[key]=war.get(key,0)+terms['cities']
    proposal.update(status='accepted',decision_turn=turn,effects={d:state[d]-before[d] for d in DIMS})
    proposal['before']=before;proposal['after']=state.copy()
    war['treaties'].append(copy.deepcopy(proposal));war['pending_treaty']=None;war['active']=False;war['version']=max(2,war.get('version',2))
    return state,proposal

def reject(engine,turn):
    war=engine['war'];proposal=copy.deepcopy(war['pending_treaty'])
    proposal.update(status='rejected',decision_turn=turn)
    war.setdefault('treaties',[]).append(proposal);war['pending_treaty']=None;war['active']=True;war['version']=max(2,war.get('version',2))
    return proposal
