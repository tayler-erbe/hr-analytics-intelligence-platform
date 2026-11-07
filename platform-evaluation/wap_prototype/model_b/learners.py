"""The five Model B learners of protocol 3.3, on a truncated Panel.

Every learner works on log(1 + y) (counts can be zero) and returns, per series index, a point forecast on the
count scale for horizons 1..H plus, where the method has one, its native interval. Nothing here reads a
quarter after the origin T: callers pass `series.truncate(panel, T)` and the design matrix uses only columns
<= T (the test suite perturbs the future and checks that forecasts are unchanged).

  B-snaive   same quarter last year (the MASE reference); native interval from lag-4 log differences
  B-ets      ETS additive damped trend, additive seasonality, on log(1+y); native statsmodels interval
  B-pooled   one ridge regression per horizon across all modelled series, target
             log((y[T+h]+1) / (mean of last 4 quarters + 1)), series intercepts shrunk to a common intercept
             by the ridge penalty, with unit age-structure and external covariates dated at T or earlier
  B-gbm      LightGBM on the same rows with horizon, series and quarter as features, fixed seed, deterministic
  B-ens      equal-weight geometric mean of B-ets, B-pooled, B-gbm on the 1+y scale (weights fixed a priori)

COVID handling as in turnover_forecast: `covid_target` marks training targets in 2020Q1..2021Q2 and is always 0
on prediction rows; `origin_covid` (origin inside the window) is a legitimate forecast-time feature. The
synthetic v3 data carries no COVID shock, so these columns are constant-free of signal here but the mechanism is
kept so the real-data run needs no code change.
"""
from __future__ import annotations

import math
import sys
import warnings
from pathlib import Path

import numpy as np

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from wap_prototype.model_b import config as C  # noqa: E402
from wap_prototype.model_b.series import Panel, is_covid  # noqa: E402

H = C.H
Z = {80: 1.2815515655446004, 95: 1.959963984540054}
COV_FEATURES = C.UNIT_COVARIATES + C.EXTERNAL_COVARIATES
DESIGN_NAMES = ["h", "tq_mod4", "series", "last_rel", "trend4", "trend8", "seas_last_rel", "seas_prev_rel",
                "origin_covid"] + COV_FEATURES + ["covid_target"]


def _tail(y: np.ndarray, T: int) -> np.ndarray:
    """Contiguous non-missing history ending at T (empty when y[T] is missing)."""
    if T >= len(y) or np.isnan(y[T]):
        return np.array([])
    s = T
    while s - 1 >= 0 and not np.isnan(y[s - 1]):
        s -= 1
    return y[s: T + 1]


def _empty() -> dict:
    return {"point": [np.nan] * H}


# ------------------------------------------------------------------------------------------- univariate
def seasonal_naive(y: np.ndarray, T: int) -> dict:
    hist = _tail(y, T)
    if hist.size < 5:
        return _empty()
    ly = np.log1p(hist)
    d = ly[4:] - ly[:-4]
    sd = float(np.std(d, ddof=1)) if d.size >= 2 else float("nan")
    out = {"point": [], "lo80": [], "hi80": [], "lo95": [], "hi95": []}
    n = len(hist)
    for h in range(1, H + 1):
        k = math.ceil(h / 4)
        j = n - 1 + h - 4 * k
        out["point"].append(float(hist[j]))
        for c in (80, 95):
            out[f"lo{c}"].append(float(np.expm1(ly[j] - Z[c] * sd * math.sqrt(k))) if not np.isnan(sd) else np.nan)
            out[f"hi{c}"].append(float(np.expm1(ly[j] + Z[c] * sd * math.sqrt(k))) if not np.isnan(sd) else np.nan)
    return out


