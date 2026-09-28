# Bihar MSME Chatbot — OKF + RAG Architecture
## Implementation Specification

| | |
|---|---|
| **Version** | 2.0 (supersedes `RAG_IMPLEMENTATION.md` v1.0 as the live spec) |
| **Status** | Approved for implementation — Phase 0 in progress |
| **Predecessor document** | [`RAG_IMPLEMENTATION.md`](./RAG_IMPLEMENTATION.md) — kept as historical record of the single-document build; every generalization below is anchored against it |
| **Companion document** | [`HANDOFF.md`](../HANDOFF.md) — current phase status and open decisions |

---

## 1. Why this rebuild

The original build was a citation-grounded RAG chatbot over one 27-page draft policy PDF. It already contained the seed of something more general: `policy_data.py` hand-transcribed the policy's incentive table and 21 known drafting defects (AMB-01 … AMB-21; note `RAG_IMPLEMENTATION.md` §2.3 still says 19 — the register grew after that document was written, and the code is authoritative) into Python dataclasses, and the project's own internal engineering doctrine (quoted from an internal roadmap note, never indexed into the bot) already stated the target philosophy:

> *"RAG provides policy knowledge. Rules determine eligibility. Code calculates benefits. The LLM explains and drafts."*

That is the OKF/RAG split, already intended, only implemented for one document. This rebuild:

1. Names that structured-fact layer **OKF (Open Knowledge Framework)** and gives it an explicit schema, independent of any one PDF.
2. Generalizes it from one hardcoded document to a human-editable **Markdown vault** any of ~24 Bihar/central MSME sources can be authored into.
3. Expands the retrieval corpus from 1 source to ~24 (the P0 core + P1 major-scheme tiers of a larger research catalog; P2/P3, another ~44 sources, are explicitly out of scope for this rebuild).
4. Generalizes every module that assumed "one document" — chunking, the ambiguity register, citation formatting, the Coverage Gate, the Numeric Guard — to be source-agnostic from the start.

---

## 2. OKF vs RAG vs OKF+RAG

| Dimension | OKF-only | RAG-only | **OKF + RAG (chosen)** |
|---|---|---|---|
| Best query shape | Exact attribute lookup ("what's the CGTMSE guarantee fee for a small enterprise?") | Narrative/explanatory ("why does the policy require EPF proof?") | Both, plus figure-with-reasoning ("why do I need 10 employees for X?") |
| Grounding | Exact by construction — no LLM in the loop | Depends on Coverage Gate + Numeric Guard catching failures | Exact figures from OKF; narrative still guarded the same way |
| Hallucination risk | None (template answer or "no record") | Present, mitigated not eliminated | Lowest — OKF is ground truth the Numeric Guard checks *against*, not just internal consistency |
| Coverage of "why"/nuance questions | None | Full | Full |
| Coverage of exact numeric questions | Full, instant | Weak — depends on chunking not shearing a number from its cap | Full and fast via the OKF-only sub-path; recoverable via RAG if OKF has no record |
| Cross-source contradiction handling | Detectable automatically at compile time | Invisible — RAG confidently returns whichever chunk ranks highest | Detected at compile time, disclosed at answer time |
| Latency | Milliseconds | Full pipeline: embed → hybrid search → rerank → gate → generate | Milliseconds for OKF-only queries; full pipeline only when narrative is genuinely needed |
| Auditability | Perfect — every field carries `provenance` | Citation-level only | Both: page citation and exact structured field + verification status |
| Maintainability at 24+ sources | Scales cleanly — one vault note per fact | No structural place to store "the fact," only text containing it | Vault is single source of truth; RAG chunks are derived, regenerable |

**Why not OKF-only or RAG-only:** the original single-document build already proved both halves necessary on its own — RAG-only cannot express 19 real policy ambiguities or "why" questions; OKF-shaped structure was already required to keep the §7.9 incentive table's rates from being sheared from their caps by naive chunking. That table-atom explosion *was* an OKF record, just undeclared. This rebuild makes the split explicit and lets it hold across many sources instead of one.

---

## 3. OKF entity schema

Frozen in `backend/app/okf/schemas.py` (Pydantic models). Every entity carries a shared `Provenance` block:

```yaml
provenance:
  source_id: CGTMSE_SCHEME_GUIDELINES   # FK into config/sources.yaml
  source_url: "https://www.cgtmse.in/Content/Documents/Scheme-Guidelines.pdf"
  source_document_version: "Revised-2024-01"
  fetch_date: "2026-08-14"
  fetch_method: pdf_download             # html_scrape | pdf_download | api | manual
  extraction_method: hand_transcribed
  page_or_section_ref: "Chapter III, para 3.2, Table 2"
  verification_status: verified          # verified | unverified | superseded | disputed
  verified_by: "soumyasharma2402@gmail.com"
  verified_at: "2026-08-15"
  checksum: "sha256:1a2b3c…"              # detects silent source drift on re-fetch
```

