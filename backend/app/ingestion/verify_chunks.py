"""
CI gate for Step 3 (chunk.py). Run after every chunk build.

Checks the specific invariants the architecture depends on
(docs/RAG_IMPLEMENTATION.md section 3.2):
  - exactly 25 table atoms (4 varying rows x 3 categories + 13 shared rows x 1)
  - no duplicate chunk_ids, no empty text/parent_text
  - no two chunks share identical text (the zero-overlap design principle --
    a true duplicate would mean the same rupee figure is retrievable from two
    places, which corrupts the Numeric Guard's provenance check)
  - every ambiguity_flags reference resolves to a real AMBIGUITY_REGISTER id
    (catches typos in policy_data.py's cross-reference lists)
  - every table_atom / residual_incentive chunk not flagged as a blocking
    ambiguity (missing rate) contains at least one figure (%, Rs., Crore,
    Lakh, etc.) -- a row that should have a number but doesn't would mean a
    silent content-loss bug in chunk.py's text assembly
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.ingestion import policy_data as pd  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]
CHUNKS_JSON = REPO_ROOT / "data" / "chunks" / "msme_policy_2026.chunks.json"

FIGURE_PATTERN = re.compile(r"\d+(?:\.\d+)?\s*(?:%|Crore|croe|Lakhs?|lakhs?|Kw)|₹\s?\d|Rs[.,]?\s?\d")

# Rows/items where the source genuinely states no figure -- these are exempt
# from the "must contain a number" check because their absence IS the fact:
#   AMB-03 Interest Subsidy       -- conditions given, rate never stated
#   AMB-09 Revival Package        -- eligibility given, amount never stated
#   AMB-13 SME Exchange (Micro)   -- source literally prints "-" for this cell
FIGURE_EXEMPT_AMBIGUITIES = {"AMB-03", "AMB-09", "AMB-13"}

# Section 8.5/8.6 explicitly defer to future guidelines in the source text
# ("as per approved project proposals and scheme guidelines" / "as per
# approved norms and scheme guidelines") rather than omitting a figure by
# oversight -- a documented deferral, not a drafting gap, so exempt on the
# same self-documenting phrase rather than inventing a new ambiguity ID for
# something the text already explains about itself.
DEFERRAL_PHRASE = "as per approved"


def main() -> None:
    if not CHUNKS_JSON.exists():
        print(f"FAIL: {CHUNKS_JSON} not found -- run `python -m app.ingestion.chunk` first.")
        sys.exit(1)

    data = json.loads(CHUNKS_JSON.read_text(encoding="utf-8"))
    chunks = data["chunks"]
    errors: list[str] = []

    table_atoms = [c for c in chunks if c["chunk_type"] == "table_atom"]
    if len(table_atoms) != 25:
        errors.append(f"table_atom count = {len(table_atoms)}, expected 25")

    ids = [c["chunk_id"] for c in chunks]
    dupe_ids = {i for i in ids if ids.count(i) > 1}
    if dupe_ids:
        errors.append(f"duplicate chunk_ids: {dupe_ids}")

    for c in chunks:
        if not c["text"].strip():
            errors.append(f"{c['chunk_id']}: empty text")
        if not c["parent_text"].strip():
            errors.append(f"{c['chunk_id']}: empty parent_text")

    texts = [c["text"] for c in chunks]
    dupe_texts = {t for t in texts if texts.count(t) > 1}
    if dupe_texts:
        errors.append(f"{len(dupe_texts)} chunk(s) share identical text with another chunk")

    valid_amb_ids = {e.id for e in pd.AMBIGUITY_REGISTER}
    for c in chunks:
        for flag in c.get("ambiguity_flags", []):
            if flag not in valid_amb_ids:
                errors.append(f"{c['chunk_id']}: ambiguity_flags references unknown id {flag!r}")

    for c in chunks:
        if c["chunk_type"] not in ("table_atom", "residual_incentive"):
            continue
        exempt = bool(set(c.get("ambiguity_flags", [])) & FIGURE_EXEMPT_AMBIGUITIES)
        exempt = exempt or DEFERRAL_PHRASE in c["text"].lower()
        if exempt:
            continue
        if not FIGURE_PATTERN.search(c["text"]):
            errors.append(f"{c['chunk_id']}: no figure found in a row expected to carry one")

    if errors:
        for e in errors:
            print(f"FAIL: {e}")
        print(f"\n{len(errors)} error(s).")
        sys.exit(1)

    by_type: dict[str, int] = {}
    for c in chunks:
        by_type[c["chunk_type"]] = by_type.get(c["chunk_type"], 0) + 1
    print(f"PASS: {len(chunks)} chunks, {len(table_atoms)} table atoms, "
          f"no duplicate ids/text, all ambiguity references resolve. By type: {by_type}")


if __name__ == "__main__":
    main()
