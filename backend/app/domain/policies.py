"""Small policy ledger. Historical effects never grant permission to resume an order."""
import re


def identify(text: str, proposed: dict | None = None) -> dict:
    intent = dict(proposed or {})
    lower = text.lower()
    # A prohibition is not the governance target (e.g. policing, "不增税").
    operative = re.sub(r"(?:不准|不得|严禁|禁止|勿|不增|不征)[^，,。；;]*", "", lower)
    kinds = [
        ("water", r"水渠|沟渠|灌溉|修渠|疏浚|疏通.*渠"),
        ("dike", r"堤|坝"),
        ("tax", r"税|田赋|田賦|tax"),
        ("relief", r"赈|賑|放粮|开仓|粮仓|领.*粮"),
        ("road", r"官道|修路|驿道|驿站"),
    ]
    # Relief with accompanying tax relief remains one relief policy.
    if re.search(r"购粮|籴粮|买粮|采买.{0,4}粮|补仓|充实粮储", operative) and (re.search(r"补仓|入库|入仓|储备|粮储", operative) or not re.search(r"赈济|赈灾|放粮", operative)):
        intent["category"] = "grain_supply"
        intent["project"] = "grain_purchase"
    elif re.search(r"开仓|放粮|赈济|赈灾|賑災", operative):
        intent["category"] = "relief"
    else:
        for kind, pattern in kinds:
            if re.search(pattern, operative):
                intent["category"] = kind
                break
    intent.setdefault("category", "other")
    location = re.search(r"城[东西南北]|[东西南北]郊|灾州|災州|京畿", text)
    if location:
        intent["region"] = location[0].replace("災", "灾").replace("西郊", "城西").replace("东郊", "城东").replace("南郊", "城南").replace("北郊", "城北")
    intent.setdefault("region", "全境")
    if not intent.get("project") or (proposed and proposed.get("category") != intent["category"]):
        intent["project"] = "grain_purchase" if intent["category"] == "grain_supply" else intent["category"]
    if intent["category"] == "water" and re.search(r"水渠|沟渠|修渠", text):
        intent["project"] = "canal"
    if intent["category"] == "tax":
        intent["project"] = "trade_tax" if re.search(r"商税|商賦|trade tax", lower) else "land_tax" if re.search(r"田税|田赋|land tax", lower) else (intent.get("project") or "tax")
    intent.setdefault("action", "enact")
    # Withdrawing a sentence/charge is a new justice policy, not revoking a
    # previous edict. Only explicit order references override the model action.
    if re.search(r"撤令|(?:撤销|废止|收回|撤回).{0,24}(?:诏|令|政策)|revoke.{0,20}(?:edict|policy|order)", operative):
        intent["action"] = "revoke"
    elif re.search(r"暂停|停发|停止.*赈|不得继续赈|suspend", lower):
        intent["action"] = "suspend"
    elif re.search(r"恢复|重新启用|resume", operative):
        intent["action"] = "resume"
    elif re.search(r"维护|岁修|再疏浚|再清|同一段|maintain", lower):
        intent["action"] = "maintain"
    if intent["category"] == "tax":
        if re.search(r"恢复(?:原|旧|正常|原有|原定).{0,6}(?:税|田赋)|恢复.{0,4}(?:原税额|原额征收)|按原额征收", operative):
            intent["magnitude"] = "restore"
            intent["action"] = "enact"
            intent["execution_default"] = "恢复原定税额征收，不是免税，也不是重新执行旧减免令。"
        elif re.search(r"不再减|不得减|停止减", lower):
            intent["magnitude"] = "unchanged"
        elif re.search(r"全免|免除|免去|免.*田赋|exempt|waive", lower) and not re.search(r"不得.*免|不.*全免|不要.*免", lower):
            intent["magnitude"] = "full"
        elif re.search(r"减半|一半|half|50%", lower):
            intent["magnitude"] = "half"
        elif re.search(r"减|少收|降低|reduce|lower", lower):
            intent["magnitude"] = "moderate"
    intent.setdefault("magnitude", "unspecified")
    intent.setdefault("duration_years", None)
    intent.setdefault("prohibitions", [])
    if intent["category"] == "tax" and intent["magnitude"] == "moderate":
        intent["execution_default"] = "原诏未指定比例，按温和减征办理，并非全部免除。"
    return intent


def limit_monitoring_echoes(history: list[dict], intent: dict, text: str, echoes: list[dict]) -> tuple[list[dict], list[str]]:
    """One supervision-breakdown event per domain/region; other consequences survive."""
    if not echoes:
        return [], []
    def topic(raw, policy):
        for domain, pattern in (("grain", "粮|仓|赈"), ("tax", "税|赋"), ("works", "工役|工程|渠|堤|筑"), ("trade", "商|市舶")):
            if re.search(pattern, raw):
                return domain, policy.get("region", "全境")
        return policy.get("project") or policy.get("category"), policy.get("region", "全境")
    def failure(reason):
        breakdown = "失效|失灵|流于形式|徇私|舞弊|贪墨|勾结|瞒报|敷衍|失察|规避|形同虚设|串通|侵吞"
        cleaned = re.sub(r"(?:未见|没有|并无|防止|减少|杜绝|遏制|避免|防范|抑制).{0,5}(?:" + breakdown + ")", "", reason)
        return bool(re.search("监督|监察|稽核|巡查|核查|查账|督办|审计", reason) and re.search(breakdown, cleaned))
    repeated = any(topic(item["raw_text"], item.get("policy_intent") or identify(item["raw_text"])) == topic(text, intent)
                   and any(failure(e["reason"]) for e in item.get("new_echoes", [])) for item in history if item.get("raw_text") and item.get("new_echoes"))
    kept = [e for e in echoes if not (repeated and failure(e["reason"]))]
    notes = ["同一领域的监督失灵已有后患记录，本次不再新增同因后患；既有后果仍照常查考，有效补救应体现改善。"] if len(kept) != len(echoes) else []
    return kept, notes


def same_scope(a: dict, b: dict) -> bool:
    if a.get("category") == "tax" and a.get("project") != b.get("project"):
        return False
    return a.get("category") != "other" and a.get("category") == b.get("category") and a.get("region", "全境") == b.get("region", "全境")


def transition(history: list[dict], intent: dict, turn_no: int) -> tuple[list[dict], list[str]]:
    ledger = [dict(item) for item in history]
    notes = []
    for item in ledger:
        old = item.get("policy_intent") or identify(item["raw_text"])
        item["policy_intent"] = old
        item.setdefault("policy_status", "active")
        duration = old.get("duration_years")
        if duration and (turn_no - item["turn_no"]) * 3 >= duration and item["policy_status"] == "active":
            item["policy_status"] = "completed"
    if intent["action"] in ("revoke", "suspend", "resume"):
        matches = [item for item in ledger if same_scope(item["policy_intent"], intent)]
        # An explicit reference to the previous edict can omit its object/region.
        if not matches and intent["category"] == "other" and ledger:
            matches = [ledger[-1]]
        for item in matches:
            item["policy_status"] = {"revoke": "revoked", "suspend": "suspended", "resume": "active"}[intent["action"]]
            label = {"revoked": "撤销", "suspended": "暂停", "active": "恢复执行"}[item["policy_status"]]
            notes.append(f"第{item['turn_no']}回合旧令现为{label}；已经发生的后果保留，后续执行以本次授权为准。")
    return ledger, notes
