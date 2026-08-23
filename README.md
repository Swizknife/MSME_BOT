# Bihar MSME Policy 2026 — RAG Chatbot

A citation-grounded chatbot that answers questions about the Bihar MSME Policy 2026 draft — retrieval-augmented, running entirely on a CPU-only local machine (embedding, retrieval, and reranking never leave the machine; the LLM step is swappable between a local Ollama model and a hosted API).

- **Architecture and design rationale:** [`docs/RAG_IMPLEMENTATION.md`](docs/RAG_IMPLEMENTATION.md)
- **Learn the RAG pipeline from scratch, with the real challenges hit while building it:** [`docs/RAG_LEARNING_GUIDE.md`](docs/RAG_LEARNING_GUIDE.md)

This README is only about **running it locally**. Commands below are Git Bash (the shell this project was actually built and tested in on Windows); a PowerShell note is added wherever a command genuinely differs.

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

`gemma3:4b` was chosen over the smaller/faster `llama3.2:1b` because this project's system prompt carries 8 strict rules (citations, never-do-arithmetic, exact figures, bilingual output, ambiguity disclosure) that a 1B-class model follows unreliably — see `backend/app/generation/llm_provider.py` for the actual benchmark numbers behind that choice. If you'd rather use a different model (or a hosted API instead of Ollama entirely), see [§5 Configuration](#5-configuration) below.

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

This is **ingestion** — it reads the policy PDF and builds the searchable index. It does not need to be re-run on every chat message, only the first time (or after the source PDF or `policy_data.py` changes). See `docs/RAG_LEARNING_GUIDE.md` Part 2 for what each step actually does.

From `backend/`, with the venv activated:

```bash
# Step 1 -- extract clean text from the PDF (fast, no downloads)
python -m app.ingestion.extract

# Step 2 -- build ~85 retrievable chunks from the structured policy data
python -m app.ingestion.chunk

# Step 3 -- embed every chunk with BGE-M3 and index into local Qdrant
#           (downloads ~2.3GB the first time -- can take a while depending
#           on your connection; see the troubleshooting note below if it
#           times out partway through)
python -m app.ingestion.embed_index
```

Then verify each step actually produced correct output — these are fast, mechanical checks, not another LLM call:

```bash
python -m app.ingestion.verify_extraction
python -m app.ingestion.verify_policy_data
python -m app.ingestion.verify_chunks
```

All three should print `PASS: ...`. If any prints `FAIL`, stop and read the error before continuing — it means something in the source PDF or the hand-encoded policy data has changed in a way the pipeline didn't expect.

You should end up with:

```
data/extracted/msme_policy_2026.raw.json    <- Step 1 output
data/chunks/msme_policy_2026.chunks.json    <- Step 2 output (85 chunks)
data/qdrant_local/                          <- Step 3 output (the search index)
```

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
| `hosted` | Talks to any OpenAI-compatible hosted endpoint (also set `HOSTED_LLM_BASE_URL`, `HOSTED_LLM_API_KEY`, `HOSTED_LLM_MODEL`) | Faster (~2–4s), but retrieved policy text is sent to that external endpoint |

Retrieval, embedding, and reranking are **always local** regardless of this setting — only the final generation step is swappable. See `backend/app/generation/llm_provider.py`.

Coverage-Gate abstention thresholds live in `config/thresholds.yaml`. They are currently placeholder defaults (`calibrated: false`) — see `docs/RAG_IMPLEMENTATION.md` §10.4 for how they're meant to eventually be tuned against a real evaluation set (`eval/`, not built yet).

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

A healthy response cites `S7.9 > Item 1 Capital Subsidy > Micro` at page 18 and states 30%/25% rates by district region. If you get an empty `sources` list and a "not covered" answer for this exact question, something in ingestion (§3) didn't complete — re-run the three `verify_*` scripts.

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

---

## 8. Project layout

```
backend/app/
  ingestion/     PDF -> text -> structured facts -> chunks -> embeddings (run manually, once)
  retrieval/     query encoding, hybrid search, reranking, coverage gate (runs per request)
  generation/    prompts, LLM provider, post-generation guards (runs per request)
  policy/        intent classification, ambiguity register accessor
  api/           the FastAPI /api/chat endpoint -- the tiered response ladder lives here
frontend/src/
  api/chat.ts              typed client for /api/chat
  components/              ChatMessage, SourceCitations, TierBadge, ChatInput, StarterQuestions
  App.tsx                  ties it together: language toggle, draft banner, chat window
docs/
  RAG_IMPLEMENTATION.md    the architecture doc -- what was built and why
  RAG_LEARNING_GUIDE.md    a from-scratch RAG tutorial using this exact codebase as the example
config/
  .env.example             copy to backend/.env
  thresholds.yaml          Coverage Gate thresholds (currently uncalibrated defaults)
data/
  raw/                     the source PDFs
  extracted/, chunks/      ingestion output (rebuilt by the commands in §3)
  qdrant_local/            the vector index (rebuilt by embed_index.py)
```
