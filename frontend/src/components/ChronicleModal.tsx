import { useEffect, useRef } from "react";
import type { Game, TurnResult } from "../types/game";
import { periodName } from "../types/game";

interface Props {
  game: Game | null;
  history: TurnResult[];
  open: boolean;
  onClose: () => void;
}

export default function ChronicleModal({ game, history, open, onClose }: Props) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const onCloseRef = useRef(onClose);

  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    if (!open || !dialogRef.current) return;
    const dialog = dialogRef.current;
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
        onCloseRef.current();
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
  }, [open]);

  if (!open) return null;

  return (
    <div
      className="modal-backdrop"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label="皇帝纪事"
    >
      <div className="modal" ref={dialogRef} onClick={(event) => event.stopPropagation()}>
        <div className="modal-head">
          <h2 className="modal-title">皇帝纪事</h2>
          <button className="modal-close" onClick={onClose} aria-label="关闭纪事">
            ×
          </button>
        </div>
        <div className="modal-body">
          <p className="chronicle-summary">
            本局共颁 {history.length} 道圣旨。
            {game?.status === "won" && `民心达到 ${game.people},天下渐安。`}
            {game?.status === "lost" && (game.ending ? `${game.ending.title}：${game.ending.text}` : `民心止于 ${game.people},八回合、二十四年已尽。`)}
            {game?.status === "playing" && "尚未分出胜负。"}
          </p>
          {history.length === 0 && (
            <p className="chronicle-empty">本局尚未颁布圣旨。</p>
          )}
          {history.map((result) => (
            <article className="chronicle-item" key={result.id}>
              <div className="chronicle-head">
                <span className="chronicle-season">
                  {periodName(result.turn_no)} · 第 {result.turn_no} / 8 回合
                </span>
                <span className="chronicle-people">
                  民心 {result.before.people} → {result.after.people}
                </span>
              </div>
              <p className="chronicle-edict">{result.raw_text}</p>
              <p className="chronicle-summary-line">{result.summary}</p>
            </article>
          ))}
        </div>
      </div>
    </div>
  );
}
