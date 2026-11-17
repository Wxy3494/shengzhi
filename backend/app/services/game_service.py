import hashlib
import logging
import json
import re
import sqlite3
import threading
import uuid
import time

from ..domain import settlement
from ..domain import events
from ..domain import war
from ..domain import treaties
from ..domain.order_plan import plan_order
from ..domain.crises import initial_realm, advance_realm
from ..domain.crisis_v3 import initial_crisis,advance_crisis,public_crisis,finish_events
from ..domain.openings import choose_opening, initial_conditions, opening_effect, advance_conditions
from ..domain.policies import identify, transition, limit_monitoring_echoes
from ..domain.narration import factual_narration, narration_errors, prose_is_safe
from ..domain.models import GameState, period_name
from ..domain.emperors import CATALOG_VERSION, EMPERORS, EMPEROR_BY_ID
from ..llm.base import LlmAdapter, ModelContext, ModelOutputInvalid, ModelTimeout, ModelUnavailable
from ..llm.schema import ClarificationCandidate, candidate_to_dict
from ..storage.sqlite import Database, utcnow

MAX_POLICY_CHARS = 500
logger = logging.getLogger(__name__)
EVENTS_DEFAULT = True


class ServiceError(Exception):
    def __init__(self, code: str, message: str, status_code: int, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.retryable = retryable


def _request_hash(policy_text: str, expected_revision: int) -> str:
    digest = hashlib.sha256(f"{expected_revision}|{policy_text}".encode("utf-8"))
    return digest.hexdigest()


def _game_view(row: dict) -> dict:
    view = {
        "id": row["id"],
        "schema_version": row["schema_version"],
        "revision": row["revision"],
        "accepted_turns": row["accepted_turns"],
        "status": row["status"],
        "people": row["people"],
        "treasury": row["treasury"],
        "grain": row["grain"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "realm": json.loads(row.get("realm_json") or "{}") if row["schema_version"] >= 2 else None,
        "ending": json.loads(row.get("realm_json") or "{}").get("ending") if row["schema_version"] >= 2 else None,
        "opening": json.loads(row.get("opening_json") or "{}") or None,
        "conditions": json.loads(row.get("conditions_json") or "{}") or None,
        "events": events.public_events(json.loads(row.get("events_json") or "{}")),
        "diplomacy": json.loads(row.get('diplomacy_json') or '{}'),
    }
    if row['schema_version'] >= 4:
        engine=json.loads(row.get('events_json') or '{}')
        if engine.get('initial_state') and view['conditions'] is not None:
            resolved=events.repaired_weakness(engine['initial_state'],{d:row[d] for d in events.DIMS})
            view['conditions']={**view['conditions'],'resolved':resolved,
                'resolved_turn':view['conditions'].get('resolved_turn') if resolved else None,'basis':'国情快照'}
        crisis=json.loads(row.get('realm_json') or '{}')
        view['realm'] = public_crisis(crisis)
        appraisal = view['events']['appraisal'] if view['events'] else None
        view['ending'] = ({'kind':'mandate','title':appraisal['title'],
            'text':'八回合已尽，依民心与应变实绩立论。','status':row['status'],
            'turn_no':8,'source_turns':list(range(1,9))} if appraisal else None)
        war_ending = json.loads(row.get('events_json') or '{}').get('war',{}).get('ending')
        if war_ending: view['ending'] = war_ending
        elif crisis.get('version')==3 and crisis.get('ending'):view['ending']=crisis['ending']
    if row['schema_version']>=4:
        view['diplomacy']['pending']=json.loads(row.get('events_json') or '{}').get('war',{}).get('pending_treaty')
    else:
        view['diplomacy']['pending']=view['diplomacy'].get('engine',{}).get('war',{}).get('pending_treaty')
        diplomacy_ending=view['diplomacy'].get('engine',{}).get('war',{}).get('ending')
        if diplomacy_ending:view['ending']=diplomacy_ending
    return view


def _echo_view(row: dict) -> dict:
    return {
        "id": row["id"],
        "source_policy_id": row["source_policy_id"],
        "due_turn": row["due_turn"],
        "reason": row["reason"],
        "status": row["status"],
        "created_turn": row["created_turn"],
        "resolved_turn": row["resolved_turn"],
        "effect_kind": row.get("effect_kind", "consequence"),
    }


class GameService:
    def __init__(self, db: Database, adapter: LlmAdapter, opening_factory=None, events_enabled=None) -> None:
        self.db = db
        self.adapter = adapter
        self.opening_factory = opening_factory
        self.events_enabled = EVENTS_DEFAULT if events_enabled is None else events_enabled
        self._emperor_locks: dict[str, threading.Lock] = {}
        self._emperor_lock_guard = threading.Lock()
        self._retry_candidates={}
        self._retry_cache_lock=threading.Lock()

    def create_game(self, seed=None) -> dict:
        game_id = uuid.uuid4().hex
        now = utcnow()
        initial = settlement.initial_state()
        seed = seed or uuid.uuid4().hex
        opening = events.seeded_opening(seed) if self.events_enabled else (self.opening_factory or choose_opening)()
        event_state = events.initial_events(seed, opening) if self.events_enabled else None
        if opening:
            initial = GameState(**opening["initial"])
        game = {
            "id": game_id,
            "schema_version": 4 if self.events_enabled else 3 if opening else 2,
            "revision": 0,
            "accepted_turns": 0,
            "status": "playing",
            "people": initial.people,
            "treasury": initial.treasury,
            "grain": initial.grain,
            "created_at": now,
            "updated_at": now,
        }
        with self.db.transaction() as conn:
            self.db.insert_game(conn, game)
            self.db.save_realm(conn, game_id, initial_crisis() if self.events_enabled else initial_realm())
            if opening:
                self.db.save_opening(conn, game_id, opening, initial_conditions(opening))
            if event_state:
                self.db.save_events(conn, game_id, event_state)
        return self._detail(game_id)

    def _detail(self, game_id: str) -> dict | None:
        row = self.db.get_game(game_id)
        if row is None:
            return None
        return {
            "game": _game_view(row),
            "history": self.db.get_history(game_id),
            "echoes": [_echo_view(e) for e in self.db.get_echoes(game_id)],
        }

    def get_game_detail(self, game_id: str) -> dict | None:
        return self._detail(game_id)

    def generate_opening_briefing(self, game_id: str) -> dict:
        with self._emperor_lock_guard:
            lock = self._emperor_locks.setdefault("opening:" + game_id, threading.Lock())
        with lock:
            game = self.db.get_game(game_id)
            if game is None:
                raise ServiceError("GAME_NOT_FOUND", "未找到该局存档。", 404)
            opening = json.loads(game.get("opening_json") or "{}")
            if not opening:
                raise ServiceError("NO_OPENING", "本局为旧规则存档，没有随机开局奏报。", 409)
            cached = json.loads(game.get("briefing_json") or "{}")
            if cached:
                return cached
            try:
                if callable(getattr(self.adapter, "brief_opening", None)):
                    text = self.adapter.brief_opening(opening)
                    source = "model"
                else:
                    text = f"陛下，臣谨奏国情：{opening['background']} {opening['advantage']} {opening['difficulty']} 请陛下审势下诏，量力施行。"
                    source = "fixture"
                response = {"game_id": game_id, "briefing": text, "source": source}
                with self.db.transaction() as conn:
                    self.db.save_briefing(conn, game_id, response)
                return response
            except ModelTimeout as exc:
                raise ServiceError("MODEL_TIMEOUT", "开场奏报暂未送达，国情已保存，可重试。", 504, True) from exc
            except (ModelOutputInvalid, ModelUnavailable, ValueError) as exc:
                raise ServiceError("MODEL_OUTPUT_INVALID", "开场奏报未能完成，国情不变，可重试。", 502, True) from exc
            except sqlite3.Error as exc:
                raise ServiceError("SAVE_FAILED", "开场奏报保存失败，可重试。", 500, True) from exc


    def get_emperor_review(self, game_id: str) -> dict:
        game = self.db.get_game(game_id)
        if game is None:
            raise ServiceError("GAME_NOT_FOUND", "未找到该局存档。", 404)
        if game["status"] == "playing":
            raise ServiceError("GAME_NOT_FINISHED", "本局尚未结束，终局后才能评估帝王图鉴。", 409)
        cached = self.db.get_emperor_review(game_id, game["revision"])
        if cached:
            # Old saved assessments remain intact; the codex exposes biography only.
            cached["review"] = {key: value for key, value in cached["review"].items() if key in ("emperor_id", "biography", "reign_title", "historian_comment", "referenced_turns")}
            return cached
        return {"state": "not_generated", "game_id": game_id}

    def generate_emperor_review(self, game_id: str) -> dict:
        cached = self.get_emperor_review(game_id)
        if cached["state"] == "ready":
            return cached
        if not callable(getattr(self.adapter, "assess_emperor", None)):
            raise ServiceError("LIVE_MODEL_REQUIRED", "帝王图鉴需要真实模型；当前为演示模式，无法生成。", 503)
        with self._emperor_lock_guard:
            lock = self._emperor_locks.setdefault(game_id, threading.Lock())
        with lock:
            cached = self.get_emperor_review(game_id)
            if cached["state"] == "ready":
                return cached
            detail = self._detail(game_id)
            if not detail["history"]:
                raise ServiceError("NO_POLICY_HISTORY", "这局没有可供评估的政策记录。", 422)
            if detail['game']['schema_version']>=4:
                engine=json.loads(self.db.get_game(game_id).get('events_json') or '{}')
                if engine.get('seed') is not None:detail['matching_seed']=engine['seed']
            try:
                from ..llm.emperor_review import EmperorReview, validate_review
                generated = self.adapter.assess_emperor(detail)
                review = generated if isinstance(generated, EmperorReview) else EmperorReview.model_validate(generated)
                if detail['game']['schema_version'] >= 4:
                    review = review.model_copy(update=events.historian_facts(detail))
                validate_review(review, detail)
            except ModelTimeout as exc:
                raise ServiceError("MODEL_TIMEOUT", "帝王图鉴评估超时，本局结局已保存，可稍后重试。", 504, True) from exc
            except (ModelOutputInvalid, ModelUnavailable, ValueError) as exc:
                raise ServiceError("MODEL_OUTPUT_INVALID", "帝王图鉴暂未评成，本局结局已保存，可重试评估。", 502, True) from exc
            result = review.model_dump(exclude_none=True)
            emperor = EMPEROR_BY_ID[review.emperor_id]
            response = {"state": "ready", "game_id": game_id, "game_revision": detail["game"]["revision"],
                "generated_at": utcnow(), "catalog_version": CATALOG_VERSION, "candidate_count": len(EMPERORS),
                "emperor": {key: emperor[key] for key in ("id", "name", "dynasty", "era", "facts", "sources")}, "review": result}
            if detail.get('matching_seed') is not None:
                from ..domain.emperor_matching import matching_candidates
                response['matching_audit']={**matching_candidates(detail),'selected_emperor':review.emperor_id}
            try:
                with self.db.transaction() as conn:
                    current = self.db.get_game(game_id)
                    if current["revision"] != detail["game"]["revision"] or current["status"] == "playing":
                        raise ServiceError("STALE_REVISION", "存档状态已变化，请重新读取结局。", 409)
                    self.db.save_emperor_review(conn, game_id, current["revision"], response)
            except sqlite3.Error as exc:
                raise ServiceError("SAVE_FAILED", "帝王图鉴暂未保存，本局结局仍在，可重试评估。", 500, True) from exc
            return self.db.get_emperor_review(game_id, detail["game"]["revision"])



    def _diplomacy_engine(self,game):
        if game['schema_version']>=4:return json.loads(game['events_json'])
        saved=json.loads(game.get('diplomacy_json') or '{}')
        if saved.get('engine'):
            engine=saved['engine']
            last_turn=engine.get('legacy_policy_turn',max((r['turn'] for r in saved.get('records',[])),default=0))
            for item in reversed(self.db.get_history(game['id'])):
                if item['turn_no']<=last_turn:break
                if war.is_combat(item['raw_text'],{'action':'enact'}):
                    summary=item['summary']
                    outcome='defeat' if '战败' in summary or '败退' in summary else 'victory' if '获胜' in summary or '大捷' in summary else 'unknown'
                    engine['war']['active']=True
                    engine['war'].pop('pending_treaty',None)
                    engine['war'].setdefault('records',[]).append({'turn':item['turn_no'],'outcome':outcome,'source':'legacy_record'})
                    break
            engine['legacy_policy_turn']=game['accepted_turns']
            return engine
        records=[]
        for item in reversed(self.db.get_history(game['id'])):
            if war.is_combat(item['raw_text'],{'action':'enact'}):
                summary=item['summary']
                outcome='defeat' if '战败' in summary or '败退' in summary else 'victory' if '获胜' in summary or '大捷' in summary else 'unknown'
                records=[{'turn':item['turn_no'],'outcome':outcome,'source':'legacy_record'}];break
        return {'seed':'diplomacy:'+game['id'],'legacy_policy_turn':game['accepted_turns'],'war':{'version':3,'active':True,'records':records,'cities_lost':0,'ending':None}}

    def negotiate(self,game_id,request_id,expected_revision,action,text='',proposal_id=None,remaining_policy='',digest=None):
        if action not in ('accept','reject','counter'):raise ServiceError('INVALID_DECISION','请选择接受、拒绝或还价。',422)
        digest=digest or _request_hash('diplomacy:'+json.dumps([action,text,proposal_id,remaining_policy],ensure_ascii=False),expected_revision)
        existing=self.db.find_request_record(game_id,request_id)
        if existing:
            if existing['request_hash']!=digest:raise ServiceError('IDEMPOTENCY_KEY_REUSED','请求编号已用于其他操作。',409)
            return existing['response']
        if action=='counter' and not text.strip():raise ServiceError('EMPTY_COUNTEROFFER','请先填写还价条件。',422)
        game=self.db.get_game(game_id)
        if not game:raise ServiceError('GAME_NOT_FOUND','未找到存档。',404)
        if game['status']!='playing':raise ServiceError('GAME_FINISHED','本局已经结束。',409)
        if game['revision']!=expected_revision:raise ServiceError('STALE_REVISION','存档或议和条件已更新，请重新核对。',409)
        engine=self._diplomacy_engine(game);current=engine.get('war',{}).get('pending_treaty')
        if proposal_id and (not current or current['id']!=proposal_id):raise ServiceError('STALE_PROPOSAL','当前条款已经变化，请重新核对。',409)
        if action=='accept' and not current:raise ServiceError('NO_PROPOSAL','尚无可接受的正式条款，请先开始谈判。',409)
        if (game['schema_version']>=4 and not war.active(engine)) or engine['war'].get('active') is False:raise ServiceError('NO_WAR','当前没有未结束的战争。',409)
        state={d:game[d] for d in events.DIMS};before=state.copy();phase=max(1,game['accepted_turns'])
        log=json.loads(game.get('diplomacy_json') or '{}');sequence=len(log.get('records',[]))+1
        battle=None;proposal=None;reply=None;reason=war.enemy_attack(engine,state,action=='reject')
        if action=='reject' or reason:
            if current:treaties.reject(engine,phase)
            engine,state,battle=war.resolve(engine,phase,state,before,reason or 'refused_negotiation',sequence)
            if not battle['collapsed']:
                battle['negotiation_status']='enemy_attacking';war.suspend_negotiation(engine,reason or 'refused_negotiation',state,phase)
            summary=battle['text']
        elif action=='accept':
            state,proposal=treaties.accept(engine,phase,state)
            summary='和约已经签订并按确认条款履约。' if proposal['status']=='accepted' else '现有钱粮不足，尚未付款或割城，可当场继续谈判。'
        else:
            records=engine.get('war',{}).get('records',[])
            outcome=current['outcome'] if current else records[-1]['outcome'] if records else 'unknown'
            direction=current['direction'] if current else ('receive' if outcome=='victory' or any(w in text for w in ('索赔','索取','要求对方')) else 'pay')
            context=self._build_context(game,min(game['accepted_turns']+1,8),text or '开始议和谈判')
            facts={'outcome':outcome,'direction':direction,'state':state,'previous_offer':current,'same_round':True,
                   'requested_terms':treaties.requested_terms(text,current['terms'] if current else None)}
            source='model' if hasattr(self.adapter,'propose_treaty') else 'fixture'
            try:
                raw=self.adapter.propose_treaty(context,facts) if source=='model' else {**treaties.RULES['fixture_terms'],'reason':'隔离测试谈判提案。'}
                terms,reply=treaties.interpret_reply(raw,text,current)
                if reply['decision']=='rejected':
                    proposal=current
                else:
                    proposal=treaties.propose(engine,phase,outcome,terms,source,same_round=True)
                    proposal['direction']=direction;engine['war']['pending_treaty']['direction']=direction
                summary={'accepted':'对方同意本次还价，条款待签。','rejected':'对方拒绝本次还价，原条款保留。','counter':'对方未接受原要求，另提以下条件。'}[reply['decision']]
            except (ModelTimeout,ModelUnavailable,ModelOutputInvalid,ValueError) as exc:
                raise ServiceError('TREATY_MODEL_FAILED','谈判答复未完成，尚未修改存档，请重试。',502,True) from exc
        status=game['status']
        if engine['war'].get('ending'):status='lost'
        elif game['accepted_turns']>=8 and not engine['war'].get('pending_treaty'):status='won' if state['people']>=80 else 'lost'
        if game['schema_version']>=4 and status!='playing':
            for record in engine['records']:
                if record['instance_id'] in engine['pending']:record.update(status='closed',outcome='closed',resolved_turn=phase)
            engine['pending']=[];engine['appraisal']=events.appraise(engine,state)
        session={'version':1,'id':request_id,'sequence':sequence,'turn':phase,'action':action,'text':text,'summary':summary,
            'proposal':proposal,'battle':battle,'reply':reply,'before':before,'after':state,
            'state_diff':{d:state[d]-before[d] for d in events.DIMS},'remaining_policy':remaining_policy}
        log.setdefault('records',[]).append(session)
        if game['schema_version']<4:log['engine']=engine
        updated={**game,**state,'revision':expected_revision+1,'status':status,'updated_at':utcnow(),
            'diplomacy_json':json.dumps(log,ensure_ascii=False)}
        if game['schema_version']>=4:updated['events_json']=json.dumps(engine,ensure_ascii=False)
        response={'kind':'diplomacy','game':_game_view(updated),'session':session,'remaining_policy':remaining_policy}
        with self.db.transaction() as conn:
            replay=self.db.find_request_record(game_id,request_id)
            if replay:
                if replay['request_hash']!=digest:raise ServiceError('IDEMPOTENCY_KEY_REUSED','请求编号已用于其他操作。',409)
                return replay['response']
            current_game=self.db.get_game(game_id)
            if current_game['revision']!=expected_revision or current_game['status']!='playing':raise ServiceError('STALE_REVISION','存档已更新，本次谈判没有生效。',409)
            self.db.update_game_after_turn(conn,updated)
            conn.execute('UPDATE games SET diplomacy_json=? WHERE id=?',(updated['diplomacy_json'],game_id))
            if game['schema_version']>=4:self.db.save_events(conn,game_id,engine)
            self.db.insert_request_record(conn,{'game_id':game_id,'request_id':request_id,'request_hash':digest,
                'expected_revision':expected_revision,'response_json':json.dumps(response,ensure_ascii=False),'created_at':updated['updated_at']})
        return response

    def preview_order(self,game_id,expected_revision,policy_text):
        text=policy_text.strip();game=self.db.get_game(game_id)
        if not game:raise ServiceError('GAME_NOT_FOUND','未找到该局存档。',404)
        if game['status']!='playing':raise ServiceError('GAME_FINISHED','本局已结束。',409)
        if game['accepted_turns']>=8:raise ServiceError('DIPLOMACY_ONLY','治理圣旨已颁完，请在议和窗口处理当前条款。',409)
        if game['revision']!=expected_revision:raise ServiceError('STALE_REVISION','存档已更新，请重新预览。',409)
        if not text or len(text)>MAX_POLICY_CHARS:raise ServiceError('INVALID_POLICY_TEXT','圣旨须为1至500字。',422)
        turn=game['accepted_turns']+1;state=GameState(**{d:game[d] for d in events.DIMS})
        engine=json.loads(game.get('events_json') or '{}')
        plan=plan_order(text,engine,state.model_dump()) if game['schema_version']>=4 else None
        deal_text,governance_text=treaties.split_order(text)
        diplomatic=bool(re.search(r'议和|和约|谈判|(?:同意|接受).{0,8}条件',deal_text) or treaties.action(deal_text,self._diplomacy_engine(game)))
        execution=plan['execution'] if plan else None
        if diplomatic:execution='当前回合处理议和，不占治理圣旨'+('；议和后保留治理草稿：'+governance_text if governance_text else '')
        context=self._build_context(game,turn,text)
        intent=plan['intent'] if plan else identify(text)
        effect=plan['effect'].copy() if plan else dict.fromkeys(events.DIMS,0)
        opening=json.loads(game.get('opening_json') or '{}') or None
        conditions=json.loads(game.get('conditions_json') or '{}') or None
        effect,notes=opening_effect(opening,conditions,intent,text,turn,state,effect)
        effect,limits=settlement.apply_execution_constraints(state,effect,context.history,text,text[:200],intent)
        clauses=[s.strip() for s in re.split(r'[，,。；;\n]+|、(?=不|禁止|严禁|勿)',text) if s.strip()]
        prohibitions=[s for s in clauses if re.match(r'(?:且|并|一律|务必)?(?:不|禁止|严禁|勿|毋)',s)]
        methods=[s for s in clauses[1:] if s not in prohibitions]
        if clauses and re.search(r'雇工|雇佣|无偿征役|拨款|开仓|平粜',clauses[0]):methods.insert(0,clauses[0])
        pending=events.public_events(engine)['pending'] if engine else []
        due=[{'id':e['instance_id'],'name':e['name'],'turn':e['respond_by_turn']} for e in pending if e['respond_by_turn']<=turn]
        notes+=limits
        if plan and plan['combat']:notes.append('本次将结算一场战斗，另付军费军粮；战果尚未发生。')
        elif plan and war.active(engine):notes.append('战争尚未结束；若本回合支出后两项国力低于20，还会遭到敌军进攻。')
        if plan and plan['intent']['category']=='inaction':notes.append('当前识别为不新增施政；若与本意不符，请返回修改。')
        return {'game_id':game_id,'revision':game['revision'],'turn':turn,'policy_text':text,
            'execution':execution,'diplomacy':diplomatic,'governance_text':governance_text if diplomatic else text,
            'intent':intent,'methods':methods,
            'prohibitions':prohibitions,'base_effect':effect,'notes':notes,
            'due_events':due,'due_echoes':[{'id':e['id'],'reason':e['reason']} for e in context.due_echoes],
            'treaty':engine.get('war',{}).get('pending_treaty') if plan and plan['requested_treaty_action'] else None}

    def _build_context(self, game: dict, turn_no: int, policy_text: str) -> ModelContext:
        history_rows = self.db.get_history(game["id"])
        history = []
        for item in history_rows:
            history.append(
                {
                    "turn_no": item["turn_no"],
                    "period": period_name(item["turn_no"]),
                    "policy_id": item["policy_id"],
                    "raw_text": item["raw_text"],
                    "normalized_goal": item["normalized_goal"],
                    "summary": item["summary"],
                    "reactions": item["reactions"],
                    "after": item["after"],
                    "policy_intent": identify(item["raw_text"], item.get("policy_intent")),
                    "new_echoes": item.get("new_echoes", []),
                    "policy_status": item.get("policy_status", "active"),
                }
            )
        history, _ = transition(history, {"action": "enact", "category": "other"}, turn_no)
        return ModelContext(
            game=_game_view(game),
            turn_no=turn_no,
            period=period_name(turn_no),
            history=history,
            due_echoes=self.db.get_due_echoes(game["id"], turn_no),
            player_policy=policy_text,
        )

    def submit_turn(
        self,
        game_id: str,
        request_id: str,
        expected_revision: int,
        policy_text: str,
        expected_turn: int | None = None,
    ) -> dict:
        policy_text = policy_text.strip()
        if not policy_text:
            raise ServiceError("INVALID_POLICY_TEXT", "圣旨内容不能为空。", 422)
        if len(policy_text) > MAX_POLICY_CHARS:
            raise ServiceError(
                "INVALID_POLICY_TEXT",
                f"圣旨内容不能超过 {MAX_POLICY_CHARS} 字。",
                422,
            )

        digest = _request_hash(policy_text, expected_revision)
        if expected_turn is not None:
            digest = hashlib.sha256(f'{digest}|{expected_turn}'.encode()).hexdigest()

        existing = self.db.find_request_record(game_id, request_id)
        if existing is not None:
            if existing["request_hash"] != digest:
                raise ServiceError(
                    "IDEMPOTENCY_KEY_REUSED",
                    "同一 request_id 已用于其他请求,请更换后重试。",
                    409,
                )
            return existing["response"]

        game = self.db.get_game(game_id)
        if game is None:
            raise ServiceError("GAME_NOT_FOUND", "未找到该局存档。", 404)
        if game["status"] != "playing":
            raise ServiceError("GAME_FINISHED", "本局已结束,无法继续下旨。", 409)
        if game["revision"] != expected_revision:
            raise ServiceError(
                "STALE_REVISION",
                "存档已更新,请刷新当前回合状态后重新颁布。",
                409,
            )

        turn_no = game["accepted_turns"] + 1
        event_mode = game['schema_version'] >= 4
        if event_mode and expected_turn is None:
            raise ServiceError('EXPECTED_TURN_REQUIRED', '新版圣旨须附带预期回合，请刷新页面后重试。', 422)
        if expected_turn is not None and expected_turn != turn_no:
            raise ServiceError('STALE_TURN', '回合已变化，请读取当前存档后重试。', 409)
        deal_text,governance_text=treaties.split_order(policy_text)
        diplomacy_engine=self._diplomacy_engine(game)
        deal_action=treaties.action(deal_text,diplomacy_engine) if deal_text else None
        deal_topic=bool(re.search(r'议和|和约|谈判|(?:同意|接受).{0,8}条件',deal_text))
        if deal_topic and re.search(r'如果|是否|能否|会怎样|考虑|询问',deal_text):
            return {'kind':'clarification','warning_type':'unclear','message':'请在议和窗口明确选择接受、拒绝或提出还价条件。询问不会改变条款。','game':_game_view(game)}
        if deal_action or deal_topic:
            choice={'accept':'accept','reject':'reject','negotiate':'counter'}.get(deal_action,'counter')
            if choice=='accept' and not diplomacy_engine.get('war',{}).get('pending_treaty'):choice='counter'
            return self.negotiate(game_id,request_id,expected_revision,choice,deal_text,
                remaining_policy=governance_text,digest=digest)
        if turn_no>8:raise ServiceError('DIPLOMACY_ONLY','八道治理圣旨已颁完，请完成当前议和。',409)
        context = self._build_context(game, turn_no, policy_text)
        prior_engine=json.loads(game.get('events_json') or '{}') if event_mode else {}
        rule_plan=plan_order(policy_text,prior_engine,{d:game[d] for d in events.DIMS}) if event_mode else None
        treaty_action=rule_plan['treaty_action'] if rule_plan else None
        cache_key=(id(self.adapter),game_id,request_id,digest,game['revision'],game['people'],game['treasury'],game['grain'])
        with self._retry_cache_lock:
            cached=self._retry_candidates.get(cache_key)
            cached=cached[1] if cached and time.monotonic()-cached[0]<180 else None
        try:
            candidate = cached.model_copy(deep=True) if cached is not None else self.adapter.evaluate(context)
            if cached is not None:context.deadline=time.monotonic()+getattr(self.adapter,'timeout',50)
        except ModelTimeout as exc:
            raise ServiceError("MODEL_TIMEOUT", "奏报拟写超时,本回合尚未结算,请稍后重试。", 504, retryable=True) from exc
        except ModelUnavailable as exc:
            raise ServiceError("MODEL_OUTPUT_INVALID", "奏报拟写失败,本回合尚未结算,请稍后重试。", 502, retryable=True) from exc
        except ModelOutputInvalid as exc:
            raise ServiceError("MODEL_OUTPUT_INVALID", "奏报拟写失败,本回合尚未结算,请稍后重试。", 502, retryable=True) from exc

        due_echoes = self.db.get_due_echoes(game_id, turn_no)
        if isinstance(candidate, ClarificationCandidate):
            return {
                "kind": "clarification",
                "warning_type": candidate.warning_type,
                "message": candidate.message,
                "game": _game_view(game),
            }
        data = candidate_to_dict(candidate)
        model_policy_effect = dict(data.get("policy_effect", {}))
        if event_mode:
            safe_intent = dict(rule_plan['intent'])
            data['policy_intent'] = safe_intent
            data['normalized_goal'] = policy_text[:200]
            data['policy_effect'] = dict(rule_plan['effect'])
            sources={h['policy_id']:h for h in context.history}
            data['echo_effects'] = [dict(echo_id=e['id'], **events.echo_effect(sources.get(e['source_policy_id'],{})), explanation='已施政的一次后效，由规则核定。') for e in due_echoes]
            data['new_echoes'] = events.policy_echoes(safe_intent, False, turn_no)
            data['tags'] = events.policy_tags(safe_intent, policy_text)
        errors = settlement.validate_candidate_semantics(data, due_echoes, turn_no)
        if errors:
            raise ServiceError(
                "MODEL_OUTPUT_INVALID",
                "推演结果不符合契约(超出数值范围或回声不完整),本回合尚未结算。",
                502,
                retryable=True,
            )

        if getattr(self.adapter,'retry_cache_safe',False):
            with self._retry_cache_lock:
                self._retry_candidates[cache_key]=(time.monotonic(),candidate.model_copy(deep=True))
                while len(self._retry_candidates)>64:self._retry_candidates.pop(next(iter(self._retry_candidates)))
        intent = dict(rule_plan['intent']) if rule_plan else identify(policy_text, data.get("policy_intent"))
        player_combat=rule_plan['player_combat'] if rule_plan else False
        requested_treaty_action=rule_plan['requested_treaty_action'] if rule_plan else None
        attack_reason=rule_plan['attack_reason'] if rule_plan else None
        treaty_blocked=rule_plan['treaty_blocked'] if rule_plan else False
        combat=rule_plan['combat'] if rule_plan else False
        if requested_treaty_action:
            intent.update(category='diplomacy',project='war_treaty',action='enact')
            data['policy_intent']=intent
            data['policy_effect']=dict.fromkeys(settlement.DIMENSIONS,0)
            data['new_echoes']=[]
        if player_combat:
            # Campaign costs/results are accounted separately, with no repeat discount.
            data['policy_effect'] = dict.fromkeys(settlement.DIMENSIONS, 0)
            data['new_echoes'] = []
        # execution_default is a program note, not a model-schema field.
        intent_default = intent.pop("execution_default", None)
        data["policy_intent"] = intent
        if intent["category"] == "tax" and intent["magnitude"] in ("moderate", "half", "full", "unchanged", "restore"):
            data["normalized_goal"] = f"{intent['region']}：" + {"moderate": "温和减征税赋（未指定比例）", "half": "税赋减半", "full": "免除税赋", "unchanged": "停止继续减征税赋", "restore": "恢复原定税额征收"}[intent["magnitude"]]
        if intent["category"] == "grain_supply":
            data["normalized_goal"] = f"{intent['region']}：购粮补仓，增加储备"
        ledger, lifecycle_notes = transition(context.history, intent, turn_no)
        context.history = ledger
        due_echo_by_id = {e["id"]: e for e in due_echoes}
        source_policies = {item["policy_id"]: item for item in context.history}
        enriched_echo_effects = []
        for effect in data["echo_effects"]:
            source = due_echo_by_id[effect["echo_id"]]
            source_policy = source_policies.get(source["source_policy_id"], {})
            enriched_echo_effects.append(
                {
                    "echo_id": effect["echo_id"],
                    "people": effect["people"],
                    "treasury": effect["treasury"],
                    "grain": effect["grain"],
                    "explanation": effect["explanation"],
                    "source_policy_id": source["source_policy_id"],
                    "source_raw_text": source_policy.get("raw_text", "原圣旨"),
                    "created_turn": source["created_turn"],
                    "reason": source["reason"],
                }
            )

        before = GameState(
            people=game["people"],
            treasury=game["treasury"],
            grain=game["grain"],
        )
        if intent["category"] == "tax" and not any(word in policy_text for word in ("粮税", "征粮", "粮赋")):
            data["policy_effect"]["grain"] = 0
        # Repeat detection uses stable policy scope, not generated goal wording.
        opening = json.loads(game.get("opening_json") or "{}") or None
        conditions = json.loads(game.get("conditions_json") or "{}") or None
        adjusted_effect, opening_notes = opening_effect(opening, conditions, intent, policy_text, turn_no, before, data["policy_effect"])
        policy_effect, constraint_notes = settlement.apply_execution_constraints(
            before, adjusted_effect, context.history, policy_text, data["normalized_goal"], intent,
        )
        constraint_notes.extend(opening_notes)
        constraint_notes.extend(lifecycle_notes)
        data["new_echoes"], monitoring_notes = limit_monitoring_echoes(context.history, intent, policy_text, data["new_echoes"])
        constraint_notes.extend(monitoring_notes)
        constrained_policy_effect = dict(policy_effect)
        if any(item["policy_status"] in ("revoked", "suspended") for item in ledger):
            constraint_notes.append("已停旧令不因本次新政自动恢复；只执行本次明确授权事项。")
        if intent_default:
            constraint_notes.append(intent_default)
        blocked = any(getattr(before, dim) == 0 and data["policy_effect"][dim] < 0 for dim in ("treasury", "grain"))
        if intent["category"] == "relief" and intent["action"] not in ("revoke", "suspend") and before.grain == 0:
            blocked = True
        if blocked:
            policy_effect = {dim: min(0, policy_effect[dim]) if dim == "people" else 0 for dim in settlement.DIMENSIONS}
            constraint_notes.append("所需资源为零，本次无法实施；不得虚构外仓、借粮或采购来源，不产生实施成功回声。")
            data["new_echoes"] = []
        if intent["action"] in ("revoke", "suspend"):
            policy_effect["grain"] = 0
            constraint_notes.append("封存只是停止使用，不会凭空增加粮储。")
            data["new_echoes"] = []
        # Due echoes cannot spend unavailable resources or restart stopped orders.
        available = {dim: max(0, getattr(before, dim) + min(0, policy_effect[dim])) for dim in ("treasury", "grain")}
        for effect in enriched_echo_effects:
            source = source_policies.get(effect["source_policy_id"], {})
            stopped = source.get("policy_status") in ("revoked", "suspended", "completed")
            if stopped:
                if due_echo_by_id[effect["echo_id"]].get("effect_kind") == "execution":
                    effect.update(people=0, treasury=0, grain=0)
                else:
                    # Memory, harvests and social effects can outlive revocation;
                    # an echo cannot pay for a new action without authorization.
                    effect.update(treasury=max(0, effect["treasury"]), grain=max(0, effect["grain"]))
                effect["explanation"] = "原令已停止；不再拨付钱粮或计入继续实施的收益，仅保留既有民情后果。"
                constraint_notes.append(f"第{effect['created_turn']}回合旧令已停，不得借回声恢复执行。")
            else:
                echo_state = GameState(people=before.people, **available)
                adjusted, echo_notes = settlement.apply_execution_constraints(echo_state, effect, [], "", "")
                if echo_notes:
                    effect.update(adjusted)
                    effect["explanation"] = "旧令后续施行所需钱粮不足，本次按可动用存量办理，未能全额实现原定后效。"
                    constraint_notes.extend(echo_notes)
                for dim in available:
                    effect[dim] = max(-available[dim], effect[dim])
                    available[dim] = max(0, available[dim] + min(0, effect[dim]))
        result_settlement = settlement.settle(before, policy_effect, enriched_echo_effects)
        settlement.attribute_applied(result_settlement)
        enriched_echo_effects = result_settlement.echo_effects
        if any(result_settlement.audit["raw_totals"][dim] != getattr(result_settlement.applied_effects, dim) for dim in settlement.DIMENSIONS):
            constraint_notes.append("合并政策与旧政后效后，按单回合上限及现有存量结算；下列分项为实际计入变化。")
        if re.search(r"(?:全部|尽数|所有|用尽).{0,12}(?:钱粮|军需|国库|粮储)|(?:钱粮|国库|粮储).{0,8}(?:全部|尽数|所有|用尽)", policy_text) and (result_settlement.after.treasury > 0 or result_settlement.after.grain > 0):
            constraint_notes.append("原诏要求全部动用钱粮，但本次受单回合支出上限约束；留存钱粮未解付，不得称已经全部送出。")
        data["echo_effects"] = [{key: effect[key] for key in ("echo_id", "people", "treasury", "grain", "explanation")} for effect in enriched_echo_effects]
        data["policy_effect"] = result_settlement.policy_effect
        next_conditions = advance_conditions(opening, conditions, intent, policy_text, result_settlement.policy_effect, blocked, turn_no, bool(opening_notes))
        event_state = None
        event_report = None
        if event_mode:
            policy_after = result_settlement.after.model_dump()
            campaign_engine = json.loads(game['events_json'])
            battle = None
            treaty_report = None
            if treaty_action=='accept':
                policy_after,treaty_report=treaties.accept(campaign_engine,turn_no,policy_after)
                data['new_echoes']=[]
            elif treaty_action=='reject':
                if campaign_engine['war'].get('pending_treaty'):treaties.reject(campaign_engine,turn_no)
            def propose_terms(outcome):
                source='model' if hasattr(self.adapter,'propose_treaty') else 'fixture'
                term_facts={'outcome':outcome,'direction':'receive' if outcome=='victory' else 'pay',
                    'state':policy_after,'previous_offer':prior_engine.get('war',{}).get('pending_treaty')}
                try:
                    raw=self.adapter.propose_treaty(context,term_facts) if source=='model' else {
                        **treaties.RULES['fixture_terms'],'reason':'隔离测试议和条件。'}
                    return treaties.propose(campaign_engine,turn_no,outcome,raw,source,same_round=True)
                except (ModelTimeout,ModelUnavailable,ModelOutputInvalid,ValueError) as exc:
                    raise ServiceError('TREATY_MODEL_FAILED','议和条件拟定失败，本回合尚未结算，请重试。',502,retryable=True) from exc
            if not combat and war.active(campaign_engine) and war.weak(policy_after):
                combat=True;attack_reason='two_weak_dimensions'
            if combat:
                campaign_engine, policy_after, battle = war.resolve(campaign_engine,turn_no,policy_after,before.model_dump(),attack_reason)
                suspended=attack_reason or ('two_weak_dimensions_after_battle' if war.weak(policy_after) else None)
                if suspended and not battle['collapsed']:
                    battle['negotiation_status']='enemy_attacking'
                    war.suspend_negotiation(campaign_engine,suspended,policy_after,turn_no)
                    battle['text']+='敌军未提出停战条件，战事仍在继续。'
                elif not battle['collapsed']:
                    campaign_engine['war']['negotiation_suspended']=None
                    treaty_report=propose_terms(battle['outcome'])
            elif treaty_action=='negotiate':
                previous=prior_engine['war'].get('pending_treaty')
                outcome=previous['outcome'] if previous else prior_engine['war']['records'][-1]['outcome']
                treaty_report=propose_terms(outcome)
            if turn_no==8 and campaign_engine.get('war',{}).get('pending_treaty') and treaty_report and treaty_report['status']=='unfunded':
                campaign_engine['war']['pending_treaty']=None
                campaign_engine['war']['active']=True
                if treaty_report and treaty_report['status']=='unfunded':treaty_report['status']='expired'
            event_state, event_after, event_report = events.advance_events(
                campaign_engine, turn_no, policy_after, intent, policy_text, blocked)
            if war.active(event_state) and war.weak(event_after.model_dump()):
                war.suspend_negotiation(event_state,'two_weak_dimensions',event_after.model_dump(),turn_no)
                treaty_report=None
                if battle and not battle['collapsed'] and battle.get('negotiation_status')!='enemy_attacking':
                    battle['negotiation_status']='enemy_attacking'
                    battle['text']+='敌军未提出停战条件，战事仍在继续。'
                    event_state['war']['records'][-1]=dict(battle)
            if treaty_report:
                event_report['treaty']=treaty_report
                if treaty_report['status']=='accepted':
                    event_report['state_diff'].insert(0,{'source':'treaty','before':treaty_report['before'],
                        'after':treaty_report['after'],'applied':treaty_report['effects'],'proposal_id':treaty_report['id']})
            if battle:
                if event_report.get('quiet'):event_report['quiet']='本回合没有新增天时国运事件。'
                event_report['war'] = battle
                event_report['state_diff'].insert(0, {'source':'war','before':battle['before'],
                    'after':battle['after'],'applied':battle['effects'],'config_version':battle['version']})
                if battle['collapsed']:
                    for record in event_state['records']:
                        if record['instance_id'] in event_state['pending']:
                            record.update(status='closed',outcome='closed',resolved_turn=turn_no)
                    event_state['pending'] = []
                    event_state['appraisal'] = events.appraise(event_state,event_after.model_dump())
                    event_state['appraisal'].update(title='兵败国亡',won=False,legacy_issues=True)
                    data['new_echoes'] = []
            event_report['state_diff'].insert(0, {'source':'policy_and_echoes',
                'before':before.model_dump(), 'after':result_settlement.after.model_dump(),
                'policy':result_settlement.policy_effect, 'echoes':enriched_echo_effects,
                'applied':result_settlement.applied_effects.model_dump(),
                'bounds':result_settlement.audit['bounded_totals']})
            if result_settlement.audit['raw_totals'] != result_settlement.applied_effects.model_dump():
                event_report['state_diff'].insert(1, {'source':'clamp','parent':'policy_and_echoes',
                    'requested':result_settlement.audit['raw_totals'],
                    'applied':result_settlement.applied_effects.model_dump()})
            result_settlement.after = event_after
            if next_conditions is not None:
                repaired=events.repaired_weakness(event_state['initial_state'],event_after.model_dump())
                next_conditions={**next_conditions,'resolved':repaired,
                    'resolved_turn':(next_conditions.get('resolved_turn') or turn_no) if repaired else None,'basis':'国情快照'}
            result_settlement.applied_effects = settlement.EffectDelta(**{d:getattr(event_after,d)-getattr(before,d) for d in settlement.DIMENSIONS})
            result_settlement.audit['events'] = event_report
        facts = {"intent": intent, "blocked": blocked, "constraint_notes": constraint_notes,
                 "before": before.model_dump(), "after": result_settlement.after.model_dump(),
                 "actual_policy_effect": result_settlement.policy_effect, "actual_echo_effects": enriched_echo_effects,
                 "history": ledger, "original_goal": policy_text, "policy_analysis": data["policy_analysis"]}
        from ..domain.policy_tradeoffs import considerations
        facts['policy_considerations']=considerations(policy_text,intent)
        facts["opening"] = opening
        facts["conditions"] = next_conditions
        if event_mode:
            facts['execution_required'] = not blocked and intent['category'] != 'inaction' and intent.get('action') not in ('revoke', 'suspend')
            if treaty_blocked:facts['execution_required']=False
            if treaty_report and treaty_report['status'] in ('unfunded','expired'):facts['execution_required']=False
            facts['event_report'] = event_report
            facts['war'] = battle
            facts['opening_repair'] = next_conditions.get('resolved') if next_conditions else None
            facts['treaty'] = treaty_report
            facts['pending_events'] = events.public_events(event_state)['pending']
            facts['policy_after_before_new_event'] = policy_after
            facts['rules_title'] = event_state['appraisal']
        realm = None
        base_status = ('playing' if turn_no < 8 else 'won' if result_settlement.after.people >= 80 else 'lost') if event_mode else settlement.decide_status(result_settlement.after.people, turn_no)
        if event_mode and turn_no==8 and event_state.get('war',{}).get('pending_treaty'):base_status='playing'
        if event_mode and battle and battle['collapsed']: base_status = 'lost'
        if 2 <= game["schema_version"] < 4:
            realm = advance_realm(json.loads(game.get("realm_json") or "{}"), result_settlement.after,
                                  intent, policy_text, blocked, constraint_notes, turn_no, base_status)
            facts["realm"] = realm
            facts["ending"] = realm["ending"]
        elif event_mode:
            realm=advance_crisis(json.loads(game.get('realm_json') or '{}'),result_settlement.after,
                intent,policy_text,blocked,constraint_notes,turn_no,event_state.get('war'),battle)
            if battle and battle['collapsed']:realm['ending']=None
            if realm['ending']:
                base_status='lost';data['new_echoes']=[]
                finish_events(event_state,result_settlement.after.model_dump(),realm,turn_no)
                event_report['quiet']=None
                facts['rules_title']=event_state['appraisal']
            facts['realm']=realm;facts['ending']=realm['ending']
            if realm['warnings']:event_report['quiet']=None
        # Live narration is mandatory even when resources, repetition or old
        # orders constrain execution. No canned character lines on live failure.
        if hasattr(self.adapter, "narrate"):
            try:
                narrated = self.adapter.narrate(context, data, facts)
                errors = narration_errors(narrated, facts)
                if errors:
                    raise ModelOutputInvalid("；".join(errors))
                if any(narrated[key] != data[key] for key in ("policy_effect", "policy_intent")):
                    raise ModelOutputInvalid("人物奏报改变了已经核定的事实")
                data = narrated
            except ModelTimeout as exc:
                raise ServiceError("MODEL_TIMEOUT", "人物奏报拟写超时，本回合尚未结算，请稍后重试。", 504, retryable=True) from exc
            except (ModelOutputInvalid, ModelUnavailable, ValueError) as exc:
                # Keep stage/rule evidence without logging prompts, model prose
                # or credentials. Do not reduce future failures to a lone 502.
                reason = 'TAX_EXEMPTION_MISMATCH' if '免除' in str(exc) or '全免' in str(exc) else 'UNAUTHORIZED_BURDEN' if '未授权的民间' in str(exc) else 'NARRATION_CONTRACT'
                logger.warning('narration rejected game=%s schema=%s turn=%s exception=%s rule=%s',
                    game_id, game['schema_version'], turn_no, type(exc).__name__, reason)
                explanation={'UNAUTHORIZED_BURDEN':'奏报写入了未获授权的代垫或摊派','TAX_EXEMPTION_MISMATCH':'奏报税收范围与原诏不符','NARRATION_CONTRACT':'奏报未通过人物身份或结算事实校验'}[reason]
                raise ServiceError("MODEL_OUTPUT_INVALID", "人物奏报未能完成："+explanation+"。本回合尚未结算，草稿已保留，请重试。", 502, retryable=True) from exc
            narration_source = "model"
        else:
            # Fixture/scripted adapters are explicitly offline test data. They
            # may still use factual fixture text; live adapters never enter here.
            if constraint_notes or not prose_is_safe(data, intent):
                data = factual_narration(data, facts)
                for effect in data["echo_effects"]:
                    effect["explanation"] = "旧令后效按本次资源和启停状态核定；不代表重新颁令或全额完成原目标。"
                for echo in data["new_echoes"]:
                    echo["reason"] = "查考本次实际办理部分的后续影响，不追加未经新诏授权的执行。"
            narration_source = "fixture"
        for effect, prose in zip(enriched_echo_effects, data["echo_effects"]):
            effect["explanation"] = prose["explanation"]
        facts["policy_analysis"] = data["policy_analysis"]
        result_settlement.audit["execution"] = facts
        result_settlement.audit["model_policy_analysis"] = candidate_to_dict(candidate)["policy_analysis"]
        result_settlement.audit["policy_analysis"] = data["policy_analysis"]
        result_settlement.audit["narration_source"] = narration_source
        result_settlement.audit["model_echo_effects"] = candidate_to_dict(candidate)["echo_effects"]
        result_settlement.audit["model_policy_effect"] = model_policy_effect
        result_settlement.audit["constrained_policy_effect"] = constrained_policy_effect
        result_settlement.audit["constraint_notes"] = constraint_notes
        after = result_settlement.after
        new_status = realm["ending"]["status"] if realm and realm["ending"] else base_status

        policy_id = uuid.uuid4().hex
        result_id = uuid.uuid4().hex
        now = utcnow()

        new_echoes = []
        for echo in data["new_echoes"]:
            echo_id = uuid.uuid4().hex
            due_turn = turn_no + echo["delay"]
            new_echoes.append(
                {
                    "id": echo_id,
                    "source_policy_id": policy_id,
                    "created_turn": turn_no,
                    "delay": echo["delay"],
                    "due_turn": due_turn,
                    "reason": echo["reason"],
                    "effect_kind": echo.get("effect_kind", "consequence"),
                }
            )

        response = {
            "kind": "accepted",
            "game": {},
            "policy_statuses": {item["policy_id"]: item["policy_status"] for item in ledger},
            "result": {
                "id": result_id,
                "policy_id": policy_id,
                "turn_no": turn_no,
                "raw_text": policy_text,
                "normalized_goal": data["normalized_goal"],
                "before": {
                    "people": before.people,
                    "treasury": before.treasury,
                    "grain": before.grain,
                },
                "applied_effects": {
                    "people": result_settlement.applied_effects.people,
                    "treasury": result_settlement.applied_effects.treasury,
                    "grain": result_settlement.applied_effects.grain,
                },
                "after": {
                    "people": after.people,
                    "treasury": after.treasury,
                    "grain": after.grain,
                },
                "advisor": data["advisor"],
                "reactions": data["reactions"],
                "summary": data["summary"],
                "constraint_notes": constraint_notes,
                "policy_analysis": data["policy_analysis"],
                "narration_source": narration_source,
                "policy_intent": intent,
                "policy_status": "completed" if blocked or intent["action"] in ("revoke", "suspend") else "active",
                "execution": facts,
                "realm": realm,
                "events": event_report,
                "echo_effects": enriched_echo_effects,
                "new_echoes": new_echoes,
            },
        }

        try:
            with self.db.transaction() as conn:
                # A concurrent retry may have committed while this request was
                # evaluating. Replay it before checking the now newer revision.
                replay = self.db.find_request_record(game_id, request_id)
                if replay is not None:
                    if replay["request_hash"] != digest:
                        raise ServiceError("IDEMPOTENCY_KEY_REUSED", "同一 request_id 已被占用,请更换后重试。", 409)
                    return replay["response"]
                current = self.db.get_game(game_id)
                if current is None or current["revision"] != expected_revision:
                    raise ServiceError(
                        "STALE_REVISION",
                        "存档已更新,请刷新当前回合状态后重新颁布。",
                        409,
                    )
                if current["status"] != "playing":
                    raise ServiceError("GAME_FINISHED", "本局已结束,无法继续下旨。", 409)
                self.db.insert_policy(
                    conn,
                    {
                        "id": policy_id,
                        "game_id": game_id,
                        "turn_no": turn_no,
                        "raw_text": policy_text,
                        "normalized_goal": data["normalized_goal"],
                        "tags": json.dumps(data["tags"], ensure_ascii=False),
                        "metadata": json.dumps(intent, ensure_ascii=False),
                        "status": response["result"]["policy_status"],
                    },
                )
                for item in ledger:
                    self.db.update_policy_status(conn, item["policy_id"], item["policy_status"])
                if realm is not None:
                    self.db.save_realm(conn, game_id, realm)
                if event_state is not None:
                    self.db.save_events(conn, game_id, event_state)
                if next_conditions is not None:
                    self.db.save_conditions(conn, game_id, next_conditions)
                self.db.insert_turn_result(
                    conn,
                    {
                        "id": result_id,
                        "game_id": game_id,
                        "policy_id": policy_id,
                        "turn_no": turn_no,
                        "before_people": before.people,
                        "before_treasury": before.treasury,
                        "before_grain": before.grain,
                        "after_people": after.people,
                        "after_treasury": after.treasury,
                        "after_grain": after.grain,
                        "applied_people": result_settlement.applied_effects.people,
                        "applied_treasury": result_settlement.applied_effects.treasury,
                        "applied_grain": result_settlement.applied_effects.grain,
                        "advisor": data["advisor"],
                        "reactions": json.dumps(data["reactions"], ensure_ascii=False),
                        "summary": data["summary"],
                        "echo_effects": json.dumps(enriched_echo_effects, ensure_ascii=False),
                        "new_echoes": json.dumps(new_echoes, ensure_ascii=False),
                        "audit": json.dumps(result_settlement.audit, ensure_ascii=False),
                    },
                )
                for echo in due_echoes:
                    self.db.resolve_echo(conn, echo["id"], turn_no)
                for echo in new_echoes:
                    self.db.insert_echo(
                        conn,
                        {
                            "id": echo["id"],
                            "game_id": game_id,
                            "source_policy_id": echo["source_policy_id"],
                            "created_turn": turn_no,
                            "due_turn": echo["due_turn"],
                            "reason": echo["reason"],
                            "effect_kind": echo.get("effect_kind", "consequence"),
                            "status": "pending",
                            "resolved_turn": None,
                        },
                    )
                updated_game = {
                    "id": game_id,
                    "revision": expected_revision + 1,
                    "accepted_turns": turn_no,
                    "status": new_status,
                    "people": after.people,
                    "treasury": after.treasury,
                    "grain": after.grain,
                    "updated_at": now,
                    "realm_json": json.dumps(realm, ensure_ascii=False) if realm is not None else game.get("realm_json", "{}"),
                    "conditions_json": json.dumps(next_conditions, ensure_ascii=False) if next_conditions is not None else game.get("conditions_json", "{}"),
                    "events_json": json.dumps(event_state, ensure_ascii=False) if event_state is not None else game.get('events_json', '{}'),
                }
                self.db.update_game_after_turn(conn, updated_game)
                response["game"] = _game_view(
                    {
                        **game,
                        **updated_game,
                    }
                )
                self.db.insert_request_record(
                    conn,
                    {
                        "game_id": game_id,
                        "request_id": request_id,
                        "request_hash": digest,
                        "expected_revision": expected_revision,
                        "response_json": json.dumps(response, ensure_ascii=False),
                        "created_at": now,
                    },
                )
        except ServiceError:
            raise
        except Exception as exc:
            raise ServiceError("SAVE_FAILED", "存档写入失败,本回合未结算。", 500, retryable=True) from exc

        return response
