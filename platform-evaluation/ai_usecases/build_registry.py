"""Build the SYNTHETIC demo registry: specs -> full entries -> triage -> checks -> ROI -> DuckDB rollups.

    python ai_usecases/build_registry.py            # writes ai_usecases/data/{registry,roi,summary}.json

Deterministic (seeded). Every entry is fictional and carries synthetic=true. The script fails if any
entry breaks the schema, the data contract, the stored-triage check or a lifecycle gate.
"""
from __future__ import annotations

import datetime as dt
import json
import random
import sys
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parent))
import registry_lib as L  # noqa: E402
from seed_catalog import SPECS, UNITS, HD  # noqa: E402

SEED = 20261106
TODAY = dt.date(2026, 11, 6)
FIRST = dt.date(2025, 11, 10)
DATA = L.HERE / "data"

OWNER = {"HR": "HR Operations Manager", "Finance": "Business Manager", "Advising": "Associate Director of Advising",
         "IT": "IT Service Manager", "Research Administration": "Research Administration Manager"}
REVIEWER = {"HR": "HR Specialist", "Finance": "Accounting Associate", "Advising": "Academic Advisor",
            "IT": "IT Analyst", "Research Administration": "Grants and Contracts Specialist"}
STAGE_ROLE = {"triaged": "JIAT registry steward", "in_review": "JIAT review lead", "approved_pilot": "JIAT review lead",
              "production": "JIAT review lead", "reusable_library": "JIAT registry steward", "rejected": "JIAT review lead"}
MAINT = {"prompt_template": (0.5, 2), "document_template": (0.5, 1.5), "custom_gpt": (1, 3),
         "rag_chatbot": (2, 6), "workflow_script": (2, 8)}
FAILURES = {
    "prompt_template": ["Drops a requirement when the input is long", "Invents a policy citation when asked for one"],
    "document_template": ["Keeps placeholder text when a field is missing"],
    "custom_gpt": ["Answers outside its instructions when pushed", "Formatting drifts on long inputs"],
    "rag_chatbot": ["Answers from an outdated page when two versions exist", "Over-confident when the sources are silent"],
    "workflow_script": ["Fails silently on malformed input files", "Misreads scanned PDFs"],
}


def stage_path(stage: str, tier: int) -> list[str]:
    p = ["submitted"]
    if stage == "submitted":
        return p
    p.append("triaged")
    if stage == "triaged":
        return p
    if stage in ("in_review", "rejected"):
        return p + ["in_review"] + (["rejected"] if stage == "rejected" else [])
    if tier >= 2:
        p.append("in_review")
    p.append("approved_pilot")
    if stage == "approved_pilot":
        return p
    p.append("piloting")
    if stage == "piloting":
        return p
    if stage == "paused":
        return p + ["paused"]
    p.append("production")
    if stage == "production":
        return p
    return p + [stage]  # reusable_library or retired


def cohort_for(d: dt.date, rng: random.Random):
    if d < dt.date(2026, 2, 1):
        prog = rng.choice(["AI PD leader track", "Unit-initiated", "JIAT sprint"])
        return prog, ("2025-Fall-C1" if prog == "AI PD leader track" else None)
    term = "Spring" if d.month <= 5 else ("Summer" if d.month <= 7 else "Fall")
    r = rng.random()
    if r < 0.7:
        return "AI PD Intermediate cohort", f"{d.year}-{term}-C{rng.randint(1, 3)}"
    if r < 0.8:
        return "AI PD leader track", f"{d.year}-{term}-C1"
    return rng.choice(["JIAT sprint", "Unit-initiated"]), None


