"""Coverage of the integrated network: which share of classes, positions and headcount reaches each source.

    python integration/coverage_report.py                 # every built set
    python integration/coverage_report.py --set CLEAN

Reads data/lake/integrated/integrated_<set>.duckdb (run build_integrated.py first) and writes
integration/coverage/coverage_<set>.json and .md. Output contains aggregates only.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import duckdb

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from integration import external as X  # type: ignore
    from integration.build_integrated import OUT_ROOT  # type: ignore
    from integration.mapping import HERE, PE_ROOT, load_mapping, set_location  # type: ignore
else:
    from . import external as X
    from .build_integrated import OUT_ROOT
    from .mapping import HERE, PE_ROOT, load_mapping, set_location

COVERAGE_DIR = HERE / "coverage"

# source -> (class-level expression on dim_job_class_external, bridge chain)
SOURCES = [
    ("sucss_class_record", "source_record_id IS NOT NULL", "job_class_to_sucss_record"),
    ("onet_occupation (duty match, not abstained)", "onet_code IS NOT NULL", "sucss_to_onet"),
    ("soc_2018", "soc_2018_code IS NOT NULL", "onet_to_soc2018"),
    ("oews_national_median_2025", "oews_national_median IS NOT NULL", "soc_to_bls_oews"),
    ("oews_illinois_median_2025", "oews_illinois_median IS NOT NULL", "soc_to_bls_oews"),
    ("oews_any_local_msa_median_2025", "coalesce(oews_msa_champaign_urbana_median, oews_msa_chicago_median, oews_msa_springfield_median) IS NOT NULL", "soc_to_bls_oews"),
    ("oews_naics611300_median_2025", "oews_ind611300_all_median IS NOT NULL", "soc_to_bls_oews"),
    ("bls_projections_separation_rate", "proj_occ_separations_rate_pct IS NOT NULL", "soc_to_bls_projections"),
    ("oews_national_trend", "oews_trend_median_cagr_pct IS NOT NULL", "soc_to_oews_national_history"),
    ("aei_observed_exposure", "aei_observed_exposure IS NOT NULL", "soc_to_aei_exposure"),
    ("onet_job_zone", "onet_job_zone IS NOT NULL", "onet_to_job_zone_tasks_tech"),
    ("job_evolution_watch_score", "je_watch_score IS NOT NULL", "sucss_to_job_evolution"),
    ("class_evolution_timeline", "ce_status IS NOT NULL", "sucss_to_class_evolution"),
    ("class_evolution_stale_spec", "ce_stale_flag IS NOT NULL", "sucss_to_class_evolution"),
    ("class_evolution_revision_risk", "ce_revision_risk_index IS NOT NULL", "sucss_to_class_evolution"),
]


def pct(n, d):
    return None if not d else round(100.0 * n / d, 1)


def coverage(set_name: str, out_root: Path | None = None) -> dict:
    db = Path(out_root or OUT_ROOT) / f"integrated_{set_name}.duckdb"
    if not db.exists():
        raise FileNotFoundError(f"{db} not built; run build_integrated.py --set {set_name}")
    con = duckdb.connect(str(db), read_only=True)
    one = lambda s: con.execute(s).fetchall()[0]
    latest = one("SELECT max(as_of_date) FROM fact_position_snapshot")[0]
    L = f"DATE '{latest}'"
    used = "job_class_code IN (SELECT DISTINCT job_class_code FROM canon_appointment)"
    n_ref = one("SELECT count(*) FROM dim_job_class_external")[0]
    n_used = one(f"SELECT count(*) FROM dim_job_class_external WHERE {used}")[0]
    pos_where = f"as_of_date = {L} AND known_as_of = {L} AND (position_active OR incumbent_count > 0)"
    n_pos = one(f"SELECT count(*) FROM fact_position_snapshot WHERE {pos_where}")[0]
    hc_total = one(f"SELECT sum(headcount) FROM fact_headcount_asof WHERE as_of_date = {L} AND known_as_of = {L}")[0] or 0
    rows = []
    for name, expr, bridge in SOURCES:
        c_used = one(f"SELECT count(*) FROM dim_job_class_external WHERE {used} AND {expr}")[0]
        c_ref = one(f"SELECT count(*) FROM dim_job_class_external WHERE {expr}")[0]
        p = one(f"""SELECT count(*) FROM fact_position_snapshot WHERE {pos_where}
                    AND job_class_code IN (SELECT job_class_code FROM dim_job_class_external WHERE {expr})""")[0]
        h = one(f"""SELECT coalesce(sum(headcount), 0) FROM fact_headcount_asof WHERE as_of_date = {L} AND known_as_of = {L}
                    AND job_class_code IN (SELECT job_class_code FROM dim_job_class_external WHERE {expr})""")[0]
        rows.append({"source": name, "bridge": bridge,
                     "classes_used": c_used, "classes_used_pct": pct(c_used, n_used),
                     "classes_reference": c_ref, "classes_reference_pct": pct(c_ref, n_ref),
                     "positions": p, "positions_pct": pct(p, n_pos),
                     "headcount": int(h), "headcount_pct": pct(h, hc_total)})
    # position-level local market pay (needs campus as well as SOC)
    mk = one(f"""SELECT count(*) FILTER (WHERE incumbent_count > 0), count(market_pay_ratio_local), count(market_pay_ratio_il)
                 FROM fact_position_snapshot WHERE {pos_where}""")
    match_types = [dict(zip(("sucss_match_type", "classes_used", "headcount"), r)) for r in con.execute(f"""
        SELECT e.sucss_match_type, count(DISTINCT e.job_class_code) FILTER (WHERE e.{used}),
               coalesce(sum(h.headcount), 0)
        FROM dim_job_class_external e LEFT JOIN fact_headcount_asof h
          ON h.job_class_code = e.job_class_code AND h.as_of_date = {L} AND h.known_as_of = {L}
        GROUP BY 1 ORDER BY 1""").fetchall()]
    abstained = [dict(zip(("job_class_code", "class_title", "abstain_reason", "headcount"), r)) for r in con.execute(f"""
        SELECT e.job_class_code, e.class_title, e.onet_abstain_reason, coalesce(sum(h.headcount), 0)
        FROM dim_job_class_external e LEFT JOIN fact_headcount_asof h
          ON h.job_class_code = e.job_class_code AND h.as_of_date = {L} AND h.known_as_of = {L}
        WHERE e.onet_abstained AND e.{used} GROUP BY ALL ORDER BY 1""").fetchall()]
    multi = [dict(zip(("job_class_code", "n_sucss_records", "sucss_match_type", "sucss_class_title"), r)) for r in con.execute(
        "SELECT job_class_code, n_sucss_records, sucss_match_type, sucss_class_title FROM dim_job_class_external "
        "WHERE n_sucss_records > 1 ORDER BY 1").fetchall()]
    bands = [dict(zip(("evidence_band", "classes_used", "headcount"), r)) for r in con.execute(f"""
        WITH b AS (SELECT e.job_class_code, e.{used} AS in_use,
                          coalesce(e.onet_evidence_band, CASE WHEN e.onet_abstained THEN 'abstained' ELSE 'no_link' END) AS band
                   FROM dim_job_class_external e),
        h AS (SELECT job_class_code, sum(headcount) AS hc FROM fact_headcount_asof
              WHERE as_of_date = {L} AND known_as_of = {L} GROUP BY 1)
        SELECT band, count(*) FILTER (WHERE in_use), coalesce(sum(h.hc), 0)
        FROM b LEFT JOIN h USING (job_class_code) GROUP BY band ORDER BY band""").fetchall()]
    title_disagree = one(f"SELECT count(*) FROM dim_job_class_external WHERE {used} AND sample_title_agrees = FALSE")[0]
    soc_rollup = one(f"SELECT count(*) FROM dim_job_class_external WHERE {used} AND oews_soc_match = 'broad_rollup'")[0]
    suppressed = one(f"SELECT count(*) FROM dim_job_class_external WHERE {used} AND oews_null_reason LIKE 'oews_national_median_suppressed%'")[0]
    unmapped_org = one(f"SELECT count(*) FROM fact_position_snapshot WHERE {pos_where} AND campus_unitid IS NULL")[0]
    bridges = X.load_bridges()
    weak = [{"bridge": b["id"], "review_status": b["review_status"]} for b in bridges["bridges"]
            if b["review_status"] in ("unreviewed", "synthetic_assignment", "curated_rule")]
    con.close()
    man_path = Path(out_root or OUT_ROOT) / set_name / "manifest.json"
    man = json.loads(man_path.read_text()) if man_path.exists() else {}
    out = {
        "set": set_name, "latest_snapshot": str(latest),
        "denominators": {"classes_reference": n_ref, "classes_used_in_appointments": n_used,
                         "positions_active_or_filled": n_pos, "headcount_distinct_persons": int(hc_total)},
        "reach": rows,
        "position_market_pay": {"filled_positions": mk[0], "with_local_msa_ratio": mk[1], "with_il_ratio": mk[2],
                                "local_pct": pct(mk[1], mk[0]), "il_pct": pct(mk[2], mk[0])},
        "sucss_match_types": match_types, "onet_evidence_bands": bands, "abstained_classes": abstained,
        "multi_record_codes": multi, "sample_titles_disagreeing_with_sucss": title_disagree,
        "oews_broad_rollup_classes": soc_rollup, "oews_national_median_suppressed_classes": suppressed,
        "positions_without_campus": unmapped_org,
        "unreviewed_or_synthetic_bridges": weak,
        "mapping_ok": man.get("mapping_validation", {}).get("ok"),
        "mapping_concepts": {k: v.get("status") for k, v in man.get("mapping_validation", {}).get("concepts", {}).items()},
        "oews_year_recovery": man.get("external", {}).get("oews_year_recovery", {}).get("method"),
        "flows": man.get("flows"), "benchmarks": man.get("benchmarks"),
    }
    out["generator_truth_check"] = truth_check(set_name, out_root)
    return out


def truth_check(set_name: str, out_root: Path | None) -> dict | None:
    """Longitudinal only: compare flow counts with the generator's planted totals (truth.json stats)."""
    try:
        loc, storage = set_location(load_mapping(), set_name)
    except Exception:
        return None
    truth = (loc.parent if storage == "duckdb" else loc) / "truth.json"
    if not truth.exists():
        return None
    stats = json.loads(truth.read_text()).get("stats", {})
    con = duckdb.connect(str(Path(out_root or OUT_ROOT) / f"integrated_{set_name}.duckdb"), read_only=True)
    ev = dict(con.execute("SELECT event_type, count(*) FROM fact_appointment_events GROUP BY 1").fetchall())
    seps = con.execute("SELECT count(*) FROM fact_separation_events").fetchall()[0][0]
    con.close()
    return {"truth_stats": stats,
            "integration_counts_all_years": {"first_observed_appointments (external_hire)": ev.get("external_hire", 0),
                                             "internal_moves": ev.get("internal_move", 0), "rehires": ev.get("rehire", 0),
                                             "separations": seps},
            "note": "external_hire counts every person's first observed appointment, so it includes the generator's "
                    "initial stock; the generator's external_hires counts only hires during the simulation."}


