"""Shared paths, parameters, assumptions and governance switches for the succession pipeline.

Everything that differs between the SYNTHETIC run in this repository and a run on real EDW history
on an approved AITS machine lives here or in `source_map.yaml`-style SOURCE_MAP below. Model code
does not change between the two.
"""
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
PE_ROOT = HERE.parent                                     # platform-evaluation/
ERP_DIR = PE_ROOT / "erp_readiness"                       # reused (import only, never modified)
DATA_DIR = HERE / "data" / "synthetic"                    # git-ignored, regenerable
RUNS_DIR = HERE / "runs"                                  # git-ignored, regenerable
MODEL_CARD_DIR = HERE / "model_cards"
HTML_OUT = PE_ROOT / "output" / "succession_models" / "succession_planning.html"

SEED = 20261106
OPEN_END = dt.date(9999, 12, 31)          # open *_EXP_DT / ROW_REC_END_DT convention (assumed for EDW)
HISTORY_START = dt.date(2004, 1, 1)       # synthetic history start
EXTRACT_DATE = dt.date(2026, 10, 31)      # synthetic extract date ("today" for the final scoring run)

PERIOD_MONTHS = 6                          # discrete-time hazard interval
HORIZONS = (6, 12, 24)                     # months
K_MIN = 10                                 # minimum cell size for anything that leaves the machine
MOBILITY_WINDOW_YEARS = 10                 # trailing window used to estimate the transition matrix
DIRICHLET_ALPHA_TOTAL = 1.0                # total prior pseudo-count per origin row (spread uniformly)
BENCH_DRAWS = 4000                         # Monte Carlo draws for bench coverage uncertainty

# Out-of-time backtest origins: train on everything KNOWN and OBSERVED before the origin (Jan 1 of Y+1),
# evaluate on Y+1..Y+2. All origins + 24 months fall inside the synthetic history.
BACKTEST_ORIGINS = [dt.date(y + 1, 1, 1) for y in (2019, 2020, 2021, 2022, 2023)]   # train <= Y, test Y+1..Y+2
TRAIN_HISTORY_YEARS = 12                   # person-periods older than this before the origin are not used

# ----------------------------------------------------------------------------------------------
# SURS retirement eligibility -- ASSUMPTION, to be confirmed with SURS / University benefits staff.
# Simplified from SURS member guidance as commonly summarised (not a legal reading):
#   Tier 1 (SURS participation began before 2011-01-01):
#       unreduced: age >= 60 with >= 8 years service, or any age with >= 35 years
#       reduced:   age >= 55 with >= 8 years service
#   Tier 2 (participation began on/after 2011-01-01):
#       unreduced: age >= 67 with >= 10 years; reduced: age >= 62 with >= 10 years
# Service is approximated by years since FIRST_HIRE_DT (no reciprocal/prior SURS service, no leave
# adjustments). On real data prefer a SURS tier / service-credit feed if one is approved.
# ----------------------------------------------------------------------------------------------
SURS_TIER2_START = dt.date(2011, 1, 1)
SURS_RULES = {
    1: {"unreduced": [(60, 8), (0, 35)], "reduced": [(55, 8)]},
    2: {"unreduced": [(67, 10)], "reduced": [(62, 10)]},
}
SURS_ASSUMPTION_LABEL = ("ASSUMPTION: simplified SURS Tier 1/Tier 2 age+service rules, service = years since "
                         "first hire; verify with SURS before any use")

