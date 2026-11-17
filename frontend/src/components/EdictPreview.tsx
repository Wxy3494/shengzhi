import { useEffect, useRef, useState } from 'react';
import { previewPolicy, type PolicyPreview } from '../api/client';

export default function EdictPreview({text, gameId, revision, onCancel, onConfirm}: {
  text: string; gameId: string; revision: number; onCancel: () => void; onConfirm: () => void;
}) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const cancelRef = useRef(onCancel);
  cancelRef.current = onCancel;
  const [plan,setPlan]=useState<PolicyPreview | null>(null);
  const [error,setError]=useState('');
  const [attempt,setAttempt]=useState(0);
  useEffect(() => {
    let active=true;setPlan(null);setError('');
    previewPolicy(gameId,revision,text).then(result => {
      if(active && result.game_id===gameId && result.revision===revision && result.policy_text===text)setPlan(result);
    }).catch(e=>{if(active)setError(e instanceof Error ? e.message : '预览未完成，请重试。');});
    return ()=>{active=false;};
  },[text,gameId,revision,attempt]);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const dialog = dialogRef.current!;
    const buttons = () => Array.from(dialog.querySelectorAll<HTMLButtonElement>('button:not([disabled])'));
    buttons()[0]?.focus();
    const keydown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') cancelRef.current();
      if (event.key === 'Tab') {
        const items=buttons();
        if (event.shiftKey && document.activeElement === items[0]) {
          event.preventDefault(); items[items.length - 1]?.focus();
        } else if (!event.shiftKey && document.activeElement === items[items.length - 1]) {
          event.preventDefault(); items[0]?.focus();
        }
      }
    };
    window.addEventListener('keydown', keydown);
    return () => { window.removeEventListener('keydown', keydown); previous?.focus(); };
  }, []);
  return <div className="modal-backdrop" onClick={onCancel}>
    <div className="modal edict-preview" ref={dialogRef} role="dialog" aria-modal="true"
      aria-labelledby="edict-preview-title" onClick={event => event.stopPropagation()}>
      <div className="modal-head"><h2 className="modal-title" id="edict-preview-title">诏意预览</h2>
        <button className="modal-close" onClick={onCancel} aria-label="返回修改">×</button></div>
      <div className="modal-body">
        <p className="edict-preview-note">核对系统准备执行的事项，再确认颁布。预览不消耗回合。</p>
        {!plan && !error && <p role="status">正在核对诏意与本回合待办……</p>}
        {error && <div role="alert"><p>{error}</p><button className="secondary-button" onClick={()=>setAttempt(n=>n+1)}>重试预览</button></div>}
        {plan && <>
          <dl>{plan.execution && <><dt>系统准备执行</dt><dd>{plan.execution}</dd></>}
          <dt>实施方式</dt><dd>{plan.methods.length ? plan.methods.join('；') : '按原诏内容办理，未指定额外方式。'}</dd>
          <dt>禁止事项</dt><dd>{plan.prohibitions.length ? plan.prohibitions.join('；') : '未写明禁止事项。'}</dd></dl>
          {plan.treaty && <p>当前和约{plan.treaty.direction==='pay' ? '交付' : '收取'}：城池 {plan.treaty.terms.cities} 座 · 国库 {plan.treaty.terms.treasury} · 粮储 {plan.treaty.terms.grain}</p>}
          <h3>本回合即将到期</h3>
          {plan.due_events.length ? plan.due_events.map(e=><p key={e.id}>{e.name} · 第 {e.turn} 回合到期</p>) : <p>没有即将到期的国运事件。</p>}
          {plan.due_echoes.length>0 && <details><summary>本回合查考的旧诏后效（{plan.due_echoes.length}项）</summary>{plan.due_echoes.map(e=><p key={e.id}>{e.reason}</p>)}</details>}
          {plan.notes.map((note,index)=><p key={index} className="edict-preview-note">{note}</p>)}
        </>}
        <details><summary>圣旨原文</summary><p className="edict-preview-original">{text}</p></details>
        <div className="edict-preview-actions">
          <button className="secondary-button" onClick={onCancel}>返回修改</button>
          <button className="secondary-button" disabled={!plan} onClick={onConfirm}>确认颁布</button>
        </div>
      </div>
    </div>
  </div>;
}
