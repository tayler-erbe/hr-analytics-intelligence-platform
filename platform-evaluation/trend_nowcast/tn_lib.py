"""Pure statistical helpers for the trend-to-reality nowcast (no I/O).

Conventions
-----------
* A quarter is an int key ``year * 4 + (q - 1)``; ``qlabel`` turns it into "2024Q3".
* Series are dicts ``{quarter_key: float}``; missing quarters are simply absent.
* Growth is in log points (0.01 = about 1%).
"""
from __future__ import annotations

import math
from typing import Iterable

import numpy as np
from scipy import stats

COVID_FIT_EXCLUDE = None  # set below once qkey exists


def qkey(year: int, q: int) -> int:
    return int(year) * 4 + int(q) - 1


def qlabel(k: int) -> str:
    return f"{k // 4}Q{k % 4 + 1}"


def qparse(label: str) -> int:
    y, q = label.split("Q")
    return qkey(int(y), int(q))


def qtr_of(k: int) -> int:
    return k % 4 + 1


COVID_FIT_EXCLUDE = set(range(qkey(2020, 2), qkey(2021, 2) + 1))  # 2020Q2-2021Q2


# ----------------------------------------------------------------------------- transforms
def log_series(s: dict[int, float]) -> dict[int, float]:
    return {k: math.log(v) for k, v in s.items() if v is not None and v > 0}


def diff(s: dict[int, float], lag: int = 1) -> dict[int, float]:
    """s_t - s_{t-lag} where both exist."""
    return {k: s[k] - s[k - lag] for k in s if (k - lag) in s}


def yoy(s: dict[int, float]) -> dict[int, float]:
    """Year-over-year log growth (seasonal difference of logs)."""
    return diff(log_series(s), 4)


def deseasonalize_by_quarter(s: dict[int, float], fit_keys: Iterable[int] | None = None) -> dict[int, float]:
    """Subtract quarter-of-year means (estimated on fit_keys, default all keys).

    Applied to a first difference, this removes deterministic seasonality: it is the
    same as putting quarter dummies in a regression.
    """
    keys = list(s) if fit_keys is None else [k for k in fit_keys if k in s]
    means = {}
    for q in (1, 2, 3, 4):
        vals = [s[k] for k in keys if qtr_of(k) == q]
        means[q] = float(np.mean(vals)) if vals else 0.0
    return {k: v - means[qtr_of(k)] for k, v in s.items()}


def align(*series: dict[int, float], keys: Iterable[int] | None = None) -> tuple[list[int], list[np.ndarray]]:
    common = set(series[0])
    for s in series[1:]:
        common &= set(s)
    if keys is not None:
        common &= set(keys)
    ks = sorted(common)
    return ks, [np.array([s[k] for k in ks], dtype=float) for s in series]


# ----------------------------------------------------------------------------- OLS
def ols(y: np.ndarray, X: np.ndarray) -> tuple[np.ndarray, float]:
    """Least-squares coefficients and residual sum of squares."""
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    return beta, float(resid @ resid)


def seasonal_dummies(keys: list[int]) -> np.ndarray:
    """Three quarter dummies (Q2, Q3, Q4); Q1 is the base."""
    return np.array([[1.0 if qtr_of(k) == q else 0.0 for q in (2, 3, 4)] for k in keys])


