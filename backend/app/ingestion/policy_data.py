"""
Hand-encoded structured facts for the highest-value, highest-risk objects in
the MSME Policy 2026: the section 7.9 incentive matrix, section 8 residual
incentives, and the Annexures.

WHY HAND-ENCODED RATHER THAN AUTO-EXTRACTED FROM THE TABLE DETECTOR:
PyMuPDF's page.find_tables() was tried first (see the exploration that
preceded this file). On pages 18-20 it truncates cell text and, for row 1
(Capital Subsidy), splits the single logical row's two district-category
values ("...A Category District" / "...B Category District", which the
source renders as two stacked paragraphs inside one cell) into two separate
table rows with a blank S.No. That is exactly the kind of silent corruption
the architecture doc warns about (docs/RAG_IMPLEMENTATION.md section 2.2):
"naive chunking splits it... the single most likely way this product
embarrasses the Department."

Given the corpus is fixed at 27 pages, this data was transcribed by direct,
verified reading of the source PDF (each figure was independently confirmed
against the extracted text during the extraction re-validation pass -- see
verify_extraction.py's REQUIRED_FIGURES list, which is checked against this
exact set of numbers). Every entry below is additionally re-validated by
verify_policy_data.py, which asserts every figure token (percentage, rupee
amount, count) appearing in a rate/cap string here is present in the
whitespace-normalized extracted text for its source page or the page
immediately after it. If the source PDF is ever revised, that validator
will fail loudly rather than silently indexing stale figures.

(Note: earlier revisions of this docstring named a "policy_data_validate.py"
that has never existed in the repo. The validator is verify_policy_data.py.
It checks figure TOKENS, not whole-string containment -- whole-sentence
matching fails on correct data because the source wraps cells across page
boundaries.)

Known typos and inconsistencies are preserved EXACTLY as printed in the
source (e.g. "croe" for "Crore", "7Crore" with no space) -- this module
never corrects the policy's own drafting; it only structures it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# --------------------------------------------------------------------------
# Section 7.9 Financial Incentives -- pp. 18-20
# --------------------------------------------------------------------------


@dataclass
class CategoryRate:
    """One enterprise-category's rate/cap for one incentive row."""

    micro: str
    small: str
    medium: str


@dataclass
class IncentiveRow:
    no: int
    name: str
    page: int
    varies_by_category: bool  # True if micro/small/medium differ (see
                               # docs/RAG_IMPLEMENTATION.md section 2.2 --
                               # only 4 of 17 rows genuinely vary)
    micro: str
    small: str
    medium: str
    conditions_ref: list[str] = field(default_factory=list)  # e.g. ["9.1"]
    ambiguity_flags: list[str] = field(default_factory=list)


