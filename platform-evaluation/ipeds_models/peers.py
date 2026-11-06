"""Data-driven peer groups: nearest neighbours on structural features, compared with the Big Ten list.

    python ipeds_models/peers.py     # after build_panel.py -> artifacts/peers.json

Profile = mean of Fall 2021-2023 values (comparable years only, `exclude` flags masked) for every
institution in the Fall 2023 universe. Features are z-scored over that universe, missing values are set to
the universe median (and counted), and distance is Euclidean with equal weights. Two feature sets:
  * full: size, research intensity, graduate mix, staffing structure, tenure, pay, medical/hospital flags;
  * no_medical: the same without the medical-school / hospital / healthcare-staff features
    (a sensitivity check, because hospital payroll scope differs across IPEDS reporters).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import features as F  # noqa: E402

ART = HERE / "artifacts"
UOFI = {"145637": "UIUC", "145600": "UIC", "148654": "UIS"}
K = 15
FULL = ["log_fte", "log_staff", "staff_per_100_fte", "grad_fte_share", "log_research_per_fte", "research_exp_share",
        "research_share", "instr_share", "health_share", "tenured_share", "log_pay7", "ga_per_100_fte",
        "medical", "hospital", "public", "r1", "landgrant"]
NO_MED = [c for c in FULL if c not in ("medical", "hospital", "health_share")]
LABELS = {"log_fte": "Student FTE (log)", "log_staff": "Staff headcount (log)", "staff_per_100_fte": "Staff per 100 FTE",
          "grad_fte_share": "Graduate share of FTE", "log_research_per_fte": "Research $ per FTE (log)",
          "research_exp_share": "Research share of expenses", "research_share": "Research staff share",
          "instr_share": "Instructional staff share", "health_share": "Healthcare staff share",
          "tenured_share": "Tenured share", "log_pay7": "Faculty pay (log, real)", "ga_per_100_fte": "Grad assistants per 100 FTE",
          "medical": "Medical school", "hospital": "Hospital", "public": "Public", "r1": "R1", "landgrant": "Land grant"}


def profiles() -> pd.DataFrame:
    panel = pd.read_parquet(ART / "panel.parquet")
    feats = F.build_features(F.mask_excluded(panel)).reset_index()
    cur = feats[feats["year"] == 2023][["unitid", "name", "state", "sector", "carnegie_group", "is_big_ten"]]
    recent = feats[feats["year"].between(2021, 2023)]
    num = ["log_fte", "log_staff", "staff_per_100_fte", "grad_fte_share", "log_research_per_fte", "research_exp_share",
           "research_share", "instr_share", "health_share", "tenured_share", "log_pay7", "ga_per_100_fte"]
    agg = recent.groupby("unitid")[num].mean()
    flags = recent.groupby("unitid")[["medical", "hospital", "landgrant"]].max()
    prof = cur.set_index("unitid").join(agg).join(flags)
    prof["public"] = (prof["sector"] == 1).astype(float)
    prof["r1"] = (prof["carnegie_group"] == "R1").astype(float)
    return prof


def knn(prof: pd.DataFrame, cols: list[str], focal: str, k: int = K):
    X = prof[cols].astype(float)
    n_missing = X.isna().sum(axis=1)
    X = X.fillna(X.median())
    Z = (X - X.mean()) / X.std(ddof=0).replace(0, 1)
    d = np.sqrt(((Z - Z.loc[focal]) ** 2).sum(axis=1)).drop(index=focal)
    order = d.sort_values()
    rank = pd.Series(np.arange(1, len(order) + 1), index=order.index)
    return order, rank, Z, n_missing


def main() -> int:
    prof = profiles()
    big_ten = prof.index[prof["is_big_ten"].astype(bool)].tolist()
    out = {"k": K, "universe": int(len(prof)), "features": {"full": FULL, "no_medical": NO_MED}, "labels": LABELS,
           "campuses": {}}
    for u, short in UOFI.items():
        entry = {"name": prof.loc[u, "name"], "short": short}
        for fs_name, cols in (("full", FULL), ("no_medical", NO_MED)):
            order, rank, Z, nmiss = knn(prof, cols, u)
            top = order.head(K)
            neigh = [{"unitid": v, "name": prof.loc[v, "name"], "state": prof.loc[v, "state"],
                      "distance": round(float(top[v]), 3), "big_ten": bool(prof.loc[v, "is_big_ten"]),
                      "carnegie": prof.loc[v, "carnegie_group"], "sector": int(prof.loc[v, "sector"])} for v in top.index]
            bt = [{"unitid": v, "name": prof.loc[v, "name"], "rank": int(rank[v]), "distance": round(float(order[v]), 3),
                   "top_gaps": [{"feature": LABELS[c], "z_diff": round(float(Z.loc[v, c] - Z.loc[u, c]), 2)}
                                for c in (Z.loc[v] - Z.loc[u]).abs().sort_values(ascending=False).index[:3]]}
                  for v in big_ten if v in rank.index]
            bt.sort(key=lambda r: r["rank"])
            overlap = sum(n["big_ten"] for n in neigh)
            entry[fs_name] = {
                "neighbours": neigh, "big_ten_ranks": bt, "overlap_top_k_big_ten": int(overlap),
                "median_big_ten_rank": float(np.median([b["rank"] for b in bt])),
                "median_distance_top_k": float(top.median()),
                "median_distance_big_ten": float(np.median([b["distance"] for b in bt])),
                "focal_missing_features": int(nmiss[u]),
                "overlap_top_25_big_ten": int(sum(bool(prof.loc[v, "is_big_ten"]) for v in order.head(25).index)),
            }
        entry["profile"] = {c: (None if pd.isna(prof.loc[u, c]) else round(float(prof.loc[u, c]), 4)) for c in FULL}
        out["campuses"][u] = entry
    # Big Ten peer medians for context
    out["big_ten_profile_median"] = {c: round(float(prof.loc[big_ten, c].median()), 4) for c in FULL}
    (ART / "peers.json").write_text(json.dumps(out, indent=1, default=str))
    for u, e in out["campuses"].items():
        print(e["short"], "full: overlap", e["full"]["overlap_top_k_big_ten"], "median BT rank",
              e["full"]["median_big_ten_rank"], "| no_medical overlap", e["no_medical"]["overlap_top_k_big_ten"])
        print("   ", [n["name"] for n in e["full"]["neighbours"]])
    return 0


if __name__ == "__main__":
    sys.exit(main())
