"""Deterministic scoring functions for wap-protocol-v1 (MODEL_PROTOCOL_v1.md).

Pure numpy/scipy re-implementations of the metrics the protocol pre-registers, so the Phase 2
model code and the model cards use one definition each:

  Model A (classification)   auc_roc, auc_pr, brier, brier_skill, calibration, ece,
                             decile_table, poisson_binomial_quantiles, expected_count_cell
  Fairness                   four_fifths, equalized_odds_gaps, calibration_by_group
  Model B (forecasting)      mase_scale, mase, smape, interval_coverage, relative_mase
  Thresholds                 THRESHOLDS_A, THRESHOLDS_B, check_thresholds_a, check_thresholds_b

Semantics follow succession_models/metrics.py, succession_models/fairness.py and
turnover_forecast/models.py. No function draws random numbers; the Poisson-binomial interval
is an exact dynamic programme, not a simulation. Tests: protocol/tests/test_scorers.py.
"""
from __future__ import annotations

import math
from typing import Iterable, Sequence

import numpy as np
from scipy.stats import fisher_exact

PROTOCOL_VERSION = "wap-protocol-v1"
K_MIN = 10  # minimum group / cell size for anything reported


# --------------------------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------------------------

def _arr(x, dtype=float) -> np.ndarray:
    return np.asarray(list(x) if not isinstance(x, np.ndarray) else x, dtype=dtype)


def _check_binary(y: np.ndarray) -> None:
    if not np.all(np.isin(y, (0, 1))):
        raise ValueError("labels must be 0/1")


def _rankdata_avg(x: np.ndarray) -> np.ndarray:
    """Average ranks (1-based) with ties sharing the mean rank."""
    order = np.argsort(x, kind="mergesort")
    xs = x[order]
    ranks = np.empty(len(x), float)
    i = 0
    while i < len(xs):
        j = i
        while j + 1 < len(xs) and xs[j + 1] == xs[i]:
            j += 1
        ranks[order[i:j + 1]] = (i + j) / 2.0 + 1.0
        i = j + 1
    return ranks


# --------------------------------------------------------------------------------------------
# Model A: discrimination
# --------------------------------------------------------------------------------------------

def auc_roc(y: Iterable, p: Iterable) -> float:
    """Area under the ROC curve = Mann-Whitney U / (n_pos * n_neg); ties count one half.
    Returns nan when either class is absent."""
    y, p = _arr(y, int), _arr(p)
    _check_binary(y)
    n_pos, n_neg = int(y.sum()), int((1 - y).sum())
    if n_pos == 0 or n_neg == 0:
        return float("nan")
    r = _rankdata_avg(p)
    u = r[y == 1].sum() - n_pos * (n_pos + 1) / 2.0
    return float(u / (n_pos * n_neg))


def auc_pr(y: Iterable, p: Iterable) -> float:
    """Average precision: sum over distinct score thresholds (descending) of
    (recall gain) x (precision at that threshold). Ties are grouped at one threshold.
    Equals the area under the step-wise precision-recall curve. Returns nan with no positives."""
    y, p = _arr(y, int), _arr(p)
    _check_binary(y)
    n_pos = int(y.sum())
    if n_pos == 0:
        return float("nan")
    order = np.argsort(-p, kind="mergesort")
    ys, ps = y[order], p[order]
    ap, tp, fp, prev_recall = 0.0, 0, 0, 0.0
    i = 0
    while i < len(ps):
        j = i
        while j + 1 < len(ps) and ps[j + 1] == ps[i]:
            j += 1
        tp += int(ys[i:j + 1].sum())
        fp += int((1 - ys[i:j + 1]).sum())
        recall = tp / n_pos
        precision = tp / (tp + fp)
        ap += (recall - prev_recall) * precision
        prev_recall = recall
        i = j + 1
    return float(ap)


def prevalence(y: Iterable) -> float:
    y = _arr(y, int)
    return float(y.mean()) if len(y) else float("nan")


# --------------------------------------------------------------------------------------------
# Model A: calibration and skill
# --------------------------------------------------------------------------------------------

def brier(y: Iterable, p: Iterable) -> float:
    y, p = _arr(y), _arr(p)
    return float(np.mean((p - y) ** 2))


