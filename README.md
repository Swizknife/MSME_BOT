# Bihar MSME Chatbot — OKF + RAG

> 👋 **New here, or not from a technical background?**
> Read **[`ONBOARDING.md`](ONBOARDING.md)** first. It explains the entire
> project from zero — what we're building, what RAG and OKF actually are, why
> we use both, and what every file does. This README assumes you already know
> all that and just want to run the thing.

A citation-grounded chatbot answering questions across Bihar's MSME policy and scheme landscape, built on two cooperating layers:

- **OKF** — [Google's **Open Knowledge Format**](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md) **v0.2**, an open specification for representing knowledge as Markdown files with YAML frontmatter. Our vault (`data/okf_vault/`) is a conformant OKF bundle: 249 concept documents holding every structured fact (incentive rates, eligibility rules, district classifications, known defects), each carrying its own provenance and trust tier, compiled into machine-readable records plus a 311-edge concept graph. Answers to exact questions come straight from here — no LLM involved, no hallucination possible.
- **RAG** — retrieval-augmented generation over the full source text, for narrative and "why"/"what conditions" questions the structured layer can't answer on its own.

A router decides per-query which layer (or both) answers, and the concept graph is walked to assemble multi-hop answers no single chunk contains. Retrieval, embedding, and reranking run entirely on a CPU-only local machine and never leave it; the LLM generation step is swappable between a local Ollama model and a hosted API.

- **Explained from scratch, for newcomers:** [`ONBOARDING.md`](ONBOARDING.md)
- **Architecture and design rationale:** [`docs/OKF_RAG_IMPLEMENTATION.md`](docs/OKF_RAG_IMPLEMENTATION.md)
- **Current project status, decisions made, and open questions:** [`HANDOFF.md`](HANDOFF.md)
- **Original single-document RAG build (historical record, still accurate for the retrieval/generation internals this rebuild generalizes):** [`docs/RAG_IMPLEMENTATION.md`](docs/RAG_IMPLEMENTATION.md) and [`docs/RAG_LEARNING_GUIDE.md`](docs/RAG_LEARNING_GUIDE.md)

This README is only about **running it locally**. Commands below are Git Bash (the shell this project was actually built and tested in on Windows); a PowerShell note is added wherever a command genuinely differs.

> **Where this project stands right now:** the vault is a conformant Google OKF v0.2 bundle (249 concepts, 311 graph edges), concept-graph traversal is live, and `/api/chat` serves three genuinely different architectures selectable from a toggle in the UI — `rag` (no structured fact reaches the answer), `okf` (zero vector searches), and `okf_rag` (both, with the graph seeded by retrieval). Four sources are indexed (Bihar MSME Policy 2026, CGTMSE, TReDS, MSME Samadhaan) across 91 chunks. **Not yet built:** the automated dataset acquisition pipeline — `backend/app/acquisition/` is a docstring only, and 20 of the 24 sources registered in `config/sources.yaml` have never been fetched. See `HANDOFF.md` for the live phase checklist and known limitations (the OKF router is English-keyword-only today; a Hindi query still gets a correct answer, just always via full RAG rather than the fast OKF tier).

---

## 1. Prerequisites

| Tool | Version used in development | Check with |
|---|---|---|
| Python | 3.13 | `python --version` |
| Node.js | 22.x | `node --version` |
| npm | 10.x | `npm --version` |
| [Ollama](https://ollama.com/download) | 0.32.x | `ollama --version` |

No GPU is required — everything here is designed to run on CPU. No Docker or Qdrant server is required either: Qdrant runs in **local mode** (an on-disk folder, no separate service — see `backend/app/retrieval/qdrant_local.py`).

You'll need roughly **6–8 GB free disk space** the first time you run this: the embedding model (BGE-M3, ~2.3 GB) and the reranker model (~1.1 GB) download once and are cached under `~/.cache/huggingface`, and at least one Ollama model (2–6 GB depending on which you pick) needs to be pulled.

---

## 2. First-time setup

### 2.1 Backend (Python)

From the repo root:

```bash
cd backend
python -m venv .venv
source .venv/Scripts/activate      # PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

> The `transformers` version in `requirements.txt` is pinned deliberately (`5.15.1`) — a newer major version breaks the reranker's tokenizer loading, and an older one drags in an unrelated TensorFlow/Keras crash on some machines. Don't `pip install --upgrade transformers` without reading `docs/RAG_LEARNING_GUIDE.md` Part 6 first.

### 2.2 Frontend (React + Vite)

From the repo root:

```bash
cd frontend
npm install
```

### 2.3 Ollama (local LLM)

Install Ollama from [ollama.com/download](https://ollama.com/download) if you haven't already, then pull the model this project defaults to:

```bash
ollama pull gemma3:4b
```

`gemma3:4b` was chosen over the smaller/faster `llama3.2:1b` because this project's system prompt carries strict rules (citations, never-do-arithmetic, exact figures, bilingual output, ambiguity disclosure) that a 1B-class model follows unreliably — see `backend/app/generation/llm_provider.py` for the actual benchmark numbers behind that choice, and `docs/OKF_RAG_IMPLEMENTATION.md` §7 for the recommendation to also evaluate a hosted Claude model once the OKF rebuild's generation tier is finalized. If you'd rather use a different model (or a hosted API instead of Ollama entirely), see [§5 Configuration](#5-configuration) below.

Start the Ollama server (skip this if it's already running as a background service):

```bash
ollama serve
```

Leave this running in its own terminal, or run it in the background:

```bash
ollama serve > /tmp/ollama.log 2>&1 &
```

---

## 3. Build the knowledge base (run once)

This is **ingestion** — it reads source documents and builds the searchable index plus the structured OKF store. It does not need to be re-run on every chat message, only the first time (or after a source changes).

### 3.1 Acquire source data *(Phase 2, not built yet)*

```bash
python -m app.acquisition.run_acquisition          # fetches all P0+P1 sources in config/sources.yaml
python -m app.acquisition.run_acquisition --status  # shows what's manual_pending
```

For sources flagged `manual_pending` (see `manual_fallback_instructions` in `config/sources.yaml`), follow the printed instructions, then:

```bash
python -m app.acquisition.register_manual_fetch <source_id>
```

### 3.2 Compile the OKF vault

```bash
python -m app.okf.migrate_policy_data --clean   # regenerate vault notes from policy_data.py
python -m app.okf.compile                        # validate + cross-check + emit records & chunks
python -m app.okf.verify_compile                 # compile health + parity with the existing index
```

`compile` validates all 238 vault notes against the entity schemas, checks every reference and
wikilink resolves, cross-checks each fact's figure tokens against the staged source text, runs the
contradiction and completeness ambiguity passes, and writes `data/okf_compiled/` plus
`data/chunks/okf.chunks.json`.

`verify_compile` additionally asserts the emitted chunks match the pre-OKF index
(`data/chunks/msme_policy_2026.chunks.json`) on every semantic field. That parity check is what
made the migration trustworthy before switching the live index over: the same already-verified
policy, routed through the vault, yields the same retrievable units.

### 3.3 Embed and index (run after every compile)

```bash
# Downloads ~2.3GB the first time -- can take a while depending on your
# connection; see the troubleshooting note below if it times out partway
# through. Embeds and indexes data/chunks/okf.chunks.json into local Qdrant.
python -m app.ingestion.embed_index
```

This is the command that actually builds the running search index — §3.2 only validates and
compiles the vault into chunks, it doesn't embed anything. Re-run this any time `okf.chunks.json`
changes (i.e. after any re-compile).

You should end up with:

```
data/okf_compiled/                          <- structured OKF records (§3.2)
data/chunks/okf.chunks.json                 <- RAG chunks, 85 today (§3.2)
data/qdrant_local/                          <- the live search index (§3.3)
```

### 3.4 The pre-OKF pipeline (historical; superseded by §3.2–3.3 above)

Before the OKF rebuild, ingestion ran as three separate steps directly against
`policy_data.py`, with no vault in between:

```bash
python -m app.ingestion.extract   # PDF -> data/extracted/msme_policy_2026.raw.json
python -m app.ingestion.chunk     # policy_data.py -> data/chunks/msme_policy_2026.chunks.json
```

plus the same `verify_extraction` / `verify_policy_data` / `verify_chunks` checks described in
`docs/RAG_LEARNING_GUIDE.md`. Nothing in the running app reads this pipeline's output anymore, but
`extract.py`'s PDF-to-text extraction and `verify_policy_data.py`'s figure-token cross-check are
still exactly what the OKF compiler's source verification (§3.2) relies on — see
`docs/OKF_RAG_IMPLEMENTATION.md` §4 for how the two connect. Run `verify_policy_data` if you ever
suspect the hand-encoded facts in `policy_data.py` have drifted from the source PDF; that check is
independent of the vault and still the ground-truth verification for that one file.

---

## 4. Run the app

You need **three things running at once**, each in its own terminal: Ollama (§2.3, if not already running), the backend API, and the frontend dev server.

### 4.1 Backend

```bash
cd backend
source .venv/Scripts/activate      # if not already active
uvicorn app.main:app --port 8000
```

Confirm it's up:

```bash
curl http://localhost:8000/health
# {"status":"ok"}
```

> ⚠️ **Qdrant local-mode holds an exclusive file lock.** Only one Python process can have `data/qdrant_local` open at a time. If you ran the ingestion steps in §3 in the same terminal session and it's still "open" somehow, or you try to run a second backend instance, you'll see `RuntimeError: Storage folder ... is already accessed by another instance of Qdrant client`. Make sure any ingestion script has fully exited before starting the server, and don't start a second backend instance against the same `data/qdrant_local` folder.

### 4.2 Frontend

In a new terminal:

```bash
cd frontend
npm run dev
```

Open **http://localhost:5173** in your browser.

### 4.3 First message will be slow — this is expected

The very first chat request pays a one-time cost: loading BGE-M3, the reranker, and (for the first Ollama call) the LLM into memory. Expect the first response to take anywhere from ~20 seconds to over a minute. Every request after that is much faster, since the models stay loaded in the running backend process.

---

## 5. Configuration

Copy the example env file and edit as needed:

```bash
cp config/.env.example backend/.env
```

The most relevant setting is `LLM_PROVIDER` in that file:

| `LLM_PROVIDER` | What it does | When to use it |
|---|---|---|
| `ollama` (default) | Talks to your local Ollama server | Fully local/offline, slower (~10–60s per answer on CPU) |
| `hosted` | Talks to any OpenAI-compatible hosted endpoint (also set `HOSTED_LLM_BASE_URL`, `HOSTED_LLM_API_KEY`, `HOSTED_LLM_MODEL`) | Faster (~2–4s), but retrieved policy text is sent to that external endpoint — see the open question on hosted LLMs + government data in `HANDOFF.md` before defaulting to this for anything beyond local dev/testing |

Retrieval, embedding, and reranking are **always local** regardless of this setting — only the final generation step is swappable. See `backend/app/generation/llm_provider.py`.

Coverage-Gate abstention thresholds live in `config/thresholds.yaml`. They are currently placeholder defaults (`calibrated: false`) — see `docs/RAG_IMPLEMENTATION.md` §10.4 for how they're meant to eventually be tuned against a real evaluation set (`eval/`, not built yet). The file now has a `by_source_type` structure (`default` + per-type overrides), keyed on each chunk's `source_type` — live as a mechanism, but every entry is still the same uncalibrated placeholder since only one source type exists today.

`config/sources.yaml` is the dataset source registry for the OKF+RAG rebuild (24 sources: 9 P0 core + 15 P1 major schemes) — see `docs/OKF_RAG_IMPLEMENTATION.md` §6. It is a registry skeleton right now; nothing has been fetched through it yet (Phase 2).

---

## 6. Verifying it's actually working

Run the backend test suite:

```bash
cd backend
pytest tests/ -q
```

Then try a real end-to-end request without the UI:

```bash
curl -s -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"What capital subsidy does a micro enterprise get?"}'
```

A healthy response has `"tier":"okf_lookup"`, cites `MSME-2026 > Item 1 Capital Subsidy > Micro [OKF]` at page 18, states 30%/25% rates by district region, and returns in well under a second — no LLM call for this one, since it routes through the OKF deterministic tier (`docs/OKF_RAG_IMPLEMENTATION.md` §5). If you get an empty `sources` list and a "not covered" answer for this exact question, the OKF compile or the embed/index step (§3.2–3.3) didn't complete — re-run `python -m app.okf.verify_compile` first to check the compile, then re-run `embed_index`.

Try an explanatory question too, to see the other tiers: `"why do I need 10 employees for the payroll subsidy for a micro enterprise?"` should come back with `"tier":"synthesis"`, an `[S1]` citation tagged `[OKF]`, and take much longer (an LLM call) — this is the hybrid path, where the OKF record supplies the exact figure and full retrieval supplies the surrounding narrative.

---

## 7. Troubleshooting

**`RuntimeError: Storage folder ... already accessed by another instance of Qdrant client`**
Another Python process still has `data/qdrant_local` open. Find and stop it (on Windows: `Get-CimInstance Win32_Process -Filter "CommandLine LIKE '%uvicorn%'"` in PowerShell, then `Stop-Process -Id <id> -Force`) before starting a new one.

**Model download times out partway through (`httpx.ReadTimeout`, `IncompleteSnapshotError`)**
The BGE-M3 download is ~2.3 GB; on a slow or unstable connection a single attempt can time out. Just re-run the same ingestion command — `huggingface_hub` resumes from the partial download rather than starting over. If it keeps failing, try `HF_HUB_DISABLE_XET=1 python -m app.ingestion.embed_index` to fall back to plain HTTP downloads instead of the Xet fast-transfer protocol.

**`AttributeError: XLMRobertaTokenizer has no attribute prepare_for_model`**
You have an incompatible `transformers` version installed (this happens if something else in your environment upgraded it past the pin). Run `pip install "transformers==5.15.1"` inside the backend venv. See `docs/RAG_LEARNING_GUIDE.md` Part 6, challenge #2, for the full story on why this exact version matters.

**Port already in use (`8000` or `5173`)**
Something from a previous run is still bound to that port. On Windows, find it with `Get-CimInstance Win32_Process -Filter "CommandLine LIKE '%uvicorn%'"` (or `%vite%`) in PowerShell and stop it, rather than picking a different port — the frontend's CORS config and API base URL both assume `8000`/`5173`.

**Chat responses never come back / hang forever with `LLM_PROVIDER=ollama`**
Confirm Ollama is actually running: `curl http://localhost:11434/api/version`. If that fails, run `ollama serve`. Also confirm the model is pulled: `ollama list` should show `gemma3:4b` (or whichever model you set `OLLAMA_MODEL` to).

**Frontend shows "Could not reach the assistant backend"**
The backend isn't running, isn't on port 8000, or crashed. Check the terminal running `uvicorn` for a traceback.

**`python -m app.acquisition.run_acquisition` — command not found**
The acquisition pipeline is Phase 2 and doesn't exist yet (`backend/app/acquisition/` is a stub). Check `HANDOFF.md` for current phase status.

**`python -m app.okf.compile` fails with schema or reference errors**
A vault note's frontmatter is invalid, or a `[[wikilink]]`/id reference points at a note that doesn't exist. The error names the note and field. This is a hard gate by design: a dangling reference indexed into the bot becomes a citation that goes nowhere. If you edited notes by hand and want to start over, `python -m app.okf.migrate_policy_data --clean` regenerates them.

**`python -m app.okf.compile` fails with "figure ... not found in staged source text"**
A figure in a vault note doesn't appear in the extracted text of the page it claims to come from. Either the fact is wrong, or its `source.page_start` is wrong. Note the check compares figure *tokens* with a one-page tolerance, because the source wraps table cells across page boundaries.

---

## 8. Project layout

```
backend/app/
  acquisition/   source registry, fetchers, manual-fallback staging          (Phase 2, skeleton only)
  okf/           vault.py (parse/write notes), schemas.py (entity models),
                 migrate_policy_data.py, compiler.py, chunk_from_okf.py,
                 verify_compile.py, store.py (query-time read accessor)      (Phases 0-1, live)
  ingestion/     PDF -> text -> structured facts (policy_data.py)           (feeds okf/migrate_policy_data.py;
                                                                                embed_index.py now reads okf.chunks.json)
  retrieval/     query encoding, hybrid search, reranking, coverage gate     (runs per request; coverage_gate.py has
                                                                                by_source_type thresholds, Phase 5)
  generation/    prompts, LLM provider, post-generation guards               (runs per request; okf_consistency_guard
                                                                                added Phase 5)
  policy/        intent + retrieval_mode routing, ambiguity register        (classify_retrieval_mode() is the
                                                                                OKF/RAG/hybrid router, Phase 5)
  api/           the FastAPI /api/chat endpoint -- tiered response ladder    (Tier 1 okf_lookup + hybrid injection
                                                                                added Phase 5)
frontend/src/
  api/chat.ts              typed client for /api/chat
  components/              ChatMessage, SourceCitations, TierBadge, ChatInput, StarterQuestions
  App.tsx                  ties it together: language toggle, draft banner, chat window
docs/
  OKF_RAG_IMPLEMENTATION.md   the live architecture spec for the OKF+RAG rebuild
  RAG_IMPLEMENTATION.md       the original single-document spec (historical, still accurate for retrieval/generation internals)
  RAG_LEARNING_GUIDE.md       a from-scratch RAG tutorial using the original build as the example
config/
  .env.example             copy to backend/.env
  thresholds.yaml           Coverage Gate thresholds (currently uncalibrated defaults)
  sources.yaml              OKF+RAG dataset source registry (24 sources, registry skeleton -- nothing fetched yet)
data/
  raw/                     the source PDFs (today: one policy PDF; will become one folder per source)
  extracted/               PDF text extraction, feeds the OKF compiler's source cross-check
  chunks/                  okf.chunks.json (live, 85 chunks, indexed) + msme_policy_2026.chunks.json
                            (legacy, kept only for the parity check, nothing reads it for serving)
  qdrant_local/            the live vector index -- 85 points, OKF payload (rebuilt by embed_index.py)
  okf_vault/               human-edited Markdown OKF facts -- 238 notes migrated from policy_data.py,
                            plus _reference/ (closed-universe validation sets, e.g. bihar_districts.yaml)
  okf_compiled/            compiler output: 238 structured OKF JSON records + findings.json
HANDOFF.md                 current project status, decisions made, open questions, how to pick this project back up
```
