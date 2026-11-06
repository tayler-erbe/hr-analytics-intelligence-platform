"""Fixed protocol for the SWP workbench data layer (swp_workbench_v1).

Every threshold, crosswalk and assumption used by build_workbench.py lives here.
They were fixed before results were inspected. Changing any of them requires a
new labelled protocol version (swp_workbench_v2); do not edit v1 in place.

Everything person-shaped in this module describes the SYNTHETIC workforce from
../workforce_sim. Nothing here describes a real University employee.
"""
from __future__ import annotations

from datetime import date

PROTOCOL_VERSION = "swp_workbench_v1"

# --------------------------------------------------------------------- disclosure
K_MIN_CELL = 10  # a published count of people is 0 or >= K; rates need n >= K

# --------------------------------------------------------------------- snapshot
SNAPSHOT = date(2023, 11, 1)          # same as workforce_sim (IPEDS Fall 2023)
KNOWLEDGE_CUTOFF = date(2023, 11, 15)  # as-known date used by workforce_sim
SYNTHETIC_SEED = 20231101             # workforce_sim.synthesize.DEFAULT_SEED
UNIT_SALT = "swp_workbench_v1/unit"   # salt for the deterministic unit assignment

FAMILIES = ["FAC", "RES", "LIB", "SAA", "MGT", "BFO", "CES", "CSL", "HLT", "SVC", "OAS", "NRC", "PTM"]

# --------------------------------------------------------------------- synthetic units
# workforce_sim has no department dimension ("Not modelled: ... department level").
# The workbench needs one, so each synthetic position line is assigned to one of
# these SYNTHETIC unit archetypes by a salted hash of its position_id and the
# family's affinity weights below. Weights are illustrative ASSUMPTIONS chosen to
# give recognisable unit shapes (an academic college, a facilities MAU, a small
# centre whose cells are mostly suppressed). They are not UIUC unit sizes and the
# archetype labels deliberately avoid real college or MAU names.
UNITS = [
    ("U01", "Unit 01", "Academic college archetype: engineering & physical sciences"),
    ("U02", "Unit 02", "Academic college archetype: liberal arts & sciences"),
    ("U03", "Unit 03", "Academic college archetype: agriculture, environment & extension"),
    ("U04", "Unit 04", "Academic college archetype: business"),
    ("U05", "Unit 05", "Academic college archetype: education & social work"),
    ("U06", "Unit 06", "Academic college archetype: fine & applied arts, media"),
    ("U07", "Unit 07", "Academic college archetype: medicine & health sciences"),
    ("U08", "Unit 08", "Research institute archetype"),
    ("U09", "Unit 09", "MAU archetype: facilities & services"),
    ("U10", "Unit 10", "MAU archetype: technology services"),
    ("U11", "Unit 11", "MAU archetype: business & financial services"),
    ("U12", "Unit 12", "MAU archetype: student affairs & health"),
    ("U13", "Unit 13", "MAU archetype: library"),
    ("U14", "Unit 14", "MAU archetype: human resources (small)"),
    ("U15", "Unit 15", "Small interdisciplinary centre archetype (mostly suppressed)"),
]
#            FAC  RES  LIB  SAA  MGT  BFO  CES  CSL  HLT  SVC  OAS  NRC  PTM
UNIT_FAMILY_WEIGHTS = {
    "U01": [22, 25, 0, 12, 10, 8, 30, 3, 0, 2, 12, 2, 2],
    "U02": [30, 20, 0, 20, 12, 10, 15, 10, 0, 1, 15, 0, 0],
    "U03": [12, 25, 0, 8, 9, 8, 14, 8, 0, 3, 10, 8, 6],
    "U04": [8, 3, 0, 10, 7, 6, 3, 4, 0, 0, 6, 0, 0],
    "U05": [6, 6, 0, 8, 5, 3, 2, 8, 2, 0, 5, 0, 0],
    "U06": [9, 2, 0, 6, 4, 3, 2, 25, 0, 1, 5, 0, 0],
    "U07": [5, 8, 0, 4, 4, 3, 6, 2, 15, 0, 5, 0, 0],
    "U08": [0, 10, 0, 0, 4, 4, 10, 2, 0, 0, 3, 1, 0],
    "U09": [0, 0, 0, 0, 7, 5, 4, 0, 0, 60, 6, 75, 70],
    "U10": [0, 0, 0, 0, 6, 2, 18, 1, 0, 0, 3, 0, 0],
    "U11": [0, 0, 0, 0, 7, 25, 3, 0, 0, 0, 12, 0, 0],
    "U12": [0, 0, 0, 30, 6, 3, 2, 20, 80, 25, 12, 0, 0],
    "U13": [0, 0, 100, 2, 2, 0, 2, 0, 0, 0, 2, 0, 0],
    "U14": [0, 0, 0, 0, 2.5, 4, 0.5, 0.5, 0, 0, 3, 0, 0],
    "U15": [0, 0.6, 0, 0, 0.15, 0, 0.3, 0, 0, 0, 0.15, 0, 0],
}

