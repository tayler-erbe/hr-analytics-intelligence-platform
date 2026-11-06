"""Predict which occupations will show high task or technology churn at their next
O*NET update, with a rolling-origin temporal backtest.

Targets
  task : at the lineage's NEXT real task update after origin release t (the first
         later release whose task 'Date' moved), is task churn above the training-
         period 67th percentile? (Most updates change no statement at all, so the
         training 67th percentile is 0 and "high" means "any substantive change".)
  tech : over the NEXT release interval after t, is technology-example churn
         (added + removed, renames excluded) above the training 67th percentile?
         O*NET publishes no per-occupation technology update date, so the next
         release interval is the update unit for technology.

Leakage controls (asserted in code and in tests)
  * Features for origin t are computed from releases <= t only (features_at
    filters by release index; a truncated-panel test checks equality).
  * A training row is used for test origin T only if its origin < T AND its label
    event was published in a release <= T.
  * The "high" threshold is computed from those training labels only.
  * AEI AI-usage exposure (published 2025-2026) postdates every test origin, so it
    appears only in a separately reported, flagged ex-post variant.

Also fits a discrete-time (cloglog) hazard model of WHEN an occupation's tasks are
next updated, because release-to-release change is dominated by update timing.

Outputs: artifacts/backtest_report.json, artifacts/predictions_latest.parquet,
         artifacts/timing_model.json
"""
from __future__ import annotations

import os

# Single-threaded BLAS: ~10x faster for these small problems and bit-for-bit reproducible.
for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_v, "1")

import math
import sys
import warnings
from collections import defaultdict

import duckdb
import lightgbm as lgb
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import statsmodels.api as sm
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score

from common import ART, CONTRACT, DERIVED, PROTOCOL, REL_INDEX, RELEASES, dump_json, release_year, rnd

warnings.filterwarnings("ignore")
VERS = [v for v, _, _ in RELEASES]
SEED = PROTOCOL["random_seed"]
LATEST = VERS[-1]
GWA_IDS: list[str] = []


def q(con, sql):
    rel = con.execute(sql)
    cols = [d[0] for d in rel.description]
    return [dict(zip(cols, r)) for r in rel.fetchall()]


# ---------------------------------------------------------------------------
# data
# ---------------------------------------------------------------------------
def load_panel():
    con = duckdb.connect()
    states = defaultdict(dict)  # lineage -> rel -> state
    for r in q(con, f"select * from '{ART / 'occ_state.parquet'}'"):
        states[r["lineage_id"]][r["release"]] = r
    trans = defaultdict(list)   # lineage -> [transition rows sorted]
    for r in q(con, f"select * from '{ART / 'transitions.parquet'}'"):
        trans[r["lineage_id"]].append(r)
    for k in trans:
        trans[k].sort(key=lambda r: REL_INDEX[r["rel"]])
    gwa = defaultdict(dict)
    for r in q(con, f"select * from '{DERIVED / 'state_gwa.parquet'}'"):
        gwa[(r["lineage_id"], r["release"])][r["element_id"]] = r["im"]
    ids = sorted({e for d in gwa.values() for e in d})
    GWA_IDS[:] = ids
    aei = {r["soc_2018_code"]: r["observed_exposure"]
           for r in q(con, f"select soc_2018_code, observed_exposure from '{CONTRACT / 'aei_occupation_exposure.parquet'}'")}
    return states, trans, gwa, aei


