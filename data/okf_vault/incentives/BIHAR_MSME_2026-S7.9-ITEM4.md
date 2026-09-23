---
type: Incentive
title: Payroll subsidy
status: stable
generated:
  by: process:migrate_policy_data
verified:
- by: process:verify_policy_data
  at: '2026-09-23T00:00:00'
sources:
- id: BIHAR_MSME_POLICY_2026
  resource: https://state.bihar.gov.in/industries/
  title: Bihar MSME Policy 2026 (Draft)
  source_document_version: draft-v1
  fetch_date: '2026-08-23'
  fetch_method: manual
  extraction_method: hand_transcribed
  page_or_section_ref: section 7.9, item 4
  page_start: 18
  page_end: 18
  verification_status: verified
  verified_by: verify_policy_data.py (figure tokens checked against extracted text)
  verified_at: '2026-09-23T00:00:00'
  checksum: null
incentive_id: BIHAR_MSME_2026-S7.9-ITEM4
scheme_id: BIHAR_MSME_2026
name: Payroll subsidy
item_no: '4'
incentive_type: payroll_subsidy
category_rates:
- enterprise_category: micro
  rate_text: Reimbursement of employer's contribution to the EPF for the first three years from the date of commencement of production, if the unit has employed more than 10 persons, subject to a maximum of Rs, 24,000/- per employee per annum
  rate_value: null
  cap_value: null
  cap_unit: null
- enterprise_category: small
  rate_text: Reimbursement of employer's contribution to the EPF for the first three years from the date of commencement of production, if the unit has employed more than 20 persons, subject to a maximum of Rs, 24,000/- per employee per annum
  rate_value: null
  cap_value: null
  cap_unit: null
- enterprise_category: medium
  rate_text: Reimbursement of employer's contribution to the EPF for the first three years from the date of commencement of production, if the unit has employed more than 50 persons, subject to a maximum of Rs, 24,000/- per employee per annum
  rate_value: null
  cap_value: null
  cap_unit: null
varies_by_category: true
district_scope: []
sector_scope: []
eligibility_rule_ids:
- BIHAR_MSME_2026-S9.4-a
- BIHAR_MSME_2026-S9.4-b
- BIHAR_MSME_2026-S9.4-c
- BIHAR_MSME_2026-S9.4-d
ambiguity_flags: []
cross_references: []
incentive_status: active
---

## Payroll subsidy

Item 4 of the section 7.9 financial incentive table (page 18).

This incentive's terms differ by enterprise category; see the per-category rates above.

Governing conditions: section(s) 9.4.
