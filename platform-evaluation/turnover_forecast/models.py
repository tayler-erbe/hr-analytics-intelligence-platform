"""Forecasters and metrics.

Every forecaster works on the log of a strictly positive series and returns, for horizons
1..H, a point forecast on the original scale plus (where the method has one) its own
prediction interval. Global models (pooled ridge, LightGBM) are trained on all 14 states.

All functions take data already truncated at the origin T; nothing here reads later quarters.
"""
from __future__ import annotations

import math
import warnings

import numpy as np

from series import Data, covariates, is_covid, target, _roll_mean

H = 8
Z = {80: 1.2815515655446004, 95: 1.959963984540054}
COV_FEATURES = ["share55", "share55_d4", "share65", "tot_emp_yoy", "tot_hire_rate_4q",
                "tot_hire_rate_4q_d4", "tot_sep_rate_4q", "hosp_sep_rate_4q", "k12_sep_rate_4q", "he_emp_yoy"]


# ----------------------------------------------------------------------------------- metrics
def smape(y, f) -> np.ndarray:
    y, f = np.asarray(y, float), np.asarray(f, float)
    return 200.0 * np.abs(y - f) / (np.abs(y) + np.abs(f))


def mase_scale(y_train: np.ndarray, m: int = 4) -> float:
    """In-sample mean absolute seasonal-naive (lag m) error over the training series."""
    y = np.asarray(y_train, float)
    d = np.abs(y[m:] - y[:-m])
    d = d[~np.isnan(d)]
    return float(d.mean()) if d.size else float("nan")


def mase(y, f, scale) -> np.ndarray:
    return np.abs(np.asarray(y, float) - np.asarray(f, float)) / np.asarray(scale, float)


def coverage(y, lo, hi) -> float:
    y, lo, hi = (np.asarray(a, float) for a in (y, lo, hi))
    ok = ~(np.isnan(y) | np.isnan(lo) | np.isnan(hi))
    return float(np.mean((y[ok] >= lo[ok]) & (y[ok] <= hi[ok]))) if ok.any() else float("nan")


def dm_test(loss_a: np.ndarray, loss_b: np.ndarray, h: int) -> tuple[float, float]:
    """Diebold-Mariano test of equal expected loss, Newey-West variance with h-1 lags and the
    Harvey-Leybourne-Newbold small-sample correction. Returns (statistic, two-sided p) using a
    normal reference; negative statistic means model a has lower loss."""
    d = np.asarray(loss_a, float) - np.asarray(loss_b, float)
    d = d[~np.isnan(d)]
    n = d.size
    if n < 8:
        return float("nan"), float("nan")
    dc = d - d.mean()
    v = dc @ dc / n
    for k in range(1, h):
        w = 1 - k / h
        v += 2 * w * (dc[k:] @ dc[:-k]) / n
    if v <= 0:
        return float("nan"), float("nan")
    stat = d.mean() / math.sqrt(v / n)
    stat *= math.sqrt((n + 1 - 2 * h + h * (h - 1) / n) / n)
    p = math.erfc(abs(stat) / math.sqrt(2))
    return float(stat), float(p)


# ------------------------------------------------------------------------- univariate models
def _tail(y: np.ndarray, T: int) -> np.ndarray:
    """Contiguous non-missing history ending at T (empty if y[T] is missing)."""
    if np.isnan(y[T]) or y[T] <= 0:
        return np.array([])
    s = T
    while s - 1 >= 0 and not np.isnan(y[s - 1]) and y[s - 1] > 0:
        s -= 1
    return y[s: T + 1]


def seasonal_naive(y: np.ndarray, T: int) -> dict:
    hist = _tail(y, T)
    if hist.size < 9:
        return {}
    ly = np.log(hist)
    sd = np.nanstd(ly[4:] - ly[:-4], ddof=1)
    out = {"point": [], "lo80": [], "hi80": [], "lo95": [], "hi95": []}
    for h in range(1, H + 1):
        k = math.ceil(h / 4)
        base = ly[len(ly) - 1 + h - 4 * k]
        out["point"].append(float(hist[len(hist) - 1 + h - 4 * k]))  # exact value, no log round-trip
        for c in (80, 95):
            out[f"lo{c}"].append(math.exp(base - Z[c] * sd * math.sqrt(k)))
            out[f"hi{c}"].append(math.exp(base + Z[c] * sd * math.sqrt(k)))
    return out


def ets(y: np.ndarray, T: int) -> dict:
    from statsmodels.tsa.exponential_smoothing.ets import ETSModel
    hist = _tail(y, T)
    if hist.size < 16:
        return {}
    import pandas as pd  # statsmodels' ETS prediction intervals need an indexed series
    ly = pd.Series(np.log(hist))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        m = ETSModel(ly, error="add", trend="add", damped_trend=True, seasonal="add",
                     seasonal_periods=4).fit(disp=False, maxiter=2000)
        out = {"point": list(np.exp(m.forecast(H).to_numpy()))}
        for c in (80, 95):
            fr = m.get_prediction(start=len(ly), end=len(ly) + H - 1).summary_frame(alpha=1 - c / 100)
            out[f"lo{c}"] = list(np.exp(fr["pi_lower"].to_numpy()))
            out[f"hi{c}"] = list(np.exp(fr["pi_upper"].to_numpy()))
    return out


