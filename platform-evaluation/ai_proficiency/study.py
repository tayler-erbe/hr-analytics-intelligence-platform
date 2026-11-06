"""Run every reliability, rater, item, standard-setting and fairness analysis on
the synthetic rating set and write artifacts/reliability_report.json.

Usage (from platform-evaluation/ai_proficiency/):  python study.py
The same code runs on a real pilot export if it has the columns of
data/ratings_long.csv; real exports stay on approved university machines.
"""
from __future__ import annotations

import itertools
import json
import math
from collections import defaultdict
from pathlib import Path

import numpy as np

import reliability as R
import rubric_io
import synth

HERE = Path(__file__).resolve().parent
ARTIFACTS = HERE / "artifacts"
REPORT_PATH = ARTIFACTS / "reliability_report.json"
LABELS = rubric_io.BADGE_ORDER


def _f(x):
    """JSON-safe floats (NaN -> None, numpy -> python)."""
    if isinstance(x, dict):
        return {str(k): _f(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_f(v) for v in x]
    if isinstance(x, (np.floating, float)):
        return None if math.isnan(float(x)) else round(float(x), 4)
    if isinstance(x, np.integer):
        return int(x)
    if isinstance(x, np.bool_):
        return bool(x)
    return x


def candidate_dim_scores(op_rows, dims, slot: str = "final"):
    """Per-candidate dimension means across tasks.

    slot 'final': adjudicated score if present, else mean of available reads.
    slot 'A' / 'B': first / second read only (for decision consistency).
    """
    per = defaultdict(lambda: defaultdict(list))  # (cand) -> (task, dim) -> [(phase, rater, score)]
    for r in op_rows:
        per[r["candidate_id"]][(r["task_id"], r["dim"])].append(r)
    out = {}
    for cand, cells in per.items():
        task_scores = defaultdict(list)
        ok = True
        for (task, dim), rs in cells.items():
            reads = [x for x in rs if x["phase"] == "operational"]
            adj = [x for x in rs if x["phase"] == "adjudication"]
            if slot == "final":
                s = float(adj[0]["score"]) if adj else float(np.mean([float(x["score"]) for x in reads]))
            else:
                i = 0 if slot == "A" else 1
                if len(reads) <= i:
                    ok = False
                    break
                s = float(reads[i]["score"])
            task_scores[dim].append(s)
        if ok:
            out[cand] = {d: float(np.mean(task_scores[d])) for d in dims}
    return out


def run(regenerate: bool = True) -> dict:
    if regenerate:
        synth.generate()
    rubric = rubric_io.load_rubric()
    dims = rubric_io.dimension_ids(rubric)
    dim_names = {d["id"]: d["name"] for d in rubric["dimensions"]}
    rows = synth.read_csv(synth.DATA / "ratings_long.csv")
    for r in rows:
        r["score"] = int(r["score"])
        r["session"] = int(r["session"])
        r["master"] = int(r["master"]) if r["master"] != "" else None
    cands = {c["candidate_id"]: c for c in synth.read_csv(synth.DATA / "candidates.csv")}
    known = json.loads((synth.DATA / "known_properties.json").read_text())
    raters = known["raters"]
    report: dict = {"generated_from": "synthetic seeded study (no real people)", "seed": known["seed"],
                    "rubric_version": rubric["version"], "dimensions": dim_names}

    # ---- 1. Calibration set: fully crossed --------------------------------
    cal = [r for r in rows if r["phase"] == "calibration"]
    arts = sorted({r["artifact_id"] for r in cal})
    cube = np.full((len(arts), len(raters), len(dims)), np.nan)
    ai = {a: i for i, a in enumerate(arts)}
    for r in cal:
        cube[ai[r["artifact_id"]], raters.index(r["rater"]), dims.index(r["dim"])] = r["score"]
    totals = cube.sum(axis=2)
    icc_total = R.icc(totals)
    ci = R.bootstrap_ci(lambda m: R.icc(m)["ICC(2,k)"], totals, n_boot=1000, seed=1)
    ci1 = R.bootstrap_ci(lambda m: R.icc(m)["ICC(2,1)"], totals, n_boot=1000, seed=2)
    per_dim = {}
    for j, d in enumerate(dims):
        m = cube[:, :, j]
        ic = R.icc(m)
        per_dim[d] = {"ICC(2,1)": ic["ICC(2,1)"], "ICC(2,k)": ic["ICC(2,k)"],
                      "alpha_ordinal": R.krippendorff_alpha(m.T, "ordinal")}
    units = cube.transpose(1, 0, 2).reshape(len(raters), -1)  # raters x (artifact, dim)
    pair_qwk = {}
    for a, b in itertools.combinations(range(len(raters)), 2):
        pair_qwk[f"{raters[a]}-{raters[b]}"] = R.weighted_kappa(units[a], units[b], [1, 2, 3, 4], "quadratic")
    report["calibration"] = {
        "n_artifacts": len(arts), "k_raters": len(raters),
        "total_score": {k: icc_total[k] for k in ("ICC(1,1)", "ICC(2,1)", "ICC(2,k)", "ICC(3,1)", "ICC(3,k)")},
        "total_score_ci95": {"ICC(2,k)": ci, "ICC(2,1)": ci1},
        "alpha_ordinal_all_cells": R.krippendorff_alpha(units, "ordinal"),
        "alpha_interval_all_cells": R.krippendorff_alpha(units, "interval"),
        "per_dimension": per_dim,
        "pairwise_qwk": pair_qwk,
        "pairwise_qwk_range": [min(pair_qwk.values()), max(pair_qwk.values())],
        "note": "ICC(2,k) is the reliability of the MEAN of k=6 raters; operational scores use 1-2 raters, so ICC(2,1) is the figure that applies to a single operational read.",
    }

    # ---- 2. Operational double scoring ------------------------------------
    op = [r for r in rows if r["phase"] in ("operational", "adjudication")]
    reads = defaultdict(list)
    for r in op:
        if r["phase"] == "operational":
            reads[(r["artifact_id"], r["dim"])].append(r)
    double_cells = {k: v for k, v in reads.items() if len(v) == 2}
    first = [v[0]["score"] for v in double_cells.values()]
    second = [v[1]["score"] for v in double_cells.values()]
    dbl_by_dim = {}
    for d in dims:
        cells = [v for (a, dd), v in double_cells.items() if dd == d]
        mat = np.full((len(raters), len(cells)), np.nan)
        for u, v in enumerate(cells):
            for x in v:
                mat[raters.index(x["rater"]), u] = x["score"]
        dbl_by_dim[d] = {"alpha_ordinal": R.krippendorff_alpha(mat, "ordinal"),
                         "qwk_slots": R.weighted_kappa([v[0]["score"] for v in cells],
                                                       [v[1]["score"] for v in cells], [1, 2, 3, 4]),
                         **R.exact_and_adjacent([v[0]["score"] for v in cells], [v[1]["score"] for v in cells])}
    n_adj = sum(1 for r in op if r["phase"] == "adjudication")
    n_art_total = len({r["artifact_id"] for r in op})
    n_art_double = len({a for (a, _d) in double_cells})
    report["double_scoring"] = {
        "n_artifacts": n_art_total, "n_double_scored_artifacts": n_art_double,
        "double_rate": n_art_double / n_art_total, "n_double_cells": len(double_cells),
        "qwk_slots_all": R.weighted_kappa(first, second, [1, 2, 3, 4]),
        **R.exact_and_adjacent(first, second),
        "adjudicated_cells": n_adj, "adjudication_rate": n_adj / len(double_cells),
        "per_dimension": dbl_by_dim,
        "note": "Raters rotate, so slot-based kappa (first vs second read) treats 'rater slot' as the rater; Krippendorff's alpha is the primary statistic because it handles rotating raters and missing cells.",
    }

    # ---- 3. Rater severity and drift --------------------------------------
    multi = [r for r in rows if r["phase"] in ("calibration", "anchor", "operational")]
    sev_records = [{"rater": r["rater"], "unit": r["artifact_id"], "dim": r["dim"], "score": r["score"]} for r in multi]
    severity = R.rater_severity(sev_records)
    drift = R.rater_drift([{"rater": r["rater"], "session": r["session"], "score": r["score"], "master": r["master"]}
                           for r in rows if r["master"] is not None])
    report["raters"] = {"severity": severity, "drift": drift}

    # ---- 4. Item analysis on candidate dimension scores --------------------
    final = candidate_dim_scores(op, dims, "final")
    ids = sorted(final)
    X = np.array([[final[c][d] for d in dims] for c in ids])
    ia = R.item_analysis(X, dims)
    tot = X.sum(axis=1)
    rel_for_sem = ia["alpha"]
    report["items"] = {**ia, "total_mean": float(tot.mean()), "total_sd": float(tot.std(ddof=1)),
                       "sem_total": R.sem(float(tot.std(ddof=1)), rel_for_sem),
                       "sem_basis": "Cronbach's alpha across the 8 dimensions (internal consistency). Rater error is reported separately (ICC(2,1)); a G-study would combine both."}
    # task-level difficulty
    task_scores = defaultdict(list)
    for (art, d), v in reads.items():
        task_scores[v[0]["task_id"]].append(np.mean([x["score"] for x in v]))
    report["tasks"] = {t: {"n_cells": len(s), "mean": float(np.mean(s))} for t, s in sorted(task_scores.items())}

    # ---- 5. Standard setting ------------------------------------------------
    ang_rows = synth.read_csv(synth.DATA / "angoff_panel.csv")
    angoff = {}
    for badge in rubric_io.BADGE_KEYS:
        angoff[badge] = {}
        for rnd in (1, 2):
            sel = [x for x in ang_rows if x["badge"] == badge and int(x["round"]) == rnd]
            panelists = sorted({x["panelist"] for x in sel})
            M = np.array([[float(next(x["rating"] for x in sel if x["panelist"] == p and x["dim"] == d))
                           for d in dims] for p in panelists])
            res = R.angoff(M, dims)
            res["impact"] = R.angoff_impact(tot, res["cut"], res["se_cut"])
            angoff[badge][f"round{rnd}"] = res
        angoff[badge]["provisional_cut"] = rubric["badges"][badge]["provisional_total_cut"]
        angoff[badge]["recommended_cut"] = round(angoff[badge]["round2"]["cut"] * 2) / 2  # nearest 0.5
    report["angoff"] = angoff
    rec_cuts = {b: angoff[b]["recommended_cut"] for b in angoff}

    # ---- 6. Badge outcomes and decision consistency ------------------------
    prov = {c: rubric_io.classify(rubric, final[c]) for c in ids}
    reco = {c: rubric_io.classify(rubric, final[c], rec_cuts) for c in ids}
    truth = {c: cands[c]["truth_badge"] for c in ids}
    A = candidate_dim_scores(op, dims, "A")
    B = candidate_dim_scores(op, dims, "B")
    both = sorted(set(A) & set(B))
    dc_double = R.decision_consistency([rubric_io.classify(rubric, A[c], rec_cuts) for c in both],
                                       [rubric_io.classify(rubric, B[c], rec_cuts) for c in both], LABELS)
    rep_rows = synth.read_csv(synth.DATA / "replication_ratings.csv")
    rep = {k: defaultdict(lambda: defaultdict(list)) for k in (1, 2, 3, 4)}
    for x in rep_rows:
        rep[int(x["replicate"])][x["candidate_id"]][x["dim"]].append(float(x["score"]))
    rep_cls = {k: [rubric_io.classify(rubric, {d: float(np.mean(rep[k][c][d])) for d in dims}, rec_cuts) for c in ids]
               for k in (1, 2, 3, 4)}
    dc_rep = R.decision_consistency(rep_cls[1], rep_cls[2], LABELS)
    dc_rep_cal = R.decision_consistency(rep_cls[3], rep_cls[4], LABELS)
    dc_binary = {b: R.decision_consistency([LABELS.index(x) >= LABELS.index(b) and "yes" or "no" for x in rep_cls[1]],
                                           [LABELS.index(x) >= LABELS.index(b) and "yes" or "no" for x in rep_cls[2]], ["no", "yes"])
                 for b in LABELS[1:]}
    acc = R.decision_consistency([reco[c] for c in ids], [truth[c] for c in ids], LABELS)
    # near-cut rule from rubric: second-score submissions within 1 point of a cut
    near = sum(1 for c in ids if any(abs(sum(final[c].values()) - cut) <= 1.0 for cut in rec_cuts.values()))
    report["badges"] = {
        "counts_provisional": {lab: sum(1 for v in prov.values() if v == lab) for lab in LABELS},
        "counts_recommended": {lab: sum(1 for v in reco.values() if v == lab) for lab in LABELS},
        "counts_truth": {lab: sum(1 for v in truth.values() if v == lab) for lab in LABELS},
        "recommended_cuts": rec_cuts,
        "decision_consistency_double_scored": dc_double,
        "decision_consistency_replication_synthetic": dc_rep,
        "decision_consistency_replication_calibrated_raters_synthetic": dc_rep_cal,
        "decision_consistency_by_cut_synthetic": {f"{b} or above": v for b, v in dc_binary.items()},
        "classification_accuracy_vs_truth_synthetic": acc,
        "n_within_1pt_of_a_cut": near,
        "note": "The double-scored estimate uses only the ~20% of candidates read twice, so its CI is wide. The replication and accuracy estimates exist only because the data are synthetic.",
    }

    # ---- 7. Fairness: DIF by role family and impact ratios -----------------
    fam = [cands[c]["role_family"] for c in ids]
    dif = {}
    families = known["families"]

    def one_dif(j, d, f, exclude=(), drop_items=()):
        keep = [i for i, x in enumerate(fam) if x not in exclude or x == f]
        Xk = X[keep]
        match_cols = [k for k in range(len(dims)) if k != j and dims[k] not in drop_items]
        rest = Xk[:, match_cols].sum(axis=1)
        strata = R.band(rest, 5)
        focal = [fam[i] == f for i in keep]
        item_sd = float(X[:, j].std(ddof=1))
        mh = R.mantel_haenszel_dif((Xk[:, j] >= 3).astype(int).tolist(), focal, strata)
        smd = R.standardized_mean_difference(Xk[:, j].tolist(), focal, strata)
        ratio = smd / item_sd if item_sd else None
        review = bool(mh["ets_class"] == "C" or (ratio is not None and abs(ratio) >= 0.25
                                                  and mh["p"] is not None and mh["p"] < 0.05))
        return {**mh, "smd": smd, "smd_over_sd": ratio, "review": review}

    # Stage 1: each family vs all others.
    for j, d in enumerate(dims):
        dif[d] = {f: one_dif(j, d, f) for f in families}
    # Stage 2 (purification, Holland & Thayer 1988 style), re-testing every
    # comparison:
    #  * item purification: dimensions flagged for the same focal family in
    #    stage 1 are removed from the matching score (DIF in one dimension
    #    otherwise distorts the match for all the others);
    #  * reference purification: families flagged on the same dimension in the
    #    opposite direction are removed from the reference group.
    for d in dims:
        for f in families:
            dif[d][f]["stage1_review"] = dif[d][f]["review"]
    for j, d in enumerate(dims):
        for f in families:
            st1 = dif[d][f]
            drop = tuple(dd for dd in dims if dd != d and dif[dd][f]["stage1_review"])
            sign = np.sign(st1["smd"])
            opp = tuple(g for g in families if g != f and dif[d][g]["stage1_review"]
                        and np.sign(dif[d][g]["smd"]) == -sign)
            if drop or opp:
                st2 = one_dif(j, d, f, exclude=opp, drop_items=drop)
                st1["stage2"] = {**st2, "reference_excludes": list(opp), "matching_excludes": list(drop)}
                st1["review"] = st2["review"]
    flagged = [[d, f] for d in dims for f in families if dif[d][f]["review"]]
    stage1 = [[d, f] for d in dims for f in families if dif[d][f]["stage1_review"]]
    report["fairness"] = {
        "dif": dif, "dif_flagged": flagged, "dif_flagged_stage1": stage1,
        "dif_method": "Focal = one role family, reference = all others; matched on rest score (sum of other 7 dimensions) in 5 quantile bands. MH on dimension mean >= 3; SMD on the dimension mean. Flag = ETS class C, or |SMD|/SD >= 0.25 with MH p < .05. Stage 2 re-tests every comparison with stage-1-flagged dimensions removed from the matching score and oppositely-flagged families removed from the reference (purification). With 30 per family these tests have low power and some false-positive risk; flags trigger SME content review, never automatic score changes.",
        "impact_catalyst_or_above": R.impact_ratios([reco[c] != "Not yet" for c in ids], fam),
        "impact_practitioner": R.impact_ratios([reco[c] == "Practitioner" for c in ids], fam),
    }

    # ---- 8. Recovery of planted properties ---------------------------------
    exp = known["expected"]
    sev_sorted = sorted(severity, key=lambda r: severity[r]["mean_dev"])
    drift_flagged = sorted(r for r, v in drift.items() if v["drift_flag"])
    bias_flagged = sorted(r for r, v in drift.items() if v["bias_flag"])
    weakest = min(ia["items"], key=lambda it: it["item_rest_r"])["item"]
    checks = [
        {"check": "Most severe rater recovered", "expected": exp["most_severe_rater"], "observed": sev_sorted[0]},
        {"check": "Most lenient rater recovered", "expected": exp["most_lenient_rater"], "observed": sev_sorted[-1]},
        {"check": "Only the drifting rater flagged for drift (trend)", "expected": exp["drifting_raters"], "observed": drift_flagged},
        {"check": "Static-bias raters flagged for bias vs master", "expected": exp["static_bias_raters"],
         "observed": [r for r in bias_flagged if r in exp["static_bias_raters"]]},
        {"check": "Weakest item (lowest item-rest r)", "expected": exp["weakest_item"], "observed": weakest},
        {"check": "Planted DIF detected (D7, Advising)", "expected": True, "observed": exp["dif_flag"] in flagged},
        {"check": "False DIF flags among the 39 null comparisons (<= 2, i.e. ~5%)", "expected": "<= 2",
         "observed": len([x for x in flagged if x != exp["dif_flag"]])},
        *[{"check": f"Angoff round-2 {b} cut within 0.5 of panel target", "expected": known["angoff_target_totals"][b],
           "observed": round(angoff[b]["round2"]["cut"], 2)} for b in rubric_io.BADGE_KEYS],
        {"check": "Panel converged (round-2 SD < round-1 SD, every badge)", "expected": True,
         "observed": all(angoff[b]["round2"]["sd_totals"] < angoff[b]["round1"]["sd_totals"] for b in angoff)},
    ]
    for c in checks:
        if c["expected"] == "<= 2":
            c["pass"] = c["observed"] <= 2
        elif "within 0.5" in c["check"]:
            c["pass"] = abs(c["observed"] - c["expected"]) <= 0.5
        else:
            c["pass"] = c["observed"] == c["expected"]
    report["recovery_checks"] = checks
    report = _f(report)
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2))
    return report


