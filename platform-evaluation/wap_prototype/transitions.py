"""Employee-transition dataset: one row per job event per person (the ESGC "Reusable HR Data Asset").

`build_events(src, snaps_table, out_table, effective_only)` derives events from the appointment rows known at
each `snap_date` in `snaps_table` (one column, snap_date). publish.py calls it with a single snapshot (the
extract date) to produce `transition_events`; features.py calls it with every feature snapshot so that
history-based features use only what was known at the snapshot (leakage safety).

Event rules (version in EVENT_RULE_VERSION). Rows are ordered per person by event_date; "job" means
(person, position, job suffix); "the previous row" is the previous row of the same job.
  hire                 the person's first appointment row (left-censored: the first row we can see)
  rehire               a new job starting more than one day after every earlier appointment of the person ended
  promotion            a new job starting the day after another job of the person ended, when the ladder level
                       rises (same POSN_JOB_PRGS_CD ladder, higher level) or the role family is the same and
                       REF_ROLE_FAMILY.ROLE_LEVEL rises -- OR an in-place class change with the same rise.
                       CANDIDATE LABEL (config.PROMOTION_RULE_VERSION): not an HR-confirmed promotion.
  transfer_lateral     the same move when the level is unchanged or unknown (sub-type says cross_org / cross_campus)
  transfer_down        the same move when the level falls (candidate; could be a voluntary step-down)
  additional_job       a new job that overlaps an existing active job
  reclassification     the class changes in place without a level rise (sub-type: level_same / level_down / unknown)
  org_change           the org changes in place (same job)
  fte_change           FTE changes in place
  pay_change           annual salary changes in place
  status_change        the status description changes in place (neither state is Terminated)
  reactivation         an Active row after a Terminated row of the same job
  separation_<group>   a Terminated row matched to a termination record (T_EMPEE_HIST) on the same date;
                       <group> = resignation | end_of_appointment | involuntary | death | other
  retirement           as separation when the Cookbook retirement rule holds (TERMN_REASON_CD TR/TF or EMPEE_RET_IND)
  job_end              a Terminated row with no termination record on that date (end of one job among several,
                       or the old job of an internal move)
  leave                a leave spell from T_EMPEE_HIST (status B/F), one event per spell
  no_change            a new effective row whose tracked attributes equal the previous row's (e.g. an annual pay
                       cycle row for someone already at the range maximum)
When several things change in the same in-place row the priority is class > org > FTE > pay > status.
"""
from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from wap_prototype import extract as E  # noqa: E402

EVENT_RULE_VERSION = "wap_phase1_events_v1"
EVENT_TYPES = ["hire", "rehire", "promotion", "transfer_lateral", "transfer_down", "additional_job", "reclassification",
               "org_change", "fte_change", "pay_change", "status_change", "reactivation", "separation_resignation",
               "separation_end_of_appointment", "separation_involuntary", "separation_death", "separation_other",
               "retirement", "job_end", "leave", "no_change"]
MOVE_TYPES = ("promotion", "transfer_lateral", "transfer_down")
LABEL_STATUS = {"promotion": "candidate_rule", "transfer_lateral": "candidate_rule", "transfer_down": "candidate_rule",
                "reclassification": "candidate_rule", "hire": "candidate_rule_left_censored", "rehire": "candidate_rule",
                "additional_job": "candidate_rule", "job_end": "candidate_rule", "leave": "source_status_code",
                "org_change": "derived_from_row_diff", "fte_change": "derived_from_row_diff",
                "pay_change": "derived_from_row_diff", "status_change": "derived_from_row_diff",
                "reactivation": "derived_from_row_diff"}

