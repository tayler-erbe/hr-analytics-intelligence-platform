"""Model A constants, bound to protocol/MODEL_PROTOCOL_v1.md (wap-protocol-v1).

Nothing here may be loosened to improve a result (AGENTS.md rule 4). Thresholds live in
protocol/scorers.THRESHOLDS_A and are not repeated; learners' fixed hyper-parameters, the origin set, the
horizon set, the seed and the logical -> physical feature binding (protocol section 0.1) live here.

Environment overrides (all optional):
  WAP_A_OUTPUT_DIR            output folder (default wap_prototype/model_a/outputs)
  WAP_A_INPUT_DIR             Phase 1 restricted folder (default wap_prototype/outputs/restricted)
  WAP_A_UNIT_LEVEL            campus (default) | college | dept  - the reporting unit for ROLE x UNIT
  WAP_ENABLE_PERSON_LEVEL     "1" opens the person-level gate together with synthetic data or approval.json
"""
from __future__ import annotations

import datetime as dt
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
WAP_DIR = HERE.parent                                  # wap_prototype/
PE_ROOT = WAP_DIR.parent                               # platform-evaluation/
SUCCESSION_DIR = PE_ROOT / "succession_models"
PROTOCOL_DIR = WAP_DIR / "protocol"
STAR_SCHEMA = WAP_DIR / "delivery" / "star_schema.yaml"

PROTOCOL_VERSION = "wap-protocol-v1"
MODEL_ID = "A"
SEED = 20261107                                        # protocol 5.2
K_MIN = 10                                             # protocol 6.1; scorers.K_MIN agrees
HORIZONS = (12, 18)                                    # months
TRAIN_HORIZON_MONTHS = 18                              # train on snapshots whose 18-month horizon ends <= origin
TEST_WINDOW_YEARS = 2                                  # evaluate on Y+1 .. Y+2
RECAL_OFFSET_YEARS = 2                                 # Platt recalibration fitted on the origin two years earlier
ORIGINS = tuple(dt.date(y, 12, 31) for y in (2019, 2020, 2021, 2022, 2023))   # protocol 2.5
STEP_BACKOFF_MIN_N = 30                                # A-base-step backs off to A-base-family below this
LABEL_AUDIT_N = 200                                    # protocol 2.7
LABEL_AUDIT_MIN_AGREEMENT = 0.85
TOP_SHARE_SELECTION = 0.10                             # fairness selection rule: top 10% within ladder step
CAL_BY_GROUP_MIN_N = 50
COVERAGE_MC_DRAWS = 4000                               # pipeline-coverage ratio interval (seeded Monte Carlo)

# Learner run ids and fixed hyper-parameters (protocol 2.4). Changing any value is a protocol version bump.
LEARNERS = {
    "A-base-family": {"kind": "base_family"},
    "A-base-step": {"kind": "base_step", "backoff_min_n": STEP_BACKOFF_MIN_N},
    "A-logit": {"kind": "logit", "C_grid": (0.01, 0.1, 1.0, 10.0), "cv_folds": 5, "penalty": "l2"},
    "A-rf": {"kind": "rf", "n_estimators": 500, "min_samples_leaf": 50, "max_features": "sqrt", "class_weight": "balanced"},
    "A-gbm": {"kind": "gbm", "n_estimators": 300, "learning_rate": 0.05, "num_leaves": 15, "min_child_samples": 100,
              "deterministic": True, "num_threads": 1},
}
ML_LEARNERS = ("A-logit", "A-rf", "A-gbm")
BASELINES = ("A-base-family", "A-base-step")
SIMPLICITY_ORDER = ("A-logit", "A-rf", "A-gbm")        # tie-break order (protocol 2.4)
TIE_MARGIN = 0.005                                     # < 0.5 percentage point of Brier skill is a tie
# Named runs beyond the main learners. The age ablation is "the primary learner refitted with age_band" (2.3);
# because the primary is only known after evaluation, the ablation is fitted for every ML learner and the
# evaluation reports the one that matches the primary (and the A-gbm one named in the 2.4 table).
ABLATION_SUFFIX = ":age"
SENSITIVITIES = {"S1": "label=transition_12m", "S2": "drop external covariates", "S3": "drop tenure_years and time_in_class_years"}

# Logical name (protocol) -> physical column (Phase 1 person_period_features). Section 0.1 of the protocol.
FEATURE_MAP = {
    "tenure_years": "tenure_first_hire_years",
    "time_in_class_years": "time_in_class_years",
    "time_in_position_years": "time_in_position_years",
    "fte": "fte_primary",
    "pay_position_in_range": "pay_range_position",
    "moves_per_year": "moves_per_year",
    "time_since_last_move": "time_since_last_move_years",
    "unit_churn_12m": "dept_churn_12m",
    "e_class": "e_class",
    "p_class": "p_class_code",
    "role_family": "role_family",
    "ladder": "ladder_code",
    "level": "ladder_level",
    "campus": "campus_org_code",
    "onet_job_zone": "onet_job_zone",
    "bls_projected_growth_pct": "proj_growth_pct_2025_35",
    "bls_separation_rate": "proj_occ_separations_rate_pct",
    "oews_pay_ratio_local": "pay_ratio_oews_local",
    "aei_exposure": "aei_observed_exposure",
    "job_evolution_watch": "je_watch_score",
}
NUMERIC_FEATURES = ("tenure_years", "time_in_class_years", "time_in_position_years", "fte", "pay_position_in_range",
                    "moves_per_year", "time_since_last_move", "unit_churn_12m", "level", "onet_job_zone",
                    "bls_projected_growth_pct", "bls_separation_rate", "oews_pay_ratio_local", "aei_exposure",
                    "job_evolution_watch")
