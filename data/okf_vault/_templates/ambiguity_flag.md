---
entity_type: ambiguity_flag
id: ""                          # namespaced per source, e.g. "BIHAR_MSME_2026-AMB-03"
scope: ""                        # single_source | cross_source
source_ids: []                    # 1 for single_source; 2+ for cross_source
clause_refs: []
issue_type: ""                     # missing_rate | contradiction | undefined_term | external_dependency
                                     # | inoperative | scope_gap | typo | subjective | status | ingestion
                                     # | cross_source_contradiction | stale_source | citation_ambiguity
severity: ""                        # blocking | advisory
description: ""                      # internal, precise, for reviewers
public_disclosure_en: ""              # verbatim user-facing text
public_disclosure_hi: ""
status: ""                             # open | clarified | superseded
resolution: null
resolved_by: null
resolved_at: null
supersedes_version: null
cross_references: []
last_compiled: null
---

<!-- severity: blocking means the bot MUST NOT state a figure for whatever
     this flag attaches to -- it returns the public_disclosure text instead.
     Auto-detected cross_source_contradiction entries (emitted by the
     compiler's natural-key diff pass, not hand-authored) always start at
     severity: advisory; a human must explicitly promote to blocking. -->
