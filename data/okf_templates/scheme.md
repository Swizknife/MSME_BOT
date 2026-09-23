---
entity_type: scheme
scheme_id: ""              # UPPER_SNAKE_CASE, unique, e.g. "CGTMSE"
name: ""                    # full official name
short_name: ""               # citation tag, <=12 chars, e.g. "CGTMSE"
issuing_authority_id: ""      # ref -> an authority_id in 04_authorities/
level: ""                     # central | state
status: ""                    # draft_not_notified | notified | active | superseded | proposed | withdrawn
effective_from: null          # date or null
effective_to: null            # date or null
tier: ""                      # P0 | P1 | P2 | P3 (acquisition-phase tag, not a policy concept)
legal_basis: []                # list of act_ids in 09_acts/, if any
supersedes: null               # scheme_id this replaces, or null
summary: ""                    # one or two plain-language sentences
source:
  source_id: ""                 # must match an entry in config/sources.yaml
  source_url: ""
  source_document_version: ""
  fetch_date: null
  fetch_method: ""              # html_scrape | pdf_download | api | manual
  extraction_method: ""         # hand_transcribed | table_detector | ocr | api_field
  page_or_section_ref: ""
  verification_status: ""       # verified | unverified | superseded | disputed
  verified_by: ""
  verified_at: null
  checksum: ""
cross_references: []            # ["[[OTHER-ID]]", ...]
last_compiled: null              # filled by the compiler; never hand-edit
---

<!-- Plain-language summary of what this scheme is, who runs it, who it's
     for, and how it relates to other schemes. Use [[wikilinks]] to related
     Scheme/Incentive/Authority notes. -->
