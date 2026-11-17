import type { ChatMessage } from "../types/chat";
import { ADVISOR_INFO, SPEAKER_INFO } from "../types/game";

interface Props {
  message: ChatMessage;
}

function Portrait({ id, name }: { id: string; name: string }) {
  return <img className={`portrait portrait-${id}`} src={`/avatars/${id}.png`} alt={name} />;
}

function BubbleWatermark() {
  return (
    <svg className="bubble-watermark" viewBox="0 0 150 54" aria-hidden="true">
      <path d="M0 51c22-4 28-19 43-20 12-1 17 10 29 6 15-5 18-23 34-25 15-2 22 14 44 17v22Z" />
      <path d="M91 40h42M98 40V27h29v13M94 27h38l-7-6h-23ZM105 20V12h14v8M102 12h20l-5-5h-10Z" />
    </svg>
  );
}

function CheckIcon() {
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true">
      <path d="m4 10 4 4 8-9" />
    </svg>
  );
}

export default function MessageBubble({ message }: Props) {
  if (message.kind === "edict") {
    const pending = message.status === "pending";
    return (
      <article className={`message-row edict-row ${pending ? "pending" : ""}`}>
        <Portrait id="emperor" name="皇帝" />
        <div className="message-main">
          <div className="speaker-tag edict-tag">
            <span className="bubble-stamp">{pending ? "圣旨 · 待结算" : "圣旨 · 已颁"}</span>
          </div>
          <div className={`bubble edict ${pending ? "pending" : ""}`}>
            <p className="bubble-text">{message.text}</p>
            <span className="scroll-seal" aria-hidden="true">奉<br />旨</span>
          </div>
        </div>
        {!pending && (
          <span className="edict-read"><CheckIcon />天下已阅</span>
        )}
      </article>
    );
  }

  if (message.kind === "advisor") {
    return (
      <article className="message-row advisor-row">
        <Portrait id="shen" name={ADVISOR_INFO.name} />
        <div className="message-main">
          <div className="speaker-tag advisor-tag">
            <span className="speaker-name">{ADVISOR_INFO.name}</span>
            <span className="speaker-role">· {ADVISOR_INFO.role}</span>
          </div>
          <div className="bubble advisor">
            <p className="bubble-text">{message.text}</p>
            <BubbleWatermark />
          </div>
        </div>
      </article>
    );
  }

  if (message.kind === "reaction") {
    const info = SPEAKER_INFO[message.speaker];
    return (
      <article className={`message-row reaction-row reaction-${message.speaker}`}>
        <Portrait id={message.speaker} name={info.name} />
        <div className="message-main">
          <div className={`speaker-tag speaker-tag-${message.speaker}`}>
            <span className="speaker-name">{info.name}</span>
            <span className="speaker-role">· {info.role}</span>
          </div>
          <div className="bubble reaction">
            <p className="bubble-text">{message.text}</p>
            <BubbleWatermark />
          </div>
        </div>
      </article>
    );
  }

  if (message.kind === "error") {
    return (
      <div className="bubble error" role="alert">
        <p className="bubble-text">{message.text}</p>
      </div>
    );
  }

  return null;
}
