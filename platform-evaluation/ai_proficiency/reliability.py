"""Reliability, rater-quality, item, standard-setting and fairness statistics
for a HUMAN-scored rubric.

Nothing in this module produces a score. Human raters produce the scores; this
module measures how consistently they did it and whether the instrument and its
cut scores behave. Only the Python standard library and numpy are used.

Conventions
-----------
* Missing ratings are ``np.nan``.
* "Raters x units" matrices have one row per rater and one column per unit
  (Krippendorff's layout). "Subjects x raters" matrices (ICC) have one row per
  scored artifact and one column per rater.

References
----------
Cohen (1968) weighted kappa; Krippendorff (2011) "Computing Krippendorff's
alpha-reliability"; Shrout & Fleiss (1979) intraclass correlations; Cronbach
(1951); Holland & Thayer (1988) Mantel-Haenszel DIF; Dorans & Kulick (1986)
standardization; Angoff (1971) / Cizek & Bunch (2007) for the modified Angoff
procedure.
"""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Iterable, Sequence

import numpy as np


# --------------------------------------------------------------------------
# Inter-rater agreement
# --------------------------------------------------------------------------
def weighted_kappa(a: Sequence, b: Sequence, categories: Sequence | None = None,
                   weights: str = "quadratic") -> float:
    """Cohen's kappa for two raters, with 'none', 'linear' or 'quadratic' weights.

    kappa_w = 1 - sum(w * O) / sum(w * E), where w are disagreement weights,
    O the observed joint proportions and E the product of the marginals.
    Pairs where either rating is missing are dropped.
    """
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    keep = ~(np.isnan(a) | np.isnan(b))
    a, b = a[keep], b[keep]
    if a.size == 0:
        return float("nan")
    cats = np.asarray(sorted(set(a) | set(b)) if categories is None else categories, dtype=float)
    k = cats.size
    idx = {c: i for i, c in enumerate(cats)}
    obs = np.zeros((k, k))
    for x, y in zip(a, b):
        obs[idx[x], idx[y]] += 1
    obs /= obs.sum()
    exp = np.outer(obs.sum(axis=1), obs.sum(axis=0))
    i, j = np.indices((k, k))
    if weights == "none":
        w = (i != j).astype(float)
    elif weights == "linear":
        w = np.abs(i - j) / max(k - 1, 1)
    elif weights == "quadratic":
        w = (i - j) ** 2 / max(k - 1, 1) ** 2
    else:
        raise ValueError("weights must be 'none', 'linear' or 'quadratic'")
    denom = (w * exp).sum()
    if denom == 0:
        return float("nan")
    return float(1.0 - (w * obs).sum() / denom)


def cohen_kappa(a, b, categories=None) -> float:
    return weighted_kappa(a, b, categories, weights="none")


def krippendorff_alpha(data, level: str = "ordinal") -> float:
    """Krippendorff's alpha for a raters x units matrix (np.nan = missing).

    level: 'nominal', 'ordinal' or 'interval'. Units with fewer than two
    ratings are not pairable and are ignored. The ordinal metric uses the
    coincidence-matrix marginals n_g (Krippendorff 2011):
        delta^2(c, k) = (sum_{g=c..k} n_g - (n_c + n_k) / 2)^2
    """
    data = np.asarray(data, dtype=float)
    values = np.unique(data[~np.isnan(data)])
    if values.size < 2:
        return float("nan")
    vidx = {v: i for i, v in enumerate(values)}
    m = values.size
    o = np.zeros((m, m))
    for u in range(data.shape[1]):
        col = data[:, u]
        col = col[~np.isnan(col)]
        mu = col.size
        if mu < 2:
            continue
        counts = np.zeros(m)
        for v in col:
            counts[vidx[v]] += 1
        # ordered pairs of distinct raters within the unit, weighted 1/(mu-1)
        pair = np.outer(counts, counts) - np.diag(counts)
        o += pair / (mu - 1)
    n_c = o.sum(axis=1)
    n = n_c.sum()
    if n <= 1:
        return float("nan")
    ci, ki = np.indices((m, m))
    if level == "nominal":
        d2 = (ci != ki).astype(float)
    elif level == "interval":
        d2 = (values[ci] - values[ki]) ** 2
    elif level == "ordinal":
        cum = np.concatenate([[0.0], np.cumsum(n_c)])
        lo, hi = np.minimum(ci, ki), np.maximum(ci, ki)
        d2 = (cum[hi + 1] - cum[lo] - (n_c[ci] + n_c[ki]) / 2.0) ** 2
    else:
        raise ValueError("level must be 'nominal', 'ordinal' or 'interval'")
    d_o = (o * d2).sum()
    d_e = (np.outer(n_c, n_c) * d2).sum()
    if d_e == 0:
        return float("nan")
    return float(1.0 - (n - 1) * d_o / d_e)


