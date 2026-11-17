"""Narration is downstream of settlement; unsafe prose is never committed."""
import re
from .policies import limit_monitoring_echoes


def _has_affirmative_burden(line: str) -> bool:
    for clause in re.split(r'[，,。；;！!\n]|但是|然而|不过|但|却|而',line):
        if not re.search(r'代垫|摊派|加派',clause):continue
        if re.search(r'若|倘|可能|恐怕|建议|请陛下|此前|旧政',clause):continue
        # Do not let an outer denial of a denial hide an actual claim.
        clause=re.sub(r'(?:并非|不是|并不是|不代表|不等于|不能说|不得说)(?:没有|并未|未曾|未|不曾|不再|无需|不需|无须|不)[^，,。；;]{0,18}?(代垫|加派|摊派)',r'\1',clause)
        denial=r'(?:未曾|并未|没有|不曾|无需|不需|无须|不得|禁止|不再|不另|不向|不让|不由|不使|不要求|免于|未|不(?=加|摊|代))[^，,。；;]{0,18}?(?:代垫|摊派|加派)'
        affirmative=re.sub(denial,'',clause)
        if re.search(r'代垫|摊派|加派',affirmative):
            return True
    return False


def unapproved_burden_claims(policy_text: str, analysis: dict) -> list[str]:
    """Check each assertion separately; a denial is not a new levy."""
    from .policy_actions import operative_text
    if _has_affirmative_burden(operative_text(policy_text)):
        return []
    if any(_has_affirmative_burden(line) for line in analysis.get('benefits',[])+analysis.get('costs',[])):
        return ['未授权的民间代垫、加派或摊派不能写成已经发生；按国库实际支出说明成本']
    return []


