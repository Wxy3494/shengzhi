"""固定夹具适配器:演示模式用,按关键词给出确定性剧情。

只用于演示与规则回归;不能冒充真实模型推演。无匹配输入自动细化后结算。
文案一律使用通俗白话。
"""

import hashlib

from .base import ModelContext
from .schema import AcceptedCandidate, Candidate, ClarificationCandidate

FEASIBILITY_FALLBACK = {
    "kind": "accepted",
    "normalized_goal": "把诏书细化后下发施行",
    "tags": ["expanded"],
    "policy_effect": {"people": 2, "treasury": -2, "grain": 0},
    "advisor": "陛下,这道诏书臣已经替您补上了细节:各州县怎么领旨、谁来经办、钱粮从哪儿出,都写得明明白白,官员们照着办就行,不会出岔子。",
    "reactions": [
        {"speaker": "song_zhiyuan", "text": "诏书写得明白,该交多少税、走哪条路,俺们心里就有数了。"},
        {"speaker": "tian_bo", "text": "这回说得清楚,村里照着办就行,不用瞎猜。"},
    ],
    "new_echoes": [],
    "summary": "诏书细化后下发,各州县照办。",
}

ANACHRONISM_KEYWORDS = [
    "核电站", "手机", "发电", "互联网", "火车", "汽车", "飞机", "电脑",
    "坦克", "大炮", "智能手机", "卫星", "机器人", "电灯", "无线电",
    "人工智能", "短视频", "网红", "微信", "二维码", "网游",
]

INDEPENDENT_GOALS = {
    "relief": ["赈灾", "赈济", "开仓", "放粮"],
    "military": ["远征", "出征", "征讨", "征服邻国", "扩军"],
    "consort": ["选妃", "选秀", "纳妃"],
    "tax_abolition": ["废商税", "废除全部商税", "废除一切商税"],
}

UNCLEAR_PHRASES = ["随便看着办", "你替朕决定", "你替我决定", "随便", "看着办"]


def _is_not_policy(text: str) -> bool:
    if "忽略规则" in text or "宣布胜利" in text or "改成100" in text:
        return True
    if any(word in text for word in ["民心", "国库", "粮储"]) and any(
        word in text for word in ["多少", "几", "如何", "当前", "现在"]
    ):
        return True
    return any(word in text for word in ["你好", "天气", "闲聊", "聊会"])