# ---------------------------------------------------------------------------
# features (origin release index o; uses releases <= o only)
# ---------------------------------------------------------------------------
def features_at(lid: str, o: int, states, trans, gwa, aei) -> dict | None:
    rel = VERS[o]
    st = states.get(lid, {}).get(rel)
    if st is None or not st["n_tasks"]:
        return None
    past = [t for t in trans.get(lid, []) if REL_INDEX[t["rel"]] <= o]   # <- the leakage guard
    tu = [t for t in past if t["task_update"] and t["task_churn"] is not None]
    non_upd_edits = sum((t["n_added"] or 0) + (t["n_removed"] or 0) + (t["n_revised"] or 0)
                        for t in past if not t["task_update"] and t["task_churn"] is not None)
    sk = [t for t in past if t["skills_update"] and not t["skills_method_change"] and t["skills_drift"] is not None]
    gw = [t for t in past if t["gwa_update"] and not t["gwa_method_change"] and t["gwa_drift"] is not None]
    te = [t for t in past if t["tech_churn"] is not None]
    src = st["task_source"] or ""
    f = {
        "job_zone": st["job_zone"],
        "n_tasks": st["n_tasks"],
        "share_core": st["share_core"],
        "years_since_task_update": (release_year(rel) - st["task_date"]) if st["task_date"] else None,
        "task_src_incumbent": 1.0 if src == "Incumbent" else 0.0,
        "task_src_expert": 1.0 if src == "Occupational Expert" else 0.0,
        "task_src_analyst": 1.0 if src.startswith("Analyst") else 0.0,
        "n_past_task_updates": len(tu),
        "last_task_churn": tu[-1]["task_churn"] if tu else None,
        "mean_task_churn_past": float(np.mean([t["task_churn"] for t in tu])) if tu else None,
        "frac_past_updates_changed": float(np.mean([t["task_churn"] > 0 for t in tu])) if tu else None,
        "past_nonupdate_edits": non_upd_edits,
        "last_skills_drift": sk[-1]["skills_drift"] if sk else None,
        "last_gwa_drift": gw[-1]["gwa_drift"] if gw else None,
        "n_emerging_listed": st["n_emerging_listed"] if o >= REL_INDEX["21.0"] else None,
        "n_tech": st["n_tech"],
        "hot_share": (st["n_hot"] / st["n_tech"]) if st["n_tech"] else None,
        "n_ai_tech": st["n_ai_tech"],
        "data_tech_share": (st["n_data_tech"] / st["n_tech"]) if st["n_tech"] else None,
        "last_tech_churn": te[-1]["tech_churn"] if te else None,
        "mean_tech_churn_past": float(np.mean([t["tech_churn"] for t in te])) if te else None,
        "last_tech_added_per_year": te[-1]["tech_adoption_per_year"] if te else None,
    }
    g = gwa.get((lid, rel), {})
    for e in GWA_IDS:
        f[f"gwa_{e}"] = g.get(e)
    f["soc_major"] = st["code"][:2]
    c19 = st["codes_2019"] or []
    f["aei_exposure_expost"] = aei.get(c19[0][:7]) if len(c19) == 1 else None
    return f


def make_rows(kind: str, states, trans, gwa, aei, origins: list[int]) -> tuple[list[dict], dict]:
    """One row per (lineage, origin) with features at origin and the label event."""
    rows, censored = [], defaultdict(int)
    for lid in sorted(states):
        tr = trans.get(lid, [])
        for o in origins:
            f = features_at(lid, o, states, trans, gwa, aei)
            if f is None:
                continue
            fut = [t for t in tr if REL_INDEX[t["rel"]] > o]
            if kind == "task":
                ev = next((t for t in fut if t["task_update"] and t["task_churn"] is not None), None)
                if ev is None:
                    censored["no_task_update_observed_by_" + LATEST if (fut and fut[-1]["rel"] == LATEST)
                             else "lineage_ended_or_no_data"] += 1
                    continue
                yv = ev["task_churn"]
            else:
                if f["n_tech"] is None or o < REL_INDEX["22.0"]:
                    continue
                ev = fut[0] if fut and REL_INDEX[fut[0]["rel"]] == o + 1 else None
                if ev is None or ev["tech_churn"] is None:
                    censored["no_next_release_on_lineage"] += 1
                    continue
                yv = ev["tech_churn"]
            rows.append({"lineage_id": lid, "origin": o, "event_idx": REL_INDEX[ev["rel"]], "y_value": yv,
                         "code": states[lid][VERS[o]]["code"], "feat": f})
    return rows, dict(censored)


