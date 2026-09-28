---
entity_type: incentive
incentive_id: ""             # UPPER-SNAKE, unique, e.g. "CGTMSE-GUARANTEE-FEE-2024"
scheme_id: ""                 # ref -> a scheme_id in 01_schemes/
name: ""
incentive_type: ""            # capital_subsidy | interest_subsidy | payroll_subsidy | guarantee_fee
                                # | grant_in_aid | tax_exemption | power_tariff_subsidy | other
category_rates:                 # one entry per enterprise category this rate varies by
  - enterprise_category: ""      # micro | small | medium | other
    rate_text: ""                 # VERBATIM from the source, including its own typos -- never corrected
    rate_value: null               # normalized numeric (e.g. 0.30 for 30%), or null if not a clean single %
    cap_value: null
    cap_unit: null                 # e.g. "INR"
varies_by_category: false
district_scope: []               # list of district_id refs, or [] for state/nationwide
sector_scope: []                  # list of sector_id refs, or [] for all sectors
eligibility_rule_ids: []           # refs -> 03_eligibility_rules/
ambiguity_flags: []                 # refs -> 08_ambiguities/, if this rate has a known issue
status: ""                          # active | rate_unstated | superseded
source:
  source_id: ""
  source_url: ""
  source_document_version: ""
  fetch_date: null
  fetch_method: ""
  extraction_method: ""
  page_or_section_ref: ""
  verification_status: ""
  verified_by: ""
  verified_at: null
  checksum: ""
cross_references: []
last_compiled: null
---

<!-- Plain-language explanation of what this incentive covers, and any
     conditions the reader needs to know before quoting the figure above.
     [[wikilink]] to the eligibility rules and the parent scheme. -->
