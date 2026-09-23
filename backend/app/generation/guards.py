"""
Post-generation guards. Per docs/RAG_IMPLEMENTATION.md section 6:
  - Only deterministic checks may BLOCK a response (citation validity,
    Numeric Guard, ambiguity disclosure). An LLM-judge groundedness check
    would add tens of seconds on CPU and is run async, post-hoc, into the
    admin review queue instead -- never on the blocking path.

THE NUMERIC GUARD (the strongest single control, and the mechanical
enforcement of "explain only, no computed amounts" -- D2):
Every monetary amount, percentage, year count and headcount in a generated
answer must appear, after normalization, in the retrieved context it was
generated from. Anything that doesn't is by construction either invented or
computed, both forbidden.

An earlier draft of this guard demanded VERBATIM matching, which silently
conflicted with the separate requirement that Hindi and English answers be
equally well-supported: a Hindi answer writing "25 lakh" using Devanagari
digits (२५ लाख) or number-words (पच्चीस लाख) matches nothing in an
English-only source verbatim. This module normalizes BOTH sides (Devanagari
digits -> Latin, lakh/crore spelled multiple ways including the source's own
"croe" typo, rupee symbols unified) before the containment check, so a
correctly-translated Hindi figure passes and a truly invented one still
fails.
"""

from __future__ import annotations

import re

DEVANAGARI_DIGITS = "०१२३४५६७८९"
LATIN_DIGITS = "0123456789"
_DEVANAGARI_TO_LATIN = str.maketrans(DEVANAGARI_DIGITS, LATIN_DIGITS)

# Unit synonyms actually seen in the source (including its own typos, which
# must normalize to the SAME bucket as the correct spelling so a correct
# quotation of the source's own "croe" is never rejected as unsupported).
_UNIT_SYNONYMS = [
    (re.compile(r"\bcroe\b", re.IGNORECASE), "crore"),
    (re.compile(r"\bcror(?:es)?\b", re.IGNORECASE), "crore"),
    (re.compile(r"करोड़?", re.IGNORECASE), "crore"),
    (re.compile(r"\blakhs?\b", re.IGNORECASE), "lakh"),
    (re.compile(r"लाख", re.IGNORECASE), "lakh"),
    (re.compile(r"₹|Rs\.?,?\s?|INR\b", re.IGNORECASE), "RUPEE "),
]

_WS_RE = re.compile(r"\s+")

# Matches a figure: an optional rupee marker, digits (with , or . as
# separators), an optional unit word, or a bare percentage.
FIGURE_PATTERN = re.compile(
    r"(?:RUPEE\s?)?\d[\d,]*(?:\.\d+)?\s*(?:%|crore|lakh|kw)?",
    re.IGNORECASE,
)


def normalize_numeric_text(text: str) -> str:
    """
    Normalize a string so figures are comparable across English/Hindi and
    across the source's own spelling inconsistencies:
      - Devanagari digits -> Latin digits
      - unit synonyms (crore/croe/करोड़, lakh/लाख) -> one canonical spelling
      - ₹ / Rs. / Rs, / INR -> one canonical marker
      - whitespace collapsed
    This does NOT translate Hindi prose to English -- it only normalizes the
    numeric/unit tokens the Numeric Guard checks.
    """
    t = text.translate(_DEVANAGARI_TO_LATIN)
    for pattern, replacement in _UNIT_SYNONYMS:
        t = pattern.sub(replacement, t)
    t = _WS_RE.sub(" ", t)
    return t.strip()


def _extract_figures(normalized_text: str) -> set[str]:
    found = set()
    for m in FIGURE_PATTERN.finditer(normalized_text):
        token = m.group(0).strip()
        # Skip degenerate matches (bare digits with no unit are still kept
        # -- a lone "10" could be "10 persons" in the payroll threshold --
        # but skip empty/whitespace-only matches from the optional groups).
        if token and any(ch.isdigit() for ch in token):
            found.add(_WS_RE.sub(" ", token).strip(", ").lower())
    return found


_CITATION_TAG_STRIP_RE = re.compile(r"\[S\d+\]")