def brier_skill(y: Iterable, p: Iterable, p_ref: Iterable) -> float:
    """1 - Brier(model) / Brier(reference). Positive = better than the reference
    (e.g. the base-rate-by-role-family or by-ladder-step baseline)."""
    b_ref = brier(y, p_ref)
    if b_ref == 0:
        return float("nan")
    return float(1.0 - brier(y, p) / b_ref)


def _logit(p: np.ndarray, eps: float = 1e-6) -> np.ndarray:
    p = np.clip(p, eps, 1 - eps)
    return np.log(p / (1 - p))


def _sigmoid(z: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-z))


def _fit_logistic_1d(z: np.ndarray, y: np.ndarray, max_iter: int = 100, tol: float = 1e-10) -> tuple[float, float]:
    """Unpenalised MLE of y ~ sigmoid(a + b z) by Newton-Raphson. Returns (a, b)."""
    a, b = 0.0, 1.0
    X = np.column_stack([np.ones_like(z), z])
    beta = np.array([a, b])
    for _ in range(max_iter):
        mu = _sigmoid(X @ beta)
        w = mu * (1 - mu)
        grad = X.T @ (y - mu)
        hess = (X * w[:, None]).T @ X + 1e-12 * np.eye(2)
        step = np.linalg.solve(hess, grad)
        beta = beta + step
        if np.max(np.abs(step)) < tol:
            break
    return float(beta[0]), float(beta[1])


def calibration(y: Iterable, p: Iterable) -> dict:
    """Calibration-in-the-large (observed rate - mean prediction), logistic calibration slope and
    intercept (y regressed on logit p; slope 1, intercept 0 is ideal). As succession_models
    metrics.calibration, plus the intercept."""
    y, p = _arr(y, int), _arr(p)
    _check_binary(y)
    out = {"mean_pred": float(p.mean()), "obs_rate": float(y.mean()), "citl": float(y.mean() - p.mean())}
    if len(np.unique(y)) == 2:
        a, b = _fit_logistic_1d(_logit(p), y.astype(float))
        out["intercept"], out["slope"] = a, b
    else:
        out["intercept"], out["slope"] = float("nan"), float("nan")
    return out


def ece(y: Iterable, p: Iterable, bins: int = 10) -> float:
    """Expected calibration error with equal-count bins (sorted by prediction, split into `bins`
    contiguous groups of as-equal-as-possible size): sum_b (n_b/n) |obs_b - mean_pred_b|."""
    y, p = _arr(y), _arr(p)
    n = len(y)
    if n == 0:
        return float("nan")
    order = np.argsort(p, kind="mergesort")
    ys, ps = y[order], p[order]
    total = 0.0
    for idx in np.array_split(np.arange(n), min(bins, n)):
        if len(idx) == 0:
            continue
        total += len(idx) / n * abs(ys[idx].mean() - ps[idx].mean())
    return float(total)


def decile_table(y: Iterable, p: Iterable, bins: int = 10) -> list[dict]:
    y, p = _arr(y), _arr(p)
    order = np.argsort(p, kind="mergesort")
    rows = []
    for b, idx in enumerate(np.array_split(np.arange(len(y)), min(bins, len(y)))):
        if len(idx) == 0:
            continue
        obs = float(y[order][idx].mean())
        rows.append(dict(bin=b, n=int(len(idx)), mean_pred=float(p[order][idx].mean()), obs_rate=obs,
                         se=float(math.sqrt(obs * (1 - obs) / len(idx)))))
    return rows


# --------------------------------------------------------------------------------------------
# Model A: aggregation to the reporting grain (role x unit)
# --------------------------------------------------------------------------------------------

def poisson_binomial_pmf(p: Sequence[float]) -> np.ndarray:
    """Exact pmf of the number of successes among independent Bernoulli(p_i) (dynamic programme)."""
    pmf = np.array([1.0])
    for q in _arr(p):
        new = np.zeros(len(pmf) + 1)
        new[:-1] += pmf * (1 - q)
        new[1:] += pmf * q
        pmf = new
    return pmf


