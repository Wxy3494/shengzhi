"""Conservative action evidence for schema 4, shared by effects and responses.

Mentions, rejected orders and deferred intentions are not executed actions.
This does not migrate legacy policy interpretation.
"""
import re

NEGATION=r'不(?:反击|反攻|还击|迎战|应战|回击|突袭|进攻|开战|宣战|攻打|攻城|督战|进兵|用兵|打仗|作战|出征|远征|征伐|征讨)|不(?:御驾)?亲征|不出兵|不派兵|不调兵|不建|不强征|不搜刮|不夺|不拨|不发|不作|不做|不赈|不修|不增|不征|不再|不要|不得|不许|不准|禁止|严禁|勿|停止|暂停|拒绝'
COMBAT_PATTERN=r'亲征|出征|征伐|远征|征讨|督战|进兵|出兵|开战|宣战|攻打|攻城|迎敌|抗敌|作战|平叛|打仗|发动战争|继续战争|反击|反攻|还击|迎战|应战|回击|突袭|进攻|发动攻势|征战|反扑|出战|进军|决战|攻击.{0,8}(?:敌|军|城|邻国)|击退(?:敌|来犯)|收复(?:失地|失城)|讨伐|北伐|南征'
NEGATION=r'不(?:把|将)|不无偿|不(?:反扑|出战|进军|决战|攻击|击退|收复|讨伐|北伐|南征)|'+NEGATION


def operative_text(text):
    clauses=re.split(r'[，,。；;、\n]|但|而',text)
    accepted=[]
    for clause in clauses:
        if not re.search(r'(?:不准|不得|不许|禁止|严禁|勿).{0,18}(?:治罪|拘押|下狱|问罪|惩处|论处|判刑|处罚|惩治)',clause):
            clause=re.sub(r'(?:将|把)?[^，,。；;]{0,14}(?:批评|议论|进谏|谏言|异议|非议|诽谤朝廷)[^，,。；;]{0,8}(?:者|之人)(?:一律|皆|均|依法|以[^，,。；;]{1,8}罪|按律|严加)*(?:治罪|下狱|问罪|拘押|论罪|逮捕|严惩|惩处|论处|判刑|处罚|惩治)', '禁言治罪',clause)
        if re.search(r'提到|听闻|谈及|询问|查看|只问|仅问|暂缓|待议|另议',clause) and not re.search(r'立即|下令|拨款|开仓',clause):
            continue
        clause=re.sub(r'(?:禁止|不许|不得)(?:百姓|臣民|官民|士人|众人)?(?:批评|议论|进谏)', '禁言',clause)
        # Banning misconduct is governance; banning expenditure is not spending.
        clause=re.sub(r'(?:禁止|严禁|不得)(?:官员|官吏|胥吏)?(?:贪墨|贪污|侵吞|勒索)', '查办贪墨',clause)
        clause=re.sub(r'(?:修完|等到|待到|待).*?(?:再|才).*$', '',clause)
        clause=re.sub(r'(?:以后|日后|随后)再.*$', '',clause)
        clause=re.sub(r'交(?:由)?地方自理|地方自行处理|暂不处理|置之不理', '',clause)
        clause=re.sub(r'(?:不减少|不削减|不压减|不缩减|不裁减|不节省|不节约|'+NEGATION+r')[^，,。；;、\n]*','',clause)
        accepted.append(clause)
    return '，'.join(accepted).strip('， ')


