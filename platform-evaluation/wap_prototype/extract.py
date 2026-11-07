"""As-of extract over the six Cookbook tables, read only through integration/mapping.py.

`open_source(cfg)` registers the canonical views `c_<concept>` (mapping.resolve) and then the prototype's
working views:

  x_org_path      org -> campus / admin / college / department ancestors (tree walk over the org concept)
  x_ladder        position class (P-Class) -> job-progression ladder and level (documented derived rule)
  x_class         class key -> role family (+ source), ladder, class range
  x_appointment   appointment rows with event_date and the effective / recorded intervals chosen by the
                  `job_change_date_column` switch, plus org path, ladder, deleted flag
  x_employment    employment rows (T_EMPEE_HIST) with known intervals
  x_position      position versions with known intervals
  x_separation    one row per (person, termination date): reason code, reason group, retirement flag
  x_leave         leave spells from employment status codes (config.leave_status_codes)
  r_person        RESTRICTED: birth date and fairness-only demographics, read straight from the physical
                  person table via the mapping's column names. Only an age band ever leaves this module;
                  the demographics go to the restricted fairness frame and never into features.

As-known rule everywhere: a row is known at K when known_from <= K < known_to; effective on d when
valid_from <= d <= valid_to (inclusive, 9999-12-31 open end). CUR_INFO_IND 'D' rows are known only from their
version start to their post date (mapping.py). The latest knowledge is K = the extract date.

The date-column switch (config.job_change_date_column):
  JOB_DETL_EFF_DT        (v3) event_date = eff_date; versions of the same (person, position, suffix, eff_date)
                         lineage are ordered by recorded_start = JOB_DETL_HIST_EFF_DT (mode lineage_next).
  JOB_DETL_HIST_EFF_DT   (alternative) event_date = recorded_start; each row is a distinct effective state whose
                         interval runs to the day before the next recorded_start of the same job, capped at the
                         row's exp_date; rows are known from their post date (mode post_date), or from their
                         effective date when config.hist_mode_known_from = effective_date (assumes immediate posting).
"""
from __future__ import annotations

import datetime as dt
import os
import sys
from pathlib import Path

import duckdb

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from integration import mapping as M  # noqa: E402
from wap_prototype.config import OPEN_END, Config, EMPLOYEE_GROUP_FAMILY  # noqa: E402

OPEN = f"DATE '{OPEN_END}'"
TERMINATED_KEY = "appointment_status_terminated"
ACTIVE_KEY = "appointment_status_active"
FAIRNESS_ROLE = "restricted_fairness_only"


def lit(s) -> str:
    return "NULL" if s is None else "'" + str(s).replace("'", "''") + "'"


def in_list(vals) -> str:
    return "(" + ", ".join(lit(v) for v in vals) + ")" if vals else "(NULL)"


class Source:
    """One open DuckDB connection with canonical and working views registered."""

    def __init__(self, con, cfg: Config, m: dict, res: M.Resolution, date_mode: str, knowledge_date: dt.date, report: dict):
        self.con, self.cfg, self.m, self.res = con, cfg, m, res
        self.date_mode = date_mode                  # eff_date | recorded_start
        self.knowledge_date = knowledge_date
        self.report = report

    def codes(self, key: str) -> list[str]:
        return M.code_values(self.m, key)

    def code_map(self, key: str) -> dict:
        return M.code_map(self.m, key)

    def close(self) -> None:
        try:
            self.con.close()
        except Exception:
            pass


# ----------------------------------------------------------------------------- opening
def resolve_date_mode(cfg: Config, m: dict) -> str:
    """Map the configured physical column to the canonical appointment field it is mapped to."""
    fields = m["concepts"]["appointment"]["fields"]
    for fname in ("eff_date", "recorded_start"):
        if fields.get(fname, {}).get("column") == cfg.job_change_date_column:
            return fname
    raise M.MappingError(f"job_change_date_column={cfg.job_change_date_column!r} is neither appointment.eff_date "
                         f"nor appointment.recorded_start in {m['_path']}")