# --------------------------------------------------------------------- IPEDS family -> O*NET
# Representative occupations for each synthetic (IPEDS) family. ASSUMPTION:
# an occupation represents a family if its SOC code starts with one of these
# prefixes AND it is in the reskilling evidence set, i.e. one of reskilling's 173
# curated O*NET roles, or the rank-1 candidate of a SUCSS class with lexical title
# similarity >= REP_MIN_SUCSS_SIMILARITY (still unreviewed). Occupations are
# weighted equally inside a family because no public source gives UIUC's
# occupation mix inside an IPEDS category. RES and CES both use SOC 19 (IPEDS
# "Research" is a function, not an occupation); this overlap is deliberate.
FAMILY_SOC_PREFIXES = {
    # Faculty: no evidence. The only 25-1 occupations in the reskilling set arrive
    # through civil-service SUCSS titles lexically matched to "postsecondary
    # teacher" occupations (e.g. Social Work Aide -> Social Work Teachers), which
    # says nothing about faculty work. Faculty are out of reskilling's scope.
    "FAC": [],
    "RES": ["19-"],
    "LIB": ["25-4"],
    "SAA": ["25-2", "25-3", "25-9", "21-1012"],
    "MGT": ["11-"],
    "BFO": ["13-"],
    "CES": ["15-", "17-", "19-"],
    "CSL": ["21-", "23-", "27-"],
    "HLT": ["29-"],
    "SVC": ["31-", "33-", "35-", "37-", "39-"],
    "OAS": ["43-"],
    "NRC": ["45-", "47-", "49-"],
    "PTM": ["51-", "53-"],
}
FAMILY_SOC_EXCLUDE = {"CSL": ["21-1012"]}
REP_MIN_SUCSS_SIMILARITY = 0.35
THIN_EVIDENCE_OCCUPATIONS = 3  # fewer representative occupations -> "thin evidence" flag

# --------------------------------------------------------------------- capability
SKILL_DOMAINS = ("essential_skills", "transferable_skills")  # the 35 O*NET skills
SKILL_CORE_IMPORTANCE = 3.5   # skill is "core" to an occupation at IM >= 3.5 (reskilling's durable cut)
# Default target capability profile (editable in the page): the workforce_sim
# reskilling lever at 5%/yr for 2 years, i.e. 10% of FT Office & Administrative
# Support level 1-2 FTE moves into new level-1 lines, half CES and half BFO.
TARGET_RESKILL_SHARE = 0.10
TARGET_RESKILL_SOURCE = ("OAS", "FT", (1, 2))
TARGET_RESKILL_DEST = {"CES": 0.5, "BFO": 0.5}

# --------------------------------------------------------------------- AI lens
AI_HIGH_FAMILY_SHARE = 0.15  # family median importance-weighted high-band task share
# Reskilling's AI-literacy targets mapped to the AI Professional Development
# Series staff tiers. ASSUMPTION for discussion only: the series defines its own
# tiers and this crosswalk has not been reviewed by the series owners.
COMPETENCY_TO_AIPD = {
    "Aware": "AI Explorer",
    "Practitioner": "AI Catalyst",
    "Integrator": "AI Practitioner",
    "Leader": "AI Practitioner + leader track",
}
COMPETENCY_LEVELS = ["Aware", "Practitioner", "Integrator", "Leader"]

# --------------------------------------------------------------------- ERP lens
# ASSUMPTION: a task "touches Banner/HRFE-heavy work" if its O*NET text matches
# one of these HR/payroll/finance transaction patterns (ERP phase 1 is HR and
# finance). This is a keyword proxy on national task text, not a reading of
# Banner security classes or HRFE role assignments.
ERP_HR_FIN_PATTERNS = [
    r"payroll", r"timekeep", r"time ?(card|sheet|record)", r"\bleave\b", r"employee benefit", r"\bbenefits\b",
    r"personnel (record|action|file)", r"employee record", r"\bhiring\b", r"\brecruit", r"onboard",
    r"\bpurchas", r"procure", r"requisition", r"invoice", r"accounts? (payable|receivable)", r"\bbilling\b",
    r"\bbudget", r"\bledger", r"journal entr", r"reconcil", r"financial (record|statement|report|data|transaction)",
    r"expenditure", r"\bexpense", r"reimburs", r"\bgrants?\b", r"encumb", r"position control",
    r"\bsalar(y|ies)\b", r"\bwages?\b", r"compensation", r"\baudit",
]
ERP_STUDENT_PATTERNS = [r"enrol", r"registration", r"student record", r"transcript", r"financial aid", r"admission"]
ERP_TECH_COMMODITIES = ["Enterprise resource planning ERP software", "Human resources software",
                        "Accounting software", "Time accounting software"]
