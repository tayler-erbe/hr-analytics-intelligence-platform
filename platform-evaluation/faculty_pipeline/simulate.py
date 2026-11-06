"""Run the faculty pipeline scenario grid and write summaries for the page.

Grid per institution (UIUC, UIC, UIS):
  hiring budget  x {0.70, 0.85, 1.00, 1.15, 1.30} of the budget that buys the Fall 2023 IPEDS hires
  NTT share of hires = IPEDS 2023 share + {-0.20, -0.10, 0, +0.10, +0.20} (clipped to 0.05-0.95)
  retirement incentive x {1.0, 1.5, 2.0} on SURS-eligible retirement hazard in years 1-2
= 75 scenarios x 3 institutions. Enrollment scenarios (4) are applied to every run afterwards
because they change demand, not supply (hiring is budget-driven).

Usage:  python faculty_pipeline/simulate.py [--runs 300] [--seed 20231101] [--workers 4]
Output: faculty_pipeline/data/scenario_grid.json
"""
from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ProcessPoolExecutor
from itertools import product
from pathlib import Path

import numpy as np

import model as M

HERE = Path(__file__).resolve().parent
OUT = HERE / "data" / "scenario_grid.json"
INSTS = ["UIUC", "UIC", "UIS"]
BUDGETS = [0.70, 0.85, 1.00, 1.15, 1.30]
NTT_OFFSETS = [-0.20, -0.10, 0.0, 0.10, 0.20]
INCENTIVES = [1.0, 1.5, 2.0]
MODEL_VERSION = "faculty_pipeline_v1"


def pct(a, nd=1):
    q = np.percentile(a, [10, 50, 90], axis=0)
    return [np.round(x, nd).tolist() if nd else np.rint(x).astype(int).tolist() for x in q]


def salary_by_state(inst: M.Institution, cal: dict):
    sal = cal["institutions"][inst.key]["salary"]
    return {"PRE": M._avg(sal, ["3"]), "ASC": M._avg(sal, ["2"]), "FUL": M._avg(sal, ["1"]),
            "NTP": M._avg(sal, ["3"]), "NTL": inst.cost["NTL"]}


def summarize(inst: M.Institution, out: dict, cal: dict):
    st = out["stock"]
    fl = out["flows"]
    tot = sum(st[s] for s in M.STATES).astype(float)
    ten = (st["ASC"] + st["FUL"]).astype(float)
    tsys = ten + st["PRE"]
    exits = fl["retire"] + fl["separate"]
    sal = salary_by_state(inst, cal)
    payroll = sum(st[s] * sal[s] for s in M.STATES) / 1e6
    s = {
        "total": pct(tot, 0),
        "stock": {k: pct(st[k], 0) for k in M.STATES},
        "tenure_density": pct(ten / tot, 4),
        "tenure_system_share": pct(tsys / tot, 4),
        "ntt_faculty_share": pct((st["NTP"] + st["NTL"]) / tot, 4),
        "pre_per_tenured": pct(st["PRE"] / np.maximum(ten, 1), 4),
        "retire": pct(fl["retire"], 0),
        "retire_tenured": pct(fl["retire_tenured"], 0),
        "separate": pct(fl["separate"], 0),
        "exits": pct(exits, 0),
        "hire": pct(fl["hire"], 0),
        "tenure": pct(fl["tenure"], 0),
        "to_full": pct(fl["to_full"], 0),
        "pre_exit": pct(fl["pre_exit"], 0),
        "eligible": pct(fl["eligible"], 0),
        "payroll_musd": pct(payroll, 1),
        "cum_retire": pct(np.cumsum(fl["retire"], axis=1), 0),
        "rank_share": {k: pct(st[k] / tot, 4)[1] for k in M.STATES},
    }
    enr = {}
    for sc in M.ENROLLMENT_SCENARIOS:
        groups, idx, fte = M.enrollment_path(inst, sc)
        ratio = fte[None, :] / tot
        r0 = fte[0] / tot[:, :1]
        target = fte[None, :] / r0
        # Hires needed in year t if faculty tracked the constant-ratio target: replace this run's
        # exits plus the change in the target (growth adds, decline subtracts; floored at 0).
        need = np.zeros_like(tot)
        need[:, 1:] = np.maximum(0, exits[:, 1:] + target[:, 1:] - target[:, :-1])
        gidx = {g: pct(idx[gi][None, :] / (tot / tot[:, :1]), 3) for gi, g in enumerate(groups)}
        enr[sc] = {"ratio": pct(ratio, 2), "need": pct(need, 0), "group_ratio_index": gidx,
                   "fte": np.round(fte).astype(int).tolist()}
    s["enrollment"] = enr
    return s


