"""
The tiered response ladder (D11, docs/RAG_IMPLEMENTATION.md section 4, OKF
extension per docs/OKF_RAG_IMPLEMENTATION.md section 5): most answers
should never reach the LLM, and the ones that do should not have to
re-derive a fact the OKF layer already holds structured and verified.

  Tier 0 (cache)       exact-match query cache, in-memory for now
  Tier 1 (okf_lookup)  the router resolved the query to exactly one OKF
                        incentive+category -> deterministic template answer
                        from the structured record. No retrieval, no
                        rerank, no Coverage Gate, no LLM call: a lookup is a
                        binary "record found or not," not a confidence
                        question. Falls through to the full pipeline if the
                        resolved slot has no rate on record.
  Tier 2 (abstain)     Coverage Gate says no confident match -> no LLM call
  Tier 3 (extractive)  a single dominant, self-contained chunk answers the
                        query -> template + verbatim quote + citation, no LLM
  Tier 4 (synthesis)   everything else -> full LLM generation with guards.
                        If the router additionally resolved a single OKF
                        incentive+category (retrieval_mode "hybrid"), that
                        record's rate_text is injected as the LLM's [S1]
                        source ahead of the retrieved narrative chunks, and
                        the generated answer's figures are checked against
                        it post-hoc (okf_consistency_guard) in addition to
                        the existing context-containment check.

Tier 3 is not a degraded answer for this product: D2 says "explain only,
quote as written," so a verbatim quote with its citation is exactly the
mandated answer, and it is perfectly grounded by construction (the Numeric
Guard passes trivially since the figures ARE the source). The same is true
of Tier 1, one level more so: the figures don't just pass a containment
check, they ARE the OKF record.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from fastapi import APIRouter
from pydantic import BaseModel

from app.generation.guards import (
    ambiguity_disclosure_guard,
    citation_validity_guard,
    numeric_guard,
    okf_consistency_guard,
)
from app.generation.llm_provider import ChatMessage, chat_completion
from app.generation.prompts import SYSTEM_PROMPT, build_user_message
from app.okf import store as okf_store
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
    tier: str  # "cache" | "okf_lookup" | "abstain" | "extractive" | "synthesis"
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
    # Strip the leading "[<doc name> ... > p.N]" breadcrumb -- it's for
    # citation display, not for the answer body.
    body = re.sub(r"^\[.*?\]\n\n", "", text, flags=re.DOTALL)
    clause_path = chunk_payload.get("clause_path", "")
    # `or` not `.get(key, "?")`: a web-sourced chunk carries page_start as
    # an explicit None (no PDF page number), which the key-absent-only
    # default doesn't catch -- caught by a real crash testing a CGTMSE
    # query where this exact pattern (elsewhere in this file) produced a
    # Pydantic validation error; here it would have silently printed
    # "p.None" to a user instead of crashing, which is worse, not better.
    page = chunk_payload.get("page_start") or None
    page_part = f", p.{page}" if page else ""

    # "According to the draft policy" is only true for the one draft
    # source this text was originally written for. A second, non-draft,
    # non-Bihar source (CGTMSE, TReDS, MSME Samadhaan) needs its own name,
    # not a blanket claim that every chunk is "the draft policy" --
    # generalizing this was part of the same citation-contamination class
    # of bug fixed in okf/chunk_from_okf.py's doc_label().
    scheme_id = chunk_payload.get("scheme_id")
    if scheme_id == "BIHAR_MSME_2026" or not scheme_id:
        prefix = "According to the draft policy" if query_lang != "hi" else "प्रारूप नीति के अनुसार"
    else:
        scheme = okf_store.get_scheme(scheme_id)
        doc_name = (scheme or {}).get("name") or (scheme or {}).get("short_name") or scheme_id
        prefix = f"According to {doc_name}" if query_lang != "hi" else f"{doc_name} के अनुसार"

    return f"{prefix} ({clause_path}{page_part}): {body}"


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
    # `or 0`, not `.get(key, 0)`: a web-sourced chunk carries page_start as
    # an explicit None. Left as `.get(key, 0)` this is a latent crash, not
    # just an ugly default -- sorted() compares tuples element-by-element,
    # and Python raises TypeError comparing None to an int the moment one
    # page-less chunk and one paginated chunk land in the same top6 (which
    # a mixed-source retrieval set will now routinely produce).
    rest_sorted = sorted(
        rest,
        key=lambda t: (t[0].payload.get("page_start") or 0, t[0].payload.get("clause_path", "")),
    )
    return [best, *rest_sorted]


def _clause_path_with_source_prefix(payload: dict) -> str:
    """Multi-source citation format (docs/OKF_RAG_IMPLEMENTATION.md section
    5): once more than one source is indexed, "S7.9 > Item 1" is ambiguous
    about which document it's in. Prefix with the scheme's short_name when
    the chunk carries one (every OKF-emitted chunk does; nothing before
    Phase 1 did, so this degrades gracefully for any leftover legacy
    payload that lacks scheme_id)."""
    clause_path = payload.get("clause_path", "")
    scheme_id = payload.get("scheme_id")
    if not scheme_id:
        return clause_path
    short_name = okf_store.scheme_short_name(scheme_id)
    return f"{short_name} > {clause_path}" if clause_path else short_name


def _make_sources(reranked) -> list[Source]:
    """Builds numbered [Sn] sources from an already-ordered chunk list --
    callers decide the order (document order for Tier 4 context, a single
    best-match chunk for Tier 3) since the tag numbering depends on it."""
    sources = []
    for i, (chunk, _score) in enumerate(reranked, start=1):
        p = chunk.payload
        sources.append(Source(
            tag=f"S{i}", clause_path=_clause_path_with_source_prefix(p),
            # `.get(key, 0)` only defaults when the key is ABSENT -- every
            # chunk carries the key with an explicit None for a web-sourced
            # fact with no PDF page number (found by a real crash testing
            # a CGTMSE query: page_start=None reached Source's required
            # int field and Pydantic raised). `or 0` catches both cases.
            page_start=p.get("page_start") or 0, page_end=p.get("page_end") or 0,
            text=p.get("parent_text") or p.get("text", ""),
        ))
    return sources


def _retag(sources: list[Source]) -> list[Source]:
    """Re-numbers [Sn] tags in place order. Needed whenever a source is
    prepended after _make_sources already assigned tags (the hybrid path
    injects an OKF ground-truth source ahead of the retrieved chunks)."""
    return [s.model_copy(update={"tag": f"S{i}"}) for i, s in enumerate(sources, start=1)]


def _okf_ground_truth_rate(incentive: dict, category: str | None) -> dict | None:
    """The rate the router's resolved category should quote. If no category
    was detected but the incentive's terms don't vary by category anyway,
    any category's rate is representative and safe to use -- for a varying
    incentive with no detected category, there is no single correct slot to
    quote, so this returns None and callers skip OKF injection entirely
    rather than guess."""
    if category:
        return okf_store.rate_for_category(incentive, category)
    if not incentive.get("varies_by_category") and incentive.get("category_rates"):
        return incentive["category_rates"][0]
    return None


def _okf_citation_source(incentive_id: str, category: str | None) -> tuple[Source, dict | None] | None:
    """The OKF record rendered as a citable Source (tag is a placeholder;
    callers must _retag after combining with other sources), plus the
    ground-truth rate dict for the consistency guard, or None if the
    incentive doesn't exist or has no quotable rate for this slot."""
    incentive = okf_store.get_incentive(incentive_id)
    if not incentive:
        return None
    rate = _okf_ground_truth_rate(incentive, category)
    if not rate:
        return None
    scheme_id = incentive["scheme_id"]
    short_name = okf_store.scheme_short_name(scheme_id)
    src = incentive.get("source", {}) or {}
    page = src.get("page_start") or 0
    item_no = incentive.get("item_no") or ""
    item_part = f"Item {item_no} {incentive['name']}" if item_no else incentive["name"]
    cat = rate.get("enterprise_category")
    cat_part = f" > {cat.capitalize()}" if cat and cat != "other" else ""
    clause_path = f"{short_name} > {item_part}{cat_part} [OKF]"
    return (
        Source(tag="S0", clause_path=clause_path, page_start=page, page_end=page, text=rate["rate_text"]),
        rate,
    )


