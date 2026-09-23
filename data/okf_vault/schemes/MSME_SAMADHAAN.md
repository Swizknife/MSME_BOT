---
type: Scheme
title: MSME Samadhaan — Delayed Payment Monitoring System
description: An online portal for a Micro or Small Enterprise supplier to file a reference against a buyer who has not paid within the statutory window, for resolution before the Micro and Small Enterprises Fac...
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
scheme_id: MSME_SAMADHAAN
name: MSME Samadhaan — Delayed Payment Monitoring System
short_name: SAMADHAAN
issuing_authority_id: null
level: central
effective_from: null
effective_to: null
tier: P0
legal_basis:
- MSMED_ACT_2006
supersedes: null
summary: 'An online portal for a Micro or Small Enterprise supplier to file a reference against a buyer who has not paid within the statutory window, for resolution before the Micro and Small Enterprises Facilitation Council (MSEFC). Filing has since moved to the MSME ODR Portal (odr.msme.gov.in); this scheme record covers the underlying delayed- payment rule, which is unchanged.

  '
cross_references:
- eligibility-rules/MSME_SAMADHAAN-DELAYED-PAYMENT-INTEREST
- eligibility-rules/MSME_SAMADHAAN-MSEFC-90-DAY
last_compiled: null
scheme_status: active
---

## MSME Samadhaan

"Filing online application by the supplier MSE unit against the buyer of
goods/services before the concerned MSEFC." A supplier must be a valid
Micro or Small Enterprise with Udyam Registration to file. See
[MSME_SAMADHAAN-DELAYED-PAYMENT-INTEREST](/eligibility-rules/MSME_SAMADHAAN-DELAYED-PAYMENT-INTEREST.md) for the statutory interest
penalty on late payment, and [MSME_SAMADHAAN-MSEFC-90-DAY](/eligibility-rules/MSME_SAMADHAAN-MSEFC-90-DAY.md) for the
Council's resolution timeline.

> **Disambiguation this record exists to support.** This scheme's
> "interest" is a *statutory penalty rate a late-paying buyer owes a
> supplier* — a completely different thing from the Bihar MSME Policy
> 2026's "Interest Subsidy" (`BIHAR_MSME_2026-AMB-03`), which is a
> *state incentive with claim conditions but no stated rate*. Both
> legitimately use the word "interest." A query like "what's the interest
> rate for my MSME?" is genuinely ambiguous between the two, and the
> router must not silently pick one — see the eligibility rule body for
> the concrete figure this scheme actually provides.
