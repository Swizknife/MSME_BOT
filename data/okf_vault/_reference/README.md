# Reference sets

Canonical lists the **completeness pass** checks compiled OKF records against.

These are not OKF entities and not facts *from* a policy. They are the
closed universes a policy's coverage is measured against: the full set of
Bihar districts, the full set of enterprise categories, and so on. A fact
that is simply *absent* cannot be found by the contradiction pass, which
diffs records that disagree — there is nothing to diff. It is found by
checking compiled records against one of these lists and reporting what is
missing.

## Why this exists (the defect that motivated it)

`AMB-20` in the pre-OKF ambiguity register: the Bihar MSME Policy 2026's
Annexure I categorises only **37 of Bihar's 38 districts** into Region A/B.
Araria is absent from both lists, so an enterprise there has no defined
capital-subsidy region and therefore no determinable rate. That defect is
`severity: blocking`.

It was found by diffing Annexure I against the official district list. A
contradiction-only implementation of ambiguity detection would silently
miss it, because Araria has no record to disagree with.

**Prior art, and what is actually new here.** That check already exists for
the single-source build: `backend/app/ingestion/verify_policy_data.py`
asserts `BIHAR_ALL_38_DISTRICTS - (Region A ∪ Region B) == {"Araria"}`, and
`BIHAR_ALL_38_DISTRICTS` has been in `policy_data.py` all along. So the
completeness *idea* is not new and was not missing. What this folder adds is
making the universe a first-class, source-attributed artifact the vault
compiler can consume for **any** source, rather than a Python constant
hardcoded for one policy, with the naming-variant handling that multi-source
comparison needs.

## Rules

1. A reference set is a **closed universe**, not a policy's claim about one.
   Its provenance is an authoritative external register (a state government
   district list, a statutory definition), never the policy being checked.
2. Reference sets are **never** compiled into OKF records and are **never**
   indexed into RAG. They are validation inputs only.
3. When a completeness check fails, the compiler emits an `ambiguity_flag`
   with `issue_type: scope_gap` (or `missing_rate` where the gap makes a
   figure undeterminable) at `severity: advisory`. Promotion to `blocking`
   is a human judgement, as AMB-20's was.

## Current sets

| File | Universe | Used to check |
|---|---|---|
| `bihar_districts.yaml` | All 38 districts of Bihar | Every district has a `DistrictClassification` under each scheme that claims statewide district-linked benefits |

## Adding a set

Create a `.yaml` file with a `reference_set_id`, a `provenance` block
naming the authoritative external source, and a `members` list. Then add a
row to the table above and wire the check into the completeness pass
(`backend/app/okf/compiler.py`, Phase 1 — not built yet).
