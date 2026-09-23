"""Phase 1 migration: policy_data.py -> OKF vault notes.

This is a ONE-WAY, RE-RUNNABLE generator. It reads the hand-encoded
structured facts for the Bihar MSME Policy 2026 and writes them out as
Markdown vault notes under data/okf_vault/.

Why scripted rather than hand-retyped: policy_data.py's figures are already
independently verified against the extracted PDF text by
verify_policy_data.py. Re-typing ~240 facts by hand would throw that
guarantee away and reintroduce exactly the transcription risk that
validator exists to catch. Generating them preserves every string byte for
byte, including the source's own typos ("croe", "7Crore"), which the OKF
rules require be kept verbatim.

Run:  python -m app.okf.migrate_policy_data
"""

from __future__ import annotations

import argparse
import re
import shutil
from typing import Any

from app.ingestion import policy_data as pd
from app.okf import vault

SCHEME_ID = "BIHAR_MSME_2026"
SOURCE_ID = "BIHAR_MSME_POLICY_2026"
SOURCE_URL = "https://state.bihar.gov.in/industries/"
SHORT_NAME = "MSME-2026"
FETCH_DATE = "2026-08-23"     # date the source PDF was extracted (see extract.py)
MIGRATED_ON = "2026-09-23"

# Incentive-name -> OKF incentive_type. Anything unmapped falls back to
# OTHER rather than being guessed, so a wrong type is never silently minted.
INCENTIVE_TYPE_MAP = {
    "Capital Subsidy": "capital_subsidy",
    "Additional Subsidy for disadvantaged group": "capital_subsidy",
    "Additional Subsidy for Scaling up": "capital_subsidy",
    "Payroll subsidy": "payroll_subsidy",
    "Low Tension Power Tariff Subsidy": "power_tariff_subsidy",
    "Roof Top Solar Subsidy": "capital_subsidy",
    "Energy Audit Incentive": "grant_in_aid",
    "Water Audit Incentive": "grant_in_aid",
    "Stamp Duty": "tax_exemption",
    "Quality Certification": "grant_in_aid",
    "Subsidy for Asset creation for Intellectual Property": "grant_in_aid",
    "Trade Mark Registration for GI registration": "grant_in_aid",
    "Incentive for SME exchange": "grant_in_aid",
    "Net SGST Reimbursement": "tax_exemption",
    "E-Commerce Adoption": "grant_in_aid",
    "Export Linked Performance Subsidy": "grant_in_aid",
    "Revival package for units": "other",
    "R&D and Testing Centre Capital Incentives": "capital_subsidy",
    "Special Package for Emerging Industries": "capital_subsidy",
    "Private MSME Park Development Subsidies": "grant_in_aid",
    "Heritage Cluster Infrastructure Grants": "grant_in_aid",
    "Export and Supply Chain Intervention Subsidies": "grant_in_aid",
    "MSME Retail Outlet Development Subsidies": "grant_in_aid",
}

# section 9 clause -> OKF condition_type.
CONDITION_TYPE_MAP = {
    "9.1": "investment_ceiling",
    "9.2": "other",
    "9.3": "other",
    "9.4": "headcount_threshold",
    "9.5": "time_window",
    "9.6": "other",
    "9.7": "time_window",
    "9.8": "other",
    "9.9": "time_window",
    "9.10": "time_window",
}

SECTOR_LISTS = [
    ("HIGH_PRIORITY_SECTORS", "high_priority", 25, "Annexure II"),
    ("PRIORITY_SECTORS", "priority", 25, "Annexure III"),
    ("EMERGING_INDUSTRIES", "emerging", 26, "Annexure IV (Emerging)"),
    ("NEGATIVE_LIST", "negative_list", 26, "Annexure V"),
    ("HERITAGE_CLUSTERS", "heritage_cluster", 26, "Heritage & Traditional Clusters"),
]


def _slug(text: str, maxlen: int = 60) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").upper()
    return s[:maxlen].rstrip("-")


def _provenance(page_start: int, page_end: int, ref: str, extraction: str = "hand_transcribed") -> dict[str, Any]:
    return {
        "source_id": SOURCE_ID,
        "source_url": SOURCE_URL,
        "source_document_version": "draft-v1",
        "fetch_date": FETCH_DATE,
        "fetch_method": "manual",
        "extraction_method": extraction,
        "page_or_section_ref": ref,
        "page_start": page_start,
        "page_end": page_end,
        "verification_status": "verified",
        "verified_by": "verify_policy_data.py (figure tokens checked against extracted text)",
        "verified_at": f"{MIGRATED_ON}T00:00:00",
        "checksum": None,
    }


