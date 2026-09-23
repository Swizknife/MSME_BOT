"""Verify the OKF compile, and prove it did not change the index.

Two independent checks:

  1. COMPILE HEALTH -- the vault compiles with zero schema, reference or
     figure-cross-check errors, and the ambiguity passes ran.

  2. INDEX PARITY -- the chunks emitted from the migrated BIHAR_MSME_2026
     vault content are equivalent to the chunks the pre-OKF pipeline
     produced (data/chunks/msme_policy_2026.chunks.json). This is the real
     Phase 1 exit criterion: the whole migration is only trustworthy if
     routing the existing, already-verified policy through the vault
     yields the same retrievable units. Chunks are compared by chunk_id on
     the semantic fields; the new multi-source fields (source_id,
     scheme_id, okf_entity_id, ...) are expected additions and are ignored
     here.

     Scoped to scheme_id == BIHAR_MSME_2026 deliberately: the legacy index
     only ever covered that one source, so once a second source (e.g.
     TReDS, CGTMSE) is authored into the vault, its chunks have no legacy
     counterpart to compare against by design, not by omission -- comparing
     them would fail this check for a reason that has nothing to do with
     migration correctness.

Run:  python -m app.okf.verify_compile
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from app.okf import chunk_from_okf
from app.okf.compiler import compile_vault

REPO_ROOT = Path(__file__).resolve().parents[3]
LEGACY_JSON = REPO_ROOT / "data" / "chunks" / "msme_policy_2026.chunks.json"

# Fields that must match exactly between the legacy and OKF-emitted chunk.
PARITY_FIELDS = [
    "chunk_type", "text", "parent_text", "clause_path",
    "page_start", "page_end", "enterprise_category", "district_region",
    "incentive_type", "cross_references", "ambiguity_flags", "visibility",
]


def main() -> None:
    failures: list[str] = []

    # --- 1. compile health -------------------------------------------------
    result = compile_vault()
    if result.errors:
        for e in result.errors[:20]:
            failures.append(f"compile error: {e}")
    total_records = sum(len(v) for v in result.records.values())
    if total_records == 0:
        failures.append("compile produced zero records")
    if result.figures_checked == 0:
        failures.append("no figure tokens were cross-checked against source text")

    # The answer ladder branches on `Incentive.status == "rate_unstated"` to
    # produce the "conditions stated, rate never stated" disclosure. Google's
    # OKF v0.2 also defines a `status` key (draft|stable|deprecated), so the
    # migration renames this one on disk. If the two were ever collapsed the
    # branch would stop firing and the bot would begin quoting
    # "NO RATE/AMOUNT SPECIFIED IN SOURCE" as though it were a rate -- and
    # NOTHING else here would catch it, because chunk text does not depend on
    # this field. Hence an explicit assertion.
    rate_unstated = [
        i["incentive_id"] for i in result.records.get("incentive", [])
        if i.get("status") == "rate_unstated"
    ]
    if len(rate_unstated) < 2:
        failures.append(
            f"expected at least 2 incentives with status 'rate_unstated' "
            f"(Revival Package and Interest Subsidy), found {len(rate_unstated)}: "
            f"{rate_unstated}. If Incentive.status was merged into OKF's "
            f"draft|stable|deprecated, the Tier 1 rate-unstated disclosure is "
            f"now silently dead."
        )

    # EligibilityRule.ambiguity_flags must be a real typed field, not
    # re-derived from cross_references. The old derivation assumed every
    # cross_reference was an ambiguity flag and leaked a scheme id and an act
    # id into a live answer the first time that assumption broke.
    rules_with_flags = [
        r for r in result.records.get("eligibility_rule", []) if r.get("ambiguity_flags")
    ]
    if not rules_with_flags:
        failures.append(
            "no eligibility_rule carries ambiguity_flags; the typed field is "
            "either unpopulated or was dropped, which silently disables "
            "ambiguity disclosure on guiding-clause answers"
        )

    completeness = [f for f in result.findings if f["issue_type"] == "scope_gap"]
    araria = [f for f in completeness if "Araria" in (f.get("missing_members") or [])]
    if not araria:
        failures.append(
            "completeness pass did NOT rediscover the Araria district gap (AMB-20). "
            "This is the gating check: a contradiction-only implementation misses it."
        )
    for f in result.findings:
        if f["severity"] != "advisory":
            failures.append(
                f"auto-detected finding {f['id']} has severity {f['severity']!r}; "
                f"auto-emitted findings must start advisory and be promoted by a human"
            )

    # --- 2. index parity ---------------------------------------------------
    other_sources_chunk_count = 0
    if not LEGACY_JSON.exists():
        failures.append(f"legacy chunk file not found: {LEGACY_JSON}")
    else:
        legacy = {c["chunk_id"]: c for c in json.loads(
            LEGACY_JSON.read_text(encoding="utf-8"))["chunks"]}
        all_new = {c.chunk_id: c for c in chunk_from_okf.build_chunks(result)}
        # Scope to the one scheme the legacy index actually covers -- see
        # this module's docstring on why comparing other sources' chunks
        # against it would be a false failure, not a real one.
        new = {cid: c for cid, c in all_new.items() if c.scheme_id == "BIHAR_MSME_2026"}
        other_sources_chunk_count = len(all_new) - len(new)

        missing = sorted(set(legacy) - set(new))
        added = sorted(set(new) - set(legacy))
        for cid in missing:
            failures.append(f"parity: chunk present in legacy index but NOT emitted: {cid}")
        # `added` BIHAR_MSME_2026 chunks are NOT a failure -- this check's
        # invariant is "nothing the legacy index had is ever lost or
        # altered," not "the vault may never grow." It was strict set
        # equality through Phase 1 because that phase only migrated
        # EXISTING policy_data.py content and nothing should have differed.
        # Once real gap-closing content is deliberately authored (e.g. an
        # Interest Subsidy incentive record, added after a query about
        # "interest subsidy" mis-retrieved Capital Subsidy instead --
        # AMB-03 already documents that Interest Subsidy has no rate and
        # no incentive-table row at all, so nothing in the legacy migration
        # could have caught it), that's growth, not corruption. Reported
        # for visibility, never as a failure.
        if added:
            print(f"INFO: {len(added)} new BIHAR_MSME_2026 chunk(s) beyond the original "
                  f"migration (expected growth, not a parity failure): {added}")

        for cid in sorted(set(legacy) & set(new)):
            old, cur = legacy[cid], new[cid]
            for fname in PARITY_FIELDS:
                a, b = old.get(fname), getattr(cur, fname)
                if a != b:
                    failures.append(
                        f"parity: {cid}.{fname} differs\n    legacy: {a!r}\n    okf   : {b!r}"
                    )

        # The new fields must actually be populated, or the multi-source
        # migration is cosmetic. Checked across ALL emitted chunks, not just
        # the BIHAR_MSME_2026 subset -- every source must carry its own
        # identity, not just the originally-migrated one.
        for cid, cur in all_new.items():
            if not cur.source_id or not cur.scheme_id or not cur.source_status:
                failures.append(f"parity: {cid} is missing multi-source identity fields")

        # A second real scheme_id among the emitted chunks is itself a
        # sanity check: if additional vault content was authored but never
        # made it into a chunk (e.g. a typo in scheme_id breaking the
        # meta() lookup in chunk_from_okf.py), other_sources_chunk_count
        # silently staying 0 is the symptom -- surfaced in the pass message
        # below so it's visible, not just checked implicitly by absence of
        # a failure.

    if failures:
        for f in failures[:40]:
            print(f"FAIL: {f}")
        if len(failures) > 40:
            print(f"... and {len(failures) - 40} more")
        print(f"\n{len(failures)} failure(s).")
        sys.exit(1)

    legacy_count = len(json.loads(LEGACY_JSON.read_text(encoding="utf-8"))["chunks"])
    print(
        f"PASS: {total_records} OKF records compiled with no schema/reference errors; "
        f"{result.figures_checked} figure tokens verified against staged source text; "
        f"{legacy_count} BIHAR_MSME_2026 chunks reproduced at full parity with the pre-OKF "
        f"index (plus per-chunk source identity); {other_sources_chunk_count} additional "
        f"chunk(s) from other sources, all carrying source identity; completeness pass "
        f"independently rediscovered the Araria gap; {len(result.findings)} auto-finding(s), "
        f"all advisory."
    )


if __name__ == "__main__":
    main()
