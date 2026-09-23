"""Emit RAG chunks from compiled OKF records.

This is the OKF-era replacement for the data path in
ingestion/chunk.py. It deliberately reproduces that module's chunk shapes
exactly -- same chunk_ids, same text, same parent_text -- because the
Phase 1 exit criterion is that migrating the existing policy through the
vault does not change the index. The chunking *decisions* are unchanged and
their rationale still lives in ingestion/chunk.py's docstring:

  - Conditional table-atom explosion: only the incentive rows that actually
    differ across micro/small/medium are split three ways. Blanket
    explosion burns retrieval slots on near-duplicate vectors.
  - Zero overlap: chunks are semantically closed, and overlap would
    duplicate rupee figures across chunks and corrupt the Numeric Guard.
  - Every chunk carries parent_text for small-to-big retrieval.

What is new is that chunks now carry per-chunk source identity
(source_id / scheme_id / source_status) and okf_entity_id, instead of
inheriting one document's identity from file-level constants. That is what
lets a second source coexist in the same index, and lets a guard find the
structured record behind a citation.

KNOWN LATENT GAP, not yet hit: the incentive/eligibility_rule/ambiguity
renderers below are scheme-aware (doc_label()) after a real bug was caught
integrating the first non-Bihar sources (TReDS/CGTMSE/MSME Samadhaan) --
every chunk was rendering with the citation header "MSME Policy 2026
(Draft)" regardless of which document it actually came from. The
sector/district/glossary renderers further down were NOT given the same
treatment, because no Sector, DistrictClassification, or GlossaryTerm
record for any scheme other than BIHAR_MSME_2026 exists yet -- they are
Bihar-only in practice today, so the hardcoded text is still correct, not
yet wrong. The moment a future source contributes one of those three
entity types, this will need the same doc_label() fix applied there too.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
OUT_DIR = REPO_ROOT / "data" / "chunks"
OUT_JSON = OUT_DIR / "okf.chunks.json"

ALL_CATEGORIES = ["micro", "small", "medium"]

# Presentation notes attached to annexure lists. These are rendering
# templates, not facts, which is why they live here and not in the vault.
SECTOR_LIST_RENDER = {
    "high_priority": {
        "header": "[MSME Policy 2026 (Draft) > Annexure II: High Priority Sector > p.25]",
        "lead": "High Priority Sectors: ",
        "note": (" Note: no incentive rate or eligibility elsewhere in the policy is stated to "
                 "differ based on this classification (see AMB-10)."),
        "clause_path": "Annexure II > High Priority Sector",
        "chunk_key": ("annexure2", "high_priority_sectors"),
        "pages": (25, 25),
        "xrefs": ["AMB-10"],
    },
    "priority": {
        "header": "[MSME Policy 2026 (Draft) > Annexure III: Priority Sector > p.25-26]",
        "lead": "Priority Sectors: ",
        "note": (" Note: no incentive rate or eligibility elsewhere in the policy is stated to "
                 "differ based on this classification (see AMB-10)."),
        "clause_path": "Annexure III > Priority Sector",
        "chunk_key": ("annexure3", "priority_sectors"),
        "pages": (25, 26),
        "xrefs": ["AMB-10"],
    },
    "emerging": {
        "header": ("[MSME Policy 2026 (Draft) > Annexure IV: Emerging Industries eligible for "
                   "Special Package (section 8.2) > p.26]"),
        "lead": ("Emerging Industry Sectors eligible for the 25% Capital Subsidy Special Package "
                 "for Emerging Industries (section 8.2, max Rs.10 Crore): "),
        "note": "",
        "clause_path": "Annexure IV > Emerging Industries",
        "chunk_key": ("annexure4", "emerging_industries"),
        "pages": (26, 26),
        "xrefs": ["8.2"],
    },
    "negative_list": {
        "header": ("[MSME Policy 2026 (Draft) > Annexure V: Units not eligible for any kind of "
                   "incentive > p.26]"),
        "lead": "The following units are NOT eligible for any incentive under this policy: ",
        "note": "",
        "clause_path": "Annexure V > Negative List",
        "chunk_key": ("annexure5", "negative_list"),
        "pages": (26, 26),
        "xrefs": ["AMB-12"],
    },
    "heritage_cluster": {
        "header": ("[MSME Policy 2026 (Draft) > Heritage & Traditional Clusters eligible for "
                   "special incentive > p.26-27]"),
        "lead": "Heritage and Traditional Clusters: ",
        "note": (" Note: no unit-level special incentive amount is quantified for these clusters "
                 "anywhere in the policy; section 8.4 grants (up to 90% Grant-in-Aid) go to "
                 "cluster infrastructure, not individual units (see AMB-11)."),
        "clause_path": "Heritage & Traditional Clusters",
        "chunk_key": ("annexure_heritage", "clusters"),
        "pages": (26, 27),
        "xrefs": ["8.4", "AMB-11"],
    },
}


@dataclass
class Chunk:
    chunk_id: str
    chunk_type: str
    text: str
    parent_text: str
    clause_path: str
    page_start: int
    page_end: int
    enterprise_category: list[str] = field(default_factory=list)
    district_region: list[str] = field(default_factory=list)
    incentive_type: str | None = None
    monetary_values: list[str] = field(default_factory=list)
    percentages: list[str] = field(default_factory=list)
    cross_references: list[str] = field(default_factory=list)
    ambiguity_flags: list[str] = field(default_factory=list)
    visibility: str = "public"
    # Multi-source fields -- the point of the rebuild.
    source_id: str = ""
    scheme_id: str = ""
    source_version: str = ""
    source_status: str = ""
    # Coverage Gate calibration key (retrieval/coverage_gate.py): reranker
    # score distributions differ by source register (a scraped HTML FAQ vs.
    # a structured policy PDF don't rerank on the same scale), so this is
    # kept separate from source_id even though only one value exists today.
    source_type: str = "structured_policy_pdf"
    okf_entity_id: str | None = None


def _slug_name(name: str) -> str:
    return name.lower().replace(" ", "_").replace("/", "_")


def _sluggish(text: str, maxlen: int = 40) -> str:
    """A short, stable identifier fragment. `version` was previously
    inserted into chunk_id raw -- fine for Bihar's compact "draft-v1", but
    the first non-Bihar source's prose-style source_document_version
    ("CGTMSE homepage, fetched 2026-09-23") produced a chunk_id containing
    literal spaces and a comma. Deliberately narrow: only whitespace/commas
    become underscores and anything else non-identifier-safe is dropped --
    NOT the aggressive alphanumeric-only slugify used elsewhere, because
    that would also rewrite Bihar's hyphen ("draft-v1" -> "draft_v1"),
    silently breaking the parity check against the legacy index, whose
    chunk_ids were built the same un-aggressive way (see
    ingestion/chunk.py's _chunk_id, which also leaves POLICY_VERSION
    untouched)."""
    import re

    s = re.sub(r"[\s,]+", "_", text.strip())
    s = re.sub(r"[^A-Za-z0-9._-]", "", s)
    return (s[:maxlen].rstrip("_") or "v").lower()


def _chunk_id(scheme_id: str, version: str, *parts: str) -> str:
    slug = ".".join(p.lower().replace(" ", "_") for p in parts)
    return f"{scheme_id.lower()}.{_sluggish(version)}.{slug}"


def _local_amb(scheme_id: str, namespaced: str) -> str:
    prefix = f"{scheme_id}-"
    return namespaced[len(prefix):] if namespaced.startswith(prefix) else namespaced


def _sections_from_rule_ids(scheme_id: str, rule_ids: list[str]) -> list[str]:
    """['BIHAR_MSME_2026-S9.1-a', ...] -> ['9.1'] preserving first-seen order."""
    out: list[str] = []
    for rid in rule_ids:
        core = rid[len(f"{scheme_id}-S"):] if rid.startswith(f"{scheme_id}-S") else rid
        section = core.rsplit("-", 1)[0]
        if section not in out:
            out.append(section)
    return out


def build_chunks(result) -> list[Chunk]:
    recs = result.records
    schemes = {s["scheme_id"]: s for s in recs.get("scheme", [])}
    # Known ambiguity_flag ids (fully namespaced, e.g. "CGTMSE-AMB-01"), used
    # below to tell an eligibility_rule's genuine ambiguity cross-references
    # apart from references to other entity types (a scheme, an act...).
    # EligibilityRule has no dedicated ambiguity field in the schema; Bihar's
    # migration overloaded the general-purpose `cross_references` with only
    # ambiguity-flag wikilinks, which happened to make "every
    # cross_reference is an ambiguity flag" true for that one source by
    # convention, not by schema. It broke the moment a hand-authored rule
    # (MSME_SAMADHAAN-DELAYED-PAYMENT-INTEREST) used cross_references for
    # its actual purpose -- linking to the MSME_SAMADHAAN scheme and the
    # MSMED_ACT_2006 act -- and both leaked into ambiguity_ids in a real
    # end-to-end test. Filtering against the real ambiguity id set fixes it
    # for every source, not just by convention for one.
    known_amb_ids = {a["id"] for a in recs.get("ambiguity_flag", [])}
    chunks: list[Chunk] = []

    def meta(scheme_id: str) -> tuple[str, str, str, str]:
        s = schemes.get(scheme_id, {})
        src = s.get("source", {}) or {}
        version = src.get("source_document_version") or "v1"
        status = {
            "draft_not_notified": "DRAFT_NOT_NOTIFIED",
            "notified": "NOTIFIED",
            "active": "ACTIVE",
            "superseded": "SUPERSEDED",
        }.get(s.get("status", ""), (s.get("status") or "").upper())
        return src.get("source_id", ""), version, status, scheme_id

    def doc_label(scheme_id: str) -> str:
        """The document name a citation header opens with. Bihar keeps its
        exact pre-OKF wording ("MSME Policy 2026 (Draft)") for byte-for-byte
        parity with the legacy index; every other scheme uses its own real
        name -- hardcoding Bihar's document name into every chunk regardless
        of source was a real bug caught while adding the first second
        source (TReDS/CGTMSE/MSME Samadhaan chunks were rendering with the
        citation header "MSME Policy 2026 (Draft)", which is simply false)."""
        if scheme_id == "BIHAR_MSME_2026":
            return "MSME Policy 2026 (Draft)"
        s = schemes.get(scheme_id, {})
        return s.get("name") or s.get("short_name") or scheme_id

    def page_suffix(page) -> str:
        return f" > p.{page}" if page else ""

    # ---- incentives -------------------------------------------------------
    for inc in sorted(recs.get("incentive", []), key=lambda r: r["incentive_id"]):
        scheme_id = inc["scheme_id"]
        source_id, version, status, _ = meta(scheme_id)
        src = inc.get("source", {}) or {}
        page = src.get("page_start")
        amb_local = [_local_amb(scheme_id, a) for a in inc.get("ambiguity_flags", [])]
        sections = _sections_from_rule_ids(scheme_id, inc.get("eligibility_rule_ids", []))
        rates = {r["enterprise_category"]: r["rate_text"] for r in inc.get("category_rates", [])}
        name = inc["name"]
        slug = _slug_name(name)
        item_no = inc.get("item_no") or ""
        is_residual = scheme_id == "BIHAR_MSME_2026" and "." in item_no
        label = doc_label(scheme_id)

        conditions_note = (f" Governing conditions: section(s) {', '.join(sections)}."
                           if sections else "")
        ambiguity_note = (f" Known open questions on this incentive: {', '.join(amb_local)}."
                          if amb_local else "")

        if is_residual:
            text = (
                f"[{label} > Section 8 Residual Incentives and Support "
                f"Provisions > {item_no} {name}{page_suffix(page)}]\n\n{rates.get('other', '')}"
            )
            chunks.append(Chunk(
                chunk_id=_chunk_id(scheme_id, version, "s8", item_no, slug),
                chunk_type="residual_incentive",
                text=text, parent_text=text,
                clause_path=f"S8 > {item_no} {name}",
                page_start=page, page_end=page,
                enterprise_category=list(ALL_CATEGORIES),
                incentive_type=slug,
                ambiguity_flags=amb_local,
                source_id=source_id, scheme_id=scheme_id,
                source_version=version, source_status=status,
                okf_entity_id=inc["incentive_id"],
            ))
            continue

        # A record with a single "other"-category rate (e.g. CGTMSE's
        # guarantee fee -- see category_rates in migrate scripts and the
        # vault notes under 02_incentives/) has no micro/small/medium
        # breakdown to render -- rendering it as a bare fact avoids
        # falsely implying a category split that doesn't exist in the
        # source, which the Bihar-specific "Micro/Small/Medium" wording
        # below would otherwise do.
        only_other = set(rates.keys()) == {"other"}

        if scheme_id != "BIHAR_MSME_2026" or only_other:
            item_part = f"Item {item_no} {name}" if item_no else name
            rate_text = rates.get("other") or next(iter(rates.values()), "")
            text = (
                f"[{label} > {item_part}{page_suffix(page)}]\n\n"
                f"{name}: {rate_text}.{conditions_note}{ambiguity_note}"
            )
            chunks.append(Chunk(
                chunk_id=_chunk_id(scheme_id, version, "incentive", slug),
                chunk_type="table_atom",
                text=text, parent_text=text,
                clause_path=item_part,
                page_start=page, page_end=page,
                enterprise_category=["other"] if only_other else list(ALL_CATEGORIES),
                incentive_type=slug,
                cross_references=list(sections),
                ambiguity_flags=amb_local,
                source_id=source_id, scheme_id=scheme_id,
                source_version=version, source_status=status,
                okf_entity_id=inc["incentive_id"],
            ))
            continue

        parent_text = (
            f"{name} (item {item_no} of the section 7.9 incentive table, p.{page}):\n"
            f"  Micro enterprises: {rates.get('micro','')}\n"
            f"  Small enterprises: {rates.get('small','')}\n"
            f"  Medium enterprises: {rates.get('medium','')}\n"
            f"{conditions_note}{ambiguity_note}"
        ).strip()

        if inc.get("varies_by_category"):
            for cat in ALL_CATEGORIES:
                text = (
                    f"[{label} > Section 7.9 Financial Incentives > "
                    f"Item {item_no} {name} > {cat.capitalize()} Enterprise > p.{page}]\n\n"
                    f"{name} for a {cat.upper()} enterprise: {rates.get(cat,'')}."
                    f"{conditions_note}{ambiguity_note}"
                )
                chunks.append(Chunk(
                    chunk_id=_chunk_id(scheme_id, version, "s7_9", f"item{item_no}", slug, cat),
                    chunk_type="table_atom",
                    text=text, parent_text=parent_text,
                    clause_path=f"S7.9 > Item {item_no} {name} > {cat.capitalize()}",
                    page_start=page, page_end=page,
                    enterprise_category=[cat],
                    incentive_type=slug,
                    cross_references=list(sections),
                    ambiguity_flags=amb_local,
                    source_id=source_id, scheme_id=scheme_id,
                    source_version=version, source_status=status,
                    okf_entity_id=inc["incentive_id"],
                ))
        else:
            text = (
                f"[{label} > Section 7.9 Financial Incentives > "
                f"Item {item_no} {name} > Micro / Small / Medium > p.{page}]\n\n"
                f"{name} (same for Micro, Small and Medium enterprises): "
                f"{rates.get('micro','')}.{conditions_note}{ambiguity_note}"
            )
            chunks.append(Chunk(
                chunk_id=_chunk_id(scheme_id, version, "s7_9", f"item{item_no}", slug, "all"),
                chunk_type="table_atom",
                text=text, parent_text=parent_text,
                clause_path=f"S7.9 > Item {item_no} {name} > All categories",
                page_start=page, page_end=page,
                enterprise_category=list(ALL_CATEGORIES),
                incentive_type=slug,
                cross_references=list(sections),
                ambiguity_flags=amb_local,
                source_id=source_id, scheme_id=scheme_id,
                source_version=version, source_status=status,
                okf_entity_id=inc["incentive_id"],
            ))

    # ---- eligibility rules ------------------------------------------------
    rules = recs.get("eligibility_rule", [])
    by_section: dict[str, list[dict]] = {}
    for r in rules:
        by_section.setdefault(r["clause_ref"], []).append(r)
    for section in by_section:
        by_section[section].sort(key=lambda r: (r.get("letter") or ""))

    for rule in sorted(rules, key=lambda r: (r["clause_ref"], r.get("letter") or "")):
        scheme_id = rule["applies_to"][0] if rule.get("applies_to") else ""
        source_id, version, status, _ = meta(scheme_id)
        src = rule.get("source", {}) or {}
        page = src.get("page_start")
        section = rule["clause_ref"]
        title = rule.get("section_title") or ""
        letter = rule.get("letter") or ""
        siblings = by_section[section]
        label = doc_label(scheme_id)
        letter_part = f"({letter})" if letter else ""
        # Read the typed field rather than re-deriving it from cross_references.
        # The old form assumed every cross_reference was an ambiguity flag,
        # which held only by the Bihar migration's convention and leaked a
        # scheme id and an act id into a live answer the first time a rule
        # used that field for its actual purpose.
        amb_local = [
            _local_amb(scheme_id, a)
            for a in rule.get("ambiguity_flags", [])
            if a in known_amb_ids
        ]

        if scheme_id == "BIHAR_MSME_2026":
            parent_text = (
                f"Section {section} {title} (full clause set):\n" +
                "\n".join(f"  ({s.get('letter')}) {s['condition_text']}" for s in siblings)
            )
            text = (
                f"[{label} > Section 9 Guiding Principles for availing "
                f"incentive benefits > {section} {title} > {letter_part} > p.{page}]\n\n"
                f"{rule['condition_text']}"
            )
            chunk_id = _chunk_id(scheme_id, version, "s9", section, letter or "root")
            clause_path = f"S{section} {title} > {letter_part}".strip(" >")
        else:
            # No "Section 9" claim for a scheme whose clauses aren't
            # numbered that way -- section here is often a free-text
            # clause_ref (e.g. "RBI TReDS Guidelines"), not a Bihar-style
            # numbered sub-clause.
            parent_text = rule["condition_text"]
            title_part = f" {title}" if title else ""
            text = f"[{label} > {section}{title_part}{page_suffix(page)}]\n\n{rule['condition_text']}"
            chunk_id = _chunk_id(scheme_id, version, "rule", rule["rule_id"])
            clause_path = f"{section}{title_part}".strip()

        chunks.append(Chunk(
            chunk_id=chunk_id,
            chunk_type="guiding_clause",
            text=text, parent_text=parent_text,
            clause_path=clause_path,
            page_start=page, page_end=page,
            enterprise_category=list(ALL_CATEGORIES),
            cross_references=[section],
            ambiguity_flags=amb_local,
            source_id=source_id, scheme_id=scheme_id,
            source_version=version, source_status=status,
            okf_entity_id=rule["rule_id"],
        ))

    # ---- ambiguity notes --------------------------------------------------
    for amb in sorted(recs.get("ambiguity_flag", []), key=lambda r: r["id"]):
        scheme_id = amb["id"].rsplit("-AMB-", 1)[0]
        source_id, version, status, _ = meta(scheme_id)
        pages = amb.get("page_refs") or [0]
        local = amb.get("local_id") or _local_amb(scheme_id, amb["id"])
        label = doc_label(scheme_id)
        page_part = f" > p.{','.join(str(p) for p in pages)}" if pages != [0] else ""
        text = (
            f"[{label} > Ambiguity Register > {local}{page_part}]\n\n{amb['public_disclosure_en']}"
        )
        chunks.append(Chunk(
            chunk_id=_chunk_id(scheme_id, version, "ambiguity", local),
            chunk_type="ambiguity_note",
            text=text,
            parent_text=f"{amb['description']}\n\nHindi: {amb['public_disclosure_hi']}",
            clause_path=f"Ambiguity Register > {local}",
            page_start=min(pages), page_end=max(pages),
            enterprise_category=list(ALL_CATEGORIES),
            cross_references=list(amb.get("clause_refs", [])),
            ambiguity_flags=[local],
            source_id=source_id, scheme_id=scheme_id,
            source_version=version, source_status=status,
            okf_entity_id=amb["id"],
        ))

    # ---- district reference lists ----------------------------------------
    districts = {d["district_id"]: d["name"] for d in recs.get("district", [])}
    by_cat: dict[tuple[str, str], list[dict]] = {}
    for dc in recs.get("district_classification", []):
        by_cat.setdefault((dc["scheme_id"], dc["category"]), []).append(dc)

    for (scheme_id, category), items in sorted(by_cat.items()):
        source_id, version, status, _ = meta(scheme_id)
        items.sort(key=lambda r: (r.get("list_order") is None, r.get("list_order") or 0))
        names = [districts.get(i["district_id"], i["district_id"]) for i in items]
        joined = ", ".join(names)
        rate = "30%" if category == "A" else "25%"
        chunks.append(Chunk(
            chunk_id=_chunk_id(scheme_id, version, "annexure1", f"region_{category.lower()}"),
            chunk_type="reference_list",
            text=(
                "[MSME Policy 2026 (Draft) > Annexure I: District Categorization (BIIPP) > "
                f"Region {category} > p.25]\n\nRegion {category} districts ({rate} capital "
                f"subsidy rate under section 7.9 item 1): {joined}."
            ),
            parent_text=f"Region {category} ({len(names)} districts): {joined}",
            clause_path=f"Annexure I > Region {category}",
            page_start=25, page_end=25,
            district_region=[category],
            cross_references=["AMB-01", "AMB-20"] if category == "A" else ["AMB-01"],
            source_id=source_id, scheme_id=scheme_id,
            source_version=version, source_status=status,
        ))

    # ---- completeness gaps as retrievable chunks --------------------------
    # A district the policy never classified must be answerable, not silent.
    # This chunk is emitted from the completeness pass's finding rather than
    # hardcoded, so a newly-discovered gap becomes retrievable automatically.
    for finding in result.findings:
        if finding["issue_type"] != "scope_gap" or "missing_members" not in finding:
            continue
        scheme_id = finding["source_ids"][0]
        source_id, version, status, _ = meta(scheme_id)
        for missing in finding["missing_members"]:
            chunks.append(Chunk(
                chunk_id=_chunk_id(scheme_id, version, "annexure1", f"{_slug_name(missing)}_gap"),
                chunk_type="ambiguity_note",
                text=(
                    "[MSME Policy 2026 (Draft) > Annexure I: District Categorization (BIIPP) > "
                    f"{missing} district > p.25]\n\n{missing} district does not appear in either "
                    "Region A or Region B of Annexure I. The capital subsidy district-category "
                    "rate for an enterprise located in "
                    f"{missing} cannot be determined from this document."
                ),
                parent_text="See AMB-20 in the Policy Ambiguity Register.",
                clause_path=f"Annexure I > {missing} (not categorised)",
                page_start=25, page_end=25,
                district_region=["unclassified"],
                cross_references=["AMB-20"],
                ambiguity_flags=["AMB-20"],
                source_id=source_id, scheme_id=scheme_id,
                source_version=version, source_status=status,
            ))

    # ---- sector reference lists -------------------------------------------
    by_class: dict[tuple[str, str], list[dict]] = {}
    for s in recs.get("sector", []):
        by_class.setdefault((s["scheme_id"], s["classification_type"]), []).append(s)
    for (scheme_id, classification), items in by_class.items():
        spec = SECTOR_LIST_RENDER.get(classification)
        if not spec:
            continue
        source_id, version, status, _ = meta(scheme_id)
        items.sort(key=lambda r: (r.get("list_order") is None, r.get("list_order") or 0))
        joined = "; ".join(i["name"] for i in items)
        chunks.append(Chunk(
            chunk_id=_chunk_id(scheme_id, version, *spec["chunk_key"]),
            chunk_type="reference_list",
            text=f"{spec['header']}\n\n{spec['lead']}{joined}.{spec['note']}",
            parent_text=joined,
            clause_path=spec["clause_path"],
            page_start=spec["pages"][0], page_end=spec["pages"][1],
            cross_references=list(spec["xrefs"]),
            source_id=source_id, scheme_id=scheme_id,
            source_version=version, source_status=status,
        ))

    # ---- glossary ---------------------------------------------------------
    terms = recs.get("glossary_term", [])
    if terms:
        terms = sorted(terms, key=lambda r: (r.get("list_order") is None, r.get("list_order") or 0))
        scheme_id = terms[0]["definitions"][0]["scheme_id"]
        source_id, version, status, _ = meta(scheme_id)
        glossary_text = "; ".join(
            f"{t['term']} = {t['definitions'][0]['definition_text']}" for t in terms
        )
        chunks.append(Chunk(
            chunk_id=_chunk_id(scheme_id, version, "glossary", "abbreviations"),
            chunk_type="reference_list",
            text=f"[MSME Policy 2026 (Draft) > List of Abbreviations > p.4]\n\n{glossary_text}",
            parent_text=glossary_text,
            clause_path="List of Abbreviations",
            page_start=4, page_end=4,
            source_id=source_id, scheme_id=scheme_id,
            source_version=version, source_status=status,
        ))

    return chunks


def build_and_write(result) -> int:
    chunks = build_chunks(result)
    ids = [c.chunk_id for c in chunks]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        raise AssertionError(f"Duplicate chunk_ids: {dupes}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_by": "app.okf.chunk_from_okf",
        "chunk_count": len(chunks),
        "chunks": [asdict(c) for c in chunks],
    }
    OUT_JSON.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
        newline="\n",
    )
    return len(chunks)