def open_source(cfg: Config, mapping: dict | None = None, attach_integrated: bool = True) -> Source:
    os.environ.update(cfg.mapping_env())
    m = mapping or M.load_mapping(cfg.mapping_file)
    con = duckdb.connect()
    con.execute("SET threads TO 4")
    res = M.resolve(con, m, cfg.set_name, strict=True)
    date_mode = resolve_date_mode(cfg, m)
    report = {"mapping_file": m["_path"], "date_mode": date_mode, "integrated_attached": False,
              "hist_mode_known_from": cfg.hist_mode_known_from if date_mode == "recorded_start" else "n/a (lineage_next)"}
    if attach_integrated and cfg.integrated_db.exists():
        con.execute(f"ATTACH {lit(cfg.integrated_db.as_posix())} AS integ (READ_ONLY)")
        report["integrated_attached"] = True
        report["integrated_db"] = str(cfg.integrated_db)
    k = cfg.as_of_date or cfg.manifest_extract_date()
    if k is None:
        k = con.execute("SELECT max(post_date) FROM c_appointment").fetchall()[0][0]
    src = Source(con, cfg, m, res, date_mode, k, report)
    register_views(src)
    return src


# ----------------------------------------------------------------------------- working views
def register_views(src: Source) -> None:
    con, cfg, res = src.con, src.cfg, src.res
    K = f"DATE '{src.knowledge_date}'"
    # --- org path -------------------------------------------------------------------------------------------
    has_level = res.has_field("org", "org_level")
    con.execute(f"""CREATE OR REPLACE TEMP TABLE x_org_path AS
        WITH RECURSIVE o AS (SELECT DISTINCT org_code, parent_org_code, org_title, {'org_level' if has_level else 'NULL::INTEGER AS org_level'} FROM c_org),
        roots AS (SELECT org_code FROM o WHERE parent_org_code IS NULL OR parent_org_code NOT IN (SELECT org_code FROM o)),
        walk(org_code, anc, anc_parent, anc_level, depth) AS (
            SELECT org_code, org_code, parent_org_code, org_level, 0 FROM o
            UNION ALL
            SELECT w.org_code, o.org_code, o.parent_org_code, o.org_level, w.depth + 1
            FROM walk w JOIN o ON o.org_code = w.anc_parent WHERE w.depth < 25),
        agg AS (
            SELECT org_code,
                   max(depth) AS org_depth,
                   max(anc) FILTER (WHERE anc_parent IN (SELECT org_code FROM roots)) AS campus_child,
                   max(anc) FILTER (WHERE anc IN (SELECT org_code FROM roots)) AS root_code,
                   max(anc) FILTER (WHERE anc_level = 2) AS admin_level_2,
                   max(anc) FILTER (WHERE anc_level = 3) AS college_by_level,
                   max(anc) FILTER (WHERE anc_level = 5) AS dept_by_level,
                   max(anc) FILTER (WHERE depth = (SELECT max(depth) FROM walk w2 WHERE w2.org_code = walk.org_code) - 3) AS college_by_depth
            FROM walk GROUP BY org_code)
        SELECT a.org_code, o.org_title, a.org_depth, coalesce(a.campus_child, a.root_code) AS campus_org_code, a.admin_level_2,
               coalesce(a.college_by_level, a.college_by_depth) AS college_org_code,
               coalesce(a.dept_by_level, CASE WHEN a.org_depth >= 4 THEN a.org_code END) AS dept_org_code,
               CASE WHEN a.college_by_level IS NOT NULL OR a.dept_by_level IS NOT NULL THEN 'org_level_column' ELSE 'depth_fallback' END AS path_source
        FROM agg a JOIN o USING (org_code)""")
    # --- ladders: P-Class -> job progression code and level --------------------------------------------------
    has_rf = res.available("role_family")
    rf_join = "LEFT JOIN c_role_family rf ON rf.job_class_code = pc.job_class_code" if has_rf else \
        "LEFT JOIN (SELECT NULL::VARCHAR AS job_class_code, NULL::VARCHAR AS role_family, NULL::INTEGER AS role_level, NULL::VARCHAR AS critical_ind) rf ON FALSE"
    has_ladder = res.has_field("position", "job_progression_code")
    ladder_expr = "p.job_progression_code" if has_ladder else "NULL::VARCHAR"
    con.execute(f"""CREATE OR REPLACE TEMP TABLE x_ladder AS
        WITH pc AS (
            SELECT p.p_class_code, mode(p.job_class_code) AS job_class_code, mode({ladder_expr}) AS ladder_code,
                   median(p.range_min) AS range_min, median(p.range_mid) AS range_mid, median(p.range_max) AS range_max
            FROM c_position p WHERE p.p_class_code IS NOT NULL GROUP BY 1),
        lv AS (
            SELECT pc.*, rf.role_family, rf.role_level, rf.critical_ind,
                   count(*) OVER (PARTITION BY pc.ladder_code) AS n_on_ladder,
                   count(rf.role_level) OVER (PARTITION BY pc.ladder_code) AS n_with_role_level,
                   dense_rank() OVER (PARTITION BY pc.ladder_code ORDER BY pc.range_min NULLS LAST, pc.p_class_code) AS rank_by_range_min
            FROM pc {rf_join})
        SELECT p_class_code, job_class_code, ladder_code, role_family, role_level, critical_ind, range_min, range_mid, range_max,
               CASE WHEN ladder_code IS NULL THEN NULL
                    WHEN n_with_role_level = n_on_ladder THEN role_level ELSE rank_by_range_min END AS ladder_level,
               CASE WHEN ladder_code IS NULL THEN 'no_ladder'
                    WHEN n_with_role_level = n_on_ladder THEN 'role_family_role_level' ELSE 'rank_of_range_min_within_ladder' END AS ladder_level_source
        FROM lv""")
    # --- class key -> role family -----------------------------------------------------------------------------
    integ = src.report["integrated_attached"]
    integ_join = "LEFT JOIN integ.dim_job_class_internal di ON di.job_class_code = jc.job_class_code" if integ else \
        "LEFT JOIN (SELECT NULL::VARCHAR AS job_class_code, NULL::VARCHAR AS role_family, NULL::VARCHAR AS role_family_source) di ON FALSE"
    eg_case = "CASE " + " ".join(f"WHEN eg.grp = {lit(k)} THEN {lit(v)}" for k, v in EMPLOYEE_GROUP_FAMILY.items()) + " END"
    con.execute(f"""CREATE OR REPLACE TEMP TABLE x_class AS
        WITH jc AS (SELECT DISTINCT job_class_code FROM c_appointment WHERE job_class_code IS NOT NULL
                    UNION SELECT DISTINCT job_class_code FROM c_position WHERE job_class_code IS NOT NULL),
        eg AS (SELECT job_class_code, mode(substr(employee_class_code, 1, 1)) AS grp FROM c_appointment GROUP BY 1),
        rf AS (SELECT * FROM {'c_role_family' if has_rf else '(SELECT NULL::VARCHAR AS job_class_code, NULL::VARCHAR AS role_family, NULL::INTEGER AS role_level, NULL::VARCHAR AS critical_ind) t'}),
        cls AS (SELECT * FROM {'c_job_class' if res.available('job_class') else '(SELECT NULL::VARCHAR AS job_class_code, NULL::VARCHAR AS class_title, NULL::DOUBLE AS min_annual_amount, NULL::DOUBLE AS max_annual_amount, NULL::VARCHAR AS class_source) t'})
        SELECT jc.job_class_code,
               coalesce(rf.role_family, CASE WHEN di.role_family <> 'Unassigned' THEN di.role_family END, {eg_case}, 'Unassigned') AS role_family,
               CASE WHEN rf.role_family IS NOT NULL THEN 'sample_role_family_reference'
                    WHEN di.role_family IS NOT NULL AND di.role_family <> 'Unassigned' THEN 'integration_dim_job_class_internal'
                    WHEN {eg_case} IS NOT NULL THEN 'employee_group_fallback' ELSE 'unassigned' END AS role_family_source,
               rf.role_level, rf.critical_ind, cls.class_title, cls.class_source, cls.min_annual_amount, cls.max_annual_amount
        FROM jc LEFT JOIN rf ON rf.job_class_code = jc.job_class_code
        {integ_join}
        LEFT JOIN eg ON eg.job_class_code = jc.job_class_code
        LEFT JOIN cls ON cls.job_class_code = jc.job_class_code""")
    # --- appointments with the date switch applied ------------------------------------------------------------
    deleted = f"coalesce(a.current_info_ind IN {in_list(_deleted_values(src))}, FALSE)"
    if src.date_mode == "eff_date":
        ev = "a.eff_date"
        vf, vt, kf, kt = "a.valid_from", "a.valid_to", "a.known_from", "a.known_to"
    else:
        ev = "a.recorded_start"
        vf = "a.recorded_start"
        vt = (f"least(a.valid_to, coalesce(lead(a.recorded_start) OVER (PARTITION BY a.person_id, a.position_id, a.job_suffix "
              f"ORDER BY a.recorded_start, a.eff_date) - INTERVAL 1 DAY, {OPEN})::DATE)")
        known = "a.recorded_start" if cfg.hist_mode_known_from == "effective_date" else "coalesce(a.post_date, DATE '0001-01-01')"
        kf = f"CASE WHEN {deleted} THEN a.recorded_start ELSE {known} END"
        kt = f"CASE WHEN {deleted} THEN coalesce(a.post_date, {OPEN}) ELSE {OPEN} END"
    con.execute(f"""CREATE OR REPLACE TEMP TABLE x_appointment AS
        SELECT a.* EXCLUDE (valid_from, valid_to, known_from, known_to),
               {ev} AS event_date, {vf} AS valid_from, {vt} AS valid_to, {kf} AS known_from, {kt} AS known_to,
               {deleted} AS is_deleted,
               a.status_code IN {in_list(src.codes(ACTIVE_KEY))} AS is_active_status,
               a.status_code IN {in_list(src.codes(TERMINATED_KEY))} AS is_terminated_status,
               op.campus_org_code, op.admin_level_2, op.college_org_code, op.dept_org_code,
               xc.role_family, xc.role_family_source, xc.role_level,
               {lit(src.cfg.job_change_date_column)} AS date_column_used
        FROM c_appointment a
        LEFT JOIN x_org_path op ON op.org_code = a.org_code
        LEFT JOIN x_class xc ON xc.job_class_code = a.job_class_code""")
    # --- employment, positions, separations, leave ------------------------------------------------------------
    if res.has_field("employment", "home_org_code"):
        con.execute("CREATE OR REPLACE TEMP TABLE x_employment AS SELECT e.*, op.campus_org_code AS home_campus_org_code "
                    "FROM c_employment e LEFT JOIN x_org_path op ON op.org_code = e.home_org_code")
    else:
        con.execute("CREATE OR REPLACE TEMP TABLE x_employment AS SELECT e.*, NULL::VARCHAR AS home_campus_org_code FROM c_employment e")
    con.execute("""CREATE OR REPLACE TEMP TABLE x_position AS
        SELECT p.*, xl.ladder_code, xl.ladder_level, xl.ladder_level_source FROM c_position p
        LEFT JOIN x_ladder xl ON xl.p_class_code = p.p_class_code""")
    reasons = src.code_map("separation_reason_group")
    rcase = "CASE " + " ".join(f"WHEN s.term_reason_code = {lit(k)} THEN {lit(v)}" for k, v in sorted(reasons.items())) + " ELSE 'other' END"
    surs = in_list(src.codes("surs_retirement_yes"))
    retire_codes = [k for k, v in reasons.items() if v == "retirement"]
    con.execute(f"""CREATE OR REPLACE TEMP TABLE x_separation AS
        SELECT s.person_id, s.term_date, min(s.term_reason_code) AS term_reason_code, min(s.term_reason_desc) AS term_reason_desc,
               min({rcase}) AS reason_group,
               bool_or(coalesce(s.surs_retirement_ind IN {surs}, FALSE) OR s.term_reason_code IN {in_list(retire_codes)}) AS is_retirement,
               min(s.known_from) AS known_from, max(s.known_to) AS known_to, min(s.post_date) AS post_date
        FROM c_separation s WHERE s.term_date IS NOT NULL GROUP BY 1, 2""")
    con.execute(f"""CREATE OR REPLACE TEMP TABLE x_leave AS
        SELECT person_id, valid_from AS leave_from, valid_to AS leave_to, status_code AS leave_status_code,
               leave_reason_code, loa_from_date, loa_to_date, known_from, known_to, post_date
        FROM c_employment WHERE status_code IN {in_list(cfg.leave_status_codes)}""")
    src.report.update({
        "knowledge_date": str(src.knowledge_date),
        "rows": {t: con.execute(f"SELECT count(*) FROM {t}").fetchall()[0][0]
                 for t in ("x_appointment", "x_employment", "x_position", "x_separation", "x_leave", "x_class", "x_ladder", "x_org_path")},
        "deleted_appointment_rows": con.execute("SELECT count(*) FROM x_appointment WHERE is_deleted").fetchall()[0][0],
        "has_supervisor": res.has_field("appointment", "supervisor_person_id"),
        "has_role_family_reference": has_rf, "has_ladder": has_ladder,
    })