EVENT_COLUMNS = [
    "event_id", "known_as_of", "person_id", "position_id", "job_suffix", "event_date", "event_type", "event_subtype",
    "move_kind", "level_direction", "is_future",
    "from_p_class", "to_p_class", "from_class_key", "to_class_key", "from_e_class", "to_e_class",
    "from_ladder", "to_ladder", "from_ladder_level", "to_ladder_level", "from_role_family", "to_role_family",
    "from_role_level", "to_role_level", "from_position_id",
    "from_org_code", "to_org_code", "from_campus_org_code", "to_campus_org_code", "from_college_org_code",
    "to_college_org_code", "from_dept_org_code", "to_dept_org_code", "cross_org", "cross_campus", "cross_college", "cross_dept",
    "from_supervisor_person_id", "to_supervisor_person_id", "from_fte", "to_fte", "from_salary", "to_salary",
    "state_valid_to", "row_eff_date", "row_recorded_start", "row_post_date", "row_known_from", "current_info_ind",
    "change_reason_code", "change_reason_desc", "change_reason_label", "term_reason_code", "leave_reason_code",
    "label_status", "date_column_used", "source_table", "rule_version",
]


def build_events(src: E.Source, snaps_table: str, out_table: str = "wap_events", effective_only: bool = False) -> None:
    con, m = src.con, src.m
    appt_table = m["concepts"]["appointment"]["table"]
    empl_table = m["concepts"]["employment"]["table"]
    sep_table = m["concepts"]["separation"]["table"]
    labels = src.code_map("job_change_reason_labels")
    lcase = ("CASE " + " ".join(f"WHEN r.change_reason_code = {E.lit(k)} THEN {E.lit(v)}" for k, v in sorted(labels.items())) + " END") \
        if labels else "NULL::VARCHAR"
    eff = f"AND a.valid_from <= s.snap_date" if effective_only else ""
    K = f"DATE '{src.knowledge_date}'"
    # 1. rows known at each snapshot ------------------------------------------------------------------------
    con.execute(f"""CREATE OR REPLACE TEMP TABLE ev_rows AS
        SELECT s.snap_date, a.* FROM {snaps_table} s JOIN x_appointment a
          ON a.known_from <= s.snap_date AND a.known_to > s.snap_date {eff}""")
    keys = ["snap_date", "person_id", "position_id", "job_suffix", "eff_date", "recorded_start"]
    E.position_pick(con, "ev_rows", "event_date", "snap_date", "ev_pos", keys)
    con.execute(f"""CREATE OR REPLACE TEMP TABLE ev_o AS
        SELECT r.*, p.ladder_code, p.ladder_level, p.posn_range_min, p.posn_range_max,
               row_number() OVER wp AS rn_person,
               row_number() OVER wj AS rn_job,
               lag(r.job_class_code) OVER wj AS prev_class_key, lag(r.p_class_code) OVER wj AS prev_p_class,
               lag(r.employee_class_code) OVER wj AS prev_e_class, lag(r.org_code) OVER wj AS prev_org_code,
               lag(r.campus_org_code) OVER wj AS prev_campus, lag(r.college_org_code) OVER wj AS prev_college,
               lag(r.dept_org_code) OVER wj AS prev_dept, lag(r.fte) OVER wj AS prev_fte,
               lag(r.annual_salary) OVER wj AS prev_salary, lag(r.supervisor_person_id) OVER wj AS prev_supervisor,
               lag(r.status_desc) OVER wj AS prev_status_desc, lag(r.is_terminated_status) OVER wj AS prev_terminated,
               lag(r.role_family) OVER wj AS prev_role_family, lag(r.role_level) OVER wj AS prev_role_level,
               lag(p.ladder_code) OVER wj AS prev_ladder, lag(p.ladder_level) OVER wj AS prev_ladder_level,
               -- latest end of any EARLIER ACTIVE row (a Terminated row's open exp date must not extend the spell)
               max(CASE WHEN r.is_active_status THEN r.valid_to END) OVER (PARTITION BY r.snap_date, r.person_id
                                     ORDER BY r.event_date, r.valid_to, r.position_id, r.job_suffix, r.recorded_start, r.eff_date
                                     ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS prev_max_to
        FROM ev_rows r LEFT JOIN ev_pos p USING ({', '.join(keys)})
        WINDOW wp AS (PARTITION BY r.snap_date, r.person_id ORDER BY r.event_date, r.valid_to, r.position_id, r.job_suffix, r.recorded_start, r.eff_date),
               wj AS (PARTITION BY r.snap_date, r.person_id, r.position_id, r.job_suffix ORDER BY r.event_date, r.recorded_start, r.eff_date)""")
    # 2. the "from" job of a new job: the other job that ended the day before, else the latest earlier active job
    con.execute("""CREATE OR REPLACE TEMP TABLE ev_from AS
        SELECT * EXCLUDE (rn) FROM (
            SELECT n.snap_date, n.person_id, n.position_id, n.job_suffix, n.eff_date, n.recorded_start,
                   f.position_id AS from_position_id, f.job_class_code AS f_class_key, f.p_class_code AS f_p_class,
                   f.employee_class_code AS f_e_class, f.org_code AS f_org, f.campus_org_code AS f_campus,
                   f.college_org_code AS f_college, f.dept_org_code AS f_dept, f.fte AS f_fte, f.annual_salary AS f_salary,
                   f.supervisor_person_id AS f_supervisor, f.role_family AS f_role_family, f.role_level AS f_role_level,
                   f.ladder_code AS f_ladder, f.ladder_level AS f_ladder_level,
                   (f.valid_to = n.event_date - INTERVAL 1 DAY) AS ended_day_before,
                   row_number() OVER (PARTITION BY n.snap_date, n.person_id, n.position_id, n.job_suffix, n.eff_date, n.recorded_start
                                      ORDER BY (f.valid_to = n.event_date - INTERVAL 1 DAY) DESC, f.event_date DESC, f.valid_to DESC, f.fte DESC, f.position_id) AS rn
            FROM ev_o n JOIN ev_o f
              ON f.snap_date = n.snap_date AND f.person_id = n.person_id
             AND (f.position_id, f.job_suffix) <> (n.position_id, n.job_suffix)
             AND f.is_active_status AND f.event_date < n.event_date
            WHERE n.rn_job = 1 AND n.rn_person > 1)
        WHERE rn = 1""")
    # 3. separation records known at the snapshot, matched to Terminated rows on the same date --------------
    con.execute("""CREATE OR REPLACE TEMP TABLE ev_sep AS
        SELECT s.snap_date, x.* FROM (SELECT DISTINCT snap_date FROM ev_rows) s JOIN x_separation x
          ON x.known_from <= s.snap_date AND x.known_to > s.snap_date""")
    con.execute("""CREATE OR REPLACE TEMP TABLE ev_sep_match AS
        SELECT * EXCLUDE (rn) FROM (
            SELECT o.snap_date, o.person_id, o.position_id, o.job_suffix, o.eff_date, o.recorded_start,
                   sp.term_date, sp.term_reason_code, sp.reason_group, sp.is_retirement,
                   row_number() OVER (PARTITION BY o.snap_date, o.person_id, sp.term_date ORDER BY o.fte DESC NULLS LAST, o.position_id, o.job_suffix) AS rn
            FROM ev_o o JOIN ev_sep sp ON sp.snap_date = o.snap_date AND sp.person_id = o.person_id AND sp.term_date = o.event_date
            WHERE o.is_terminated_status)
        WHERE rn = 1""")
    # 4. classify appointment rows ------------------------------------------------------------------------------
    def level_dir(t_ladder, f_ladder, t_level, f_level, t_rf, f_rf, t_rl, f_rl):
        return f"""CASE WHEN {t_ladder} IS NOT NULL AND {t_ladder} = {f_ladder} AND {t_level} IS NOT NULL AND {f_level} IS NOT NULL
                        THEN CASE WHEN {t_level} > {f_level} THEN 'up' WHEN {t_level} < {f_level} THEN 'down' ELSE 'same' END
                        WHEN {t_rf} IS NOT NULL AND {t_rf} = {f_rf} AND {t_rl} IS NOT NULL AND {f_rl} IS NOT NULL
                        THEN CASE WHEN {t_rl} > {f_rl} THEN 'up' WHEN {t_rl} < {f_rl} THEN 'down' ELSE 'same' END
                        WHEN {t_ladder} IS NOT NULL AND {f_ladder} IS NOT NULL AND {t_ladder} <> {f_ladder} THEN 'different_ladder'
                        ELSE 'unknown' END"""
    ld = level_dir("b.ladder_code", "b.f_ladder_c", "b.ladder_level", "b.f_level_c", "b.role_family", "b.f_rf_c", "b.role_level", "b.f_rl_c")
    con.execute(f"""CREATE OR REPLACE TEMP TABLE ev_cls AS
        WITH b AS (
            SELECT o.*, f.* EXCLUDE (snap_date, person_id, position_id, job_suffix, eff_date, recorded_start),
                   sm.term_reason_code, sm.reason_group, sm.is_retirement,
                   -- the comparison state: the from-job for a new job, the previous row for an in-place change
                   CASE WHEN o.rn_job = 1 THEN f.f_ladder ELSE o.prev_ladder END AS f_ladder_c,
                   CASE WHEN o.rn_job = 1 THEN f.f_ladder_level ELSE o.prev_ladder_level END AS f_level_c,
                   CASE WHEN o.rn_job = 1 THEN f.f_role_family ELSE o.prev_role_family END AS f_rf_c,
                   CASE WHEN o.rn_job = 1 THEN f.f_role_level ELSE o.prev_role_level END AS f_rl_c
            FROM ev_o o
            LEFT JOIN ev_from f USING (snap_date, person_id, position_id, job_suffix, eff_date, recorded_start)
            LEFT JOIN ev_sep_match sm USING (snap_date, person_id, position_id, job_suffix, eff_date, recorded_start)),
        c AS (
            SELECT b.*, {ld} AS level_direction
            FROM b)
        SELECT c.*,
               CASE WHEN c.is_terminated_status THEN
                        CASE WHEN c.reason_group IS NULL THEN 'job_end'
                             WHEN c.is_retirement THEN 'retirement'
                             ELSE 'separation_' || c.reason_group END
                    WHEN c.rn_person = 1 THEN 'hire'
                    WHEN c.rn_job = 1 AND (c.prev_max_to IS NULL OR c.event_date > c.prev_max_to + INTERVAL 1 DAY) THEN 'rehire'
                    WHEN c.rn_job = 1 AND coalesce(c.ended_day_before, FALSE) THEN
                        CASE c.level_direction WHEN 'up' THEN 'promotion' WHEN 'down' THEN 'transfer_down' ELSE 'transfer_lateral' END
                    WHEN c.rn_job = 1 THEN 'additional_job'
                    WHEN coalesce(c.prev_terminated, FALSE) AND c.is_active_status THEN 'reactivation'
                    WHEN c.job_class_code IS DISTINCT FROM c.prev_class_key OR c.p_class_code IS DISTINCT FROM c.prev_p_class THEN
                        CASE WHEN c.level_direction = 'up' THEN 'promotion' ELSE 'reclassification' END
                    WHEN c.org_code IS DISTINCT FROM c.prev_org_code THEN 'org_change'
                    WHEN c.fte IS DISTINCT FROM c.prev_fte THEN 'fte_change'
                    WHEN c.annual_salary IS DISTINCT FROM c.prev_salary THEN 'pay_change'
                    WHEN c.status_desc IS DISTINCT FROM c.prev_status_desc THEN 'status_change'
                    ELSE 'no_change' END AS event_type,
               CASE WHEN c.rn_job = 1 THEN 'job_change' ELSE 'in_place' END AS move_kind
        FROM c""")
    # 5. appointment-sourced events in the published layout ------------------------------------------------------
    con.execute(f"""CREATE OR REPLACE TEMP TABLE ev_appt AS
        SELECT md5(concat_ws('|', r.snap_date, r.person_id, r.position_id, r.job_suffix, r.eff_date, r.recorded_start, {E.lit(appt_table)})) AS event_id,
               r.snap_date AS known_as_of, r.person_id, r.position_id, r.job_suffix, r.event_date, r.event_type,
               CASE WHEN r.event_type IN ('promotion', 'transfer_lateral', 'transfer_down') AND r.move_kind = 'job_change' THEN
                        concat_ws(',', CASE WHEN r.campus_org_code IS DISTINCT FROM r.f_campus THEN 'cross_campus' END,
                                       CASE WHEN r.org_code IS DISTINCT FROM r.f_org THEN 'cross_org' ELSE 'same_org' END)
                    WHEN r.event_type IN ('promotion', 'reclassification') THEN 'level_' || r.level_direction
                    WHEN r.event_type LIKE 'separation_%' OR r.event_type = 'retirement' THEN r.term_reason_code
                    WHEN r.event_type = 'hire' THEN 'first_observed_appointment'
                    END AS event_subtype,
               CASE WHEN r.event_type IN ('hire', 'rehire', 'additional_job') THEN 'job_start'
                    WHEN r.is_terminated_status THEN 'job_stop' ELSE r.move_kind END AS move_kind,
               CASE WHEN r.rn_job = 1 AND r.rn_person > 1 OR (r.rn_job > 1 AND (r.job_class_code IS DISTINCT FROM r.prev_class_key))
                    THEN r.level_direction END AS level_direction,
               r.event_date > r.snap_date AS is_future,
               CASE WHEN r.rn_job = 1 THEN r.f_p_class ELSE r.prev_p_class END AS from_p_class, r.p_class_code AS to_p_class,
               CASE WHEN r.rn_job = 1 THEN r.f_class_key ELSE r.prev_class_key END AS from_class_key, r.job_class_code AS to_class_key,
               CASE WHEN r.rn_job = 1 THEN r.f_e_class ELSE r.prev_e_class END AS from_e_class, r.employee_class_code AS to_e_class,
               r.f_ladder_c AS from_ladder, r.ladder_code AS to_ladder, r.f_level_c AS from_ladder_level, r.ladder_level AS to_ladder_level,
               r.f_rf_c AS from_role_family, r.role_family AS to_role_family, r.f_rl_c AS from_role_level, r.role_level AS to_role_level,
               CASE WHEN r.rn_job = 1 THEN r.from_position_id ELSE r.position_id END AS from_position_id,
               CASE WHEN r.rn_job = 1 THEN r.f_org ELSE r.prev_org_code END AS from_org_code, r.org_code AS to_org_code,
               CASE WHEN r.rn_job = 1 THEN r.f_campus ELSE r.prev_campus END AS from_campus_org_code, r.campus_org_code AS to_campus_org_code,
               CASE WHEN r.rn_job = 1 THEN r.f_college ELSE r.prev_college END AS from_college_org_code, r.college_org_code AS to_college_org_code,
               CASE WHEN r.rn_job = 1 THEN r.f_dept ELSE r.prev_dept END AS from_dept_org_code, r.dept_org_code AS to_dept_org_code,
               NULL::BOOLEAN AS cross_org, NULL::BOOLEAN AS cross_campus, NULL::BOOLEAN AS cross_college, NULL::BOOLEAN AS cross_dept,
               CASE WHEN r.rn_job = 1 THEN r.f_supervisor ELSE r.prev_supervisor END AS from_supervisor_person_id, r.supervisor_person_id AS to_supervisor_person_id,
               CASE WHEN r.rn_job = 1 THEN r.f_fte ELSE r.prev_fte END AS from_fte, r.fte AS to_fte,
               CASE WHEN r.rn_job = 1 THEN r.f_salary ELSE r.prev_salary END AS from_salary, r.annual_salary AS to_salary,
               r.valid_to AS state_valid_to, r.eff_date AS row_eff_date, r.recorded_start AS row_recorded_start, r.post_date AS row_post_date,
               r.known_from AS row_known_from, r.current_info_ind,
               r.change_reason_code, r.change_reason_desc, {lcase} AS change_reason_label,
               r.term_reason_code, NULL::VARCHAR AS leave_reason_code,
               NULL::VARCHAR AS label_status, r.date_column_used, {E.lit(appt_table)} AS source_table, {E.lit(EVENT_RULE_VERSION)} AS rule_version
        FROM ev_cls r""")
    # 6. employment-sourced events: separations with no Terminated row that day, and leave spells ----------------
    con.execute(f"""CREATE OR REPLACE TEMP TABLE ev_emp_raw AS
        SELECT sp.snap_date, sp.person_id, sp.term_date AS event_date,
               CASE WHEN sp.is_retirement THEN 'retirement' ELSE 'separation_' || sp.reason_group END AS event_type,
               sp.term_reason_code AS event_subtype, sp.term_reason_code, NULL::VARCHAR AS leave_reason_code,
               NULL::DATE AS state_valid_to, sp.post_date, sp.known_from, {E.lit(sep_table)} AS source_table
        FROM ev_sep sp
        WHERE NOT EXISTS (SELECT 1 FROM ev_sep_match sm WHERE sm.snap_date = sp.snap_date AND sm.person_id = sp.person_id AND sm.term_date = sp.term_date)
        {'AND sp.term_date <= sp.snap_date' if effective_only else ''}
        UNION ALL
        SELECT s.snap_date, l.person_id, l.leave_from, 'leave', l.leave_status_code, NULL, l.leave_reason_code, l.leave_to, l.post_date, l.known_from, {E.lit(empl_table)}
        FROM (SELECT DISTINCT snap_date FROM ev_rows) s JOIN x_leave l ON l.known_from <= s.snap_date AND l.known_to > s.snap_date
        {'WHERE l.leave_from <= s.snap_date' if effective_only else ''}""")
    con.execute(f"""CREATE OR REPLACE TEMP TABLE ev_emp AS
        WITH st AS (
            SELECT * EXCLUDE (rn) FROM (
                SELECT e.snap_date, e.person_id, e.event_date, e.event_type, o.* EXCLUDE (snap_date, person_id, event_date),
                       row_number() OVER (PARTITION BY e.snap_date, e.person_id, e.event_date, e.event_type ORDER BY o.event_date DESC, o.fte DESC NULLS LAST, o.position_id) AS rn
                FROM ev_emp_raw e LEFT JOIN ev_o o ON o.snap_date = e.snap_date AND o.person_id = e.person_id AND o.is_active_status AND o.event_date <= e.event_date)
            WHERE rn = 1)
        SELECT md5(concat_ws('|', e.snap_date, e.person_id, e.event_date, e.event_type, e.source_table)) AS event_id,
               e.snap_date AS known_as_of, e.person_id, st.position_id, st.job_suffix, e.event_date, e.event_type, e.event_subtype,
               CASE WHEN e.event_type = 'leave' THEN 'leave_spell' ELSE 'job_stop' END AS move_kind, NULL::VARCHAR AS level_direction,
               e.event_date > e.snap_date AS is_future,
               st.p_class_code AS from_p_class, st.p_class_code AS to_p_class, st.job_class_code AS from_class_key, st.job_class_code AS to_class_key,
               st.employee_class_code AS from_e_class, st.employee_class_code AS to_e_class,
               st.ladder_code AS from_ladder, st.ladder_code AS to_ladder, st.ladder_level AS from_ladder_level, st.ladder_level AS to_ladder_level,
               st.role_family AS from_role_family, st.role_family AS to_role_family, st.role_level AS from_role_level, st.role_level AS to_role_level,
               st.position_id AS from_position_id, st.org_code AS from_org_code, st.org_code AS to_org_code,
               st.campus_org_code AS from_campus_org_code, st.campus_org_code AS to_campus_org_code,
               st.college_org_code AS from_college_org_code, st.college_org_code AS to_college_org_code,
               st.dept_org_code AS from_dept_org_code, st.dept_org_code AS to_dept_org_code,
               FALSE AS cross_org, FALSE AS cross_campus, FALSE AS cross_college, FALSE AS cross_dept,
               st.supervisor_person_id AS from_supervisor_person_id, st.supervisor_person_id AS to_supervisor_person_id,
               st.fte AS from_fte, st.fte AS to_fte, st.annual_salary AS from_salary, st.annual_salary AS to_salary,
               e.state_valid_to, NULL::DATE AS row_eff_date, NULL::DATE AS row_recorded_start, e.post_date AS row_post_date,
               e.known_from AS row_known_from, NULL::VARCHAR AS current_info_ind,
               NULL::VARCHAR AS change_reason_code, NULL::VARCHAR AS change_reason_desc, NULL::VARCHAR AS change_reason_label,
               e.term_reason_code, e.leave_reason_code, NULL::VARCHAR AS label_status,
               {E.lit(src.cfg.job_change_date_column)} AS date_column_used, e.source_table, {E.lit(EVENT_RULE_VERSION)} AS rule_version
        FROM ev_emp_raw e LEFT JOIN st USING (snap_date, person_id, event_date, event_type)""")
    lab = "CASE " + " ".join(f"WHEN event_type = {E.lit(k)} THEN {E.lit(v)}" for k, v in LABEL_STATUS.items()) + \
        " WHEN event_type LIKE 'separation_%' OR event_type = 'retirement' THEN 'source_termination_code' ELSE 'derived' END"
    con.execute(f"""CREATE OR REPLACE TEMP TABLE {out_table} AS
        SELECT * REPLACE ({lab} AS label_status,
                          (from_org_code IS DISTINCT FROM to_org_code) AS cross_org,
                          (from_campus_org_code IS DISTINCT FROM to_campus_org_code) AS cross_campus,
                          (from_college_org_code IS DISTINCT FROM to_college_org_code) AS cross_college,
                          (from_dept_org_code IS DISTINCT FROM to_dept_org_code) AS cross_dept)
        FROM (SELECT * FROM ev_appt UNION ALL BY NAME SELECT * FROM ev_emp)
        ORDER BY known_as_of, person_id, event_date, event_type, position_id, job_suffix""")
    for t in ("ev_rows", "ev_pos", "ev_o", "ev_from", "ev_sep", "ev_sep_match", "ev_cls", "ev_appt", "ev_emp_raw", "ev_emp"):
        con.execute(f"DROP TABLE IF EXISTS {t}")


