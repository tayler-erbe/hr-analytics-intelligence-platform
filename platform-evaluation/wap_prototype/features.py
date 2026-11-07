"""Point-in-time person-period feature table (quarterly or annual snapshots), leakage-safe.

For every snapshot date t the features use only appointment, position, employment and separation rows that
were (a) effective on or before t and (b) known on t (known_from <= t < known_to). Events (moves, leaves,
separations) are re-derived per snapshot from the rows known at t (transitions.build_events with
effective_only=True), so a late-keyed or corrected row changes a feature only from its post date onwards.

The targets are forward-looking and use the LATEST knowledge on purpose (they are labels for Phase 2, not
features): promoted within 12/18 months, separated within 6/12 months, retired within 12 months. A target is
NULL with `target_censored = TRUE` when t + horizon lies after the extract date.

Demographics never enter the feature table. `build_restricted_demographics` writes a separate person-level
frame (sex, gender, race/ethnicity reporting code, IPEDS category, citizenship group, veteran class) for the
fairness review only; it joins to the feature table on person_id inside the restricted folder.

Age band is the only thing derived from the restricted birth date, and the SURS eligibility band is an
ASSUMPTION (config.SURS_ASSUMPTION): EDW has no SURS tier or service credit.
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from wap_prototype import extract as E  # noqa: E402
from wap_prototype import transitions as T  # noqa: E402
from wap_prototype.config import AGE_BANDS, TENURE_BUCKETS, Config, bucket_sql  # noqa: E402

FEATURE_RULE_VERSION = "wap_phase1_features_v1"
OEWS_LOCAL = {"msa_champaign_urbana": "oews_msa_champaign_urbana_median", "msa_chicago": "oews_msa_chicago_median",
              "msa_springfield": "oews_msa_springfield_median"}


def snapshot_dates(cfg: Config, knowledge_date: dt.date) -> list[dt.date]:
    out, d = [], cfg.snapshot_start
    while d <= knowledge_date:
        out.append(d)
        if cfg.snapshot_frequency == "Q":
            m = d.month + 3
            y = d.year + (m - 1) // 12
            m = (m - 1) % 12 + 1
            d = (dt.date(y + (m == 12), 1 if m == 12 else m + 1, 1) - dt.timedelta(days=1))
        else:
            d = dt.date(d.year + 1, d.month, d.day if d.month != 2 else 28)
    return out


def _years(a: str, b: str) -> str:
    return f"round(date_diff('day', {b}, {a}) / 365.25, 3)"


def build_features(src: E.Source, snaps: list[dt.date], out_table: str = "person_period_features",
                   latest_events_table: str = "transition_events") -> dict:
    con, cfg = src.con, src.cfg
    K = f"DATE '{src.knowledge_date}'"
    vals = ", ".join(f"(DATE '{d}')" for d in snaps)
    con.execute(f"CREATE OR REPLACE TEMP TABLE fs_snaps AS SELECT * FROM (VALUES {vals}) t(snap_date)")
    # history rows known at t and effective on or before t (the only appointment rows a snapshot may see)
    con.execute("""CREATE OR REPLACE TEMP TABLE fs_hist AS
        SELECT s.snap_date, a.* FROM fs_snaps s JOIN x_appointment a
          ON a.known_from <= s.snap_date AND a.known_to > s.snap_date AND a.valid_from <= s.snap_date""")
    # events as known at t
    T.build_events(src, "fs_snaps", "fs_events", effective_only=True)
    # active appointments at t; primary = highest FTE, then lowest position / suffix (integration headcount rule)
    con.execute("""CREATE OR REPLACE TEMP TABLE fs_active AS
        SELECT *, sum(fte) OVER (PARTITION BY snap_date, person_id) AS person_fte,
               count(*) OVER (PARTITION BY snap_date, person_id) AS n_active_jobs,
               row_number() OVER (PARTITION BY snap_date, person_id ORDER BY fte DESC NULLS LAST, position_id, job_suffix) AS rn
        FROM fs_hist WHERE valid_to >= snap_date AND is_active_status""")
    con.execute("CREATE OR REPLACE TEMP TABLE fs_primary AS SELECT * EXCLUDE (rn) FROM fs_active WHERE rn = 1")
    E.position_pick(con, "fs_primary", "snap_date", "snap_date", "fs_pos", ["snap_date", "person_id"])
    # employment row effective at t and known at t
    con.execute("""CREATE OR REPLACE TEMP TABLE fs_empl AS
        SELECT * EXCLUDE (rn) FROM (
            SELECT p.snap_date, p.person_id, e.status_code AS empl_status_code, e.employee_group_code, e.first_hire_date,
                   e.current_hire_date, e.adj_service_date, e.first_work_date, e.fte AS empl_fte, e.annual_salary AS empl_annual_salary,
                   row_number() OVER (PARTITION BY p.snap_date, p.person_id ORDER BY e.valid_from DESC, e.known_from DESC) AS rn
            FROM fs_primary p JOIN x_employment e ON e.person_id = p.person_id
             AND e.valid_from <= p.snap_date AND e.valid_to >= p.snap_date AND e.known_from <= p.snap_date AND e.known_to > p.snap_date)
        WHERE rn = 1""")
    # spells: continuous run of the primary class / position across the person's rows known at t
    con.execute("""CREATE OR REPLACE TEMP TABLE fs_spell AS
        WITH b AS (
            SELECT p.snap_date, p.person_id, p.job_class_code AS cur_class, p.position_id AS cur_pos,
                   h.event_date, h.job_class_code, h.position_id, h.is_active_status
            FROM fs_primary p JOIN fs_hist h ON h.snap_date = p.snap_date AND h.person_id = p.person_id),
        m AS (
            SELECT snap_date, person_id,
                   max(event_date) FILTER (WHERE job_class_code IS DISTINCT FROM cur_class OR NOT is_active_status) AS last_other_class,
                   max(event_date) FILTER (WHERE position_id IS DISTINCT FROM cur_pos OR NOT is_active_status) AS last_other_pos,
                   min(event_date) AS first_observed_appointment
            FROM b GROUP BY 1, 2)
        SELECT b.snap_date, b.person_id, m.first_observed_appointment,
               min(b.event_date) FILTER (WHERE b.job_class_code = b.cur_class AND b.is_active_status AND b.event_date >= coalesce(m.last_other_class, DATE '0001-01-01')) AS class_spell_start,
               min(b.event_date) FILTER (WHERE b.position_id = b.cur_pos AND b.is_active_status AND b.event_date >= coalesce(m.last_other_pos, DATE '0001-01-01')) AS position_spell_start
        FROM b JOIN m USING (snap_date, person_id) GROUP BY ALL""")
    # move history as known at t
    con.execute("""CREATE OR REPLACE TEMP TABLE fs_moves AS
        SELECT known_as_of AS snap_date, person_id,
               count(*) FILTER (WHERE event_type = 'promotion') AS n_promotions,
               count(*) FILTER (WHERE event_type IN ('transfer_lateral', 'transfer_down')) AS n_transfers,
               count(*) FILTER (WHERE event_type = 'reclassification') AS n_reclassifications,
               count(*) FILTER (WHERE event_type = 'rehire') AS n_rehires,
               count(*) FILTER (WHERE event_type = 'leave') AS n_leaves,
               count(*) FILTER (WHERE event_type = 'pay_change' AND event_date > known_as_of - INTERVAL 3 YEAR) AS n_pay_changes_3y,
               max(event_date) FILTER (WHERE event_type IN ('promotion', 'transfer_lateral', 'transfer_down')) AS last_move_date,
               max(event_date) FILTER (WHERE event_type = 'promotion') AS last_promotion_date,
               count(DISTINCT position_id) FILTER (WHERE event_type IN ('hire', 'rehire', 'promotion', 'transfer_lateral', 'transfer_down', 'additional_job')) AS n_positions_held
        FROM fs_events WHERE NOT is_future GROUP BY 1, 2""")
    # supervisor span at t (people whose active job names this person as supervisor)
    con.execute("""CREATE OR REPLACE TEMP TABLE fs_span AS
        SELECT snap_date, supervisor_person_id AS person_id, count(DISTINCT person_id) AS supervisor_span
        FROM fs_active WHERE supervisor_person_id IS NOT NULL GROUP BY 1, 2""")
    has_sup = con.execute("SELECT count(*) FROM fs_span").fetchall()[0][0] > 0
    # unit (department) churn, trailing 12 months, as known at t
    con.execute("""CREATE OR REPLACE TEMP TABLE fs_unit AS
        WITH hc AS (SELECT snap_date, dept_org_code, count(*) AS dept_headcount FROM fs_primary GROUP BY 1, 2),
        ev AS (SELECT known_as_of AS snap_date,
                      CASE WHEN event_type IN ('hire', 'rehire') THEN to_dept_org_code ELSE from_dept_org_code END AS dept_org_code,
                      count(*) FILTER (WHERE event_type LIKE 'separation_%' OR event_type = 'retirement') AS dept_separations_12m,
                      count(*) FILTER (WHERE event_type IN ('hire', 'rehire')) AS dept_hires_12m,
                      count(*) FILTER (WHERE event_type IN ('promotion', 'transfer_lateral', 'transfer_down') AND cross_dept) AS dept_outbound_moves_12m
               FROM fs_events WHERE NOT is_future AND event_date > known_as_of - INTERVAL 12 MONTH GROUP BY 1, 2)
        SELECT hc.snap_date, hc.dept_org_code, hc.dept_headcount, coalesce(ev.dept_separations_12m, 0) AS dept_separations_12m,
               coalesce(ev.dept_hires_12m, 0) AS dept_hires_12m, coalesce(ev.dept_outbound_moves_12m, 0) AS dept_outbound_moves_12m,
               round((coalesce(ev.dept_separations_12m, 0) + coalesce(ev.dept_outbound_moves_12m, 0)) / hc.dept_headcount, 4) AS dept_churn_12m
        FROM hc LEFT JOIN ev USING (snap_date, dept_org_code)""")
    # targets from the latest knowledge
    hz = cfg.target_horizons_months
    tcols = []
    for name, src_filter in (("promoted", "event_type = 'promotion'"), ("separated", "(event_type LIKE 'separation_%' OR event_type = 'retirement')"),
                             ("retired", "event_type = 'retirement'")):
        for h in hz[name]:
            tcols.append(f"""CASE WHEN p.snap_date + INTERVAL {h} MONTH > {K} THEN NULL
                              ELSE coalesce(bool_or(e.{name}_flag AND e.event_date > p.snap_date AND e.event_date <= p.snap_date + INTERVAL {h} MONTH), FALSE) END AS {name}_within_{h}m""")
            tcols.append(f"(p.snap_date + INTERVAL {h} MONTH > {K}) AS {name}_within_{h}m_censored")
    con.execute(f"""CREATE OR REPLACE TEMP TABLE fs_targets AS
        SELECT p.snap_date, p.person_id, {', '.join(tcols)}
        FROM fs_primary p LEFT JOIN (
            SELECT person_id, event_date, event_type = 'promotion' AS promoted_flag,
                   (event_type LIKE 'separation_%' OR event_type = 'retirement') AS separated_flag, event_type = 'retirement' AS retired_flag
            FROM {latest_events_table} WHERE NOT is_future) e ON e.person_id = p.person_id
        GROUP BY p.snap_date, p.person_id""")
    # external context through the integration bridges
    integ = src.report["integrated_attached"]
    local_case = "CASE o.oews_local_area_key " + " ".join(f"WHEN '{k}' THEN x.{v}" for k, v in OEWS_LOCAL.items()) + " END"
    ext_sel = f"""x.onet_job_zone, x.proj_growth_pct_2025_35, x.proj_occ_separations_rate_pct, x.proj_labor_force_exit_rate_pct,
               {local_case} AS oews_local_median, x.oews_illinois_median AS oews_il_median, x.aei_observed_exposure, x.je_watch_score,
               x.onet_code, x.soc_2018_code, x.chain_review_status AS external_chain_review_status,
               coalesce(x.external_null_reason, CASE WHEN x.job_class_code IS NULL THEN 'class_not_in_reference' END) AS external_null_reason""" if integ else \
        """NULL::BIGINT AS onet_job_zone, NULL::DOUBLE AS proj_growth_pct_2025_35, NULL::DOUBLE AS proj_occ_separations_rate_pct, NULL::DOUBLE AS proj_labor_force_exit_rate_pct,
           NULL::DOUBLE AS oews_local_median, NULL::DOUBLE AS oews_il_median, NULL::DOUBLE AS aei_observed_exposure, NULL::DOUBLE AS je_watch_score,
           NULL::VARCHAR AS onet_code, NULL::VARCHAR AS soc_2018_code, NULL::VARCHAR AS external_chain_review_status, 'integrated_db_absent' AS external_null_reason"""
    ext_join = "LEFT JOIN integ.dim_job_class_external x ON x.job_class_code = p.job_class_code LEFT JOIN integ.dim_org_external o ON o.org_code = p.org_code" if integ else ""
    # age band and SURS band (assumption)
    surs = cfg.surs
    def rule(pairs):
        return " OR ".join(f"(age_years >= {a} AND service_years >= {s})" for a, s in pairs)
    def near(pairs, w):
        return " OR ".join(f"(age_years + {w} >= {a} AND service_years + {w} >= {s})" for a, s in pairs)
    w = surs["within_years"]
    con.execute(f"""CREATE OR REPLACE TEMP TABLE {out_table} AS
        WITH base AS (
            SELECT p.snap_date, p.person_id, p.position_id, p.job_suffix, p.n_active_jobs, p.person_fte AS fte_total, p.fte AS fte_primary,
                   p.annual_salary, p.job_class_code AS class_key, p.p_class_code, p.employee_class_code AS e_class,
                   substr(p.employee_class_code, 1, 1) AS employee_group, p.civil_service_ind, p.role_family, p.role_family_source, p.role_level,
                   p.org_code, p.campus_org_code, p.admin_level_2, p.college_org_code, p.dept_org_code, p.supervisor_person_id,
                   p.event_date AS primary_row_start, p.known_from AS primary_row_known_from,
                   pz.ladder_code, pz.ladder_level, pz.ladder_level_source, pz.posn_status_code, pz.posn_range_min, pz.posn_range_mid, pz.posn_range_max,
                   pz.budget_fte, CASE WHEN pz.posn_desc_update_date <= p.snap_date THEN pz.posn_desc_update_date END AS posn_desc_update_date,
                   em.empl_status_code, em.employee_group_code AS empl_group_code, em.first_hire_date, em.current_hire_date, em.adj_service_date,
                   sp.first_observed_appointment, sp.class_spell_start, sp.position_spell_start,
                   mv.* EXCLUDE (snap_date, person_id), un.* EXCLUDE (snap_date, dept_org_code),
                   {'ss.supervisor_span' if has_sup else 'NULL::BIGINT AS supervisor_span'},
                   date_diff('day', rp.birth_date, p.snap_date) / 365.25 AS age_years_raw,
                   {ext_sel}
            FROM fs_primary p
            LEFT JOIN fs_pos pz USING (snap_date, person_id)
            LEFT JOIN fs_empl em USING (snap_date, person_id)
            LEFT JOIN fs_spell sp USING (snap_date, person_id)
            LEFT JOIN fs_moves mv USING (snap_date, person_id)
            LEFT JOIN fs_unit un USING (snap_date, dept_org_code)
            {'LEFT JOIN fs_span ss USING (snap_date, person_id)' if has_sup else ''}
            LEFT JOIN r_person rp ON rp.person_id = p.person_id
            {ext_join}),
        d AS (
            SELECT *, coalesce(first_hire_date, first_observed_appointment) AS hire_date_proxy,
                   CASE WHEN first_hire_date IS NOT NULL THEN 'employment_first_hire_date' ELSE 'first_observed_appointment' END AS hire_date_source,
                   {_years('snap_date', 'coalesce(first_hire_date, first_observed_appointment)')} AS tenure_first_hire_years,
                   {_years('snap_date', 'coalesce(current_hire_date, first_observed_appointment)')} AS tenure_current_hire_years,
                   {_years('snap_date', 'coalesce(class_spell_start, primary_row_start)')} AS time_in_class_years,
                   {_years('snap_date', 'coalesce(position_spell_start, primary_row_start)')} AS time_in_position_years,
                   {_years('snap_date', 'coalesce(adj_service_date, first_hire_date, first_observed_appointment)')} AS service_years,
                   floor(age_years_raw) AS age_years
            FROM base)
        SELECT snap_date, {K} AS knowledge_date, person_id, position_id, job_suffix,
               {bucket_sql('age_years', AGE_BANDS)} AS age_band,
               tenure_first_hire_years, {bucket_sql('tenure_first_hire_years', TENURE_BUCKETS)} AS tenure_bucket,
               tenure_current_hire_years, time_in_class_years, {bucket_sql('time_in_class_years', TENURE_BUCKETS)} AS time_in_class_bucket,
               time_in_position_years,
               n_active_jobs, fte_total, fte_primary, budget_fte, annual_salary,
               CASE WHEN fte_primary > 0 THEN round(annual_salary / fte_primary, 2) END AS annual_salary_fte_adjusted,
               posn_range_min, posn_range_mid, posn_range_max,
               CASE WHEN posn_range_max > posn_range_min AND fte_primary > 0 THEN round((annual_salary / fte_primary - posn_range_min) / (posn_range_max - posn_range_min), 4) END AS pay_range_position,
               CASE WHEN posn_range_mid > 0 AND fte_primary > 0 THEN round(annual_salary / fte_primary / posn_range_mid, 4) END AS compa_ratio,
               CASE WHEN posn_range_max > 0 AND fte_primary > 0 THEN round(1 - annual_salary / fte_primary / posn_range_max, 4) END AS pay_ceiling_gap,
               coalesce(n_promotions, 0) AS n_promotions, coalesce(n_transfers, 0) AS n_transfers, coalesce(n_reclassifications, 0) AS n_reclassifications,
               coalesce(n_rehires, 0) AS n_rehires, coalesce(n_leaves, 0) AS n_leaves, coalesce(n_pay_changes_3y, 0) AS n_pay_changes_3y,
               coalesce(n_positions_held, 1) AS n_positions_held,
               CASE WHEN tenure_first_hire_years > 0 THEN round((coalesce(n_promotions, 0) + coalesce(n_transfers, 0)) / tenure_first_hire_years, 4) END AS moves_per_year,
               CASE WHEN last_move_date IS NOT NULL THEN {_years('snap_date', 'last_move_date')} ELSE tenure_current_hire_years END AS time_since_last_move_years,
               CASE WHEN last_promotion_date IS NOT NULL THEN {_years('snap_date', 'last_promotion_date')} END AS time_since_last_promotion_years,
               supervisor_span, {'TRUE' if has_sup else 'FALSE'} AS supervisor_data_available,
               supervisor_person_id IS NOT NULL AS has_supervisor,
               dept_headcount, dept_separations_12m, dept_hires_12m, dept_outbound_moves_12m, dept_churn_12m,
               e_class, employee_group, civil_service_ind, p_class_code, class_key, role_family, role_family_source, role_level,
               ladder_code, ladder_level, ladder_level_source, org_code, campus_org_code, admin_level_2, college_org_code, dept_org_code,
               empl_status_code, posn_status_code, {_years('snap_date', 'posn_desc_update_date')} AS posn_desc_age_years,
               hire_date_source,
               CASE WHEN hire_date_proxy < DATE '{surs["tier1_if_first_hire_before"]}' THEN 'tier1_assumed' WHEN hire_date_proxy IS NOT NULL THEN 'tier2_assumed' END AS surs_tier_assumed,
               CASE WHEN age_years IS NULL OR service_years IS NULL THEN 'unknown'
                    WHEN hire_date_proxy < DATE '{surs["tier1_if_first_hire_before"]}' THEN
                        CASE WHEN {rule(surs['tier1']['unreduced'])} THEN 'eligible_unreduced'
                             WHEN {rule(surs['tier1']['reduced'])} THEN 'eligible_reduced'
                             WHEN {near(surs['tier1']['unreduced'] + surs['tier1']['reduced'], w)} THEN 'within_{w}_years'
                             ELSE 'not_eligible' END
                    ELSE CASE WHEN {rule(surs['tier2']['unreduced'])} THEN 'eligible_unreduced'
                              WHEN {rule(surs['tier2']['reduced'])} THEN 'eligible_reduced'
                              WHEN {near(surs['tier2']['unreduced'] + surs['tier2']['reduced'], w)} THEN 'within_{w}_years'
                              ELSE 'not_eligible' END END AS surs_eligibility_band,
               '{surs["rule_version"]}' AS surs_rule_version,
               onet_job_zone, proj_growth_pct_2025_35, proj_occ_separations_rate_pct, proj_labor_force_exit_rate_pct,
               oews_local_median, oews_il_median,
               CASE WHEN oews_local_median > 0 AND fte_primary > 0 THEN round(annual_salary / fte_primary / oews_local_median, 4) END AS pay_ratio_oews_local,
               CASE WHEN oews_il_median > 0 AND fte_primary > 0 THEN round(annual_salary / fte_primary / oews_il_median, 4) END AS pay_ratio_oews_il,
               aei_observed_exposure, je_watch_score, onet_code, soc_2018_code, external_chain_review_status, external_null_reason,
               tg.* EXCLUDE (snap_date, person_id),
               primary_row_start, primary_row_known_from, '{cfg.job_change_date_column}' AS date_column_used, '{FEATURE_RULE_VERSION}' AS rule_version
        FROM d LEFT JOIN fs_targets tg USING (snap_date, person_id)
        ORDER BY snap_date, person_id""")
    n = con.execute(f"SELECT count(*), count(DISTINCT person_id), count(DISTINCT snap_date) FROM {out_table}").fetchall()[0]
    for t in ("fs_hist", "fs_active", "fs_primary", "fs_pos", "fs_empl", "fs_spell", "fs_moves", "fs_span", "fs_unit", "fs_targets"):
        con.execute(f"DROP TABLE IF EXISTS {t}")
    return {"rows": n[0], "persons": n[1], "snapshots": n[2], "supervisor_data_available": has_sup,
            "first_snapshot": str(snaps[0]), "last_snapshot": str(snaps[-1])}


def build_restricted_demographics(src: E.Source, out_table: str = "person_demographics_restricted") -> dict:
    """Fairness-review frame: one row per person with the restricted_fairness_only fields. Never a feature."""
    info = E.register_restricted(src)
    cols = ", ".join(info["fairness_fields"]) if info["fairness_fields"] else "NULL::VARCHAR AS no_fairness_fields"
    src.con.execute(f"""CREATE OR REPLACE TEMP TABLE {out_table} AS
        SELECT person_id, {cols}, 'restricted_fairness_only' AS role, '{info["table"]}' AS source_table
        FROM r_person ORDER BY person_id""")
    return info


def feature_summary_sql(k: int) -> str:
    """Aggregate feature summaries by snapshot x campus x role family; cells below k are suppressed."""
    return f"""
        SELECT snap_date, campus_org_code, role_family, count(*) AS n_persons,
               CASE WHEN count(*) >= {k} THEN round(avg(tenure_first_hire_years), 2) END AS mean_tenure_years,
               CASE WHEN count(*) >= {k} THEN round(avg(time_in_class_years), 2) END AS mean_time_in_class_years,
               CASE WHEN count(*) >= {k} THEN round(avg(fte_total), 3) END AS mean_fte,
               CASE WHEN count(*) >= {k} THEN round(median(annual_salary_fte_adjusted), 0) END AS median_salary_fte_adjusted,
               CASE WHEN count(*) >= {k} THEN round(avg(pay_range_position), 3) END AS mean_pay_range_position,
               CASE WHEN count(*) >= {k} THEN round(avg(moves_per_year), 4) END AS mean_moves_per_year,
               CASE WHEN count(*) >= {k} THEN round(avg(dept_churn_12m), 4) END AS mean_dept_churn_12m,
               CASE WHEN count(*) >= {k} THEN round(avg(CASE WHEN surs_eligibility_band IN ('eligible_unreduced', 'eligible_reduced') THEN 1.0 ELSE 0 END), 4) END AS share_surs_eligible_assumed,
               CASE WHEN count(*) >= {k} THEN round(avg(CASE WHEN promoted_within_12m THEN 1.0 WHEN promoted_within_12m IS NULL THEN NULL ELSE 0 END), 4) END AS share_promoted_within_12m,
               CASE WHEN count(*) >= {k} THEN round(avg(CASE WHEN separated_within_12m THEN 1.0 WHEN separated_within_12m IS NULL THEN NULL ELSE 0 END), 4) END AS share_separated_within_12m,
               CASE WHEN count(*) >= {k} THEN round(avg(proj_growth_pct_2025_35), 2) END AS mean_bls_growth_pct,
               CASE WHEN count(*) >= {k} THEN round(avg(aei_observed_exposure), 4) END AS mean_aei_exposure,
               count(*) < {k} AS suppressed
        FROM person_period_features GROUP BY ALL"""


if __name__ == "__main__":  # pragma: no cover
    import json
    cfg = Config.from_env()
    s = E.open_source(cfg)
    E.register_restricted(s)
    T.build_latest(s)
    print(json.dumps(build_features(s, snapshot_dates(cfg, s.knowledge_date)), indent=1))
