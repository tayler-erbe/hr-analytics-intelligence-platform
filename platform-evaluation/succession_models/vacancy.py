"""(a) Position vacancy risk over 6/12/24 months.

* Discrete-time, cause-specific logistic hazards on 6-month incumbent person-periods
  (separation from the University, internal move out of the position). P(vacancy within h) is
  1 - prod_k (1 - h_sep,k - h_move,k), with age, service and tenure rolled forward each period so
  SURS eligibility can switch on inside the horizon.
* Cox proportional hazards and Weibull AFT (lifelines) on landmark incumbent spells (annual
  landmarks, administrative censoring at the training origin).
* Logistic recalibration per horizon, fitted out-of-time on an origin 24 months earlier.
* Baselines: role-family base rate; age-band-only rule.
* Aggregation: position (restricted), role (family x level), role family and unit, with
  Poisson-binomial intervals for expected vacancy counts.
"""
from __future__ import annotations

import datetime as dt
import warnings

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

from config import HORIZONS, PERIOD_MONTHS, add_months
from features import age_band, design

warnings.filterwarnings("ignore", category=RuntimeWarning)


def label_periods(raw: pd.DataFrame, sp: pd.DataFrame, origin: dt.date) -> pd.DataFrame:
    """Attach 6-month outcomes (labels as known at `origin`) to snapshot rows whose period ends <= origin."""
    snap = pd.to_datetime(raw["snap_dt"])
    end = snap.map(lambda s: pd.Timestamp(add_months(s.date(), PERIOD_MONTHS)))
    keep = end <= pd.Timestamp(origin)
    pp = raw.loc[keep].merge(sp[["pers_id", "posn_nbr", "exit_dt", "cause"]], on=["pers_id", "posn_nbr"], how="left")
    s = pd.to_datetime(pp["snap_dt"])
    e = pd.to_datetime(pp["exit_dt"])
    pend = s.map(lambda x: pd.Timestamp(add_months(x.date(), PERIOD_MONTHS)))
    pp = pp.loc[~(e <= s)].copy()                         # already gone (keyed late): not at risk
    s, e, pend = s[pp.index], e[pp.index], pend[pp.index]
    ev = (e > s) & (e <= pend)
    pp["y_sep"] = (ev & (pp["cause"] == "SEP")).astype(int)
    pp["y_move"] = (ev & (pp["cause"] == "MOVE")).astype(int)
    pp["y_any"] = (pp["y_sep"] | pp["y_move"]).astype(int)
    return pp.reset_index(drop=True)


def _fit_logit(X: pd.DataFrame, y: np.ndarray):
    m = LogisticRegression(C=1e4, max_iter=5000)
    m.fit(X.to_numpy(), y)
    X1 = np.column_stack([np.ones(len(X)), X.to_numpy()])
    p = m.predict_proba(X.to_numpy())[:, 1]
    H = X1.T @ (X1 * (p * (1 - p))[:, None])
    cov = np.linalg.pinv(H)
    names = ["intercept"] + list(X.columns)
    coef = np.concatenate([m.intercept_, m.coef_[0]])
    return m, pd.DataFrame({"term": names, "coef": coef, "se": np.sqrt(np.diag(cov))})


class DiscreteHazard:
    """Cause-specific discrete-time logistic hazard (6-month periods)."""

    def __init__(self, families: list[str], drop: tuple[str, ...] = ()):
        self.families, self.drop = families, drop

    def fit(self, pp: pd.DataFrame):
        X = design(pp, self.families, drop=self.drop)
        self.cols = list(X.columns)
        self.m_sep, self.coef_sep = _fit_logit(X, pp["y_sep"].to_numpy())
        self.m_move, self.coef_move = _fit_logit(X, pp["y_move"].to_numpy())
        self.n_train, self.events = len(pp), int(pp["y_any"].sum())
        return self

    def hazards(self, raw: pd.DataFrame, shift: float):
        X = design(raw, self.families, shift_years=shift, drop=self.drop)[self.cols].to_numpy()
        return self.m_sep.predict_proba(X)[:, 1], self.m_move.predict_proba(X)[:, 1]

    def predict(self, raw: pd.DataFrame, horizons=HORIZONS) -> pd.DataFrame:
        kmax = max(horizons) // PERIOD_MONTHS
        S = np.ones(len(raw))
        cif_sep = np.zeros(len(raw))
        out = {}
        for k in range(kmax):
            hs, hm = self.hazards(raw, k * PERIOD_MONTHS / 12)
            h = np.clip(hs + hm, 0, 0.999)
            cif_sep += S * hs
            S = S * (1 - h)
            m = (k + 1) * PERIOD_MONTHS
            if m in horizons:
                out[f"p{m}"] = 1 - S
                out[f"p{m}_sep"] = cif_sep.copy()
        return pd.DataFrame(out, index=raw.index)


class Recalibrator:
    """Per-horizon logistic recalibration: logit(p') = a + b * logit(p)."""

    def fit(self, preds: pd.DataFrame, outcomes: dict[int, np.ndarray]):
        self.ab = {}
        for h, y in outcomes.items():
            z = _logit(preds[f"p{h}"].to_numpy())
            if len(np.unique(y)) < 2:
                self.ab[h] = (0.0, 1.0)
                continue
            m = LogisticRegression(C=1e6, max_iter=2000).fit(z[:, None], y)
            self.ab[h] = (float(m.intercept_[0]), float(m.coef_[0, 0]))
        return self

    def apply(self, preds: pd.DataFrame) -> pd.DataFrame:
        out = preds.copy()
        for h, (a, b) in self.ab.items():
            out[f"p{h}"] = _expit(a + b * _logit(preds[f"p{h}"].to_numpy()))
        # keep monotone in horizon after recalibration
        hs = sorted(self.ab)
        for i in range(1, len(hs)):
            out[f"p{hs[i]}"] = np.maximum(out[f"p{hs[i]}"], out[f"p{hs[i - 1]}"])
        return out