def base_record(i: int, s: dict, rng: random.Random) -> dict:
    division, _ = UNITS[s["u"]]
    owner = OWNER[s["d"]]
    reviewer = REVIEWER[s["d"]]
    hb = s["hb"]
    rec = {
        "id": f"UC-{i:04d}",
        "schema_version": "1.0",
        "synthetic": True,
        "title": s["t"],
        "problem_statement": s["prob"],
        "proposed_solution": s["sol"],
        "domain": s["d"],
        "unit": {"name": s["u"], "division": division},
        "process": {"name": s["proc"], "frequency": s["freq"], "step_augmented": s["step"]},
        "origin": None,  # set once the submission date is known
        "owner_role": owner,
        "tool": {"approved_tool": s["tool"], "artifact_type": s["art"],
                 "configuration": f"{s['art'].replace('_', ' ').capitalize()} on {s['tool']}; inputs: {', '.join(s['src'])}. Prompt and settings stored with the evaluation evidence."},
        "data": {"classification": s["cls"], "contains_pii": s["pii"], "sources": s["src"]},
        "human_in_the_loop": {
            "pattern": s["hitl"],
            "reviewer_role": reviewer,
            "review_point": ("The human writes the work product; AI suggestions are accepted or ignored while drafting."
                             if s["hitl"] == HD else f"{reviewer} checks the AI output for: {s['step'].lower()}."),
            "override_logged": False,
            "fallback_process": f"Documented manual procedure for {s['proc'].lower()}; no step depends on the tool.",
        },
        "affected_people": {"groups": s["grp"], "scale_band": s["scale"], "output_audience": s["aud"]},
        "employment_decision": {
            "hb3773_flag": bool(hb),
            "decision_types": list(hb or []),
            "notice_plan": ("Written notice to affected applicants/employees that AI assists this step, posted with the job posting or "
                            "process guide and in the HR notice inventory; wording approved by University Counsel." if hb else None),
            "uses_zip_code_or_proxy": False,
        },
        "consequential_decision": {"flag": bool(s["cons"]), "description": s["cons"]},
        "risk": {"tier": 1, "review_paths": ["self_certify"], "blocked": False, "reasons": [],
                 "triage_rules_version": "0.0", "reviews_completed": []},
        "evaluation": {"method": "none_yet", "test_cases": 0, "observed_error_rate": None, "known_failure_modes": [],
                       "evidence_location": None, "last_evaluated": None},
        "time_saved": {"method": "not_estimated", "baseline": None, "pilot": None, "self_reported_minutes": None,
                       "instances_per_year": {"low": float(s["vol"][0]), "high": float(s["vol"][1])}},
        "maintenance": {"owner_role": owner, "hours_per_month": {"low": MAINT[s["art"]][0], "high": MAINT[s["art"]][1]},
                        "review_cadence": "semiannual"},
        "adoption_events": [],
        "status": {"stage": s["stage"], "history": []},
        "submitted_on": None,
        "tags": s["tags"],
    }
    return rec


