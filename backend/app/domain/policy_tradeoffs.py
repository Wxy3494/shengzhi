"""Qualitative policy mechanisms. These never alter authoritative numeric effects."""
import copy,re
from .policy_actions import operative_text

GUIDANCE={
 'water':'灌溉、通航和抗旱收益；工程支出、工期和沿线田产影响，雇工与强征必须区分。',
 'dike':'防洪与田舍保护；修堤工费、维护及上下游水势，不能凭空宣布决口。',
 'relief':'饥民获得救济、灾区安定；仓储和运输负担，按赈济范围讨论公平，不默认贪腐。',
 'grain_supply':'补充储备、提高应灾能力；采购库款和市场粮价，民户买粮不能算官府采购。',
 'tax':'民户负担、财政供给与地区公平；征减幅度以诏意为准，不能把减税说成免税。',
 'trade':'交易和税源扩大；价格、竞争、通行成本及边市安全，区分可能波动与已发生损失。',
 'road':'货运和交通便利；建养支出与沿途土地、劳役负担。',
 'justice':'司法公平与秩序；办案成本、程序保障、宽严尺度和当事人感受。',
 'education':'扩大人才来源；教育和考务支出、录用标准及机会公平。',
 'reform':'制度效率与新受益者；过渡成本、原有利益群体反应及执行条件，反对不是必然叛乱。',
 'administration':'政务效率与职责明确；办事成本、信息偏差和权责约束。',
 'oversight':'减少舞弊和纠错；稽核成本与正常行政负担，不制造无穷监督失灵。',
 'military':'安全和战略收益；军费军粮、乡间负担与战败风险，战果只依核定战报。',
 'defense':'边地安全和威慑；驻军供给、训练和财政负担，不等于自动获胜。',
 'finance':'筹资与资源调度；征敛对象、负担分配、持续性，不能凭空创造收入。',
 'diplomacy':'停战、贸易和安全空间；让步、履约负担及信用，未签约不当作已割地。',
 'coercive':'宫室或国家动员目标；钱粮、劳役和民户生计代价，保护措施不得反判为强征。',
 'repression':'统治控制的短期效果；言路、公平、恐惧与积怨，不包装成普通司法善政。',
 'rest':'减轻劳役并恢复生计；财政和公共事务的取舍，不能凭无所作为无限增长。',
 'inaction':'本次没有新增施政，原有事件和后效按事实处理，不奖励虚构行动。',
}

def considerations(text,intent):
    operative=operative_text(text)
    result={'mechanism':GUIDANCE.get(intent.get('category'),'明确实际受益者、支出和受影响者；区分眼前结果与有条件的长期影响。'),
            'prohibitions':intent.get('prohibitions',[]),'conditional_risks':[]}
    if intent.get('category')=='finance' and re.search('军费|军饷|军需',operative):
        result['mechanism']='按原诏削减军费，节省财政支出；同时考虑军饷、训练与装备供给的取舍，不自动裁军或停止已存在的战争，不追溯退还已经花掉的战费。若压缩必要边备或欠饷才增加军心与边防风险。'
    if re.search('焚书|坑儒|文字狱',operative):
        result['mechanism']='文化压制可能收紧言论和统治控制，但损害典籍传承、士人安全、言路与民间信任；焚书坑儒不能美化为普通司法善政。已核定负面影响应如实说明，未发生的动乱只能作为条件风险。'
    if re.search('大赦|赦免|赦轻罪|赦罪',operative):
        result['mechanism']='释放符合条件者、减少积案和家庭负担；同时核查受害者公平、重犯范围、安置与治安。'
        protected=bool(re.search('排除重犯|不赦重犯|重犯不赦|仅赦轻罪|只赦轻罪',text))
        result['conditional_risks'].append({'condition':'若轻罪获赦者缺乏安置或巡捕疏漏' if protected else '若赦免涵盖重犯且释放后缺乏安置与约束',
            'consequence':'可能增加再犯与地方治安隐患，受害者也可能感到不公。',
            'likelihood':'low' if protected else 'medium','horizon':'delayed'})
    if re.search(r'(?:女子|女性|妇女).{0,12}(?:为官|入仕|任官|选官|科举|取士)',operative):
        result['mechanism']='扩大选才范围，让有能力的女子参与政务；同时考虑考核标准、任职衔接和传统礼法观念的阻力。'
        result['conditional_risks'].append({'condition':'若保守官绅以旧有礼法反对且沟通、任职衔接不足',
            'consequence':'可能出现舆论争议或任用阻力，不能将反对预写成必然动乱。','likelihood':'medium','horizon':'current'})
    return result

def retain_analysis(analysis,considerations,blocked=False):
    result=copy.deepcopy(analysis)
    if not blocked:
        existing=result.setdefault('risks',[])
        for risk in considerations['conditional_risks']:
            if not any(('治安' in r['consequence'] or '再犯' in r['consequence']) if '再犯' in risk['consequence'] else ('礼法' in r['condition'] or '保守' in r['condition']) for r in existing):
                if len(existing)<3:existing.append(copy.deepcopy(risk))
    return result
