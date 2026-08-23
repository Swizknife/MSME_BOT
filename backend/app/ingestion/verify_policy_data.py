"""
Cross-validates the hand-encoded structured facts in policy_data.py against
the extracted PDF text (data/extracted/msme_policy_2026.raw.json).

policy_data.py was transcribed by direct reading of the source PDF rather
than derived from PyMuPDF's table detector (which was found to truncate
cells and mis-split rows on pp.18-20 -- see the module docstring there for
the full reasoning). Hand transcription trades one risk (table-detector
corruption) for another (human transcription error), so this script closes
the loop: every rate, cap, and figure asserted in policy_data.py must be
found, after whitespace normalization, in the extracted text of the page it
claims to come from. Any mismatch fails loudly rather than silently indexing
a wrong number.

This is intentionally a strict, mechanical check -- it does not understand
policy semantics, only string containment. That is sufficient here because
figures (percentages, rupee amounts, counts) are exactly the class of fact
this project cannot afford to get wrong (docs/RAG_IMPLEMENTATION.md's
"Numeric Guard" and "table atom" design both exist for this reason).
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.ingestion import policy_data as pd  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]
EXTRACTED_JSON = REPO_ROOT / "data" / "extracted" / "msme_policy_2026.raw.json"

# Figures are checked as short numeric/percent tokens extracted from each
# hand-encoded field, rather than the whole sentence, because the source
# wraps sentences across table cells and page breaks in ways that don't
# preserve exact phrase adjacency (verified during extraction re-validation).
FIGURE_PATTERN = re.compile(
    r"\d+(?:\.\d+)?\s*(?:%|Crore|croe|Lakhs?|lakhs?|Kw)|Rs\.?\s?\d[\d,]*|\d[\d,]*/-"
)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def _page_text_map(data: dict) -> dict[int, str]:
    return {p["page_number"]: _normalize(p["text"]) for p in data["pages"]}


def _check_figures(label: str, page: int, text: str, page_text: dict[int, str], errors: list[str]) -> None:
    if page not in page_text:
        errors.append(f"{label}: page {page} not found in extracted text")
        return
    # A table row's cell content can wrap across a page boundary (verified:
    # the Roof Top Solar Subsidy row starts on p.18 but its cap "5.0 Lakhs"
    # is rendered on p.19 as the table continues). So a figure is accepted
    # if it appears on the row's stated page OR the immediately following
    # page, rather than forcing every row to be re-attributed to whichever
    # page happens to hold its last cell.
    haystack = page_text[page] + " " + page_text.get(page + 1, "")
    figures = set(FIGURE_PATTERN.findall(text))
    for fig in figures:
        norm_fig = _normalize(fig)
        if norm_fig not in haystack:
            errors.append(f"{label} (p.{page}/{page+1}): figure {norm_fig!r} not found in extracted page text")


def main() -> None:
    if not EXTRACTED_JSON.exists():
        print(f"FAIL: {EXTRACTED_JSON} not found -- run extract.py first.")
        sys.exit(1)

    data = json.loads(EXTRACTED_JSON.read_text(encoding="utf-8"))
    page_text = _page_text_map(data)
    errors: list[str] = []

    # --- Incentive table -------------------------------------------------
    if len(pd.INCENTIVE_TABLE) != 17:
        errors.append(f"INCENTIVE_TABLE has {len(pd.INCENTIVE_TABLE)} rows, expected 17")
    varying = [r for r in pd.INCENTIVE_TABLE if r.varies_by_category]
    if len(varying) != 4:
        errors.append(
            f"{len(varying)} rows marked varies_by_category, expected 4 "
            f"(docs/RAG_IMPLEMENTATION.md section 2.2). Rows: {[r.name for r in varying]}"
        )
    for row in pd.INCENTIVE_TABLE:
        for cat_label, cat_text in (("micro", row.micro), ("small", row.small), ("medium", row.medium)):
            _check_figures(f"INCENTIVE_TABLE #{row.no} {row.name} [{cat_label}]", row.page, cat_text, page_text, errors)

    # --- Residual incentives ----------------------------------------------
    if len(pd.RESIDUAL_INCENTIVES) != 6:
        errors.append(f"RESIDUAL_INCENTIVES has {len(pd.RESIDUAL_INCENTIVES)} rows, expected 6")
    for ri in pd.RESIDUAL_INCENTIVES:
        _check_figures(f"RESIDUAL_INCENTIVES {ri.no} {ri.name}", ri.page, ri.detail, page_text, errors)

    # --- Guiding principles -------------------------------------------------
    if len(pd.GUIDING_PRINCIPLES) < 20:
        errors.append(f"GUIDING_PRINCIPLES has only {len(pd.GUIDING_PRINCIPLES)} entries, expected ~23")
    for gc in pd.GUIDING_PRINCIPLES:
        _check_figures(f"GUIDING_PRINCIPLES {gc.section}({gc.letter})", gc.page, gc.text, page_text, errors)

    # --- Annexure I district count -----------------------------------------
    region_a, region_b = set(pd.REGION_A_DISTRICTS), set(pd.REGION_B_DISTRICTS)
    if region_a & region_b:
        errors.append(f"Districts in both Region A and Region B: {region_a & region_b}")
    total = region_a | region_b
    if len(pd.REGION_A_DISTRICTS) != 31:
        errors.append(f"Region A has {len(pd.REGION_A_DISTRICTS)} districts, expected 31")
    if len(pd.REGION_B_DISTRICTS) != 6:
        errors.append(f"Region B has {len(pd.REGION_B_DISTRICTS)} districts, expected 6")
    bihar38 = set(pd.BIHAR_ALL_38_DISTRICTS)
    missing_from_annexure = bihar38 - total
    if missing_from_annexure != {"Araria"}:
        errors.append(
            f"Expected exactly {{'Araria'}} missing from Annexure I (AMB-20), got {missing_from_annexure}"
        )
    extra_in_annexure = total - bihar38
    if extra_in_annexure:
        errors.append(f"Annexure I districts not in the official 38: {extra_in_annexure}")

    # --- Ambiguity register --------------------------------------------
    if len(pd.AMBIGUITY_REGISTER) != 21:
        errors.append(f"AMBIGUITY_REGISTER has {len(pd.AMBIGUITY_REGISTER)} entries, expected 21")
    ids = [e.id for e in pd.AMBIGUITY_REGISTER]
    if len(ids) != len(set(ids)):
        dupes = {i for i in ids if ids.count(i) > 1}
        errors.append(f"Duplicate ambiguity IDs: {dupes}")
    for e in pd.AMBIGUITY_REGISTER:
        if e.severity not in ("blocking", "advisory"):
            errors.append(f"{e.id}: invalid severity {e.severity!r}")
        if not e.public_disclosure_en or not e.public_disclosure_hi:
            errors.append(f"{e.id}: missing bilingual disclosure text")
    if pd.BLOCKING_AMBIGUITY_IDS != {"AMB-03", "AMB-09", "AMB-20"}:
        errors.append(f"Expected blocking = {{AMB-03, AMB-09, AMB-20}}, got {pd.BLOCKING_AMBIGUITY_IDS}")

    if errors:
        for e in errors:
            print(f"FAIL: {e}")
        print(f"\n{len(errors)} error(s).")
        sys.exit(1)

    print(
        f"PASS: {len(pd.INCENTIVE_TABLE)} incentive rows ({len(varying)} vary by category), "
        f"{len(pd.RESIDUAL_INCENTIVES)} residual incentives, "
        f"{len(pd.GUIDING_PRINCIPLES)} guiding clauses, "
        f"{len(total)}/38 districts categorised (Araria confirmed missing -> AMB-20), "
        f"{len(pd.AMBIGUITY_REGISTER)} ambiguity entries "
        f"({len(pd.BLOCKING_AMBIGUITY_IDS)} blocking) -- all figures verified against extracted text."
    )


if __name__ == "__main__":
    main()
