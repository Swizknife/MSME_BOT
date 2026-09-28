"""Query-time traversal of the OKF concept graph.

Loads `data/okf_compiled/graph.json` once and walks it. This is the part
that answers questions vector search structurally cannot: not "which
passage resembles this question" but "which facts, taken together, answer
it" -- assembled by following links a human curated.

    "is a micro food-processing unit in Araria eligible, and for how much?"

        districts/ARARIA ......... no classification -> the finding that
                                   says so (AMB-20's territory)
        sectors/FOOD-PROCESSING .. in_scheme -> BIHAR_MSME_2026
        incentives/...ITEM1 ...... governed_by -> eligibility-rules/...S9.1

No single chunk contains that. Vector search will confidently return the
capital-subsidy table row and state a rate that does not apply, which is
the documented failure this module exists to fix.

## Design constraints, and why

**No LLM, anywhere.** Entry points are resolved by alias matching, matching
`intents.py`'s existing doctrine. A router that needs a model call to decide
how to route is a router that can hallucinate a route.

**Hub suppression.** A Scheme links to every incentive, sector and district
it contains, so traversing THROUGH one turns any query into "here is the
entire policy". Scheme nodes are terminal once traversal has left its
starting point.

**Missing is a finding, not an error.** A node reached with no onward edge,
or carrying a compile-time completeness finding, lands in
`GraphEvidence.missing`. "The policy never classified Araria" is the answer
to the motivating query, not a failure to answer it.

**Degrades to empty, never raises.** Same doctrine as `store.py`: if the
graph is absent or malformed the bot falls back to plain RAG rather than
returning a 500.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from app.okf import vault

REPO_ROOT = Path(__file__).resolve().parents[3]
GRAPH_JSON = vault.COMPILED_DIR / "graph.json"
CONFIG_PATH = REPO_ROOT / "config" / "graph.yaml"

# Types a hub (a Scheme) may expand toward, and the order neighbours are
# preferred in when a fan-out cap bites. An Incentive answers "how much", an
# EligibilityRule answers "can I", an AmbiguityFlag answers "why can't you
# tell me" -- those carry answers. A Scheme's 67 sectors and 38 district
# classifications are membership lists, not answers, so they are reachable
# as destinations but are not what a hub expands into.
HUB_EXPAND_TYPES = frozenset({"incentive", "eligibility_rule", "ambiguity_flag", "act"})

_TYPE_PRIORITY = {
    "incentive": 0,
    "eligibility_rule": 1,
    "ambiguity_flag": 2,
    "act": 3,
    "district_classification": 4,
    "district": 5,
    "sector": 6,
    "glossary_term": 7,
    "authority": 8,
    "scheme": 9,
}

DEFAULTS = {
    "max_hops": 2,
    "fan_out": 8,
    "hub_fan_out": 6,
    "max_nodes": 24,
    "decay": 0.6,
    "reverse_edge_factor": 0.6,
    "min_alias_length": 4,
    "allow_graph_override_of_gate": True,
    "min_nodes_for_graph_tier": 2,
}

# Words too common to identify a concept on their own. An alias consisting
# only of these is ignored, or every query matches every scheme.
_STOPWORDS = {
    "the", "and", "for", "with", "from", "policy", "scheme", "subsidy",
    "incentive", "bihar", "msme", "enterprise", "enterprises", "state",
    "district", "districts", "sector", "sectors", "other", "general",
}

_WORD_RE = re.compile(r"[a-z0-9]+")


@lru_cache(maxsize=1)
def _config() -> dict[str, Any]:
    cfg = dict(DEFAULTS)
    if CONFIG_PATH.exists():
        try:
            loaded = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
            if isinstance(loaded, dict):
                cfg.update({k: v for k, v in loaded.items() if k in DEFAULTS})
        except (yaml.YAMLError, OSError):
            pass
    return cfg


@dataclass
class Graph:
    nodes: dict[str, dict[str, Any]] = field(default_factory=dict)
    out_edges: dict[str, list[dict]] = field(default_factory=dict)
    in_edges: dict[str, list[dict]] = field(default_factory=dict)
    alias_index: dict[str, list[str]] = field(default_factory=dict)
    by_domain_id: dict[str, str] = field(default_factory=dict)
    hub_types: frozenset = frozenset()

    def __bool__(self) -> bool:
        return bool(self.nodes)


def _normalize(text: str) -> str:
    return " ".join(_WORD_RE.findall((text or "").lower()))


@lru_cache(maxsize=1)
def _graph() -> Graph:
    if not GRAPH_JSON.exists():
        return Graph()
    try:
        raw = json.loads(GRAPH_JSON.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return Graph()

    nodes = raw.get("nodes") or {}
    graph = Graph(
        nodes=nodes,
        hub_types=frozenset(raw.get("hub_types") or ()),
    )
    for edge in raw.get("edges") or []:
        graph.out_edges.setdefault(edge["from"], []).append(edge)
        graph.in_edges.setdefault(edge["to"], []).append(edge)

    minimum = _config()["min_alias_length"]
    for concept_id, node in nodes.items():
        graph.by_domain_id.setdefault(str(node.get("domain_id", "")), concept_id)
        surfaces = list(node.get("aliases") or [])
        surfaces.append(str(node.get("domain_id", "")))
        for surface in surfaces:
            key = _normalize(surface)
            if len(key) < minimum:
                continue
            if all(word in _STOPWORDS for word in key.split()):
                continue
            graph.alias_index.setdefault(key, []).append(concept_id)
    return graph


def is_available() -> bool:
    return bool(_graph())


@dataclass
class GraphNode:
    concept_id: str
    type: str
    title: str
    hop: int
    via: str | None
    score: float
    trust: str
    chunk_ids: list[str] = field(default_factory=list)
    summary: str = ""


@dataclass
class GraphEvidence:
    entry_points: list[str] = field(default_factory=list)
    nodes: list[GraphNode] = field(default_factory=list)
    chunk_ids: list[str] = field(default_factory=list)
    ambiguity_ids: list[str] = field(default_factory=list)
    finding_ids: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.nodes)


def resolve_entry_points(text: str, *, seed_entity_ids: list[str] | None = None) -> list[str]:
    """Concepts a query names, by alias match. No LLM, no embedding.

    `seed_entity_ids` are `okf_entity_id`s from chunks the vector retriever
    already ranked highly. Seeding from them is what makes hybrid mode more
    than the union of the two pure modes: retrieval finds a starting point
    the query's own wording did not name, and the graph then walks outward
    from it.
    """
    graph = _graph()
    if not graph:
        return []

    found: list[str] = []
    seen: set[str] = set()

    for entity_id in seed_entity_ids or []:
        concept_id = graph.by_domain_id.get(str(entity_id))
        if concept_id and concept_id not in seen:
            seen.add(concept_id)
            found.append(concept_id)

    haystack = _normalize(text)
    if haystack:
        padded = f" {haystack} "
        # Longest aliases first: "food processing" should win over "food".
        for alias in sorted(graph.alias_index, key=len, reverse=True):
            if f" {alias} " in padded:
                for concept_id in graph.alias_index[alias]:
                    if concept_id not in seen:
                        seen.add(concept_id)
                        found.append(concept_id)
    return found


def traverse(
    entry_points: list[str],
    *,
    max_hops: int | None = None,
    fan_out: int | None = None,
    max_nodes: int | None = None,
) -> GraphEvidence:
    """Breadth-first walk outward from the entry points."""
    graph = _graph()
    evidence = GraphEvidence(entry_points=list(entry_points))
    if not graph or not entry_points:
        return evidence

    cfg = _config()
    max_hops = cfg["max_hops"] if max_hops is None else max_hops
    fan_out = cfg["fan_out"] if fan_out is None else fan_out
    max_nodes = cfg["max_nodes"] if max_nodes is None else max_nodes
    decay = float(cfg["decay"])
    reverse_factor = float(cfg["reverse_edge_factor"])

    best: dict[str, GraphNode] = {}
    frontier: list[tuple[str, int, float, str | None]] = [
        (concept_id, 0, 1.0, None)
        for concept_id in entry_points
        if concept_id in graph.nodes
    ]

    while frontier:
        concept_id, hop, score, via = frontier.pop(0)
        node = graph.nodes.get(concept_id)
        if node is None:
            continue

        existing = best.get(concept_id)
        if existing is not None and existing.score >= score:
            continue
        best[concept_id] = GraphNode(
            concept_id=concept_id,
            type=str(node.get("type", "")),
            title=str(node.get("title", concept_id)),
            hop=hop,
            via=via,
            score=score,
            trust=str(node.get("trust", "unverified")),
            chunk_ids=list(node.get("chunk_ids") or []),
            summary=str(node.get("summary", "")),
        )

        if hop >= max_hops or len(best) >= max_nodes:
            continue

        candidates: list[tuple[float, str, str]] = []
        for edge in graph.out_edges.get(concept_id, []):
            candidates.append((float(edge["w"]), edge["to"], edge["kind"]))
        for edge in graph.in_edges.get(concept_id, []):
            # Reverse edges matter: a classification points AT a district,
            # so reaching the classification from the district requires
            # walking the edge backwards. Discounted, because "X refers to
            # me" is weaker evidence than "I refer to X".
            candidates.append(
                (float(edge["w"]) * reverse_factor, edge["from"], f"{edge['kind']}~")
            )

        # Hub handling. A Scheme is pointed at by all 156 of its incentives,
        # sectors and district classifications, so expanding one freely
        # turns any query into "here is the entire policy". Blocking it
        # entirely is worse though: "how much does a food-processing unit
        # get" reaches the scheme through its sector and then has nowhere to
        # go, so it never finds a rate and returns no citable chunk at all.
        #
        # So a hub expands, but only toward the types that carry answers,
        # and narrowly. The remaining gap -- an incentive the query never
        # names -- is what hybrid mode's vector seeding is for, not
        # something to paper over by widening this.
        limit = fan_out
        if hop > 0 and node.get("entity_type") in graph.hub_types:
            candidates = [
                c for c in candidates
                if graph.nodes.get(c[1], {}).get("entity_type") in HUB_EXPAND_TYPES
            ]
            limit = _config()["hub_fan_out"]

        candidates.sort(
            key=lambda c: (
                -c[0],
                _TYPE_PRIORITY.get(
                    graph.nodes.get(c[1], {}).get("entity_type", ""), 99
                ),
                c[1],
            )
        )
        for weight, target, kind in candidates[:limit]:
            frontier.append((target, hop + 1, score * weight * decay, kind))

    ranked = sorted(best.values(), key=lambda n: (-n.score, n.hop, n.concept_id))
    evidence.nodes = ranked[:max_nodes]

    chunk_ids: list[str] = []
    ambiguity_ids: list[str] = []
    finding_ids: list[str] = []
    missing: list[str] = []

    for node in evidence.nodes:
        for chunk_id in node.chunk_ids:
            if chunk_id not in chunk_ids:
                chunk_ids.append(chunk_id)
        raw = graph.nodes.get(node.concept_id, {})
        if raw.get("entity_type") == "ambiguity_flag":
            ambiguity_ids.append(str(raw.get("domain_id")))
        for finding_id in raw.get("findings") or []:
            if finding_id not in finding_ids:
                finding_ids.append(finding_id)
                missing.append(
                    f"{node.title}: {finding_id}"
                )

    evidence.chunk_ids = chunk_ids
    evidence.ambiguity_ids = ambiguity_ids
    evidence.finding_ids = finding_ids
    evidence.missing = missing
    return evidence


def walk(text: str, *, seed_entity_ids: list[str] | None = None) -> GraphEvidence:
    """resolve_entry_points + traverse, the usual pairing."""
    return traverse(resolve_entry_points(text, seed_entity_ids=seed_entity_ids))


def _cli() -> None:
    import sys

    if len(sys.argv) < 2:
        print('usage: python -m app.okf.graph "<query>"')
        raise SystemExit(2)
    query = " ".join(sys.argv[1:])
    graph = _graph()
    print(f"graph: {len(graph.nodes)} nodes, "
          f"{sum(len(v) for v in graph.out_edges.values())} edges")
    evidence = walk(query)
    print(f"\nquery        : {query!r}")
    print(f"entry points : {evidence.entry_points or '(none)'}")
    print(f"nodes reached: {len(evidence.nodes)}")
    for node in evidence.nodes:
        via = f" via {node.via}" if node.via else " (entry)"
        chunks = f"  [{len(node.chunk_ids)} chunk(s)]" if node.chunk_ids else ""
        print(f"  h{node.hop} {node.score:.3f}  {node.type:22s} {node.title}{via}{chunks}")
        if node.summary:
            print(f"        {node.summary[:110]}")
    print(f"\nchunk ids    : {len(evidence.chunk_ids)}")
    print(f"ambiguities  : {evidence.ambiguity_ids or '(none)'}")
    print(f"missing      : {evidence.missing or '(none)'}")


if __name__ == "__main__":
    _cli()
