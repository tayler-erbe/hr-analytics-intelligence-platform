"""Temporal validation, leave-institution-out U of I scoring and 2024/2025 forecasts.

    python ipeds_models/models.py            # after build_panel.py; ~5-10 minutes
    python ipeds_models/models.py --quick    # fewer folds / trees (smoke test)

Validation design (per task and horizon h in {1, 2}):
  cutoff T = last year whose data are "known"; train on origins t with t + h <= T (targets observed by T,
  features from years <= t); test on origins t = T (targets in T + h). T runs 2018..(2023 - h).
Methods: persistence (level carried forward), sector-year mean (mean target by sector [x group/rank] in the
latest training target year), repeat-last-change (reported, not a headline baseline), ridge regression
(RidgeCV, median imputation + missing indicators, standardised, target winsorised at train 1/99 pct),
LightGBM (L1 objective, deterministic). Both models get the same features, incl. peer-group context.
Intervals: temporal split conformal - refit on targets < T, take signed residual quantiles on target year T
(calibration slice), then refit on all training rows.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import features as F  # noqa: E402

ART = HERE / "artifacts"
MAN = HERE / "manifests"
SEED = 20240
UOFI = {"145637": "UIUC", "145600": "UIC", "148654": "UIS"}
HORIZONS = (1, 2)
FIRST_CUTOFF = 2018
B_BOOT = 1000
warnings.filterwarnings("ignore", category=UserWarning)


# ----------------------------------------------------------------------------- models
class RidgeModel:
    def __init__(self, task):
        self.task = task

    def fit(self, rows):
        from sklearn.impute import SimpleImputer
        from sklearn.linear_model import RidgeCV
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler
        X, self.names = F.design_matrix(rows, self.task)
        y = rows["y"].to_numpy(float)
        lo, hi = np.quantile(y, [0.01, 0.99])
        self.pipe = make_pipeline(SimpleImputer(strategy="median", add_indicator=True, keep_empty_features=True),
                                  StandardScaler(), RidgeCV(alphas=np.logspace(-2, 4, 13)))
        self.pipe.fit(X, np.clip(y, lo, hi))
        return self

    def predict_X(self, X):
        return self.pipe.predict(X)

    def predict(self, rows):
        return self.predict_X(F.design_matrix(rows, self.task)[0])


class LGBMModel:
    def __init__(self, task, n_estimators=500):
        self.task, self.n = task, n_estimators

    def fit(self, rows):
        import lightgbm as lgb
        X, self.names = F.design_matrix(rows, self.task)
        y = rows["y"].to_numpy(float)
        lo, hi = np.quantile(y, [0.01, 0.99])
        self.m = lgb.LGBMRegressor(objective="l1", n_estimators=self.n, learning_rate=0.03, num_leaves=31,
                                   min_child_samples=40, subsample=0.8, subsample_freq=1, colsample_bytree=0.8,
                                   reg_lambda=1.0, random_state=SEED, deterministic=True, force_row_wise=True,
                                   n_jobs=1, verbose=-1)  # multi-threaded OpenMP hung in the sandbox
        self.m.fit(X, np.clip(y, lo, hi))
        return self

    def predict_X(self, X):
        return self.m.predict(X)

    def predict(self, rows):
        return self.predict_X(F.design_matrix(rows, self.task)[0])


def make_model(kind, task, quick=False):
    return RidgeModel(task) if kind == "ridge" else LGBMModel(task, 150 if quick else 500)


def fit_with_intervals(kind, task, train, quick=False):
    """Temporal split conformal: calibration slice = latest target year in train."""
    last = train["target_year"].max()
    proper, calib = train[train["target_year"] < last], train[train["target_year"] == last]
    q = None
    if len(proper) >= 300 and len(calib) >= 100:
        r = calib["y"].to_numpy() - make_model(kind, task, quick).fit(proper).predict(calib)
        q = {k: float(np.quantile(r, p)) for k, p in (("q05", .05), ("q10", .10), ("q90", .90), ("q95", .95))}
    model = make_model(kind, task, quick).fit(train)
    if q is None:  # too little history: in-sample residuals (narrower than honest; flagged)
        r = train["y"].to_numpy() - model.predict(train)
        q = {k: float(np.quantile(r, p)) for k, p in (("q05", .05), ("q10", .10), ("q90", .90), ("q95", .95))}
        q["in_sample"] = True
    return model, q


def sector_year_mean(train, test):
    """Mean target by sector (x cat) among training rows with the latest target year; overall fallback."""
    last = train[train["target_year"] == train["target_year"].max()]
    m = last.groupby(["sector", "cat"])["y"].mean()
    overall = last.groupby("cat")["y"].mean()
    key = pd.MultiIndex.from_arrays([test["sector"], test["cat"]])
    p = pd.Series(m.reindex(key).to_numpy(), index=test.index)
    return p.fillna(pd.Series(overall.reindex(test["cat"]).to_numpy(), index=test.index)).fillna(last["y"].mean()).to_numpy()


def clip_rate(task, v):
    """New-hire rates cannot be negative: predictions and interval bounds are floored at 0."""
    return np.maximum(v, 0.0) if task == "newhire" else v


# ----------------------------------------------------------------------------- metrics
def cluster_boot(abs_err: dict[str, np.ndarray], units: np.ndarray, B=B_BOOT, seed=SEED) -> dict:
    """Institution-cluster bootstrap of MAE per method and of MAE differences vs baselines."""
    rng = np.random.default_rng(seed)
    uniq, inv = np.unique(units, return_inverse=True)
    sums = {k: np.bincount(inv, weights=v, minlength=len(uniq)) for k, v in abs_err.items()}
    cnt = np.bincount(inv, minlength=len(uniq)).astype(float)
    draws = rng.integers(0, len(uniq), size=(B, len(uniq)))
    w = np.zeros((B, len(uniq)))
    for b in range(B):
        w[b] = np.bincount(draws[b], minlength=len(uniq))
    n_b = w @ cnt
    mae_b = {k: (w @ s) / n_b for k, s in sums.items()}
    out = {}
    for k in abs_err:
        out[k] = {"mae": float(abs_err[k].mean()), "ci": [float(np.quantile(mae_b[k], .025)), float(np.quantile(mae_b[k], .975))]}
    for k in ("ridge", "lgbm"):
        for base in ("persistence", "sector_year_mean"):
            d = mae_b[k] - mae_b[base]
            out[f"{k}_minus_{base}"] = {"diff": float(abs_err[k].mean() - abs_err[base].mean()),
                                        "ci": [float(np.quantile(d, .025)), float(np.quantile(d, .975))],
                                        "pct": float(100 * (abs_err[k].mean() / abs_err[base].mean() - 1))}
    return out


def calibration(y, p, bins=10):
    import statsmodels.api as sm
    qs = np.unique(np.quantile(p, np.linspace(0, 1, bins + 1)))
    idx = np.clip(np.searchsorted(qs, p, side="right") - 1, 0, len(qs) - 2)
    rows = [{"pred_mean": float(p[idx == i].mean()), "actual_mean": float(y[idx == i].mean()),
             "actual_median": float(np.median(y[idx == i])), "n": int((idx == i).sum())}
            for i in range(len(qs) - 1) if (idx == i).any()]
    fit = sm.OLS(y, sm.add_constant(p)).fit(cov_type="HC1")
    return {"bins": rows, "slope": float(fit.params[1]), "slope_ci": [float(x) for x in fit.conf_int()[1]],
            "intercept": float(fit.params[0])}


def permutation_importance(model, X, y, names, rng, repeats=2):
    blocks = F.feature_blocks(names)
    base = np.abs(y - model.predict_X(X)).mean()
    out = {}
    for b, cols in blocks.items():
        inc = []
        for _ in range(repeats):
            Xp = X.copy()
            perm = rng.permutation(len(X))
            Xp[:, cols] = X[perm][:, cols]
            inc.append(np.abs(y - model.predict_X(Xp)).mean() - base)
        out[b] = float(np.mean(inc))
    return out


# ----------------------------------------------------------------------------- pipeline
def task_rows(task, h, feats, masked):
    return F.make_task(task, h, feats, masked)


def validate(task, h, rows, quick, log):
    rows_y = rows[rows["y"].notna()]
    cutoffs = list(range(FIRST_CUTOFF, 2024 - h))
    if quick:
        cutoffs = cutoffs[-2:]
    preds, imps, folds = [], {"ridge": {}, "lgbm": {}}, []
    rng = np.random.default_rng(SEED)
    for T in cutoffs:
        train = rows_y[rows_y["target_year"] <= T]
        test = rows_y[rows_y["year"] == T].copy()
        if len(test) == 0 or len(train) < 200:
            continue
        # leakage guard (also unit-tested): no training target after T, no test target at or before T
        assert train["target_year"].max() <= T < test["target_year"].min()
        test["persistence"] = test["persist"].to_numpy()
        test["sector_year_mean"] = sector_year_mean(train, test)
        test["last_change_pred"] = test["last_change"].fillna(test["persist"]).to_numpy()
        for kind in ("ridge", "lgbm"):
            model, q = fit_with_intervals(kind, task, train, quick)
            X, names = F.design_matrix(test, task)
            p = clip_rate(task, model.predict_X(X))
            test[kind] = p
            for k in ("q05", "q10", "q90", "q95"):
                test[f"{kind}_{k}"] = clip_rate(task, p + q[k])
            imp = permutation_importance(model, X, test["y"].to_numpy(), names, rng)
            for b, v in imp.items():
                imps[kind].setdefault(b, []).append((v, len(test)))
        folds.append({"cutoff": T, "n_train": int(len(train)), "n_test": int(len(test)),
                      "train_target_years": [int(train["target_year"].min()), int(train["target_year"].max())],
                      "test_target_year": int(T + h), "train_units": int(train["unitid"].nunique())})
        log(f"    {task} h={h} T={T}: train {len(train):,} test {len(test):,}")
        preds.append(test[["unitid", "year", "target_year", "cat", "sector", "carnegie_group", "y", "persistence",
                           "sector_year_mean", "last_change_pred", "ridge", "lgbm"]
                          + [f"{k}_{q}" for k in ("ridge", "lgbm") for q in ("q05", "q10", "q90", "q95")]])
    P = pd.concat(preds, ignore_index=True)
    P["task"], P["h"] = task, h
    y = P["y"].to_numpy()
    ae = {m: np.abs(y - P[m].to_numpy()) for m in ("persistence", "sector_year_mean", "last_change_pred", "ridge", "lgbm")}
    boot = cluster_boot(ae, P["unitid"].to_numpy())
    best = "lgbm" if ae["lgbm"].mean() <= ae["ridge"].mean() else "ridge"
    cov = {k: {"80": float(((y >= P[f"{k}_q10"]) & (y <= P[f"{k}_q90"])).mean()),
               "90": float(((y >= P[f"{k}_q05"]) & (y <= P[f"{k}_q95"])).mean()),
               "width80_median": float((P[f"{k}_q90"] - P[f"{k}_q10"]).median())} for k in ("ridge", "lgbm")}
    by_cat = []
    if F.TASKS[task]["stacked"]:
        for c, d in P.groupby("cat"):
            yy = d["y"].to_numpy()
            by_cat.append({"cat": c, "n": int(len(d)), **{m: float(np.abs(yy - d[m]).mean()) for m in
                                                           ("persistence", "sector_year_mean", "ridge", "lgbm")}})
    by_year = []
    for ty, d in P.groupby("target_year"):
        yy = d["y"].to_numpy()
        by_year.append({"target_year": int(ty), "n": int(len(d)), **{m: float(np.abs(yy - d[m]).mean()) for m in
                                                                      ("persistence", "sector_year_mean", "ridge", "lgbm")}})
    by_sector = []
    for s, d in P.groupby("sector"):
        yy = d["y"].to_numpy()
        by_sector.append({"sector": int(s), "n": int(len(d)), **{m: float(np.abs(yy - d[m]).mean()) for m in
                                                                  ("persistence", "sector_year_mean", "ridge", "lgbm")}})
    imp_out = {}
    for kind in ("ridge", "lgbm"):
        agg = {b: sum(v * n for v, n in lst) / sum(n for _, n in lst) for b, lst in imps[kind].items()}
        imp_out[kind] = sorted(({"feature": b, "mae_increase": round(v, 5)} for b, v in agg.items()),
                               key=lambda r: -r["mae_increase"])[:15]
    summary = {"task": task, "h": h, "n": int(len(P)), "n_units": int(P["unitid"].nunique()), "folds": folds,
               "metrics": boot, "median_ae": {m: float(np.median(v)) for m, v in ae.items()},
               "best_model": best, "coverage": cov,
               "calibration": {k: calibration(y, P[k].to_numpy()) for k in ("ridge", "lgbm")},
               "by_cat": by_cat, "by_year": by_year, "by_sector": by_sector, "importance": imp_out,
               "target_sd": float(np.std(y))}
    return summary, P


def score_uofi(task, h, rows_lio, best, quick, log):
    """Leave-institution-out: models trained on non-U-of-I institutions only (all three campuses held out,
    and kept out of every peer-context feature), temporal cutoff T, scored on U of I origin T."""
    has_y = rows_lio["y"].notna()
    out, trains = [], []
    origins = sorted(rows_lio["year"].unique())
    for T in origins:
        if T + h > 2023 and T != 2023:
            continue
        train = rows_lio[has_y & (rows_lio["target_year"] <= T) & ~rows_lio["unitid"].isin(UOFI)]
        test = rows_lio[(rows_lio["year"] == T) & rows_lio["unitid"].isin(UOFI)].copy()
        if len(train) < 1000 or len(test) == 0 or train["target_year"].nunique() < 2:
            continue
        assert not train["unitid"].isin(UOFI).any()
        model, q = fit_with_intervals(best, task, train, quick)
        p = clip_rate(task, model.predict(test))
        test["pred"] = p
        for k in ("q05", "q10", "q90", "q95"):
            test[k] = clip_rate(task, p + q[k])
        test["sector_year_mean"] = sector_year_mean(train, test)
        test["model"] = best
        test["interval_in_sample"] = bool(q.get("in_sample", False))
        trains.append({"cutoff": int(T), "n_train": int(len(train)), "train_units": int(train["unitid"].nunique()),
                       "max_train_target_year": int(train["target_year"].max())})
        out.append(test[["unitid", "year", "target_year", "cat", "y", "persist", "pred", "q05", "q10", "q90", "q95",
                         "sector_year_mean", "model", "interval_in_sample"]])
    log(f"    LIO {task} h={h}: {len(trains)} cutoffs")
    U = pd.concat(out, ignore_index=True)
    U["task"], U["h"] = task, h
    U["residual"] = U["y"] - U["pred"]
    return U, trains


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--tasks", default=",".join(F.TASKS))
    args = ap.parse_args(argv)
    t0 = time.time()
    log = lambda s: print(f"[{time.time() - t0:6.1f}s] {s}", flush=True)  # noqa: E731
    panel = pd.read_parquet(ART / "panel.parquet")
    masked = F.mask_excluded(panel)
    feats = F.build_features(masked)
    feats_lio = F.build_features(masked, context_exclude=frozenset(UOFI))
    log(f"panel {len(panel):,} institution-years, features {feats.shape}")
    results = {"tasks": {}, "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "quick": args.quick}
    all_preds, all_ui, lio_meta = [], [], {}
    for task in args.tasks.split(","):
        results["tasks"][task] = {"label": F.TASKS[task]["label"], "unit": F.TASKS[task]["unit"],
                                  "stacked": F.TASKS[task]["stacked"], "horizons": {}}
        for h in HORIZONS:
            rows = task_rows(task, h, feats, masked)
            summ, P = validate(task, h, rows, args.quick, log)
            results["tasks"][task]["horizons"][str(h)] = summ
            all_preds.append(P)
            rows_lio = task_rows(task, h, feats_lio, masked)
            U, trains = score_uofi(task, h, rows_lio, summ["best_model"], args.quick, log)
            all_ui.append(U)
            lio_meta[f"{task}_h{h}"] = trains
            m = summ["metrics"]
            log(f"  {task} h={h}: MAE persist {m['persistence']['mae']:.3f} secmean {m['sector_year_mean']['mae']:.3f} "
                f"ridge {m['ridge']['mae']:.3f} lgbm {m['lgbm']['mae']:.3f} | best {summ['best_model']}")
    P = pd.concat(all_preds, ignore_index=True)
    U = pd.concat(all_ui, ignore_index=True)
    P.to_parquet(ART / "validation_predictions.parquet", index=False)
    U.to_parquet(ART / "uofi_scores.parquet", index=False)
    results["uofi"] = json.loads(U.replace({np.nan: None}).to_json(orient="records"))
    results["lio_training"] = lio_meta
    import lightgbm, sklearn, statsmodels  # noqa: E401
    (ART / "results.json").write_text(json.dumps(results, separators=(",", ":"), default=float))
    MAN.mkdir(exist_ok=True)
    (MAN / "model_manifest.json").write_text(json.dumps({
        "run_at_utc": results["generated_utc"], "seed": SEED, "quick": args.quick, "bootstrap_reps": B_BOOT,
        "panel_sha256": sha(ART / "panel.parquet"),
        "versions": {"python": sys.version.split()[0], "numpy": np.__version__, "pandas": pd.__version__,
                     "scikit-learn": sklearn.__version__, "lightgbm": lightgbm.__version__,
                     "statsmodels": statsmodels.__version__},
        "validation_predictions_rows": int(len(P)), "uofi_rows": int(len(U)),
        "runtime_seconds": round(time.time() - t0, 1)}, indent=1) + "\n")
    log("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
