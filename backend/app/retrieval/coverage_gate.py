"""
The Coverage Gate: decides, from the reranker score alone, whether the LLM
is allowed to answer at all.

Per docs/RAG_IMPLEMENTATION.md section 6.3: cosine similarity is not
reliably thresholdable (scores compress into a narrow band and drift with
query length), but cross-encoder reranker scores separate relevant from
irrelevant by a wide, stable margin -- so this gate thresholds on
rerank score, never on raw retrieval score.

Two thresholds, calibrated in config/thresholds.yaml against a held-out
eval split (never the same split used to report accuracy -- see the
architecture doc's fix for a circularity bug in an earlier draft):
  - score >= TAU_SOFT  -> normal answer
  - TAU_HARD <= score < TAU_SOFT -> answer, but flagged low-confidence
  - score < TAU_HARD -> ABSTAIN, the LLM is never called

Defaults below are placeholders pending Phase 4 calibration (the
architecture doc is explicit that thresholds must be fitted on real score
distributions, not guessed) -- they are deliberately conservative (a higher
TAU_HARD, biased toward abstaining) since an incorrect refusal is far
cheaper than an ungrounded answer for a government policy bot.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
THRESHOLDS_PATH = REPO_ROOT / "config" / "thresholds.yaml"

DEFAULT_TAU_HARD = 0.35
DEFAULT_TAU_SOFT = 0.55


@dataclass
class GateDecision:
    action: str  # "answer" | "answer_low_confidence" | "abstain"
    top_score: float
    tau_hard: float
    tau_soft: float


def _load_thresholds(source_type: str | None = None) -> tuple[float, float]:
    """Multi-source amendment (docs/OKF_RAG_IMPLEMENTATION.md section 5):
    reranker score distributions differ by source register -- a scraped
    HTML FAQ page and a structured policy PDF don't rerank on the same
    scale -- so thresholds can be keyed by source_type. Falls back to
    `default` (or the hardcoded constants) when no by_source_type entry
    exists for the given type, or when no source_type is known at all,
    which is always true today since exactly one source is indexed."""
    if not THRESHOLDS_PATH.exists():
        return DEFAULT_TAU_HARD, DEFAULT_TAU_SOFT
    try:
        import yaml

        data = yaml.safe_load(THRESHOLDS_PATH.read_text(encoding="utf-8")) or {}
        by_type = data.get("by_source_type") or {}
        if source_type and source_type in by_type:
            entry = by_type[source_type]
            return float(entry.get("tau_hard", DEFAULT_TAU_HARD)), float(entry.get("tau_soft", DEFAULT_TAU_SOFT))
        default = data.get("default") or data  # tolerate the flat pre-multi-source shape too
        return float(default.get("tau_hard", DEFAULT_TAU_HARD)), float(default.get("tau_soft", DEFAULT_TAU_SOFT))
    except Exception:
        return DEFAULT_TAU_HARD, DEFAULT_TAU_SOFT


def decide(reranked: list[tuple[object, float]]) -> GateDecision:
    # Threshold by the top-ranked chunk's own source_type when the payload
    # carries one; a mixed shortlist is thresholded by whichever source
    # produced the candidate actually being judged, not a single global
    # figure that a scraped-HTML source's noisier scores would miscalibrate.
    source_type = None
    if reranked:
        source_type = reranked[0][0].payload.get("source_type")
    tau_hard, tau_soft = _load_thresholds(source_type)
    top_score = reranked[0][1] if reranked else 0.0

    if top_score < tau_hard:
        action = "abstain"
    elif top_score < tau_soft:
        action = "answer_low_confidence"
    else:
        action = "answer"

    return GateDecision(action=action, top_score=top_score, tau_hard=tau_hard, tau_soft=tau_soft)


def okf_coverage(evidence) -> GateDecision:
    """The Coverage Gate's OKF-mode counterpart: no reranker score exists,
    because okf mode issues no vector search at all. Confidence here is
    binary -- either the graph assembled real, trustworthy evidence about
    what the query named, or it did not -- not a threshold on a continuous
    score, so `top_score` is a coarse three-level stand-in (0 / 0.5 / 1.0)
    kept only so GateDecision stays the one type every caller downstream
    (the ladder, the UI's low_confidence flag) already knows how to read.

    Levels, in the order they're checked:
      no entry points matched the query -> abstain (nothing to traverse from)
      entry points matched but the walk reached nothing -> abstain
      nodes reached, but none above 'unverified' trust -> answer_low_confidence
      at least one node is machine-confirmed or human-reviewed -> answer
    """
    tau_hard, tau_soft = _load_thresholds()
    if not evidence or not evidence.entry_points:
        return GateDecision(action="abstain", top_score=0.0, tau_hard=tau_hard, tau_soft=tau_soft)
    if not evidence.nodes:
        return GateDecision(action="abstain", top_score=0.0, tau_hard=tau_hard, tau_soft=tau_soft)

    trusted = [n for n in evidence.nodes if n.trust != "unverified"]
    if not trusted:
        return GateDecision(
            action="answer_low_confidence", top_score=0.5, tau_hard=tau_hard, tau_soft=tau_soft
        )
    return GateDecision(action="answer", top_score=1.0, tau_hard=tau_hard, tau_soft=tau_soft)


ABSTAIN_TEMPLATE_EN = (
    "This does not appear to be covered in the Bihar MSME Policy 2026 as currently drafted. "
    "This assistant answers only from that document, and it is still a draft. "
    "Related topics I can help with: {suggestions}. "
    "For anything outside this policy, please contact your District Industries Centre (DIC) "
    "or the MSME helpline."
)

ABSTAIN_TEMPLATE_HI = (
    "यह विषय बिहार एमएसएमई नीति 2026 के वर्तमान प्रारूप में शामिल नहीं है। "
    "यह सहायक केवल उसी दस्तावेज़ से उत्तर देता है, और वह अभी प्रारूप (draft) है। "
    "मैं इन विषयों में सहायता कर सकता हूँ: {suggestions}। "
    "अन्य किसी प्रश्न के लिए कृपया अपने ज़िला उद्योग केंद्र (DIC) या एमएसएमई हेल्पलाइन से संपर्क करें।"
)


def abstain_message(lang: str, suggestions: list[str]) -> str:
    suggestion_text = ", ".join(suggestions) if suggestions else (
        "capital subsidy, payroll subsidy, district categories" if lang == "en"
        else "पूंजी सब्सिडी, वेतन सब्सिडी, जिला श्रेणियाँ"
    )
    template = ABSTAIN_TEMPLATE_HI if lang == "hi" else ABSTAIN_TEMPLATE_EN
    return template.format(suggestions=suggestion_text)