# ---------------------------------------------------------------------------
# matrices and models
# ---------------------------------------------------------------------------
def feature_names(include_aei: bool) -> list[str]:
    base = ["job_zone", "n_tasks", "share_core", "years_since_task_update", "task_src_incumbent",
            "task_src_expert", "task_src_analyst", "n_past_task_updates", "last_task_churn",
            "mean_task_churn_past", "frac_past_updates_changed", "past_nonupdate_edits", "last_skills_drift",
            "last_gwa_drift", "n_emerging_listed", "n_tech", "hot_share", "n_ai_tech", "data_tech_share",
            "last_tech_churn", "mean_tech_churn_past", "last_tech_added_per_year"] + [f"gwa_{e}" for e in GWA_IDS]
    return base + (["aei_exposure_expost"] if include_aei else [])


SOC_MAJORS = ["11", "13", "15", "17", "19", "21", "23", "25", "27", "29", "31", "33", "35", "37", "39", "41",
              "43", "45", "47", "49", "51", "53", "55"]


def to_matrix(rows, names):
    X = np.array([[np.nan if r["feat"].get(n) is None else float(r["feat"][n]) for n in names] for r in rows],
                 dtype=float).reshape(len(rows), len(names))
    S = np.array([[1.0 if r["feat"]["soc_major"] == m else 0.0 for m in SOC_MAJORS] for r in rows],
                 dtype=float).reshape(len(rows), len(SOC_MAJORS))
    return X, S


class Logit:
    """Median imputation + missing indicators + standardization + L2 logistic."""

    def __init__(self, C=0.5):
        self.C = C

    def fit(self, X, S, y, w):
        self.med = np.nanmedian(X, axis=0)
        self.med = np.where(np.isnan(self.med), 0.0, self.med)
        self.miss_cols = np.where(np.isnan(X).any(axis=0))[0]
        Z = self._z(X, S, fit=True)
        self.m = LogisticRegression(C=self.C, max_iter=5000)
        self.m.fit(Z, y, sample_weight=w)
        return self

    def _z(self, X, S, fit=False):
        Xi = np.where(np.isnan(X), self.med, X)
        M = np.isnan(X[:, self.miss_cols]).astype(float)
        Z = np.hstack([Xi, M])
        if fit:
            self.mu = Z.mean(axis=0)
            self.sd = Z.std(axis=0)
            self.sd[self.sd == 0] = 1.0
        return np.hstack([(Z - self.mu) / self.sd, S])

    def predict(self, X, S):
        return self.m.predict_proba(self._z(X, S))[:, 1]


def fit_lgbm(X, S, y, w):
    m = lgb.LGBMClassifier(n_estimators=300, learning_rate=0.03, num_leaves=15, min_child_samples=25,
                           subsample=0.8, subsample_freq=1, colsample_bytree=0.8, reg_lambda=1.0,
                           random_state=SEED, verbose=-1, deterministic=True, force_row_wise=True, n_jobs=1)
    m.fit(np.hstack([X, S]), y, sample_weight=w)
    return m


def event_weights(rows):
    """Rows sharing one label event (same lineage, same next update) get total weight 1."""
    cnt = defaultdict(int)
    for r in rows:
        cnt[(r["lineage_id"], r["event_idx"])] += 1
    return np.array([1.0 / cnt[(r["lineage_id"], r["event_idx"])] for r in rows])


def threshold_from(rows):
    uniq = {(r["lineage_id"], r["event_idx"]): r["y_value"] for r in rows}
    return float(np.quantile(np.array(list(uniq.values())), PROTOCOL["target_quantile"]))


# ---------------------------------------------------------------------------
# metrics
# ---------------------------------------------------------------------------
def ece(y, p, bins=10):
    edges = np.linspace(0, 1, bins + 1)
    idx = np.clip(np.digitize(p, edges) - 1, 0, bins - 1)
    e = 0.0
    out = []
    for b in range(bins):
        m = idx == b
        if m.any():
            e += m.mean() * abs(y[m].mean() - p[m].mean())
            out.append({"bin": b, "n": int(m.sum()), "mean_pred": rnd(p[m].mean()), "obs_rate": rnd(y[m].mean())})
    return e, out


