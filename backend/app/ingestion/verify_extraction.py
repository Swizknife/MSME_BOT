"""
CI gate for Step 1 (extract.py). Run after every extraction to prove the
repair actually recovered content rather than silently degrading it.

Per docs/RAG_IMPLEMENTATION.md "Verification" section, this asserts:
  - page count == 27
  - page 10's repaired text contains every known-good anchor string
  - page 8 is confirmed empty after its heading (a genuine policy defect,
    not an extraction failure)
  - every rupee amount / percentage in the section 7.9 incentive table
    (pages 18-20) and section 8 residual incentives (pages 20-21) survived
    extraction, since that table is the highest-value, highest-risk object
    in the corpus (docs/RAG_IMPLEMENTATION.md section 2.2)
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
EXTRACTED_JSON = REPO_ROOT / "data" / "extracted" / "msme_policy_2026.raw.json"

EXPECTED_PAGE_COUNT = 27

PAGE_10_ANCHORS = [
    "a chatbot will be developed",
    "for the MSME where they can reach out for their",
    "grievances and",
    "solution",
    "MSME Kendras at the District Industries Centres (DICs)",
    "Udyog Salahkaar",
    "Panchayat",
]

# Every monetary/percentage figure that appears in the section 7.9 incentive
# matrix (pp.18-20) and section 8 residual incentives (pp.20-21), verified by
# manual read-through of the source PDF. If any of these vanish after
# extraction, a rate or cap has been silently lost.
REQUIRED_FIGURES = [
    "30%", "25%",  # capital subsidy rates
    "25 Lakhs", "1.5 Crore", "5 croe",  # capital subsidy caps (note: "croe" is
                                         # the source's own typo -- AMB-05/15
                                         # class; must survive as-written)
    "10%",  # disadvantaged-group top-up
    "7 Crore", "7Crore",  # disadvantaged-group cap (both spellings in source)
    "5%",  # scaling-up
    "24,000",  # payroll subsidy per-employee cap
    "20%",  # LT power tariff / SME exchange
    "300 Kw",  # rooftop solar capacity cap
    "5.0 Lakhs",  # rooftop solar cap
    "75%",  # energy/water audit, IP subsidy
    "1 lakhs",  # energy/water audit cap (source spelling)
    "100%",  # stamp duty / quality certification
    "2 lakhs", "10 Lakhs",  # quality certification caps
    "3 Lakhs",  # patent subsidy cap
    "50%",  # trademark subsidy / net SGST / aggregate cap (multi-use figure)
    "25,",  # trademark cap "Rs. 25, 000" (source line-break spacing)
    "5 Lakhs",  # SME exchange cap
    "1.00 lakh",  # e-commerce adoption cap
    "1%",  # export-linked performance
    "20.00 lakh",  # export-linked performance cap
    "1 Crore", "12 Crore",  # revival package ceilings (5 Crore covered above)
    "10 Crore",  # aggregate financial assistance cap (section 9.1d)
]


def _fail(msg: str) -> None:
    print(f"FAIL: {msg}")
    sys.exit(1)


def main() -> None:
    if not EXTRACTED_JSON.exists():
        _fail(f"{EXTRACTED_JSON} not found -- run `python -m app.ingestion.extract` first.")

    data = json.loads(EXTRACTED_JSON.read_text(encoding="utf-8"))
    pages = {p["page_number"]: p for p in data["pages"]}

    errors: list[str] = []

    if data["page_count"] != EXPECTED_PAGE_COUNT:
        errors.append(f"page_count = {data['page_count']}, expected {EXPECTED_PAGE_COUNT}")

    p10 = pages.get(10)
    if p10 is None:
        errors.append("page 10 missing from extraction output")
    else:
        missing = [a for a in PAGE_10_ANCHORS if a not in p10["text"]]
        if missing:
            errors.append(f"page 10 repair missing anchors: {missing}")
        if p10.get("repair_applied") != "seam_merge":
            errors.append(f"page 10 repair_applied = {p10.get('repair_applied')!r}, expected 'seam_merge'")

    p8 = pages.get(8)
    if p8 is None:
        errors.append("page 8 missing from extraction output")
    elif p8.get("repair_applied") != "empty_confirmed":
        errors.append(
            f"page 8 repair_applied = {p8.get('repair_applied')!r}, expected 'empty_confirmed' "
            "-- if the source PDF changed and page 8 now has content under section 5.2, "
            "extract.py's empty-page detection needs updating, not this test."
        )

    # Concatenate pages 18-21 (the incentive matrix + residual incentives +
    # general conditions) to check figure survival across whatever page a
    # given cell's continuation happens to land on. Table cells in this PDF
    # wrap with embedded newlines (e.g. "Cap 1.5 \nCrore"), which is expected
    # PDF layout behaviour, not content loss -- so whitespace is normalized
    # to single spaces before matching each required figure.
    incentive_text_raw = "".join(pages[n]["text"] for n in (18, 19, 20, 21) if n in pages)
    incentive_text = re.sub(r"\s+", " ", incentive_text_raw)
    missing_figures = [f for f in REQUIRED_FIGURES if f not in incentive_text]
    if missing_figures:
        errors.append(f"incentive table figures missing after extraction: {missing_figures}")

    if errors:
        for e in errors:
            print(f"FAIL: {e}")
        sys.exit(1)

    print(f"PASS: {data['page_count']} pages, page 10 repair verified, "
          f"page 8 empty-heading confirmed, {len(REQUIRED_FIGURES)} incentive "
          f"figures all present.")


if __name__ == "__main__":
    main()
