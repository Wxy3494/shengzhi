import type { EchoRecord, Game, TurnResult } from "../types/game";
import { YEARS_PER_TURN } from "../types/game";
import EmperorPortrait from "./EmperorPortrait";
import { eventOutcome } from './RealmEventReport';

interface Props {
  game: Game;
  history: TurnResult[];
  echoes: EchoRecord[];
  onNewGame: () => void;
  onShowChronicle: () => void;
}

export default function EndingView({ game, echoes, onNewGame, onShowChronicle }: Props) {
  const won = game.status === "won";
  const ending = game.ending;
  return (
    <section className={`ending ending-${game.status} ending-codex`} role="status">
      <div className="ending-content">
        {game.schema_version < 4 && game.accepted_turns < 8 && <p className="legacy-ending-note">旧版存档已按原规则提前结算。新局一般在第八回合判定胜负，严重战败亡国可提前结束。</p>}
        <div className="codex-ending-summary"><span>{ending?.title ?? (won ? "承平" : "终局")}</span><p>共颁 {game.accepted_turns} 道圣旨 · 历经 {game.accepted_turns * YEARS_PER_TURN} 年 · 民心 {game.people}<small>{ending?.text ?? (won ? "民心归附，本朝渐安。" : "八回合已尽，本朝落幕。")}</small>{!!ending?.source_turns.length && <small>关联施政与国情记录：第 {ending.source_turns.join("、")} 回合</small>}</p></div>
        {game.opening && <section className="reign-comparison" aria-label="开局与终局对照"><h3>{game.opening.name} · 一朝兴替</h3>
          <table><thead><tr><th>国情</th><th>登基时</th><th>终局时</th></tr></thead><tbody>{(["people", "treasury", "grain"] as const).map(k => <tr key={k}><th>{{people:"民心",treasury:"国库",grain:"粮储"}[k]}</th><td>{game.opening!.initial[k]}</td><td>{game[k]}</td></tr>)}</tbody></table>
          <p>开局旧患：{game.opening.difficulty} · {game.conditions?.resolved ? (game.conditions.resolved_turn ? `第${game.conditions.resolved_turn}回合已确认改善` : '终局国情已达到修复标准') : "尚未达到修复标准"}</p>
          <p>遗留回声：{echoes.filter(e => e.status === "pending").length} 项尚待查考，未作已发生后果。</p>
        </section>}
        {game.events?.appraisal && <section className="reign-comparison" aria-label="应天处变">
          <h3>应天处变 · {game.events.appraisal.handling_score}</h3>
          <p>一朝 {game.events.appraisal.event_count} 件主事，妥善处理 {game.events.appraisal.resolved_count} 件，升级结清 {game.events.appraisal.escalated_count} 件。</p>
          {game.events.records.map(e => <p key={e.instance_id}>第 {e.announced_turn} 回合 · {e.name}：{eventOutcome(e)}</p>)}
        </section>}
        <EmperorPortrait key={game.id} gameId={game.id} />
      </div>
      <div className="ending-actions">
        <button className="secondary-button" onClick={onShowChronicle}>查看皇帝纪事</button>
        <button className="submit-button" onClick={onNewGame}>{game.schema_version < 4 ? "开启八回合新局" : "再启新朝"}</button>
      </div>
    </section>
  );
}
