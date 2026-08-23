import { useState } from "react";
import type { Source } from "../api/chat";

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
            className={"source-chip" + (openTag === s.tag ? " source-chip--open" : "")}
            onClick={() => setOpenTag(openTag === s.tag ? null : s.tag)}
            aria-expanded={openTag === s.tag}
          >
            [{s.tag}] {s.clause_path || "Source"} · p.{s.page_start}
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
                  {s.clause_path || "Bihar MSME Policy 2026 (Draft)"} · page{" "}
                  {s.page_start === s.page_end ? s.page_start : `${s.page_start}–${s.page_end}`}
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
