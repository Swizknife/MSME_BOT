import type { ChatTurn } from "../types/chat";
import { GraphPath } from "./GraphPath";
import { SourceCitations } from "./SourceCitations";
import { ModeBadge, TierBadge } from "./TierBadge";

export function ChatMessage({ turn }: { turn: ChatTurn }) {
  if (turn.role === "user") {
    return (
      <div className="message message--user">
        <div className="message__bubble">{turn.text}</div>
      </div>
    );
  }

  const language = turn.language === "hi" ? "hi" : "en";

  return (
    <div className={"message message--assistant" + (turn.error ? " message--error" : "")}>
      <div className="message__bubble">
        {turn.tier && !turn.error && (
          <div className="message__meta">
            <TierBadge tier={turn.tier} lowConfidence={turn.lowConfidence} />
            {turn.mode && <ModeBadge mode={turn.mode} timingMs={turn.timingMs} />}
          </div>
        )}
        <p className="message__text">{turn.text}</p>
        {turn.ambiguityIds && turn.ambiguityIds.length > 0 && (
          <div className="message__ambiguity">
            Policy gap flagged in the draft: {turn.ambiguityIds.join(", ")}
          </div>
        )}
        {turn.sources && <SourceCitations sources={turn.sources} />}
        {!turn.error && (
          <GraphPath path={turn.graphPath ?? []} missing={turn.graphMissing ?? []} language={language} />
        )}
      </div>
    </div>
  );
}
