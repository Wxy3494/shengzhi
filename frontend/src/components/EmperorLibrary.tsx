import {useEffect,useRef,useState} from 'react';
import {getEmperorLibrary,type EmperorEntry} from '../api/client';

export default function EmperorLibrary({open,onClose}:{open:boolean;onClose:()=>void}) {
  const ref=useRef<HTMLDialogElement>(null);
  const [entries,setEntries]=useState<EmperorEntry[]>([]),[selected,setSelected]=useState(''),[error,setError]=useState(''),[attempt,setAttempt]=useState(0);
  useEffect(()=>{if(open&&!ref.current?.open)ref.current?.showModal();if(!open&&ref.current?.open)ref.current?.close();},[open]);
  useEffect(()=>{if(!open||entries.length)return;let active=true;setError('');
    getEmperorLibrary().then(data=>{if(active){setEntries(data.emperors);setSelected(data.emperors[0]?.id??'');}}).catch(()=>{if(active)setError('图鉴暂未载入，请重试。');});
    return()=>{active=false;};},[open,attempt,entries.length]);
  const item=entries.find(e=>e.id===selected);
  return <dialog ref={ref} className="help-dialog emperor-library" onCancel={onClose} onClose={onClose}>
    <div className="modal-head"><h2 className="modal-title">帝王图鉴{entries.length?` · ${entries.length}位`:''}</h2><button className="modal-close" onClick={onClose} aria-label="关闭帝王图鉴">×</button></div>
    <div className="modal-body"><p>终局根据整局治政风格匹配人物，并非等概率抽取。此处可查看全部人物。</p>
      {error?<p role="alert">{error}<button className="secondary-button" onClick={()=>setAttempt(a=>a+1)}>重试</button></p>:!entries.length?<p>正在载入图鉴……</p>:<>
      <nav className="codex-library-list" aria-label="全部皇帝">{entries.map(e=><button className="secondary-button" key={e.id} onClick={()=>setSelected(e.id)} aria-pressed={selected===e.id}>{e.name.split('·')[0]}</button>)}</nav>
      {item&&<article aria-label="图鉴人物介绍"><h3>{item.name}</h3><p>{item.dynasty} · {item.era}</p><h4>人物生平与主要事迹</h4>{item.facts.map((fact,i)=><p key={i}>{fact}</p>)}<details><summary>史料出处</summary>{item.sources.map(s=><p key={s.url}><a href={s.url} target="_blank" rel="noopener noreferrer">{s.title}</a></p>)}</details></article>}
    </>}</div></dialog>;
}
