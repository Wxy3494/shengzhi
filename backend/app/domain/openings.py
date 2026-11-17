"""Six budget-balanced openings and finite, recoverable policy context."""
import copy
import secrets
import re


def scenario(id, name, treasury, grain, background, advantage, difficulty, categories, words, cost):
    return {"id": id, "name": name, "initial": {"people": 50, "treasury": treasury, "grain": grain},
            "background": background, "advantage": advantage, "difficulty": difficulty,
            "categories": categories, "words": words, "cost_resource": cost, "active_until_turn": 2}


SCENARIOS = [
    scenario("dry_fields", "旱后待苏", 65, 55, "先帝末年旱情反复，田渠淤塞。新君继位，朝廷尚有积蓄，乡里正盼恢复耕作。",
             "库款较足，乡民愿意协力修复水利。", "农渠失修，恢复田间生产尚需施政。", ["water", "dike"], ["修渠", "水利", "修堤", "疏浚"], "treasury"),
    scenario("trade_routes", "商路待通", 70, 50, "前朝经营商埠，库藏稍丰，近来道路梗阻，农货与粮运却不够顺畅。",
             "商帮网络尚在，恢复流通可较快惠及民间。", "商路梗阻，粮食转运未畅。", ["road", "trade"], ["通商", "商路", "关卡", "市舶", "修路"], "grain"),
    scenario("border_recovery", "边地初定", 65, 55, "边地战事方歇，军民都盼安定。朝廷还有周转之资，戍卒安置与边地生计尚待恢复。",
             "边地人心思定，妥善安军可减少后续纷扰。", "军民安置未稳，军需与生计仍须照料。", ["military", "defense"], ["军饷", "安置戍", "安置军", "屯田", "抚恤"], "treasury"),
    scenario("full_granaries", "仓丰库紧", 50, 70, "前朝丰收后收储较多，又因连年修缮支用库款。如今粮仓可用，财政调度却偏紧。",
             "粮储充裕，恢复生产与流通有周转余地。", "财政收入与支出未理顺。", ["tax", "finance", "trade"], ["税额", "征税", "商税", "增收", "财政"], "grain"),
    scenario("official_cleanup", "吏治待清", 60, 60, "王朝田里与库仓尚称平稳，前朝留下的账册和官吏考核却颇多积弊。百姓盼新君整顿政务。",
             "钱粮配置均衡，地方尚有配合整顿的基础。", "账册混乱，吏治积弊尚待查清。", ["justice", "administration", "oversight"], ["查账", "吏治", "清查", "考课", "贪墨", "整顿官"], "treasury"),
    scenario("unfinished_edicts", "新政待续", 55, 65, "先帝曾议兴学与厘定新法，尚未配齐施行办法便已驾崩。士民有所期待，朝廷须决定如何接续。",
             "粮储稍宽，士民对切实可行的新政抱有期待。", "旧有新政缺乏落实配套。", ["reform", "education"], ["新法", "变法", "改革", "兴学", "学校", "科举"], "grain"),
]


def choose_opening():
    return copy.deepcopy(secrets.choice(SCENARIOS))


def initial_conditions(opening):
    return {"resolved": False, "resolved_turn": None, "bonus_used": False, "active_until_turn": opening["active_until_turn"]}


def relevant(opening, intent, text):
    operative = re.sub(r"(?:不得|不许|不准|禁止|停止|不再|勿)[^，。；,;]*", "", text)
    if opening["id"] == "official_cleanup" and re.search(r"(?:禁止|不得|不许)(?:官员|官吏|吏员)?(?:贪墨|舞弊|勒索|瞒报)", text):
        operative = text  # Banning misconduct is a positive governance measure.
    return bool(operative.strip("，。；,; ")) and intent.get("action") not in ("revoke", "suspend") and not any(w in text for w in ("拆毁", "焚毁", "破坏")) and (
        intent.get("category") in opening["categories"] or any(w in operative for w in opening["words"]))


def opening_effect(opening, conditions, intent, text, turn, before, effect):
    adjusted = dict(effect)
    if not opening or not conditions or conditions.get("resolved") or conditions.get("bonus_used") or turn > conditions["active_until_turn"]:
        return adjusted, []
    cost = opening["cost_resource"]
    if relevant(opening, intent, text) and 0 < effect["people"] < 8 and all(getattr(before, d) >= max(0, -effect[d]) + 1 for d in ("treasury", "grain")):
        adjusted["people"] += 1
        adjusted[cost] -= 1
        return adjusted, [f"开局国情「{opening['name']}」的前期协作机会：民心候选收益增加1，另用{'库款' if cost == 'treasury' else '粮储'}指数1；最终仍受实际存量与回合上限约束。"]
    return adjusted, []


def advance_conditions(opening, previous, intent, text, actual, blocked, turn, modifier_applied):
    if not opening:
        return None
    result = copy.deepcopy(previous or initial_conditions(opening))
    if modifier_applied and not blocked:
        result["bonus_used"] = True
    improved = actual["treasury"] > 0 if opening["id"] == "full_granaries" else any(actual[d] > 0 for d in ("people", "grain"))
    if not blocked and improved and relevant(opening, intent, text) and not result["resolved"]:
        result.update(resolved=True, resolved_turn=turn)
    return result
