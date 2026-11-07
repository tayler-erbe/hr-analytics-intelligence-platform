"""Unit x job-family attrition-risk score (protocol 3.5) and the Model B disparate-burden check (protocol 4).

expected_sep_rate_4q = sum of forecast separations h=1..4 / mean forecast headcount h=1..4, with P10/P90 from a
seeded Monte Carlo that resamples the method's own resolved 4-quarter log-error paths (joint across horizons
and across the separations / headcount pair, so the correlation between them is kept). Flag rule, fixed by the
protocol: attrition_flag = 1 when the unit's P10 exceeds the 75th percentile of expected rates across its peers
AND its trailing 4-quarter observed rate also exceeds that percentile.

Peer set. The protocol defines peers as "same campus, same job family, headcount >= 10", which assumes dept x
family units under a campus x family parent. On this population no dept series is modelled (every one pools to
campus x family), so the literal peer set is the unit itself. The next level up, all modelled units of the same
campus (PEER_SCOPE = "campus"), is used instead and recorded as a protocol gap in the model card; the dept rule
(PEER_SCOPE = "campus_family") is implemented and switches on automatically when dept series are modelled.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from wap_prototype.model_b import config as C  # noqa: E402
from wap_prototype.model_b.series import Panel  # noqa: E402

RISK_H = 4


def error_paths(bt: pd.DataFrame, method: str, T: int) -> tuple[np.ndarray, np.ndarray]:
    """Resolved 4-quarter log1p error paths (separations, headcount) of `method` with origin + 4 <= T, aligned
    by (series, origin). Shapes (n_paths, 4). Only rows whose target quarter is <= T are used (no look-ahead)."""
    sub = bt[(bt["method"] == method) & (bt["h"] <= RISK_H) & (bt["origin"] + RISK_H <= T) & bt["actual"].notna()
             & bt["target"].isin(["separations", "headcount"])].copy()
    if sub.empty:
        return np.empty((0, RISK_H)), np.empty((0, RISK_H))
    sub["err"] = np.log1p(sub["actual"]) - np.log1p(sub["point"].clip(lower=0))
    piv = sub.pivot_table(index=["series_id", "origin"], columns=["target", "h"], values="err")
    need = [(t, h) for t in ("separations", "headcount") for h in range(1, RISK_H + 1)]
    if not all(c in piv.columns for c in need):
        return np.empty((0, RISK_H)), np.empty((0, RISK_H))
    piv = piv[need].dropna()
    return piv["separations"].to_numpy(float), piv["headcount"].to_numpy(float)


def rate_interval(sep_pts: np.ndarray, hc_pts: np.ndarray, sep_paths: np.ndarray, hc_paths: np.ndarray,
                  rng: np.random.Generator) -> tuple[float, float, float]:
    """(point, P10, P90) of the 4-quarter expected separation rate. NaN bounds when fewer than MIN_PATHS paths."""
    sep_pts, hc_pts = np.asarray(sep_pts, float), np.asarray(hc_pts, float)
    point = float(sep_pts.sum() / hc_pts.mean()) if hc_pts.mean() > 0 else float("nan")
    if len(sep_paths) < C.MIN_PATHS:
        return point, float("nan"), float("nan")
    j = rng.integers(0, len(sep_paths), size=C.MC_DRAWS)
    seps = np.expm1(np.log1p(sep_pts)[None, :] + sep_paths[j]).clip(min=0).sum(axis=1)
    hcs = np.expm1(np.log1p(hc_pts)[None, :] + hc_paths[j]).clip(min=0).mean(axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        r = np.where(hcs > 0, seps / hcs, np.nan)
    r = r[~np.isnan(r)]
    if r.size < C.MIN_PATHS:
        return point, float("nan"), float("nan")
    return point, float(np.quantile(r, 0.10)), float(np.quantile(r, 0.90))


def trailing_rate(p: Panel, i: int, T: int) -> float:
    """Observed separations over (T-4, T] divided by mean headcount over T-4..T (NaN when history is short)."""
    if T < 4:
        return float("nan")
    seps = p.y["separations"][i, T - 3: T + 1]
    hc = p.y["headcount"][i, T - 4: T + 1]
    if np.isnan(seps).any() or np.isnan(hc).any() or hc.mean() <= 0:
        return float("nan")
    return float(seps.sum() / hc.mean())


def realized_rate(p_full: Panel, i: int, T: int) -> float:
    """Realised 4-quarter rate after T from the untruncated panel (backtest scoring only)."""
    if T + RISK_H >= p_full.n_q:
        return float("nan")
    seps = p_full.y["separations"][i, T + 1: T + RISK_H + 1]
    hc = p_full.y["headcount"][i, T + 1: T + RISK_H + 1]
    if np.isnan(seps).any() or np.isnan(hc).any() or hc.mean() <= 0:
        return float("nan")
    return float(seps.sum() / hc.mean())


def peer_scope(p: Panel) -> str:
    return "campus_family" if bool(p.registry.loc[p.registry["level"] == "dept", "modelled"].any()) else "campus"


def score_units(p: Panel, T: int, points: dict[int, dict[str, list[float]]], sep_paths: np.ndarray, hc_paths: np.ndarray,
                seed: int = C.SEED, p_full: Panel | None = None) -> pd.DataFrame:
    """One row per modelled unit with headcount >= K_MIN at T: expected rate, P10/P90, trailing observed rate,
    peer median / p75, flag. `points[i]` holds 'separations' and 'headcount' point forecasts for h=1..4."""
    rng = np.random.default_rng(seed)
    scope = peer_scope(p)
    rows = []
    for i, pt in sorted(points.items()):
        r = p.registry.iloc[i]
        hc_T = p.y["headcount"][i, T]
        sep_pts, hc_pts = np.asarray(pt["separations"][:RISK_H], float), np.asarray(pt["headcount"][:RISK_H], float)
        if np.isnan(sep_pts).any() or np.isnan(hc_pts).any():
            continue
        point, lo, hi = rate_interval(sep_pts, hc_pts, sep_paths, hc_paths, rng)
        rows.append(dict(series_id=r["series_id"], level=r["level"], campus=r["campus"], dept=r["dept"], role_family=r["role_family"],
                         origin=T, n=int(hc_T) if not np.isnan(hc_T) else 0, expected_sep_rate_4q=point,
                         expected_sep_rate_p10=lo, expected_sep_rate_p90=hi, observed_sep_rate_trailing_4q=trailing_rate(p, i, T),
                         realized_sep_rate_4q=realized_rate(p_full, i, T) if p_full is not None else float("nan")))
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["eligible"] = df["n"] >= C.K_MIN
    key = ["campus", "role_family"] if scope == "campus_family" else ["campus"]
    df["peer_scope"] = scope
    df["peer_median_rate"] = np.nan; df["peer_p75_rate"] = np.nan; df["n_peer_units"] = 0; df["realized_peer_p75"] = np.nan
    for _, idx in df[df["eligible"]].groupby(key).groups.items():
        peers = df.loc[idx]
        vals = peers["expected_sep_rate_4q"].dropna()
        df.loc[idx, "n_peer_units"] = int(len(vals))
        if len(vals):
            df.loc[idx, "peer_median_rate"] = float(np.median(vals))
            df.loc[idx, "peer_p75_rate"] = float(np.percentile(vals, C.PEER_PCTL))
        rv = peers["realized_sep_rate_4q"].dropna()
        if len(rv):
            df.loc[idx, "realized_peer_p75"] = float(np.percentile(rv, C.PEER_PCTL))
    ok = df["eligible"] & (df["n_peer_units"] >= C.PEER_MIN_UNITS) & df["expected_sep_rate_p10"].notna() & df["observed_sep_rate_trailing_4q"].notna()
    flag = (df["expected_sep_rate_p10"] > df["peer_p75_rate"]) & (df["observed_sep_rate_trailing_4q"] > df["peer_p75_rate"])
    df["attrition_flag"] = pd.array(np.where(ok, flag, None), dtype="boolean")
    return df


def flag_precision(scored: pd.DataFrame) -> tuple[float, int, int]:
    """B7: among flagged cells with a realised rate, the share above the realised peer p75. Returns
    (precision, n_flagged_scored, n_cells_with_flag_decision)."""
    f = scored[(scored["attrition_flag"] == True) & scored["realized_sep_rate_4q"].notna() & scored["realized_peer_p75"].notna()]  # noqa: E712
    n_dec = int(scored["attrition_flag"].notna().sum())
    if f.empty:
        return float("nan"), 0, n_dec
    return float((f["realized_sep_rate_4q"] > f["realized_peer_p75"]).mean()), int(len(f)), n_dec


# ------------------------------------------------------------------------------------ disparate burden
def disparate_burden(features: pd.DataFrame, demographics: pd.DataFrame, scored: pd.DataFrame, T_date) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Protocol 4, Model B: for each attribute compare the group composition of incumbents in flagged units with
    that of incumbents in unflagged units at the origin. Returns (published per-attribute summary, restricted
    per-group table). Groups with n < K_MIN in either side are not reported. Reported, not gating."""
    f = features[features["snap_date"] == T_date][["person_id", "campus_org_code", "dept_org_code", "role_family", "age_band"]].copy()
    d = demographics[["person_id", "sex_code", "race_eth_rpt_code"]]
    f = f.merge(d, on="person_id", how="left")
    f["age_40_plus"] = np.where(f["age_band"].isin(C.AGE_45_PLUS), "45+", np.where(f["age_band"].isna(), None, "<45"))
    dec = scored[scored["attrition_flag"].notna()]
    if dec.empty:
        return pd.DataFrame(columns=["attribute", "n_flagged_units", "n_unflagged_units", "max_share_gap_pp", "burden_flag", "groups_suppressed"]), pd.DataFrame()
    def unit_key(row):
        return (row["campus"], row["dept"], row["role_family"]) if row["level"] == "dept" else (row["campus"], None, row["role_family"])
    flagged = {unit_key(r) for _, r in dec[dec["attrition_flag"] == True].iterrows()}  # noqa: E712
    unflagged = {unit_key(r) for _, r in dec[dec["attrition_flag"] == False].iterrows()}  # noqa: E712
    lvl_dept = any(k[1] is not None for k in flagged | unflagged)
    f["unit"] = list(zip(f["campus_org_code"], f["dept_org_code"] if lvl_dept else [None] * len(f), f["role_family"]))
    f["side"] = np.where(f["unit"].isin(flagged), "flagged", np.where(f["unit"].isin(unflagged), "unflagged", None))
    f = f[f["side"].notna()]
    summary, groups = [], []
    for attr, col in (("sex", "sex_code"), ("race_eth_rpt_cd", "race_eth_rpt_code"), ("age_40_plus", "age_40_plus")):
        x = f[f[col].notna()]
        ct = x.groupby(["side", col]).size().unstack("side", fill_value=0)
        for side in ("flagged", "unflagged"):
            if side not in ct.columns:
                ct[side] = 0
        tot = ct.sum()
        gaps, suppressed = [], 0
        for g, r in ct.iterrows():
            if r["flagged"] < C.K_MIN or r["unflagged"] < C.K_MIN:
                suppressed += 1
                continue
            sf, su = r["flagged"] / tot["flagged"] if tot["flagged"] else np.nan, r["unflagged"] / tot["unflagged"] if tot["unflagged"] else np.nan
            gaps.append(abs(sf - su) * 100)
            groups.append(dict(attribute=attr, group=str(g), n_flagged=int(r["flagged"]), n_unflagged=int(r["unflagged"]),
                               share_flagged=float(sf), share_unflagged=float(su), gap_pp=float((sf - su) * 100)))
        mx = max(gaps) if gaps else float("nan")
        summary.append(dict(attribute=attr, n_flagged_units=len(flagged), n_unflagged_units=len(unflagged), n_persons_flagged=int(tot["flagged"]),
                            n_persons_unflagged=int(tot["unflagged"]), max_share_gap_pp=mx, burden_flag=bool(mx > 10) if not np.isnan(mx) else None,
                            groups_suppressed=suppressed))
    return pd.DataFrame(summary), pd.DataFrame(groups)