PATTERNS=[
    ('repression',r'禁言|(?:拘押|逮捕|囚禁|抓捕|治罪|惩处).{0,12}(?:批评|议论|进谏|谏言|异议)|(?:没收|抄没).{0,8}(?:家产|财产)'),
    ('coercive',r'强征|无偿(?:征役|徭役|劳役)|征发.{0,5}(?:民夫|徭役)|夺种粮|搜刮|征伐|远征|(?:大兴|营建|兴建|修|建|造|扩建).{0,5}(?:宫殿|宫室|行宫)'),
    ('grain_supply',r'购粮|买粮|籴粮|补仓|采买.{0,6}粮|调运.{0,6}粮'),
    ('relief',r'赈济|赈灾|开仓|放粮|发粮|发放.{0,4}粮|(?:分发|散发|散给|分给|发给).{0,5}(?:粮食|粮草|官粮|仓粮)|(?:粮食|粮草|官粮|仓粮|存粮|粮)[^，,。；;]{0,8}(?:发给|分给|散给|发放|分发)[^，,。；;]{0,8}(?:百姓|灾民|饥民|民户|穷人)|安置灾民'),
    ('water',r'(?:修|建|开凿|挖掘|修筑|修缮|整修|疏通).{0,8}(?:渠|运河)|疏浚|灌溉|(?:兴修|修复|修缮|整修).{0,5}水利'),
    ('dike',r'(?:修|筑|加固|堵|抢修).{0,5}(?:堤|坝|决口)'),
    ('tax',r'(?:减|免|增|加|征|恢复|降低|调整|整顿|少收|提高|加重).{0,6}(?:税|田赋)|按原额征收'),
    ('trade',r'通商|互市|(?:开放|开设|设立|准许|允许).{0,8}(?:集市|市场)|整顿.{0,5}(?:市场|商路)|平粜|平抑'),
    ('justice',r'查账|反腐|清查|查办|整顿官|治安|剿匪|大赦|赦免|赦轻罪|赦罪'),
    ('defense',r'(?:修建|修筑|修缮|整修|加固|建造|营建|修复|修|建).{0,5}(?:长城|边墙|城防|烽燧|关防)'),
    ('military',COMBAT_PATTERN+r'|加强边防|加固关隘|发放军饷|补充军需|安置戍|整顿军队|(?:召集|集结|招募|募集).{0,4}(?:士兵|兵卒|军队|军士)|征兵'),
    ('diplomacy',r'交涉|议和|外交'),
    ('finance',r'(?:减少|削减|压减|缩减|裁减|节省|节约).{0,6}(?:军费|军饷|军需|财政开支|宫廷开支)|(?:军费|军饷|军需|财政开支|宫廷开支).{0,5}(?:减少|削减|压减|缩减)'),
    ('administration',r'调整行政制度|改革官制|吸纳汉官参与政务|选用汉官'),
    ('reform',r'(?:女子|女性|妇女).{0,12}(?:为官|入仕|任官|选官|科举|取士)'),
    ('education',r'兴学|设立学校|修建学校|育才|(?:严明|整饬|改革|推行|采用|仿照|参照|按).{0,12}(?:科举|取士|糊名|誊录)|(?:科举|取士).{0,8}(?:糊名|誊录)'),
    ('reform',r'推行新法|改革|变法'),
    ('rest',r'休养生息|轻徭薄赋'),
    ('road',r'修路|(?:修|建|整修).{0,5}(?:官道|驿道|驿站)'),
    ('consultation',r'咨议|协商|议政'),
]


def action_categories(text):
    operative=operative_text(text)
    # Household purchases are not an order for the treasury to buy grain.
    fiscal=re.sub(r'(?:贫户|贫民|百姓|农户|灾民|民户|乡民|商户|居民|小民)[^，,。；;]{0,8}?(?:购粮|买粮|籴粮)','',operative)
    categories=[category for category,pattern in PATTERNS if re.search(pattern,fiscal if category=='grain_supply' else operative)]
    from .historical_policies import categories as history_categories
    categories=list(dict.fromkeys(categories+history_categories(operative)))
    if re.search(r'不拨款|不动(?:用)?国库|拒绝拨款',text):
        categories=[c for c in categories if c not in ('water','dike','road','education','military')]
        if re.search(r'不发粮|不开仓|拒绝放粮',text):categories=[c for c in categories if c!='relief']
    return categories

def primary_category(text,categories):
    if not categories:return 'inaction'
    if 'repression' in categories:return 'repression'
    if 'coercive' in categories:return 'coercive'
    if 'relief' in categories and 'tax' in categories:return 'relief'
    if 'trade' in categories and 'tax' in categories:
        operative=operative_text(text)
        positions={name:min((m.start() for n,p in PATTERNS if n==name for m in re.finditer(p,operative)),default=9999) for name in ('trade','tax')}
        return min(positions,key=positions.get)
    return categories[0]