def _deleted_values(src: Source) -> list[str]:
    rt = src.m["concepts"]["appointment"].get("recorded_time") or {}
    return [str(v) for v in rt.get("deleted_values", ["D"])]


# ----------------------------------------------------------------------------- restricted reader
def register_restricted(src: Source) -> dict:
    """Register r_person (person_id, birth_date, <fairness fields>) straight from the physical person table.

    Column names come from the mapping only. Returns {"birth_date": bool, "fairness_fields": [...]}.
    Nothing from r_person is written by this module; features.py derives an age band and the fairness
    frame is written only to outputs/restricted/.
    """
    con, m = src.con, src.m
    c = m["concepts"]["person"]
    loc, storage = M.set_location(m, src.cfg.set_name)
    ref = M._source_ref(con, loc, storage, c["table"])
    cols = M._columns(con, ref)
    pid = c["fields"]["person_id"]["column"]
    sel = [f"CAST(s.{M._qi(pid)} AS VARCHAR) AS person_id"]
    sel.append(f"TRY_CAST(s.{M._qi(c['fields']['eff_date']['column'])} AS DATE) AS eff_date")
    bd = c["fields"].get("birth_date", {})
    has_bd = bool(bd) and bd["column"] in cols
    sel.append(f"TRY_CAST(s.{M._qi(bd['column'])} AS DATE) AS birth_date" if has_bd else "NULL::DATE AS birth_date")
    fair = []
    for fname, f in c["fields"].items():
        if f.get("role") == FAIRNESS_ROLE and f["column"] in cols:
            sel.append(f"CAST(s.{M._qi(f['column'])} AS VARCHAR) AS {M._qi(fname)}")
            fair.append(fname)
    con.execute(f"""CREATE OR REPLACE TEMP TABLE r_person AS
        SELECT * FROM (SELECT {', '.join(sel)}, row_number() OVER (PARTITION BY s.{M._qi(pid)} ORDER BY s.{M._qi(c['fields']['eff_date']['column'])} DESC) AS rn
                       FROM {ref} s) WHERE rn = 1""")
    return {"birth_date": has_bd, "fairness_fields": fair, "table": c["table"]}