def build(rules, rng: random.Random) -> list[dict]:
    unit_names = sorted(UNITS)
    out = []
    for i, s in enumerate(SPECS, start=1):
        rec = base_record(i, s, rng)
        tier = L.triage(rec, rules)["tier"]
        path = stage_path(s["stage"], tier)
        gaps = [rng.randint(9, 38) for _ in path[1:]]
        latest_start = TODAY - dt.timedelta(days=1 + sum(gaps) + (60 if s["stage"] in ("production", "reusable_library") else 5))
        span = max(0, (latest_start - FIRST).days)
        d0 = FIRST + dt.timedelta(days=rng.randint(0, span))
        dates = [d0]
        for g in gaps:
            dates.append(dates[-1] + dt.timedelta(days=g))
        rec["submitted_on"] = d0.isoformat()
        prog, cohort = cohort_for(d0, rng)
        rec["origin"] = {"program": prog, "cohort": cohort}
        rec["status"]["history"] = [{"stage": st, "date": d.isoformat(),
                                     "by_role": STAGE_ROLE.get(st, rec["owner_role"])} for st, d in zip(path, dates)]
        stage = s["stage"]
        last = dates[-1]

        # evaluation evidence grows with the stage
        ev = rec["evaluation"]
        deep = stage in ("production", "reusable_library", "retired")
        if stage in ("in_review", "rejected") and rng.random() < 0.5 or stage == "approved_pilot":
            ev.update(method="spot_check", test_cases=rng.randint(6, 14))
        if stage in ("piloting", "paused"):
            ev.update(method=rng.choice(["test_set", "side_by_side"]), test_cases=rng.randint(15, 40))
        if deep:
            ev.update(method="test_set", test_cases=rng.randint(30, 120))
        if ev["method"] != "none_yet":
            ev["observed_error_rate"] = round(rng.uniform(0.02, 0.18), 3)
            ev["known_failure_modes"] = FAILURES[s["art"]][: rng.randint(1, len(FAILURES[s["art"]]))]
            store = rng.choice(["Box", "SharePoint"])
            ev["evidence_location"] = f"{store}: JIAT Registry/{rec['id']}/evaluation/"
            ev["last_evaluated"] = (last - dt.timedelta(days=rng.randint(0, 6))).isoformat()
            if ev["last_evaluated"] < rec["submitted_on"]:
                ev["last_evaluated"] = rec["submitted_on"]

        # time-saved evidence
        ts = rec["time_saved"]
        method = s["tm"] or ("timed_baseline_vs_pilot" if stage in ("piloting", "paused", "production", "reusable_library", "retired")
                             else "self_report" if stage in ("in_review", "approved_pilot", "triaged") else "not_estimated")
        ts["method"] = method
        if method == "timed_baseline_vs_pilot":
            nb = rng.randint(8, 15) if stage in ("piloting", "paused") else rng.randint(15, 40)
            npl = rng.randint(8, 15) if stage in ("piloting", "paused") else rng.randint(15, 40)
            mb = s["base"] * rng.uniform(0.9, 1.1)
            mp = mb * (1 - s["save"] * rng.uniform(0.8, 1.2))
            ts["baseline"] = {"n": nb, "mean_minutes": round(mb, 1), "sd_minutes": round(mb * rng.uniform(0.25, 0.45), 1)}
            ts["pilot"] = {"n": npl, "mean_minutes": round(mp, 1), "sd_minutes": round(mp * rng.uniform(0.3, 0.55), 1)}
            if deep:
                ev["method"] = "pilot_with_baseline"
        elif method == "self_report":
            ts["self_reported_minutes"] = round(s["base"] * rng.uniform(0.3, 0.6), 1)

        # review cadence and override logging follow the tier
        rec["maintenance"]["review_cadence"] = {1: "semiannual", 2: "quarterly"}.get(tier, "monthly")
        rec["human_in_the_loop"]["override_logged"] = tier >= 3 or deep or rng.random() < 0.5

        # adoption by other units
        n_adopt = {"reusable_library": rng.randint(2, 6), "production": rng.randint(0, 3) if tier < 4 else 0,
                   "piloting": rng.randint(0, 1), "retired": 1}.get(stage, 0)
        same = [u for u in unit_names if UNITS[u][1] == s["d"] and u != s["u"]]
        other = [u for u in unit_names if UNITS[u][1] != s["d"]]
        chosen = []
        for _ in range(n_adopt):
            pool = [u for u in (same if rng.random() < 0.6 and same else other) if u not in chosen]
            if pool:
                chosen.append(rng.choice(pool))
        anchor = dates[path.index("production")] if "production" in path else dates[path.index("piloting")] if "piloting" in path else last
        for u in chosen:
            room = (TODAY - dt.timedelta(days=1) - anchor).days
            if room < 3:
                continue
            ed = anchor + dt.timedelta(days=rng.randint(2, room))
            if stage == "piloting":
                kind = "pilot_started"
            elif stage == "retired":
                kind = "adopted"
            else:
                kind = rng.choices(["adopted", "forked_adapted", "pilot_started"], weights=[6, 3, 1])[0]
            share = rng.uniform(0.15, 0.7)
            lo = round(s["vol"][0] * share)
            rec["adoption_events"].append({"date": ed.isoformat(), "unit": u, "domain": UNITS[u][1], "event": kind,
                                           "instances_per_year": {"low": float(lo), "high": float(round(s["vol"][1] * share))}})
            if stage in ("retired", "reusable_library") and rng.random() < (1.0 if stage == "retired" else 0.12):
                rd = ed + dt.timedelta(days=rng.randint(1, max(1, (TODAY - dt.timedelta(days=1) - ed).days)))
                if rd < TODAY:
                    rec["adoption_events"].append({"date": rd.isoformat(), "unit": u, "domain": UNITS[u][1],
                                                   "event": "retired_by_unit", "instances_per_year": None})
        rec["adoption_events"].sort(key=lambda e: (e["date"], e["unit"]))

        # triage, then record which reviews are done given the stage
        rec = L.apply_triage(rec, rules)
        paths = rec["risk"]["review_paths"]
        if stage in ("approved_pilot", "piloting", "production", "reusable_library", "paused", "retired"):
            done = list(paths)
        elif stage in ("in_review", "rejected"):
            done = [p for p in paths if rng.random() < 0.5][: max(0, len(paths) - 1)]
        else:
            done = []
        rec["risk"]["reviews_completed"] = done
        out.append(rec)
    return out