CATEGORIES = [
    (
        "relief",
        ["赈", "赈灾", "赈济", "开仓", "放粮", "粮仓", "饥", "灾民", "灾州", "救灾"],
        {
            "kind": "accepted",
            "normalized_goal": "开仓放粮,赈济灾民",
            "tags": ["relief"],
            "policy_effect": {"people": 5, "treasury": -6, "grain": -8},
            "advisor": "陛下,赈灾的诏书已经传下去了。官仓开始放粮,灾民有了口粮,减免田赋也能让他们喘口气。朝廷少了些收入和存粮,先紧着受灾最重的州县用。",
            "reactions": [
                {"speaker": "tian_bo", "text": "赈粮到了,锅里就能见着米了。乡亲们惦记着地里的苗,都盼着缓过这阵再好好种地。"},
                {"speaker": "gu_tingzhang", "text": "赈灾能安定乡里,田产和宗族也少受流离之苦,这是好事,地方自当协力把粮送到灾民手中。"},
            ],
            "new_echoes": [{"delay": 1, "reason": "赈灾后灾民返乡复耕的成效"}],
            "summary": "灾情缓过来了,百姓安顿下来,官仓支出有所增加。",
        },
    ),
    (
        "waterworks",
        ["水利", "修河", "筑堤", "河堤", "灌溉", "水渠"],
        {
            "kind": "accepted",
            "normalized_goal": "兴修水利",
            "tags": ["water"],
            "policy_effect": {"people": -2, "treasury": -8, "grain": 0},
            "advisor": "修河的活儿开工了,府库拨了银子,州县按段修筑。眼下要用些人力,等河堤牢固、水渠通畅,沿岸田地便能少受水患。",
            "reactions": [
                {"speaker": "tian_bo", "text": "修河虽要忙上一阵,若能拦住大水、引来灌溉,庄稼就有指望,乡亲们愿意把活儿干好。"},
                {"speaker": "gu_tingzhang", "text": "水利修成,沿岸田产和村庄都能得益,地方按段合力承办便是。"},
            ],
            "new_echoes": [{"delay": 2, "reason": "水利工程完工后的灌溉成效"}],
            "summary": "眼下动用钱粮人力,往后有望护田增收。",
        },
    ),
    (
        "roads",
        ["修路", "官道", "驿道", "铺路"],
        {
            "kind": "accepted",
            "normalized_goal": "修整官道",
            "tags": ["road"],
            "policy_effect": {"people": 3, "treasury": -6, "grain": 0},
            "advisor": "官道开工了,州县分段整修,眼下要用些人力。等道路平整,行商赶路、乡里运粮都会方便许多。",
            "reactions": [
                {"speaker": "song_zhiyuan", "text": "路平了,车马走得稳,货物少些耽搁,南北买卖都更顺当。"},
                {"speaker": "tian_bo", "text": "官道修好,挑粮赶集都省力。眼下出工修路,也是为了往后方便。"},
            ],
            "new_echoes": [{"delay": 1, "reason": "官道完工后货运与乡里出行的便利"}],
            "summary": "官道逐渐平整,行商和乡里出行都更方便。",
        },
    ),
    (
        "military",
        ["军", "兵", "出征", "征讨", "远征", "扩军", "练兵"],
        {
            "kind": "accepted",
            "normalized_goal": "兴兵用武",
            "tags": ["military"],
            "policy_effect": {"people": -3, "treasury": -10, "grain": -5},
            "advisor": "大军还没出发,粮草先得备上。府库和粮仓都吃紧,民间也怕被征。",
            "reactions": [
                {"speaker": "gu_tingzhang", "text": "打仗是凶险的事,守土还说得过去,要是为了开疆,怕会伤了国家的根本。"},
                {"speaker": "tian_bo", "text": "又要征粮拉夫,今年的日子可怎么过。"},
            ],
            "new_echoes": [{"delay": 1, "reason": "核验军需粮草转运与民间负担"}],
            "summary": "军费太重,百姓不安。",
        },
    ),
    (
        "exam",
        ["科举", "开科", "书院", "取士"],
        {
            "kind": "accepted",
            "normalized_goal": "开科取士",
            "tags": ["exam"],
            "policy_effect": {"people": 3, "treasury": -2, "grain": 0},
            "advisor": "开科考试,穷人家的读书人也有了出路。只是办考要花钱,还得防着有人托关系、搞舞弊。",
            "reactions": [
                {"speaker": "gu_tingzhang", "text": "取士看重德行和才学,才能正本清源。"},
                {"speaker": "song_zhiyuan", "text": "读书人多了,纸墨的生意倒也好做了。"},
            ],
            "new_echoes": [],
            "summary": "读书人开始拥护,考试得看严点。",
        },
    ),
    (
        "tax_relief",
        ["免税", "减税", "田赋", "商税", "赋税", "税"],
        {
            "kind": "accepted",
            "normalized_goal": "减免税赋",
            "tags": ["tax"],
            "policy_effect": {"people": 4, "treasury": -5, "grain": 0},
            "advisor": "减税的诏书一下,百姓的担子轻了不少。可朝廷的收入也跟着少了,户部得另想办法开源。",
            "reactions": [
                {"speaker": "song_zhiyuan", "text": "税少一分,商路就能多通一里。可官道要是不修,商税减了也白搭。"},
                {"speaker": "gu_tingzhang", "text": "重新理田赋有它的道理,只是这事要是太急,地方上怕会起纷争。"},
            ],
            "new_echoes": [{"delay": 2, "reason": "核验各地税吏是否照章减征"}],
            "summary": "百姓负担轻了点,朝廷收入少了。",
        },
    ),
    (
        "trade",
        ["通商", "商路", "互市", "商禁"],
        {
            "kind": "accepted",
            "normalized_goal": "畅通商路",
            "tags": ["trade"],
            "policy_effect": {"people": 2, "treasury": 4, "grain": 0},
            "advisor": "商路一开,货物流动起来,税收也慢慢多了。只是牙行定价,得防着有人囤货抬价。",
            "reactions": [
                {"speaker": "song_zhiyuan", "text": "朝廷放宽了商禁,行商的日子好过多了。"},
                {"speaker": "tian_bo", "text": "物价别跟着涨,俺们才买得起粮。"},
            ],
            "new_echoes": [{"delay": 2, "reason": "核验通商后各地物价波动"}],
            "summary": "商路热闹了,物价还得盯着。",
        },
    ),
    (
        "consort",
        ["选妃", "选秀", "纳妃", "妃嫔"],
        {
            "kind": "accepted",
            "normalized_goal": "遴选秀女",
            "tags": ["court"],
            "policy_effect": {"people": 0, "treasury": -1, "grain": 0},
            "advisor": "选秀女的事已经传开了。不过眼下灾情还没过去,大家更盼着陛下多操心政务、体恤百姓。",
            "reactions": [
                {"speaker": "gu_tingzhang", "text": "宫里的花销定好规矩,才不会打扰地方。"},
                {"speaker": "tian_bo", "text": "宫里的事俺们不懂,只盼别为这个加派差役。"},
            ],
            "new_echoes": [],
            "summary": "宫里多了规矩,大家都在看。",
        },
    ),
]