def icc(ratings) -> dict:
    """Shrout & Fleiss intraclass correlations for a complete subjects x raters matrix.

    Returns ICC(1,1), ICC(1,k), ICC(2,1), ICC(2,k) (two-way random, absolute
    agreement - the forms that generalize to other trained raters), ICC(3,1),
    ICC(3,k) (consistency) and the mean squares.
    """
    x = np.asarray(ratings, dtype=float)
    if np.isnan(x).any():
        raise ValueError("ICC needs a complete (fully crossed) matrix")
    n, k = x.shape
    grand = x.mean()
    ss_total = ((x - grand) ** 2).sum()
    ss_rows = k * ((x.mean(axis=1) - grand) ** 2).sum()
    ss_cols = n * ((x.mean(axis=0) - grand) ** 2).sum()
    ss_err = ss_total - ss_rows - ss_cols
    msr = ss_rows / (n - 1)
    msc = ss_cols / (k - 1)
    mse = ss_err / ((n - 1) * (k - 1))
    msw = (ss_cols + ss_err) / (n * (k - 1))
    return {
        "n_subjects": n, "k_raters": k,
        "MSR": msr, "MSC": msc, "MSE": mse, "MSW": msw,
        "ICC(1,1)": (msr - msw) / (msr + (k - 1) * msw),
        "ICC(1,k)": (msr - msw) / msr,
        "ICC(2,1)": (msr - mse) / (msr + (k - 1) * mse + k * (msc - mse) / n),
        "ICC(2,k)": (msr - mse) / (msr + (msc - mse) / n),
        "ICC(3,1)": (msr - mse) / (msr + (k - 1) * mse),
        "ICC(3,k)": (msr - mse) / msr,
    }


def bootstrap_ci(stat_fn, x: np.ndarray, n_boot: int = 1000, seed: int = 0,
                 level: float = 0.95, axis: int = 0) -> tuple[float, float]:
    """Percentile bootstrap CI, resampling along `axis` (subjects/units)."""
    rng = np.random.default_rng(seed)
    x = np.asarray(x, dtype=float)
    size = x.shape[axis]
    stats = []
    for _ in range(n_boot):
        idx = rng.integers(0, size, size)
        val = stat_fn(np.take(x, idx, axis=axis))
        if not math.isnan(val):
            stats.append(val)
    lo, hi = np.percentile(stats, [(1 - level) / 2 * 100, (1 + level) / 2 * 100])
    return float(lo), float(hi)


def exact_and_adjacent(a, b) -> dict:
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    keep = ~(np.isnan(a) | np.isnan(b))
    d = np.abs(a[keep] - b[keep])
    return {"n": int(d.size), "exact": float((d == 0).mean()), "adjacent_or_exact": float((d <= 1).mean())}


# --------------------------------------------------------------------------
# Rater severity and drift
# --------------------------------------------------------------------------
def rater_severity(records: Iterable[dict]) -> dict:
    """Mean signed deviation of each rater from the OTHER raters on shared ratings.

    records: dicts with 'rater', 'unit' (artifact id), 'dim', 'score'.
    Positive = lenient, negative = severe. Only (unit, dim) cells with at least
    two raters contribute.
    """
    cells = defaultdict(list)
    for r in records:
        cells[(r["unit"], r["dim"])].append((r["rater"], float(r["score"])))
    dev = defaultdict(list)
    for ratings in cells.values():
        if len(ratings) < 2:
            continue
        total = sum(s for _, s in ratings)
        for rater, s in ratings:
            others = (total - s) / (len(ratings) - 1)
            dev[rater].append(s - others)
    out = {}
    for rater, d in sorted(dev.items()):
        d = np.asarray(d)
        se = d.std(ddof=1) / math.sqrt(d.size) if d.size > 1 else float("nan")
        out[rater] = {"n": int(d.size), "mean_dev": float(d.mean()), "se": float(se)}
    return out


