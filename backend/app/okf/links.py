"""Concept identity and cross-links -- one definition, used by three callers.

Google's OKF v0.2 defines a concept's identity as its **bundle-relative path
with `.md` removed**, and its cross-links as ordinary markdown links:

    data/okf_vault/ambiguities/BIHAR_MSME_2026-AMB-03.md
      -> concept id  "ambiguities/BIHAR_MSME_2026-AMB-03"
      -> linked as   [AMB-03](/ambiguities/BIHAR_MSME_2026-AMB-03.md)

This project historically used `[[WIKILINKS]]` keyed on a domain id
(`BIHAR_MSME_2026-AMB-03`) instead, which is not an OKF construct. Both forms
have to be understood during the migration, and exactly one of them written.

Three modules need to turn "a reference to another concept" into "the note it
means": the migrator (rewriting links), the compiler (integrity checks and
graph edges), and the graph retriever (traversal). Putting that resolution
here means there is one definition of what a link means rather than three
that can disagree -- which matters because a silently-unresolved link in a
citation-grounded bot is a citation pointing at nothing.

## Broken links are not errors

The spec is explicit that consumers must tolerate broken links, because a
link to a document nobody has written yet is how an OKF bundle records that
the knowledge is missing. This project keeps that, with one distinction the
compiler makes and this module does not: a broken link in *prose* is
tolerated and reported, while an unresolved id in a *typed domain reference
field* (`eligibility_rule_ids`, `ambiguity_flags`) stays a hard error,
because those get dereferenced into chunk text and would render a citation
that goes nowhere.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from app.okf import vault
from app.okf.frontmatter import OKF_TYPE_TO_ENTITY
from app.okf.okf_spec import concept_id as _concept_id
from app.okf.okf_spec import is_reserved

# [text](target) -- target may not contain whitespace or a closing paren.
MARKDOWN_LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)\s]+)\)")

# The legacy form this migration removes. Kept here, and only here, so
# `verify_okf` can assert that none survives anywhere in the bundle.
WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")

# A markdown footnote reference and its definition, per the spec's per-claim
# attribution convention: `claim.[^src-id]` joined to `sources[].id`.
FOOTNOTE_REF_RE = re.compile(r"\[\^([^\]]+)\]")
FOOTNOTE_DEF_RE = re.compile(r"^\[\^([^\]]+)\]:", re.MULTILINE)


# When two concepts claim the same domain id, which one a bare reference
# means. Ordered most- to least-authoritative claim on a bare identifier.
#
# This is not hypothetical: `CGTMSE` and `TREDS` each exist twice in the
# vault today, once as a Scheme and once as a GlossaryTerm expanding the same
# acronym. Under `[[CGTMSE]]` that ambiguity was invisible -- resolution
# depended on which note happened to sort last. All three real references
# ("see X for the fee", "see X for MSME-facing eligibility", "RBI's X
# Guidelines") mean the scheme, so a GlossaryTerm ranks last: an abbreviation
# expansion is the weakest claim on a bare acronym, not a genuine rival
# meaning.
#
# Ambiguities are still recorded in `LinkIndex.duplicate_domain_ids` so they
# stay visible rather than being quietly resolved. After migration the point
# is moot inside the bundle: every written link is a path-derived concept id,
# which cannot collide.
RESOLUTION_PREFERENCE: tuple[str, ...] = (
    "scheme",
    "act",
    "incentive",
    "eligibility_rule",
    "district_classification",
    "district",
    "sector",
    "authority",
    "ambiguity_flag",
    "glossary_term",
)


def _preference(entity_type: str) -> int:
    try:
        return RESOLUTION_PREFERENCE.index(entity_type)
    except ValueError:
        return len(RESOLUTION_PREFERENCE)


@dataclass(frozen=True)
class ConceptRef:
    """One concept in the bundle, addressable by either identifier scheme."""

    concept_id: str      # "ambiguities/BIHAR_MSME_2026-AMB-03"  (OKF identity)
    path: Path           # absolute path on disk
    okf_type: str        # "AmbiguityFlag"
    entity_type: str     # "ambiguity_flag"  (this project's domain vocabulary)
    domain_id: str       # "BIHAR_MSME_2026-AMB-03"
    title: str

    @property
    def link_target(self) -> str:
        """Bundle-absolute link target, which the spec recommends over relative."""
        return f"/{self.concept_id}.md"


class LinkIndex:
    """Resolves any reference form to the concept it means."""

    def __init__(self, refs: Iterable[ConceptRef]) -> None:
        self.by_concept_id: dict[str, ConceptRef] = {}
        self.by_domain_id: dict[str, ConceptRef] = {}
        self.duplicate_domain_ids: dict[str, list[ConceptRef]] = {}

        for ref in refs:
            self.by_concept_id[ref.concept_id] = ref
            existing = self.by_domain_id.get(ref.domain_id)
            if existing is None:
                self.by_domain_id[ref.domain_id] = ref
                continue
            # Two concepts claim one domain id. Record it so it stays
            # visible, and resolve by documented preference rather than by
            # whichever note happened to be walked last.
            bucket = self.duplicate_domain_ids.setdefault(ref.domain_id, [existing])
            bucket.append(ref)
            if _preference(ref.entity_type) < _preference(existing.entity_type):
                self.by_domain_id[ref.domain_id] = ref

    def __len__(self) -> int:
        return len(self.by_concept_id)

    def resolve(self, token: str, *, base: Path | None = None) -> ConceptRef | None:
        """Resolve any of the reference forms this project has ever used.

            "BIHAR_MSME_2026-AMB-03"                    domain id (legacy)
            "[[BIHAR_MSME_2026-AMB-03]]"                wikilink  (legacy)
            "ambiguities/BIHAR_MSME_2026-AMB-03"        concept id (OKF)
            "/ambiguities/BIHAR_MSME_2026-AMB-03.md"    bundle-absolute link
            "./BIHAR_MSME_2026-AMB-03.md"               relative link (needs `base`)

        Returns None for anything unresolvable. Callers decide whether that
        is tolerable; this module takes no position.
        """
        if not token:
            return None
        token = token.strip()

        match = WIKILINK_RE.fullmatch(token)
        if match:
            token = match.group(1).strip()

        # An external URL is not a concept reference.
        if token.startswith(("http://", "https://", "mailto:")):
            return None

        # Strip a fragment: "/a/b.md#section" addresses the same concept.
        token = token.split("#", 1)[0]
        if not token:
            return None

        if token.startswith("/"):
            return self.by_concept_id.get(_concept_id(token.lstrip("/")))

        if token.startswith("./") or token.startswith("../"):
            if base is None:
                return None
            try:
                resolved = (base.parent / token).resolve()
                rel = resolved.relative_to(vault.VAULT_DIR.resolve())
            except (ValueError, OSError):
                return None
            return self.by_concept_id.get(_concept_id(str(rel)))

        if token in self.by_concept_id:
            return self.by_concept_id[token]
        if token.endswith(".md") and _concept_id(token) in self.by_concept_id:
            return self.by_concept_id[_concept_id(token)]
        return self.by_domain_id.get(token)

    def markdown_link(self, token: str, *, text: str | None = None,
                      base: Path | None = None) -> str | None:
        """Render a reference as an OKF markdown link, or None if unresolvable."""
        ref = self.resolve(token, base=base)
        if ref is None:
            return None
        return f"[{text or ref.title}]({ref.link_target})"

    def parse_body_links(self, body: str) -> list[tuple[str, str]]:
        """Every `[text](target)` in a note body, as (text, target) pairs.

        Footnote definitions are not links and are excluded -- `[^id]:` does
        not match the link pattern, but a footnote *reference* immediately
        followed by a parenthesis could, so the check stays explicit.
        """
        return [
            (text, target)
            for text, target in MARKDOWN_LINK_RE.findall(body)
            if not text.startswith("^")
        ]


def _ref_from_note(note: vault.VaultNote, vault_dir: Path) -> ConceptRef | None:
    """Build a ConceptRef from a note, tolerating either frontmatter shape.

    Works before and after the OKF migration: a pre-migration note is keyed
    on `entity_type`, a migrated one on `type`. Being able to read both is
    what lets the migrator build an index of the bundle it is about to
    rewrite.
    """
    fm = note.frontmatter
    okf_type = fm.get("type")
    entity_type = fm.get("entity_type")

    if okf_type in OKF_TYPE_TO_ENTITY:
        entity_type = OKF_TYPE_TO_ENTITY[okf_type]
    elif entity_type:
        from app.okf.frontmatter import ENTITY_TO_OKF_TYPE

        okf_type = ENTITY_TO_OKF_TYPE.get(entity_type, entity_type)
    else:
        return None

    id_field = vault.ID_FIELD.get(entity_type)
    domain_id = str(fm.get(id_field, "") or "").strip() if id_field else ""
    if not domain_id:
        return None

    rel = note.path.relative_to(vault_dir)
    title = str(fm.get("title") or fm.get("name") or fm.get("term") or domain_id)

    return ConceptRef(
        concept_id=_concept_id(str(rel)),
        path=note.path,
        okf_type=str(okf_type),
        entity_type=entity_type,
        domain_id=domain_id,
        title=title,
    )


def build_index(vault_dir: Path = vault.VAULT_DIR,
                notes: Iterable[vault.VaultNote] | None = None) -> LinkIndex:
    """Index every concept document in the bundle.

    Reserved filenames (`index.md`, `log.md`) are skipped: the spec defines
    them as directory listings and change history, not concepts, so they must
    never become link targets.
    """
    if notes is None:
        notes = vault.iter_notes(vault_dir)
    refs = []
    for note in notes:
        if is_reserved(note.path.name):
            continue
        ref = _ref_from_note(note, vault_dir)
        if ref is not None:
            refs.append(ref)
    return LinkIndex(refs)