def narration_errors(data: dict, facts: dict) -> list[str]:
    """Check public prose against settled facts, without writing character lines."""
    errors = []
    errors.extend(prose_errors(data, facts["intent"]))
    if facts.get('original_goal'):
        errors.extend(unapproved_burden_claims(facts['original_goal'],data.get('policy_analysis',{})))
    if facts.get('original_goal'):
        from .policy_actions import action_categories
        allowed=action_categories(facts['original_goal'])
        if 'relief' not in allowed:
            statements=[data['advisor'],data['summary'],*(r['text'] for r in data['reactions']),
                *data.get('policy_analysis',{}).get('benefits',[]),*data.get('policy_analysis',{}).get('costs',[])]
            for line in statements:
                for sentence in re.split(r'[，,。；;！!\n]',line):
                    if re.search(r'旧政|旧诏|此前|先前|若|倘|可能|建议|请陛下|尚未|未能|并未|没有',sentence):continue
                    if re.search(r'(?:已|已经|现已|完成|落实|得以).{0,8}(?:赈济|安置|发粮|放粮)|(?:赈济|安置灾民|发粮|放粮).{0,8}(?:完成|到位|落实)|灾民.{0,6}(?:得到|获得|已获)(?:了)?.{0,4}(?:粮食|安置|赈济)',sentence):
                        errors.append('本诏未授权发粮或安置，减税缓灾不等于已经赈济、发粮或安置灾民')
    battle=facts.get('war')
    if battle:
        expected='获胜' if battle['outcome']=='victory' else '战败'
        if expected not in data['summary']:
            errors.append('战役已结算，summary必须明确写此役'+expected)
        for text in (data['summary'],data['advisor'],*(r['text'] for r in data['reactions'])):
            if re.search(r'天下(?:平稳|太平|无事)|四海无事',text):errors.append('已有战事，不能说天下平稳；没有新国运事件不等于没有战争')
            if re.search(r'胜率|胜算.{0,6}(?:成|%|％|百分)|无战事结算|军未接仗|尚未交战|尚未开战|未发生战斗',text):
                errors.append('战报不显示胜率；本役已经实际交战并结算，不得叙述无战事')
            if battle.get('negotiation_status')=='enemy_attacking' and re.search(r'敌使(?:已)?提出|对方(?:已)?提出.{0,5}(?:和议|议和|赔款)|已停战|现已停战',text):
                errors.append('敌军继续进攻，没有新和议提案或停战事实')
            if re.search(r'军势未定|胜负未分|战果未定|战局未定',text):
                errors.append('本役胜负已由规则确定，不得模糊战果')
            if not battle['ceded_city'] and re.search(r'已割|已(?:经)?割让|已献城|已献地',text):
                errors.append('本役未割城，不得虚构割地')
            if not battle['collapsed'] and not facts.get('ending') and re.search(r'本朝(?:已)?覆亡|本朝(?:已)?灭亡|敌军破都',text):
                errors.append('本朝未亡，不得虚构亡国')
    treaty=facts.get('treaty')
    if treaty and treaty['status']!='accepted':
        for text in (data['summary'],data['advisor'],*(r['text'] for r in data['reactions'])):
            assertion=re.sub(r'(?:尚未|并未|未曾|不得|不能|不可)[^。；]*','',text)
            if re.search(r'已(?:经)?(?:割让|割城|献地|赔付|赔款|签约|签订和约)|和约已(?:定|成|生效)|两国已(?:经)?停战',assertion):
                errors.append('和约尚未履约，不能叙述已割地赔款或已签约停战')
    if facts.get('opening_repair') is not None:
        for text in (data['summary'],data['advisor'],*(r['text'] for r in data['reactions'])):
            unresolved=re.search(r'(?:开局短板|开局旧患|旧患|旧疾).{0,8}(?:未化解|未解决|未修复|尚未改善)',text)
            resolved=re.search(r'(?:开局短板|开局旧患|旧患|旧疾).{0,8}(?:已化解|已解决|已修复|已改善)',text)
            if facts['opening_repair'] and unresolved or not facts['opening_repair'] and resolved:
                errors.append('开局旧患修复叙事须与opening_repair的唯一国情判断一致')
    if facts.get('execution_required'):
        # Advice may discuss costs, but must not silently veto an accepted edict.
        refusal = r'未新动|未获新进展|未获进展|未动工|尚未动工|未开工|尚未开工|未予执行|未予施行|暂不执行|暂不施行|未执行|未施行|仅作议论|未曾出兵|尚未出兵|(?:之议|此诏|圣旨|亲征|工程).{0,8}(?:宜缓|暂缓|搁置|不予执行)'
        for text in (data['summary'], data['advisor']):
            if re.search(refusal, text):
                errors.append('此诏已经核定执行，人物不能擅自停工、缓办或改诏；须叙述原诏实际执行与得失，劝谏不能替代执行')
    if facts.get("realm") is not None:
        declared = facts.get("ending") or {}
        claims = {"civil": r"民变(?:已|已经)?(?:爆发|蔓延|四起)|民变已起", "army": r"兵变(?:已|已经)?(?:爆发|发生)|军队哗变",
                  "border": r"边疆(?:已|已经)?失守|边防全线崩溃", "bankruptcy": r"朝廷(?:已|已经)?破产|国库破产"}
        for text in (data["summary"], data["advisor"], *(r["text"] for r in data["reactions"])):
            for sentence in re.split(r"[。；;]", text):
                assertion = re.split(r"若|倘|可能|恐|尚未|未曾|避免|防止", sentence, maxsplit=1)[0]
                for key, pattern in claims.items():
                    if key != declared.get("kind") and re.search(pattern, assertion):
                        errors.append("危机尚未被核定为该结局，不得将预警写成已经发生的灾变")
    _, monitoring_notes = limit_monitoring_echoes(facts.get("history", []), facts["intent"], facts.get("original_goal", ""), data.get("new_echoes", []))
    if monitoring_notes:
        errors.append("最终奏报不得把已收束的同因监督失灵重新写成新增后患")
    speakers = [r["speaker"] for r in data["reactions"]]
    if set(speakers) != {"tian_bo", "song_zhiyuan", "gu_tingzhang"} or len(speakers) != 3:
        errors.append("田伯、宋知远、顾廷章须各回应一次")
    if len({r["text"].strip() for r in data["reactions"]}) != 3:
        errors.append("三位人物不可使用同一句回应")
    old_lines = {r["text"].strip() for item in facts.get("history", []) for r in item.get("reactions", [])}
    canned = ("乡亲们只按实际办到的事看成效", "地方依核定范围办理，旧令若已停下")
    if any(r["text"].strip() in old_lines or any(line in r["text"] for line in canned) for r in data["reactions"]):
        repeated=[f"{r['speaker']}：{r['text'][:100]}" for r in data['reactions'] if r['text'].strip() in old_lines or any(line in r['text'] for line in canned)]
        errors.append("须按本次圣旨及人物处境重新回应，不可照抄旧言或使用通用模板。必须重写这些原句："+'；'.join(repeated))
    texts = [data["advisor"], data["summary"], *(r["text"] for r in data["reactions"]),
             *(e["explanation"] for e in data["echo_effects"]), *(e["reason"] for e in data["new_echoes"])]
    analysis = data.get("policy_analysis", {})
    texts += [*analysis.get("benefits", []), *analysis.get("costs", []), analysis.get("effect_basis", "")]
    text = "\n".join(texts)
    errors.extend(settled_prose_errors(data, facts))
    affirmative = re.sub(r"(?:不得|不能|未能|没有|尚未|未|不曾|并无|尚无|无)[^。；;！!\n]*", "", text)
    affirmative = re.sub(r"(?:若|倘|如能|原本|本可)[^。；;！!\n]*", "", affirmative)
    if facts.get("blocked"):
        if not re.search(r"未能|未发|未办|暂缓|停工|无力|无粮|空仓|不足|无米|未.*赈", data["advisor"] + data["summary"]):
            errors.append("须明确本次所需资源不足、政令未实际施行")
        unsupported = re.search(r"领到[^。；;，,\n]*粮|收到[^。；;，,\n]*赈粮|已[^。；;，,\n]{0,16}(?:发粮|放粮|赈济|赈粮)|调来[^。；;，,\n]*粮|另[^。；;，,\n]*仓[^。；;，,\n]*粮|(?:仓底|余粮).{0,12}(?:散|发|给|调)|(?:动用|搜集|聚拢).{0,8}(?:仓底|余粮)|邻近调拨|酌量散给|工程[^。；;，,\n]*(?:告竣|完工)", affirmative)
        if unsupported:
            errors.append(f"资源不足时不得声称本次发粮或工程成功，不得虚构外部仓粮：'{unsupported[0]}'")
    if any(item.get("policy_status") in ("revoked", "suspended") for item in facts.get("history", [])) and facts["intent"]["category"] != "relief":
        if re.search(r"恢复赈|重启赈|重新发粮|继续发粮", affirmative):
            errors.append("本次未授权恢复赈济，不得借人物或回声恢复旧令")
    if any("未解付" in note for note in facts.get("constraint_notes", [])):
        if re.search(r"尽数(?:解|送|发|拨)|全部(?:送|发|调|拨)|悉数(?:送|发|拨)", affirmative):
            errors.append("单回合支出封顶后仍有留存，不能写全部钱粮已送出")
    return errors


