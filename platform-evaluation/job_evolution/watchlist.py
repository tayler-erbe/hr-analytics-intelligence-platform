"""Map job-evolution evidence to University role families and SUCSS classes, and
build the data bundle for the offline explorer.

Inputs : artifacts/{occ_state,transitions,task_changes,tech_changes,predictions_latest}.parquet,
         artifacts/{backtest_report,timing_model,update_validation,release_inventory}.json,
         derived/tech.parquet, sucss_mapping/outputs/candidates.parquet, contract/sucss_class.parquet
Outputs: artifacts/occupation_indicators.parquet, artifacts/watchlist.json,
         artifacts/sucss_class_watch.parquet, artifacts/explorer_data.json

Role level only. No person-level data is read or produced.
"""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict

import duckdb
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from common import ART, CAVEATS, CONTRACT, DERIVED, PROTOCOL, REL_INDEX, RELEASES, SUCSS_CANDIDATES, dump_json, \
    release_year, rnd

VERS = [v for v, _, _ in RELEASES]
LATEST = VERS[-1]

# Copied from reskilling/build_pathways.py FAMILIES (reskilling_pathways_v1) so both
# prototypes use the same UIUC-relevant role families. First prefix match wins.
FAMILIES = [
    ("management", "Admin, IT, HR, finance & facilities management",
     ["11-3012", "11-3013", "11-3021", "11-3031", "11-3111", "11-3121", "11-3131", "11-9033"]),
    ("hr", "Human resources & training", ["13-1071", "13-1075", "13-1141", "13-1151", "43-4161"]),
    ("finance", "Finance & accounting", ["13-2", "43-3"]),
    ("business", "Business operations", ["13-1"]),
    ("it", "Information technology & data", ["15-12", "15-2051"]),
    ("library", "Library & archives", ["25-40", "43-4121"]),
    ("student_services", "Student services & academic support", ["21-1012", "25-9031"]),
    ("admin", "Office & administrative support", ["43-"]),
    ("facilities", "Facilities & building services",
     ["37-", "47-2031", "47-2111", "47-2141", "47-2152", "49-1011", "49-9021", "49-9071", "51-8021"]),
]
FAMILY_LABEL = {f: l for f, l, _ in FAMILIES}

# Technology adoption curves: transparent regex per technology (case-insensitive).
TECH_CURVES = [
    ("Python", r"\bpython\b"), ("SQL", r"\bsql\b|structured query"), ("Tableau", r"tableau"),
    ("Microsoft Power BI", r"power ?bi"), ("Salesforce", r"salesforce"), ("Workday", r"\bworkday\b"),
    ("ServiceNow", r"servicenow"), ("Microsoft Teams", r"microsoft teams"), ("Slack", r"\bslack\b"),
    ("Zoom", r"\bzoom\b"), ("Amazon Web Services", r"amazon web services|\baws\b"),
    ("Microsoft Azure", r"azure"), ("Git / GitHub", r"\bgit\b|github"), ("Atlassian JIRA", r"\bjira\b"),
    ("ChatGPT / OpenAI", r"chatgpt|openai"), ("TensorFlow / PyTorch", r"tensorflow|pytorch"),
]


def family_of(code: str | None) -> str | None:
    if not code:
        return None
    for fid, _, prefixes in FAMILIES:
        if any(code.startswith(p) for p in prefixes):
            return fid
    return None


def q(con, sql):
    rel = con.execute(sql)
    cols = [d[0] for d in rel.description]
    return [dict(zip(cols, r)) for r in rel.fetchall()]


def pct_rank(vals: list) -> list:
    """Percentile rank in [0, 1]; None stays None."""
    arr = [(v, i) for i, v in enumerate(vals) if v is not None]
    out = [None] * len(vals)
    if not arr:
        return out
    srt = sorted(v for v, _ in arr)
    n = len(srt)
    import bisect
    for v, i in arr:
        lo = bisect.bisect_left(srt, v)
        hi = bisect.bisect_right(srt, v)
        out[i] = ((lo + hi) / 2) / n
    return out


def mean(xs):
    xs = [x for x in xs if x is not None]
    return float(np.mean(xs)) if xs else None


