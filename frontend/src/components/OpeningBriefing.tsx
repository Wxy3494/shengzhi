import { useEffect, useState } from "react";
import type { Game } from "../types/game";
import { getOpeningBriefing } from "../api/client";
import { ApiError } from "../types/game";

export default function OpeningBriefing({ game }: { game: Game }) {
  const [text, setText] = useState("");
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let active = true;
    setText(""); setError("");
    getOpeningBriefing(game.id).then(r => { if (active && r.game_id === game.id) setText(r.briefing); })
      .catch(e => { if (active) setError(e instanceof ApiError && e.code !== "NETWORK_ERROR" ? e.message : "开场奏报暂未送达，国情已保存，可以重试。"); });
    return () => { active = false; };
  }, [game.id, attempt]);
  if (!game.opening) return null;
  return <article className="opening-briefing" aria-label="沈砚登基奏报">
    <img src="/avatars/shen.png" alt="沈砚" />
    <div><details open={game.accepted_turns === 0}>
      <summary>沈砚 · 登基奏报 <strong>{game.opening.name}</strong></summary>
      {!text && !error && <p role="status">沈砚正在整理开朝奏报……</p>}
      {text && <p className="opening-speech">{text}</p>}
      {error && <div role="alert"><p>{error}</p><button className="secondary-button" onClick={() => setAttempt(n => n + 1)}>重呈奏报</button></div>}
      <dl><dt>登基时优势</dt><dd>{game.opening.advantage}</dd><dt>登基时困难</dt><dd>{game.opening.difficulty}</dd></dl>
      <p className="opening-note">{game.schema_version >= 4 ? '本局共八道圣旨，第八回合民心达到80获胜。国运事件在回合末公告，下一道圣旨可回应；开局快照不会改变，也不提供永久扣罚。' : '开局协作机会限前两回合；针对旧患施政可确认化解，不会永久固定扣罚。'}</p>
    </details></div>
  </article>;
}
