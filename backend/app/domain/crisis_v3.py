"""Schema-4 crisis integration, without changing legacy pressure rules."""
import copy
from .crises import initial_realm,advance_realm,NAMES

def initial_crisis(turn=1):
    realm=initial_realm();realm.update(version=3,activated_turn=turn)
    return realm

def advance_crisis(previous,after,intent,text,blocked,notes,turn,war=None,battle=None):
    previous=copy.deepcopy(previous) if previous and previous.get('version')==3 else initial_crisis(turn)
    # Compute increments with the legacy mechanism, then apply warning gates.
    # The trial ending is discarded until the player has had both warning turns.
    effective=dict(intent)
    if battle or (war or {}).get('active'):
        previous['military_engaged']=True;previous['border_engaged']=True
    elif war and war.get('active') is False and previous.get('was_war_active'):
        previous['military_engaged']=False;previous['border_engaged']=False
    previous['was_war_active']=bool((war or {}).get('active'))
    trial=advance_realm(previous,after,effective,text,blocked,notes,turn,'playing')
    trial.update(version=3,activated_turn=previous['activated_turn'],ending=None,warnings=[])
    trial['notified']=copy.deepcopy(previous['notified'])
    for key in NAMES:
        old=previous['pressures'][key];value=trial['pressures'][key]
        for threshold in (75,90):
            if old<threshold<=value and threshold not in previous['notified'][key]:
                value=threshold;break
        trial['pressures'][key]=value
        for threshold in (75,90):
            if value>=threshold and threshold not in trial['notified'][key]:
                trial['notified'][key].append(threshold)
                trial['warnings'].append({'id':key,'threshold':threshold,'label':NAMES[key],'value':value,
                    'level':'critical' if threshold==90 else 'warning','reason':{
                        'civil':'民间生计与支持持续受损，地方怨情正在累积。',
                        'army':'军务持续而供给吃紧，军心已有不稳迹象。',
                        'border':'边地钱粮难以支持防线，边防形势渐趋严峻。',
                        'bankruptcy':'财政困局持续，朝廷周转已显困难。'}[key],
                    'advice':{'civil':'减轻民间负担，恢复生计和粮食供给。','army':'补充军需钱粮，避免困乏时继续动员。',
                        'border':'改善边防供给，量力收缩战线或议和。','bankruptcy':'恢复财政收入，节制支出。'}[key],
                    'source_turns':trial['sources'][key].copy()})
    # Reuse legacy ending priority only after the gated values reach 100.
    for key in ('civil','army','border','bankruptcy'):
        if trial['pressures'][key]>=100:
            from .crises import ending
            trial['ending']=ending(key,NAMES[key],{
                'civil':'民怨与生计困局持续恶化，民变蔓延，本朝统治告终。',
                'army':'军中供给与动员压力未获缓解，兵变终结本朝。',
                'border':'边防钱粮与战线承诺失衡，边疆失守，本朝未能渡过危局。',
                'bankruptcy':'财政危机持续而未获恢复，朝廷难以维持运转，以破产收场。'}[key],
                'lost',turn,trial['sources'][key]);break
    trial['trends']=[{'id':key,'label':NAMES[key],
        'trend':'easing' if trial['pressures'][key]<previous['pressures'][key] else 'worsening' if trial['pressures'][key]>previous['pressures'][key] else 'stable',
        'condition':'quiet' if trial['pressures'][key]==0 else 'critical' if trial['pressures'][key]>=90 else 'warning' if trial['pressures'][key]>=75 else 'building'} for key in NAMES]
    return trial

def public_crisis(realm):
    if not realm or realm.get('version')!=3:return None
    result={k:copy.deepcopy(realm[k]) for k in ('version','activated_turn','warnings','reform_started','reform_steps','ending')}
    result['trends']=copy.deepcopy(realm.get('trends',[]));return result

def finish_events(engine,state,realm,turn):
    """Close outstanding events without fabricating a response or applying losses."""
    from . import events
    for record in engine['records']:
        if record['instance_id'] in engine['pending']:record.update(status='closed',outcome='closed',resolved_turn=turn)
    engine['pending']=[]
    engine['crisis']={'version':3,'ending':realm['ending']}
    engine['appraisal']=events.appraise(engine,state)