def settled_prose_errors(data: dict, facts: dict) -> list[str]:
    """Check net statements against net deltas and each echo against its own delta."""
    errors = []
    before, after = facts.get("before"), facts.get("after")
    if not before or not after:
        return errors
    metrics = {"people": "民心", "treasury": "国库|库藏|库银", "grain": "粮储|仓粮|存粮"}
    def check(text, changes, component=False):
        for sentence in re.split(r"[。；;！!\n]", text):
            sentence = re.split(r"若|倘|可能|恐怕|预期|预计|有望|尚未|未能|不曾", sentence, maxsplit=1)[0]
            for clause in re.split(r"[，,]", sentence):
                if not component and re.search(r"新政|本项|此政|旧政|后效|单看", clause):
                    continue
                for key, names in metrics.items():
                    match = re.search(rf"(?:{names})(?:已|略|稍|微|有所|略有|稍有|仍|却|反而|持续|总体|净|小幅|大幅|显著|逐渐|趋于|继续|回合内|本次)*\s*(上升|升|增加|增长|回升|增|下降|降|减少|下滑|减|持平|不变)", clause)
                    if match:
                        direction = match[1]
                        positive = direction in ("上升", "升", "增加", "增长", "回升", "增")
                        neutral = direction in ("持平", "不变")
                        delta = changes[key]
                        if (neutral and delta != 0) or (not neutral and (delta <= 0 if positive else delta >= 0)):
                            errors.append(f"'{match[0]}'与实际{key}变化{delta}不符，须依核定变化改写")
    changes = {key: after[key] - before[key] for key in metrics}
    for text in (data["advisor"], data["summary"], *(r["text"] for r in data["reactions"]), data.get("policy_analysis", {}).get("effect_basis", "")):
        check(text, changes)
    actual_echoes = {e["echo_id"]: e for e in facts.get("actual_echo_effects", [])}
    for echo in data.get("echo_effects", []):
        if echo["echo_id"] in actual_echoes:
            check(echo["explanation"], actual_echoes[echo["echo_id"]], True)
    public = [data["advisor"], data["summary"], *(r["text"] for r in data["reactions"]),
              *(e["explanation"] for e in data.get("echo_effects", [])),
              *data.get("policy_analysis", {}).get("benefits", []), *data.get("policy_analysis", {}).get("costs", []),
              data.get("policy_analysis", {}).get("effect_basis", "")]
    if after["grain"] > 0:
        for text in public:
            for sentence in re.split(r"[。；;！!\n]", text):
                sentence = re.split(r"若|倘|可能|恐|未至|并非|不是|不等于|此前|原先|先前|曾经|一度", sentence, maxsplit=1)[0]
                if re.search(r"(?:官仓|仓中|仓内|粮仓|仓粮|存粮|粮储|地方仓储)(?:已|现已|既|全|尽|皆|告|已告|中|亦|随之)*\s*(?:无粮|空空|为空|空了|空|耗尽|见底|告罄)|无粮可发|无米可炊", sentence):
                    errors.append("实际粮储仍有留存，不得说官仓无粮；若只是缺银或存粮不足，应准确说明")
    if after['treasury'] >= 35:
        for text in public:
            for sentence in re.split(r'[。；;！!\n]',text):
                assertion=re.split(r'若|倘|可能|恐|并非|不是|此前|原先|曾经',sentence,maxsplit=1)[0]
                if re.search(r'(?:国库|府库|库帑)(?:已|现已|全|皆|告)?(?:空虚|空空|耗尽|告罄|无钱|无款)',assertion):
                    errors.append('实际库款仍在可用区间，不得宣称府库空虚或耗尽；只说明实际支出与取舍')
    return errors


