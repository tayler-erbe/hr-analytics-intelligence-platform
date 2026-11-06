"""Final 8-quarter forecasts for Illinois and the Illinois-vs-peers view.

Reads data/backtest.parquet and data/metrics.json (from backtest.py), writes data/results.json.

Forecast origin = the last quarter in which the Illinois measure is published with a usable flag.
Intervals are empirical: quantiles of the model's own Illinois backtest log errors at each horizon
(all scored origins, including warm-up). The model shown first for each target is the one with the
lowest mean MASE over h = 1..8 in the backtest; seasonal naive is always shown for reference.
"""
from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent))
import backtest as B  # noqa: E402
import models as M  # noqa: E402
import series as S  # noqa: E402

DATA = Path(__file__).resolve().parent / "data"
PEER_START = S.parse_label("2000Q1")


def _r(x, nd=5):
    return None if x is None or (isinstance(x, float) and not math.isfinite(x)) else round(float(x), nd)


def final_forecasts(d: S.Data, bt: list[dict], met: dict) -> dict:
    errs: dict = {}
    for r in bt:
        if r["actual"]:
            errs.setdefault((r["target"], r["model"], r["h"]), []).append(math.log(r["actual"] / r["point"]))
    out = {}
    for name in S.TARGETS:
        T = B.last_obs(d, name)
        fc = B.forecast_at(S.truncate(d, T), name, T)
        avg = met["all"][name]["avg_h1_8"]
        best = min(avg, key=lambda m: avg[m]["mase"])
        y = S.target(d, name)[0]
        hist = [{"q": S.q_label(q), "y": _r(y[q])} for q in range(S.parse_label("2005Q1"), T + 1)]
        models = {}
        for m, f in fc.items():
            if not f or not f.get("point"):
                continue
            rows = []
            for h in range(1, M.H + 1):
                p = f["point"][h - 1]
                e = np.array(errs.get((name, m, h), []))
                row = {"q": S.q_label(T + h), "h": h, "point": _r(p)}
                for c, (a, b) in ((80, (0.10, 0.90)), (95, (0.025, 0.975))):
                    row[f"lo{c}"] = _r(p * math.exp(np.quantile(e, a))) if e.size >= B.MIN_ERRORS else None
                    row[f"hi{c}"] = _r(p * math.exp(np.quantile(e, b))) if e.size >= B.MIN_ERRORS else None
                row["n_errors"] = int(e.size)
                rows.append(row)
            models[m] = rows
        last4 = float(np.nanmean(y[T - 3: T + 1]))
        out[name] = {"label": S.TARGETS[name], "origin": S.q_label(T), "selected_model": best,
                     "selected_avg_mase": _r(avg[best]["mase"], 3),
                     "snaive_avg_mase": _r(avg["snaive"]["mase"], 3),
                     "last4_mean": _r(last4), "history": hist, "models": models,
                     "next4_sum_selected": _r(sum(r["point"] for r in models[best][:4]), 1)
                     if name not in S.RATE_TARGETS else None,
                     "provisional_quarters": [S.q_label(T - 1), S.q_label(T)]}
    return out


def _quant(v: np.ndarray, p: float):
    v = v[~np.isnan(v)]
    return _r(np.quantile(v, p)) if v.size else None


