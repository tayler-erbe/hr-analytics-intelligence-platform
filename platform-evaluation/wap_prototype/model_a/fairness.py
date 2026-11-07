"""Model A fairness review (protocol section 4), on every test-year person-period set of every backtest origin.

    python -m wap_prototype.model_a.fairness          # after train.py

Attributes: sex, race_eth_rpt_cd (as coded) from person_demographics_restricted and age_40_plus from the Phase 1
age_band (which carries a cut at 40). The demographics frame is loaded here and nowhere else in model_a.
Selection rule under test: top 10% of calibrated scores within each ladder step. Metrics come from
protocol/scorers.py (four_fifths, equalized_odds_gaps, calibration_by_group, fairness_summary). Group-level
rows (n >= 10) go to outputs/restricted/; only per-attribute summaries go to outputs/ and fact_model_quality.
"""
from __future__ import annotations

import argparse
import datetime as dt
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from wap_prototype.model_a import config as C  # noqa: E402
from wap_prototype.model_a import data as D  # noqa: E402
from wap_prototype.model_a import governance_bridge as G  # noqa: E402
from wap_prototype.protocol import scorers as S  # noqa: E402

FLAG_RANK = {"none": 0, "below_4_5": 1, "adverse": 2}


def attach_attributes(preds: pd.DataFrame, inputs: D.Inputs) -> pd.DataFrame:
    """Join the fairness attributes onto prediction rows (restricted, in memory only)."""
    demo = inputs.demographics[["person_id", C.FAIRNESS_ATTRIBUTES["sex"][0], C.FAIRNESS_ATTRIBUTES["race_eth_rpt_cd"][0]]]
    demo = demo.drop_duplicates("person_id").rename(columns={C.FAIRNESS_ATTRIBUTES["sex"][0]: "sex",
                                                               C.FAIRNESS_ATTRIBUTES["race_eth_rpt_cd"][0]: "race_eth_rpt_cd"})
    f = inputs.features[list(C.KEY_COLS)].copy()
    f["age_40_plus"] = D.age_40_plus(inputs.features)
    out = preds.merge(demo, on="person_id", how="left").merge(f, on=list(C.KEY_COLS), how="left")
    return out


def top_share_within_step(df: pd.DataFrame, p_col: str = "p_cal", share: float = C.TOP_SHARE_SELECTION, seed: int = C.SEED) -> np.ndarray:
    """1 for the top `share` of scores within each (ladder, level). Ties are broken by a seeded random draw (a tied
    selection is a lottery in practice; for the base-rate learners every score within a step is tied, so their
    audit result reflects chance, not the learner)."""
    d = df.reset_index(drop=True)
    d["_tie"] = np.random.default_rng(seed).random(len(d))
    order = d.sort_values([p_col, "_tie"], ascending=[False, True], kind="mergesort")
    sel = np.zeros(len(d), dtype=int)
    for _, idx in order.groupby(["ladder_code", "ladder_level"], sort=False).groups.items():
        k = int(math.ceil(share * len(idx)))
        sel[np.asarray(list(idx)[:k])] = 1
    return sel


def audit_set(d: pd.DataFrame, attribute: str) -> dict:
    """One attribute on one test set: four-fifths rows, equalized-odds gaps, calibration by group."""
    m = d[attribute].notna() & d["y"].notna()
    x = d[m]
    g, sel, y, p = x[attribute].astype(str).to_numpy(object), x["selected"].to_numpy(int), x["y"].to_numpy(int), x["p_cal"].to_numpy(float)
    ff = S.four_fifths(g, sel)
    eo = S.equalized_odds_gaps(g, sel, y)
    cal = S.calibration_by_group(g, y, p, min_n=C.CAL_BY_GROUP_MIN_N)
    return dict(ff=ff, eo=eo, cal=cal, summary=S.fairness_summary(ff, eo), n=int(m.sum()))


def historical_disparity(inputs: D.Inputs, origin: dt.date, horizon: int, attribute_frame: pd.DataFrame) -> dict:
    """Four-fifths test on the realized promotion label itself in the training years (labels as known at origin)."""
    tr = D.train_mask(inputs.features, origin)
    y = D.event_label(inputs.features, inputs.events, origin, horizon, "promotion")[tr]
    rows = inputs.features.loc[tr, list(C.KEY_COLS)].merge(attribute_frame, on=list(C.KEY_COLS), how="left")
    out = {}
    for a in C.FAIRNESS_ATTRIBUTES:
        m = rows[a].notna().to_numpy() & y.notna().to_numpy()
        out[a] = S.four_fifths(rows.loc[m, a].astype(str).to_numpy(object), y[m].to_numpy(int))
    return out