def prose_errors(data: dict, intent: dict) -> list[str]:
    texts = [data["advisor"], data["summary"], *(r["text"] for r in data["reactions"]),
             *(e["explanation"] for e in data["echo_effects"]), *(e["reason"] for e in data["new_echoes"])]
    errors = []
    analysis = data.get("policy_analysis", {})
    texts += [*analysis.get("benefits", []), *analysis.get("costs", []), analysis.get("effect_basis", ""),
              *(s for r in analysis.get("risks", []) for s in (r["condition"], r["consequence"]))]
    number = r"[\d一二三四五六七八九十百千万两]+"
    for index, text in enumerate(texts):
        assertion=re.split(r'若|可能|并非|不等于|不得',text,maxsplit=1)[0]
        population_text=re.sub(r'(?:不是|不等于|不代表|并非|不能说)[^。；]*','',text)
        if re.search(r'(?:人口|人丁|民数).{0,8}(?:增长|增加|增|升|下降|减少|减|繁盛|兴旺|恢复|多了|渐多|回升|凋零)',population_text) or re.search(r'民心.{0,8}(?:就是|是|代表|即).{0,4}(?:人口|人丁)',population_text):
            errors.append('不能把民心变化写成人口或人丁增长；没有人口指标')
        if re.search(r'(?:民心|民意|人心|国库|粮储).{0,16}(?:[一二三四五六七八九十两\d]+成|百分之|\d+%)',assertion):
            errors.append('抽象指数的增减不能改写为几成或百分比')
        # No population counter exists; role prose must not invent one or
        # recast authoritative index changes as physical quantities/fractions.
        metric_number = re.search(r"(?:民心|民意|人心|民望|民力|民数|人口|人丁|国库|库银|库款|府库|仓储|粮储|仓粮|存粮|粮仓)(?:由|从|净|略|稍|已|现|升|增|降|减|上升|增加|下降|减少|至|到|有|余|为|余下|剩余|增至|减至|\s)*" + number, text)
        if metric_number:
            errors.append(f"文案{index}中的'{metric_number[0]}'把国情指数写成角色报数；只描述具体处境与得失，准确数值由结算表展示")
        era = re.search(r"去年|去岁|前两年|前年|来年|明年|今岁|今年", text)
        if era:
            errors.append(f"文案{index}用'{era[0]}'指代三年一回合，须改为明确年代或三年/六年")
        unit = re.search(number + r"\s*(?:万)?(?:石|贯|两银|银两)", text)
        score = re.search(r"(?:民心|国库|粮储|库藏).{0,10}?" + number + r"(?:分|点)", text)
        silver = re.search(r"(?:钱|库银|拨银|用银|花银|支银).{0,10}?" + number + r"两", text)
        inflated = re.search(r"(?:民心|国库|粮储|库藏|库银|钱粮)[^。；，,]{0,18}?[\d一二三四五六七八九十百两]+[万亿]", text)
        if unit or score or silver or inflated:
            match = unit or score or silver or inflated
            errors.append(f"文案{index}中的'{match[0]}'将抽象指数编成单位或角色分数，须改为具体处境的定性描述")
    text = "\n".join(texts)
    if intent.get("category") == "tax" and intent.get("magnitude") not in ("full", "unspecified"):
        # Preserve double negatives as affirmative exemption claims before
        # removing single denials. Never let an inner '非全免' hide '并非不全免'.
        tax_text = re.sub(r"(?:并非|不是|并不是|并不|不)(?:不|非)(?:全部)?(?:免除|免征|全免|免税)", "全免", text)
        tax_text = re.sub(r"(?:并不是|并非|而非|绝非|不是|并不|不予|没有|不得|不能|不可|未予|不再|取消|停止|未|非|不)(?:全部)?(?:免除|免征|全免|免税)", "", tax_text)
        tax_text = re.sub(r"(?:此前|原先|先前|旧令).{0,8}(?:免征|免除|免去|全免|免税)", "", tax_text)
        tax_text = re.sub(r"(?:停止|取消|撤销|终止|结束|不再)[^。；，,]{0,10}?(?:减免|免除|免征|全免|免税)", "", tax_text)
        tax_text = re.sub(r"(?:从|由)(?:原来|先前)?(?:免税|免征)", "", tax_text)
        exemption = re.search(r"免征|免除|免去|(?<!减)免[^。；，,]{0,6}田赋|全免|免税", tax_text)
        if exemption:
            errors.append(("圣旨要求恢复原税额，文案却变成免除" if intent.get("magnitude") == "restore" else "圣旨要求减征，文案却变成免除；须明示仍征收一部分") + f"：{exemption[0]}")
    return errors