INCENTIVE_TABLE: list[IncentiveRow] = [
    IncentiveRow(
        no=1, name="Capital Subsidy", page=18, varies_by_category=True,
        micro=(
            "30% of Fixed Capital Investment (Cap 25 Lakhs) in A Category District "
            "as defined in BIPP Policy; 25% of Fixed Capital Investment (Cap 25 Lakhs) "
            "in B Category District as defined in BIIPP Policy"
        ),
        small=(
            "30% of Fixed Capital Investment (Cap 1.5 Crore) in A Category District "
            "as defined in BIPP Policy; 25% of Fixed Capital Investment (Cap 1.5 Crore) "
            "in B Category District as defined in BIIPP Policy"
        ),
        medium=(
            "30% of Fixed Capital Investment (Cap 5 croe) in A Category District "
            "as defined in BIPP Policy; 25% of Fixed Capital Investment (Cap 5 croe) "
            "in B Category District as defined in BIIPP Policy"
        ),
        conditions_ref=["9.1"],
        ambiguity_flags=["AMB-01", "AMB-02", "AMB-07", "AMB-20"],
    ),
    IncentiveRow(
        no=2, name="Additional Subsidy for disadvantaged group", page=18,
        varies_by_category=False,
        micro="Additional 10% for women/SC/ST/BC/PwD/Transgender with maximum cap of 7 Crore",
        small="Additional 10% for women/SC/ST/BC/PwD/Transgender with maximum cap of 7Crore",
        medium="Additional 10% for women/SC/ST/BC/PwD/Transgender with maximum cap of 7 Crore",
        conditions_ref=["9.1"],
        ambiguity_flags=["AMB-05"],
    ),
    IncentiveRow(
        no=3, name="Additional Subsidy for Scaling up", page=18, varies_by_category=False,
        micro="5% additional capital subsidy (Maximum Cap 25 Lakhs)",
        small="5% additional capital subsidy (Maximum Cap 25 Lakhs)",
        medium="5% additional capital subsidy (Maximum Cap 25 Lakhs)",
        conditions_ref=["9.3"],
        ambiguity_flags=["AMB-08"],
    ),
    IncentiveRow(
        no=4, name="Payroll subsidy", page=18, varies_by_category=True,
        micro=(
            "Reimbursement of employer's contribution to the EPF for the first three years "
            "from the date of commencement of production, if the unit has employed more than "
            "10 persons, subject to a maximum of Rs, 24,000/- per employee per annum"
        ),
        small=(
            "Reimbursement of employer's contribution to the EPF for the first three years "
            "from the date of commencement of production, if the unit has employed more than "
            "20 persons, subject to a maximum of Rs, 24,000/- per employee per annum"
        ),
        medium=(
            "Reimbursement of employer's contribution to the EPF for the first three years "
            "from the date of commencement of production, if the unit has employed more than "
            "50 persons, subject to a maximum of Rs, 24,000/- per employee per annum"
        ),
        conditions_ref=["9.4"],
    ),
    IncentiveRow(
        no=5, name="Low Tension Power Tariff Subsidy", page=18, varies_by_category=False,
        micro=(
            "20% of the power charges paid by the enterprise for the first 3 years from the "
            "date of commencement of production or from the date of power connection, "
            "whichever is later"
        ),
        small=(
            "20% of the power charges paid by the enterprise for the first 3 years from the "
            "date of commencement of production or from the date of power connection, "
            "whichever is later"
        ),
        medium=(
            "20% of the power charges paid by the enterprise for the first 3 years from the "
            "date of commencement of production or from the date of power connection, "
            "whichever is later"
        ),
        conditions_ref=["9.5"],
    ),
    IncentiveRow(
        no=6, name="Roof Top Solar Subsidy", page=18, varies_by_category=False,
        micro="25% of the cost of Roof Top Solar set up to the capacity of 300 Kw, subject to a maximum limit of 5.0 Lakhs",
        small="25% of the cost of Roof Top Solar set up to the capacity of 300 Kw, subject to a maximum limit of 5.0 Lakhs",
        medium="25% of the cost of Roof Top Solar set up to the capacity of 300 Kw, subject to a maximum limit of 5.0 Lakhs",
        conditions_ref=["9.6"],
    ),
    IncentiveRow(
        no=7, name="Energy Audit Incentive", page=19, varies_by_category=False,
        micro="75% of the cost of the audit subject to a maximum of 1 lakhs per energy audit",
        small="75% of the cost of the audit subject to a maximum of 1 lakhs per energy audit",
        medium="75% of the cost of the audit subject to a maximum of 1 lakhs per energy audit",
        conditions_ref=["9.7"],
    ),
    IncentiveRow(
        no=8, name="Water Audit Incentive", page=19, varies_by_category=False,
        micro="75% of the cost of the audit subject to a maximum of 1 lakhs per water audit",
        small="75% of the cost of the audit subject to a maximum of 1 lakhs per water audit",
        medium="75% of the cost of the audit subject to a maximum of 1 lakhs per water audit",
    ),
    IncentiveRow(
        no=9, name="Stamp Duty", page=19, varies_by_category=False,
        micro="100% stamp duty reimbursement on land purchase to new manufacturing enterprises",
        small="100% stamp duty reimbursement on land purchase to new manufacturing enterprises",
        medium="100% stamp duty reimbursement on land purchase to new manufacturing enterprises",
        conditions_ref=["9.9"],
    ),
    IncentiveRow(
        no=10, name="Quality Certification", page=19, varies_by_category=False,
        micro="100% reimbursement of certification and consulting charges subject to maximum of 2 lakhs for National Certification and 10 Lakhs for International Certification",
        small="100% reimbursement of certification and consulting charges subject to maximum of 2 lakhs for National Certification and 10 Lakhs for International Certification",
        medium="100% reimbursement of certification and consulting charges subject to maximum of 2 lakhs for National Certification and 10 Lakhs for International Certification",
        conditions_ref=["9.8"],
    ),
    IncentiveRow(
        no=11, name="Subsidy for Asset creation for Intellectual Property", page=19,
        varies_by_category=False,
        micro="75% subsidy on the cost of filing of the application for patent registration including the cost of first time maintenance fee of the granted application, subject to a maximum of Rs. 3 Lakhs per patent registration",
        small="75% subsidy on the cost of filing of the application for patent registration including the cost of first time maintenance fee of the granted application, subject to a maximum of Rs. 3 Lakhs per patent registration",
        medium="75% subsidy on the cost of filing of the application for patent registration including the cost of first time maintenance fee of the granted application, subject to a maximum of Rs. 3 Lakhs per patent registration",
    ),
    IncentiveRow(
        no=12, name="Trade Mark Registration for GI registration", page=19,
        varies_by_category=False,
        micro="50% subsidy on the cost of filing of the application for Trade Mark registration including the cost of first time maintenance fee of the granted application, subject to a maximum of Rs. 25, 000 per Trade Mark if GI registration",
        small="50% subsidy on the cost of filing of the application for Trade Mark registration including the cost of first time maintenance fee of the granted application, subject to a maximum of Rs. 25, 000 per Trade Mark if GI registration",
        medium="50% subsidy on the cost of filing of the application for Trade Mark registration including the cost of first time maintenance fee of the granted application, subject to a maximum of Rs. 25, 000 per Trade Mark if GI registration",
    ),
    IncentiveRow(
        no=13, name="Incentive for SME exchange", page=20, varies_by_category=True,
        micro="Not applicable (no assistance shown for Micro enterprises in the source table)",
        small="One time assistance of 20% of the expenditure incurred for listing subject to a maximum of 5 Lakhs for successful listing on SME exchange",
        medium="One time assistance of 20% of the expenditure incurred for listing subject to a maximum of 5 Lakhs for successful listing on SME exchange",
        conditions_ref=["9.10"],
        ambiguity_flags=["AMB-13"],
    ),
    IncentiveRow(
        no=14, name="Net SGST Reimbursement", page=20, varies_by_category=False,
        micro="50% for 6 years with annual cap of 5% of Annual turnover",
        small="50% for 6 years with annual cap of 5% of Annual turnover",
        medium="50% for 6 years with annual cap of 5% of Annual turnover",
        ambiguity_flags=["AMB-14"],
    ),
    IncentiveRow(
        no=15, name="E-Commerce Adoption", page=20, varies_by_category=False,
        micro="75% reimbursement of e-commerce platform subscription charges, subject to a maximum assistance of ₹1.00 lakh per unit, one time",
        small="75% reimbursement of e-commerce platform subscription charges, subject to a maximum assistance of ₹1.00 lakh per unit, one time",
        medium="75% reimbursement of e-commerce platform subscription charges, subject to a maximum assistance of ₹1.00 lakh per unit, one time",
    ),
    IncentiveRow(
        no=16, name="Export Linked Performance Subsidy", page=20, varies_by_category=False,
        micro="Export performance incentive at 1% of incremental export growth, subject to a maximum assistance of ₹20.00 lakh per unit per financial year",
        small="Export performance incentive at 1% of incremental export growth, subject to a maximum assistance of ₹20.00 lakh per unit per financial year",
        medium="Export performance incentive at 1% of incremental export growth, subject to a maximum assistance of ₹20.00 lakh per unit per financial year",
    ),
    IncentiveRow(
        no=17, name="Revival package for units", page=20, varies_by_category=True,
        micro="Revival package for units closed for more than one year, with investment up to INR 1 Crore -- NO RATE/AMOUNT SPECIFIED IN SOURCE",
        small="Revival package for units closed for more than one year, with investment up to INR 5 Crore -- NO RATE/AMOUNT SPECIFIED IN SOURCE",
        medium="Revival package for units closed for more than one year, with investment up to INR 12 Crore -- NO RATE/AMOUNT SPECIFIED IN SOURCE",
        ambiguity_flags=["AMB-09"],
    ),
]

