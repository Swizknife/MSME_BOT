"""The OKF vault compiler.

Reads every authored note in data/okf_vault/, and:

  1. VALIDATES its frontmatter against the matching entity schema
     (schemas.py). A note that fails is a hard error, not a warning.
  2. RESOLVES every [[wikilink]] and every ref-style id field against the
     set of entity ids actually present. An unresolved link fails the
     compile -- a dangling reference indexed into the bot is a citation
     that goes nowhere.
  3. CROSS-CHECKS each fact's figures against the staged raw source text.
     This compares FIGURE TOKENS (percentages, rupee amounts, counts), not
     whole strings: the source PDF wraps sentences across table cells and
     page boundaries, so whole-sentence containment fails on correct data.
     The token approach and its page+1 tolerance are reused deliberately
     from ingestion/verify_policy_data.py, which learned this the hard way.
  4. Runs the two AMBIGUITY DETECTION passes:
       (a) contradiction  -- records sharing a natural key that disagree
       (b) completeness   -- records absent relative to a reference set
     Pass (b) is what finds a gap like Araria's missing district
     classification, which (a) structurally cannot: there is no record to
     disagree with. Auto-emitted findings are always `advisory`; promoting
     one to `blocking` is a human judgement.
  5. EMITS two artifacts from the same parse: structured OKF JSON records
     under data/okf_compiled/, and RAG-ready chunks.

Run:  python -m app.okf.compile     (thin wrapper)
      python -m app.okf.compiler
"""

from __future__ import annotations

import json
import re
import shutil
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.okf import links as links_mod
from app.okf import vault
from app.okf.frontmatter import to_domain_payload
from app.okf.okf_spec import OKFDocument
from app.okf.schemas import ENTITY_MODELS

REPO_ROOT = Path(__file__).resolve().parents[3]
EXTRACTED_JSON = REPO_ROOT / "data" / "extracted" / "msme_policy_2026.raw.json"

# Same token grammar as ingestion/verify_policy_data.py -- kept in sync
# deliberately. See this module's docstring for why whole-string matching
# is wrong here.
FIGURE_PATTERN = re.compile(
    r"\d+(?:\.\d+)?\s*(?:%|Crore|croe|Lakhs?|lakhs?|Kw)|Rs\.?\s?\d[\d,]*|\d[\d,]*/-"
)

# Which staged source text each source_id's figures are checked against.
# Only sources whose raw text has actually been extracted can be checked;
# anything else is reported as unchecked rather than silently passing.
EXTRACTED_TEXT_BY_SOURCE = {
    "BIHAR_MSME_POLICY_2026": EXTRACTED_JSON,
}

# Which entity id field identifies each entity type.
# Moved to vault.py so links.py can use it without making that module and
# this one circular. Re-exported here because callers already import it from
# the compiler.
ID_FIELD = vault.ID_FIELD

# Fields holding references to other entities, checked for resolvability.
REF_FIELDS = {
    "incentive": ["eligibility_rule_ids", "ambiguity_flags", "district_scope", "sector_scope"],
    "eligibility_rule": ["applies_to"],
    "district_classification": ["district_id"],
    "scheme": ["legal_basis"],
}