def _echo_effect_for(echo: dict) -> dict:
    stable_key = f"{echo['created_turn']}|{echo['due_turn']}|{echo['reason']}"
    digest = hashlib.sha256(stable_key.encode("utf-8")).digest()
    people = (digest[0] % 5) - 2
    treasury = (digest[1] % 3) - 1
    grain = (digest[2] % 3) - 1
    return {
        "echo_id": echo["id"],
        "people": people,
        "treasury": treasury,
        "grain": grain,
        "explanation": f"这是旧诏书「{echo['reason']}」留下的回响(演示模式)。",
    }


def _accepted_with_echoes(payload: dict, context: ModelContext) -> AcceptedCandidate:
    payload = dict(payload)
    payload["echo_effects"] = [
        _echo_effect_for(e) for e in context.due_echoes
    ]
    if context.turn_no >= 8:
        payload["new_echoes"] = []
    elif context.turn_no == 7:
        payload["new_echoes"] = [
            e for e in payload["new_echoes"] if e["delay"] == 1
        ]
    return AcceptedCandidate.model_validate(payload)


class FixtureAdapter:
    def evaluate(self, context: ModelContext) -> Candidate:
        text = context.player_policy

        for keyword in ANACHRONISM_KEYWORDS:
            if keyword in text:
                return ClarificationCandidate(
                    kind="clarification",
                    warning_type="anachronism",
                    message="陛下,诏中所言之物,臣与满朝官吏都从未听闻,非大晟所有。请陛下收回此诏,改以本朝可行之事示下。",
                )

        goal_count = sum(
            any(keyword in text for keyword in keywords)
            for keywords in INDEPENDENT_GOALS.values()
        )
        if goal_count > 1:
            return ClarificationCandidate(
                kind="clarification",
                warning_type="multiple_goals",
                message="陛下,这几件事各有牵连,请先选定本回合最要紧的一件,臣再照旨拟办。",
            )

        if _is_not_policy(text):
            return ClarificationCandidate(
                kind="clarification",
                warning_type="not_policy",
                message="陛下,这些话并不是一道要施行的政令。请陛下示下一件要办的事,臣才能拟旨。",
            )

        if any(phrase in text for phrase in UNCLEAR_PHRASES) or not any(
            char.isalpha() for char in text
        ):
            return ClarificationCandidate(
                kind="clarification",
                warning_type="unclear",
                message="陛下,臣实在看不出要办什么事。请陛下把心中所想重新说明白,臣再照旨拟办。",
            )

        matched = [
            candidate
            for _key, keywords, candidate in CATEGORIES
            if any(k in text for k in keywords)
        ]
        if not matched:
            return _accepted_with_echoes(FEASIBILITY_FALLBACK, context)

        return _accepted_with_echoes(matched[0], context)
