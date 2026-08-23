# Learning RAG From Scratch — Using This Project as the Example

**Who this is for:** you know how to code, but you've never built a RAG system. By the end of this document you should understand not just "what RAG is" but *why every single design decision in this specific codebase was made* — including the ones that turned out to be wrong the first time and had to be fixed.

**How to use this document:** read it top to bottom once for the concepts, then re-read it with the actual project files open next to you. Every section names the exact file and function it's describing. Don't take my word for a number — go check `data/chunks/msme_policy_2026.chunks.json` yourself.

**The project in one sentence:** a chatbot that answers questions about the Bihar MSME Policy 2026 (a 27-page government PDF) by finding the exact relevant clause and quoting it back with a citation — never by "remembering" facts about MSME policy from its training data.

---

## Part 0 — What problem does RAG actually solve?

Before touching this codebase, understand the problem RAG exists to solve.

### The core problem: LLMs don't know your data, and they lie confidently when they don't know something

A large language model (an "LLM" — the thing that generates text, like GPT or Llama or Qwen) is trained once, on a huge snapshot of text, and then frozen. Ask it "What capital subsidy does a micro enterprise get under the Bihar MSME Policy 2026?" and one of three things happens:

1. It was never trained on this document (near-certain — this is a draft government PDF from 2026, not public web text) → it either says "I don't know" (rare) or **confidently invents a plausible-sounding number** (common — this is called **hallucination**).
2. Even if it had seen something like it, it can't tell you *which page* the number came from, because it doesn't "remember" documents — it only learned statistical patterns from them.
3. Numbers are exactly the thing LLMs are worst at reproducing exactly. A model will happily "round" ₹25 lakh to "around 25 lakhs" or invent a subsidy percentage that sounds right.

For a government policy bot, hallucination isn't a minor bug — it's the failure mode that matters most. If this bot invents a subsidy rate and an entrepreneur acts on it, that's a real-world harm.

### The RAG idea

**R**etrieval-**A**ugmented **G**eneration. The name describes the fix in three words:

1. **Retrieval** — before answering, search a knowledge base you control (in this project: the actual policy PDF, broken into pieces) and pull out the pieces that are actually relevant to the question.
2. **Augmentation** — take those retrieved pieces and construct a prompt that hands them to the LLM *as context*, along with instructions like "answer only from what I'm giving you."
3. **Generation** — the LLM writes an answer, but now it's writing a *summary of the text in front of it*, not recalling facts from training. This is a much easier and much more reliable task for a model to do well.

The LLM's job changes completely: instead of being the *source of facts*, it becomes a *fluent paraphraser of facts you handed it, with citations*. That's the whole idea. Everything else in this document is about doing that well, efficiently, and safely.

### Why not just paste the whole 27-page PDF into every prompt?

You might reasonably ask: this PDF is only ~56,000 characters (~15,000 tokens). Modern LLMs can accept 100,000+ tokens of context. Why not skip retrieval entirely and just paste the whole document into the system prompt every time?

This project's architecture doc (`docs/RAG_IMPLEMENTATION.md`, section 2.1) answers this directly, and it's worth understanding because it's a genuinely close call here — at many organizations' scale it wouldn't be:

