"""
Runtime accessor for the Policy Ambiguity Register.

Per docs/RAG_IMPLEMENTATION.md section 8: the register is designed to be
editable by officers through the admin console without a redeploy. Today
(no Postgres/admin console yet -- see the Phase roadmap), this module reads
directly from the seed data in app/ingestion/policy_data.py, which is
exactly what the future Postgres-backed version replaces one-for-one:
db/models.py's PolicyAmbiguity table will be seeded from this same list
(db/seed_ambiguities.py), and this module's functions will switch to
querying the DB instead of the in-memory list -- callers in app/api/chat.py
do not change.
"""

from __future__ import annotations

from app.ingestion import policy_data as pd

_BY_ID = {e.id: e for e in pd.AMBIGUITY_REGISTER}


def get(amb_id: str):
    return _BY_ID.get(amb_id)


def disclosures_for(amb_ids: list[str], lang: str) -> list[str]:
    out = []
    for amb_id in amb_ids:
        entry = _BY_ID.get(amb_id)
        if entry is None:
            continue
        text = entry.public_disclosure_hi if lang == "hi" else entry.public_disclosure_en
        out.append(f"[{amb_id}] {text}")
    return out


def is_blocking(amb_id: str) -> bool:
    entry = _BY_ID.get(amb_id)
    return entry is not None and entry.severity == "blocking"
