"""Tests for the integration layer.

    cd platform-evaluation && python -m unittest discover -s integration/tests -v

Needs the sample pack (sample_datasets/v1) and the built public lake (data/lake/contract + silver).
Builds write only to temporary folders.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path

import duckdb
import yaml

from integration import external as X
from integration import mapping as M
from integration.build_integrated import EXPORT, build, measure_registry

PACK = M.PE_ROOT / "sample_datasets" / "v1"
LONG_DB = PACK / "longitudinal" / "sample.duckdb"
CLEAN_DB = PACK / "quality" / "CLEAN" / "sample.duckdb"
LAKE_OK = (M.PE_ROOT / "data/lake/contract/sucss_class.parquet").exists() and \
    (M.PE_ROOT / "data/lake/silver/bls_oews_all.parquet").exists()


def write_mapping(m: dict, path: Path, pack: Path, storage: str, sets: dict) -> Path:
    m = copy.deepcopy(m)
    m.pop("_path", None)
    m["data"] = {"pack_path": str(pack), "storage": storage, "duckdb_file": "sample.duckdb", "sets": sets}
    path.write_text(yaml.safe_dump(m, sort_keys=False), encoding="utf-8")
    return path


def make_fixture(dst: Path, n_people: int = 60) -> None:
    """Small longitudinal subset (first n people in ID order, their positions, all reference tables) as Parquet."""
    dst.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute(f"ATTACH '{LONG_DB.as_posix()}' AS s (READ_ONLY)")
    con.execute(f"CREATE TEMP TABLE ppl AS SELECT DISTINCT EDW_PERS_ID FROM s.T_JOB_DETL_HIST ORDER BY 1 LIMIT {n_people}")
    con.execute("CREATE TEMP TABLE pos AS SELECT DISTINCT POSN_NBR FROM s.T_JOB_DETL_HIST WHERE EDW_PERS_ID IN (SELECT * FROM ppl)")
    q = {
        "T_PERS_HIST": "SELECT * FROM s.T_PERS_HIST WHERE EDW_PERS_ID IN (SELECT * FROM ppl)",
        "T_EMPEE_HIST": "SELECT * FROM s.T_EMPEE_HIST WHERE EDW_PERS_ID IN (SELECT * FROM ppl)",
        "T_EMPEE_HIST_5": "SELECT * FROM s.T_EMPEE_HIST_5 WHERE EDW_PERS_ID IN (SELECT * FROM ppl)",
        "T_JOB_DETL_HIST": "SELECT * FROM s.T_JOB_DETL_HIST WHERE EDW_PERS_ID IN (SELECT * FROM ppl)",
        "T_POSN_HIST": "SELECT * FROM s.T_POSN_HIST WHERE POSN_NBR IN (SELECT * FROM pos)",
        "REF_JOB_CLASS": "SELECT * FROM s.REF_JOB_CLASS", "REF_ORG": "SELECT * FROM s.REF_ORG",
        "REF_ROLE_FAMILY": "SELECT * FROM s.REF_ROLE_FAMILY",
    }
    for t, sql in q.items():
        con.execute(f"COPY ({sql} ORDER BY ALL) TO '{(dst / (t + '.parquet')).as_posix()}' (FORMAT parquet)")
    con.close()


@unittest.skipUnless(LONG_DB.exists() and CLEAN_DB.exists(), "sample pack not present")
class TestMapping(unittest.TestCase):
    def test_every_concept_resolves_on_every_set(self):
        m = M.load_mapping()
        reports = M.validate_all(m)
        self.assertEqual(set(reports), {"longitudinal", "CLEAN", "DEFECTS"})
        for s, r in reports.items():
            self.assertTrue(r["ok"], (s, r["problems"]))
            for cname, c in m["concepts"].items():
                status = r["concepts"][cname]["status"]
                if c.get("optional"):
                    self.assertIn(status, {"resolved", "absent_optional"}, (s, cname))
                else:
                    self.assertEqual(status, "resolved", (s, cname))
                    for fname, f in r["concepts"][cname]["fields"].items():
                        self.assertIn(f["provenance"], M.PROVENANCE_VALUES)
                        if not c["fields"][fname].get("optional"):
                            self.assertEqual(f["status"], "resolved", (s, cname, fname))
            chk = M.check_schema_assumptions(m, s)
            self.assertGreater(chk["checked"], 50)
            self.assertEqual(chk["mismatches"], [], s)
        # optional concepts exist where the pack says they do
        self.assertEqual(reports["longitudinal"]["concepts"]["role_family"]["status"], "resolved")
        self.assertEqual(reports["CLEAN"]["concepts"]["payroll_line"]["status"], "resolved")
        self.assertEqual(reports["longitudinal"]["concepts"]["payroll_line"]["status"], "absent_optional")

    def test_every_entry_has_provenance_flag(self):
        raw = yaml.safe_load(M.DEFAULT_MAPPING.read_text())
        for cname, c in raw["concepts"].items():
            for fname, f in c["fields"].items():
                self.assertIn(f.get("provenance"), M.PROVENANCE_VALUES, (cname, fname))

    def test_restricted_fields_never_exposed(self):
        con = duckdb.connect()
        M.resolve(con, M.load_mapping(), "longitudinal")
        cols = [r[0] for r in con.execute("DESCRIBE c_person").fetchall()]
        self.assertNotIn("birth_date", cols)

    def test_edw_source_requires_explicit_mapping(self):
        import os
        old = os.environ.get("HR_DATA_SOURCE")
        try:
            os.environ["HR_DATA_SOURCE"] = "edw"
            os.environ.pop("HR_EDW_MAPPING", None)
            with self.assertRaises(M.MappingError):
                M.load_mapping()
        finally:
            if old is None:
                os.environ.pop("HR_DATA_SOURCE", None)
            else:
                os.environ["HR_DATA_SOURCE"] = old


@unittest.skipUnless(LAKE_OK, "public lake not built")
class TestSuppression(unittest.TestCase):
    def test_bls_codes_become_null_not_zero(self):
        con = duckdb.connect()
        X.register_macros(con)
        for code in ("*", "**", "#", "~", "", None):
            v, f = con.execute("SELECT bls_num(?), bls_flag(?)", [code, code]).fetchall()[0]
            self.assertIsNone(v, code)
            self.assertIsNotNone(f, code)
        self.assertEqual(con.execute("SELECT bls_num('1,234.5'), bls_flag('1,234.5')").fetchall()[0], (1234.5, None))
        self.assertEqual(con.execute("SELECT bls_num('0')").fetchall()[0][0], 0.0)

    def test_oews_suppressed_cells_null_in_loaded_table(self):
        con = duckdb.connect()
        X.load_external(con, X.load_bridges())
        n_flag, n_bad = con.execute("""SELECT count(*) FILTER (WHERE a_pct90_flag IN ('#', '*') OR a_median_flag IN ('#', '*')
                                                                OR tot_emp_flag = '**'),
            count(*) FILTER (WHERE (a_pct90_flag IS NOT NULL AND a_pct90 IS NOT NULL)
                             OR (a_median_flag IS NOT NULL AND a_median IS NOT NULL)
                             OR (tot_emp_flag IS NOT NULL AND tot_emp IS NOT NULL))
            FROM ext_oews""").fetchall()[0]
        self.assertGreater(n_flag, 0, "fixture expectation: OEWS has top-coded/suppressed cells")
        self.assertEqual(n_bad, 0)
        # QCEW disclosure-suppressed years stay NULL
        self.assertEqual(con.execute("SELECT count(*) FROM ext_qcew_county_year WHERE any_suppressed AND avg_employment IS NOT NULL").fetchall()[0][0], 0)


@unittest.skipUnless(LONG_DB.exists() and LAKE_OK, "sample pack or lake missing")
class TestBuild(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="integ_"))
        cls.man_long = build("longitudinal", out_root=cls.tmp / "a")
        cls.man_clean = build("CLEAN", out_root=cls.tmp / "a")
        cls.db_long = cls.tmp / "a" / "integrated_longitudinal.duckdb"
        cls.db_clean = cls.tmp / "a" / "integrated_CLEAN.duckdb"

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _raw_counts(self, sample_db: Path, d: str, bitemporal: bool):
        con = duckdb.connect(str(sample_db), read_only=True)
        rec = f"AND ROW_REC_START_DT <= DATE '{d}' AND ROW_REC_END_DT > DATE '{d}'" if bitemporal else ""
        r = con.execute(f"""SELECT count(DISTINCT (EDW_PERS_ID, POSN_NBR)), count(DISTINCT EDW_PERS_ID) FROM T_JOB_DETL_HIST
                            WHERE JOB_DETL_EFF_DT <= DATE '{d}' AND JOB_DETL_EXP_DT >= DATE '{d}' AND JOB_STATUS_CD = 'A' {rec}""").fetchall()[0]
        con.close()
        return r

    def test_no_headcount_fanout(self):
        for db, sample, bt in ((self.db_long, LONG_DB, True), (self.db_clean, CLEAN_DB, False)):
            con = duckdb.connect(str(db), read_only=True)
            snaps = con.execute("SELECT DISTINCT as_of_date FROM fact_position_snapshot ORDER BY 1").fetchall()
            self.assertGreaterEqual(len(snaps), 5)
            for (d,) in snaps:
                inc = con.execute(f"SELECT sum(incumbent_count) FROM fact_position_snapshot WHERE as_of_date = DATE '{d}'").fetchall()[0][0]
                hc = con.execute(f"SELECT sum(headcount) FROM fact_headcount_asof WHERE as_of_date = DATE '{d}'").fetchall()[0][0]
                raw_pp, raw_people = self._raw_counts(sample, str(d), bt)
                self.assertEqual(inc, raw_pp, (db.name, d))
                self.assertEqual(hc, raw_people, (db.name, d))
            # one row per class and per position-date despite multi-record SUCSS codes and top-k candidates
            self.assertEqual(con.execute("SELECT count(*) - count(DISTINCT job_class_code) FROM dim_job_class_external").fetchall()[0][0], 0)
            self.assertEqual(con.execute("""SELECT count(*) FROM (SELECT as_of_date, known_as_of, position_id FROM fact_position_snapshot
                                            GROUP BY ALL HAVING count(*) > 1)""").fetchall()[0][0], 0)
            con.close()
        con = duckdb.connect(str(self.db_clean), read_only=True)
        r = con.execute("SELECT n_sucss_records, sucss_match_type FROM dim_job_class_external WHERE job_class_code = '1164'").fetchall()
        self.assertEqual(r, [(2, "exact_code_multi_record_title_resolved")])
        con.close()

    def test_flows_match_generator_truth(self):
        truth = json.loads((PACK / "longitudinal" / "truth.json").read_text())["stats"]
        con = duckdb.connect(str(self.db_long), read_only=True)
        moves = con.execute("SELECT count(*) FROM fact_appointment_events WHERE event_type = 'internal_move'").fetchall()[0][0]
        seps = con.execute("SELECT count(*) FROM fact_separation_events").fetchall()[0][0]
        con.close()
        self.assertEqual(moves, truth["internal_moves"])
        self.assertEqual(seps, truth["separations"])

    def test_provenance_on_every_external_fact(self):
        reg = measure_registry()
        for db in (self.db_long, self.db_clean):
            con = duckdb.connect(str(db), read_only=True)
            measures = {r[0] for r in con.execute("SELECT DISTINCT measure FROM fact_class_external_long").fetchall()}
            self.assertEqual(measures, {c for c, _ in reg})
            bad = con.execute("""SELECT count(*) FROM fact_class_external_long WHERE value IS NOT NULL
                                 AND (source_id IS NULL OR vintage IS NULL OR review_status IS NULL)""").fetchall()[0][0]
            self.assertEqual(bad, 0, db.name)
            no_reason = con.execute("SELECT count(*) FROM fact_class_external_long WHERE value IS NULL AND null_reason IS NULL").fetchall()[0][0]
            self.assertEqual(no_reason, 0)
            # anything downstream of the SUCSS->O*NET link is marked unreviewed
            self.assertEqual(con.execute("""SELECT count(*) FROM fact_class_external_long WHERE value IS NOT NULL
                AND provenance_group IN ('oews', 'projections', 'aei', 'onet_profile', 'job_evolution', 'oews_trend', 'soc')
                AND coalesce(chain_review_status, '') NOT LIKE 'unreviewed%'""").fetchall()[0][0], 0)
            # abstained -> NULL external facts plus a reason
            ab = con.execute("""SELECT count(*), count(*) FILTER (WHERE external_null_reason LIKE 'onet_match_abstained%'),
                                       count(soc_2018_code) + count(oews_national_median) + count(je_watch_score) + count(aei_observed_exposure)
                                FROM dim_job_class_external WHERE onet_abstained""").fetchall()[0]
            self.assertGreater(ab[0], 0)
            self.assertEqual(ab[0], ab[1])
            self.assertEqual(ab[2], 0)
            # position market facts carry provenance whenever present
            self.assertEqual(con.execute("""SELECT count(*) FROM fact_position_snapshot WHERE (market_pay_ratio_local IS NOT NULL
                OR market_pay_ratio_il IS NOT NULL) AND (market_source_id IS NULL OR market_vintage IS NULL OR market_review_status IS NULL
                OR market_chain_review_status NOT LIKE '%synthetic_assignment%')""").fetchall()[0][0], 0)
            for t in [r[0] for r in con.execute("SELECT table_name FROM information_schema.tables WHERE table_name LIKE 'ext_%'").fetchall()]:
                cols = {r[0] for r in con.execute(f"DESCRIBE {t}").fetchall()}
                self.assertTrue({"source_id", "vintage", "review_status"} <= cols, t)
                self.assertEqual(con.execute(f"SELECT count(*) FROM {t} WHERE source_id IS NULL OR vintage IS NULL OR review_status IS NULL").fetchall()[0][0], 0, t)
            con.close()

    def test_reproducible(self):
        man2 = build("longitudinal", out_root=self.tmp / "b")
        for t in EXPORT:
            self.assertEqual(self.man_long["tables"][t]["content_sha256"], man2["tables"][t]["content_sha256"], t)
        a = (self.tmp / "a" / "longitudinal" / "manifest.json").read_text()
        b = (self.tmp / "b" / "longitudinal" / "manifest.json").read_text()
        self.assertEqual(a.replace(str(self.tmp / "a"), "X"), b.replace(str(self.tmp / "b"), "X"))
        for t in EXPORT:
            pa = (self.tmp / "a" / "longitudinal" / f"{t}.parquet").read_bytes()
            pb = (self.tmp / "b" / "longitudinal" / f"{t}.parquet").read_bytes()
            self.assertEqual(hashlib.sha256(pa).hexdigest(), hashlib.sha256(pb).hexdigest(), t)

    def test_jsonl_text_storage_matches_duckdb(self):
        m = M.load_mapping()
        mp = write_mapping(m, self.tmp / "jsonl_mapping.yaml", PACK, "jsonl", {"longitudinal": "longitudinal"})
        man = build("longitudinal", out_root=self.tmp / "j", mapping_file=mp, write_parquet=False)
        for t in EXPORT:
            self.assertEqual(self.man_long["tables"][t]["content_sha256"], man["tables"][t]["content_sha256"], t)


@unittest.skipUnless(LONG_DB.exists() and LAKE_OK, "sample pack or lake missing")
class TestFixtures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="integfx_"))
        make_fixture(cls.tmp / "pack" / "orig")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_swapping_mapping_files_gives_identical_outputs(self):
        """Rename every table and column, store FTE as a percent and make effective ends exclusive;
        only the mapping file changes, and every exported table is identical."""
        m = M.load_mapping()
        orig_map = write_mapping(m, self.tmp / "orig.yaml", self.tmp / "pack", "parquet", {"fx": "orig"})
        alt = copy.deepcopy(m)
        alt_dir = self.tmp / "pack" / "renamed"
        alt_dir.mkdir(parents=True, exist_ok=True)
        con = duckdb.connect()
        for cname, c in m["concepts"].items():
            src = self.tmp / "pack" / "orig" / f"{c['table']}.parquet"
            if not src.exists():
                continue
            new_table = f"EDWV_{cname.upper()}"
            alt["concepts"][cname]["table"] = new_table
            cols = [r[0] for r in con.execute(f"DESCRIBE SELECT * FROM '{src.as_posix()}'").fetchall()]
            by_col = {f["column"]: (fname, f) for fname, f in c["fields"].items()}
            sel = []
            for col in cols:
                fname, f = by_col.get(col, (None, None))
                new_col = f"X_{cname[:4].upper()}_{(fname or col).upper()}"
                expr = f'"{col}"'
                if fname == "fte" or fname == "budget_fte":
                    expr = f'"{col}" * 100'
                    alt["concepts"][cname]["fields"][fname]["transform"] = "percent_to_fraction"
                if fname == "exp_date":
                    expr = f"""CASE WHEN "{col}" >= DATE '9999-12-31' THEN "{col}" ELSE "{col}" + INTERVAL 1 DAY END"""
                    alt["concepts"][cname]["fields"][fname]["convention"] = "exclusive"
                sel.append(f"{expr} AS {new_col}")
                if fname:
                    alt["concepts"][cname]["fields"][fname]["column"] = new_col
            con.execute(f"COPY (SELECT {', '.join(sel)} FROM '{src.as_posix()}') TO '{(alt_dir / (new_table + '.parquet')).as_posix()}' (FORMAT parquet)")
        con.close()
        alt_map = write_mapping(alt, self.tmp / "alt.yaml", self.tmp / "pack", "parquet", {"fx": "renamed"})
        self.assertNotIn("T_JOB_DETL_HIST", alt_map.read_text())
        a = build("fx", out_root=self.tmp / "out_a", mapping_file=orig_map, write_parquet=False)
        b = build("fx", out_root=self.tmp / "out_b", mapping_file=alt_map, write_parquet=False)
        self.assertGreater(a["tables"]["fact_position_snapshot"]["rows"], 0)
        self.assertGreater(a["tables"]["fact_flows_year"]["rows"], 0)
        for t in EXPORT:
            self.assertEqual(a["tables"][t], b["tables"][t], t)

    def test_asof_inclusive_effective_and_recorded_as_of(self):
        """Hand-made bitemporal fixture: inclusive effective end, exclusive recorded end, late-keyed rows."""
        d = self.tmp / "pack" / "asof"
        d.mkdir(parents=True, exist_ok=True)
        con = duckdb.connect()
        orig = self.tmp / "pack" / "orig"
        for t in ("REF_JOB_CLASS", "REF_ORG", "REF_ROLE_FAMILY"):
            shutil.copy(orig / f"{t}.parquet", d / f"{t}.parquet")
        open_ = "DATE '9999-12-31'"
        # P1: appointment ends 2020-06-30 (inclusive). P2: hired 2020-06-01 but keyed on 2020-08-15 (late).
        # P3: version recorded 2020-01-01 says the job ends 2020-03-31; corrected on 2020-05-01 to continue (open).
        con.execute(f"""COPY (SELECT * FROM (VALUES
            ('P1','Q1','00',DATE '2019-01-01',DATE '2020-06-30','P','A',1.0,50000.0,'0010','C1','U111',NULL,DATE '2019-01-01',{open_}),
            ('P2','Q2','00',DATE '2020-06-01',{open_},'P','A',1.0,60000.0,'0011','C1','U211',NULL,DATE '2020-08-15',{open_}),
            ('P3','Q3','00',DATE '2020-01-01',DATE '2020-03-31','P','A',1.0,70000.0,'0012','C1','U311',NULL,DATE '2020-01-01',DATE '2020-05-01'),
            ('P3','Q3','00',DATE '2020-01-01',{open_},'P','A',1.0,70000.0,'0012','C1','U311',NULL,DATE '2020-05-01',{open_})
            ) t(EDW_PERS_ID,POSN_NBR,JOB_SUFFIX,JOB_DETL_EFF_DT,JOB_DETL_EXP_DT,JOB_CONTRACT_TYPE_CD,JOB_STATUS_CD,JOB_FTE,
                JOB_ANNUAL_SAL_AMT,JOB_CLS_CD,JOB_ECLS_CD,JOB_ORG_CD,SUPERVISOR_PERS_ID,ROW_REC_START_DT,ROW_REC_END_DT))
            TO '{(d / 'T_JOB_DETL_HIST.parquet').as_posix()}' (FORMAT parquet)""")
        con.execute(f"""COPY (SELECT * FROM (VALUES
            ('Q1',DATE '2010-01-01',{open_},'A','0010','U111',1.0,'p',DATE '2010-01-01',{open_}),
            ('Q2',DATE '2010-01-01',{open_},'A','0011','U211',1.0,'p',DATE '2010-01-01',{open_}),
            ('Q3',DATE '2010-01-01',{open_},'A','0012','U311',1.0,'p',DATE '2010-01-01',{open_})
            ) t(POSN_NBR,POSN_EFF_DT,POSN_EXP_DT,POSN_STATUS_CD,POSN_CLS_CD,POSN_ORG_CD,POSN_BUDGET_FTE,POSN_TITLE,ROW_REC_START_DT,ROW_REC_END_DT))
            TO '{(d / 'T_POSN_HIST.parquet').as_posix()}' (FORMAT parquet)""")
        con.execute(f"""COPY (SELECT * FROM (VALUES ('P1',DATE '2019-01-01',{open_},NULL::DATE,'x','x',DATE '2019-01-01',{open_}))
            t(EDW_PERS_ID,PERS_EFF_DT,PERS_EXP_DT,BIRTH_DT,SEX_CD,RACE_ETH_CD,ROW_REC_START_DT,ROW_REC_END_DT))
            TO '{(d / 'T_PERS_HIST.parquet').as_posix()}' (FORMAT parquet)""")
        con.execute(f"""COPY (SELECT * FROM (VALUES ('P1',DATE '2019-01-01',{open_},'A','C1',DATE '2019-01-01',DATE '2019-01-01',NULL,NULL,DATE '2019-01-01',{open_}))
            t(EDW_PERS_ID,EMPEE_EFF_DT,EMPEE_EXP_DT,EMPEE_STATUS_CD,EMPEE_CLS_CD,FIRST_HIRE_DT,CUR_HIRE_DT,HOME_ORG_CD,CAMPUS_CD,ROW_REC_START_DT,ROW_REC_END_DT))
            TO '{(d / 'T_EMPEE_HIST.parquet').as_posix()}' (FORMAT parquet)""")
        con.execute(f"""COPY (SELECT * FROM (VALUES ('P1',DATE '2020-07-01','RES','N',DATE '2020-07-10',{open_}))
            t(EDW_PERS_ID,TERM_DT,TERM_REASON_CD,SURS_RETIR_IND,ROW_REC_START_DT,ROW_REC_END_DT))
            TO '{(d / 'T_EMPEE_HIST_5.parquet').as_posix()}' (FORMAT parquet)""")
        con.close()
        mp = write_mapping(M.load_mapping(), self.tmp / "asof.yaml", self.tmp / "pack", "parquet", {"asof": "asof"})
        pairs = [("2020-06-30", "2020-06-30"), ("2020-07-01", "2020-07-01"), ("2020-07-01", "2020-08-15"),
                 ("2020-04-15", "2020-04-30"), ("2020-04-15", "2020-05-01")]
        build("asof", out_root=self.tmp / "out_asof", mapping_file=mp, write_parquet=False, snapshot_pairs=pairs)
        con = duckdb.connect(str(self.tmp / "out_asof" / "integrated_asof.duckdb"), read_only=True)
        rows = con.execute("""SELECT CAST(as_of_date AS VARCHAR), CAST(known_as_of AS VARCHAR), position_id, incumbent_count
                              FROM fact_position_snapshot ORDER BY ALL""").fetchall()
        filled = {(a, k): sorted(p for a2, k2, p, n in rows if (a2, k2) == (a, k) and n > 0) for a, k in pairs}
        con.close()
        self.assertEqual(filled[("2020-06-30", "2020-06-30")], ["Q1", "Q3"])        # inclusive end day counts; P2 not yet keyed
        self.assertEqual(filled[("2020-07-01", "2020-07-01")], ["Q3"])              # day after inclusive end: gone; P2 still unknown
        self.assertEqual(filled[("2020-07-01", "2020-08-15")], ["Q2", "Q3"])        # late-keyed row visible once recorded
        self.assertEqual(filled[("2020-04-15", "2020-04-30")], ["Q1"])              # as believed on 4/30: P3 ended 3/31
        self.assertEqual(filled[("2020-04-15", "2020-05-01")], ["Q1", "Q3"])        # recorded end is exclusive: correction live on 5/1


class TestExplorerPage(unittest.TestCase):
    PAGE = M.PE_ROOT / "output" / "integration" / "integration_explorer.html"

    @unittest.skipUnless(PAGE.exists(), "explorer not rendered")
    def test_page_is_offline_aggregate_and_labelled(self):
        html = self.PAGE.read_text(encoding="utf-8")
        self.assertIn("SYNTHETIC SAMPLE + PUBLIC EXTERNAL DATA", html)
        self.assertIsNone(re.search(r"\b(SYN\d{4,}|SP\d{6}|[QRO]\d{6})\b", html), "synthetic person/position IDs on page")
        self.assertIsNone(re.search(r"<script[^>]+src=|<link[^>]+href=\"http", html), "page must not load external resources")


if __name__ == "__main__":
    unittest.main()
