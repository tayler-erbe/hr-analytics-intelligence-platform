"""Build the integrated workforce data network for one sample set.

    python integration/build_integrated.py                    # longitudinal (default)
    python integration/build_integrated.py --set CLEAN
    python integration/build_integrated.py --set all

Output: data/lake/integrated/integrated_<set>.duckdb plus data/lake/integrated/<set>/<table>.parquet
and data/lake/integrated/<set>/manifest.json (gitignored via data/lake/).

All internal reads go through the canonical views registered by mapping.py (edw_mapping.yaml);
no physical sample table or column name appears in this file. All external reads go through
external.py (bridges.yaml).
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import shutil
import sys
from pathlib import Path

import duckdb

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from integration import mapping as M  # type: ignore
    from integration import external as X  # type: ignore
else:
    from . import mapping as M
    from . import external as X

OUT_ROOT = M.PE_ROOT / "data" / "lake" / "integrated"
LATEST_KNOWLEDGE = "9999-12-30"   # "as known today": rows whose recorded version is still open
OEWS_AREAS = ["national", "illinois", "msa_champaign_urbana", "msa_chicago", "msa_springfield",
              "ind611300_all", "ind611300_state_gov"]

# Exported tables, with the ORDER BY that makes their Parquet deterministic.
EXPORT = {
    "dim_org_external": "org_code",
    "dim_job_class_external": "job_class_code",
    "br_class_sucss": "job_class_code",
    "br_sucss_onet": "source_record_id",
    "br_sucss_onet_topk": "source_record_id, candidate_rank",
    "br_soc_oews": "soc_2018_code, survey_year, area_key",
    "fact_class_external_long": "job_class_code, measure",
    "fact_position_snapshot": "as_of_date, known_as_of, position_id",
    "fact_headcount_asof": "as_of_date, known_as_of, campus_org_code, role_family, job_class_code",
    "fact_flows_year": "year, campus_org_code, role_family",
    "dim_calendar_quarter": "quarter_start",
    "bench_separation_role_family": "role_family",
    "bench_pay_role_family_campus": "role_family, campus_org_code",
    "bench_ai_pressure_role_family": "role_family",
    "bench_campus_peers": "campus_org_code",
    "ext_qcew_county_year": "area_fips, series, year",
    "ext_qwi_il_year": "year",
    "ext_jolts_year": "year",
}

# Every external measure in dim_job_class_external and the provenance group that carries it.
def measure_registry() -> list[tuple[str, str]]:
    reg = [("sucss_class_title", "sucss"), ("sucss_occupational_line", "sucss"),
           ("onet_code", "onet_match"), ("onet_title", "onet_match"), ("onet_evidence_index", "onet_match"),
           ("onet_evidence_band", "onet_match"),
           ("soc_2018_code", "soc"), ("soc_2018_title", "soc")]
    for a in OEWS_AREAS:
        for m in ("emp", "median", "p10", "p90"):
            reg.append((f"oews_{a}_{m}", "oews"))
    reg += [("oews_national_median_2024", "oews"),
            ("proj_growth_pct_2025_35", "projections"), ("proj_openings_rate_pct", "projections"),
            ("proj_occ_separations_rate_pct", "projections"), ("proj_labor_force_exit_rate_pct", "projections"),
            ("proj_occ_transfer_rate_pct", "projections"), ("proj_emp_2025_k", "projections"),
            ("oews_trend_median_cagr_pct", "oews_trend"), ("oews_trend_n_years", "oews_trend"),
            ("aei_observed_exposure", "aei"),
            ("onet_job_zone", "onet_profile"), ("onet_n_tasks", "onet_profile"), ("onet_n_tech", "onet_profile"),
            ("onet_n_hot_tech", "onet_profile"),
            ("je_watch_score", "job_evolution"), ("je_p_task_update_2y", "job_evolution"),
            ("je_p_task_high", "job_evolution"), ("je_p_tech_high", "job_evolution"),
            ("ce_status", "class_evolution"), ("ce_spec_effective_date", "class_evolution"),
            ("ce_last_revision_date", "class_evolution"), ("ce_spec_age_years", "class_evolution"),
            ("ce_n_known_revisions", "class_evolution"), ("ce_stale_flag", "class_evolution"),
            ("ce_revision_risk_index", "class_evolution"), ("ce_revision_risk_rank", "class_evolution")]
    return reg


PROV_GROUPS = ["sucss", "onet_match", "soc", "oews", "projections", "oews_trend", "aei", "onet_profile",
               "job_evolution", "class_evolution"]


def lit(s) -> str:
    return X.lit(s)


def in_list(vals) -> str:
    return "(" + ", ".join(lit(v) for v in vals) + ")" if vals else "(NULL)"


# ----------------------------------------------------------------------------- steps
def build_org(con, res: M.Resolution, bridges: dict) -> None:
    assign = bridges["by_id"]["org_to_campus"]["params"]["assignment"]
    values = ", ".join(f"({lit(k)}, {lit(v['unitid'])}, {lit(v['label'])})" for k, v in sorted(assign.items()))
    con.execute(f"CREATE OR REPLACE TEMP TABLE campus_assignment AS SELECT * FROM (VALUES {values}) t(campus_org_code, unitid, campus_label)")
    con.execute("""CREATE OR REPLACE TABLE dim_org_external AS
        WITH RECURSIVE o AS (SELECT DISTINCT org_code, parent_org_code, org_title FROM c_org),
        walk(org_code, cur, parent, depth) AS (
            SELECT org_code, org_code, parent_org_code, 0 FROM o
            UNION ALL
            SELECT w.org_code, o.org_code, o.parent_org_code, w.depth + 1
            FROM walk w JOIN o ON o.org_code = w.parent WHERE w.depth < 25),
        roots AS (SELECT org_code AS root FROM o WHERE parent_org_code IS NULL),
        chain AS (SELECT w.*, (w.parent IN (SELECT root FROM roots)) AS parent_is_root,
                         (w.cur IN (SELECT root FROM roots)) AS is_root FROM walk w),
        lvl AS (SELECT org_code, max(depth) AS depth,
                       max(cur) FILTER (WHERE parent_is_root) AS campus_child,
                       max(cur) FILTER (WHERE is_root) AS root_code
                FROM chain GROUP BY org_code)
        SELECT o.org_code, o.parent_org_code, o.org_title, l.depth AS org_depth,
               coalesce(l.campus_child, l.root_code) AS campus_org_code,
               ca.unitid AS campus_unitid, ca.campus_label,
               'integration_synthetic_campus_assignment' AS campus_source_id, 'v1' AS campus_vintage,
               CASE WHEN ca.unitid IS NULL THEN NULL ELSE 'synthetic_assignment' END AS campus_review_status,
               i.institution_name AS ipeds_institution_name, i.county_fips, i.cbsa_code, i.state_abbr,
               i.source_id AS geo_source_id, i.vintage AS geo_vintage, i.review_status AS geo_review_status,
               a.area_key AS oews_local_area_key,
               i.county_fips AS qcew_area_fips, '17' AS qwi_state_fips, '6113' AS qwi_industry,
               CASE WHEN ca.unitid IS NULL THEN 'org_not_under_an_assigned_campus' END AS campus_null_reason
        FROM o JOIN lvl l USING (org_code)
        LEFT JOIN campus_assignment ca ON ca.campus_org_code = coalesce(l.campus_child, l.root_code)
        LEFT JOIN ext_ipeds_institution i ON i.unitid = ca.unitid
        LEFT JOIN (SELECT DISTINCT area, area_key FROM ext_oews WHERE area_key LIKE 'msa_%') a ON a.area = i.cbsa_code""")


def build_class_internal(con, res: M.Resolution) -> None:
    has_rf = res.available("role_family")
    has_ec = res.available("employee_class")
    rf = "LEFT JOIN c_role_family rf ON rf.job_class_code = j.job_class_code" if has_rf else \
        "LEFT JOIN (SELECT NULL::VARCHAR AS job_class_code, NULL::VARCHAR AS role_family, NULL::INTEGER AS role_level, NULL::VARCHAR AS critical_ind) rf ON FALSE"
    ec = """LEFT JOIN (SELECT job_class_code, mode(employee_class_code ORDER BY employee_class_code) AS ecls
                       FROM c_appointment GROUP BY 1) ae ON ae.job_class_code = j.job_class_code
            LEFT JOIN c_employee_class ec ON ec.employee_class_code = ae.ecls""" if has_ec else \
        "LEFT JOIN (SELECT NULL::VARCHAR AS job_class_code) ae ON FALSE LEFT JOIN (SELECT NULL::VARCHAR AS description) ec ON FALSE"
    con.execute(f"""CREATE OR REPLACE TABLE dim_job_class_internal AS
        SELECT j.job_class_code, j.class_source, j.class_title, j.min_annual_amount, j.max_annual_amount,
               coalesce(rf.role_family, ce.ce_job_family, ec.description, 'Unassigned') AS role_family,
               CASE WHEN rf.role_family IS NOT NULL THEN 'sample_role_family_reference'
                    WHEN ce.ce_job_family IS NOT NULL THEN 'fallback_class_evolution_title_keyword_family'
                    WHEN ec.description IS NOT NULL THEN 'fallback_employee_class_description'
                    ELSE 'unassigned' END AS role_family_source,
               rf.role_level, rf.critical_ind
        FROM (SELECT DISTINCT * FROM c_job_class) j
        {rf}
        LEFT JOIN ext_class_evolution ce ON ce.class_code = j.job_class_code
        {ec}""")


def build_class_bridges(con, m: dict, bridges: dict) -> None:
    public = in_list(M.code_values(m, "class_source_public_sucss"))
    con.execute(f"""CREATE OR REPLACE TABLE br_class_sucss AS
        WITH cand AS (
            SELECT j.job_class_code, j.class_title, s.source_record_id, s.class_title AS sucss_class_title,
                   s.occupational_line, s.source_id, s.vintage,
                   count(*) OVER (PARTITION BY j.job_class_code) AS n_records,
                   norm_title(j.class_title) = norm_title(s.class_title) AS title_eq,
                   sum(CASE WHEN norm_title(j.class_title) = norm_title(s.class_title) THEN 1 ELSE 0 END)
                       OVER (PARTITION BY j.job_class_code) AS n_title_eq
            FROM dim_job_class_internal j JOIN ext_sucss_class s ON s.class_code = j.job_class_code),
        pick AS (SELECT *, row_number() OVER (PARTITION BY job_class_code
                     ORDER BY CASE WHEN n_title_eq = 1 AND title_eq THEN 0 ELSE 1 END, source_record_id) AS rn FROM cand)
        SELECT j.job_class_code, j.class_title, j.class_source, p.source_record_id, p.sucss_class_title,
               p.occupational_line AS sucss_occupational_line, coalesce(p.n_records, 0) AS n_sucss_records,
               p.title_eq AS sample_title_agrees,
               CASE WHEN p.source_record_id IS NULL AND j.class_source IN {public} THEN 'code_not_in_sucss_catalog'
                    WHEN p.source_record_id IS NULL THEN 'local_class_no_sucss_record'
                    WHEN p.n_records = 1 THEN 'exact_code'
                    WHEN p.n_title_eq = 1 THEN 'exact_code_multi_record_title_resolved'
                    ELSE 'exact_code_multi_record_ambiguous' END AS sucss_match_type,
               coalesce(p.source_id, 'sucss_catalog') AS sucss_source_id, coalesce(p.vintage, 'acquired 2026-10-29') AS sucss_vintage,
               CASE WHEN p.source_record_id IS NULL THEN NULL ELSE 'derived_rule' END AS sucss_review_status
        FROM dim_job_class_internal j LEFT JOIN pick p ON p.job_class_code = j.job_class_code AND p.rn = 1""")

    b = bridges["by_id"]["sucss_to_onet"]["params"]
    fallback = bool(b.get("allow_title_lexical_fallback"))
    con.execute(f"""CREATE OR REPLACE TABLE br_sucss_onet AS
        WITH r1 AS (SELECT * FROM ext_sucss_onet_candidates WHERE candidate_rank = 1),
        lx AS (SELECT * FROM ext_sucss_onet_lexical WHERE candidate_rank = 1)
        SELECT s.source_record_id, s.class_code,
               CASE WHEN NOT r1.abstained THEN r1.onetsoc_code
                    WHEN {str(fallback).lower()} THEN lx.onetsoc_code END AS onet_code,
               CASE WHEN NOT r1.abstained THEN r1.occupation_title
                    WHEN {str(fallback).lower()} THEN lx.occupation_title END AS onet_title,
               CASE WHEN NOT r1.abstained THEN r1.method
                    WHEN {str(fallback).lower()} AND lx.onetsoc_code IS NOT NULL THEN lx.method || ' (fallback after abstain; flagged)' END AS onet_method,
               CASE WHEN NOT r1.abstained THEN r1.evidence_index END AS onet_evidence_index,
               CASE WHEN NOT r1.abstained THEN r1.evidence_band END AS onet_evidence_band,
               r1.abstained AS onet_abstained, r1.abstain_reason AS onet_abstain_reason, r1.top1_margin AS onet_top1_margin,
               r1.has_spec_duties, (r1.abstained AND {str(fallback).lower()} AND lx.onetsoc_code IS NOT NULL) AS onet_used_lexical_fallback,
               CASE WHEN r1.source_record_id IS NULL THEN 'no_onet_candidate_for_record'
                    WHEN r1.abstained AND NOT {str(fallback).lower()} THEN 'onet_match_abstained: ' || coalesce(r1.abstain_reason, 'unspecified') END
                    AS onet_null_reason,
               coalesce(r1.source_id, 'sucss_mapping') AS onet_source_id, coalesce(r1.vintage, 'sucss_duty_tfidf_v1') AS onet_vintage,
               coalesce(r1.review_status, 'unreviewed') AS onet_review_status
        FROM ext_sucss_class s LEFT JOIN r1 USING (source_record_id) LEFT JOIN lx USING (source_record_id)""")
    k = int(b.get("top_k", 3))
    con.execute(f"""CREATE OR REPLACE TABLE br_sucss_onet_topk AS
        SELECT source_record_id, class_code, candidate_rank, onetsoc_code, occupation_title, evidence_index, evidence_band,
               abstained,
               round(evidence_index / sum(evidence_index) OVER (PARTITION BY source_record_id), 4) AS display_weight,
               {lit(b.get('top_k_weight_note'))} AS display_weight_note,
               source_id, vintage, review_status
        FROM ext_sucss_onet_candidates WHERE candidate_rank <= {k}""")

    # SOC -> OEWS (detailed, else broad roll-up flagged; a published-but-suppressed detailed row is kept as NULL)
    con.execute("""CREATE OR REPLACE TABLE br_soc_oews AS
        WITH socs AS (SELECT DISTINCT soc_2018_code FROM ext_onet_soc),
        d AS (SELECT s.soc_2018_code, o.*, 'detailed' AS soc_match FROM socs s JOIN ext_oews o ON o.occ_code = s.soc_2018_code),
        b AS (SELECT s.soc_2018_code, o.*, 'broad_rollup' AS soc_match FROM socs s
              JOIN ext_oews o ON o.occ_code = soc_broad(s.soc_2018_code) AND soc_broad(s.soc_2018_code) <> s.soc_2018_code
              WHERE NOT EXISTS (SELECT 1 FROM ext_oews o2 WHERE o2.occ_code = s.soc_2018_code
                                AND o2.survey_year IS NOT DISTINCT FROM o.survey_year AND o2.area_key = o.area_key))
        SELECT * FROM d UNION ALL BY NAME SELECT * FROM b""")
    con.execute("""CREATE OR REPLACE TABLE br_soc_projections AS
        WITH socs AS (SELECT DISTINCT soc_2018_code FROM ext_onet_soc)
        SELECT s.soc_2018_code, p.*, CASE WHEN p.soc = s.soc_2018_code THEN 'detailed' ELSE 'broad_rollup' END AS soc_match
        FROM socs s JOIN ext_projections p ON p.soc = s.soc_2018_code
           OR (p.soc = soc_broad(s.soc_2018_code)
               AND NOT EXISTS (SELECT 1 FROM ext_projections p2 WHERE p2.soc = s.soc_2018_code))""")


def build_class_external(con, bridges: dict) -> None:
    year = int(bridges["by_id"]["soc_to_bls_oews"]["params"]["primary_year"])
    oews_cols = []
    for a in OEWS_AREAS:
        for m, c in (("emp", "tot_emp"), ("median", "a_median"), ("p10", "a_pct10"), ("p90", "a_pct90")):
            oews_cols.append(f"max(o.{c}) FILTER (WHERE o.area_key = {lit(a)} AND o.survey_year = {year}) AS oews_{a}_{m}")
        oews_cols.append(f"max(o.a_median_flag) FILTER (WHERE o.area_key = {lit(a)} AND o.survey_year = {year}) AS oews_{a}_median_flag")
    oews_cols.append(f"max(o.a_median) FILTER (WHERE o.area_key = 'national' AND o.survey_year = {year - 1}) AS oews_national_median_2024")
    oews_cols.append(f"max(o.soc_match) FILTER (WHERE o.area_key = 'national' AND o.survey_year = {year}) AS oews_soc_match")
    oews_cols.append(f"count(*) FILTER (WHERE o.survey_year = {year}) AS oews_rows_{year}")
    con.execute(f"""CREATE OR REPLACE TEMP TABLE soc_oews_wide AS
        SELECT o.soc_2018_code, {', '.join(oews_cols)} FROM br_soc_oews o GROUP BY 1""")
    con.execute(f"""CREATE OR REPLACE TABLE dim_job_class_external AS
        WITH chain AS (
            SELECT j.*, b.source_record_id, b.sucss_class_title, b.sucss_occupational_line, b.n_sucss_records,
                   b.sample_title_agrees, b.sucss_match_type, b.sucss_source_id, b.sucss_vintage, b.sucss_review_status,
                   so.onet_code, so.onet_title, so.onet_method, so.onet_evidence_index, so.onet_evidence_band,
                   so.onet_abstained, so.onet_abstain_reason, so.onet_top1_margin, so.onet_used_lexical_fallback,
                   so.onet_source_id, so.onet_vintage, so.onet_review_status,
                   x.soc_2018_code, x.soc_2018_title, x.source_id AS soc_source_id, x.vintage AS soc_vintage,
                   CASE WHEN x.soc_2018_code IS NOT NULL THEN x.review_status END AS soc_review_status,
                   CASE WHEN b.source_record_id IS NULL THEN b.sucss_match_type
                        WHEN so.onet_code IS NULL THEN coalesce(so.onet_null_reason, 'no_onet_link')
                        WHEN x.soc_2018_code IS NULL THEN 'onet_code_not_in_soc_crosswalk' END AS external_null_reason
            FROM dim_job_class_internal j
            JOIN br_class_sucss b USING (job_class_code)
            LEFT JOIN br_sucss_onet so ON so.source_record_id = b.source_record_id
            LEFT JOIN ext_onet_soc x ON x.onetsoc_code = so.onet_code)
        SELECT c.*,
               CASE WHEN c.onet_code IS NULL THEN NULL
                    ELSE concat_ws(';', 'unreviewed', CASE WHEN c.onet_used_lexical_fallback THEN 'lexical_fallback' END) END
                    AS chain_review_status,
               {', '.join('w.' + x.split(' AS ')[-1] for x in oews_cols)},
               CASE WHEN c.soc_2018_code IS NOT NULL THEN 'bls_oews' END AS oews_source_id,
               CASE WHEN c.soc_2018_code IS NOT NULL THEN 'OEWS May {year}' END AS oews_vintage,
               CASE WHEN c.soc_2018_code IS NOT NULL THEN 'publisher_asserted' END AS oews_review_status,
               CASE WHEN c.external_null_reason IS NOT NULL THEN c.external_null_reason
                    WHEN coalesce(w.oews_rows_{year}, 0) = 0 THEN 'soc_not_published_in_oews_{year}'
                    WHEN w.oews_national_median IS NULL THEN 'oews_national_median_suppressed:' || coalesce(w.oews_national_median_flag, '?') END
                    AS oews_null_reason,
               p.emp_2025_k AS proj_emp_2025_k, p.growth_pct_2025_35 AS proj_growth_pct_2025_35,
               p.openings_rate_pct AS proj_openings_rate_pct, p.occ_separations_rate_pct AS proj_occ_separations_rate_pct,
               p.labor_force_exit_rate_pct AS proj_labor_force_exit_rate_pct, p.occ_transfer_rate_pct AS proj_occ_transfer_rate_pct,
               p.soc_match AS proj_soc_match,
               CASE WHEN c.soc_2018_code IS NOT NULL THEN 'bls_projections' END AS projections_source_id,
               CASE WHEN c.soc_2018_code IS NOT NULL THEN 'Employment Projections 2025-35' END AS projections_vintage,
               CASE WHEN c.soc_2018_code IS NOT NULL THEN 'publisher_asserted' END AS projections_review_status,
               CASE WHEN c.external_null_reason IS NOT NULL THEN c.external_null_reason
                    WHEN p.soc IS NULL THEN 'soc_not_in_projections_matrix' END AS projections_null_reason,
               t.median_wage_cagr_pct AS oews_trend_median_cagr_pct, t.n_years AS oews_trend_n_years,
               t.first_year AS oews_trend_first_year, t.last_year AS oews_trend_last_year,
               CASE WHEN c.soc_2018_code IS NOT NULL THEN 'bls_oews' END AS oews_trend_source_id,
               CASE WHEN c.soc_2018_code IS NOT NULL THEN coalesce(t.vintage, 'OEWS national May 2015-2025') END AS oews_trend_vintage,
               CASE WHEN c.soc_2018_code IS NOT NULL THEN 'publisher_asserted' END AS oews_trend_review_status,
               a.observed_exposure AS aei_observed_exposure,
               CASE WHEN c.soc_2018_code IS NOT NULL THEN 'anthropic_economic_index' END AS aei_source_id,
               CASE WHEN c.soc_2018_code IS NOT NULL THEN 'labor_market_impacts' END AS aei_vintage,
               CASE WHEN c.soc_2018_code IS NOT NULL THEN 'publisher_asserted' END AS aei_review_status,
               CASE WHEN c.external_null_reason IS NOT NULL THEN c.external_null_reason
                    WHEN a.soc_2018_code IS NULL THEN 'soc_not_in_aei' END AS aei_null_reason,
               op.job_zone AS onet_job_zone, op.n_tasks AS onet_n_tasks, op.n_tech AS onet_n_tech, op.n_hot_tech AS onet_n_hot_tech,
               CASE WHEN c.onet_code IS NOT NULL THEN 'onet_db_31_0' END AS onet_profile_source_id,
               CASE WHEN c.onet_code IS NOT NULL THEN 'O*NET 31.0' END AS onet_profile_vintage,
               CASE WHEN c.onet_code IS NOT NULL THEN 'publisher_asserted' END AS onet_profile_review_status,
               CASE WHEN c.onet_code IS NOT NULL THEN je.watch_score END AS je_watch_score,
               CASE WHEN c.onet_code IS NOT NULL THEN je.p_task_update_2y END AS je_p_task_update_2y,
               CASE WHEN c.onet_code IS NOT NULL THEN je.p_task_high END AS je_p_task_high,
               CASE WHEN c.onet_code IS NOT NULL THEN je.p_tech_high END AS je_p_tech_high,
               je.je_family, je.onet_code AS je_onet_code,
               CASE WHEN c.source_record_id IS NOT NULL THEN 'job_evolution' END AS job_evolution_source_id,
               CASE WHEN c.source_record_id IS NOT NULL THEN 'O*NET 13.0-31.0 panel' END AS job_evolution_vintage,
               CASE WHEN c.source_record_id IS NOT NULL THEN 'unreviewed' END AS job_evolution_review_status,
               CASE WHEN c.external_null_reason IS NOT NULL THEN c.external_null_reason
                    WHEN je.watch_score IS NULL THEN 'no_job_evolution_score' END AS job_evolution_null_reason,
               ce.ce_status, ce.spec_effective_date AS ce_spec_effective_date, ce.last_revision_date AS ce_last_revision_date,
               ce.years_since_last_revision AS ce_spec_age_years, ce.n_known_revisions AS ce_n_known_revisions,
               ce.n_final_notices AS ce_n_final_notices, ce.open_process AS ce_open_process,
               ce.stale_flag AS ce_stale_flag, ce.lag_flag AS ce_lag_flag,
               ce.revision_risk_index AS ce_revision_risk_index, ce.revision_risk_rank AS ce_revision_risk_rank,
               ce.revision_risk_mode AS ce_revision_risk_mode,
               CASE WHEN ce.class_code IS NOT NULL THEN ce.source_id END AS class_evolution_source_id,
               CASE WHEN ce.class_code IS NOT NULL THEN ce.vintage END AS class_evolution_vintage,
               CASE WHEN ce.class_code IS NOT NULL THEN ce.review_status END AS class_evolution_review_status,
               CASE WHEN ce.class_code IS NULL THEN 'class_code_not_in_class_evolution' END AS class_evolution_null_reason
        FROM chain c
        LEFT JOIN soc_oews_wide w ON w.soc_2018_code = c.soc_2018_code
        LEFT JOIN br_soc_projections p ON p.soc_2018_code = c.soc_2018_code
        LEFT JOIN ext_oews_trend t ON t.occ_code = c.soc_2018_code
        LEFT JOIN ext_aei a ON a.soc_2018_code = c.soc_2018_code
        LEFT JOIN ext_onet_profile op ON op.onetsoc_code = c.onet_code
        LEFT JOIN ext_job_evolution je ON je.source_record_id = c.source_record_id
        LEFT JOIN ext_class_evolution ce ON ce.class_code = c.job_class_code""")
    union = []
    for col, grp in measure_registry():
        g = {"onet_match": "onet"}.get(grp, grp)
        union.append(f"""SELECT job_class_code, {lit(col)} AS measure, CAST({col} AS VARCHAR) AS value,
            {g}_source_id AS source_id, {g}_vintage AS vintage, {g}_review_status AS review_status,
            chain_review_status, {lit(grp)} AS provenance_group,
            CASE WHEN {col} IS NULL THEN coalesce({'external_null_reason' if grp in ('sucss', 'onet_match', 'soc') else grp + '_null_reason' if grp in ('oews', 'projections', 'aei', 'job_evolution', 'class_evolution') else 'external_null_reason'}, 'value_not_published') END AS null_reason
            FROM dim_job_class_external""")
    con.execute("CREATE OR REPLACE TABLE fact_class_external_long AS " + " UNION ALL ".join(union))


def snapshot_dates(con, as_of: list[str] | None, known: str) -> list[tuple[str, str]]:
    ref = con.execute("""SELECT max(d) FROM (
        SELECT max(valid_from) AS d FROM c_appointment WHERE valid_from < DATE '9999-01-01'
        UNION ALL SELECT max(term_date) FROM c_separation)""").fetchall()[0][0]
    if as_of:
        dates = sorted(set(as_of))
    else:
        dates = [f"{y}-06-30" for y in range(ref.year - 10, ref.year + 1) if dt.date(y, 6, 30) <= ref]
    pairs = [(d, d if known == "as_of" else LATEST_KNOWLEDGE) for d in dates]
    return pairs


def position_org_sql(res: M.Resolution) -> str:
    """Org of each snapshot position. Positions carry an org column in v1/v2; the Data Cookbook's T_POSN_HIST
    has none, so the org is derived from the position's job records as known at known_as_of: the latest
    job effective on or before the as-of date, else the earliest job, else the campus org of the position's
    chart (COA_CD), else NULL. Returns a SELECT over snap_posn_raw yielding (as_of_date, known_as_of,
    position_id, org_code, org_source)."""
    if res.has_field("position", "org_code"):
        return """SELECT as_of_date, known_as_of, position_id, org_code,
                         CASE WHEN org_code IS NOT NULL THEN 'position_record' END AS org_source FROM snap_posn_raw"""
    chart = ("LEFT JOIN (SELECT chart_code, min(org_code) AS campus_org FROM c_org o "
             "WHERE o.parent_org_code IS NULL OR o.parent_org_code IN (SELECT org_code FROM c_org WHERE parent_org_code IS NULL) "
             "GROUP BY 1) ch ON ch.chart_code = p.chart_code") if res.has_field("position", "chart_code") and res.has_field("org", "chart_code") \
        else "LEFT JOIN (SELECT NULL::VARCHAR AS campus_org) ch ON FALSE"
    return f"""WITH j AS (
            SELECT p.as_of_date, p.known_as_of, p.position_id, a.org_code, a.valid_from,
                   row_number() OVER (PARTITION BY p.as_of_date, p.known_as_of, p.position_id
                                      ORDER BY CASE WHEN a.valid_from <= p.as_of_date THEN 0 ELSE 1 END,
                                               CASE WHEN a.valid_from <= p.as_of_date THEN -epoch(a.valid_from) ELSE epoch(a.valid_from) END,
                                               a.fte DESC NULLS LAST, a.person_id, a.job_suffix) AS rn
            FROM snap_posn_raw p JOIN c_appointment a ON a.position_id = p.position_id
             AND a.known_from <= p.known_as_of AND a.known_to > p.known_as_of)
        SELECT p.as_of_date, p.known_as_of, p.position_id, coalesce(j.org_code, ch.campus_org) AS org_code,
               CASE WHEN j.org_code IS NOT NULL THEN 'derived_from_jobs' WHEN ch.campus_org IS NOT NULL THEN 'campus_of_position_chart' END AS org_source
        FROM snap_posn_raw p LEFT JOIN j ON j.as_of_date = p.as_of_date AND j.known_as_of = p.known_as_of
             AND j.position_id = p.position_id AND j.rn = 1
        {chart}"""


def build_snapshots(con, m: dict, pairs: list[tuple[str, str]], bridges: dict, res: M.Resolution | None = None) -> None:
    year = int(bridges["by_id"]["soc_to_bls_oews"]["params"]["primary_year"])
    act = in_list(M.code_values(m, "appointment_status_active"))
    pact = in_list(M.code_values(m, "position_status_active"))
    vals = ", ".join(f"(DATE {lit(a)}, DATE {lit(k)})" for a, k in pairs)
    con.execute(f"CREATE OR REPLACE TEMP TABLE snap_dates AS SELECT * FROM (VALUES {vals}) t(as_of_date, known_as_of)")
    # Inclusive effective interval; half-open recorded interval [known_from, known_to).
    con.execute(f"""CREATE OR REPLACE TEMP TABLE snap_appt AS
        SELECT s.as_of_date, s.known_as_of, a.*
        FROM snap_dates s JOIN c_appointment a
          ON a.valid_from <= s.as_of_date AND a.valid_to >= s.as_of_date
         AND a.known_from <= s.known_as_of AND a.known_to > s.known_as_of
        WHERE a.status_code IN {act}""")
    con.execute(f"""CREATE OR REPLACE TEMP TABLE snap_posn_raw AS
        SELECT * FROM (
            SELECT s.as_of_date, s.known_as_of, p.*,
                   row_number() OVER (PARTITION BY s.as_of_date, s.known_as_of, p.position_id
                                      ORDER BY p.valid_from DESC, p.known_from DESC, p.status_code, p.job_class_code, p.org_code) AS rn,
                   count(*) OVER (PARTITION BY s.as_of_date, s.known_as_of, p.position_id) AS n_position_rows
            FROM snap_dates s JOIN c_position p
              ON p.valid_from <= s.as_of_date AND p.valid_to >= s.as_of_date
             AND p.known_from <= s.known_as_of AND p.known_to > s.known_as_of)
        WHERE rn = 1""")
    if res is not None and not res.has_field("position", "org_code"):
        con.execute(f"""CREATE OR REPLACE TEMP TABLE snap_posn AS
            SELECT r.* REPLACE (o.org_code AS org_code) FROM snap_posn_raw r
            JOIN ({position_org_sql(res)}) o USING (as_of_date, known_as_of, position_id)""")
    else:
        con.execute("CREATE OR REPLACE TEMP TABLE snap_posn AS SELECT * FROM snap_posn_raw")
    con.execute(f"""CREATE OR REPLACE TABLE fact_position_snapshot AS
        WITH inc AS (
            SELECT as_of_date, known_as_of, position_id,
                   count(DISTINCT person_id) AS incumbent_count,
                   count(DISTINCT (person_id, job_suffix)) AS appointment_count,
                   sum(fte) AS filled_fte, avg(annual_salary) AS mean_annual_salary,
                   min(job_class_code) AS appt_class_code, count(DISTINCT job_class_code) AS n_appt_classes,
                   min(org_code) AS appt_org_code
            FROM snap_appt GROUP BY ALL),
        spine AS (
            SELECT coalesce(p.as_of_date, i.as_of_date) AS as_of_date, coalesce(p.known_as_of, i.known_as_of) AS known_as_of,
                   coalesce(p.position_id, i.position_id) AS position_id,
                   p.position_id IS NOT NULL AS position_record_present, p.status_code AS position_status_code,
                   coalesce(p.status_code IN {pact}, FALSE) AS position_active, p.n_position_rows,
                   p.budget_fte, coalesce(p.job_class_code, i.appt_class_code) AS job_class_code,
                   (p.job_class_code IS NOT NULL AND i.appt_class_code IS NOT NULL AND p.job_class_code <> i.appt_class_code) AS class_mismatch,
                   coalesce(p.org_code, i.appt_org_code) AS org_code,
                   coalesce(i.incumbent_count, 0) AS incumbent_count, coalesce(i.appointment_count, 0) AS appointment_count,
                   coalesce(i.filled_fte, 0) AS filled_fte, i.mean_annual_salary
            FROM snap_posn p FULL OUTER JOIN inc i
              ON i.as_of_date = p.as_of_date AND i.known_as_of = p.known_as_of AND i.position_id = p.position_id)
        SELECT s.*, (s.position_active AND s.incumbent_count = 0) AS vacant,
               o.campus_org_code, o.campus_unitid, o.campus_label, j.role_family, j.class_source,
               j.min_annual_amount AS class_min_annual, j.max_annual_amount AS class_max_annual,
               CASE WHEN s.mean_annual_salary IS NOT NULL AND j.max_annual_amount > j.min_annual_amount
                    THEN round((s.mean_annual_salary - j.min_annual_amount) / (j.max_annual_amount - j.min_annual_amount), 4) END AS range_position,
               CASE WHEN s.mean_annual_salary IS NOT NULL AND (j.min_annual_amount + j.max_annual_amount) > 0
                    THEN round(s.mean_annual_salary / ((j.min_annual_amount + j.max_annual_amount) / 2), 4) END AS compa_ratio,
               s.mean_annual_salary < j.min_annual_amount AS below_class_min,
               s.mean_annual_salary > j.max_annual_amount AS above_class_max,
               e.soc_2018_code, o.oews_local_area_key,
               CASE o.oews_local_area_key
                    WHEN 'msa_champaign_urbana' THEN e.oews_msa_champaign_urbana_median
                    WHEN 'msa_chicago' THEN e.oews_msa_chicago_median
                    WHEN 'msa_springfield' THEN e.oews_msa_springfield_median END AS oews_local_median,
               e.oews_illinois_median AS oews_il_median,
               round(s.mean_annual_salary / nullif(CASE o.oews_local_area_key
                    WHEN 'msa_champaign_urbana' THEN e.oews_msa_champaign_urbana_median
                    WHEN 'msa_chicago' THEN e.oews_msa_chicago_median
                    WHEN 'msa_springfield' THEN e.oews_msa_springfield_median END, 0), 4) AS market_pay_ratio_local,
               round(s.mean_annual_salary / nullif(e.oews_illinois_median, 0), 4) AS market_pay_ratio_il,
               CASE WHEN e.soc_2018_code IS NOT NULL THEN 'bls_oews' END AS market_source_id,
               CASE WHEN e.soc_2018_code IS NOT NULL THEN 'OEWS May {year}' END AS market_vintage,
               CASE WHEN e.soc_2018_code IS NOT NULL THEN 'publisher_asserted' END AS market_review_status,
               CASE WHEN e.soc_2018_code IS NOT NULL
                    THEN concat_ws(';', e.chain_review_status, CASE WHEN o.campus_review_status IS NOT NULL THEN 'synthetic_assignment' END) END
                    AS market_chain_review_status,
               CASE WHEN s.mean_annual_salary IS NULL THEN 'no_incumbent_salary'
                    WHEN e.job_class_code IS NULL THEN 'class_not_in_reference'
                    WHEN e.external_null_reason IS NOT NULL THEN e.external_null_reason
                    WHEN o.campus_unitid IS NULL THEN 'org_not_mapped_to_campus'
                    WHEN e.oews_illinois_median IS NULL THEN 'oews_il_median_unavailable' END AS market_null_reason
        FROM spine s
        LEFT JOIN dim_org_external o ON o.org_code = s.org_code
        LEFT JOIN dim_job_class_internal j ON j.job_class_code = s.job_class_code
        LEFT JOIN dim_job_class_external e ON e.job_class_code = s.job_class_code""")


def headcount_sql(dates_table: str) -> str:
    """Distinct-person headcount by primary assignment (highest FTE, then lowest position) at each date."""
    return f"""
        SELECT as_of_date, known_as_of, campus_org_code, role_family, job_class_code,
               count(*) AS headcount, sum(person_fte) AS fte
        FROM (
            SELECT a.as_of_date, a.known_as_of, a.person_id, o.campus_org_code, j.role_family, a.job_class_code,
                   sum(a.fte) OVER (PARTITION BY a.as_of_date, a.known_as_of, a.person_id) AS person_fte,
                   row_number() OVER (PARTITION BY a.as_of_date, a.known_as_of, a.person_id
                                      ORDER BY a.fte DESC NULLS LAST, a.position_id, a.job_suffix) AS rn
            FROM {dates_table} a
            LEFT JOIN dim_org_external o ON o.org_code = a.org_code
            LEFT JOIN dim_job_class_internal j ON j.job_class_code = a.job_class_code)
        WHERE rn = 1
        GROUP BY ALL"""


def build_headcount(con) -> None:
    con.execute(f"CREATE OR REPLACE TABLE fact_headcount_asof AS {headcount_sql('snap_appt')}")


def build_flows(con, m: dict, years: tuple[int, int] | None) -> dict:
    act = in_list(M.code_values(m, "appointment_status_active"))
    surs = in_list(M.code_values(m, "surs_retirement_yes"))
    reasons = M.code_map(m, "separation_reason_group")
    rcase = "CASE " + " ".join(f"WHEN term_reason_code = {lit(k)} THEN {lit(v)}" for k, v in sorted(reasons.items())) + " ELSE 'other' END"
    K = LATEST_KNOWLEDGE
    con.execute(f"""CREATE OR REPLACE TEMP TABLE cur_appt AS
        SELECT * FROM c_appointment WHERE known_from <= DATE '{K}' AND known_to > DATE '{K}' AND status_code IN {act}""")
    ref = con.execute("""SELECT max(d) FROM (SELECT max(valid_from) d FROM cur_appt
                         UNION ALL SELECT max(term_date) FROM c_separation)""").fetchall()[0][0]
    last = ref.year
    partial_last = (ref.month, ref.day) != (12, 31)
    y0, y1 = years if years else (last - 20, last)
    con.execute(f"""CREATE OR REPLACE TABLE fact_appointment_events AS
        WITH o AS (
            SELECT a.*, row_number() OVER w AS rn,
                   lag(position_id) OVER w AS prev_position_id, lag(job_class_code) OVER w AS prev_class_code,
                   lag(org_code) OVER w AS prev_org_code, lag(valid_to) OVER w AS prev_valid_to,
                   max(valid_to) OVER (PARTITION BY person_id ORDER BY valid_from, valid_to, position_id, job_suffix
                                       ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS prev_max_to
            FROM cur_appt a
            WINDOW w AS (PARTITION BY person_id ORDER BY valid_from, valid_to, position_id, job_suffix)),
        e AS (
            SELECT *, CASE WHEN rn = 1 THEN 'external_hire'
                           WHEN valid_from > prev_max_to + INTERVAL 1 DAY THEN 'rehire'
                           WHEN position_id = prev_position_id THEN CASE WHEN job_class_code <> prev_class_code THEN 'reclassification' END
                           WHEN prev_valid_to = valid_from - INTERVAL 1 DAY THEN 'internal_move'
                           ELSE 'additional_appointment' END AS event_type
            FROM o)
        SELECT e.person_id, e.position_id, e.job_suffix, e.valid_from AS event_date, year(e.valid_from) AS year, e.event_type,
               e.job_class_code, e.prev_class_code, e.org_code, e.prev_org_code,
               o1.campus_org_code, o0.campus_org_code AS prev_campus_org_code, j.role_family,
               (e.event_type IN ('internal_move', 'reclassification') AND e.job_class_code <> e.prev_class_code) AS class_transition,
               (e.event_type = 'internal_move' AND e.org_code <> e.prev_org_code) AS transfer_cross_org,
               (e.event_type = 'internal_move' AND o1.campus_org_code IS DISTINCT FROM o0.campus_org_code) AS transfer_cross_campus
        FROM e
        LEFT JOIN dim_org_external o1 ON o1.org_code = e.org_code
        LEFT JOIN dim_org_external o0 ON o0.org_code = e.prev_org_code
        LEFT JOIN dim_job_class_internal j ON j.job_class_code = e.job_class_code
        WHERE e.event_type IS NOT NULL""")
    con.execute(f"""CREATE OR REPLACE TABLE fact_separation_events AS
        WITH s AS (SELECT DISTINCT person_id, term_date, term_reason_code, surs_retirement_ind FROM c_separation
                   WHERE known_from <= DATE '{K}' AND known_to > DATE '{K}' AND term_date IS NOT NULL),
        last AS (
            SELECT s.*, a.org_code, a.job_class_code,
                   row_number() OVER (PARTITION BY s.person_id, s.term_date
                                      ORDER BY a.valid_from DESC NULLS LAST, a.fte DESC NULLS LAST, a.position_id, a.job_suffix) AS rn
            FROM s LEFT JOIN cur_appt a ON a.person_id = s.person_id AND a.valid_from <= s.term_date)
        SELECT l.person_id, l.term_date, year(l.term_date) AS year, l.term_reason_code, {rcase} AS reason_group,
               l.surs_retirement_ind IN {surs} AS surs_retirement, l.org_code, l.job_class_code,
               o.campus_org_code, coalesce(j.role_family, 'Unassigned') AS role_family
        FROM last l LEFT JOIN dim_org_external o ON o.org_code = l.org_code
        LEFT JOIN dim_job_class_internal j ON j.job_class_code = l.job_class_code
        WHERE l.rn = 1""")
    # headcount at Jan 1 and Dec 31 of each year, as known today
    vals = ", ".join(f"(DATE '{y}-01-01', DATE '{K}'), (DATE '{y}-12-31', DATE '{K}')" for y in range(y0, y1 + 1))
    con.execute(f"CREATE OR REPLACE TEMP TABLE hc_dates AS SELECT * FROM (VALUES {vals}) t(as_of_date, known_as_of)")
    con.execute("""CREATE OR REPLACE TEMP TABLE hc_appt AS
        SELECT s.as_of_date, s.known_as_of, a.* FROM hc_dates s JOIN cur_appt a
          ON a.valid_from <= s.as_of_date AND a.valid_to >= s.as_of_date""")
    con.execute(f"CREATE OR REPLACE TEMP TABLE hc_year AS {headcount_sql('hc_appt')}")
    con.execute(f"""CREATE OR REPLACE TABLE fact_flows_year AS
        WITH hc AS (
            SELECT year(as_of_date) AS year, campus_org_code, role_family,
                   sum(headcount) FILTER (WHERE month(as_of_date) = 1) AS headcount_start,
                   sum(headcount) FILTER (WHERE month(as_of_date) = 12) AS headcount_end
            FROM hc_year GROUP BY ALL),
        ev AS (
            SELECT year, campus_org_code, coalesce(role_family, 'Unassigned') AS role_family,
                   count(*) FILTER (WHERE event_type = 'external_hire') AS external_hires,
                   count(*) FILTER (WHERE event_type = 'rehire') AS rehires,
                   count(*) FILTER (WHERE event_type = 'internal_move') AS internal_hires,
                   count(*) FILTER (WHERE event_type = 'additional_appointment') AS additional_appointments,
                   count(*) FILTER (WHERE transfer_cross_org) AS transfers_cross_org,
                   count(*) FILTER (WHERE transfer_cross_campus) AS transfers_cross_campus,
                   count(*) FILTER (WHERE class_transition) AS class_transitions,
                   count(*) FILTER (WHERE event_type = 'reclassification') AS reclassifications_in_place
            FROM fact_appointment_events WHERE year BETWEEN {y0} AND {y1} GROUP BY ALL),
        sp AS (
            SELECT year, campus_org_code, role_family, count(*) AS separations_total,
                   count(*) FILTER (WHERE reason_group = 'resignation') AS sep_resignation,
                   count(*) FILTER (WHERE reason_group = 'retirement') AS sep_retirement,
                   count(*) FILTER (WHERE reason_group = 'end_of_appointment') AS sep_end_of_appointment,
                   count(*) FILTER (WHERE reason_group = 'other') AS sep_other,
                   count(*) FILTER (WHERE surs_retirement) AS surs_retirement_ind
            FROM fact_separation_events WHERE year BETWEEN {y0} AND {y1} GROUP BY ALL),
        keys AS (SELECT year, campus_org_code, role_family FROM hc UNION SELECT year, campus_org_code, role_family FROM ev
                 UNION SELECT year, campus_org_code, role_family FROM sp)
        SELECT k.year, k.campus_org_code, o.campus_unitid, k.role_family,
               coalesce(hc.headcount_start, 0) AS headcount_start, coalesce(hc.headcount_end, 0) AS headcount_end,
               (coalesce(hc.headcount_start, 0) + coalesce(hc.headcount_end, 0)) / 2.0 AS avg_headcount,
               coalesce(external_hires, 0) AS external_hires, coalesce(rehires, 0) AS rehires,
               coalesce(internal_hires, 0) AS internal_hires, coalesce(additional_appointments, 0) AS additional_appointments,
               coalesce(transfers_cross_org, 0) AS transfers_cross_org, coalesce(transfers_cross_campus, 0) AS transfers_cross_campus,
               coalesce(class_transitions, 0) AS class_transitions, coalesce(reclassifications_in_place, 0) AS reclassifications_in_place,
               coalesce(separations_total, 0) AS separations_total, coalesce(sep_resignation, 0) AS sep_resignation,
               coalesce(sep_retirement, 0) AS sep_retirement, coalesce(sep_end_of_appointment, 0) AS sep_end_of_appointment,
               coalesce(sep_other, 0) AS sep_other, coalesce(surs_retirement_ind, 0) AS surs_retirement_ind,
               CASE WHEN (coalesce(hc.headcount_start, 0) + coalesce(hc.headcount_end, 0)) > 0
                    THEN round(100.0 * coalesce(separations_total, 0) / ((coalesce(hc.headcount_start, 0) + coalesce(hc.headcount_end, 0)) / 2.0), 2) END
                    AS separation_rate_pct,
               (k.year = {last} AND {str(partial_last).lower()}) AS partial_year,
               CAST(k.year AS VARCHAR) AS calendar_key
        FROM keys k
        LEFT JOIN hc USING (year, campus_org_code, role_family)
        LEFT JOIN ev USING (year, campus_org_code, role_family)
        LEFT JOIN sp USING (year, campus_org_code, role_family)
        LEFT JOIN (SELECT DISTINCT campus_org_code, campus_unitid FROM dim_org_external) o ON o.campus_org_code IS NOT DISTINCT FROM k.campus_org_code""")
    con.execute(f"""CREATE OR REPLACE TABLE dim_calendar_quarter AS
        SELECT CAST(d AS DATE) AS quarter_start, year(d) AS year, quarter(d) AS quarter,
               year(d) || 'Q' || quarter(d) AS qcew_qwi_key, CAST(year(d) AS VARCHAR) AS calendar_key,
               'M13' AS jolts_annual_period, 'integration_calendar' AS source_id, 'v1' AS vintage, 'derived_rule' AS review_status
        FROM range(DATE '{y0}-01-01', DATE '{y1 + 1}-01-01', INTERVAL 3 MONTH) t(d)""")
    return {"flow_years": [y0, y1], "reference_date": str(ref), "partial_last_year": partial_last}


def build_benchmarks(con, flow_info: dict) -> dict:
    y0f, y1f = flow_info["flow_years"]
    last_complete = y1f - 1 if flow_info["partial_last_year"] else y1f
    w0, w1 = last_complete - 2, last_complete
    latest = con.execute("SELECT max(as_of_date) FROM fact_position_snapshot").fetchall()[0][0]
    L = f"DATE '{latest}'"
    con.execute(f"""CREATE OR REPLACE TEMP TABLE class_hc AS
        SELECT job_class_code, role_family, sum(headcount) AS hc FROM fact_headcount_asof
        WHERE as_of_date = {L} AND known_as_of = {L} GROUP BY ALL""")
    con.execute(f"""CREATE OR REPLACE TABLE bench_separation_role_family AS
        WITH i AS (SELECT role_family, sum(separations_total) AS separations, sum(avg_headcount) AS headcount_years,
                          sum(sep_retirement) AS retirements, sum(sep_resignation) AS resignations
                   FROM fact_flows_year WHERE year BETWEEN {w0} AND {w1} GROUP BY 1),
        x AS (SELECT h.role_family, sum(h.hc) AS hc,
                     sum(h.hc * e.proj_occ_separations_rate_pct) / nullif(sum(h.hc) FILTER (WHERE e.proj_occ_separations_rate_pct IS NOT NULL), 0) AS proj_sep_rate,
                     sum(h.hc * e.proj_labor_force_exit_rate_pct) / nullif(sum(h.hc) FILTER (WHERE e.proj_labor_force_exit_rate_pct IS NOT NULL), 0) AS proj_exit_rate,
                     sum(h.hc) FILTER (WHERE e.proj_occ_separations_rate_pct IS NOT NULL) / nullif(sum(h.hc), 0) AS proj_coverage
              FROM class_hc h LEFT JOIN dim_job_class_external e USING (job_class_code) GROUP BY 1),
        q AS (SELECT avg(separation_rate_pct) AS qwi_rate, string_agg(DISTINCT CAST(year AS VARCHAR), ',' ORDER BY CAST(year AS VARCHAR)) AS qwi_years
              FROM ext_qwi_il_year WHERE year BETWEEN {w0} AND {w1} AND separation_rate_pct IS NOT NULL),
        j AS (SELECT avg(us_state_local_govt_education_ts_rate) AS jolts_rate FROM ext_jolts_year WHERE year BETWEEN {w0} AND {w1})
        SELECT coalesce(i.role_family, x.role_family) AS role_family, '{w0}-{w1}' AS window_years,
               i.separations, round(i.headcount_years, 1) AS headcount_years,
               round(100.0 * i.separations / nullif(i.headcount_years, 0), 2) AS internal_separation_rate_pct,
               round(100.0 * i.retirements / nullif(i.headcount_years, 0), 2) AS internal_retirement_rate_pct,
               round(x.proj_sep_rate, 2) AS bls_projected_occ_separation_rate_pct,
               round(x.proj_exit_rate, 2) AS bls_projected_labor_force_exit_rate_pct,
               round(x.proj_coverage, 3) AS bls_projection_headcount_coverage,
               'bls_projections' AS bls_source_id, 'Employment Projections 2025-35' AS bls_vintage,
               'publisher_asserted' AS bls_review_status, 'unreviewed' AS bls_chain_review_status,
               round(q.qwi_rate, 2) AS qwi_il_higher_ed_separation_rate_pct, q.qwi_years,
               'qwi_il' AS qwi_source_id, 'LEHD latest_release' AS qwi_vintage, 'publisher_asserted' AS qwi_review_status,
               round(j.jolts_rate, 2) AS jolts_us_state_local_govt_education_ts_rate_pct,
               'bls_jolts' AS jolts_source_id, 'JOLTS annual M13 NSA' AS jolts_vintage, 'publisher_asserted' AS jolts_review_status,
               'BLS rate = leaving the occupation (exits + transfers); QWI = all job separations, Illinois NAICS 6113 public+private; internal = synthetic' AS comparability_note
        FROM i FULL OUTER JOIN x ON x.role_family = i.role_family CROSS JOIN q CROSS JOIN j""")
    con.execute(f"""CREATE OR REPLACE TABLE bench_pay_role_family_campus AS
        SELECT role_family, campus_org_code, campus_unitid, campus_label,
               count(*) FILTER (WHERE incumbent_count > 0) AS filled_positions,
               round(median(mean_annual_salary), 0) AS internal_median_salary,
               round(median(oews_local_median), 0) AS oews_local_median_of_matched,
               round(median(oews_il_median), 0) AS oews_il_median_of_matched,
               round(median(market_pay_ratio_local), 3) AS median_market_pay_ratio_local,
               round(median(market_pay_ratio_il), 3) AS median_market_pay_ratio_il,
               round(median(compa_ratio), 3) AS median_compa_ratio_class_range,
               count(market_pay_ratio_local) AS n_with_local_ratio,
               round(count(market_pay_ratio_il) / nullif(count(*) FILTER (WHERE incumbent_count > 0), 0), 3) AS market_coverage_il,
               'bls_oews' AS market_source_id, 'OEWS May 2025' AS market_vintage, 'publisher_asserted' AS market_review_status,
               'unreviewed;synthetic_assignment' AS market_chain_review_status,
               {L} AS as_of_date
        FROM fact_position_snapshot WHERE as_of_date = {L} AND known_as_of = {L} AND incumbent_count > 0
        GROUP BY ALL""")
    con.execute(f"""CREATE OR REPLACE TABLE bench_ai_pressure_role_family AS
        WITH p AS (SELECT role_family, sum(incumbent_count) AS incumbents,
                          count(*) FILTER (WHERE position_active) AS active_positions,
                          count(*) FILTER (WHERE vacant) AS vacant_positions
                   FROM fact_position_snapshot WHERE as_of_date = {L} AND known_as_of = {L} GROUP BY 1),
        x AS (SELECT h.role_family, sum(h.hc) AS headcount,
                     sum(h.hc * e.aei_observed_exposure) / nullif(sum(h.hc) FILTER (WHERE e.aei_observed_exposure IS NOT NULL), 0) AS aei,
                     sum(h.hc) FILTER (WHERE e.aei_observed_exposure IS NOT NULL) / nullif(sum(h.hc), 0) AS aei_cov,
                     sum(h.hc * e.je_watch_score) / nullif(sum(h.hc) FILTER (WHERE e.je_watch_score IS NOT NULL), 0) AS watch,
                     sum(h.hc) FILTER (WHERE e.je_watch_score IS NOT NULL) / nullif(sum(h.hc), 0) AS watch_cov,
                     sum(h.hc * e.ce_revision_risk_index) / nullif(sum(h.hc) FILTER (WHERE e.ce_revision_risk_index IS NOT NULL), 0) AS risk,
                     sum(h.hc) FILTER (WHERE e.ce_stale_flag) / nullif(sum(h.hc) FILTER (WHERE e.ce_stale_flag IS NOT NULL), 0) AS stale_share,
                     sum(h.hc * e.ce_spec_age_years) / nullif(sum(h.hc) FILTER (WHERE e.ce_spec_age_years IS NOT NULL), 0) AS spec_age,
                     sum(h.hc * e.proj_growth_pct_2025_35) / nullif(sum(h.hc) FILTER (WHERE e.proj_growth_pct_2025_35 IS NOT NULL), 0) AS growth
              FROM class_hc h LEFT JOIN dim_job_class_external e USING (job_class_code) GROUP BY 1)
        SELECT coalesce(p.role_family, x.role_family) AS role_family, x.headcount, p.incumbents, p.active_positions,
               p.vacant_positions, round(p.vacant_positions / nullif(p.active_positions, 0), 3) AS vacancy_rate,
               round(x.aei, 4) AS aei_observed_exposure_hc_weighted, round(x.aei_cov, 3) AS aei_headcount_coverage,
               round(x.watch, 4) AS job_evolution_watch_score_hc_weighted, round(x.watch_cov, 3) AS watch_headcount_coverage,
               round(x.risk, 1) AS class_revision_risk_index_hc_weighted, round(x.stale_share, 3) AS stale_spec_headcount_share,
               round(x.spec_age, 1) AS spec_age_years_hc_weighted, round(x.growth, 2) AS bls_projected_growth_pct_hc_weighted,
               'anthropic_economic_index|job_evolution|class_evolution|bls_projections' AS source_ids,
               'labor_market_impacts|O*NET 13.0-31.0 panel|SUCSS notices 2003-2026|Employment Projections 2025-35' AS vintages,
               'unreviewed' AS review_status,
               'AI exposure is observed usage evidence, not a displacement forecast; watch score is a rank, not a probability' AS note,
               {L} AS as_of_date
        FROM p FULL OUTER JOIN x ON x.role_family = p.role_family""")
    con.execute(f"""CREATE OR REPLACE TABLE bench_campus_peers AS
        WITH hc AS (SELECT campus_org_code, sum(headcount) AS headcount, sum(fte) AS fte FROM fact_headcount_asof
                    WHERE as_of_date = {L} AND known_as_of = {L} GROUP BY 1),
        hires AS (SELECT campus_org_code, sum(external_hires + rehires) AS hires, sum(avg_headcount) AS avg_hc
                  FROM fact_flows_year WHERE year = {last_complete} GROUP BY 1),
        py AS (SELECT max(year) AS y FROM ext_ipeds_peers WHERE staff_total IS NOT NULL),
        peers AS (SELECT * FROM ext_ipeds_peers WHERE year = (SELECT y FROM py)),
        pm AS (SELECT median(staff_per_100_fte12) AS peer_staff_per_100, median(management_share_pct) AS peer_mgmt,
                      median(new_hires_per_100_fulltime) AS peer_hires, count(*) AS n_peers
               FROM peers WHERE panel_role = 'big_ten_peer'),
        uofi AS (SELECT sum(staff_total) AS sys_staff FROM peers WHERE unitid IN (SELECT unitid FROM campus_assignment))
        SELECT ca.campus_org_code, ca.unitid AS campus_unitid, ca.campus_label, 'synthetic_assignment' AS campus_review_status,
               hc.headcount AS internal_headcount, round(hc.fte, 1) AS internal_fte,
               round(hc.headcount / nullif(sum(hc.headcount) OVER (), 0), 3) AS internal_share_of_system,
               round(100.0 * hires.hires / nullif(hires.avg_hc, 0), 2) AS internal_hires_per_100_{last_complete},
               p.year AS ipeds_year, p.short_name AS ipeds_short_name, p.staff_total AS ipeds_staff_total,
               round(p.staff_total / nullif(uofi.sys_staff, 0), 3) AS ipeds_share_of_system,
               p.staff_per_100_fte12 AS ipeds_staff_per_100_fte12, pm.peer_staff_per_100 AS peer_median_staff_per_100_fte12,
               p.management_share_pct AS ipeds_management_share_pct, pm.peer_mgmt AS peer_median_management_share_pct,
               p.new_hires_per_100_fulltime AS ipeds_new_hires_per_100_ft, pm.peer_hires AS peer_median_new_hires_per_100_ft,
               pm.n_peers, p.source_id AS ipeds_source_id, p.vintage AS ipeds_vintage, p.review_status AS ipeds_review_status,
               q.avg_employment AS qcew_county_avg_employment, q.year AS qcew_year, q.source_id AS qcew_source_id,
               q.vintage AS qcew_vintage, q.review_status AS qcew_review_status,
               'internal counts are synthetic; IPEDS counts are real public totals; compare shares and rates, never levels' AS note
        FROM campus_assignment ca
        LEFT JOIN hc ON hc.campus_org_code = ca.campus_org_code
        LEFT JOIN hires ON hires.campus_org_code = ca.campus_org_code
        LEFT JOIN peers p ON p.unitid = ca.unitid
        CROSS JOIN pm CROSS JOIN uofi
        LEFT JOIN ext_ipeds_institution i ON i.unitid = ca.unitid
        LEFT JOIN (SELECT * FROM ext_qcew_county_year WHERE series = 'all_industries_all_ownerships' AND avg_employment IS NOT NULL
                   QUALIFY row_number() OVER (PARTITION BY area_fips ORDER BY year DESC) = 1) q ON q.area_fips = i.county_fips""")
    return {"benchmark_window": [w0, w1], "latest_snapshot": str(latest), "last_complete_year": last_complete}


def build_funding_mix(con, res: M.Resolution) -> bool:
    """Share of salary expense by funding source, role family and campus (payroll sets with a funding source).

    Each payroll line is linked to the single job version in force at its pay-period end (as known today), so
    payroll is never multiplied by job history rows. Expense amounts net voids and adjustments by summation.
    Returns False (no table) when the mapping has no payroll funding source."""
    if not (res.available("payroll_line") and res.has_field("payroll_line", "funding_source")):
        return False
    K = LATEST_KNOWLEDGE
    con.execute(f"""CREATE OR REPLACE TABLE bench_funding_mix_role_family_campus AS
        WITH p AS (SELECT * FROM c_payroll_line WHERE pay_amount IS NOT NULL),
        j AS (SELECT p.transaction_id, a.job_class_code,
                     row_number() OVER (PARTITION BY p.transaction_id ORDER BY a.valid_from DESC, a.known_from DESC) AS rn
              FROM p JOIN c_appointment a ON a.person_id = p.person_id AND a.position_id = p.position_id
               AND a.job_suffix = p.job_suffix AND a.valid_from <= p.pay_period_end_date AND a.valid_to >= p.pay_period_end_date
               AND a.known_from <= DATE '{K}' AND a.known_to > DATE '{K}'),
        x AS (SELECT coalesce(c.role_family, 'Unassigned') AS role_family, o.campus_org_code,
                     coalesce(p.funding_source, 'Unknown') AS funding_source, p.pay_amount
              FROM p LEFT JOIN j ON j.transaction_id = p.transaction_id AND j.rn = 1
              LEFT JOIN dim_job_class_internal c ON c.job_class_code = j.job_class_code
              LEFT JOIN dim_org_external o ON o.org_code = p.org_code)
        SELECT role_family, campus_org_code, funding_source, round(sum(pay_amount), 2) AS salary_expense,
               round(sum(pay_amount) / nullif(sum(sum(pay_amount)) OVER (PARTITION BY role_family, campus_org_code), 0), 4) AS share_of_salary,
               count(*) AS payroll_lines, any_value(period_from) AS period_from, any_value(period_to) AS period_to,
               'internal payroll (synthetic); funding source as recorded on the payroll line' AS note
        FROM x CROSS JOIN (SELECT min(pay_period_end_date) AS period_from, max(pay_period_end_date) AS period_to FROM p) r
        GROUP BY role_family, campus_org_code, funding_source""")
    return True


def materialize_canonical(con, res: M.Resolution) -> None:
    for c, rep in res.concepts.items():
        if rep.get("status") == "resolved":
            con.execute(f"CREATE OR REPLACE TABLE canon_{c} AS SELECT * FROM c_{c}")


def table_hash(con, table: str, order: str) -> str:
    h = hashlib.sha256()
    for row in con.execute(f"SELECT * FROM {table} ORDER BY {order}").fetchall():
        h.update(repr(tuple(row)).encode())
    return h.hexdigest()


# ----------------------------------------------------------------------------- driver
def build(set_name: str = "longitudinal", out_root: Path | None = None, mapping_file: str | Path | None = None,
          as_of: list[str] | None = None, known: str = "as_of", flow_years: tuple[int, int] | None = None,
          write_parquet: bool = True, bridges_file: str | Path | None = None,
          snapshot_pairs: list[tuple[str, str]] | None = None) -> dict:
    out_root = Path(out_root or OUT_ROOT)
    out_root.mkdir(parents=True, exist_ok=True)
    db_path = out_root / f"integrated_{set_name}.duckdb"
    for p in (db_path, Path(str(db_path) + ".wal")):
        if p.exists():
            p.unlink()
    m = M.load_mapping(mapping_file)
    bridges = X.load_bridges(bridges_file)
    con = duckdb.connect(str(db_path))
    con.execute("SET threads TO 4")
    res = M.resolve(con, m, set_name, strict=True)
    ext_notes = X.load_external(con, bridges)
    build_org(con, res, bridges)
    build_class_internal(con, res)
    build_class_bridges(con, m, bridges)
    build_class_external(con, bridges)
    pairs = [tuple(p) for p in snapshot_pairs] if snapshot_pairs else snapshot_dates(con, as_of, known)
    build_snapshots(con, m, pairs, bridges, res)
    build_headcount(con)
    flow_info = build_flows(con, m, flow_years)
    bench_info = build_benchmarks(con, flow_info)
    export = dict(EXPORT)
    if build_funding_mix(con, res):
        export["bench_funding_mix_role_family_campus"] = "role_family, campus_org_code, funding_source"
    materialize_canonical(con, res)
    con.execute("CREATE OR REPLACE TABLE meta_bridges AS SELECT * FROM (VALUES " + ", ".join(
        f"({lit(b['id'])}, {lit(b['from'])}, {lit(b['to'])}, {lit(b['method'] if isinstance(b['method'], str) else str(b['method']))}, "
        f"{lit(b['source']['source_id'])}, {lit(b['source'].get('vintage'))}, {lit(b['review_status'])})"
        for b in bridges["bridges"]) + ") t(bridge_id, from_concept, to_target, method, source_id, vintage, review_status)")
    manifest = {
        "set": set_name, "data_source": M.data_source(), "mapping_file": Path(m["_path"]).name,
        "mapping_validation": res.to_dict(), "schema_assumptions_check": M.check_schema_assumptions(m, set_name)
        if M.data_source() == "sample" else None,
        "snapshots": [list(p) for p in pairs], "flows": flow_info, "benchmarks": bench_info,
        "external": ext_notes, "tables": {},
    }
    pq_dir = out_root / set_name
    if write_parquet:
        if pq_dir.exists():
            shutil.rmtree(pq_dir)
        pq_dir.mkdir(parents=True)
    for t, order in export.items():
        n = con.execute(f"SELECT count(*) FROM {t}").fetchall()[0][0]
        manifest["tables"][t] = {"rows": n, "content_sha256": table_hash(con, t, order)}
        if write_parquet:
            con.execute(f"COPY (SELECT * FROM {t} ORDER BY {order}) TO {X.q(pq_dir / (t + '.parquet'))} (FORMAT parquet)")
    con.execute("DETACH src") if res.storage == "duckdb" else None
    con.close()
    manifest["database"] = str(db_path.relative_to(M.PE_ROOT)) if db_path.is_relative_to(M.PE_ROOT) else str(db_path)
    if write_parquet:
        (pq_dir / "manifest.json").write_text(json.dumps(manifest, indent=1, default=str, sort_keys=True), encoding="utf-8")
    return manifest


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--set", default="longitudinal", help="longitudinal | CLEAN | DEFECTS | all")
    ap.add_argument("--out", default=None, help="output root (default data/lake/integrated)")
    ap.add_argument("--mapping", default=None, help="mapping file (default: HR_DATA_SOURCE rules)")
    ap.add_argument("--as-of", nargs="*", default=None, help="snapshot dates YYYY-MM-DD (default: June 30 yearly, last 11 years)")
    ap.add_argument("--known", choices=["as_of", "latest"], default="as_of",
                    help="recorded-as-of policy: as_of = what was recorded by each date; latest = current knowledge")
    a = ap.parse_args(argv)
    sets = ["longitudinal", "CLEAN", "DEFECTS"] if a.set == "all" else [a.set]
    for s in sets:
        man = build(s, out_root=a.out, mapping_file=a.mapping, as_of=a.as_of, known=a.known)
        print(f"[{s}] " + ", ".join(f"{t}={v['rows']}" for t, v in man["tables"].items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
