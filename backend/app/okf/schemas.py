"""OKF entity schemas -- Phase 0 (schema lock).

These Pydantic models are the frozen contract for every fact authored in
``data/okf_vault/``. They are the single source of truth for what a valid
vault note's frontmatter must contain; the vault compiler (Phase 1,
``backend/app/okf/compiler.py``, not built yet) will parse each note's
YAML frontmatter and validate it against the matching model here before
emitting a compiled OKF record or a RAG chunk.

Every model here is a direct generalization of something that already
existed narrowly in this codebase before the OKF rebuild:

  - Scheme              generalizes the hardcoded POLICY_ID/POLICY_VERSION
                         constants that used to assume one document.
  - Incentive            generalizes IncentiveRow in
                         backend/app/ingestion/policy_data.py. It also
                         absorbs ResidualIncentive from the same module
                         (the section-8 residual items, which state a rate
                         as one free-text 'detail' with no per-category
                         breakdown): those map to a single CategoryRate
                         with enterprise_category=other and the detail
                         text verbatim in rate_text, so the figure stays
                         in a structured field the Numeric Guard can use
                         as ground truth rather than living only in prose.
  - EligibilityRule       generalizes the Section 9 "guiding principles"
                         clauses hand-encoded in policy_data.py.
  - Authority              generalizes hardcoded "DIC"/helpline strings in
                         backend/app/policy/intents.py.
  - District / DistrictClassification
                            generalizes the flat district_region payload
                         field, deliberately split into two entities so two
                         sources can disagree on a district's category
                         without collision (see AMB-01 in the pre-OKF
                         ambiguity register: the BIPP/BIIPP naming and
                         year-mismatch defect).
  - Sector                 generalizes the five separate flat lists
                         (HIGH_PRIORITY_SECTORS, PRIORITY_SECTORS,
                         EMERGING_INDUSTRIES, NEGATIVE_LIST,
                         HERITAGE_CLUSTERS) into one entity family with a
                         classification_type.
  - GlossaryTerm            generalizes the flat ABBREVIATIONS dict; NOT a
                         flat term->definition mapping, because the same
                         term can mean different things under different
                         schemes (see the "cross-source citation ambiguity"
                         risk in docs/OKF_RAG_IMPLEMENTATION.md).
  - AmbiguityFlag           generalizes AmbiguityEntry in policy_data.py.
  - Act / LegalProvision    new entity, needed once statutory sources
                         (MSMED Act 2006, Udyam Registration's legal basis)
                         enter the corpus.

Nothing in this module reads or writes files yet -- that is the compiler's
job (Phase 1). This module only defines what "valid" means.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Shared provenance block -- every entity carries one.
# ---------------------------------------------------------------------------


class FetchMethod(str, Enum):
    HTML_SCRAPE = "html_scrape"
    PDF_DOWNLOAD = "pdf_download"
    API = "api"
    MANUAL = "manual"


class ExtractionMethod(str, Enum):
    HAND_TRANSCRIBED = "hand_transcribed"
    TABLE_DETECTOR = "table_detector"
    OCR = "ocr"
    API_FIELD = "api_field"


class VerificationStatus(str, Enum):
    VERIFIED = "verified"
    UNVERIFIED = "unverified"
    SUPERSEDED = "superseded"
    DISPUTED = "disputed"


class Provenance(BaseModel):
    source_id: str = Field(..., description="Must match an entry in config/sources.yaml")
    source_url: str
    source_document_version: Optional[str] = None
    fetch_date: Optional[date] = None
    fetch_method: FetchMethod
    extraction_method: Optional[ExtractionMethod] = None
    page_or_section_ref: Optional[str] = None
    # Structured page range, kept alongside the human-readable ref above.
    # Phase 1 amendment: needed because RAG chunks carry integer page_start/
    # page_end for citation display, and parsing them back out of a free-text
    # "Chapter III, para 3.2" style ref is not reliable.
    page_start: Optional[int] = None
    page_end: Optional[int] = None
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED
    verified_by: Optional[str] = None
    verified_at: Optional[datetime] = None
    checksum: Optional[str] = None


# ---------------------------------------------------------------------------
# Scheme
# ---------------------------------------------------------------------------


class SchemeLevel(str, Enum):
    CENTRAL = "central"
    STATE = "state"


class SchemeStatus(str, Enum):
    DRAFT_NOT_NOTIFIED = "draft_not_notified"
    NOTIFIED = "notified"
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    PROPOSED = "proposed"
    WITHDRAWN = "withdrawn"


class SourceTier(str, Enum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"


class Scheme(BaseModel):
    scheme_id: str
    name: str
    short_name: str = Field(..., max_length=12, description="Citation tag, e.g. 'CGTMSE'")
    issuing_authority_id: Optional[str] = None
    level: SchemeLevel
    status: SchemeStatus
    effective_from: Optional[date] = None
    effective_to: Optional[date] = None
    tier: SourceTier
    legal_basis: list[str] = Field(default_factory=list)
    supersedes: Optional[str] = None
    summary: str
    source: Provenance
    cross_references: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Incentive
# ---------------------------------------------------------------------------


class IncentiveType(str, Enum):
    CAPITAL_SUBSIDY = "capital_subsidy"
    INTEREST_SUBSIDY = "interest_subsidy"
    PAYROLL_SUBSIDY = "payroll_subsidy"
    GUARANTEE_FEE = "guarantee_fee"
    GRANT_IN_AID = "grant_in_aid"
    TAX_EXEMPTION = "tax_exemption"
    POWER_TARIFF_SUBSIDY = "power_tariff_subsidy"
    OTHER = "other"


class EnterpriseCategory(str, Enum):
    MICRO = "micro"
    SMALL = "small"
    MEDIUM = "medium"
    OTHER = "other"


class IncentiveStatus(str, Enum):
    ACTIVE = "active"
    RATE_UNSTATED = "rate_unstated"
    SUPERSEDED = "superseded"


class CategoryRate(BaseModel):
    enterprise_category: EnterpriseCategory
    rate_text: str = Field(
        ...,
        description="Verbatim from the source, including its own typos. Never corrected.",
    )
    rate_value: Optional[float] = Field(
        None, description="Normalized numeric, e.g. 0.30 for 30%. Null if not a clean single %."
    )
    cap_value: Optional[float] = None
    cap_unit: Optional[str] = None


class Incentive(BaseModel):
    incentive_id: str
    scheme_id: str
    name: str
    # The source's own item number, e.g. "1".."17" for a section 7.9 table
    # row or "8.1".."8.6" for a section 8 residual item. Phase 1 amendment:
    # citations render it ("Item 4 Payroll subsidy"), so it must survive the
    # round-trip rather than being buried inside incentive_id.
    item_no: Optional[str] = None
    incentive_type: IncentiveType
    category_rates: list[CategoryRate] = Field(default_factory=list)
    varies_by_category: bool = False
    district_scope: list[str] = Field(default_factory=list)
    sector_scope: list[str] = Field(default_factory=list)
    eligibility_rule_ids: list[str] = Field(default_factory=list)
    ambiguity_flags: list[str] = Field(default_factory=list)
    status: IncentiveStatus
    source: Provenance
    cross_references: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# EligibilityRule
# ---------------------------------------------------------------------------


class ConditionType(str, Enum):
    HEADCOUNT_THRESHOLD = "headcount_threshold"
    EPF_REGISTRATION = "epf_registration"
    UDYAM_REGISTRATION = "udyam_registration"
    SECTOR_INCLUSION = "sector_inclusion"
    NEGATIVE_LIST_EXCLUSION = "negative_list_exclusion"
    INVESTMENT_CEILING = "investment_ceiling"
    TIME_WINDOW = "time_window"
    OTHER = "other"


class EligibilityRule(BaseModel):
    rule_id: str
    applies_to: list[str] = Field(default_factory=list)
    condition_text: str
    condition_type: ConditionType
    parameters: dict = Field(default_factory=dict)
    clause_ref: Optional[str] = Field(
        None, description="Section number the clause sits under, e.g. '9.1'"
    )
    # Phase 1 amendments: a clause's citation breadcrumb is
    # "S9.1 General Conditions ... > (d)", so the section title and the
    # sub-clause letter must be stored, not re-derived.
    section_title: Optional[str] = None
    letter: Optional[str] = None
    # Ambiguity flags raised against this clause. Every other entity that can
    # carry them already has this field; EligibilityRule did not, so the
    # migration smuggled them through `cross_references` as wikilinks and
    # chunk_from_okf parsed them back out. That only worked because the Bihar
    # migration happened to put nothing else in `cross_references` -- the
    # first hand-authored rule to use that field for its real, general
    # purpose (linking to a scheme and an act) leaked those identifiers into
    # a live answer's ambiguity_ids. Storing them in their own typed field
    # removes the guess.
    ambiguity_flags: list[str] = Field(default_factory=list)
    source: Provenance
    cross_references: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Authority
# ---------------------------------------------------------------------------


class AuthorityType(str, Enum):
    DISTRICT_OFFICE = "district_office"
    STATE_DEPARTMENT = "state_department"
    CENTRAL_PSU = "central_psu"
    NODAL_AGENCY = "nodal_agency"


class AuthorityContact(BaseModel):
    helpline: Optional[str] = None
    email: Optional[str] = None
    portal_url: Optional[str] = None


class Authority(BaseModel):
    authority_id: str
    name: str
    type: AuthorityType
    jurisdiction: list[str] = Field(
        default_factory=list, description="District IDs, or a single 'state_wide'/'national' string"
    )
    contact: AuthorityContact = Field(default_factory=AuthorityContact)
    source: Provenance
    cross_references: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# District / DistrictClassification
# ---------------------------------------------------------------------------


class District(BaseModel):
    district_id: str
    name: str
    state: str = "Bihar"
    source: Provenance


class DistrictClassification(BaseModel):
    classification_id: str
    district_id: str
    scheme_id: str = Field(..., description="Which scheme/source asserts this classification")
    category: str
    basis: str
    # Position within the source's own printed list for this category.
    # Phase 1 amendment: the annexure is rendered back as an ordered list,
    # and re-sorting it alphabetically would silently rewrite the source.
    list_order: Optional[int] = None
    source: Provenance
    cross_references: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Sector
# ---------------------------------------------------------------------------


class SectorClassificationType(str, Enum):
    HIGH_PRIORITY = "high_priority"
    PRIORITY = "priority"
    EMERGING = "emerging"
    NEGATIVE_LIST = "negative_list"
    HERITAGE_CLUSTER = "heritage_cluster"
    ZED_TARGET = "zed_target"
    ODOP = "odop"


class Sector(BaseModel):
    sector_id: str
    name: str
    classification_type: SectorClassificationType
    scheme_id: str
    nic_codes: list[str] = Field(default_factory=list)
    # Phase 1 amendment: sectors are authored one note per sector, but a
    # source publishes them as an ordered annexure list that is rendered
    # back as a single retrievable list. Preserving position keeps the
    # rendered list faithful to the source's ordering.
    list_order: Optional[int] = None
    source: Provenance


# ---------------------------------------------------------------------------
# GlossaryTerm -- deliberately per-scheme, never a flat term->definition dict
# ---------------------------------------------------------------------------


class GlossaryDefinition(BaseModel):
    scheme_id: str = Field(..., description="Which scheme this definition applies under")
    definition_text: str
    source: Provenance


class GlossaryTerm(BaseModel):
    term_id: str
    term: str
    definitions: list[GlossaryDefinition] = Field(default_factory=list)
    cross_scheme_conflict: bool = False
    list_order: Optional[int] = None  # position in the source's own glossary table


# ---------------------------------------------------------------------------
# AmbiguityFlag
# ---------------------------------------------------------------------------


class AmbiguityScope(str, Enum):
    SINGLE_SOURCE = "single_source"
    CROSS_SOURCE = "cross_source"


class AmbiguityIssueType(str, Enum):
    MISSING_RATE = "missing_rate"
    CONTRADICTION = "contradiction"
    UNDEFINED_TERM = "undefined_term"
    EXTERNAL_DEPENDENCY = "external_dependency"
    INOPERATIVE = "inoperative"
    SCOPE_GAP = "scope_gap"
    TYPO = "typo"
    SUBJECTIVE = "subjective"
    STATUS = "status"
    INGESTION = "ingestion"
    CROSS_SOURCE_CONTRADICTION = "cross_source_contradiction"
    STALE_SOURCE = "stale_source"
    CITATION_AMBIGUITY = "citation_ambiguity"


class AmbiguitySeverity(str, Enum):
    BLOCKING = "blocking"
    ADVISORY = "advisory"


class AmbiguityStatus(str, Enum):
    OPEN = "open"
    CLARIFIED = "clarified"
    SUPERSEDED = "superseded"


class AmbiguityFlag(BaseModel):
    id: str = Field(..., description="Namespaced per source, e.g. 'BIHAR_MSME_2026-AMB-03'")
    # Phase 1 amendment: the un-namespaced id as the source document uses it
    # ("AMB-03"). Answers and chunk ids cite this form, and the pre-OKF
    # register keys on it, so it must round-trip rather than be parsed back
    # out of the namespaced id.
    local_id: Optional[str] = None
    scope: AmbiguityScope
    source_ids: list[str] = Field(default_factory=list)
    clause_refs: list[str] = Field(default_factory=list)
    page_refs: list[int] = Field(default_factory=list)
    issue_type: AmbiguityIssueType
    severity: AmbiguitySeverity
    description: str
    public_disclosure_en: str
    public_disclosure_hi: str
    status: AmbiguityStatus
    resolution: Optional[str] = None
    resolved_by: Optional[str] = None
    resolved_at: Optional[datetime] = None
    supersedes_version: Optional[str] = None
    cross_references: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Act / LegalProvision
# ---------------------------------------------------------------------------


class ActJurisdiction(str, Enum):
    CENTRAL = "central"
    STATE = "state"


class ActSection(BaseModel):
    section_no: str
    title: str
    text_summary: str
    source: Provenance


class Act(BaseModel):
    act_id: str
    name: str
    jurisdiction: ActJurisdiction
    sections: list[ActSection] = Field(default_factory=list)
    cross_references: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Entity-type registry -- the compiler (Phase 1) will dispatch on this to
# pick which model validates a given vault note's frontmatter.
# ---------------------------------------------------------------------------

ENTITY_MODELS: dict[str, type[BaseModel]] = {
    "scheme": Scheme,
    "incentive": Incentive,
    "eligibility_rule": EligibilityRule,
    "authority": Authority,
    "district": District,
    "district_classification": DistrictClassification,
    "sector": Sector,
    "glossary_term": GlossaryTerm,
    "ambiguity_flag": AmbiguityFlag,
    "act": Act,
}