def main() -> int:
    con = duckdb.connect()
    preds = q(con, f"select * from '{ART / 'predictions_latest.parquet'}'")
    trans = q(con, f"select * from '{ART / 'transitions.parquet'}'")
    states = q(con, f"select * from '{ART / 'occ_state.parquet'}'")
    task_chg = q(con, f"select * from '{ART / 'task_changes.parquet'}'")
    tech_chg = q(con, f"select * from '{ART / 'tech_changes.parquet'}'")
    report = json.loads((ART / "backtest_report.json").read_text())
    timing = json.loads((ART / "timing_model.json").read_text())
    validation = json.loads((ART / "update_validation.json").read_text())
    inventory = json.loads((ART / "release_inventory.json").read_text())

    # transitions and states grouped by O*NET-SOC 2019 code (history reaches back
    # through crosswalk chains; rows that arrive via a split/merge carry a flag)
    tr_by = defaultdict(list)
    for t in trans:
        for c in t["codes_2019"] or []:
            tr_by[c].append(t)
    st_by = defaultdict(list)
    for s in states:
        for c in s["codes_2019"] or []:
            st_by[c].append(s)
    lin_of_current = {p["code"]: p["lineage_id"] for p in preds}
    chg_by_lin = defaultdict(list)
    for x in task_chg:
        chg_by_lin[x["lineage_id"]].append(x)
    tech_by_lin = defaultdict(list)
    for x in tech_chg:
        tech_by_lin[x["lineage_id"]].append(x)

    # ---------------- occupation indicators (2019 code) ----------------
    occ = []
    for p in preds:
        code = p["code"]
        tt = tr_by.get(code, [])
        upd = [t for t in tt if t["task_update"] and t["task_churn"] is not None]
        sk = [t["skills_drift"] for t in tt if t["skills_update"] and not t["skills_method_change"]
              and t["skills_drift"] is not None]
        gw = [t["gwa_drift"] for t in tt if t["gwa_update"] and not t["gwa_method_change"]
              and t["gwa_drift"] is not None]
        te = [t for t in tt if t["tech_churn"] is not None]
        yrs_te = sum(t["years"] for t in te)
        n_src = len({t["lineage_id"] for t in tt})
        occ.append({
            "code": code, "title": p["title"], "family": family_of(code), "job_zone": p["job_zone"],
            "lineage_id": p["lineage_id"], "n_source_lineages": n_src,
            "history_via_taxonomy_change": n_src > 1 or not p["lineage_id"].endswith("@13.0"),
            "n_task_updates": len(upd),
            "update_years": [rnd(t["task_date"], 2) for t in upd],
            "update_sources": [t["task_source"] for t in upd],
            "mean_task_churn_at_update": mean([t["task_churn"] for t in upd]),
            "share_updates_with_task_change": mean([1.0 if t["task_churn"] > 0 else 0.0 for t in upd]),
            "tasks_added_total": sum(t["n_added"] or 0 for t in upd),
            "tasks_removed_total": sum(t["n_removed"] or 0 for t in upd),
            "tasks_revised_total": sum(t["n_revised"] or 0 for t in upd),
            "nonupdate_task_edits": sum((t["n_added"] or 0) + (t["n_removed"] or 0) + (t["n_revised"] or 0)
                                        for t in tt if not t["task_update"] and t["task_churn"] is not None),
            "mean_skill_drift_at_update": mean(sk), "mean_gwa_drift_at_update": mean(gw),
            "tech_added_per_year": (sum(t["tech_added"] for t in te) / yrs_te) if yrs_te else None,
            "tech_added_total": sum(t["tech_added"] for t in te),
            "ai_ml_added_total": sum(t["tech_added_ai"] for t in te),
            "data_tools_added_total": sum(t["tech_added_data"] for t in te),
            "hot_added_total": sum(t["tech_added_hot"] for t in te),
            "years_since_task_update": p["years_since_task_update"],
            "p_task_update_2y": p["p_task_update_2y"],
            "p_task_high": p["p_task_high"], "p_task_high_p10": p["p_task_high_p10"],
            "p_task_high_p90": p["p_task_high_p90"],
            "p_tech_high": p["p_tech_high"], "p_tech_high_p10": p["p_tech_high_p10"],
            "p_tech_high_p90": p["p_tech_high_p90"],
        })
        o = occ[-1]
        o["expected_task_change_2y"] = (o["p_task_update_2y"] * o["p_task_high"]) \
            if o["p_task_high"] is not None else None
    cur_state = {s["code"]: s for s in states if s["release"] == LATEST}
    for o in occ:
        s = cur_state.get(o["code"], {})
        o["n_tasks"] = s.get("n_tasks")
        o["n_tech"] = s.get("n_tech")
        o["hot_share"] = (s["n_hot"] / s["n_tech"]) if s.get("n_tech") else None
        o["n_ai_tech"] = s.get("n_ai_tech")
        o["data_tech_share"] = (s["n_data_tech"] / s["n_tech"]) if s.get("n_tech") else None
        o["n_emerging_listed"] = s.get("n_emerging_listed")
        o["task_source_latest"] = s.get("task_source")
    # watch score: mean percentile of (expected task change in 2y, P(high tech churn), data/AI tool adoption)
    r1 = pct_rank([o["expected_task_change_2y"] for o in occ])
    r2 = pct_rank([o["p_tech_high"] for o in occ])
    r3 = pct_rank([(o["data_tools_added_total"] + 3 * o["ai_ml_added_total"]) if o["n_tech"] else None for o in occ])
    for o, a, b, c in zip(occ, r1, r2, r3):
        parts = [x for x in (a, b, c) if x is not None]
        o["watch_score"] = float(np.mean(parts)) if len(parts) == 3 else None
        o["watch_components"] = [rnd(a), rnd(b), rnd(c)]
    pq.write_table(pa.Table.from_pylist([{k: (rnd(v) if isinstance(v, float) else v) for k, v in o.items()}
                                         for o in occ]), ART / "occupation_indicators.parquet",
                   compression="zstd")
    occ_by = {o["code"]: o for o in occ}

    # ---------------- family watchlist ----------------
    def summarize(group):
        g = [o for o in group if o["watch_score"] is not None]
        return {
            "n_occupations": len(group), "n_scored": len(g),
            "watch_score": rnd(mean([o["watch_score"] for o in g])),
            "p_task_update_2y": rnd(mean([o["p_task_update_2y"] for o in group])),
            "p_task_high": rnd(mean([o["p_task_high"] for o in group])),
            "p_task_high_p10": rnd(mean([o["p_task_high_p10"] for o in group])),
            "p_task_high_p90": rnd(mean([o["p_task_high_p90"] for o in group])),
            "p_tech_high": rnd(mean([o["p_tech_high"] for o in group])),
            "p_tech_high_p10": rnd(mean([o["p_tech_high_p10"] for o in group])),
            "p_tech_high_p90": rnd(mean([o["p_tech_high_p90"] for o in group])),
            "mean_task_churn_at_update": rnd(mean([o["mean_task_churn_at_update"] for o in group])),
            "share_updates_with_task_change": rnd(mean([o["share_updates_with_task_change"] for o in group])),
            "mean_skill_drift_at_update": rnd(mean([o["mean_skill_drift_at_update"] for o in group])),
            "tech_added_per_year": rnd(mean([o["tech_added_per_year"] for o in group])),
            "data_tools_added_total": int(sum(o["data_tools_added_total"] for o in group)),
            "ai_ml_added_total": int(sum(o["ai_ml_added_total"] for o in group)),
            "median_years_since_task_update": rnd(float(np.median([o["years_since_task_update"] for o in group
                                                                   if o["years_since_task_update"] is not None]))
                                                  if group else None, 1),
            "top_roles": [{"code": o["code"], "title": o["title"], "watch_score": rnd(o["watch_score"])}
                          for o in sorted(g, key=lambda o: -o["watch_score"])[:5]],
        }

    fam_rows = []
    for fid, label, _ in FAMILIES:
        grp = [o for o in occ if o["family"] == fid]
        fam_rows.append({"family": fid, "label": label, **summarize(grp)})
    fam_rows.sort(key=lambda r: -(r["watch_score"] or 0))
    for i, r in enumerate(fam_rows, 1):
        r["rank"] = i
    all_sum = summarize(occ)

    # ---------------- SUCSS classes (rank-1 candidate, unreviewed) ----------------
    cands = q(con, f"""select c.source_record_id, c.class_code, c.class_title, c.onetsoc_code, c.occupation_title,
                         c.evidence_index, c.evidence_band, c.title_similarity, c.abstained, c.review_status, c.method,
                         s.occupational_line
                  from '{SUCSS_CANDIDATES}' c
                  left join '{CONTRACT / 'sucss_class.parquet'}' s using (source_record_id)
                  where c.candidate_rank = 1 order by c.class_code, c.source_record_id""")
    sucss_rows = []
    for c in cands:
        o = occ_by.get(c["onetsoc_code"])
        sucss_rows.append({
            "source_record_id": c["source_record_id"], "class_code": c["class_code"], "class_title": c["class_title"],
            "occupational_line": c["occupational_line"] or "(blank)", "onet_code": c["onetsoc_code"],
            "onet_title": c["occupation_title"], "family": family_of(c["onetsoc_code"]),
            "mapping_method": c["method"], "evidence_band": c["evidence_band"], "evidence_index": c["evidence_index"],
            "abstained": c["abstained"], "review_status": c["review_status"] or "unreviewed",
            "watch_score": rnd(o["watch_score"]) if o else None,
            "p_task_update_2y": rnd(o["p_task_update_2y"]) if o else None,
            "p_task_high": o["p_task_high"] if o else None, "p_tech_high": o["p_tech_high"] if o else None,
            "tech_added_per_year": rnd(o["tech_added_per_year"]) if o else None,
            "n_task_updates": o["n_task_updates"] if o else None,
            "years_since_task_update": rnd(o["years_since_task_update"], 1) if o and o["years_since_task_update"] else None,
        })
    pq.write_table(pa.Table.from_pylist(sucss_rows), ART / "sucss_class_watch.parquet", compression="zstd")
    line_rows = []
    by_line = defaultdict(list)
    for s in sucss_rows:
        by_line[s["occupational_line"]].append(s)
    for line, rows in sorted(by_line.items()):
        grp = [occ_by[r["onet_code"]] for r in rows if r["onet_code"] in occ_by]
        sm = summarize(grp)  # weighted by number of class records mapped to each occupation
        line_rows.append({"line": line, "n_class_records": len(rows),
                          "n_distinct_occupations": len({r["onet_code"] for r in rows}),
                          "n_abstained": sum(1 for r in rows if r["abstained"]),
                          "n_weak_evidence": sum(1 for r in rows if r["evidence_band"] == "weak"),
                          **{k: sm[k] for k in ("watch_score", "p_task_update_2y", "p_task_high", "p_tech_high",
                                                "tech_added_per_year", "mean_task_churn_at_update")},
                          "top_classes": [{"class_code": r["class_code"], "class_title": r["class_title"],
                                           "onet_title": r["onet_title"], "watch_score": r["watch_score"],
                                           "evidence_band": r["evidence_band"]}
                                          for r in sorted([r for r in rows if r["watch_score"] is not None],
                                                          key=lambda r: -r["watch_score"])[:5]]})
    line_rows.sort(key=lambda r: -(r["watch_score"] or 0))

    watch = {"protocol": PROTOCOL["version"], "origin_release": LATEST,
             "score_definition": ("watch_score = mean of three percentile ranks across all scored O*NET occupations: "
                                  "(1) P(task update within 2 years) x P(substantive task change at that update); "
                                  "(2) P(high technology churn next release); (3) data/AI tools added 2016-2026 "
                                  "(AI/ML examples weighted 3x). It ranks where to look first. It is not a forecast "
                                  "of job loss or of change in University positions."),
             "families": fam_rows, "all_occupations": all_sum, "sucss_lines": line_rows,
             "caveats": CAVEATS}
    dump_json(watch, ART / "watchlist.json")

    # ---------------- explorer bundle ----------------
    vidx = {v: i for i, v in enumerate(VERS)}
    occ_js = {}
    for o in occ:
        code = o["code"]
        tl = {}
        for t in sorted(tr_by.get(code, []), key=lambda t: (vidx[t["rel"]], -(t["n_new"] or 0))):
            if t["rel"] in tl:
                continue
            tl[t["rel"]] = [vidx[t["rel"]], 1 if t["task_update"] else 0, rnd(t["task_churn"], 3),
                            t["n_added"], t["n_removed"], t["n_revised"],
                            rnd(t["skills_drift"], 3) if t["skills_update"] and not t["skills_method_change"] else None,
                            rnd(t["gwa_drift"], 3) if t["gwa_update"] and not t["gwa_method_change"] else None,
                            t["tech_added"], t["tech_removed"], t["tech_added_data"], t["tech_added_ai"],
                            (t["task_source"] or "")[:1] if t["task_update"] else ""]
        sts = {}
        for s in sorted(st_by.get(code, []), key=lambda s: (vidx[s["release"]], -(s["n_tasks"] or 0))):
            if s["release"] in sts:
                continue
            sts[s["release"]] = [vidx[s["release"]], s["n_tasks"], s["n_tech"], s["n_data_tech"], s["n_ai_tech"],
                                 s["n_hot"]]
        lin = lin_of_current.get(code)
        recent = sorted([x for x in chg_by_lin.get(lin, []) if x["task_update"]],
                        key=lambda x: -vidx[x["rel"]])[:12] if o["family"] else []
        rtech = sorted([x for x in tech_by_lin.get(lin, []) if x["change"] == "added"],
                       key=lambda x: (-vidx[x["rel"]], x["example"]))[:15] if o["family"] else []
        occ_js[code] = {
            "t": o["title"], "f": o["family"], "jz": o["job_zone"], "tl": list(tl.values()), "st": list(sts.values()),
            "hx": 1 if o["history_via_taxonomy_change"] else 0, "nu": o["n_task_updates"],
            "ys": rnd(o["years_since_task_update"], 1), "pu": rnd(o["p_task_update_2y"], 3),
            "pt": [rnd(o["p_task_high"], 3), rnd(o["p_task_high_p10"], 3), rnd(o["p_task_high_p90"], 3)],
            "pk": [rnd(o["p_tech_high"], 3), rnd(o["p_tech_high_p10"], 3), rnd(o["p_tech_high_p90"], 3)],
            "ws": rnd(o["watch_score"], 3), "mc": rnd(o["mean_task_churn_at_update"], 3),
            "sd": rnd(o["mean_skill_drift_at_update"], 3), "ta": rnd(o["tech_added_per_year"], 2),
            "ai": o["ai_ml_added_total"], "da": o["data_tools_added_total"],
            "rc": [[VERS[vidx[x["rel"]]], x["change"][0], x["task"] or x["task_prev"]] for x in recent],
            "rt": [[x["rel"], x["example"], 1 if x["data_tool"] else 0, 1 if x["ai_ml"] else 0, 1 if x["hot"] else 0]
                   for x in rtech],
        }

    # top movers (measured, not predicted)
    def top(key, n=15, filt=lambda o: True):
        g = [o for o in occ if o[key] is not None and filt(o)]
        return [[o["code"], rnd(o[key], 4)] for o in sorted(g, key=lambda o: -o[key])[:n]]
    movers = {
        "task_churn": top("mean_task_churn_at_update", filt=lambda o: o["n_task_updates"] >= 2),
        "skill_drift": top("mean_skill_drift_at_update"),
        "tech_velocity": top("tech_added_per_year"),
        "data_ai_tools": top("data_tools_added_total"),
    }

    # technology adoption curves (occupations listing the technology, by release)
    tech_rows = q(con, f"select release, code, example from '{DERIVED / 'tech.parquet'}'")
    fam_n = defaultdict(lambda: defaultdict(set))
    curves = {name: [0] * len(VERS) for name, _ in TECH_CURVES}
    occs_rel = defaultdict(set)
    pats = [(name, re.compile(rx, re.I)) for name, rx in TECH_CURVES]
    sets = {name: defaultdict(set) for name, _ in TECH_CURVES}
    for r in tech_rows:
        occs_rel[r["release"]].add(r["code"])
        for name, rx in pats:
            if rx.search(r["example"]):
                sets[name][r["release"]].add(r["code"])
    for name in curves:
        curves[name] = [len(sets[name].get(v, ())) if v in occs_rel else None for v in VERS]
    ai_occ = [None if v not in occs_rel else 0 for v in VERS]
    data_share = {}
    for s in states:
        if s["n_tech"] is None:
            continue
        f = family_of(s["code"]) or "other"
        fam_n[f][s["release"]].add((s["code"], s["n_data_tech"] / s["n_tech"] if s["n_tech"] else 0))
        if s["n_ai_tech"]:
            ai_occ[vidx[s["release"]]] = (ai_occ[vidx[s["release"]]] or 0) + 1
    for f, d in fam_n.items():
        data_share[f] = [rnd(np.mean([x for _, x in d[v]]), 4) if v in d else None for v in VERS]
    n_occ_tech = [len(occs_rel[v]) if v in occs_rel else None for v in VERS]

    bundle = {
        "releases": [[v, m, t] for v, m, t in RELEASES], "occ": occ_js, "families": FAMILY_LABEL,
        "watch": {"families": fam_rows, "lines": line_rows, "all": all_sum, "def": watch["score_definition"]},
        "sucss": [[s["class_code"], s["class_title"], s["occupational_line"], s["onet_code"], s["onet_title"],
                   s["evidence_band"], 1 if s["abstained"] else 0, s["watch_score"]] for s in sucss_rows],
        "movers": movers,
        "tech": {"curves": curves, "n_occ": n_occ_tech, "ai_occ": ai_occ, "data_share": data_share},
        "backtest": {k: {"pooled": report[k]["pooled"], "folds": report[k]["folds"],
                         "boot": report[k]["bootstrap"], "calib": report[k]["calibration_bins"],
                         "n_events": report[k]["n_unique_label_events"], "censored": report[k]["censored_rows"],
                         "thr": report[k]["final_threshold_all_labels"],
                         "leak_ok": report[k]["all_leakage_checks_ok"], "imp": report[k]["importance_final_fit"]}
                     for k in ("task", "tech")},
        "leakage": report["leakage_prevention"],
        "timing": {"emp": timing["empirical_by_years_since_update"], "by_rel": timing["share_updated_by_release"],
                   "check": timing["temporal_check"], "n": timing["n_intervals"], "nu": timing["n_updates"]},
        "validation": {k: {kk: validation[k][kk] for kk in ("compared_transitions", "agreement_rate")}
                       for k in ("tasks", "gwa")},
        "summary": summary_stats(trans, inventory),
        "caveats": CAVEATS,
    }
    dump_json(bundle, ART / "explorer_data.json")
    print("families ranked:", [(r["rank"], r["family"], r["watch_score"]) for r in fam_rows])
    return 0