def calib_slope(y, p):
    lp = np.log(np.clip(p, 1e-6, 1 - 1e-6) / (1 - np.clip(p, 1e-6, 1 - 1e-6)))
    try:
        res = sm.GLM(y, sm.add_constant(lp), family=sm.families.Binomial()).fit()
        return float(res.params[0]), float(res.params[1])
    except Exception:
        return None, None


def metrics(y, p):
    if len(set(y.tolist())) < 2:
        return {"n": int(len(y)), "positives": int(y.sum()), "auc": None, "ap": None,
                "brier": rnd(brier_score_loss(y, p)) if len(y) else None}
    e, _ = ece(y, p)
    a, b = calib_slope(y, p)
    return {"n": int(len(y)), "positives": int(y.sum()), "base_rate": rnd(y.mean()),
            "auc": rnd(roc_auc_score(y, p)), "ap": rnd(average_precision_score(y, p)),
            "brier": rnd(brier_score_loss(y, p)), "brier_ref_base_rate": rnd(brier_score_loss(y, np.full_like(p, y.mean()))),
            "ece": rnd(e), "calib_intercept": rnd(a), "calib_slope": rnd(b)}


def cluster_bootstrap(y, preds: dict, clusters, reps, rng):
    """Bootstrap by lineage. Returns 95% CIs for AUC/AP/Brier of each predictor and
    the paired AUC difference of each model versus each baseline."""
    uc = np.unique(clusters)
    idx_by = {c: np.where(clusters == c)[0] for c in uc}
    stats = defaultdict(list)
    for _ in range(reps):
        pick = rng.choice(uc, size=len(uc), replace=True)
        ii = np.concatenate([idx_by[c] for c in pick])
        yy = y[ii]
        if len(set(yy.tolist())) < 2:
            continue
        aucs = {}
        for k, p in preds.items():
            pp = p[ii]
            aucs[k] = roc_auc_score(yy, pp)
            stats[(k, "auc")].append(aucs[k])
            stats[(k, "ap")].append(average_precision_score(yy, pp))
            stats[(k, "brier")].append(brier_score_loss(yy, pp))
        for m in ("logit", "lgbm", "logit_aei_expost", "logit_recal_posthoc"):
            for b in ("baseline_last_change", "baseline_family_mean"):
                if m in aucs and b in aucs:
                    stats[(f"{m}_minus_{b}", "auc")].append(aucs[m] - aucs[b])
    out = {}
    for (k, s), v in stats.items():
        v = np.array(v)
        out.setdefault(k, {})[f"{s}_ci95"] = [rnd(np.quantile(v, 0.025)), rnd(np.quantile(v, 0.975))]
        if "_minus_" in k:
            out[k]["share_reps_above_0"] = rnd((v > 0).mean())
    return out