# --------------------------------------------------------------------------
# Section 8 Residual Incentives and Support Provisions -- pp. 20-21
# --------------------------------------------------------------------------


@dataclass
class ResidualIncentive:
    no: str
    name: str
    page: int
    detail: str
    ambiguity_flags: list[str] = field(default_factory=list)


RESIDUAL_INCENTIVES: list[ResidualIncentive] = [
    ResidualIncentive(
        no="8.1", name="R&D and Testing Centre Capital Incentives", page=20,
        detail="State Government shall provide capital subsidy equivalent to 5% of eligible Plant & Machinery investment, subject to a maximum of ₹25 lakh.",
    ),
    ResidualIncentive(
        no="8.2", name="Special Package for Emerging Industries", page=20,
        detail="25% Capital Subsidy on eligible Plant & Machinery investment, subject to a maximum of ₹10 Crore.",
        ambiguity_flags=["AMB-04"],
    ),
    ResidualIncentive(
        no="8.3", name="Private MSME Park Development Subsidies", page=20,
        detail="The State will provide ₹2 Crore assistance for Nano Clusters and ₹5 Crore assistance for Mega Clusters.",
    ),
    ResidualIncentive(
        no="8.4", name="Heritage Cluster Infrastructure Grants", page=20,
        detail="90% Grant-in-Aid of project cost up to ₹3 Crore for Mega Clusters and 90% Grant-in-Aid of project cost up to ₹1 Crore for Mini Clusters.",
        ambiguity_flags=["AMB-11"],
    ),
    ResidualIncentive(
        no="8.5", name="Export and Supply Chain Intervention Subsidies", page=21,
        detail="Support to be provided as per approved project proposals and scheme guidelines.",
    ),
    ResidualIncentive(
        no="8.6", name="MSME Retail Outlet Development Subsidies", page=21,
        detail="Rental assistance, setup grants, and space allotment support as per approved norms and scheme guidelines.",
    ),
]

# --------------------------------------------------------------------------
# Section 9 Guiding Principles for availing incentive benefits -- pp. 21-23
# --------------------------------------------------------------------------


@dataclass
class GuidingClause:
    section: str  # e.g. "9.1"
    section_title: str
    letter: str  # e.g. "(a)" or "" for the section itself
    text: str
    page: int
    ambiguity_flags: list[str] = field(default_factory=list)


