import type { ChatTurn } from "../types/chat";
import { SourceCitations } from "./SourceCitations";
import { TierBadge } from "./TierBadge";

export function ChatMessage({ turn }: { turn: ChatTurn }) {
  if (turn.role === "user") {
    return (
      <div className="message message--user">
        <div className="message__bubble">{turn.text}</div>
      </div>
    );
  }

  return (
    <div className={"message message--assistant" + (turn.error ? " message--error" : "")}>
      <div className="message__bubble">
        {turn.tier && !turn.error && (
          <div className="message__meta">
            <TierBadge tier={turn.tier} lowConfidence={turn.lowConfidence} />
          </div>
        )}
        <p className="message__text">{turn.text}</p>
        {turn.ambiguityIds && turn.ambiguityIds.length > 0 && (
          <div className="message__ambiguity">
            Policy gap flagged in the draft: {turn.ambiguityIds.join(", ")}
          </div>
        )}
        {turn.sources && <SourceCitations sources={turn.sources} />}
      </div>
    </div>
  );
}