# ----------------------------------------------------------------------------- helpers used by other modules
def position_pick(con, src_table: str, date_col: str, known_col: str, out_table: str, key_cols: list[str]) -> None:
    """For every row of src_table, attach the position version effective on date_col and known at known_col."""
    keys = ", ".join(f"t.{k}" for k in key_cols)
    con.execute(f"""CREATE OR REPLACE TEMP TABLE {out_table} AS
        SELECT * EXCLUDE (rn) FROM (
            SELECT {keys}, p.status_code AS posn_status_code, p.open_position_ind, p.range_min AS posn_range_min,
                   p.range_mid AS posn_range_mid, p.range_max AS posn_range_max, p.p_class_code AS posn_p_class_code,
                   p.job_class_code AS posn_job_class_code, p.ladder_code, p.ladder_level, p.ladder_level_source,
                   p.supervisor_position_id AS posn_supervisor_position_id, p.budget_fte, p.title AS posn_title,
                   p.desc_update_date AS posn_desc_update_date,
                   row_number() OVER (PARTITION BY {keys} ORDER BY p.valid_from DESC, p.known_from DESC) AS rn
            FROM {src_table} t JOIN x_position p
              ON p.position_id = t.position_id AND p.valid_from <= t.{date_col} AND p.valid_to >= t.{date_col}
             AND p.known_from <= t.{known_col} AND p.known_to > t.{known_col})
        WHERE rn = 1""")


def summary(src: Source) -> dict:
    return dict(src.report)


if __name__ == "__main__":  # pragma: no cover
    import json
    s = open_source(Config.from_env())
    print(json.dumps(summary(s), indent=1, default=str))