def _amb_ref(local_id: str) -> str:
    return f"{SCHEME_ID}-{local_id}"


def _rule_id(section: str, letter: str) -> str:
    return f"{SCHEME_ID}-S{section}-{letter or 'root'}"


def _rules_by_section() -> dict[str, list[str]]:
    """section number -> every rule_id authored under it.

    An incentive row cites a governing section ("9.1"), but rules are
    authored one note per lettered sub-clause, so the reference has to fan
    out to the actual note ids or it will not resolve at compile time.
    """
    out: dict[str, list[str]] = {}
    for gc in pd.GUIDING_PRINCIPLES:
        out.setdefault(gc.section, []).append(_rule_id(gc.section, gc.letter))
    return out


# ---------------------------------------------------------------------------
# Builders -- one per source structure in policy_data.py
# ---------------------------------------------------------------------------


def build_scheme() -> list[tuple[str, str, dict, str]]:
    fm = {
        "entity_type": "scheme",
        "scheme_id": SCHEME_ID,
        "name": "Bihar MSME Policy 2026 (Draft)",
        "short_name": SHORT_NAME,
        "issuing_authority_id": None,
        "level": "state",
        "status": "draft_not_notified",
        "effective_from": None,
        "effective_to": None,
        "tier": "P0",
        "legal_basis": [],
        "supersedes": None,
        "summary": (
            "Draft MSME policy of the Government of Bihar setting out financial "
            "incentives, eligibility conditions, sector classifications and district "
            "categorisation for micro, small and medium enterprises. Not yet notified: "
            "validity runs five years from a notification date that does not exist yet."
        ),
        "source": _provenance(1, 27, "whole document"),
        "cross_references": [f"[[{_amb_ref('AMB-17')}]]"],
    }
    body = (
        "## Bihar MSME Policy 2026 (Draft)\n\n"
        "The policy this assistant was originally built for, and still its primary "
        "source. Every incentive, eligibility rule and annexure list compiled from it "
        "carries `source_status: DRAFT_NOT_NOTIFIED`, because the document has not been "
        "formally notified by the Government of Bihar and no incentive in it is in legal "
        f"effect. See [[{_amb_ref('AMB-17')}]].\n"
    )
    return [("scheme", SCHEME_ID, fm, body)]


def build_incentives() -> list[tuple[str, str, dict, str]]:
    out = []
    rules_by_section = _rules_by_section()
    for row in pd.INCENTIVE_TABLE:
        iid = f"{SCHEME_ID}-S7.9-ITEM{row.no}"
        rates = []
        for cat in ("micro", "small", "medium"):
            rates.append({
                "enterprise_category": cat,
                "rate_text": getattr(row, cat),
                "rate_value": None,
                "cap_value": None,
                "cap_unit": None,
            })
        amb = [_amb_ref(a) for a in row.ambiguity_flags]
        fm = {
            "entity_type": "incentive",
            "incentive_id": iid,
            "scheme_id": SCHEME_ID,
            "name": row.name,
            "item_no": str(row.no),
            "incentive_type": INCENTIVE_TYPE_MAP.get(row.name, "other"),
            "category_rates": rates,
            "varies_by_category": row.varies_by_category,
            "district_scope": [],
            "sector_scope": [],
            "eligibility_rule_ids": [
                rid for s in row.conditions_ref for rid in rules_by_section.get(s, [])
            ],
            "ambiguity_flags": amb,
            "status": "rate_unstated" if "AMB-09" in row.ambiguity_flags else "active",
            "source": _provenance(row.page, row.page, f"section 7.9, item {row.no}"),
            "cross_references": [f"[[{a}]]" for a in amb],
        }
        body = (
            f"## {row.name}\n\n"
            f"Item {row.no} of the section 7.9 financial incentive table "
            f"(page {row.page}).\n\n"
            + ("This incentive's terms differ by enterprise category; see the "
               "per-category rates above.\n"
               if row.varies_by_category else
               "The source states identical terms for micro, small and medium "
               "enterprises.\n")
            + (f"\nGoverning conditions: section(s) {', '.join(row.conditions_ref)}.\n"
               if row.conditions_ref else "")
            + (f"\nOpen questions on this incentive: "
               f"{', '.join('[[' + a + ']]' for a in amb)}.\n" if amb else "")
        )
        out.append(("incentive", iid, fm, body))

    for ri in pd.RESIDUAL_INCENTIVES:
        iid = f"{SCHEME_ID}-S{ri.no}"
        amb = [_amb_ref(a) for a in ri.ambiguity_flags]
        fm = {
            "entity_type": "incentive",
            "incentive_id": iid,
            "scheme_id": SCHEME_ID,
            "name": ri.name,
            "item_no": ri.no,
            "incentive_type": INCENTIVE_TYPE_MAP.get(ri.name, "other"),
            # A residual item states one rate with no per-category breakdown,
            # so it maps to a single `other`-category rate rather than being
            # left rate-less with the figure stranded in prose.
            "category_rates": [{
                "enterprise_category": "other",
                "rate_text": ri.detail,
                "rate_value": None,
                "cap_value": None,
                "cap_unit": None,
            }],
            "varies_by_category": False,
            "district_scope": [],
            "sector_scope": [],
            "eligibility_rule_ids": [],
            "ambiguity_flags": amb,
            "status": "active",
            "source": _provenance(ri.page, ri.page, f"section {ri.no}"),
            "cross_references": [f"[[{a}]]" for a in amb],
        }
        body = (
            f"## {ri.name}\n\n"
            f"Section {ri.no} of the residual incentives and support provisions "
            f"(page {ri.page}).\n"
            + (f"\nOpen questions: {', '.join('[[' + a + ']]' for a in amb)}.\n" if amb else "")
        )
        out.append(("incentive", iid, fm, body))
    return out