# ---------------------------------------------------------------------------
# backtest
# ---------------------------------------------------------------------------
def run_backtest(kind, all_rows, test_origins, rng):
    folds, pooled = [], defaultdict(list)
    names = feature_names(False)
    names_aei = feature_names(True)
    leakage = []
    for T in test_origins:
        To = REL_INDEX[T]
        train = [r for r in all_rows if r["origin"] < To and r["event_idx"] <= To]
        test = [r for r in all_rows if r["origin"] == To]
        if len(train) < PROTOCOL["min_train_rows"] or not test:
            folds.append({"origin": T, "skipped": True, "n_train": len(train), "n_test": len(test)})
            continue
        thr = threshold_from(train)
        ytr = np.array([r["y_value"] > thr for r in train], dtype=int)
        yte = np.array([r["y_value"] > thr for r in test], dtype=int)
        if len(set(ytr.tolist())) < 2:
            folds.append({"origin": T, "skipped": True, "reason": "single-class training labels"})
            continue
        leakage.append({"origin": T, "max_train_event_release": VERS[max(r["event_idx"] for r in train)],
                        "max_train_origin": VERS[max(r["origin"] for r in train)],
                        "ok": max(r["event_idx"] for r in train) <= To and max(r["origin"] for r in train) < To})
        w = event_weights(train)
        Xtr, Str = to_matrix(train, names)
        Xte, Ste = to_matrix(test, names)
        p = {}
        p["logit"] = Logit().fit(Xtr, Str, ytr, w).predict(Xte, Ste)
        # POST-HOC variant (added after the first backtest run showed calibration drift):
        # recalibrate the primary logit on the most recent labels known at T.
        a, b = recalibration(train, To, thr, names)
        p["logit_recal_posthoc"] = apply_recal(p["logit"], a, b) if a is not None else p["logit"]
        recal_info = {"intercept": rnd(a), "slope": rnd(b), "applied": a is not None}
        p["lgbm"] = fit_lgbm(Xtr, Str, ytr, w).predict_proba(np.hstack([Xte, Ste]))[:, 1]
        # ex-post variant (flagged): AEI exposure was published after every origin
        Xa, Sa = to_matrix(train, names_aei)
        Xb, Sb = to_matrix(test, names_aei)
        p["logit_aei_expost"] = Logit().fit(Xa, Sa, ytr, w).predict(Xb, Sb)
        # naive baselines
        last_key = "last_task_churn" if kind == "task" else "last_tech_churn"
        li = names.index(last_key)
        b1 = Logit(C=1e6).fit(Xtr[:, [li]], np.zeros((len(train), 0)), ytr, w)
        p["baseline_last_change"] = b1.predict(Xte[:, [li]], np.zeros((len(test), 0)))
        fam = defaultdict(list)
        for r, yy, ww in zip(train, ytr, w):
            fam[r["feat"]["soc_major"]].append((yy, ww))
        glob = float(np.average(ytr, weights=w))
        fm = {k: (sum(a * b for a, b in v) + 2 * glob) / (sum(b for _, b in v) + 2) for k, v in fam.items()}
        p["baseline_family_mean"] = np.array([fm.get(r["feat"]["soc_major"], glob) for r in test])
        p["baseline_base_rate"] = np.full(len(test), glob)
        fold = {"origin": T, "origin_year": RELEASES[To][1], "n_train": len(train), "n_test": len(test),
                "threshold": rnd(thr), "recalibration_posthoc": recal_info, "train_positive_rate": rnd(float(np.average(ytr, weights=w))),
                "models": {k: metrics(yte, v) for k, v in p.items()}}
        folds.append(fold)
        pooled["y"].append(yte)
        pooled["cl"].append(np.array([r["lineage_id"] for r in test]))
        pooled["origin"].append(np.full(len(test), To))
        for k, v in p.items():
            pooled[k].append(v)
    y = np.concatenate(pooled["y"])
    cl = np.concatenate(pooled["cl"])
    preds = {k: np.concatenate(v) for k, v in pooled.items() if k not in ("y", "cl", "origin")}
    pooled_m = {k: metrics(y, v) for k, v in preds.items()}
    calib = {k: ece(y, v)[1] for k, v in preds.items() if k in ("logit", "logit_recal_posthoc", "lgbm", "baseline_family_mean")}
    boot = cluster_bootstrap(y, {k: v for k, v in preds.items() if k != "baseline_base_rate"}, cl,
                             PROTOCOL["bootstrap_reps"], rng)
    return {"folds": folds, "pooled": pooled_m, "pooled_n_test_rows": int(len(y)),
            "pooled_unique_lineages": int(len(np.unique(cl))), "calibration_bins": calib, "bootstrap": boot,
            "leakage_checks": leakage, "all_leakage_checks_ok": all(x["ok"] for x in leakage)}


