---
type: EligibilityRule
title: TREDS-OPERATOR-CAPITAL
description: An entity wishing to operate a TReDS platform must have minimum paid-up equity capital of Rs. 25 crore, since a TReDS operator cannot assume credit risk. Foreign shareholding follows the extant for...
status: stable
verified:
- by: claude-code/opus-5
  at: '2026-09-23T00:00:00'
sources:
- id: TREDS_RBI_FRAMEWORK
  resource: https://www.rbi.org.in/Scripts/bs_viewcontent.aspx?Id=3504
  title: TReDS -- RBI Framework/Directions
  source_document_version: RBI TReDS Guidelines, updated 2018-07-02
  fetch_date: '2026-09-23'
  fetch_method: manual
  extraction_method: hand_transcribed
  page_or_section_ref: RBI TReDS Guidelines (full page)
  verification_status: verified
  verified_by: Claude (WebFetch retrieval, quoted verbatim from the live RBI page)
  verified_at: '2026-09-23T00:00:00'
  checksum: null
rule_id: TREDS-OPERATOR-CAPITAL
applies_to:
- TREDS
condition_text: 'An entity wishing to operate a TReDS platform must have minimum paid-up equity capital of Rs. 25 crore, since a TReDS operator cannot assume credit risk. Foreign shareholding follows the extant foreign investment policy, with outside shareholders capped at 10% of equity capital, and promoters must demonstrate sound credentials and integrity with a minimum 5-year business track record.

  '
condition_type: investment_ceiling
parameters:
  min_paid_up_capital_inr: 250000000
  max_outside_shareholding_pct: 10
  min_promoter_track_record_years: 5
clause_ref: RBI TReDS Guidelines
cross_references:
- schemes/TREDS
last_compiled: null
---

## Who can operate a TReDS platform

This condition is about the companies licensed to run a TReDS platform
(e.g. RXIL, M1xchange, Invoicemart) — **not** about which MSMEs can use
one. An MSME asking "can I use TReDS?" should never be answered with this
figure; it answers a different question ("can my company start a TReDS
platform?"). See [TREDS](/schemes/TREDS.md) for the MSME-facing eligibility (none stated).