CATEGORICAL_FEATURES = ("e_class", "p_class", "role_family", "ladder", "campus")
EXTERNAL_FEATURES = ("onet_job_zone", "bls_projected_growth_pct", "bls_separation_rate", "oews_pay_ratio_local",
                     "aei_exposure", "job_evolution_watch")                      # dropped in S2
TENURE_PROXIES = ("tenure_years", "time_in_class_years")                        # dropped in S3; age-correlated
AGE_FEATURE = ("age_band", "age_band")                                          # ablation only (logical, physical)
# Never in a Model A feature matrix (protocol 2.3). Checked by tests and by data.feature_frame().
EXCLUDED_ALWAYS = ("age_band", "surs_eligibility_band", "surs_tier_assumed", "sex_code", "gender_code", "race_eth_rpt_code",
                   "ipeds_race_eth", "citizenship_group", "veteran_class", "college_org_code", "dept_org_code", "org_code",
                   "admin_level_2", "person_id", "position_id", "job_suffix", "annual_salary", "supervisor_span")
# Reporting dimensions carried next to the predictions (never features).
REPORTING_COLS = ("campus_org_code", "college_org_code", "dept_org_code", "ladder_code", "ladder_level", "p_class_code",
                  "e_class", "role_family")
KEY_COLS = ("snap_date", "person_id", "position_id")
LABELS = {12: "promoted_within_12m", 18: "promoted_within_18m"}
SEPARATION_LABELS = {12: "separated_within_12m", 18: None}   # 18m separation base rate is derived from events
TRANSITION_EVENT_TYPES = ("promotion", "transfer_lateral", "transfer_down", "reclassification")  # S1 label
SEPARATION_EVENT_PREFIX = "separation_"

# Fairness attributes (protocol 4): logical name -> (physical column in the demographics frame or features, note)
FAIRNESS_ATTRIBUTES = {
    "sex": ("sex_code", "as reported (restricted frame)"),
    "race_eth_rpt_cd": ("race_eth_rpt_code", "as coded, no re-grouping"),
    "age_40_plus": ("age_band", "derived from the Phase 1 age_band, which carries a cut at 40 (config.AGE_BANDS); "
                                "the protocol's 45+ fallback is not needed"),
}
AGE_40_PLUS_BANDS = ("40-44", "45-54", "55-59", "60-64", "65+")
AGE_UNDER_40_BANDS = ("<25", "25-34", "35-39")

# Star-schema scenarios (delivery/star_schema.yaml dim_scenario). "candidate" is an addition for non-selected
# learners so their failures are published in fact_model_quality (protocol 8); flagged in the README for the
# contract owner. "no_external" is the contract's own code and carries the S2 sensitivity of the primary.
SCENARIOS = {
    "primary": (1, "Primary model", "The learner selected by the protocol 2.4 rule, or A-base-step when no learner passes", True),
    "base_step": (2, "Base rate by ladder step", "A-base-step: base rate by (ladder, level), backoff to role family below 30", False),
    "base_family": (3, "Base rate by role family", "A-base-family: base rate by role_family in the training years", False),
    "candidate": (4, "Candidate learner (not selected)", "A pre-registered learner that was not selected as primary; model-quality page only", False),
    "no_external": (5, "Primary without external covariates", "Sensitivity S2 of the primary learner (external covariates dropped)", False),
}

PERSON_LEVEL_ENV = "WAP_ENABLE_PERSON_LEVEL"
APPROVAL_FILE = SUCCESSION_DIR / "governance" / "approval.json"


def _env(name: str, default):
    v = os.environ.get(name)
    return v if v not in (None, "") else default


def input_dir() -> Path:
    return Path(_env("WAP_A_INPUT_DIR", WAP_DIR / "outputs" / "restricted"))


def output_dir() -> Path:
    return Path(_env("WAP_A_OUTPUT_DIR", HERE / "outputs"))


def restricted_dir() -> Path:
    return output_dir() / "restricted"


def unit_level() -> str:
    u = _env("WAP_A_UNIT_LEVEL", "campus")
    if u not in ("campus", "college", "dept"):
        raise ValueError("WAP_A_UNIT_LEVEL must be campus, college or dept")
    return u


UNIT_COLUMN = {"campus": "campus_org_code", "college": "college_org_code", "dept": "dept_org_code"}


def add_months(d: dt.date, n: int) -> dt.date:
    y, m = divmod(d.month - 1 + n, 12)
    y += d.year
    m += 1
    last = (dt.date(y + (m == 12), 1 if m == 12 else m + 1, 1) - dt.timedelta(days=1)).day
    return dt.date(y, m, min(d.day, last))


def model_version(run_id: str, data_as_of: dt.date) -> str:
    return f"{run_id}-{data_as_of:%Y%m%d}"
