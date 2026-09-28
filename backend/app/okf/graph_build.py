"""Build the concept graph the retriever traverses at query time.

Emitted once at compile time to `data/okf_compiled/graph.json`, because
walking 249 Markdown files per query would be absurd.

## Why a graph at all

Vector search retrieves passages that *resemble* a question. It has no way
to assemble an answer whose parts live in different documents, because no
single passage resembles the whole question. The reference implementation
this project follows measured exactly that: on multi-hop questions, basic
RAG scored 0.15 correctness at 0.95 "helpfulness" -- confidently wrong --
while graph traversal over curated links scored 1.00.

The motivating query here is "is a micro food-processing unit in Araria
eligible, and for how much?", which needs five separate concepts:

    districts/ARARIA
      -> (no classification exists)          -> ambiguities/...-AMB-20
    sectors/FOOD-PROCESSING
      -> schemes/BIHAR_MSME_2026
      -> incentives/...-S7.9-ITEM1           (the rate)
      -> eligibility-rules/...-S9.1-*        (the conditions)

No chunk contains that path. The links do.

## Edge weights

Weights express how strongly one concept implies another is relevant, and
they exist mainly to stop hub nodes swamping the evidence set. `in_scheme`
is deliberately weak (0.40): every incentive, sector and district points at
its scheme, so following that edge freely turns any query into "here is the
entire policy".
"""

from __future__ import annotations

import json
from typing import Any

from app.okf import links as links_mod
from app.okf import vault
from app.okf.frontmatter import ENTITY_TO_OKF_TYPE
from app.okf.okf_spec import OKFDocument, trust_tier

GRAPH_JSON = vault.COMPILED_DIR / "graph.json"

# Typed reference fields -> the kind of edge they represent, and its weight.
# These are domain semantics, not prose association, so they are the strong
# edges.
REF_EDGES: dict[str, dict[str, tuple[str, float]]] = {
    "incentive": {
        "eligibility_rule_ids": ("governed_by", 1.00),
        "ambiguity_flags": ("flagged_by", 0.95),
        "district_scope": ("scoped_to_district", 0.80),
        "sector_scope": ("scoped_to_sector", 0.80),
    },
    "eligibility_rule": {
        "ambiguity_flags": ("flagged_by", 0.95),
        "applies_to": ("in_scheme", 0.40),
    },
    "district_classification": {
        # The edge that makes the Araria query answerable: a classification
        # is ABOUT a district, and nothing materialised that link before.
        "district_id": ("classifies", 1.00),
    },
    "scheme": {
        "legal_basis": ("rests_on", 0.90),
    },
}

# scheme_id on these entity types is an implicit edge to the scheme.
SCHEME_EDGE_TYPES = ("incentive", "sector", "district_classification")

# Weighted well below every typed domain edge, including a discounted
# REVERSE in_scheme edge (0.40 * reverse_edge_factor 0.6 = 0.24). Found by
# running an actual query: at 0.70 a scheme's own boilerplate cross-
# reference to its draft-status disclaimer (AMB-17) outscored the real
# incentives reached by walking BACKWARD through that same scheme, so a
# tangential "this policy is unnotified" note ranked ahead of the capital-
# subsidy rate the query was actually asking about. A prose "see also" is
# real evidence of relatedness, but it is the weakest kind this graph has --
# weaker than an explicit typed reference, even one only reachable in
# reverse.
PROSE_EDGE = ("prose_link", 0.30)

# Entity types whose notes are terminal once traversal has left its starting
# point. A Scheme links to everything it contains, so allowing traversal
# THROUGH one pulls in the entire corpus.
HUB_TYPES = frozenset({"scheme"})


def _aliases(entity_type: str, record: dict) -> list[str]:
    """Surface forms a query might use for this concept."""
    out: list[str] = []
    for key in ("name", "term", "short_name", "title"):
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            out.append(value.strip())
    if entity_type == "glossary_term":
        for definition in record.get("definitions") or []:
            pass  # the term itself is already covered by `term`
    # De-duplicate case-insensitively, preserving order.
    seen: set[str] = set()
    unique = []
    for alias in out:
        key = alias.lower()
        if key not in seen:
            seen.add(key)
            unique.append(alias)
    return unique


def _summary(entity_type: str, record: dict) -> str:
    if entity_type == "incentive":
        rates = record.get("category_rates") or []
        if rates:
            return "; ".join(
                f"{r.get('enterprise_category')}: {r.get('rate_text')}"
                for r in rates[:3]
            )[:400]
    for key in ("summary", "description", "condition_text", "basis", "category"):
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            return " ".join(value.split())[:400]
    return ""


