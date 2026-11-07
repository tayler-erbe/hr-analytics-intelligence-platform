"""Tests for the v3 Cookbook binding of the conversion-readiness catalog (synthetic data only).

    python -m unittest discover -s erp_readiness/v3/tests -v        # from platform-evaluation/

Covers: the source map resolves every catalog rule (same logical contract as the v1 map); the compiled
DuckDB script for the v3 map executes on both sets and under every switch option; CLEAN has no catalog
findings; longitudinal's known findings are stable; and a planted-defect fixture in the Cookbook layout is
detected for the critical rules (and D rows are excluded from them).
"""
from __future__ import annotations

import json
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import duckdb

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))          # erp_readiness/v3/
sys.path.insert(0, str(HERE.parent.parent))   # erp_readiness/

import run_v3  # noqa: E402
from common import PE_ROOT, SOURCE_MAP_PATH, load_catalog, load_yaml  # noqa: E402

PACK = PE_ROOT / "sample_datasets" / "v3_cookbook"
_TMP: Path
_CACHE: dict = {}


def setUpModule():
    global _TMP
    _TMP = Path(tempfile.mkdtemp(prefix="erp_v3_test_"))


def tearDownModule():
    shutil.rmtree(_TMP, ignore_errors=True)


def run_cached(set_name: str, **kw):
    key = (set_name, tuple(sorted((kw.get("switches") or {}).items())))
    if key not in _CACHE:
        _CACHE[key] = run_v3.run_set(set_name, out_dir=_TMP / "runs" / "_".join(map(str, key)), **kw)
    return _CACHE[key]


class SourceMapResolvesEveryRule(unittest.TestCase):
    def setUp(self):
        self.cat = load_catalog()
        self.raw = load_yaml(run_v3.V3_SOURCE_MAP_PATH)
        self.v1 = load_yaml(SOURCE_MAP_PATH)
        self.smap = run_v3.load_source_map()

    def test_same_logical_contract_as_v1(self):
        self.assertEqual(set(self.smap["views"]), set(self.v1["views"]))
        for v, spec in self.v1["views"].items():
            self.assertEqual(set(self.smap["views"][v]["columns"]), set(spec["columns"]), v)
            self.assertEqual(bool(self.smap["views"][v].get("interval")), bool(spec.get("interval")), v)

    def test_every_rule_has_a_binding_record(self):
        ids = {r["id"] for r in self.cat["rules"]}
        self.assertEqual(set(self.raw["rule_bindings"]), ids)
        for rid, b in self.raw["rule_bindings"].items():
            self.assertTrue(b["columns"], rid)
            for col in b["columns"]:
                view, c = col.split(".")
                self.assertIn(view, self.smap["views"], f"{rid}: {col}")
                self.assertTrue(c in self.smap["views"][view]["columns"] or c == "exp_dt", f"{rid}: {col}")

    def test_unbound_rules_are_exactly_the_documented_ones(self):
        unbound = {rid for rid, b in self.raw["rule_bindings"].items() if b.get("unbound")}
        self.assertEqual(unbound, {"P01", "P02", "S06"})

    def test_every_view_points_at_a_prepared_or_raw_table(self):
        prepared = {p["name"] for p in self.smap["prepared"]}
        for v, spec in self.smap["views"].items():
            self.assertTrue(spec["table"] in prepared or spec["table"] in self.smap["physical_tables"], v)

    def test_every_rule_depends_on_some_raw_table(self):
        deps = run_v3.rule_dependencies(self.smap, self.cat)
        for rid, d in deps.items():
            self.assertTrue(d["raw_tables"], rid)
        self.assertIn("T_PAYR_ACCTG_DETL", deps["Y02"]["raw_tables"])
        self.assertIn("REF_HIERARCHY_ROOT", deps["O01"]["raw_tables"])
        self.assertIn("X_JOB_CONTRACT_TYPE", deps["J04"]["raw_tables"])

    def test_switches_substitute_and_validate(self):
        for name, spec in self.raw["switches"].items():
            for opt in spec["options"]:
                smap = run_v3.load_source_map({name: opt})
                text = json.dumps(smap["prepared"]) + json.dumps(smap["views"])
                self.assertNotIn("${", text, f"{name}={opt}")
        with self.assertRaises(ValueError):
            run_v3.load_source_map({"job_change_date": "nope"})
        with self.assertRaises(ValueError):
            run_v3.load_source_map({"no_such_switch": "x"})