def recalibration(train, To, thr, names, lag=2):
    """Leak-free Platt recalibration for origin index To: fit the model as it would
    have been fitted at To-lag, predict the rows whose origin is in [To-lag, To)
    (labels published by To), and regress those labels on logit(p)."""
    inner = [r for r in train if r["origin"] < To - lag and r["event_idx"] <= To - lag]
    cal = [r for r in train if To - lag <= r["origin"] < To and r["event_idx"] <= To]
    if len(inner) < PROTOCOL["min_train_rows"] or len(cal) < 50:
        return None, None
    yi = np.array([r["y_value"] > thr for r in inner], dtype=int)
    yc = np.array([r["y_value"] > thr for r in cal], dtype=int)
    if len(set(yi.tolist())) < 2 or len(set(yc.tolist())) < 2:
        return None, None
    Xi, Si = to_matrix(inner, names)
    Xc, Sc = to_matrix(cal, names)
    pc = Logit().fit(Xi, Si, yi, event_weights(inner)).predict(Xc, Sc)
    return calib_slope(yc, pc)


def apply_recal(p, a, b):
    lp = np.log(np.clip(p, 1e-6, 1 - 1e-6) / (1 - np.clip(p, 1e-6, 1 - 1e-6)))
    return 1 / (1 + np.exp(-(a + b * lp)))


def importance(rows, thr):
    names = feature_names(False)
    y = np.array([r["y_value"] > thr for r in rows], dtype=int)
    w = event_weights(rows)
    X, S = to_matrix(rows, names)
    lg = Logit().fit(X, S, y, w)
    coefs = lg.m.coef_[0][:len(names)]
    order = np.argsort(-np.abs(coefs))[:12]
    gb = fit_lgbm(X, S, y, w)
    gain = gb.booster_.feature_importance("gain")[:len(names)]
    gorder = np.argsort(-gain)[:12]
    return {"logit_top_standardized_coefficients": [[names[i], rnd(coefs[i])] for i in order],
            "lgbm_top_gain": [[names[i], rnd(gain[i] / gain.sum())] for i in gorder]}


# ---------------------------------------------------------------------------
# timing (hazard) model
# ---------------------------------------------------------------------------
YS_BINS = [(0, 2), (2, 4), (4, 6), (6, 8), (8, 10), (10, 99)]


def timing_rows(states, trans):
    rows = []
    for lid, tr in trans.items():
        for t in tr:
            st = states[lid].get(t["rel_prev"])
            if t["task_churn"] is None or st is None or st["task_date"] is None:
                continue
            ys = release_year(t["rel_prev"]) - st["task_date"]
            rows.append({"lineage_id": lid, "rel": t["rel"], "y": int(bool(t["task_update"])),
                         "years": t["years"], "ys": ys, "jz": st["job_zone"],
                         "src": st["task_source"] or "", "code": st["code"]})
    return rows


def timing_design(rows):
    X = []
    for r in rows:
        x = [1.0 if lo <= r["ys"] < hi else 0.0 for lo, hi in YS_BINS[1:]]
        x += [1.0 if r["jz"] == j else 0.0 for j in (1, 2, 4, 5)]
        x += [1.0 if r["src"] == "Occupational Expert" else 0.0, 1.0 if r["src"].startswith("Analyst") else 0.0]
        X.append(x)
    names = [f"ys_{lo}_{hi}" for lo, hi in YS_BINS[1:]] + ["jz1", "jz2", "jz4", "jz5", "src_expert", "src_analyst"]
    return sm.add_constant(np.array(X), has_constant="add"), ["const"] + names


