---
type: EligibilityRule
title: MSME_SAMADHAAN-DELAYED-PAYMENT-INTEREST
description: The buyer is liable to pay compound interest with the monthly rests to the supplier on the amount at the three times of the bank rate notified by RBI in case he does not make payment to the supplie...
status: stable
verified:
- by: claude-code/opus-5
  at: '2026-09-23T00:00:00'
sources:
- id: MSME_SAMADHAAN
  resource: https://samadhaan.msme.gov.in/
  title: MSME Samadhaan / Delayed Payment Framework
  source_document_version: MSME Samadhaan homepage, fetched 2026-09-23
  fetch_date: '2026-09-23'
  fetch_method: manual
  extraction_method: hand_transcribed
  page_or_section_ref: MSME Samadhaan homepage
  verification_status: verified
  verified_by: Claude (WebFetch retrieval, quoted verbatim from the live MSME Samadhaan homepage)
  verified_at: '2026-09-23T00:00:00'
  checksum: null
rule_id: MSME_SAMADHAAN-DELAYED-PAYMENT-INTEREST
applies_to:
- MSME_SAMADHAAN
condition_text: 'The buyer is liable to pay compound interest with the monthly rests to the supplier on the amount at the three times of the bank rate notified by RBI in case he does not make payment to the supplier for his supplies of goods or services within 45 days of the acceptance of the goods/service rendered.

  '
condition_type: other
parameters:
  payment_window_days: 45
  interest_multiplier_of_rbi_bank_rate: 3
  compounding: monthly
clause_ref: MSMED Act 2006 (delayed payment provision, as described by MSME Samadhaan -- see MSMED_ACT_2006.md for why the primary section number is unconfirmed)
cross_references:
- schemes/MSME_SAMADHAAN
- acts/MSMED_ACT_2006
last_compiled: null
---

## Delayed payment interest — the real, on-record figure

This is a **statutory penalty a late-paying buyer owes**, not a subsidy or
incentive to the MSME. If a query is about "interest subsidy" (an
incentive, see `BIHAR_MSME_2026-AMB-03` — undefined rate, clarification
required) rather than "what happens if my buyer pays late" (this rule — a
concrete, on-record 3x-bank-rate penalty), the router must resolve to the
right one and never blend them into a single answer.
