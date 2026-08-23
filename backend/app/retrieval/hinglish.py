"""
Romanised-Hindi (Hinglish) query mitigation.

Per docs/RAG_IMPLEMENTATION.md section 5.3: BGE-M3's cross-lingual strength
is well established for Devanagari Hindi, but materially weaker for
romanised Hindi typed in Latin script ("kitni subsidy milegi") -- that text
looks like English to the encoder, so it neither matches English clauses as
well as real English would, nor benefits from BGE-M3's cross-lingual
Devanagari<->English alignment. The documented mitigation: transliterate the
query to Devanagari and retrieve with BOTH the original and the
transliterated form, then fuse.

Uses `indic_transliteration`'s ITRANS scheme -- built for formally
romanised Sanskrit-derived text, not casual English-loanword-heavy Hinglish,
so it will render English loanwords (e.g. "subsidy") somewhat oddly. It
still measurably helps: the native-Hindi function words that make up most
of a query's retrieval signal against this corpus's Devanagari-titled
sections and clause breadcrumbs ("kitni", "milegi", "kya", "hai") come
through reasonably. This is a recall-boosting ADDITION, not a replacement --
the original query is always retrieved too (see pipeline.py), so a poor
transliteration can only add noise to the candidate pool, not remove a
correct hit the original query would have found on its own.
"""

from __future__ import annotations


def transliterate_to_devanagari(text: str) -> str | None:
    """Best-effort ITRANS -> Devanagari transliteration. Returns None if the
    library isn't available or transliteration fails, so callers can treat
    this as an optional enhancement rather than a hard dependency."""
    try:
        from indic_transliteration import sanscript
        from indic_transliteration.sanscript import transliterate
    except ImportError:
        return None

    try:
        result = transliterate(text.lower(), sanscript.ITRANS, sanscript.DEVANAGARI)
    except Exception:
        return None

    return result if result and result.strip() else None