def fit_timing(states, trans):
    rows = timing_rows(states, trans)
    emp = []
    for lo, hi in YS_BINS:
        sub = [r for r in rows if lo <= r["ys"] < hi]
        if sub:
            emp.append({"years_since_update": f"{lo}-{hi}" if hi < 99 else f"{lo}+", "n_intervals": len(sub),
                        "update_rate_per_interval": rnd(np.mean([r["y"] for r in sub])),
                        "update_rate_per_year": rnd(sum(r["y"] for r in sub) / sum(r["years"] for r in sub))})
    by_rel = []
    for v in VERS[1:]:
        sub = [r for r in rows if r["rel"] == v]
        if sub:
            by_rel.append({"release": v, "n": len(sub), "share_updated": rnd(np.mean([r["y"] for r in sub]))})

    def fit(rr):
        X, names = timing_design(rr)
        y = np.array([r["y"] for r in rr])
        off = np.log(np.array([r["years"] for r in rr]))
        fam = sm.families.Binomial(link=sm.families.links.CLogLog())
        return sm.GLM(y, X, family=fam, offset=off).fit(), names

    cut = REL_INDEX["23.0"]
    tr = [r for r in rows if REL_INDEX[r["rel"]] <= cut]
    te = [r for r in rows if REL_INDEX[r["rel"]] > cut]
    m_tr, names = fit(tr)
    Xte, _ = timing_design(te)
    pte = m_tr.predict(Xte, offset=np.log(np.array([r["years"] for r in te])))
    yte = np.array([r["y"] for r in te])
    m_all, _ = fit(rows)
    return m_all, names, {
        "unit": "lineage x release interval (tasks present at both ends)",
        "model": "discrete-time hazard, binomial GLM with complementary log-log link and log(interval years) offset",
        "n_intervals": len(rows), "n_updates": int(sum(r["y"] for r in rows)),
        "empirical_by_years_since_update": emp, "share_updated_by_release": by_rel,
        "temporal_check": {"train_releases": f"14.0-{VERS[cut]}", "test_releases": f"{VERS[cut + 1]}-{LATEST}",
                           "auc": rnd(roc_auc_score(yte, pte)), "ap": rnd(average_precision_score(yte, pte)),
                           "base_rate": rnd(yte.mean()), "mean_pred": rnd(pte.mean())},
        "coefficients": {n: {"coef": rnd(c), "se": rnd(s)} for n, c, s in zip(names, m_all.params, m_all.bse)},
    }


def p_update_within(model, st, horizon):
    ys = release_year(LATEST) - st["task_date"] if st["task_date"] else 0.0
    r = {"ys": ys, "jz": st["job_zone"], "src": st["task_source"] or ""}
    X, _ = timing_design([r])
    eta = float((X @ np.asarray(model.params))[0])
    return 1 - math.exp(-math.exp(eta) * horizon)


