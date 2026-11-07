"""Rolling-origin backtest for Model B (protocol 3.4, thresholds 3.6).

Origins: every quarter from the first with 12 quarters of history (index 11) to data_as_of - 1 quarter; the first
8 are warm-up (errors only, for the empirical intervals). At each origin T the panel is truncated at T and every
learner forecasts h = 1..12 for every modelled series. Actuals are attached afterwards from the full panel.
Empirical intervals at origin T are quantiles of the method's own log1p errors whose target quarter is <= T
(minimum 12), pooled across series within target x method x horizon because 29 short series do not give 12
resolved errors per series and horizon early enough (recorded in the model card).

Metrics (protocol/scorers.py): MASE with the in-sample lag-4 seasonal-naive scale up to T, sMAPE, 80/95%
coverage (empirical, plus native for B-snaive / B-ets), mean signed error. Aggregated across series weighted by
mean headcount and unweighted; per-origin values kept. Thresholds B1..B7 via scorers.check_thresholds_b.

COVID: the protocol's with / without COVID-target-quarter metrics are both produced; the synthetic v3 data has
no COVID shock, so the two sets differ only by the quarters removed.

Usage (from platform-evaluation/):  python -m wap_prototype.model_b.backtest [--workers 4] [--targets ...]
Outputs: model_b/outputs/restricted/backtest.parquet and risk_backtest.parquet (series-level, unsuppressed),
model_b/outputs/metrics_b.json (aggregates over >= 29 series: publishable).
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
import pandas as pd

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from wap_prototype.model_b import config as C  # noqa: E402
from wap_prototype.model_b import learners as L  # noqa: E402
from wap_prototype.model_b import risk as R  # noqa: E402
from wap_prototype.model_b import series as S  # noqa: E402
from wap_prototype.protocol import scorers as SC  # noqa: E402

_P: S.Panel | None = None


def _init(panel: S.Panel | None = None) -> None:
    global _P
    _P = panel if panel is not None else S.load_panel()[0]


def origins(p: S.Panel) -> tuple[list[int], list[int]]:
    """(all origins, scored origins)."""
    all_o = list(range(C.MIN_HISTORY - 1, p.n_q - 1))
    return all_o, all_o[C.WARMUP_ORIGINS:]


def q_label(p: S.Panel, q: int) -> str:
    d = p.quarters[q]
    return f"{d.year}Q{(d.month - 1) // 3 + 1}"


def records_at(p_full: S.Panel, target: str, T: int, series_idx: list[int] | None = None) -> list[dict]:
    """Backtest rows for one (target, origin): every learner on the truncated panel, actuals from the full one."""
    p = S.truncate(p_full, T)
    fc = L.forecast_at(p, target, T, series_idx)
    y_full = p_full.y[target]
    recs = []
    for method, by_series in fc.items():
        for i, f in by_series.items():
            sid = p.registry.iloc[i]["series_id"]
            with np.errstate(divide="ignore", invalid="ignore"):
                scale = SC.mase_scale(p.y[target][i, : T + 1])
            for h in range(1, C.H + 1):
                tq = T + h
                pt = f["point"][h - 1]
                if pt is None or not np.isfinite(pt):
                    continue
                act = float(y_full[i, tq]) if tq < p_full.n_q and not np.isnan(y_full[i, tq]) else None
                recs.append({"target": target, "method": method, "series_id": sid, "series_idx": int(i), "origin": T, "h": h, "tq": tq,
                             "actual": act, "point": float(pt), "scale": float(scale),
                             **{f"nat_{k}": (float(f[k][h - 1]) if k in f and np.isfinite(f[k][h - 1]) else None) for k in ("lo80", "hi80", "lo95", "hi95")}})
    return recs


def _job(args) -> list[dict]:
    target, T = args
    return records_at(_P, target, T)


def add_empirical_intervals(df: pd.DataFrame) -> pd.DataFrame:
    """emp_lo/hi from the method's own earlier log1p errors with target quarter <= origin, pooled across series."""
    df = df.sort_values(["target", "method", "h", "origin", "series_idx"]).reset_index(drop=True)
    for c in ("emp_lo80", "emp_hi80", "emp_lo95", "emp_hi95"):
        df[c] = np.nan
    err = np.log1p(df["actual"]) - np.log1p(df["point"].clip(lower=0))
    for (_, _, _), idx in df.groupby(["target", "method", "h"]).groups.items():
        sub = df.loc[idx]
        done = sub[sub["actual"].notna()]
        done_tq, done_e = done["tq"].to_numpy(), err.loc[done.index].to_numpy()
        lp = np.log1p(sub["point"].clip(lower=0).to_numpy())
        for origin in np.unique(sub["origin"]):
            rows = sub.index[sub["origin"] == origin]
            e = done_e[done_tq <= origin]
            if e.size >= C.MIN_ERRORS:
                base = lp[sub.index.get_indexer(rows)]
                for c, (a, b) in ((80, (0.10, 0.90)), (95, (0.025, 0.975))):
                    df.loc[rows, f"emp_lo{c}"] = np.maximum(np.expm1(base + np.quantile(e, a)), 0.0)
                    df.loc[rows, f"emp_hi{c}"] = np.expm1(base + np.quantile(e, b))
    return df


