import { useState } from "react";
import type { GraphNodeRef } from "../api/chat";

const TRUST_LABEL: Record<GraphNodeRef["trust"], { en: string; hi: string }> = {
  unverified: { en: "unverified", hi: "असत्यापित" },
  "machine-confirmed": { en: "machine-confirmed", hi: "मशीन-सत्यापित" },
  "human-reviewed": { en: "human-reviewed", hi: "मानव-समीक्षित" },
};

/**
 * "How this answer was assembled" -- the visible artefact that makes the
 * architecture toggle mean something rather than just relabel an answer.
 * Switch to RAG-only and this panel disappears entirely, because rag mode
 * never runs a graph walk (evidence.py: graph=None) -- that absence IS the
 * comparison, made checkable rather than just claimed.
 *
 * Renders the traversed concepts as a chain (Scheme -> District ->
 * Classification -> Incentive -> Rule), each with its hop number, the edge
 * that reached it, and a trust dot. Collapsed by default: most users just
 * want the answer, and this is for the person who wants to see the
 * reasoning underneath.
 */
export function GraphPath({
  path,
  missing,
  language,
}: {
  path: GraphNodeRef[];
  missing: string[];
  language: "en" | "hi";
}) {
  const [open, setOpen] = useState(false);

  if (path.length === 0 && missing.length === 0) return null;

  const label =
    language === "hi"
      ? `यह उत्तर कैसे तैयार हुआ (${path.length} तथ्य)`
      : `How this answer was assembled (${path.length} concept${path.length === 1 ? "" : "s"})`;

  return (
    <div className="graph-path">
      <button
        type="button"
        className="graph-path__toggle"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        {open ? "▾" : "▸"} {label}
      </button>
      {open && (
        <div className="graph-path__body">
          {path.length > 0 && (
            <ol className="graph-path__chain">
              {path.map((node) => (
                <li key={node.concept_id} className="graph-path__node">
                  <span className={`trust-dot trust-dot--${node.trust}`} title={TRUST_LABEL[node.trust][language]} />
                  <span className="graph-path__type">{node.type}</span>
                  <span className="graph-path__title">{node.title}</span>
                  {node.via && <span className="graph-path__via">via {node.via.replace(/~$/, " (reverse)")}</span>}
                  <span className="graph-path__hop">hop {node.hop}</span>
                </li>
              ))}
            </ol>
          )}
          {missing.length > 0 && (
            <div className="graph-path__missing">
              {language === "hi" ? "ज्ञात अंतराल: " : "Known gaps: "}
              {missing.join("; ")}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
