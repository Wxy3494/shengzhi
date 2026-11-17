import { useCallback, useEffect, useRef, useState } from "react";
import * as api from "./api/client";
import ChronicleModal from "./components/ChronicleModal";
import CrisisPanel from "./components/CrisisPanel";
import OpeningBriefing from "./components/OpeningBriefing";
import Decorations from "./components/Decorations";
import EdictInput from "./components/EdictInput";
import EdictPreview from "./components/EdictPreview";
import DiplomacyModal from './components/DiplomacyModal';
import EndingView from "./components/EndingView";
import Header from "./components/Header";
import HelpModal from "./components/HelpModal";
import EmperorLibrary from './components/EmperorLibrary';
import MessageBubble from "./components/MessageBubble";
import MetricsBar from "./components/MetricsBar";
import TurnResultCard from "./components/TurnResultCard";
import type { ChatMessage } from "./types/chat";
import { buildChatFromHistory } from "./types/chat";
import type { EchoRecord, Game, GameDetail, TurnResult, WarningType } from "./types/game";
import { ApiError } from "./types/game";

const MAX_CHARS = 500;
const GAME_IDS_KEY = "shengzhi.gameIds";
const CURRENT_KEY = "shengzhi.currentGame";
const DRAFT_KEY = (id: string) => `shengzhi.draft.${id}`;
const PENDING_KEY = (id: string) => `shengzhi.pending.${id}`;

interface SavedGameMeta {
  id: string;
  turns: number;
  status: string;
  endingTitle?: string;
}

interface PendingState {
  requestId: string;
  text: string;
  msgId: string;
  expectedRevision: number;
  expectedTurn?: number;
  gameId: string;
}

const WARNING_COPY: Record<WarningType, { title: string; note: string }> = {
  anachronism: {
    title: "超出时代限制",
    note: "本回合尚未结算,草稿已保留,请改以本朝可行之事下诏。",
  },
  multiple_goals: {
    title: "请选定一个目标",
    note: "本回合尚未结算,草稿已保留,请只保留最要紧的一件;同一目标的配套措施可以保留。",
  },
  not_policy: {
    title: "这不是一道政令",
    note: "本回合尚未结算,草稿已保留,请提出一件要办的事。",
  },
  unclear: {
    title: "诏意未明",
    note: "本回合尚未结算,草稿已保留,请把想办的事说得明白些。",
  },
};

function loadJson<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    if (raw === null) return fallback;
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

function saveJson(key: string, value: unknown): void {
  localStorage.setItem(key, JSON.stringify(value));
}