# ------------------------------------------------------------------------------------------- evaluation
def _wmean(v: np.ndarray, w: np.ndarray) -> float:
    ok = ~np.isnan(v)
    return float(np.sum(v[ok] * w[ok]) / np.sum(w[ok])) if ok.any() and np.sum(w[ok]) > 0 else float("nan")


def evaluate(df: pd.DataFrame, p: S.Panel, exclude_covid: bool = False) -> dict:
    """Per target x horizon x method on the common (series, origin) set scored by every method, with empirical
    intervals available. Series-level means first, then headcount-weighted and unweighted means across series."""
    _, scored = origins(p)
    w_all = p.registry["mean_headcount"].to_numpy(float)
    covid_q = {q for q in range(p.n_q) if S.is_covid(p, q)}
    d = df[df["origin"].isin(scored) & df["actual"].notna()]
    if exclude_covid:
        d = d[~d["tq"].isin(covid_q)]
    res = {}
    for target in sorted(d["target"].unique()):
        dt_ = d[d["target"] == target]
        out, per_origin = {}, {m: {} for m in C.METHODS}
        for h in range(1, C.H + 1):
            dh = dt_[dt_["h"] == h]
            keys = [set(map(tuple, dh[dh["method"] == m][["series_idx", "origin"]].to_numpy())) for m in C.METHODS]
            common = set.intersection(*keys) if keys else set()
            if not common:
                out[str(h)] = {}
                continue
            dh = dh[[t in common for t in map(tuple, dh[["series_idx", "origin"]].to_numpy())]]
            cell = {}
            sn = dh[dh["method"] == "B-snaive"].set_index(["series_idx", "origin"])
            sn_mase = SC.mase(sn["actual"], sn["point"], sn["scale"])
            sn_by_series = pd.Series(sn_mase, index=sn.index).groupby(level=0).mean()
            for m in C.METHODS:
                x = dh[dh["method"] == m].set_index(["series_idx", "origin"]).sort_index()
                y, f, sc = x["actual"].to_numpy(), x["point"].to_numpy(), x["scale"].to_numpy()
                with np.errstate(divide="ignore", invalid="ignore"):
                    ase = pd.Series(SC.mase(y, f, sc), index=x.index)
                sm = pd.Series(SC.smape(y, f), index=x.index)
                err = pd.Series(f - y, index=x.index)
                g = pd.DataFrame({"mase": ase, "smape": sm, "err": err, "act": y}).groupby(level=0).mean()
                w = w_all[g.index.to_numpy()]
                cov = {}
                for pre in ("emp", "nat"):
                    for c in (80, 95):
                        lo, hi = x[f"{pre}_lo{c}"].to_numpy(float), x[f"{pre}_hi{c}"].to_numpy(float)
                        has = ~np.isnan(lo)
                        if not has.any():
                            cov[f"cov{c}_{pre}_w"] = cov[f"cov{c}_{pre}_u"] = None
                            cov[f"n_cov_{pre}"] = 0
                            continue
                        inside = pd.Series(((y >= lo) & (y <= hi)).astype(float), index=x.index).where(has).groupby(level=0).mean().dropna()
                        cov[f"cov{c}_{pre}_w"] = _wmean(inside.to_numpy(), w_all[inside.index.to_numpy()])
                        cov[f"cov{c}_{pre}_u"] = float(np.nanmean(inside))
                        cov[f"n_cov_{pre}"] = int(has.sum())
                sn_m = sn_by_series.reindex(g.index).to_numpy()
                cell[m] = {"n": int(len(x)), "n_series": int(len(g)), "n_origins": int(x.index.get_level_values(1).nunique()),
                           "mase_w": _wmean(g["mase"].to_numpy(), w), "mase_u": float(np.nanmean(g["mase"])),
                           "smape_w": _wmean(g["smape"].to_numpy(), w), "smape_u": float(np.nanmean(g["smape"])),
                           "rel_mase_w": (_wmean(g["mase"].to_numpy(), w) / _wmean(sn_m, w) if np.isfinite(_wmean(sn_m, w)) and _wmean(sn_m, w) > 0 else float("nan")),
                           "rel_mase_u": (float(np.nanmean(g["mase"]) / np.nanmean(sn_m)) if np.isfinite(np.nanmean(sn_m)) and np.nanmean(sn_m) > 0 else float("nan")),
                           "bias_w": _wmean(g["err"].to_numpy(), w), "bias_u": float(g["err"].mean()),
                           "mean_actual_w": _wmean(g["act"].to_numpy(), w), **cov}
                # per-origin relative MASE (headcount-weighted across series) for the protocol's per-origin report
                po = pd.DataFrame({"mase": ase, "sn": pd.Series(sn_mase, index=sn.index).reindex(x.index)}).reset_index()
                po["w"] = w_all[po["series_idx"]]
                for o, gg in po.groupby("origin"):
                    a, b = _wmean(gg["mase"].to_numpy(), gg["w"].to_numpy()), _wmean(gg["sn"].to_numpy(), gg["w"].to_numpy())
                    per_origin[m].setdefault(str(h), {})[q_label(p, int(o))] = (a / b) if b else None
            out[str(h)] = cell
        avg = {}
        for m in C.METHODS:
            for lo, hi, name in ((1, 4, "h1_4"), (5, 12, "h5_12"), (1, 12, "h1_12")):
                vals = [out[str(h)][m] for h in range(lo, hi + 1) if m in out.get(str(h), {})]
                if vals:
                    avg.setdefault(m, {})[name] = {k: (float(np.mean([v[k] for v in vals if v[k] is not None])) if any(v[k] is not None for v in vals) else None)
                                                  for k in ("mase_w", "mase_u", "rel_mase_w", "rel_mase_u", "smape_w", "smape_u",
                                                            "cov80_emp_w", "cov95_emp_w", "cov80_emp_u", "cov95_emp_u", "cov80_nat_w", "cov95_nat_w")}
        res[target] = {"by_h": out, "avg": avg, "per_origin_rel_mase_w": per_origin}
    return res


