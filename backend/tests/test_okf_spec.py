"""Google OKF v0.2 conformance, and the frontmatter adapter's exactness.

The load-bearing test here is `test_every_vault_note_round_trips_exactly`.
The whole migration strategy rests on one claim: the shape of a note on disk
can change completely while the shape `schemas.py` sees stays identical, so
every emitted RAG chunk is byte-identical by construction rather than by
luck. If that claim is false, the 85-chunk parity check against the pre-OKF
index is the next thing to fail, and it is far harder to debug from there.
"""

from __future__ import annotations

import pytest

from app.okf import frontmatter as F
from app.okf import vault
from app.okf.okf_spec import (
    OKF_VERSION,
    OKFDocument,
    concept_id,
    is_reserved,
    trust_tier,
)


# ---------------------------------------------------------------------------
# The spec's own rules
# ---------------------------------------------------------------------------


def test_type_is_the_only_required_field():
    doc = OKFDocument.model_validate({"type": "Incentive"})
    assert doc.type == "Incentive"
    assert doc.status == "stable"  # spec default
    assert doc.verified == []
    assert doc.sources == []


def test_empty_type_is_rejected():
    with pytest.raises(Exception):
        OKFDocument.model_validate({"type": ""})
    with pytest.raises(Exception):
        OKFDocument.model_validate({"title": "no type at all"})


def test_unknown_keys_are_preserved_not_rejected():
    """The spec says consumers MUST NOT reject unknown keys and MUST keep them.

    This is the mechanism the whole migration depends on: ~40 domain fields
    ride along inside a document that stays conformant and portable.
    """
    doc = OKFDocument.model_validate(
        {"type": "Incentive", "incentive_id": "X-1", "category_rates": [{"a": 1}]}
    )
    assert doc.model_extra["incentive_id"] == "X-1"
    assert doc.model_extra["category_rates"] == [{"a": 1}]
    assert "incentive_id" in doc.extensions()
    # Spec-owned keys are not extensions.
    assert "type" not in doc.extensions()


def test_single_verified_mapping_is_coerced_to_a_one_element_list():
    """The spec allows a bare mapping and tells consumers to treat it as a list."""
    doc = OKFDocument.model_validate(
        {"type": "Scheme", "verified": {"by": "human:someone", "at": "2026-06-25T09:00:00Z"}}
    )
    assert len(doc.verified) == 1
    assert doc.verified[0].by == "human:someone"


@pytest.mark.parametrize(
    "verified,expected",
    [
        ([], "unverified"),
        ([{"by": "process:verify_policy_data"}], "machine-confirmed"),
        ([{"by": "claude-code/opus-5"}], "machine-confirmed"),
        ([{"by": "human:soumyasharma2402"}], "human-reviewed"),
        # A human anywhere in the list wins -- the strongest evidence present.
        (
            [{"by": "process:verify_policy_data"}, {"by": "human:soumyasharma2402"}],
            "human-reviewed",
        ),
    ],
)
def test_trust_tier_derivation(verified, expected):
    doc = OKFDocument.model_validate({"type": "Scheme", "verified": verified})
    assert trust_tier(doc) == expected


def test_reserved_filenames():
    assert is_reserved("index.md")
    assert is_reserved("log.md")
    assert not is_reserved("capital-subsidy.md")


def test_concept_id_is_path_minus_md_with_forward_slashes():
    assert concept_id("incentives/capital-subsidy.md") == "incentives/capital-subsidy"
    # Windows separators must not leak into an identifier that appears in links.
    assert concept_id("incentives\\capital-subsidy.md") == "incentives/capital-subsidy"


def test_okf_version_is_the_one_we_target():
    assert OKF_VERSION == "0.2"


# ---------------------------------------------------------------------------
# The adapter
# ---------------------------------------------------------------------------


def test_status_collision_is_renamed_not_merged():
    """`Incentive.status: rate_unstated` must survive as a domain field.

    The answer ladder branches on it to produce the "conditions stated, rate
    never stated" disclosure. If it were folded into OKF's
    draft|stable|deprecated the branch would stop firing and the bot would
    begin quoting "NO RATE/AMOUNT SPECIFIED IN SOURCE" as if it were a rate.
    """
    payload = {"incentive_id": "X", "status": "rate_unstated"}
    fm = F.to_okf_frontmatter("incentive", payload)
    assert fm["incentive_status"] == "rate_unstated"
    assert fm["status"] in ("draft", "stable", "deprecated")
    _, back = F.to_domain_payload(fm)
    assert back["status"] == "rate_unstated"


def test_ambiguity_description_is_promoted_not_duplicated():
    """AmbiguityFlag.description IS the OKF description -- stored once."""
    payload = {"id": "X-AMB-01", "description": "Two clauses disagree."}
    fm = F.to_okf_frontmatter("ambiguity_flag", payload)
    assert fm["description"] == "Two clauses disagree."
    assert "ambiguity_description" not in fm
    _, back = F.to_domain_payload(fm)
    assert back["description"] == "Two clauses disagree."