- **Citations.** If you paste the whole document, the model has to *guess* which page/section a fact came from when it writes a citation — it has no structural signal for that. If you retrieve a specific chunk that was tagged with its page number in advance, the citation is a fact you already know, not something the model has to infer.
- **Hallucination doesn't go away just because the right text is present.** A 15,000-token context still leaves plenty of room for a model to blend two different clauses' numbers together, especially under a Windows/CPU-only setup with smaller local models (this project's constraint — see Part 3).
- **It doesn't scale.** This corpus is one 27-page PDF today. The architecture is built to survive adding the Bihar Industrial Investment Promotion Policy, the Startup Policy, amendments, and a notified final version — at that point "paste everything" stops being an option, and you'd have to retrofit retrieval anyway.
- **Auditability.** With retrieval, you can log *exactly which chunks were shown to the model* for every single answer. That's what makes it possible to prove, after the fact, why the bot said what it said.

So: this project builds retrieval even though it's a borderline case, because the four reasons above are permanent, structural reasons, not just today's convenience.

---

## Part 1 — The pipeline, at a glance

Two completely separate processes make up this system. Confusing them is the single most common beginner mistake in RAG, so get this straight first:

```
                         ┌─────────────────────────────────────┐
  RUNS ONCE, OFFLINE     │  INGESTION  (build the knowledge base)│
  (or whenever the       │  PDF -> extract -> structure ->      │
  source document        │  chunk -> embed -> index in Qdrant   │
  changes)                └─────────────────────────────────────┘
                                          │
                                          ▼  (writes vectors to disk)
                         ┌─────────────────────────────────────┐
  RUNS ON EVERY          │  QUERY  (answer one user question)   │
  USER MESSAGE            │  encode query -> search -> rerank -> │
                          │  gate -> assemble -> generate ->     │
                          │  guard -> respond                    │
                          └─────────────────────────────────────┘
```

**Ingestion** happens in `backend/app/ingestion/` and is run by hand from the command line (`python -m app.ingestion.extract`, then `chunk`, then `embed_index`). It reads the PDF and produces a searchable index. You do NOT run this on every user question — that would be absurdly slow and pointless, since the policy document doesn't change between one user's question and the next.

**Query time** happens in `backend/app/retrieval/`, `backend/app/generation/`, and `backend/app/api/chat.py`. This is the code that runs every time someone types a message into the chat box.

Keep asking yourself, for every file in this project: *is this an ingestion-time file or a query-time file?* It will make the whole codebase click into place.

---

## Part 2 — Ingestion: building the knowledge base

### Step 1 — Extraction (`backend/app/ingestion/extract.py`)

**The concept:** you can't search a PDF directly. A PDF is a page-layout format, not a text format — it stores where ink goes on a page, not "this is a sentence." The first job of any RAG pipeline over documents is turning that layout into clean, structured text.

**The tool:** [PyMuPDF](https://pymupdf.readthedocs.io/) (`import pymupdf`), a Python library that reads PDF internals directly. `page.get_text()` extracts the text layer of one page. This project also uses `page.find_tables()` (structural table detection) and `page.get_text("dict")` (returns every individual text *span* with its exact x/y coordinates on the page — this becomes important below) and `page.get_drawings()` / `page.get_images()` (to prove a page is genuinely blank, not just badly extracted).

**Why this project doesn't use OCR:** OCR (optical character recognition — reading text out of a picture of a page) is for scanned documents that have no real text layer. This PDF is a digitally-typeset Word/LaTeX-style document — PyMuPDF gets clean text straight out of it on 25 of 27 pages. Running OCR over a document that's already digital text would *throw away* accuracy to fix problems that don't exist on those 25 pages.

**Challenge #1 you'll hit immediately in any real document: layout bugs that corrupt extraction.**

Page 10 of this PDF looked, on first extraction, like this (real output, seen early in this project):

```
The State shall initiate a de edicated helpline and toll free number for MSM MEs of the state, also
a chatbot will be developed d for the MSME where they can reach out for their t grievances and
```

Notice `de edicated` and `MSM MEs` — words are broken and duplicated mid-token. This is NOT a bug in your code — it's how the PDF was actually built. The document diagnosis (see `extract.py`'s module docstring, which explains this in detail) turned out to be: the page lays text out in two side-by-side columns whose bounding boxes meet and slightly overlap around x≈225–230pt. When PyMuPDF walks the page in its default reading order, it interleaves the two columns mid-sentence, and the exact boundary character gets rendered once at the tail of the left column's text span and once again at the head of the right column's span.

**How this was diagnosed** — not guessed at, actually diagnosed: `page.get_text("dict")` was used to look at the raw span structure, which showed spans like `"...create dedi"` immediately followed, at the *same y-coordinate*, by `"icated divisions..."`. Both spans share the letter `i`. That's the smoking gun — a real column-break-mid-word bug, not random corruption.

**How it was fixed** (`_reconstruct_seam_page` in `extract.py`) — this is a good example of "understand the mechanism, then write the minimal rule that fixes it," rather than pattern-matching symptoms:

1. Pull every text span with its `(y0, x0, text)`.
2. Bucket spans into visual rows by `y0` (rounding to a small tolerance, since two spans "on the same line" won't have bit-identical y-coordinates).
3. Within each row, sort spans left-to-right by `x0`.
4. Concatenate adjacent spans, but with one rule: **if the last character of the accumulated text and the first character of the next span are both letters and match case-insensitively, drop the duplicated leading character before joining.**

```python
def _concat_with_boundary_dedup(left: str, right: str) -> str:
    if left and right and left[-1].isalpha() and right[0].isalpha() and left[-1].lower() == right[0].lower():
        return left + right[1:]
    return left + right
```

This one rule handles three cases at once: the boundary-duplication case (`"dedi"` + `"icated"` → `"dedicated"`, dropping the shared `i`), the no-overlap mid-word case (`"aspir"` + `"ing"` → `"aspiring"`, falls through unchanged since the letters at the boundary don't match), and ordinary spans that are already separated by their own space (also a no-op). No dictionary, no spell-checker, no LLM call — just understanding the actual cause and writing the smallest correct fix.

**How you prove the fix actually worked, instead of just "looking okay":** `extract.py` defines a list of known-good phrases that MUST appear in the repaired text — `PAGE_10_ANCHORS`, things like `"a chatbot will be developed"` and `"Udyog Salahkaar"`. After repair, the code checks every anchor string is present. This is a recurring pattern in this whole project, worth learning as a habit: **whenever you write a repair/transformation step, write an assertion that checks the repair actually happened**, not just that the code ran without crashing.

**Challenge #2: knowing when NOT to "fix" something.**

Page 8 has a heading, `"5.2 Guiding principles of the policy"`, with nothing underneath it. The naive assumption is "extraction must have failed to grab an image or a diagram." The actual investigation (`_page_is_confirmed_empty_after_heading`) checked: is there text after the heading? No. Are there any vector drawings on the page? Zero. Any images? Zero. **The page is genuinely empty in the source document.** This is a defect in the government's draft policy, not a bug in the extraction code — and it gets recorded as such (this becomes ambiguity register entry `AMB-18`, see Part 6). The lesson: don't assume every weird thing you find is a bug in your pipeline. Sometimes the source data really is broken, and your job is to detect that and say so honestly, not to paper over it.

### Step 2 — Structuring (`backend/app/ingestion/policy_data.py`)

**The concept:** raw extracted text is still just one long string per page. For a RAG system to answer precisely, you need to know the *structure*: which sentence belongs to which section, which numbers belong to which enterprise category, which conditions govern which incentive. This step turns flat text into typed Python objects.

**A genuinely important lesson from this project: don't always trust automated table detection.**

PyMuPDF's `page.find_tables()` was tried first for the big incentive table on pages 18–20 (17 rows × 3 columns of subsidy rates). It looked like it should work — it's built exactly for this. But on inspection it **truncated cell text and split the Capital Subsidy row's two district-category values into two separate table rows with a blank serial number**, because the source PDF renders "...A Category District" and "...B Category District" as two stacked paragraphs inside a single logical cell, and the table detector's heuristics misread that as two rows.

This is exactly the kind of silent corruption a RAG pipeline can't afford: if that split had gone unnoticed, a "Capital Subsidy" query could retrieve a chunk with the rate but not the cap, or vice versa.

**The decision:** given the corpus is small and fixed (27 pages, doesn't change often), the incentive table, the residual incentives, the section 9 conditions, and all the annexures were **hand-transcribed directly from the rendered PDF** into typed dataclasses (`IncentiveRow`, `ResidualIncentive`, `GuidingClause`, etc. in `policy_data.py`), rather than trusting the automated table extractor. This trades one risk (a bad table detector) for a different risk (human transcription error) — so a *second* safeguard was added:

**`verify_policy_data.py`** — this script re-opens the *raw extracted text* from Step 1 and mechanically checks that every rate, cap, and figure written in `policy_data.py` actually appears (after whitespace-normalizing) somewhere in the extracted text of the page it claims to be on:

```python
FIGURE_PATTERN = re.compile(
    r"\d+(?:\.\d+)?\s*(?:%|Crore|croe|Lakhs?|lakhs?|Kw)|Rs\.?\s?\d[\d,]*|\d[\d,]*/-"
)
```

This closes the loop: hand-transcription is trusted, but it's *mechanically audited* against the source, not just trusted blindly. If someone edits `policy_data.py` and typos a number, this script fails loudly instead of silently indexing a wrong figure. This general pattern — "hand-author something for correctness, then write a script that machine-checks it against the source of truth" — is worth remembering; it shows up again in `verify_chunks.py`.

**A second important lesson: preserve the source's own mistakes, don't "fix" them.**

The policy table literally spells "Crore" as **"croe"** in two places, and writes **"7Crore"** with no space in another. `policy_data.py`'s own docstring is explicit about this: *"Known typos and inconsistencies are preserved EXACTLY as printed in the source... this module never corrects the policy's own drafting; it only structures it."* Why does this matter? Because this bot's job is to tell a user exactly what the *draft policy* says — including its flaws — not to present a cleaned-up version that looks more authoritative than the actual document. (This also has a very concrete downstream consequence you'll see in Part 5: the "Numeric Guard" has to specifically handle the "croe" typo, or it would incorrectly flag a correct quotation of the source as a hallucination.)

**A third lesson, and arguably the most valuable finding in this whole project: data validation itself can discover real defects in your source data.**

`policy_data.py` includes `BIHAR_ALL_38_DISTRICTS` — the actual, official list of Bihar's 38 districts, sourced independently of the policy PDF. This is compared programmatically against the policy's own Annexure I (which categorizes districts into "Region A" / "Region B" for subsidy-rate purposes):

```python
Region A count : 31
Region B count : 6
Total covered  : 37
Bihar districts: 38
MISSING from Annexure I -> ['Araria']
```

**The policy's own official district-categorization table simply omits one of Bihar's 38 districts.** This wasn't something anyone told this project to look for — it was found by writing a boring cross-check (`set(bihar38) - (region_a | region_b)`) and looking at what came out. This became ambiguity register entry `AMB-20`, and it's treated as seriously as it deserves: an enterprise in Araria genuinely has no determinable capital-subsidy rate from this document, and the bot must say so rather than guess. **The general lesson: a chunk-and-embed pipeline is also a great forcing function for finding data-quality bugs in your source, if you write the cross-checks.**

### Step 3 — Chunking (`backend/app/ingestion/chunk.py`)

**The concept, from scratch:** a "chunk" is the unit of text you actually embed and search over. You cannot feed a whole 27-page document into a retrieval index as one giant blob — retrieval needs to be able to point at a *specific* small piece of text that answers a *specific* question. So you split the document into pieces. This sounds simple; it is the single most consequential design decision in most real RAG systems, and getting it wrong is the most common way RAG systems fail in production.

**Why chunk size and boundaries matter so much — the general principle:** if a chunk is too big, it dilutes the signal (a paragraph mentioning five unrelated things all gets embedded into one vector, so the vector isn't a strong match for any single fact in it). If a chunk is too small or badly split, you separate a fact from the context that makes it meaningful or correct — e.g. a subsidy rate on its own, disconnected from the condition that caps it.

**How this project chunks — and why it's NOT simple fixed-size splitting:**

A very common (and often wrong) approach you'll see in RAG tutorials is: split the document into fixed N-character (or N-token) windows with some overlap, regardless of what's inside them. This project deliberately does **not** do that. Instead there are five distinct chunk-building functions in `chunk.py`, each producing a different `chunk_type`, because different parts of this document need to be split differently:

| `chunk_type` | Built by | What it is |
|---|---|---|
| `table_atom` | `build_incentive_atoms()` | One incentive row, for one enterprise category (or "all three" if identical) |
| `residual_incentive` | `build_residual_incentive_chunks()` | One section-8 grant (R&D subsidy, MSME park subsidy, etc.) |
| `guiding_clause` | `build_guiding_clause_chunks()` | One lettered sub-clause of section 9 (the conditions that govern eligibility) |
| `ambiguity_note` | `build_ambiguity_chunks()` | One entry from the 21-item defect register, directly retrievable |
| `reference_list` | `build_reference_list_chunks()` | Annexures (district lists, sector lists, glossary) |

**Challenge: the "51 vs 25" table-atom miscalculation.** This is worth walking through in detail because it's a genuinely instructive mistake.

The section 7.9 incentive table has 17 rows × 3 enterprise-category columns (Micro/Small/Medium) = 51 cells. The very first instinct — "split every cell into its own chunk" — sounds reasonable: 17 × 3 = 51 chunks. But before building that, someone actually checked which rows *differ* across the three categories:

```
capital-subsidy caps  -> ['Cap 25 Lakhs','Cap 1.5 Crore','Cap 5 croe'] x3   -> VARIES
payroll thresholds    -> ['more than 10','more than 20','more than 50']    -> VARIES
revival ceilings      -> ['INR 1 Crore','INR 5 Crore','INR 12 Crore']      -> VARIES
SME exchange          -> ['-', '20% cap Rs.5L', '20% cap Rs.5L']            -> VARIES
disadvantaged-group   -> ['7 Crore','7Crore','7 Crore']                    -> identical
scaling-up            -> ['Cap 25 Lakhs'] x3                               -> identical
... (13 of 17 rows are identical across all three categories)
```

**Only 4 of the 17 rows actually vary by category.** The other 13 (roof-top solar, energy audit, stamp duty, quality certification, patents, trademarks, SGST reimbursement, e-commerce, export subsidy, scaling-up, etc.) give the exact same rate to Micro, Small, and Medium enterprises alike.

If you'd blindly exploded all 17 rows × 3, you'd end up with 39 chunks that are *word-for-word near-duplicates of each other* (three copies of the identical Roof Top Solar Subsidy text, one per category, differing only in a category label). Why is that actually harmful, not just wasteful? Because retrieval only returns a limited number of top candidates (this project reranks the top ~12, generation sees the top ~6). If a query about rooftop solar retrieves three duplicate vectors of the *same fact*, that burns three of your six precious context slots on one fact — potentially **displacing a different, actually-needed chunk**, like the section 9.6 condition that governs when rooftop solar subsidy is claimable.

**The fix — conditional explosion**, in `build_incentive_atoms()`:

```python
if row.varies_by_category:
    for cat, cat_text in (("micro", row.micro), ("small", row.small), ("medium", row.medium)):
        # ... build one chunk per category, e.g. 3 chunks for Capital Subsidy
else:
    # Verified identical across categories -- ONE chunk, tagged with all three
    # categories, instead of three near-duplicate vectors.
    # ... build a single chunk covering all 3 categories
```

Result: 4 rows × 3 categories (12 chunks) + 13 rows × 1 chunk (13 chunks) = **exactly 25 table atoms**, not 51. This number is enforced as an invariant — `verify_chunks.py` fails the build if it's ever anything other than 25 — precisely so that a future edit can't accidentally regress back to blanket explosion without someone noticing.

**The "small-to-big" pattern — `text` vs `parent_text`.** Every `Chunk` object carries two different strings:

```python
@dataclass
class Chunk:
    text: str          # the SMALL unit -- this is what gets embedded and searched
    parent_text: str   # the FULLER context -- this is what the LLM actually reads
```

Why two? Because precision and context pull in opposite directions. A small, tightly-focused chunk (just "Capital Subsidy for a MICRO enterprise: 30%... 25%...") produces a sharp, unambiguous embedding vector that's easy to match precisely against a specific question. But if that's *all* the LLM sees, it might not know about the section 9.1 conditions that cap or restrict that subsidy. So: **embed the small chunk (for search precision), but hand the LLM the bigger `parent_text` (for generation completeness)** — for a table atom, `parent_text` is the whole row across all three categories, plus its governing conditions. This is a standard, important RAG technique often called "small-to-big retrieval," and this project's implementation of it is a good concrete example to learn from.

**Why ambiguity notes are indexed as retrievable chunks, not just stored as metadata.** `build_ambiguity_chunks()` turns every one of the 21 known policy defects into its own directly-searchable chunk. The reasoning, straight from the code comment: a real class of question this bot must answer well is *"does the policy define backward districts?"* or *"how much interest subsidy do I get?"* — and the *correct* answer to both is "the draft doesn't specify this; departmental clarification is needed," which is exactly the content of ambiguity entries `AMB-02` and `AMB-03`. If these weren't independently retrievable, the bot would have nothing relevant to find for those questions and would either abstain uselessly or (worse) let the LLM guess. Treating "here is a known gap in the source" as first-class retrievable content, not an afterthought, is what makes this bot honest about a draft document's limitations.

**Why zero overlap.** Many RAG tutorials chunk with overlapping windows (e.g. each 500-character chunk shares 50 characters with its neighbor) to avoid cutting a sentence in half at a boundary. This project uses **zero overlap**, deliberately, for a reason specific to this domain: overlap would duplicate rupee figures and percentages across multiple chunks. That directly breaks a later safety mechanism — the Numeric Guard (Part 5) — which checks "does every number in the answer appear in the retrieved context." If the same ₹25 lakh appeared in two overlapping chunks, you'd lose the ability to cleanly trace *which* chunk a figure actually came from. Since this project's chunks are hand-built around complete, self-contained clauses (not sliced by character count), there's no sentence-splitting problem that overlap would have solved anyway.

### Step 4 — Embedding: what it actually is, from scratch

You now have ~85 chunks of text (`data/chunks/msme_policy_2026.chunks.json`; run `python -m app.ingestion.chunk` and count them yourself). None of them are searchable yet — a computer can't compare two strings for "meaning," only for exact character equality. Embedding is the fix.

**The concept:** an embedding model is a neural network that reads a piece of text and outputs a fixed-length list of numbers — a **vector** (e.g. 1024 numbers for the model this project uses). The model is trained so that texts with *similar meaning* produce vectors that are *close together* in that 1024-dimensional space, and texts with different meaning produce vectors that are far apart. "Close together" is measured with **cosine similarity** — essentially, do these two vectors point in roughly the same direction, regardless of their length. Once you have vectors, "find text similar to this query" becomes "find the vectors closest to the query's vector" — a well-understood, fast, purely mathematical operation. That's the entire trick that makes semantic search possible.

**Dense vs. sparse — two different kinds of vector, and why this project uses both.**

- **Dense vectors** (the kind described above) capture *semantic/conceptual* similarity. A dense embedding model can tell that "how much money will I get" and "what is the subsidy amount" are related in meaning, even though they don't share many words. This is powerful, but it has a real weakness: it's comparatively **bad at exact tokens** — specific numbers, section references, acronyms. A dense model doesn't have a strong reason to treat "₹24,000" as meaningfully different from "₹25,000" — both are "a rupee amount," semantically similar, even though for this policy bot getting that exact figure right is the whole point.
- **Sparse vectors** are the mathematical descendant of classic keyword search (like BM25/TF-IDF, if you've heard of those) — a huge vector, mostly zeros, where each non-zero position corresponds to a specific vocabulary token and its weight represents how important that exact token is in the text. Sparse retrieval is excellent at exact-token matching: it will reliably find the chunk containing the literal string "₹24,000" or "section 9.1(d)" or "MSMED Act, 2006."

Combining both is called **hybrid search**, and it exists specifically to cover each method's blind spot: dense retrieval brings conceptual/semantic matching, sparse retrieval brings exact-token precision. This corpus needs both — a policy document is dense with exact figures, section numbers, and legal acronyms, exactly the content sparse retrieval is strong at, layered under natural-language questions, exactly what dense retrieval is strong at.

**Why this project's chosen model, BGE-M3, is unusual and genuinely convenient here.**

Most embedding setups need to run *two separate models* (or a model plus a classic algorithm like BM25) to get both dense and sparse vectors, which means two indexes, two pieces of infrastructure to keep in sync. **BGE-M3** (`BAAI/bge-m3`) is one model that, in a single forward pass, produces **both** a dense vector *and* sparse token weights (plus a third representation, ColBERT multi-vector, which this project deliberately does not use — more below). "M3" literally stands for **Multi-Functionality** (dense + sparse + multi-vector from one model), **Multi-Linguality** (100+ languages, including Hindi — this matters a lot for this project, see Part 4), and **Multi-Granularity** (it accepts up to 8,192 tokens of input, versus the 512-token limit of many older embedding models — this matters because this corpus's incentive table and its surrounding context, embedded together as a chunk, would risk silent truncation on a 512-token model).

**A subtle but important quirk you must know before writing embedding code: instruction prefixes.** Some embedding model families expect you to prepend a fixed instruction string before the text you're embedding — e.g. `bge-large-en-v1.5` wants `"Represent this sentence for searching relevant passages:"` prepended to queries, and the E5 model family wants `"query: "` or `"passage: "` prepended. **BGE-M3 is symmetric and wants no prefix at all.** Adding one measurably *hurts* retrieval quality with this specific model, because the model was never trained to expect it. This is an extremely easy mistake to make, precisely because so many RAG tutorials online use those other model families and casually copy-paste a prefix pattern that doesn't apply here.

This project takes this seriously enough to write an actual regression test for it — `backend/tests/test_embedder.py`. It doesn't download the real 2GB model (that would make every test run slow and require network access); instead it substitutes a tiny fake model that just *records* what text it was asked to encode, and checks two things:

```python
BANNED_PREFIXES = (
    "represent this sentence", "represent this query",
    "query:", "passage:", "search_query:", "search_document:",
)
```

1. The text handed to `.encode()` is *exactly* what was passed in — untouched.
2. It doesn't start with any of the instruction-prefix patterns from other model families.

This is a good general lesson for any ML pipeline: when a subtle configuration detail (like "no prefix") is easy to get wrong and hard to notice you got wrong (the model still runs, it just retrieves slightly worse), write a fast, dependency-free test that locks in the correct behavior, rather than relying on remembering the rule.

**Where embedding actually happens:** `backend/app/ingestion/embed_index.py` (ingestion time — embeds all 85 chunks once) and `backend/app/retrieval/embedder.py` (query time — embeds one user question at a time, using an in-process singleton so the ~2.3GB model is loaded into memory only once, not once per request):

```python
out = model.encode(
    texts,
    return_dense=True,
    return_sparse=True,
    return_colbert_vecs=False,   # deliberately off -- see the discussion below
    max_length=1024,
)
```

**Why ColBERT (the third, multi-vector representation) is deliberately switched off:** ColBERT-style retrieval keeps a separate vector *per token* rather than one vector per chunk, which can improve precision further — but at roughly 100–400× the storage of a single dense vector per chunk. At this corpus's size (a few hundred chunks), that cost buys very little, because the cross-encoder reranker (Part 4) already recovers most of the precision gain ColBERT would have offered, at far less complexity. This is documented in the code as a conscious trade-off, not an oversight — a good habit: when you decide *not* to use a technique, write down why, so a future reader doesn't wonder if you forgot about it.

### Step 5 — Indexing (`backend/app/ingestion/embed_index.py`, storage: `backend/app/retrieval/qdrant_local.py`)

**The concept:** once you have a vector for every chunk, you need somewhere to store them that supports fast "find the nearest vectors to this query vector" search. This project uses **Qdrant**, a vector database that natively supports both dense vectors and sparse vectors in the same collection — which matters, because it means the dense+sparse hybrid design from Step 4 doesn't need two separate storage systems.

**A genuinely important, non-obvious point about scale: exact search, not ANN, and why.** Most vector-database tutorials reach immediately for **HNSW** (an approximate nearest-neighbor / "ANN" index) — a clever graph structure that makes nearest-neighbor search fast even over millions of vectors, at the cost of occasionally missing the true best match (hence "approximate"). This project deliberately turns that off:

```python
DENSE_VECTOR_NAME: VectorParams(
    size=DENSE_DIM, distance=Distance.COSINE,
    hnsw_config=HnswConfigDiff(m=0),   # m=0 disables HNSW graph construction
),
```

Why? At **~85 to a few hundred vectors** (this corpus's actual scale), brute-force exact search — literally comparing the query vector against every single stored vector — takes well under a millisecond. An approximate index exists to trade a small amount of accuracy for speed *at a scale where brute force would be too slow*. Here, brute force isn't just "fast enough," it's both faster AND more accurate than the approximate alternative, because there's no approximation error and no large-scale search to speed up. This is a good instinct to build: **don't reach for a scaling technique before you've checked whether you're actually at the scale where it matters.** Using HNSW here would have been pure complexity with a real (if small) accuracy cost and zero benefit.

**Local mode vs. a server — an honest operational compromise.** Qdrant can run as a separate server process (the "normal" production setup) or in "local mode," where the Python client talks directly to an on-disk folder with no separate server at all. This project uses local mode (`backend/app/retrieval/qdrant_local.py`), not because it's architecturally preferred, but because Docker wasn't running on the development machine and, at this corpus's tiny scale, local mode is strictly simpler and equally correct. The code is explicit that this is a substitution, not the final design, and that switching to a real server later is a one-line change (`path=` → `url=`) because both modes expose the identical Python client API.

**An operational gotcha worth knowing about, because it will bite you if you don't:** local-mode Qdrant **file-locks** its storage folder. Only one process may have the collection open at a time.

```
RuntimeError: Storage folder ...\data\qdrant_local is already accessed by another
instance of Qdrant client. If you require concurrent access, use Qdrant server instead.
```

This actually happened during development of this project — running a one-off debugging script while the FastAPI server (which also holds the collection open) was still running failed with exactly this error. The fix isn't a code fix, it's an operational rule documented directly in `qdrant_local.py`: run the ingestion script to completion and let it exit *before* starting the API server, and don't try to run two Python processes against local-mode Qdrant at once. This is a real limitation of local mode that a server deployment wouldn't have — one more reason it's explicitly marked as a stand-in, not the end state.

---

## Part 3 — Retrieval: finding the right chunks for a question

You now have an index. This part covers what happens the instant a user's message arrives — `backend/app/retrieval/pipeline.py`'s `retrieve()` function is the entry point; read it top to bottom, it's short and it's the map for everything below.

### Query encoding

The user's question is encoded with the exact same BGE-M3 model used at ingestion time, producing a dense vector and sparse weights for the query — using the *same* no-prefix rule from Part 2 (BGE-M3 is symmetric: queries and passages are encoded identically, with no special "this is a query" marker). This symmetry is actually what makes the whole approach work: a query's vector and a matching passage's vector need to land close together in the *same* space, which only happens if they were produced the same way.

### Hybrid search and Reciprocal Rank Fusion (`backend/app/retrieval/hybrid.py`)

The query's dense vector searches the dense vector space; its sparse weights search the sparse vector space — two separate searches, each returning a ranked list of candidate chunks. Now you have two different rankings of the same corpus and need to combine them into one.

**The naive approach — and why it's fragile:** just add the two scores together, maybe with a weight: `combined = 0.5 * dense_score + 0.5 * sparse_score`. The problem: dense cosine similarity and sparse dot-product scores live on **completely different, incompatible numeric scales**. A dense cosine score might range narrowly between 0.6 and 0.9 for almost anything; a sparse dot-product score has a totally different range depending on vocabulary overlap. Averaging two incompatible scales with a hand-picked weight is a classic fragile-hack: it "works" until the score distributions shift slightly (e.g. after re-indexing) and the weight needs re-tuning, silently, forever.

**The fix used here — Reciprocal Rank Fusion (RRF):** instead of combining *scores*, combine *ranks*. For a candidate that appeared at rank `r` (0-indexed) in a result list, its contribution to the fused score is:

```python
score += 1.0 / (RRF_K + rank + 1)
```

with `RRF_K = 60` (a standard, empirically-settled constant — a chunk ranked #1 contributes `1/61`, ranked #2 contributes `1/62`, and so on; a chunk that appears in *both* the dense and sparse top lists gets both contributions summed). Because this only ever depends on *position in a list*, not on the raw score's scale, it's scale-free — no tuning knob to drift out of calibration. This is the standard, robust way to fuse rankings from different retrieval methods, and it's worth understanding independent of this project, because you'll see it in essentially every serious hybrid-search system.

**Why hybrid search over dense-only search matters concretely for this corpus:** a purely dense search for `"section 9.1(d)"` or `"₹24,000"` is genuinely weak — dense embeddings blur exact tokens together with semantically-similar-but-wrong ones. Sparse retrieval recovers exactly this case, because it matches on the literal tokens. This is the concrete payoff of the dense+sparse design from Part 2 — this is *where* it pays off.

### The Hinglish problem — a real, still-imperfect challenge

**What Hinglish is:** Hindi written in Latin script instead of Devanagari — e.g. *"micro enterprise ko kitni capital subsidy milegi"* instead of *"सूक्ष्म उद्यम को कितनी पूंजी सब्सिडी मिलेगी?"*. This is extremely common in India for informal typing (most phone keyboards default to Latin script), and this bot's audience will absolutely type this way.

**Why this genuinely breaks the plan from Part 2:** BGE-M3's cross-lingual strength — its ability to match a Hindi query against an English passage — is well-established for *Devanagari* Hindi. Romanized Hindi looks, to the embedding model, essentially like a string of unfamiliar English-alphabet tokens; it doesn't get the same cross-lingual benefit, because the model wasn't trained to recognize "kitni" as the Devanagari word "कितनी" spelled differently.

**Challenge: this was implemented incompletely at first, and the gap sat unnoticed until someone actually checked for it.** `backend/app/policy/intents.py` has a `detect_language()` function that correctly flags a query as `"hinglish"` using a small domain lexicon (`kitni, milegi, subsidy, udyami, kaise, ...`) and computes an `is_hinglish` flag on its `QueryUnderstanding` result. But for a while, **that flag was computed and then never used anywhere** — `retrieve()` in `pipeline.py` only ever encoded and searched the *original* query text. The detection worked; the actual mitigation the architecture doc called for was simply never wired up. This is a very common and easy-to-miss category of bug: a feature that looks finished because a *piece* of it (the detection) works and even has plausible-looking output, while the piece that actually changes behavior downstream was never connected.

**The fix**, once found (`backend/app/retrieval/hinglish.py` + the corresponding block in `pipeline.py`'s `retrieve()`):

```python
if is_hinglish:
    translit = transliterate_to_devanagari(query)
    if translit:
        t_dense, t_sparse = encode_query(translit)
        translit_candidates = hybrid_search(t_dense, t_sparse, query_filter=query_filter)
        candidates = merge_candidate_lists([candidates, translit_candidates])
```

Using the `indic_transliteration` library's ITRANS scheme, the romanized query is transliterated to Devanagari, encoded and searched *as a second, independent query*, and the two candidate lists are merged with a second RRF pass (`merge_candidate_lists` in `hybrid.py` — the same rank-fusion idea from above, applied one level up: fusing across *query variants* rather than across dense/sparse within one query). The original query is always still searched too, so this can only ever *add* recall, never remove a match the original phrasing would have found on its own.

**Be honest about the limits of this fix, because a junior engineer should learn to say this out loud too:** ITRANS is a formal transliteration scheme built for Sanskrit-derived text, not casual English-loanword-heavy Hinglish. Feeding it `"kitni subsidy milegi"` produces something like `"कित्नि सुब्सिद्य् मिलेगि"` — the native-Hindi function words (kitni → कित्नि, milegi → मिलेगि) come through reasonably, but the English loanword "subsidy" is rendered phonetically into an odd, non-standard Devanagari spelling that won't match the real Hindi word for subsidy anywhere in the corpus. **This is a real, acknowledged limitation, not a solved problem** — it's a recall-boosting addition on top of the original query, which is why it's safe to leave imperfect: it can only help, never hurt, but it doesn't fully close the gap. This is normal in real engineering: you ship the version that's strictly better than not having it, document its limits honestly, and mark the follow-up (better transliteration, or measuring an actual Recall@10 number on a set of real Hinglish test questions) as a next step rather than pretending it's finished.

---

## Part 4 — Augmentation: making retrieval trustworthy before generation

"Augmentation" is the middle letter of RAG, and it's easy to under-appreciate: it's not just "hand the retrieved text to the LLM," it's everything that happens *between* getting a ranked list of candidate chunks and deciding what the LLM is even allowed to see or say.

### Reranking — a second, more accurate but more expensive pass (`backend/app/retrieval/rerank.py`)

**The concept — bi-encoders vs. cross-encoders.** The embedding model from Part 2/3 is a **bi-encoder**: it encodes the query and each passage *completely separately*, each into its own vector, and only compares them afterward via cosine similarity. This is what makes it fast enough to search thousands of chunks — each chunk's vector is computed once, in advance, at ingestion time, and query time is just a fast vector comparison. But it has an inherent ceiling on accuracy, because the model never actually sees the query and the passage *together* — it has to compress a passage's full meaning into one fixed vector without knowing in advance what it will be compared against.

A **cross-encoder** reads the query and one candidate passage *together*, in a single forward pass, and directly outputs a relevance score for that specific pair. Because it sees both texts at once, it can pick up on much finer-grained relevance signals a bi-encoder's pre-computed vector can't capture. The catch: this means a fresh, non-cacheable computation for every single (query, candidate) pair, so it doesn't scale to searching a huge corpus directly — you can't cross-encode a query against 100,000 documents in real time.

**The standard two-stage pattern, used here:** use the cheap bi-encoder (Part 3's hybrid search) to cast a wide net and pull a *shortlist* of maybe 12 plausible candidates out of the full corpus, then use the expensive cross-encoder to precisely re-score just those 12 and pick the best few. This project uses `BAAI/bge-reranker-v2-m3` for that second pass — from the same BGE model family as the embedder, which matters because it means it handles Hindi/English cross-lingual reranking correctly too.

**Why this is called out as "the largest single quality lever in the pipeline"** (a direct quote from this project's architecture doc): the reranker's score isn't just "a bit more accurate," it's *dramatically* better calibrated — which turns out to be essential for the next section.

### The Coverage Gate — deciding when to say "I don't know" (`backend/app/retrieval/coverage_gate.py`)

**The concept, and why it's genuinely hard to get right:** for a policy bot, silently refusing to answer an out-of-scope question is *safe*; confidently answering with a hallucinated fact is *dangerous*. So the system needs a reliable way to say "this isn't in the document" — but *reliable* is the hard part.

**Why you can't just threshold on cosine similarity — a subtle but important point.** The obvious first idea: "if the top retrieved chunk's cosine similarity score is below some threshold, say I-don't-know." This sounds reasonable and is what a lot of beginner RAG systems do. It doesn't actually work well in practice, for a specific, learnable reason: raw cosine similarity scores from a bi-encoder tend to compress into a narrow band — for most real embedding models, almost *any* two pieces of related-domain text score somewhere around 0.6–0.9, whether they're a good match or a bad one, and that band **shifts depending on query length and phrasing**. There's no stable, universal cutoff you can pick, because the same "0.7" might mean "great match" for a short query and "poor match" for a long one.

**Why the reranker's score IS reliably thresholdable — this is the actual reason reranking is architecturally load-bearing here, not just a quality nice-to-have.** A cross-encoder, having actually read the query and passage together, produces a score (this project applies a sigmoid to squash the raw model output into 0–1) that separates genuinely relevant from genuinely irrelevant by a wide, stable margin — much closer to "0.99 means yes, 0.02 means no" than the narrow band cosine similarity gives you. That's what makes a fixed threshold meaningful at all.

**The actual gate logic** (`coverage_gate.py`):

```python
if top_score < tau_hard:
    action = "abstain"                    # LLM is never called
elif top_score < tau_soft:
    action = "answer_low_confidence"       # answer, but flagged
else:
    action = "answer"
```

Two thresholds rather than one, so there's a middle ground between "confident answer" and "refuse entirely" — a genuinely-relevant-but-not-certain match gets answered with a visible low-confidence flag, rather than forcing a binary choice between overconfidence and unhelpfulness.

**An honest, still-open engineering task worth understanding, not glossing over: these thresholds are *currently placeholder defaults*, not calibrated values.** `config/thresholds.yaml` stores `tau_hard: 0.35`, `tau_soft: 0.55`, and literally says `calibrated: false`. Real calibration requires a labeled evaluation set — a batch of real questions labeled "this should be answered" or "this should be refused" — run through the pipeline, so you can pick threshold values that actually maximize correct behavior on real examples, rather than guessing plausible-sounding numbers. That eval set hasn't been built yet in this project. This is a completely normal, honest state for a project to be in mid-build, and it's worth learning to recognize the difference between "this works" and "this works, but its exact tuning is a placeholder pending real evaluation data" — conflating the two is a common way projects overstate how finished something is.

**A concrete finding from live-testing this exact gate, worth knowing as a realistic example of what "uncalibrated" costs you in practice:** a question phrased conversationally — *"My investment is 80 lakh, what capital subsidy rate applies and how much will I get?"* — scored essentially **0.000** from the reranker and was abstained on, even though the *exact same underlying fact*, asked directly as *"What capital subsidy does a micro enterprise get?"*, scored **0.998** and answered perfectly. Nothing was broken — this is the reranker genuinely giving a low score to conversational, personal-scenario phrasing, because it was trained on more direct query-passage relevance pairs, and this corpus is written in impersonal legal register ("Capital Subsidy for a MICRO enterprise: 30%..."). The system did the *safe* thing (abstained rather than guessed a number), but it wasn't the *most helpful* thing. This is precisely the kind of gap that threshold calibration against a real eval set is meant to catch and fix — a good concrete illustration of why "it never lies" and "it's fully tuned" are two different, separately-earned properties.

### Context assembly — order matters, and this project shipped a real bug here

Once the top few chunks are chosen, they need to be assembled into the prompt the LLM will read. The naive approach is "just put them in score order, best first." This project's architecture doc explicitly argues against that:

> score-ordering scrambles conditions relative to the rates they govern... a capital-subsidy rate could be shown before or after the section 9.1 conditions that cap it, depending on which scored higher.

So the design calls for **document order** instead — sort the selected chunks by page number (and then by clause path) so that, e.g., a rate and the condition that limits it appear in something closer to their natural reading order, rather than shuffled by an unrelated relevance score.

**But the first implementation of "document order" introduced a new, different bug — a genuinely good lesson in why you test the whole pipeline live, not just each piece in isolation.** Sorting purely by `(page_start, clause_path)` seemed like a faithful implementation of "document order." Then a real end-to-end test asked *"What capital subsidy does a micro enterprise get?"* and the answer the LLM produced cited `[S1]` for its main fact — except source `[S1]`, once inspected, turned out to be an **Ambiguity Register note about a completely different subsidy** (`"Ambiguity Register > AMB-05"`), not the actual capital-subsidy table entry that was the true best match (which had scored 0.998!). Why? Both chunks happened to share page 18, and the string `"Ambiguity Register..."` sorts alphabetically *before* the string `"S7.9 > Item 1..."` — a pure accident of string comparison landed an unrelated tangential note in the [S1] slot, and the LLM — quite reasonably, since [S1] is presented as the first and presumably most important source — cited it as if it were the primary fact.

**The fix**, in `backend/app/api/chat.py`'s `_doc_order()`:

```python
if not reranked:
    return []
best, rest = reranked[0], reranked[1:]
rest_sorted = sorted(
    rest,
    key=lambda t: (t[0].payload.get("page_start", 0), t[0].payload.get("clause_path", "")),
)
return [best, *rest_sorted]
```

Pin the single best-scored chunk (from the reranker, Part 4) as `[S1]` always, and only apply document-order sorting to *everything else*, behind it. This satisfies both goals at once: `[S1]` is always genuinely the most relevant fact (fixing the bug), while the *supporting* context around it still reads in a sensible document order (preserving the original intent — conditions still sit near the rates they govern, among the non-primary sources).

**The lesson to take away, generalized:** "sort by X" is never neutral — the sort key you pick has second-order effects you may not predict from reading the code alone (here: alphabetical ordering of an unrelated label string). The bug was invisible in every unit test and every code review, because nothing about `_doc_order`'s logic was *wrong* in isolation — it did exactly what it was told to do. It only became visible by actually running a real query through the real pipeline and reading the real answer critically, asking "does this citation make sense?" rather than just "did the code run without an error?" This is why Part 6 exists — a lot of this project's real bugs were found exactly this way.

---

## Part 5 — Generation: turning retrieved facts into an answer, safely

### The tiered response ladder — the efficiency idea (`backend/app/api/chat.py`)

This is the project's central efficiency decision, and it's worth understanding as a design pattern independent of this specific project: **most RAG systems run the full pipeline — including an LLM call — for every single query.** For a bot whose job is D2 ("explain only, quote the policy as written — never compute or invent a number"), a huge fraction of real questions are single-fact lookups whose complete, correct answer *is* one verbatim retrieved chunk. Running an LLM generation step for those isn't just slower, it's strictly *riskier* — every LLM call is another chance for a subtle paraphrasing error, and on this project's CPU-only hardware (see Part 7), it's also 10–100× slower than skipping it.

So `chat()` in `chat.py` implements four tiers, checked in order, each one a chance to answer *without* paying for the next one:

| Tier | What triggers it | What happens |
|---|---|---|
| **0 — cache** | Exact repeat of an already-answered question | Return the stored answer instantly, no computation at all |
| **1 — abstain** | Coverage Gate says the top match is below `tau_hard` | Return a deterministic "not covered" message — **the LLM is never called** |
| **2 — extractive** | A single chunk clearly dominates (score gap > 0.15 over the runner-up) and the question is a simple lookup shape | Return a template-wrapped **verbatim quote** of that chunk plus its citation — **no LLM call** |
| **3 — synthesis** | Everything else (multi-clause questions, conversational phrasing, follow-ups) | Full LLM generation, with the guards below |

**Why Tier 2 (extractive) isn't a "worse" answer, and this is a genuinely important reframing to understand:** it's tempting to think of "no LLM, just paste the chunk" as a fallback for when the LLM path is unavailable, a degraded experience. For *this specific product*, it's the opposite — the whole system's rule (D2, decided early in this project) is "explain only, quote what's written, never compute individual entitlements." A verbatim quote with a correct citation **is exactly what's mandated**, and it's *automatically, perfectly* grounded — there's no possibility of paraphrasing drift, because nothing was paraphrased. The LLM's contribution, when it is used (Tier 3), is fluency and the ability to synthesize *across* multiple chunks — not correctness. Correctness comes from retrieval and the guards below.

### Prompt construction (`backend/app/generation/prompts.py`)

The system prompt handed to the LLM for Tier-3 synthesis has eight numbered "ABSOLUTE RULES" — worth reading in full in the file, but the ones worth understanding conceptually:

- **Rule 1**: answer only from the numbered sources given, never from general knowledge — this is the entire RAG contract restated as an instruction.
- **Rule 3**: reproduce every figure *exactly* as written — no rounding, no unit conversion.
- **Rule 4**: never perform arithmetic, never estimate an individual's entitlement — this is D2, restated directly in the prompt.
- **Rule 6**: if a source carries a known ambiguity flag, say so explicitly rather than silently filling the gap.

**A crucial mental model to take away here: a system prompt is a strong hint, not a guarantee.** This project's own documentation is explicit that D2 (never compute/estimate) is deliberately enforced in **three separate, independent places** — the prompt rule above, an early intent-classification check (`calculation_request` in `intents.py`, which routes calculation-flavored questions to a special response before generation even happens), *and* the Numeric Guard below, which checks the actual output after the fact. Why three layers for one rule? Because a single instruction in a prompt is not a hard constraint — models can and do violate instructions, especially under a phrasing that pressures them ("just give me a rough number," a real adversarial test case this project checks for). **Never rely on a prompt instruction alone for a safety property you actually care about; always add a mechanical check on the output too.** This is arguably the single most important lesson in this whole document for any RAG system that needs to be trustworthy, not just usually-correct.

Sources are handed to the model as document-order-sorted, numbered blocks:

```python
def build_source_block(sources: list[dict]) -> str:
    lines = []
    for s in sources:
        lines.append(f"[{s['tag']}] {s['clause_path']} (p.{s['page_start']})\n{s['text']}")
    return "\n\n".join(lines)
```

so the model can (and is instructed to) tag every factual sentence it writes with `[S1]`, `[S2]`, etc. — which is what makes the citation guard below possible: those tags are checkable, structured output, not free-form text the code has to interpret.

### The LLM provider abstraction (`backend/app/generation/llm_provider.py`)

**The concept:** the actual model that turns a prompt into text — Ollama running a small model locally, or a hosted API — is the one piece of this pipeline that's genuinely expensive on this project's hardware (no discrete GPU; more on this in Part 7). Everything else in the pipeline (embedding, retrieval, reranking) is designed to run comfortably on CPU. To keep from being locked into one specific way of running the LLM while that constraint is worked out, generation sits behind a small abstraction:

```python
def chat_completion(messages: list[ChatMessage], stream: bool = False, temperature: float = 0.1):
    client, model = _client_for(PROVIDER)   # "ollama" | "hosted" | "vllm"
    ...
```

Every provider — a local Ollama server, a hosted API, or (in the future) a vLLM server running on dedicated GPU hardware — is made to speak the same OpenAI-compatible `chat.completions` request shape, so switching between them is a single environment variable (`LLM_PROVIDER`), never a code change. This is a standard, worthwhile pattern any time a component of your system might need to move between "cheap and local" and "fast but external" depending on circumstances you don't fully control yet.

**Why the temperature is set low (0.1), and this is a good general RAG lesson too:** "temperature" controls how random/creative a model's output sampling is. High temperature is useful for creative writing, where you *want* varied, surprising output. This bot's actual job — faithfully paraphrasing retrieved text — is the opposite of creative writing. A low temperature keeps the model close to the most likely, most literal continuation of the prompt, which directly supports the "reproduce figures exactly" rule; a high temperature would actively fight against that goal.

**A real, concrete lesson in benchmark-before-you-configure, not benchmark-never:** the default configuration originally named a model (`qwen2.5:3b-instruct`) that wasn't actually installed on this development machine and would have required a fresh multi-gigabyte download. Rather than just picking whatever was already available, two of the actually-installed local models were benchmarked directly against this task:

```
llama3.2:1b: ~21.2 tok/s
gemma3:4b:   ~10.4 tok/s
```

`llama3.2:1b` is twice as fast. But the system prompt carries 8 strict rules (citations, never-arithmetic, exact figures, bilingual output, ambiguity disclosure) — a demanding instruction-following task — and a 1B-parameter model is a real risk for following that unreliably. An unreliable answer means the guards below trigger a retry, which costs *more* wall-clock time than the slower-but-more-reliable model would have taken generating a correct answer the first time. `gemma3:4b` was chosen as the default specifically for that reason, with the actual measured numbers and the reasoning both recorded in the code comment — not "seemed fine," a measured trade-off with the number attached.

### The guards — checking the LLM's output, not just trusting the prompt (`backend/app/generation/guards.py`)

This is the follow-through on the "prompt instructions aren't guarantees" lesson from above. Three checks run on every Tier-3 answer *after* generation, before it's returned to the user:

**1. Citation validity** — every `[Sn]` tag in the answer must refer to a source that was actually supplied:

```python
def citation_validity_guard(answer_text: str, num_sources: int) -> tuple[bool, list[str]]:
    tags = CITATION_TAG_RE.findall(answer_text)
    invalid = [f"[S{t}]" for t in tags if not (1 <= int(t) <= num_sources)]
    return (len(invalid) == 0, invalid)
```

Cheap, mechanical, and catches a real failure mode: a model inventing a `[S9]` when only 6 sources were given.

**2. The Numeric Guard — the single strongest safety mechanism in this whole project.** Every monetary figure, percentage, duration, and headcount in the generated answer is extracted and checked: **does it appear, verbatim (after normalization), somewhere in the actual retrieved context the model was shown?** Any number that doesn't is, by construction, either invented or the product of arithmetic the model wasn't supposed to do — both forbidden under D2. This is what makes "never compute or hallucinate a number" an *enforced property of the system*, not just a hopeful instruction.

**Challenge: the first version of this guard was too strict, and would have silently broken correct Hindi answers.** The very first implementation demanded *exact string* matching. This quietly conflicted with a separate goal — that Hindi and English answers should be equally well-supported. A Hindi answer correctly stating "₹25 lakh" as Devanagari digits (`२५ लाख`) or spelled-out Hindi number words (`पच्चीस लाख`) would match *nothing* in an English-only source string, purely because of surface-form differences, not because anything was actually wrong. The fix, in `normalize_numeric_text()`, is to normalize *both* the answer and the context before comparing — Devanagari digits to Latin, every spelling variant of "crore"/"lakh" (including, deliberately, the source's own "croe" typo) to one canonical form, every rupee-symbol variant to one marker — so a correctly-translated Hindi figure passes, while a genuinely invented one still fails:

```python
_UNIT_SYNONYMS = [
    (re.compile(r"\bcroe\b", re.IGNORECASE), "crore"),   # the source's own typo
    (re.compile(r"\bcror(?:es)?\b", re.IGNORECASE), "crore"),
    (re.compile(r"करोड़?", re.IGNORECASE), "crore"),
    (re.compile(r"\blakhs?\b", re.IGNORECASE), "lakh"),
    (re.compile(r"लाख", re.IGNORECASE), "lakh"),
    (re.compile(r"₹|Rs\.?,?\s?|INR\b", re.IGNORECASE), "RUPEE "),
]
```

Notice the deliberate inclusion of `croe` — the source PDF's own misspelling of "crore" (from `policy_data.py`, Part 2). If the guard didn't specifically fold that typo into the same normalized bucket as the correct spelling, a perfectly correct verbatim quotation of the source's own error would be wrongly flagged as an unsupported hallucination. This is a small but real detail worth remembering: your "correctness" checks need to be checked against your *actual* source data's actual quirks, not an idealized clean version of it.

**3. Ambiguity disclosure** — if any cited source carries a known-gap flag (from the 21-item register, Part 2), the answer must actually mention that gap (either the ambiguity ID itself, or a phrase like "clarification required"). If the model's answer omits it, the code deterministically appends the register's own disclosure text rather than asking the model to try again indefinitely.

**Which checks are allowed to block the response, and why that distinction matters for latency.** Citation validity and the Numeric Guard are cheap, deterministic, regex-based checks — they run in milliseconds and *can* trigger one automatic retry. A fourth, more thorough check — "does an independent judgment (e.g. another LLM call) agree this answer is actually grounded in its sources" — is explicitly documented as something that must run *asynchronously, after the fact*, into a review queue, never as a blocking step, because an LLM-based judgment call is exactly as slow as the generation step itself was, and blocking the user's response on *two* sequential slow LLM calls would make the system unusably slow. **Lesson: not every safety check needs to (or can afford to) block the response — separate "must be true before I answer" from "should be checked and flagged for a human, but the user doesn't have to wait for it."**

---

## Part 6 — Challenges faced, and how "test it for real" kept finding real bugs

This section exists because the challenges in getting this system *actually running* were at least as instructive as the architecture itself — and a junior engineer should see that a working RAG system is rarely "design it once, build it, done." Every one of these was found by actually executing code and reading real output, never by re-reading the plan and deciding it looked fine.

### 1. The vector-database API had silently moved on

The retrieval code was originally written against an older `qdrant-client` API shape (`client.search(query_vector=NamedVector(...))`). The **first time this code path was actually executed**, it failed immediately:

```
ImportError: cannot import name 'NamedSparseVector' from 'qdrant_client.models'
```

Investigating showed the installed `qdrant-client` version (1.19.0) had removed `client.search()` and the `NamedVector`/`NamedSparseVector` helper classes entirely, replacing them with a unified `client.query_points(query=..., using=<vector_name>)` call. **The lesson:** library APIs described in older tutorials, or even written from memory of "how this usually works," can be stale by the time you actually run the code — always verify against the version you actually have installed (`python -c "from qdrant_client import QdrantClient; import inspect; print(inspect.signature(QdrantClient.query_points))"` is exactly how this was diagnosed), rather than trusting recollection. The fix was mechanical once diagnosed — swap the call shape, keep the RRF fusion logic (which doesn't touch the vector-store API at all) unchanged.

### 2. A well-known library was broken against the installed version of a dependency it claimed to support

The reranker library (`FlagEmbedding`'s `FlagReranker` wrapper) failed with:

```
AttributeError: XLMRobertaTokenizer has no attribute prepare_for_model
```

`FlagEmbedding` declared compatibility with `transformers<6.0.0`, and the installed `transformers` was 5.15.1 — technically within that declared range, but the declaration turned out to be simply wrong for the 5.x line; the method the library's internal code called had been removed from the tokenizer class it expected. **First instinct — downgrade `transformers`** — made things *worse*, not better: downgrading to a 4.x release resolved the `prepare_for_model` error but immediately broke the *embedder* (which had been working fine under 5.15.1, since it doesn't hit this particular buggy code path), and at one specific downgrade target, pulled in a completely unrelated crash from a stray TensorFlow/Keras-3 installation on the machine — `ValueError: Your currently installed version of Keras is Keras 3, but this is not yet supported in Transformers.` A textbook dependency-conflict cascade: fixing one library's version compatibility broke a second, unrelated one.

**The actual fix was to stop treating the whole library as a black box and understand what it was doing internally.** BGE reranker models are, underneath `FlagReranker`'s convenience wrapper, just standard Hugging Face sequence-classification models — loadable directly with `AutoTokenizer` + `AutoModelForSequenceClassification`, which is in fact the model's own officially documented usage pattern, independent of `FlagEmbedding` entirely. `rerank.py` was rewritten to bypass `FlagReranker` and load the model this more direct way — keeping `transformers` at the version the (separately working) embedder needed, and sidestepping the buggy code path entirely rather than trying to make the buggy path work:

```python
_tokenizer = AutoTokenizer.from_pretrained(path)
_model = AutoModelForSequenceClassification.from_pretrained(path)
...
logits = model(**inputs, return_dict=True).logits.view(-1).float()
scores = torch.sigmoid(logits)
```

**Lesson:** when a convenience wrapper library breaks against your exact dependency versions, check whether the underlying model is actually a standard, directly-loadable architecture before assuming you're stuck. Often the wrapper is a thin, optional convenience — not the only way to use the model — and going one layer more direct can be both a fix and a simplification.

### 3. A promising optimization was abandoned once the real cost was understood — and that's a legitimate engineering decision, not a failure

Once retrieval was working end-to-end, it was measured (never assumed) to be slow: reranking 12 candidates took **~4–8 seconds**, dominating a total per-query latency of ~4.3–5.3 seconds (encoding: ~0.4s, vector search: ~0.06s, reranking: the rest). The architecture doc had already anticipated exactly this and named the fix: export the reranker model to ONNX format with int8 quantization, expected to give a 3–4× CPU speedup.

Attempting this surfaced a genuine, hard dependency conflict: the `optimum` library (which does the ONNX export) has a hard, source-level requirement of `transformers<4.58.0` — not a loose version-pin issue like challenge #2, but code that literally imports a function (`is_offline_mode`) that no longer exists in `transformers` 5.x at all. That's incompatible, at the source level, with the `transformers` 5.15.1 the embedder genuinely needs.

**The decision made here is worth studying as much as any successful fix: `optimum` was uninstalled, and the (already-correct, if slower) plain-`transformers` reranker from challenge #2 was kept as the shipped solution, with the ONNX optimization explicitly documented as a deferred follow-up rather than pursued further at that moment.** Untangling it properly would mean running the reranker in an isolated environment (a separate virtualenv or subprocess) just for that one optimization — a real, but disproportionate, amount of new complexity and risk for a latency improvement, when the system was already *correct*, just not yet as fast as the target. **This is a legitimate, disciplined engineering call, not giving up: correctness first, optimize once correctness is proven, and don't let chasing a performance number introduce a new source of fragility into a system that's already working.** Recognizing when to stop pulling on an optimization thread — and writing down exactly why, with the concrete blocker recorded, so the next person doesn't have to rediscover it — is as much a skill as writing the optimization in the first place.

### 4. Live, end-to-end testing found bugs that no unit test or code review had caught

Both the citation-ordering bug (Part 4, `_doc_order`) and the incomplete Hinglish wiring (Part 3) were found the same way: by actually starting the server, sending a real question through the real HTTP API, and reading the real answer with a critical eye — "does this citation actually point at the right thing?", "is this flag actually being used anywhere downstream?" — not by re-reading the code and deciding it looked correct. Both bugs were, in isolation, code that ran without any error and looked reasonable on inspection. **This is probably the single most important habit to take from this whole project: run the full system against real inputs, regularly, and read the output like a skeptical user, not just like a programmer checking for exceptions.** A pipeline with five correct-looking stages can still produce a wrong end-to-end answer, for reasons that only show up when you look at what actually comes out the other end.

---

## Part 7 — A constraint that shaped almost every decision: no GPU

This machine has **no discrete GPU** (AMD integrated graphics only, no CUDA). Every model in this pipeline — the embedder, the reranker, and (in the default local configuration) the LLM — runs on plain CPU. This single fact explains a large fraction of the design choices in this document, and it's worth collecting them in one place:

- **BGE-M3 over larger multilingual alternatives** (Part 2) — a 568M-parameter model is workable on CPU; a 9B-parameter alternative like `bge-multilingual-gemma2` would not be, for this corpus's modest gain.
- **Exact search instead of HNSW** (Part 2, Step 5) — moot on CPU either way at this corpus's scale, but the same "don't add machinery you don't need yet" instinct that avoided a GPU-hungry setup.
- **The reranker candidate count kept small (12, not 30)** (Part 4) — reranking is the measured bottleneck; fewer candidates directly trades a little theoretical recall for a lot of real wall-clock time.
- **The whole tiered response ladder** (Part 5) — the entire point of Tiers 0–2 is to avoid an LLM call whenever a verbatim quote is the mandated correct answer anyway, because the LLM call is, on this hardware, the single most expensive step by an order of magnitude.
- **The LLM provider abstraction** (Part 5) — lets generation move to a hosted API (fast, external) or stay local (slow, fully private) as a config change, precisely because CPU generation is genuinely too slow for a snappy live demo, while still being usable for correctness testing.
- **The abandoned ONNX optimization** (Part 6, challenge #3) — was specifically chasing this exact constraint; it just turned out not to be worth the dependency risk *yet*.

If you take one meta-lesson from this whole section: **know your actual hardware and actual data scale before choosing techniques, and re-check that assumption whenever it might have changed.** Several of this project's better decisions (exact search, dropping ColBERT, the tiered ladder) came from correctly recognizing "we don't need the usual heavyweight answer here" — and one of its real bugs (the original table-atom explosion, Part 2) came from *not* checking a similar assumption ("do these rows actually differ?") before building for the worst case.

---

## Part 8 — Testing and verification: "trust, but verify mechanically"

A pattern repeats throughout this project, and it's worth naming explicitly as something to imitate: **whenever a step depends on something that's easy to get subtly wrong — a hand-transcribed number, a repaired PDF page, a chunk-building rule — a separate, mechanical, boring verification script checks the *actual output* against a *known-independent ground truth*, and fails loudly if they disagree.**

| Script | What it mechanically checks |
|---|---|
| `verify_extraction.py` | The page 10 repair actually recovered known-good anchor phrases; page 8's emptiness is confirmed, not assumed |
| `verify_policy_data.py` | Every hand-transcribed rate/cap/figure in `policy_data.py` is actually findable, after normalization, in the raw extracted PDF text of the page it claims to be from; district counts and ambiguity-register counts match expected totals |
| `verify_chunks.py` | Exactly 25 table atoms (not 51, not some other accidental number); no duplicate chunk IDs; no two chunks share identical text; every `ambiguity_flags` reference resolves to a real register entry; every incentive/residual chunk that should carry a figure actually contains one |
| `tests/test_embedder.py` | The embedder never adds an instruction prefix (Part 2); `use_fp16` is correctly `False` on this CPU-only machine |

None of these are exotic — they're mostly regex checks, set differences, and string-containment tests. Their value isn't cleverness, it's that **they check the real artifact against an independent expectation, automatically, every time**, instead of relying on someone remembering to eyeball the output correctly forever. Notice, too, that several of these scripts (`verify_policy_data.py` especially) exist specifically because an *earlier* step in the pipeline (hand-transcription, to work around the table-detector bug from Part 2) traded one risk for a different one — and the response was to write a check for the *new* risk, not to assume the workaround was automatically safe.

---

## Glossary — quick reference

| Term | Meaning in this project |
|---|---|
| **RAG** | Retrieval-Augmented Generation: search a trusted knowledge base first, then have an LLM generate an answer from what was found, instead of from its training memory |
| **Chunk** | One retrievable unit of text; this project builds ~85, of five different types, deliberately not by fixed-size splitting |
| **Embedding** | A neural network's numeric-vector representation of a piece of text, such that similar meaning → nearby vectors |
| **Dense vector** | An embedding capturing semantic/conceptual similarity (this project: 1024 numbers per chunk, from BGE-M3) |
| **Sparse vector** | A vocabulary-sized, mostly-zero vector good at exact-token matching (numbers, section refs, acronyms) |
| **Hybrid search** | Searching both dense and sparse vector spaces and combining the results, to get both kinds of matching |
| **RRF (Reciprocal Rank Fusion)** | Combining multiple ranked lists by summing `1/(k+rank+1)` per list, rather than averaging raw scores on incompatible scales |
| **Bi-encoder** | Encodes query and passage separately, then compares vectors — fast, used for first-pass retrieval |
| **Cross-encoder / reranker** | Encodes query and passage *together*, more accurate but slower — used for a second, precision pass over a shortlist |
| **Coverage Gate** | This project's mechanism for deciding, from the reranker's score, whether to answer or to abstain |
| **Small-to-big retrieval** | Embed a small, precise chunk for search; hand the LLM a bigger `parent_text` for context |
| **Numeric Guard** | Post-generation check that every figure in an answer is verbatim (after normalization) in the retrieved context — the mechanical enforcement of "never invent a number" |
| **Tiered response ladder** | This project's efficiency design: try cache, then abstain-check, then a verbatim extractive answer, before ever calling the LLM |
| **Ambiguity register** | The 21-item catalogue of genuine defects/gaps in the source policy document, treated as first-class retrievable, citable content |
| **AMB-XX** | An individual ambiguity register entry's ID, e.g. `AMB-20` (Araria district missing from the policy's own district table) |
| **D1–D11** | This project's shorthand for its own numbered architectural decisions, referenced throughout the code comments — see `docs/RAG_IMPLEMENTATION.md` for the full list |

---

## Suggested way to actually learn this, hands-on

Reading this document once will not be enough — treat it as a map, then go walk the territory:

1. **Run the ingestion pipeline yourself, one step at a time**, printing/inspecting the output after each: `python -m app.ingestion.extract`, then look at `data/extracted/msme_policy_2026.raw.json`. Then `python -m app.ingestion.chunk`, and look at `data/chunks/msme_policy_2026.chunks.json` — find a `table_atom` chunk and a `guiding_clause` chunk and compare their `text` vs `parent_text`.
2. **Deliberately break something and see what catches it.** Change one figure in `policy_data.py` to a wrong number and run `verify_policy_data.py` — watch it fail. Put back the change, then try making one incentive row's `varies_by_category` wrong and run `verify_chunks.py`.
3. **Trace one real question through the whole pipeline by hand**, using `app/retrieval/pipeline.py`'s `retrieve()` function as your script: print the dense/sparse candidates, then the reranked scores, then the gate decision. Watch the same information the code sees.
4. **Read `chat.py`'s `chat()` function top to bottom** and, for a specific question you make up, predict *before running it* which tier it will land in and why. Then run it and see if you were right.
5. Once comfortable, **re-read `docs/RAG_IMPLEMENTATION.md`** (the original architecture document) — it will make much more sense now that you've seen the actual code it describes, and it's a good exercise to spot the handful of places where the *implementation* ended up differing from the *original plan* (the 51→25 table-atom count is one; there are others if you compare carefully).
