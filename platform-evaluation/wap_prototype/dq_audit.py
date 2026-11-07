"""Data-quality audit of the extract: an issue register with counts and synthetic example ids only.

Checks run on the canonical / working views (x_*), on the current-knowledge chain where stated. Every check
reports: check_id, severity, concept (source table from the mapping), description, n_rows, n_entities,
example_ids (at most 5 ids; synthetic in this pack, and never more than ids in a real run), rule.
"""
from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from wap_prototype import extract as E  # noqa: E402

AUDIT_RULE_VERSION = "wap_phase1_dq_v1"
FTE_MAX = 1.0           # JOB_DETL_FTE stored as a fraction in v3 (percent vs fraction unconfirmed; see README)
PAY_TOLERANCE = 0.005   # 0.5% slack on the class range check (rounding of FTE-adjusted pay)


def _check(con, check_id, severity, concept, description, rule, sql, id_cols: str, entity_col: str) -> dict:
    """sql must return rows with the example id columns; counts are taken from it."""
    con.execute(f"CREATE OR REPLACE TEMP TABLE dq_tmp AS {sql}")
    n, ne = con.execute(f"SELECT count(*), count(DISTINCT {entity_col}) FROM dq_tmp").fetchall()[0]
    ex = con.execute(f"SELECT DISTINCT {id_cols} FROM dq_tmp ORDER BY ALL LIMIT 5").fetchall()
    return {"check_id": check_id, "severity": severity, "concept": concept, "description": description, "rule": rule,
            "n_rows": int(n), "n_entities": int(ne), "example_ids": "; ".join("/".join(str(x) for x in r) for r in ex),
            "status": "pass" if n == 0 else ("warn" if severity in ("info", "warn") else "fail")}


