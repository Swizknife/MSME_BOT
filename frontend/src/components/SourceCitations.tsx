import { useState } from "react";
import type { Source, SourceOrigin } from "../api/chat";

// Which architectural layer produced a citation -- a mixed-origin okf_rag
// answer can carry all three at once, and colouring them differently is
// what lets a user see which parts of an answer came from where, not just
// that the answer exists.
const ORIGIN_LABEL: Record<SourceOrigin, string> = {
  vector: "Retrieved text",
  okf: "Structured fact",
  graph: "Linked fact",
};

/**
 * Renders the numbered [S1][S2].. sources a response was grounded in as
 * expandable chips. This is the product's trust mechanism (architecture
 * doc section 11.1): a government answer the user cannot verify against
 * the actual clause text is worth little. There's no PDF-page-image
 * endpoint on the backend yet (that was scoped for a later phase), so each
 * chip expands to the verbatim chunk text plus its clause path and page
 * number instead of a rendered page image.
 */
export function SourceCitations({ sources }: { sources: Source[] }) {
  const [openTag, setOpenTag] = useState<string | null>(null);

  if (sources.length === 0) return null;

  return (
    <div className="source-citations">
      <div className="source-chips">
        {sources.map((s) => (
          <button
            key={s.tag}
            type="button"
            className={
              "source-chip" +
              ` source-chip--${s.origin}` +
              (openTag === s.tag ? " source-chip--open" : "")
            }
            onClick={() => setOpenTag(openTag === s.tag ? null : s.tag)}
            aria-expanded={openTag === s.tag}
          >
            [{s.tag}] {s.clause_path || "Source"}
            {s.page_start ? ` · p.${s.page_start}` : ""}
          </button>
        ))}
      </div>
      {openTag && (
        <div className="source-detail">
          {(() => {
            const s = sources.find((x) => x.tag === openTag);
            if (!s) return null;
            return (
              <>
                <div className="source-detail__path">
                  <span className={`source-origin-tag source-origin-tag--${s.origin}`}>
                    {ORIGIN_LABEL[s.origin]}
                  </span>
                  {s.clause_path || "Bihar MSME Policy 2026 (Draft)"}
                  {s.page_start > 0 &&
                    ` · page ${s.page_start === s.page_end ? s.page_start : `${s.page_start}–${s.page_end}`}`}
                </div>
                <p className="source-detail__text">{s.text}</p>
              </>
            );
          })()}
        </div>
      )}
    </div>
  );
}
