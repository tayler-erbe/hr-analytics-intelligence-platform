"""(c) Bench strength for critical role families: expected internal-successor supply vs expected need.

For a critical tier F (classes of one role family flagged critical) over 24 months:

  need   D = sum_i in F [ P(separate) + P(move out) * P(destination not in F | class_i) ]
  supply S = sum_k not in F [ P(move) * P(destination in F | class_k) ]
  coverage = S / D

Incumbent-level probabilities come from the vacancy model (a); destination probabilities from the
Markov matrix (b). Monte Carlo draws combine Dirichlet posterior uncertainty of the matrix with
Bernoulli event noise, giving P10/P50/P90 of coverage and P(coverage < 1). Within-F moves cancel
(they open one F seat and fill another). Currently vacant F positions are reported alongside.

Only aggregates come out of this module. Supply is a FLOW of people in feeder roles, not a named
slate: it is the talent-pool view recommended over 1:1 replacement charts.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from config import BENCH_DRAWS


def critical_tiers(roles: pd.DataFrame) -> dict[str, list[str]]:
    c = roles[roles["critical_ind"] == "Y"]
    return {f: sorted(g["class_cd"]) for f, g in c.groupby("role_family")}


def bench(scored: pd.DataFrame, mob, roles: pd.DataFrame, horizon: int = 24, draws: int = BENCH_DRAWS,
          seed: int = 7, vacant: pd.DataFrame | None = None) -> pd.DataFrame:
    """scored: incumbents at the origin with class_cd, p{h} and p{h}_sep (calibrated)."""
    rng = np.random.default_rng(seed)
    tiers = critical_tiers(roles)
    Pdraw = mob.sample_rows(rng, draws)                  # (B, K, K)
    idx = mob.idx
    sc = scored[scored["class_cd"].isin(idx)].reset_index(drop=True)
    ci = sc["class_cd"].map(idx).to_numpy()
    p_all = sc[f"p{horizon}"].to_numpy()
    p_sep = np.minimum(sc[f"p{horizon}_sep"].to_numpy(), p_all)
    p_mov = np.clip(p_all - p_sep, 0, 1)
    rows = []
    for fam, cls in tiers.items():
        tgt = np.array([idx[c] for c in cls if c in idx])
        in_F = np.isin(ci, tgt)
        # posterior mean quantities
        pF_mean = mob.P[:, tgt].sum(axis=1)
        need_mean = float((p_sep[in_F] + p_mov[in_F] * (1 - pF_mean[ci[in_F]])).sum())
        sup_mean = float((p_mov[~in_F] * pF_mean[ci[~in_F]]).sum())
        # Monte Carlo: parameter (Dirichlet) + event (Bernoulli) uncertainty
        pF = Pdraw[:, :, tgt].sum(axis=2)               # (B, K)
        q_need = p_sep[in_F][None, :] + p_mov[in_F][None, :] * (1 - pF[:, ci[in_F]])
        q_sup = p_mov[~in_F][None, :] * pF[:, ci[~in_F]]
        need = (rng.random(q_need.shape) < q_need).sum(axis=1)
        sup = (rng.random(q_sup.shape) < q_sup).sum(axis=1)
        ratio = np.where(need > 0, sup / np.maximum(need, 1), np.nan)
        ok = ~np.isnan(ratio)
        contrib = pd.Series(p_mov[~in_F] * pF_mean[ci[~in_F]]).groupby(sc.loc[~in_F, "role_family"].to_numpy()).sum()
        share = contrib / contrib.sum() if contrib.sum() > 0 else contrib
        H = -(share[share > 0] * np.log(share[share > 0])).sum()
        n_vac = int(vacant["class_cd"].isin(cls).sum()) if vacant is not None else 0
        rows.append(dict(
            role_family=fam, critical_classes=",".join(cls), n_incumbents=int(in_F.sum()),
            n_feeder_incumbents=int(((pF_mean[ci] > 0.02) & ~in_F).sum()), vacant_now=n_vac,
            need_expected=need_mean, need_p10=float(np.percentile(need, 10)), need_p90=float(np.percentile(need, 90)),
            supply_expected=sup_mean, supply_p10=float(np.percentile(sup, 10)), supply_p90=float(np.percentile(sup, 90)),
            coverage_expected=sup_mean / need_mean if need_mean > 0 else np.nan,
            coverage_p10=float(np.nanpercentile(ratio[ok], 10)), coverage_p50=float(np.nanpercentile(ratio[ok], 50)),
            coverage_p90=float(np.nanpercentile(ratio[ok], 90)), p_coverage_below_1=float(np.mean(ratio[ok] < 1)),
            feeder_families_effective=float(np.exp(H)), top_feeder_family=str(share.idxmax()) if len(share) else "",
            top_feeder_share=float(share.max()) if len(share) else np.nan))
    df = pd.DataFrame(rows)
    df["status"] = np.select([df["p_coverage_below_1"] >= 0.5, df["coverage_p10"] < 1], ["Thin", "Watch"], "Covered")
    return df.sort_values("coverage_expected").reset_index(drop=True)


def realized_flows(sp_final: pd.DataFrame, roles: pd.DataFrame, origin, horizon_months: int = 24) -> pd.DataFrame:
    """Observed need (exits that left F) and supply (moves into F by people outside F at the origin)."""
    tiers = critical_tiers(roles)
    t0 = pd.Timestamp(origin)
    t1 = t0 + pd.DateOffset(months=horizon_months)
    e = pd.to_datetime(sp_final["exit_dt"])
    s = pd.to_datetime(sp_final["start_dt"])
    rows = []
    for fam, cls in tiers.items():
        cls = set(cls)
        win = e.notna() & (e >= t0) & (e < t1)
        from_F = sp_final["class_cd"].isin(cls)
        into_F = sp_final["dest_class_cd"].isin(cls)
        # need: incumbents in F at origin whose exit in window left F
        at_origin = (s <= t0) & (e.isna() | (e > t0))
        need = int((at_origin & from_F & win & ~((sp_final["cause"] == "MOVE") & into_F)).sum())
        supply = int((at_origin & win & ~from_F & (sp_final["cause"] == "MOVE") & into_F).sum())
        rows.append(dict(role_family=fam, realized_need=need, realized_supply=supply))
    return pd.DataFrame(rows)