def build_eligibility_rules() -> list[tuple[str, str, dict, str]]:
    out = []
    for gc in pd.GUIDING_PRINCIPLES:
        rid = _rule_id(gc.section, gc.letter)
        amb = [_amb_ref(a) for a in gc.ambiguity_flags]
        fm = {
            "entity_type": "eligibility_rule",
            "rule_id": rid,
            "applies_to": [SCHEME_ID],
            "condition_text": gc.text,
            "condition_type": CONDITION_TYPE_MAP.get(gc.section, "other"),
            "parameters": {},
            "clause_ref": gc.section,
            "section_title": gc.section_title,
            "letter": gc.letter,
            "source": _provenance(gc.page, gc.page, f"section {gc.section}({gc.letter})"),
            "cross_references": [f"[[{a}]]" for a in amb],
        }
        body = (
            f"## Section {gc.section}({gc.letter}) — {gc.section_title}\n\n"
            f"{gc.text}\n"
            + (f"\nOpen questions: {', '.join('[[' + a + ']]' for a in amb)}.\n" if amb else "")
        )
        out.append(("eligibility_rule", rid, fm, body))
    return out


def build_districts() -> list[tuple[str, str, dict, str]]:
    out = []
    ref = vault.load_reference_set("bihar_districts")
    for name in ref["members"]:
        did = _slug(name)
        fm = {
            "entity_type": "district",
            "district_id": did,
            "name": name,
            "state": "Bihar",
            "source": _provenance(25, 25, "Annexure I / reference set BIHAR_DISTRICTS"),
        }
        body = f"## {name}\n\nDistrict of Bihar.\n"
        out.append(("district", did, fm, body))

    for category, districts in (("A", pd.REGION_A_DISTRICTS), ("B", pd.REGION_B_DISTRICTS)):
        for order, name in enumerate(districts):
            cid = f"{_slug(name)}-BIIPP-REGION-{category}"
            fm = {
                "entity_type": "district_classification",
                "classification_id": cid,
                "district_id": _slug(name),
                "scheme_id": SCHEME_ID,
                "category": category,
                "basis": "Annexure I district categorisation, attributed to BIIPP",
                "list_order": order,
                "source": _provenance(25, 25, "Annexure I"),
                "cross_references": [f"[[{_amb_ref('AMB-01')}]]"],
            }
            body = (
                f"## {name} — Region {category}\n\n"
                f"Annexure I places {name} in Region {category}, which sets the capital "
                f"subsidy rate under section 7.9 item 1 "
                f"({'30%' if category == 'A' else '25%'}).\n\n"
                f"The annexure attributes this categorisation to BIIPP; the naming and "
                f"edition of that policy are unresolved, see [[{_amb_ref('AMB-01')}]].\n"
            )
            out.append(("district_classification", cid, fm, body))
    return out