def hierarchy_check(df: pd.DataFrame, p: S.Panel) -> dict:
    """B6: dept forecasts summed to campus x family vs the directly modelled campus x family forecast at h=4,
    as a share of campus x family headcount. Undefined (NaN) when no dept series is modelled."""
    reg = p.registry
    dept = reg[(reg["level"] == "dept") & reg["modelled"]]
    out = {"n_dept_series_modelled": int(len(dept)), "discrepancy": float("nan"), "by_method": {}}
    if dept.empty:
        out["note"] = "no dept x family series reached mean headcount 10; every series is pooled to campus x family, so the bottom-up sum does not exist"
        return out
    _, scored = origins(p)
    d = df[(df["target"] == "headcount") & (df["h"] == 4) & df["origin"].isin(scored)]
    for m in C.METHODS:
        x = d[d["method"] == m].merge(reg[["series_id", "level", "campus", "role_family"]], on="series_id")
        bu = x[x["level"] == "dept"].groupby(["campus", "role_family", "origin"])["point"].sum()
        direct = x[x["level"] == "campus"].set_index(["campus", "role_family", "origin"])["point"]
        both = pd.concat([bu.rename("bu"), direct.rename("direct")], axis=1).dropna()
        out["by_method"][m] = float((both["bu"] - both["direct"]).abs().sum() / both["direct"].sum()) if len(both) else float("nan")
    return out