def poisson_binomial_quantiles(p: Sequence[float], qs: Sequence[float] = (0.1, 0.5, 0.9)) -> list[int]:
    """Smallest k with CDF(k) >= q, for each q."""
    cdf = np.cumsum(poisson_binomial_pmf(p))
    return [int(np.searchsorted(cdf, q - 1e-12, side="left")) for q in qs]


def expected_count_cell(p: Sequence[float], observed: int | None = None, k: int = K_MIN) -> dict:
    """One reporting-grain cell: expected count, exact P10/P90, observed count (when the horizon
    has resolved) and whether it falls inside the interval. Cells with n < k are suppressed."""
    p = _arr(p)
    n = len(p)
    if n < k:
        return dict(n=n, suppressed=True, expected=None, p10=None, p90=None, observed=None, inside=None)
    p10, p90 = poisson_binomial_quantiles(p, (0.1, 0.9))
    out = dict(n=n, suppressed=False, expected=float(p.sum()), p10=p10, p90=p90, observed=observed, inside=None)
    if observed is not None:
        out["inside"] = bool(p10 <= observed <= p90)
    return out


def reporting_grain_coverage(cells: Iterable[dict]) -> dict:
    """Share of unsuppressed, resolved cells whose observed count lies inside P10-P90, and the mean
    signed bias (expected - observed)."""
    cells = [c for c in cells if not c["suppressed"] and c.get("observed") is not None]
    if not cells:
        return {"n_cells": 0, "coverage": float("nan"), "mean_bias": float("nan")}
    return {"n_cells": len(cells),
            "coverage": float(np.mean([c["inside"] for c in cells])),
            "mean_bias": float(np.mean([c["expected"] - c["observed"] for c in cells]))}


# --------------------------------------------------------------------------------------------
# Fairness (protocol section 4)
# --------------------------------------------------------------------------------------------

FLAG_ADVERSE = "adverse impact indicated (<4/5, p<0.05)"
FLAG_BELOW = "below 4/5, not significant"


def four_fifths(group: Iterable, selected: Iterable, k: int = K_MIN, alpha: float = 0.05,
                ratio_threshold: float = 0.8) -> list[dict]:
    """Selection-rate ratio of each group against the highest-rate group among groups with n >= k,
    with a two-sided Fisher exact test of the group against all others. Groups with n < k are
    returned with suppressed=True and no rates. Same rules as succession_models/fairness.py."""
    g, s = _arr(group, object), _arr(selected, int)
    _check_binary(s)
    names = sorted(set(g.tolist()), key=str)
    n = {name: int((g == name).sum()) for name in names}
    nsel = {name: int(s[g == name].sum()) for name in names}
    reported = [name for name in names if n[name] >= k]
    rates = {name: nsel[name] / n[name] for name in reported}
    sr_max = max(rates.values()) if rates else float("nan")
    rows = []
    for name in names:
        row = dict(group=name, n=n[name], n_selected=nsel[name])
        if n[name] < k:
            row.update(suppressed=True, selection_rate=None, impact_ratio=None, fisher_p=None, flag="suppressed")
            rows.append(row)
            continue
        sel_g, n_g = nsel[name], n[name]
        sel_o = sum(nsel.values()) - sel_g
        n_o = sum(n.values()) - n_g
        if n_o > 0:
            _, pval = fisher_exact([[sel_g, n_g - sel_g], [sel_o, n_o - sel_o]], alternative="two-sided")
        else:
            pval = float("nan")
        ratio = rates[name] / sr_max if sr_max > 0 else float("nan")
        flag = (FLAG_ADVERSE if (ratio < ratio_threshold and pval < alpha) else
                FLAG_BELOW if ratio < ratio_threshold else "")
        row.update(suppressed=False, selection_rate=float(rates[name]), impact_ratio=float(ratio),
                   fisher_p=float(pval), flag=flag)
        rows.append(row)
    return rows


