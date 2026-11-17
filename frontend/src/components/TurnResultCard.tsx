import type { TurnResult } from "../types/game";
import { periodName } from "../types/game";
import { formatRiskSentence } from "../types/riskText";
import MessageBubble from "./MessageBubble";
import RealmEventReport from './RealmEventReport';
import { displayBattleText } from '../types/warText';

interface Props {
  result: TurnResult;
}

function signed(value: number): string {
  if (value > 0) return `+${value}`;
  if (value < 0) return `−${Math.abs(value)}`;
  return "0";
}

function metricsLine(before: number, after: number, applied: number): string {
  const change = after !== before ? `(${signed(applied)})` : "(不变)";
  return `${before} → ${after} ${change}`;
}

export default function TurnResultCard({ result }: Props) {
  const { before, after, applied_effects } = result;

  return (
    <article className="message-row report-row">
      <img className="portrait portrait-shen" src="/avatars/shen.png" alt="沈砚" />
      <div className="message-main">
        <div className="speaker-tag advisor-tag">沈砚 · 本回合奏报</div>
        <div className="turn-card">
          <div className="turn-card-head">
            <span className="turn-card-title">
              民心 {metricsLine(before.people, after.people, applied_effects.people)}
            </span>
            <span className="turn-card-season">
              {periodName(result.turn_no)} · 第 {result.turn_no} / 8 回合
            </span>
          </div>
          <div className="turn-card-body">
            <p className="execution-summary">{result.summary}</p>
            {result.execution?.actual_policy_effect && <p className="analysis-caption">本次新政民心 {signed(result.execution.actual_policy_effect.people)}；本回合总变化 {signed(applied_effects.people)}（还包含战事、旧政与国运影响）。</p>}
            {result.events?.war && <section className="war-report" aria-label="战报">
              <h3>战报 · {result.events.war.outcome === 'victory' ? '获胜' : '战败'}</h3>
              <p>{displayBattleText(result.events.war.text)}</p>
              <p>出征支出：国库 −{result.events.war.paid_cost.treasury} · 粮储 −{result.events.war.paid_cost.grain}</p>
              {result.events.war.outcome === 'victory' ? <p>缴获回补：国库 +{result.events.war.returns.treasury} · 粮储 +{result.events.war.returns.grain}</p>
                : <p>败退损失：国库 −{result.events.war.extra_loss.treasury} · 粮储 −{result.events.war.extra_loss.grain}</p>}
              <p>本役净变化：民心 {signed(result.events.war.effects.people)} · 国库 {signed(result.events.war.effects.treasury)} · 粮储 {signed(result.events.war.effects.grain)}</p>
              {result.events.war.cities_lost > 0 && <p>本朝累计割让城池：{result.events.war.cities_lost} 座</p>}
            </section>}
            {result.events?.treaty && <section className="war-report treaty-report" aria-label="议和条款">
              <h3>议和条款 · {{pending:'待御裁',accepted:'已签约',unfunded:'未能履约',expired:'未获确认'}[result.events.treaty.status]}</h3>
              <p>{result.events.treaty.direction==='pay' ? '对方要求我朝交付' : '对方向我朝交付'}：城池 {result.events.treaty.terms.cities} 座 · 国库 {result.events.treaty.terms.treasury} · 粮储 {result.events.treaty.terms.grain}</p>
              <p>{result.events.treaty.terms.reason}</p>
              {result.events.treaty.status==='pending' && <p>尚未签约。可在当回合议和窗口接受、拒绝或还价，不占治理圣旨。</p>}
              {result.events.treaty.status==='unfunded' && <p>现有钱粮不足以兑现条件，未付款、未割城；原提案仍待处理。</p>}
              {result.events.treaty.status==='expired' && <p>本局结束前未确认，条款没有生效，未作割城赔付。</p>}
              {result.events.treaty.status==='accepted' && <p>已按玩家同意的条款签约，战争结束。钱粮与城池转移已记入本朝记录。</p>}
              {result.events.treaty.effects && <p>本次履约净变化：国库 {signed(result.events.treaty.effects.treasury)} · 粮储 {signed(result.events.treaty.effects.grain)}</p>}
            </section>}
            <details className="original-goal"><summary>原诏目标与执行范围</summary>
              <p>{result.raw_text}</p>
              <p>实际执行：{result.execution?.blocked ? "所需资源不足，未能实施" : result.summary}</p>
              {result.policy_intent && <p>适用地区：{result.policy_intent.region} · {result.policy_intent.duration_years ? `期限 ${result.policy_intent.duration_years} 年` : "未指定固定期限"}</p>}
            </details>
            <div className="metrics-line dim">
              <span className="metrics-name">国库</span>
              <span className="metrics-change">
                {metricsLine(before.treasury, after.treasury, applied_effects.treasury)}
              </span>
            </div>
            <div className="metrics-line dim">
              <span className="metrics-name">粮储</span>
              <span className="metrics-change">
                {metricsLine(before.grain, after.grain, applied_effects.grain)}
              </span>
            </div>
          </div>

          {result.policy_analysis?.benefits?.length ? (
            <div className="policy-analysis">
              <h3>政策权衡</h3>
              <p className="analysis-caption">受益与代价是本次推演的判断；后患列出发生条件，不代表必然发生。</p>
              <div className="analysis-columns">
                <div><h4>可能受益</h4>{result.policy_analysis.benefits.map((item, index) => <p key={index}>{item}</p>)}</div>
                <div><h4>代价与取舍</h4>{result.policy_analysis.costs?.map((item, index) => <p key={index}>{item}</p>)}</div>
              </div>
              {result.policy_analysis.risks?.map((risk, index) => <p className="policy-risk" key={index}>
                <strong>{risk.horizon === "delayed" ? "后续隐患" : "当下风险"} · {{ low: "风险较低", medium: "值得防范", high: "风险较高" }[risk.likelihood]}</strong>
                <span>{formatRiskSentence(risk.condition, risk.consequence)}</span>
              </p>)}
              {result.policy_analysis.effect_basis && <p className="effect-basis">综合判断：{result.policy_analysis.effect_basis}</p>}
            </div>
          ) : null}

          {result.echo_effects.length > 0 && (
            <div className="echo-effects">
              <div className="echo-title">旧诏回响</div>
              {result.echo_effects.map((echo) => (
                <div className="echo-item" key={echo.echo_id}>
                  <div className="echo-source">
                    第 {echo.created_turn} 回合「{echo.source_raw_text ?? "原圣旨"}」 · {echo.reason}
                  </div>
                  <div className="echo-detail">
                    {echo.explanation}
                    {echo.people !== 0 || echo.treasury !== 0 || echo.grain !== 0 ? (
                      <span className="echo-deltas">
                        民心 {signed(echo.people)},国库 {signed(echo.treasury)},粮储{" "}
                        {signed(echo.grain)}
                      </span>
                    ) : (
                      <span className="echo-deltas">本回合无实际影响</span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}

          {result.new_echoes.length > 0 && (
            <div className="echo-effects new-echo-effects">
              <div className="echo-title">新政回声</div>
              {result.new_echoes.map((echo) => (
                <div className="echo-item" key={echo.id}>
                  <div className="echo-source">
                    将于第 {echo.due_turn} 回合 · {periodName(echo.due_turn)}触发
                  </div>
                  <div className="echo-detail">{echo.reason}</div>
                </div>
              ))}
            </div>
          )}

          {result.constraint_notes && result.constraint_notes.length > 0 && (
            <div className="echo-effects constraint-notes">
              <div className="echo-title">执行约束</div>
              {result.constraint_notes.map((note) => (
                <div className="echo-detail" key={note}>{note}</div>
              ))}
            </div>
          )}

          <details className="full-report" open><summary>沈砚奏对与天下回应</summary>
            <MessageBubble message={{ kind: "advisor", id: `advisor-${result.id}`, text: result.advisor, turnNo: result.turn_no }} />
            {result.reactions.map((reaction) => <MessageBubble key={reaction.speaker} message={{ kind: "reaction", id: `${result.id}-${reaction.speaker}`, speaker: reaction.speaker, text: reaction.text, turnNo: result.turn_no }} />)}
          </details>

          {result.events && (result.events.announcement || result.events.responses.length > 0 || result.events.watch || result.events.quiet) && <RealmEventReport report={result.events} />}

        </div>
      </div>
    </article>
  );
}
