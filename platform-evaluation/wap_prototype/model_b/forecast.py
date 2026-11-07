"""Forecasts from the latest origin (data_as_of), the unit x family attrition-risk score and the disparate-burden
check (protocol 3.1, 3.5, 4).

Every learner forecasts h = 1..12 for every modelled series and target. P10/P50/P90 (and the 95% band) come
from the method's own backtest log1p errors pooled across series per target x horizon, i.e. the same
construction as the backtest's empirical intervals with every resolved error available at data_as_of.
B-snaive and B-ets also carry their native intervals. The `primary` series follows the pre-registered
selection in metrics_b.json (per horizon, so a method failing B1 is replaced by B-snaive for h <= 4).

Usage (from platform-evaluation/):  python -m wap_prototype.model_b.forecast
Outputs (restricted, unsuppressed): forecast_latest.parquet, risk_latest.parquet, disparate_burden_groups.csv;
plus forecast_meta.json. publish_b.py turns these into the suppressed star-schema tables.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from wap_prototype.model_b import config as C  # noqa: E402
from wap_prototype.model_b import learners as L  # noqa: E402
from wap_prototype.model_b import risk as R  # noqa: E402
from wap_prototype.model_b import series as S  # noqa: E402

QUANTILES = {"p10": 0.10, "p50": 0.50, "p90": 0.90, "p025": 0.025, "p975": 0.975}


def error_pool(bt: pd.DataFrame, T: int) -> dict[tuple[str, str, int], np.ndarray]:
    """Resolved log1p errors per (target, method, h) with target quarter <= T."""
    d = bt[bt["actual"].notna() & (bt["tq"] <= T)]
    e = np.log1p(d["actual"]) - np.log1p(d["point"].clip(lower=0))
    return {k: e.loc[idx].to_numpy() for k, idx in d.groupby(["target", "method", "h"]).groups.items()}


def forecast_latest(p: S.Panel, bt: pd.DataFrame, selection: dict, targets: list[str] | None = None) -> pd.DataFrame:
    T = p.n_q - 1
    pool = error_pool(bt, T)
    rows = []
    for target in targets or (C.TARGETS + C.SENSITIVITY_TARGETS):
        fc = L.forecast_at(S.truncate(p, T), target, T)
        for method, by_series in fc.items():
            for i, f in by_series.items():
                r = p.registry.iloc[i]
                for h in range(1, C.H + 1):
                    pt = f["point"][h - 1]
                    if pt is None or not np.isfinite(pt):
                        continue
                    e = pool.get((target, method, h), np.empty(0))
                    q = {k: (float(max(np.expm1(np.log1p(pt) + np.quantile(e, v)), 0.0)) if e.size >= C.MIN_ERRORS else np.nan) for k, v in QUANTILES.items()}
                    rows.append(dict(target=target, method=method, series_id=r["series_id"], series_idx=int(i), level=r["level"], campus=r["campus"],
                                     dept=r["dept"], role_family=r["role_family"], origin=T, h=h, tq=T + h, point=float(pt), n_errors=int(e.size), **q,
                                     **{f"nat_{k}": (float(f[k][h - 1]) if k in f and np.isfinite(f[k][h - 1]) else np.nan) for k in ("lo80", "hi80", "lo95", "hi95")}))
    df = pd.DataFrame(rows)
    by_h = {int(k): v for k, v in selection["by_horizon"].items()}
    prim = df[[by_h.get(h) == m for h, m in zip(df["h"], df["method"])]].copy()
    prim["method_used"] = prim["method"]; prim["method"] = "primary"
    if selection["chosen"] == "B-snaive":   # seasonal naive is published with its native interval (protocol 3.6)
        for a, b in (("p10", "nat_lo80"), ("p90", "nat_hi80"), ("p025", "nat_lo95"), ("p975", "nat_hi95")):
            prim[a] = prim[b]
        prim["p50"] = prim["point"]
    df["method_used"] = df["method"]
    return pd.concat([prim, df], ignore_index=True)


def risk_latest(p: S.Panel, bt: pd.DataFrame, fc: pd.DataFrame) -> pd.DataFrame:
    T = p.n_q - 1
    prim = fc[(fc["method"] == "primary") & (fc["h"] <= R.RISK_H) & fc["target"].isin(["separations", "headcount"])]
    points: dict[int, dict] = {}
    for (i, t), g in prim.groupby(["series_idx", "target"]):
        points.setdefault(int(i), {})[t] = g.sort_values("h")["point"].tolist()
    points = {i: v for i, v in points.items() if len(v.get("separations", [])) == R.RISK_H and len(v.get("headcount", [])) == R.RISK_H}
    method_h1 = prim[prim["h"] == 1]["method_used"].iloc[0] if len(prim) else "B-ens"
    sp, hp = R.error_paths(bt, method_h1, T)
    sc = R.score_units(p, T, points, sp, hp, seed=C.SEED)
    sc["method"] = "primary"; sc["method_used"] = method_h1
    return sc


def main() -> None:
    p, _ = S.load_panel()
    bt = pd.read_parquet(C.RESTRICTED / "backtest.parquet")
    met = json.loads((C.OUT / "metrics_b.json").read_text())
    sel = met["selection"]
    fc = forecast_latest(p, bt, sel)
    fc.to_parquet(C.RESTRICTED / "forecast_latest.parquet", index=False)
    rk = risk_latest(p, bt, fc)
    rk.to_parquet(C.RESTRICTED / "risk_latest.parquet", index=False)
    features, _ = S.load_phase1()
    demo = pd.read_parquet(C.PHASE1_RESTRICTED / "person_demographics_restricted.parquet")
    summary, groups = R.disparate_burden(features, demo, rk, p.data_as_of)
    groups.to_csv(C.RESTRICTED / "disparate_burden_groups.csv", index=False)
    meta = {"origin": p.data_as_of.isoformat(), "origin_index": p.n_q - 1, "selection": sel, "n_series": int(fc["series_id"].nunique()),
            "n_rows": int(len(fc)), "risk_units_scored": int(len(rk)), "risk_flags": int((rk["attrition_flag"] == True).sum()),  # noqa: E712
            "risk_flag_decisions": int(rk["attrition_flag"].notna().sum()), "peer_scope": R.peer_scope(p),
            "disparate_burden": summary.to_dict(orient="records")}
    (C.OUT / "forecast_meta.json").write_text(json.dumps(meta, indent=1, default=str) + "\n")
    print(json.dumps(meta, indent=1, default=str))


if __name__ == "__main__":
    main()