def arima(y: np.ndarray, T: int) -> dict:
    """Fixed-specification seasonal ARIMA(1,0,1)(0,1,1)_4 with drift on log y (not auto-selected)."""
    from statsmodels.tsa.statespace.sarimax import SARIMAX
    hist = _tail(y, T)
    if hist.size < 16:
        return {}
    ly = np.log(hist)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        m = SARIMAX(ly, order=(1, 0, 1), seasonal_order=(0, 1, 1, 4), trend="c").fit(disp=False, maxiter=200)
        fc = m.get_forecast(H)
        out = {"point": list(np.exp(fc.predicted_mean))}
        for c in (80, 95):
            ci = fc.conf_int(alpha=1 - c / 100)
            out[f"lo{c}"] = list(np.exp(ci[:, 0]))
            out[f"hi{c}"] = list(np.exp(ci[:, 1]))
    return out


# ------------------------------------------------------------------------------ global models
def design(d: Data, name: str, T: int) -> dict:
    """Training rows (state i, origin s, horizon h) with s + h <= T and prediction rows at origin T.

    Target: log(y[s+h]) - log(mean(y[s-3..s])). Features are dated at s or earlier.
    `covid_target` marks training targets in the COVID window; it is always 0 for prediction rows,
    because a forecaster at T cannot know a shock is coming.
    """
    Y = target(d, name)[:, : T + 1]
    with np.errstate(invalid="ignore", divide="ignore"):
        lY = np.log(np.where(Y > 0, Y, np.nan))
        lL = np.log(_roll_mean(Y, 4))
    cov = {k: v[:, : T + 1] for k, v in covariates(d).items()}
    n_s, n_q = Y.shape
    rows, preds = [], []
    for h in range(1, H + 1):
        k = math.ceil(h / 4)
        for s in range(12, n_q):
            tq = s + h
            for i in range(n_s):
                base = lL[i, s]
                feats = [h, (tq % 4), i,
                         lY[i, s] - base, base - lL[i, s - 4], base - lL[i, s - 8],
                         lY[i, s + h - 4 * k] - base, lY[i, s + h - 4 * k - 4] - lL[i, s - 4],
                         float(any(is_covid(s - j) for j in range(4)))] + [cov[c][i, s] for c in COV_FEATURES]
                if np.isnan(feats).any():
                    continue
                if tq <= T:
                    yv = lY[i, tq] - base
                    if not np.isnan(yv):
                        rows.append(feats + [float(is_covid(tq)), yv])
                elif s == T:
                    preds.append(feats + [0.0, base])
    names = ["h", "tq_mod4", "state", "last_rel", "trend4", "trend8", "seas_last_rel", "seas_prev_rel",
             "origin_covid"] + COV_FEATURES + ["covid_target"]
    tr = np.array(rows) if rows else np.empty((0, len(names) + 1))
    pr = np.array(preds) if preds else np.empty((0, len(names) + 1))
    return {"names": names, "X": tr[:, :-1], "y": tr[:, -1], "Xp": pr[:, :-1], "base_p": pr[:, -1]}


def _numeric_block(X: np.ndarray, names: list[str]) -> np.ndarray:
    """Quarter-of-target and state one-hots plus the numeric features (state one-hot -> intercepts)."""
    tq = X[:, names.index("tq_mod4")].astype(int)
    st = X[:, names.index("state")].astype(int)
    keep = [j for j, n in enumerate(names) if n not in ("h", "tq_mod4", "state")]
    return np.column_stack([np.eye(4)[tq], np.eye(14)[st], X[:, keep]])


def pooled_ridge(des: dict, state_idx: int = 0) -> dict:
    """Per-horizon ridge regression across all states (state intercepts shrunk toward a common
    intercept, i.e. the MAP estimate of a random-intercept model with one variance ratio)."""
    from sklearn.linear_model import RidgeCV
    from sklearn.preprocessing import StandardScaler
    names, X, y, Xp, bp = des["names"], des["X"], des["y"], des["Xp"], des["base_p"]
    hcol = names.index("h")
    out = {"point": [np.nan] * H}
    for h in range(1, H + 1):
        tr = X[:, hcol] == h
        pm = (Xp[:, hcol] == h) & (Xp[:, names.index("state")] == state_idx)
        if tr.sum() < 40 or not pm.any():
            continue
        A, Ap = _numeric_block(X[tr], names), _numeric_block(Xp[pm], names)
        sc = StandardScaler().fit(A)
        sd = sc.scale_.copy()
        sd[sd == 0] = 1.0
        sc.scale_ = sd
        m = RidgeCV(alphas=np.logspace(-2, 3, 11)).fit(sc.transform(A), y[tr])
        out["point"][h - 1] = float(np.exp(bp[pm][0] + m.predict(sc.transform(Ap))[0]))
    return out


def gbm(des: dict, state_idx: int = 0, seed: int = 7) -> dict:
    """One LightGBM model over all states and horizons (horizon, quarter and state as features)."""
    import lightgbm as lgb
    names, X, y, Xp, bp = des["names"], des["X"], des["y"], des["Xp"], des["base_p"]
    out = {"point": [np.nan] * H}
    if len(y) < 200:
        return out
    m = lgb.LGBMRegressor(n_estimators=300, learning_rate=0.03, num_leaves=15, min_child_samples=20,
                          subsample=0.8, subsample_freq=1, colsample_bytree=0.8, reg_lambda=1.0,
                          random_state=seed, deterministic=True, force_row_wise=True, n_jobs=1, verbose=-1)
    cat = [names.index("state"), names.index("tq_mod4")]
    m.fit(X, y, categorical_feature=cat)
    pm = Xp[:, names.index("state")] == state_idx
    for row, b in zip(Xp[pm], bp[pm]):
        out["point"][int(row[0]) - 1] = float(np.exp(b + m.predict(row[None, :])[0]))
    return out