GUIDING_PRINCIPLES: list[GuidingClause] = [
    GuidingClause("9.1", "General Conditions for Capital Investment Incentives", "a",
                  "The incentive shall be admissible only on investment made in plant and machinery, "
                  "equipment, and related building infrastructure. The cost of land shall not be "
                  "eligible for any incentive under this category.", 21, ["AMB-07"]),
    GuidingClause("9.1", "General Conditions for Capital Investment Incentives", "b",
                  "The eligible incentive shall be disbursed in two equal instalments. The first "
                  "instalment shall be released upon achievement of the prescribed project "
                  "implementation milestones, while the second instalment shall be released after "
                  "the unit achieves at least 50% of its commercial production capacity.", 21),
    GuidingClause("9.1", "General Conditions for Capital Investment Incentives", "c",
                  "The cost of land shall not be considered while calculating benefits under Capital "
                  "Subsidy, Capital Interest Subsidy, or any other investment-linked incentive.", 21),
    GuidingClause("9.1", "General Conditions for Capital Investment Incentives", "d",
                  "The aggregate financial assistance availed by any enterprise under this policy "
                  "shall not exceed 50% of the eligible project cost or ₹10 Crore, whichever is "
                  "lower.", 21, ["AMB-06"]),
    GuidingClause("9.1", "General Conditions for Capital Investment Incentives", "e",
                  "An MSME that has availed assistance under the Capital Subsidy scheme shall not be "
                  "eligible for assistance under the Special Capital Subsidy scheme for the same "
                  "investment.", 21, ["AMB-04"]),
    GuidingClause("9.2", "Interest Subsidy", "a",
                  "Interest Subsidy shall be provided on an annual basis.", 21, ["AMB-03"]),
    GuidingClause("9.2", "Interest Subsidy", "b",
                  "Eligible units shall be entitled to claim the subsidy only after payment of the "
                  "full interest due to the lending institution.", 21, ["AMB-03"]),
    GuidingClause("9.3", "Additional Incentive for Scaling Up", "a",
                  "Incentives sanctioned under the Scaling Up category shall be over and above the "
                  "eligible Capital Subsidy or Special Capital Subsidy available for expansion, "
                  "diversification, or modernization resulting in graduation to a higher enterprise "
                  "category.", 21),
    GuidingClause("9.3", "Additional Incentive for Scaling Up", "b",
                  "Enterprises that have already availed Scaling Up incentives and subsequently move "
                  "to a lower category due to annual updation of Udyam Registration arising from "
                  "reduction in turnover or written down value of plant and machinery shall not be "
                  "eligible to claim Scaling Up incentives again upon re-graduation to a higher "
                  "category.", 22),
    GuidingClause("9.3", "Additional Incentive for Scaling Up", "c",
                  "A Micro or Small Enterprise shall be eligible to avail the Scaling Up incentive "
                  "only once for a particular enterprise category.", 22, ["AMB-08"]),
    GuidingClause("9.4", "Payroll Subsidy", "a",
                  "Eligible MSMEs shall submit claims for Payroll Subsidy within three months from "
                  "the close of the relevant financial year.", 22),
    GuidingClause("9.4", "Payroll Subsidy", "b",
                  "Only regular employees shall be considered for determining eligibility under "
                  "Payroll Subsidy.", 22),
    GuidingClause("9.4", "Payroll Subsidy", "c",
                  "As proof of employment, the enterprise shall furnish copies of valid returns filed "
                  "under the Employees' Provident Funds and Miscellaneous Provisions Act, 1952.", 22),
    GuidingClause("9.4", "Payroll Subsidy", "d",
                  "In case the employee strength falls below the prescribed threshold during any "
                  "month, the subsidy shall be restricted proportionately to the months in which the "
                  "eligibility conditions are fulfilled.", 22),
    GuidingClause("9.5", "Low Tension Power Tariff Subsidy", "a",
                  "Claims under the Low Tension Power Tariff Subsidy shall be submitted online once "
                  "every six months.", 22),
    GuidingClause("9.5", "Low Tension Power Tariff Subsidy", "b",
                  "Enterprises sharing a common electricity connection or occupying a part of another "
                  "enterprise's premises and jointly consuming electricity shall not be eligible for "
                  "this subsidy.", 22),
    GuidingClause("9.6", "Roof Top Solar Subsidy", "a",
                  "Roof Top Solar Subsidy shall be available only for new equipment purchased from "
                  "the original manufacturer or an authorized dealer.", 22),
    GuidingClause("9.7", "Energy Audit Subsidy", "b",
                  "MSMEs undertaking a subsequent Energy Audit after a minimum interval of three "
                  "years shall be eligible for subsidy.", 22, ["AMB-16"]),
    GuidingClause("9.7", "Energy Audit Subsidy", "c",
                  "Eligible units shall submit their claim after completion of one year from the "
                  "date of the Energy Audit.", 23, ["AMB-16"]),
    GuidingClause("9.8", "Quality Certification Reimbursement", "a",
                  "Expenditure incurred for obtaining quality certifications relating to products, "
                  "processes, or social standards shall be eligible for reimbursement, provided such "
                  "certifications are recognized by the Quality Council of India or internationally "
                  "recognized accreditation bodies.", 23),
    GuidingClause("9.8", "Quality Certification Reimbursement", "b",
                  "Expenditure incurred towards renewal of quality certifications shall not be "
                  "eligible for reimbursement.", 23),
    GuidingClause("9.9", "Stamp Duty Reimbursement", "c",
                  "Eligible enterprises shall submit applications for Stamp Duty Reimbursement within "
                  "six months from the date of commencement of commercial production.", 23, ["AMB-16"]),
    GuidingClause("9.10", "Incentive for Listing on SME Exchange", "a",
                  "Eligible MSMEs shall submit applications for reimbursement within six months from "
                  "the date of listing on a recognized SME Exchange.", 23),
    GuidingClause("9.10", "Incentive for Listing on SME Exchange", "b",
                  "Eligible expenditure for reimbursement shall include Merchant Banker Fees, Due "
                  "Diligence Fees, Registrar and Transfer Agent Fees, Peer Review Auditor Fees, "
                  "Exchange Fees, and Listing Charges.", 23),
]

# --------------------------------------------------------------------------
# Annexure I -- District categorization (BIIPP) -- p.25
# --------------------------------------------------------------------------

REGION_A_DISTRICTS = [
    "Aurangabad", "Arwal", "Banka", "Bhagalpur", "Bhojpur", "Darbhanga",
    "East Champaran", "Gopalganj", "Jamui", "Jehanabad", "Kaimur", "Katihar",
    "Khagaria", "Kishanganj", "Lakhisarai", "Madhepura", "Madhubani",
    "Munger", "Nawada", "Nalanda", "Purnea", "Rohtas", "Saharsa",
    "Samastipur", "Saran", "Supaul", "Sitamarhi", "Sheikhpura", "Sheohar",
    "Siwan", "West Champaran",
]  # 31 districts, 30% capital subsidy

REGION_B_DISTRICTS = [
    "Begusarai", "Buxar", "Gaya", "Muzaffarpur", "Patna", "Vaishali",
]  # 6 districts, 25% capital subsidy

# Bihar's 38 official districts, used only to detect AMB-20 (Araria missing
# from Annexure I). Source: Government of Bihar district list. This list is
# NOT part of the policy PDF -- it exists purely to validate the policy's own
# Annexure I against reality, which is exactly how AMB-20 was discovered.
BIHAR_ALL_38_DISTRICTS = [
    "Araria", "Arwal", "Aurangabad", "Banka", "Begusarai", "Bhagalpur",
    "Bhojpur", "Buxar", "Darbhanga", "East Champaran", "Gaya", "Gopalganj",
    "Jamui", "Jehanabad", "Kaimur", "Katihar", "Khagaria", "Kishanganj",
    "Lakhisarai", "Madhepura", "Madhubani", "Munger", "Muzaffarpur",
    "Nalanda", "Nawada", "Patna", "Purnea", "Rohtas", "Saharsa",
    "Samastipur", "Saran", "Sheikhpura", "Sheohar", "Sitamarhi", "Siwan",
    "Supaul", "Vaishali", "West Champaran",
]

# --------------------------------------------------------------------------
# Annexure II & III -- Priority sectors -- p.25-26
# --------------------------------------------------------------------------

HIGH_PRIORITY_SECTORS = [  # Annexure II
    "Food Processing", "Textiles and Leather",
    "Creation for Media and Entertainment Houses", "Logistics",
    "Information Technology Enabled Services (ITeS), Electronics System "
    "Design and Manufacturing (ESDM), and Global Capability Centres (GCC)",
    "Electric Vehicle (EV)", "Pharmaceuticals and Medical Devices",
    "Toys Manufacturing",
    "Renewable and Green Energy (including CBG, Fuel-based Ethanol, and Methanol)",
]