# ----------------------------------------------------------------------------------------------
# Logical -> physical bindings. On an approved machine edit ONLY the right-hand sides (and
# `bitemporal`) after reading the EDW data dictionary. Column names are ASSUMPTIONS shared with
# erp_readiness/rules/source_map.yaml plus the two row-version (transaction-time) columns.
# ----------------------------------------------------------------------------------------------
SOURCE_MAP = {
    # "bitemporal": rows carry ROW_REC_START_DT/ROW_REC_END_DT (when the row version was known).
    # "effective_only": no transaction time in the extract; the snapshot builder clips *_EXP_DT and
    #                   TERM_DT at the snapshot and cannot see retro-keyed corrections (documented
    #                   residual leakage risk; see data_contract.md section 4).
    "bitemporal": True,
    "tables": {
        "person": {"file": "T_PERS_HIST", "cols": {
            "pers_id": "EDW_PERS_ID", "eff_dt": "PERS_EFF_DT", "exp_dt": "PERS_EXP_DT", "birth_dt": "BIRTH_DT"}},
        # Protected attributes are extracted into a SEPARATE restricted file and read only by the
        # fairness audit (never joined into model features).
        "protected": {"file": "X_PROTECTED_ATTR", "optional": True, "cols": {
            "pers_id": "EDW_PERS_ID", "sex_cd": "SEX_CD", "race_eth_cd": "RACE_ETH_CD"}},
        "employee": {"file": "T_EMPEE_HIST", "cols": {
            "pers_id": "EDW_PERS_ID", "eff_dt": "EMPEE_EFF_DT", "exp_dt": "EMPEE_EXP_DT",
            "status_cd": "EMPEE_STATUS_CD", "first_hire_dt": "FIRST_HIRE_DT", "cur_hire_dt": "CUR_HIRE_DT"}},
        "term": {"file": "T_EMPEE_HIST_5", "cols": {
            "pers_id": "EDW_PERS_ID", "term_dt": "TERM_DT", "term_reason_cd": "TERM_REASON_CD",
            "surs_retir_ind": "SURS_RETIR_IND"}},
        "job": {"file": "T_JOB_DETL_HIST", "cols": {
            "pers_id": "EDW_PERS_ID", "posn_nbr": "POSN_NBR", "suffix": "JOB_SUFFIX", "eff_dt": "JOB_DETL_EFF_DT",
            "exp_dt": "JOB_DETL_EXP_DT", "contract_type": "JOB_CONTRACT_TYPE_CD", "status_cd": "JOB_STATUS_CD",
            "fte": "JOB_FTE", "annual_sal": "JOB_ANNUAL_SAL_AMT", "class_cd": "JOB_CLS_CD", "org_cd": "JOB_ORG_CD"}},
        "position": {"file": "T_POSN_HIST", "cols": {
            "posn_nbr": "POSN_NBR", "eff_dt": "POSN_EFF_DT", "exp_dt": "POSN_EXP_DT", "status_cd": "POSN_STATUS_CD",
            "class_cd": "POSN_CLS_CD", "org_cd": "POSN_ORG_CD"}},
        "ref_class": {"file": "REF_JOB_CLASS", "cols": {
            "class_cd": "CLS_CD", "min_amt": "MIN_ANNUAL_AMT", "max_amt": "MAX_ANNUAL_AMT", "class_title": "CLS_TITLE"}},
        "ref_org": {"file": "REF_ORG", "cols": {"org_cd": "ORG_CD", "parent_org_cd": "PARENT_ORG_CD", "org_title": "ORG_TITLE"}},
        # HR-owned job architecture: class -> role family, level, critical flag. On real data this is the
        # steward-approved critical-role list; it is NOT derivable from the EDW alone.
        "ref_role": {"file": "REF_ROLE_FAMILY", "cols": {
            "class_cd": "CLS_CD", "role_family": "ROLE_FAMILY", "role_level": "ROLE_LEVEL", "critical_ind": "CRITICAL_IND"}},
    },
    "rec_cols": {"rec_start": "ROW_REC_START_DT", "rec_end": "ROW_REC_END_DT"},
    "unit_level": 2,          # org tree depth used as "unit" for reporting (0 = system, 1 = campus, 2 = college)
}

# Columns that are never model features. Protected attributes are read ONLY by the fairness audit.
PROTECTED_COLS = ("sex_cd", "race_eth_cd")
EXCLUDED_PROXIES = ("zip", "postal", "commute", "name", "graduation", "leave", "birth_place", "citizenship")
# Identifier-like columns that may never appear in anything written to the export/ folder.
FORBIDDEN_EXPORT_COLS = ("pers_id", "edw_pers_id", "posn_nbr", "birth_dt", "sex_cd", "race_eth_cd",
                         "natl_id_hash", "first_name", "last_name", "person", "candidate")

# ----------------------------------------------------------------------------------------------
# Governance gate for PERSON-LEVEL scoring (candidate readiness). Disabled by default.
# Enabled only when BOTH (a) env SUCC_ENABLE_PERSON_LEVEL=1 and (b) either the input data is the
# synthetic fixture (manifest says synthetic) or governance/approval.json carries the three sign-offs.
# ----------------------------------------------------------------------------------------------
PERSON_LEVEL_ENV = "SUCC_ENABLE_PERSON_LEVEL"
APPROVAL_FILE = HERE / "governance" / "approval.json"
REQUIRED_SIGNOFFS = ("university_counsel", "office_for_access_and_equity", "illinois_human_resources")


class PersonLevelDisabled(RuntimeError):
    """Raised when person-level scoring is requested without the governance gate being open."""


def data_is_synthetic(data_dir: Path) -> bool:
    m = Path(data_dir) / "manifest.json"
    if not m.exists():
        return False
    try:
        return json.loads(m.read_text()).get("synthetic") is True
    except json.JSONDecodeError:
        return False


def approval_ok(path: Path = APPROVAL_FILE) -> tuple[bool, str]:
    if not path.exists():
        return False, f"no approval record at {path}"
    try:
        rec = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        return False, f"approval record unreadable: {e}"
    missing = [k for k in REQUIRED_SIGNOFFS if not (rec.get(k) or {}).get("name") or not (rec.get(k) or {}).get("date")]
    if missing:
        return False, f"missing sign-offs: {', '.join(missing)}"
    return True, "approved"


def person_level_gate(data_dir: Path) -> tuple[bool, str]:
    if os.environ.get(PERSON_LEVEL_ENV) != "1":
        return False, f"person-level scoring is disabled (set {PERSON_LEVEL_ENV}=1 after governance approval)"
    if data_is_synthetic(data_dir):
        return True, "enabled on SYNTHETIC data for audit demonstration only"
    ok, why = approval_ok()
    return ok, why if not ok else "enabled under recorded governance approval"


def add_months(d: dt.date, n: int) -> dt.date:
    y, m = divmod(d.month - 1 + n, 12)
    y += d.year
    m += 1
    import calendar
    return dt.date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=2, sort_keys=True, default=str)
        fh.write("\n")