ERP_HEAVY_TASK_SHARE = 0.15   # family mean importance-weighted HR/finance task share
BANNER_ERA_START = date(2004, 1, 1)  # service began before this -> "pre/early-Banner cohort" (brief: Banner HR since 2003)

# --------------------------------------------------------------------- succession / bench
READY_QUARTERS_IN_LEVEL = 8    # same as workforce_sim ready_quarters_in_level
THIN_ROLE_MAX_FILLED = 2       # role (unit x family x level x FT) with <= 2 filled lines is coverage-thin
RETIREMENT_EXPOSURE_FLAG = 0.30  # >= 30% of a role's incumbents eligible now or within 5 years
RETIREMENT_WINDOW_YEARS = 5
SERVICE_BANDS = [(0, 2, "<2 yrs"), (2, 5, "2-5 yrs"), (5, 10, "5-10 yrs"), (10, 20, "10-20 yrs"), (20, 99, "20+ yrs")]
LONG_SERVICE_YEARS = 20

# --------------------------------------------------------------------- SURS
# Source: SURS "Retirement Eligibility" https://surs.org/retirement-eligibility/ ,
# SURS Tier I and Tier II Plan Choice Guides
# (https://surs.org/wp-content/uploads/Plan_Choice_TierI.pdf ,
#  https://surs.org/wp-content/uploads/Plan_Choice_TierII.pdf).
# surs.org is not reachable from this sandbox; the rules below were read from
# search-result text on 2026-11-06 and match faculty_pipeline/calibration.json.
# RE-CHECK AGAINST SURS BEFORE ANY USE.
SURS = {
    "tier1": {
        "applies_to": "first SURS-covered employment before 2011-01-01 (proxy here: synthetic service_start)",
        "unreduced": [(62, 5), (60, 8), (None, 30)],  # (min age, min service); None = any age
        "reduced": [(55, 8)],                          # 0.5% per month under 60
        "note": "Age 55 with 8 years carries a 0.5%/month reduction under age 60; any age with 30 years.",
    },
    "tier2": {
        "applies_to": "first SURS-covered employment on or after 2011-01-01",
        "unreduced": [(67, 10)],
        "reduced": [(62, 10)],                         # 0.5% per month under 67
        "note": "Age 62 with 10 years carries a 0.5%/month reduction under 67. A search excerpt also "
                "mentioned a 30-years-any-age option for Tier II pension plans; it was NOT applied "
                "because it could not be verified on surs.org.",
    },
    "tier_cutover": date(2011, 1, 1),
    "sources": [
        {"cite": "SURS, Retirement Eligibility", "url": "https://surs.org/retirement-eligibility/"},
        {"cite": "SURS, Tier I Plan Choice Guide", "url": "https://surs.org/wp-content/uploads/Plan_Choice_TierI.pdf"},
        {"cite": "SURS, Tier II Plan Choice Guide", "url": "https://surs.org/wp-content/uploads/Plan_Choice_TierII.pdf"},
    ],
    "verification": "surs.org blocked from the build sandbox; rules taken from search-result text "
                    "on 2026-11-06. Re-check before use.",
    "assumptions": [
        "Every synthetic employee is a SURS participant in the Traditional or Portable plan "
        "(Retirement Savings Plan rules, police/fire rules and non-participating appointments are ignored).",
        "SURS service = synthetic University service since service_start; no purchased, reciprocal or "
        "prior-employer service, and part-time service is credited in full.",
        "Tier is inferred from synthetic service_start (before 2011-01-01 -> Tier 1). Real tier comes "
        "from the SURS/benefits feed, because prior SURS service at another employer keeps Tier 1.",
        "Eligibility describes when a pension could start. It says nothing about whether anyone intends "
        "to retire and must never be used as an individual departure prediction.",
    ],
}
RETIREMENT_BANDS = ["unreduced_now", "reduced_now", "within_5y", "not_within_5y"]

PROTOCOL = {
    "version": PROTOCOL_VERSION,
    "k_min_cell": K_MIN_CELL,
    "snapshot": str(SNAPSHOT),
    "knowledge_cutoff": str(KNOWLEDGE_CUTOFF),
    "rep_min_sucss_similarity": REP_MIN_SUCSS_SIMILARITY,
    "skill_core_importance": SKILL_CORE_IMPORTANCE,
    "ai_high_family_share": AI_HIGH_FAMILY_SHARE,
    "erp_heavy_task_share": ERP_HEAVY_TASK_SHARE,
    "ready_quarters_in_level": READY_QUARTERS_IN_LEVEL,
    "thin_role_max_filled": THIN_ROLE_MAX_FILLED,
    "retirement_exposure_flag": RETIREMENT_EXPOSURE_FLAG,
    "retirement_window_years": RETIREMENT_WINDOW_YEARS,
    "long_service_years": LONG_SERVICE_YEARS,
    "banner_era_start": str(BANNER_ERA_START),
    "target_reskill_share": TARGET_RESKILL_SHARE,
}
