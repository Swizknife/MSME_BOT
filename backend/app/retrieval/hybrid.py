"""
Hybrid dense + sparse retrieval over the local Qdrant collection, fused with
Reciprocal Rank Fusion (RRF).

Per docs/RAG_IMPLEMENTATION.md section 6 ("Hybrid retrieval"): dense cosine
and sparse dot-product scores live on incompatible scales, so a fixed-alpha
weighted blend is a fragile hand-tuned constant. RRF fuses on RANK instead
of raw score, is scale-free, and needs no tuning. This is what lets sparse
retrieval recover exact-numeral queries (Rs.24,000, 300 Kw, section 9.1(d))
that dense-only retrieval is known to miss, without the two score spaces
ever having to be compared directly.

Qdrant's own query API can do prefetch+fusion server-side; this module does
it client-side instead so the RRF constant and shortlist size are easy to
inspect/tune from Python without touching query DSL, which matters more
than the small round-trip saving at this corpus size (~85-400 vectors,
sub-millisecond either way).
"""

from __future__ import annotations

from dataclasses import dataclass

from qdrant_client.models import SparseVector

from app.retrieval.qdrant_local import (
    COLLECTION_NAME,
    DENSE_VECTOR_NAME,
    SPARSE_VECTOR_NAME,
    get_client,
)

RRF_K = 60  # standard RRF constant; de-emphasizes rank-1-vs-rank-2 noise
DENSE_LIMIT = 30
SPARSE_LIMIT = 30
FUSED_LIMIT = 12  # shortlist size handed to the reranker
                   # (docs/RAG_IMPLEMENTATION.md section 5.1: 30->12 candidates,
                   # since reranking is the O(n) bottleneck on CPU)


@dataclass
class RetrievedChunk:
    chunk_id: str
    payload: dict
    dense_rank: int | None
    sparse_rank: int | None
    rrf_score: float


def _sparse_query_vector(sparse_weights: dict[str, float]) -> SparseVector:
    indices = [int(k) for k in sparse_weights.keys()]
    values = [float(v) for v in sparse_weights.values()]
    return SparseVector(indices=indices, values=values)


def hybrid_search(
    dense_vector: list[float],
    sparse_weights: dict[str, float],
    query_filter=None,
    fused_limit: int = FUSED_LIMIT,
) -> list[RetrievedChunk]:
    # client.search() + NamedVector/NamedSparseVector are the pre-1.10
    # Qdrant Python API and no longer exist on qdrant-client 1.19 (the
    # version this project installs) -- query_points() with `using=` to
    # select which named vector space to search is the current equivalent.
    # RRF fusion itself still happens client-side in Python below (not via
    # query_points' own `prefetch=`/FusionQuery), per this module's
    # docstring: keeping the fusion constant and shortlist size inspectable
    # from plain Python matters more than the small round-trip saving at
    # this corpus size.
    client = get_client()

    dense_hits = client.query_points(
        collection_name=COLLECTION_NAME,
        query=dense_vector,
        using=DENSE_VECTOR_NAME,
        query_filter=query_filter,
        limit=DENSE_LIMIT,
        with_payload=True,
    ).points
    sparse_hits = client.query_points(
        collection_name=COLLECTION_NAME,
        query=_sparse_query_vector(sparse_weights),
        using=SPARSE_VECTOR_NAME,
        query_filter=query_filter,
        limit=SPARSE_LIMIT,
        with_payload=True,
    ).points

    dense_rank = {hit.id: i for i, hit in enumerate(dense_hits)}
    sparse_rank = {hit.id: i for i, hit in enumerate(sparse_hits)}
    payload_by_id = {hit.id: hit.payload for hit in dense_hits}
    payload_by_id.update({hit.id: hit.payload for hit in sparse_hits})

    all_ids = set(dense_rank) | set(sparse_rank)
    fused: list[RetrievedChunk] = []
    for pid in all_ids:
        dr = dense_rank.get(pid)
        sr = sparse_rank.get(pid)
        score = 0.0
        if dr is not None:
            score += 1.0 / (RRF_K + dr + 1)
        if sr is not None:
            score += 1.0 / (RRF_K + sr + 1)
        payload = payload_by_id[pid]
        fused.append(RetrievedChunk(
            chunk_id=payload.get("chunk_id", str(pid)),
            payload=payload,
            dense_rank=dr,
            sparse_rank=sr,
            rrf_score=score,
        ))

    fused.sort(key=lambda c: c.rrf_score, reverse=True)
    return fused[:fused_limit]


def merge_candidate_lists(
    lists: list[list[RetrievedChunk]], fused_limit: int = FUSED_LIMIT,
) -> list[RetrievedChunk]:
    """
    Second-level RRF, this time fusing across QUERY VARIANTS rather than
    across dense/sparse retrieval within one query -- used for the Hinglish
    mitigation (docs/RAG_IMPLEMENTATION.md section 5.3): the original query
    and its Devanagari transliteration are each retrieved independently
    (each already an RRF-fused dense+sparse result), then merged here by
    each chunk's best rank across the two lists. Same RRF constant, same
    "fuse on rank, not raw score" principle as hybrid_search -- a chunk that
    ranks #1 for the transliterated query but wasn't retrieved at all for
    the original one still surfaces near the top, which is the whole point.
    """
    best_rank: dict[str, int] = {}
    chunk_by_id: dict[str, RetrievedChunk] = {}
    for candidates in lists:
        for i, c in enumerate(candidates):
            if c.chunk_id not in best_rank or i < best_rank[c.chunk_id]:
                best_rank[c.chunk_id] = i
                chunk_by_id[c.chunk_id] = c

    merged = sorted(chunk_by_id.values(), key=lambda c: best_rank[c.chunk_id])
    # Recompute rrf_score as the sum of 1/(k+rank+1) across every list the
    # chunk appeared in, so a chunk surfaced by BOTH query variants outranks
    # one found by only one -- consistent with hybrid_search's own fusion.
    rescored = []
    for c in merged:
        score = 0.0
        for candidates in lists:
            for i, cc in enumerate(candidates):
                if cc.chunk_id == c.chunk_id:
                    score += 1.0 / (RRF_K + i + 1)
                    break
        rescored.append((c, score))
    rescored.sort(key=lambda t: t[1], reverse=True)
    return [c for c, _score in rescored[:fused_limit]]