def build_graph(result, chunks: list) -> dict[str, Any]:
    """Nodes, weighted edges and unresolved links, from a compiled vault."""
    notes = {n.path: n for n in vault.iter_notes()}
    index = links_mod.build_index(notes=list(notes.values()))

    # (entity_type, domain id) -> concept id. Keyed on the pair, not the
    # domain id alone: CGTMSE and TREDS each exist as both a Scheme and a
    # GlossaryTerm under one domain id, so a flat mapping silently collapses
    # the two and drops a node from the graph entirely.
    concept_of_typed: dict[tuple[str, str], str] = {
        (ref.entity_type, ref.domain_id): ref.concept_id
        for ref in index.by_concept_id.values()
    }
    # Flat view for resolving typed reference FIELDS, whose values are bare
    # domain ids with no type information. Ambiguities resolve by the
    # documented preference in links.RESOLUTION_PREFERENCE.
    concept_of: dict[str, str] = {
        ref.domain_id: ref.concept_id for ref in index.by_domain_id.values()
    }

    # Auto-detected findings, indexed by the member they name, so a concept
    # can carry the gap that was discovered ABOUT it. This is what connects
    # districts/ARARIA -- which has no classification and therefore no edges
    # at all -- to the completeness finding explaining why. Without it a
    # traversal reaching Araria would find nothing and have nothing to say,
    # when "the policy never classified this district" is precisely the
    # answer.
    findings_by_member: dict[str, list[str]] = {}
    for finding in result.findings:
        for member in finding.get("missing_members") or []:
            findings_by_member.setdefault(str(member).lower(), []).append(finding["id"])

    # okf_entity_id -> the chunks compiled from that concept. This join did
    # not exist before: it is what lets a traversed node contribute real,
    # citable retrieved text rather than just a name.
    chunks_by_entity: dict[str, list[str]] = {}
    for chunk in chunks:
        entity_id = getattr(chunk, "okf_entity_id", None)
        if entity_id:
            chunks_by_entity.setdefault(entity_id, []).append(chunk.chunk_id)

    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []
    broken: list[dict[str, str]] = []
    seen_edges: set[tuple[str, str, str]] = set()

    def add_edge(source: str, target: str, kind: str, weight: float) -> None:
        key = (source, target, kind)
        if source == target or key in seen_edges:
            return
        seen_edges.add(key)
        edges.append({"from": source, "to": target, "kind": kind, "w": weight})

    for entity_type, records in result.records.items():
        for record in records:
            domain_id = str(record[vault.ID_FIELD[entity_type]])
            concept_id = concept_of_typed.get((entity_type, domain_id))
            if concept_id is None:
                continue

            ref = index.by_concept_id[concept_id]
            note = notes.get(ref.path)
            tier = "unverified"
            okf_status = "stable"
            if note is not None:
                try:
                    doc = OKFDocument.model_validate(note.frontmatter)
                    tier = trust_tier(doc)
                    okf_status = doc.status
                except Exception:
                    pass

            nodes[concept_id] = {
                "domain_id": domain_id,
                "type": ENTITY_TO_OKF_TYPE.get(entity_type, entity_type),
                "entity_type": entity_type,
                "title": ref.title,
                "scheme_id": record.get("scheme_id")
                or (record.get("applies_to") or [None])[0],
                "trust": tier,
                "status": okf_status,
                "aliases": _aliases(entity_type, record),
                "chunk_ids": sorted(chunks_by_entity.get(domain_id, [])),
                "summary": _summary(entity_type, record),
                "findings": findings_by_member.get(str(ref.title).lower(), [])
                or findings_by_member.get(domain_id.lower(), []),
            }

            # Typed reference fields.
            for field, (kind, weight) in REF_EDGES.get(entity_type, {}).items():
                value = record.get(field)
                targets = value if isinstance(value, list) else ([value] if value else [])
                for target in targets:
                    if not target:
                        continue
                    target_concept = concept_of.get(str(target))
                    if target_concept is None:
                        broken.append({"from": concept_id, "to": str(target),
                                       "kind": kind})
                        continue
                    add_edge(concept_id, target_concept, kind, weight)

            # Implicit scheme membership.
            if entity_type in SCHEME_EDGE_TYPES:
                scheme_id = record.get("scheme_id")
                target_concept = concept_of.get(str(scheme_id)) if scheme_id else None
                if target_concept:
                    add_edge(concept_id, target_concept, "in_scheme", 0.40)

            # Prose links in the body.
            if note is not None:
                for _text, target in index.parse_body_links(note.body):
                    if target.startswith(("http://", "https://", "mailto:")):
                        continue
                    resolved = index.resolve(target, base=note.path)
                    if resolved is None:
                        broken.append({"from": concept_id, "to": target,
                                       "kind": PROSE_EDGE[0]})
                        continue
                    add_edge(concept_id, resolved.concept_id, *PROSE_EDGE)

    return {
        "generated_by": "app.okf.graph_build",
        "okf_version": "0.2",
        "nodes": nodes,
        "edges": edges,
        "broken_links": broken,
        "hub_types": sorted(HUB_TYPES),
    }


def write_graph(result, chunks: list) -> dict[str, Any]:
    graph = build_graph(result, chunks)
    GRAPH_JSON.parent.mkdir(parents=True, exist_ok=True)
    GRAPH_JSON.write_text(
        json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n"
    )
    return graph
