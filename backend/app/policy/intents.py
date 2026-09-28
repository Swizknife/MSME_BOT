"""
Query understanding: language detection and intent classification.

Deliberately heuristic/regex-first rather than an LLM call, per the
efficiency thesis in docs/RAG_IMPLEMENTATION.md section 4 -- most of this
routing is cheap pattern matching (a calculation request, a greeting, a
grievance all have recognisable shapes), so there is no reason to spend an
LLM call, and the associated CPU latency, just to classify intent before
retrieval has even happened.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.okf import store as okf_store

DEVANAGARI_RE = re.compile(r"[ऀ-ॿ]")

# A small domain lexicon of romanised Hindi/Hinglish tokens, used to detect
# Hinglish queries so the retrieval layer can add a transliterated query
# variant (docs/RAG_IMPLEMENTATION.md section 5.3). Not exhaustive -- it
# only needs to catch common patterns, since a miss here just means the
# query is retrieved dense/sparse-only without the extra Devanagari variant,
# not that it fails outright.
HINGLISH_LEXICON = {
    "kitni", "kitna", "milegi", "milega", "subsidy", "udyami", "udyog",
    "karobar", "chahiye", "kaise", "kya", "hai", "hain", "yojana", "paisa",
    "paise", "sahayata", "lakh", "crore", "jile", "jila", "vyapar",
}

CALCULATION_PATTERNS = [
    re.compile(r"\bhow much (will|would|do) i (get|receive)\b", re.IGNORECASE),
    re.compile(r"\bmy investment (is|will be)\b", re.IGNORECASE),
    re.compile(r"\bcalculate\b", re.IGNORECASE),
    re.compile(r"\bमुझे कितन[ीा]\b"),
    re.compile(r"\bमेरा निवेश\b"),
]

GRIEVANCE_PATTERNS = [
    re.compile(r"\bcomplain(t|ing)?\b", re.IGNORECASE),
    re.compile(r"\bgrievance\b", re.IGNORECASE),
    re.compile(r"\bnot (received|working|responding)\b", re.IGNORECASE),
    re.compile(r"\bशिकायत\b"),
]

GREETING_PATTERNS = [
    re.compile(r"^\s*(hi|hello|hey|namaste|namaskar)\b", re.IGNORECASE),
]

# --------------------------------------------------------------------------
# OKF routing (docs/OKF_RAG_IMPLEMENTATION.md section 5): a second
# classification dimension alongside `intent`, deciding whether a question
# can be answered from a structured OKF record alone (no retrieval, no LLM),
# needs the full RAG pipeline, or needs both -- the exact figure from OKF
# plus RAG-retrieved narrative/conditions around it.
# --------------------------------------------------------------------------

# A short, single-fact lookup shape ("what/how much/rate/cap ..."), reused
# from the same intuition as chat.py's Tier-2 _LOOKUP_HINTS: these are the
# queries a direct structured answer serves well.
_LOOKUP_HINTS = re.compile(
    r"\b(what|how much|rate|cap|percentage|kitn[iā]|kya hai|कितन[ीा]|क्या है)\b", re.IGNORECASE
)

# Explanatory/conditional language means the user wants reasoning or
# surrounding conditions, not just a number -- routes to hybrid (OKF figure
# + full RAG narrative) rather than a bare OKF template answer.
EXPLANATORY_PATTERNS = [
    re.compile(r"\bwhy\b", re.IGNORECASE),
    re.compile(r"\bexplain\b", re.IGNORECASE),
    re.compile(r"\bhow does\b", re.IGNORECASE),
    re.compile(r"\bwhat condition", re.IGNORECASE),
    re.compile(r"\beligib(le|ility)\b", re.IGNORECASE),
    re.compile(r"\bक्यों\b"),
    re.compile(r"\bशर्त"),
]


@dataclass
class QueryUnderstanding:
    language: str  # "en" | "hi" | "hinglish"
    intent: str  # "policy_qa" | "greeting" | "out_of_scope" | "calculation_request" | "grievance"
    is_hinglish: bool
    retrieval_mode: str = "rag_narrative"  # "okf_lookup" | "rag_narrative" | "hybrid"
    okf_matches: list[str] = field(default_factory=list)  # matched incentive_ids
    okf_category: str | None = None  # "micro" | "small" | "medium" | None


def detect_language(text: str) -> str:
    if DEVANAGARI_RE.search(text):
        return "hi"
    tokens = re.findall(r"[a-zA-Z]+", text.lower())
    hinglish_hits = sum(1 for t in tokens if t in HINGLISH_LEXICON)
    if tokens and hinglish_hits / len(tokens) >= 0.15:
        return "hinglish"
    return "en"


def classify_intent(text: str) -> str:
    for pat in GREETING_PATTERNS:
        if pat.search(text):
            return "greeting"
    for pat in GRIEVANCE_PATTERNS:
        if pat.search(text):
            return "grievance"
    for pat in CALCULATION_PATTERNS:
        if pat.search(text):
            return "calculation_request"
    return "policy_qa"


def _is_explanatory(text: str) -> bool:
    return any(pat.search(text) for pat in EXPLANATORY_PATTERNS)


def classify_retrieval_mode(text: str, intent: str) -> tuple[str, list[str], str | None]:
    """Returns (retrieval_mode, matched incentive_ids, detected category).

    Only `policy_qa` questions are eligible for the OKF-only path.
    `calculation_request` and `grievance` already have dedicated, designed
    response paths (D2's explain-only routing; the grievance helpline
    routing) that must not be bypassed by a structured-lookup shortcut --
    an OKF template answer skips the calculation_request disclaimer and the
    grievance acknowledgement, both of which are policy-mandated text.

    Falls through to "rag_narrative" whenever the OKF store has nothing to
    route against (compiler hasn't run) -- see okf_store.is_available().
    """
    if intent != "policy_qa" or not okf_store.is_available():
        return "rag_narrative", [], None

    matches = okf_store.resolve_incentives(text)
    if not matches:
        return "rag_narrative", [], None

    category = okf_store.detect_category(text)
    explanatory = _is_explanatory(text)
    lookup_shaped = bool(_LOOKUP_HINTS.search(text))

    if explanatory:
        return "hybrid", matches, category
    if category and lookup_shaped:
        return "okf_lookup", matches, category
    # An incentive was named but without a category or a lookup shape
    # (e.g. "tell me about capital subsidy") -- OKF alone can't answer for
    # a specific category, and it isn't clearly explanatory either, so give
    # the full RAG narrative rather than guessing a category.
    return "hybrid", matches, category


def understand(text: str) -> QueryUnderstanding:
    lang = detect_language(text)
    intent = classify_intent(text)
    mode, matches, category = classify_retrieval_mode(text, intent)
    return QueryUnderstanding(
        language=lang, intent=intent, is_hinglish=(lang == "hinglish"),
        retrieval_mode=mode, okf_matches=matches, okf_category=category,
    )


CALCULATION_RESPONSE_EN = (
    "This assistant does not calculate individual entitlements -- it explains what the draft "
    "policy states. Based on the applicable rate and cap shown above, please contact your "
    "District Industries Centre (DIC) or the MSME helpline for a specific assessment of your "
    "case."
)
CALCULATION_RESPONSE_HI = (
    "यह सहायक व्यक्तिगत पात्रता की गणना नहीं करता -- यह केवल प्रारूप नीति में जो लिखा है वह बताता है। "
    "ऊपर दी गई लागू दर और सीमा के आधार पर, अपने विशेष मामले के आकलन के लिए कृपया अपने ज़िला उद्योग केंद्र "
    "(DIC) या एमएसएमई हेल्पलाइन से संपर्क करें।"
)

GRIEVANCE_RESPONSE_EN = (
    "This policy establishes a dedicated helpline and this chatbot as an entry point for MSME "
    "grievances (section 7.1). Please describe your issue and it will be logged; for urgent "
    "matters, contact your District Industries Centre (DIC) directly."
)
GRIEVANCE_RESPONSE_HI = (
    "यह नीति एमएसएमई शिकायतों के लिए एक समर्पित हेल्पलाइन और यह चैटबॉट प्रवेश बिंदु के रूप में स्थापित करती है "
    "(धारा 7.1)। कृपया अपनी समस्या बताएं, इसे दर्ज किया जाएगा; तत्काल मामलों के लिए, सीधे अपने ज़िला उद्योग "
    "केंद्र (DIC) से संपर्क करें।"
)