# ----------------------------------------------------------------------------- lead-lag
def prewhitened_ccf(x: dict[int, float], y: dict[int, float], lags: Iterable[int], ar_order: int = 1) -> dict:
    """Box-Jenkins prewhitened cross-correlation.

    Fit AR(p) to x, filter both x and y with it, and correlate the filtered series.
    Lag k > 0 means x leads y by k quarters: corr(x_{t-k}, y_t).
    Returns {"n": ..., "band": 1.96/sqrt(n), "ccf": {k: r}}.
    """
    ks, (xv,) = align(x)
    xs = {k: v for k, v in zip(ks, xv)}
    # AR(p) on x using consecutive quarters only
    rows = [k for k in ks if all((k - i) in xs for i in range(1, ar_order + 1))]
    if len(rows) < ar_order + 5:
        return {"n": 0, "band": None, "ccf": {}}
    X = np.column_stack([np.ones(len(rows))] + [[xs[k - i] for k in rows] for i in range(1, ar_order + 1)])
    phi, _ = ols(np.array([xs[k] for k in rows]), X)

    def filt(s):
        return {k: s[k] - phi[0] - sum(phi[i] * s[k - i] for i in range(1, ar_order + 1))
                for k in s if all((k - i) in s for i in range(1, ar_order + 1))}

    fx, fy = filt(x), filt(y)
    out, ns = {}, []
    for lag in lags:
        pairs = [(fx[k - lag], fy[k]) for k in fy if (k - lag) in fx]
        if len(pairs) >= 8:
            a = np.array(pairs)
            out[lag] = float(np.corrcoef(a[:, 0], a[:, 1])[0, 1])
            ns.append(len(pairs))
    n = min(ns) if ns else 0
    return {"n": n, "band": 1.96 / math.sqrt(n) if n else None, "ccf": out, "ar_coef": [float(c) for c in phi]}


def granger_test(y: dict[int, float], x: dict[int, float], p: int, keys: Iterable[int] | None = None) -> dict | None:
    """F-test that p lags of x add to p own lags of y, a constant and quarter dummies.

    y and x should already be stationary (e.g. first differences of logs). Returns None
    if there are too few observations (residual df < 5).
    """
    allowed = set(keys) if keys is not None else None
    rows = [k for k in sorted(y) if all((k - i) in y and (k - i) in x for i in range(1, p + 1))
            and (allowed is None or k in allowed)]
    n = len(rows)
    k_full = 1 + 3 + 2 * p
    if n - k_full < 5:
        return None
    yv = np.array([y[k] for k in rows])
    base = np.column_stack([np.ones(n), seasonal_dummies(rows)] + [[y[k - i] for k in rows] for i in range(1, p + 1)])
    full = np.column_stack([base] + [[x[k - i] for k in rows] for i in range(1, p + 1)])
    b_full, ssr_u = ols(yv, full)
    _, ssr_r = ols(yv, base)
    df2 = n - k_full
    F = ((ssr_r - ssr_u) / p) / (ssr_u / df2) if ssr_u > 0 else float("inf")
    pval = float(stats.f.sf(F, p, df2))
    return {"n": n, "p": p, "df_resid": df2, "F": float(F), "pvalue": pval,
            "x_coef_sum": float(sum(b_full[-p:])), "first": qlabel(rows[0]), "last": qlabel(rows[-1])}


def bh_qvalues(pvals: list[float]) -> list[float]:
    """Benjamini-Hochberg adjusted p-values (q-values), same order as input."""
    m = len(pvals)
    if m == 0:
        return []
    order = sorted(range(m), key=lambda i: pvals[i])
    q = [0.0] * m
    running = 1.0
    for rank in range(m, 0, -1):
        i = order[rank - 1]
        running = min(running, pvals[i] * m / rank)
        q[i] = running
    return q


def adf_pvalue(values: np.ndarray) -> float | None:
    """Augmented Dickey-Fuller p-value (constant, 1 lag). Low power with n < 30."""
    from statsmodels.tsa.stattools import adfuller
    if len(values) < 12:
        return None
    try:
        return float(adfuller(values, maxlag=1, autolag=None, regression="c", result_object=False)[1])
    except Exception:  # noqa: BLE001 - degenerate series
        return None


# ----------------------------------------------------------------------------- forecasting
def dm_test(e_model: np.ndarray, e_base: np.ndarray, h: int) -> dict:
    """Diebold-Mariano test on squared error with the Harvey et al. (1997) small-sample fix.

    Negative statistic means the model has lower squared error than the baseline.
    Two-sided p-value from Student t with n-1 df.
    """
    d = e_model ** 2 - e_base ** 2
    n = len(d)
    if n < 4:
        return {"stat": None, "pvalue": None, "n": n}
    dbar = d.mean()
    gamma0 = np.mean((d - dbar) ** 2)
    lrv = gamma0 + 2 * sum(np.mean((d[k:] - dbar) * (d[:-k] - dbar)) for k in range(1, h))
    if lrv <= 0:
        return {"stat": None, "pvalue": None, "n": n}
    stat = dbar / math.sqrt(lrv / n)
    stat *= math.sqrt((n + 1 - 2 * h + h * (h - 1) / n) / n)
    return {"stat": float(stat), "pvalue": float(2 * stats.t.sf(abs(stat), n - 1)), "n": n}


