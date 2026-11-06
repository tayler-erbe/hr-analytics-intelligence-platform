"""Rolling-origin backtest for Illinois NAICS 6113 targets.

For each target and each origin T (warm-up from 2003Q1, scored from 2010Q1), every model sees
only `truncate(data, T)` and forecasts T+1..T+8. Actuals are attached afterwards from the full
panel. Empirical ("calibrated") intervals for origin T use only that model's own Illinois errors
whose target quarter is <= T, so they are also free of look-ahead.

Usage (from platform-evaluation/):  python turnover_forecast/backtest.py [--targets sep_rate ...]
Outputs: turnover_forecast/data/backtest.parquet, turnover_forecast/data/metrics.json
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent))
import models as M  # noqa: E402
import series as S  # noqa: E402

DATA = Path(__file__).resolve().parent / "data"
WARMUP = S.parse_label("2003Q1")
EVAL_START = S.parse_label("2010Q1")
MODELS = ["snaive", "ets", "arima", "pooled_ridge", "gbm", "ensemble"]
ENSEMBLE_OF = ["ets", "arima", "pooled_ridge", "gbm"]  # fixed a priori, equal weights in logs
MIN_ERRORS = 12

_D: S.Data | None = None


def _init():
    global _D
    _D = S.load()


def forecast_at(d: S.Data, name: str, T: int, univariate: bool = True, glob: bool = True) -> dict:
    """All model forecasts for Illinois (state index 0) at origin T. `d` must already be truncated."""
    y = S.target(d, name)[0]
    out: dict[str, dict] = {}
    if univariate:
        out["snaive"] = M.seasonal_naive(y, T)
        for nm, fn in (("ets", M.ets), ("arima", M.arima)):
            try:
                out[nm] = fn(y, T)
            except Exception:  # noqa: BLE001  (a failed fit is recorded as missing, not hidden)
                out[nm] = {}
    if glob:
        des = M.design(d, name, T)
        out["pooled_ridge"] = M.pooled_ridge(des)
        out["gbm"] = M.gbm(des)
    if all(out.get(m, {}).get("point") for m in ENSEMBLE_OF):
        pts = np.array([out[m]["point"] for m in ENSEMBLE_OF], float)
        out["ensemble"] = {"point": list(np.exp(np.nanmean(np.log(pts), axis=0)))}
    return out


def _job(args) -> list[dict]:
    name, T = args
    d = S.truncate(_D, T)
    y_full = S.target(_D, name)[0]
    scale = M.mase_scale(S.target(d, name)[0][: T + 1])
    recs = []
    for model, fc in forecast_at(d, name, T).items():
        if not fc or not fc.get("point"):
            continue
        for h in range(1, M.H + 1):
            tq = T + h
            p = fc["point"][h - 1]
            if p is None or not np.isfinite(p):
                continue
            recs.append({"target": name, "model": model, "origin": T, "h": h, "tq": tq,
                         "actual": float(y_full[tq]) if tq < len(y_full) and not np.isnan(y_full[tq]) else None,
                         "point": float(p), "scale": scale,
                         **{f"nat_{k}": float(fc[k][h - 1]) if k in fc else None
                            for k in ("lo80", "hi80", "lo95", "hi95")}})
    return recs


def last_obs(d: S.Data, name: str) -> int:
    y = S.target(d, name)[0]
    return int(np.max(np.where(~np.isnan(y))[0]))


def add_empirical_intervals(recs: list[dict]) -> None:
    """lo/hi from the model's own earlier Illinois log errors (target quarter <= origin)."""
    by = {}
    for r in recs:
        by.setdefault((r["target"], r["model"], r["h"]), []).append(r)
    for rows in by.values():
        rows.sort(key=lambda r: r["origin"])
        done = [(r["tq"], math.log(r["actual"] / r["point"])) for r in rows if r["actual"]]
        for r in rows:
            errs = np.array([e for tq, e in done if tq <= r["origin"]])
            if errs.size >= MIN_ERRORS:
                lp = math.log(r["point"])
                for c, (a, b) in ((80, (0.10, 0.90)), (95, (0.025, 0.975))):
                    r[f"emp_lo{c}"] = math.exp(lp + np.quantile(errs, a))
                    r[f"emp_hi{c}"] = math.exp(lp + np.quantile(errs, b))
            else:
                for c in (80, 95):
                    r[f"emp_lo{c}"] = r[f"emp_hi{c}"] = None