def run_audit(src: E.Source, out_table: str = "dq_issue_register") -> list[dict]:
    con, m = src.con, src.m
    K = f"DATE '{src.knowledge_date}'"
    cur = f"known_from <= {K} AND known_to > {K}"
    cura = f"a.known_from <= {K} AND a.known_to > {K}"
    tbl = {c: m["concepts"][c]["table"] for c in m["concepts"]}
    out = []
    # 1. overlapping effective intervals within a job (current knowledge)
    out.append(_check(con, "DQ01", "error", tbl["appointment"], "Overlapping effective intervals within one job (person, position, suffix)",
                      "next valid_from <= previous valid_to on the current-knowledge chain",
                      f"""SELECT person_id, position_id, job_suffix, valid_from FROM (
                              SELECT *, lag(valid_to) OVER (PARTITION BY person_id, position_id, job_suffix ORDER BY valid_from, recorded_start) AS prev_to
                              FROM x_appointment WHERE {cur} AND NOT is_deleted) WHERE valid_from <= prev_to""",
                      "person_id, position_id, valid_from", "person_id"))
    # 2. gaps inside a job between consecutive Active rows
    out.append(_check(con, "DQ02", "warn", tbl["appointment"], "Gap between consecutive Active rows of the same job",
                      "next valid_from > previous valid_to + 1 day, both Active",
                      f"""SELECT person_id, position_id, job_suffix, valid_from, prev_to FROM (
                              SELECT *, lag(valid_to) OVER w AS prev_to, lag(is_active_status) OVER w AS prev_active
                              FROM x_appointment WHERE {cur} AND NOT is_deleted
                              WINDOW w AS (PARTITION BY person_id, position_id, job_suffix ORDER BY valid_from, recorded_start))
                          WHERE prev_active AND is_active_status AND valid_from > prev_to + INTERVAL 1 DAY""",
                      "person_id, position_id, valid_from", "person_id"))
    # 3. orphan jobs: no position version covers the row's effective start
    out.append(_check(con, "DQ03", "error", tbl["appointment"], "Appointment row with no position version effective on its start date",
                      "no T_POSN_HIST row with valid_from <= event_date <= valid_to (current knowledge)",
                      f"""SELECT a.person_id, a.position_id, a.event_date FROM x_appointment a WHERE {cura} AND NOT a.is_deleted
                          AND NOT EXISTS (SELECT 1 FROM x_position p WHERE p.position_id = a.position_id AND p.valid_from <= a.event_date AND p.valid_to >= a.event_date
                                          AND p.known_from <= {K} AND p.known_to > {K})""",
                      "position_id, person_id, event_date", "position_id"))
    out.append(_check(con, "DQ03b", "error", tbl["appointment"], "Appointment row whose position does not exist at all",
                      "position_id absent from T_POSN_HIST",
                      f"SELECT DISTINCT position_id, person_id FROM x_appointment a WHERE NOT EXISTS (SELECT 1 FROM x_position p WHERE p.position_id = a.position_id)",
                      "position_id, person_id", "position_id"))
    # 4. terminated people with active jobs after the termination date
    out.append(_check(con, "DQ04", "error", tbl["separation"], "Terminated person with an Active appointment effective after the termination date",
                      "x_separation.term_date < Active row valid_to and no later rehire row starts after the termination",
                      f"""SELECT s.person_id, s.term_date, a.position_id FROM x_separation s JOIN x_appointment a
                            ON a.person_id = s.person_id AND {cura} AND NOT a.is_deleted AND a.is_active_status
                           AND a.valid_from <= s.term_date AND a.valid_to > s.term_date
                          WHERE s.known_from <= {K} AND s.known_to > {K}""",
                      "person_id, term_date, position_id", "person_id"))
    out.append(_check(con, "DQ04b", "warn", tbl["separation"], "Termination record with no Terminated appointment row on that date",
                      "x_separation row without an appointment row of terminated status starting on term_date",
                      f"""SELECT s.person_id, s.term_date FROM x_separation s WHERE s.known_from <= {K} AND s.known_to > {K}
                          AND NOT EXISTS (SELECT 1 FROM x_appointment a WHERE a.person_id = s.person_id AND a.is_terminated_status AND a.event_date = s.term_date AND {cura})""",
                      "person_id, term_date", "person_id"))
    # 5. FTE out of range
    out.append(_check(con, "DQ05", "error", tbl["appointment"], f"FTE outside (0, {FTE_MAX}] on Active rows (fraction assumption)",
                      f"fte IS NULL OR fte <= 0 OR fte > {FTE_MAX}; appointment percent outside (0, 100]",
                      f"""SELECT person_id, position_id, event_date, fte, appointment_pct FROM x_appointment WHERE {cur} AND NOT is_deleted AND is_active_status
                          AND (fte IS NULL OR fte <= 0 OR fte > {FTE_MAX} OR appointment_pct <= 0 OR appointment_pct > 100)""",
                      "person_id, position_id, event_date", "person_id"))
    # 6. pay outside the position's class range (FTE-adjusted)
    out.append(_check(con, "DQ06", "warn", tbl["position"], "FTE-adjusted annual salary outside the position's POSN_MIN_SAL..POSN_MAX_SAL range",
                      f"annual_salary / fte < min*(1-{PAY_TOLERANCE}) or > max*(1+{PAY_TOLERANCE}) on Active rows; position version effective at the row start",
                      f"""SELECT a.person_id, a.position_id, a.event_date, a.annual_salary, a.fte, p.range_min, p.range_max FROM x_appointment a
                          JOIN x_position p ON p.position_id = a.position_id AND p.valid_from <= a.event_date AND p.valid_to >= a.event_date AND p.known_from <= {K} AND p.known_to > {K}
                          WHERE a.known_from <= {K} AND a.known_to > {K} AND NOT a.is_deleted AND a.is_active_status AND a.fte > 0
                            AND p.range_min IS NOT NULL AND p.range_max IS NOT NULL
                            AND (a.annual_salary / a.fte < p.range_min * (1 - {PAY_TOLERANCE}) OR a.annual_salary / a.fte > p.range_max * (1 + {PAY_TOLERANCE}))""",
                      "person_id, position_id, event_date", "person_id"))
    out.append(_check(con, "DQ06b", "warn", tbl["position"], "Position version with a missing or inverted salary range",
                      "range_min IS NULL OR range_max IS NULL OR range_min > range_max",
                      "SELECT position_id, valid_from FROM x_position WHERE range_min IS NULL OR range_max IS NULL OR range_min > range_max",
                      "position_id, valid_from", "position_id"))
    # 7. supervisors
    if src.res.has_field("appointment", "supervisor_person_id"):
        out.append(_check(con, "DQ07", "info", tbl["appointment"], "Active appointment rows with no supervisor (current rows at the extract date)",
                          "supervisor_person_id IS NULL on rows effective at the extract date",
                          f"""SELECT person_id, position_id FROM x_appointment WHERE {cur} AND NOT is_deleted AND is_active_status
                              AND valid_from <= {K} AND valid_to >= {K} AND supervisor_person_id IS NULL""",
                          "person_id, position_id", "person_id"))
        out.append(_check(con, "DQ07b", "error", tbl["appointment"], "Supervisor cycles (self-supervision or A<->B) among current rows",
                          "person supervises themself, or their supervisor's supervisor is them",
                          f"""WITH c AS (SELECT DISTINCT person_id, supervisor_person_id FROM x_appointment WHERE {cur} AND NOT is_deleted AND is_active_status
                                        AND valid_from <= {K} AND valid_to >= {K} AND supervisor_person_id IS NOT NULL)
                              SELECT a.person_id, a.supervisor_person_id FROM c a WHERE a.person_id = a.supervisor_person_id
                              UNION SELECT a.person_id, a.supervisor_person_id FROM c a JOIN c b ON b.person_id = a.supervisor_person_id AND b.supervisor_person_id = a.person_id""",
                          "person_id, supervisor_person_id", "person_id"))
        out.append(_check(con, "DQ07c", "warn", tbl["appointment"], "Supervisor id that is not a person with any appointment",
                          "supervisor_person_id not in the appointment table",
                          f"""SELECT DISTINCT supervisor_person_id, person_id FROM x_appointment a WHERE supervisor_person_id IS NOT NULL
                              AND NOT EXISTS (SELECT 1 FROM x_appointment b WHERE b.person_id = a.supervisor_person_id)""",
                          "supervisor_person_id, person_id", "supervisor_person_id"))
    # 8. deleted rows
    out.append(_check(con, "DQ08", "info", tbl["appointment"], "Appointment rows deleted in source (CUR_INFO_IND = D); excluded from current knowledge",
                      "is_deleted", "SELECT person_id, position_id, event_date FROM x_appointment WHERE is_deleted", "person_id, position_id, event_date", "person_id"))
    dv = E.in_list([str(v) for v in (m["concepts"]["employment"].get("recorded_time") or {}).get("deleted_values", ["D"])])
    out.append(_check(con, "DQ08b", "info", tbl["employment"], "Employment rows deleted in source (CUR_INFO_IND = D)",
                      "current_info_ind in deleted values", f"SELECT person_id, valid_from FROM x_employment WHERE current_info_ind IN {dv}", "person_id, valid_from", "person_id"))
    out.append(_check(con, "DQ08c", "info", tbl["position"], "Position rows deleted in source (CUR_INFO_IND = D)",
                      "current_info_ind in deleted values", f"SELECT position_id, valid_from FROM x_position WHERE current_info_ind IN {dv}", "position_id, valid_from", "position_id"))
    # 9. duplicate keys and version hygiene
    out.append(_check(con, "DQ09", "error", tbl["appointment"], "Duplicate primary key (person, position, suffix, eff_date, recorded_start)",
                      "count(*) > 1 per key", """SELECT person_id, position_id, job_suffix, eff_date, recorded_start FROM x_appointment
                                                GROUP BY ALL HAVING count(*) > 1""", "person_id, position_id, eff_date", "person_id"))
    out.append(_check(con, "DQ09b", "error", tbl["appointment"], "Lineage with more than one open (currently known) version",
                      "more than one row with known_to = open end per (person, position, suffix, eff_date)",
                      f"""SELECT person_id, position_id, job_suffix, eff_date FROM x_appointment WHERE known_to = DATE '9999-12-31' AND NOT is_deleted
                          GROUP BY ALL HAVING count(*) > 1""", "person_id, position_id, eff_date", "person_id"))
    # 10. referential integrity person / employment / appointment
    out.append(_check(con, "DQ10", "error", tbl["appointment"], "Appointment person with no person record",
                      "person_id not in the person table", "SELECT DISTINCT person_id FROM x_appointment a WHERE NOT EXISTS (SELECT 1 FROM c_person p WHERE p.person_id = a.person_id)",
                      "person_id", "person_id"))
    out.append(_check(con, "DQ10b", "warn", tbl["employment"], "Appointment person with no employment record",
                      "person_id not in the employment table", "SELECT DISTINCT person_id FROM x_appointment a WHERE NOT EXISTS (SELECT 1 FROM x_employment e WHERE e.person_id = a.person_id)",
                      "person_id", "person_id"))
    out.append(_check(con, "DQ10c", "warn", tbl["employment"], "Employment row whose effective interval is not covered by any appointment of the person (current knowledge)",
                      "no appointment row overlapping [valid_from, least(valid_to, extract)] for Active employment rows",
                      f"""SELECT e.person_id, e.valid_from FROM x_employment e WHERE e.status_code IN {E.in_list(src.codes('employment_status_active'))} AND e.known_from <= {K} AND e.known_to > {K}
                          AND NOT EXISTS (SELECT 1 FROM x_appointment a WHERE a.person_id = e.person_id AND {cura} AND NOT a.is_deleted AND a.is_active_status
                                          AND a.valid_from <= least(e.valid_to, {K}) AND a.valid_to >= e.valid_from)""",
                      "person_id, valid_from", "person_id"))
    # 11. class reference coverage and ladder
    out.append(_check(con, "DQ11", "warn", tbl["appointment"], "Class key with no role family (Unassigned)",
                      "x_class.role_family_source = 'unassigned'", "SELECT job_class_code FROM x_class WHERE role_family_source = 'unassigned'", "job_class_code", "job_class_code"))
    out.append(_check(con, "DQ11b", "info", tbl["position"], "Position class with no job-progression ladder",
                      "x_ladder.ladder_code IS NULL", "SELECT p_class_code FROM x_ladder WHERE ladder_code IS NULL", "p_class_code", "p_class_code"))
    # 12. future-dated and late-keyed rows
    out.append(_check(con, "DQ12", "info", tbl["appointment"], "Rows effective after the extract date (Future)",
                      f"valid_from > extract date", f"SELECT person_id, position_id, event_date FROM x_appointment WHERE {cur} AND valid_from > {K}",
                      "person_id, position_id, event_date", "person_id"))
    out.append(_check(con, "DQ12b", "info", tbl["appointment"], "Late-keyed rows: first known more than 30 days after they took effect",
                      "min(known_from) over the row's lineage (all versions) - valid_from > 30 days",
                      """SELECT person_id, position_id, event_date FROM (
                             SELECT person_id, position_id, job_suffix, eff_date, min(event_date) AS event_date, min(valid_from) AS first_from, min(known_from) AS first_known
                             FROM x_appointment WHERE NOT is_deleted GROUP BY 1, 2, 3, 4)
                         WHERE date_diff('day', first_from, first_known) > 30""",
                      "person_id, position_id, event_date", "person_id"))
    # 13. restricted-field hygiene (presence only; values never read here)
    cols = {r[0] for r in con.execute("DESCRIBE c_person").fetchall()}
    leaked = sorted(c for c in cols if c in ("birth_date", "sex_code", "gender_code", "race_eth_rpt_code", "ipeds_race_eth", "citizenship_group", "veteran_class"))
    out.append({"check_id": "DQ13", "severity": "error", "concept": tbl["person"], "description": "Restricted or fairness-only fields exposed in the canonical person view",
                "rule": "mapping roles restricted / restricted_fairness_only must be hidden", "n_rows": len(leaked), "n_entities": len(leaked),
                "example_ids": ", ".join(leaked), "status": "pass" if not leaked else "fail"})
    con.execute("DROP TABLE IF EXISTS dq_tmp")
    cols = ["check_id", "severity", "concept", "description", "rule", "n_rows", "n_entities", "example_ids", "status"]
    rows = ", ".join("(" + ", ".join(E.lit(r[c]) if not isinstance(r[c], int) else str(r[c]) for c in cols) + ")" for r in out)
    con.execute(f"CREATE OR REPLACE TEMP TABLE {out_table} AS SELECT * FROM (VALUES {rows}) t({', '.join(cols)})")
    con.execute(f"ALTER TABLE {out_table} ADD COLUMN rule_version VARCHAR DEFAULT '{AUDIT_RULE_VERSION}'")
    return out


def register_markdown(rows: list[dict], src: E.Source) -> str:
    lines = [f"# Data-quality issue register ({src.cfg.set_name}, extract date {src.knowledge_date}, rule version {AUDIT_RULE_VERSION})", "",
             "Counts only; example ids are synthetic. Severity: error = must be resolved before modelling; warn = review; info = expected behaviour to document.", "",
             "| Check | Status | Severity | Source table | Description | Rows | Entities | Example ids |", "|---|---|---|---|---|---:|---:|---|"]
    for r in rows:
        lines.append(f"| {r['check_id']} | {r['status']} | {r['severity']} | {r['concept']} | {r['description']} | {r['n_rows']} | {r['n_entities']} | {r['example_ids']} |")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":  # pragma: no cover
    from wap_prototype.config import Config
    s = E.open_source(Config.from_env())
    print(register_markdown(run_audit(s), s))
