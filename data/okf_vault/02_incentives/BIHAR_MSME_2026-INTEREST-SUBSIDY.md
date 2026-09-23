---
entity_type: incentive
incentive_id: BIHAR_MSME_2026-INTEREST-SUBSIDY
scheme_id: BIHAR_MSME_2026
name: "Interest Subsidy"
item_no: null
incentive_type: interest_subsidy
category_rates:
  - enterprise_category: micro
    rate_text: "NO RATE/AMOUNT SPECIFIED IN SOURCE -- section 9.2 states claim conditions (annual basis; claimable only after full interest payment) but no rate, cap, or tenure anywhere in the document"
    rate_value: null
    cap_value: null
    cap_unit: null
  - enterprise_category: small
    rate_text: "NO RATE/AMOUNT SPECIFIED IN SOURCE -- section 9.2 states claim conditions (annual basis; claimable only after full interest payment) but no rate, cap, or tenure anywhere in the document"
    rate_value: null
    cap_value: null
    cap_unit: null
  - enterprise_category: medium
    rate_text: "NO RATE/AMOUNT SPECIFIED IN SOURCE -- section 9.2 states claim conditions (annual basis; claimable only after full interest payment) but no rate, cap, or tenure anywhere in the document"
    rate_value: null
    cap_value: null
    cap_unit: null
varies_by_category: false
district_scope: []
sector_scope: []
eligibility_rule_ids: ["BIHAR_MSME_2026-S9.2-a", "BIHAR_MSME_2026-S9.2-b"]
ambiguity_flags: ["BIHAR_MSME_2026-AMB-03"]
status: rate_unstated
source:
  source_id: BIHAR_MSME_POLICY_2026
  source_url: "https://state.bihar.gov.in/industries/"
  source_document_version: draft-v1
  fetch_date: "2026-08-23"
  fetch_method: manual
  extraction_method: hand_transcribed
  page_or_section_ref: "section 9.2"
  page_start: 21
  page_end: 21
  verification_status: verified
  verified_by: "verify_policy_data.py (figure tokens checked against extracted text)"
  verified_at: "2026-09-23T00:00:00"
  checksum: null
cross_references: ["[[BIHAR_MSME_2026-AMB-03]]"]
last_compiled: null
---

## Interest Subsidy

**Why this note exists, added after the original migration.** The
§7.9 financial incentive table has no "Interest Subsidy" row at all --
`INCENTIVE_TABLE` in `policy_data.py` never contained one, so nothing in
the original migration created an OKF record for it, and the OKF router
had nothing to match a query like "what is the interest subsidy rate?"
against. That query was tested end-to-end and mis-retrieved Capital
Subsidy's table entry instead -- not a hallucination (the retrieved
figures were real, verbatim, correctly grounded in *some* chunk), but a
retrieval relevance failure numeric_guard cannot catch, because the wrong
topic was retrieved confidently, not an invented one.

Section 9.2 states Interest Subsidy's *claim conditions* (annual basis;
claimable only after full interest payment) without ever stating a rate,
cap, or duration anywhere in the document -- exactly what
[[BIHAR_MSME_2026-AMB-03]] (`severity: blocking`) already documents. This
record exists so a query naming "Interest Subsidy" resolves to that
disclosure deterministically, the same way the Revival Package
(`status: rate_unstated`) already does for its own no-rate gap, instead of
falling through to RAG and risking exactly the mis-retrieval this note was
authored to fix.
