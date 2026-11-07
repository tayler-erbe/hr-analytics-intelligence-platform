"""Tests for the v3 Data-Cookbook-shaped synthetic pack and integration/edw_mapping_cookbook.yaml.

    cd platform-evaluation && python -m unittest integration.tests.test_cookbook_v3 -v

Needs sample_datasets/v3_cookbook (build_v3.py) and v2_public_schema. The integration comparison also needs
the built public lake (skipped otherwise). Builds write only to temporary folders.
"""
from __future__ import annotations

import csv
import datetime as dt
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import duckdb
import yaml

from integration import mapping as M

PE = M.PE_ROOT
V2 = PE / "sample_datasets" / "v2_public_schema"
V3 = PE / "sample_datasets" / "v3_cookbook"
CB = PE / "integration" / "edw_cookbook_reference"
COOKBOOK_MAPPING = PE / "integration" / "edw_mapping_cookbook.yaml"
PUBLIC_MAPPING = PE / "integration" / "edw_mapping_public.yaml"
SETS = ("longitudinal", "CLEAN")
EXPECTED_COLUMNS = {"T_JOB_DETL_HIST": 79, "T_EMPEE_HIST": 71, "T_EMPEE_HIST_5": 27, "T_POSN_HIST": 52,
                    "T_PERS_HIST": 62, "T_PAYR_ACCTG_DETL": 47}
LAKE_OK = (PE / "data/lake/contract/sucss_class.parquet").exists() and (PE / "data/lake/silver/bls_oews_all.parquet").exists()
ENV_KEYS = ("HR_DATA_SOURCE", "HR_EDW_MAPPING", "HR_EDW_DATA", "HR_SAMPLE_PACK_PATH")


