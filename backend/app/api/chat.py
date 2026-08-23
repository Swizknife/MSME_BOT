"""
The tiered response ladder (D11, docs/RAG_IMPLEMENTATION.md section 4):
most answers should never reach the LLM.

  Tier 0 (cache)      exact-match query cache, in-memory for now
  Tier 1 (abstain)    Coverage Gate says no confident match -> no LLM call
  Tier 2 (extractive) a single dominant, self-contained chunk answers the
                       query -> template + verbatim quote + citation, no LLM
  Tier 3 (synthesis)  everything else -> full LLM generation with guards

Tier 2 is not a degraded answer for this product: D2 says "explain only,
quote as written," so a verbatim quote with its citation is exactly the
mandated answer, and it is perfectly grounded by construction (the Numeric
Guard passes trivially since the figures ARE the source).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from fastapi import APIRouter
from pydantic import BaseModel

from app.generation.guards import ambiguity_disclosure_guard, citation_validity_guard, numeric_guard
from app.generation.llm_provider import ChatMessage, chat_completion
from app.generation.prompts import SYSTEM_PROMPT, build_user_message
from app.policy import ambiguity_register
from app.policy.intents import (
    CALCULATION_RESPONSE_EN,
    CALCULATION_RESPONSE_HI,
    GRIEVANCE_RESPONSE_EN,
    GRIEVANCE_RESPONSE_HI,
    understand,
)
from app.retrieval.coverage_gate import abstain_message
from app.retrieval.pipeline import retrieve, top_chunk_suggestions

router = APIRouter()

# Single-chunk-answers-it-cleanly intent shapes -- short, single-fact
# lookups are the common case this policy corpus serves well.
_LOOKUP_HINTS = re.compile(
    r"\b(what|how much|rate|cap|percentage|kitn[iā]|kya hai|कितन[ीा]|क्या है)\b", re.IGNORECASE
)

_query_cache: dict[str, dict] = {}  # Tier 0 -- in-memory; TODO persist to Postgres


class ChatRequest(BaseModel):
    message: str
    conversation_id: str | None = None


class Source(BaseModel):
    tag: str
    clause_path: str
    page_start: int
    page_end: int
    text: str


class ChatResponse(BaseModel):
    answer: str
    tier: str  # "cache" | "abstain" | "extractive" | "synthesis"
    language: str
    sources: list[Source]
    low_confidence: bool = False
    ambiguity_ids: list[str] = []


def _is_dominant_lookup(reranked, gate) -> bool:
    if len(reranked) < 1:
        return False
    if gate.action != "answer":
        return False
    if len(reranked) == 1:
        return True
    top_score = reranked[0][1]
    second_score = reranked[1][1]
    # "Dominant" = clearly ahead of the runner-up, not just barely first.
    return (top_score - second_score) > 0.15


def _extractive_answer(query_lang: str, chunk_payload: dict) -> str:
    text = chunk_payload["text"]
    # Strip the leading "[MSME Policy ... > p.N]" breadcrumb -- it's for
    # citation display, not for the answer body.
    body = re.sub(r"^\[.*?\]\n\n", "", text, flags=re.DOTALL)
    clause_path = chunk_payload.get("clause_path", "")
    page = chunk_payload.get("page_start", "?")
    prefix = "According to the draft policy" if query_lang != "hi" else "प्रारूप नीति के अनुसार"
    return f"{prefix} ({clause_path}, p.{page}): {body}"


def _doc_order(reranked: list[tuple]) -> list[tuple]:
    """Order a reranked shortlist for presentation to the LLM: the single
    best-scored chunk stays first (so [S1] is always the LLM's primary,
    most-relevant citation), and everything else is sorted by document
    position (page, then clause path) behind it.

    Pure (page, clause_path) sorting was tried first and produced a real bug
    in end-to-end testing: an Ambiguity Register chunk's clause_path
    ("Ambiguity Register > AMB-05") sorts alphabetically before a policy
    clause's ("S7.9 > Item 1..."), so a tangential ambiguity note that
    happened to share a page with the actual answer landed as [S1] ahead of
    the capital-subsidy table entry that was the true best match -- and the
    LLM then cited [S1] as if it were the primary fact. Per
    docs/RAG_IMPLEMENTATION.md section 6, doc-ordering exists so score-order
    doesn't scramble a rate away from the section 9.1 conditions that govern
    it -- it was never meant to bury the actual best match under an
    alphabetical accident. Pinning the top match first fixes that while
    keeping the rest in document order for the same reason as before."""
    if not reranked:
        return []
    best, rest = reranked[0], reranked[1:]
    rest_sorted = sorted(
        rest,
        key=lambda t: (t[0].payload.get("page_start", 0), t[0].payload.get("clause_path", "")),
    )
    return [best, *rest_sorted]


def _make_sources(reranked) -> list[Source]:
    """Builds numbered [Sn] sources from an already-ordered chunk list --
    callers decide the order (document order for Tier 3 context, a single
    best-match chunk for Tier 2) since the tag numbering depends on it."""
    sources = []
    for i, (chunk, _score) in enumerate(reranked, start=1):
        p = chunk.payload
        sources.append(Source(
            tag=f"S{i}", clause_path=p.get("clause_path", ""),
            page_start=p.get("page_start", 0), page_end=p.get("page_end", 0),
            text=p.get("parent_text") or p.get("text", ""),
        ))
    return sources


def _collect_ambiguity_ids(reranked) -> list[str]:
    ids: list[str] = []
    for chunk, _score in reranked:
        for flag in chunk.payload.get("ambiguity_flags", []):
            if flag not in ids:
                ids.append(flag)
    return ids


@router.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    understanding = understand(req.message)
    lang = "hi" if understanding.language in ("hi",) else "en"

    if understanding.intent == "greeting":
        text = ("Hello! Ask me anything about the Bihar MSME Policy 2026 draft -- capital "
                "subsidy, payroll subsidy, district categories, and more."
                if lang == "en" else
                "नमस्ते! बिहार एमएसएमई नीति 2026 के प्रारूप के बारे में कुछ भी पूछें।")
        return ChatResponse(answer=text, tier="cache", language=lang, sources=[])

    if understanding.intent == "grievance":
        text = GRIEVANCE_RESPONSE_EN if lang == "en" else GRIEVANCE_RESPONSE_HI
        return ChatResponse(answer=text, tier="cache", language=lang, sources=[])

    cache_key = f"{lang}:{req.message.strip().lower()}"
    if cache_key in _query_cache:
        cached = _query_cache[cache_key]
        return ChatResponse(**cached, tier="cache")

    result = retrieve(req.message, is_hinglish=understanding.is_hinglish)

    if result.gate.action == "abstain":
        suggestions = top_chunk_suggestions(result.reranked)
        text = abstain_message(lang, suggestions)
        return ChatResponse(answer=text, tier="abstain", language=lang, sources=[])

    low_confidence = result.gate.action == "answer_low_confidence"
    top6 = result.reranked[:6]
    ambiguity_ids = _collect_ambiguity_ids(top6)

    # --- Tier 2: extractive, no LLM call -------------------------------
    is_lookup = understanding.intent == "policy_qa" and bool(_LOOKUP_HINTS.search(req.message))
    if is_lookup and _is_dominant_lookup(result.reranked, result.gate) and understanding.intent != "calculation_request":
        top_chunk, top_score = result.reranked[0]
        answer = _extractive_answer(lang, top_chunk.payload) + " [S1]"
        # Single source, built straight from the actual best-match chunk --
        # never assume it lines up positionally with a differently-ordered
        # sources list (that was the bug: reusing a doc-ordered sources[0]
        # here would show whichever chunk happens to have the earliest page,
        # not the chunk the answer was actually extracted from).
        resp = dict(answer=answer, language=lang, sources=_make_sources([(top_chunk, top_score)]),
                    low_confidence=low_confidence, ambiguity_ids=top_chunk.payload.get("ambiguity_flags", []))
        _query_cache[cache_key] = resp
        return ChatResponse(**resp, tier="extractive")

    # --- Tier 3: LLM synthesis -------------------------------------------
    # Document order for presentation to the LLM (and to the UI's citation
    # panel) -- see _doc_order's docstring. Retrieval ranking already did its
    # job selecting *which* 6 chunks matter; it has no further role here.
    sources = _make_sources(_doc_order(top6))
    source_dicts = [s.model_dump() for s in sources]
    user_msg = build_user_message(req.message, source_dicts)
    messages = [ChatMessage("system", SYSTEM_PROMPT), ChatMessage("user", user_msg)]

    answer = chat_completion(messages, stream=False)

    context_text = "\n".join(s.text for s in sources)
    ok_numeric, leaked = numeric_guard(answer, context_text)
    if not ok_numeric:
        answer = chat_completion(messages, stream=False)  # one retry
        ok_numeric, leaked = numeric_guard(answer, context_text)
    if not ok_numeric and sources:
        # deterministic fallback: verbatim quote of the top source
        answer = _extractive_answer(lang, result.reranked[0][0].payload) + " [S1]"

    ok_citations, _invalid = citation_validity_guard(answer, num_sources=len(sources))
    if not ok_citations and sources:
        answer = _extractive_answer(lang, result.reranked[0][0].payload) + " [S1]"

    ok_disclosure, missing_amb = ambiguity_disclosure_guard(answer, ambiguity_ids)
    if not ok_disclosure:
        disclosures = ambiguity_register.disclosures_for(missing_amb, lang)
        if disclosures:
            answer = answer.rstrip() + "\n\n" + "\n".join(disclosures)

    if understanding.intent == "calculation_request":
        answer = answer.rstrip() + "\n\n" + (CALCULATION_RESPONSE_EN if lang == "en" else CALCULATION_RESPONSE_HI)

    resp = dict(answer=answer, language=lang, sources=sources,
                low_confidence=low_confidence, ambiguity_ids=ambiguity_ids)
    _query_cache[cache_key] = resp
    return ChatResponse(**resp, tier="synthesis")
