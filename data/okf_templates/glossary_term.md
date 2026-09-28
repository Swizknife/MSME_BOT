---
entity_type: glossary_term
term_id: ""                    # slug, e.g. "MSME", "EPF", "FCI"
term: ""                         # display form, e.g. "Fixed Capital Investment"
definitions:
  - scheme_id: ""                 # which scheme this definition applies under -- REQUIRED, not optional
    definition_text: ""
    source:
      source_id: ""
      source_url: ""
      fetch_date: null
      page_or_section_ref: ""
      verification_status: ""
cross_scheme_conflict: false       # set true if two definitions[] entries materially differ
last_compiled: null
---

<!-- If the same term means different things under different schemes (e.g.
     "MSME" thresholds under the MSMED Act vs. the revised Udyam
     notification), add one definitions[] entry per scheme rather than
     picking one -- this is the single biggest source of wrong-source
     conflation bugs at multi-source scale. Set cross_scheme_conflict: true
     and consider authoring a linked ambiguity_flag note. -->
