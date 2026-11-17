import { useEffect, useRef } from "react";
import type { TreatyReport } from '../types/game';

const MAX_CHARS = 500;

interface Props {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  disabled: boolean;
  submitting: boolean;
  sendingStatus?: string | null;
  error: string | null;
  treaty?: TreatyReport | null;
  onTreatyDecision?: (decision: 'accept' | 'reject' | 'counter') => void;
  policyDisabled?:boolean;
}

export default function EdictInput({
  value,
  onChange,
  onSubmit,
  disabled,
  submitting,
  sendingStatus,
  error,
  treaty,
  onTreatyDecision,
  policyDisabled,
}: Props) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const length = [...value].length;

  useEffect(() => {
    if (!submitting && !disabled) {
      textareaRef.current?.focus();
    }
  }, [submitting, disabled]);

  const handleKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
      event.preventDefault();
      if (!disabled && !submitting && !policyDisabled && value.trim().length > 0) {
        onSubmit();
      }
    }
  };

  return (
    <section className="input-area" aria-label="圣旨输入区">
      {treaty?.status==='pending' && onTreatyDecision && <div className="treaty-actions" aria-label="当前和约决定">
        <span>当前和约：{treaty.direction==='pay' ? '交付' : '收取'} {treaty.terms.cities}城 · 国库 {treaty.terms.treasury} · 粮储 {treaty.terms.grain}</span>
        <div>{(['accept','reject','counter'] as const).map(decision=><button key={decision} className="secondary-button" disabled={disabled || submitting} onClick={()=>{
          onTreatyDecision(decision);if(decision==='counter')textareaRef.current?.focus();
        }}>{{accept:'接受',reject:'拒绝',counter:'还价'}[decision]}</button>)}</div>
        <small>当回合立即答复，可反复谈判，不占治理圣旨。</small>
      </div>}
      {submitting && (
        <div className="court-waiting" aria-live="polite">
          <span className="waiting-dots" aria-hidden="true"><i /><i /><i /></span>
          {sendingStatus ?? "天下正在回应……"}
        </div>
      )}
      <div className="input-compose">
        <div className="input-scroll">
          <svg className="quill-icon" viewBox="0 0 32 32" aria-hidden="true">
            <path d="M5 27 25 7M9 25C5 17 11 6 28 3c-1 16-10 22-19 19M12 19l6 2m-2-7 6 2" />
          </svg>
          <textarea
            ref={textareaRef}
            className="edict-input"
            value={value}
            onChange={(event) => onChange(event.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="请输入下一道圣旨……"
            disabled={disabled || submitting || policyDisabled}
            rows={1}
            aria-label="圣旨内容"
            aria-invalid={error !== null}
          />
        </div>
        <button
          className="submit-button"
          onClick={onSubmit}
          disabled={disabled || submitting || policyDisabled || value.trim().length === 0 || length > MAX_CHARS}
        >
          {submitting ? "等候奏报" : "颁布圣旨"}
        </button>
      </div>
      <div className="input-footer">
        <div className="input-info">
          {error ? (
            <span className="input-error" role="alert">{error}</span>
          ) : (
            <span className="input-hint">{policyDisabled?'治理圣旨已颁完，请完成当前议和':'Ctrl + Enter 预览诏意'}</span>
          )}
        </div>
        <div className="input-actions">
          <span className={`char-count ${length > MAX_CHARS ? "over" : ""}`}>
            {length} / {MAX_CHARS}
          </span>
        </div>
      </div>
    </section>
  );
}