PRIORITY_SECTORS = [  # Annexure III (mislabeled "High Priority Sector" in source -- AMB-15)
    "Automobiles", "Small Machine Manufacturing", "Mechanical Appliances",
    "FMCG Products (Soap, Detergents, Washing Preparations, Organics, etc.)",
    "Plastic and Rubber", "Healthcare", "Wood-Based Industries",
    "General Manufacturing", "Paints and Chemical Products",
    "Health and Wellness Centres", "Waste Recycling", "Fertilizers",
    "Clocks and Watches", "Beverages, Spirits and Vinegars",
    "Ceramic Products", "Arms and Ammunition", "Glass and Glassware",
    "Bullion, Gems and Jewellery Manufacturing", "Sports Goods Manufacturing",
    "Furniture Manufacturing (Plastic, Glass, Leather, Modular, MDF, "
    "Aluminium, Metal, or a combination of these materials)",
]

# --------------------------------------------------------------------------
# Annexure IV -- Emerging industries eligible for Special Package (section 8.2)
# --------------------------------------------------------------------------

EMERGING_INDUSTRIES = [
    "Electronics System Design & Manufacturing (ESDM)",
    "Electric Vehicles (EV) and EV Components",
    "Battery and Energy Storage Systems", "Renewable & Green Energy",
    "Green Hydrogen", "Aerospace & Defence Manufacturing",
    "Medical Devices & Pharmaceuticals",
    "Semiconductor & Electronics Components",
    "Artificial Intelligence (AI), Internet of Things (IoT), Robotics & Automation",
    "Drones and Unmanned Systems", "Biotechnology",
    "Advanced Textiles (Technical Textiles)", "Precision Engineering",
    "Data Centres & Cloud Infrastructure",
    "Circular Economy & Waste Recycling Technologies",
]

# --------------------------------------------------------------------------
# Annexure V -- Negative list (no incentives)
# --------------------------------------------------------------------------

NEGATIVE_LIST = [
    "Units manufacturing narcotic drugs",
    "Units manufacturing alcoholic beverages",
    "Units manufacturing asbestos",
    "Any industry which impacts the environment negatively",
]

# --------------------------------------------------------------------------
# Heritage & Traditional Clusters (source mislabels this "Annexure IV" too,
# duplicating the Emerging Industries annexure number -- AMB-15)
# --------------------------------------------------------------------------

HERITAGE_CLUSTERS = [
    "Bhagalpuri Silk (Tussar & Mulberry)", "Madhubani Painting",
    "Sikki Grass Craft", "Sujani Embroidery", "Tikuli Art", "Manjusha Art",
    "Stone Carving & Stone Craft", "Terracotta & Pottery",
    "Bamboo & Cane Craft", "Banana Fibre Products", "Water Hyacinth Products",
    "Makhana Processing & Value Addition", "Handloom & Cotton Weaving",
    "Jute & Natural Fibre Products", "Wood Craft & Wooden Furniture",
    "Metal Craft (Brass, Iron & Bell Metal)", "Lac & Lac Products",
    "Mithila Textile & Apparel",
    "Other Heritage & Traditional Clusters as notified by the State Government",
]

# --------------------------------------------------------------------------
# Abbreviations (p.4) -- free glossary for query expansion
# --------------------------------------------------------------------------

ABBREVIATIONS = {
    "MSME": "Micro, Small and Medium Enterprises",
    "GSDP": "Gross State Domestic Product",
    "GDP": "Gross Domestic Product",
    "MMUY": "Mukhya Mantri Udyami Yojana",
    "BLUY": "Bihar Laghu Udyami Yojana",
    "PMFME": "Pradhan Mantri Formalisation of Micro Food Processing Enterprises Scheme",
    "PMEGP": "Prime Minister's Employment Generation Programme",
    "ODOP": "One District One Product",
    "RAMP": "Raising and Accelerating MSME Performance",
    "EDP": "Entrepreneurship Development Programme",
    "GSTIN": "Goods and Services Tax Identification Number",
    "PAN": "Permanent Account Number",
    "BIADA": "Bihar Industrial Area Development Authority",
    "EDC": "Entrepreneurship Development Centre",
    "SEBI": "Securities and Exchange Board of India",
    "AIFs": "Alternative Investment Funds",
    "IoT": "Internet of Things",
    "AI": "Artificial Intelligence",
    "ITR": "Income Tax Return",
    "TReDS": "Trade Receivables Discounting System",
    "GoI": "Government of India",
    "MOOCs": "Massive Open Online Courses",
    "IT/ITeS": "Information Technology / Information Technology Enabled Services",
    "MoU": "Memorandum of Understanding",
    "CGTMSE": "Credit Guarantee Fund Trust for Micro and Small Enterprises",
    "B2C": "Business-to-Consumer",
    "B2B": "Business-to-Business",
}

# --------------------------------------------------------------------------
# Ambiguity register seed -- 21 entries. See docs/POLICY_AMBIGUITY_REGISTER.md
# for the full narrative version; this is the machine-readable seed loaded
# into Postgres by db/seed_ambiguities.py.
# --------------------------------------------------------------------------


@dataclass
class AmbiguityEntry:
    id: str
    clause_refs: list[str]
    page_refs: list[int]
    issue_type: str
    severity: str  # "blocking" | "advisory"
    description: str
    public_disclosure_en: str
    public_disclosure_hi: str


