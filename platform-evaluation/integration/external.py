"""Load and clean the public external sources the bridges point at (all `ext_*` tables).

Nothing here touches internal (synthetic) data. Every ext_* row carries source_id, vintage and
review_status. Published suppression codes become NULL with a *_flag column, never zero.
"""
from __future__ import annotations

import os
from pathlib import Path

import yaml

from .mapping import PE_ROOT, HERE

BRIDGES_FILE = HERE / "bridges.yaml"
BLS_SUPPRESSION_CODES = ("*", "**", "#", "~")


def load_bridges(path: str | Path | None = None) -> dict:
    with open(path or BRIDGES_FILE, encoding="utf-8") as fh:
        b = yaml.safe_load(fh)
    b["by_id"] = {x["id"]: x for x in b["bridges"]}
    for x in b["bridges"]:
        for key in ("method", "source", "review_status"):
            if key not in x:
                raise ValueError(f"bridge {x['id']} lacks {key}")
    return b


def lake_root(bridges: dict) -> Path:
    p = Path(os.environ.get("HR_LAKE_PATH", "") or bridges.get("lake_root", "data/lake"))
    return p if p.is_absolute() else PE_ROOT / p


def resolve_path(bridges: dict, path: str) -> Path:
    if path.startswith("lake:"):
        return lake_root(bridges) / path[5:]
    return PE_ROOT / path


def q(p: Path | str) -> str:
    return "'" + str(Path(p).as_posix()).replace("'", "''") + "'"


def lit(s) -> str:
    return "NULL" if s is None else "'" + str(s).replace("'", "''") + "'"


def register_macros(con) -> None:
    codes = ", ".join(lit(c) for c in BLS_SUPPRESSION_CODES)
    con.execute(f"""CREATE OR REPLACE MACRO bls_num(v) AS
        CASE WHEN v IS NULL OR trim(CAST(v AS VARCHAR)) IN ('', {codes}) THEN NULL
             ELSE TRY_CAST(replace(trim(CAST(v AS VARCHAR)), ',', '') AS DOUBLE) END""")
    con.execute(f"""CREATE OR REPLACE MACRO bls_flag(v) AS
        CASE WHEN v IS NULL OR trim(CAST(v AS VARCHAR)) = '' THEN 'missing'
             WHEN trim(CAST(v AS VARCHAR)) IN ({codes}) THEN trim(CAST(v AS VARCHAR))
             WHEN TRY_CAST(replace(trim(CAST(v AS VARCHAR)), ',', '') AS DOUBLE) IS NULL THEN 'unparsed'
             ELSE NULL END""")
    con.execute("CREATE OR REPLACE MACRO norm_title(t) AS "
                "trim(regexp_replace(lower(coalesce(t, '')), '[^a-z0-9]+', ' ', 'g'))")
    con.execute("CREATE OR REPLACE MACRO soc_broad(s) AS substr(s, 1, 6) || '0'")


# ----------------------------------------------------------------------------- OEWS year recovery
def recover_years(con, silver: Path, extract_glob_dir: Path, pattern: str, year_from_name) -> dict:
    """Return {"method", "boundaries": [(start_row, end_row_excl, year)], "note"} for a silver BLS table.

    The lake's silver `survey_year` column holds the literal header text 'survey_year' (a bug in
    lake_build.xlsx_to_csv: every row after the header is written through the header branch). If the
    column is usable it is used; otherwise the year is recovered from the per-year extract CSVs that
    lake_build unioned in sorted file order, verified by total row count and by matching each file's
    first row against the silver row at that offset.
    """
    total = con.execute(f"SELECT count(*) FROM read_parquet({q(silver)})").fetchall()[0][0]
    good = con.execute(f"SELECT count(*) FROM read_parquet({q(silver)}) "
                       "WHERE TRY_CAST(survey_year AS INTEGER) BETWEEN 1990 AND 2100").fetchall()[0][0]
    if good == total:
        return {"method": "silver_survey_year", "boundaries": None, "total": total,
                "note": "survey_year column usable"}
    files = sorted(extract_glob_dir.glob(pattern)) if extract_glob_dir.exists() else []
    if not files:
        return {"method": "unrecoverable", "boundaries": [], "total": total,
                "note": "silver survey_year is the literal header text and no extract CSVs exist; year left NULL"}
    bounds, start = [], 0
    for f in files:
        n = con.execute(f"SELECT count(*) FROM read_csv({q(f)}, header=true, all_varchar=true)").fetchall()[0][0]
        bounds.append((start, start + n, year_from_name(f.name), f))
        start += n
    if start != total:
        return {"method": "unrecoverable", "boundaries": [], "total": total,
                "note": f"extract row total {start} != silver {total}; year left NULL"}
    for s, e, y, f in bounds:
        if e == s:
            continue
        a = con.execute(f"SELECT occ_code, tot_emp, a_median FROM read_csv({q(f)}, header=true, all_varchar=true) LIMIT 1").fetchall()[0]
        b = con.execute(f"SELECT occ_code, tot_emp, a_median FROM read_parquet({q(silver)}, file_row_number=true) "
                        f"WHERE file_row_number = {s}").fetchall()[0]
        if tuple(a) != tuple(b):
            return {"method": "unrecoverable", "boundaries": [], "total": total,
                    "note": f"first row of {f.name} does not match silver row {s}; year left NULL"}
    return {"method": "recovered_from_extract_row_order", "total": total,
            "boundaries": [(s, e, y) for s, e, y, _ in bounds],
            "note": "silver survey_year is the literal text 'survey_year'; year recovered from the sorted "
                    "per-year extract files (row totals and first rows verified)"}


