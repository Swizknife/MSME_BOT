"""What a mode is allowed to answer from, decided before the ladder runs.

Three modes, one ladder (`ladder.py`). This module is the only place that
decides what "rag", "okf" and "okf_rag" actually mean in terms of what data
reaches an answer -- the ladder itself just reads the `Evidence` this
produces and never branches on `mode` directly, so its logic cannot quietly
diverge between modes by accident.

    rag      vector retrieval only. No graph, no OKF injection, no OKF
             consistency guard. The confidently-wrong baseline the mode
             toggle exists to expose: e.g. the interest-subsidy query that
             mis-retrieves Capital Subsidy's real, grounded, wrong-topic
             figures with no structured layer to catch it.

    okf      no vector search at all -- zero Qdrant queries. The graph is
             walked from the query's own wording, and confidence is decided
             by `coverage_gate.okf_coverage`, not a reranker score.

    okf_rag  (default) vector retrieval AND the graph, and the graph is
             seeded by BOTH the query's wording and the `okf_entity_id`s of
             whatever the vector search ranked highest. That second seeding
             is what makes this more than the union of the other two modes:
             it can start a multi-hop walk from a concept the query itself
             never named.

Safety property that must never move: in every mode, the Coverage Gate
decision is made from vector evidence ALONE, before any graph chunk is
merged in. If a graph-only chunk could push `top_score` past a threshold,
graph traversal would silently defeat abstention -- and abstention is this
product's whole safety story. See `_build_okf_rag`: `evidence.gate` is
`result.gate`, computed by `coverage_gate.decide()` on `result.reranked`
alone, untouched by the graph walk that follows it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from app.okf import graph as graph_mod
from app.policy.intents import QueryUnderstanding
from app.retrieval.coverage_gate import GateDecision, okf_coverage
from app.retrieval.hybrid import RetrievedChunk
from app.retrieval.pipeline import retrieve

Mode = Literal["rag", "okf", "okf_rag"]


@dataclass
class Evidence:
    mode: Mode
    reranked: list[tuple[RetrievedChunk, float]] = field(default_factory=list)
    gate: GateDecision = field(
        default_factory=lambda: GateDecision(action="abstain", top_score=0.0, tau_hard=0.0, tau_soft=0.0)
    )
    graph: graph_mod.GraphEvidence | None = None
    # Whether Tier 4 may inject a single resolved OKF record as [S1] ahead of
    # the retrieved narrative (the existing "hybrid" behaviour), and whether
    # okf_consistency_guard may run against it. False in rag mode: no
    # structured record may reach the prompt or a guard, or the mode is not
    # actually RAG-only.
    allow_okf_injection: bool = False
    # Whether Tier 3 (single dominant chunk, no LLM) is reachable. True in
    # every mode that has a reranked vector list to be dominant IN --
    # meaningless in pure okf mode, where "dominant chunk" has no reranker
    # score to be dominant BY.
    allow_extractive: bool = True


def normalize_understanding(mode: Mode, understanding: QueryUnderstanding) -> QueryUnderstanding:
    """Applies mode's effect on ROUTING, as distinct from evidence.

    rag mode must force retrieval_mode back to "rag_narrative" and clear the
    OKF matches: `understanding.retrieval_mode` is what gates Tier 1
    (okf_lookup) and the Tier 4 hybrid-injection branch in ladder.py, and
    those branches are unchanged by this refactor -- they are exactly what
    "no structured record reaches the answer" means operationally. Clearing
    it here, once, is what makes that guarantee hold without touching either
    branch's logic.
    """
    if mode != "rag":
        return understanding
    if understanding.retrieval_mode == "rag_narrative" and not understanding.okf_matches:
        return understanding
    from dataclasses import replace

    return replace(understanding, retrieval_mode="rag_narrative", okf_matches=[], okf_category=None)


def _seed_entity_ids(reranked: list[tuple[RetrievedChunk, float]], limit: int = 6) -> list[str]:
    seeds: list[str] = []
    for chunk, _score in reranked[:limit]:
        entity_id = chunk.payload.get("okf_entity_id")
        if entity_id and entity_id not in seeds:
            seeds.append(entity_id)
    return seeds


def _build_rag(message: str, understanding: QueryUnderstanding) -> Evidence:
    result = retrieve(message, is_hinglish=understanding.is_hinglish)
    return Evidence(
        mode="rag", reranked=result.reranked, gate=result.gate,
        graph=None, allow_okf_injection=False, allow_extractive=True,
    )


def _build_okf(message: str, understanding: QueryUnderstanding) -> Evidence:
    graph_evidence = graph_mod.walk(message)
    gate = okf_coverage(graph_evidence)
    reranked: list[tuple[RetrievedChunk, float]] = []
    if graph_evidence.chunk_ids:
        # A payload lookup, not a search -- no embedding, no rerank score.
        # Each chunk's synthetic score is its node's traversal score, so
        # citation order still roughly reflects relevance without claiming a
        # reranker judged it.
        from app.retrieval.hybrid import fetch_by_chunk_ids

        chunk_map = fetch_by_chunk_ids(graph_evidence.chunk_ids)
        score_by_chunk_id = {
            cid: node.score for node in graph_evidence.nodes for cid in node.chunk_ids
        }
        reranked = [
            (chunk_map[cid], score_by_chunk_id.get(cid, 0.0))
            for cid in graph_evidence.chunk_ids
            if cid in chunk_map
        ]
        reranked.sort(key=lambda t: t[1], reverse=True)
    return Evidence(
        mode="okf", reranked=reranked, gate=gate, graph=graph_evidence,
        allow_okf_injection=True, allow_extractive=False,
    )


def _build_okf_rag(message: str, understanding: QueryUnderstanding) -> Evidence:
    result = retrieve(message, is_hinglish=understanding.is_hinglish)
    seeds = _seed_entity_ids(result.reranked)
    graph_evidence = graph_mod.walk(message, seed_entity_ids=seeds)
    return Evidence(
        mode="okf_rag", reranked=result.reranked, gate=result.gate,
        graph=graph_evidence, allow_okf_injection=True, allow_extractive=True,
    )


_BUILDERS = {"rag": _build_rag, "okf": _build_okf, "okf_rag": _build_okf_rag}


def build(mode: Mode, message: str, understanding: QueryUnderstanding) -> Evidence:
    builder = _BUILDERS.get(mode, _build_okf_rag)
    return builder(message, understanding)
