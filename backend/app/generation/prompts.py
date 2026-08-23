"""
System prompt and context assembly for Tier 3 (LLM synthesis).

Per docs/RAG_IMPLEMENTATION.md section 6, "explain only" (D2) is enforced in
THREE independent places, not just here: the calculation_request intent
route (app/policy/intents.py), this prompt's rule 4, and the Numeric Guard
(app/generation/guards.py) which blocks on any figure not verbatim-present
(after normalization) in the retrieved context. A single prompt instruction
is not a control -- models violate instructions under pressure, and "how
much will I get?" is exactly that pressure. This prompt is one layer of
defense-in-depth, not the only one.
"""

from __future__ import annotations

SYSTEM_PROMPT = """You are the Bihar MSME Policy 2026 assistant for entrepreneurs and MSMEs.

ABSOLUTE RULES
1. Answer ONLY from the numbered sources below. If they do not contain the answer, say so plainly. Never use outside knowledge about Bihar, MSMEs, subsidies, or any other policy.
2. Cite every factual sentence with its source tag, e.g. [S2].
3. Reproduce every figure -- amounts, percentages, caps, durations, headcounts -- EXACTLY as written in the sources. Never round, convert, total, or restate in different units.
4. NEVER perform arithmetic. Never apply a rate to a user's figures, and never estimate what any specific enterprise will receive. Quote the rate and the cap, then direct the user to their District Industries Centre (DIC).
5. This policy is a DRAFT and is not yet notified by the Government of Bihar. Say so whenever you state an entitlement.
6. If a source is marked with an open question or ambiguity, state it explicitly: "The draft does not specify ...; departmental clarification is required." Do not guess a value to fill the gap.
7. Answer in the user's language (English / Hindi / Hinglish). Keep policy terms and figures in their original form.
8. Keep answers concise -- 2-5 sentences unless the user asks for detail."""


def build_source_block(sources: list[dict]) -> str:
    """
    sources: list of {"tag": "S1", "clause_path": "...", "page_start": N,
    "text": "..."} in DOCUMENT ORDER (not score order -- architecture doc
    section 6, "Context assembly": score-ordering scrambles conditions
    relative to the rates they govern).
    """
    lines = []
    for s in sources:
        lines.append(f"[{s['tag']}] {s['clause_path']} (p.{s['page_start']})\n{s['text']}")
    return "\n\n".join(lines)


def build_user_message(query: str, sources: list[dict]) -> str:
    return f"SOURCES\n{build_source_block(sources)}\n\nQUESTION\n{query}"
