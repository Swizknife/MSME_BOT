---
okf_version: "0.2"
type: Bundle
title: "Bihar MSME Knowledge Bundle"
description: "Structured, provenance-tracked facts about Bihar and central MSME schemes, authored as a Google Open Knowledge Format bundle."
---

# Bihar MSME Knowledge Bundle

This directory is a [Google Open Knowledge Format](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md) v0.2 bundle.

Every file is one concept: YAML frontmatter for the structured facts, Markdown prose for what a person needs to know, and ordinary markdown links to related concepts. A compiler validates it and emits both machine-readable records and the chunks the retrieval layer searches.

Edit the Markdown. Never edit `data/okf_compiled/`, which is regenerated, or the search index directly.

- [schemes/index.md](schemes/index.md) — Top-level programmes and policies: the container every other fact hangs off.
- [incentives/index.md](incentives/index.md) — What a scheme offers, per enterprise category, with the rate quoted verbatim.
- [eligibility-rules/index.md](eligibility-rules/index.md) — Conditions a claimant must satisfy, one clause per note.
- [districts/index.md](districts/index.md) — Districts, and each source's classification of them, kept as separate concepts so two sources can disagree without collision.
- [sectors/index.md](sectors/index.md) — Sector lists, by classification (high priority, priority, emerging, negative list, heritage cluster).
- [glossary/index.md](glossary/index.md) — Terms and abbreviations, defined per scheme rather than globally, because the same term can mean different things under different schemes.
- [ambiguities/index.md](ambiguities/index.md) — Known defects in the source documents: missing rates, contradictions, undefined terms. The bot discloses these instead of guessing.
- [acts/index.md](acts/index.md) — Statutory instruments the schemes rest on.