def seed_sensitivity(seeds=range(1, 21)) -> dict:
    """Re-run the whole synthetic study on other seeds and count how often each
    planted property is recovered. Uses a temporary directory; the main
    seed's data and report are left untouched."""
    import tempfile
    real_data, real_art, real_rep = synth.DATA, ARTIFACTS, REPORT_PATH
    counts, extra_flags, dc = defaultdict(int), 0, []
    seeds = list(seeds)
    g = globals()
    with tempfile.TemporaryDirectory() as tmp:
        try:
            synth.DATA = Path(tmp)
            g["ARTIFACTS"], g["REPORT_PATH"] = Path(tmp), Path(tmp) / "r.json"
            for sd in seeds:
                synth.generate(sd, synth.DATA)
                r = run(regenerate=False)
                for c in r["recovery_checks"]:
                    counts[c["check"]] += int(c["pass"])
                    if c["check"].startswith("False DIF flags"):
                        extra_flags += c["observed"]
                dc.append(r["badges"]["decision_consistency_replication_synthetic"]["p0"])
        finally:
            synth.DATA = real_data
            g["ARTIFACTS"], g["REPORT_PATH"] = real_art, real_rep
    return {"seeds": [seeds[0], seeds[-1]], "n_seeds": len(seeds),
            "pass_counts": dict(counts),
            "false_dif_flag_rate": extra_flags / (39 * len(seeds)),
            "replication_decision_consistency_p0": {"min": min(dc), "median": float(np.median(dc)), "max": max(dc)}}


