# Handoff — Bihar MSME Chatbot (OKF + RAG)

**Last updated:** 2026-09-23 · **By:** Soumya Sharma (soumyasharma2402@gmail.com), with Claude

## What this project is

A citation-grounded chatbot over Bihar's MSME policy and scheme landscape, built as two cooperating layers: a deterministic structured-fact store (OKF) authored as a Markdown vault, and RAG over the full source text for narrative questions. See `docs/OKF_RAG_IMPLEMENTATION.md` for the full architecture rationale and `README.md` to run it.

## Where this came from

Started as a single-document RAG chatbot over one 27-page draft policy PDF (see git history / `docs/RAG_LEARNING_GUIDE.md` for that build's real challenges and fixes — the table-shearing bug, the Hinglish gap, the citation-ordering bug — all still relevant since this rebuild generalizes that pipeline rather than replacing it). Rebuilt into OKF+RAG starting 2026-09-23 to (a) stop hand-encoding one document's facts in Python and make structured knowledge an explicit, curatable, provenance-tracked layer, and (b) scale the corpus from 1 source to ~24 Bihar/central MSME sources without repeating the single-document special-casing.

## Current status

- [x] **Phase 0 — OKF schema locked, vault skeleton created** *(this session, 2026-09-23)*
  - `backend/app/okf/schemas.py` — frozen Pydantic models for all 10 OKF entity types
  - `data/okf_vault/` — numbered folder skeleton + one frontmatter template per entity type under `_templates/`
  - `data/okf_vault/_reference/` — reference-set layer the completeness pass validates against; `bihar_districts.yaml` (38 districts) is the first set, currently **unverified** and pending replacement with the official register in Phase 2
  - `config/sources.yaml` — registry skeleton for all 24 P0+P1 sources (nothing fetched yet — `fetch_strategy`/`blocked` flags set from prior manual research only), now carrying an **enforced compliance gate** that blocks automated fetching of any source whose robots.txt/terms have not been reviewed
  - `docs/OKF_RAG_IMPLEMENTATION.md` — live architecture spec, supersedes `docs/RAG_IMPLEMENTATION.md`
  - `README.md` rewritten; this file created
- [x] **Phase 1 — Compiler built and proven against migrated existing content** *(2026-09-23)*
  - `backend/app/okf/migrate_policy_data.py` — scripted, re-runnable migration of `policy_data.py` into **238 vault notes** (1 scheme, 23 incentives, 24 eligibility rules, 38 districts + 37 classifications, 67 sectors, 27 glossary terms, 21 ambiguities). Generated, never hand-retyped, so the existing figure verification carries over intact and the source's own typos survive verbatim.
  - `backend/app/okf/vault.py` — frontmatter parse/serialize, wikilink extraction, reference-set loading
  - `backend/app/okf/compiler.py` — validate against schemas, resolve every reference and wikilink, cross-check figure tokens against staged source text, run both ambiguity passes, emit records + chunks
  - `backend/app/okf/chunk_from_okf.py` — RAG chunk emission carrying per-chunk `source_id`/`scheme_id`/`source_status`/`okf_entity_id`
  - `backend/app/okf/verify_compile.py` — compile health + strict index parity
  - **Exit criterion met:** 238 records compile with zero schema/reference errors, 109 figure tokens verified against the source PDF text, and all **85 chunks reproduce at full parity** with the pre-OKF index on every semantic field, plus the new source-identity fields. The completeness pass independently rediscovered the Araria gap.
  - **Negative-tested**, so the checks are not vacuous: corrupting a figure, breaking a reference, and deleting a district classification each fail the verifier, and deleting Patna's classification auto-emits a `patna_gap` chunk — the gap handling is data-driven, not hardcoded to Araria.
  - Not wired into the live app at the time: the running backend still read `data/chunks/msme_policy_2026.chunks.json`. Superseded by Phase 4/5 below, same day.
- [ ] Phase 2 — Acquisition pipeline built; 9 P0 sources staged
- [ ] Phase 3 — P0 sources authored into the vault
- [x] **Phase 4 — Multi-source Qdrant migration** *(2026-09-23)*
  - `backend/app/ingestion/embed_index.py` now indexes `data/chunks/okf.chunks.json` (OKF-compiled, per-chunk `source_id`/`scheme_id`/`source_status`/`source_type`/`okf_entity_id`), not the legacy single-source file, which is left on disk untouched and unread by anything.
  - Live Qdrant collection rebuilt: 85 points, full OKF payload, confirmed via `client.count()`.
  - The ambiguity-detection passes from Phase 1's compiler (contradiction + completeness) are what feed this index; no separate migration step was needed for those.
- [x] **Phase 5 — Router (OKF/RAG/hybrid) + guard generalization** *(2026-09-23)*
  - `backend/app/okf/store.py` — read accessor + alias index over compiled records (incentive name matching, enterprise-category detection)
  - `backend/app/policy/intents.py` — `QueryUnderstanding` gained `retrieval_mode` (`okf_lookup`/`rag_narrative`/`hybrid`), `okf_matches`, `okf_category`; `classify_retrieval_mode()` is the router
  - `backend/app/api/chat.py` — new **Tier 1 (`okf_lookup`)**: a deterministic template answer straight from the OKF record, skipping retrieval/rerank/Coverage Gate/LLM entirely (measured: **0.02–0.13s**, vs. ~20–110s for an LLM tier on this CPU-only dev setup). **Hybrid injection**: the OKF record is prepended as `[S1]` ahead of retrieved narrative chunks for `hybrid`-mode queries. Citations now carry a scheme short-name prefix (`MSME-2026 > ...`).
  - `backend/app/generation/guards.py` — new `okf_consistency_guard`: checks a synthesized answer's figures against the ONE resolved OKF ground-truth slot, not just "appears somewhere in context" (which `numeric_guard` already did and still does). This catches a failure mode `numeric_guard` structurally cannot: a table-atom's `parent_text` legitimately contains all three enterprise categories' rates side by side, so an LLM swapping in the wrong category's figure passes context-containment trivially.
  - `backend/app/retrieval/coverage_gate.py` + `config/thresholds.yaml` — `by_source_type` threshold structure, keyed on the top-ranked chunk's `source_type`. Currently a mechanism only: all traffic is `structured_policy_pdf` today, so no differentiated calibration exists yet.
  - **A real bug was found and fixed during end-to-end testing**, not just unit tests: the first version of Tier 1 treated *any* blocking ambiguity attached to an incentive as grounds to replace the whole answer. A plain "capital subsidy for a micro enterprise" question was answered with the Araria-district disclosure (AMB-20) instead of the actual 30%/25% rate, because AMB-20 happens to be attached to the Capital Subsidy incentive record even though it only concerns one specific district the query never mentioned. Fixed to key off `incentive.status == "rate_unstated"` (set at migration time from genuine no-rate-in-source findings like the Revival Package/AMB-09), which correctly distinguishes "this incentive has nothing to quote" from "this incentive has a disclosed caveat somewhere." All ambiguities, blocking or advisory, are still disclosed after the rate either way — unchanged from what the pre-OKF Tier 4 path already did.
  - **Verified, not just implemented**: the consistency guard was tested in isolation (passes on a correct answer, fails on a category-swapped figure, fails on a fabricated one) and then end-to-end with the LLM call mocked to return a wrong figure — confirmed the fallback actually replaces it with the correct deterministic quote, not just that the guard function returns the right boolean.
  - **Known limitation, not yet fixed**: the OKF router's incentive-name matching is English-keyword-only. A Hindi query (e.g. "सूक्ष्म उद्यम को कितनी पूंजी सब्सिडी मिलेगी?") never resolves to `okf_lookup` or `hybrid` and always falls through to `rag_narrative` -- which still answers correctly via the existing cross-lingual RAG pipeline, just without the Tier 1 speedup. Fixing this means either a bilingual alias table or reusing BGE-M3 for a lightweight semantic match, neither built yet.
- [x] **Prototype-scale real dataset integration (2026-09-23)** — proves the corpus can actually grow past one source, ahead of building the full Phase 2 pipeline
  - **What was fetched, for real, not simulated.** A single manual-equivalent `WebFetch` call per source (not the automated acquisition runner, which stays unbuilt and still gated — see below) against 4 P0 sources: **TReDS** (RBI guidelines page — full success), **CGTMSE** (homepage — partial success: a real fee figure, no full fee slab), **MSME Samadhaan** (homepage — full success, including the statutory delayed-payment interest rule), **MSMED Act 2006** (failed honestly: the only PDF link found is a scanned image with no text layer; a second attempt via India Code returned HTTP 403; recorded as `partial_failure_scanned_pdf_no_text_layer` in `config/sources.yaml`, not silently dropped). Two of these four sources — CGTMSE and MSME Samadhaan — were marked `blocked: true` in the original prior research; `WebFetch` succeeded where the earlier scripted checks reportedly failed, which is itself worth knowing for Phase 2.
  - **11 new vault notes authored by hand** from the real fetched content: 3 new `Scheme`s (TReDS, CGTMSE, MSME Samadhaan), 2 `Act` stubs (MSMED Act 2006 — deliberately marked `unverified` and section number `"unconfirmed"` rather than guessed; Payment & Settlement Systems Act 2007), 1 new `Incentive` (CGTMSE's guarantee fee, 0.37% p.a. minimum), 3 new `EligibilityRule`s (TReDS operator capital requirement; the delayed-payment 3×-bank-rate interest penalty; the 90-day MSEFC resolution window), 1 new `AmbiguityFlag` (CGTMSE's incomplete fee-slab gap), plus a `BIHAR_MSME_2026-INTEREST-SUBSIDY` incentive record — not from an external source, authored to close a gap the corpus already had (see below).
  - **The compiler's own validation gate caught two real authoring mistakes** (missing `fetch_method` on both new Act notes' section blocks) before anything was written — exactly the "hard gate, not a warning" behavior it was designed for.
  - **A real defect was found integrating the second source and fixed at the root**: every chunk-rendering template in `chunk_from_okf.py` hardcoded the citation header `"MSME Policy 2026 (Draft)"` regardless of which document a fact actually came from — the first TReDS/CGTMSE/Samadhaan chunks were citing the wrong document entirely. Fixed with a `doc_label(scheme_id)` helper, branching to preserve Bihar's exact legacy wording (parity-critical) while giving every other scheme its own real name. The sector/district/glossary renderers were **not** given the same fix, because no non-Bihar record of those types exists yet — flagged explicitly in the module docstring as a latent gap for whenever one does.
  - **A second real defect, also found by testing, not review**: `_chunk_id()` inserted `source_document_version` into the id raw, unslugified — harmless for Bihar's compact `"draft-v1"`, but a new source's prose-style version string (`"CGTMSE homepage, fetched 2026-09-23"`) produced a chunk_id containing literal spaces and a comma. Fixed narrowly (only whitespace/commas become underscores) specifically so Bihar's `"draft-v1"` stayed byte-identical and the parity check kept passing.
  - **A third real defect, a live crash**: `Source.page_start`/`page_end` are required `int` fields, and `_make_sources()` used `.get("page_start", 0)` — which only defaults when the key is *absent*, not when it's present as an explicit `None`, which every web-sourced chunk has (no PDF page number). A CGTMSE query crashed with a Pydantic validation error. Fixed there and in two more places carrying the identical pattern: `_extractive_answer` (would have silently printed `"p.None"` to a user instead of crashing) and `_doc_order`'s sort key (a **latent crash**, not yet triggered — `sorted()` on a tuple containing `None` next to an `int` raises `TypeError` in Python, and a mixed-source top-6 retrieval set will now routinely produce exactly that mix).
  - **`_extractive_answer` also generalized**: it prefixed every answer with `"According to the draft policy"` unconditionally — false for a non-draft, non-Bihar source. Now names the actual scheme via `okf_store.get_scheme()`.
  - **`verify_compile.py`'s parity semantics evolved on purpose, twice this pass**: first, scoped the byte-for-byte comparison to `scheme_id == BIHAR_MSME_2026` only (a second source's chunks have no legacy counterpart *by design*, not by omission — comparing them was a false failure). Second, changed the invariant from "the Bihar chunk set is exactly what it always was" to "nothing the legacy index ever had is lost or altered" — new, deliberately-authored Bihar content (the Interest Subsidy incentive, below) is now expected growth, reported via an `INFO:` line, never a failure.
  - **A genuine cross-source query was tested end-to-end and initially got the wrong answer**, which is the most important finding of this pass: *"What is the interest subsidy rate for a micro enterprise?"* mis-retrieved Capital Subsidy's real 30%/25% figures — not a hallucination (every figure was genuinely grounded in a real chunk), but a retrieval-relevance failure that `numeric_guard` structurally cannot catch, since it only checks that figures appear in the shown context, not that the right topic was retrieved. Root cause: Bihar's own §7.9 incentive table has no "Interest Subsidy" row at all (`policy_data.py`'s `INCENTIVE_TABLE` never had one — this is a genuine, pre-existing gap in the source policy, already documented as `AMB-03`), so the OKF router had nothing to match against and the query fell through to plain RAG, where dense retrieval ranked the wrong incentive highest. **Fixed by authoring the missing `Incentive` record** (`status: rate_unstated`, linking to `AMB-03`) so the router now catches it. Measured before/after on the identical query:

    | | Before | After |
    |---|---|---|
    | Tier | `extractive` (RAG) | `okf_lookup` |
    | Latency | 27.9s | 0.08s |
    | Answer | Capital Subsidy's real 30%/25% figures — wrong topic, confidently stated | AMB-03's clarification-required disclosure — correct |

  - **The disambiguation this content was designed to test passed on the first real run**: *"If my buyer does not pay me on time, what interest am I entitled to?"* correctly retrieved MSME Samadhaan's real 3×-bank-rate statutory penalty (5.4s, `extractive` tier), never conflating it with Bihar's unrelated, undefined "Interest Subsidy." Two different real facts, both containing the word "interest," resolved to the right one each time.
  - **A fourth real defect, found via a genuine HTTP round-trip, not a Python function call**: `chunk_from_okf.py`'s eligibility-rule renderer treated *every* `cross_references` wikilink as an ambiguity-flag reference. Bihar's migration only ever put ambiguity flags there, so this was invisible for a year of single-source operation; the first hand-authored rule to use `cross_references` for its real, general-purpose meaning (linking `MSME_SAMADHAAN-DELAYED-PAYMENT-INTEREST` to the `MSME_SAMADHAAN` scheme and the `MSMED_ACT_2006` act) leaked those two identifiers straight into `ambiguity_ids` in a live API response. Fixed by filtering `cross_references` against the actual set of known ambiguity-flag ids rather than assuming the field's contents. **This was caught specifically because testing went through the real FastAPI server via `curl`, not just direct Python calls to `chat()`** — a caution about testing depth worth keeping: two earlier "Internal Server Error" results in this same verification pass turned out to be a stale zombie `uvicorn` process left over from an earlier turn (its `kill` had only terminated a wrapper process, not the actual listener), not a real regression — found by checking `Get-CimInstance Win32_Process`, force-killing the real PIDs, and re-testing against a verified-fresh server before drawing any conclusion either way.
  - **The compliance gate was not weakened.** `config/sources.yaml`'s `compliance_checked: false` gate for automated/recurring scraping is untouched; these were individual, deliberate `WebFetch` calls for prototype content, explicitly logged as `ok_manual_prototype_fetch` (distinct from what the real Phase 2 acquisition runner would record), not the automated pipeline the gate exists to constrain.
- [ ] Phase 6 — Full P1 scale (~24 sources total)
- [ ] Phase 7 — UI updates + eval harness populated
- [ ] Phase 8 — Hardening

*(Update this checklist as phases complete — this is the single place to look to know what state the rebuild is actually in. The app that runs today, end to end, is still the original single-source pipeline described in `docs/RAG_IMPLEMENTATION.md` — Phase 0 only added schema/skeleton files, nothing wired in yet.)*

## Key decisions made (and why)

| Decision | Why |
|---|---|
| OKF is a human-edited Markdown vault, not hand-authored JSON | Non-engineers (policy reviewers) can edit a fact by editing a file; a compiler validates and emits structured data + RAG chunks from the same source |
| Full rebuild, not a bolt-on | Existing single-document modules (`policy_data.py`, `ambiguity_register.py`, `chunk.py`'s file-level constants) don't generalize to multiple sources without changing their shape; patching around them would leave two incompatible fact models |
| Dataset scope = P0 + P1 (~24 sources), not the full ~68-source research catalog | Prove the architecture at a real but bounded multi-source scale before taking on the full catalog's ~40% blocked-portal acquisition cost |
| Automated scraping + documented manual fallback, same downstream pipeline either way | ~40% of target .gov.in portals block scripted fetches (confirmed by prior research); manual downloads must not become a second, divergent code path |
| Embedding/reranking stack (BGE-M3 + bge-reranker-v2-m3 + local Qdrant) kept unchanged | Already proven in this exact repo; corpus size at 24 sources doesn't yet justify a different stack |
| Generation LLM: evaluate hosted Claude alongside existing Ollama/hosted-API abstraction | Strict instruction-following requirements (8 absolute prompt rules); config-only swap given the existing provider abstraction — **not yet decided, needs a compliance answer on hosted LLM + government data (see Open questions)** |

## Open questions — need a decision before certain phases proceed

1. **Is a hosted LLM API acceptable for the generation step of a public government-facing bot**, or must generation also stay fully local/on-prem? Blocks finalizing the Phase 5 default provider.
2. **Who owns re-running acquisition per source, and on what cadence?** Without an owner, the staleness-disclosure mechanism (`docs/OKF_RAG_IMPLEMENTATION.md` §10, risk 2) degrades into banners nobody acts on.
3. **Should P2/P3 sources (the remaining ~44 in the original research catalog) ever be pulled into scope**, or does this project intentionally stop at P0+P1? Affects whether Phase 6+ work should keep the acquisition/vault pipeline generic enough for that, or can start specializing to the 24-source set.
4. **Licensing/robots.txt review per source** — *mechanism now in place, review itself still outstanding.* `config/sources.yaml` carries an enforced compliance gate: the acquisition runner must refuse an automated fetch while `compliance_checked` is false or `robots_txt_status` is not `allowed`. All 24 sources currently fail that gate by design, so Phase 2 cannot scrape anything until a human reviews each of the 9 automated-strategy sources (8 `html_scrape`, 1 `pdf_download`) and sets both fields. The 15 `manual` sources are exempt and can proceed. Who performs that review is still unassigned.

## How to pick this project back up

1. Read `docs/OKF_RAG_IMPLEMENTATION.md` for the architecture, then check the phase checklist above for where things stand.
2. Read `config/sources.yaml` for which sources are registered and their `blocked`/`fetch_strategy` flags (all still unfetched as of this handoff).
3. Read `data/okf_vault/README.md` before authoring any fact by hand.
4. `data/okf_vault/` is the source of truth for structured facts once the compiler exists — never hand-edit `data/okf_compiled/` (it will be regenerated) or the Qdrant index directly.
5. Rebuild the vault and check it at any time:
   ```
   python -m app.okf.migrate_policy_data --clean   # regenerate notes from policy_data.py
   python -m app.okf.compile                        # validate + cross-check + emit
   python -m app.okf.verify_compile                 # compile health + index parity
   ```
6. The live app now actually runs OKF+RAG hybrid, not just single-source RAG. Try it:
   ```
   uvicorn app.main:app --port 8000          # backend
   curl -s -X POST http://localhost:8000/api/chat -H "Content-Type: application/json" \
     -d '{"message":"What capital subsidy does a micro enterprise get?"}'
   # tier should be "okf_lookup", answered in well under a second, no LLM call
   ```
7. Next concrete step is **Phase 2**: the acquisition pipeline under `backend/app/acquisition/`. It must enforce the compliance gate before any automated fetch (see Open question 4), and Phase 2 also owes the reference set a real Government of Bihar citation. Phases 4/5 were pulled forward ahead of Phase 2/3/6 because they prove the OKF+RAG *query-time* architecture end-to-end on the one already-migrated source, which was the highest-uncertainty part of the whole redesign; scaling to more sources (Phase 2/3/6) is now lower-risk repetition of a proven pattern, not open architecture questions.

## Phase 1 schema amendments

Phase 0 froze the entity schemas; Phase 1 found six fields genuinely required for a lossless round-trip, each recorded inline in `schemas.py` with its reason. `Provenance.page_start`/`page_end` (citations need integer pages, not free text), `Incentive.item_no`, `EligibilityRule.section_title`/`letter`, `AmbiguityFlag.local_id`/`page_refs`, and `list_order` on `Sector`, `GlossaryTerm` and `DistrictClassification` (a source's printed list order is part of the source; re-sorting it alphabetically would silently rewrite the annexure).

## Validation notes (2026-09-23)

The Phase 0 artifacts were validated against the actual codebase after being written. Corrections applied, recorded here so they are not silently reintroduced:

- The source cross-check in the compiler must compare **figure tokens**, not whole strings — `backend/app/ingestion/verify_policy_data.py` documents that the PDF wraps sentences across cells/page breaks, so substring matching fails on correct data. (There is no `policy_data_validate.py`; an earlier draft of the architecture doc cited that non-existent filename.)
- Ambiguity detection needs **two** passes, not one. A cross-source contradiction diff cannot find AMB-20 (Araria missing from Annexure I) because that record is absent, not disagreeing — it needs a completeness check against the 38-district reference set. AMB-20 is `blocking`, so this distinction is load-bearing, not academic.
- The ambiguity register has **21** entries, not the 19 quoted in the older spec.
- `RESIDUAL_INCENTIVES` and `HERITAGE_CLUSTERS` had no home in the first schema draft; `Sector.classification_type` gained `heritage_cluster`, and residual incentives map onto `Incentive` with a single `other`-category rate.

### Methodology changes made in response to those flags

Splitting ambiguity detection into two passes and flagging the licensing gap each implied a structural change, not just a wording fix. Both were applied:

- **Reference-set layer added** (`data/okf_vault/_reference/`), giving the completeness pass a source-attributed universe to check against for any source. *Correction to an earlier draft of this note:* the repo was **not** missing a canonical district list. `BIHAR_ALL_38_DISTRICTS` has always been in `policy_data.py`, and `verify_policy_data.py` already performs exactly this Araria check for the single-source build. The new reference set was verified set-identical to it. What is new is that the universe is now a first-class artifact with provenance and naming-variant aliases, consumable for any source, instead of a Python constant hardcoded for one policy. It stays `unverified` because neither copy carries a URL or official document reference.
- **Compliance gate made enforceable** (`config/sources.yaml`, honoured by `backend/app/acquisition/`). The licensing concern was recorded as an open question while 8 sources sat marked for automated fetching, meaning the first run of the acquisition pipeline would have scraped government portals whose terms nobody had read. It is now a hard precondition in the registry that the runner must honour, failing closed for every source by default.

Verified figures behind these notes, for anyone re-checking: 85 chunks total (25 table atoms, 6 residual, 24 guiding clauses, 22 ambiguity notes, 8 reference lists); 37 of 38 districts classified; 21 ambiguity entries, 3 blocking; 8 numbered rules in the system prompt.