def evaluate(recs: list[dict], exclude_covid: bool = False) -> dict:
    """Per target x model x horizon on the common set of (origin, h) scored by every model."""
    res = {}
    for name in sorted({r["target"] for r in recs}):
        rr = [r for r in recs if r["target"] == name and r["origin"] >= EVAL_START and r["actual"]
              and r["emp_lo80"] is not None and not (exclude_covid and S.is_covid(r["tq"]))]
        keysets = [{(r["origin"], r["h"]) for r in rr if r["model"] == m} for m in MODELS]
        common = set.intersection(*keysets)
        rows = {m: sorted((r for r in rr if r["model"] == m and (r["origin"], r["h"]) in common),
                          key=lambda r: (r["h"], r["origin"])) for m in MODELS}
        out = {}
        for h in range(1, M.H + 1):
            hs = {m: [r for r in rows[m] if r["h"] == h] for m in MODELS}
            base = np.array([M.mase(r["actual"], r["point"], r["scale"]) for r in hs["snaive"]])
            cell = {}
            for m in MODELS:
                xs = hs[m]
                if not xs:
                    continue
                y = np.array([r["actual"] for r in xs])
                f = np.array([r["point"] for r in xs])
                sc = np.array([r["scale"] for r in xs])
                ase = M.mase(y, f, sc)
                stat, p = M.dm_test(ase, base, h) if m != "snaive" else (float("nan"), float("nan"))
                def cov(pre, c):
                    lo = [r[f"{pre}lo{c}"] if r[f"{pre}lo{c}"] is not None else np.nan for r in xs]
                    hi = [r[f"{pre}hi{c}"] if r[f"{pre}hi{c}"] is not None else np.nan for r in xs]
                    return M.coverage(y, lo, hi) if not np.all(np.isnan(lo)) else None
                cell[m] = {"n": len(xs), "mase": float(ase.mean()), "smape": float(M.smape(y, f).mean()),
                           "rel_mase_vs_snaive": float(ase.mean() / base.mean()),
                           "dm_stat_vs_snaive": stat, "dm_p_vs_snaive": p,
                           "cov80_native": cov("nat_", 80), "cov95_native": cov("nat_", 95),
                           "cov80_empirical": cov("emp_", 80), "cov95_empirical": cov("emp_", 95)}
            out[str(h)] = cell
        avg = {}
        for m in MODELS:
            vals = [out[str(h)][m] for h in range(1, M.H + 1) if m in out[str(h)]]
            if vals:
                avg[m] = {k: float(np.mean([v[k] for v in vals if v[k] is not None]))
                          for k in ("mase", "smape", "rel_mase_vs_snaive", "cov80_empirical", "cov95_empirical")}
        n_orig = len({o for o, _ in common})
        res[name] = {"by_h": out, "avg_h1_8": avg, "n_origins": n_orig,
                     "first_origin": S.q_label(min(o for o, _ in common)) if common else None,
                     "last_origin": S.q_label(max(o for o, _ in common)) if common else None}
    return res


def run(targets: list[str], workers: int = 4) -> list[dict]:
    _init()
    jobs = [(n, T) for n in targets for T in range(WARMUP, last_obs(_D, n))]
    t0 = time.time()
    recs: list[dict] = []
    with ProcessPoolExecutor(workers, initializer=_init) as ex:
        for i, r in enumerate(ex.map(_job, jobs, chunksize=4)):
            recs.extend(r)
            if i % 100 == 0:
                print(f"  {i}/{len(jobs)} jobs, {time.time() - t0:.0f}s", flush=True)
    recs.sort(key=lambda r: (r["target"], r["model"], r["origin"], r["h"]))
    add_empirical_intervals(recs)
    return recs


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--targets", nargs="*", default=list(S.TARGETS))
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    recs = run(a.targets, a.workers)
    DATA.mkdir(exist_ok=True)
    pq.write_table(pa.Table.from_pylist(recs), DATA / "backtest.parquet")
    met = {"eval_start": S.q_label(EVAL_START), "warmup_start": S.q_label(WARMUP), "models": MODELS,
           "ensemble_of": ENSEMBLE_OF, "covid_window": list(S.COVID), "min_errors_for_empirical": MIN_ERRORS,
           "all": evaluate(recs), "excl_covid_targets": evaluate(recs, exclude_covid=True)}
    (DATA / "metrics.json").write_text(json.dumps(met, indent=1))
    for name, r in met["all"].items():
        print(f"\n{name}  origins {r['first_origin']}..{r['last_origin']} (n={r['n_origins']})")
        print("  model          " + " ".join(f"h{h:<5}" for h in range(1, 9)) + "  avg   cov80 cov95 (empirical)")
        for m in MODELS:
            row = [r["by_h"][str(h)].get(m, {}).get("mase", float("nan")) for h in range(1, 9)]
            av = r["avg_h1_8"].get(m, {})
            print(f"  {m:<14} " + " ".join(f"{v:5.2f} " for v in row) +
                  f" {av.get('mase', float('nan')):5.2f}  {av.get('cov80_empirical', float('nan')):.2f}  {av.get('cov95_empirical', float('nan')):.2f}")


if __name__ == "__main__":
    main()