def run_one(args):
    key, ii, b, off, inc, runs, seed = args
    cal = M.load_cal()
    inst = M.institution(cal, key)
    share = float(np.clip(round(inst.ntt_share_hires + off, 4), 0.05, 0.95))
    lev = M.Levers(budget_mult=b, ntt_share=share, incentive=inc)
    out = M.simulate(inst, lev, runs=runs, seed=seed, inst_index=ii, cal=cal)
    s = summarize(inst, out, cal)
    s.update({"key": f"{key}|{b:.2f}|{off:+.2f}|{inc:.1f}", "inst": key, "budget_mult": b, "ntt_offset": off,
              "ntt_share": share, "incentive": inc, "hires_per_year": out["hires_per_year"],
              "cost_per_hire": round(out["cost_per_hire"]), "budget_musd": round(inst.baseline_budget * b / 1e6, 2)})
    if b == 1.0 and off == 0.0 and inc == 1.0:   # flow-noise-only band for the baseline
        fx = M.simulate(inst, lev, runs=runs, seed=seed, inst_index=ii, cal=cal, fixed_params=True)
        tot = sum(fx["stock"][k] for k in M.STATES)
        s["fixed_params"] = {"total": pct(tot, 0), "retire": pct(fx["flows"]["retire"], 0),
                             "tenure_density": pct((fx["stock"]["ASC"] + fx["stock"]["FUL"]) / tot, 4)}
    return s


def institution_meta(cal, key):
    inst = M.institution(cal, key)
    p = M.draw_params(1, 0, 0, cal, fixed=True)
    X0 = M.start_state(inst.counts, inst.fit)
    mat = M.aggregate_matrix(inst, X0, p, run=0)
    age = {s: X0[s].sum(axis=(1, 2)).tolist() for s in M.STATES}
    return {
        "name": inst.name, "unitid": cal["institutions"][key]["unitid"], "counts": inst.counts,
        "hires_2023": inst.hires, "cost_per_hire": {k: round(v) for k, v in inst.cost.items()},
        "baseline_budget_musd": round(inst.baseline_budget / 1e6, 2), "baseline_hires": inst.baseline_hires,
        "ntt_share_hires": round(inst.ntt_share_hires, 4), "senior_share_tt": round(inst.senior_share_tt, 4),
        "tenured_sep": round(inst.s_ten, 4), "ntp_sep": round(inst.s_np, 4), "ntl_sep": round(inst.s_nl, 4),
        "fte0": inst.fte0, "group_share": inst.group_share, "diagnostics": inst.diagnostics,
        "transition_matrix_t0": {"states": M.AGG_STATES, "matrix": np.round(mat, 4).tolist(),
                                 "note": "Fixed literature defaults, no incentive, weighted by the Fall 2023 synthetic composition."},
        "start_age_by_state": age,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=300)
    ap.add_argument("--seed", type=int, default=20231101)
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    cal = M.load_cal()
    jobs = [(k, i, b, o, inc, a.runs, a.seed) for i, k in enumerate(INSTS)
            for b, o, inc in product(BUDGETS, NTT_OFFSETS, INCENTIVES)]
    t0 = time.time()
    if a.workers > 1:
        with ProcessPoolExecutor(a.workers) as ex:
            res = list(ex.map(run_one, jobs, chunksize=4))
    else:
        res = [run_one(j) for j in jobs]
    grid = {
        "model_version": MODEL_VERSION, "calibration_version": cal["calibration_version"],
        "runs": a.runs, "seed": a.seed, "base_year": M.BASE_YEAR, "horizon_years": M.HORIZON,
        "states": M.STATES, "state_labels": cal["states"], "levers": {"budget_mult": BUDGETS,
        "ntt_offset": NTT_OFFSETS, "incentive": INCENTIVES},
        "enrollment_scenarios": {k: {"label": v["label"], "growth": v["growth"], "default": v["default"]}
                                 for k, v in M.ENROLLMENT_SCENARIOS.items()},
        "groups": {k: v["label"] for k, v in cal["discipline_groups"].items()},
        "assumptions": M.ASSUMPTIONS,
        "institutions": {k: institution_meta(cal, k) for k in INSTS},
        "scenarios": res,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(grid, separators=(",", ":")))
    print(f"{len(res)} scenarios x {a.runs} runs in {time.time() - t0:.0f}s -> {OUT} ({OUT.stat().st_size / 1e6:.1f} MB)")
    for k in INSTS:
        b = next(s for s in res if s["key"] == f"{k}|1.00|+0.00|1.0")
        print(k, "baseline total P50 y0/y5/y10/y15:", [b["total"][1][t] for t in (0, 5, 10, 15)],
              "tenure density P50 y15:", b["tenure_density"][1][15], "retire P50 y1..5:", b["retire"][1][1:6])


if __name__ == "__main__":
    main()
