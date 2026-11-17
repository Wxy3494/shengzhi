"""Historical names are executable policy shorthand, not a replay of history."""
import re

# These aliases only classify an order. No historical outcome or score is granted.
ALIASES={
 'repression':r'焚书坑儒|焚书|坑儒|文字狱|罢黜百家|废黜百家',
 'reform':r'商鞅变法|王安石变法|戊戌变法|庆历新政|均田制|府兵制|洋务运动|明治维新|改革开放',
 'administration':r'推恩令|郡县制|三省六部制|废除丞相|废丞相|改土归流',
 'finance':r'摊丁入亩|耗羡归公|一条鞭法|盐铁专营',
 'education':r'科举制|开科取士|独尊儒术|兴办太学',
 'trade':r'隆庆开关|海禁开放|开放海禁',
 'coercive':r'玄武门之变|靖难之役|清君侧',
}

QUESTION_PATTERN=r'介绍|讲解|怎么看|为什么|为何|是否|听闻|提到|询问|如果|假如|是什么|什么是|讲讲|讲一|请解释|解释一下|说明一下|有何|评价'

def categories(operative):
    if re.search(QUESTION_PATTERN,operative):return []
    return [name for name,pattern in ALIASES.items() if re.search(pattern,operative)]

def is_order(text):
    if re.search(QUESTION_PATTERN,text):return False
    from .policy_actions import operative_text
    return any(re.search(pattern,operative_text(text)) for pattern in ALIASES.values())