def summary_stats(trans, inventory):
    upd = [t for t in trans if t["task_update"] and t["task_churn"] is not None]
    non = [t for t in trans if not t["task_update"] and t["task_churn"] is not None]
    ch_upd = sum((t["n_added"] or 0) + (t["n_removed"] or 0) + (t["n_revised"] or 0) for t in upd)
    ch_non = sum((t["n_added"] or 0) + (t["n_removed"] or 0) + (t["n_revised"] or 0) for t in non)
    te = [t for t in trans if t["tech_churn"] is not None]
    return {
        "n_releases": len(inventory["releases"]), "n_transitions": len(trans),
        "n_task_update_events": len(upd), "n_nonupdate_intervals": len(non),
        "mean_task_churn_update": rnd(mean([t["task_churn"] for t in upd])),
        "mean_task_churn_nonupdate": rnd(mean([t["task_churn"] for t in non])),
        "share_updates_with_any_task_change": rnd(mean([1.0 if t["task_churn"] > 0 else 0.0 for t in upd])),
        "share_nonupdate_with_any_task_change": rnd(mean([1.0 if t["task_churn"] > 0 else 0.0 for t in non])),
        "task_changes_at_updates": ch_upd, "task_changes_without_update": ch_non,
        "tech_added_total": sum(t["tech_added"] for t in te), "tech_removed_total": sum(t["tech_removed"] for t in te),
        "tech_renamed_total": sum(t["tech_renamed"] for t in te),
        "ai_ml_added_total": sum(t["tech_added_ai"] for t in te),
        "data_tools_added_total": sum(t["tech_added_data"] for t in te),
        "n_skill_updates": sum(1 for t in trans if t["skills_update"]),
        "n_skill_method_changes": sum(1 for t in trans if t["skills_update"] and t["skills_method_change"]),
        "n_link_one_to_one": sum(1 for t in trans if t["link_type"] == "one_to_one"),
    }


if __name__ == "__main__":
    sys.exit(main())
