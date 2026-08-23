import type { Tier } from "../api/chat";

// Surfaces which tier of the response ladder answered (architecture doc
// section 4 / D11) -- not an internal debugging detail here, but a small
// piece of honesty: "Quoted directly" tells the user this is a verbatim
// clause, not a paraphrase, which is exactly what D2 promises them.
const TIER_LABEL: Record<Tier, string> = {
  cache: "Cached",
  abstain: "Not covered",
  extractive: "Quoted directly",
  synthesis: "Answered",
};

export function TierBadge({ tier, lowConfidence }: { tier: Tier; lowConfidence?: boolean }) {
  return (
    <span className={`tier-badge tier-badge--${tier}`}>
      {TIER_LABEL[tier]}
      {lowConfidence && <span className="tier-badge__low-confidence"> · low confidence</span>}
    </span>
  );
}