def peer_view(d: S.Data) -> dict:
    """Illinois against the 13-state peer distribution, and Illinois' deviation from peer change.

    level4: trailing 4-quarter mean (removes seasonality) for Illinois and peer quantiles.
    resid: log(IL_t / IL_{t-4}) - median over peers of log(y_t / y_{t-4}): the part of Illinois'
    year-over-year change that the peer states' common movement does not explain. z uses a robust
    scale (1.4826 x median absolute residual since 2000).
    """
    series = {"sep_rate": S.target(d, "sep_rate"), "sep_rate_55p": S.rate55(d),
              "hire_rate": S.target(d, "hire_rate"), "turnover": S.target(d, "turnover"),
              "share55": S.covariates(d)["share55"], "share65": S.covariates(d)["share65"]}
    labels = {"sep_rate": "Separation rate, all ages", "sep_rate_55p": "Separation rate, workers 55+",
              "hire_rate": "Hire rate, all ages", "turnover": "Stable-job turnover (TurnOvrS)",
              "share55": "Share of workforce aged 55+", "share65": "Share of workforce aged 65+"}
    out = {}
    for k, Y in series.items():
        L4 = S._roll_mean(Y, 4)
        with np.errstate(invalid="ignore", divide="ignore"):
            g = np.log(Y) - np.log(S._lag(Y, 4))
        last = int(np.max(np.where(~np.isnan(Y[0]))[0]))
        rows, res = [], []
        for q in range(PEER_START, last + 1):
            peers = L4[1:, q]
            pg = g[1:, q]
            med_g = float(np.nanmedian(pg)) if np.sum(~np.isnan(pg)) >= 5 else float("nan")
            resid = g[0, q] - med_g
            res.append(resid)
            rows.append({"q": S.q_label(q), "il": _r(L4[0, q]), "il_q": _r(Y[0, q]),
                         "p10": _quant(peers, .1), "p25": _quant(peers, .25), "p50": _quant(peers, .5),
                         "p75": _quant(peers, .75), "p90": _quant(peers, .9),
                         "n_peers": int(np.sum(~np.isnan(peers))),
                         "il_rank_from_top": int(np.sum(peers > L4[0, q])) + 1 if not np.isnan(L4[0, q]) else None,
                         "resid": _r(resid), "il_yoy": _r(g[0, q]), "peer_med_yoy": _r(med_g)})
        rv = np.array(res, float)
        scale = 1.4826 * np.nanmedian(np.abs(rv - np.nanmedian(rv)))
        for row in rows:
            row["z"] = _r(row["resid"] / scale, 2) if row["resid"] is not None else None
        ok = rv[~np.isnan(rv)]
        cum = np.nancumsum(np.where(np.isnan(rv), 0, rv))
        for row, c in zip(rows, cum):
            row["cum_resid"] = _r(c)
        flagged = [r["q"] for r in rows if r["z"] is not None and abs(r["z"]) > 2]
        out[k] = {"label": labels[k], "rows": rows, "resid_scale": _r(scale), "flagged_quarters": flagged,
                  "mean_resid_since_2010": _r(np.nanmean(rv[S.parse_label("2010Q1") - PEER_START:])),
                  "n_resid": int(ok.size)}
    # comparator industries (Illinois only), trailing 4-quarter separation rates
    comp = {}
    for ind, lab in (("6113", "Colleges & universities (6113)"), ("6111", "K-12 schools (6111)"),
                     ("6221", "General hospitals (6221)"), ("00", "All industries")):
        Y = S._roll_mean(S.target(d, "sep_rate", ind), 4)[0]
        comp[ind] = {"label": lab, "rows": [{"q": S.q_label(q), "v": _r(Y[q])} for q in range(PEER_START, d.n_q)
                                            if not np.isnan(Y[q])]}
    return {"series": out, "comparators": comp, "peers": S.STATES[1:]}


def main() -> None:
    d = S.load()
    bt = pq.read_table(DATA / "backtest.parquet").to_pylist()
    met = json.loads((DATA / "metrics.json").read_text())
    acq = json.loads((DATA / "acquisition_manifest.json").read_text())
    pman = json.loads((DATA / "panel_manifest.json").read_text())
    res = {"forecasts": final_forecasts(d, bt, met), "peer": peer_view(d), "metrics": met,
           "sources": [{k: f.get(k) for k in ("state", "filename", "url", "bytes", "sha256",
                                              "md5_matches_publisher", "version_qwi", "listing_size")}
                       for f in acq["files"]],
           "panel": {"sha256": pman["panel"] and pman["sha256"], "by_state": pman["by_state"]},
           "backtest_sha256": hashlib.sha256((DATA / "backtest.parquet").read_bytes()).hexdigest()}
    (DATA / "results.json").write_text(json.dumps(res, indent=1))
    for n, f in res["forecasts"].items():
        sel = f["models"][f["selected_model"]]
        print(f"{n:<10} origin {f['origin']} best={f['selected_model']:<13} avgMASE {f['selected_avg_mase']} "
              f"(snaive {f['snaive_avg_mase']}) next: " +
              ", ".join(f"{r['q']} {r['point']:.4g} [{r['lo80']:.4g},{r['hi80']:.4g}]" for r in sel[:4]))
    for k, v in res["peer"]["series"].items():
        last = [r for r in v["rows"] if r["il"] is not None][-1]
        print(f"peer {k:<13} last {last['q']} IL {last['il']} median {last['p50']} rank {last['il_rank_from_top']}"
              f"/{last['n_peers'] + 1} flagged {v['flagged_quarters'][-6:]} mean resid since 2010 {v['mean_resid_since_2010']}")


if __name__ == "__main__":
    main()