def duckdb_rollups(registry, roi_rows) -> dict:
    con = duckdb.connect()
    con.execute("""CREATE TABLE usecases(id VARCHAR, title VARCHAR, domain VARCHAR, unit VARCHAR, division VARCHAR,
                   stage VARCHAR, tier INTEGER, blocked BOOLEAN, tool VARCHAR, data_class VARCHAR, evidence VARCHAR)""")
    con.executemany("INSERT INTO usecases VALUES (?,?,?,?,?,?,?,?,?,?,?)", [
        (r["id"], r["title"], r["domain"], r["unit"]["name"], r["unit"]["division"], r["status"]["stage"], r["risk"]["tier"],
         r["risk"]["blocked"], r["tool"]["approved_tool"], r["data"]["classification"], r["time_saved"]["method"]) for r in registry])
    con.execute("CREATE TABLE adoption(id VARCHAR, unit VARCHAR, domain VARCHAR, event VARCHAR, date DATE)")
    con.executemany("INSERT INTO adoption VALUES (?,?,?,?,?)", [
        (r["id"], e["unit"], e["domain"], e["event"], e["date"]) for r in registry for e in r["adoption_events"]])
    cols = [f"{k}_{b}" for k in ("gross", "cost", "net", "reuse") for b in ("low", "mid", "high")]
    con.execute("CREATE TABLE roi(id VARCHAR, evidence VARCHAR, realized BOOLEAN, " + ", ".join(f"{c} DOUBLE" for c in cols) + ")")
    con.executemany("INSERT INTO roi VALUES (" + ",".join("?" * (3 + len(cols))) + ")", [
        (x["id"], x["evidence"], x["realized"], *[x[f"{k}_hours"][b] for k in ("gross", "cost", "net", "reuse") for b in ("low", "mid", "high")])
        for x in roi_rows])

    active = """WITH latest AS (
                  SELECT id, unit, domain, event,
                         row_number() OVER (PARTITION BY id, unit ORDER BY date DESC, event) AS rn
                  FROM adoption)
                SELECT id, unit, domain, event FROM latest WHERE rn = 1 AND event <> 'retired_by_unit'"""
    reuse_matrix = con.execute(f"""
        SELECT u.domain AS origin_domain, a.domain AS adopter_domain, count(*) AS adoptions
        FROM ({active}) a JOIN usecases u USING (id)
        GROUP BY ALL ORDER BY origin_domain, adopter_domain""").fetchall()
    unit_edges = con.execute(f"""
        SELECT u.unit AS origin_unit, u.domain AS origin_domain, a.unit AS adopter_unit, a.domain AS adopter_domain,
               count(*) AS solutions, string_agg(u.id, ',' ORDER BY u.id) AS ids
        FROM ({active}) a JOIN usecases u USING (id)
        GROUP BY ALL ORDER BY solutions DESC, origin_unit, adopter_unit""").fetchall()
    by_domain = con.execute("""
        SELECT u.domain, r.evidence, count(*) AS n, sum(r.realized::INT) AS realized,
               round(sum(r.net_low), 3), round(sum(r.net_mid), 3), round(sum(r.net_high), 3),
               round(sum(r.gross_low), 3), round(sum(r.gross_mid), 3), round(sum(r.gross_high), 3)
        FROM roi r JOIN usecases u USING (id) GROUP BY ALL ORDER BY 1, 2""").fetchall()
    tool_class = con.execute("SELECT tool, data_class, count(*) FROM usecases GROUP BY ALL ORDER BY 1, 2").fetchall()
    tiers = con.execute("SELECT tier, sum(blocked::INT), count(*) FROM usecases GROUP BY tier ORDER BY tier").fetchall()
    stages = con.execute("SELECT stage, count(*) FROM usecases GROUP BY stage ORDER BY stage").fetchall()
    totals = con.execute("""SELECT evidence, round(sum(net_low), 3), round(sum(net_mid), 3), round(sum(net_high), 3)
                            FROM roi GROUP BY evidence ORDER BY evidence""").fetchall()
    return {
        "reuse_matrix": [dict(zip(("origin_domain", "adopter_domain", "adoptions"), r)) for r in reuse_matrix],
        "unit_edges": [dict(zip(("origin_unit", "origin_domain", "adopter_unit", "adopter_domain", "solutions", "ids"), r)) for r in unit_edges],
        "roi_by_domain": [dict(zip(("domain", "evidence", "n", "realized", "net_low", "net_mid", "net_high",
                                    "gross_low", "gross_mid", "gross_high"), r)) for r in by_domain],
        "tool_by_class": [dict(zip(("tool", "data_class", "n"), r)) for r in tool_class],
        "tiers": [dict(zip(("tier", "blocked", "n"), r)) for r in tiers],
        "stages": [dict(zip(("stage", "n"), r)) for r in stages],
        "net_totals_sql": [dict(zip(("evidence", "low", "mid", "high"), r)) for r in totals],
    }


