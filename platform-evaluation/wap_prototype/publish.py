"""Run the Phase 1 pipeline end to end and publish the outputs.

    cd platform-evaluation
    python -m wap_prototype.publish                                   # v3 longitudinal, quarterly snapshots
    python -m wap_prototype.publish --source v3_clean
    python -m wap_prototype.publish --date-column JOB_DETL_HIST_EFF_DT  # the alternative reading of the dates
    HR_EDW_DATA=<extract.duckdb> python -m wap_prototype.publish --source edw

Outputs (wap_prototype/outputs/, Parquet + CSV, with data_dictionary.md and manifest.json):
  outputs/                  aggregates only, k >= config.min_cell_size with complementary suppression:
      unit_quarter_aggregates, unit_year_aggregates, transition_counts, feature_summary,
      dq_issue_register (+ .md), reconciliation (.json, .md), run_config.json
  outputs/restricted/       person-level, gitignored, never leaves the machine:
      transition_events, person_period_features, person_demographics_restricted
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import shutil
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from wap_prototype import dq_audit as DQ  # noqa: E402
from wap_prototype import extract as E  # noqa: E402
from wap_prototype import features as F  # noqa: E402
from wap_prototype import reconcile as R  # noqa: E402
from wap_prototype import transitions as T  # noqa: E402
from wap_prototype.config import Config  # noqa: E402

PUBLIC_TABLES = {"unit_quarter_aggregates": "quarter_end, campus_org_code, college_org_code, dept_org_code, role_family",
                 "unit_year_aggregates": "year, campus_org_code, role_family",
                 "transition_counts": "year, campus_org_code, role_family, event_type",
                 "feature_summary": "snap_date, campus_org_code, role_family",
                 "dq_issue_register": "check_id"}
RESTRICTED_TABLES = {"transition_events": "known_as_of, person_id, event_date, event_type, position_id, job_suffix",
                     "person_period_features": "snap_date, person_id",
                     "person_demographics_restricted": "person_id"}


# ----------------------------------------------------------------------------- aggregates
def build_aggregates(src: E.Source) -> None:
    con, k = src.con, src.cfg.min_cell_size
    K = f"DATE '{src.knowledge_date}'"
    # quarter ends covering the event history inside the feature window
    con.execute("""CREATE OR REPLACE TEMP TABLE ag_quarters AS
        SELECT DISTINCT snap_date AS quarter_end, (snap_date - INTERVAL 3 MONTH)::DATE AS prev_end FROM person_period_features""")
    con.execute(f"""CREATE OR REPLACE TEMP TABLE ag_raw AS
        WITH hc AS (
            SELECT snap_date AS quarter_end, campus_org_code, college_org_code, dept_org_code, role_family,
                   count(*) AS headcount, round(sum(fte_total), 2) AS fte
            FROM person_period_features GROUP BY ALL),
        ev AS (
            SELECT q.quarter_end,
                   CASE WHEN e.event_type IN ('hire', 'rehire') THEN e.to_campus_org_code ELSE e.from_campus_org_code END AS campus_org_code,
                   CASE WHEN e.event_type IN ('hire', 'rehire') THEN e.to_college_org_code ELSE e.from_college_org_code END AS college_org_code,
                   CASE WHEN e.event_type IN ('hire', 'rehire') THEN e.to_dept_org_code ELSE e.from_dept_org_code END AS dept_org_code,
                   CASE WHEN e.event_type IN ('hire', 'rehire') THEN e.to_role_family ELSE e.from_role_family END AS role_family,
                   count(*) FILTER (WHERE e.event_type IN ('hire', 'rehire')) AS hires,
                   count(*) FILTER (WHERE e.event_type LIKE 'separation_%' OR e.event_type = 'retirement') AS separations,
                   count(*) FILTER (WHERE e.event_type = 'retirement') AS retirements,
                   count(*) FILTER (WHERE e.event_type = 'promotion') AS promotions,
                   count(*) FILTER (WHERE e.event_type IN ('transfer_lateral', 'transfer_down')) AS transfers
            FROM ag_quarters q JOIN transition_events e ON e.event_date > q.prev_end AND e.event_date <= q.quarter_end AND NOT e.is_future
            GROUP BY ALL),
        keys AS (SELECT quarter_end, campus_org_code, college_org_code, dept_org_code, role_family FROM hc
                 UNION SELECT quarter_end, campus_org_code, college_org_code, dept_org_code, role_family FROM ev)
        SELECT k.*, coalesce(hc.headcount, 0) AS headcount, coalesce(hc.fte, 0) AS fte, coalesce(ev.hires, 0) AS hires,
               coalesce(ev.separations, 0) AS separations, coalesce(ev.retirements, 0) AS retirements,
               coalesce(ev.promotions, 0) AS promotions, coalesce(ev.transfers, 0) AS transfers
        FROM keys k LEFT JOIN hc USING (quarter_end, campus_org_code, college_org_code, dept_org_code, role_family)
        LEFT JOIN ev USING (quarter_end, campus_org_code, college_org_code, dept_org_code, role_family)""")
    con.execute(f"CREATE OR REPLACE TEMP TABLE unit_quarter_aggregates AS {suppress_sql('ag_raw', ['quarter_end', 'campus_org_code', 'college_org_code', 'dept_org_code', 'role_family'], ['quarter_end', 'campus_org_code', 'college_org_code', 'role_family'], ['hires', 'separations', 'retirements', 'promotions', 'transfers'], k)} ORDER BY 1, 2, 3, 4, 5")
    # annual campus x role family (headcount at the year's last snapshot)
    con.execute(f"""CREATE OR REPLACE TEMP TABLE ag_year_raw AS
        WITH last_snap AS (SELECT year(snap_date) AS year, max(snap_date) AS snap_date FROM person_period_features GROUP BY 1),
        hc AS (SELECT year(f.snap_date) AS year, f.campus_org_code, f.role_family, count(*) AS headcount, round(sum(f.fte_total), 2) AS fte
               FROM person_period_features f JOIN last_snap l ON l.snap_date = f.snap_date GROUP BY ALL),
        ev AS (SELECT year(e.event_date) AS year,
                      CASE WHEN e.event_type IN ('hire', 'rehire') THEN e.to_campus_org_code ELSE e.from_campus_org_code END AS campus_org_code,
                      CASE WHEN e.event_type IN ('hire', 'rehire') THEN e.to_role_family ELSE e.from_role_family END AS role_family,
                      count(*) FILTER (WHERE e.event_type IN ('hire', 'rehire')) AS hires,
                      count(*) FILTER (WHERE e.event_type LIKE 'separation_%' OR e.event_type = 'retirement') AS separations,
                      count(*) FILTER (WHERE e.event_type = 'retirement') AS retirements,
                      count(*) FILTER (WHERE e.event_type = 'promotion') AS promotions,
                      count(*) FILTER (WHERE e.event_type IN ('transfer_lateral', 'transfer_down')) AS transfers
               FROM transition_events e WHERE NOT e.is_future AND year(e.event_date) IN (SELECT year FROM last_snap) GROUP BY ALL),
        keys AS (SELECT year, campus_org_code, role_family FROM hc UNION SELECT year, campus_org_code, role_family FROM ev)
        SELECT k.*, coalesce(hc.headcount, 0) AS headcount, coalesce(hc.fte, 0) AS fte, coalesce(ev.hires, 0) AS hires,
               coalesce(ev.separations, 0) AS separations, coalesce(ev.retirements, 0) AS retirements,
               coalesce(ev.promotions, 0) AS promotions, coalesce(ev.transfers, 0) AS transfers
        FROM keys k LEFT JOIN hc USING (year, campus_org_code, role_family) LEFT JOIN ev USING (year, campus_org_code, role_family)""")
    con.execute(f"CREATE OR REPLACE TEMP TABLE unit_year_aggregates AS {suppress_sql('ag_year_raw', ['year', 'campus_org_code', 'role_family'], ['year', 'campus_org_code'], ['hires', 'separations', 'retirements', 'promotions', 'transfers'], k)} ORDER BY 1, 2, 3")
    # transition counts by year x campus x role family x event type (each count must reach k or be suppressed)
    con.execute(f"""CREATE OR REPLACE TEMP TABLE transition_counts AS
        SELECT year, campus_org_code, role_family, event_type,
               CASE WHEN n >= {k} OR n = 0 THEN n END AS n_events, (n > 0 AND n < {k}) AS suppressed, {k} AS min_cell_size
        FROM (SELECT year(event_date) AS year, coalesce(to_campus_org_code, from_campus_org_code) AS campus_org_code,
                     coalesce(to_role_family, from_role_family) AS role_family, event_type, count(*) AS n
              FROM transition_events WHERE NOT is_future GROUP BY ALL)
        ORDER BY 1, 2, 3, 4""")
    con.execute(f"CREATE OR REPLACE TEMP TABLE feature_summary AS {F.feature_summary_sql(k)} ORDER BY 1, 2, 3")
    con.execute("DROP TABLE IF EXISTS ag_raw"); con.execute("DROP TABLE IF EXISTS ag_year_raw"); con.execute("DROP TABLE IF EXISTS ag_quarters")


def suppress_sql(table: str, keys: list[str], parent_keys: list[str], counts: list[str], k: int) -> str:
    """Primary suppression: a cell whose headcount is below k loses every measure. Any count between 1 and k-1
    is also suppressed. Complementary suppression: when exactly one cell of a parent group is suppressed by
    headcount, the smallest other cell of the group is suppressed too so the parent total cannot reveal it."""
    pk = ", ".join(parent_keys)
    measures = ["headcount", "fte"] + counts
    sup = ", ".join(f"CASE WHEN suppressed THEN NULL WHEN {c} > 0 AND {c} < {k} THEN NULL ELSE {c} END AS {c}" for c in counts)
    small = " OR ".join(f"({c} > 0 AND {c} < {k})" for c in counts)
    return f"""
        WITH p AS (SELECT *, headcount < {k} AS primary_sup FROM {table}),
        g AS (SELECT *, sum(CASE WHEN primary_sup THEN 1 ELSE 0 END) OVER (PARTITION BY {pk}) AS n_sup,
                     row_number() OVER (PARTITION BY {pk} ORDER BY primary_sup, headcount, {', '.join(keys)}) AS rn_small
              FROM p),
        s AS (SELECT *, primary_sup OR (n_sup = 1 AND NOT primary_sup AND rn_small = 1) AS suppressed FROM g)
        SELECT {', '.join(keys)},
               CASE WHEN suppressed THEN NULL ELSE headcount END AS headcount,
               CASE WHEN suppressed THEN NULL ELSE fte END AS fte,
               {sup},
               suppressed OR coalesce(NOT suppressed AND ({small}), FALSE) AS any_suppressed,
               CASE WHEN primary_sup THEN 'headcount_below_k' WHEN suppressed THEN 'complementary' WHEN {small} THEN 'small_count' END AS suppression_reason,
               {k} AS min_cell_size
        FROM s"""


# ----------------------------------------------------------------------------- data dictionary
DESC = {
    "event_id": "md5 of the event key (snapshot, person, position, suffix, row dates, source table)",
    "known_as_of": "knowledge date used to derive the event (the extract date for the published table)",
    "event_date": "effective date of the event: the column chosen by config.job_change_date_column",
    "event_type": "see transitions.py docstring; promotion/transfer/reclassification are candidate labels",
    "event_subtype": "move: cross_org/cross_campus/same_org; promotion/reclassification: level_<direction>; separation: termination code; hire: first_observed_appointment",
    "move_kind": "job_change (new appointment), in_place (same appointment), job_start, job_stop, leave_spell",
    "level_direction": "up / same / down / different_ladder / unknown, comparing ladder level then role level",
    "is_future": "event dated after the knowledge date (Future rows)",
    "from_class_key": "canonical class key before the event (SUCSS 4-digit code via PAPE_CIV_SVC_ID, else P-Class)",
    "to_class_key": "canonical class key after the event",
    "from_ladder_level": "job-progression level before (x_ladder rule: ROLE_LEVEL, else rank of range minimum)",
    "state_valid_to": "last effective date of the row that produced the event (9999-12-31 if open)",
    "row_eff_date": "JOB_DETL_EFF_DT of the source row (mapping appointment.eff_date)",
    "row_recorded_start": "JOB_DETL_HIST_EFF_DT of the source row (mapping appointment.recorded_start)",
    "row_post_date": "post date of the source row", "row_known_from": "start of the recorded interval of the version used",
    "change_reason_code": "source JOB_DETL_CHG_REASON_CD (not used to derive event_type; kept for comparison)",
    "change_reason_label": "mapping code_values.job_change_reason_labels for the code",
    "label_status": "candidate_rule | derived_from_row_diff | source_termination_code | source_status_code | candidate_rule_left_censored",
    "date_column_used": "value of config.job_change_date_column for this run",
    "snap_date": "snapshot date t; features use only rows effective <= t and known at t",
    "knowledge_date": "extract date; targets are evaluated with this knowledge",
    "age_band": "age band at t from the restricted birth date (only derived value that leaves T_PERS_HIST); boundary at 40 for the ADEA cut",
    "tenure_first_hire_years": "years from FIRST_HIRE_DT (employment row known at t), else first observed appointment",
    "hire_date_source": "employment_first_hire_date | first_observed_appointment (the employment row was not yet known at t)",
    "time_in_class_years": "years since the start of the continuous spell in the primary job's class key",
    "time_in_position_years": "years since the start of the continuous spell in the primary position",
    "fte_total": "sum of FTE over active appointments at t", "fte_primary": "FTE of the primary appointment (highest FTE, then lowest position)",
    "annual_salary_fte_adjusted": "annual_salary / fte_primary", "pay_range_position": "(FTE-adjusted salary - POSN_MIN_SAL) / (POSN_MAX_SAL - POSN_MIN_SAL)",
    "compa_ratio": "FTE-adjusted salary / POSN_MIDPT_SAL", "pay_ceiling_gap": "1 - FTE-adjusted salary / POSN_MAX_SAL",
    "moves_per_year": "(promotions + transfers known at t) / tenure_first_hire_years",
    "time_since_last_move_years": "years since the last promotion or transfer known at t, else tenure since current hire",
    "supervisor_span": "distinct people whose active appointment at t names this person as supervisor (NULL: no supervisor data)",
    "dept_churn_12m": "(separations + outbound moves from the department in the trailing 12 months, as known at t) / department headcount at t",
    "surs_eligibility_band": "ASSUMPTION assumption_v1: tier by first hire before 2011-01-01, service = university service; not SURS data",
    "onet_job_zone": "O*NET job zone via class -> SUCSS -> O*NET (unreviewed bridge)",
    "proj_growth_pct_2025_35": "BLS projected employment growth 2025-35 for the SOC code",
    "proj_occ_separations_rate_pct": "BLS projected occupational separations rate", "pay_ratio_oews_local": "FTE-adjusted salary / OEWS local-MSA median (synthetic campus assignment)",
    "pay_ratio_oews_il": "FTE-adjusted salary / OEWS Illinois median", "aei_observed_exposure": "AEI observed AI-usage exposure (evidence about tasks, not a forecast)",
    "je_watch_score": "job_evolution watch score (unreviewed)", "external_null_reason": "why external facts are NULL for this class",
    "promoted_within_12m": "TARGET: a promotion event in (t, t+12m] with latest knowledge; NULL when censored",
    "separated_within_6m": "TARGET: a separation or retirement in (t, t+6m]", "retired_within_12m": "TARGET: a retirement in (t, t+12m]",
    "headcount": "distinct people with an active appointment at the period end (NULL when suppressed)",
    "suppressed": "cell suppressed (headcount below k, complementary, or small count)",
    "suppression_reason": "headcount_below_k | complementary | small_count", "min_cell_size": "k used for suppression",
    "n_events": "count of events; NULL when 0 < n < k", "role": "mapping role of the demographic fields: restricted_fairness_only",
    "person_id": "EDW_PERS_ID (synthetic 99xxxxxxx ids in this pack)", "position_id": "POSN_NBR", "job_suffix": "JOB_SUFFIX",
    "quarter_end": "last day of the calendar quarter (snapshot date)", "year": "calendar year",
    "campus_org_code": "campus-level org (child of the org root; synthetic campus assignment)", "college_org_code": "level-3 (college) ancestor org",
    "dept_org_code": "level-5 (department) ancestor org", "admin_level_2": "level-2 (admin) ancestor org", "org_code": "ORG_CD of the primary appointment",
    "role_family": "role family of the class key (role_family_source says which rule assigned it)", "role_family_source": "sample_role_family_reference | integration_dim_job_class_internal | employee_group_fallback | unassigned",
    "fte": "sum of FTE of the people counted (NULL when suppressed)", "hires": "hire + rehire events in the period (NULL when suppressed or 0 < n < k)",
    "separations": "separation_* + retirement events in the period", "retirements": "retirement events in the period",
    "promotions": "candidate promotion events in the period", "transfers": "transfer_lateral + transfer_down events in the period",
    "any_suppressed": "TRUE when any measure in the row is suppressed", "n_persons": "people in the cell (always shown; measures NULL below k)",
    "class_key": "canonical class key (SUCSS code or local P-Class)", "p_class_code": "5-character position class (P-Class)", "e_class": "employee class (E-Class)",
    "employee_group": "first character of the E-Class", "ladder_code": "POSN_JOB_PRGS_CD of the primary position", "ladder_level": "level on that ladder (see x_ladder rule)",
    "ladder_level_source": "role_family_role_level | rank_of_range_min_within_ladder | no_ladder", "empl_status_code": "EMPEE_STATUS_CD of the employment row known at t (NULL when that row was posted after t)",
    "posn_status_code": "POSN_STATUS_CD of the primary position version", "posn_desc_age_years": "years since POSN_DESC_UPDATE_DT when that date is on or before t",
    "surs_tier_assumed": "tier1_assumed when the hire-date proxy is before 2011-01-01 (ASSUMPTION)", "surs_rule_version": "version of the SURS assumption",
    "n_active_jobs": "active appointments at t", "budget_fte": "POSN_APPT_PCT of the primary position (fraction)", "annual_salary": "JOB_DETL_ANNL_SAL of the primary appointment",
    "posn_range_min": "POSN_MIN_SAL", "posn_range_mid": "POSN_MIDPT_SAL", "posn_range_max": "POSN_MAX_SAL",
    "n_promotions": "promotions known at t", "n_transfers": "transfers known at t", "n_reclassifications": "reclassifications known at t", "n_rehires": "rehires known at t",
    "n_leaves": "leave spells known at t", "n_pay_changes_3y": "pay_change events in the trailing 3 years", "n_positions_held": "distinct positions entered through hire/rehire/move/additional-job events",
    "time_since_last_promotion_years": "years since the last promotion known at t (NULL if none)", "supervisor_data_available": "FALSE when the source carries no supervisor ids (longitudinal)",
    "has_supervisor": "the primary appointment names a supervisor", "dept_headcount": "people whose primary appointment is in the department at t",
    "dept_separations_12m": "separations from the department in the trailing 12 months, as known at t", "dept_hires_12m": "hires into the department in the trailing 12 months",
    "dept_outbound_moves_12m": "moves out of the department in the trailing 12 months", "civil_service_ind": "JOB_DETL_CIV_SVC_IND",
    "role_level": "REF_ROLE_FAMILY.ROLE_LEVEL of the class key", "proj_labor_force_exit_rate_pct": "BLS projected labor-force exit rate",
    "oews_local_median": "OEWS median for the campus's MSA", "oews_il_median": "OEWS Illinois median", "onet_code": "O*NET-SOC code (unreviewed bridge)", "soc_2018_code": "SOC 2018 code",
    "external_chain_review_status": "weakest review status on the class -> SUCSS -> O*NET -> SOC chain", "primary_row_start": "event_date of the primary appointment row",
    "primary_row_known_from": "known_from of that row (always <= snap_date)", "rule_version": "rule version of the module that built the table",
    "tenure_bucket": "0-3 | 3-7 | 7-15 | 15+ years", "time_in_class_bucket": "same buckets on time_in_class_years", "tenure_current_hire_years": "years from CUR_HIRE_DT (else first observed appointment)",
    "check_id": "audit check id", "severity": "error | warn | info", "concept": "source table (mapping)", "n_rows": "rows flagged", "n_entities": "distinct entities flagged",
    "example_ids": "up to 5 synthetic example ids", "status": "pass | warn | fail", "source_table": "physical source table (mapping)",
    "sex_code": "RESTRICTED fairness-only", "gender_code": "RESTRICTED fairness-only", "race_eth_rpt_code": "RESTRICTED fairness-only (U, 9, H, M, 1-5)",
    "ipeds_race_eth": "RESTRICTED fairness-only", "citizenship_group": "RESTRICTED fairness-only", "veteran_class": "RESTRICTED fairness-only",
    "from_position_id": "position before the event (the from-job for a move)", "from_supervisor_person_id": "supervisor before", "to_supervisor_person_id": "supervisor after",
    "cross_org": "org changed", "cross_campus": "campus changed", "cross_college": "college changed", "cross_dept": "department changed",
    "term_reason_code": "TERMN_REASON_CD for separation / retirement events", "leave_reason_code": "EMPEE_LEAVE_REASON_CD for leave events",
    "current_info_ind": "CUR_INFO_IND of the source row", "change_reason_desc": "JOB_DETL_CHG_REASON_DESC", "from_fte": "FTE before", "to_fte": "FTE after",
    "from_salary": "annual salary before", "to_salary": "annual salary after", "from_e_class": "E-Class before", "to_e_class": "E-Class after",
    "from_p_class": "P-Class before", "to_p_class": "P-Class after", "from_ladder": "ladder before", "to_ladder": "ladder after", "to_ladder_level": "ladder level after",
    "from_role_family": "role family before", "to_role_family": "role family after", "from_role_level": "role level before", "to_role_level": "role level after",
    "from_org_code": "org before", "to_org_code": "org after", "from_campus_org_code": "campus before", "to_campus_org_code": "campus after",
    "from_college_org_code": "college before", "to_college_org_code": "college after", "from_dept_org_code": "department before", "to_dept_org_code": "department after",
}


def data_dictionary(con, tables: dict, cfg: Config, where: dict) -> str:
    lines = ["# Data dictionary (wap_prototype Phase 1)", "",
             f"Run: source {cfg.data_source}, date column {cfg.job_change_date_column}, snapshots {cfg.snapshot_frequency}, k = {cfg.min_cell_size}. "
             "Synthetic data (v3 Cookbook pack). Restricted tables stay in outputs/restricted/ and never leave the machine.", ""]
    for t in tables:
        lines += [f"## {t}  ({where[t]})", "", "| Column | Type | Description |", "|---|---|---|"]
        for name, typ, *_ in con.execute(f"DESCRIBE {t}").fetchall():
            d = DESC.get(name) or DESC.get(name.replace("to_", "from_", 1)) or ""
            if not d and name.endswith("_censored"):
                d = "TRUE when t + horizon is after the knowledge date (target NULL)"
            if not d and name.startswith(("from_", "to_")):
                d = "state before / after the event"
            lines.append(f"| {name} | {typ} | {d} |")
        lines.append("")
    return "\n".join(lines)


# ----------------------------------------------------------------------------- driver
def write_table(con, table: str, order: str, folder: Path) -> dict:
    folder.mkdir(parents=True, exist_ok=True)
    pq, csv = folder / f"{table}.parquet", folder / f"{table}.csv"
    con.execute(f"COPY (SELECT * FROM {table} ORDER BY {order}) TO {E.lit(pq.as_posix())} (FORMAT parquet)")
    con.execute(f"COPY (SELECT * FROM {table} ORDER BY {order}) TO {E.lit(csv.as_posix())} (FORMAT csv, HEADER)")
    n = con.execute(f"SELECT count(*) FROM {table}").fetchall()[0][0]
    return {"rows": int(n), "csv_sha256": hashlib.sha256(csv.read_bytes()).hexdigest(), "columns": len(con.execute(f"DESCRIBE {table}").fetchall())}


def run(cfg: Config, write: bool = True) -> dict:
    src = E.open_source(cfg)
    con = src.con
    E.register_restricted(src)
    T.build_latest(src, "transition_events")
    snaps = F.snapshot_dates(cfg, src.knowledge_date)
    feat_info = F.build_features(src, snaps)
    demo_info = F.build_restricted_demographics(src)
    dq_rows = DQ.run_audit(src)
    build_aggregates(src)
    rec = R.run(src)
    manifest = {"run_at_note": "no timestamps: outputs are deterministic for a given input", "config": cfg.to_dict(),
                "extract": E.summary(src), "features": feat_info, "restricted_fairness_fields": demo_info["fairness_fields"],
                "event_counts": T.event_counts(con), "reconciliation_summary": rec["summary"],
                "dq_summary": {"fail": sum(r["status"] == "fail" for r in dq_rows), "warn": sum(r["status"] == "warn" for r in dq_rows),
                               "pass": sum(r["status"] == "pass" for r in dq_rows)},
                "tables": {}}
    if write:
        out, res = cfg.output_dir, cfg.output_dir / "restricted"
        for d in (out, res):
            d.mkdir(parents=True, exist_ok=True)
        for t, order in PUBLIC_TABLES.items():
            manifest["tables"][t] = dict(write_table(con, t, order, out), location="outputs/")
        for t, order in RESTRICTED_TABLES.items():
            manifest["tables"][t] = dict(write_table(con, t, order, res), location="outputs/restricted/ (never leaves the machine)")
        (out / "dq_issue_register.md").write_text(DQ.register_markdown(dq_rows, src), encoding="utf-8")
        (out / "reconciliation.md").write_text(R.to_markdown(rec), encoding="utf-8")
        (out / "reconciliation.json").write_text(json.dumps(rec, indent=1, default=str), encoding="utf-8")
        (out / "transition_rule_agreement.csv").write_text(
            "event_type,source_change_reason_label,n\n" + "".join(f"{a},{b},{n}\n" for a, b, n in T.agreement_with_change_codes(con)), encoding="utf-8")
        where = {t: "outputs/" for t in PUBLIC_TABLES} | {t: "outputs/restricted/" for t in RESTRICTED_TABLES}
        (out / "data_dictionary.md").write_text(data_dictionary(con, list(PUBLIC_TABLES) + list(RESTRICTED_TABLES), cfg, where), encoding="utf-8")
        (out / "run_config.json").write_text(json.dumps(cfg.to_dict(), indent=1, default=str), encoding="utf-8")
        (out / "manifest.json").write_text(json.dumps(manifest, indent=1, default=str, sort_keys=True), encoding="utf-8")
        gi = res / ".gitignore"
        gi.write_text("*\n!.gitignore\n", encoding="utf-8")
    manifest["_source"] = src
    return manifest


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", default=None, help="v3_longitudinal | v3_clean | edw")
    ap.add_argument("--date-column", default=None, help="JOB_DETL_EFF_DT | JOB_DETL_HIST_EFF_DT")
    ap.add_argument("--frequency", default=None, help="Q | A")
    ap.add_argument("--as-of", default=None, help="extract / knowledge date YYYY-MM-DD")
    ap.add_argument("--out", default=None, help="output folder")
    a = ap.parse_args(argv)
    kw = {}
    if a.source: kw["data_source"] = a.source
    if a.date_column: kw["job_change_date_column"] = a.date_column
    if a.frequency: kw["snapshot_frequency"] = a.frequency
    if a.as_of: kw["as_of_date"] = dt.date.fromisoformat(a.as_of)
    if a.out: kw["output_dir"] = Path(a.out)
    cfg = Config.from_env(**kw)
    man = run(cfg)
    src = man.pop("_source")
    src.close()
    print(json.dumps({k: v for k, v in man.items() if k in ("features", "event_counts", "reconciliation_summary", "dq_summary")}, indent=1, default=str))
    print("tables: " + ", ".join(f"{t}={v['rows']}" for t, v in man["tables"].items()))
    return 0 if man["reconciliation_summary"]["fail"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