def load_builder():
    spec = importlib.util.spec_from_file_location("build_v3", V3 / "build_v3.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


B = load_builder()


def clean_env() -> dict:
    return {k: v for k, v in os.environ.items() if k not in ENV_KEYS}


def con_for(s: str):
    return duckdb.connect(str(V3 / s / "sample.duckdb"), read_only=True)


def tables_in(s: str) -> list[str]:
    return [t for t in EXPECTED_COLUMNS if (V3 / s / f"{t}.parquet").exists()]


def one(con, sql):
    return con.execute(sql).fetchone()[0]


def latest_jobs(alias="j") -> str:
    """Current-knowledge job rows: the latest non-deleted history version of each lineage."""
    return f"""(SELECT * FROM T_JOB_DETL_HIST x WHERE x.JOB_DETL_CUR_INFO_IND <> 'D' AND x.JOB_DETL_HIST_EFF_DT =
               (SELECT max(k.JOB_DETL_HIST_EFF_DT) FROM T_JOB_DETL_HIST k WHERE k.EDW_PERS_ID = x.EDW_PERS_ID
                AND k.POSN_NBR = x.POSN_NBR AND k.JOB_SUFFIX = x.JOB_SUFFIX AND k.JOB_DETL_EFF_DT = x.JOB_DETL_EFF_DT
                AND k.JOB_DETL_CUR_INFO_IND <> 'D')) {alias}"""


# ----------------------------------------------------------------------------- schema
class TestCookbookSchema(unittest.TestCase):
    def test_reference_column_counts(self):
        for t, n in EXPECTED_COLUMNS.items():
            self.assertEqual(len(B.cookbook_spec(t)), n, t)

    def test_oracle_type_mapping(self):
        self.assertEqual(B.oracle_to_duckdb("NUMBER(9,0)"), ("INTEGER", None))
        self.assertEqual(B.oracle_to_duckdb("NUMBER(15,0)"), ("BIGINT", None))
        self.assertEqual(B.oracle_to_duckdb("NUMBER(38,0)"), ("DECIMAL(38,0)", None))
        self.assertEqual(B.oracle_to_duckdb("NUMBER(6,3)"), ("DECIMAL(6,3)", None))
        self.assertEqual(B.oracle_to_duckdb("NUMBER"), ("DOUBLE", None))
        self.assertEqual(B.oracle_to_duckdb("VARCHAR2(30)"), ("VARCHAR", 30))
        self.assertEqual(B.oracle_to_duckdb("DATE"), ("DATE", None))

    def test_exact_columns_order_and_types_vs_tsv(self):
        for s in SETS:
            con = con_for(s)
            for t in tables_in(s):
                with open(CB / f"{t}.tsv", encoding="utf-8", newline="") as fh:
                    tsv = list(csv.DictReader(fh, delimiter="\t"))
                got = con.execute(f"DESCRIBE {t}").fetchall()
                self.assertEqual([g[0] for g in got], [r["column"] for r in tsv], f"{s}.{t} order")
                self.assertEqual(len(got), EXPECTED_COLUMNS[t], f"{s}.{t}")
                for g, r in zip(got, tsv):
                    self.assertEqual(g[1], B.oracle_to_duckdb(r["datatype"])[0], f"{s}.{t}.{g[0]}")
                # parquet keeps the same schema
                pq = [r[0] for r in con.execute(f"DESCRIBE SELECT * FROM read_parquet('{(V3 / s / (t + '.parquet')).as_posix()}')").fetchall()]
                self.assertEqual(pq, [r["column"] for r in tsv])
            con.close()
        self.assertIn("T_PAYR_ACCTG_DETL", tables_in("CLEAN"))

    def test_primary_keys_unique_and_not_null(self):
        for s in SETS:
            con = con_for(s)
            for t in tables_in(s):
                pk = [c["name"] for c in B.cookbook_spec(t) if c["pk"]]
                self.assertTrue(pk, t)
                n, d = con.execute(f"SELECT count(*), count(DISTINCT ({', '.join(pk)})) FROM {t}").fetchone()
                self.assertEqual(n, d, f"{s}.{t} PK {pk} not unique")
                nulls = one(con, f"SELECT count(*) FROM {t} WHERE " + " OR ".join(f"{c} IS NULL" for c in pk))
                self.assertEqual(nulls, 0, f"{s}.{t}")
            pk = [c["name"] for c in B.cookbook_spec("T_JOB_DETL_HIST") if c["pk"]]
            self.assertEqual(pk, ["EDW_PERS_ID", "POSN_NBR", "JOB_SUFFIX", "JOB_DETL_EFF_DT", "JOB_DETL_HIST_EFF_DT"])
            con.close()

    def test_varchar_lengths(self):
        for s in SETS:
            con = con_for(s)
            for t in tables_in(s):
                for c in B.cookbook_spec(t):
                    if c["max_length"]:
                        mx = one(con, f"SELECT coalesce(max(length({c['name']})), 0) FROM {t}")
                        self.assertLessEqual(mx, c["max_length"], f"{s}.{t}.{c['name']}")
            con.close()

    def test_id_formats(self):
        for s in SETS:
            con = con_for(s)
            lo = B.PERS_BASE[s]
            self.assertEqual(one(con, f"SELECT count(*) FROM T_PERS_HIST WHERE EDW_PERS_ID NOT BETWEEN {lo} AND {lo + 999999}"), 0)
            self.assertEqual(one(con, "SELECT count(*) FROM T_JOB_DETL_HIST WHERE NOT regexp_full_match(POSN_NBR, '[OQRV][0-9]{5}')"), 0)
            self.assertEqual(one(con, "SELECT count(*) FROM T_PERS_HIST WHERE NOT starts_with(CAST(EDW_PERS_ID AS VARCHAR), '99') OR length(CAST(EDW_PERS_ID AS VARCHAR)) <> 9"), 0)
            con.close()

    def test_schema_json_marks_value_status(self):
        for s in SETS:
            sch = json.loads((V3 / s / "schema.json").read_text(encoding="utf-8"))
            for t in tables_in(s):
                self.assertEqual(len(sch[t]), EXPECTED_COLUMNS[t])
                for c in sch[t]:
                    self.assertEqual(c["provenance"], "verified_dictionary")
                    self.assertTrue(c["value_status"])
            fte = [c for c in sch["T_JOB_DETL_HIST"] if c["name"] == "JOB_DETL_FTE"][0]
            self.assertIn("UNCONFIRMED", fte["note"])
            self.assertIn("synthetic", [c for c in sch["T_JOB_DETL_HIST"] if c["name"] == "JOB_DETL_CAMPUS_CD"][0]["value_status"])


# ----------------------------------------------------------------------------- job detail content
class TestJobDetail(unittest.TestCase):
    def test_current_indicator_and_data_status(self):
        for s in SETS:
            con = con_for(s)
            X = B.EXTRACT[s]
            pairs = set(con.execute("SELECT DISTINCT JOB_DETL_CUR_INFO_IND, JOB_DETL_DATA_STATUS_DESC FROM T_JOB_DETL_HIST").fetchall())
            self.assertLessEqual(pairs, {("Y", "Current"), ("N", "Expired"), ("N", "Future"), ("D", "Deleted")}, s)
            self.assertIn(("D", "Deleted"), pairs)
            n, d = con.execute("SELECT count(*), count(*) FILTER (WHERE JOB_DETL_CUR_INFO_IND = 'D') FROM T_JOB_DETL_HIST").fetchone()
            self.assertTrue(0 < d / n < 0.01, f"{s}: D share {d}/{n}")
            bad = one(con, f"""SELECT count(*) FROM T_JOB_DETL_HIST WHERE JOB_DETL_CUR_INFO_IND = 'Y'
                               AND NOT (JOB_DETL_EFF_DT <= DATE '{X}' AND JOB_DETL_EXP_DT >= DATE '{X}' AND JOB_DETL_DATA_EXP_DT >= DATE '{X}')""")
            self.assertEqual(bad, 0)
            self.assertEqual(one(con, "SELECT count(*) FROM T_JOB_DETL_HIST WHERE JOB_DETL_HIST_POST_DT < JOB_DETL_HIST_EFF_DT"), 0)
            self.assertEqual(one(con, "SELECT count(*) FROM T_JOB_DETL_HIST WHERE JOB_DETL_CUR_INFO_IND = 'D' AND JOB_DETL_HIST_POST_DT <= JOB_DETL_HIST_EFF_DT"), 0)
            self.assertEqual(one(con, "SELECT count(*) FROM T_JOB_DETL_HIST WHERE JOB_DETL_PAYR_CALC_IND <> CASE WHEN JOB_DETL_CUR_INFO_IND = 'Y' THEN 'Y' ELSE 'N' END"), 0)
            # at most one Y row per job; open-ended current rows use 9999-12-31
            self.assertEqual(one(con, "SELECT count(*) FROM (SELECT 1 FROM T_JOB_DETL_HIST WHERE JOB_DETL_CUR_INFO_IND = 'Y' GROUP BY EDW_PERS_ID, POSN_NBR, JOB_SUFFIX HAVING count(*) > 1)"), 0)
            con.close()

    def test_group_code_and_civil_service(self):
        for s in SETS:
            con = con_for(s)
            self.assertEqual(one(con, "SELECT count(*) FROM T_JOB_DETL_HIST WHERE JOB_DETL_EMPEE_GROUP_CD <> left(JOB_DETL_EMPEE_CLS_CD, 1)"), 0)
            self.assertEqual(one(con, """SELECT count(*) FROM T_JOB_DETL_HIST WHERE JOB_DETL_CIV_SVC_IND <>
                                 CASE WHEN left(JOB_DETL_EMPEE_CLS_CD, 1) IN ('C', 'D') THEN 'Y' ELSE 'N' END"""), 0)
            con.close()

    def test_pay_identities(self):
        for s in SETS:
            con = con_for(s)
            self.assertEqual(one(con, """SELECT count(*) FROM T_JOB_DETL_HIST WHERE
                abs(JOB_DETL_PAY_PERD_SAL * JOB_DETL_ANNL_PAY_COUNT - JOB_DETL_ANNL_SAL) > 0.005 * JOB_DETL_ANNL_PAY_COUNT + 0.001"""), 0)
            self.assertEqual(one(con, """SELECT count(*) FROM T_JOB_DETL_HIST WHERE JOB_DETL_PAY_HOURS > 0
                AND abs(JOB_DETL_REGULAR_RT * JOB_DETL_PAY_HOURS - JOB_DETL_PAY_PERD_SAL) > 0.01 + JOB_DETL_PAY_HOURS * 0.000001"""), 0)
            self.assertEqual(one(con, "SELECT count(*) FROM T_JOB_DETL_HIST WHERE JOB_DETL_PAYS_YR <> JOB_DETL_ANNL_PAY_COUNT"), 0)
            # FTE stored as a fraction; actual FTE = FTE * appt pct / 100 (APPT_PCT 100 everywhere)
            self.assertEqual(one(con, "SELECT count(*) FROM T_JOB_DETL_HIST WHERE JOB_DETL_FTE > 1 OR JOB_DETL_APPT_PCT <> 100"), 0)
            con.close()

    def test_supervisor_foreign_keys(self):
        n_sup = 0
        for s in SETS:
            con = con_for(s)
            n_sup += one(con, "SELECT count(SUPV_POSN_NBR) FROM T_JOB_DETL_HIST")
            self.assertEqual(one(con, """SELECT count(*) FROM T_JOB_DETL_HIST j WHERE j.SUPV_POSN_NBR IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM T_JOB_DETL_HIST k WHERE k.EDW_PERS_ID = j.SUPV_EDW_PERS_ID AND k.POSN_NBR = j.SUPV_POSN_NBR
                AND k.JOB_SUFFIX = j.SUPV_JOB_SUFFIX)"""), 0)
            self.assertEqual(one(con, "SELECT count(*) FROM T_JOB_DETL_HIST WHERE (SUPV_EDW_PERS_ID IS NULL) <> (SUPV_POSN_NBR IS NULL)"), 0)
            self.assertEqual(one(con, "SELECT count(*) FROM T_JOB_DETL_HIST WHERE SUPV_EDW_PERS_ID IS NOT NULL AND SUPV_EDW_PERS_ID NOT IN (SELECT EDW_PERS_ID FROM T_PERS_HIST)"), 0)
            con.close()
        self.assertGreater(n_sup, 1000)

    def test_org_columns_follow_tree_and_campus_assignment(self):
        for s in SETS:
            con = con_for(s)
            self.assertEqual(one(con, """SELECT count(*) FROM T_JOB_DETL_HIST j JOIN REF_ORG o ON o.ORG_CD = j.ORG_CD
                WHERE o.COA_CD <> j.COA_CD OR j.JOB_DETL_CAMPUS_CD <> j.COA_CD
                   OR (o.ORG_HIER_LEVEL_NBR = 5 AND (j.JOB_DETL_DEPT_CD <> j.ORG_CD OR j.JOB_DETL_COLL_CD <> (SELECT PARENT_ORG_CD FROM REF_ORG p WHERE p.ORG_CD = j.ORG_CD)))
                   OR (o.ORG_HIER_LEVEL_NBR = 3 AND (j.JOB_DETL_COLL_CD <> j.ORG_CD OR j.JOB_DETL_DEPT_CD IS NOT NULL))"""), 0)
            self.assertEqual(one(con, "SELECT count(*) FROM T_JOB_DETL_HIST WHERE ORG_CD NOT IN (SELECT ORG_CD FROM REF_ORG)"), 0)
            # campus follows bridges.yaml: Campus 1 -> UIUC role (COA 1), 2 -> UIC (2), 3 -> UIS (4), U00 -> System (9)
            got = set(con.execute("SELECT DISTINCT substr(ORG_CD, 1, 2), COA_CD FROM T_JOB_DETL_HIST").fetchall())
            self.assertLessEqual(got, {("U0", "9"), ("U1", "1"), ("U2", "2"), ("U3", "4")})
            con.close()

    def test_cookbook_listed_values(self):
        for s in SETS:
            con = con_for(s)
            for col, allowed in (("TIME_ENTRY_METHOD_CD", B.TIME_ENTRY), ("JOB_DETL_LEAVE_RPT_METHOD_CD", B.LEAVE_RPT),
                                 ("JOB_DETL_WORK_LOCN_CD", B.WORK_LOCN), ("JOB_DETL_EEO_SKILL_CD", B.EEO_SKILL)):
                vals = {r[0] for r in con.execute(f"SELECT DISTINCT {col} FROM T_JOB_DETL_HIST WHERE {col} IS NOT NULL").fetchall()}
                self.assertLessEqual(vals, set(allowed), f"{s}.{col}")
            self.assertLessEqual({r[0] for r in con.execute("SELECT DISTINCT JOB_DETL_TIME_ENTRY_TYPE_DESC FROM T_JOB_DETL_HIST").fetchall()},
                                 {"TimeSheet", "Exception Time Only", "None"})
            ecls = set(B.eclass_domain())
            self.assertLessEqual({r[0] for r in con.execute("SELECT DISTINCT JOB_DETL_EMPEE_CLS_CD FROM T_JOB_DETL_HIST").fetchall()}, ecls)
            con.close()

    def test_change_reasons(self):
        for s in SETS:
            con = con_for(s)
            codes = {r[0] for r in con.execute("SELECT DISTINCT JOB_DETL_CHG_REASON_CD FROM T_JOB_DETL_HIST WHERE JOB_DETL_CHG_REASON_CD IS NOT NULL").fetchall()}
            self.assertLessEqual(codes, set(B.CHG), s)
            # every person's first job row is a hire; every Active -> Terminated job row has an end/separation reason
            self.assertEqual(one(con, f"""SELECT count(*) FROM {latest_jobs()} WHERE (j.EDW_PERS_ID, j.JOB_DETL_EFF_DT) IN
                (SELECT EDW_PERS_ID, min(JOB_DETL_EFF_DT) FROM T_JOB_DETL_HIST WHERE JOB_DETL_CUR_INFO_IND <> 'D' GROUP BY 1)
                AND j.JOB_DETL_CHG_REASON_CD NOT IN ('HR001', 'HR002', 'JB001')"""), 0)
            self.assertEqual(one(con, f"""WITH c AS (SELECT j.*, lag(JOB_DETL_STATUS_DESC) OVER (PARTITION BY EDW_PERS_ID, POSN_NBR, JOB_SUFFIX ORDER BY JOB_DETL_EFF_DT) AS p
                FROM {latest_jobs()}) SELECT count(*) FROM c WHERE p = 'Active' AND JOB_DETL_STATUS_DESC = 'Terminated'
                AND JOB_DETL_CHG_REASON_CD NOT IN ('EJ001', 'EJ002', 'SP003')"""), 0)
            # promotion codes only where the job progression level rises within the same ladder
            self.assertEqual(one(con, f"""WITH c AS (SELECT j.*, x.POSN_JOB_PRGS_CD AS g, x.JOB_PRGS_LEVEL_NBR AS lv FROM {latest_jobs()}
                                         JOIN REF_PCLS_SUCSS_XWALK x ON x.JOB_DETL_POSN_CLS_CD = j.JOB_DETL_POSN_CLS_CD)
                SELECT count(*) FROM c WHERE JOB_DETL_CHG_REASON_CD IN ('OT010', 'FA002', 'PR001', 'RC001') AND NOT EXISTS (
                  SELECT 1 FROM c p WHERE p.EDW_PERS_ID = c.EDW_PERS_ID AND p.g = c.g AND p.lv < c.lv AND p.JOB_DETL_EFF_DT < c.JOB_DETL_EFF_DT)"""), 0)
            self.assertGreater(one(con, "SELECT count(*) FROM T_JOB_DETL_HIST WHERE JOB_DETL_CHG_REASON_CD IN ('OT010', 'FA002', 'PR001')"), 0)
            con.close()

    def test_late_keyed_history_preserved(self):
        con = con_for("longitudinal")
        late = one(con, "SELECT count(*) FROM T_JOB_DETL_HIST WHERE JOB_DETL_HIST_EFF_DT > JOB_DETL_EFF_DT")
        multi = one(con, "SELECT count(*) FROM (SELECT 1 FROM T_JOB_DETL_HIST GROUP BY EDW_PERS_ID, POSN_NBR, JOB_SUFFIX, JOB_DETL_EFF_DT HAVING count(*) > 1)")
        self.assertGreater(late, 30000)
        self.assertGreater(multi, 10000)
        con.close()


# ----------------------------------------------------------------------------- other verified tables
class TestEmployeePersonPosition(unittest.TestCase):
    def test_employee_status_leave_and_termination(self):
        for s in SETS:
            con = con_for(s)
            self.assertLessEqual({r[0] for r in con.execute("SELECT DISTINCT EMPEE_STATUS_CD FROM T_EMPEE_HIST").fetchall()}, {"A", "B", "F", "T"})
            self.assertGreater(one(con, "SELECT count(*) FROM T_EMPEE_HIST WHERE EMPEE_STATUS_CD IN ('B', 'F')"), 0)
            self.assertEqual(one(con, """SELECT count(*) FROM T_EMPEE_HIST WHERE (EMPEE_STATUS_CD IN ('B', 'F')) <>
                (EMPEE_LOA_FROM_DT IS NOT NULL AND EMPEE_LEAVE_REASON_CD IS NOT NULL)"""), 0)
            self.assertEqual(one(con, """SELECT count(*) FROM T_EMPEE_HIST WHERE EMPEE_STATUS_CD IN ('B', 'F')
                AND (EMPEE_LOA_FROM_DT <> EMPEE_EFF_DT OR EMPEE_LOA_TO_DT <> EMPEE_EXP_DT)"""), 0)
            self.assertEqual(one(con, "SELECT count(*) FROM T_EMPEE_HIST WHERE (EMPEE_STATUS_CD = 'T') <> (ACTIVE_EMPEE_IND = 'N')"), 0)
            self.assertEqual(one(con, """SELECT count(*) FROM T_EMPEE_HIST WHERE EMPEE_RET_IND <>
                CASE WHEN TERMN_REASON_CD IN ('TR', 'TF') OR EMPEE_CLS_CD = 'TR' THEN 'Y' ELSE 'N' END"""), 0)
            self.assertEqual(one(con, "SELECT count(*) FROM T_EMPEE_HIST WHERE (TERMN_REASON_CD IS NULL) <> (EMPEE_TERMN_DT IS NULL)"), 0)
            pairs = set(con.execute("SELECT DISTINCT EMPEE_CUR_INFO_IND, EMPEE_DATA_STATUS_DESC FROM T_EMPEE_HIST").fetchall())
            self.assertLessEqual(pairs, {("Y", "Current"), ("N", "Expired"), ("N", "Future"), ("D", "Deleted")})
            self.assertIn(("D", "Deleted"), pairs)
            con.close()

    def test_employee_rollups_match_jobs(self):
        for s in SETS:
            con = con_for(s)
            X = B.EXTRACT[s]
            bad = one(con, f"""WITH e AS (SELECT *, CASE WHEN EMPEE_EFF_DT > DATE '{X}' THEN EMPEE_EFF_DT ELSE least(EMPEE_EXP_DT, DATE '{X}') END AS r FROM T_EMPEE_HIST),
                s AS (SELECT e.EDW_PERS_ID, e.EMPEE_EFF_DT, e.EMPEE_CUR_INFO_IND, coalesce(sum(j.JOB_DETL_FTE), 0) AS fte,
                             coalesce(sum(j.JOB_DETL_ANNL_SAL * j.JOB_DETL_APPT_PCT / 100), 0) AS sal
                      FROM e LEFT JOIN {latest_jobs()} ON j.EDW_PERS_ID = e.EDW_PERS_ID AND j.JOB_DETL_STATUS_DESC = 'Active'
                       AND j.JOB_DETL_EFF_DT <= e.r AND j.JOB_DETL_EXP_DT >= e.r AND j.JOB_SUFFIX <> 'CE' GROUP BY ALL)
                SELECT count(*) FROM T_EMPEE_HIST t JOIN s USING (EDW_PERS_ID, EMPEE_EFF_DT, EMPEE_CUR_INFO_IND)
                WHERE abs(t.EMPEE_FTE - s.fte) > 0.0005 OR abs(t.EMPEE_ANNL_SAL - s.sal) > 0.01""")
            self.assertEqual(bad, 0, s)
            con.close()

    def test_service_dates_consistent_with_jobs(self):
        for s in SETS:
            con = con_for(s)
            self.assertEqual(one(con, """SELECT count(*) FROM T_EMPEE_HIST e JOIN (SELECT EDW_PERS_ID, min(JOB_DETL_EFF_DT) AS f
                FROM T_JOB_DETL_HIST WHERE JOB_DETL_CUR_INFO_IND <> 'D' GROUP BY 1) j USING (EDW_PERS_ID)
                WHERE e.FIRST_WORK_DT <> j.f OR e.FIRST_HIRE_DT > e.FIRST_WORK_DT OR e.CUR_HIRE_DT < e.FIRST_HIRE_DT
                   OR e.UNIV_SNRTY_DT <> e.FIRST_HIRE_DT OR e.ADJ_SVC_DT < e.FIRST_HIRE_DT"""), 0)
            self.assertEqual(one(con, "SELECT count(*) FROM T_EMPEE_HIST WHERE LAST_WORK_DT > EMPEE_TERMN_DT OR (LAST_WORK_DT IS NOT NULL) <> (EMPEE_STATUS_CD = 'T')"), 0)
            con.close()

    def test_empee5_equals_empee_termination(self):
        for s in SETS:
            con = con_for(s)
            n5 = one(con, "SELECT count(*) FROM T_EMPEE_HIST_5")
            self.assertEqual(n5, one(con, "SELECT count(*) FROM T_EMPEE_HIST WHERE TERMN_REASON_CD IS NOT NULL"))
            self.assertEqual(one(con, """SELECT count(*) FROM T_EMPEE_HIST_5 f LEFT JOIN T_EMPEE_HIST e USING (EDW_PERS_ID, EMPEE_EFF_DT)
                WHERE e.TERMN_REASON_CD IS DISTINCT FROM f.TERMN_REASON_CD OR e.TERMN_REASON_DESC IS DISTINCT FROM f.TERMN_REASON_DESC
                   OR e.EMPEE_TERMN_DT IS DISTINCT FROM f.EMPEE_TERMN_DT OR e.EMPEE_CUR_INFO_IND IS DISTINCT FROM f.EMPEE_CUR_INFO_IND"""), 0)
            # ancestor path follows the org tree
            self.assertEqual(one(con, """SELECT count(*) FROM T_EMPEE_HIST_5 f JOIN T_EMPEE_HIST e USING (EDW_PERS_ID, EMPEE_EFF_DT)
                JOIN REF_ORG o ON o.ORG_CD = e.ORG_CD WHERE (o.ORG_HIER_LEVEL_NBR = 5 AND f.DEPT_LEVEL_5_CD <> o.ORG_CD)
                OR (f.COLL_LEVEL_3_CD IS NOT NULL AND (SELECT PARENT_ORG_CD FROM REF_ORG a WHERE a.ORG_CD = f.COLL_LEVEL_3_CD) <> f.ADMIN_LEVEL_2_CD)
                OR (SELECT PARENT_ORG_CD FROM REF_ORG a WHERE a.ORG_CD = f.ADMIN_LEVEL_2_CD) <> f.CAMPUS_LEVEL_1_CD"""), 0)
            con.close()

    def test_prohibited_columns_null(self):
        for s in SETS:
            con = con_for(s)
            for t, cols in B.PROHIBITED_NULL.items():
                if t not in tables_in(s):
                    continue
                for c in cols:
                    self.assertEqual(one(con, f"SELECT count({c}) FROM {t}"), 0, f"{s}.{t}.{c}")
            con.close()

    def test_race_hierarchy_and_age(self):
        for s in SETS:
            con = con_for(s)
            n = " + ".join(f"CASE WHEN {c} = 'Y' THEN 1 ELSE 0 END" for c in B.RACE_IND.values())
            single = " ".join(f"WHEN {c} = 'Y' THEN '{k}'" for k, c in B.RACE_IND.items())
            self.assertEqual(one(con, f"""SELECT count(*) FROM T_PERS_HIST WHERE RACE_ETH_RPT_CD <> CASE
                WHEN PERS_CITZN_TYPE_CD IN ('AS', 'NR', 'RA') THEN '9' WHEN PERS_CITZN_TYPE_CD = 'UC' THEN 'U'
                WHEN HISPANIC_ETH_IND = 'Y' THEN 'H' WHEN ({n}) > 1 THEN 'M' {single} ELSE 'U' END"""), 0)
            self.assertEqual(one(con, f"SELECT count(*) FROM T_PERS_HIST WHERE MULT_RACE_IND <> CASE WHEN ({n}) > 1 THEN 'Y' ELSE 'N' END"), 0)
            self.assertEqual(one(con, """SELECT count(*) FROM T_PERS_HIST WHERE (RACE_ETH_RPT_CD = '9') <> (PERS_CITZN_TYPE_GROUP = 'International')"""), 0)
            self.assertEqual({r[0] for r in con.execute("SELECT DISTINCT RACE_ETH_RPT_CD FROM T_PERS_HIST").fetchall()},
                             {"U", "9", "H", "M", "1", "2", "3", "4", "5"})
            self.assertEqual(one(con, "SELECT count(*) FROM T_PERS_HIST WHERE (AGE IS NOT NULL) <> (PERS_CUR_INFO_IND = 'Y')"), 0)
            y = one(con, "SELECT count(*) FILTER (WHERE PERS_CONFIDENTIALITY_IND = 'Y') / count(*) FROM T_PERS_HIST")
            self.assertTrue(0 < y < 0.03)
            con.close()

    def test_positions(self):
        for s in SETS:
            con = con_for(s)
            X = B.EXTRACT[s]
            self.assertEqual(one(con, "SELECT count(*) FROM T_POSN_HIST WHERE POSN_STATUS_DESC <> CASE POSN_STATUS_CD WHEN 'A' THEN 'Active' WHEN 'C' THEN 'Cancelled' WHEN 'F' THEN 'Frozen' WHEN 'I' THEN 'Inactive' END"), 0)
            self.assertGreater(one(con, "SELECT count(*) FROM T_POSN_HIST WHERE POSN_STATUS_CD = 'F'"), 0)
            self.assertGreater(one(con, "SELECT count(*) FROM T_POSN_HIST WHERE POSN_STATUS_CD = 'C'"), 0)
            filled = f"""SELECT count(*) FROM {latest_jobs()} WHERE j.POSN_NBR = p.POSN_NBR AND j.JOB_DETL_STATUS_DESC = 'Active'
                         AND j.JOB_DETL_EFF_DT <= p.r AND j.JOB_DETL_EXP_DT >= p.r"""
            self.assertEqual(one(con, f"""WITH p AS (SELECT *, CASE WHEN POSN_HIST_EFF_DT > DATE '{X}' THEN POSN_HIST_EFF_DT ELSE least(POSN_HIST_EXP_DT, DATE '{X}') END AS r FROM T_POSN_HIST)
                SELECT count(*) FROM p WHERE OPEN_POSN_IND <> CASE WHEN ({filled}) = 0 THEN 'Y' ELSE 'N' END"""), 0)
            self.assertEqual(one(con, f"""WITH p AS (SELECT *, DATE '{X}' AS r FROM T_POSN_HIST WHERE POSN_STATUS_CD IN ('F', 'C') AND POSN_HIST_CUR_INFO_IND = 'Y')
                SELECT count(*) FROM p WHERE ({filled}) > 0"""), 0)
            # PAPE_CIV_SVC_ID resolves to a SUCSS class for civil-service positions; AP gets 49901-49920
            self.assertEqual(one(con, """SELECT count(*) FROM T_POSN_HIST p JOIN REF_PCLS_SUCSS_XWALK x ON x.JOB_DETL_POSN_CLS_CD = p.POSN_CLS_CD
                WHERE x.CLS_SOURCE = 'SUCSS' AND (p.PAPE_CIV_SVC_ID IS DISTINCT FROM x.SUCSS_CLS_CD
                      OR p.PAPE_CIV_SVC_ID NOT IN (SELECT POSN_CLS_CD FROM T_POSN_CLS_HIST WHERE CLS_SOURCE = 'SUCSS'))"""), 0)
            self.assertEqual(one(con, """SELECT count(*) FROM T_POSN_HIST WHERE PAPE_CIV_SVC_ID IS NOT NULL AND NOT regexp_full_match(PAPE_CIV_SVC_ID, '[0-9]{4}')
                AND CAST(PAPE_CIV_SVC_ID AS INTEGER) NOT BETWEEN 49901 AND 49920"""), 0)
            self.assertEqual(one(con, "SELECT count(*) FROM T_POSN_HIST WHERE NOT (POSN_MIN_SAL <= POSN_MIDPT_SAL AND POSN_MIDPT_SAL <= POSN_MAX_SAL)"), 0)
            self.assertEqual(one(con, "SELECT count(*) FROM T_POSN_HIST WHERE POSN_APPT_PCT > 1"), 0)
            self.assertEqual(one(con, """SELECT count(*) FROM T_POSN_HIST p WHERE SUPV_POSN_NBR IS NOT NULL AND SUPV_POSN_NBR NOT IN
                (SELECT SUPV_POSN_NBR FROM T_JOB_DETL_HIST j WHERE j.POSN_NBR = p.POSN_NBR AND SUPV_POSN_NBR IS NOT NULL)"""), 0)
            stale = one(con, f"SELECT count(*) FILTER (WHERE POSN_DESC_UPDATE_DT < DATE '{X}' - INTERVAL 5 YEAR) / count(*) FROM T_POSN_HIST")
            self.assertTrue(0.05 < stale < 0.8, stale)
            con.close()


# ----------------------------------------------------------------------------- payroll
class TestPayroll(unittest.TestCase):
    def test_payroll_reconciles_and_has_no_deductions(self):
        con = con_for("CLEAN")
        bad = one(con, f"""WITH n AS (SELECT EDW_PERS_ID, POSN_NBR, JOB_SUFFIX, PAYR_ID, PAYR_YR, PAYR_NBR, any_value(PAYR_ACCTG_EFF_DT) AS pend,
                                   sum(PAYR_ACCTG_EXPS_AMT) AS net FROM T_PAYR_ACCTG_DETL WHERE PAYR_ACCTG_EXPS_AMT IS NOT NULL GROUP BY ALL)
            SELECT count(*) FROM n JOIN {latest_jobs()} ON j.EDW_PERS_ID = n.EDW_PERS_ID AND j.POSN_NBR = n.POSN_NBR AND j.JOB_SUFFIX = n.JOB_SUFFIX
              AND j.JOB_DETL_EFF_DT <= n.pend AND j.JOB_DETL_EXP_DT >= n.pend
            WHERE abs(n.net - j.JOB_DETL_ANNL_SAL / j.JOB_DETL_ANNL_PAY_COUNT) > 0.01 OR j.JOB_DETL_PAYR_ID <> n.PAYR_ID""")
        self.assertEqual(bad, 0)
        unmatched = one(con, f"""SELECT count(*) FROM T_PAYR_ACCTG_DETL p WHERE NOT EXISTS (SELECT 1 FROM {latest_jobs()}
            WHERE j.EDW_PERS_ID = p.EDW_PERS_ID AND j.POSN_NBR = p.POSN_NBR AND j.JOB_SUFFIX = p.JOB_SUFFIX
              AND j.JOB_DETL_EFF_DT <= p.PAYR_ACCTG_EFF_DT AND j.JOB_DETL_EXP_DT >= p.PAYR_ACCTG_EFF_DT AND j.ORG_CD = p.ORG_CD)""")
        self.assertEqual(unmatched, 0)
        ev = dict(con.execute("SELECT PAYR_EVENT_TYPE_CD, count(*) FROM T_PAYR_ACCTG_DETL GROUP BY 1").fetchall())
        self.assertTrue(ev.get("V") and ev.get("J") and ev.get("I"))
        self.assertEqual(one(con, "SELECT round(sum(PAYR_ACCTG_ENC_AMT), 2) FROM T_PAYR_ACCTG_DETL"), 0)
        self.assertEqual(one(con, "SELECT count(*) FROM T_PAYR_ACCTG_DETL WHERE GRANT_CD IS NOT NULL AND NOT regexp_full_match(GRANT_CD, 'SYNG[0-9]{5}')"), 0)
        self.assertEqual(one(con, "SELECT count(*) FROM T_PAYR_ACCTG_DETL WHERE (GRANT_CD IS NOT NULL) <> (PAYR_ACCTG_FUNDING_SRC_DESC = 'Grant')"), 0)
        self.assertEqual(one(con, "SELECT count(*) FROM T_PAYR_ACCTG_DETL WHERE FY_CD <> CAST(year(PAYR_ACCTG_EFF_DT) + CASE WHEN month(PAYR_ACCTG_EFF_DT) >= 7 THEN 1 ELSE 0 END AS VARCHAR)"), 0)
        self.assertEqual(one(con, "SELECT count(DISTINCT EDW_VPD_NBR) FROM T_PAYR_ACCTG_DETL"), 1)
        con.close()


# ----------------------------------------------------------------------------- v2 relationships
class TestV2Relationships(unittest.TestCase):
    def test_row_counts_and_keys_match_v2(self):
        for s in SETS:
            man = json.loads((V3 / s / "manifest.json").read_text(encoding="utf-8"))
            t = man["tables"]
            notes = man["notes"]
            self.assertEqual(t["T_JOB_DETL_HIST"]["rows"], t["T_JOB_DETL_HIST"]["v2_rows"] + notes["job_rows_deleted_planted"]
                             + notes["job_rows_reappointment_close_versions_added"])
            self.assertEqual(t["T_EMPEE_HIST"]["rows"], t["T_EMPEE_HIST"]["v2_rows"] - notes["empee_superseded_versions_dropped"]
                             + 2 * notes["leave_of_absence_people"] + notes["empee_rows_deleted_planted"])
            self.assertEqual(t["T_EMPEE_HIST_5"]["rows"], t["T_EMPEE_HIST_5"]["v2_rows"])
            for name in ("T_PERS_HIST", "T_POSN_HIST", "T_POSN_CLS_HIST", "REF_ECLS_PUBLIC"):
                self.assertEqual(t[name]["rows"], t[name]["v2_rows"], f"{s}.{name}")
            self.assertEqual(t["REF_ORG"]["rows"], t["REF_ORG"]["v2_rows"] + 6)

    def test_non_deleted_job_rows_map_one_to_one_onto_v2(self):
        with open(V3 / "crosswalk_v2_to_v3.csv", encoding="utf-8", newline="") as fh:
            xw = list(csv.DictReader(fh))
        for s in SETS:
            con = duckdb.connect()
            con.execute(f"ATTACH '{(V3 / s / 'sample.duckdb').as_posix()}' AS v3 (READ_ONLY)")
            rows = [(r["v2_value"], r["v3_value"], r["v3_column"]) for r in xw if r["set"] == s and r["change"] == "id_mapped"]
            con.execute("CREATE TABLE idm (v2 VARCHAR, v3 VARCHAR, col VARCHAR)")
            con.executemany("INSERT INTO idm VALUES (?, ?, ?)", rows)
            self.assertEqual(one(con, "SELECT count(*) - count(DISTINCT (col, v3)) FROM idm"), 0)
            self.assertEqual(one(con, "SELECT count(*) - count(DISTINCT (col, v2)) FROM idm"), 0)
            rec = "ROW_REC_START_DT" if s == "longitudinal" else f"least(JOB_DETL_EFF_DT, DATE '{B.EXTRACT[s]}')"
            con.execute(f"""CREATE TABLE a AS SELECT EDW_PERS_ID, POSN_NBR, JOB_SUFFIX, JOB_DETL_EFF_DT, {rec} AS h, JOB_DETL_FTE AS fte,
                            JOB_DETL_ANNUAL_SAL AS sal, JOB_ORG_CD AS org FROM read_parquet('{(V2 / s / 'T_JOB_DETL_HIST.parquet').as_posix()}')""")
            con.execute("""CREATE TABLE b AS SELECT p.v2 AS EDW_PERS_ID, q.v2 AS POSN_NBR, JOB_SUFFIX, JOB_DETL_EFF_DT, JOB_DETL_HIST_EFF_DT AS h,
                            JOB_DETL_FTE AS fte, JOB_DETL_ANNL_SAL AS sal, ORG_CD AS org FROM v3.T_JOB_DETL_HIST j
                            JOIN idm p ON p.col = 'EDW_PERS_ID' AND p.v3 = CAST(j.EDW_PERS_ID AS VARCHAR)
                            JOIN idm q ON q.col = 'POSN_NBR' AND q.v3 = j.POSN_NBR WHERE JOB_DETL_CUR_INFO_IND <> 'D'
                            AND NOT (JOB_DETL_STATUS_DESC = 'Terminated' AND JOB_DETL_EXP_DT < DATE '9999-12-31' AND EXISTS (
                                SELECT 1 FROM v3.T_JOB_DETL_HIST k WHERE k.EDW_PERS_ID = j.EDW_PERS_ID AND k.POSN_NBR = j.POSN_NBR
                                  AND k.JOB_SUFFIX = j.JOB_SUFFIX AND k.JOB_DETL_EFF_DT = j.JOB_DETL_EFF_DT
                                  AND k.JOB_DETL_HIST_EFF_DT < j.JOB_DETL_HIST_EFF_DT AND k.JOB_DETL_EXP_DT >= DATE '9999-12-31'))""")
            # (the versions build_v3 adds to close a re-appointed job's open Terminated row have no v2 counterpart)
            self.assertEqual(one(con, "SELECT count(*) FROM (SELECT * FROM a EXCEPT ALL SELECT * FROM b)"), 0, s)
            self.assertEqual(one(con, "SELECT count(*) FROM (SELECT * FROM b EXCEPT ALL SELECT * FROM a)"), 0, s)
            self.assertEqual(one(con, """WITH cur AS (SELECT EDW_PERS_ID, POSN_NBR, JOB_SUFFIX, JOB_DETL_EFF_DT, JOB_DETL_EXP_DT FROM v3.T_JOB_DETL_HIST
                    WHERE JOB_DETL_CUR_INFO_IND <> 'D' QUALIFY row_number() OVER (PARTITION BY EDW_PERS_ID, POSN_NBR, JOB_SUFFIX, JOB_DETL_EFF_DT
                    ORDER BY JOB_DETL_HIST_EFF_DT DESC) = 1)
                SELECT count(*) FROM (SELECT *, lead(JOB_DETL_EFF_DT) OVER (PARTITION BY EDW_PERS_ID, POSN_NBR, JOB_SUFFIX ORDER BY JOB_DETL_EFF_DT) AS nxt FROM cur)
                WHERE nxt IS NOT NULL AND JOB_DETL_EXP_DT >= nxt"""), 0, s)   # current knowledge: no row overlaps the next row of its job (re-appointments closed)
            v3 = "v3."
            self.assertEqual(one(con, f"SELECT count(*) FROM {v3}T_JOB_DETL_HIST WHERE EDW_PERS_ID NOT IN (SELECT EDW_PERS_ID FROM {v3}T_PERS_HIST)"), 0)
            self.assertEqual(one(con, f"SELECT count(*) FROM {v3}T_JOB_DETL_HIST WHERE POSN_NBR NOT IN (SELECT POSN_NBR FROM {v3}T_POSN_HIST)"), 0)
            self.assertEqual(one(con, f"SELECT count(*) FROM {v3}T_EMPEE_HIST WHERE EDW_PERS_ID NOT IN (SELECT EDW_PERS_ID FROM {v3}T_PERS_HIST)"), 0)
            self.assertEqual(one(con, f"SELECT count(*) FROM {v3}T_POSN_HIST WHERE PAPE_CIV_SVC_ID IS NULL AND POSN_CLS_CD IN (SELECT JOB_DETL_POSN_CLS_CD FROM {v3}REF_PCLS_SUCSS_XWALK WHERE CLS_SOURCE = 'SUCSS')"), 0)
            con.close()

    def test_rebuild_is_deterministic(self):
        r = subprocess.run([sys.executable, str(V3 / "build_v3.py"), "--check"], capture_output=True, text=True, cwd=str(PE), timeout=600)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("content identical", r.stdout)


# ----------------------------------------------------------------------------- mapping
class TestCookbookMapping(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = M.load_mapping(COOKBOOK_MAPPING)

    def test_same_core_concepts_and_fields_as_v1_mapping(self):
        base = M.load_mapping(M.DEFAULT_MAPPING)
        for c, spec in base["concepts"].items():
            self.assertIn(c, self.m["concepts"])
            want = set(spec["fields"])
            if self.m["concepts"][c].get("recorded_time"):      # recorded interval replaced by a Cookbook mode
                want -= {"recorded_end"} if self.m["concepts"][c]["recorded_time"]["mode"] == "lineage_next" else {"recorded_start", "recorded_end"}
            self.assertLessEqual(want, set(self.m["concepts"][c]["fields"]), c)
        new = {"change_reason_code", "change_reason_desc", "status_desc", "campus_code", "college_code", "department_code",
               "admin_level_2_code", "supervisor_position_id", "supervisor_job_suffix", "p_class_code", "employee_class_code",
               "employee_group_code", "appointment_pct", "current_info_ind", "recorded_start", "post_date", "data_status"}
        self.assertLessEqual(new, set(self.m["concepts"]["appointment"]["fields"]))

    def test_verified_fields_point_at_cookbook_columns(self):
        specs = {t: {c["name"] for c in B.cookbook_spec(t)} for t in EXPECTED_COLUMNS}
        n = 0
        for cname, c in self.m["concepts"].items():
            for fname, f in c["fields"].items():
                if c["table"] in specs:
                    if f["provenance"] == "verified_dictionary":
                        self.assertIn(f["column"], specs[c["table"]], f"{cname}.{fname}")
                        self.assertEqual(f.get("cookbook"), f"{c['table']}.{f['column']}", f"{cname}.{fname}")
                        n += 1
                    else:
                        self.assertTrue(f.get("value_note"), f"{cname}.{fname} unverified without a note")
                else:
                    self.assertEqual(f["provenance"], "assumed_synthetic_layout", f"{cname}.{fname}")
                    self.assertIn("public_provenance", f, f"{cname}.{fname}")
        self.assertGreater(n, 100)
        for f in ("eff_date", "exp_date", "fte", "annual_salary", "org_code", "status_code", "employee_class_code"):
            self.assertEqual(self.m["concepts"]["appointment"]["fields"][f]["provenance"], "verified_dictionary", f)
        self.assertEqual(self.m["concepts"]["separation"]["table"], "T_EMPEE_HIST")
        self.assertEqual(self.m["concepts"]["separation_secured"]["table"], "T_EMPEE_HIST_5")

    def test_mapping_resolves_on_v3_and_hides_restricted(self):
        env = dict(clean_env(), HR_DATA_SOURCE="edw", HR_EDW_MAPPING=str(COOKBOOK_MAPPING), HR_SAMPLE_PACK_PATH=str(V3))
        with mock.patch.dict(os.environ, env, clear=True):
            for s in SETS:
                con = duckdb.connect()
                res = M.resolve(con, M.load_mapping(), s, strict=True)
                self.assertTrue(res.ok)
                self.assertEqual(res.concepts["appointment"]["recorded_time_mode"], "lineage_next")
                pcols = {r[0] for r in con.execute("DESCRIBE c_person").fetchall()}
                for hidden in ("birth_date", "sex_code", "gender_code", "race_eth_rpt_code", "ipeds_race_eth", "citizenship_group", "veteran_class"):
                    self.assertNotIn(hidden, pcols)
                # class key: PAPE bridge first, crosswalk fallback, P-Class for local classes; never NULL
                self.assertEqual(one(con, "SELECT count(*) FROM c_appointment WHERE job_class_code IS NULL"), 0)
                self.assertEqual(one(con, "SELECT count(*) FROM c_appointment a WHERE job_class_code NOT IN (SELECT job_class_code FROM c_job_class)"), 0)
                self.assertEqual(one(con, "SELECT count(*) FROM c_position WHERE job_class_code NOT IN (SELECT job_class_code FROM c_job_class)"), 0)
                # deleted rows are never known today; superseded versions end where the next starts
                self.assertEqual(one(con, "SELECT count(*) FROM c_appointment WHERE current_info_ind = 'D' AND known_to > DATE '9999-01-01'"), 0)
                # termination sets agree between T_EMPEE_HIST and the secured T_EMPEE_HIST_5
                self.assertEqual(one(con, """SELECT count(*) FROM (SELECT person_id, term_date, term_reason_code FROM c_separation WHERE term_date IS NOT NULL
                                             EXCEPT SELECT person_id, term_date, term_reason_code FROM c_separation_secured)"""), 0)
                con.close()

    def test_public_mapping_does_not_resolve_on_v3(self):
        env = dict(clean_env(), HR_DATA_SOURCE="edw", HR_EDW_MAPPING=str(PUBLIC_MAPPING), HR_SAMPLE_PACK_PATH=str(V3))
        with mock.patch.dict(os.environ, env, clear=True):
            res = M.resolve(duckdb.connect(), M.load_mapping(), "longitudinal", strict=False)
            self.assertFalse(res.ok)


class TestRecordedTimeModes(unittest.TestCase):
    """mapping.py lineage_next / post_date modes on a fixture with late-keyed corrections and a deletion."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        con = duckdb.connect(str(self.tmp / "f.duckdb"))
        con.execute("""CREATE TABLE J (P INTEGER, N VARCHAR, S VARCHAR, E DATE, X DATE, H DATE, PD DATE, C VARCHAR, ST VARCHAR, F DOUBLE, CL VARCHAR)""")
        con.execute("""INSERT INTO J VALUES
            -- job row effective 2020-01-01: keyed late on 2020-01-10 with open end, corrected on 2020-07-05 (closed 2020-06-30)
            (1, 'Q00001', '00', DATE '2020-01-01', DATE '9999-12-31', DATE '2020-01-10', DATE '2020-07-05', 'N', 'Active', 1.0, 'Y0010'),
            (1, 'Q00001', '00', DATE '2020-01-01', DATE '2020-06-30', DATE '2020-07-05', DATE '2020-07-05', 'N', 'Active', 1.0, 'Y0010'),
            -- successor row keyed late on 2020-07-05
            (1, 'Q00001', '00', DATE '2020-07-01', DATE '9999-12-31', DATE '2020-07-05', DATE '2020-07-05', 'Y', 'Active', 0.5, 'Y0011'),
            -- keyed in error with a wrong effective date, deleted two days later
            (1, 'Q00001', '00', DATE '2020-07-03', DATE '9999-12-31', DATE '2020-07-05', DATE '2020-07-07', 'D', 'Active', 0.5, 'Y0011')""")
        con.execute("CREATE TABLE XW (K VARCHAR, V VARCHAR)")
        con.execute("INSERT INTO XW VALUES ('Y0010', '0010'), ('Y0011', '0011')")
        con.execute("CREATE TABLE BAD (K VARCHAR, V VARCHAR)")
        con.execute("INSERT INTO BAD VALUES ('Y0010', '0010'), ('Y0010', '9999')")
        con.execute("CREATE TABLE E (P INTEGER, E DATE, X DATE, PD DATE, C VARCHAR, R VARCHAR)")
        con.execute("""INSERT INTO E VALUES (1, DATE '2020-01-01', DATE '9999-12-31', DATE '2020-02-01', 'Y', 'G1'),
                                            (2, DATE '2020-01-01', DATE '9999-12-31', DATE '2020-03-01', 'D', 'G2')""")
        con.close()
        f = lambda col, **kw: dict(column=col, **kw)
        self.m = {"_path": "fixture", "data": {"storage": "duckdb", "sets": {"x": "."}, "duckdb_file": "f.duckdb", "pack_path": str(self.tmp)},
                  "conventions": {"effective_end": "inclusive", "open_end": "9999-12-31"}, "default_provenance": "verified_dictionary",
                  "concepts": {
                      "appointment": {"table": "J", "recorded_time": {"mode": "lineage_next", "lineage": ["person_id", "position_id", "job_suffix", "eff_date"],
                                                                     "deleted_field": "current_info_ind", "deleted_values": ["D"], "deleted_end_field": "post_date"},
                                      "fields": {"person_id": f("P"), "position_id": f("N"), "job_suffix": f("S"), "eff_date": f("E", type="date"),
                                                 "exp_date": f("X", type="date", convention="inclusive"), "recorded_start": f("H", type="date"),
                                                 "post_date": f("PD", type="date"), "current_info_ind": f("C"), "status_code": f("ST"),
                                                 "fte": f("F", type="double"),
                                                 "job_class_code": f("CL", derive=[{"lookup": {"table": "XW", "key": "K", "value": "V"}}])}},
                      "employment": {"table": "E", "recorded_time": {"mode": "post_date", "deleted_field": "current_info_ind", "deleted_values": ["D"]},
                                     "fields": {"person_id": f("P"), "eff_date": f("E", type="date"), "exp_date": f("X", type="date"),
                                                "post_date": f("PD", type="date"), "current_info_ind": f("C"),
                                                "race": f("R", role="restricted_fairness_only")}}}}
        M._check_structure(self.m)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def known(self, con, view, k, d):
        return sorted(con.execute(f"""SELECT eff_date, fte FROM {view} WHERE known_from <= DATE '{k}' AND known_to > DATE '{k}'
                                      AND valid_from <= DATE '{d}' AND valid_to >= DATE '{d}'""").fetchall())

    def test_lineage_next_reconstructs_as_known_state(self):
        with mock.patch.dict(os.environ, {"HR_DATA_SOURCE": "sample"}, clear=False):
            con = duckdb.connect()
            res = M.resolve(con, self.m, "x", strict=True)
            self.assertTrue(res.concepts["appointment"]["has_recorded_time"])
            d = dt.date
            # before the late keying nothing is known
            self.assertEqual(self.known(con, "c_appointment", "2020-01-05", "2020-01-05"), [])
            # on 2020-07-02 the January row is still open-ended: as known then, it covers July 2
            self.assertEqual(self.known(con, "c_appointment", "2020-07-02", "2020-07-02"), [(d(2020, 1, 1), 1.0)])
            # on 2020-07-06 the correction closed it, the July row exists, and the bad 07-03 row is still known
            self.assertEqual(self.known(con, "c_appointment", "2020-07-06", "2020-07-04"), [(d(2020, 7, 1), 0.5), (d(2020, 7, 3), 0.5)])
            # after the deletion was posted (07-07) only the true July row remains
            self.assertEqual(self.known(con, "c_appointment", "2020-07-08", "2020-07-04"), [(d(2020, 7, 1), 0.5)])
            self.assertEqual(self.known(con, "c_appointment", "9999-12-30", "2020-07-02"), [(d(2020, 7, 1), 0.5)])
            ends = dict(con.execute("SELECT recorded_start || '/' || eff_date, known_to FROM c_appointment").fetchall())
            self.assertEqual(ends["2020-01-10/2020-01-01"], d(2020, 7, 5))
            self.assertEqual(ends["2020-07-05/2020-07-03"], d(2020, 7, 7))
            self.assertEqual(sorted(r[0] for r in con.execute("SELECT DISTINCT job_class_code FROM c_appointment").fetchall()), ["0010", "0011"])

    def test_post_date_mode_and_restricted_fairness_role(self):
        with mock.patch.dict(os.environ, {"HR_DATA_SOURCE": "sample"}, clear=False):
            con = duckdb.connect()
            M.resolve(con, self.m, "x", strict=True)
            cols = {r[0] for r in con.execute("DESCRIBE c_employment").fetchall()}
            self.assertNotIn("race", cols)
            rows = dict((r[0], (r[1], r[2])) for r in con.execute("SELECT person_id, known_from, known_to FROM c_employment").fetchall())
            self.assertEqual(rows["1"], (dt.date(2020, 2, 1), dt.date(9999, 12, 31)))
            self.assertEqual(rows["2"], (dt.date(2020, 1, 1), dt.date(2020, 3, 1)))

    def test_non_unique_lookup_is_a_problem(self):
        self.m["concepts"]["appointment"]["fields"]["job_class_code"]["derive"] = [{"lookup": {"table": "BAD", "key": "K", "value": "V"}}]
        with mock.patch.dict(os.environ, {"HR_DATA_SOURCE": "sample"}, clear=False):
            res = M.resolve(duckdb.connect(), self.m, "x", strict=False)
            self.assertFalse(res.ok)
            self.assertTrue(any("not unique" in p for p in res.problems))

    def test_bad_mode_rejected(self):
        self.m["concepts"]["employment"]["recorded_time"]["mode"] = "guess"
        with self.assertRaises(M.MappingError):
            M._check_structure(self.m)


# ----------------------------------------------------------------------------- integration headline comparison
@unittest.skipUnless(LAKE_OK and (V3 / "longitudinal" / "sample.duckdb").exists() and (V2 / "longitudinal" / "sample.duckdb").exists(),
                     "public lake or packs not present")
class TestIntegrationV2vsV3(unittest.TestCase):
    """Run build_integrated on v2 (public mapping) and v3 (Cookbook mapping) through the environment variables.
    Headlines must be equal; the only allowed differences are the intended ones listed in README.md."""

    QUERIES = {
        "snapshot": "SELECT as_of_date, count(*) FILTER (WHERE incumbent_count > 0), count(*) FILTER (WHERE vacant), "
                    "sum(incumbent_count), round(sum(filled_fte), 6), count(*) FROM fact_position_snapshot GROUP BY 1 ORDER BY 1",
        "snapshot_campus": "SELECT as_of_date, campus_org_code, count(*), count(*) FILTER (WHERE vacant), sum(incumbent_count) "
                           "FROM fact_position_snapshot GROUP BY ALL ORDER BY ALL",
        "headcount": "SELECT as_of_date, sum(headcount), round(sum(fte), 6) FROM fact_headcount_asof GROUP BY 1 ORDER BY 1",
        "flows": "SELECT year, sum(external_hires), sum(rehires), sum(internal_hires), sum(transfers_cross_org), "
                 "sum(class_transitions), sum(separations_total), sum(sep_resignation), sum(sep_retirement), "
                 "sum(sep_end_of_appointment), sum(sep_other) FROM fact_flows_year GROUP BY 1 ORDER BY 1",
        "coverage": "SELECT sucss_match_type, count(*) FROM br_class_sucss GROUP BY 1 ORDER BY 1",
        "class_external": "SELECT job_class_code, onet_code, soc_2018_code, oews_illinois_median FROM dim_job_class_external ORDER BY 1",
        "market": "SELECT count(*) FILTER (WHERE market_pay_ratio_local IS NOT NULL), "
                  "count(*) FILTER (WHERE market_pay_ratio_il IS NOT NULL) FROM fact_position_snapshot",
        "events": "SELECT year, event_type, count(*) FROM fact_appointment_events GROUP BY ALL ORDER BY ALL",
    }

    @classmethod
    def setUpClass(cls):
        from integration.build_integrated import EXPORT, build
        cls.EXPORT = EXPORT
        cls.tmp = Path(tempfile.mkdtemp())
        cls.man = {}
        for s in SETS:
            env = dict(clean_env(), HR_DATA_SOURCE="edw", HR_EDW_MAPPING=str(PUBLIC_MAPPING), HR_SAMPLE_PACK_PATH=str(V2))
            with mock.patch.dict(os.environ, env, clear=True):
                cls.man[("v2", s)] = build(s, out_root=cls.tmp / "v2", write_parquet=False)
            env = dict(clean_env(), HR_DATA_SOURCE="edw", HR_EDW_MAPPING=str(COOKBOOK_MAPPING), HR_SAMPLE_PACK_PATH=str(V3))
            with mock.patch.dict(os.environ, env, clear=True):
                cls.man[("v3", s)] = build(s, out_root=cls.tmp / "v3", write_parquet=False)
        # one set through HR_EDW_DATA (single database) as well
        env = dict(clean_env(), HR_DATA_SOURCE="edw", HR_EDW_MAPPING=str(COOKBOOK_MAPPING), HR_EDW_DATA=str(V3 / "CLEAN" / "sample.duckdb"))
        with mock.patch.dict(os.environ, env, clear=True):
            cls.man[("v3db", "CLEAN")] = build("CLEAN", out_root=cls.tmp / "v3db", write_parquet=False)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def con(self, v, s):
        return duckdb.connect(str(self.tmp / v / f"integrated_{s}.duckdb"), read_only=True)

    def test_v3_used_cookbook_mapping(self):
        for s in SETS:
            m = self.man[("v3", s)]
            self.assertEqual(m["mapping_file"], COOKBOOK_MAPPING.name)
            self.assertTrue(m["mapping_validation"]["ok"])
            self.assertEqual(m["flows"], self.man[("v2", s)]["flows"])
            self.assertEqual(m["snapshots"], self.man[("v2", s)]["snapshots"])
        self.assertEqual({t: v["content_sha256"] for t, v in self.man[("v3db", "CLEAN")]["tables"].items()},
                         {t: v["content_sha256"] for t, v in self.man[("v3", "CLEAN")]["tables"].items()})

    def test_headlines_equal(self):
        for s in SETS:
            a, b = self.con("v2", s), self.con("v3", s)
            for name, sql in self.QUERIES.items():
                ra = a.execute(sql).fetchall()
                self.assertTrue(ra, f"{s} {name}")
                self.assertEqual(ra, b.execute(sql).fetchall(), f"{s} {name}")
            a.close()
            b.close()

    def test_only_intended_table_differences(self):
        # tables whose content may differ, and why (README "Proof"):
        #   dim_org_external: +6 synthetic admin-level-2 org units (Cookbook org levels), org_depth +1 below campus
        #   fact_position_snapshot: new position IDs; I -> C/F statuses; org of never-yet-filled vacant positions
        #   fact_flows_year (CLEAN): surs_retirement_ind now uses the Cookbook EMPEE_RET_IND derivation
        allowed = {"longitudinal": {"dim_org_external", "fact_position_snapshot"},
                   "CLEAN": {"dim_org_external", "fact_position_snapshot", "fact_flows_year"}}
        for s in SETS:
            a, b = self.man[("v2", s)]["tables"], self.man[("v3", s)]["tables"]
            for t in self.EXPORT:
                if t == "dim_org_external":
                    self.assertEqual(b[t]["rows"], a[t]["rows"] + 6)
                    continue
                self.assertEqual(a[t]["rows"], b[t]["rows"], f"{s}.{t}")
                if t not in allowed[s]:
                    self.assertEqual(a[t]["content_sha256"], b[t]["content_sha256"], f"{s}.{t}")
        self.assertIn("bench_funding_mix_role_family_campus", self.man[("v3", "CLEAN")]["tables"])
        self.assertNotIn("bench_funding_mix_role_family_campus", self.man[("v2", "CLEAN")]["tables"])

    def test_position_snapshot_differs_only_in_intended_columns(self):
        with open(V3 / "crosswalk_v2_to_v3.csv", encoding="utf-8", newline="") as fh:
            xw = [r for r in csv.DictReader(fh) if r["change"] == "id_mapped" and r["v3_column"] == "POSN_NBR"]
        for s in SETS:
            con = duckdb.connect()
            con.execute(f"ATTACH '{(self.tmp / 'v2' / f'integrated_{s}.duckdb').as_posix()}' AS a (READ_ONLY)")
            con.execute(f"ATTACH '{(self.tmp / 'v3' / f'integrated_{s}.duckdb').as_posix()}' AS b (READ_ONLY)")
            con.execute("CREATE TABLE m (v2 VARCHAR, v3 VARCHAR)")
            con.executemany("INSERT INTO m VALUES (?, ?)", [(r["v2_value"], r["v3_value"]) for r in xw if r["set"] == s])
            con.execute("CREATE TABLE bb AS SELECT t.* REPLACE (m.v2 AS position_id) FROM b.fact_position_snapshot t JOIN m ON m.v3 = t.position_id")
            self.assertEqual(one(con, "SELECT count(*) FROM bb"), one(con, "SELECT count(*) FROM a.fact_position_snapshot"))
            cols = [r[0] for r in con.execute("DESCRIBE a.fact_position_snapshot").fetchall()]
            key = ("as_of_date", "known_as_of", "position_id")
            for c in cols:
                if c in key:
                    continue
                n = one(con, f'SELECT count(*) FROM a.fact_position_snapshot p JOIN bb q USING (as_of_date, known_as_of, position_id) WHERE p."{c}" IS DISTINCT FROM q."{c}"')
                if c == "position_status_code":
                    self.assertEqual(one(con, """SELECT count(*) FROM a.fact_position_snapshot p JOIN bb q USING (as_of_date, known_as_of, position_id)
                        WHERE p.position_status_code IS DISTINCT FROM q.position_status_code AND NOT (p.position_status_code = 'I' AND q.position_status_code IN ('C', 'F'))"""), 0)
                elif c == "org_code":
                    self.assertEqual(one(con, """SELECT count(*) FROM a.fact_position_snapshot p JOIN bb q USING (as_of_date, known_as_of, position_id)
                        WHERE p.org_code IS DISTINCT FROM q.org_code AND NOT (q.incumbent_count = 0 AND p.campus_org_code = q.campus_org_code AND q.org_code = q.campus_org_code)"""), 0)
                else:
                    self.assertEqual(n, 0, f"{s}.{c}")
            con.close()


if __name__ == "__main__":
    unittest.main()