def main() -> int:
    schema, rules, assumptions = L.load_schema(), L.load_rules(), L.load_roi_assumptions()
    registry = build(rules, random.Random(SEED))
    bad = {r["id"]: errs for r in registry if (errs := L.check_record(r, schema, rules))}
    if bad:
        for k, v in bad.items():
            print(k, v, file=sys.stderr)
        return 1
    roi_rows = [L.roi(r, assumptions) for r in registry]
    summary = {"generated_for": TODAY.isoformat(), "seed": SEED, "synthetic": True,
               "portfolio": L.portfolio(roi_rows), **duckdb_rollups(registry, roi_rows)}
    DATA.mkdir(exist_ok=True)
    (DATA / "registry.json").write_text(json.dumps(registry, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    (DATA / "roi.json").write_text(json.dumps(roi_rows, indent=1) + "\n", encoding="utf-8")
    (DATA / "summary.json").write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8")
    p = summary["portfolio"]["timed_baseline_vs_pilot"]
    print(f"{len(registry)} synthetic entries; tiers {[(t['tier'], t['n']) for t in summary['tiers']]}; "
          f"blocked {sum(r['risk']['blocked'] for r in registry)}")
    print(f"measured net hours/yr: {p['net_hours']['low']:.0f} .. {p['net_hours']['mid']:.0f} .. {p['net_hours']['high']:.0f} "
          f"({p['realized']} realized of {p['count']} timed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