def _logit(p):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def _expit(z):
    return 1 / (1 + np.exp(-z))


def landmark_data(raw: pd.DataFrame, sp: pd.DataFrame, origin: dt.date) -> pd.DataFrame:
    """Annual (January) landmarks before origin: duration in months to exit or administrative censoring."""
    r = raw[pd.to_datetime(raw["snap_dt"]).dt.month == 1]
    r = r[pd.to_datetime(r["snap_dt"]) < pd.Timestamp(origin)]
    d = r.merge(sp[["pers_id", "posn_nbr", "exit_dt"]], on=["pers_id", "posn_nbr"], how="left")
    s = pd.to_datetime(d["snap_dt"])
    e = pd.to_datetime(d["exit_dt"])
    d = d.loc[~(e <= s)].copy()
    s, e = s[d.index], e[d.index]
    end = e.fillna(pd.Timestamp(origin)).clip(upper=pd.Timestamp(origin))
    d["duration"] = ((end - s).dt.days / 30.4375).clip(lower=0.05)
    d["event"] = (e.notna() & (e <= pd.Timestamp(origin))).astype(int)
    return d.reset_index(drop=True)


class SurvivalModels:
    """CoxPH and Weibull AFT (lifelines) on landmark spells."""

    def __init__(self, families: list[str], drop: tuple[str, ...] = ()):
        self.families, self.drop = families, drop

    def fit(self, lm: pd.DataFrame):
        from lifelines import CoxPHFitter, WeibullAFTFitter
        X = design(lm, self.families, drop=self.drop)
        X = X.loc[:, X.std() > 0]
        self.cols = list(X.columns)
        df = X.assign(duration=lm["duration"].to_numpy(), event=lm["event"].to_numpy())
        self.cox = CoxPHFitter(penalizer=0.01).fit(df, "duration", "event")
        self.wei = WeibullAFTFitter(penalizer=0.01).fit(df, "duration", "event")
        return self

    def predict(self, raw: pd.DataFrame, horizons=HORIZONS) -> dict[str, pd.DataFrame]:
        X = design(raw, self.families, drop=self.drop)[self.cols]
        out = {}
        for name, m in (("cox", self.cox), ("weibull", self.wei)):
            S = m.predict_survival_function(X, times=list(horizons)).T
            S.index = raw.index
            out[name] = pd.DataFrame({f"p{h}": 1 - S[h].to_numpy() for h in horizons}, index=raw.index)
        return out


class Baselines:
    def fit(self, pp: pd.DataFrame):
        self.fam = pp.groupby("role_family")["y_any"].mean().to_dict()
        self.overall = pp["y_any"].mean()
        self.age = pp.assign(band=age_band(pp["age_years"])).groupby("band")["y_any"].mean().to_dict()
        return self

    def predict(self, raw: pd.DataFrame, horizons=HORIZONS) -> dict[str, pd.DataFrame]:
        hf = raw["role_family"].map(self.fam).fillna(self.overall).to_numpy()
        ha = pd.Series(age_band(raw["age_years"])).map(self.age).fillna(self.overall).to_numpy()
        mk = lambda h0: pd.DataFrame({f"p{h}": 1 - (1 - h0) ** (h / PERIOD_MONTHS) for h in horizons}, index=raw.index)  # noqa: E731
        return {"base_rate_family": mk(hf), "age_only": mk(ha)}


def outcomes_at(raw_origin: pd.DataFrame, sp_final: pd.DataFrame, origin: dt.date, horizons=HORIZONS):
    """Observed exits after an origin (final data). Returns time (months, capped) / event / y_h."""
    d = raw_origin[["pers_id", "posn_nbr"]].merge(sp_final[["pers_id", "posn_nbr", "exit_dt", "cause"]],
                                                   on=["pers_id", "posn_nbr"], how="left")
    e = pd.to_datetime(d["exit_dt"])
    months = ((e - pd.Timestamp(origin)).dt.days / 30.4375).clip(lower=0.0)
    hmax = max(horizons)
    t = months.fillna(np.inf).clip(upper=hmax + 0.01).to_numpy()   # no exit by hmax -> censored just after hmax
    ev = (months.notna() & (months <= hmax)).to_numpy().astype(int)
    ys = {h: (months.notna() & (months <= h)).to_numpy().astype(int) for h in horizons}
    return t, ev, ys, d["cause"].to_numpy()


def poisson_binomial_interval(p: np.ndarray, groups: np.ndarray, draws: int = 4000, seed: int = 0) -> pd.DataFrame:
    """Expected count and P10/P90 of the number of vacancies per group (independent Bernoulli)."""
    rng = np.random.default_rng(seed)
    rows = []
    for g in pd.unique(groups):
        pg = p[groups == g]
        sims = (rng.random((draws, len(pg))) < pg).sum(axis=1)
        rows.append(dict(group=g, n=len(pg), expected=float(pg.sum()), p10=float(np.percentile(sims, 10)),
                         p90=float(np.percentile(sims, 90))))
    return pd.DataFrame(rows)


def risk_band(rate: float) -> str:
    """Band on the 24-month expected vacancy RATE of a role/unit (not on any individual)."""
    if rate < 0.25:
        return "Low"
    if rate < 0.40:
        return "Moderate"
    if rate < 0.55:
        return "Elevated"
    return "High"
