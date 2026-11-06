"""Feature definitions shared by the models (and, on synthetic data only, by the generator).

The snapshot builder (snapshot.py) returns RAW as-of quantities (age, service, tenure, pay position,
unit churn ...). `design()` turns them into the model matrix, optionally rolled forward by
`shift_years` so the discrete-time hazard can project 6/12/24 months ahead with deterministic
covariates (age, service and tenure advance; SURS status is recomputed; recent-change flags expire).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from config import SURS_RULES

SEP_FEATURES = ["tenure_lt2", "surs_unreduced", "surs_reduced_only", "surs_within_3y", "part_time",
                "pay_pos_c", "unit_churn_c", "recent_change", "in_role_ge2", "top_level"]
# Features that encode age (directly or through SURS eligibility). Dropped in the "no-age" ablation that
# HB 3773 / ADEA reviewers will ask for.
AGE_DERIVED = ["surs_unreduced", "surs_reduced_only", "surs_within_3y"]
UNIT_CHURN_CENTER = 0.20       # centring constant for unit churn (trailing-12-month position-exit rate)


def surs_status(age, service, tier):
    """Vectorised SURS status under the ASSUMED rules in config.SURS_RULES.

    Returns (unreduced_eligible, reduced_only_eligible, years_to_unreduced) as numpy arrays.
    years_to_unreduced is 0 when already eligible, assuming continued service.
    """
    age = np.asarray(age, float)
    service = np.asarray(service, float)
    tier = np.asarray(tier, int)
    unred = np.zeros(age.shape, bool)
    red = np.zeros(age.shape, bool)
    ytu = np.full(age.shape, np.inf)
    for t, rules in SURS_RULES.items():
        m = tier == t
        for a_min, s_min in rules["unreduced"]:
            ok = (age >= a_min) & (service >= s_min)
            unred |= m & ok
            wait = np.maximum(np.maximum(a_min - age, s_min - service), 0.0)
            ytu = np.where(m, np.minimum(ytu, wait), ytu)
        for a_min, s_min in rules["reduced"]:
            red |= m & (age >= a_min) & (service >= s_min)
    return unred, red & ~unred, ytu


def design(raw: pd.DataFrame, families: list[str], shift_years: float = 0.0,
           drop: tuple[str, ...] = ()) -> pd.DataFrame:
    """Model matrix from raw snapshot columns. `families` fixes the dummy coding (first = reference)."""
    age = raw["age_years"].to_numpy(float) + shift_years
    service = raw["service_years"].to_numpy(float) + shift_years
    tenure = raw["tenure_years"].to_numpy(float) + shift_years
    in_role = raw["role_years"].to_numpy(float) + shift_years
    unred, red_only, ytu = surs_status(age, service, raw["surs_tier"].to_numpy(int))
    pay = np.clip(raw["pay_pos"].to_numpy(float) + 0.03 * np.floor(shift_years), 0, 1)
    recent = (raw["days_since_role_change"].to_numpy(float) + 365.25 * shift_years) <= 365
    X = pd.DataFrame({
        "tenure_lt2": (tenure < 2).astype(float),
        "surs_unreduced": unred.astype(float),
        "surs_reduced_only": red_only.astype(float),
        "surs_within_3y": ((~unred) & (~red_only) & (ytu <= 3)).astype(float),   # not yet eligible at all
        "part_time": (raw["fte"].to_numpy(float) < 0.999).astype(float),
        "pay_pos_c": pay - 0.5,
        "unit_churn_c": raw["unit_churn"].to_numpy(float) - UNIT_CHURN_CENTER,
        "recent_change": (recent & (raw["prior_role"].to_numpy(bool))).astype(float),
        "in_role_ge2": (in_role >= 2).astype(float),
        "top_level": raw["top_level"].to_numpy(float),
    }, index=raw.index)
    for f in families[1:]:
        X[f"fam::{f}"] = (raw["role_family"].to_numpy() == f).astype(float)
    if drop:
        X = X.drop(columns=[c for c in drop if c in X.columns])
    return X


def age_band(age) -> np.ndarray:
    a = np.asarray(age, float)
    bins = [0, 35, 45, 55, 60, 65, 200]
    labels = np.array(["<35", "35-44", "45-54", "55-59", "60-64", "65+"])
    return labels[np.digitize(a, bins[1:-1])]