def ols_slope(x: Sequence[float], y: Sequence[float]) -> float:
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    xc = x - x.mean()
    denom = (xc ** 2).sum()
    return float((xc * (y - y.mean())).sum() / denom) if denom else float("nan")


def rater_drift(records: Iterable[dict], slope_flag: float = 0.15,
                bias_flag: float = 0.3, exact_flag: float = 0.6) -> dict:
    """Track each rater against master scores on seeded anchor papers over sessions.

    records: dicts with 'rater', 'session' (int, chronological), 'score',
    'master'. For each rater and session: mean signed deviation (bias) and
    exact agreement with master. Drift = OLS slope of session bias on session
    number (points per session).

    Three separate flags, because they call for different responses:
    * drift_flag: |slope| >= slope_flag (the rater is changing over time);
    * bias_flag: |bias| in the latest session >= bias_flag (consistently
      severe or lenient now, whether or not it is changing);
    * agreement_flag: latest-session exact agreement < exact_flag.
    """
    by = defaultdict(lambda: defaultdict(list))
    for r in records:
        by[r["rater"]][int(r["session"])].append((float(r["score"]), float(r["master"])))
    out = {}
    for rater in sorted(by):
        sessions = sorted(by[rater])
        bias, exact = [], []
        for s in sessions:
            arr = np.asarray(by[rater][s])
            bias.append(float((arr[:, 0] - arr[:, 1]).mean()))
            exact.append(float((arr[:, 0] == arr[:, 1]).mean()))
        slope = ols_slope(sessions, bias) if len(sessions) > 1 else float("nan")
        drift_f = (not math.isnan(slope)) and abs(slope) >= slope_flag
        bias_f = abs(bias[-1]) >= bias_flag
        agree_f = exact[-1] < exact_flag
        reasons = []
        if drift_f:
            reasons.append(f"trend {slope:+.2f}/session")
        if bias_f:
            reasons.append(f"latest bias {bias[-1]:+.2f}")
        if agree_f:
            reasons.append(f"latest exact agreement {exact[-1]:.0%}")
        out[rater] = {"sessions": sessions, "bias": bias, "exact": exact, "slope": slope,
                      "drift_flag": drift_f, "bias_flag": bias_f, "agreement_flag": agree_f,
                      "flag": drift_f or bias_f or agree_f, "reasons": reasons}
    return out


# --------------------------------------------------------------------------
# Item analysis
# --------------------------------------------------------------------------
def cronbach_alpha(x) -> float:
    """Cronbach's alpha for a persons x items matrix (sample variances)."""
    x = np.asarray(x, dtype=float)
    k = x.shape[1]
    if k < 2:
        return float("nan")
    item_var = x.var(axis=0, ddof=1).sum()
    total_var = x.sum(axis=1).var(ddof=1)
    return float(k / (k - 1) * (1 - item_var / total_var)) if total_var else float("nan")


def item_analysis(x, names: Sequence[str], levels: Sequence[int] = (1, 2, 3, 4),
                  min_item_rest: float = 0.30) -> dict:
    """Per-item descriptives, distribution, corrected item-rest r and alpha-if-deleted.

    x: persons x items (items = rubric dimensions; values may be task means).
    An item is flagged if item-rest r < min_item_rest, if one level holds > 80%
    of ratings (ceiling/floor), or if deleting it raises alpha.
    """
    x = np.asarray(x, dtype=float)
    alpha = cronbach_alpha(x)
    total = x.sum(axis=1)
    items = []
    for j, name in enumerate(names):
        col = x[:, j]
        rest = total - col
        r = float(np.corrcoef(col, rest)[0, 1])
        a_del = cronbach_alpha(np.delete(x, j, axis=1))
        rounded = np.clip(np.floor(col + 0.5), min(levels), max(levels))
        dist = {int(lv): float((rounded == lv).mean()) for lv in levels}
        flags = []
        if r < min_item_rest:
            flags.append(f"low item-rest r ({r:.2f})")
        if max(dist.values()) > 0.8:
            flags.append("ceiling/floor (>80% one level)")
        if a_del > alpha + 0.005:
            flags.append("alpha rises if deleted")
        items.append({"item": name, "mean": float(col.mean()), "sd": float(col.std(ddof=1)),
                      "distribution": dist, "item_rest_r": r, "alpha_if_deleted": a_del,
                      "flags": flags})
    return {"alpha": alpha, "n_persons": int(x.shape[0]), "items": items}


