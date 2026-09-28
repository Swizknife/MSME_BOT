# Start Here — How This Project Works, Explained From Zero

**Who this is for:** you've just joined, and you may have never written a line
of code. That's fine. This document assumes you know nothing about chatbots,
databases, or AI, and builds everything up from the beginning.

Read it top to bottom once. Don't worry about memorising anything — the point
is that by the end, when someone says *"the coverage gate abstained because the
reranker score was below tau_hard"*, you'll know what they mean, and more
importantly, **why anyone would build such a thing**.

There is a glossary at the very end. Flip to it whenever a word feels slippery.

---

## Table of contents

1. [What we are actually building](#1-what-we-are-actually-building)
2. [Why this is harder than it sounds](#2-why-this-is-harder-than-it-sounds)
3. [The normal way to build this: RAG](#3-the-normal-way-to-build-this-rag)
4. [Where RAG breaks, with real examples from our data](#4-where-rag-breaks-with-real-examples-from-our-data)
5. [The second idea: OKF, Google's Open Knowledge Format](#5-the-second-idea-okf-googles-open-knowledge-format)
6. [Putting them together: OKF + RAG](#6-putting-them-together-okf--rag)
7. [The whole journey of one question](#7-the-whole-journey-of-one-question)
8. [The three modes, and the toggle in the app](#8-the-three-modes-and-the-toggle-in-the-app)
9. [A tour of every folder and file](#9-a-tour-of-every-folder-and-file)
10. [How to run it on your own machine](#10-how-to-run-it-on-your-own-machine)
11. [How we know it actually works](#11-how-we-know-it-actually-works)
12. [What is not built yet](#12-what-is-not-built-yet)
13. [Glossary](#13-glossary)

---

## 1. What we are actually building

The Government of Bihar has written a policy document: the **Bihar MSME Policy
2026**. MSME stands for *Micro, Small and Medium Enterprises* — small
businesses. The document is 27 pages of dense government language, and it
promises money to business owners: if you set up a small factory, the
government will pay back some percentage of what you spent.

A real person — say, someone who wants to open a food-processing unit — has
questions:

- *How much money will I actually get?*
- *Does my district qualify?*
- *What paperwork do I need?*

Today they have to read 27 pages of legal text, or queue at a government
office. **We are building a chatbot that answers those questions correctly, in
English or Hindi, and shows exactly which line of the policy each answer came
from.**

That last part is the whole job. Anyone can build a chatbot that *sounds*
confident. We are building one that is *right*, and that can prove it.

### The one rule that shapes everything

> **This assistant never makes up a number, and never calculates one.**

If the policy says "30% of your investment, capped at ₹25 lakh", the bot
repeats that sentence and points at the page it came from. It does **not** do
the multiplication for you, even if you tell it your investment amount.

Why so strict? Because this is a government service. If the bot tells someone
they'll receive ₹25 lakh and they don't, that's not an embarrassing bug — it's
a person who made a financial decision based on something we told them. So the
system is designed, at every level, to say *"I don't know"* rather than guess.
You'll see that principle show up again and again below.

---

## 2. Why this is harder than it sounds

Here is the thing people outside the project usually miss: **the source
document itself is flawed.** It's a draft. It has mistakes, gaps, and
contradictions. We found **21 of them** and wrote each one down.

Three real examples, because they drive almost every design decision later:

**Example A — the missing district.**
Bihar has 38 districts. The policy contains an annexure (an appendix) that
sorts districts into "Region A" and "Region B", because Region A gets 30% back
and Region B gets 25%. We counted the districts in that annexure. There are
**37**. The district of **Araria** appears in neither list.

So: what do we tell a business owner in Araria? The honest answer is *"the
policy does not say, and until the government clarifies, nobody can tell you."*
A chatbot that instead confidently says "25%" has invented a government
commitment. We track this as defect **AMB-20**.

**Example B — the incentive with no amount.**
The policy has a section describing an "Interest Subsidy". It explains *when*
you can claim it (once a year, after you've paid your interest in full). It
never says **how much**. There is no percentage, no cap, no duration —
anywhere in the document. We track this as **AMB-03**.

**Example C — the two spellings.**
The policy refers to another government scheme as "BIPP" in one place and
"BIIPP" in another, and gives it the year 2025 in one place and 2026 in
another. Are these the same document? Probably. Does the policy say so? No.
That's **AMB-01**.

**The lesson:** a good answer is often *"the document doesn't say."* Most
chatbot designs have no way to express that. Ours is built around it.

---

## 3. The normal way to build this: RAG

RAG stands for **Retrieval-Augmented Generation**. It is the standard recipe
for "chatbot that answers questions about my documents." Let's build the idea
up piece by piece.

### 3.1 The naive approach, and why it fails

You might think: just paste the whole 27-page policy into ChatGPT along with
the question. Two problems:

1. **Size.** Our policy is small, but we're adding more documents. You can't
   paste an entire library into every question.
2. **Distraction.** Give a language model 27 pages when only one paragraph is
   relevant, and its answer gets worse, not better.

So instead: **find the relevant bits first, then ask.** That's RAG.

### 3.2 Step one: chopping the document into chunks

We cut the document into small, self-contained pieces called **chunks**. Each
chunk is roughly one fact — one row of the incentive table, one eligibility
condition, one appendix list.

This sounds trivial. It isn't, and here's a real bug we hit. The policy's main
incentive table has rows like:

| Incentive | Micro | Small | Medium |
|---|---|---|---|
| Capital Subsidy | 30%, cap ₹25 lakh | 30%, cap ₹1.5 crore | 30%, cap ₹5 crore |

If you chop this carelessly, you can end up with a chunk that says "30%" and a
different chunk that says "cap ₹25 lakh" — and now the bot can tell someone
"30%, capped at ₹5 crore", mixing a micro-enterprise rate with a
medium-enterprise cap. Both numbers are real. The combination is fiction.

So we split that table **one cell per chunk**, keeping the rate and its cap
welded together. We call these **table atoms**. There are 25 of them.

We currently have **91 chunks** in total.

### 3.3 Step two: teaching a computer what words mean

Now the hard part. Someone asks *"kitni subsidy milegi?"* (Hindi-English mix
for "how much subsidy will I get?"). The policy never uses the word "kitni".
Plain text search finds nothing.

The trick is a thing called an **embedding**. An embedding turns a piece of
text into a long list of numbers — for us, 1024 of them — positioned so that
**texts with similar meaning get similar numbers.** Not similar spelling.
Similar *meaning*.

Picture a giant map where every sentence in the world has a location.
Sentences about subsidy amounts cluster in one neighbourhood; sentences about
paperwork deadlines cluster somewhere else. "How much subsidy will I get?" and
"kitni subsidy milegi?" land almost on top of each other, because they mean the
same thing — even though they share almost no letters.

The program that does this conversion is called an **embedding model**. Ours is
named **BGE-M3**, and we chose it because it understands English, Hindi, and
the romanised Hinglish mixture real users actually type.

We run every chunk through it once, in advance, and store the resulting
numbers in a **vector database** — a database built specifically for the
question *"which stored items are nearest to this one?"* Ours is called
**Qdrant**.

### 3.4 Step three: two kinds of search, combined

Meaning-based search has a blind spot: exact numbers. Ask about "₹24,000" and
meaning-based search may drift to generally-money-ish chunks instead of the
one containing that literal figure.

So we run **two** searches at once:

- **Dense search** — the meaning-based one just described.
- **Sparse search** — closer to old-fashioned keyword matching, which nails
  exact strings like `9.1(d)` or `₹24,000`.

Then we merge the two ranked lists using a method called **Reciprocal Rank
Fusion (RRF)**. The useful property of RRF is that it combines the lists by
*position* ("this was 2nd in one list and 5th in the other") rather than by
raw scores — which matters because the two kinds of search produce scores on
completely different scales that can't be meaningfully compared. Searching both
ways and fusing is called **hybrid search**.

### 3.5 Step four: a second, pickier opinion

Hybrid search gives us maybe 12 candidate chunks, fast but rough. Now we re-check
them with a slower, more accurate model called a **reranker** (ours is
**bge-reranker-v2-m3**).

The difference matters. The embedding model looked at the question and the
chunk *separately*, ahead of time. The reranker looks at the question and the
chunk **together**, right now, and scores how well that specific chunk answers
that specific question. Much better judgement, far too slow to run over
everything — which is exactly why we use the fast method to narrow to 12, then
the slow method to sort those 12.

### 3.6 Step five: knowing when to shut up

The reranker gives each chunk a score. Crucially, **a low score means nothing
in our library actually answers this question.**

So before we let the AI write anything, we check that score against two
thresholds. We call this the **Coverage Gate**:

- Score is high → answer normally.
- Score is middling → answer, but flag it as low confidence.
- Score is low → **abstain**. Don't call the AI at all. Say "this doesn't
  appear to be covered in the policy," and suggest related topics.

This is the single most important safety mechanism in the whole system. A
language model handed irrelevant text will still cheerfully write a
confident-sounding answer out of it. The Coverage Gate makes sure it never
gets the chance.

### 3.7 Step six: generation, then checking the AI's homework

Finally we hand the surviving chunks to a **large language model** (an LLM —
the technology behind ChatGPT; ours runs locally on your own machine via a tool
called **Ollama**, so no government data leaves the building) with strict
instructions: answer *only* from this text, cite your sources, never compute.

Then — and this is unusual — **we check its output before showing it to
anyone**. Automated checks called **guards**:

- **Numeric Guard** — pulls every number out of the AI's answer and verifies
  each one appears in the source text we gave it. Invented a figure? Blocked.
- **Citation Validity Guard** — if the answer cites `[S4]` but we only gave it
  three sources, that's a fabricated citation. Blocked.
- **Ambiguity Disclosure Guard** — if the answer touches a topic with a known
  defect (like Araria), the disclosure about that defect *must* appear. If the
  AI left it out, we append it.

When a guard fails, we don't show the broken answer. We fall back to quoting
the source text word-for-word.

That's RAG, end to end. It's a genuinely good design, and it was this entire
project for a while.

---

## 4. Where RAG breaks, with real examples from our data

RAG has two structural weaknesses. Not bugs — consequences of how it works.

### 4.1 Weakness one: it finds *passages*, not *answers*

RAG retrieves text that **resembles** your question. When the answer lives in
one paragraph, that works beautifully. When the answer must be **assembled
from several documents**, it fails — because no single passage resembles the
whole question.

Our standing example:

> *"Is a micro food-processing unit in Araria eligible, and for how much?"*

To answer, you need **five separate facts**:

1. Is food processing an eligible sector? (an appendix)
2. Which region is Araria in? (a different appendix)
3. What's the Capital Subsidy rate for that region? (the main table)
4. What's the cap for a *micro* enterprise? (same table, different column)
5. What conditions apply? (the conditions section)

No chunk contains all five. RAG searches for one passage that looks like the
question, finds nothing convincing, and abstains — or worse, grabs the
most-similar-looking chunk and answers from that alone.

This has a name: a **multi-hop question**, because answering it requires
hopping between facts. There's a published benchmark comparing approaches on
exactly this, and the numbers are striking: on multi-hop questions, ordinary
RAG scored **0.15 for correctness** while being rated **0.95 for
helpfulness**. Read that again — it was *confidently, fluently wrong* almost
every time.

### 4.2 Weakness two: it can't tell you what *isn't* there

Araria again. The policy simply doesn't classify it. But "absence" isn't a
passage — there's no paragraph reading *"we forgot Araria."* There is nothing
to retrieve. RAG is structurally blind to gaps, and a gap is exactly the thing
a user most needs warning about.

### 4.3 A real failure we recorded

Earlier in the project someone asked: *"What is the interest subsidy rate for
a micro enterprise?"*

The bot confidently answered with **30% / 25%** — real figures, quoted
accurately, properly cited. And **completely wrong**, because those are the
*Capital* Subsidy figures. The Interest Subsidy has no stated rate at all
(that's AMB-03 from section 2).

Notice what the guards could and couldn't do here. The Numeric Guard checked
"does this number appear in the retrieved text?" — yes, it did. The number was
real. The *topic* was wrong. No amount of checking figures against retrieved
text catches a confidently-retrieved wrong topic.

**That failure is why the rest of this document exists.**

---

## 5. The second idea: OKF, Google's Open Knowledge Format

### 5.1 What it is

In June 2026, Google Cloud published a specification called the **Open
Knowledge Format**, or **OKF**. (The spec lives at
[github.com/GoogleCloudPlatform/knowledge-catalog](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md);
it launched at version 0.1 and we build against **v0.2**.)

The problem Google set out to solve: organisations know things, but that
knowledge is scattered across wikis, spreadsheets, code comments and people's
heads. Every team building an AI assistant re-solves "how do I feed my
company's knowledge to a model?" from scratch, in an incompatible way.

OKF's answer is deliberately, almost aggressively unglamorous:

> **Write each piece of knowledge as one Markdown file with a small block of
> structured information at the top. Put those files in folders. That's it.**

No database. No special software. No vendor. Files in folders, readable by a
person in any text editor and by any program, forever.

> ⚠️ **A naming trap, worth knowing on day one.** An earlier version of this
> project invented its own name — "Open Knowledge *Framework*" — before anyone
> here knew Google's Open Knowledge *Format* existed. The names are nearly
> identical and the ideas turned out to be nearly identical too, which is a
> coincidence, not a lineage. We now conform to Google's real published
> specification. If you find an old note or comment saying "Framework",
> it's outdated — tell someone.

### 5.2 What one of our files actually looks like

Here is a real concept from our project, lightly trimmed:

```markdown
---
type: Incentive
title: Capital Subsidy
status: stable
verified:
  - by: process:verify_policy_data
sources:
  - id: BIHAR_MSME_POLICY_2026
    resource: "https://state.bihar.gov.in/industries/"
    page_start: 18
incentive_id: BIHAR_MSME_2026-S7.9-ITEM1
category_rates:
  - enterprise_category: micro
    rate_text: "30% of Fixed Capital Investment (Cap 25 Lakhs) in A Category
                District...; 25% ... in B Category District"
---

## Capital Subsidy

Region A districts receive 30%; Region B districts receive 25%.

See [AMB-01](/ambiguities/BIHAR_MSME_2026-AMB-01.md) on the BIPP/BIIPP
naming defect.
```

Three things to notice, because they're the whole point:

**The part between the `---` lines is structured data.** A program can read
`category_rates` and extract exactly the micro-enterprise rate. It doesn't have
to *interpret* anything. The answer to "what's the capital subsidy for a micro
enterprise?" is sitting in a labelled box.

**`rate_text` is copied word-for-word from the government document** — typos
included. We never clean it up. If the source says "croe" instead of "crore",
our file says "croe". The moment you start tidying a government figure, you've
started editing government policy.

**That link at the bottom is not decoration.** `[AMB-01](/ambiguities/...)` is
a real, machine-followable connection to another file. Thousands of these links
form a **graph** — a web of connected facts. Section 6 is about why that turns
out to be the most valuable thing in the entire system.

### 5.3 Provenance: every fact carries its receipts

Look again at the `sources` and `verified` blocks. Every single fact in our
system records **where it came from** and **who or what checked it**.

OKF defines three levels of trust, and we display them in the app as coloured
dots:

| Level | Meaning |
|---|---|
| **unverified** | Nobody has checked this yet |
| **machine-confirmed** | A program verified it against the source document |
| **human-reviewed** | A named person personally confirmed it |

Right now **225 of our 249 facts are machine-confirmed** and **24 are
unverified**. Zero are human-reviewed — not because nobody has done careful
work, but because *the files don't record a named human verifier*, and we
refuse to claim a level of scrutiny we can't point to. That restraint is the
feature.

### 5.4 The compiler: from friendly files to fast lookups

Markdown files are lovely for humans and too slow to search during a live
conversation. So a program called the **compiler**
(`backend/app/okf/compiler.py`) reads all 249 files and produces three things:

1. **Structured records** — one tidy machine-readable file per fact.
2. **RAG chunks** — the very same chunks the search engine indexes. *The
   knowledge is written once and feeds both systems.*
3. **The graph** — a map of all **249 concepts and 311 links** between them.

The compiler also refuses to accept bad input. If a file claims a rate the
source PDF doesn't contain, or links to a document that doesn't exist, **the
build fails.** You cannot commit a broken fact.

And it does something cleverer. It runs two automatic inspections:

- **The contradiction pass** — do any two sources disagree? (Two documents
  classifying the same district differently, say.)
- **The completeness pass** — is anything *missing*? It compares our records
  against known complete lists. This is what independently rediscovers the
  Araria gap: "you have 38 districts on file, the policy classifies 37, here's
  the one that's missing."

That second pass is the answer to RAG's blind spot from §4.2. **You can't
retrieve an absence, but you can compute one.**

---

## 6. Putting them together: OKF + RAG

Neither half is sufficient alone:

- **OKF alone** knows exact facts but can't explain, reason, or handle a
  question phrased in a way nobody anticipated.
- **RAG alone** handles open-ended language but hallucinates, can't assemble
  multi-hop answers, and can't see gaps.

Used together, each covers the other's weakness:

| | RAG alone | OKF alone | **Together** |
|---|---|---|---|
| "What's the capital subsidy rate?" | Usually right, slow, needs an AI | **Instant, exact** | Instant |
| "Why do I need EPF proof?" | **Good** | Can't answer | Good |
| "Micro food unit in Araria?" | Fails | Partial | **Works** |
| Can it tell you what's missing? | No | **Yes** | Yes |
| Can it invent a number? | Yes | **Never** | Only where RAG is used, and guarded |

### 6.1 The graph walk — the part that's genuinely new

This is the heart of the system, so let's go slowly.

Our 249 facts are connected by 311 links, and each link has a **type** and a
**strength**:

| Link type | Meaning | Strength |
|---|---|---|
| `governed_by` | this incentive is governed by that rule | 1.00 |
| `classifies` | this record classifies that district | 1.00 |
| `flagged_by` | this fact has that known defect | 0.95 |
| `in_scheme` | this belongs to that policy | 0.40 |
| `prose_link` | this file mentions that one in passing | 0.30 |

When a question arrives, instead of only searching for similar text, we:

1. **Find starting points.** Match names in the question against fact names —
   no AI, just matching. "Araria" → the Araria district file. "Food
   processing" → the food-processing sector file.
2. **Walk outward along the links**, up to two hops, preferring strong links.
3. **Collect everything reached** as evidence.

For the Araria question, that walk reaches **9 concepts and 8 citable chunks**,
including the actual Capital Subsidy rate *and* the record noting Araria was
never classified. No single search could have assembled that.

Two refinements we learned by testing, both of which are the kind of thing you
only discover by running the thing rather than reasoning about it:

**Hub suppression.** The main policy document is linked to by 156 of our 311
links — everything belongs to it. Walking freely *through* it turns every
question into "here is the entire policy." So we treat it as a destination but
barely a corridor: you can arrive there, but you leave only toward
answer-bearing things (incentives, rules, defects), never toward the 67 sector
files. Our first attempt blocked hubs entirely, which broke the Araria query in
the opposite direction — it reached the policy and then had nowhere to go,
returning three concepts and **zero quotable text**.

**Missing things are evidence.** Araria has *no links at all* — that's what
being unclassified means. A walk arriving there finds nothing onward, which
naively looks like failure. But we attach the compiler's completeness findings
to each concept, so arriving at Araria surfaces *"the policy classifies 37 of
38 districts; Araria is the missing one."* **The gap is the answer.**

### 6.2 The safety rule that must never move

One design decision is worth memorising, because it's the sort of thing that
can be casually "improved" into a disaster:

> **The Coverage Gate always decides using search results only, before any
> graph evidence is added.**

If graph-found chunks could raise the confidence score, then the graph could
quietly push a question past the "should I abstain?" check. Abstention is this
product's core safety property. So graph evidence can *add* citable material
after the decision is made — it can never *cause* the decision.

---

## 7. The whole journey of one question

Someone types a question. Here's everything that happens, in order. We call
this the **tiered ladder** — cheap, certain answers are tried first, and we
only reach the expensive, fallible AI if nothing better applies.

```
Question arrives
      │
      ▼
Is it a greeting or a complaint?  ──► canned reply. Done.
      │ no
      ▼
Asked this exact question before?  ──► TIER 0: cached answer. Done.
      │ no
      ▼
Does it name one specific fact
we hold, like "capital subsidy
for a micro enterprise"?           ──► TIER 1 (okf_lookup)
      │ no                              Read the answer straight out of the
      │                                 structured record. No search. No AI.
      │                                 ~3 milliseconds. Cannot hallucinate.
      ▼
Search the library (embed →
hybrid search → rerank)
      │
      ▼
Coverage Gate: is the best
match good enough?
      │
      ├── NO ──► Did the graph walk find
      │          enough solid, linked evidence?
      │              ├── YES ──► TIER 2a (graph)
      │              │           Assemble from the linked facts.
      │              │           Deterministic. No AI.
      │              └── NO  ──► TIER 2b (abstain)
      │                          "Not covered in this policy."
      │                          The AI is never called.
      ▼ YES
Does one chunk clearly answer
it on its own?                     ──► TIER 3 (extractive)
      │ no                              Quote it word-for-word + citation.
      │                                 No AI.
      ▼
TIER 4 (synthesis) — the only tier that uses AI
  • hand the AI the retrieved text, plus any exact OKF record,
    plus anything the graph found, plus any known gaps
  • it writes an answer
  • Numeric Guard      — every figure must appear in the source
  • Citation Guard     — every [S1] must be a real source
  • Consistency Guard  — figures must match the exact OKF record
  • Disclosure Guard   — known defects must be mentioned
  • any guard fails → discard it, quote the source instead
```

Notice how much of this never touches AI. Tiers 0, 1, 2a, 2b and 3 are all
deterministic — same input, same output, every time, with no possibility of
invention. **The AI is the last resort, not the default.**

---

## 8. The three modes, and the toggle in the app

Open the app and you'll see three buttons in the top-right: **RAG only / OKF
only / OKF + RAG**. They aren't cosmetic labels on the same engine — each runs
genuinely different code, so you can see for yourself what each layer
contributes.

| | `rag` | `okf` | `okf_rag` (default) |
|---|---|---|---|
| Searches the document library | Yes | **Never** | Yes |
| Uses structured facts | **Never** | Yes | Yes |
| Walks the concept graph | **Never** | Yes | Yes, seeded by search results too |
| Can reach Tier 1 / Tier 2a | No | Yes | Yes |

**RAG only** is a faithful reproduction of the ordinary chatbot design from
§3 — no structured fact ever reaches the answer or the guards. It's the
baseline, kept honest so the comparison means something.

**OKF + RAG** is more than the sum of the two. It seeds the graph walk using
what the search found, so it can start exploring from a concept the question
never actually named.

Two results measured on the running system:

| Question | RAG only | OKF + RAG |
|---|---|---|
| Araria multi-hop question | Abstains. Zero sources. | Answers with the real gap *and* the applicable figures |
| "Interest subsidy rate for a micro enterprise?" | Correct, but a full AI call: **78 seconds** | Same answer, **3 milliseconds**, no AI involved |

That second row deserves a note on intellectual honesty. RAG got it **right**.
Earlier in the project it got this exact question wrong (§4.3) — and the fix
was to write the missing fact into the OKF vault, which *also* produced a
better chunk for the search index. So fixing the structured layer improved the
RAG layer too. We could have quietly kept the old failing example to make our
architecture look better. We didn't, and you shouldn't either.

Under each answer there's a collapsible panel: **"How this answer was
assembled."** It shows the actual chain of concepts walked, with trust dots.
Switch to RAG-only and it vanishes, because that mode never walks the graph.
That absence is the demonstration.

---

## 9. A tour of every folder and file

```
NS-APP/
├── backend/        the brain (Python)
├── frontend/       the face (React/TypeScript)
├── data/           the knowledge
├── config/         the settings
└── docs/           the written record
```

### `data/` — the knowledge

| Path | What it is |
|---|---|
| `data/okf_vault/` | **The most important folder.** 249 Markdown files — every fact we know. Hand-editable. If you change one thing in this project, change it here. |
| `data/okf_vault/index.md` | Bundle front page; declares `okf_version: "0.2"` |
| `data/okf_vault/schemes/` | The policies and programmes themselves |
| `data/okf_vault/incentives/` | What money is offered, and how much |
| `data/okf_vault/eligibility-rules/` | Conditions you must meet |
| `data/okf_vault/districts/` | Districts and their region classifications |
| `data/okf_vault/sectors/` | Which industries qualify |
| `data/okf_vault/glossary/` | Terms, defined *per policy* (the same word can mean different things in different documents) |
| `data/okf_vault/ambiguities/` | The 21 known defects. A first-class citizen, not an afterthought |
| `data/okf_vault/acts/` | The laws underneath the policies |
| `data/okf_vault/_reference/` | Known-complete lists (e.g. all 38 districts) the completeness pass checks against |
| `data/okf_compiled/` | **Generated — never edit.** The compiler's output, including `graph.json` |
| `data/chunks/` | **Generated.** The search-ready chunks |
| `data/raw/` | Original source PDFs as downloaded |
| `data/raw/_inbox/` | Where to drop manually-downloaded government PDFs |
| `data/qdrant_local/` | The vector database's own files |

### `backend/app/okf/` — the OKF layer

| File | What it does |
|---|---|
| `okf_spec.py` | Google's spec, as code. Knows nothing about MSME policy |
| `schemas.py` | The shape a valid fact must have (an Incentive needs a rate, etc.) |
| `vault.py` | Reads and writes the Markdown files |
| `frontmatter.py` | Translates between OKF's vocabulary and ours |
| `links.py` | Understands what a link between two facts means. One definition, shared |
| `compiler.py` | **The heart.** Validates everything, runs the contradiction and completeness passes, emits all outputs |
| `chunk_from_okf.py` | Turns facts into search chunks |
| `graph_build.py` | Builds the map of 249 concepts and 311 links |
| `graph.py` | Walks that map when a question arrives |
| `store.py` | Fast lookup of a single fact |
| `migrate_policy_data.py` | Regenerates the 238 policy facts from the original hand-typed data |
| `migrate_to_okf_v02.py` | One-time conversion to Google's format |
| `verify_*.py` | Four separate programs that try to prove the others wrong (see §11) |

### `backend/app/retrieval/` — the search layer

| File | What it does |
|---|---|
| `embedder.py` | Turns text into 1024 numbers (BGE-M3) |
| `hybrid.py` | Dense + sparse search, fused with RRF |
| `rerank.py` | The slow, accurate second opinion |
| `coverage_gate.py` | Decides whether we're allowed to answer at all |
| `hinglish.py` | Handles romanised Hindi |
| `pipeline.py` | Runs the above in order |
| `qdrant_local.py` | Connection to the vector database |

### `backend/app/api/` — the conversation

| File | What it does |
|---|---|
| `chat.py` | The front door. Receives questions, returns answers |
| `evidence.py` | Decides what each of the three modes may use |
| `ladder.py` | The tiered ladder from §7 |

### `backend/app/generation/` — talking to the AI

| File | What it does |
|---|---|
| `prompts.py` | The instructions given to the AI |
| `llm_provider.py` | Connection to Ollama (swappable) |
| `guards.py` | The four checks on the AI's output |

### `backend/app/ingestion/` — the original pipeline

| File | What it does |
|---|---|
| `extract.py` | Pulls text out of PDFs |
| `policy_data.py` | The original hand-typed facts. **Frozen** — treated as a reference standard |
| `chunk.py` | The original chunker, now largely superseded |
| `embed_index.py` | Loads chunks into the vector database |
| `verify_policy_data.py`, `verify_chunks.py` | Independent checkers, also frozen |

### `backend/app/` — other

| Path | What it is |
|---|---|
| `main.py` | Starts the web server |
| `policy/intents.py` | Detects language and what kind of question this is |
| `policy/ambiguity_register.py` | Serves the defect disclosures |
| `acquisition/` | **Empty placeholder.** The automatic downloader isn't built yet (§12) |
| `db/`, `stubs/` | Empty placeholders for future work |

### `frontend/src/` — the interface

| File | What it does |
|---|---|
| `App.tsx` | The page |
| `api/chat.ts` | Talks to the backend |
| `components/ModeToggle.tsx` | The three-way architecture switch |
| `components/GraphPath.tsx` | "How this answer was assembled" |
| `components/SourceCitations.tsx` | Expandable citation chips, colour-coded by origin |
| `components/TierBadge.tsx` | Which tier answered, and how fast |
| `components/ChatMessage.tsx`, `ChatInput.tsx`, `StarterQuestions.tsx` | The rest of the chat UI |

### `config/`

| File | What it does |
|---|---|
| `sources.yaml` | All 24 government sources we intend to use, and their download rules |
| `thresholds.yaml` | The Coverage Gate's cut-offs |
| `graph.yaml` | How far the graph walk may travel |

---

## 10. How to run it on your own machine

You need **Python 3.13**, **Node 22**, and **Ollama**. Everything runs
locally — no cloud account, no GPU.

```bash
# 1. Backend setup (once)
cd backend
python -m venv .venv
source .venv/Scripts/activate      # Windows Git Bash
pip install -r requirements.txt

# 2. Frontend setup (once)
cd ../frontend
npm install

# 3. The local AI model (once)
ollama pull gemma3:4b
```

You'll need **6–8 GB of free disk space** the first time: the search models
(~3.4 GB) download once and are cached, plus the Ollama model.

Then build the knowledge base. **Order matters** — each step eats the previous
step's output:

```bash
cd backend
python -m app.okf.compile          # 249 files → records + chunks + graph
python -m app.ingestion.embed_index # chunks → vector database
```

> ⚠️ **One at a time.** The local vector database can only be open in one
> program at once. Let `embed_index` finish completely before starting the
> server, or you'll get a "storage folder is already accessed" error. This is
> expected behaviour, not a bug.

Now run it, in two terminals:

```bash
# Terminal 1
cd backend && python -m uvicorn app.main:app --port 8000

# Terminal 2
cd frontend && npm run dev
```

Open **http://localhost:5173**.

The first question is slow (30–60s) because the AI models load into memory.
After that it's quick. Questions that reach Tier 4 take a while — the AI is
running on your CPU.

---

## 11. How we know it actually works

This project's culture, stated plainly: **a change isn't finished until
something mechanical proves it didn't break anything.** We don't rely on
reading code carefully. We rely on programs that try to prove us wrong.

Run all of these from `backend/`:

| Command | What it proves |
|---|---|
| `python -m pytest` | 51 automated tests pass |
| `python -m app.okf.verify_okf` | All 249 files are valid OKF v0.2; every link resolves; no old-format leftovers |
| `python -m app.okf.verify_migration` | Every generated file is **byte-for-byte identical** to a fresh regeneration — nothing has drifted |
| `python -m app.okf.verify_compile` | All 85 original chunks still come out identical to before the rebuild |
| `python -m app.ingestion.verify_policy_data` | Every figure still matches the text extracted from the PDF |
| `python -m app.ingestion.verify_chunks` | Chunks are well-formed and all references resolve |

Note that these check each other from different angles. `verify_policy_data`
compares facts against the original PDF. `verify_compile` compares today's
output against output from before the rebuild. `verify_migration` compares
files on disk against freshly generated ones. For a wrong fact to slip
through, it would have to fool all three independently.

**Two files are deliberately frozen**: `policy_data.py` and
`msme_policy_2026.chunks.json`. Nothing may modify them. They're the fixed
reference point everything else is measured against — like a standard weight
in a laboratory.

### Bugs we only found by actually running things

Worth internalising, because every single one passed code review:

- Links were being rewritten to point at folders that were about to be
  deleted. Because OKF deliberately tolerates broken links, **nothing would
  have errored** — the system would have silently lost all 73 connections.
- A "fast lookup" tier was accidentally doing the slow search first, erasing
  the entire point of it. The answer was still correct, just 100× slower.
- In OKF-only mode, citations were labelled as coming from the search
  engine — which hadn't run at all.
- A working graph walk was silently dropped from the UI on the most common
  answer type.

**Test what you built. Actually run it. Look at the real output.**

---

## 12. What is not built yet

Honesty about the state of things, so you're not surprised:

- **The automatic downloader doesn't exist.** `backend/app/acquisition/` is a
  documentation comment and nothing else. Of the 24 government sources listed
  in `config/sources.yaml`, **4 have ever been fetched and 20 have never been
  attempted.**
- **Most source documents are still missing**, including the BIIPP district
  categorisation — the single most valuable one, because it's a *second*
  opinion on district classification, which is what would let the
  contradiction detector do its job for real. Several government portals block
  automated downloads, so a person has to fetch them by hand into
  `data/raw/_inbox/`.
- **No fact is human-reviewed yet** (§5.3).
- **The Bihar MSME Policy 2026 is still a draft** and has not been notified by
  the government. Nothing in it is currently legally in force. Every answer
  the bot gives says so.

### Where to start

1. Run it (§10). Ask it things. Flip the toggle and watch the answers change.
2. Open `data/okf_vault/incentives/` and read a few files. That's the whole
   knowledge base, in plain text.
3. Open `data/okf_vault/ambiguities/` and read all 21. That's what careful
   work on a flawed document actually looks like.
4. Run the verifiers in §11 and watch them pass.
5. Then break something on purpose — change a rate in a vault file, re-run
   `python -m app.okf.compile`, and watch the build refuse it. That's the
   safety net catching you.

---

## 13. Glossary

| Term | Plain meaning |
|---|---|
| **Abstain** | Refusing to answer because we're not confident. A feature |
| **AMB-XX** | A numbered known defect in the source document (we have 21) |
| **BGE-M3** | The model that converts text into numbers for meaning-based search |
| **Chunk** | One small, self-contained piece of a document |
| **Coverage Gate** | The check that decides whether we're confident enough to answer |
| **Compiler** | The program that turns our Markdown files into everything else |
| **Dense search** | Search by meaning |
| **Embedding** | A list of numbers representing a piece of text's meaning |
| **Graph** | The web of links connecting our facts |
| **Guard** | An automatic check on the AI's output before a human sees it |
| **Hallucination** | When an AI confidently states something false |
| **Hop** | One step along a link in the graph |
| **Hybrid search** | Dense and sparse search combined |
| **LLM** | Large Language Model — the AI that writes sentences |
| **Multi-hop question** | A question needing several facts combined |
| **OKF** | Google's Open Knowledge Format — knowledge as Markdown files |
| **Ollama** | The tool that runs the AI locally on your machine |
| **Provenance** | The record of where a fact came from and who checked it |
| **Qdrant** | The database built for searching by meaning |
| **RAG** | Retrieval-Augmented Generation — find relevant text, then ask the AI |
| **Reranker** | The slow, accurate model that re-sorts search results |
| **RRF** | The method for merging two ranked lists by position |
| **Sparse search** | Search by exact words and numbers |
| **Table atom** | One cell of the incentive table, kept whole |
| **Tier** | One rung of the answer ladder (§7) |
| **Trust tier** | unverified / machine-confirmed / human-reviewed |
| **Vault** | `data/okf_vault/` — our 249 Markdown fact files |
| **Vector database** | A database that finds things by similarity of meaning |

---

*If something here is wrong or unclear, that's a bug in this document. Say so.*
