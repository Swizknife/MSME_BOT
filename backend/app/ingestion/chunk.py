"""
Step 3 of the ingestion pipeline: build retrievable chunks from the verified
structured facts (policy_data.py) and the extracted narrative text
(extract.py output).

Per docs/RAG_IMPLEMENTATION.md section 3.2 ("Chunk"):

  - Table atoms use CONDITIONAL explosion, not blanket explosion. Only the 4
    incentive rows that actually differ across Micro/Small/Medium are split
    into 3 category-specific chunks each (12 atoms). The other 13 rows,
    verified identical across all three categories, emit ONE chunk each,
    tagged with all three categories (13 atoms). Total: 25 table atoms.
    Blanket explosion (17x3=51) was rejected because it burns retrieval
    slots on near-duplicate vectors and can displace the governing section
    9 condition that actually matters for a given incentive.

  - Guiding-principle clauses (section 9) are one chunk per lettered
    sub-clause, since these are the conditions that govern eligibility for
    a specific incentive and must be retrievable on their own (e.g. a user
    asking specifically about the aggregate cap in 9.1(d)).

  - Ambiguity notes are ALSO indexed as directly retrievable chunks (not
    only stored as metadata), because a real class of question this bot
    must answer well is "does the policy define backward districts?" or
    "how much interest subsidy do I get?" -- both of which are correctly
    answered by surfacing the relevant ambiguity register entry, not by
    silence.

  - Overlap is zero throughout: chunks are semantically closed units, and
    overlap would duplicate rupee figures across chunks, corrupting the
    Numeric Guard's provenance check at generation time.

  - Every chunk carries a `parent_text` -- the fuller context (e.g. the
    section it belongs to, or in the case of table atoms, the full row plus
    its governing section 9 conditions) that is sent to the LLM at
    generation time even though only the smaller atom is embedded
    (small-to-big retrieval, architecture doc section 3.2).

No embedding happens here. This module is pure Python producing plain-data
Chunk objects; embed.py (Step 5) is a separate, swappable stage.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from app.ingestion import policy_data as pd

REPO_ROOT = Path(__file__).resolve().parents[3]
OUT_DIR = REPO_ROOT / "data" / "chunks"
OUT_JSON = OUT_DIR / "msme_policy_2026.chunks.json"

POLICY_ID = "BIHAR_MSME_2026"
POLICY_VERSION = "draft-v1"
POLICY_STATUS = "DRAFT_NOT_NOTIFIED"

CategoryList = list[str]
ALL_CATEGORIES: CategoryList = ["micro", "small", "medium"]


@dataclass
class Chunk:
    chunk_id: str
    chunk_type: str  # "table_atom" | "residual_incentive" | "guiding_clause"
                      # | "ambiguity_note" | "reference_list" | "section_note"
    text: str               # the embedded (small) unit
    parent_text: str        # fuller context sent to the LLM at generation time
    clause_path: str        # human-readable breadcrumb for citation display
    page_start: int
    page_end: int
    enterprise_category: CategoryList = field(default_factory=list)
    district_region: list[str] = field(default_factory=list)
    incentive_type: str | None = None
    monetary_values: list[str] = field(default_factory=list)
    percentages: list[str] = field(default_factory=list)
    cross_references: list[str] = field(default_factory=list)
    ambiguity_flags: list[str] = field(default_factory=list)
    visibility: str = "public"


def _chunk_id(*parts: str) -> str:
    slug = ".".join(p.lower().replace(" ", "_") for p in parts)
    return f"{POLICY_ID.lower()}.{POLICY_VERSION}.{slug}"


def _incentive_type_slug(name: str) -> str:
    return name.lower().replace(" ", "_").replace("/", "_")


# --------------------------------------------------------------------------
# Table atoms -- section 7.9, conditional explosion
# --------------------------------------------------------------------------


def build_incentive_atoms() -> list[Chunk]:
    chunks: list[Chunk] = []
    for row in pd.INCENTIVE_TABLE:
        incentive_slug = _incentive_type_slug(row.name)
        conditions_note = (
            f" Governing conditions: section(s) {', '.join(row.conditions_ref)}."
            if row.conditions_ref else ""
        )
        ambiguity_note = (
            f" Known open questions on this incentive: {', '.join(row.ambiguity_flags)}."
            if row.ambiguity_flags else ""
        )

        # Full-row context, always available as parent_text regardless of
        # whether the row was exploded -- this is what the LLM actually sees.
        parent_text = (
            f"{row.name} (item {row.no} of the section 7.9 incentive table, p.{row.page}):\n"
            f"  Micro enterprises: {row.micro}\n"
            f"  Small enterprises: {row.small}\n"
            f"  Medium enterprises: {row.medium}\n"
            f"{conditions_note}{ambiguity_note}"
        ).strip()

        if row.varies_by_category:
            for cat, cat_text in (("micro", row.micro), ("small", row.small), ("medium", row.medium)):
                text = (
                    f"[MSME Policy 2026 (Draft) > Section 7.9 Financial Incentives > "
                    f"Item {row.no} {row.name} > {cat.capitalize()} Enterprise > p.{row.page}]\n\n"
                    f"{row.name} for a {cat.upper()} enterprise: {cat_text}."
                    f"{conditions_note}{ambiguity_note}"
                )
                chunks.append(Chunk(
                    chunk_id=_chunk_id("s7_9", f"item{row.no}", incentive_slug, cat),
                    chunk_type="table_atom",
                    text=text,
                    parent_text=parent_text,
                    clause_path=f"S7.9 > Item {row.no} {row.name} > {cat.capitalize()}",
                    page_start=row.page, page_end=row.page,
                    enterprise_category=[cat],
                    incentive_type=incentive_slug,
                    cross_references=list(row.conditions_ref),
                    ambiguity_flags=list(row.ambiguity_flags),
                ))
        else:
            # Verified identical across categories (policy_data.py + the
            # cross-validator confirm this) -- one chunk, tagged with all
            # three categories, instead of three near-duplicate vectors.
            text = (
                f"[MSME Policy 2026 (Draft) > Section 7.9 Financial Incentives > "
                f"Item {row.no} {row.name} > Micro / Small / Medium > p.{row.page}]\n\n"
                f"{row.name} (same for Micro, Small and Medium enterprises): {row.micro}."
                f"{conditions_note}{ambiguity_note}"
            )
            chunks.append(Chunk(
                chunk_id=_chunk_id("s7_9", f"item{row.no}", incentive_slug, "all"),
                chunk_type="table_atom",
                text=text,
                parent_text=parent_text,
                clause_path=f"S7.9 > Item {row.no} {row.name} > All categories",
                page_start=row.page, page_end=row.page,
                enterprise_category=list(ALL_CATEGORIES),
                incentive_type=incentive_slug,
                cross_references=list(row.conditions_ref),
                ambiguity_flags=list(row.ambiguity_flags),
            ))
    return chunks


def build_residual_incentive_chunks() -> list[Chunk]:
    chunks: list[Chunk] = []
    for ri in pd.RESIDUAL_INCENTIVES:
        text = (
            f"[MSME Policy 2026 (Draft) > Section 8 Residual Incentives and Support "
            f"Provisions > {ri.no} {ri.name} > p.{ri.page}]\n\n{ri.detail}"
        )
        chunks.append(Chunk(
            chunk_id=_chunk_id("s8", ri.no, _incentive_type_slug(ri.name)),
            chunk_type="residual_incentive",
            text=text,
            parent_text=text,
            clause_path=f"S8 > {ri.no} {ri.name}",
            page_start=ri.page, page_end=ri.page,
            enterprise_category=list(ALL_CATEGORIES),
            incentive_type=_incentive_type_slug(ri.name),
            ambiguity_flags=list(ri.ambiguity_flags),
        ))
    return chunks


def build_guiding_clause_chunks() -> list[Chunk]:
    chunks: list[Chunk] = []
    by_section: dict[str, list] = {}
    for gc in pd.GUIDING_PRINCIPLES:
        by_section.setdefault(gc.section, []).append(gc)

    for gc in pd.GUIDING_PRINCIPLES:
        siblings = by_section[gc.section]
        parent_text = (
            f"Section {gc.section} {gc.section_title} (full clause set):\n" +
            "\n".join(f"  ({s.letter}) {s.text}" for s in siblings)
        )
        letter_part = f"({gc.letter})" if gc.letter else ""
        text = (
            f"[MSME Policy 2026 (Draft) > Section 9 Guiding Principles for availing "
            f"incentive benefits > {gc.section} {gc.section_title} > {letter_part} > p.{gc.page}]\n\n"
            f"{gc.text}"
        )
        chunks.append(Chunk(
            chunk_id=_chunk_id("s9", gc.section, gc.letter or "root"),
            chunk_type="guiding_clause",
            text=text,
            parent_text=parent_text,
            clause_path=f"S{gc.section} {gc.section_title} > {letter_part}".strip(" >"),
            page_start=gc.page, page_end=gc.page,
            enterprise_category=list(ALL_CATEGORIES),
            cross_references=[gc.section],
            ambiguity_flags=list(gc.ambiguity_flags),
        ))
    return chunks


def build_ambiguity_chunks() -> list[Chunk]:
    """
    Index every register entry as a directly retrievable chunk so questions
    like "what is the interest subsidy rate?" or "does the policy define
    backward districts?" retrieve the honest answer -- a clarification
    request citing the exact gap -- rather than silence or a hallucinated
    figure. This is in addition to (not instead of) attaching
    ambiguity_flags as metadata on the chunks above.
    """
    chunks: list[Chunk] = []
    for e in pd.AMBIGUITY_REGISTER:
        text = (
            f"[MSME Policy 2026 (Draft) > Ambiguity Register > {e.id} > "
            f"p.{','.join(str(p) for p in e.page_refs)}]\n\n"
            f"{e.public_disclosure_en}"
        )
        chunks.append(Chunk(
            chunk_id=_chunk_id("ambiguity", e.id),
            chunk_type="ambiguity_note",
            text=text,
            parent_text=f"{e.description}\n\nHindi: {e.public_disclosure_hi}",
            clause_path=f"Ambiguity Register > {e.id}",
            page_start=min(e.page_refs), page_end=max(e.page_refs),
            enterprise_category=list(ALL_CATEGORIES),
            cross_references=list(e.clause_refs),
            ambiguity_flags=[e.id],
        ))
    return chunks


def build_reference_list_chunks() -> list[Chunk]:
    """Annexures I-VI and the abbreviation glossary as retrievable chunks."""
    chunks: list[Chunk] = []

    region_a_text = ", ".join(pd.REGION_A_DISTRICTS)
    region_b_text = ", ".join(pd.REGION_B_DISTRICTS)
    chunks.append(Chunk(
        chunk_id=_chunk_id("annexure1", "region_a"),
        chunk_type="reference_list",
        text=(
            "[MSME Policy 2026 (Draft) > Annexure I: District Categorization (BIIPP) > "
            f"Region A > p.25]\n\nRegion A districts (30% capital subsidy rate under "
            f"section 7.9 item 1): {region_a_text}."
        ),
        parent_text=f"Region A ({len(pd.REGION_A_DISTRICTS)} districts): {region_a_text}",
        clause_path="Annexure I > Region A",
        page_start=25, page_end=25,
        district_region=["A"],
        cross_references=["AMB-01", "AMB-20"],
    ))
    chunks.append(Chunk(
        chunk_id=_chunk_id("annexure1", "region_b"),
        chunk_type="reference_list",
        text=(
            "[MSME Policy 2026 (Draft) > Annexure I: District Categorization (BIIPP) > "
            f"Region B > p.25]\n\nRegion B districts (25% capital subsidy rate under "
            f"section 7.9 item 1): {region_b_text}."
        ),
        parent_text=f"Region B ({len(pd.REGION_B_DISTRICTS)} districts): {region_b_text}",
        clause_path="Annexure I > Region B",
        page_start=25, page_end=25,
        district_region=["B"],
        cross_references=["AMB-01"],
    ))
    # Explicitly retrievable so a Araria-district question surfaces AMB-20
    # rather than the bot silently defaulting to a region.
    chunks.append(Chunk(
        chunk_id=_chunk_id("annexure1", "araria_gap"),
        chunk_type="ambiguity_note",
        text=(
            "[MSME Policy 2026 (Draft) > Annexure I: District Categorization (BIIPP) > "
            "Araria district > p.25]\n\nAraria district does not appear in either Region A "
            "or Region B of Annexure I. The capital subsidy district-category rate for an "
            "enterprise located in Araria cannot be determined from this document."
        ),
        parent_text="See AMB-20 in the Policy Ambiguity Register.",
        clause_path="Annexure I > Araria (not categorised)",
        page_start=25, page_end=25,
        district_region=["unclassified"],
        cross_references=["AMB-20"],
        ambiguity_flags=["AMB-20"],
    ))

    chunks.append(Chunk(
        chunk_id=_chunk_id("annexure2", "high_priority_sectors"),
        chunk_type="reference_list",
        text=(
            "[MSME Policy 2026 (Draft) > Annexure II: High Priority Sector > p.25]\n\n"
            "High Priority Sectors: " + "; ".join(pd.HIGH_PRIORITY_SECTORS) + ". "
            "Note: no incentive rate or eligibility elsewhere in the policy is stated to "
            "differ based on this classification (see AMB-10)."
        ),
        parent_text="; ".join(pd.HIGH_PRIORITY_SECTORS),
        clause_path="Annexure II > High Priority Sector",
        page_start=25, page_end=25,
        cross_references=["AMB-10"],
    ))
    chunks.append(Chunk(
        chunk_id=_chunk_id("annexure3", "priority_sectors"),
        chunk_type="reference_list",
        text=(
            "[MSME Policy 2026 (Draft) > Annexure III: Priority Sector > p.25-26]\n\n"
            "Priority Sectors: " + "; ".join(pd.PRIORITY_SECTORS) + ". "
            "Note: no incentive rate or eligibility elsewhere in the policy is stated to "
            "differ based on this classification (see AMB-10)."
        ),
        parent_text="; ".join(pd.PRIORITY_SECTORS),
        clause_path="Annexure III > Priority Sector",
        page_start=25, page_end=26,
        cross_references=["AMB-10"],
    ))
    chunks.append(Chunk(
        chunk_id=_chunk_id("annexure4", "emerging_industries"),
        chunk_type="reference_list",
        text=(
            "[MSME Policy 2026 (Draft) > Annexure IV: Emerging Industries eligible for "
            "Special Package (section 8.2) > p.26]\n\nEmerging Industry Sectors eligible "
            "for the 25% Capital Subsidy Special Package for Emerging Industries "
            "(section 8.2, max Rs.10 Crore): " + "; ".join(pd.EMERGING_INDUSTRIES) + "."
        ),
        parent_text="; ".join(pd.EMERGING_INDUSTRIES),
        clause_path="Annexure IV > Emerging Industries",
        page_start=26, page_end=26,
        cross_references=["8.2"],
    ))
    chunks.append(Chunk(
        chunk_id=_chunk_id("annexure5", "negative_list"),
        chunk_type="reference_list",
        text=(
            "[MSME Policy 2026 (Draft) > Annexure V: Units not eligible for any kind of "
            "incentive > p.26]\n\nThe following units are NOT eligible for any incentive "
            "under this policy: " + "; ".join(pd.NEGATIVE_LIST) + "."
        ),
        parent_text="; ".join(pd.NEGATIVE_LIST),
        clause_path="Annexure V > Negative List",
        page_start=26, page_end=26,
        cross_references=["AMB-12"],
    ))
    chunks.append(Chunk(
        chunk_id=_chunk_id("annexure_heritage", "clusters"),
        chunk_type="reference_list",
        text=(
            "[MSME Policy 2026 (Draft) > Heritage & Traditional Clusters eligible for "
            "special incentive > p.26-27]\n\nHeritage and Traditional Clusters: " +
            "; ".join(pd.HERITAGE_CLUSTERS) + ". Note: no unit-level special incentive "
            "amount is quantified for these clusters anywhere in the policy; section 8.4 "
            "grants (up to 90% Grant-in-Aid) go to cluster infrastructure, not individual "
            "units (see AMB-11)."
        ),
        parent_text="; ".join(pd.HERITAGE_CLUSTERS),
        clause_path="Heritage & Traditional Clusters",
        page_start=26, page_end=27,
        cross_references=["8.4", "AMB-11"],
    ))

    glossary_text = "; ".join(f"{k} = {v}" for k, v in pd.ABBREVIATIONS.items())
    chunks.append(Chunk(
        chunk_id=_chunk_id("glossary", "abbreviations"),
        chunk_type="reference_list",
        text=(
            "[MSME Policy 2026 (Draft) > List of Abbreviations > p.4]\n\n" + glossary_text
        ),
        parent_text=glossary_text,
        clause_path="List of Abbreviations",
        page_start=4, page_end=4,
    ))

    return chunks


def build_all_chunks() -> list[Chunk]:
    chunks: list[Chunk] = []
    chunks += build_incentive_atoms()
    chunks += build_residual_incentive_chunks()
    chunks += build_guiding_clause_chunks()
    chunks += build_ambiguity_chunks()
    chunks += build_reference_list_chunks()
    return chunks


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    chunks = build_all_chunks()

    ids = [c.chunk_id for c in chunks]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        raise AssertionError(f"Duplicate chunk_ids: {dupes}")

    table_atoms = [c for c in chunks if c.chunk_type == "table_atom"]
    payload = {
        "policy_id": POLICY_ID,
        "policy_version": POLICY_VERSION,
        "policy_status": POLICY_STATUS,
        "chunk_count": len(chunks),
        "chunks": [asdict(c) for c in chunks],
    }
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    by_type: dict[str, int] = {}
    for c in chunks:
        by_type[c.chunk_type] = by_type.get(c.chunk_type, 0) + 1

    print(f"Built {len(chunks)} chunks -> {OUT_JSON}")
    for t, n in sorted(by_type.items()):
        print(f"  {t:22s} {n}")
    print(f"  table_atom count = {len(table_atoms)} (expected 25: 4 rows x3 + 13 rows x1)")


if __name__ == "__main__":
    main()
