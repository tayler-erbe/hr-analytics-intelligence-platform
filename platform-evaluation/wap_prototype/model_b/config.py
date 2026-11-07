"""Fixed settings for Model B (wap-protocol-v1 section 3). Nothing here is tuned on results.

Paths resolve relative to platform-evaluation/. Restricted inputs are the Phase 1 tables in
wap_prototype/outputs/restricted/ (regenerate with `python -m wap_prototype.publish`); restricted outputs go
to model_b/outputs/restricted/ (gitignored); published outputs go to model_b/outputs/.
"""
from __future__ import annotations

from pathlib import Path

HERE = Path(__file__).resolve().parent
WAP = HERE.parent
PE_ROOT = WAP.parent
PHASE1_RESTRICTED = WAP / "outputs" / "restricted"
LAKE = PE_ROOT / "data" / "lake"
OUT = HERE / "outputs"
RESTRICTED = OUT / "restricted"
PROTOCOL_DOC = WAP / "protocol" / "MODEL_PROTOCOL_v1.md"

PROTOCOL_VERSION = "wap-protocol-v1"
MODEL_ID = "B"
SEED = 20261107            # protocol 5.2 default seed
K_MIN = 10                 # protocol 6.1 / config.min_cell_size
H = 12                     # horizons 1..12 quarters (protocol 3.1)
MIN_HISTORY = 12           # first origin = first quarter with 12 quarters of history (protocol 3.4)
WARMUP_ORIGINS = 8         # first 8 origins accumulate errors for empirical intervals (protocol 3.4)
MIN_ERRORS = 12            # minimum resolved errors for an empirical interval (protocol 3.4)
MIN_PATHS = 12             # minimum resolved 4-quarter error paths for the attrition-risk interval simulation
MC_DRAWS = 2000            # Monte Carlo draws for the attrition-risk P10/P90
POOL_THRESHOLD = 10.0      # series with mean headcount below this are pooled to campus x family (protocol 3.2)
PEER_MIN_UNITS = 5         # star_schema: attrition_flag null when the peer distribution has < 5 units
PEER_PCTL = 75             # protocol 3.5
COVID = ("2020-03-31", "2021-06-30")   # target quarters 2020Q1..2021Q2 (protocol 3.3); the synthetic data has no COVID
QWI_LAG_Q = 3              # QWI arrives about three quarters late (protocol 5.1 rule 4)
QCEW_LAG_Q = 2             # QCEW arrives about two quarters late

METHODS = ["B-snaive", "B-ets", "B-pooled", "B-gbm", "B-ens"]
ENSEMBLE_OF = ["B-ets", "B-pooled", "B-gbm"]   # equal weights, geometric mean on 1+y, fixed before scoring (3.3)
TARGETS = ["headcount", "hires", "sep_voluntary", "sep_retirement", "sep_other", "separations"]
SENSITIVITY_TARGETS = ["sep_voluntary_incl_eoa"]   # end-of-appointment counted as voluntary (protocol 0.1)
GATE_TARGETS = ["headcount", "separations"]        # B1/B2 apply to headcount and total separations (3.6)

# Fixed learner hyper-parameters (protocol 3.3 names the methods; these values are frozen here, before scoring,
# following the turnover_forecast patterns, and may only change with a protocol version bump).
ETS_SPEC = dict(error="add", trend="add", damped_trend=True, seasonal="add", seasonal_periods=4)
ETS_MIN_POINTS = 16
RIDGE_ALPHAS = [0.01, 0.0316, 0.1, 0.316, 1.0, 3.16, 10.0, 31.6, 100.0, 316.0, 1000.0]
RIDGE_MIN_ROWS = 30
GBM_PARAMS = dict(n_estimators=300, learning_rate=0.03, num_leaves=15, min_child_samples=20, subsample=0.8,
                  subsample_freq=1, colsample_bytree=0.8, reg_lambda=1.0, deterministic=True,
                  force_row_wise=True, n_jobs=1, num_threads=1, verbose=-1)
GBM_MIN_ROWS = 200

# Cause groups (protocol 0.1 and 3.2): voluntary = resignation; retirement; other = involuntary, end of
# appointment, death, other. End of appointment is also carried on its own for the sensitivity target.
CAUSE_GROUPS = {
    "separation_resignation": "sep_voluntary",
    "retirement": "sep_retirement",
    "separation_end_of_appointment": "sep_other",
    "separation_involuntary": "sep_other",
    "separation_death": "sep_other",
    "separation_other": "sep_other",
}
CAUSE_PRIORITY = ["retirement", "separation_resignation", "separation_end_of_appointment", "separation_involuntary",
                  "separation_death", "separation_other"]
HIRE_EVENTS = ("hire", "rehire")
AGE_55_PLUS = ("55-59", "60-64", "65+")
AGE_45_PLUS = ("45-54", "55-59", "60-64", "65+")      # the audit's age_40_plus attribute, implemented as 45+ (protocol 0.1)
SURS_NEAR = ("eligible_unreduced", "eligible_reduced", "within_5_years")   # foundation band is within_5_years, not 3

# Covariate names in the design matrix (unit-level population shares and external context, all dated at the
# origin or earlier). Protocol 3.3.
UNIT_COVARIATES = ["share_55plus", "share_surs_near", "unit_churn_12m", "oews_pay_ratio_local",
                   "bls_projected_growth_pct", "bls_separation_rate"]
EXTERNAL_COVARIATES = ["qwi_sep_rate", "qwi_hire_rate", "qcew_he_emp_yoy"]
