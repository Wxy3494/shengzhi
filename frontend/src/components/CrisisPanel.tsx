import { useEffect, useRef, useState } from "react";
import type { Game, Realm } from "../types/game";
import { takeCrisisNotices } from "../types/crisisNotices";

type Warning = Realm["warnings"][number];
export default function CrisisPanel({ game }: { game: Game }) {
  const [visible, setVisible] = useState<Warning[]>([]);
  const batch = useRef("");
  useEffect(() => {
    const batchId = `${game.id}:${game.revision}`;
    if (batch.current === batchId) return;
    batch.current = batchId;
    setVisible(takeCrisisNotices(game, localStorage));
  }, [game.id, game.revision, game.realm]);
  if (!visible.length) return null;
  return <aside className="crisis-panel" aria-label="朝廷急报" role="alert">
    {visible.map(w => <div key={`${w.id}:${w.threshold}`} className={`crisis-warning ${w.level}`}>
      <strong>{w.threshold === 90 ? "告急" : "预警"} · {w.label}</strong>
      <p>{w.reason}</p><p>{w.advice}</p>
    </div>)}
    <button className="link-button" onClick={() => setVisible([])}>朕已知晓</button>
  </aside>;
}
