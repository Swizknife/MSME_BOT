"""The adapter between OKF v0.2 frontmatter and this project's domain models.

## Why an adapter instead of rewriting the domain models

``chunk_from_okf.build_chunks()`` never reads a note's frontmatter. It reads
``compile_vault()``'s output, which is ``model_dump(mode="json")`` of the
Pydantic models in ``schemas.py``. So if the *shape on disk* changes but the
*shape those models see* does not, every chunk this project emits is
byte-identical by construction -- and the 85-chunk parity check against the
pre-OKF index keeps passing for a real reason rather than because it was
loosened.

That is what this module does, and it is why ``schemas.py`` keeps every field
name it had before the migration to Google's Open Knowledge Format.

    on disk (OKF v0.2)                      what schemas.py sees
    ------------------                      --------------------
    type: Incentive                    <->  entity_type "incentive"
    incentive_status: rate_unstated    <->  status: rate_unstated
    sources: [ {resource: ...} ]       <->  source: {source_url: ...}
    verified: [ {by, at} ]             <->  source.verification_status

Both migrators call ``to_okf_frontmatter()``, so they cannot drift apart:
there is one definition of what an OKF note looks like, not two.

## The four name collisions

OKF reserves ``type`` and ``status``. This project already used both for
something else, and the meanings are unrelated:

  - ``Incentive.status: rate_unstated`` -- branched on in the answer ladder
    to produce the "this policy states conditions but never states a rate"
    disclosure. If this were collapsed into OKF's ``draft|stable|deprecated``
    the branch would never fire and the bot would begin quoting
    "NO RATE/AMOUNT SPECIFIED IN SOURCE" as though it were a rate.
  - ``Scheme.status: draft_not_notified`` -- becomes the chunk payload's
    ``source_status``, which is how an answer can say a policy is still a
    draft.
  - ``AmbiguityFlag.status: open``
  - ``Authority.type: district_office``

So they are renamed on disk rather than merged. OKF's own ``status`` then
carries its own meaning, mapped from verification state.
"""

from __future__ import annotations

import copy
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from app.okf.okf_spec import OKF_OWNED_KEYS

REPO_ROOT = Path(__file__).resolve().parents[3]
SOURCES_YAML = REPO_ROOT / "config" / "sources.yaml"


# ---------------------------------------------------------------------------
# Type mapping
# ---------------------------------------------------------------------------

# OKF `type:` values are human-facing strings chosen by the producer -- the
# spec has no central registry and tells consumers to tolerate unknown ones.
# PascalCase matches the spec's own examples ("BigQuery Table", "Metric").
ENTITY_TO_OKF_TYPE: dict[str, str] = {
    "scheme": "Scheme",
    "incentive": "Incentive",
    "eligibility_rule": "EligibilityRule",
    "authority": "Authority",
    "district": "District",
    "district_classification": "DistrictClassification",
    "sector": "Sector",
    "glossary_term": "GlossaryTerm",
    "ambiguity_flag": "AmbiguityFlag",
    "act": "Act",
}

OKF_TYPE_TO_ENTITY: dict[str, str] = {v: k for k, v in ENTITY_TO_OKF_TYPE.items()}

# Domain keys renamed on disk because they collide with an OKF reserved key.
# domain name -> on-disk name, per entity type.
COLLISION_RENAMES: dict[str, dict[str, str]] = {
    "scheme": {"status": "scheme_status"},
    "incentive": {"status": "incentive_status"},
    "ambiguity_flag": {"status": "ambiguity_status"},
    "authority": {"type": "authority_type"},
}

# Domain fields whose meaning is *exactly* the OKF key they collide with, so
# they are promoted into it rather than renamed beside it.
#
# `AmbiguityFlag.description` is the one case: it is already a one-line
# summary of the defect, which is precisely what OKF's `description` is for.
# Renaming it to `ambiguity_description` and then deriving a truncated
# `description:` alongside would store the same sentence twice and let the
# two drift. Promotion keeps one field, and the reverse mapping restores it.
#
# Every entry here must be restored explicitly in `to_domain_payload()`,
# because spec-owned keys are otherwise dropped on the way back.
PROMOTED_TO_OKF: dict[str, dict[str, str]] = {
    "ambiguity_flag": {"description": "description"},
}

# Entity types carrying a single top-level `source:` Provenance block.
# The others carry provenance somewhere else, and each needs its own handling:
#   glossary_term -> definitions[].source   (one per scheme, deliberately)
#   act           -> sections[].source
#   ambiguity_flag-> source_ids[]           (ids only; no URL of its own)
HAS_TOP_LEVEL_SOURCE = frozenset({
    "scheme", "incentive", "eligibility_rule", "authority",
    "district", "district_classification", "sector",
})

# Provenance fields that map onto a spec-defined OKFSource field. Everything
# else on a Provenance rides along as an extension key on the same entry,
# which is what makes the reverse mapping exact rather than approximate.
PROV_TO_OKF = {"source_id": "id", "source_url": "resource"}
OKF_TO_PROV = {v: k for k, v in PROV_TO_OKF.items()}