class CompiledSqlRunsOnDuckDB(unittest.TestCase):
    def _exec_script(self, set_name: str, switches=None):
        cat = load_catalog()
        smap = run_v3.load_source_map(switches)
        supp = load_yaml(run_v3.SUPPLEMENTARY_PATH)
        as_of = run_v3.dt.date.fromisoformat(json.loads((PACK / set_name / "manifest.json").read_text())["extract_date"])
        con = duckdb.connect()
        run_v3.load_physical(con, smap, PACK / set_name)
        script = run_v3.compiled_script(smap, cat, supp, as_of)
        stmts = [s.strip() for s in script.split(";\n") if s.strip() and not all(l.startswith("--") for l in s.strip().splitlines())]
        n_rules = 0
        for s in stmts:
            rows = con.execute(s).fetchall()
            if re.search(r"^-- [A-Z]\d\d \[", s, re.M):
                n_rules += 1
                self.assertTrue(all(len(r) == 3 for r in rows), s[:60])
        con.close()
        return n_rules

    def test_clean_and_longitudinal_default_switches(self):
        for s in run_v3.SETS:
            with self.subTest(set=s):
                self.assertEqual(self._exec_script(s), 43 + 7)

    def test_every_switch_option_executes(self):
        raw = load_yaml(run_v3.V3_SOURCE_MAP_PATH)
        for name, spec in raw["switches"].items():
            for opt in spec["options"]:
                if opt == spec["default"]:
                    continue
                with self.subTest(switch=f"{name}={opt}"):
                    self.assertEqual(self._exec_script("CLEAN", {name: opt}), 50)


class PackResults(unittest.TestCase):
    def test_clean_has_no_catalog_findings(self):
        s = run_cached("CLEAN")
        self.assertEqual(s["as_of"], "2026-10-31")
        self.assertEqual(s["totals"]["by_status"], {"pass": 40, "warn": 0, "fail": 0, "unbound": 3, "not_evaluable": 0, "vacuous": 0})
        self.assertEqual(s["totals"]["failing_entities"], 0)
        self.assertEqual(s["overall_score"], 100.0)
        self.assertTrue(all(d["gate"] == "ready" for d in s["domains"]))
        self.assertEqual([r["failing"] for r in s["supplementary"]], [0] * 7)
        # the rules did see data
        pops = {r["rule_id"]: r["population_n"] for r in s["register"]}
        self.assertGreater(pops["J01"], 1500)
        self.assertGreater(pops["Y01"], 30000)

    def test_longitudinal_known_findings(self):
        s = run_cached("longitudinal")
        self.assertEqual(s["as_of"], "2027-01-31")
        st = {r["rule_id"]: r["status"] for r in s["register"]}
        fails = {r["rule_id"]: r["failing"] for r in s["register"] if r["status"] in ("fail", "warn")}
        self.assertEqual(fails, {"J01": 5, "C01": 135})          # see README: both are v3 pack artefacts
        self.assertEqual({k for k, v in st.items() if v == "not_evaluable"}, {"O01", "Y01", "Y02", "Y03", "Y04", "Y05"})
        self.assertEqual({k for k, v in st.items() if v == "vacuous"}, {"O02", "O03", "O04"})
        self.assertEqual({k for k, v in st.items() if v == "unbound"}, {"P01", "P02", "S06"})
        supp = {r["rule_id"]: r["failing"] for r in s["supplementary"]}
        self.assertEqual(supp["X07"], 175)
        self.assertEqual(sum(v for k, v in supp.items() if k != "X07"), 0)

    def test_scores_exclude_unsupported_rules(self):
        s = run_cached("longitudinal")
        org = next(d for d in s["domains"] if d["domain"] == "org_supervisory")
        self.assertEqual(sorted(org["excluded_rules"]), ["O01", "O02", "O03", "O04"])
        self.assertEqual(org["gate"], "ready")                     # nothing scored failed; README says why
        pay = next(d for d in s["domains"] if d["domain"] == "payroll")
        self.assertEqual(len(pay["excluded_rules"]), 5)

    def test_recorded_change_date_variant_runs(self):
        s = run_cached("CLEAN", switches={"job_change_date": "recorded"})
        self.assertEqual(s["switches"]["job_change_date"], "recorded")
        fails = {r["rule_id"]: r["failing"] for r in s["register"] if r["failing"]}
        self.assertEqual(fails.get("J01"), 26)                     # CLEAN's 26 Future rows collide under this reading


