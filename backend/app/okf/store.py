"""Read accessor for compiled OKF records, and the query-time alias index
that lets the router recognise which incentive/scheme a question is about.

Consumers: app/policy/intents.py (routing), app/api/chat.py (the OKF
deterministic tier and citation formatting), app/generation/guards.py (the
OKF consistency guard).

Deliberately dumb and cheap, matching the rest of the query-time path's
"no LLM call before generation" doctrine (see intents.py's module
docstring): loading and indexing ~240 small JSON records is milliseconds,
so it happens once at import time and is reused for the process lifetime.
If data/okf_compiled/ is missing or empty (the compiler hasn't run), every
function here degrades to "no match" rather than raising -- the OKF layer
is additive, and its absence must fall through to the existing RAG-only
behaviour, never crash the bot.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
COMPILED_DIR = REPO_ROOT / "data" / "okf_compiled"

# Enterprise-category keywords, English + Hindi. Same category vocabulary
# GUIDING_PRINCIPLES/INCENTIVE_TABLE use, so a match here lines up 1:1 with
# an OKF CategoryRate.enterprise_category.
CATEGORY_PATTERNS = {
    "micro": re.compile(r"\bmicro\b|सूक्ष्म", re.IGNORECASE),
    "small": re.compile(r"\bsmall\b|लघु", re.IGNORECASE),
    "medium": re.compile(r"\bmedium\b|मध्यम", re.IGNORECASE),
}

# Stopwords stripped before matching an incentive's name against a query.
# Short and deliberately conservative: the goal is only to stop a name like
# "Stamp Duty" failing to match "stamp duty for my unit" because of an
# unrelated trailing word, not to do real NLP.
_STOPWORDS = {
    "a", "an", "and", "for", "of", "on", "the", "to", "up", "in", "under",
    "scheme", "incentive", "subsidy",  # too generic alone to require, see resolve_incentives
}


def _load_json_dir(entity_type: str) -> list[dict]:
    d = COMPILED_DIR / entity_type
    if not d.exists():
        return []
    out = []
    for f in sorted(d.glob("*.json")):
        try:
            out.append(json.loads(f.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            continue
    return out


@lru_cache(maxsize=1)
def _schemes() -> dict[str, dict]:
    return {r["scheme_id"]: r for r in _load_json_dir("scheme")}


@lru_cache(maxsize=1)
def _incentives() -> dict[str, dict]:
    return {r["incentive_id"]: r for r in _load_json_dir("incentive")}


@lru_cache(maxsize=1)
def _ambiguities() -> dict[str, dict]:
    return {r["id"]: r for r in _load_json_dir("ambiguity_flag")}


def is_available() -> bool:
    """Whether the compiler has run and produced anything to route against."""
    return bool(_incentives())


def get_scheme(scheme_id: str) -> dict | None:
    return _schemes().get(scheme_id)


def scheme_short_name(scheme_id: str) -> str:
    s = _schemes().get(scheme_id)
    return s["short_name"] if s else scheme_id


def get_incentive(incentive_id: str) -> dict | None:
    return _incentives().get(incentive_id)


def get_ambiguity(amb_id: str) -> dict | None:
    return _ambiguities().get(amb_id)


@lru_cache(maxsize=1)
def _incentive_name_index() -> list[tuple[frozenset, str]]:
    """[(significant-words-of-name, incentive_id), ...], longest names first
    so a more specific match (e.g. "additional subsidy for scaling up") is
    tried before a shorter one that could also partially match."""
    index = []
    for inc in _incentives().values():
        words = frozenset(
            w for w in re.findall(r"[a-z]+", inc["name"].lower()) if w not in _STOPWORDS
        )
        if words:
            index.append((words, inc["incentive_id"]))
    return sorted(index, key=lambda pair: -len(pair[0]))


def resolve_incentives(text: str) -> list[str]:
    """incentive_ids whose name's significant words ALL appear in the query
    text (any order, not necessarily contiguous). Cheap keyword matching,
    not semantic search -- deliberately, per intents.py's efficiency thesis.
    Only reliable while incentive names are distinct within a scheme; if a
    second scheme reuses a generic name like "Capital Subsidy", this must
    gain scheme disambiguation before it can be trusted across sources."""
    tokens = set(re.findall(r"[a-z]+", text.lower()))
    matches = []
    for words, incentive_id in _incentive_name_index():
        if words and words.issubset(tokens):
            matches.append(incentive_id)
    return matches


def detect_category(text: str) -> str | None:
    for category, pattern in CATEGORY_PATTERNS.items():
        if pattern.search(text):
            return category
    return None


def rate_for_category(incentive: dict, category: str) -> dict | None:
    for rate in incentive.get("category_rates", []):
        if rate["enterprise_category"] == category:
            return rate
    return None