def risk_backtest(df: pd.DataFrame, p: S.Panel) -> pd.DataFrame:
    """Attrition-risk scores at every scored origin whose 4 quarters have resolved, for every method (B7)."""
    _, scored = origins(p)
    rows = []
    for m in C.METHODS:
        for T in scored:
            if T + R.RISK_H >= p.n_q:
                continue
            pt = df[(df["method"] == m) & (df["origin"] == T) & (df["h"] <= R.RISK_H) & df["target"].isin(["separations", "headcount"])]
            if pt.empty:
                continue
            points: dict[int, dict] = {}
            for (i, t), g in pt.groupby(["series_idx", "target"]):
                points.setdefault(int(i), {})[t] = g.sort_values("h")["point"].tolist()
            points = {i: v for i, v in points.items() if len(v.get("separations", [])) == R.RISK_H and len(v.get("headcount", [])) == R.RISK_H}
            sp, hp = R.error_paths(df, m, T)
            sc = R.score_units(S.truncate(p, T), T, points, sp, hp, seed=C.SEED + T, p_full=p)
            if not sc.empty:
                sc["method"] = m
                rows.append(sc)
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def threshold_inputs(ev: dict, hier: dict, risk: pd.DataFrame, method: str) -> dict:
    """The m dict for scorers.check_thresholds_b, headcount-weighted (protocol 3.6)."""
    def rel(target, band):
        return ev.get(target, {}).get("avg", {}).get(method, {}).get(band, {}).get("rel_mase_w")
    def worst(band):
        vals = [rel(t, band) for t in C.GATE_TARGETS]
        return float(max(v for v in vals if v is not None)) if any(v is not None for v in vals) else float("nan")
    covs80, covs95, ws = [], [], []
    for t in C.TARGETS:
        for h in range(1, C.H + 1):
            c = ev.get(t, {}).get("by_h", {}).get(str(h), {}).get(method)
            if c and c.get("cov80_emp_w") is not None:
                covs80.append(c["cov80_emp_w"]); covs95.append(c["cov95_emp_w"]); ws.append(c.get("n_cov_emp", c["n"]))
    hc4 = ev.get("headcount", {}).get("by_h", {}).get("4", {}).get(method, {})
    bias_share = (hc4["bias_w"] / hc4["mean_actual_w"]) if hc4 and hc4.get("mean_actual_w") else float("nan")
    rb = risk[risk["method"] == method] if len(risk) else risk
    prec, n_flag, n_dec = R.flag_precision(rb) if len(rb) else (float("nan"), 0, 0)
    return {"rel_mase_h1_4": worst("h1_4"), "rel_mase_h5_12": worst("h5_12"),
            "cov80": _wmean(np.array(covs80, float), np.array(ws, float)) if ws else float("nan"),
            "cov95": _wmean(np.array(covs95, float), np.array(ws, float)) if ws else float("nan"),
            "h4_bias_share": float(bias_share), "hierarchy_discrepancy": float(hier.get("by_method", {}).get(method, hier["discrepancy"])),
            "flag_precision": float(prec), "n_flagged": n_flag, "n_flag_decisions": n_dec,
            "rel_mase_h1_4_by_target": {t: rel(t, "h1_4") for t in C.TARGETS},
            "rel_mase_h5_12_by_target": {t: rel(t, "h5_12") for t in C.TARGETS}}