# ---------------------------------------------------------------------------
def main() -> int:
    rng = np.random.default_rng(SEED)
    states, trans, gwa, aei = load_panel()
    origins_task = list(range(REL_INDEX["14.0"], len(VERS)))
    origins_tech = list(range(REL_INDEX["22.0"], len(VERS)))
    task_rows, task_cens = make_rows("task", states, trans, gwa, aei, origins_task)
    tech_rows, tech_cens = make_rows("tech", states, trans, gwa, aei, origins_tech)
    print(f"task rows {len(task_rows)} censored {task_cens}; tech rows {len(tech_rows)} censored {tech_cens}")

    report = {"protocol": PROTOCOL["version"], "target_quantile": PROTOCOL["target_quantile"]}
    for kind, rows, cens, origins in (("task", task_rows, task_cens, PROTOCOL["task_test_origins"]),
                                      ("tech", tech_rows, tech_cens, PROTOCOL["tech_test_origins"])):
        bt = run_backtest(kind, rows, origins, rng)
        bt["n_labeled_rows"] = len(rows)
        bt["n_unique_label_events"] = len({(r["lineage_id"], r["event_idx"]) for r in rows})
        bt["censored_rows"] = cens
        thr_all = threshold_from(rows)
        bt["final_threshold_all_labels"] = rnd(thr_all)
        bt["share_events_above_final_threshold"] = rnd(np.mean([v > thr_all for v in
                                                               {(r['lineage_id'], r['event_idx']): r['y_value']
                                                                for r in rows}.values()]))
        bt["importance_final_fit"] = importance(rows, thr_all)
        report[kind] = bt
        pm = bt["pooled"]
        print(kind, {k: (v.get("auc"), v.get("ap"), v.get("brier")) for k, v in pm.items()})

    timing_model, tnames, timing = fit_timing(states, trans)
    dump_json(timing, ART / "timing_model.json")
    print("timing temporal check", timing["temporal_check"])

    # ---------- final fits and predictions at the latest release ----------
    names = feature_names(False)
    latest_o = REL_INDEX[LATEST]
    pred_rows = []
    cur = []
    for lid in sorted(states):
        f = features_at(lid, latest_o, states, trans, gwa, aei)
        if f is not None:
            cur.append({"lineage_id": lid, "origin": latest_o, "event_idx": None, "y_value": None,
                        "code": states[lid][LATEST]["code"], "feat": f})
    Xc, Sc = to_matrix(cur, names)
    out = {r["lineage_id"]: {} for r in cur}
    for kind, rows in (("task", task_rows), ("tech", tech_rows)):
        thr = threshold_from(rows)
        y = np.array([r["y_value"] > thr for r in rows], dtype=int)
        w = event_weights(rows)
        X, S = to_matrix(rows, names)
        p = Logit().fit(X, S, y, w).predict(Xc, Sc)
        a, b = recalibration(rows, latest_o, thr, names)
        report[kind]["final_recalibration"] = {"intercept": rnd(a), "slope": rnd(b)}
        p_recal = apply_recal(p, a, b) if a is not None else p
        # lineage-bootstrap ensemble for uncertainty
        lins = np.array([r["lineage_id"] for r in rows])
        ul = np.unique(lins)
        idx_by = {c: np.where(lins == c)[0] for c in ul}
        ens = []
        for _ in range(PROTOCOL["ensemble_reps"]):
            ii = np.concatenate([idx_by[c] for c in rng.choice(ul, size=len(ul), replace=True)])
            if len(set(y[ii].tolist())) < 2:
                continue
            ens.append(Logit().fit(X[ii], S[ii], y[ii], w[ii]).predict(Xc, Sc))
        ens = np.array(ens)
        lo, hi = np.quantile(ens, 0.1, axis=0), np.quantile(ens, 0.9, axis=0)
        for r, a, b, c in zip(cur, p, lo, hi):
            out[r["lineage_id"]].update({f"p_{kind}_high": float(a), f"p_{kind}_high_p10": float(b),
                                         f"p_{kind}_high_p90": float(c)})
        for r, pr in zip(cur, p_recal):
            out[r["lineage_id"]][f"p_{kind}_high_recal_posthoc"] = float(pr)
    for r in cur:
        st = states[r["lineage_id"]][LATEST]
        pred_rows.append({"lineage_id": r["lineage_id"], "code": st["code"], "title": st["title"],
                          "codes_2019": st["codes_2019"], "job_zone": st["job_zone"],
                          "years_since_task_update": r["feat"]["years_since_task_update"],
                          "p_task_update_2y": p_update_within(timing_model, st, 2.0),
                          **{k: rnd(v) for k, v in out[r["lineage_id"]].items()}})
    pq.write_table(pa.Table.from_pylist(pred_rows), ART / "predictions_latest.parquet", compression="zstd")
    report["predictions_latest"] = {"origin_release": LATEST, "n_occupations": len(pred_rows),
                                    "primary_model": "logit (pre-specified); lgbm reported as a comparison",
                                    "interval": "10th-90th percentile over a lineage-bootstrap ensemble of "
                                                f"{PROTOCOL['ensemble_reps']} refits"}
    report["leakage_prevention"] = [
        "features_at() filters transitions to releases <= origin; tests/test_job_evolution.py checks that features "
        "computed from a panel truncated at the origin equal those computed from the full panel",
        "a training row enters fold T only if origin < T and its label event was published in a release <= T "
        "(asserted per fold in leakage_checks)",
        "the 'high churn' threshold is the 67th percentile of training labels only",
        "rows sharing one label event are down-weighted to total weight 1 (no over-counting of slow updaters)",
        "AEI exposure (published 2025-2026) is excluded from the primary models and reported only as the flagged "
        "ex-post variant logit_aei_expost",
        "hyperparameters are fixed in code (no tuning on test folds); the primary model was pre-specified",
    ]
    dump_json(report, ART / "backtest_report.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