if __name__ == "__main__":
    sens = _f(seed_sensitivity())
    rep = run()
    rep["seed_sensitivity"] = sens
    REPORT_PATH.write_text(json.dumps(rep, indent=2))
    print("seed sensitivity:", json.dumps(sens["pass_counts"], indent=1), "false DIF rate", sens["false_dif_flag_rate"])
    for c in rep["recovery_checks"]:
        print(("PASS " if c["pass"] else "FAIL ") + c["check"], "| expected", c["expected"], "| observed", c["observed"])
    cal = rep["calibration"]
    print("ICC(2,k) total:", cal["total_score"]["ICC(2,k)"], "ICC(2,1):", cal["total_score"]["ICC(2,1)"],
          "alpha ordinal:", cal["alpha_ordinal_all_cells"])
    print("double-scored alpha by dim:", {d: v["alpha_ordinal"] for d, v in rep["double_scoring"]["per_dimension"].items()})
    print("items alpha:", rep["items"]["alpha"], "SEM:", rep["items"]["sem_total"])
    print("badges:", rep["badges"]["counts_recommended"], "cuts:", rep["badges"]["recommended_cuts"])
    print("DC double:", rep["badges"]["decision_consistency_double_scored"]["p0"],
          rep["badges"]["decision_consistency_double_scored"]["kappa"],
          "DC rep:", rep["badges"]["decision_consistency_replication_synthetic"]["p0"],
          rep["badges"]["decision_consistency_replication_synthetic"]["kappa"],
          "DC calibrated:", rep["badges"]["decision_consistency_replication_calibrated_raters_synthetic"]["p0"],
          {k: v["p0"] for k, v in rep["badges"]["decision_consistency_by_cut_synthetic"].items()})
    print(f"wrote {REPORT_PATH}")
