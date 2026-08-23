"""
Step 1 of the ingestion pipeline: faithful extraction of the MSME Policy 2026 PDF.

Per the approved architecture (docs/RAG_IMPLEMENTATION.md, "Ingestion" and
"Verified ground truth" sections):

  - The PDF is 27 pages, ~56k characters, almost entirely clean digital text.
  - Page 10 wraps each paragraph across two side-by-side text columns whose
    bounding boxes meet (and slightly overlap) around x=225-230pt. Inspecting
    the raw span structure (page.get_text("dict")) shows the true cause: it is
    NOT a fully-duplicated overlapping run, it is a column break that lands
    mid-word, and the boundary character is rendered once at the tail of the
    left-column span and once again at the head of the right-column span --
    e.g. span "...create dedi" (col 1) is immediately followed, at the SAME
    y-coordinate, by span "icated divisions..." (col 2): both spans carry the
    shared letter "i". Repair is therefore structural, not lexical: bucket
    spans into visual rows by y0, sort each row by x0, and concatenate
    adjacent spans left-to-right, dropping the leading character of the right
    span whenever it case-insensitively matches the trailing character of the
    accumulated left text (both alphabetic). This single rule handles the
    boundary-duplication case ("dedi"+"icated" -> "dedicated", using the
    shared "i"), the no-overlap mid-word-split case ("aspir"+"ing" ->
    "aspiring", no drop needed since falls through to direct concat), and
    ordinary same-row spans separated by their own embedded space (direct
    concat is a no-op fix there). No dictionary or word list is required.
  - Page 8 has an empty §5.2 heading ("Guiding principles of the policy") with
    literally nothing below it in the source PDF -- verified by rendering the
    page and confirming zero drawings, zero images, zero text after the
    heading. This is a genuine policy defect (AMB-18), not an extraction bug,
    and no recovery is attempted.
  - Page 10 also contains a rasterised diagram (8 coloured pillar boxes) whose
    labels are not in the text layer. Its content duplicates the §7
    subsection headings almost entirely, with one exception -- an eighth box,
    "Special Assistance for Inclusion", which has no corresponding section
    anywhere in the policy (AMB-21). The diagram is OCR'd once, offline, only
    for the ambiguity register -- it is never part of the retrievable corpus.

This module performs no LLM calls and no network calls. It is pure PyMuPDF +
deterministic Python, so it is fully reproducible and safe to re-run.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from pathlib import Path

import pymupdf

REPO_ROOT = Path(__file__).resolve().parents[3]
RAW_PDF = REPO_ROOT / "data" / "raw" / "msme_policy_2026.pdf"
OUT_DIR = REPO_ROOT / "data" / "extracted"
OUT_JSON = OUT_DIR / "msme_policy_2026.raw.json"

EXPECTED_PAGE_COUNT = 27

# Known-good anchor strings used by verify_extraction.py to prove the page 10
# repair actually recovered the content rather than silently emitting garbage.
PAGE_10_ANCHORS = [
    "a chatbot will be developed",
    "for the MSME where they can reach out for their",
    "grievances and",
    "solution",
    "MSME Kendras at the District Industries Centres (DICs)",
    "Udyog Salahkaar",
]


@dataclass
class TableCell:
    text: str


@dataclass
class ExtractedTable:
    page: int
    bbox: tuple[float, float, float, float]
    rows: list[list[str]]


@dataclass
class ExtractedPage:
    page_number: int  # 1-indexed, matches the printed "Page N of 27"
    char_count: int
    text: str
    repair_applied: str | None  # None | "seam_merge" | "empty_confirmed"
    tables: list[ExtractedTable] = field(default_factory=list)


@dataclass
class ExtractionResult:
    source_pdf: str
    page_count: int
    pages: list[ExtractedPage]


# --------------------------------------------------------------------------
# Page 10 seam-duplication repair
# --------------------------------------------------------------------------

def _y_bucket(y: float, tolerance: float = 3.0) -> int:
    return round(y / tolerance)


def _concat_with_boundary_dedup(left: str, right: str) -> str:
    """
    Concatenate two adjacent spans on the same visual row, dropping a
    duplicated boundary letter when the column break split a word and the
    PDF re-rendered the split character on both sides.

    Rule: if the last character of `left` and the first character of `right`
    are both alphabetic and equal case-insensitively, drop the first
    character of `right` before concatenating. Otherwise concatenate
    directly -- this correctly handles ordinary spans (already separated by
    their own embedded space) and no-overlap mid-word splits
    ("aspir" + "ing" -> "aspiring") without any dictionary lookup.
    """
    if left and right and left[-1].isalpha() and right[0].isalpha() and left[-1].lower() == right[0].lower():
        return left + right[1:]
    return left + right


def _reconstruct_seam_page(page: pymupdf.Page) -> tuple[str, bool]:
    """
    Rebuild page text by bucketing spans into visual rows (y0), x-sorting
    each row, then concatenating spans left-to-right with boundary dedup.
    Returns (text, any_unresolved_flag) -- the flag is reserved for future
    use if a row is found where the dedup rule cannot apply cleanly; today
    it always concatenates (worst case: a direct join with no drop), so it
    is always False, kept for interface stability with verify_extraction.py.
    """
    raw = page.get_text("dict")
    spans: list[tuple[float, float, str]] = []  # (y0, x0, text)
    for block in raw.get("blocks", []):
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                text = span.get("text", "")
                if text == "":
                    continue
                x0, y0 = span["bbox"][0], span["bbox"][1]
                spans.append((y0, x0, text))

    rows: dict[int, list[tuple[float, str]]] = {}
    for y0, x0, text in spans:
        rows.setdefault(_y_bucket(y0), []).append((x0, text))

    out_lines: list[str] = []
    for key in sorted(rows):
        row = sorted(rows[key], key=lambda t: t[0])
        acc = ""
        for _, text in row:
            acc = _concat_with_boundary_dedup(acc, text) if acc else text
        out_lines.append(acc)

    text = "\n".join(out_lines)
    return text, False


def _page_is_confirmed_empty_after_heading(page: pymupdf.Page, heading: str) -> bool:
    """Used for page 8 -- verify there is genuinely nothing after the heading."""
    txt = page.get_text().strip()
    if heading not in txt:
        return False
    tail = txt.split(heading, 1)[1].strip()
    has_drawings = len(page.get_drawings()) > 0
    has_images = len(page.get_images()) > 0
    return tail == "" and not has_drawings and not has_images


def _extract_tables(page: pymupdf.Page, page_number: int) -> list[ExtractedTable]:
    found = page.find_tables()
    tables: list[ExtractedTable] = []
    for t in found.tables:
        rows = t.extract()
        norm_rows = [[(c or "").strip() for c in row] for row in rows]
        tables.append(ExtractedTable(page=page_number, bbox=tuple(t.bbox), rows=norm_rows))
    return tables


def extract() -> ExtractionResult:
    if not RAW_PDF.exists():
        raise FileNotFoundError(f"Expected source PDF at {RAW_PDF}")

    doc = pymupdf.open(RAW_PDF)
    if doc.page_count != EXPECTED_PAGE_COUNT:
        raise AssertionError(
            f"Expected {EXPECTED_PAGE_COUNT} pages, found {doc.page_count}. "
            "The source PDF may have changed -- re-validate before proceeding."
        )

    pages: list[ExtractedPage] = []
    for idx in range(doc.page_count):
        page = doc[idx]
        page_number = idx + 1
        repair_applied: str | None = None

        if page_number == 10:
            text, _ = _reconstruct_seam_page(page)
            repair_applied = "seam_merge"
        elif page_number == 8:
            is_empty = _page_is_confirmed_empty_after_heading(
                page, "5.2 Guiding principles of the policy"
            )
            text = page.get_text()
            repair_applied = "empty_confirmed" if is_empty else None
        else:
            text = page.get_text()

        tables = _extract_tables(page, page_number)
        pages.append(
            ExtractedPage(
                page_number=page_number,
                char_count=len(text),
                text=text,
                repair_applied=repair_applied,
                tables=tables,
            )
        )

    page_count = doc.page_count
    doc.close()
    return ExtractionResult(source_pdf=str(RAW_PDF), page_count=page_count, pages=pages)


def _to_jsonable(result: ExtractionResult) -> dict:
    d = asdict(result)
    for p in d["pages"]:
        for t in p["tables"]:
            t["bbox"] = list(t["bbox"])
    return d


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    result = extract()
    OUT_JSON.write_text(
        json.dumps(_to_jsonable(result), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Extracted {result.page_count} pages -> {OUT_JSON}")

    p10 = next(p for p in result.pages if p.page_number == 10)
    missing = [a for a in PAGE_10_ANCHORS if a not in p10.text]
    if missing:
        print("WARNING: page 10 repair missing anchors:", missing)
    else:
        print("Page 10 repair: all anchor strings recovered.")

    p8 = next(p for p in result.pages if p.page_number == 8)
    print(f"Page 8 repair_applied = {p8.repair_applied!r} (expect 'empty_confirmed')")


if __name__ == "__main__":
    main()