@dataclass
class CompileResult:
    records: dict[str, list[dict]] = field(default_factory=lambda: defaultdict(list))
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    findings: list[dict] = field(default_factory=list)   # auto-detected ambiguities
    figures_checked: int = 0
    figures_unchecked_sources: set = field(default_factory=set)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def _page_text_map(path: Path) -> dict[int, str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return {p["page_number"]: _normalize(p["text"]) for p in data["pages"]}


def _collect_checkable_text(entity_type: str, fm: dict) -> list[tuple[str, str]]:
    """(label, text) pairs whose figures must appear in the source."""
    out: list[tuple[str, str]] = []
    if entity_type == "incentive":
        for rate in fm.get("category_rates") or []:
            out.append((f"{fm.get('incentive_id')} [{rate.get('enterprise_category')}]",
                        rate.get("rate_text") or ""))
    elif entity_type == "eligibility_rule":
        out.append((str(fm.get("rule_id")), fm.get("condition_text") or ""))
    return out


def _check_figures(result: CompileResult, entity_type: str, fm: dict) -> None:
    source = fm.get("source") or {}
    source_id = source.get("source_id")
    page_start = source.get("page_start")
    text_path = EXTRACTED_TEXT_BY_SOURCE.get(source_id)
    checkable = _collect_checkable_text(entity_type, fm)
    if not checkable:
        return
    if text_path is None or not text_path.exists():
        if source_id:
            result.figures_unchecked_sources.add(source_id)
        return
    if page_start is None:
        result.errors.append(
            f"{fm.get(ID_FIELD.get(entity_type, 'id'))}: source.page_start missing, "
            f"cannot cross-check figures against {source_id}"
        )
        return

    page_text = _page_text_map(text_path)
    # A table row's cell can wrap onto the following page, so a figure is
    # accepted on its stated page or the next one -- same tolerance the
    # pre-OKF validator established against real data.
    haystack = page_text.get(page_start, "") + " " + page_text.get(page_start + 1, "")
    for label, text in checkable:
        for fig in set(FIGURE_PATTERN.findall(text)):
            result.figures_checked += 1
            if _normalize(fig) not in haystack:
                result.errors.append(
                    f"{label} (p.{page_start}/{page_start + 1}): figure {_normalize(fig)!r} "
                    f"not found in staged source text"
                )


# ---------------------------------------------------------------------------
# Ambiguity detection
# ---------------------------------------------------------------------------


def _pass_contradiction(result: CompileResult) -> None:
    """Records sharing a natural key whose values disagree."""
    # District classified differently by two schemes.
    by_district: dict[str, list[dict]] = defaultdict(list)
    for rec in result.records.get("district_classification", []):
        by_district[rec["district_id"]].append(rec)
    for district_id, recs in sorted(by_district.items()):
        categories = {r["category"] for r in recs}
        if len(categories) > 1:
            schemes = sorted({r["scheme_id"] for r in recs})
            result.findings.append({
                "id": f"AUTO-CONTRADICTION-DISTRICT-{district_id}",
                "scope": "cross_source",
                "issue_type": "cross_source_contradiction",
                "severity": "advisory",
                "description": (
                    f"{district_id} is classified as {sorted(categories)} by different "
                    f"schemes ({schemes}). Neither value may be silently preferred."
                ),
                "source_ids": schemes,
            })

    # Same glossary term defined differently by two schemes.
    for rec in result.records.get("glossary_term", []):
        defs = rec.get("definitions") or []
        texts = {d["definition_text"] for d in defs}
        if len(texts) > 1:
            result.findings.append({
                "id": f"AUTO-CONTRADICTION-TERM-{rec['term_id']}",
                "scope": "cross_source",
                "issue_type": "cross_source_contradiction",
                "severity": "advisory",
                "description": (
                    f"Term {rec['term']!r} carries {len(texts)} differing definitions "
                    f"across schemes {sorted(d['scheme_id'] for d in defs)}."
                ),
                "source_ids": sorted({d["scheme_id"] for d in defs}),
            })


def _pass_completeness(result: CompileResult) -> None:
    """Records absent relative to a closed reference universe.

    This is the pass that finds a gap like a district the policy never
    classified. The contradiction pass cannot: an absent record has nothing
    to disagree with.
    """
    try:
        ref = vault.load_reference_set("bihar_districts")
    except FileNotFoundError as exc:
        result.errors.append(str(exc))
        return

    aliases = ref.get("aliases") or {}
    universe = {vault.normalize_member(m, aliases) for m in ref["members"]}

    by_scheme: dict[str, set[str]] = defaultdict(set)
    district_names = {r["district_id"]: r["name"] for r in result.records.get("district", [])}
    for rec in result.records.get("district_classification", []):
        name = district_names.get(rec["district_id"], rec["district_id"])
        by_scheme[rec["scheme_id"]].add(vault.normalize_member(name, aliases))

    for scheme_id, classified in sorted(by_scheme.items()):
        missing = sorted(universe - classified)
        if missing:
            result.findings.append({
                "id": f"AUTO-COMPLETENESS-DISTRICTS-{scheme_id}",
                "scope": "single_source",
                "issue_type": "scope_gap",
                "severity": "advisory",
                "description": (
                    f"{scheme_id} classifies {len(classified)} of {len(universe)} districts "
                    f"in reference set {ref['reference_set_id']}. Missing: {missing}. "
                    f"An enterprise in a missing district has no determinable "
                    f"district-linked rate."
                ),
                "source_ids": [scheme_id],
                "missing_members": missing,
            })

    # Every incentive must state a rate for each category it claims to vary by.
    for rec in result.records.get("incentive", []):
        rates = rec.get("category_rates") or []
        if rec.get("varies_by_category") and len(rates) < 2:
            result.findings.append({
                "id": f"AUTO-COMPLETENESS-RATES-{rec['incentive_id']}",
                "scope": "single_source",
                "issue_type": "missing_rate",
                "severity": "advisory",
                "description": (
                    f"{rec['incentive_id']} is marked varies_by_category but states "
                    f"{len(rates)} category rate(s)."
                ),
                "source_ids": [rec["scheme_id"]],
            })


# ---------------------------------------------------------------------------


def compile_vault(vault_dir: Path = vault.VAULT_DIR) -> CompileResult:
    result = CompileResult()
    notes = vault.iter_notes(vault_dir)
    if not notes:
        result.errors.append(f"No authored notes found under {vault_dir}")
        return result

    known_ids: set[str] = set()
    validated: list[tuple[str, dict, vault.VaultNote]] = []
    link_index = links_mod.build_index(notes=notes)

    for note in notes:
        # Two independent validations, deliberately kept separate so their
        # failures cannot mask one another:
        #
        #   1. Is this a conformant Google OKF v0.2 document? (the spec)
        #   2. Is it a coherent Incentive/Scheme/...?          (this project)
        #
        # A note can be perfectly valid OKF and still be nonsense as policy
        # data, and the two deserve different error messages.
        try:
            OKFDocument.model_validate(note.frontmatter)
        except ValidationError as exc:
            result.errors.append(
                f"{note.path.name}: not a conformant OKF v0.2 document -- {exc}"
            )
            continue

        try:
            etype, payload = to_domain_payload(note.frontmatter)
        except ValueError as exc:
            result.errors.append(f"{note.path.name}: {exc}")
            continue

        model = ENTITY_MODELS[etype]
        try:
            obj = model.model_validate(payload)
        except ValidationError as exc:
            result.errors.append(f"{note.path.name}: schema validation failed -- {exc}")
            continue
        record = obj.model_dump(mode="json")
        record["_body"] = note.body
        validated.append((etype, record, note))
        known_ids.add(str(record[ID_FIELD[etype]]))

    # Referential integrity: ref fields and wikilinks must resolve.
    for etype, record, note in validated:
        own_id = record[ID_FIELD[etype]]
        for fname in REF_FIELDS.get(etype, []):
            value = record.get(fname)
            refs = value if isinstance(value, list) else ([value] if value else [])
            for ref in refs:
                if ref and str(ref) not in known_ids:
                    result.errors.append(
                        f"{own_id}: {fname} references unknown entity {ref!r}"
                    )
        # Prose markdown links are a different class from the typed reference
        # fields above, and the OKF spec treats them differently on purpose:
        # a broken one means "knowledge nobody has written yet", and
        # consumers MUST tolerate it. So it is a warning plus an advisory
        # finding, never a hard error -- tolerated, but never invisible.
        #
        # The typed fields stay hard failures because chunk_from_okf
        # dereferences them into chunk TEXT, so an unresolved one renders a
        # citation that goes nowhere. The spec constrains prose links, not
        # the semantics of a producer's extension keys.
        for text, target in link_index.parse_body_links(note.body):
            if link_index.resolve(target, base=note.path) is None:
                if target.startswith(("http://", "https://", "mailto:")):
                    continue
                result.warnings.append(
                    f"{own_id}: link [{text}]({target}) has no document in the bundle"
                )
                result.findings.append({
                    "id": f"AUTO-BROKEN-LINK-{own_id}-{target}",
                    "scope": "single_source",
                    "issue_type": "scope_gap",
                    "severity": "advisory",
                    "description": (
                        f"{own_id} links to {target}, which has no document in "
                        f"the bundle yet."
                    ),
                    "missing_members": [target],
                })

    for etype, record, _ in validated:
        _check_figures(result, etype, record)
        result.records[etype].append(record)

    _pass_contradiction(result)
    _pass_completeness(result)
    return result


def write_records(result: CompileResult, out_dir: Path = vault.COMPILED_DIR) -> int:
    written = 0
    for etype, records in result.records.items():
        target = out_dir / etype
        if target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True, exist_ok=True)
        for rec in records:
            rid = str(rec[ID_FIELD[etype]])
            safe = rid.replace("/", "_")
            (target / f"{safe}.json").write_text(
                json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            written += 1
    (out_dir / "findings.json").write_text(
        json.dumps(result.findings, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return written


def main() -> None:
    result = compile_vault()

    for w in result.warnings:
        print(f"WARN: {w}")
    if result.errors:
        for e in result.errors[:40]:
            print(f"FAIL: {e}")
        if len(result.errors) > 40:
            print(f"... and {len(result.errors) - 40} more")
        print(f"\n{len(result.errors)} error(s). Nothing written.")
        sys.exit(1)

    from app.okf import chunk_from_okf   # imported late: chunking depends on compiled records

    from app.okf import graph_build

    written = write_records(result)
    chunks = chunk_from_okf.build_and_write(result)
    graph = graph_build.write_graph(result, chunk_from_okf.build_chunks(result))

    print(f"Compiled {written} OKF records -> {vault.COMPILED_DIR}")
    for etype, records in sorted(result.records.items()):
        print(f"  {etype:24s} {len(records)}")
    print(f"Cross-checked {result.figures_checked} figure tokens against staged source text.")
    if result.figures_unchecked_sources:
        print(f"  NOT cross-checked (no staged text): {sorted(result.figures_unchecked_sources)}")
    print(f"Emitted {chunks} RAG chunks -> {chunk_from_okf.OUT_JSON}")
    print(
        f"Emitted concept graph -> {graph_build.GRAPH_JSON.name}: "
        f"{len(graph['nodes'])} nodes, {len(graph['edges'])} edges, "
        f"{len(graph['broken_links'])} unresolved link(s)"
    )
    print(f"\nAuto-detected findings: {len(result.findings)}")
    for f in result.findings:
        print(f"  [{f['severity']}] {f['issue_type']}: {f['id']}")
        print(f"      {f['description']}")


if __name__ == "__main__":
    main()
