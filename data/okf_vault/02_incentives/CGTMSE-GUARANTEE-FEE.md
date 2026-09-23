---
entity_type: incentive
incentive_id: CGTMSE-GUARANTEE-FEE
scheme_id: CGTMSE
name: "Credit Guarantee Fee"
item_no: null
incentive_type: guarantee_fee
category_rates:
  - enterprise_category: other
    rate_text: "Reduced the guarantee fee to a minimum level of 0.37% pa"
    rate_value: 0.0037
    cap_value: 100000000
    cap_unit: INR
varies_by_category: false
district_scope: []
sector_scope: []
eligibility_rule_ids: []
ambiguity_flags: ["CGTMSE-AMB-01"]
status: active
source:
  source_id: CGTMSE_SCHEME_GUIDELINES
  source_url: "https://www.cgtmse.in/"
  source_document_version: "CGTMSE homepage, fetched 2026-09-23"
  fetch_date: "2026-09-23"
  fetch_method: manual
  extraction_method: hand_transcribed
  page_or_section_ref: "CGTMSE homepage"
  verification_status: verified
  verified_by: "Claude (WebFetch retrieval, quoted verbatim from the live CGTMSE homepage)"
  verified_at: "2026-09-23T00:00:00"
  checksum: null
cross_references: ["[[CGTMSE]]", "[[CGTMSE-AMB-01]]"]
last_compiled: null
---

## Credit Guarantee Fee under CGTMSE

The minimum annual guarantee fee CGTMSE charges is 0.37% per annum,
against a guarantee coverage ceiling of ₹10 crore. `enterprise_category`
is set to `other` rather than micro/small/medium because the homepage
does not state a fee that varies by enterprise category — see
[[CGTMSE-AMB-01]] for what is and isn't confirmed here.
