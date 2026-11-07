"""Model A evaluation against the pre-registered protocol (sections 2.5-2.7).

    python -m wap_prototype.model_a.evaluate            # after train.py and fairness.py

Per origin, horizon and learner: AUC-ROC, AUC-PR, Brier, Brier skill vs A-base-family and A-base-step,
calibration-in-the-large, logistic calibration slope / intercept, ECE (10 equal-count bins), decile table and the
reporting-grain coverage (ladder step x unit x horizon cells with n >= 10 test person-periods). Means over
origins are checked with scorers.check_thresholds_a; the primary learner is the best mean 12-month Brier skill
(vs A-base-family) among learners that pass A1-A8, ties (< 0.5 pp) to the simpler learner. Nothing is tuned on
test origins and no origin is dropped after seeing its result.

Also: sensitivity runs S1-S3 (reported, not gating), the age ablation (A9) and the 200-event label audit (2.7).
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from wap_prototype.model_a import config as C  # noqa: E402
from wap_prototype.model_a import data as D  # noqa: E402
from wap_prototype.model_a import fairness as FA  # noqa: E402
from wap_prototype.model_a import governance_bridge as G  # noqa: E402
from wap_prototype.protocol import scorers as S  # noqa: E402

METRIC_COLS = ["auc_roc", "auc_pr", "prevalence", "brier", "brier_skill_family", "brier_skill_step", "citl", "cal_slope",
               "cal_intercept", "ece", "grain_coverage", "grain_n_cells", "grain_mean_bias", "auc_roc_raw", "ece_raw", "citl_raw"]


# ------------------------------------------------------------------------------------------- per-set metrics
def grain_cells(x: pd.DataFrame, unit_col: str, p_col: str = "p_cal") -> list[dict]:
    """Reporting-grain cells (ladder step x unit) pooled over the test-year snapshots of one origin x horizon."""
    cells = []
    for (lad, lev, unit), g in x.groupby(["ladder_code", "ladder_level", unit_col], sort=True):
        c = S.expected_count_cell(g[p_col].to_numpy(float), observed=int(g["y"].sum()))
        cells.append(dict(ladder=lad, level=int(lev), unit=unit, **c))
    return cells


def metrics_for(x: pd.DataFrame, ref_family: np.ndarray, ref_step: np.ndarray, unit_col: str) -> dict:
    y, p, praw = x["y"].to_numpy(int), x["p_cal"].to_numpy(float), x["p_raw"].to_numpy(float)
    cal, cal_raw = S.calibration(y, p), S.calibration(y, praw)
    cov = S.reporting_grain_coverage(grain_cells(x, unit_col))
    return dict(n=int(len(y)), n_pos=int(y.sum()), auc_roc=S.auc_roc(y, p), auc_pr=S.auc_pr(y, p), prevalence=S.prevalence(y),
                brier=S.brier(y, p), brier_skill_family=S.brier_skill(y, p, ref_family), brier_skill_step=S.brier_skill(y, p, ref_step),
                citl=cal["citl"], cal_slope=cal["slope"], cal_intercept=cal["intercept"], ece=S.ece(y, p),
                grain_coverage=cov["coverage"], grain_n_cells=cov["n_cells"], grain_mean_bias=cov["mean_bias"],
                auc_roc_raw=S.auc_roc(y, praw), ece_raw=S.ece(y, praw), citl_raw=cal_raw["citl"])


def by_origin(preds: pd.DataFrame, unit_col: str) -> pd.DataFrame:
    keys = ["origin", "horizon", "snap_date", "person_id", "position_id"]
    p = preds[preds["y"].notna()]
    ref = {b: p[p["run"] == b][keys + ["p_cal"]].rename(columns={"p_cal": f"ref_{b}"}) for b in C.BASELINES}
    rows = []
    for (run, origin, h), x in p.groupby(["run", "origin", "horizon"], sort=True):
        x = x.merge(ref["A-base-family"], on=keys, how="left").merge(ref["A-base-step"], on=keys, how="left")
        if x["ref_A-base-family"].isna().any() or x["ref_A-base-step"].isna().any():
            raise RuntimeError(f"baseline predictions missing for {run} {origin} {h}: train the baselines in the same run")
        m = metrics_for(x, x["ref_A-base-family"].to_numpy(float), x["ref_A-base-step"].to_numpy(float), unit_col)
        rows.append(dict(run=run, origin=origin.isoformat() if hasattr(origin, "isoformat") else str(origin), horizon=int(h), **m))
    return pd.DataFrame(rows)


def mean_over_origins(bo: pd.DataFrame) -> pd.DataFrame:
    agg = bo.groupby(["run", "horizon"]).agg({**{c: "mean" for c in METRIC_COLS}, "n": "sum", "n_pos": "sum", "origin": "nunique"}).reset_index()
    agg = agg.rename(columns={"origin": "n_origins"})
    step = agg[agg["run"] == "A-base-step"][["horizon", "auc_roc", "auc_pr"]].rename(columns={"auc_roc": "auc_roc_step", "auc_pr": "auc_pr_step"})
    return agg.merge(step, on="horizon", how="left")


# ------------------------------------------------------------------------------------------- thresholds and selection
def threshold_table(mean: pd.DataFrame, fairness_summary: pd.DataFrame, ablation_gain: dict | None = None) -> pd.DataFrame:
    rows = []
    for _, r in mean.iterrows():
        run = r["run"]
        if ":" in run:
            continue
        flag = FA.worst_flag(fairness_summary, run, int(r["horizon"])) if len(fairness_summary) else "not_applicable"
        gain = (ablation_gain or {}).get((run, int(r["horizon"])), 0.0)
        m = dict(auc_roc=r["auc_roc"], auc_roc_step=r["auc_roc_step"], auc_pr=r["auc_pr"], prevalence=r["prevalence"], auc_pr_step=r["auc_pr_step"],
                 brier_skill_family=r["brier_skill_family"], brier_skill_step=r["brier_skill_step"], cal_slope=r["cal_slope"], citl=r["citl"],
                 ece=r["ece"], grain_coverage=r["grain_coverage"], fairness_flag=flag, age_ablation_gain=gain if gain == gain else 0.0)
        checks = S.check_thresholds_a(m)
        rows.append(dict(run=run, horizon=int(r["horizon"]), **{k: bool(v) for k, v in checks.items()}, passes_all=S.passes_all(checks),
                         fairness_flag=flag, age_ablation_gain=gain))
    return pd.DataFrame(rows)


def select_primary(mean: pd.DataFrame, thr: pd.DataFrame) -> dict:
    """Protocol 2.4: best mean Brier skill (vs A-base-family) at 12 months among ML learners passing A1-A8 at 12
    months; ties within 0.5 pp go to the simpler learner (logit -> RF -> GBM)."""
    m12 = mean[(mean["horizon"] == 12) & mean["run"].isin(C.ML_LEARNERS)].set_index("run")
    passing = [r for r in C.ML_LEARNERS if r in m12.index and bool(thr[(thr["run"] == r) & (thr["horizon"] == 12)]["passes_all"].any())]
    ranked = sorted(C.ML_LEARNERS, key=lambda r: -m12.loc[r, "brier_skill_family"] if r in m12.index else math.inf)
    if not passing:
        return {"primary": None, "published_default": "A-base-step", "outcome": "no skill beyond base rates",
                "candidates_ranked_by_12m_brier_skill": ranked, "passing_at_12m": []}
    best = max(passing, key=lambda r: m12.loc[r, "brier_skill_family"])
    best_skill = m12.loc[best, "brier_skill_family"]
    tied = [r for r in passing if best_skill - m12.loc[r, "brier_skill_family"] < C.TIE_MARGIN]
    primary = min(tied, key=lambda r: C.SIMPLICITY_ORDER.index(r))
    return {"primary": primary, "published_default": primary, "outcome": "learner passes thresholds at 12 months",
            "candidates_ranked_by_12m_brier_skill": ranked, "passing_at_12m": passing, "tie_set": tied}


def ablation_gains(mean: pd.DataFrame) -> dict:
    """AUC-ROC gain of '<learner>:age' over '<learner>' per horizon (NaN when the ablation was not run)."""
    out = {}
    m = mean.set_index(["run", "horizon"])
    for lr in C.ML_LEARNERS:
        for h in C.HORIZONS:
            a, b = (f"{lr}{C.ABLATION_SUFFIX}", h), (lr, h)
            out[(lr, h)] = float(m.loc[a, "auc_roc"] - m.loc[b, "auc_roc"]) if a in m.index and b in m.index else float("nan")
    return out


def sensitivity_table(mean: pd.DataFrame) -> pd.DataFrame:
    rows = []
    m = mean.set_index(["run", "horizon"])
    for lr in C.ML_LEARNERS:
        for s, desc in C.SENSITIVITIES.items():
            for h in C.HORIZONS:
                k, base = (f"{lr}:{s}", h), (lr, h)
                if k in m.index:
                    r = m.loc[k]
                    rows.append(dict(learner=lr, sensitivity=s, description=desc, horizon=h, auc_roc=r["auc_roc"], auc_pr=r["auc_pr"],
                                     prevalence=r["prevalence"], brier_skill_family=r["brier_skill_family"], brier_skill_step=r["brier_skill_step"],
                                     citl=r["citl"], cal_slope=r["cal_slope"], ece=r["ece"], grain_coverage=r["grain_coverage"],
                                     auc_roc_main=m.loc[base, "auc_roc"] if base in m.index else float("nan"),
                                     brier_skill_family_main=m.loc[base, "brier_skill_family"] if base in m.index else float("nan")))
    return pd.DataFrame(rows)


# ------------------------------------------------------------------------------------------- calibration tables
def decile_tables(preds: pd.DataFrame, runs: list[str]) -> pd.DataFrame:
    rows = []
    p = preds[preds["y"].notna() & preds["run"].isin(runs)]
    for (run, h), x in p.groupby(["run", "horizon"], sort=True):
        for r in S.decile_table(x["y"].to_numpy(int), x["p_cal"].to_numpy(float)):
            rows.append(dict(run=run, horizon=int(h), origin="pooled", **r))
        for origin, xo in x.groupby("origin", sort=True):
            for r in S.decile_table(xo["y"].to_numpy(int), xo["p_cal"].to_numpy(float)):
                rows.append(dict(run=run, horizon=int(h), origin=origin.isoformat(), **r))
    return pd.DataFrame(rows)


def grain_cell_table(preds: pd.DataFrame, run: str, unit_col: str) -> pd.DataFrame:
    """The reporting-grain backtest cells of one learner (suppressed below k, complementary within ladder and
    within step across units), for publication next to the coverage number."""
    rows = []
    p = preds[preds["y"].notna() & (preds["run"] == run)]
    for (origin, h), x in p.groupby(["origin", "horizon"], sort=True):
        for c in grain_cells(x, unit_col):
            rows.append(dict(origin=origin.isoformat(), horizon=int(h), **c))
    df = pd.DataFrame(rows)
    if len(df) == 0:
        return df
    df = G.suppress_multi(df, "n", ["expected", "p10", "p90", "observed", "inside"],
                          [["origin", "horizon", "unit", "ladder"], ["origin", "horizon", "ladder", "level"]])
    return df.drop(columns=["suppression_reason"])


# ------------------------------------------------------------------------------------------- label audit (2.7)
AUDIT_EVIDENCE = ["event_id", "person_id", "position_id", "job_suffix", "event_date", "event_type", "event_subtype", "move_kind",
                  "level_direction", "from_class_key", "to_class_key", "from_p_class", "to_p_class", "from_ladder", "to_ladder",
                  "from_ladder_level", "to_ladder_level", "from_role_family", "to_role_family", "from_role_level", "to_role_level",
                  "from_org_code", "to_org_code", "cross_org", "cross_campus", "from_salary", "to_salary", "from_fte", "to_fte",
                  "change_reason_code", "change_reason_desc", "change_reason_label", "label_status", "rule_version"]


def label_audit(events: pd.DataFrame, n: int = C.LABEL_AUDIT_N, seed: int = C.SEED) -> tuple[pd.DataFrame, dict]:
    """Stratified (by to_ladder, proportional allocation) sample of `n` candidate promotion events with the rule
    evidence columns and blank HR columns, plus the PROVISIONAL agreement against the generator's planted
    change-reason codes (a stand-in for HR's definition until HR reviews the sheet on the approved machine)."""
    pr = events[events["event_type"] == "promotion"].sort_values(["event_id"], kind="mergesort").reset_index(drop=True)
    rng = np.random.default_rng(seed)
    strata = pr.groupby("to_ladder", sort=True).size()
    alloc = (strata / strata.sum() * n).round().astype(int)
    diff = n - int(alloc.sum())
    if diff != 0:   # fix rounding on the largest stratum
        alloc[alloc.idxmax()] += diff
    parts = []
    for lad, k in alloc.items():
        idx = pr.index[pr["to_ladder"] == lad].to_numpy()
        take = rng.choice(idx, size=min(int(k), len(idx)), replace=False)
        parts.append(pr.loc[np.sort(take)])
    sample = pd.concat(parts).sort_values(["to_ladder", "event_date", "event_id"], kind="mergesort").reset_index(drop=True)
    sheet = sample[[c for c in AUDIT_EVIDENCE if c in sample.columns]].copy()
    sheet.insert(0, "audit_row", np.arange(1, len(sheet) + 1))
    sheet["hr_classification"] = ""     # promotion | reclassification | lateral | other  (HR fills in)
    sheet["hr_reviewer"] = ""
    sheet["hr_review_date"] = ""
    sheet["hr_notes"] = ""
    # provisional stand-in: the generator planted change-reason codes; the mapping labels OT010 and PR001 'promotion'
    stand_in = sheet["change_reason_label"].fillna("").eq("promotion")
    # reverse direction over ALL events: source rows labelled promotion that the rule did not call promotion
    src_prom = events[events["change_reason_label"].fillna("").eq("promotion")]
    reverse = float((src_prom["event_type"] == "promotion").mean()) if len(src_prom) else float("nan")
    agreement = float(stand_in.mean())
    summary = dict(status="PROVISIONAL", n_sampled=int(len(sheet)), n_promotion_events=int(len(pr)), strata="to_ladder", seed=seed,
                   agreement_rule_vs_planted_codes=agreement,
                   reverse_share_of_source_promotion_codes_called_promotion=reverse, n_source_promotion_codes=int(len(src_prom)),
                   code_mix=sample["change_reason_code"].value_counts().to_dict(), threshold=C.LABEL_AUDIT_MIN_AGREEMENT,
                   label_name={12: "promoted_12m", 18: "promoted_18m"} if agreement >= C.LABEL_AUDIT_MIN_AGREEMENT
                   else {12: "upward_transition_12m", 18: "upward_transition_18m"},
                   hr_review="NOT DONE: the stand-in compares the candidate rule with the synthetic generator's planted change-reason codes, "
                             "not with HR's definition of promotion vs reclassification vs lateral. On real data HR completes "
                             "label_audit_sheet.csv on the approved machine and the agreement is recomputed from hr_classification.")
    return sheet, summary


# ------------------------------------------------------------------------------------------- driver
def run(preds: pd.DataFrame, inputs: D.Inputs, fairness_summary: pd.DataFrame, unit_col: str, out_dir: Path | None = None,
        write: bool = True, seed: int = C.SEED) -> dict:
    out_dir = Path(out_dir) if out_dir else C.output_dir()
    bo = by_origin(preds, unit_col)
    mean = mean_over_origins(bo)
    gains = ablation_gains(mean)
    thr0 = threshold_table(mean, fairness_summary)                 # A1-A8 first (A9 needs the primary)
    sel = select_primary(mean, thr0)
    a9_run = sel["primary"] or "A-gbm"
    thr = threshold_table(mean, fairness_summary, {(a9_run, h): gains[(a9_run, h)] for h in C.HORIZONS})
    sheet, audit = label_audit(inputs.events, seed=seed)
    deciles = decile_tables(preds, list(C.LEARNERS))
    cells = grain_cell_table(preds, sel["published_default"], unit_col)
    sens = sensitivity_table(mean)
    thr_rec = thr.to_dict(orient="records")
    ev = {
        "protocol_version": C.PROTOCOL_VERSION, "data_as_of": inputs.data_as_of.isoformat(), "unit_level": unit_col,
        "origins": sorted(bo["origin"].unique().tolist()), "selection": sel, "label_audit": audit,
        "thresholds": thr_rec,
        "age_ablation": {"primary_or_gbm": a9_run,
                         "gain_auc_roc_by_horizon": {str(h): gains[(a9_run, h)] for h in C.HORIZONS},
                         "gain_auc_roc_all_learners": {f"{lr}:{h}": v for (lr, h), v in gains.items()},
                         "A9_review_required": {str(h): bool(gains[(a9_run, h)] > S.THRESHOLDS_A["A9_age_ablation_gain_review"])
                                                if gains[(a9_run, h)] == gains[(a9_run, h)] else None for h in C.HORIZONS}},
        "thresholds_constants": {k: (list(v) if isinstance(v, tuple) else v) for k, v in S.THRESHOLDS_A.items()},
        "mean_over_origins": mean.to_dict(orient="records"),
        "pass_fail_by_learner": {f"{r['run']}:{r['horizon']}": {k: r[k] for k in ("A1", "A2", "A3", "A3b", "A4", "A5", "A6", "A7", "A8", "A9_review_required", "passes_all")}
                                 for r in thr_rec},
    }
    result = {"by_origin": bo, "mean": mean, "thresholds": thr, "selection": sel, "deciles": deciles, "grain_cells": cells,
              "sensitivity": sens, "label_audit_sheet": sheet, "label_audit": audit, "evaluation": ev}
    if write:
        out_dir.mkdir(parents=True, exist_ok=True)
        bo.to_csv(out_dir / "metrics_by_origin.csv", index=False)
        mean.to_csv(out_dir / "metrics_mean.csv", index=False)
        thr.to_csv(out_dir / "thresholds.csv", index=False)
        deciles.to_csv(out_dir / "calibration_deciles.csv", index=False)
        cells.to_csv(out_dir / "grain_cells_backtest.csv", index=False)
        sens.to_csv(out_dir / "sensitivity.csv", index=False)
        (out_dir / "evaluation.json").write_text(json.dumps(ev, indent=1, sort_keys=True, default=_json_default), encoding="utf-8")
        (out_dir / "label_audit.json").write_text(json.dumps(audit, indent=1, sort_keys=True, default=_json_default), encoding="utf-8")
        res = out_dir / "restricted"
        res.mkdir(parents=True, exist_ok=True)
        sheet.to_csv(res / "label_audit_sheet.csv", index=False)
        G.write_restricted(sheet, "label_audit_sheet", res)
    return result


def _json_default(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return None if np.isnan(o) else float(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if hasattr(o, "isoformat"):
        return o.isoformat()
    raise TypeError(type(o))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    out = Path(a.out) if a.out else C.output_dir()
    inputs = D.load_inputs()
    preds = pd.read_parquet(out / "restricted" / "intermediate" / "predictions.parquet")
    fs = out / "fairness_summary.csv"
    if not fs.exists():
        FA.write(FA.run_audit(preds, inputs), out)
    fairness_summary = pd.read_csv(fs)
    r = run(preds, inputs, fairness_summary, C.UNIT_COLUMN[C.unit_level()], out)
    print(r["thresholds"].to_string())
    print(json.dumps(r["selection"], indent=1))
    print("label audit (provisional):", r["label_audit"]["agreement_rule_vs_planted_codes"], "->", r["label_audit"]["label_name"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
