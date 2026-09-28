import type { ArchMode, Tier } from "../api/chat";

// Surfaces which tier of the response ladder answered (architecture doc
// section 4 / D11) -- not an internal debugging detail here, but a small
// piece of honesty: "Quoted directly" tells the user this is a verbatim
// clause, not a paraphrase, which is exactly what D2 promises them.
//
// okf_lookup and graph were previously missing from this map entirely, so
// TIER_LABEL[tier] returned undefined and the badge rendered blank for
// every Tier-1 answer and (once Tier 2a existed) every graph-tier one --
// a live bug, fixed here rather than worked around.
const TIER_LABEL: Record<Tier, string> = {
  cache: "Cached",
  okf_lookup: "From the fact store",
  graph: "Assembled from linked facts",
  abstain: "Not covered",
  extractive: "Quoted directly",
  synthesis: "Answered",
};

export function TierBadge({ tier, lowConfidence }: { tier: Tier; lowConfidence?: boolean }) {
  return (
    <span className={`tier-badge tier-badge--${tier}`}>
      {TIER_LABEL[tier] ?? tier}
      {lowConfidence && <span className="tier-badge__low-confidence"> · low confidence</span>}
    </span>
  );
}

const MODE_LABEL: Record<ArchMode, string> = {
  rag: "RAG only",
  okf: "OKF only",
  okf_rag: "OKF + RAG",
};

/** Which architecture produced this specific answer, plus how long it took
 * -- latency is half of what the toggle demonstrates: a Tier 1 OKF lookup
 * has been measured at 0.08s against 27.9s for the RAG path it replaces. */
export function ModeBadge({ mode, timingMs }: { mode: ArchMode; timingMs?: number | null }) {
  const seconds = timingMs != null ? (timingMs / 1000).toFixed(timingMs < 1000 ? 2 : 1) : null;
  return (
    <span className={`mode-badge mode-badge--${mode}`}>
      {MODE_LABEL[mode]}
      {seconds && <span className="mode-badge__timing"> · {seconds}s</span>}
    </span>
  );
}
