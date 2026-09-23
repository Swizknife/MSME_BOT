"""Concept identity and link resolution.

A silently-unresolved link in a citation-grounded bot is a citation pointing
at nothing, so these tests care most about the cases where resolution could
quietly pick the wrong target rather than fail loudly.
"""

from __future__ import annotations

from pathlib import Path

from app.okf import links, vault


def _index() -> links.LinkIndex:
    return links.build_index()


def test_every_concept_in_the_vault_is_indexed():
    index = _index()
    authored = [n for n in vault.iter_notes() if n.path.name not in ("index.md", "log.md")]
    assert len(index) == len(authored)


def test_all_reference_forms_resolve_to_the_same_concept():
    index = _index()
    target = index.by_domain_id["BIHAR_MSME_2026-AMB-03"]
    for form in (
        "BIHAR_MSME_2026-AMB-03",
        "[[BIHAR_MSME_2026-AMB-03]]",
        target.concept_id,
        f"/{target.concept_id}.md",
        f"/{target.concept_id}.md#some-heading",
    ):
        assert index.resolve(form) == target, form


def test_external_urls_and_unknown_ids_do_not_resolve():
    index = _index()
    assert index.resolve("https://example.com/a.md") is None
    assert index.resolve("mailto:someone@example.com") is None
    assert index.resolve("NO-SUCH-CONCEPT") is None
    assert index.resolve("") is None


def test_ambiguous_domain_ids_are_recorded_and_resolved_by_preference():
    """CGTMSE and TREDS each exist as both a Scheme and a GlossaryTerm.

    Under [[wikilinks]] this was invisible and resolution depended on walk
    order. Every real reference in the vault means the scheme, so a
    GlossaryTerm -- an abbreviation expansion -- must rank last.
    """
    index = _index()
    assert "CGTMSE" in index.duplicate_domain_ids
    assert "TREDS" in index.duplicate_domain_ids
    for domain_id in ("CGTMSE", "TREDS"):
        assert index.resolve(domain_id).entity_type == "scheme"


def test_preference_order_puts_glossary_last():
    assert links._preference("scheme") < links._preference("glossary_term")
    assert links._preference("act") < links._preference("glossary_term")
    # An unknown entity type sorts after every known one rather than first.
    assert links._preference("something_new") >= len(links.RESOLUTION_PREFERENCE)


def test_every_wikilink_in_the_vault_resolves():
    """No reference may be lost in the migration to OKF markdown links."""
    index = _index()
    unresolved = []
    for note in vault.iter_notes():
        targets = set(links.WIKILINK_RE.findall(note.body))
        for value in note.frontmatter.values():
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, str):
                        targets |= set(links.WIKILINK_RE.findall(item))
        for target in targets:
            if index.resolve(target) is None:
                unresolved.append(f"{note.path.name} -> [[{target}]]")
    assert not unresolved, unresolved


def test_markdown_link_is_bundle_absolute():
    index = _index()
    rendered = index.markdown_link("BIHAR_MSME_2026-AMB-03", text="AMB-03")
    assert rendered is not None
    assert rendered.startswith("[AMB-03](/")
    assert rendered.endswith(".md)")


def test_parse_body_links_ignores_footnote_definitions():
    index = _index()
    body = (
        "A rate of 30%.[^src-1]\n\n"
        "See [AMB-03](/08_ambiguities/BIHAR_MSME_2026-AMB-03.md).\n\n"
        "[^src-1]: Bihar MSME Policy 2026, S7.9\n"
    )
    parsed = index.parse_body_links(body)
    assert parsed == [("AMB-03", "/08_ambiguities/BIHAR_MSME_2026-AMB-03.md")]


def test_relative_links_need_a_base_and_resolve_against_it():
    index = _index()
    ref = index.by_domain_id["BIHAR_MSME_2026-AMB-03"]
    sibling = ref.path.parent / "other.md"
    assert index.resolve(f"./{ref.path.name}", base=sibling) == ref
    # Without a base there is nothing to resolve against; None, not a guess.
    assert index.resolve(f"./{ref.path.name}") is None


def test_link_target_uses_forward_slashes(tmp_path: Path):
    ref = links.ConceptRef(
        concept_id="incentives/capital-subsidy",
        path=tmp_path / "x.md",
        okf_type="Incentive",
        entity_type="incentive",
        domain_id="X",
        title="Capital Subsidy",
    )
    assert ref.link_target == "/incentives/capital-subsidy.md"
    assert "\\" not in ref.link_target
