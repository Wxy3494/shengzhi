import { useEffect, useState } from "react";
import { getEmperorPortrait } from "../api/client";
import { ApiError, type EmperorPortrait as Portrait } from "../types/game";
import EmperorIllustration from './EmperorIllustration';
const PAINTED=new Set(['qin_shihuang','han_wendi','han_wudi','sui_yangdi','tang_taizong','song_shenzong','ming_hongwu','ming_yongle','qing_kangxi','qing_yongzheng','qing_qianlong']);

export default function EmperorPortrait({ gameId }: { gameId: string }) {
  const [portrait, setPortrait] = useState<Portrait | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [retryable, setRetryable] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [artUnavailable, setArtUnavailable] = useState(false);
  useEffect(() => {
    let active = true;
    setPortrait(null);
    setError(null);
    setArtUnavailable(false);
    getEmperorPortrait(gameId).then((result) => {
      if (active && result.game_id === gameId) setPortrait(result);
    }).catch((reason: unknown) => {
      if (!active) return;
      setError(reason instanceof ApiError && reason.code !== "NETWORK_ERROR"
        ? reason.message : "帝王图鉴暂未送达，本局结局已保存，可重试评估。");
      setRetryable(!(reason instanceof ApiError) || reason.retryable);
    });
    return () => { active = false; };
  }, [gameId, attempt]);

  const [title, personalName] = portrait?.emperor.name.split("·") ?? [];
  return <section className="emperor-codex" aria-label="帝王图鉴" aria-live="polite">
    <header className="codex-heading"><span className="codex-heading-line" /><h3>帝王图鉴</h3><span className="codex-heading-line" /></header>
    {!portrait && !error && <div className="codex-pending"><span aria-hidden="true">鉴</span><p>本局帝王即将揭晓……</p></div>}
    {error && <div role="alert"><p>{error}</p>
      {retryable && <button className="secondary-button" onClick={() => setAttempt((value) => value + 1)}>重新载入图鉴</button>}
    </div>}
    {portrait?.review.reign_title && <section className="reign-appraisal" aria-label="本朝帝号与史官评价"><p>本朝帝号</p><h4>{portrait.review.reign_title}</h4><h5>史官曰</h5><p>{portrait.review.historian_comment}</p></section>}
    {portrait && <div className="codex-spread">
      <figure className="codex-portrait">
        <span className="codex-dynasty">{portrait.emperor.dynasty}</span>
        {!artUnavailable && PAINTED.has(portrait.emperor.id) ? <img src={`/emperors/${portrait.emperor.id}.jpg`} alt={`${title}人物立绘`} onError={() => setArtUnavailable(true)} />
          : <EmperorIllustration id={portrait.emperor.id} title={title??''}/>}
        <figcaption><span>本局帝王</span><strong>{title}</strong><span>{personalName}</span></figcaption>
      </figure>
      <article className="codex-biography">
        <div className="codex-nameplate"><div><p className="codex-eyebrow">历代帝王 · {portrait.emperor.dynasty}</p><h4>{title}<span>{personalName}</span></h4></div><span className="codex-seal" aria-hidden="true">本纪</span></div>
        <dl className="codex-metadata"><div><dt>朝代</dt><dd>{portrait.emperor.dynasty}</dd></div><div><dt>在位与年号</dt><dd>{portrait.emperor.era}</dd></div></dl>
        <section className="codex-life"><h5>人物生平</h5><p>{portrait.review.biography}</p></section>
        <section className="codex-deeds"><h5>主要事迹</h5><ol>{portrait.emperor.facts.map((fact, index) => <li key={index}><span aria-hidden="true">{["壹", "贰", "叁", "肆"][index] ?? index + 1}</span><p>{fact}</p></li>)}</ol></section>
        <details className="codex-sources"><summary>史料出处</summary>{portrait.emperor.sources.map((source) => <a key={source.url} href={source.url} target="_blank" rel="noopener noreferrer">{source.title}</a>)}</details>
      </article>
    </div>}
  </section>;
}