def fit_predict_linear(train_X: np.ndarray, train_y: np.ndarray, x_new: np.ndarray) -> float:
    X = np.column_stack([np.ones(len(train_y)), train_X])
    beta, _ = ols(train_y, X)
    return float(beta[0] + x_new @ beta[1:])


def fit_predict_ridge(train_X: np.ndarray, train_y: np.ndarray, x_new: np.ndarray) -> float:
    """Ridge with alpha chosen by leave-one-out CV on standardized inputs."""
    from sklearn.linear_model import RidgeCV
    mu, sd = train_X.mean(0), train_X.std(0)
    sd[sd == 0] = 1.0
    m = RidgeCV(alphas=np.logspace(-2, 3, 30)).fit((train_X - mu) / sd, train_y)
    return float(m.predict(((x_new - mu) / sd).reshape(1, -1))[0])


def direct_rows(g: dict[int, float], h: int, extra: list[dict[int, float]]) -> dict[int, np.ndarray]:
    """Feature rows for the direct h-step model g_t ~ g_{t-h} + extra_t."""
    out = {}
    for t in g:
        if (t - h) in g and all(t in e for e in extra):
            out[t] = np.array([g[t - h]] + [e[t] for e in extra], dtype=float)
    return out


def rolling_origin_backtest(level: dict[int, float], h: int, models: dict[str, dict],
                            eval_keys: Iterable[int], min_train: int = 8,
                            train_start: int | None = None) -> dict:
    """Expanding-window backtest of direct h-step YoY-growth models.

    ``models`` maps name -> {"extra": [series...], "kind": "naive"|"ols"|"ridge",
    "own_lag": bool}. For each target quarter e, the origin is T = e - h; a model is
    trained on target quarters t <= T (t >= train_start) with all features present,
    then predicts g_e. The level forecast is level[e-4] * exp(g_hat). The seasonal
    naive model predicts g = 0, i.e. the same quarter last year.

    Only quarters where every model can forecast are scored, so models are compared on
    identical quarters. Returns per-model errors (log points) and summary metrics.
    """
    g = yoy(level)
    llog = log_series(level)
    preds: dict[str, dict[int, float]] = {m: {} for m in models}
    for e in sorted(eval_keys):
        if e not in llog or (e - 4) not in llog:
            continue
        T = e - h
        for name, spec in models.items():
            if spec["kind"] == "naive":
                preds[name][e] = 0.0
                continue
            extra = spec.get("extra", [])
            rows = direct_rows(g, h, extra)
            if not spec.get("own_lag", True):
                rows = {t: r[1:] for t, r in rows.items()}
            train = [t for t in rows if t <= T and (train_start is None or t >= train_start)]
            if len(train) < min_train or e not in rows:
                continue
            Xtr = np.array([rows[t] for t in train])
            ytr = np.array([g[t] for t in train])
            fitter = fit_predict_ridge if spec["kind"] == "ridge" else fit_predict_linear
            preds[name][e] = fitter(Xtr, ytr, rows[e])
    common = sorted(set.intersection(*(set(p) for p in preds.values()))) if preds else []
    result = {"h": h, "eval_quarters": [qlabel(k) for k in common], "models": {}}
    if not common:
        return result
    actual = np.array([g[k] for k in common])
    errs = {m: actual - np.array([preds[m][k] for k in common]) for m in models}
    base = errs.get("seasonal_naive")
    ref = errs.get("own_lag")
    for m, e in errs.items():
        rmse = float(np.sqrt(np.mean(e ** 2)))
        r = {"n": len(e), "mae": float(np.mean(np.abs(e))), "rmse": rmse,
             "errors": [float(v) for v in e],
             "forecast_growth": [float(preds[m][k]) for k in common]}
        if base is not None:
            r["skill_vs_naive"] = float(1 - np.mean(e ** 2) / np.mean(base ** 2)) if np.mean(base ** 2) > 0 else None
            r["dm_vs_naive"] = dm_test(e, base, h) if m != "seasonal_naive" else None
        if ref is not None and m not in ("own_lag", "seasonal_naive"):
            r["skill_vs_own_lag"] = float(1 - np.mean(e ** 2) / np.mean(ref ** 2)) if np.mean(ref ** 2) > 0 else None
            r["dm_vs_own_lag"] = dm_test(e, ref, h)
        result["models"][m] = r
    result["actual_growth"] = [float(v) for v in actual]
    return result


