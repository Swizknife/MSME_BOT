"""POST /api/chat -- thin dispatcher.

Handles what doesn't belong to any one mode (greeting/grievance/cache,
language detection, timing) and then hands off to `evidence.build()` and
`ladder.run_ladder()`. The tiered ladder itself lives in `ladder.py`; what
"rag"/"okf"/"okf_rag" mean in terms of what data an answer may draw from
lives in `evidence.py`. See those modules' docstrings for the architecture;
this file is intentionally short.
"""

from __future__ import annotations

import time
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from app.api import evidence as evidence_mod
from app.api.ladder import run_ladder, try_tier1_lookup
from app.policy.intents import GRIEVANCE_RESPONSE_EN, GRIEVANCE_RESPONSE_HI, understand

router = APIRouter()

Mode = Literal["rag", "okf", "okf_rag"]

_query_cache: dict[str, dict] = {}  # Tier 0 -- in-memory; TODO persist to Postgres


class ChatRequest(BaseModel):
    message: str
    conversation_id: str | None = None
    # Which architecture answers this query. Defaults to the full system --
    # "rag" and "okf" exist so the same question can be compared across
    # architectures, which is the whole point of the frontend toggle this
    # field exists for.
    mode: Mode = "okf_rag"


class Source(BaseModel):
    tag: str
    clause_path: str
    page_start: int
    page_end: int
    text: str
    # Which layer produced this citation. "vector" for anything found by
    # embedding search, "okf" for a directly-injected structured record,
    # "graph" for a chunk the concept-graph traversal named. A rag-mode
    # answer's sources are always "vector" -- that IS what "no structured
    # layer" means, made checkable rather than just claimed.
    origin: Literal["vector", "okf", "graph"] = "vector"


class GraphNodeRef(BaseModel):
    """One node the OKF graph traversal reached, for the UI's "how this
    answer was assembled" panel. Empty in rag mode, and empty in any mode
    whenever the graph walk matched nothing."""

    concept_id: str
    type: str
    title: str
    hop: int
    via: str | None
    trust: str


class ChatResponse(BaseModel):
    answer: str
    tier: str  # "cache" | "okf_lookup" | "graph" | "abstain" | "extractive" | "synthesis"
    mode: Mode = "okf_rag"
    language: str
    sources: list[Source]
    low_confidence: bool = False
    ambiguity_ids: list[str] = []
    # Router's classification of what kind of query this was -- surfaced so
    # the UI/eval harness can show WHY a mode behaved the way it did, not
    # just what it answered.
    retrieval_mode: str = "rag_narrative"
    graph_path: list[GraphNodeRef] = []
    graph_missing: list[str] = []
    timing_ms: int | None = None


@router.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    started = time.perf_counter()
    understanding = understand(req.message)
    lang = "hi" if understanding.language in ("hi",) else "en"

    if understanding.intent == "greeting":
        text = ("Hello! Ask me anything about the Bihar MSME Policy 2026 draft -- capital "
                "subsidy, payroll subsidy, district categories, and more."
                if lang == "en" else
                "नमस्ते! बिहार एमएसएमई नीति 2026 के प्रारूप के बारे में कुछ भी पूछें।")
        return ChatResponse(answer=text, tier="cache", mode=req.mode, language=lang, sources=[],
                             timing_ms=_elapsed_ms(started))

    if understanding.intent == "grievance":
        text = GRIEVANCE_RESPONSE_EN if lang == "en" else GRIEVANCE_RESPONSE_HI
        return ChatResponse(answer=text, tier="cache", mode=req.mode, language=lang, sources=[],
                             timing_ms=_elapsed_ms(started))

    # Mode is part of the cache key. With a mode-blind key, flipping the
    # toggle and re-asking the same question returns the OTHER mode's
    # cached answer, which makes the entire comparison the toggle exists
    # for a lie -- the demonstrated failure mode, not a hypothetical one.
    cache_key = f"{req.mode}:{lang}:{req.message.strip().lower()}"
    if cache_key in _query_cache:
        cached = dict(_query_cache[cache_key])
        cached["mode"] = req.mode
        return ChatResponse(**cached, tier="cache", timing_ms=_elapsed_ms(started))

    understanding = evidence_mod.normalize_understanding(req.mode, understanding)

    # Tier 1 is checked BEFORE evidence is built, not after: evidence.build()
    # calls retrieve() for rag/okf_rag mode unconditionally (embedding +
    # hybrid search + rerank), and Tier 1's entire reason to exist is
    # answering a single-fact lookup without paying that cost -- measured at
    # 0.08s vs 27.9s for the equivalent RAG path. Checking it only after
    # evidence exists would erase that property for every lookup query.
    tier1 = try_tier1_lookup(understanding, req.mode)
    if tier1:
        _query_cache[cache_key] = tier1
        return ChatResponse(**tier1, tier="okf_lookup", timing_ms=_elapsed_ms(started))

    built = evidence_mod.build(req.mode, req.message, understanding)

    response = run_ladder(req, understanding, built, cache_key, _query_cache)
    response.timing_ms = _elapsed_ms(started)
    return response


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)