AMBIGUITY_REGISTER: list[AmbiguityEntry] = [
    AmbiguityEntry(
        "AMB-01", ["7.9 Item 1", "7.4(ii)", "Annexure I"], [18, 13, 25],
        "external_dependency", "advisory",
        "The incentive table names 'BIPP Policy' while section 7.4(ii) and Annexure I "
        "name 'BIIPP Policy'; Annexure I is dated 2025 while section 7.4(ii) references "
        "BIIPP 2026. It is unclear whether these are the same document.",
        "The draft refers to both 'BIPP' and 'BIIPP' policy, and to both 2025 and 2026 "
        "editions, without clarifying if they are the same document. This has not been "
        "resolved by the Department.",
        "यह प्रारूप 'BIPP' और 'BIIPP' नीति दोनों नामों का उल्लेख करता है, और 2025 व 2026 "
        "दोनों संस्करणों का, बिना यह स्पष्ट किए कि क्या ये एक ही दस्तावेज़ हैं। विभाग द्वारा इसे "
        "अभी स्पष्ट नहीं किया गया है।",
    ),
    AmbiguityEntry(
        "AMB-02", ["7.4(ii)", "Annexure I"], [13, 25],
        "undefined_term", "advisory",
        "Section 7.4(ii) promises an additional 5% Capital Subsidy to 'backward districts "
        "as defined in the BIIPP Policy 2026', but Annexure I defines only Region A / "
        "Region B, never 'backward districts'.",
        "The draft promises an extra 5% subsidy for 'backward districts' but never defines "
        "which districts count as backward -- only Region A and Region B are defined.",
        "प्रारूप 'पिछड़े जिलों' के लिए अतिरिक्त 5% सब्सिडी का वादा करता है, लेकिन यह कभी परिभाषित "
        "नहीं करता कि कौन से जिले 'पिछड़े' माने जाएंगे -- केवल क्षेत्र A और क्षेत्र B परिभाषित हैं।",
    ),
    AmbiguityEntry(
        "AMB-03", ["9.2", "9.1(c)"], [21],
        "missing_rate", "blocking",
        "Interest Subsidy and Capital Interest Subsidy carry claim conditions (annual "
        "basis; claimable only after full interest payment) but no rate, cap, or tenure "
        "is specified anywhere in the document.",
        "The draft describes when Interest Subsidy can be claimed, but never states the "
        "rate, cap, or duration. Departmental clarification is required before any figure "
        "can be given.",
        "प्रारूप बताता है कि ब्याज सब्सिडी (Interest Subsidy) कब दावा की जा सकती है, लेकिन दर, "
        "सीमा या अवधि कहीं नहीं बताई गई है। कोई आंकड़ा देने से पहले विभागीय स्पष्टीकरण आवश्यक है।",
    ),
    AmbiguityEntry(
        "AMB-04", ["9.1(e)", "9.3(a)"], [21],
        "undefined_term", "advisory",
        "'Special Capital Subsidy scheme' is referenced twice but never defined. It may "
        "refer to section 8.2 (Special Package for Emerging Industries) but this is not "
        "stated.",
        "The draft refers to a 'Special Capital Subsidy scheme' that is never defined "
        "elsewhere in the document.",
        "प्रारूप एक 'विशेष पूंजी सब्सिडी योजना' का उल्लेख करता है जो दस्तावेज़ में कहीं और "
        "परिभाषित नहीं है।",
    ),
    AmbiguityEntry(
        "AMB-05", ["7.9 Item 2"], [18],
        "contradiction", "advisory",
        "The disadvantaged-group additional-subsidy cap is Rs.7 Crore even for Micro "
        "enterprises, whose base Capital Subsidy cap is only Rs.25 lakh -- roughly 28x "
        "larger. Likely a drafting error, but not stated as such.",
        "The disadvantaged-group top-up subsidy carries a Rs.7 Crore cap even for Micro "
        "enterprises, though the Micro base subsidy cap is only Rs.25 lakh. This "
        "inconsistency is unresolved in the draft.",
        "वंचित वर्ग के लिए अतिरिक्त सब्सिडी की सीमा सूक्ष्म उद्यमों के लिए भी 7 करोड़ रुपये है, "
        "जबकि सूक्ष्म उद्यमों की मूल सब्सिडी सीमा केवल 25 लाख रुपये है। यह विसंगति प्रारूप में "
        "अनसुलझी है।",
    ),
    AmbiguityEntry(
        "AMB-06", ["9.1(d)", "7.9", "8.2"], [21, 18, 20],
        "contradiction", "advisory",
        "The aggregate cap (50% of project cost or Rs.10 Cr, whichever is lower) is "
        "arithmetically incompatible with summed individual caps -- e.g. Medium capital "
        "subsidy (Rs.5 Cr) plus disadvantaged-group top-up (Rs.7 Cr) already exceeds "
        "Rs.10 Cr, and section 8.2 alone permits up to Rs.10 Cr. Netting order is unstated.",
        "The draft's overall cap on total assistance (Rs.10 Crore) can be lower than the "
        "sum of individual incentive caps that might apply to the same enterprise. The "
        "draft does not explain which caps take precedence.",
        "प्रारूप की समग्र सहायता सीमा (10 करोड़ रुपये) व्यक्तिगत प्रोत्साहन सीमाओं के योग से कम हो "
        "सकती है। प्रारूप यह स्पष्ट नहीं करता कि किस सीमा को प्राथमिकता दी जाएगी।",
    ),
    AmbiguityEntry(
        "AMB-07", ["7.9 Item 1", "9.1(a)", "8.1", "8.2"], [18, 21, 20],
        "undefined_term", "advisory",
        "'Fixed Capital Investment' (the base for Capital Subsidy) is never defined. "
        "Section 9.1(a) separately narrows eligibility to plant, machinery, equipment and "
        "related building infrastructure; sections 8.1/8.2 use the narrower 'eligible "
        "Plant & Machinery'. Three different bases appear across the document.",
        "The draft uses at least three different phrases for the investment base that "
        "incentives are calculated on ('Fixed Capital Investment', 'plant and machinery, "
        "equipment and related building infrastructure', 'eligible Plant & Machinery') "
        "without clarifying whether they mean the same thing.",
        "प्रारूप प्रोत्साहन गणना के आधार के लिए कम से कम तीन भिन्न वाक्यांशों का उपयोग करता है, "
        "बिना यह स्पष्ट किए कि क्या इनका अर्थ एक ही है।",
    ),
    AmbiguityEntry(
        "AMB-08", ["9.3(c)"], [22],
        "scope_gap", "advisory",
        "Scaling-Up eligibility ('once per enterprise category') is stated only for Micro "
        "and Small enterprises. Medium enterprises appear in the section 7.9 Scaling-Up "
        "row but are not addressed by this condition.",
        "The draft's rule limiting Scaling-Up incentives to once per category is stated "
        "only for Micro and Small enterprises; Medium enterprises are not addressed.",
        "स्केलिंग-अप प्रोत्साहन को प्रति श्रेणी एक बार तक सीमित करने वाला नियम केवल सूक्ष्म और लघु "
        "उद्यमों के लिए बताया गया है; मध्यम उद्यमों को संबोधित नहीं किया गया है।",
    ),
    AmbiguityEntry(
        "AMB-09", ["7.9 Item 17"], [20],
        "missing_rate", "blocking",
        "The Revival Package states eligibility (unit closed for more than one year; "
        "investment ceilings of Rs.1/5/12 Crore by category) but no rate or amount of "
        "assistance is specified anywhere.",
        "The draft states who qualifies for the Revival Package but never states how much "
        "assistance is given. Departmental clarification is required before any figure "
        "can be given.",
        "प्रारूप यह बताता है कि पुनरुद्धार पैकेज (Revival Package) के लिए कौन पात्र है, लेकिन "
        "यह कभी नहीं बताता कि कितनी सहायता दी जाएगी। कोई आंकड़ा देने से पहले विभागीय "
        "स्पष्टीकरण आवश्यक है।",
    ),
    AmbiguityEntry(
        "AMB-10", ["Annexure II", "Annexure III"], [25, 25],
        "inoperative", "advisory",
        "High Priority Sector (9 entries) and Priority Sector (20 entries) are enumerated "
        "in the Annexures, but no incentive elsewhere in the policy differentiates its "
        "rate or eligibility by these sector lists.",
        "The draft lists 'High Priority' and 'Priority' sectors but no incentive amount "
        "anywhere in the document actually depends on this classification.",
        "प्रारूप 'उच्च प्राथमिकता' और 'प्राथमिकता' क्षेत्रों की सूची देता है, लेकिन दस्तावेज़ में "
        "कहीं भी कोई प्रोत्साहन राशि इस वर्गीकरण पर निर्भर नहीं है।",
    ),
    AmbiguityEntry(
        "AMB-11", ["Heritage Cluster Annexure", "8.4"], [27, 20],
        "inoperative", "advisory",
        "The heritage-cluster annexure is titled 'eligible for special incentive under the "
        "Policy', but section 8.4 grants go to clusters (infrastructure), not to "
        "individual units within a heritage cluster. No unit-level special incentive is "
        "quantified.",
        "The heritage-cluster list is titled as being eligible for a 'special incentive', "
        "but the only related grant in the draft (section 8.4) goes to cluster "
        "infrastructure, not to individual heritage-craft businesses.",
        "विरासत समूह सूची को 'विशेष प्रोत्साहन' के लिए पात्र बताया गया है, लेकिन प्रारूप में "
        "संबंधित अनुदान (धारा 8.4) समूह अवसंरचना के लिए है, न कि व्यक्तिगत विरासत-शिल्प "
        "व्यवसायों के लिए।",
    ),
    AmbiguityEntry(
        "AMB-12", ["Annexure V(iv)"], [26],
        "subjective", "advisory",
        "The negative list excludes 'any industry which impacts the environment "
        "negatively' with no defined criteria and no named determining authority.",
        "The draft excludes 'any industry which impacts the environment negatively' from "
        "all incentives, without stating who decides this or by what criteria.",
        "प्रारूप 'पर्यावरण पर नकारात्मक प्रभाव डालने वाले किसी भी उद्योग' को सभी प्रोत्साहनों से "
        "बाहर रखता है, बिना यह बताए कि इसका निर्णय कौन करेगा या किन मानदंडों से।",
    ),
    AmbiguityEntry(
        "AMB-13", ["7.9 Item 13"], [20],
        "scope_gap", "advisory",
        "The SME Exchange row shows '-' for Micro enterprises. It is not stated whether "
        "this means Micro enterprises are ineligible, or simply not applicable (e.g. "
        "because SME Exchange listing itself may not apply to Micro enterprises).",
        "The draft shows no entry for Micro enterprises under the SME Exchange incentive, "
        "without clarifying whether this means Micro enterprises are excluded or simply "
        "not applicable.",
        "एसएमई एक्सचेंज प्रोत्साहन के अंतर्गत सूक्ष्म उद्यमों के लिए कोई प्रविष्टि नहीं दिखाई गई है, "
        "बिना यह स्पष्ट किए कि क्या इसका अर्थ है कि सूक्ष्म उद्यम बाहर रखे गए हैं या यह केवल "
        "लागू नहीं होता।",
    ),
    AmbiguityEntry(
        "AMB-14", ["7.9 Item 14"], [20],
        "undefined_term", "advisory",
        "'Net SGST' is undefined, and the 5%-of-annual-turnover cap does not specify which "
        "turnover year (the claim year or a base year).",
        "The draft's SGST reimbursement uses the term 'Net SGST' without defining it, and "
        "does not clarify which year's turnover the 5% cap is calculated against.",
        "प्रारूप की SGST प्रतिपूर्ति 'नेट SGST' शब्द का उपयोग करती है, बिना इसे परिभाषित किए, "
        "और यह स्पष्ट नहीं करती कि 5% सीमा किस वर्ष के टर्नओवर पर गणना की जाएगी।",
    ),
    AmbiguityEntry(
        "AMB-15", ["Annexure III", "Annexure IV (Emerging)", "Annexure IV (Heritage)"],
        [25, 26, 27],
        "typo", "advisory",
        "Annexure III is titled 'High Priority Sector', duplicating Annexure II's title "
        "(it should read 'Priority Sector'). 'Annexure IV' is used twice, once for "
        "Emerging Industries and once for Heritage Clusters. Heritage cluster numbering "
        "also skips several numbers.",
        "The draft has duplicate annexure numbers and titles (e.g. 'Annexure IV' is used "
        "for two different lists). This is a drafting inconsistency, not a policy gap, "
        "but is disclosed for transparency.",
        "प्रारूप में डुप्लिकेट अनुबंध संख्या और शीर्षक हैं (जैसे 'अनुबंध IV' दो अलग-अलग सूचियों के "
        "लिए उपयोग किया गया है)। यह एक प्रारूपण असंगति है, नीतिगत कमी नहीं, लेकिन पारदर्शिता के "
        "लिए इसका खुलासा किया जा रहा है।",
    ),
    AmbiguityEntry(
        "AMB-16", ["9.7", "9.9"], [22, 23],
        "typo", "advisory",
        "Sub-clause lettering in sections 9.7 and 9.9 begins at '(b)'/'(c)' with no '(a)' "
        "present -- a clause appears to have been dropped during drafting.",
        "Two sections of the draft (Energy Audit Subsidy, Stamp Duty Reimbursement) have "
        "sub-clause lettering that skips the first letter, suggesting a clause may be "
        "missing from the published draft.",
        "प्रारूप के दो खंडों (ऊर्जा ऑडिट सब्सिडी, स्टाम्प शुल्क प्रतिपूर्ति) में उप-खंड लेबलिंग पहले "
        "अक्षर को छोड़ देती है, जो सुझाव देता है कि प्रकाशित प्रारूप से कोई खंड छूट गया हो सकता है।",
    ),
    AmbiguityEntry(
        "AMB-17", ["4(i)"], [8],
        "status", "advisory",
        "Policy validity runs '5 years from the date of notification', but this document "
        "is a draft and no notification date exists yet.",
        "This entire policy is a DRAFT. It has not yet been formally notified by the "
        "Government of Bihar, and no incentive described here is currently in legal "
        "effect.",
        "यह संपूर्ण नीति एक प्रारूप (DRAFT) है। इसे अभी तक बिहार सरकार द्वारा औपचारिक रूप से "
        "अधिसूचित नहीं किया गया है, और यहां वर्णित कोई भी प्रोत्साहन वर्तमान में कानूनी रूप से लागू "
        "नहीं है।",
    ),
    AmbiguityEntry(
        "AMB-18", ["5.2"], [8],
        "ingestion", "advisory",
        "Section 5.2 'Guiding principles of the policy' is an empty heading in the source "
        "PDF -- verified by rendering the page: zero drawings, zero images, and no text "
        "after the heading. This is a content gap in the draft itself, not an extraction "
        "failure.",
        "Section 5.2 ('Guiding principles of the policy') has a heading in the draft but "
        "no content beneath it. This is how the source document was published.",
        "धारा 5.2 ('नीति के मार्गदर्शक सिद्धांत') का प्रारूप में केवल शीर्षक है, इसके नीचे कोई सामग्री "
        "नहीं है। स्रोत दस्तावेज़ इसी प्रकार प्रकाशित किया गया था।",
    ),
    AmbiguityEntry(
        "AMB-19", ["7.1"], [10],
        "ingestion", "advisory",
        "Page 10's text layer originally rendered section 7.1 (I)-(V) across two "
        "overlapping columns whose boundary split words mid-token. Repaired "
        "deterministically (see extract.py); the page also carries a rasterised diagram "
        "of 8 pillar boxes whose labels are not in the text layer and are not part of the "
        "retrievable corpus (see AMB-21).",
        "This section's text required a technical repair during ingestion; the repaired "
        "text has been verified against the source PDF.",
        "इस खंड के पाठ को अंतर्ग्रहण (ingestion) के दौरान तकनीकी मरम्मत की आवश्यकता थी; मरम्मत किए "
        "गए पाठ को स्रोत PDF के विरुद्ध सत्यापित किया गया है।",
    ),
    AmbiguityEntry(
        "AMB-20", ["Annexure I"], [25],
        "missing_rate", "blocking",
        "Annexure I categorises only 37 of Bihar's 38 districts into Region A/B. Araria "
        "district is absent from both lists (verified by diffing Annexure I against the "
        "official 38-district list). An enterprise in Araria therefore has no defined "
        "capital-subsidy region and no determinable rate.",
        "Araria district does not appear in the draft's district categorisation table "
        "(Annexure I). This means the capital subsidy rate for an enterprise in Araria "
        "cannot currently be determined from this document. Departmental clarification "
        "is required.",
        "अराय़िया (Araria) जिला प्रारूप की जिला वर्गीकरण तालिका (अनुबंध I) में शामिल नहीं है। "
        "इसका अर्थ है कि अराय़िया में किसी उद्यम के लिए पूंजी सब्सिडी दर वर्तमान में इस दस्तावेज़ से "
        "निर्धारित नहीं की जा सकती। विभागीय स्पष्टीकरण आवश्यक है।",
    ),
    AmbiguityEntry(
        "AMB-21", ["p.10 diagram"], [10],
        "inoperative", "advisory",
        "The page 10 diagram shows 8 policy pillars; 7 map to sections 7.1-7.7. The "
        "eighth, 'Special Assistance for Inclusion', has no corresponding numbered "
        "section anywhere in the policy text.",
        "A diagram in the draft names an eighth policy pillar, 'Special Assistance for "
        "Inclusion', that has no corresponding section anywhere in the written policy "
        "text.",
        "प्रारूप के एक चित्र में आठवें नीति स्तंभ के रूप में 'समावेशन हेतु विशेष सहायता' का नाम दिया "
        "गया है, जिसके लिए नीति पाठ में कहीं कोई संबंधित खंड नहीं है।",
    ),
]

BLOCKING_AMBIGUITY_IDS = {e.id for e in AMBIGUITY_REGISTER if e.severity == "blocking"}