def equalized_odds_gaps(group: Iterable, selected: Iterable, label: Iterable, k: int = K_MIN) -> dict:
    """TPR and FPR per group (TPR needs >= k positives, FPR >= k negatives in the group) and the
    max between-group gaps. Groups with n < k are suppressed entirely."""
    g, s, y = _arr(group, object), _arr(selected, int), _arr(label, int)
    _check_binary(s)
    _check_binary(y)
    per_group, tprs, fprs = {}, [], []
    suppressed = 0
    for name in sorted(set(g.tolist()), key=str):
        m = g == name
        if m.sum() < k:
            suppressed += 1
            per_group[name] = dict(n=int(m.sum()), suppressed=True, tpr=None, fpr=None)
            continue
        pos, neg = m & (y == 1), m & (y == 0)
        tpr = float(s[pos].mean()) if pos.sum() >= k else None
        fpr = float(s[neg].mean()) if neg.sum() >= k else None
        per_group[name] = dict(n=int(m.sum()), suppressed=False, tpr=tpr, fpr=fpr)
        if tpr is not None:
            tprs.append(tpr)
        if fpr is not None:
            fprs.append(fpr)
    return dict(by_group=per_group,
                tpr_gap=float(max(tprs) - min(tprs)) if len(tprs) >= 2 else float("nan"),
                fpr_gap=float(max(fprs) - min(fprs)) if len(fprs) >= 2 else float("nan"),
                groups_reported=len(per_group) - suppressed, groups_suppressed=suppressed)


def calibration_by_group(group: Iterable, y: Iterable, p: Iterable, min_n: int = 50) -> dict:
    g, y, p = _arr(group, object), _arr(y, int), _arr(p)
    out = {}
    for name in sorted(set(g.tolist()), key=str):
        m = g == name
        out[name] = calibration(y[m], p[m]) | {"n": int(m.sum())} if m.sum() >= min_n else {"n": int(m.sum()), "suppressed": True}
    return out


def fairness_summary(ff_rows: list[dict], eo: dict) -> dict:
    """The per-attribute summary that goes to fact_model_quality (no group-level rows)."""
    reported = [r for r in ff_rows if not r["suppressed"]]
    flags = [r["flag"] for r in reported]
    return dict(min_impact_ratio=min((r["impact_ratio"] for r in reported), default=float("nan")),
                max_tpr_gap=eo["tpr_gap"], max_fpr_gap=eo["fpr_gap"],
                fairness_flag=("adverse" if FLAG_ADVERSE in flags else "below_4_5" if FLAG_BELOW in flags else "none"),
                groups_reported=len(reported), groups_suppressed=len(ff_rows) - len(reported))


# --------------------------------------------------------------------------------------------
# Model B: forecast accuracy (turnover_forecast/models.py semantics)
# --------------------------------------------------------------------------------------------

def mase_scale(y_train: Iterable, m: int = 4) -> float:
    """In-sample mean absolute lag-m seasonal-naive error over the training series (nan-aware)."""
    y = _arr(y_train)
    if len(y) <= m:
        return float("nan")
    d = np.abs(y[m:] - y[:-m])
    d = d[~np.isnan(d)]
    return float(d.mean()) if d.size else float("nan")


def mase(y: Iterable, f: Iterable, scale: float | Iterable) -> np.ndarray:
    """Absolute error divided by the seasonal-naive scale, per point."""
    return np.abs(_arr(y) - _arr(f)) / _arr(scale) if not np.isscalar(scale) else np.abs(_arr(y) - _arr(f)) / float(scale)


def smape(y: Iterable, f: Iterable) -> np.ndarray:
    """200 |y - f| / (|y| + |f|) per point; 0 when both are 0."""
    y, f = _arr(y), _arr(f)
    den = np.abs(y) + np.abs(f)
    with np.errstate(invalid="ignore", divide="ignore"):
        out = np.where(den == 0, 0.0, 200.0 * np.abs(y - f) / den)
    return out


def interval_coverage(y: Iterable, lo: Iterable, hi: Iterable) -> float:
    """Share of actuals inside [lo, hi], ignoring rows with any nan."""
    y, lo, hi = _arr(y), _arr(lo), _arr(hi)
    ok = ~(np.isnan(y) | np.isnan(lo) | np.isnan(hi))
    return float(np.mean((y[ok] >= lo[ok]) & (y[ok] <= hi[ok]))) if ok.any() else float("nan")