def to_markdown(c: dict) -> str:
    d = c["denominators"]
    L = [f"# Integration coverage: {c['set']}", "",
         "SYNTHETIC SAMPLE + PUBLIC EXTERNAL DATA. Internal records are synthetic; every SUCSS to O*NET link is unreviewed; "
         "the campus assignment is synthetic. Generated by `integration/coverage_report.py`.", "",
         f"Latest snapshot: **{c['latest_snapshot']}**. Denominators: {d['classes_reference']} reference classes, "
         f"{d['classes_used_in_appointments']} classes used in appointments, {d['positions_active_or_filled']} active or filled positions, "
         f"{d['headcount_distinct_persons']} distinct people (primary assignment).", "",
         "## Reach by source", "",
         "| Source | Bridge | Classes used | Positions | Headcount | Reference classes |", "|---|---|---:|---:|---:|---:|"]
    for r in c["reach"]:
        L.append(f"| {r['source']} | `{r['bridge']}` | {r['classes_used']} ({r['classes_used_pct']}%) | {r['positions']} ({r['positions_pct']}%) | "
                 f"{r['headcount']} ({r['headcount_pct']}%) | {r['classes_reference']} ({r['classes_reference_pct']}%) |")
    mp = c["position_market_pay"]
    L += ["", f"Position-level market pay ratio (needs incumbent salary, SOC and campus): local MSA {mp['with_local_msa_ratio']} of "
              f"{mp['filled_positions']} filled positions ({mp['local_pct']}%), Illinois {mp['with_il_ratio']} ({mp['il_pct']}%).", "",
          "## Unmatched and abstained", "", "| SUCSS match type | Classes used | Headcount |", "|---|---:|---:|"]
    for r in c["sucss_match_types"]:
        L.append(f"| {r['sucss_match_type']} | {r['classes_used']} | {int(r['headcount'])} |")
    L += ["", "| O*NET evidence band (rank-1, unreviewed) | Classes used | Headcount |", "|---|---:|---:|"]
    for r in c["onet_evidence_bands"]:
        L.append(f"| {r['evidence_band']} | {r['classes_used']} | {int(r['headcount'])} |")
    L += ["", f"Abstained classes in use: {len(c['abstained_classes'])}."]
    for r in c["abstained_classes"]:
        L.append(f"- {r['job_class_code']} {r['class_title']}: {r['abstain_reason']} (headcount {int(r['headcount'])}); external facts NULL with reason.")
    if c["multi_record_codes"]:
        L.append("")
        for r in c["multi_record_codes"]:
            L.append(f"- Code {r['job_class_code']} has {r['n_sucss_records']} SUCSS records; resolved as `{r['sucss_match_type']}` to {r['sucss_class_title']}.")
    L += ["", f"- Sample titles that disagree with the SUCSS title for the same code: {c['sample_titles_disagreeing_with_sucss']}.",
          f"- Classes whose OEWS wages come from the broad SOC roll-up: {c['oews_broad_rollup_classes']}.",
          f"- Classes whose OEWS national median is suppressed (NULL, not zero): {c['oews_national_median_suppressed_classes']}.",
          f"- Active or filled positions whose org does not reach an assigned campus: {c['positions_without_campus']}.",
          f"- OEWS survey-year recovery: `{c['oews_year_recovery']}`.", "",
          "## Bridges that are not publisher-asserted", ""]
    for b in c["unreviewed_or_synthetic_bridges"]:
        L.append(f"- `{b['bridge']}`: {b['review_status']}")
    L += ["", "## Mapping", "", f"Mapping resolved: {c['mapping_ok']}. Concepts: " +
          ", ".join(f"{k}={v}" for k, v in c["mapping_concepts"].items()) + "."]
    if c.get("generator_truth_check"):
        t = c["generator_truth_check"]
        L += ["", "## Check against the generator's planted totals", "",
              f"Generator stats: {json.dumps(t['truth_stats'])}.", "",
              f"Integration counts (all years): {json.dumps(t['integration_counts_all_years'])}.", "", t["note"]]
    return "\n".join(L) + "\n"


def write(set_name: str, out_root: Path | None = None) -> dict:
    c = coverage(set_name, out_root)
    COVERAGE_DIR.mkdir(exist_ok=True)
    (COVERAGE_DIR / f"coverage_{set_name}.json").write_text(json.dumps(c, indent=1, default=str), encoding="utf-8")
    (COVERAGE_DIR / f"coverage_{set_name}.md").write_text(to_markdown(c), encoding="utf-8")
    return c


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", default=None)
    a = ap.parse_args(argv)
    sets = [a.set] if a.set else [s for s in ("longitudinal", "CLEAN", "DEFECTS") if (OUT_ROOT / f"integrated_{s}.duckdb").exists()]
    for s in sets:
        c = write(s)
        print(f"[{s}] " + "; ".join(f"{r['source']}: {r['headcount_pct']}% hc" for r in c["reach"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