def ets(y: np.ndarray, T: int) -> dict:
    hist = _tail(y, T)
    if hist.size < C.ETS_MIN_POINTS:
        return _empty()
    import pandas as pd
    from statsmodels.tsa.exponential_smoothing.ets import ETSModel
    ly = pd.Series(np.log1p(hist))
    if float(np.std(ly)) == 0.0:   # a constant series: ETS cannot be fitted, the constant is the forecast
        return {"point": [float(hist[-1])] * H, **{f"{s}{c}": [float(hist[-1])] * H for s in ("lo", "hi") for c in (80, 95)}}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        m = ETSModel(ly, **C.ETS_SPEC).fit(disp=False, maxiter=2000)
        out = {"point": [float(v) for v in np.expm1(m.forecast(H).to_numpy())]}
        for c in (80, 95):
            fr = m.get_prediction(start=len(ly), end=len(ly) + H - 1).summary_frame(alpha=1 - c / 100)
            out[f"lo{c}"] = [float(v) for v in np.maximum(np.expm1(fr["pi_lower"].to_numpy()), 0.0)]
            out[f"hi{c}"] = [float(v) for v in np.expm1(fr["pi_upper"].to_numpy())]
    return out


# ------------------------------------------------------------------------------------------- global
def _roll_mean(a: np.ndarray, w: int) -> np.ndarray:
    out = np.full_like(a, np.nan)
    for t in range(w - 1, a.shape[1]):
        out[:, t] = a[:, t - w + 1: t + 1].mean(axis=1)
    return out


def design(p: Panel, target: str, T: int, series_mask: np.ndarray | None = None) -> dict:
    """Training rows (series i, origin s, horizon h) with s + h <= T and prediction rows at origin T.
    Target: log1p(y[s+h]) - log1p(mean(y[s-3..s])). Every feature is dated at s or earlier."""
    Y = p.y[target][:, : T + 1]
    lY = np.log1p(Y)
    lL = np.log1p(_roll_mean(Y, 4))
    cov = {k: p.cov[k][:, : T + 1] for k in COV_FEATURES}
    n_s, n_q = Y.shape
    mask = np.ones(n_s, bool) if series_mask is None else series_mask
    rows, preds = [], []
    for h in range(1, H + 1):
        k = math.ceil(h / 4)
        for s in range(11, n_q):
            tq = s + h
            if tq > T and s != T:
                continue
            for i in np.where(mask)[0]:
                base = lL[i, s]
                core = [lY[i, s] - base, base - lL[i, s - 4], base - lL[i, s - 8],
                        lY[i, s + h - 4 * k] - base, lY[i, s + h - 4 * k - 4] - lL[i, s - 4]]
                if np.isnan(core).any():
                    continue
                feats = [h, (tq % 4), i] + core + [float(any(is_covid(p, s - j) for j in range(4) if s - j >= 0))] + \
                        [cov[c][i, s] for c in COV_FEATURES]
                if tq <= T:
                    yv = lY[i, tq] - base
                    if not np.isnan(yv):
                        rows.append(feats + [float(is_covid(p, tq)), yv])
                else:
                    preds.append(feats + [0.0, base])
    w = len(DESIGN_NAMES) + 1
    tr = np.array(rows, float) if rows else np.empty((0, w))
    pr = np.array(preds, float) if preds else np.empty((0, w))
    return {"names": DESIGN_NAMES, "X": tr[:, :-1], "y": tr[:, -1], "Xp": pr[:, :-1], "base_p": pr[:, -1], "n_series": n_s}


