"""Out-of-time backtest, calibration, baselines and parameter recovery.

For each origin C (Jan 1 of Y+1) every model is trained ONLY on snapshot features as known before C
and on labels as known at C (spells(known_at=C)); predictions are made from the as-of snapshot at C
and scored against outcomes observed in the latest data over C..C+24 months.
"""
from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd

import metrics as M
from config import BACKTEST_ORIGINS, HORIZONS, TRAIN_HISTORY_YEARS, add_months
from features import AGE_DERIVED, design
from mobility import Mobility
from snapshot import spells
from vacancy import (Baselines, DiscreteHazard, Recalibrator, SurvivalModels, _expit, label_periods, landmark_data,
                     outcomes_at)
from bench import bench, realized_flows


class OracleHazard(DiscreteHazard):
    """The generator's TRUE hazards (department frailty omitted: it is unobservable). Synthetic only."""

    def __init__(self, truth: dict, families: list[str]):
        super().__init__(families)
        self.t = truth

    def hazards(self, raw, shift):
        X = design(raw, self.families, shift_years=shift)
        out = []
        for cause, famkey in (("sep", "sep_family"), ("move", "move_family")):
            c = self.t[cause]
            lp = c["intercept"] + sum(c.get(k, 0.0) * X[k].to_numpy() for k in c if k in X.columns)
            lp = lp + raw["role_family"].map(self.t[famkey]).fillna(0.0).to_numpy()
            out.append(1 - (1 - _expit(lp)) ** 1.0)
        return out[0], out[1]


def train_window(raw_all: pd.DataFrame, origin: dt.date) -> pd.DataFrame:
    s = pd.to_datetime(raw_all["snap_dt"])
    lo = pd.Timestamp(origin) - pd.DateOffset(years=TRAIN_HISTORY_YEARS)
    return raw_all[(s >= lo) & (s < pd.Timestamp(origin))]


def at(raw_all: pd.DataFrame, d: dt.date) -> pd.DataFrame:
    return raw_all[pd.to_datetime(raw_all["snap_dt"]) == pd.Timestamp(d)].reset_index(drop=True)


def fit_calibrated(con, raw_all, fams, origin: dt.date, drop=()):
    """Hazard model trained through `origin`, recalibrated on the origin 24 months earlier."""
    sp_c = spells(con, origin)
    pp = label_periods(train_window(raw_all, origin), sp_c, origin)
    model = DiscreteHazard(fams, drop).fit(pp)
    o_cal = add_months(origin, -24)
    sp_cal = spells(con, o_cal)
    pp_cal = label_periods(train_window(raw_all, o_cal), sp_cal, o_cal)
    m_cal = DiscreteHazard(fams, drop).fit(pp_cal)
    r_cal = at(raw_all, o_cal)
    _, _, ys, _ = outcomes_at(r_cal, sp_c, o_cal)          # outcomes known at `origin`
    recal = Recalibrator().fit(m_cal.predict(r_cal), ys)
    return model, recal, pp, sp_c