def prose_is_safe(data: dict, intent: dict) -> bool:
    return not prose_errors(data, intent)


def factual_narration(data: dict, facts: dict) -> dict:
    """Conservative report for constrained execution, never a fixture success story."""
    result = dict(data)
    notes = facts["constraint_notes"]
    if facts["blocked"]:
        outcome = "所需钱粮不足，此诏未能实际施行，未发出赈粮，也未完成工程。"
    elif facts["intent"]["action"] in ("revoke", "suspend"):
        outcome = "所指旧令已停止后续执行；已经发生的影响仍须查考，不得另行续办。"
    elif any("不足" in note or "上限" in note for note in notes):
        outcome = "此诏按现有钱粮与旧政约束办理，未能全额达到原定目标；本次仅记实际可办部分。"
    elif any("同一政策" in note for note in notes):
        outcome = "同一政策此前已施行，此番继续办理，新增成效递减。"
    else:
        subject = {"relief": "赈济", "water": "水渠修护", "dike": "堤坝修护", "road": "道路修整"}.get(facts["intent"]["category"], "此诏")
        outcome = f"{subject}已按核定方案办理；钱粮收支及民情变化，以本次奏报所载实绩为准。"
    magnitude = facts["intent"].get("magnitude")
    if facts["intent"]["category"] == "tax" and not facts["blocked"]:
        tax_name = {"land_tax": "田赋", "trade_tax": "商税"}.get(facts["intent"].get("project"), "税赋")
        outcome = {"moderate": f"{tax_name}按温和减征办理，原诏未定比例，并非全部免除。", "half": f"{tax_name}按减半办理，并非全部免除。", "full": f"{tax_name}按原诏免除。", "unchanged": f"{tax_name}不再继续减征。", "restore": f"{tax_name}恢复原定税额征收。"}.get(magnitude, outcome)
    result["advisor"] = f"陛下，{outcome}旧政后果另行记载，未奉新诏，不擅增发钱粮。"
    result["summary"] = outcome
    result["reactions"] = [
        {"speaker": "tian_bo", "text": "乡亲们只按实际办到的事看成效，未办到的，还不能当作已经受惠。"},
        {"speaker": "gu_tingzhang", "text": "地方依核定范围办理，旧令若已停下，未奉新诏便不得续行。"},
    ]
    return result
