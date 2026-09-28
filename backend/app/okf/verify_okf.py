"""Verify the vault is a conformant Google OKF v0.2 bundle.

Conformance per the spec is deliberately a low bar:

  1. every non-reserved `.md` file has parseable YAML frontmatter, and
  2. that frontmatter carries a non-empty `type`.

Checked here, plus the stricter house rules this project adds on top,
because a citation-grounded bot needs more than portability:

  3. the bundle-root `index.md` declares `okf_version`.
  4. every `sources[]` entry has the spec-required `resource`.
  5. no legacy `[[wikilink]]` survives anywhere -- frontmatter or body.
  6. no legacy `entity_type:` key survives.
  7. every footnote reference `[^x]` has a matching `sources[].id`, so
     per-claim attribution actually joins to something.
  8. broken prose links are reported, and fail only if their count GREW
     against the committed baseline. The spec says a broken link means
     knowledge nobody has written yet and consumers must tolerate it, so
     this is tolerated -- but bounded, and never invisible.

Run:  python -m app.okf.verify_okf
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

from app.okf import links as links_mod
from app.okf import vault
from app.okf.frontmatter import OKF_TYPE_TO_ENTITY
from app.okf.okf_spec import OKF_VERSION, OKFDocument, trust_tier

BASELINE_PATH = vault.COMPILED_DIR / "okf_baseline.json"


def _load_baseline() -> dict:
    if not BASELINE_PATH.exists():
        return {}
    try:
        return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def main() -> None:
    failures: list[str] = []
    notes = vault.iter_notes()
    index = links_mod.build_index(notes=notes)

    if not notes:
        failures.append("no concept documents found in the bundle")

    # 3. Bundle root declares the spec version.
    root_index = vault.VAULT_DIR / "index.md"
    if not root_index.exists():
        failures.append("bundle root index.md is missing")
    else:
        raw = root_index.read_text(encoding="utf-8")
        parts = raw.split("---", 2)
        front = yaml.safe_load(parts[1]) if len(parts) > 2 else {}
        declared = (front or {}).get("okf_version")
        if str(declared) != OKF_VERSION:
            failures.append(
                f"bundle root index.md declares okf_version {declared!r}, "
                f"expected {OKF_VERSION!r}"
            )

    tiers: dict[str, int] = {}
    broken_links: list[str] = []

    for note in notes:
        name = note.path.relative_to(vault.VAULT_DIR)
        fm = note.frontmatter

        # 1 + 2. Conformance.
        try:
            doc = OKFDocument.model_validate(fm)
        except Exception as exc:  # pydantic ValidationError and friends
            failures.append(f"{name}: not a conformant OKF v0.2 document -- {exc}")
            continue
        if doc.type not in OKF_TYPE_TO_ENTITY:
            failures.append(
                f"{name}: type {doc.type!r} is not one this project produces "
                f"(known: {', '.join(sorted(OKF_TYPE_TO_ENTITY))})"
            )
        tiers[trust_tier(doc)] = tiers.get(trust_tier(doc), 0) + 1

        # 4. Spec-required field on every provenance entry.
        for i, entry in enumerate(doc.sources):
            if not entry.resource:
                failures.append(f"{name}: sources[{i}] has no resource")

        # 5 + 6. No legacy constructs.
        if "entity_type" in fm:
            failures.append(f"{name}: legacy `entity_type:` key survives")
        if links_mod.WIKILINK_RE.search(note.body):
            failures.append(f"{name}: legacy [[wikilink]] survives in the body")
        if links_mod.WIKILINK_RE.search(yaml.safe_dump(fm, allow_unicode=True)):
            failures.append(f"{name}: legacy [[wikilink]] survives in frontmatter")

        # 7. Footnote attribution must join to a real source id.
        source_ids = {e.id for e in doc.sources if e.id}
        defined = set(links_mod.FOOTNOTE_DEF_RE.findall(note.body))
        for label in set(links_mod.FOOTNOTE_REF_RE.findall(note.body)):
            if label in defined:
                continue
            if label not in source_ids:
                failures.append(
                    f"{name}: footnote [^{label}] matches no sources[].id and has "
                    f"no definition in the body"
                )

        # 8. Broken prose links -- counted, not fatal.
        for text, target in index.parse_body_links(note.body):
            if target.startswith(("http://", "https://", "mailto:")):
                continue
            if index.resolve(target, base=note.path) is None:
                broken_links.append(f"{name}: [{text}]({target})")

    baseline = _load_baseline()
    allowed = int(baseline.get("broken_links", 0))
    if len(broken_links) > allowed:
        failures.append(
            f"broken prose links grew from {allowed} to {len(broken_links)}. "
            f"OKF tolerates broken links (they mean not-yet-written knowledge), "
            f"so these are allowed -- but bounded. Write the missing document, "
            f"or update the baseline in {BASELINE_PATH.name} deliberately.\n    "
            + "\n    ".join(broken_links[:10])
        )

    if index.duplicate_domain_ids:
        # Not fatal: concept ids are path-derived and cannot collide, so the
        # bundle itself is unambiguous. Worth surfacing because a bare
        # domain-id reference from outside the bundle still has to choose.
        print(
            f"NOTE: {len(index.duplicate_domain_ids)} domain id(s) claimed by more "
            f"than one concept, resolved by documented preference: "
            f"{sorted(index.duplicate_domain_ids)}"
        )

    if failures:
        for f in failures[:40]:
            print(f"FAIL: {f}")
        if len(failures) > 40:
            print(f"... and {len(failures) - 40} more")
        print(f"\n{len(failures)} failure(s).")
        sys.exit(1)

    tier_text = ", ".join(f"{n} {t}" for t, n in sorted(tiers.items()))
    print(
        f"PASS: {len(notes)} concept document(s) conform to Google OKF v"
        f"{OKF_VERSION}; bundle root declares the version; every sources[] entry "
        f"carries a resource; no [[wikilink]] or entity_type: survives; every "
        f"footnote resolves; {len(broken_links)} broken prose link(s) "
        f"(baseline {allowed}). Trust tiers: {tier_text}."
    )


if __name__ == "__main__":
    main()