def build_sectors() -> list[tuple[str, str, dict, str]]:
    out = []
    for const_name, classification, page, ref in SECTOR_LISTS:
        for i, name in enumerate(getattr(pd, const_name)):
            sid = f"{_slug(name)}-{classification.upper()}"
            fm = {
                "entity_type": "sector",
                "sector_id": sid,
                "name": name,
                "classification_type": classification,
                "scheme_id": SCHEME_ID,
                "nic_codes": [],
                "list_order": i,
                "source": _provenance(page, page, ref),
            }
            body = f"## {name}\n\nClassified as `{classification}` by {ref} of the {SHORT_NAME} policy.\n"
            out.append(("sector", sid, fm, body))
    return out


def build_glossary() -> list[tuple[str, str, dict, str]]:
    out = []
    for i, (abbr, expansion) in enumerate(pd.ABBREVIATIONS.items()):
        tid = _slug(abbr)
        fm = {
            "entity_type": "glossary_term",
            "term_id": tid,
            "term": abbr,
            "definitions": [{
                "scheme_id": SCHEME_ID,
                "definition_text": expansion,
                "source": _provenance(4, 4, "List of Abbreviations, p.4"),
            }],
            "cross_scheme_conflict": False,
            "list_order": i,
        }
        body = (
            f"## {abbr}\n\n{expansion}\n\n"
            f"Defined in the {SHORT_NAME} abbreviations table. If another source defines "
            f"this term differently, add a second entry to `definitions` rather than "
            f"editing this one, and set `cross_scheme_conflict: true`.\n"
        )
        out.append(("glossary_term", tid, fm, body))
    return out


def build_ambiguities() -> list[tuple[str, str, dict, str]]:
    out = []
    for e in pd.AMBIGUITY_REGISTER:
        aid = _amb_ref(e.id)
        fm = {
            "entity_type": "ambiguity_flag",
            "id": aid,
            "local_id": e.id,
            "scope": "single_source",
            "source_ids": [SOURCE_ID],
            "clause_refs": list(e.clause_refs),
            "page_refs": list(e.page_refs),
            "issue_type": e.issue_type,
            "severity": e.severity,
            "description": e.description,
            "public_disclosure_en": e.public_disclosure_en,
            "public_disclosure_hi": e.public_disclosure_hi,
            "status": "open",
            "resolution": None,
            "resolved_by": None,
            "resolved_at": None,
            "supersedes_version": None,
            "cross_references": [],
        }
        body = (
            f"## {e.id} — {e.issue_type} ({e.severity})\n\n"
            f"{e.description}\n\n"
            f"**Clauses:** {', '.join(e.clause_refs)}  \n"
            f"**Pages:** {', '.join(str(p) for p in e.page_refs)}\n"
        )
        out.append(("ambiguity_flag", aid, fm, body))
    return out


# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--clean", action="store_true",
        help="delete previously generated notes in the entity folders first",
    )
    args = parser.parse_args()

    records: list[tuple[str, str, dict, str]] = []
    records += build_scheme()
    records += build_incentives()
    records += build_eligibility_rules()
    records += build_districts()
    records += build_sectors()
    records += build_glossary()
    records += build_ambiguities()

    if args.clean:
        for folder in set(vault.ENTITY_FOLDERS.values()):
            target = vault.VAULT_DIR / folder
            if target.exists():
                for md in target.glob("*.md"):
                    md.unlink()

    counts: dict[str, int] = {}
    seen: set[tuple[str, str]] = set()
    for entity_type, entity_id, frontmatter, body in records:
        key = (entity_type, entity_id)
        if key in seen:
            raise AssertionError(f"Duplicate generated note: {entity_type}/{entity_id}")
        seen.add(key)
        folder = vault.ENTITY_FOLDERS[entity_type]
        path = vault.VAULT_DIR / folder / f"{entity_id}.md"
        vault.write_note(path, frontmatter, body)
        counts[entity_type] = counts.get(entity_type, 0) + 1

    total = sum(counts.values())
    print(f"Wrote {total} vault notes -> {vault.VAULT_DIR}")
    for t, n in sorted(counts.items()):
        print(f"  {t:24s} {n}")


if __name__ == "__main__":
    main()
