"""Evaluation metrics: Brier, AUC, cumulative/dynamic time-dependent AUC (IPCW), C-index, calibration."""
from __future__ import annotations

import numpy as np
import pandas as pd
from lifelines.utils import concordance_index
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score


def brier(y, p) -> float:
    y, p = np.asarray(y, float), np.asarray(p, float)
    return float(np.mean((p - y) ** 2))


def km_censoring(time, event):
    """Kaplan-Meier estimate of the censoring survival G(t) (censoring = event 0)."""
    t = np.asarray(time, float)
    c = 1 - np.asarray(event, int)
    order = np.argsort(t)
    t, c = t[order], c[order]
    uniq = np.unique(t[c == 1])
    G, surv = [], 1.0
    for u in uniq:
        at_risk = (t >= u).sum()
        d = ((t == u) & (c == 1)).sum()
        surv *= 1 - d / at_risk
        G.append((u, surv))
    def g(x):
        x = np.asarray(x, float)
        out = np.ones_like(x)
        for u, s in G:
            out = np.where(x >= u, s, out)
        return out
    return g


def auc_cd(time, event, risk, t) -> float:
    """Cumulative/dynamic AUC(t) with inverse-probability-of-censoring weights (Uno-style).

    Cases: event with T <= t (weighted 1/G(T-)); controls: T > t. When nobody is censored before t
    (true for every backtest origin here: follow-up runs past t) the weights are 1 and this equals
    the ordinary AUC of 1{T <= t}.
    """
    time, event, risk = np.asarray(time, float), np.asarray(event, int), np.asarray(risk, float)
    G = km_censoring(time, event)
    cases = (time <= t) & (event == 1)
    ctrls = time > t
    if cases.sum() == 0 or ctrls.sum() == 0:
        return float("nan")
    w = 1.0 / np.maximum(G(time[cases] - 1e-9), 1e-6)
    rc, rk = risk[cases], np.sort(risk[ctrls])
    less = np.searchsorted(rk, rc, side="left")
    leq = np.searchsorted(rk, rc, side="right")
    conc = (less + 0.5 * (leq - less)) / len(rk)
    return float(np.sum(w * conc) / np.sum(w))


def cindex(time, event, risk) -> float:
    return float(concordance_index(time, -np.asarray(risk, float), event))


def calibration(y, p) -> dict:
    y, p = np.asarray(y, int), np.clip(np.asarray(p, float), 1e-6, 1 - 1e-6)
    z = np.log(p / (1 - p))
    out = {"mean_pred": float(p.mean()), "obs_rate": float(y.mean()), "citl": float(y.mean() - p.mean())}
    if len(np.unique(y)) == 2:
        m = LogisticRegression(C=1e6, max_iter=2000).fit(z[:, None], y)
        out["slope"] = float(m.coef_[0, 0])
        out["auc"] = float(roc_auc_score(y, p))
    else:
        out["slope"], out["auc"] = float("nan"), float("nan")
    return out


def decile_table(y, p, bins: int = 10) -> pd.DataFrame:
    df = pd.DataFrame({"y": np.asarray(y, float), "p": np.asarray(p, float)})
    df["bin"] = pd.qcut(df["p"].rank(method="first"), bins, labels=False)
    g = df.groupby("bin").agg(n=("y", "size"), mean_pred=("p", "mean"), obs_rate=("y", "mean"))
    g["se"] = np.sqrt(g["obs_rate"] * (1 - g["obs_rate"]) / g["n"])
    return g.reset_index()