def year_case(rec: dict) -> str:
    if rec["method"] == "silver_survey_year":
        return "TRY_CAST(survey_year AS INTEGER)"
    if not rec["boundaries"]:
        return "CAST(NULL AS INTEGER)"
    parts = " ".join(f"WHEN file_row_number >= {s} AND file_row_number < {e} THEN {y}" for s, e, y in rec["boundaries"])
    return f"CASE {parts} ELSE NULL END"


# ----------------------------------------------------------------------------- loaders
def load_external(con, bridges: dict) -> dict:
    """Create every ext_* table. Returns a dict of notes (year recovery, row counts, missing inputs)."""
    register_macros(con)
    B = bridges["by_id"]
    lake = lake_root(bridges)
    notes = {"missing_inputs": []}

    def src(bid):
        return B[bid]["source"]

    # --- SUCSS catalog
    s = src("job_class_to_sucss_record")
    con.execute(f"""CREATE OR REPLACE TABLE ext_sucss_class AS
        SELECT CAST(source_record_id AS BIGINT) AS source_record_id, class_code, class_title, occupational_line,
               source_id, source_vintage AS vintage, 'publisher_asserted' AS review_status
        FROM read_parquet({q(resolve_path(bridges, s['path']))})""")

    # --- SUCSS -> O*NET candidates (duty matcher)
    b = B["sucss_to_onet"]
    p = b["params"]
    con.execute(f"""CREATE OR REPLACE TABLE ext_sucss_onet_candidates AS
        SELECT CAST(source_record_id AS BIGINT) AS source_record_id, class_code, candidate_rank, onetsoc_code,
               occupation_title, evidence_index, evidence_band, abstained, abstain_reason, top1_margin,
               has_spec_duties, method, review_status, {lit(b['source']['source_id'])} AS source_id,
               method AS vintage
        FROM read_parquet({q(resolve_path(bridges, b['source']['path']))})""")
    fb = p["fallback_source"]
    con.execute(f"""CREATE OR REPLACE TABLE ext_sucss_onet_lexical AS
        SELECT CAST(source_record_id AS BIGINT) AS source_record_id, class_code, rank AS candidate_rank, onetsoc_code,
               occupation_title, score, method, review_status, source_id, source_vintage AS vintage
        FROM read_parquet({q(resolve_path(bridges, fb['path']))})""")

    # --- crosswalk, O*NET profile
    s = src("onet_to_soc2018")
    con.execute(f"""CREATE OR REPLACE TABLE ext_onet_soc AS
        SELECT onetsoc_code, onetsoc_title, soc_2018_code, soc_2018_title, source_id, source_vintage AS vintage,
               'publisher_asserted' AS review_status
        FROM read_parquet({q(resolve_path(bridges, s['path']))})""")
    con.execute(f"""CREATE OR REPLACE TABLE ext_onet_profile AS
        WITH o AS (SELECT onetsoc_code, title FROM read_parquet({q(lake / 'contract/onet_occupation.parquet')})),
        jz AS (SELECT onetsoc_code, job_zone FROM read_parquet({q(lake / 'contract/onet_job_zone.parquet')})),
        t AS (SELECT onetsoc_code, count(*) AS n_tasks, count(*) FILTER (WHERE task_type = 'Core') AS n_core_tasks
              FROM read_parquet({q(lake / 'contract/onet_task_statement.parquet')}) GROUP BY 1),
        te AS (SELECT onetsoc_code, count(*) AS n_tech, count(*) FILTER (WHERE hot_technology = 'Y') AS n_hot_tech
               FROM read_parquet({q(lake / 'contract/onet_technology_skill.parquet')}) GROUP BY 1)
        SELECT o.onetsoc_code, o.title, jz.job_zone, t.n_tasks, t.n_core_tasks, te.n_tech, te.n_hot_tech,
               'onet_db_31_0' AS source_id, 'O*NET 31.0' AS vintage, 'publisher_asserted' AS review_status
        FROM o LEFT JOIN jz USING (onetsoc_code) LEFT JOIN t USING (onetsoc_code) LEFT JOIN te USING (onetsoc_code)""")

    # --- AEI
    s = src("soc_to_aei_exposure")
    con.execute(f"""CREATE OR REPLACE TABLE ext_aei AS
        SELECT soc_2018_code, observed_exposure, source_id, source_vintage AS vintage, 'publisher_asserted' AS review_status
        FROM read_parquet({q(resolve_path(bridges, s['path']))})""")

    # --- OEWS (all areas, 2024 + 2025)
    b = B["soc_to_bls_oews"]
    silver = resolve_path(bridges, b["source"]["path"])
    rec = recover_years(con, silver, lake / "_extract" / "bls", "oews_all_20*.csv",
                        lambda n: int(n.split("_")[-1].split(".")[0]))
    notes["oews_year_recovery"] = {k: v for k, v in rec.items() if k != "boundaries"} | \
        {"boundaries": [list(x) for x in (rec["boundaries"] or [])]}
    area_rows = []
    for key, a in b["params"]["areas"].items():
        cond = f"area = {lit(a['area'])} AND naics = {lit(a['naics'])}"
        if "own_code" in a:
            cond += f" AND own_code = {lit(a['own_code'])}"
        area_rows.append(f"WHEN {cond} THEN {lit(key)}")
    area_case = "CASE " + " ".join(area_rows) + " ELSE NULL END"
    cols = ["tot_emp", "a_mean", "a_pct10", "a_pct25", "a_median", "a_pct75", "a_pct90", "h_mean", "h_median"]
    num = ", ".join(f"bls_num({c}) AS {c}, bls_flag({c}) AS {c}_flag" for c in cols)
    con.execute(f"""CREATE OR REPLACE TABLE ext_oews AS
        WITH raw AS (
            SELECT *, {year_case(rec)} AS survey_year_n, {area_case} AS area_key
            FROM read_parquet({q(silver)}, file_row_number=true)
            WHERE o_group IN ('detailed', 'broad')),
        ranked AS (
            SELECT *, row_number() OVER (PARTITION BY survey_year_n, area_key, occ_code
                                         ORDER BY CASE o_group WHEN 'detailed' THEN 0 ELSE 1 END, i_group, file_row_number) AS rn,
                      count(*) OVER (PARTITION BY survey_year_n, area_key, occ_code) AS n_dup
            FROM raw WHERE area_key IS NOT NULL)
        SELECT survey_year_n AS survey_year, area_key, area, area_title, naics, own_code, occ_code, occ_title, o_group,
               {num}, n_dup,
               'bls_oews' AS source_id,
               CASE WHEN survey_year_n IS NULL THEN 'OEWS May (year unrecoverable)' ELSE 'OEWS May ' || survey_year_n END AS vintage,
               'publisher_asserted' AS review_status
        FROM ranked WHERE rn = 1""")
    notes["oews_rows"] = con.execute("SELECT count(*) FROM ext_oews").fetchall()[0][0]
    notes["oews_duplicate_keys_dropped"] = con.execute("SELECT count(*) FROM ext_oews WHERE n_dup > 1").fetchall()[0][0]

    # --- OEWS national history
    b = B["soc_to_oews_national_history"]
    silver_h = resolve_path(bridges, b["source"]["path"])
    rec_h = recover_years(con, silver_h, lake / "_extract" / "bls" / "nat", "oews_nat_20*.csv",
                          lambda n: int(n.split("_")[-1].split(".")[0]))
    notes["oews_history_year_recovery"] = {k: v for k, v in rec_h.items() if k != "boundaries"} | \
        {"boundaries": [list(x) for x in (rec_h["boundaries"] or [])]}
    con.execute(f"""CREATE OR REPLACE TABLE ext_oews_history AS
        WITH raw AS (SELECT *, {year_case(rec_h)} AS yr FROM read_parquet({q(silver_h)}, file_row_number=true)),
        r AS (SELECT yr AS survey_year, occ_code, bls_num(a_median) AS a_median, bls_flag(a_median) AS a_median_flag,
                     bls_num(tot_emp) AS tot_emp,
                     row_number() OVER (PARTITION BY yr, occ_code ORDER BY file_row_number) AS rn
              FROM raw WHERE yr IS NOT NULL)
        SELECT survey_year, occ_code, a_median, a_median_flag, tot_emp,
               'bls_oews' AS source_id, 'OEWS national May ' || survey_year AS vintage, 'publisher_asserted' AS review_status
        FROM r WHERE rn = 1""")
    con.execute("""CREATE OR REPLACE TABLE ext_oews_trend AS
        WITH h AS (SELECT * FROM ext_oews_history WHERE a_median IS NOT NULL),
        f AS (SELECT occ_code, min(survey_year) AS first_year, max(survey_year) AS last_year, count(*) AS n_years
              FROM h GROUP BY 1)
        SELECT f.occ_code, f.first_year, f.last_year, f.n_years,
               a.a_median AS median_first, z.a_median AS median_last,
               CASE WHEN f.last_year > f.first_year AND a.a_median > 0
                    THEN round(100 * (power(z.a_median / a.a_median, 1.0 / (f.last_year - f.first_year)) - 1), 2) END
                    AS median_wage_cagr_pct,
               a.tot_emp AS emp_first, z.tot_emp AS emp_last,
               'bls_oews' AS source_id, 'OEWS national May ' || f.first_year || '-' || f.last_year AS vintage,
               'publisher_asserted' AS review_status
        FROM f JOIN h a ON a.occ_code = f.occ_code AND a.survey_year = f.first_year
               JOIN h z ON z.occ_code = f.occ_code AND z.survey_year = f.last_year""")

    # --- Employment Projections
    b = B["soc_to_bls_projections"]
    po = resolve_path(bridges, b["source"]["path"])
    ps = po.with_name("bls_projections_separations.parquet")
    con.execute(f"""CREATE OR REPLACE TABLE ext_projections AS
        WITH o AS (SELECT "2025_national_employment_matrix_code" AS soc, occupation_type,
                          "2025_national_employment_matrix_title" AS title,
                          bls_num(employment_2025) AS emp_2025_k, bls_num(employment_2035) AS emp_2035_k,
                          bls_num(employment_change_percent_2025_35) AS growth_pct_2025_35,
                          bls_num(occupational_openings_2025_35_annual_average) AS openings_annual_k,
                          bls_num(median_annual_wage_dollars_2025) AS median_wage_2025,
                          typical_education_needed_for_entry AS entry_education
                   FROM read_parquet({q(po)}) WHERE occupation_type = 'Line item'),
             s AS (SELECT "2025_national_employment_matrix_code" AS soc,
                          bls_num(labor_force_exit_rate_2025_35_annual_average) AS labor_force_exit_rate_pct,
                          bls_num(occupational_transfer_rate_2025_35_annual_average) AS occ_transfer_rate_pct,
                          bls_num(total_occupational_separations_rate_2025_35_annual_average) AS occ_separations_rate_pct
                   FROM read_parquet({q(ps)}) WHERE occupation_type = 'Line item')
        SELECT o.*, CASE WHEN emp_2025_k > 0 THEN round(100 * openings_annual_k / emp_2025_k, 2) END AS openings_rate_pct,
               s.labor_force_exit_rate_pct, s.occ_transfer_rate_pct, s.occ_separations_rate_pct,
               'bls_projections' AS source_id, 'Employment Projections 2025-35' AS vintage,
               'publisher_asserted' AS review_status
        FROM o LEFT JOIN s USING (soc)""")

    # --- job_evolution, class_evolution
    s = src("sucss_to_job_evolution")
    con.execute(f"""CREATE OR REPLACE TABLE ext_job_evolution AS
        SELECT CAST(source_record_id AS BIGINT) AS source_record_id, class_code, onet_code, family AS je_family,
               mapping_method, abstained AS je_abstained, watch_score, p_task_update_2y, p_task_high, p_tech_high,
               tech_added_per_year, {lit(s['source_id'])} AS source_id, {lit(s['vintage'])} AS vintage,
               review_status
        FROM read_parquet({q(resolve_path(bridges, s['path']))})""")
    s = src("sucss_to_class_evolution")
    ce = resolve_path(bridges, s["path"])
    con.execute(f"""CREATE OR REPLACE TABLE ext_class_evolution AS
        SELECT t.class_code, t.job_family AS ce_job_family, t.status AS ce_status, t.spec_effective_date,
               t.last_revision_date, t.years_since_last_revision, t.n_known_revisions, t.n_final_notices,
               t.open_process, t.open_process_stage, t.created_date, t.abolished_date,
               st.stale_flag, st.lag_flag, st.watch_rank AS stale_watch_rank,
               rr.risk_index AS revision_risk_index, rr.rank AS revision_risk_rank, rr.mode AS revision_risk_mode,
               rr.horizon AS revision_risk_horizon,
               {lit(s['source_id'])} AS source_id, {lit(s['vintage'])} AS vintage, 'derived_rule' AS review_status
        FROM read_parquet({q(ce / 'class_timeline.parquet')}) t
        LEFT JOIN read_parquet({q(ce / 'stale_specs.parquet')}) st USING (class_code)
        LEFT JOIN read_parquet({q(ce / 'revision_risk.parquet')}) rr USING (class_code)""")

    # --- IPEDS institutions for the campus assignment
    s = src("campus_to_geography")
    units = ", ".join(lit(v["unitid"]) for v in B["org_to_campus"]["params"]["assignment"].values())
    con.execute(f"""CREATE OR REPLACE TABLE ext_ipeds_institution AS
        SELECT unitid, name AS institution_name, county_fips, cbsa_code, state_abbr, carnegie, source_id,
               source_vintage AS vintage, 'publisher_asserted' AS review_status
        FROM read_parquet({q(resolve_path(bridges, s['path']))}) WHERE unitid IN ({units})""")

    # --- QCEW county context (annual from quarters; any suppressed or missing quarter -> NULL)
    con.execute(f"""CREATE OR REPLACE TABLE ext_qcew_county_year AS
        WITH a AS (
            SELECT area_fips, 'all_industries_all_ownerships' AS series, year, qtr, disclosure_code,
                   month1_emplvl, month2_emplvl, month3_emplvl, total_qtrly_wages, source_id, source_vintage
            FROM read_parquet({q(lake / 'contract/qcew_area.parquet')})
            WHERE own_code = '0' AND industry_code = '10' AND size_code = '0'
            UNION ALL
            SELECT area_fips, 'naics611310_state_government', year, qtr, disclosure_code,
                   month1_emplvl, month2_emplvl, month3_emplvl, total_qtrly_wages, source_id, source_vintage
            FROM read_parquet({q(lake / 'contract/qcew_industry.parquet')})
            WHERE own_code = '2' AND industry_code = '611310' AND size_code = '0' AND length(area_fips) = 5
              AND area_fips LIKE '17%' AND area_fips <> '17000')
        SELECT area_fips, series, CAST(year AS INTEGER) AS year, count(*) AS n_quarters,
               bool_or(coalesce(disclosure_code, '') = 'N') AS any_suppressed,
               CASE WHEN count(*) = 4 AND NOT bool_or(coalesce(disclosure_code, '') = 'N')
                    THEN round(avg((month1_emplvl + month2_emplvl + month3_emplvl) / 3.0), 1) END AS avg_employment,
               CASE WHEN count(*) = 4 AND NOT bool_or(coalesce(disclosure_code, '') = 'N')
                         AND avg((month1_emplvl + month2_emplvl + month3_emplvl) / 3.0) > 0
                    THEN round(sum(total_qtrly_wages) / avg((month1_emplvl + month2_emplvl + month3_emplvl) / 3.0) / 52, 0) END
                    AS avg_weekly_wage,
               min(source_id) AS source_id, min(source_vintage) AS vintage, 'publisher_asserted' AS review_status
        FROM a GROUP BY ALL""")

    # --- QWI Illinois higher-ed annual separation rate (statewide, NAICS 6113, all ownerships)
    con.execute(f"""CREATE OR REPLACE TABLE ext_qwi_il_year AS
        WITH t AS (SELECT * FROM read_parquet({q(lake / 'contract/qwi_higher_ed.parquet')})
                   WHERE sex = '0' AND agegrp = 'A00'),
        last2 AS (SELECT quarter_start FROM (SELECT DISTINCT quarter_start FROM t) ORDER BY quarter_start DESC LIMIT 2)
        SELECT year, count(*) AS n_quarters,
               CASE WHEN count(*) = 4 AND count(sep) = 4 THEN sum(sep) END AS separations,
               CASE WHEN count(*) = 4 AND count(emp) = 4 THEN round(avg(emp), 1) END AS avg_employment,
               CASE WHEN count(*) = 4 AND count(sep) = 4 AND count(emp) = 4 AND avg(emp) > 0
                    THEN round(100 * sum(sep) / avg(emp), 2) END AS separation_rate_pct,
               bool_or(quarter_start IN (SELECT quarter_start FROM last2)) AS provisional,
               min(source_id) AS source_id, min(source_vintage) AS vintage, 'publisher_asserted' AS review_status
        FROM t GROUP BY year""")

    # --- JOLTS annual (NSA, M13) total separations rate
    s = src("jolts_context")
    con.execute(f"""CREATE OR REPLACE TABLE ext_jolts_year AS
        SELECT year,
               max(value) FILTER (WHERE industry_code = '923000' AND state_code = '00') AS us_state_local_govt_education_ts_rate,
               max(value) FILTER (WHERE industry_code = '000000' AND state_code = '17') AS il_total_nonfarm_ts_rate,
               'bls_jolts' AS source_id, 'JOLTS annual (M13, not seasonally adjusted)' AS vintage,
               'publisher_asserted' AS review_status
        FROM read_parquet({q(resolve_path(bridges, s['path']))})
        WHERE dataelement_code = 'TS' AND ratelevel_code = 'R' AND seasonal = 'U' AND period = 'M13'
          AND sizeclass_code = '00' AND ((industry_code = '923000' AND state_code = '00') OR (industry_code = '000000' AND state_code = '17'))
        GROUP BY year""")

    # --- IPEDS peers (peer_benchmarks artifacts if present, else contract staff totals)
    b = B["campus_to_ipeds_peers"]
    pb = resolve_path(bridges, b["source"]["path"])
    if pb.exists():
        con.execute(f"""CREATE OR REPLACE TABLE ext_ipeds_peers AS
            SELECT unitid, year, short_name, panel_role, staff_total, staff_fulltime, management_share_pct,
                   staff_per_100_fte12, new_hires_per_100_fulltime, fte12_total,
                   {lit(b['source']['source_id'])} AS source_id, 'IPEDS Fall ' || year AS vintage,
                   'publisher_asserted' AS review_status
            FROM read_parquet({q(pb)})""")
        notes["peer_source"] = "peer_benchmarks"
    else:
        fb = b["fallback_source"]
        notes["missing_inputs"].append(str(pb))
        con.execute(f"""CREATE OR REPLACE TABLE ext_ipeds_peers AS
            SELECT unitid, 2023 AS year, NULL::VARCHAR AS short_name,
                   CASE WHEN unitid IN ('145637','145600','148654','149587') THEN 'uofi_system' ELSE 'other' END AS panel_role,
                   sum(headcount) AS staff_total, NULL::DOUBLE AS staff_fulltime, NULL::DOUBLE AS management_share_pct,
                   NULL::DOUBLE AS staff_per_100_fte12, NULL::DOUBLE AS new_hires_per_100_fulltime, NULL::DOUBLE AS fte12_total,
                   {lit(fb['source_id'])} AS source_id, {lit(fb['vintage'])} AS vintage, 'publisher_asserted' AS review_status
            FROM read_parquet({q(resolve_path(bridges, fb['path']))})
            WHERE sex = 'Total' AND race_ethnicity = 'Total' AND category_level = 'total'
            GROUP BY unitid""")
        notes["peer_source"] = "contract_ipeds_fallback"
    for t in ("ext_sucss_class", "ext_sucss_onet_candidates", "ext_onet_soc", "ext_onet_profile", "ext_aei",
              "ext_oews", "ext_oews_history", "ext_oews_trend", "ext_projections", "ext_job_evolution",
              "ext_class_evolution", "ext_ipeds_institution", "ext_qcew_county_year", "ext_qwi_il_year",
              "ext_jolts_year", "ext_ipeds_peers"):
        notes.setdefault("rows", {})[t] = con.execute(f"SELECT count(*) FROM {t}").fetchall()[0][0]
    return notes
