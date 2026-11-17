import {useEffect,useRef,useState} from 'react';
import type {Game,DiplomacyResponse} from '../types/game';
import {negotiateNow,type DiplomacyBody} from '../api/client';

export default function DiplomacyModal({game,initial,onClose,onResult,onBusy}:{
  game:Game;initial:'accept'|'reject'|'counter';onClose:()=>void;
  onResult:(response:DiplomacyResponse)=>void;onBusy:(busy:boolean)=>void;
}) {
  const [choice,setChoice]=useState(initial),[text,setText]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState('');
  const requestRef=useRef<{signature:string;body:DiplomacyBody}|null>(null);
  const dialog=useRef<HTMLDivElement>(null);const busyRef=useRef(false);
  const pending=game.diplomacy?.pending ?? game.events?.war?.pending_treaty;
  const records=game.diplomacy?.records ?? [];
  const latest=records[records.length-1];
  const reply=pending && latest?.action==='counter' && latest.proposal?.id===pending.id ? latest.reply : null;
  useEffect(()=>{
    const previous=document.activeElement as HTMLElement|null;
    dialog.current?.querySelector<HTMLButtonElement>('button')?.focus();
    const key=(e:KeyboardEvent)=>{
      if(e.key==='Escape' && !busyRef.current)onClose();
      if(e.key==='Tab'){
        const fields=Array.from(dialog.current?.querySelectorAll<HTMLElement>('button:not([disabled]), textarea:not([disabled])') ?? []);
        const first=fields[0],last=fields[fields.length-1];
        if(e.shiftKey && document.activeElement===first){e.preventDefault();last?.focus();}
        else if(!e.shiftKey && document.activeElement===last){e.preventDefault();first?.focus();}
      }
    };
    window.addEventListener('keydown',key);return()=>{window.removeEventListener('keydown',key);previous?.focus();};
  },[]);
  async function send(){
    if(busyRef.current)return;
    if(choice==='counter'&&!text.trim()){setError('请先填写还价条件。');return;}
    const signature=JSON.stringify([game.id,choice,text,pending?.id]);
    const body=requestRef.current?.signature===signature ? requestRef.current.body : {
      request_id:crypto.randomUUID(),expected_revision:game.revision,action:choice,text,proposal_id:pending?.id};
    requestRef.current={signature,body};busyRef.current=true;setBusy(true);onBusy(true);setError('');
    try {const result=await negotiateNow(game.id,body);requestRef.current=null;onResult(result);setText('');}
    catch(e){setError(e instanceof Error ? e.message : '谈判未完成，请重试。');}
    finally{busyRef.current=false;setBusy(false);onBusy(false);}
  }
  return <div className="modal-backdrop"><div ref={dialog} className="modal edict-preview" role="dialog" aria-modal="true" aria-labelledby="diplomacy-title">
    <div className="modal-head"><h2 id="diplomacy-title" className="modal-title">当回合议和</h2><button className="modal-close" disabled={busy} onClick={onClose} aria-label="关闭议和">×</button></div>
    <div className="modal-body">
      {reply && <section className="diplomacy-reply" aria-label="对方还价答复">
        <h3>{{accepted:'对方同意本次还价',rejected:'对方拒绝本次还价',counter:'对方另提条件，未同意本次要求'}[reply.decision]}</h3>
        <table><thead><tr><th>条款</th><th>原条件</th><th>本次要求</th><th>对方答复</th></tr></thead><tbody>
          {(['cities','treasury','grain'] as const).map(key=><tr key={key}><th>{{cities:'城池',treasury:'国库',grain:'粮储'}[key]}</th><td>{reply.previous_terms?.[key]??'—'}</td><td>{reply.requested_terms?.[key]??'未指定'}</td><td>{reply.offered_terms[key]}{reply.changes && reply.changes[key]!==0 ? `（${reply.changes[key]>0?'+':''}${reply.changes[key]}）` : ''}</td></tr>)}
        </tbody></table>
        <p>{reply.decision==='rejected'?'原条款保留。':'以下条款仍须确认签署。'}</p>
      </section>}
      {pending ? <p>当前条款：{pending.direction==='pay'?'交付':'收取'}城池 {pending.terms.cities} 座 · 国库 {pending.terms.treasury} · 粮储 {pending.terms.grain}<br/>{pending.terms.reason}</p> : <p>当前没有待处理的议和条款。</p>}
      {latest && latest.action!=='counter' && [latest].map(record=><div className="diplomacy-receipt" key={record.id}><strong>{record.summary}</strong>
        {record.battle && <p>{record.battle.text}</p>}
        <p>本次变化：民心 {record.state_diff.people} · 国库 {record.state_diff.treasury} · 粮储 {record.state_diff.grain}</p>
        {record.remaining_policy && <p>治理草稿已保留：{record.remaining_policy}</p>}
      </div>)}
      {game.status==='playing' && pending && <><div className="edict-preview-actions">
        <button className="secondary-button" disabled={busy||!pending} onClick={()=>setChoice('accept')}>接受</button>
        <button className="secondary-button" disabled={busy} onClick={()=>setChoice('reject')}>拒绝</button>
        <button className="secondary-button" disabled={busy} onClick={()=>setChoice('counter')}>还价</button>
      </div>
      {choice==='counter' && <textarea className="negotiation-input" aria-label="还价条件" value={text} maxLength={500} disabled={busy} onChange={e=>setText(e.target.value)} placeholder="提出本次谈判条件……"/>}
      {choice==='accept' && <p>确认后按当前条款立即履约，不另算一回合。</p>}
      {choice==='reject' && <p>拒绝谈判将触发敌军进攻，军费和战果当场结算。</p>}
      <button className="secondary-button" disabled={busy||(choice==='accept'&&!pending)||(choice==='counter'&&!text.trim())} onClick={()=>void send()}>{busy?'正在等待答复……':{accept:'确认接受',reject:'确认拒绝并应战',counter:'发送谈判要求'}[choice]}</button></>}
      {error && <p role="alert">{error}</p>}<button className="secondary-button" disabled={busy} onClick={onClose}>返回治理</button>
    </div></div></div>;
}