class PlantedDefectsInCookbookLayout(unittest.TestCase):
    """Copy CLEAN, plant one defect per critical rule (plus a few others) with DuckDB, run, assert detection."""

    @classmethod
    def setUpClass(cls):
        src = PACK / "CLEAN"
        cls.dir = _TMP / "planted"
        cls.dir.mkdir(parents=True, exist_ok=True)
        shutil.copy(src / "manifest.json", cls.dir / "manifest.json")
        con = duckdb.connect()
        tables = [p.stem for p in src.glob("*.parquet")]
        for t in tables:
            con.execute(f"CREATE TABLE {t} AS SELECT * FROM read_parquet('{(src / t).with_suffix('.parquet').as_posix()}')")
        q = lambda sql: con.execute(sql).fetchall()  # noqa: E731
        P = cls.planted = {}
        as_of = "DATE '2026-10-31'"

        # Helpers: current (Y) Active primary jobs with a supervisor, one per person, oldest ids first.
        prim = q(f"""SELECT j.EDW_PERS_ID, j.POSN_NBR, j.JOB_SUFFIX, j.JOB_DETL_EFF_DT, j.SUPV_EDW_PERS_ID
                     FROM T_JOB_DETL_HIST j JOIN X_JOB_CONTRACT_TYPE x USING (EDW_PERS_ID, POSN_NBR, JOB_SUFFIX)
                     WHERE j.JOB_DETL_CUR_INFO_IND = 'Y' AND j.JOB_DETL_STATUS_DESC = 'Active' AND x.JOB_CONTRACT_TYPE_CD = 'P'
                       AND j.SUPV_EDW_PERS_ID IS NOT NULL AND j.JOB_DETL_EMPEE_CLS_CD = 'CA'
                       AND NOT EXISTS (SELECT 1 FROM T_JOB_DETL_HIST o WHERE o.EDW_PERS_ID = j.EDW_PERS_ID AND o.JOB_DETL_CUR_INFO_IND = 'Y'
                                       AND o.JOB_DETL_STATUS_DESC = 'Active' AND (o.POSN_NBR <> j.POSN_NBR OR o.JOB_SUFFIX <> j.JOB_SUFFIX))
                     ORDER BY j.EDW_PERS_ID""")
        key = lambda r: f"{r[0]}|{r[1]}|{r[2]}"  # noqa: E731
        it = iter(prim)

        # J01 overlap: a person's earliest lineage row extended 5 days past the next row's start (the
        # extended row stays historical, so no second current row appears).
        while True:
            r = next(it)
            rows = q(f"SELECT JOB_DETL_EFF_DT FROM T_JOB_DETL_HIST WHERE EDW_PERS_ID={r[0]} AND POSN_NBR='{r[1]}' AND JOB_SUFFIX='{r[2]}' AND JOB_DETL_CUR_INFO_IND<>'D' ORDER BY 1")
            if len(rows) >= 2 and str(rows[1][0]) < "2026-01-01":
                break
        con.execute(f"UPDATE T_JOB_DETL_HIST SET JOB_DETL_EXP_DT = DATE '{rows[1][0]}' + INTERVAL 5 DAY WHERE EDW_PERS_ID={r[0]} AND POSN_NBR='{r[1]}' AND JOB_SUFFIX='{r[2]}' AND JOB_DETL_EFF_DT = DATE '{rows[0][0]}'")
        P["J01"] = key(r)
        # J03 inverted interval on a current row (also planted as a D copy below for the exclusion test).
        r = next(it)
        con.execute(f"UPDATE T_JOB_DETL_HIST SET JOB_DETL_EXP_DT = JOB_DETL_EFF_DT - INTERVAL 10 DAY WHERE EDW_PERS_ID={r[0]} AND POSN_NBR='{r[1]}' AND JOB_SUFFIX='{r[2]}' AND JOB_DETL_CUR_INFO_IND='Y'")
        P["J03"] = key(r)
        # J04 two active primary jobs: promote an active secondary (S) job to P.
        s = q("""SELECT x.EDW_PERS_ID, x.POSN_NBR, x.JOB_SUFFIX FROM X_JOB_CONTRACT_TYPE x JOIN T_JOB_DETL_HIST j USING (EDW_PERS_ID, POSN_NBR, JOB_SUFFIX)
                 WHERE x.JOB_CONTRACT_TYPE_CD = 'S' AND j.JOB_DETL_CUR_INFO_IND = 'Y' AND j.JOB_DETL_STATUS_DESC = 'Active' ORDER BY 1 LIMIT 1""")[0]
        con.execute(f"UPDATE X_JOB_CONTRACT_TYPE SET JOB_CONTRACT_TYPE_CD = 'P' WHERE EDW_PERS_ID={s[0]} AND POSN_NBR='{s[1]}' AND JOB_SUFFIX='{s[2]}'")
        P["J04"] = str(s[0])
        # J06 FTE above 1 on a current job (stored as a fraction).
        r = next(it)
        con.execute(f"UPDATE T_JOB_DETL_HIST SET JOB_DETL_FTE = 1.500 WHERE EDW_PERS_ID={r[0]} AND POSN_NBR='{r[1]}' AND JOB_SUFFIX='{r[2]}' AND JOB_DETL_CUR_INFO_IND='Y'")
        P["J06"] = key(r)
        # E03 terminated employee with an active job: flip the current employee row to T.
        r = next(it)
        con.execute(f"UPDATE T_EMPEE_HIST SET EMPEE_STATUS_CD = 'T', EMPEE_STATUS_DESC = 'Terminated' WHERE EDW_PERS_ID={r[0]} AND EMPEE_CUR_INFO_IND='Y'")
        P["E03"] = str(r[0])
        # E01 overlapping employee rows: an expired Active row extended 5 days into the next one (highest id,
        # so it cannot collide with the low-id persons used by the other plants).
        e = q("""SELECT n.EDW_PERS_ID, n.EMPEE_EFF_DT, n.EMPEE_EXP_DT FROM T_EMPEE_HIST n
                 WHERE n.EMPEE_CUR_INFO_IND = 'N' AND n.EMPEE_STATUS_CD = 'A' AND n.EMPEE_EXP_DT < DATE '2025-12-31'
                 ORDER BY n.EDW_PERS_ID DESC, n.EMPEE_EFF_DT LIMIT 1""")[0]
        con.execute(f"UPDATE T_EMPEE_HIST SET EMPEE_EXP_DT = EMPEE_EXP_DT + INTERVAL 5 DAY WHERE EDW_PERS_ID={e[0]} AND EMPEE_EFF_DT = DATE '{e[1]}'")
        P["E01"] = str(e[0])
        # S04 job on a position missing from position control.
        r = next(it)
        con.execute(f"DELETE FROM T_POSN_HIST WHERE POSN_NBR='{r[1]}'")
        P["S04"] = key(r)
        # O03 reporting cycle between two people; O04 self-supervision for a third.
        a, b, c = next(it), next(it), next(it)
        con.execute(f"UPDATE T_JOB_DETL_HIST SET SUPV_EDW_PERS_ID={b[0]} WHERE EDW_PERS_ID={a[0]} AND POSN_NBR='{a[1]}' AND JOB_SUFFIX='{a[2]}' AND JOB_DETL_CUR_INFO_IND='Y'")
        con.execute(f"UPDATE T_JOB_DETL_HIST SET SUPV_EDW_PERS_ID={a[0]} WHERE EDW_PERS_ID={b[0]} AND POSN_NBR='{b[1]}' AND JOB_SUFFIX='{b[2]}' AND JOB_DETL_CUR_INFO_IND='Y'")
        con.execute(f"UPDATE T_JOB_DETL_HIST SET SUPV_EDW_PERS_ID={c[0]} WHERE EDW_PERS_ID={c[0]} AND POSN_NBR='{c[1]}' AND JOB_SUFFIX='{c[2]}' AND JOB_DETL_CUR_INFO_IND='Y'")
        P["O03"] = sorted([str(a[0]), str(b[0])])
        P["O04"] = str(c[0])
        # O01 primary job with no supervisor (position not in REF_HIERARCHY_ROOT).
        r = next(it)
        con.execute(f"UPDATE T_JOB_DETL_HIST SET SUPV_EDW_PERS_ID=NULL WHERE EDW_PERS_ID={r[0]} AND POSN_NBR='{r[1]}' AND JOB_SUFFIX='{r[2]}' AND JOB_DETL_CUR_INFO_IND='Y'")
        P["O01"] = str(r[0])
        # C01 civil-service job whose P-Class resolves to no SUCSS class.
        r = next(it)
        con.execute(f"UPDATE T_JOB_DETL_HIST SET JOB_DETL_POSN_CLS_CD='Y9999' WHERE EDW_PERS_ID={r[0]} AND POSN_NBR='{r[1]}' AND JOB_SUFFIX='{r[2]}' AND JOB_DETL_CUR_INFO_IND='Y'")
        P["C01"] = key(r)
        # P05 employee rows with no person record.
        r = next(it)
        con.execute(f"DELETE FROM T_PERS_HIST WHERE EDW_PERS_ID={r[0]}")
        P["P05"] = str(r[0])
        # Y02 pay after termination: move a recent pay row to a person terminated before it (no rehire).
        t = q(f"""SELECT e.EDW_PERS_ID, e.EMPEE_TERMN_DT FROM T_EMPEE_HIST e WHERE e.EMPEE_CUR_INFO_IND='Y' AND e.EMPEE_STATUS_CD='T'
                  AND e.EMPEE_TERMN_DT < DATE '2026-01-01' ORDER BY 1 LIMIT 1""")[0]
        y = q("SELECT PAYR_ACCTG_TRAN_NBR, POSN_NBR, JOB_SUFFIX, PAYR_ACCTG_EFF_DT FROM T_PAYR_ACCTG_DETL WHERE PAYR_ACCTG_EFF_DT = DATE '2026-10-31' AND PAYR_EVENT_TYPE_CD='C' ORDER BY 1 LIMIT 1")[0]
        con.execute(f"UPDATE T_PAYR_ACCTG_DETL SET EDW_PERS_ID={t[0]} WHERE PAYR_ACCTG_TRAN_NBR={y[0]}")
        P["Y02"] = f"{t[0]}|{y[1]}|{y[2]}|{y[3]}"
        # Y05 duplicate pay accounting row (same event type) on a new transaction number.
        con.execute("""INSERT INTO T_PAYR_ACCTG_DETL SELECT (SELECT MAX(PAYR_ACCTG_TRAN_NBR) + 1 FROM T_PAYR_ACCTG_DETL), * EXCLUDE (PAYR_ACCTG_TRAN_NBR)
                       FROM T_PAYR_ACCTG_DETL WHERE PAYR_EVENT_TYPE_CD='C' AND PAYR_ACCTG_CATGRY_CD='E' AND PAYR_ACCTG_EFF_DT = DATE '2026-09-30' ORDER BY PAYR_ACCTG_TRAN_NBR LIMIT 1""")
        d = q("SELECT EDW_PERS_ID, POSN_NBR, JOB_SUFFIX, PAYR_ACCTG_EFF_DT FROM T_PAYR_ACCTG_DETL WHERE PAYR_ACCTG_TRAN_NBR = (SELECT MAX(PAYR_ACCTG_TRAN_NBR) FROM T_PAYR_ACCTG_DETL)")[0]
        P["Y05"] = f"{d[0]}|{d[1]}|{d[2]}|{d[3]}"
        # X04 secured copy disagrees: shift one secured termination date.
        x = q("SELECT EDW_PERS_ID, EMPEE_EFF_DT FROM T_EMPEE_HIST_5 WHERE EMPEE_CUR_INFO_IND='Y' ORDER BY 1 LIMIT 1")[0]
        con.execute(f"UPDATE T_EMPEE_HIST_5 SET EMPEE_TERMN_DT = EMPEE_TERMN_DT + INTERVAL 1 DAY WHERE EDW_PERS_ID={x[0]} AND EMPEE_EFF_DT = DATE '{x[1]}'")
        P["X04"] = str(x[0])
        # D-row exclusion: a deleted copy of a current row keyed 3 days late (would overlap if not excluded),
        # and a job key that exists only as a D row (X02).
        r = next(it)
        con.execute(f"""INSERT INTO T_JOB_DETL_HIST SELECT * REPLACE (JOB_DETL_EFF_DT + INTERVAL 3 DAY AS JOB_DETL_EFF_DT, 'D' AS JOB_DETL_CUR_INFO_IND,
                        'Deleted' AS JOB_DETL_DATA_STATUS_DESC) FROM T_JOB_DETL_HIST
                        WHERE EDW_PERS_ID={r[0]} AND POSN_NBR='{r[1]}' AND JOB_SUFFIX='{r[2]}' AND JOB_DETL_CUR_INFO_IND='Y'""")
        P["D_excluded"] = key(r)
        r = next(it)
        con.execute(f"""INSERT INTO T_JOB_DETL_HIST SELECT * REPLACE ('99' AS JOB_SUFFIX, 'D' AS JOB_DETL_CUR_INFO_IND, 'Deleted' AS JOB_DETL_DATA_STATUS_DESC)
                        FROM T_JOB_DETL_HIST WHERE EDW_PERS_ID={r[0]} AND POSN_NBR='{r[1]}' AND JOB_SUFFIX='{r[2]}' AND JOB_DETL_CUR_INFO_IND='Y'""")
        P["X02"] = f"{r[0]}|{r[1]}|99"

        for t in tables:
            con.execute(f"COPY {t} TO '{(cls.dir / t).with_suffix('.parquet').as_posix()}' (FORMAT PARQUET)")
        con.close()
        cls.summary = run_v3.run_set("CLEAN", data_dir=cls.dir, out_dir=_TMP / "runs" / "planted")
        cls.found = cls.summary["_entity_ids"]

    def test_critical_rules_detect_planted_defects(self):
        for rid in ("J01", "J03", "J04", "J06", "E03", "E01", "S04", "O01", "O03", "O04", "C01", "P05", "Y02", "Y05", "X04", "X02"):
            with self.subTest(rule=rid):
                want = self.planted[rid]
                ids = self.found[rid]
                if isinstance(want, list):
                    self.assertTrue(set(want) <= set(ids), (want, ids[:5]))
                else:
                    self.assertIn(want, ids, ids[:5])

    def test_planted_rules_fire_only_where_planted(self):
        for rid in ("J03", "J04", "J06", "E03", "E01", "S04", "O04", "P05", "Y05", "X04", "X02"):
            with self.subTest(rule=rid):
                self.assertEqual(len(self.found[rid]), 1, self.found[rid][:5])
        self.assertEqual(len(self.found["J01"]), 1)
        self.assertEqual(sorted(self.found["O03"]), self.planted["O03"])

    def test_deleted_rows_are_excluded(self):
        self.assertNotIn(self.planted["D_excluded"], self.found["J01"])
        self.assertNotIn(self.planted["D_excluded"], self.found["J02"])
        self.assertNotIn(self.planted["X02"], self.found["J01"])
        self.assertEqual(self.found["X01"], [])

    def test_gates_reflect_planted_defects(self):
        gates = {d["domain"]: d["gate"] for d in self.summary["domains"]}
        self.assertEqual(gates["job_history"], "blocked")
        self.assertEqual(gates["org_supervisory"], "blocked")
        self.assertEqual(gates["payroll"], "blocked")
        self.assertLess(self.summary["overall_score"], 100.0)


if __name__ == "__main__":
    unittest.main()