export default function App() {
  const [game, setGame] = useState<Game | null>(null);
  const [llmMode, setLlmMode] = useState<"live" | "fixture" | null>(null);
  const [history, setHistory] = useState<TurnResult[]>([]);
  const [echoes, setEchoes] = useState<EchoRecord[]>([]);
  const [chat, setChat] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [preview, setPreview] = useState<{text: string; gameId: string; revision: number} | null>(null);
  const [diplomacyOpen,setDiplomacyOpen]=useState(false);
  const [diplomacyChoice,setDiplomacyChoice]=useState<'accept'|'reject'|'counter'>('counter');
  const [diplomacyBusy,setDiplomacyBusy]=useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [retryStatus, setRetryStatus] = useState<string | null>(null);
  const [inputError, setInputError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [showChronicle, setShowChronicle] = useState(false);
  const [showHelp, setShowHelp] = useState(false);
  const [showLibrary,setShowLibrary]=useState(false);
  const [switching, setSwitching] = useState(false);
  const [edictWarning, setEdictWarning] = useState<{
    type: WarningType;
    message: string;
  } | null>(null);
  const [savedGames, setSavedGames] = useState<SavedGameMeta[]>([]);
  const pendingRef = useRef<PendingState | null>(null);
  const initedRef = useRef(false);
  const chatEndRef = useRef<HTMLDivElement>(null);
  const warningDialogRef = useRef<HTMLDivElement>(null);
  const activeGameRef = useRef<string | null>(null);
  const busyRef = useRef(false);

  const applyDetail = useCallback((detail: GameDetail) => {
    activeGameRef.current = detail.game.id;
    setGame(detail.game);
    setHistory(detail.history);
    setEchoes(detail.echoes);
    setChat(buildChatFromHistory(detail.history));
    setDraft(localStorage.getItem(DRAFT_KEY(detail.game.id)) ?? "");
    setSavedGames((prev) => {
      const others = prev.filter((item) => item.id !== detail.game.id);
      return [
        ...others,
        {
          id: detail.game.id,
          turns: detail.game.accepted_turns,
          status: detail.game.status,
          endingTitle: detail.game.ending?.title,
        },
      ];
    });
    localStorage.setItem(CURRENT_KEY, detail.game.id);
  }, []);

  const loadGame = useCallback(
    async (gameId: string) => {
      const detail = await api.getGame(gameId);
      applyDetail(detail);
      const pending = loadJson<PendingState | null>(
        PENDING_KEY(gameId),
        null
      );
      // Old clients did not retain the complete request. Never guess a revision.
      pendingRef.current = pending && typeof pending.expectedRevision === "number" && pending.gameId === gameId ? pending : null;
      if (pending && !pendingRef.current) localStorage.removeItem(PENDING_KEY(gameId));
      if (pendingRef.current && detail.game.revision > pendingRef.current.expectedRevision) {
        const settled = detail.history.find((item) => item.turn_no === (pendingRef.current!.expectedTurn ?? pendingRef.current!.expectedRevision + 1));
        if (settled?.raw_text === pendingRef.current.text) {
          pendingRef.current = null;
          localStorage.removeItem(PENDING_KEY(gameId));
          localStorage.removeItem(DRAFT_KEY(gameId));
          setDraft("");
        }
      }
      return detail;
    },
    [applyDetail]
  );

  const startNewGame = useCallback(async () => {
    const detail = await api.createGame();
    pendingRef.current = null;
    applyDetail(detail);
    return detail;
  }, [applyDetail]);

  useEffect(() => {
    api.getHealth()
      .then((health) => setLlmMode(health.llm_mode))
      .catch(() => setLlmMode(null));
  }, []);

  useEffect(() => {
    if (initedRef.current) return;
    initedRef.current = true;

    (async () => {
      setSavedGames(loadJson<SavedGameMeta[]>(GAME_IDS_KEY, []));
      const currentId = localStorage.getItem(CURRENT_KEY);
      try {
        if (currentId) {
          try {
            await loadGame(currentId);
            setLoading(false);
            return;
          } catch (error) {
            if (error instanceof ApiError && error.status !== 404) {
              throw error;
            }
            localStorage.removeItem(CURRENT_KEY);
          }
        }
        await startNewGame();
      } catch (error) {
        const message =
          error instanceof ApiError
            ? error.message
            : "无法连接后端,请确认后端已启动(见 README)。";
        setLoadError(message);
      }
      setLoading(false);
    })();
  }, [loadGame, startNewGame]);

  useEffect(() => {
    if (game) {
      localStorage.setItem(DRAFT_KEY(game.id), draft);
    }
  }, [draft, game]);

  useEffect(() => {
    if (game) {
      if (pendingRef.current) {
        saveJson(PENDING_KEY(game.id), pendingRef.current);
      } else {
        localStorage.removeItem(PENDING_KEY(game.id));
      }
    }
  }, [game, submitting]);

  useEffect(() => {
    saveJson(GAME_IDS_KEY, savedGames);
  }, [savedGames]);

  useEffect(() => {
    if (!game) return;
    setSavedGames((prev) =>
      prev.map((item) =>
        item.id === game.id
          ? { ...item, turns: game.accepted_turns, status: game.status, endingTitle: game.ending?.title }
          : item
      )
    );
  }, [game]);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [chat, submitting]);

  useEffect(() => {
    if (!edictWarning || !warningDialogRef.current) return;
    const dialog = warningDialogRef.current;
    const previousFocus = document.activeElement as HTMLElement | null;
    const getFocusable = () =>
      Array.from(
        dialog.querySelectorAll<HTMLElement>(
          'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
        )
      );
    const frame = window.requestAnimationFrame(() => getFocusable()[0]?.focus());
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setEdictWarning(null);
        return;
      }
      if (event.key !== "Tab") return;
      const focusable = getFocusable();
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last?.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first?.focus();
      }
    };
    window.addEventListener("keydown", handleKey);
    return () => {
      window.cancelAnimationFrame(frame);
      window.removeEventListener("keydown", handleKey);
      previousFocus?.focus();
    };
  }, [edictWarning]);

  const removePendingBubble = useCallback(() => {
    const pending = pendingRef.current;
    if (!pending) return;
    setChat((prev) => prev.filter((msg) => msg.id !== pending.msgId));
  }, []);

  const syncFromServer = useCallback(async () => {
    if (!game) return;
    try {
      const detail = await api.getGame(game.id);
      applyDetail(detail);
    } catch {
      /* 核对失败时保持本地状态 */
    }
  }, [game, applyDetail]);

  const handleSubmit = useCallback(async () => {
    if (!game || busyRef.current) return;
    const text = draft.trim();
    if (text.length === 0) {
      setInputError("圣旨不能为空,请先拟定一道圣旨。");
      return;
    }
    if ([...text].length > MAX_CHARS) {
      setInputError(`圣旨不能超过 ${MAX_CHARS} 字。`);
      return;
    }
    setInputError(null);
    setRetryStatus(null);

    const pending = pendingRef.current;
    setChat(prev => prev.filter(msg => msg.kind !== "error" && !(pending && pending.text !== text && msg.id === pending.msgId)));
    let requestId: string;
    let msgId: string;
    if (pending && pending.text === text) {
      requestId = pending.requestId;
      msgId = pending.msgId;
    } else {
      requestId = crypto.randomUUID();
      msgId = `pending-${requestId}`;
      pendingRef.current = { requestId, text, msgId, expectedRevision: game.revision, expectedTurn:game.accepted_turns+1, gameId: game.id };
      setChat((prev) => [
        ...prev,
        {
          kind: "edict",
          id: msgId,
          text,
          status: "pending",
          turnNo: game.accepted_turns + 1,
        },
      ]);
    }

    const expectedRevision = pendingRef.current!.expectedRevision;
    saveJson(PENDING_KEY(game.id), pendingRef.current);
    busyRef.current = true;
    setSubmitting(true);

    let retries = 0;
    try {
      const response = await api.submitTurnWithRetry(game.id, {
        request_id: requestId,
        expected_revision: expectedRevision,
        expected_turn:pendingRef.current!.expectedTurn ?? game.accepted_turns+1,
        policy_text: text,
      }, progress => {
        retries = progress.retry;
        setRetryStatus(`正在第 ${progress.retry}/${progress.maxRetries} 次重试：${progress.reason}`);
      });
      if (activeGameRef.current !== game.id) return;

      if (response.kind === "recovered") {
        pendingRef.current = null;
        applyDetail(response.detail);
        setDraft("");
        return;
      }

      if (response.kind === "clarification") {
        removePendingBubble();
        pendingRef.current = null;
        setGame(response.game);
        setEdictWarning({ type: response.warning_type, message: response.message });
        return;
      }

      if(response.kind==='diplomacy'){
        pendingRef.current=null;
        applyDetail({game:response.game,history,echoes});
        setDraft(response.remaining_policy);
        localStorage.setItem(DRAFT_KEY(game.id),response.remaining_policy);
        setDiplomacyChoice(response.game.diplomacy?.pending ? 'accept' : 'counter');setDiplomacyOpen(true);
        return;
      }

      pendingRef.current = null;
      const newHistory = [...history.filter((item) => item.id !== response.result.id).map((item) => ({
        ...item, policy_status: response.policy_statuses?.[item.policy_id] ?? item.policy_status,
      })), response.result].sort((a, b) => a.turn_no - b.turn_no);
      setHistory(newHistory);
      setChat(buildChatFromHistory(newHistory));
      setEchoes((prev) => [
        ...prev.map((echo) =>
          response.result.echo_effects.some((effect) => effect.echo_id === echo.id)
            ? { ...echo, status: "resolved" as const, resolved_turn: response.result.turn_no }
            : echo
        ),
        ...response.result.new_echoes.map<EchoRecord>((echo) => ({
          id: echo.id,
          source_policy_id: echo.source_policy_id,
          due_turn: echo.due_turn,
          reason: echo.reason,
          effect_kind: echo.effect_kind,
          status: "pending",
          created_turn: echo.created_turn,
          resolved_turn: null,
        })),
      ]);
      setGame(response.game);
      setDraft("");
    } catch (error) {
      if (activeGameRef.current !== game.id) return;
      const apiError = error instanceof ApiError ? error : null;
      const status = apiError?.status ?? 0;

      if (status === 0 || apiError?.retryable) {
        const exhausted = retries === api.MAX_TURN_RETRIES ? "自动重试3次仍未成功。" : "";
        const reason = (apiError?.message ?? "发送失败").trim().replace(/[。；;.!?！？]+$/, "");
        setChat(prev => [...prev.filter(msg => msg.kind !== "error"), {
          kind:"error",id:`send-${requestId}`,
          text:`${exhausted}${reason}。草稿已保留，可稍后再次颁布；已完成的回合不会重复结算。`,
        }]);
      } else if (status === 422) {
        removePendingBubble();
        pendingRef.current = null;
        setInputError(apiError?.message ?? "圣旨格式有误。");
      } else if (status === 409) {
        removePendingBubble();
        pendingRef.current = null;
        await syncFromServer();
        setChat((prev) => [
          ...prev,
          {
            kind: "error",
            id: `conflict-${requestId}`,
            text: apiError?.message ?? "存档状态已变化,已刷新。",
          },
        ]);
      } else {
        setChat((prev) => [
          ...prev,
          {
            kind: "error",
            id: `send-${requestId}`,
            text: apiError?.message ?? "本回合尚未结算,请稍后重试。",
          },
        ]);
      }
    } finally {
      if (!pendingRef.current) localStorage.removeItem(PENDING_KEY(game.id));
      busyRef.current = false;
      setSubmitting(false);
      setRetryStatus(null);
    }
  }, [
    game,
    submitting,
    draft,
    history,
    applyDetail,
    removePendingBubble,
    syncFromServer,
  ]);

  const handleNewGame = useCallback(async () => {
    if (busyRef.current) return;
    if (
      game?.status === "playing" &&
      (game.accepted_turns > 0 || draft.trim().length > 0) &&
      !window.confirm("当前对局尚未结束。确定要另开新朝吗?旧局会保留在历史存档中。")
    ) {
      return;
    }
    try {
      busyRef.current = true;
      setSwitching(true);
      await startNewGame();
      setInputError(null);
    } catch (error) {
      setInputError(
        error instanceof ApiError ? error.message : "无法新建对局,请检查后端。"
      );
    } finally { busyRef.current = false; setSwitching(false); }
  }, [startNewGame, game, draft]);

  const handleSwitchGame = useCallback(
    async (gameId: string) => {
      if (!gameId || gameId === game?.id || busyRef.current) return;
      try {
        busyRef.current = true;
        setSwitching(true);
        await loadGame(gameId);
        setInputError(null);
      } catch (error) {
        setInputError(
          error instanceof ApiError ? error.message : "读取存档失败。"
        );
      } finally { busyRef.current = false; setSwitching(false); }
    },
    [game, loadGame]
  );

  if (loading) {
    return (
      <main className="page">
        <p className="loading">正在准备奏报……</p>
      </main>
    );
  }

  if (loadError) {
    return (
      <main className="page">
        <div className="bubble error" role="alert">
          <p className="bubble-text">{loadError}</p>
        </div>
        <button className="submit-button" onClick={() => window.location.reload()}>
          重新连接
        </button>
      </main>
    );
  }

  const finished = game !== null && game.status !== "playing";

  return (
    <main className="page">
      <div className="topbar">
        <Header
          game={game}
          llmMode={llmMode}
          onNewGame={handleNewGame}
          onShowChronicle={() => setShowChronicle(true)}
          busy={submitting || switching || diplomacyBusy}
          onShowHelp={() => setShowHelp(true)}
          onShowLibrary={()=>setShowLibrary(true)}
        />
        <MetricsBar game={game} />
      </div>
      <Decorations />

      {savedGames.length > 1 && (
        <div className="saved-games">
          <label htmlFor="saved-games-select">历史存档</label>
          <select
            id="saved-games-select"
            value={game?.id ?? ""}
            disabled={submitting || switching || diplomacyBusy}
            onChange={(event) => handleSwitchGame(event.target.value)}
          >
            {savedGames.map((item) => (
              <option key={item.id} value={item.id}>
                {item.id.slice(0, 8)} · {item.turns}/8 回合 ·{" "}
                {item.endingTitle ?? (item.status === "playing"
                  ? "进行中"
                  : item.status === "won"
                    ? "已获胜"
                    : "已失败")}
              </option>
            ))}
          </select>
        </div>
      )}

      {game && <CrisisPanel key={game.id} game={game} />}
      {!finished && <section className="chat-log" aria-label="奏报记录" aria-live="polite">
        {game?.opening && <OpeningBriefing key={game.id} game={game} />}
        {chat.length === 0 && !game?.opening && (
          <div className="chat-empty">
            <p>输入一道圣旨,听见天下的回应。</p>
            <p>八回合内使民心达到 80；每回合三年。</p>
            <p>试试“减轻灾州田赋”或“雇工修城西水渠”。同一目标允许配套措施。</p>
            <button className="secondary-button" onClick={() => setShowHelp(true)}>查看国情与完整规则</button>
          </div>
        )}
        {chat.map((message) =>
          message.kind === "turn-card" ? (
            <TurnResultCard key={message.id} result={message.result} />
          ) : (
            <MessageBubble key={message.id} message={message} />
          )
        )}
        <div ref={chatEndRef} />
      </section>}

      {finished && game ? (
        <EndingView
          game={game}
          history={history}
          echoes={echoes}
          onNewGame={handleNewGame}
          onShowChronicle={() => setShowChronicle(true)}
        />
      ) : (
        <EdictInput
          value={draft}
          onChange={setDraft}
          onSubmit={() => {
            if (!game || busyRef.current || switching || !draft.trim()) return;
            if ([...draft.trim()].length > MAX_CHARS) {
              setInputError(`圣旨不能超过 ${MAX_CHARS} 字。`);
              return;
            }
            setInputError(null);
            setPreview({text: draft.trim(), gameId: game.id, revision: game.revision});
          }}
          disabled={game === null || switching || diplomacyBusy}
          policyDisabled={(game?.accepted_turns ?? 0)>=8}
          submitting={submitting}
          sendingStatus={retryStatus}
          error={inputError}
          treaty={game?.diplomacy?.pending ?? game?.events?.war?.pending_treaty}
          onTreatyDecision={decision=>{
            if(!game || busyRef.current || switching)return;
            setDiplomacyChoice(decision==='counter'?'counter':decision);setDiplomacyOpen(true);
          }}
        />
      )}

      {preview && <EdictPreview text={preview.text} gameId={preview.gameId} revision={preview.revision} onCancel={() => setPreview(null)} onConfirm={() => {
        const current = preview;
        setPreview(null);
        if (!game || current.gameId !== game.id || current.revision !== game.revision || current.text !== draft.trim()) {
          setInputError('草稿或存档已更新，请重新预览。');
          return;
        }
        void handleSubmit();
      }} />}

      {game && diplomacyOpen && <DiplomacyModal key={game.id} game={game} initial={diplomacyChoice}
        onClose={()=>setDiplomacyOpen(false)} onBusy={busy=>{busyRef.current=busy;setDiplomacyBusy(busy);}}
        onResult={response=>{if(activeGameRef.current!==response.game.id)return;
          const keptDraft=draft;applyDetail({game:response.game,history,echoes});setDraft(keptDraft);
        }}/ >}

      <ChronicleModal
        game={game}
        history={history}
        open={showChronicle}
        onClose={() => setShowChronicle(false)}
      />
      <HelpModal open={showHelp} onClose={() => setShowHelp(false)} game={game} history={history} />
      <EmperorLibrary open={showLibrary} onClose={()=>setShowLibrary(false)}/>

      {edictWarning && (
        <div
          className="modal-backdrop"
          role="dialog"
          aria-modal="true"
          aria-labelledby="edict-warning-title"
          onClick={() => setEdictWarning(null)}
        >
          <div
            className="modal era-warning"
            ref={warningDialogRef}
            onClick={(event) => event.stopPropagation()}
          >
            <div className="modal-head">
              <h2 className="modal-title" id="edict-warning-title">
                {WARNING_COPY[edictWarning.type].title}
              </h2>
              <button
                className="modal-close"
                onClick={() => setEdictWarning(null)}
                aria-label="关闭圣旨警告"
              >
                ×
              </button>
            </div>
            <div className="modal-body">
              <p className="era-warning-message">{edictWarning.message}</p>
              <p className="era-warning-note">{WARNING_COPY[edictWarning.type].note}</p>
              <button className="secondary-button" onClick={() => setEdictWarning(null)} autoFocus>
                知道了
              </button>
            </div>
          </div>
        </div>
      )}
    </main>
  );
}