def _okf_lookup_answer(lang: str, incentive_id: str, category: str) -> dict | None:
    """Tier 1: a deterministic template answer straight from the OKF
    record, with no retrieval and no LLM call. Returns None if the record
    or the specific category's rate doesn't exist -- callers must fall
    through to the full pipeline rather than answer nothing, since
    retrieval_mode is a routing hint, not a guarantee the data exists.

    IMPORTANT: an ambiguity flag on `incentive.ambiguity_flags` does not
    necessarily concern the SPECIFIC category/slot this answer quotes --
    e.g. Capital Subsidy (item 1) carries AMB-20 (severity=blocking)
    because Araria district has no defined rate, but that says nothing
    about a Micro/Region-A answer, which has a perfectly good rate on
    record. Blocking district/definitional ambiguities like that must
    never suppress an answer for a slot they don't actually affect --
    early testing caught exactly this: a plain "capital subsidy for a
    micro enterprise" question was answered with the Araria disclosure
    text instead of the rate, because every ambiguity attached to the
    incentive was treated as blocking the whole thing.
    The one case that genuinely has nothing to quote is when the SOURCE
    ITSELF states no rate for this incentive at all (e.g. the Revival
    Package: its rate_text literally reads "...NO RATE/AMOUNT SPECIFIED IN
    SOURCE" for every category) -- migrate_policy_data.py already marks
    that as `status: "rate_unstated"` at migration time, from the same
    AMB-09/AMB-03-style missing_rate findings. That field, not "does any
    attached ambiguity happen to be severity=blocking", is what this
    checks. All attached ambiguities (blocking or advisory) are disclosed
    after the rate either way -- exactly what the existing Tier 4
    ambiguity_disclosure_guard already does for the RAG path, unchanged.
    """
    incentive = okf_store.get_incentive(incentive_id)
    if not incentive:
        return None
    rate = okf_store.rate_for_category(incentive, category)
    if not rate:
        return None

    amb_records = [okf_store.get_ambiguity(a) for a in incentive.get("ambiguity_flags", [])]
    amb_records = [a for a in amb_records if a]
    local_ids = [a.get("local_id") or a["id"] for a in amb_records]

    source, _ = _okf_citation_source(incentive_id, category)
    source = source.model_copy(update={"tag": "S1"})

    if incentive.get("status") == "rate_unstated":
        rate_gap = next((a for a in amb_records if a.get("issue_type") == "missing_rate"), None)
        if rate_gap:
            text = rate_gap["public_disclosure_hi"] if lang == "hi" else rate_gap["public_disclosure_en"]
            return {"answer": f"{text} [S1]", "source": source, "ambiguity_ids": local_ids}

    if lang == "hi":
        answer = f"{incentive['name']} ({category} उद्यम के लिए): {rate['rate_text']}। [S1]"
    else:
        answer = f"{incentive['name']} for a {category} enterprise: {rate['rate_text']}. [S1]"

    if amb_records:
        disclosures = [
            (a["public_disclosure_hi"] if lang == "hi" else a["public_disclosure_en"]) for a in amb_records
        ]
        answer = answer + "\n\n" + "\n".join(disclosures)

    return {"answer": answer, "source": source, "ambiguity_ids": local_ids}


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

    # --- Tier 1: OKF deterministic lookup ---------------------------------
    # Only when the router resolved exactly one incentive: with more than
    # one match there is no safe way to pick which the user meant, so that
    # ambiguity is left to retrieval + the LLM's judgement instead of a
    # template guessing wrong. A resolved-but-dataless slot (rate not on
    # record) falls through to the full pipeline below rather than
    # answering nothing.
    if (understanding.retrieval_mode == "okf_lookup"
            and len(understanding.okf_matches) == 1
            and understanding.okf_category):
        okf_answer = _okf_lookup_answer(lang, understanding.okf_matches[0], understanding.okf_category)
        if okf_answer:
            resp = dict(answer=okf_answer["answer"], language=lang, sources=[okf_answer["source"]],
                        low_confidence=False, ambiguity_ids=okf_answer["ambiguity_ids"])
            _query_cache[cache_key] = resp
            return ChatResponse(**resp, tier="okf_lookup")

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

    # --- Tier 4: LLM synthesis ---------------------------------------------
    # Document order for presentation to the LLM (and to the UI's citation
    # panel) -- see _doc_order's docstring. Retrieval ranking already did its
    # job selecting *which* 6 chunks matter; it has no further role here.
    sources = _make_sources(_doc_order(top6))

    # Hybrid injection (docs/OKF_RAG_IMPLEMENTATION.md section 5): the
    # router resolved a single OKF incentive+category alongside the
    # explanatory language that sent this query to full synthesis. Inject
    # its record as [S1], ahead of the retrieved narrative, so the LLM has
    # the authoritative figure and cites it -- and so numeric_guard's
    # context (built from these same sources) already contains it.
    okf_ground_truth = None
    if understanding.retrieval_mode == "hybrid" and len(understanding.okf_matches) == 1:
        injected = _okf_citation_source(understanding.okf_matches[0], understanding.okf_category)
        if injected:
            gt_source, okf_ground_truth = injected
            sources = _retag([gt_source, *sources])
            incentive = okf_store.get_incentive(understanding.okf_matches[0])
            for a in incentive.get("ambiguity_flags", []) if incentive else []:
                amb = okf_store.get_ambiguity(a)
                local_id = (amb.get("local_id") or a) if amb else a
                if local_id not in ambiguity_ids:
                    ambiguity_ids.append(local_id)

    source_dicts = [s.model_dump() for s in sources]
    user_msg = build_user_message(req.message, source_dicts)
    messages = [ChatMessage("system", SYSTEM_PROMPT), ChatMessage("user", user_msg)]

    answer = chat_completion(messages, stream=False)
    answer_is_synthesized = True

    context_text = "\n".join(s.text for s in sources)
    ok_numeric, leaked = numeric_guard(answer, context_text)
    if not ok_numeric:
        answer = chat_completion(messages, stream=False)  # one retry
        ok_numeric, leaked = numeric_guard(answer, context_text)
    if not ok_numeric and sources:
        # deterministic fallback: verbatim quote of the top source
        answer = _extractive_answer(lang, result.reranked[0][0].payload) + " [S1]"
        answer_is_synthesized = False

    ok_citations, _invalid = citation_validity_guard(answer, num_sources=len(sources))
    if not ok_citations and sources:
        answer = _extractive_answer(lang, result.reranked[0][0].payload) + " [S1]"
        answer_is_synthesized = False

    # OKF consistency guard (docs/OKF_RAG_IMPLEMENTATION.md section 5):
    # numeric_guard only checks that a figure appears SOMEWHERE in the
    # shown context, which a table-atom's multi-category parent_text
    # satisfies trivially even if the LLM attributes the wrong category's
    # rate to this answer. This checks the figure against the ONE resolved
    # ground-truth slot specifically. Skipped once a guard above has
    # already replaced the answer with a verbatim OKF/chunk quote -- that
    # text is grounded by construction and re-checking it would be
    # checking the guard's own fallback against itself.
    if answer_is_synthesized and okf_ground_truth:
        ok_consistent, mismatched = okf_consistency_guard(answer, okf_ground_truth["rate_text"])
        if not ok_consistent:
            fallback = _okf_lookup_answer(lang, understanding.okf_matches[0], understanding.okf_category)
            if fallback:
                answer = fallback["answer"]

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
