"""One-shot, idempotent migration of the vault to Google OKF v0.2.

Converts every authored note from this project's original frontmatter shape
to a conformant Open Knowledge Format v0.2 document, and moves the bundle
into the layout the spec's identity rule implies.

    python -m app.okf.migrate_to_okf_v02 --dry-run   # read the diff first
    python -m app.okf.migrate_to_okf_v02

What changes, and why:

  frontmatter   `entity_type: incentive` -> `type: Incentive`, the singular
                `source:` mapping -> a `sources:` list, verification fields
                -> `verified:`/`status:`. Domain fields ride along as
                extension keys, which the spec explicitly permits and
                requires consumers to preserve. See frontmatter.py.

  links         `[[BIHAR_MSME_2026-AMB-03]]` -> a markdown link
                `[BIHAR_MSME_2026-AMB-03](/ambiguities/....md)`, which is
                what OKF actually defines. `cross_references:` holds bare
                concept ids for machine adjacency.

                Link TEXT is deliberately the original domain id rather than
                the target's title. It reads slightly worse in one or two
                places, but it makes this migrator and migrate_policy_data.py
                produce byte-identical output without either needing to look
                a title up -- and verify_migration.py asserts exactly that
                byte-identity, so a divergence here would surface as a
                confusing failure far from its cause.

  folders       Numbered prefixes are dropped: OKF derives a concept's
                identity from its bundle-relative path, so `02_incentives/X`
                would bake a human sort-order prefix into a public
                identifier and into every link that points at it. Ordering
                moves to the generated root `index.md`, where the spec puts
                it.

  templates     Move OUT of the bundle, to data/okf_templates/. They are
                `.md` files with frontmatter, so inside the bundle
                conformance would demand a non-empty `type` on each -- making
                ten blank skeletons look like real concepts to any OKF
                consumer and to the graph builder. An exclusion list would
                work; moving them is simply true.

  index.md      Generated per directory, plus the bundle root, which also
                carries `okf_version: "0.2"`. `index.md` and `log.md` are the
                only two filenames the spec reserves.

Safe to re-run: a note that already has `type:` and no `entity_type:` is
left untouched, so a partial run can simply be finished.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.okf import frontmatter as F
from app.okf import links, vault

REPO_ROOT = Path(__file__).resolve().parents[3]
TEMPLATES_DEST = REPO_ROOT / "data" / "okf_templates"

# Old numbered folder -> OKF bundle folder.
FOLDER_RENAMES: dict[str, str] = {
    "00_sources": "sources",
    "01_schemes": "schemes",
    "02_incentives": "incentives",
    "03_eligibility_rules": "eligibility-rules",
    "04_authorities": "authorities",
    "05_districts": "districts",
    "06_sectors": "sectors",
    "07_glossary": "glossary",
    "08_ambiguities": "ambiguities",
    "09_acts": "acts",
}

# Reading order for the generated root index.md. The numbered prefixes used
# to encode this; the spec puts it here instead.
BUNDLE_ORDER: list[str] = [
    "schemes", "incentives", "eligibility-rules", "authorities",
    "districts", "sectors", "glossary", "ambiguities", "acts", "sources",
]

FOLDER_BLURB: dict[str, str] = {
    "schemes": "Top-level programmes and policies: the container every other fact hangs off.",
    "incentives": "What a scheme offers, per enterprise category, with the rate quoted verbatim.",
    "eligibility-rules": "Conditions a claimant must satisfy, one clause per note.",
    "authorities": "Bodies that administer, sanction or receive claims.",
    "districts": "Districts, and each source's classification of them, kept as separate concepts so two sources can disagree without collision.",
    "sectors": "Sector lists, by classification (high priority, priority, emerging, negative list, heritage cluster).",
    "glossary": "Terms and abbreviations, defined per scheme rather than globally, because the same term can mean different things under different schemes.",
    "ambiguities": "Known defects in the source documents: missing rates, contradictions, undefined terms. The bot discloses these instead of guessing.",
    "acts": "Statutory instruments the schemes rest on.",
    "sources": "Per-source provenance notes.",
}


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _generated_ids() -> set[tuple[str, str]]:
    """(entity_type, id) pairs that migrate_policy_data.py can regenerate.

    Only these get `generated.by: process:migrate_policy_data`, which is what
    that script's --clean guard keys on. Getting this set from the script
    itself rather than from a hand-maintained list means the two cannot drift
    and a hand-authored note cannot be mislabelled as reproducible.
    """
    from app.okf import migrate_policy_data as mpd

    records = (
        mpd.build_scheme() + mpd.build_incentives() + mpd.build_eligibility_rules()
        + mpd.build_districts() + mpd.build_sectors() + mpd.build_glossary()
        + mpd.build_ambiguities()
    )
    return {(entity_type, entity_id) for entity_type, entity_id, _fm, _body in records}


def target_index(notes: list[vault.VaultNote]) -> links.LinkIndex:
    """A link index keyed on where each note WILL live, not where it is now.

    Building it from current paths produces links into the old numbered
    folders (`/08_ambiguities/...`), which are about to stop existing. Every
    link in the bundle would then be broken the moment the move completes --
    and because OKF tolerates broken links by design, nothing would fail
    loudly. The bundle would simply, silently, lose all 73 of its
    cross-references.
    """
    refs = []
    for note in notes:
        ref = links._ref_from_note(note, vault.VAULT_DIR)
        if ref is None:
            continue
        destination = new_path_for(note)
        rel = destination.relative_to(vault.VAULT_DIR)
        refs.append(
            links.ConceptRef(
                concept_id=links._concept_id(str(rel)),
                path=destination,
                okf_type=ref.okf_type,
                entity_type=ref.entity_type,
                domain_id=ref.domain_id,
                title=ref.title,
            )
        )
    return links.LinkIndex(refs)


def new_path_for(note: vault.VaultNote) -> Path:
    rel = note.path.relative_to(vault.VAULT_DIR)
    parts = list(rel.parts)
    if parts and parts[0] in FOLDER_RENAMES:
        parts[0] = FOLDER_RENAMES[parts[0]]
    return vault.VAULT_DIR.joinpath(*parts)


def rewrite_body_links(body: str, index: links.LinkIndex) -> str:
    """`[[TARGET]]` -> `[TARGET](/concept/id.md)`, leaving unresolvable ones alone.

    An unresolvable wikilink is left verbatim rather than silently deleted:
    losing a reference is worse than carrying one that needs a human to look
    at it, and verify_okf reports any that survive.
    """

    def replace(match) -> str:
        token = match.group(1).strip()
        ref = index.resolve(token)
        if ref is None:
            return match.group(0)
        return f"[{token}]({ref.link_target})"

    return links.WIKILINK_RE.sub(replace, body)


# Frontmatter fields holding bare references for machine adjacency rather
# than prose. Their items become concept ids; every other string becomes a
# markdown link.
REFERENCE_LIST_FIELDS = frozenset({"cross_references"})


def rewrite_frontmatter(value: Any, index: links.LinkIndex, key: str | None = None) -> Any:
    """Rewrite every wikilink anywhere in a frontmatter structure.

    Recursive because references are not only top-level: `Act.sections[]` and
    `GlossaryTerm.definitions[]` are lists of mappings whose prose fields can
    carry a link. Handling only `cross_references` left two wikilinks alive
    inside `sections[].text_summary`, which would have survived the migration
    into a bundle that is supposed to contain none.

    Verbatim source text never contains a wikilink -- it is this project's own
    annotation syntax -- so there is no risk of rewriting a quoted figure.
    """
    if isinstance(value, dict):
        return {k: rewrite_frontmatter(v, index, k) for k, v in value.items()}
    if isinstance(value, list):
        return [rewrite_frontmatter(v, index, key) for v in value]
    if isinstance(value, str):
        if key in REFERENCE_LIST_FIELDS:
            return rewrite_reference_list([value], index)[0]
        return rewrite_body_links(value, index)
    return value


def rewrite_reference_list(values: Any, index: links.LinkIndex) -> Any:
    """`cross_references: ["[[X]]"]` -> `["folder/X"]` (bare concept ids)."""
    if not isinstance(values, list):
        return values
    out = []
    for item in values:
        if not isinstance(item, str):
            out.append(item)
            continue
        token = item.strip()
        match = links.WIKILINK_RE.fullmatch(token)
        if match:
            token = match.group(1).strip()
        ref = index.resolve(token)
        out.append(ref.concept_id if ref else item)
    return out


def migrate_note(
    note: vault.VaultNote,
    index: links.LinkIndex,
    generated: set[tuple[str, str]],
) -> tuple[dict, str] | None:
    """Returns (okf_frontmatter, body), or None if already migrated."""
    fm = note.frontmatter
    if "type" in fm and "entity_type" not in fm:
        return None  # idempotent: already OKF

    entity_type = note.entity_type
    if not entity_type:
        return None

    payload = rewrite_frontmatter(
        {k: v for k, v in fm.items() if k != "entity_type"}, index
    )

    id_field = vault.ID_FIELD.get(entity_type, "id")
    entity_id = str(payload.get(id_field, "") or "")
    is_generated = (entity_type, entity_id) in generated

    okf = F.to_okf_frontmatter(
        entity_type,
        payload,
        generated_by="process:migrate_policy_data" if is_generated else None,
    )
    return okf, rewrite_body_links(note.body, index)


def _write_index(directory: Path, entries: list[tuple[str, str]], *,
                 is_root: bool, dry_run: bool) -> None:
    """Generate an `index.md` -- the spec's directory listing for a folder."""
    name = directory.name if not is_root else "Bihar MSME Knowledge Bundle"
    lines = ["---"]
    if is_root:
        lines += [
            'okf_version: "0.2"',
            "type: Bundle",
            f'title: "{name}"',
            'description: "Structured, provenance-tracked facts about Bihar and '
            'central MSME schemes, authored as a Google Open Knowledge Format bundle."',
        ]
    else:
        lines += [
            "type: Index",
            f'title: "{name}"',
            f'description: "{FOLDER_BLURB.get(directory.name, "Concept documents.")}"',
        ]
    lines += ["---", "", f"# {name}", ""]

    if is_root:
        lines += [
            "This directory is a [Google Open Knowledge Format]"
            "(https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md)"
            " v0.2 bundle.",
            "",
            "Every file is one concept: YAML frontmatter for the structured facts,"
            " Markdown prose for what a person needs to know, and ordinary markdown"
            " links to related concepts. A compiler validates it and emits both"
            " machine-readable records and the chunks the retrieval layer searches.",
            "",
            "Edit the Markdown. Never edit `data/okf_compiled/`, which is"
            " regenerated, or the search index directly.",
            "",
        ]

    for path_text, blurb in entries:
        lines.append(f"- [{path_text}]({path_text})" + (f" — {blurb}" if blurb else ""))
    lines.append("")

    content = "\n".join(lines)
    if dry_run:
        print(f"  [index] would write {directory.relative_to(vault.VAULT_DIR) or '.'}/index.md")
        return
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "index.md").write_text(content, encoding="utf-8", newline="\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="print what would change and write nothing")
    args = parser.parse_args()
    dry = args.dry_run

    notes = vault.iter_notes()
    index = target_index(notes)
    generated = _generated_ids()

    print(f"{len(notes)} note(s) in {vault.VAULT_DIR}")
    print(f"{len(index)} concept(s) indexed; "
          f"{len(generated)} regenerable from policy_data.py")
    if index.duplicate_domain_ids:
        print(f"note: {len(index.duplicate_domain_ids)} domain id(s) claimed by more "
              f"than one concept, resolved by documented preference: "
              f"{sorted(index.duplicate_domain_ids)}")

    migrated = skipped = 0
    moves: list[tuple[Path, Path]] = []

    for note in notes:
        result = migrate_note(note, index, generated)
        if result is None:
            skipped += 1
            continue
        okf, body = result
        destination = new_path_for(note)

        if dry:
            rel_old = note.path.relative_to(vault.VAULT_DIR)
            rel_new = destination.relative_to(vault.VAULT_DIR)
            arrow = f"{rel_old} -> {rel_new}" if rel_old != rel_new else str(rel_old)
            print(f"  {arrow}")
            print(f"      type: {okf['type']}"
                  f"   status: {okf.get('status')}"
                  f"   verified: {len(okf.get('verified', []))}"
                  f"   sources: {len(okf.get('sources', []))}"
                  f"   generated: {okf.get('generated', {}).get('by', '-')}")
        else:
            vault.write_note(destination, okf, body)
            if destination != note.path:
                moves.append((note.path, destination))
        migrated += 1

    if not dry:
        for old, _new in moves:
            old.unlink()
        # Drop now-empty numbered folders.
        for old_folder in FOLDER_RENAMES:
            path = vault.VAULT_DIR / old_folder
            if path.exists() and not any(path.iterdir()):
                path.rmdir()
            elif path.exists() and not any(p for p in path.iterdir() if p.suffix == ".md"):
                shutil.rmtree(path)

    # Templates out of the bundle.
    templates = vault.VAULT_DIR / "_templates"
    if templates.exists():
        if dry:
            print(f"  [templates] would move {templates} -> {TEMPLATES_DEST}")
        else:
            TEMPLATES_DEST.parent.mkdir(parents=True, exist_ok=True)
            if TEMPLATES_DEST.exists():
                shutil.rmtree(TEMPLATES_DEST)
            shutil.move(str(templates), str(TEMPLATES_DEST))

    # The old hand-written vault README becomes the bundle's reserved index.
    legacy_readme = vault.VAULT_DIR / "README.md"
    if legacy_readme.exists() and not dry:
        legacy_readme.unlink()

    # Generate index.md per concept directory, then the bundle root.
    if not dry:
        directories = sorted(
            {p.parent for p in vault.VAULT_DIR.rglob("*.md")
             if p.parent != vault.VAULT_DIR and "_reference" not in p.parts}
        )
        for directory in directories:
            entries = sorted(
                (p.name, "") for p in directory.glob("*.md") if p.name != "index.md"
            )
            _write_index(directory, entries, is_root=False, dry_run=False)

        root_entries = [
            (f"{folder}/index.md", FOLDER_BLURB.get(folder, ""))
            for folder in BUNDLE_ORDER
            if (vault.VAULT_DIR / folder).exists()
        ]
        _write_index(vault.VAULT_DIR, root_entries, is_root=True, dry_run=False)

    print(f"\n{'would migrate' if dry else 'migrated'}: {migrated}")
    print(f"already OKF (skipped): {skipped}")
    if dry:
        print("\nDry run -- nothing written. Re-run without --dry-run to apply.")
    else:
        print(f"moved: {len(moves)}")
        print("Next: python -m app.okf.verify_okf && python -m app.okf.verify_compile")


if __name__ == "__main__":
    sys.exit(main())