def relative_mase(mase_model: Iterable, mase_naive: Iterable) -> float:
    """Mean MASE of the model divided by mean MASE of seasonal naive on the same (origin, horizon)
    pairs (< 1 = better than seasonal naive)."""
    a, b = _arr(mase_model), _arr(mase_naive)
    ok = ~(np.isnan(a) | np.isnan(b))
    if not ok.any() or b[ok].mean() == 0:
        return float("nan")
    return float(a[ok].mean() / b[ok].mean())


# --------------------------------------------------------------------------------------------
# Pre-registered thresholds (MODEL_PROTOCOL_v1.md sections 2.6 and 3.6). Do not edit without a
# protocol version bump.
# --------------------------------------------------------------------------------------------

THRESHOLDS_A = {
    "A1_auc_roc_min": 0.62, "A1_auc_roc_gain_over_step": 0.03,
    "A2_auc_pr_prevalence_multiple": 1.5,
    "A3_brier_skill_vs_family_min": 0.02, "A3b_brier_skill_vs_step_min": 0.0,
    "A4_cal_slope_range": (0.85, 1.15), "A5_citl_abs_max": 0.01, "A6_ece_max": 0.02,
    "A7_grain_coverage_min": 0.70, "A9_age_ablation_gain_review": 0.03,
}

THRESHOLDS_B = {
    "B1_rel_mase_h1_4_max": 0.95, "B2_rel_mase_h5_12_max": 1.00,
    "B3_cov80_range": (0.70, 0.90), "B4_cov95_min": 0.88,
    "B5_h4_bias_share_max": 0.02, "B6_hierarchy_discrepancy_max": 0.05, "B7_flag_precision_min": 0.60,
}


def check_thresholds_a(m: dict) -> dict:
    """m keys: auc_roc, auc_roc_step, auc_pr, prevalence, auc_pr_step, brier_skill_family,
    brier_skill_step, cal_slope, citl, ece, grain_coverage, fairness_flag, age_ablation_gain."""
    t = THRESHOLDS_A
    return {
        "A1": m["auc_roc"] >= t["A1_auc_roc_min"] and m["auc_roc"] >= m["auc_roc_step"] + t["A1_auc_roc_gain_over_step"],
        "A2": m["auc_pr"] >= t["A2_auc_pr_prevalence_multiple"] * m["prevalence"] and m["auc_pr"] >= m["auc_pr_step"],
        "A3": m["brier_skill_family"] >= t["A3_brier_skill_vs_family_min"],
        "A3b": m["brier_skill_step"] >= t["A3b_brier_skill_vs_step_min"],
        "A4": t["A4_cal_slope_range"][0] <= m["cal_slope"] <= t["A4_cal_slope_range"][1],
        "A5": abs(m["citl"]) <= t["A5_citl_abs_max"],
        "A6": m["ece"] <= t["A6_ece_max"],
        "A7": m["grain_coverage"] >= t["A7_grain_coverage_min"],
        "A8": m.get("fairness_flag", "none") != "adverse",
        "A9_review_required": m.get("age_ablation_gain", 0.0) > t["A9_age_ablation_gain_review"],
    }


def check_thresholds_b(m: dict) -> dict:
    """m keys: rel_mase_h1_4, rel_mase_h5_12, cov80, cov95, h4_bias_share, hierarchy_discrepancy,
    flag_precision."""
    t = THRESHOLDS_B
    return {
        "B1": m["rel_mase_h1_4"] <= t["B1_rel_mase_h1_4_max"],
        "B2": m["rel_mase_h5_12"] <= t["B2_rel_mase_h5_12_max"],
        "B3": t["B3_cov80_range"][0] <= m["cov80"] <= t["B3_cov80_range"][1],
        "B4": m["cov95"] >= t["B4_cov95_min"],
        "B5": abs(m["h4_bias_share"]) <= t["B5_h4_bias_share_max"],
        "B6": m["hierarchy_discrepancy"] <= t["B6_hierarchy_discrepancy_max"],
        "B7": m["flag_precision"] >= t["B7_flag_precision_min"],
    }


def passes_all(checks: dict) -> bool:
    return all(v for k, v in checks.items() if not k.endswith("_review_required"))
