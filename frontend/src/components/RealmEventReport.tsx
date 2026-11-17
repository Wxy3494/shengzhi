import type { RealmEvent, TurnResult } from '../types/game';

export function eventOutcome(event: RealmEvent): string {
  return ({well_handled:'妥善处理',mitigated:'部分缓解',escalated:'未回应，后果已结清',expired:'机会已到期',closed:'已结',pending:'待下一道圣旨回应'} as Record<string,string>)[event.outcome] ?? event.status;
}
export default function RealmEventReport({report}:{report: NonNullable<TurnResult['events']>}) {
  const announced=report.announcement;
  return <section className="realm-event-report" aria-label="天时国运奏报">
    {report.responses.map(event => <p key={event.instance_id}><strong>{event.name} · {eventOutcome(event)}</strong><br />
      回应的是第 {event.announced_turn} 回合所报之事；本次影响已计入结算，后果不再反复追罚。
      {event.response_effects && <small>民心 {event.response_effects.people} · 国库 {event.response_effects.treasury} · 粮储 {event.response_effects.grain}</small>}
    </p>)}
    {report.quiet && <p className="event-quiet">{report.war ? '本回合没有新增天时国运事件。' : report.quiet}</p>}
    {report.watch && <p>{report.watch}</p>}
    {announced && <div><h3>回合末 · 天时国运</h3><strong>{announced.name} · {({small:"小事",medium:"要事",major:"大事"} as Record<string,string>)[announced.tier]}</strong><p>{announced.announcement}
      </p>
      <small>本次即时影响已计入：民心 {announced.immediate_effects.people} · 国库 {announced.immediate_effects.treasury} · 粮储 {announced.immediate_effects.grain}。</small>
    </div>}
  </section>;
}