def _nan_to_none(o):
    if isinstance(o, dict):
        return {k: _nan_to_none(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_nan_to_none(v) for v in o]
    if isinstance(o, (float, np.floating)) and (math.isnan(o) or math.isinf(o)):
        return None
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    return o


def select_learner(checks: dict[str, dict], inputs: dict[str, dict]) -> dict:
    """Pre-registered rule (protocol 3.3 / 3.6): B-ens is published unless it fails a threshold that another
    method passes; a method failing B1 but passing B2-B5 is published for h >= 5 with B-snaive for h <= 4; when
    every method fails B1 and B2 the published forecast is B-snaive. B6 is not testable on this population
    (see hierarchy_check) and is ignored for selection because it does not separate the methods.
    Tie-break among candidates (not specified by the protocol; fixed here): most thresholds passed, then the
    lowest gating relative MASE at h = 1-4."""
    gating = ["B1", "B2", "B3", "B4", "B5", "B7"]
    cand = [m for m in C.METHODS if m != "B-snaive"]
    def score(m):
        return (sum(bool(checks[m][k]) for k in gating), -inputs[m]["rel_mase_h1_4"] if not math.isnan(inputs[m]["rel_mase_h1_4"]) else -9)
    chosen, reason = "B-ens", "default: B-ens published"
    fails_others_pass = [k for k in gating if not checks["B-ens"][k] and any(checks[m][k] for m in cand if m != "B-ens")]
    if fails_others_pass:
        chosen = max(cand, key=score)
        reason = f"B-ens fails {fails_others_pass} which another method passes; best by passes-then-MASE is {chosen}"
    ck = checks[chosen]
    horizons = {h: chosen for h in range(1, C.H + 1)}
    if not ck["B1"] and all(ck[k] for k in ("B2", "B3", "B4", "B5")):
        for h in range(1, 5):
            horizons[h] = "B-snaive"
        reason += f"; {chosen} fails B1 but passes B2-B5: published for h >= 5 only, B-snaive for h <= 4"
    if all(not checks[m]["B1"] and not checks[m]["B2"] for m in cand):
        chosen = "B-snaive"; horizons = {h: "B-snaive" for h in range(1, C.H + 1)}
        reason = "every method fails B1 and B2: the published forecast is seasonal naive with its native interval"
    return {"chosen": chosen, "by_horizon": {str(h): m for h, m in horizons.items()}, "reason": reason,
            "passes_all_gating": all(bool(ck[k]) for k in gating) if chosen != "B-snaive" else None}


def run(p: S.Panel, targets: list[str], workers: int = 4) -> pd.DataFrame:
    all_o, _ = origins(p)
    jobs = [(t, T) for t in targets for T in all_o]
    t0 = time.time()
    recs: list[dict] = []
    if workers <= 1:
        _init(p)
        for i, j in enumerate(jobs):
            recs.extend(_job(j))
    else:
        with ProcessPoolExecutor(workers, initializer=_init) as ex:
            for i, r in enumerate(ex.map(_job, jobs, chunksize=2)):
                recs.extend(r)
                if i % 40 == 0:
                    print(f"  {i}/{len(jobs)} jobs, {time.time() - t0:.0f}s", flush=True)
    df = pd.DataFrame(recs)
    return add_empirical_intervals(df)


def summarize(df: pd.DataFrame, p: S.Panel) -> tuple[dict, pd.DataFrame]:
    ev_all, ev_xc = evaluate(df, p), evaluate(df, p, exclude_covid=True)
    hier = hierarchy_check(df, p)
    risk = risk_backtest(df, p)
    inputs = {m: threshold_inputs(ev_all, hier, risk, m) for m in C.METHODS}
    checks = {m: SC.check_thresholds_b(inputs[m]) for m in C.METHODS}
    sel = select_learner(checks, inputs)
    all_o, scored = origins(p)
    met = {"protocol_version": C.PROTOCOL_VERSION, "seed": C.SEED, "methods": C.METHODS, "ensemble_of": C.ENSEMBLE_OF,
           "targets": C.TARGETS, "sensitivity_targets": C.SENSITIVITY_TARGETS, "horizons": C.H,
           "origins": {"all": [q_label(p, o) for o in all_o], "scored": [q_label(p, o) for o in scored], "warmup": C.WARMUP_ORIGINS},
           "covid_window": list(C.COVID), "covid_present_in_data": False, "min_errors_for_empirical": C.MIN_ERRORS,
           "empirical_interval_pooling": "errors pooled across series within target x method x horizon",
           "peer_scope": R.peer_scope(p), "n_series_modelled": int(p.registry["modelled"].sum()),
           "data_as_of": p.data_as_of.isoformat(), "thresholds": SC.THRESHOLDS_B,
           "all": ev_all, "excl_covid_targets": ev_xc, "hierarchy": hier, "threshold_inputs": inputs, "checks": checks, "selection": sel}
    return _nan_to_none(met), risk


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--targets", nargs="*", default=C.TARGETS + C.SENSITIVITY_TARGETS)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--summarize-only", action="store_true", help="recompute metrics_b.json from the saved backtest.parquet")
    a = ap.parse_args()
    p, _ = S.load_panel()
    if a.summarize_only:
        df = pd.read_parquet(C.RESTRICTED / "backtest.parquet")
    else:
        df = run(p, a.targets, a.workers)
        C.RESTRICTED.mkdir(parents=True, exist_ok=True)
        df.to_parquet(C.RESTRICTED / "backtest.parquet", index=False)
    met, risk = summarize(df, p)
    risk.to_parquet(C.RESTRICTED / "risk_backtest.parquet", index=False)
    C.OUT.mkdir(parents=True, exist_ok=True)
    (C.OUT / "metrics_b.json").write_text(json.dumps(met, indent=1) + "\n")
    for t in C.TARGETS:
        r = met["all"].get(t)
        if not r:
            continue
        print(f"\n{t}: relative MASE (headcount-weighted) vs B-snaive, scored origins {met['origins']['scored'][0]}..{met['origins']['scored'][-1]}")
        print("  method     " + " ".join(f"h{h:<4}" for h in range(1, C.H + 1)) + "  h1-4  h5-12 cov80 cov95")
        for m in C.METHODS:
            row = [r["by_h"].get(str(h), {}).get(m, {}).get("rel_mase_w") for h in range(1, C.H + 1)]
            av = r["avg"].get(m, {})
            print(f"  {m:<10} " + " ".join(f"{(v if v is not None else float('nan')):5.2f}" for v in row) +
                  f"  {(av.get('h1_4', {}).get('rel_mase_w') or float('nan')):5.2f} {(av.get('h5_12', {}).get('rel_mase_w') or float('nan')):5.2f}"
                  f" {(av.get('h1_12', {}).get('cov80_emp_w') or float('nan')):5.2f} {(av.get('h1_12', {}).get('cov95_emp_w') or float('nan')):5.2f}")
    print("\nthresholds:", json.dumps(met["checks"], indent=1))
    print("selection:", json.dumps(met["selection"], indent=1))


if __name__ == "__main__":
    main()
