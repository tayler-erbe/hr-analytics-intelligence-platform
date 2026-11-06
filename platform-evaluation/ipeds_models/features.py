"""Feature and target construction for the IPEDS institution models (pure functions, unit-tested).

Temporal rule: every feature for origin year t is a function of panel values in years <= t only
(own lags, and same-year peer-group context). Targets are values in year t+h. Domain values in an
institution-year flagged `exclude` (comparability_flags) are set to NaN *before* lags, targets and
peer context are computed, so a broken year can neither be a target nor contaminate a lag.

Peer-group context ("ctx_*") is a leave-one-out mean over the same sector x Carnegie group in the
same year, excluding the row itself and any unitid in `context_exclude` (used to keep the U of I
campuses out of every other institution's features when scoring U of I leave-institution-out).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

YEARS = list(range(2015, 2024))
GROUP_CODES = ["210", "220", "230", "250", "300", "310", "320", "330", "340", "350", "360", "370", "380", "390"]
GROUP_LABELS = {
    "210": "Instructional", "220": "Research", "230": "Public service",
    "250": "Library, student & academic affairs", "300": "Management", "310": "Business & financial ops",
    "320": "Computer, engineering & science", "330": "Community, legal, arts & media",
    "340": "Healthcare practitioners", "350": "Service", "360": "Sales", "370": "Office & admin support",
    "380": "Construction & maintenance", "390": "Production & transportation",
}
RANK_CODES = ["7", "1", "2", "3"]
RANK_LABELS = {"7": "All ranks", "1": "Professor", "2": "Associate professor", "3": "Assistant professor"}
MAX_STAFF_RATIO = 300.0
CARNEGIE_GROUPS = ["R1", "R2", "D/PU", "Masters", "Baccalaureate", "Special focus", "Other"]

STAFF_COLS = (["staff_total", "staff_ft", "published_grand_total", "graduate_assistants"]
              + [f"staff_{g}" for g in GROUP_CODES] + [f"staff_ft_{g}" for g in GROUP_CODES])
DOMAIN_COLS = {
    "staff": STAFF_COLS,
    "tenure": ["ft_instr", "tenured", "tenure_track", "tenured_share", "tenure_track_share"],
    "new_hires": ["nh_rate_all"] + [f"nh_rate_{g}" for g in GROUP_CODES],
    "faculty_pay": [f"fac_pay_real_{r}" for r in RANK_CODES] + [f"fac_n_{r}" for r in RANK_CODES],
    "enrollment": ["fte12", "fall_fte", "fte12_grad", "grad_fte_share"],
}
STATIC_COLS = ["name", "state", "sector", "carnegie_group", "carnegie_basic", "instsize", "hospital", "medical",
               "landgrant", "hbcu", "is_uofi", "is_big_ten"]

TASKS = {
    "tenure": {"label": "Next-year change in tenured share (pp of FT instructional staff)", "unit": "pp",
               "stacked": None, "min_origin": 2015},
    "newhire": {"label": "Next-year FT new-hire rate by occupation group (hires per 100 FT staff)", "unit": "per 100",
                "stacked": "group", "min_origin": 2016},
    "staffratio": {"label": "Change in staff per 100 FTE students", "unit": "per 100 FTE", "stacked": None,
                   "min_origin": 2015},
    "pay": {"label": "Faculty real-pay growth by rank (%, 9-month equated, 2023-24 $)", "unit": "%",
            "stacked": "rank", "min_origin": 2015},
}


def mask_excluded(panel: pd.DataFrame) -> pd.DataFrame:
    """NaN-out domain values in institution-years flagged `exclude` for that domain."""
    p = panel.copy()
    for dom, cols in DOMAIN_COLS.items():
        m = p[f"excl_{dom}"].astype(bool)
        if dom == "new_hires":
            m = m | p["excl_staff"].astype(bool)  # rates use FT staff as denominator
        p.loc[m, [c for c in cols if c in p.columns]] = np.nan
    both = p["excl_staff"].astype(bool) | p["excl_enrollment"].astype(bool)
    p.loc[both, "staff_per_100_fte"] = np.nan
    p.loc[p["excl_enrollment"].astype(bool), ["research_per_fte"]] = np.nan
    return p


def to_grid(panel: pd.DataFrame) -> pd.DataFrame:
    """Complete unitid x year grid (2015-2023) so that shift(1) is exactly 'previous calendar year'."""
    idx = pd.MultiIndex.from_product([sorted(panel["unitid"].unique()), YEARS], names=["unitid", "year"])
    g = panel.set_index(["unitid", "year"]).reindex(idx)
    g["in_universe"] = g["sector"].notna()
    return g


def _log(x):
    x = pd.to_numeric(x, errors="coerce").astype(float)
    return np.log(x.where(x > 0))


def _loo_ctx(df: pd.DataFrame, col: str, exclude: frozenset, keys=("sector", "carnegie_group", "year"),
             fallback=("sector", "year"), min_n: int = 3) -> pd.Series:
    """Leave-one-out group mean of `col`, skipping rows in `exclude`; falls back to coarser keys when n < min_n."""
    v = df[col].astype(float)
    elig = v.notna() & df["in_universe"].fillna(False).astype(bool) & ~df["unitid"].isin(exclude)
    vv = v.where(elig, 0.0)
    out = None
    for k in (list(keys), list(fallback)):
        s = vv.groupby([df[c] for c in k]).transform("sum")
        n = elig.astype(float).groupby([df[c] for c in k]).transform("sum")
        s_loo = s - vv * elig
        n_loo = n - elig.astype(float)
        m = (s_loo / n_loo).where(n_loo >= min_n)
        out = m if out is None else out.fillna(m)
    return out


def build_features(masked: pd.DataFrame, context_exclude: frozenset = frozenset()) -> pd.DataFrame:
    """Institution-level features at origin year t (one row per unitid x year in the universe)."""
    g = to_grid(masked)
    f = pd.DataFrame(index=g.index)
    st = g["staff_total"]
    f["log_staff"] = _log(st)
    f["log_fte"] = _log(g["fte12"])
    f["ft_share"] = g["staff_ft"] / st
    for code, name in (("210", "instr"), ("220", "research"), ("300", "mgmt"), ("340", "health"), ("350", "service"),
                       ("370", "office")):
        f[f"{name}_share"] = g[f"staff_{code}"] / st
    f["ga_per_100_fte"] = 100 * g["graduate_assistants"] / g["fte12"].where(g["fte12"] >= 200)
    f["tenured_share"] = g["tenured_share"]
    f["tenure_track_share"] = g["tenure_track_share"]
    f["log_ft_instr"] = _log(g["ft_instr"])
    f["staff_per_100_fte"] = g["staff_per_100_fte"]
    f["grad_fte_share"] = g["grad_fte_share"]
    f["log_research_per_fte"] = np.log1p(g["research_per_fte"].clip(lower=0))
    f["research_exp_share"] = (g["research_exp_real"] / g["total_exp_real"]).where(g["total_exp_real"] > 0)
    f["nh_rate_all"] = g["nh_rate_all"]
    f["log_pay7"] = _log(g["fac_pay_real_7"])
    f["log_pay1"] = _log(g["fac_pay_real_1"])
    f["log_nis_pay"] = _log(g["nis_pay_real"])
    # one-year dynamics (t-1 -> t) and their lag (t-2 -> t-1); NaN when either year is missing/excluded
    lag = lambda s, k=1: s.groupby(level="unitid").shift(k)  # noqa: E731
    for c in ("tenured_share", "tenure_track_share", "staff_per_100_fte", "log_staff", "log_fte", "log_pay7",
              "nh_rate_all", "log_ft_instr", "instr_share", "mgmt_share"):
        f[f"d1_{c}"] = f[c] - lag(f[c])
    for c in ("tenured_share", "staff_per_100_fte", "log_pay7"):
        f[f"d1lag_{c}"] = lag(f[f"d1_{c}"])
    f["nh_rate_all_lag"] = lag(f["nh_rate_all"])
    # static / regime
    for c in ("sector", "carnegie_group", "instsize", "hospital", "medical", "landgrant", "hbcu", "is_uofi",
              "is_big_ten", "name", "state", "in_universe"):
        f[c] = g[c]
    yr = f.index.get_level_values("year")
    f["soc2018"] = (yr >= 2018).astype(int)
    f["pandemic"] = np.isin(yr, [2020, 2021]).astype(int)
    f["caution_lag_staff"] = lag(g["excl_staff"].astype(float))  # excluded prior year (lag is NaN)
    # peer-group context (leave-one-out, same year)
    f = f.reset_index()
    for c in ("d1_tenured_share", "tenured_share", "d1_staff_per_100_fte", "staff_per_100_fte", "d1_log_pay7",
              "nh_rate_all", "d1_log_staff", "d1_log_fte"):
        f[f"ctx_{c}"] = _loo_ctx(f, c, context_exclude)
    # occupation-group and rank detail (used by stacked tasks)
    gr = g.reset_index()
    for code in GROUP_CODES:
        f[f"nh_rate_{code}"] = gr[f"nh_rate_{code}"].values
        f[f"share_{code}"] = (gr[f"staff_{code}"] / gr["staff_total"]).values
        f[f"log_ft_{code}"] = _log(gr[f"staff_ft_{code}"]).values
    for r in RANK_CODES:
        f[f"log_pay_r{r}"] = _log(gr[f"fac_pay_real_{r}"]).values
        f[f"log_n_r{r}"] = _log(gr[f"fac_n_{r}"]).values
    f = f.set_index(["unitid", "year"])
    for code in GROUP_CODES:
        f[f"nh_rate_{code}_lag"] = f[f"nh_rate_{code}"].groupby(level="unitid").shift(1)
    for r in RANK_CODES:
        f[f"d1_log_pay_r{r}"] = f[f"log_pay_r{r}"] - f[f"log_pay_r{r}"].groupby(level="unitid").shift(1)
    f = f.reset_index()
    for code in GROUP_CODES:
        f[f"ctx_nh_rate_{code}"] = _loo_ctx(f, f"nh_rate_{code}", context_exclude)
    for r in RANK_CODES:
        f[f"ctx_d1_log_pay_r{r}"] = _loo_ctx(f, f"d1_log_pay_r{r}", context_exclude)
    f = f[f["in_universe"].fillna(False).astype(bool)].drop(columns="in_universe")
    return f.set_index(["unitid", "year"]).sort_index()


BASE_NUMERIC = ["log_staff", "log_fte", "ft_share", "instr_share", "research_share", "mgmt_share", "health_share",
                "service_share", "office_share", "ga_per_100_fte", "tenured_share", "tenure_track_share",
                "log_ft_instr", "staff_per_100_fte", "grad_fte_share", "log_research_per_fte", "research_exp_share",
                "nh_rate_all", "nh_rate_all_lag", "log_pay7", "log_pay1", "log_nis_pay",
                "d1_tenured_share", "d1_tenure_track_share", "d1_staff_per_100_fte", "d1_log_staff", "d1_log_fte",
                "d1_log_pay7", "d1_nh_rate_all", "d1_log_ft_instr", "d1_instr_share", "d1_mgmt_share",
                "d1lag_tenured_share", "d1lag_staff_per_100_fte", "d1lag_log_pay7",
                "instsize", "hospital", "medical", "landgrant", "hbcu", "soc2018", "pandemic", "caution_lag_staff",
                "ctx_d1_tenured_share", "ctx_tenured_share", "ctx_d1_staff_per_100_fte", "ctx_staff_per_100_fte",
                "ctx_d1_log_pay7", "ctx_nh_rate_all", "ctx_d1_log_staff", "ctx_d1_log_fte"]
STACK_NUMERIC = {"group": ["grp_rate", "grp_rate_lag", "grp_share", "grp_log_ft", "ctx_grp_rate"],
                 "rank": ["rank_log_pay", "rank_d1_log_pay", "rank_log_n", "ctx_rank_d1_log_pay"]}


def _level(feats: pd.DataFrame, target_year: pd.Series, col: str, src: pd.DataFrame) -> np.ndarray:
    """Look up src[col] at (unitid, target_year) for each row in feats."""
    key = pd.MultiIndex.from_arrays([feats.index.get_level_values("unitid"), target_year])
    return src[col].reindex(key).to_numpy(dtype=float)


def make_task(task: str, h: int, feats: pd.DataFrame, masked: pd.DataFrame) -> pd.DataFrame:
    """Rows: origin (unitid, year=t) [x group/rank], target y at t+h, naive baseline inputs, features.

    Target values are read from the masked panel; origins without a valid target are kept with y = NaN
    (needed for forecasting 2024/2025). Callers drop NaN targets for training/evaluation.
    """
    src = masked.set_index(["unitid", "year"])
    f = feats[feats.index.get_level_values("year") >= TASKS[task]["min_origin"]].copy()
    t = f.index.get_level_values("year").to_numpy()
    ty = pd.Series(t + h, index=f.index)
    out = []
    if task == "tenure":
        d = f.copy()
        d["y"] = _level(f, ty, "tenured_share", src) - f["tenured_share"].to_numpy()
        d["persist"] = 0.0
        d["last_change"] = f["d1_tenured_share"].to_numpy() * h
        d["cat"] = "all"
        d = d[d["tenured_share"].notna()]
        out.append(d)
    elif task == "staffratio":
        d = f.copy()
        d["y"] = _level(f, ty, "staff_per_100_fte", src) - f["staff_per_100_fte"].to_numpy()
        d["persist"] = 0.0
        d["last_change"] = f["d1_staff_per_100_fte"].to_numpy() * h
        d["cat"] = "all"
        # origins above MAX_STAFF_RATIO (stand-alone medical / health-science centres whose ratio is driven by
        # hospital payroll) are left out of this task; see README.
        d = d[d["staff_per_100_fte"].notna() & (d["staff_per_100_fte"] <= MAX_STAFF_RATIO)]
        out.append(d)
    elif task == "newhire":
        for code in GROUP_CODES:
            d = f.copy()
            d["cat"] = code
            d["grp_rate"] = f[f"nh_rate_{code}"]
            d["grp_rate_lag"] = f[f"nh_rate_{code}_lag"]
            d["grp_share"] = f[f"share_{code}"]
            d["grp_log_ft"] = f[f"log_ft_{code}"]
            d["ctx_grp_rate"] = f[f"ctx_nh_rate_{code}"]
            d["y"] = _level(f, ty, f"nh_rate_{code}", src)
            d["persist"] = d["grp_rate"]
            d["last_change"] = d["grp_rate"]
            d = d[d["grp_rate"].notna()]
            out.append(d)
    elif task == "pay":
        for r in RANK_CODES:
            d = f.copy()
            d["cat"] = r
            d["rank_log_pay"] = f[f"log_pay_r{r}"]
            d["rank_d1_log_pay"] = f[f"d1_log_pay_r{r}"]
            d["rank_log_n"] = f[f"log_n_r{r}"]
            d["ctx_rank_d1_log_pay"] = f[f"ctx_d1_log_pay_r{r}"]
            d["y"] = 100 * (np.exp(np.log(_level(f, ty, f"fac_pay_real_{r}", src)) - f[f"log_pay_r{r}"].to_numpy()) - 1)
            d["persist"] = 0.0
            d["last_change"] = 100 * (np.exp(f[f"d1_log_pay_r{r}"].to_numpy() * h) - 1)
            d = d[d["rank_log_pay"].notna()]
            out.append(d)
    else:
        raise KeyError(task)
    d = pd.concat(out).reset_index()
    d["h"] = h
    d["target_year"] = d["year"] + h
    return d


def numeric_columns(task: str) -> list[str]:
    st = TASKS[task]["stacked"]
    return BASE_NUMERIC + (STACK_NUMERIC[st] if st else [])


def design_matrix(rows: pd.DataFrame, task: str) -> tuple[np.ndarray, list[str]]:
    """Numeric features + one-hot sector, Carnegie group and (stacked tasks) group/rank. NaNs kept."""
    cols = numeric_columns(task)
    X = rows[cols].astype(float)
    parts = [X]
    names = list(cols)
    for s in (1, 2, 3):
        parts.append(pd.DataFrame({f"sector_{s}": (rows["sector"] == s).astype(float)}))
        names.append(f"sector_{s}")
    for cg in CARNEGIE_GROUPS:
        parts.append(pd.DataFrame({f"carnegie_{cg}": (rows["carnegie_group"] == cg).astype(float)}))
        names.append(f"carnegie_{cg}")
    st = TASKS[task]["stacked"]
    if st:
        for c in (GROUP_CODES if st == "group" else RANK_CODES):
            parts.append(pd.DataFrame({f"{st}_{c}": (rows["cat"] == c).astype(float)}))
            names.append(f"{st}_{c}")
    M = np.column_stack([p.to_numpy(dtype=float).reshape(len(rows), -1) for p in parts])
    return M, names


def feature_blocks(names: list[str]) -> dict[str, list[int]]:
    """Group one-hot columns into one block each for permutation importance."""
    blocks: dict[str, list[int]] = {}
    for i, n in enumerate(names):
        key = n
        for pre in ("sector_", "carnegie_", "group_", "rank_"):
            if n.startswith(pre) and not n.startswith("rank_log") and not n.startswith("rank_d1"):
                key = pre.rstrip("_") + " (one-hot)"
        blocks.setdefault(key, []).append(i)
    return blocks