def build_latest(src: E.Source, out_table: str = "transition_events") -> None:
    """The published transition dataset: everything as known on the extract date, future-dated rows flagged."""
    src.con.execute(f"CREATE OR REPLACE TEMP TABLE ev_snaps AS SELECT DATE '{src.knowledge_date}' AS snap_date")
    build_events(src, "ev_snaps", out_table, effective_only=False)


def event_counts(con, table: str = "transition_events") -> dict:
    return {r[0]: r[1] for r in con.execute(f"SELECT event_type, count(*) FROM {table} GROUP BY 1 ORDER BY 1").fetchall()}


def agreement_with_change_codes(con, table: str = "transition_events"):
    """Diagnostic: event_type x the source change-reason label (mapping code_values.job_change_reason_labels)."""
    return con.execute(f"""SELECT event_type, coalesce(change_reason_label, change_reason_code, '(none)') AS source_label, count(*) AS n
                           FROM {table} GROUP BY 1, 2 ORDER BY 1, 2""").fetchall()


if __name__ == "__main__":  # pragma: no cover
    import json
    from wap_prototype.config import Config
    s = E.open_source(Config.from_env())
    build_latest(s)
    print(json.dumps(event_counts(s.con), indent=1))
    for r in agreement_with_change_codes(s.con):
        print(r)