def _numeric_block(X: np.ndarray, n_series: int, col_means: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Quarter and series one-hots plus the numeric features; NaN covariates imputed with training column means."""
    names = DESIGN_NAMES
    tq = X[:, names.index("tq_mod4")].astype(int)
    st = X[:, names.index("series")].astype(int)
    keep = [j for j, n in enumerate(names) if n not in ("h", "tq_mod4", "series")]
    num = X[:, keep].copy()
    if col_means is None:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            col_means = np.nanmean(num, axis=0)
        col_means = np.where(np.isnan(col_means), 0.0, col_means)
    num = np.where(np.isnan(num), col_means, num)
    return np.column_stack([np.eye(4)[tq], np.eye(n_series)[st], num]), col_means


def pooled_ridge(des: dict) -> dict[int, dict]:
    """Per-horizon ridge across all series. Series one-hots are penalised like every other column, which is the
    MAP estimate of a random-intercept model shrinking each series intercept to the common intercept."""
    from sklearn.linear_model import RidgeCV
    from sklearn.preprocessing import StandardScaler
    names, X, y, Xp, bp = des["names"], des["X"], des["y"], des["Xp"], des["base_p"]
    hcol, scol = names.index("h"), names.index("series")
    out: dict[int, dict] = {int(i): _empty() for i in np.unique(Xp[:, scol])} if len(Xp) else {}
    for h in range(1, H + 1):
        tr = X[:, hcol] == h
        pm = Xp[:, hcol] == h
        if tr.sum() < C.RIDGE_MIN_ROWS or not pm.any():
            continue
        A, means = _numeric_block(X[tr], des["n_series"])
        Ap, _ = _numeric_block(Xp[pm], des["n_series"], means)
        sc = StandardScaler().fit(A)
        sd = sc.scale_.copy(); sd[sd == 0] = 1.0; sc.scale_ = sd
        m = RidgeCV(alphas=np.array(C.RIDGE_ALPHAS)).fit(sc.transform(A), y[tr])
        pred = m.predict(sc.transform(Ap))
        for row, b, pv in zip(Xp[pm], bp[pm], pred):
            out[int(row[scol])]["point"][h - 1] = float(max(np.expm1(b + pv), 0.0))
    return out


def gbm(des: dict, seed: int = C.SEED) -> dict[int, dict]:
    import lightgbm as lgb
    names, X, y, Xp, bp = des["names"], des["X"], des["y"], des["Xp"], des["base_p"]
    scol = names.index("series")
    out: dict[int, dict] = {int(i): _empty() for i in np.unique(Xp[:, scol])} if len(Xp) else {}
    if len(y) < C.GBM_MIN_ROWS or not len(Xp):
        return out
    m = lgb.LGBMRegressor(random_state=seed, **C.GBM_PARAMS)
    cat = [scol, names.index("tq_mod4")]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        m.fit(X, y, categorical_feature=cat)
        pred = m.predict(Xp)
    for row, b, pv in zip(Xp, bp, pred):
        out[int(row[scol])]["point"][int(row[0]) - 1] = float(max(np.expm1(b + pv), 0.0))
    return out


def ensemble(parts: list[dict]) -> dict:
    """Equal-weight geometric mean on the 1+y scale; missing when any member is missing (common-set scoring)."""
    pts = np.array([q["point"] for q in parts], float)
    if np.isnan(pts).any():
        res = np.full(H, np.nan)
        ok = ~np.isnan(pts).any(axis=0)
        res[ok] = np.expm1(np.mean(np.log1p(pts[:, ok]), axis=0))
        return {"point": [float(v) for v in res]}
    return {"point": [float(v) for v in np.expm1(np.mean(np.log1p(pts), axis=0))]}


# ------------------------------------------------------------------------------------------- driver
def forecast_at(p: Panel, target: str, T: int, series_idx: list[int] | None = None) -> dict[str, dict[int, dict]]:
    """All five learners for every modelled series at origin T on an already-truncated panel.
    Returns {method: {series_index: {"point": [...], "lo80": ..}}}."""
    idx = series_idx if series_idx is not None else [int(i) for i in np.where(p.registry["modelled"].to_numpy())[0]]
    mask = np.zeros(p.n_series, bool); mask[idx] = True
    out: dict[str, dict[int, dict]] = {m: {} for m in C.METHODS}
    for i in idx:
        y = p.y[target][i]
        out["B-snaive"][i] = seasonal_naive(y, T)
        try:
            out["B-ets"][i] = ets(y, T)
        except Exception:  # noqa: BLE001  a failed fit is recorded as missing, never hidden
            out["B-ets"][i] = _empty()
    des = design(p, target, T, mask)
    pr, gb = pooled_ridge(des), gbm(des)
    for i in idx:
        out["B-pooled"][i] = pr.get(i, _empty())
        out["B-gbm"][i] = gb.get(i, _empty())
        out["B-ens"][i] = ensemble([out[m][i] for m in C.ENSEMBLE_OF])
    return out
