"""Reconciliation checks: feature-table headcount vs the integration layer, and transition counts vs the
generator's planted totals (v3 README) and the integration layer's own event tables.

Tolerances (documented, not tuned): separations and retirements must match exactly (they come from the
termination code); promotions and transfers are candidate-rule labels and are allowed +/- 2% of the planted
count before the check fails. The report keeps every number whether or not it passes.
"""
from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from wap_prototype import extract as E  # noqa: E402

# Planted totals from sample_datasets/v3_cookbook/README.md (change-reason counts on the current-knowledge chain).
PLANTED = {
    "longitudinal": {"promotion": 626 + 178, "transfer": 422 + 236, "separation_resignation": 972, "retirement": 36,
                     "separation_end_of_appointment": 472, "separations_total": 1480, "internal_moves": 1467, "hire": 2302, "rehire": 0},
    # CLEAN: promotions/transfers/hires/rehires are the job change-code counts (PR001+FA002, OT012, HR001, HR002);
    # separations are the termination records in T_EMPEE_HIST (TQ 201, TR 199, TE 212 = 612 people), which differ
    # from the job-row codes EJ002 210 / SP003 206 because people with several jobs carry the code on each job.
    "CLEAN": {"promotion": 23 + 15, "transfer": 156, "separation_resignation": 201, "retirement": 199,
              "separation_end_of_appointment": 212, "separations_total": 612, "hire": 1500, "rehire": 150},
}
TOLERANCE = {"promotion": 0.02, "transfer": 0.02, "internal_moves": 0.02, "hire": 0.0, "rehire": 0.0,
             "separation_resignation": 0.0, "retirement": 0.0, "separation_end_of_appointment": 0.0, "separations_total": 0.0}


def _row(name, expected, actual, tol, note="", informational=False):
    ok = expected is None or actual is None or abs(actual - expected) <= tol * max(expected, 1)
    return {"check": name, "expected": expected, "actual": actual, "tolerance": tol,
            "status": "pass" if ok else ("info" if informational else "fail"), "note": note}