def sem(sd: float, reliability: float) -> float:
    """Classical standard error of measurement."""
    return float(sd * math.sqrt(max(0.0, 1.0 - reliability)))


# --------------------------------------------------------------------------
# Standard setting: modified Angoff
# --------------------------------------------------------------------------
def angoff(panel_ratings, item_names: Sequence[str] | None = None) -> dict:
    """Modified (polytomous) Angoff for one round.

    panel_ratings: panelists x items; each entry is the panelist's estimate of
    the expected score of a minimally qualified (borderline) candidate on that
    item, on the rubric scale. Recommended cut = mean of panelist totals.
    SE of the cut = SD of panelist totals / sqrt(n panelists).
    """
    p = np.asarray(panel_ratings, dtype=float)
    totals = p.sum(axis=1)
    n = p.shape[0]
    sd = float(totals.std(ddof=1)) if n > 1 else float("nan")
    names = list(item_names) if item_names is not None else [f"item{j+1}" for j in range(p.shape[1])]
    return {
        "n_panelists": n,
        "panelist_totals": totals.tolist(),
        "cut": float(totals.mean()),
        "sd_totals": sd,
        "se_cut": sd / math.sqrt(n) if n > 1 else float("nan"),
        "item_means": dict(zip(names, p.mean(axis=0).tolist())),
        "item_sd": dict(zip(names, (p.std(axis=0, ddof=1) if n > 1 else np.full(p.shape[1], np.nan)).tolist())),
    }


def angoff_impact(totals: Sequence[float], cut: float, se: float = 0.0) -> dict:
    """Share of candidates at/above the cut, and at cut +/- 2 SE (sensitivity)."""
    t = np.asarray(totals, dtype=float)
    return {"cut": cut, "pass_rate": float((t >= cut).mean()),
            "pass_rate_cut_minus_2se": float((t >= cut - 2 * se).mean()),
            "pass_rate_cut_plus_2se": float((t >= cut + 2 * se).mean())}


# --------------------------------------------------------------------------
# Decision consistency
# --------------------------------------------------------------------------
def decision_consistency(a: Sequence[str], b: Sequence[str], labels: Sequence[str]) -> dict:
    """Agreement between two independent classifications of the same candidates.

    Returns proportion agreement p0, Cohen's kappa, linear-weighted kappa on
    the ordered labels and the confusion matrix (rows = a, cols = b).
    """
    idx = {lab: i for i, lab in enumerate(labels)}
    ai = np.array([idx[x] for x in a], dtype=float)
    bi = np.array([idx[x] for x in b], dtype=float)
    cm = np.zeros((len(labels), len(labels)), dtype=int)
    for x, y in zip(ai.astype(int), bi.astype(int)):
        cm[x, y] += 1
    cats = list(range(len(labels)))
    return {"n": int(ai.size), "p0": float((ai == bi).mean()) if ai.size else float("nan"),
            "kappa": cohen_kappa(ai, bi, cats),
            "kappa_linear": weighted_kappa(ai, bi, cats, "linear"),
            "labels": list(labels), "confusion": cm.tolist()}


# --------------------------------------------------------------------------
# Fairness: differential item functioning and impact ratios
# --------------------------------------------------------------------------
def _chi2_sf_1df(x: float) -> float:
    return math.erfc(math.sqrt(max(x, 0.0) / 2.0))


