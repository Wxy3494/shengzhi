import type { Game } from "../types/game";

interface Props {
  game: Game | null;
  llmMode: "live" | "fixture" | null;
  onNewGame: () => void;
  onShowChronicle?: () => void;
  busy?: boolean;
  onShowHelp: () => void;
  onShowLibrary?:()=>void;
}

export default function Header({ game, llmMode, onNewGame, onShowChronicle, busy, onShowHelp,onShowLibrary }: Props) {
  const finished = game !== null && game.status !== "playing";
  const modeLabel = llmMode === "live" ? "真实模型" : llmMode === "fixture" ? "演示 / 回归" : "模式未确认";

  return (
    <header className="header">
      <div className="header-row">
        <span className="title-seal" aria-hidden="true">
          御
        </span>
        <h1 className="title">圣旨输入中……</h1>
        <div className="header-tools">
          {game && game.schema_version < 4 && <span className="mode-badge">旧版存档</span>}
          {llmMode !== "live" && <span className={`mode-badge mode-${llmMode ?? "unknown"}`}>
            {modeLabel}
          </span>}
          {game && onShowChronicle && (
            <button className="link-button" onClick={onShowChronicle}>
              皇帝纪事
            </button>
          )}
          <button className="link-button" onClick={onShowHelp}>国情与规则</button>
          {onShowLibrary&&<button className="link-button" onClick={onShowLibrary}>帝王图鉴</button>}
          {game && (
            <button className="link-button" onClick={onNewGame} disabled={busy}>
              新开一局
            </button>
          )}
        </div>
      </div>
      <div className="subtitle-row">
        <span className="subtitle-line" aria-hidden="true" />
        <p className="subtitle">
          圣旨已下,后果未卜。{finished ? " 本局已结束。" : ""}
        </p>
        <span className="subtitle-line" aria-hidden="true" />
      </div>
      {game && game.schema_version < 4 && <p className="legacy-save-note">此存档沿用旧版提前结局规则。新开一局可体验完整八回合的天时国运，原有纪事仍会保留。</p>}
    </header>
  );
}