def live_forecast(level: dict[int, float], origin: int, h: int, spec: dict,
                  train_start: int | None = None) -> float | None:
    """Forecast log-growth g_{origin+h} training on quarters <= origin. None if infeasible."""
    if spec["kind"] == "naive":
        return 0.0
    g = yoy(level)
    rows = direct_rows(g, h, spec.get("extra", []))
    if not spec.get("own_lag", True):
        rows = {t: r[1:] for t, r in rows.items()}
    e = origin + h
    # the feature row for e needs g_{e-h} = g_origin and extra_e; build it directly
    if origin not in g or not all(e in x for x in spec.get("extra", [])):
        return None
    feat = np.array(([g[origin]] if spec.get("own_lag", True) else []) + [x[e] for x in spec.get("extra", [])])
    train = [t for t in rows if t <= origin and (train_start is None or t >= train_start)]
    if len(train) < 6:
        return None
    Xtr = np.array([rows[t] for t in train])
    ytr = np.array([g[t] for t in train])
    fitter = fit_predict_ridge if spec["kind"] == "ridge" else fit_predict_linear
    return fitter(Xtr, ytr, feat)


# ----------------------------------------------------------------------------- divergence
def divergence_z(actual: dict[int, float], driver: dict[int, float],
                 fit_exclude: set[int] = frozenset(), min_fit: int = 8) -> list[dict]:
    """Leave-one-out residual z-scores of actual_t against a + b * driver_t.

    For each quarter t, the line is fitted on every other quarter (minus fit_exclude),
    so the latest quarter's reading uses only earlier data, as a real-time monitor would.
    z = residual / (s * sqrt(1 + leverage-free 1/n)), s = residual SD of the fit.
    """
    ks, (a, d) = align(actual, driver)
    out = []
    for i, k in enumerate(ks):
        fit = [j for j, kk in enumerate(ks) if j != i and kk not in fit_exclude]
        if len(fit) < min_fit:
            continue
        X = np.column_stack([np.ones(len(fit)), d[fit]])
        beta, ssr = ols(a[fit], X)
        s = math.sqrt(ssr / (len(fit) - 2))
        implied = beta[0] + beta[1] * d[i]
        resid = a[i] - implied
        z = resid / (s * math.sqrt(1 + 1 / len(fit))) if s > 0 else 0.0
        out.append({"q": qlabel(k), "actual": float(a[i]), "driver": float(d[i]), "implied": float(implied),
                    "resid": float(resid), "z": float(z), "band": float(2 * s * math.sqrt(1 + 1 / len(fit))),
                    "beta": float(beta[1]), "n_fit": len(fit), "covid": k in COVID_FIT_EXCLUDE})
    return out


def spearman_with_perm(x: list[float], y: list[float], n_perm: int = 5000, seed: int = 7) -> dict:
    """Spearman rank correlation and a two-sided permutation p-value."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    rho = float(stats.spearmanr(x, y).statistic)
    rng = np.random.default_rng(seed)
    perm = np.array([stats.spearmanr(x, rng.permutation(y)).statistic for _ in range(n_perm)])
    p = float((np.sum(np.abs(perm) >= abs(rho)) + 1) / (n_perm + 1))
    return {"rho": rho, "pvalue": p, "n": len(x)}


def quarter_mean(points: Iterable[tuple[int, float]]) -> dict[int, tuple[float, int]]:
    """Mean of (quarter_key, value) pairs per quarter, with the count of points."""
    acc: dict[int, list[float]] = {}
    for k, v in points:
        if v is not None:
            acc.setdefault(k, []).append(v)
    return {k: (float(np.mean(v)), len(v)) for k, v in acc.items()}

