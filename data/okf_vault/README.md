# OKF Vault

This folder is the **Open Knowledge Framework (OKF)** source of truth: every
structured fact this chatbot can state with certainty (an incentive rate, an
eligibility condition, a district's region classification, a scheme's
issuing authority, a glossary definition, a known ambiguity in a source
document) is authored here as one Markdown file with YAML frontmatter.

**Do not hand-edit anything outside this folder to add or change a fact.**
`data/okf_compiled/` is generated output (Phase 1 — the compiler that
produces it does not exist yet); the Qdrant index under `data/qdrant_local/`
is built from compiled vault content. Both are regenerated from this vault,
never edited directly.

## How to add or edit a fact

1. Copy the matching template from `_templates/` into the right numbered
   folder for its entity type.
2. Fill in the frontmatter. Every field is documented in the template's
   comments. `source.*` fields are mandatory — a fact with no traceable
   source (URL, fetch date, who verified it) does not belong in the vault.
3. Write the prose body: what the fact means in plain language, and
   `[[wikilinks]]` to any related facts (a district's classification links
   to the scheme that asserts it; an incentive links to the eligibility
   rules that govern it).
4. Run the compiler (`python -m app.okf.compile`, once it exists — Phase 1)
   to validate frontmatter, check wikilinks resolve, and cross-check the
   fact's `rate_text`/`condition_text` against the staged raw source
   document. A failed validation blocks the compile; it does not silently
   ingest a bad fact.

## Folder guide

| Folder | Entity type | Generalizes (from the pre-OKF codebase) |
|---|---|---|
| `00_sources/` | Source registry anchor notes | — new |
| `01_schemes/` | Scheme | hardcoded `POLICY_ID`/`POLICY_VERSION` constants |
| `02_incentives/` | Incentive | `IncentiveRow` in `policy_data.py` |
| `03_eligibility_rules/` | EligibilityRule | §9 "guiding principles" clauses |
| `04_authorities/` | Authority | hardcoded "DIC"/helpline strings in `intents.py` |
| `05_districts/` | District, DistrictClassification | `district_region` payload field |
| `06_sectors/` | Sector | `HIGH_PRIORITY_SECTORS`/`PRIORITY_SECTORS`/`EMERGING_INDUSTRIES`/`NEGATIVE_LIST` |
| `07_glossary/` | GlossaryTerm | flat `ABBREVIATIONS` dict |
| `08_ambiguities/` | AmbiguityFlag | `AmbiguityEntry` in `policy_data.py` |
| `09_acts/` | Act / LegalProvision | — new |

Full entity field definitions live in `backend/app/okf/schemas.py`. The
architecture rationale for why the vault is Markdown rather than raw JSON,
and how it compiles into both structured records and RAG chunks, is in
`docs/OKF_RAG_IMPLEMENTATION.md` §§2–3.

## Status

Vault skeleton only — no content authored yet. Content authoring starts in
Phase 3 of the rebuild plan, after the compiler (Phase 1) and the
acquisition pipeline for the 9 P0 sources (Phase 2) exist. See `HANDOFF.md`
at the repo root for current phase status.