def mantel_haenszel_dif(correct: Sequence[int], focal: Sequence[bool], strata: Sequence) -> dict:
    """Mantel-Haenszel DIF for a dichotomized item.

    correct: 1 if the item score meets the criterion (e.g., >= 3), else 0.
    focal: True for the focal group, False for reference.
    strata: matching variable (e.g., banded rest score).
    alpha_MH > 1 favours the reference group. ETS delta = -2.35 ln(alpha_MH).
    ETS class (simplified): A if |delta| < 1 or p >= .05; C if |delta| >= 1.5
    and p < .05; otherwise B.
    """
    num = den = sum_a = sum_ea = sum_var = 0.0
    tables = defaultdict(lambda: [0, 0, 0, 0])  # A ref-right, B ref-wrong, C foc-right, D foc-wrong
    for c, f, s in zip(correct, focal, strata):
        t = tables[s]
        t[(2 if f else 0) + (0 if c else 1)] += 1
    for a, b, c, d in tables.values():
        n = a + b + c + d
        nr, nf, m1, m0 = a + b, c + d, a + c, b + d
        if n < 2 or nr == 0 or nf == 0:
            continue
        num += a * d / n
        den += b * c / n
        sum_a += a
        sum_ea += nr * m1 / n
        sum_var += nr * nf * m1 * m0 / (n * n * (n - 1))
    if den == 0 or num == 0 or sum_var == 0:
        return {"alpha_mh": float("nan"), "delta_mh": float("nan"), "chi2": float("nan"),
                "p": float("nan"), "ets_class": "n/a"}
    alpha = num / den
    delta = -2.35 * math.log(alpha)
    chi2 = (abs(sum_a - sum_ea) - 0.5) ** 2 / sum_var
    p = _chi2_sf_1df(chi2)
    if abs(delta) < 1.0 or p >= 0.05:
        cls = "A"
    elif abs(delta) >= 1.5:
        cls = "C"
    else:
        cls = "B"
    return {"alpha_mh": alpha, "delta_mh": delta, "chi2": chi2, "p": p, "ets_class": cls}


def standardized_mean_difference(scores: Sequence[float], focal: Sequence[bool], strata: Sequence) -> float:
    """Dorans-Kulick standardization for polytomous items.

    SMD = sum_s w_s (mean_focal_s - mean_ref_s), with w_s the focal group's
    proportion in stratum s (strata lacking either group are dropped and the
    weights renormalized). Negative = item harder for the focal group at the
    same matched level. |SMD| / SD(item) >= 0.25 is a common review flag.
    """
    groups = defaultdict(lambda: ([], []))
    for x, f, s in zip(scores, focal, strata):
        groups[s][0 if f else 1].append(float(x))
    num = wsum = 0.0
    for foc, ref in groups.values():
        if foc and ref:
            num += len(foc) * (np.mean(foc) - np.mean(ref))
            wsum += len(foc)
    return float(num / wsum) if wsum else float("nan")


def band(values: Sequence[float], n_bands: int = 5) -> list[int]:
    """Quantile bands (0..n_bands-1) for a matching variable."""
    v = np.asarray(values, dtype=float)
    edges = np.quantile(v, np.linspace(0, 1, n_bands + 1)[1:-1])
    return np.searchsorted(edges, v, side="right").tolist()


def fisher_exact_two_sided(a: int, b: int, c: int, d: int) -> float:
    """Two-sided Fisher exact p for [[a, b], [c, d]] (sum of tables as or less likely)."""
    r1, r2, c1, n = a + b, c + d, a + c, a + b + c + d

    def prob(x):
        return math.comb(r1, x) * math.comb(r2, c1 - x) / math.comb(n, c1)

    p_obs = prob(a)
    lo, hi = max(0, c1 - r2), min(r1, c1)
    return float(min(1.0, sum(prob(x) for x in range(lo, hi + 1) if prob(x) <= p_obs * (1 + 1e-9))))


def impact_ratios(outcome: Sequence[bool], group: Sequence[str], min_n: int = 10) -> dict:
    """Pass rate per group and ratio to the highest-rate group (four-fifths check).

    Groups with fewer than min_n members are suppressed. Each ratio also
    carries a Fisher exact p against the highest-rate group, because the
    four-fifths rule alone is unstable for small groups.
    """
    counts = defaultdict(lambda: [0, 0])
    for o, g in zip(outcome, group):
        counts[g][0] += int(bool(o))
        counts[g][1] += 1
    rates = {g: (p / n if n >= min_n else None) for g, (p, n) in counts.items()}
    shown = {g: r for g, r in rates.items() if r is not None}
    if not shown:
        return {}
    top = max(shown, key=shown.get)
    out = {}
    for g, (p, n) in sorted(counts.items()):
        if n < min_n:
            out[g] = {"n": n, "suppressed": True}
            continue
        tp, tn = counts[top]
        ratio = (rates[g] / rates[top]) if rates[top] else float("nan")
        out[g] = {"n": n, "pass": p, "rate": rates[g], "ratio_to_top": ratio,
                  "four_fifths_flag": bool(ratio < 0.8),
                  "fisher_p_vs_top": fisher_exact_two_sided(p, n - p, tp, tn - tp) if g != top else 1.0}
    return out