def numeric_guard(answer_text: str, context_text: str) -> tuple[bool, list[str]]:
    """
    Returns (passed, leaked_figures). `context_text` should be the
    concatenation of every retrieved chunk's `text` actually shown to the
    LLM for this answer.

    Citation tags like [S1] are stripped before figure extraction -- their
    digit is not a policy figure and must not be checked against the
    context (a bare "1" from "[S1]" would otherwise almost never appear
    literally in the source text and would false-positive as a leak).
    """
    answer_text = _CITATION_TAG_STRIP_RE.sub(" ", answer_text)
    norm_answer = normalize_numeric_text(answer_text)
    norm_context = normalize_numeric_text(context_text)

    answer_figures = _extract_figures(norm_answer)
    leaked = [fig for fig in answer_figures if fig not in norm_context]
    return (len(leaked) == 0, leaked)


CITATION_TAG_RE = re.compile(r"\[S(\d+)\]")


def citation_validity_guard(answer_text: str, num_sources: int) -> tuple[bool, list[str]]:
    """Every [Sn] tag in the answer must reference a source that was
    actually supplied (1-indexed, <= num_sources)."""
    tags = CITATION_TAG_RE.findall(answer_text)
    invalid = [f"[S{t}]" for t in tags if not (1 <= int(t) <= num_sources)]
    return (len(invalid) == 0, invalid)


def okf_consistency_guard(answer_text: str, ground_truth_rate_text: str) -> tuple[bool, list[str]]:
    """
    OKF-era addition (docs/OKF_RAG_IMPLEMENTATION.md section 5): checks a
    synthesized answer's figures against the SPECIFIC OKF record the query
    resolved to, not just "does this figure appear somewhere in the shown
    context" (that's numeric_guard's job).

    The two checks catch different failures. A table-atom's `parent_text`
    legitimately contains all three enterprise categories' rates side by
    side (small-to-big retrieval, see ingestion/chunk.py), so a paraphrase
    that swaps the Small rate in for a Micro question passes numeric_guard
    trivially -- both figures ARE in the shown context. This guard instead
    requires every rate-shaped figure in the answer to match the ground
    truth for the one category actually resolved, catching exactly that
    misattribution.

    Only meaningful when the router resolved the query to one specific OKF
    incentive+category (retrieval_mode "okf_lookup" or "hybrid" with a
    detected category) -- callers must not invoke this for an open
    rag_narrative answer, where no single ground-truth slot exists to check
    against.
    """
    answer_text = _CITATION_TAG_STRIP_RE.sub(" ", answer_text)
    norm_answer = normalize_numeric_text(answer_text)
    norm_truth = normalize_numeric_text(ground_truth_rate_text)

    truth_figures = _extract_figures(norm_truth)
    answer_figures = _extract_figures(norm_answer)

    # A figure the answer states that is rate-shaped (has a % or a
    # crore/lakh/rupee unit -- i.e. plausibly THE rate/cap being asked
    # about) but does not appear in the resolved ground truth is a
    # mismatch. Bare numbers with no unit (a headcount, a year count) are
    # not checked here -- they are not what this guard exists to verify,
    # and requiring them would false-positive on incidental figures the
    # LLM's prose legitimately restates from elsewhere in context.
    rate_shaped = re.compile(r"%|crore|lakh|rupee", re.IGNORECASE)
    mismatched = [
        fig for fig in answer_figures
        if rate_shaped.search(fig) and fig not in truth_figures
    ]
    return (len(mismatched) == 0, mismatched)


def ambiguity_disclosure_guard(answer_text: str, required_ambiguity_ids: list[str]) -> tuple[bool, list[str]]:
    """
    If any cited chunk carries an ambiguity_flags entry, the answer must
    mention it is disputed/unclear (we check for the ambiguity ID or the
    words "clarification"/"not specified"/"unclear" as a proxy -- the
    calling code in api/chat.py appends the register's disclosure text
    deterministically when this fails, rather than asking the LLM to try
    again indefinitely).
    """
    if not required_ambiguity_ids:
        return True, []
    lowered = answer_text.lower()
    missing = []
    for amb_id in required_ambiguity_ids:
        if amb_id.lower() in lowered:
            continue
        if any(kw in lowered for kw in ("clarification", "not specified", "unclear", "cannot be determined", "not defined")):
            continue
        missing.append(amb_id)
    return (len(missing) == 0, missing)