Entity types (full fields in `schemas.py`, folder mapping in `data/okf_vault/README.md`):

- **Scheme** — top-level program container. Generalizes the hardcoded `POLICY_ID`/`POLICY_VERSION` constants.
- **Incentive** — generalizes `IncentiveRow`. Carries `category_rates[]`, each with verbatim `rate_text` (typos preserved, never corrected) plus a normalized `rate_value`/`cap_value`.
- **EligibilityRule** — generalizes the §9 "guiding principles" clauses.
- **Authority** — generalizes hardcoded "DIC"/helpline strings.
- **District** + **DistrictClassification** — deliberately split entities, so two sources can disagree on a district's region/category without collision. This is the AMB-01 (BIPP/BIIPP) defect class, made structural instead of accidental.
- **Sector** — generalizes the four separate flat lists (`HIGH_PRIORITY_SECTORS`, `PRIORITY_SECTORS`, `EMERGING_INDUSTRIES`, `NEGATIVE_LIST`).
- **GlossaryTerm** — a `definitions[]` list keyed by `scheme_id`, **not** a flat dict, because the same term can legitimately mean different things under different schemes (§7, Risk 3).
- **AmbiguityFlag** — generalizes `AmbiguityEntry`, namespaced per source, with new `scope` (`single_source`/`cross_source`) and new issue types (`cross_source_contradiction`, `stale_source`, `citation_ambiguity`).
- **Act / LegalProvision** — new, for MSMED Act 2006 / Udyam Registration's statutory basis.

---

## 4. The Markdown vault (OKF authoring layer)

`data/okf_vault/` — numbered folders, one fact per `.md` file, YAML frontmatter + prose + `[[wikilinks]]`. Folder guide and full authoring instructions live in `data/okf_vault/README.md`; blank per-entity-type templates live in `data/okf_vault/_templates/`.

**Compiler** (`backend/app/okf/compiler.py`, **not built yet — Phase 1**): will parse every vault note, validate frontmatter against `schemas.py`, verify every `ref(...)` field and `[[wikilink]]` resolves to a real entity (unresolved links fail the compile — a CI gate, not a warning), cross-check every fact against the staged raw source artifact under `data/raw/<source_id>/`, diff against the previous compile to flag changed figures, then emit two artifacts from one parse: a structured OKF JSON record under `data/okf_compiled/<entity_type>/<id>.json`, and a RAG-ready chunk fed into the existing `backend/app/ingestion/chunk.py` pipeline.

> ⚠️ **Implementation trap the existing code already learned the hard way.** The source-cross-check must compare **figure tokens** (percentages, rupee amounts, counts) extracted per field and normalized for whitespace — **not** whole-string containment of `rate_text`. `backend/app/ingestion/verify_policy_data.py` documents why: the source PDF wraps sentences across table cells and page breaks, so exact phrase adjacency is not preserved and a whole-sentence substring check fails on correct data. Reuse that module's `FIGURE_PATTERN` approach rather than reinventing it. (Note the file is `verify_policy_data.py` — there is no `policy_data_validate.py`.)

The existing single PDF's content migrates into vault notes via a **scripted** migration from `policy_data.py`'s `INCENTIVE_TABLE`, `RESIDUAL_INCENTIVES`, `GUIDING_PRINCIPLES`, the five sector/cluster lists, `ABBREVIATIONS` and `AMBIGUITY_REGISTER` — not hand-retyped — which both seeds the vault and proves the compiler against data whose correctness is already independently verified today.

---

## 5. Router: OKF vs RAG vs hybrid at query time

`backend/app/policy/intents.py` gains a second classification dimension alongside its existing intent (`greeting`/`grievance`/`calculation_request`/`policy_qa`):

```python
@dataclass
class QueryUnderstanding:
    language: str
    intent: str
    is_hinglish: bool
    retrieval_mode: str      # "okf_lookup" | "rag_narrative" | "hybrid"
    okf_matches: list[str]   # entity_ids matched against an in-memory OKF alias index
```

