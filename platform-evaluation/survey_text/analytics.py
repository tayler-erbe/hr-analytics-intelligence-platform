"""Aggregate analytics with small-cell suppression. Inputs are coded, redacted records;
outputs are aggregates only (no ResponseIds, no text).

Suppression policy (K = codebook min_cell_size, default 10):
  * a cell whose denominator n < K is suppressed (value and n withheld; "n<10" shown);
  * a published count/share whose numerator is 1..K-1 is masked ("<10"); zero is shown as zero;
  * complementary suppression: within one dimension, if exactly one segment is primary-suppressed,
    the next-smallest segment is also suppressed so it cannot be recovered from the total;
  * a driver (relative-risk) estimate is published only when every cell of its 2x2 table is >= K.
"""
from __future__ import annotations

import math
from collections import defaultdict

Z = 1.959964


def nps(scores: list[int]) -> tuple[float, float, float, float, float]:
    """eNPS (x100) with Wald 95% CI using var(P-D) = (p + d - (p-d)^2)/n."""
    n = len(scores)
    p = sum(s >= 9 for s in scores) / n
    d = sum(s <= 6 for s in scores) / n
    e = p - d
    se = math.sqrt(max(p + d - e * e, 0) / n)
    return 100 * e, 100 * (e - Z * se), 100 * (e + Z * se), 100 * p, 100 * d


def mask_count(c: int, k: int):
    return c if (c == 0 or c >= k) else None


def enps_by(records, dim: str | None, k: int, score_key="score") -> list[dict]:
    groups = defaultdict(list)
    for r in records:
        groups[r[dim] if dim else "All respondents"].append(r[score_key])
    out = []
    for g, sc in sorted(groups.items(), key=lambda kv: str(kv[0])):
        row = {"segment": g, "n": len(sc), "suppressed": len(sc) < k, "reason": "n<k" if len(sc) < k else None}
        if not row["suppressed"]:
            e, lo, hi, p, d = nps(sc)
            row.update(enps=round(e, 1), lo=round(lo, 1), hi=round(hi, 1), promoters=round(p, 1), detractors=round(d, 1))
        out.append(row)
    primary = [r for r in out if r["suppressed"]]
    if dim and len(primary) == 1:
        rest = sorted((r for r in out if not r["suppressed"]), key=lambda r: r["n"])
        if rest:
            c = rest[0]
            for key in ("enps", "lo", "hi", "promoters", "detractors"):
                c.pop(key, None)
            c.update(suppressed=True, reason="complementary")
    for r in out:
        if r["suppressed"]:
            r["n"] = None  # do not reveal small n either
    return out


def prevalence(records, themes, k: int, group_key: str | None = None) -> list[dict]:
    groups = defaultdict(list)
    for r in records:
        if r["answered"]:
            groups[r[group_key] if group_key else "all"].append(r)
    out = []
    for g, rs in sorted(groups.items(), key=lambda kv: str(kv[0])):
        n = len(rs)
        for th in themes:
            c = sum(th in r["themes"] for r in rs)
            row = {"group": g, "theme": th, "n_comments": n if n >= k else None}
            if n < k:
                row.update(suppressed=True, count=None, share=None)
            else:
                mc = mask_count(c, k)
                row.update(suppressed=mc is None, count=mc, share=None if mc is None else round(c / n, 4))
            out.append(row)
    return out


def relative_risk(a, b, c, d):
    """a: theme & detractor, b: theme & not, c: no theme & detractor, d: no theme & not. Katz log CI."""
    r1, r0 = a / (a + b), c / (c + d)
    rr = r1 / r0
    se = math.sqrt(1 / a - 1 / (a + b) + 1 / c - 1 / (c + d))
    return rr, rr * math.exp(-Z * se), rr * math.exp(Z * se), r1, r0


def drivers(records, themes, k: int, outcome="detractor") -> list[dict]:
    rs = [r for r in records if r["answered"]]
    out = []
    for th in themes:
        y = [r[outcome] for r in rs]
        x = [th in r["themes"] for r in rs]
        a = sum(1 for xi, yi in zip(x, y) if xi and yi)
        b = sum(1 for xi, yi in zip(x, y) if xi and not yi)
        c = sum(1 for xi, yi in zip(x, y) if not xi and yi)
        d = sum(1 for xi, yi in zip(x, y) if not xi and not yi)
        row = {"theme": th, "n_mention": a + b if a + b >= k else None}
        if min(a, b, c, d) < k:
            row.update(suppressed=True)
        else:
            rr, lo, hi, r1, r0 = relative_risk(a, b, c, d)
            row.update(suppressed=False, rr=round(rr, 3), lo=round(lo, 3), hi=round(hi, 3),
                       rate_with=round(r1, 4), rate_without=round(r0, 4))
        out.append(row)
    return out


def logistic(records, themes, k: int, outcome="detractor", controls=("survey_wave",)) -> dict:
    """Multivariable logistic regression (IRLS, numpy) of outcome on theme indicators + controls.
    Wald 95% CIs from the observed information matrix. Themes with < k mentions are dropped."""
    import numpy as np
    rs = [r for r in records if r["answered"]]
    keep = [th for th in themes if sum(th in r["themes"] for r in rs) >= k]
    cols, X = ["intercept"], [[1.0] * len(rs)]
    for th in keep:
        cols.append(th)
        X.append([float(th in r["themes"]) for r in rs])
    for ctl in controls:
        levels = sorted({r[ctl] for r in rs})
        for lv in levels[1:]:
            cols.append(f"{ctl}={lv}")
            X.append([float(r[ctl] == lv) for r in rs])
    X = np.array(X).T
    y = np.array([float(r[outcome]) for r in rs])
    beta = np.zeros(X.shape[1])
    for _ in range(50):
        p = 1 / (1 + np.exp(-X @ beta))
        W = p * (1 - p)
        H = X.T @ (X * W[:, None])
        step = np.linalg.solve(H, X.T @ (y - p))
        beta += step
        if np.max(np.abs(step)) < 1e-9:
            break
    cov = np.linalg.inv(H)
    se = np.sqrt(np.diag(cov))
    terms = []
    for i, c in enumerate(cols):
        if c == "intercept":
            continue
        terms.append({"term": c, "or": round(float(np.exp(beta[i])), 3),
                      "lo": round(float(np.exp(beta[i] - Z * se[i])), 3),
                      "hi": round(float(np.exp(beta[i] + Z * se[i])), 3)})
    return {"n": int(len(y)), "outcome": outcome, "dropped_small_themes": [t for t in themes if t not in keep],
            "terms": terms}


def share_table(records, group_key, cat_key, k: int, categories=None) -> list[dict]:
    groups = defaultdict(list)
    for r in records:
        groups[r[group_key]].append(r[cat_key])
    cats = categories or sorted({r[cat_key] for r in records})
    out = []
    for g in sorted(groups):
        vals = groups[g]
        n = len(vals)
        for c in cats:
            cnt = vals.count(c)
            mc = mask_count(cnt, k) if n >= k else None
            out.append({"group": g, "category": c, "n": n if n >= k else None, "count": mc,
                        "share": None if mc is None else round(cnt / n, 4), "suppressed": mc is None})
    return out