def run(src: E.Source, features_table: str = "person_period_features", events_table: str = "transition_events") -> dict:
    con, set_name = src.con, src.cfg.set_name
    out = {"headcount": [], "transitions": [], "integration_events": [], "set": set_name}
    integ = src.report["integrated_attached"]
    # 1. headcount: feature-table persons per snapshot vs fact_headcount_asof (as_of_date = known_as_of)
    if integ:
        rows = con.execute(f"""
            SELECT f.snap_date, f.n, h.hc, h.fte, f.fte_f FROM
              (SELECT snap_date, count(*) AS n, round(sum(fte_total), 2) AS fte_f FROM {features_table} GROUP BY 1) f
            JOIN (SELECT as_of_date, sum(headcount) AS hc, round(sum(fte), 2) AS fte FROM integ.fact_headcount_asof
                  WHERE as_of_date = known_as_of GROUP BY 1) h ON h.as_of_date = f.snap_date
            ORDER BY 1""").fetchall()
        for d, n, hc, fte, fte_f in rows:
            out["headcount"].append(_row(f"headcount {d}", int(hc), int(n), 0.0, f"fte feature={fte_f} integration={fte}"))
        if not rows:
            out["headcount"].append({"check": "headcount", "status": "skipped", "note": "no common snapshot date with fact_headcount_asof"})
    else:
        out["headcount"].append({"check": "headcount", "status": "skipped", "note": "integrated database not attached"})
    # 2. transition counts vs planted totals
    c = {r[0]: r[1] for r in con.execute(f"SELECT event_type, count(*) FROM {events_table} WHERE NOT is_future GROUP BY 1").fetchall()}
    actual = {"promotion": c.get("promotion", 0), "transfer": c.get("transfer_lateral", 0) + c.get("transfer_down", 0),
              "separation_resignation": c.get("separation_resignation", 0), "retirement": c.get("retirement", 0),
              "separation_end_of_appointment": c.get("separation_end_of_appointment", 0),
              "separations_total": sum(v for k, v in c.items() if k.startswith("separation_") or k == "retirement"),
              # the generator and the integration layer count a re-appointment to an earlier job the day after another
              # job ended as an internal move; this layer labels it 'reactivation' (same job lineage)
              "internal_moves": c.get("promotion", 0) + c.get("transfer_lateral", 0) + c.get("transfer_down", 0) + c.get("reactivation", 0),
              "hire": c.get("hire", 0), "rehire": c.get("rehire", 0)}
    planted = PLANTED.get(set_name, {})
    for k, v in actual.items():
        exp = planted.get(k)
        out["transitions"].append(_row(f"planted {k}", exp, v, TOLERANCE[k],
                                       "no planted total for this set" if exp is None else
                                       "promotions + transfers + reactivations (re-appointment to an earlier job)" if k == "internal_moves" else
                                       "candidate rule" if TOLERANCE[k] > 0 else "from source codes"))
    out["event_counts"] = c
    # 3. the integration layer's own event tables (same source, independent SQL). Informational: the integration
    #    layer's appointment-event rule looks at the previous row of the PERSON, so people with concurrent jobs
    #    (CLEAN) turn annual pay rows into "internal moves"; it is exact on longitudinal (one job per person).
    note_im = "integration rule counts concurrent-job pay cycles as moves (CLEAN); exact on longitudinal"
    if integ:
        im = con.execute("SELECT count(*) FROM integ.fact_appointment_events WHERE event_type = 'internal_move'").fetchall()[0][0]
        out["integration_events"].append(_row("internal moves vs fact_appointment_events", int(im), actual["internal_moves"], 0.0, note_im, informational=True))
        for g, a in (("resignation", "separation_resignation"), ("retirement", "retirement"), ("end_of_appointment", "separation_end_of_appointment")):
            n = con.execute(f"SELECT count(*) FROM integ.fact_separation_events WHERE reason_group = '{g}'").fetchall()[0][0]
            out["integration_events"].append(_row(f"{g} vs fact_separation_events", int(n), actual[a], 0.0))
        eh = con.execute("SELECT count(*) FROM integ.fact_appointment_events WHERE event_type IN ('external_hire', 'rehire')").fetchall()[0][0]
        out["integration_events"].append(_row("hires + rehires vs fact_appointment_events", int(eh), actual["hire"] + actual["rehire"], 0.0, note_im, informational=True))
    checks = out["headcount"] + out["transitions"] + out["integration_events"]
    out["summary"] = {"pass": sum(r.get("status") == "pass" for r in checks), "fail": sum(r.get("status") == "fail" for r in checks),
                      "info": sum(r.get("status") == "info" for r in checks), "skipped": sum(r.get("status") == "skipped" for r in checks)}
    return out


def to_markdown(rep: dict) -> str:
    lines = [f"# Reconciliation ({rep['set']})", "", f"pass {rep['summary']['pass']}, fail {rep['summary']['fail']}, info (mismatch, informational) {rep['summary']['info']}, skipped {rep['summary']['skipped']}", ""]
    for section in ("headcount", "transitions", "integration_events"):
        lines += [f"## {section}", "", "| Check | Expected | Actual | Tolerance | Status | Note |", "|---|---:|---:|---:|---|---|"]
        for r in rep[section]:
            lines.append(f"| {r['check']} | {r.get('expected', '')} | {r.get('actual', '')} | {r.get('tolerance', '')} | {r['status']} | {r.get('note', '')} |")
        lines.append("")
    lines += ["## Event counts (as known at the extract date)", "", "| Event type | n |", "|---|---:|"]
    for k, v in sorted(rep["event_counts"].items()):
        lines.append(f"| {k} | {v} |")
    return "\n".join(lines) + "\n"