# ---------------------------------------------------------------------------
# Source registry (for titles, and for ambiguity flags that carry only ids)
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _registry() -> dict[str, dict[str, Any]]:
    """source_id -> registry entry from config/sources.yaml.

    Read-only. Nothing in this project writes that file from code.
    """
    if not SOURCES_YAML.exists():
        return {}
    try:
        doc = yaml.safe_load(SOURCES_YAML.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return {}
    return {s["source_id"]: s for s in doc.get("sources", []) if "source_id" in s}


def registry_url(source_id: str) -> str | None:
    entry = _registry().get(source_id)
    return entry.get("url") if entry else None


def registry_title(source_id: str) -> str | None:
    entry = _registry().get(source_id)
    return entry.get("name") if entry else None


# ---------------------------------------------------------------------------
# Verification -> OKF trust actors
# ---------------------------------------------------------------------------

# How a free-text `verified_by` string becomes an OKF actor.
#
# Deliberately conservative about claiming `human:`. The trust tier derived
# from these actors is shown to the person reading an answer, so asserting
# human review where the evidence only shows a script ran would overstate it
# in exactly the direction that matters. Across all 198 provenance blocks in
# the vault today there are four distinct `verified_by` strings and NONE
# records a human verifier, so every migrated note lands at
# machine-confirmed.
#
# Promoting the 191 policy_data-derived notes to human-reviewed is a real and
# probably correct change -- their figures were transcribed from the PDF by a
# person before any script existed -- but it is the author's claim to make,
# not something to infer from a filename. See HUMAN_TRANSCRIBER below.
HUMAN_TRANSCRIBER: str | None = None  # e.g. "human:soumyasharma2402"

_ACTOR_PATTERNS: list[tuple[str, str]] = [
    (r"verify_policy_data", "process:verify_policy_data"),
    (r"verify_chunks", "process:verify_chunks"),
    (r"\bClaude\b|WebFetch", "claude-code/opus-5"),
]


def actors_from_verified_by(verified_by: str | None) -> list[str]:
    """Map a free-text verifier string to OKF actor identifiers."""
    if not verified_by:
        return []
    actors: list[str] = []
    for pattern, actor in _ACTOR_PATTERNS:
        if re.search(pattern, verified_by, re.IGNORECASE):
            actors.append(actor)
    if not actors:
        # Unrecognised verifier: record it as a process rather than silently
        # dropping the fact that something verified this.
        slug = re.sub(r"[^a-z0-9]+", "-", verified_by.lower()).strip("-")[:40]
        actors.append(f"process:{slug}" if slug else "process:unknown")
    if (
        HUMAN_TRANSCRIBER
        and any(a.startswith("process:verify_policy_data") for a in actors)
    ):
        actors.insert(0, HUMAN_TRANSCRIBER)
    return actors


# verification_status -> OKF lifecycle status.
# `unverified` stays `stable`: it means nobody has checked this yet, not that
# the document is a draft. The trust tier already carries "unverified", and
# duplicating it into `status` would conflate two different axes.
_VERIFICATION_TO_OKF_STATUS = {
    "verified": "stable",
    "unverified": "stable",
    "superseded": "deprecated",
    "disputed": "draft",
}


def _verified_block(prov: dict[str, Any]) -> list[dict[str, Any]]:
    if prov.get("verification_status") != "verified":
        return []
    at = prov.get("verified_at")
    return [
        {"by": actor, **({"at": at} if at else {})}
        for actor in actors_from_verified_by(prov.get("verified_by"))
    ]


# ---------------------------------------------------------------------------
# Provenance <-> OKFSource
# ---------------------------------------------------------------------------


def provenance_to_okf_source(prov: dict[str, Any]) -> dict[str, Any]:
    """One `sources:` entry from one Provenance block.

    `source_id`/`source_url` become the spec's `id`/`resource`; every other
    Provenance field rides along as an extension key on the same entry. The
    spec permits that explicitly and requires consumers to preserve it, which
    is what makes `okf_source_to_provenance()` exact rather than lossy.
    """
    entry: dict[str, Any] = {}
    source_id = prov.get("source_id")
    if source_id:
        entry["id"] = source_id
    entry["resource"] = prov.get("source_url") or registry_url(source_id or "") or ""
    title = registry_title(source_id or "")
    if title:
        entry["title"] = title
    for key, value in prov.items():
        if key in PROV_TO_OKF:
            continue
        entry[key] = value
    return entry


def okf_source_to_provenance(entry: dict[str, Any]) -> dict[str, Any]:
    """The exact inverse. `title` is derived from the registry, so it is dropped."""
    prov: dict[str, Any] = {}
    if entry.get("id") is not None:
        prov["source_id"] = entry["id"]
    prov["source_url"] = entry.get("resource", "")
    for key, value in entry.items():
        if key in OKF_TO_PROV or key == "title":
            continue
        prov[key] = value
    return prov


def _nested_provenances(entity_type: str, payload: dict[str, Any]) -> list[dict]:
    """Provenance blocks for the entity types that don't have a top-level one."""
    if entity_type == "glossary_term":
        return [d["source"] for d in payload.get("definitions", []) if d.get("source")]
    if entity_type == "act":
        return [s["source"] for s in payload.get("sections", []) if s.get("source")]
    return []


def _sources_for(entity_type: str, payload: dict[str, Any],
                 prov: dict[str, Any] | None) -> list[dict[str, Any]]:
    if prov:
        return [provenance_to_okf_source(prov)]

    nested = _nested_provenances(entity_type, payload)
    if nested:
        out, seen = [], set()
        for p in nested:
            entry = provenance_to_okf_source(p)
            key = (entry.get("id"), entry.get("resource"))
            if key not in seen:
                seen.add(key)
                out.append(entry)
        return out

    # AmbiguityFlag carries `source_ids` and no URL of its own -- a flag is a
    # statement *about* one or more sources. Resolve each id through the
    # registry so the note still carries a conformant `sources:` block and so
    # footnote labels have something real to join to.
    entries = []
    for sid in payload.get("source_ids", []) or []:
        url = registry_url(sid)
        if url:
            entry = {"id": sid, "resource": url}
            title = registry_title(sid)
            if title:
                entry["title"] = title
            entries.append(entry)
    return entries


# ---------------------------------------------------------------------------
# The two public directions
# ---------------------------------------------------------------------------


def _title_for(entity_type: str, payload: dict[str, Any]) -> str | None:
    for key in ("name", "term", "title"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    for key in ("id", "district_id", "sector_id", "rule_id", "act_id"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _description_for(entity_type: str, payload: dict[str, Any]) -> str | None:
    for key in ("summary", "description", "condition_text"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            # One line, per the spec's "one-line summary".
            flat = " ".join(value.split())
            return flat[:197] + "..." if len(flat) > 200 else flat
    return None


def to_okf_frontmatter(
    entity_type: str,
    payload: dict[str, Any],
    *,
    generated_by: str | None = None,
    generated_at: Any | None = None,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    """Domain payload -> OKF v0.2 frontmatter.

    `payload` is the frontmatter this project used before the migration,
    minus `entity_type`. The result is a conformant OKF document whose
    extension keys are that same payload, so `to_domain_payload()` can undo
    it exactly.
    """
    if entity_type not in ENTITY_TO_OKF_TYPE:
        raise ValueError(f"Unknown entity_type {entity_type!r}")

    work = copy.deepcopy(payload)
    work.pop("entity_type", None)
    prov = work.pop("source", None) if entity_type in HAS_TOP_LEVEL_SOURCE else None

    for domain_key, disk_key in COLLISION_RENAMES.get(entity_type, {}).items():
        if domain_key in work:
            work[disk_key] = work.pop(domain_key)

    fm: dict[str, Any] = {"type": ENTITY_TO_OKF_TYPE[entity_type]}

    promoted = PROMOTED_TO_OKF.get(entity_type, {})

    title = _title_for(entity_type, work)
    if title:
        fm["title"] = title
    if "description" in promoted:
        value = work.pop(promoted["description"], None)
        if value is not None:
            fm["description"] = value
    else:
        description = _description_for(entity_type, work)
        if description:
            fm["description"] = description
    if tags:
        fm["tags"] = list(tags)

    reference = prov or (_nested_provenances(entity_type, work) or [None])[0]
    fm["status"] = _VERIFICATION_TO_OKF_STATUS.get(
        (reference or {}).get("verification_status", "unverified"), "stable"
    )
    if generated_by:
        entry: dict[str, Any] = {"by": generated_by}
        if generated_at:
            entry["at"] = generated_at
        fm["generated"] = entry

    verified = _verified_block(reference) if reference else []
    if verified:
        fm["verified"] = verified

    sources = _sources_for(entity_type, work, prov)
    if sources:
        fm["sources"] = sources

    fm.update(work)
    return fm


def to_domain_payload(fm: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """OKF v0.2 frontmatter -> (entity_type, payload for schemas.py).

    The exact inverse of `to_okf_frontmatter()`. Spec-owned keys are dropped
    because every one of them is derived from the domain payload; the
    Provenance block is rebuilt from `sources[0]`.
    """
    okf_type = fm.get("type")
    if okf_type not in OKF_TYPE_TO_ENTITY:
        raise ValueError(
            f"Unknown OKF type {okf_type!r}. Known types: "
            f"{', '.join(sorted(OKF_TYPE_TO_ENTITY))}"
        )
    entity_type = OKF_TYPE_TO_ENTITY[okf_type]

    payload = {k: v for k, v in fm.items() if k not in OKF_OWNED_KEYS}

    for domain_key, disk_key in COLLISION_RENAMES.get(entity_type, {}).items():
        if disk_key in payload:
            payload[domain_key] = payload.pop(disk_key)

    # Restore fields promoted into a spec key; they were stripped above with
    # the rest of OKF_OWNED_KEYS.
    for domain_key, okf_key in PROMOTED_TO_OKF.get(entity_type, {}).items():
        if okf_key in fm:
            payload[domain_key] = fm[okf_key]

    if entity_type in HAS_TOP_LEVEL_SOURCE:
        sources = fm.get("sources") or []
        if sources:
            payload["source"] = okf_source_to_provenance(sources[0])

    return entity_type, payload
