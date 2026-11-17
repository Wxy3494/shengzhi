import type { Game } from "../types/game";
import { periodName } from "../types/game";

interface Props {
  game: Game | null;
}

function MetricIcon({ kind }: { kind: "season" | "people" | "treasury" | "grain" }) {
  if (kind === "people") {
    return (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M12 20.5 3.8 12.3A5.3 5.3 0 0 1 11.3 4.8l.7.7.7-.7a5.3 5.3 0 0 1 7.5 7.5Z" />
      </svg>
    );
  }
  if (kind === "treasury") {
    return (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <ellipse cx="12" cy="6" rx="7" ry="3" />
        <path d="M5 6v4c0 1.7 3.1 3 7 3s7-1.3 7-3V6M5 10v4c0 1.7 3.1 3 7 3s7-1.3 7-3v-4M5 14v4c0 1.7 3.1 3 7 3s7-1.3 7-3v-4" />
      </svg>
    );
  }
  if (kind === "grain") {
    return (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M8 21 16 3M12 15c-4 0-6-2-6-5 4 0 6 2 6 5Zm3-5c-4 0-6-2-6-5 4 0 6 2 6 5Zm-5 9c-4 0-6-2-6-5 4 0 6 2 6 5Zm4-3c4 0 6-2 6-5-4 0-6 2-6 5Zm-2 5c4 0 6-2 6-5-4 0-6 2-6 5Z" />
      </svg>
    );
  }
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M12 21c-5-3-7-7-6-12 4 0 6 2 6 6 0-4 2-6 6-6 1 5-1 9-6 12Z" />
      <path d="M12 15c-3-2-4-5-3-9 3 1 4 3 3 6 1-3 3-4 6-4 0 4-2 6-6 7ZM7 5 5 2m12 3 2-3" />
    </svg>
  );
}

export default function MetricsBar({ game }: Props) {
  const people = game?.people ?? 50;
  const treasury = game?.treasury ?? 60;
  const grain = game?.grain ?? 60;
  const turn = game ? Math.min(game.accepted_turns + 1, 8) : 1;
  const finished = game !== null && game.status !== "playing";
  const shownTurn = finished ? game.accepted_turns : turn;

  return (
    <section className="metrics-bar" aria-label="王朝概况">
      <div className="metric season">
        <span className="metric-icon"><MetricIcon kind="season" /></span>
        <span className="metric-label dynasty">{periodName(shownTurn)}</span>
        <span className="metric-divider" aria-hidden="true" />
        <span className="metric-value">第 {shownTurn} / 8 回合</span>
      </div>
      <div className="metric people">
        <span className="metric-icon"><MetricIcon kind="people" /></span>
        <span className="metric-label">民心</span>
        <span className="metric-value">{people}/100</span>
      </div>
      <div className="metric dim">
        <span className="metric-icon"><MetricIcon kind="treasury" /></span>
        <span className="metric-label">国库</span>
        <span className="metric-value">{treasury}</span>
      </div>
      <div className="metric dim">
        <span className="metric-icon"><MetricIcon kind="grain" /></span>
        <span className="metric-label">粮储</span>
        <span className="metric-value">{grain}</span>
      </div>
    </section>
  );
}
