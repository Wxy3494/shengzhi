"""Version-two realm pressures and endings; all decisions are program-owned."""
import copy
import re

NAMES = {"civil": "民变", "army": "兵变", "border": "边疆失守", "bankruptcy": "破产"}
ADVICE = {"civil": "减轻民间负担，恢复生计和粮食供给。", "army": "改善钱粮供给，避免在困乏时继续动员军队。",
          "border": "补充边防钱粮，量力收缩战线。", "bankruptcy": "停止难以负担的支出，恢复财政收入。"}


def initial_realm():
    return {"version": 2, "notified": {k: [] for k in NAMES}, "pressures": {k: 0 for k in NAMES}, "sources": {k: [] for k in NAMES},
            "warnings": [], "military_engaged": False, "border_engaged": False,
            "reform_steps": 0, "reform_started": False, "reform_sources": [], "ending": None}


def ending(kind, title, text, status, turn, sources):
    return {"kind": kind, "title": title, "text": text, "status": status, "turn_no": turn,
            "source_turns": sorted(set(sources))}


def advance_realm(previous, after, intent, raw_text, blocked, notes, turn_no, base_status):
    realm = copy.deepcopy(previous or initial_realm())
    # Flags describe actual sustained commitments, not mere mention of a hazard.
    active = intent.get("action") not in ("revoke", "suspend") and not blocked
    operative = re.sub(r"(?:不得|不许|禁止|不再)[^，。；,;]*", "", raw_text)
    military = intent.get("category") in ("military", "defense")
    if active and military:
        realm["military_engaged"] = True
        if re.search("边|戍|关隘|远征|征伐|宣战|开战|用兵", operative):
            realm["border_engaged"] = True
    if (military and not active and not blocked) or (active and re.search("停战|罢兵|结束远征", operative)):
        realm["military_engaged"] = False
    reform = intent.get("category") == "reform" or bool(re.search("改革|变法|新法|改制", operative))
    if reform and active:
        realm["reform_started"] = True
        realm.setdefault("reform_sources", []).append(turn_no)
        if not any("同一政策" in note for note in notes):
            realm["reform_steps"] += 1
    people, treasury, grain = after.people, after.treasury, after.grain
    increments = {
        "civil": (35 if people <= 20 else 18 if people <= 35 else -20) + (10 if grain <= 10 else 0),
        "army": ((25 if treasury <= 10 else 0) + (15 if grain <= 10 else 0) + (10 if people <= 25 else 0) or -20) if realm["military_engaged"] else -20,
        "border": ((30 if grain <= 20 else 0) + (15 if treasury <= 20 else 0) or -20) if realm["border_engaged"] else -20,
        "bankruptcy": 35 if treasury == 0 else 20 if treasury <= 10 else -25,
    }
    reasons = {
        "civil": f"本回合末民心{people}、粮储{grain}，" + ("民生困局继续累积。" if increments["civil"] > 0 else "民间压力缓和。"),
        "army": f"军务动员{'仍在持续' if realm['military_engaged'] else '未持续'}，国库{treasury}、粮储{grain}，" + ("军中供给与承受压力加重。" if increments["army"] > 0 else "军中压力缓和。"),
        "border": f"边防战线{'已有持续承诺' if realm['border_engaged'] else '尚无持续承诺'}，国库{treasury}、粮储{grain}，" + ("边防供给不足。" if increments["border"] > 0 else "边防压力缓和。"),
        "bankruptcy": f"本回合末国库{treasury}，" + ("财政困局持续，仍须筹措恢复。" if increments["bankruptcy"] > 0 else "财政恢复，破产压力下降。"),
    }
    realm["warnings"] = []
    realm["version"] = 2
    notified = realm.setdefault("notified", {k: [] for k in NAMES})
    for key, inc in increments.items():
        old = realm["pressures"][key]
        value = max(0, min(100, old + inc))
        realm["pressures"][key] = value
        if inc > 0:
            realm["sources"][key].append(turn_no)
        if value == 0:
            realm["sources"][key] = []
        for threshold in (75, 90):
            sent = notified.setdefault(key, [])
            if value >= threshold and threshold not in sent:
                sent.append(threshold)
                realm["warnings"].append({"id": key, "threshold": threshold, "label": NAMES[key], "value": value,
                    "level": "critical" if threshold == 90 else "warning", "delta": value - old,
                    "reason": reasons[key], "advice": ADVICE[key], "source_turns": list(realm["sources"][key])})
    # Simultaneous disasters have one deterministic primary ending; all pressures remain visible.
    for key in ("civil", "army", "border", "bankruptcy"):
        if realm["pressures"][key] >= 100:
            texts = {"civil": "民间积怨与生计困境未能平复，民变蔓延，本朝统治告终。",
                     "army": "动员压力与军中供给危机累积，军心失控，兵变终结了本朝。",
                     "border": "边防承诺超出钱粮承受能力，战线失守，本朝未能渡过边疆危局。",
                     "bankruptcy": "财政困局持续而未获恢复，朝廷已难以维持运转，以破产收场。"}
            realm["ending"] = ending(key, NAMES[key], texts[key], "lost", turn_no, realm["sources"][key])
            return realm
    if base_status == "won":
        if realm["reform_steps"] >= 3:
            realm["ending"] = ending("reform_success", "改革中兴", "新法持续推进，民心归附，本朝走出了改革的险途。", "won", turn_no, realm.get("reform_sources", []))
        else:
            realm["ending"] = ending("peace", "承平之治", "民心归附，危机尚未酿成灾变，本朝渐入安定。", "won", turn_no, [])
    elif base_status == "lost":
        if realm["reform_started"]:
            realm["ending"] = ending("unfinished_reform", "改革未竟", "新法曾经启程，却未能在八回合内使民心归附，改革事业留待后来。", "lost", turn_no, realm.get("reform_sources", []))
        else:
            realm["ending"] = ending("mandate_lost", "民心未归", "八回合已尽，民心尚未归附，本朝未能达成安定。", "lost", turn_no, [])
    return realm