def run_audit(preds: pd.DataFrame, inputs: D.Inputs, runs: list[str] | None = None) -> dict:
    d = attach_attributes(preds, inputs)
    # main learners and the S1-S3 sensitivity runs (the ablation is never audited: its outputs are never published)
    runs = runs or sorted(r for r in d["run"].unique() if not r.endswith(C.ABLATION_SUFFIX))
    group_rows, cal_rows, hist_rows, summary_rows = [], [], [], []
    # attributes for EVERY feature row (the historical test runs on training-year rows, not on the prediction rows)
    attr_frame = attach_attributes(inputs.features[list(C.KEY_COLS)].copy(), inputs)[list(C.KEY_COLS) + list(C.FAIRNESS_ATTRIBUTES)]
    hist_done = set()
    for run in runs:
        for (origin, h), x in d[d["run"] == run].groupby(["origin", "horizon"], sort=True):
            x = x[x["y"].notna()].reset_index(drop=True)
            if len(x) == 0:
                continue
            x["selected"] = top_share_within_step(x)
            for a in C.FAIRNESS_ATTRIBUTES:
                r = audit_set(x, a)
                for row in r["ff"]:
                    eo_g = r["eo"]["by_group"].get(row["group"], {})
                    group_rows.append(dict(run=run, origin=origin, horizon=h, attribute=a, **row,
                                           tpr=eo_g.get("tpr"), fpr=eo_g.get("fpr")))
                for grp, c in r["cal"].items():
                    cal_rows.append(dict(run=run, origin=origin, horizon=h, attribute=a, group=grp, **c))
                s = r["summary"]
                summary_rows.append(dict(run=run, origin=origin.isoformat() if hasattr(origin, "isoformat") else str(origin), horizon=h,
                                         attribute=a, n=r["n"], **s))
            if (origin, h) not in hist_done:
                hist_done.add((origin, h))
                for a, rows in historical_disparity(inputs, origin, h, attr_frame).items():
                    for row in rows:
                        hist_rows.append(dict(origin=origin, horizon=h, attribute=a, **row))
    summary = pd.DataFrame(summary_rows)
    # per (run, horizon, attribute) across origins: worst flag, smallest ratio, largest gaps (protocol 2.6 A8 is
    # evaluated on the mean over origins' outcome, which for a flag is "any origin flagged")
    agg = (summary.groupby(["run", "horizon", "attribute"])
           .agg(min_impact_ratio=("min_impact_ratio", "min"), max_tpr_gap=("max_tpr_gap", "max"), max_fpr_gap=("max_fpr_gap", "max"),
                groups_suppressed=("groups_suppressed", "max"), groups_reported=("groups_reported", "min"), n=("n", "sum"),
                n_origins=("origin", "nunique"),
                n_origins_adverse=("fairness_flag", lambda s: int((s == "adverse").sum())),
                n_origins_below=("fairness_flag", lambda s: int((s == "below_4_5").sum())),
                fairness_flag=("fairness_flag", lambda s: max(s, key=lambda v: FLAG_RANK[v])))
           .reset_index())
    return {"groups": pd.DataFrame(group_rows), "calibration_by_group": pd.DataFrame(cal_rows), "historical": pd.DataFrame(hist_rows),
            "summary_by_origin": summary, "summary": agg}


def worst_flag(summary: pd.DataFrame, run: str, horizon: int) -> str:
    s = summary[(summary["run"] == run) & (summary["horizon"] == horizon)]
    if len(s) == 0:
        return "not_applicable"
    return max(s["fairness_flag"], key=lambda v: FLAG_RANK[v])


def write(res: dict, out_dir: Path) -> None:
    restricted = out_dir / "restricted"
    restricted.mkdir(parents=True, exist_ok=True)
    for name in ("groups", "calibration_by_group", "historical"):
        G.write_restricted(res[name], f"fairness_{name}", restricted)
        res[name].to_csv(restricted / f"fairness_{name}.csv", index=False)
    res["summary"].to_csv(out_dir / "fairness_summary.csv", index=False)
    res["summary_by_origin"].to_csv(out_dir / "fairness_summary_by_origin.csv", index=False)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    out = Path(a.out) if a.out else C.output_dir()
    inputs = D.load_inputs()
    preds = pd.read_parquet(out / "restricted" / "intermediate" / "predictions.parquet")
    res = run_audit(preds, inputs)
    write(res, out)
    print(res["summary"].to_string())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
