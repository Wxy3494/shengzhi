"""Read-only planning shared by preflight and actual schema-4 settlement."""
from . import events,war,treaties

LABELS={'coercive':'宫室营建或强制征役','grain_supply':'朝廷购粮补仓','trade':'平粜、市场或通商治理',
 'military':'军事施政','defense':'修筑边防或整备防线','water':'修建水利或运河','dike':'修堤治河','tax':'调整税赋',
 'relief':'赈济灾民','justice':'司法或吏治','repression':'禁言、拘押或抄没','education':'兴学取士',
 'reform':'推行改革','rest':'休养生息','road':'道路工程','administration':'行政协商','finance':'调整财政收支与资源调度','inaction':'不新增施政'}

def plan_order(text,engine,state):
    intent=events.validated_intent(text,{})
    requested=treaties.action(text,engine)
    action=requested
    player_combat=war.is_combat(text,intent)
    reason=war.enemy_attack(engine,state,action=='reject')
    if player_combat and war.weak(state) and not reason:reason='two_weak_dimensions'
    blocked=bool(reason and action in ('accept','negotiate'))
    if blocked:action=None
    if action=='reject':player_combat=True
    if action in ('accept','negotiate'):player_combat=False
    if requested:intent.update(category='diplomacy',project='war_treaty',action='enact')
    effect=events.policy_effect(intent,text)
    if requested or player_combat:effect=dict.fromkeys(events.DIMS,0)
    execution=LABELS.get(intent['category'],'按圣旨施政')
    from .historical_policies import is_order
    if is_order(text) and intent['category']=='repression':execution='按原诏实施文化压制或惩治异议，结算民心与秩序代价'
    if intent['category']=='coercive':
        from .policy_actions import operative_text
        import re
        operative=operative_text(text);parts=[]
        if re.search(r'宫殿|宫室|行宫',operative):parts.append('按原诏营建宫室')
        if re.search(r'无偿(?:征役|徭役|劳役)|强征|征发',operative):parts.append('按原诏征役')
        if re.search(r'征伐|远征',operative):parts.append('按原诏征战')
        if parts:execution='；'.join(parts)
    if action=='accept':execution='接受当前和约并按原条款履约（不会重新谈判）'
    if action=='negotiate':execution='提出新议和条件，等待再次确认；本次不割地、不赔付'
    if player_combat:execution='执行交战命令，结算本役战果、军费与军粮'
    if reason:execution=('拒绝谈判，敌军直接进攻' if reason=='refused_negotiation' else '战争中两项国力低于20，敌军直接进攻')+('；当前议和请求不能履约' if blocked else '')
    return {'intent':intent,'requested_treaty_action':requested,'treaty_action':action,'player_combat':player_combat,
            'attack_reason':reason,'treaty_blocked':blocked,'combat':player_combat or bool(reason),
            'effect':effect,'execution':execution}