def backtest(con, raw_all, fams, roles, truth=None, origins=BACKTEST_ORIGINS):
    sp_final = spells(con)
    rows, cal_rows, cidx, bench_rows, recal_rows = [], [], [], [], []
    for o in origins:
        model, recal, pp, sp_c = fit_calibrated(con, raw_all, fams, o)
        m_noage = DiscreteHazard(fams, tuple(AGE_DERIVED)).fit(pp)
        surv = SurvivalModels(fams).fit(landmark_data(train_window(raw_all, o), sp_c, o))
        base = Baselines().fit(pp)
        ro = at(raw_all, o)
        raw_pred = model.predict(ro)
        preds = {"logistic_hazard": recal.apply(raw_pred), "logistic_hazard_uncalibrated": raw_pred,
                 "logistic_hazard_no_age": m_noage.predict(ro)}
        preds.update(surv.predict(ro))
        preds.update(base.predict(ro))
        if truth is not None:
            preds["oracle_true_parameters"] = OracleHazard(truth, fams).predict(ro)
        t, ev, ys, _ = outcomes_at(ro, sp_final, o)
        for name, p in preds.items():
            for h in HORIZONS:
                c = M.calibration(ys[h], p[f"p{h}"])
                rows.append(dict(origin=o.isoformat(), train_through=o.year - 1, model=name, horizon=h, n=len(ro),
                                 events=int(ys[h].sum()), brier=M.brier(ys[h], p[f"p{h}"]),
                                 auc_t=M.auc_cd(t, ev, p[f"p{h}"].to_numpy(), h), mean_pred=c["mean_pred"],
                                 obs_rate=c["obs_rate"], citl=c["citl"], cal_slope=c["slope"]))
            cidx.append(dict(origin=o.isoformat(), model=name, c_index=M.cindex(t, ev, p["p24"].to_numpy())))
            if o == origins[-1] and name in ("logistic_hazard", "logistic_hazard_uncalibrated", "cox", "weibull",
                                             "base_rate_family", "oracle_true_parameters"):
                for h in (12, 24):
                    d = M.decile_table(ys[h], p[f"p{h}"])
                    d["model"], d["horizon"], d["origin"] = name, h, o.isoformat()
                    cal_rows.append(d)
        recal_rows += [dict(origin=o.isoformat(), horizon=h, a=a, b=b) for h, (a, b) in recal.ab.items()]
        # bench forecast vs realized internal flows
        mob = Mobility(roles).fit(sp_c, o)
        scored = ro.join(preds["logistic_hazard"])
        b = bench(scored, mob, roles, draws=1000, seed=11)
        r = realized_flows(sp_final, roles, o)
        bb = b.merge(r, on="role_family")
        bb["origin"] = o.isoformat()
        bench_rows.append(bb)
    res = pd.DataFrame(rows)
    return dict(results=res, cindex=pd.DataFrame(cidx), calibration=pd.concat(cal_rows, ignore_index=True),
                bench=pd.concat(bench_rows, ignore_index=True), recal=pd.DataFrame(recal_rows))


def summarize(res: pd.DataFrame, cidx: pd.DataFrame) -> pd.DataFrame:
    g = res.groupby(["model", "horizon"]).agg(brier=("brier", "mean"), auc_t=("auc_t", "mean"),
                                              auc_t_min=("auc_t", "min"), auc_t_max=("auc_t", "max"),
                                              citl=("citl", "mean"), abs_citl=("citl", lambda s: s.abs().mean()),
                                              cal_slope=("cal_slope", "mean")).reset_index()
    ref = g[g["model"] == "base_rate_family"].set_index("horizon")["brier"]
    g["brier_skill_vs_family_rate"] = 1 - g["brier"] / g["horizon"].map(ref)
    c = cidx.groupby("model")["c_index"].mean().rename("c_index_24m")
    return g.merge(c, on="model", how="left")


def recovery(model: DiscreteHazard, truth: dict) -> pd.DataFrame:
    rows = []
    for cause, coef, fam_key in (("separation", model.coef_sep, "sep_family"), ("internal move", model.coef_move, "move_family")):
        t = truth["sep" if cause == "separation" else "move"]
        tf = truth[fam_key]
        c = coef.set_index("term")
        for term, r in c.iterrows():
            if term.startswith("fam::"):
                f = term[5:]
                ref_f = model.families[0]
                true = tf.get(f, 0.0) - tf.get(ref_f, 0.0)
            elif term == "unit_churn_c":
                true = np.nan                      # not planted directly (proxy for unobserved unit frailty)
            else:
                true = t.get(term, np.nan)
            lo, hi = r["coef"] - 1.96 * r["se"], r["coef"] + 1.96 * r["se"]
            rows.append(dict(cause=cause, term=term, true=true, estimate=r["coef"], se=r["se"], ci_lo=lo, ci_hi=hi,
                             covered=bool(lo <= true <= hi) if not np.isnan(true) else None,
                             abs_error=abs(r["coef"] - true) if not np.isnan(true) else np.nan))
    return pd.DataFrame(rows)
