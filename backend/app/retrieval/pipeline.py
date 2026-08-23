"""
End-to-end retrieval: encode -> hybrid search -> rerank -> gate.
Generation (Tier 3) and the extractive path (Tier 2) live in app/api/chat.py,
which is the tiered-ladder orchestrator; this module only answers "what are
the relevant chunks, and are we confident enough to use them at all."
"""

from __future__ import annotations

from dataclasses import dataclass

from app.retrieval.coverage_gate import GateDecision, decide
from app.retrieval.embedder import encode_query
from app.retrieval.hinglish import transliterate_to_devanagari
from app.retrieval.hybrid import RetrievedChunk, hybrid_search, merge_candidate_lists
from app.retrieval.rerank import rerank


@dataclass
class RetrievalResult:
    query: str
    reranked: list[tuple[RetrievedChunk, float]]  # sorted, best first
    gate: GateDecision


def retrieve(query: str, query_filter=None, is_hinglish: bool = False) -> RetrievalResult:
    dense_vec, sparse_weights = encode_query(query)
    candidates = hybrid_search(dense_vec, sparse_weights, query_filter=query_filter)

    # Hinglish mitigation (architecture doc section 5.3): retrieve the
    # Devanagari transliteration too and merge, rather than relying on
    # BGE-M3 to cross-lingually match romanised Hindi as well as it matches
    # the real thing (it doesn't -- see hinglish.py's docstring). The
    # original query's candidates are kept either way, so this can only add
    # recall, never remove a hit the original query already found.
    if is_hinglish:
        translit = transliterate_to_devanagari(query)
        if translit:
            t_dense, t_sparse = encode_query(translit)
            translit_candidates = hybrid_search(t_dense, t_sparse, query_filter=query_filter)
            candidates = merge_candidate_lists([candidates, translit_candidates])

    reranked = rerank(query, candidates)
    gate = decide(reranked)
    return RetrievalResult(query=query, reranked=reranked, gate=gate)


def top_chunk_suggestions(reranked: list[tuple[RetrievedChunk, float]], n: int = 3) -> list[str]:
    """Used by the Coverage Gate's abstain message to suggest in-scope
    topics -- drawn from whatever DID retrieve, even below threshold,
    rather than a static list."""
    seen = []
    for chunk, _score in reranked:
        path = chunk.payload.get("clause_path", "")
        top_level = path.split(">")[0].strip() if path else None
        if top_level and top_level not in seen:
            seen.append(top_level)
        if len(seen) >= n:
            break
    return seen