- **OKF-only** (new Tier 1 in `api/chat.py`'s response ladder, between cache and the existing abstain tier): entity alias + attribute keyword match, no explanatory language. Template answer with exact `rate_text` and citation; retrieval, reranking, and the Coverage Gate are skipped entirely.
- **RAG-only**: no OKF match, or explanatory language present ("why," "explain," "how does"). Existing pipeline, unchanged.
- **Hybrid**: OKF match **and** explanatory/conditional language. OKF supplies the exact figure as a header; full RAG retrieval still runs for surrounding conditions/narrative — a moderate extension of the small-to-big parent-expansion logic already used informally for the §7.9 table atoms.
- OKF match with no data for the specific slot asked (e.g., an unclassified district) falls through to RAG rather than answering nothing.

**Guard generalization:**
- **Numeric Guard** (`generation/guards.py`) becomes an OR: a figure passes if verbatim in retrieved text (today's behavior) **or** in the OKF record cited (new).
- **New `okf_consistency_guard`**: if a synthesized answer's figure disagrees with the OKF record it cites, block and fall back to the deterministic OKF quote.
- **Coverage Gate** bypassed on OKF-only hits (binary lookup, not a confidence question); gains a `by_source_type` threshold dimension in `config/thresholds.yaml` (structured PDF / scraped HTML / API — reranker score distributions differ by source register).
- **Citations** gain a source prefix: `[S1] MSME-2026 §7.9 Item 1 · Capital Subsidy · Micro · p.18` / `[S2] CGTMSE §3.2 · Guarantee Fee · Small`.

---

## 6. Dataset acquisition pipeline

Source registry: `config/sources.yaml` (24 entries: 9 P0 + 15 P1, see file for the full list). Each entry: `source_id`, `url`, `fetch_strategy` (`html_scrape`/`pdf_download`/`api`/`manual`), `tier`, `blocked`, `manual_fallback_instructions`, `refresh_cadence`, plus fetch-history fields the acquisition pipeline (Phase 2, `backend/app/acquisition/`, not built yet) will populate.

**A manual download lands at the identical staging path an automated fetch would use** (`data/raw/<source_id>/<fetch_date>.*`), with the identical checksum/registry stamp — every downstream step reads only from this uniform location and never branches on acquisition method. ~40% of the 24 registered sources are pre-flagged `blocked: true` from prior manual research and start as `manual_pending`, not as failures.

**Compliance gate (enforced).** 9 of the 24 sources carry an automated `fetch_strategy` (8 `html_scrape`, 1 `pdf_download`), and no source's robots.txt or terms of use has been reviewed yet. The acquisition runner must therefore **refuse** an automated fetch for any source where `compliance_checked` is not `true` or `robots_txt_status` is not `allowed`, skipping and reporting it rather than fetching. Manual downloads are exempt, since a person retrieving a public document in a browser is not automated access. Every registered source fails this gate by default as of Phase 0, which is intentional: clearing it is a per-source human review that sets both fields, not a code change. The `license_notes` in the registry are explicitly placeholders and are not licensing determinations.

---

## 7. Model/embedding stack

**Unchanged: BGE-M3 encoder + bge-reranker-v2-m3 + Qdrant local mode.** Nothing about 1→24 sources changes this case — corpus size stays modest (a few thousand chunks at most), the cross-lingual requirement is unchanged, and the stack is already proven in this exact repo. Re-indexing with the generalized multi-source payload schema (§8) is required; re-benchmarking the encoder/reranker choice is not.

**Generation LLM — recommend evaluating a hosted Claude model (e.g. Sonnet 5)** as the `hosted` provider option, alongside keeping Ollama as the local/offline default, given the system prompt's 8 strict absolute rules (citation-forced, never-compute, verbatim figures, bilingual, ambiguity disclosure) — an instruction-density regime where model choice affects reliability most, and the existing `LLMProvider` abstraction makes this a config-only swap. **Open question, not resolved here:** whether a hosted API is acceptable for the generation step of a public government-facing bot is a compliance call, not a technical one — see `HANDOFF.md` Open questions.

---

## 8. Multi-source corpus changes

`Chunk` (`backend/app/ingestion/chunk.py`) and the Qdrant payload move from file-level constants (`POLICY_ID`, `POLICY_VERSION`, `POLICY_STATUS`) to per-chunk fields: `source_id`, `scheme_id`, `source_version`, `source_status`, and a new `okf_entity_id` linking every RAG chunk back to the OKF record it was compiled from.

The ambiguity register moves from hardcoded Python (`backend/app/policy/ambiguity_register.py`) to vault notes under `data/okf_vault/08_ambiguities/`, namespaced per source. Ambiguity detection at multi-source scale needs **two distinct automated passes**, which are often conflated and must not be:

**(a) Contradiction pass** (`issue_type: cross_source_contradiction`) — diffs OKF records sharing a natural key across schemes and flags *disagreeing values*: same district with differing region classification, same glossary term with differing scheme-specific definitions, matched incentive names with differing rates. This finds conflicts between records that both exist.

**(b) Completeness pass** (`issue_type: scope_gap` / `missing_rate`) — checks compiled records against **reference sets**: all 38 Bihar districts classified, every incentive carrying a rate for every enterprise category it claims to cover, every scheme having at least one eligibility rule. This finds records that are *absent*, which pass (a) structurally cannot detect — there is nothing to diff against a missing record.

Reference sets live in `data/okf_vault/_reference/` (see its `README.md`). They are closed universes drawn from authoritative external registers, never from the policy being checked; they are validation inputs only and are never compiled into OKF records or indexed into RAG. `bihar_districts.yaml` is the first one.

The completeness *check* is not new — `verify_policy_data.py` already asserts the Araria gap against `BIHAR_ALL_38_DISTRICTS`, a constant that has always lived in `policy_data.py`. The reference set was verified set-identical to it. What the layer adds is a source-attributed universe with naming-variant aliases that the compiler can apply to **any** source, rather than one hardcoded Python constant serving one policy. It remains `verification_status: unverified` because neither copy carries a URL or official document reference; attaching a real Government of Bihar citation is Phase 2 work, flagged in the file.

The existing register proves why both are needed. **AMB-01** (BIPP/BIIPP naming plus a 2025/2026 year mismatch, `external_dependency`, advisory) is contradiction-shaped. **AMB-20** (`missing_rate`, **blocking**) is not: Annexure I categorises only 37 of Bihar's 38 districts, omitting Araria entirely, so an enterprise there has no determinable capital-subsidy rate. That defect was originally found by diffing Annexure I against the official district list — a completeness check. Only pass (b) can rediscover it.

Auto-emitted entries from either pass default to `severity: advisory` — never auto-promoted to `blocking` — a human must escalate. AMB-20's blocking status was a human judgement and would stay one.

---

## 9. Phased build sequence

| Phase | Work | Exit criterion |
|---|---|---|
| **0** — Schema lock | OKF entity schemas frozen (`backend/app/okf/schemas.py`); vault skeleton + templates (`data/okf_vault/`); reference-set layer (`data/okf_vault/_reference/`); source registry skeleton with the compliance gate (`config/sources.yaml`); this document | Schema reviewed; vault skeleton committed — **this phase** |
| **1** — Compiler proof-of-concept | Scripted migration of `policy_data.py` into ~30 vault notes; build `compiler.py` | Compiler emits OKF JSON + RAG chunks from the migrated vault; existing eval doesn't regress |
| **2** — Acquisition pipeline, 9 P0 sources | Fetcher framework (`backend/app/acquisition/`) incl. the compliance gate; per-source robots/ToS review; replace `bihar_districts.yaml` with the official register; run against the 9 P0 sources | 9/9 P0 sources staged (scraped or manual), checksummed, registry-stamped; no automated fetch ran against an unreviewed source |
| **3** — Vault authoring at P0 scale | Author vault notes for the 9 P0 sources' highest-value facts | Compiler green on all P0 content; spot-check 20 random compiled facts |
| **4** — Ambiguity detection + Qdrant migration | Both detection passes (contradiction + completeness, §8); migrate `Chunk`/payload to per-chunk fields; re-index | Contradiction pass rediscovers AMB-01; **completeness pass rediscovers AMB-20 (the missing Araria classification)** — a blocking defect, so this is the gating check |
| **5** — Router + guard generalization | `retrieval_mode` routing; new OKF-deterministic tier; OR-guard against OKF; `okf_consistency_guard`; Coverage Gate `by_source_type` | Existing golden set unchanged; new OKF-lookup eval slice passes with correct source tags |
| **6** — Scale to full P1 (~24 sources total) | Repeat acquisition + authoring + compile + index | All P0+P1 sources compiled and indexed |
| **7** — UI + eval harness | Source-tag citations, OKF-vs-RAG badge; populate `eval/` | Golden set runs in CI |
| **8** — Hardening | Adversarial suite, rate limits, audit log, CI gates | All gates green |

See `HANDOFF.md` for live phase status.

---

## 10. Risks specific to multi-source generalization

1. **Conflicting numbers between two live government sources for the same fact.** Never silently prefer "newer" or "higher authority" — mandatory dual-value disclosure whenever an entity has an open `cross_source_contradiction`.
2. **Staleness skew across sources with very different refresh needs.** `last_fetched_at`/`refresh_cadence` must propagate into the answer itself, not stay internal metadata — a source past its own refresh window triggers a staleness disclosure.
3. **Same term, different meaning across policies.** A flat glossary dict actively creates wrong-source-conflation bugs at scale — mitigated by `GlossaryTerm.definitions[]` keyed per scheme, enforced against the router's inferred scheme at generation time.
4. **Acquisition as a recurring operational liability**, not a one-time migration — ~40% of sources need manual intervention; ownership and cadence per source must be explicit or the staleness mechanism degrades into ignored banners.

These risks did not exist in `RAG_IMPLEMENTATION.md` §15 because they only emerge at multi-source scale; that document's risk list (table-shearing, coverage-gate miscalibration, draft-notification timing) still applies unchanged.