def test_provenance_becomes_a_conformant_sources_entry():
    prov = {
        "source_id": "BIHAR_MSME_POLICY_2026",
        "source_url": "https://state.bihar.gov.in/industries/",
        "fetch_method": "manual",
        "page_start": 18,
        "verification_status": "verified",
        "verified_by": "verify_policy_data.py (figure tokens checked)",
    }
    fm = F.to_okf_frontmatter("incentive", {"incentive_id": "X", "source": prov})
    entry = fm["sources"][0]
    assert entry["id"] == "BIHAR_MSME_POLICY_2026"
    assert entry["resource"] == "https://state.bihar.gov.in/industries/"  # spec-required
    assert entry["page_start"] == 18  # extension key rides along
    assert fm["verified"][0]["by"] == "process:verify_policy_data"
    _, back = F.to_domain_payload(fm)
    assert back["source"] == prov  # exact inverse


def test_verified_by_is_not_upgraded_to_a_human_claim():
    """Trust tiers are shown to the reader, so `human:` is never inferred.

    No provenance block in the vault records a human verifier. Promoting the
    policy_data-derived notes to human-reviewed is the author's claim to
    make, not something to derive from a script's filename.
    """
    assert F.HUMAN_TRANSCRIBER is None
    actors = F.actors_from_verified_by("verify_policy_data.py (figure tokens checked)")
    assert actors == ["process:verify_policy_data"]
    assert not any(a.startswith("human:") for a in actors)


def test_unknown_okf_type_is_rejected_with_a_useful_message():
    with pytest.raises(ValueError, match="Unknown OKF type"):
        F.to_domain_payload({"type": "Sandwich"})


# ---------------------------------------------------------------------------
# The whole vault
# ---------------------------------------------------------------------------


def _notes():
    return vault.iter_notes()



def test_every_vault_note_round_trips_exactly():
    """OKF -> domain -> OKF must be the identity, for every authored note.

    `chunk_from_okf` reads the domain payload, never the frontmatter, so
    identity here means the on-disk shape can keep evolving without any
    emitted RAG chunk changing -- which is why the 85-chunk parity check
    against the pre-OKF index still passes after the migration.
    """
    failures = []
    for note in _notes():
        original = note.frontmatter
        entity_type, payload = F.to_domain_payload(original)
        generated = original.get("generated") or {}
        rebuilt = F.to_okf_frontmatter(
            entity_type,
            payload,
            generated_by=generated.get("by"),
            generated_at=generated.get("at"),
            tags=original.get("tags"),
        )
        if rebuilt != original:
            differing = sorted(
                k for k in set(original) | set(rebuilt)
                if original.get(k) != rebuilt.get(k)
            )
            failures.append(f"{note.path.name}: differs after round-trip: {differing}")
    assert not failures, "; ".join(failures[:20])


def test_every_vault_note_is_conformant_okf():
    """Conformance, per the spec: parseable frontmatter with a non-empty type."""
    for note in _notes():
        doc = OKFDocument.model_validate(note.frontmatter)
        assert doc.type, f"{note.path.name}: empty type"
        assert doc.type in F.OKF_TYPE_TO_ENTITY, f"{note.path.name}: unknown type {doc.type}"
        for entry in doc.sources:
            assert entry.resource, f"{note.path.name}: sources[] entry without a resource"


def test_no_domain_field_silently_collides_with_a_spec_key():
    """Guards against a future entity quietly shadowing an OKF reserved key.

    `description` on AmbiguityFlag was exactly this, and it was caught only
    because the round-trip test failed on 22 notes. Any new collision must be
    added to COLLISION_RENAMES or PROMOTED_TO_OKF deliberately.

    Checked on the DOMAIN payload, not the frontmatter: after migration the
    frontmatter is supposed to carry spec keys, so looking there would find
    every note guilty.
    """
    from app.okf.okf_spec import OKF_OWNED_KEYS

    handled = set()
    for mapping in (*F.COLLISION_RENAMES.values(), *F.PROMOTED_TO_OKF.values()):
        handled.update(mapping)

    unhandled: dict[str, set[str]] = {}
    for note in _notes():
        entity_type, payload = F.to_domain_payload(note.frontmatter)
        for key in payload:
            if key in handled or key not in OKF_OWNED_KEYS:
                continue
            unhandled.setdefault(key, set()).add(entity_type)
    assert not unhandled, f"unhandled spec-key collisions: {unhandled}"


def test_the_bundle_root_index_declares_the_okf_version():
    """`okf_version` belongs in the bundle-root index.md, and only there."""
    import yaml

    root_index = vault.VAULT_DIR / "index.md"
    assert root_index.exists(), "bundle root index.md missing"
    front = root_index.read_text(encoding="utf-8").split("---", 2)[1]
    assert yaml.safe_load(front)["okf_version"] == OKF_VERSION


def test_no_legacy_entity_type_key_survives_in_the_bundle():
    stragglers = [n.path.name for n in _notes() if "entity_type" in n.frontmatter]
    assert not stragglers, f"notes still using entity_type: {stragglers}"
