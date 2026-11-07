"""Tests for the v3 / Data Cookbook source binding (synthetic data only).

    python -m unittest succession_models.tests.test_v3_cookbook -v     # from platform-evaluation/

Covers: the layout resolves (CLI/env, switches); the seven gates pass on the v3 longitudinal pack; the
as-known snapshot on a tiny Cookbook-shaped fixture with a late-keyed correction, a late-keyed exit and a
deleted (D) row; the separation, FTE, pay-range, vacancy and ladder-fallback semantics; and that the v1
path is byte-identical to the pre-v3 code (hashes recorded before the v3 binding was added).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import config  # noqa: E402
import extract as X  # noqa: E402
import snapshot as S  # noqa: E402
import synth_edw  # noqa: E402

PACK = config.PE_ROOT / "sample_datasets" / "v3_cookbook" / "longitudinal"
OPEN = dt.date(9999, 12, 31)
D = dt.date
_TMP: Path | None = None


def setUpModule():
    global _TMP
    _TMP = Path(tempfile.mkdtemp(prefix="succ_v3_test_"))


def tearDownModule():
    shutil.rmtree(_TMP, ignore_errors=True)


def _d(v) -> dt.date:
    """datetime.date of a DuckDB/pandas date value (Timestamp or date)."""
    return pd.Timestamp(v).date()


def _write(d: Path, name: str, rows: list[dict], dates=(), ints=()):
    """Write a Cookbook-shaped table with explicit DATE / INTEGER columns (NULL-only columns need a type)."""
    df = pd.DataFrame(rows)
    fields = []
    for c in df.columns:
        if c in dates:
            fields.append(pa.field(c, pa.date32()))
        elif c in ints:
            fields.append(pa.field(c, pa.int32()))
        elif df[c].dtype == object or df[c].isna().all():
            fields.append(pa.field(c, pa.string()))
        else:
            fields.append(pa.field(c, pa.float64()))
    pq.write_table(pa.Table.from_pandas(df, schema=pa.schema(fields), preserve_index=False), d / f"{name}.parquet")


def build_fixture(d: Path) -> Path:
    """A tiny v3-shaped EDW. All ids and values are invented.

    Person 1 / Q00001 (class Y0010 -> SUCSS 0010): row effective 2020-01-01 keyed late on 2020-01-10 with an
      open end, corrected on 2020-07-05 (closed 2020-06-30); successor row effective 2020-07-01 (class
      Y0011, fte 0.5) keyed on 2020-07-05; a copy keyed in error with effective date 2020-07-03 on
      2020-07-05 and deleted on 2020-07-07 (CUR_INFO_IND = 'D').
    Person 2 / Q00002: hired 2015-03-01, separated 2021-03-01 (TR, retirement) but the termination (job
      Terminated row, closure of the Active row, employee T row) was keyed on 2021-05-15. FTE 1.0 with
      JOB_DETL_APPT_PCT 50 -> effective FTE 0.5.
    Person 3 / Q00003: active since 2010-01-01 (gives the 8 years of history gate G5 needs); also holds an
      overload job Q00006 (job type O) that must not count as a primary position.
    Positions: Q00004 is Cancelled with OPEN_POSN_IND = 'Y' (never a vacancy); Q00005 is Active, open, has no
      job and its class ZLOCL is not in REF_ROLE_FAMILY (ladder fallback JP009).
    """
    d.mkdir(parents=True, exist_ok=True)
    job_dates = ("JOB_DETL_EFF_DT", "JOB_DETL_HIST_EFF_DT", "JOB_DETL_HIST_POST_DT", "JOB_DETL_EXP_DT")

    def job(pid, posn, eff, hist, post, exp, cur, status, cls, fte=1.0, pct=100.0, sal=60000.0, org="U111"):
        return dict(EDW_PERS_ID=pid, POSN_NBR=posn, JOB_SUFFIX="00", JOB_DETL_EFF_DT=eff, JOB_DETL_HIST_EFF_DT=hist,
                    JOB_DETL_HIST_POST_DT=post, JOB_DETL_EXP_DT=exp, JOB_DETL_CUR_INFO_IND=cur, JOB_DETL_STATUS_DESC=status,
                    JOB_DETL_FTE=fte, JOB_DETL_APPT_PCT=pct, JOB_DETL_ANNL_SAL=sal, JOB_DETL_POSN_CLS_CD=cls, ORG_CD=org)
    jobs = [
        job(1, "Q00001", D(2020, 1, 1), D(2020, 1, 10), D(2020, 7, 5), OPEN, "N", "Active", "Y0010"),
        job(1, "Q00001", D(2020, 1, 1), D(2020, 7, 5), D(2020, 7, 5), D(2020, 6, 30), "N", "Active", "Y0010"),
        job(1, "Q00001", D(2020, 7, 1), D(2020, 7, 5), D(2020, 7, 5), OPEN, "Y", "Active", "Y0011", fte=0.5, sal=35000.0),
        job(1, "Q00001", D(2020, 7, 3), D(2020, 7, 5), D(2020, 7, 7), OPEN, "D", "Active", "Y0011", fte=0.5, sal=35000.0),
        job(2, "Q00002", D(2015, 3, 1), D(2015, 3, 1), D(2021, 5, 15), OPEN, "N", "Active", "Y0010", pct=50.0),
        job(2, "Q00002", D(2015, 3, 1), D(2021, 5, 15), D(2021, 5, 15), D(2021, 2, 28), "N", "Active", "Y0010", pct=50.0),
        job(2, "Q00002", D(2021, 3, 1), D(2021, 5, 15), D(2021, 5, 15), OPEN, "Y", "Terminated", "Y0010", pct=50.0),
        job(3, "Q00003", D(2010, 1, 1), D(2010, 1, 1), D(2010, 1, 1), OPEN, "Y", "Active", "Y0011", org="U112"),
        job(3, "Q00006", D(2019, 1, 1), D(2019, 1, 1), D(2019, 1, 1), OPEN, "Y", "Active", "Y0010", org="U112"),
    ]
    _write(d, "T_JOB_DETL_HIST", jobs, job_dates)
    _write(d, "X_JOB_CONTRACT_TYPE", [dict(EDW_PERS_ID=p, POSN_NBR=n, JOB_SUFFIX="00", JOB_CONTRACT_TYPE_CD=t)
                                      for p, n, t in ((1, "Q00001", "P"), (2, "Q00002", "P"), (3, "Q00003", "P"), (3, "Q00006", "O"))])

    def emp(pid, eff, exp, status, post, cur="Y", first=None, term_cd=None, term_dt=None, ret="N"):
        return dict(EDW_PERS_ID=pid, EMPEE_EFF_DT=eff, EMPEE_EXP_DT=exp, EMPEE_STATUS_CD=status, FIRST_HIRE_DT=first or eff,
                    CUR_HIRE_DT=first or eff, TERMN_REASON_CD=term_cd, EMPEE_TERMN_DT=term_dt, EMPEE_RET_IND=ret,
                    EMPEE_CUR_INFO_IND=cur, EMPEE_POST_DT=post)
    emps = [
        emp(1, D(2020, 1, 1), OPEN, "A", D(2020, 1, 10)),
        emp(2, D(2015, 3, 1), D(2021, 2, 28), "A", D(2021, 5, 15), cur="N"),
        emp(2, D(2021, 3, 1), OPEN, "T", D(2021, 5, 15), first=D(2015, 3, 1), term_cd="TR", term_dt=D(2021, 3, 1), ret="Y"),
        emp(2, D(2014, 1, 1), D(2014, 1, 31), "A", D(2014, 2, 5), cur="D"),       # keyed with a wrong date, deleted
        emp(3, D(2010, 1, 1), OPEN, "A", D(2010, 1, 1)),
    ]
    _write(d, "T_EMPEE_HIST", emps, ("EMPEE_EFF_DT", "EMPEE_EXP_DT", "FIRST_HIRE_DT", "CUR_HIRE_DT", "EMPEE_TERMN_DT", "EMPEE_POST_DT"))
    _write(d, "T_EMPEE_HIST_5", [dict(EDW_PERS_ID=2, EMPEE_EFF_DT=D(2021, 3, 1), EMPEE_EXP_DT=OPEN, TERMN_REASON_CD="TR",
                                      EMPEE_TERMN_DT=D(2021, 3, 1), EMPEE_CUR_INFO_IND="Y", EMPEE_5_POST_DT=D(2021, 5, 15))],
           ("EMPEE_EFF_DT", "EMPEE_EXP_DT", "EMPEE_TERMN_DT", "EMPEE_5_POST_DT"))
    _write(d, "T_PERS_HIST", [dict(EDW_PERS_ID=p, PERS_HIST_EFF_DT=e, PERS_EXP_DT=OPEN, BIRTH_DT=b, PERS_CUR_INFO_IND="Y",
                                   PERS_HIST_POST_DT=e, SEX_CD="F", RACE_ETH_RPT_CD="5")
                              for p, e, b in ((1, D(2019, 12, 20), D(1985, 5, 5)), (2, D(2015, 2, 20), D(1958, 2, 2)), (3, D(2009, 12, 1), D(1980, 1, 1)))],
           ("PERS_HIST_EFF_DT", "PERS_EXP_DT", "BIRTH_DT", "PERS_HIST_POST_DT"))

    def posn(n, eff, status, cls, pape, ladder, open_ind, lo, hi, cur="Y"):
        return dict(POSN_NBR=n, POSN_HIST_EFF_DT=eff, POSN_HIST_EXP_DT=OPEN, POSN_STATUS_CD=status, POSN_CLS_CD=cls,
                    PAPE_CIV_SVC_ID=pape, POSN_JOB_PRGS_CD=ladder, OPEN_POSN_IND=open_ind, POSN_MIN_SAL=lo,
                    POSN_MIDPT_SAL=(lo + hi) / 2, POSN_MAX_SAL=hi, POSN_HIST_CUR_INFO_IND=cur, POSN_HIST_POST_DT=eff)
    posns = [
        posn("Q00001", D(2019, 12, 1), "A", "Y0010", "0010", "JP002", "N", 50000.0, 90000.0),
        posn("Q00002", D(2015, 1, 1), "A", "Y0010", "0010", "JP002", "Y", 50000.0, 90000.0),
        posn("Q00003", D(2009, 1, 1), "A", "Y0011", "0011", "JP002", "N", 60000.0, 100000.0),
        posn("Q00004", D(2009, 1, 1), "C", "Y0011", "0011", "JP002", "Y", 60000.0, 100000.0),
        posn("Q00005", D(2018, 1, 1), "A", "ZLOCL", "49901", "JP009", "Y", 70000.0, 110000.0),
        posn("Q00006", D(2018, 1, 1), "A", "Y0010", "0010", "JP002", "N", 50000.0, 90000.0),
        posn("Q00007", D(2018, 1, 1), "A", "Y0010", "0010", "JP002", "Y", 50000.0, 90000.0, cur="D"),   # deleted version
    ]
    _write(d, "T_POSN_HIST", posns, ("POSN_HIST_EFF_DT", "POSN_HIST_EXP_DT", "POSN_HIST_POST_DT"))
    _write(d, "T_POSN_CLS_HIST", [dict(POSN_CLS_CD=c, POSN_CLS_DESC=t, MIN_ANNUAL_AMT=30000.0, MAX_ANNUAL_AMT=90000.0)
                                  for c, t in (("0010", "Accountant I"), ("0011", "Accountant II"), ("ZLOCL", "Local (synthetic)"))])
    _write(d, "REF_ORG", [dict(ORG_CD=o, PARENT_ORG_CD=p, ORG_TITLE=t, ORG_HIER_LEVEL_NBR=l) for o, p, t, l in
                          (("U00", None, "System", 0), ("U10", "U00", "Campus", 1), ("U1A", "U10", "Admin", 2),
                           ("U11", "U1A", "College", 3), ("U111", "U11", "Dept 1", 5), ("U112", "U11", "Dept 2", 5))],
           ints=("ORG_HIER_LEVEL_NBR",))
    _write(d, "REF_ROLE_FAMILY", [dict(CLS_CD="0010", ROLE_FAMILY="Accountant", ROLE_LEVEL=1, CRITICAL_IND="N"),
                                  dict(CLS_CD="0011", ROLE_FAMILY="Accountant", ROLE_LEVEL=2, CRITICAL_IND="Y")], ints=("ROLE_LEVEL",))
    _write(d, "REF_PCLS_SUCSS_XWALK", [dict(JOB_DETL_POSN_CLS_CD=c, POSN_CLS_CD=k) for c, k in (("Y0010", "0010"), ("Y0011", "0011"), ("ZLOCL", "ZLOCL"))])
    (d / "manifest.json").write_text(json.dumps({"synthetic": True, "extract_date": "2021-12-31"}))
    return d


class TestLayoutResolves(unittest.TestCase):
    def test_default_is_v1_and_unchanged(self):
        name, smap, sql = config.resolve_layout(None, env={})
        self.assertEqual(name, "v1")
        self.assertIs(smap, config.SOURCE_MAP)
        self.assertEqual(sql, X.SQL_PATH)
        self.assertEqual(X.layout_sql(smap), (X.SQL_PATH, {}))

    def test_v3_by_argument_and_by_env(self):
        for args in (("v3_cookbook", {}), (None, {"SUCC_LAYOUT": "v3_cookbook"})):
            name, smap, sql = config.resolve_layout(*args)
            self.assertEqual(name, "v3_cookbook")
            self.assertTrue(sql.exists() and sql.name == "extract_v3_cookbook.sql")
            self.assertEqual(smap["tables"]["term"]["file"], "T_EMPEE_HIST")
            self.assertEqual(smap["tables"]["term"]["rec_cols"]["rec_start"], "EMPEE_POST_DT")
            self.assertEqual(smap["tables"]["job"]["status_values"], {"A": "Active", "T": "Terminated"})
            self.assertEqual(smap["unit_level"], 3)
            self.assertEqual(smap["switches"], {k: v[0] for k, v in config.V3_SWITCHES.items()})
        self.assertIsNot(config.resolve_layout("v3_cookbook")[1], config.SOURCE_MAP_V3_COOKBOOK)   # a copy

    def test_switches(self):
        _, smap, _ = config.resolve_layout("v3_cookbook", env={"SUCC_V3_TERM_SOURCE": "T_EMPEE_HIST_5",
                                                               "SUCC_V3_INPLACE_KNOWN_FROM": "post_dt",
                                                               "SUCC_V3_JOB_CHANGE_DATE": "JOB_DETL_HIST_EFF_DT"})
        self.assertEqual(smap["tables"]["term"]["file"], "T_EMPEE_HIST_5")
        self.assertEqual(smap["tables"]["term"]["rec_cols"]["rec_start"], "EMPEE_5_POST_DT")
        self.assertEqual(smap["tables"]["job"]["cols"]["eff_dt"], "JOB_DETL_HIST_EFF_DT")
        tok = config.v3_sql_tokens(smap["switches"])
        self.assertEqual(tok["JOB_REC_START"], "JOB_DETL_HIST_POST_DT")
        self.assertEqual(tok["EMPEE_REC_START"], "EMPEE_POST_DT")
        with self.assertRaises(ValueError):
            config.resolve_layout("v3_cookbook", env={"SUCC_V3_TERM_SOURCE": "T_NOPE"})
        with self.assertRaises(ValueError):
            config.resolve_layout("v9", env={})

    def test_v3_sql_renders_every_token(self):
        _, smap, sql = config.resolve_layout("v3_cookbook", env={})
        stm = X.statements(sql.read_text(), "edw", config.HISTORY_START, D(2027, 1, 31), X.layout_sql(smap)[1])
        self.assertEqual([n for n, _ in stm], ["T_PERS_HIST", "X_PROTECTED_ATTR", "T_EMPEE_HIST", "T_EMPEE_HIST_5", "T_JOB_DETL_HIST",
                                               "T_POSN_HIST", "T_POSN_CLS_HIST", "REF_ORG", "REF_ROLE_FAMILY", "X_LADDER"])
        with self.assertRaises(ValueError):          # the v3 SQL cannot be rendered without its tokens
            X.statements(sql.read_text(), "edw", config.HISTORY_START, D(2027, 1, 31))


@unittest.skipUnless(PACK.exists(), "v3 cookbook pack not present")
class TestGatesOnV3Pack(unittest.TestCase):
    def test_all_seven_gates_pass_on_longitudinal(self):
        _, smap, _ = config.resolve_layout("v3_cookbook", env={})
        ext = _TMP / "pack_extract"
        counts = X.run_duckdb(PACK, ext, extract_date=D(2027, 1, 31), source_map=smap)
        self.assertEqual(counts["T_JOB_DETL_HIST"], 36811)          # every version kept, D rows included
        self.assertEqual(counts["T_EMPEE_HIST"], 3888 - 10 - 12)    # 10 deleted rows and 12 rows effective after the extract date dropped
        gates = X.validate(ext, smap)
        self.assertEqual({k: v["status"] for k, v in gates.items() if k.startswith("G")},
                         {f"G{i}_{n}": "PASS" for i, n in enumerate(("required_columns", "no_identity_columns", "interval_order", "row_versions",
                                                                     "history_depth", "role_family_coverage", "one_primary_job"), 1)}, gates)
        self.assertEqual(gates["I1_retro_keying_rate"]["status"], "INFO")
        man = json.loads((ext / "manifest.json").read_text())
        self.assertEqual(man["layout"], "v3_cookbook")
        self.assertTrue(man["synthetic"])
        # deleted job versions are known from their start until the deletion post date and are never current
        j = pq.read_table(ext / "T_JOB_DETL_HIST.parquet").to_pandas()
        d = j[j["JOB_DETL_CUR_INFO_IND"] == "D"]
        self.assertEqual(len(d), 112)
        self.assertTrue((d["ROW_REC_END_DT"] == d["JOB_DETL_HIST_POST_DT"]).all())
        self.assertTrue((j[j["JOB_DETL_CUR_INFO_IND"] == "Y"]["ROW_REC_END_DT"] == OPEN).all())
        self.assertTrue(j["SUCSS_CLS_CD"].str.match(r"^[0-9]{4}$|^[A-Z]{5}$").all())

    def test_alternative_change_date_is_caught_by_the_gates(self):
        """Reading JOB_DETL_HIST_EFF_DT as the change date is wrong for this pack, and G3/G4 say so."""
        _, smap, _ = config.resolve_layout("v3_cookbook", env={"SUCC_V3_JOB_CHANGE_DATE": "JOB_DETL_HIST_EFF_DT"})
        ext = _TMP / "pack_extract_alt"
        X.run_duckdb(PACK, ext, extract_date=D(2027, 1, 31), source_map=smap)
        gates = X.validate(ext, smap)
        self.assertEqual(gates["G3_interval_order"]["status"], "FAIL")
        self.assertEqual(gates["G4_row_versions"]["status"], "FAIL")


class TestAsKnownOnFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.edw = build_fixture(_TMP / "fixture_edw")
        cls.ext = _TMP / "fixture_extract"
        _, cls.smap, _ = config.resolve_layout("v3_cookbook", env={})
        X.run_duckdb(cls.edw, cls.ext, extract_date=D(2021, 12, 31), source_map=cls.smap)
        cls.gates = X.validate(cls.ext, cls.smap)
        cls.con = S.open_source(cls.ext, cls.smap)

    def known(self, k, d):
        return sorted(self.con.execute(f"""SELECT eff_dt, fte FROM v_job WHERE pers_id = 1 AND rec_start <= DATE '{k}' AND DATE '{k}' < rec_end
                                           AND eff_dt <= DATE '{d}' AND exp_dt >= DATE '{d}'""").fetchall())

    def feat(self, d):
        f = S.incumbents_asof(self.con, [d])
        return f.set_index("pers_id")

    def test_gates_pass_on_fixture(self):
        self.assertFalse([k for k, v in self.gates.items() if v["status"] == "FAIL"], self.gates)

    def test_lineage_reconstructs_as_known_versions(self):
        self.assertEqual(self.known("2020-01-05", "2020-01-05"), [])                                  # not keyed yet
        self.assertEqual(self.known("2020-07-02", "2020-07-02"), [(D(2020, 1, 1), 1.0)])              # January row still open as known then
        self.assertEqual(self.known("2020-07-06", "2020-07-04"), [(D(2020, 7, 1), 0.5), (D(2020, 7, 3), 0.5)])  # D row visible before deletion
        self.assertEqual(self.known("2020-07-08", "2020-07-04"), [(D(2020, 7, 1), 0.5)])              # deleted
        self.assertEqual(self.known("9999-12-30", "2020-07-02"), [(D(2020, 7, 1), 0.5)])

    def test_features_follow_what_was_known(self):
        self.assertNotIn(1, self.feat(D(2020, 1, 5)).index)
        f = self.feat(D(2020, 7, 2)).loc[1]
        self.assertEqual((f["class_cd"], f["fte"], f["role_level"]), ("0010", 1.0, 1))
        self.assertAlmostEqual(f["pay_pos"], (60000 - 50000) / 40000)     # position range 50-90k, not the class range 30-90k
        self.assertEqual(f["unit_cd"], "U11")                              # level-3 college under system root, campus and admin
        f = self.feat(D(2020, 7, 6)).loc[1]
        self.assertEqual((f["class_cd"], f["fte"], f["critical_ind"]), ("0011", 0.5, "Y"))
        self.assertEqual(_d(f["role_start"]), D(2020, 1, 1))
        f = self.feat(D(2020, 7, 8)).loc[1]
        self.assertEqual((f["class_cd"], f["fte"]), ("0011", 0.5))

    def test_late_keyed_exit_invisible_until_keyed_and_appt_pct_applied(self):
        f = self.feat(D(2021, 4, 1))
        self.assertIn(2, f.index)                                           # exit effective 03-01 keyed 05-15: still an incumbent
        self.assertAlmostEqual(f.loc[2, "fte"], 0.5)                        # 1.0 x 50 / 100
        self.assertAlmostEqual(f.loc[2, "service_years"], (D(2021, 4, 1) - D(2015, 3, 1)).days / 365.25)  # employee row known from eff_dt
        self.assertNotIn(2, self.feat(D(2021, 6, 1)).index)
        sp = S.spells(self.con, D(2021, 4, 1)).set_index(["pers_id", "posn_nbr"])
        self.assertTrue(pd.isna(sp.loc[(2, "Q00002"), "exit_dt"]))
        sp = S.spells(self.con).set_index(["pers_id", "posn_nbr"])
        self.assertEqual((_d(sp.loc[(2, "Q00002"), "exit_dt"]), sp.loc[(2, "Q00002"), "cause"]), (D(2021, 3, 1), "SEP"))
        self.assertEqual(len(sp.loc[1]), 1)                                 # the D row never becomes a spell
        self.assertNotIn((3, "Q00006"), sp.index)                            # overload job is not a primary position
        term = self.con.sql("SELECT pers_id, term_dt, term_reason_cd, surs_retir_ind, rec_start FROM v_term WHERE term_dt IS NOT NULL").fetchall()
        self.assertEqual(term, [(2, D(2021, 3, 1), "TR", "Y", D(2021, 5, 15))])

    def test_vacancy_uses_status_and_open_indicator(self):
        v = S.vacant_asof(self.con, D(2021, 12, 31)).set_index("posn_nbr")
        self.assertEqual(sorted(v.index), ["Q00002", "Q00005"])              # Q00004 is Cancelled, Q00007 was deleted
        self.assertEqual((v.loc["Q00005", "role_family"], v.loc["Q00005", "role_level"], v.loc["Q00005", "critical_ind"]), ("JP009", 1, "N"))
        roles = pd.read_parquet(self.ext / "REF_ROLE_FAMILY.parquet")
        self.assertEqual(roles["ROLE_SOURCE"].value_counts().to_dict(), {"REF_ROLE_FAMILY": 2, "POSN_JOB_PRGS_CD": 1})

    def test_secured_term_source_and_post_date_mode(self):
        _, smap, _ = config.resolve_layout("v3_cookbook", env={"SUCC_V3_TERM_SOURCE": "T_EMPEE_HIST_5", "SUCC_V3_INPLACE_KNOWN_FROM": "post_dt"})
        ext = _TMP / "fixture_extract_5"
        X.run_duckdb(self.edw, ext, extract_date=D(2021, 12, 31), source_map=smap)
        self.assertFalse([k for k, v in X.validate(ext, smap).items() if v["status"] == "FAIL"])
        con = S.open_source(ext, smap)
        self.assertEqual(con.sql("SELECT pers_id, term_dt, surs_retir_ind, rec_start FROM v_term").fetchall(), [(2, D(2021, 3, 1), "Y", D(2021, 5, 15))])
        sp = S.spells(con).set_index(["pers_id", "posn_nbr"])
        self.assertEqual(sp.loc[(2, "Q00002"), "cause"], "SEP")
        # post_dt mode: person 2's surviving Active employee row was rewritten on 2021-05-15, so at 2021-04-01 it is
        # unknown and service falls back to the role start (the label-correlated missingness the default avoids)
        f = S.incumbents_asof(con, [D(2021, 4, 1)]).set_index("pers_id")
        self.assertEqual(_d(f.loc[2, "first_hire_dt"]), D(2015, 3, 1))       # equal here only because role start == hire
        self.assertEqual(con.sql("SELECT rec_start FROM v_employee WHERE pers_id = 2 AND status_cd = 'A'").fetchall(), [(D(2021, 5, 15),)])


class TestV1PathUnchanged(unittest.TestCase):
    """Hashes recorded with the pre-v3 code on the test-scale v1 fixture (seed SEED, scale 0.3)."""
    EXPECT = {
        "REF_JOB_CLASS.parquet": "5643c7ac5d8dc3478e8682eb13f85dd57024a323cfd6125146bd7058d0af81ec",
        "REF_ORG.parquet": "fab4ca1aa53770d1e59b611a99b92fdb700167305fb3a7b6a580793e977739c5",
        "REF_ROLE_FAMILY.parquet": "3100331960ea939f3161705c96f1831acd940bf08973848e5af93b9cc317804e",
        "T_EMPEE_HIST.parquet": "2315a347fdc04c50b21287e592a296103102838c0f39a9d8aff1da58b53bdc47",
        "T_EMPEE_HIST_5.parquet": "debf67b88f0801f9368ff245f4996eaa5f78051640d78447aa0d24d122b51499",
        "T_JOB_DETL_HIST.parquet": "c69b47cfa4021b69973d610e3efd1b60e385ba33b957fb57d79a3dd048d838d1",
        "T_PERS_HIST.parquet": "eb996c72a5f3127d744cb9d5417e8180d05691360dd2707ddcc84b385b1c9f69",
        "T_POSN_HIST.parquet": "d8007e1f010dedb70e8964d4023f4d50f2a6675abe3de9a6b56f45250d623f77",
        "X_PROTECTED_ATTR.parquet": "c30c933fb2f7ac1733b119265236e625acb212f152d36f5de8c8291005b401a4",
        "features_2018-07-01": "1215ae46b20e8c7a7c8580369bff508817d160a330710f7d30b372d2f35381ba",
        "spells_latest": "929794f5c4f2a6cebcbe6b11383fd01e1bd8bbf70afd839c919853b3f7ad45af",
        "sql_rendered": "159a4024cc64a02ec523b1a8927db975dd6ad694a5b401eb39b3aba478fd4b38",
    }

    def test_v1_extract_features_spells_and_sql_hashes(self):
        edw, ext = _TMP / "v1_edw", _TMP / "v1_extract"
        synth_edw.generate(config.SEED, 0.3, edw)
        X.run_duckdb(edw, ext)                                   # default layout, no source_map argument
        got = {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(ext.glob("*.parquet"))}
        con = S.open_source(ext)
        feat = S.incumbents_asof(con, [D(2018, 7, 1)]).sort_values(["pers_id", "posn_nbr"]).reset_index(drop=True)
        self.assertEqual(len(feat), 973)
        got["features_2018-07-01"] = hashlib.sha256(feat.to_csv(index=False).encode()).hexdigest()
        sp = S.spells(con).sort_values(["pers_id", "start_dt", "posn_nbr"]).reset_index(drop=True)
        got["spells_latest"] = hashlib.sha256(sp.to_csv(index=False).encode()).hexdigest()
        stm = X.statements(X.SQL_PATH.read_text(), "edw", config.HISTORY_START, config.EXTRACT_DATE)
        got["sql_rendered"] = hashlib.sha256(json.dumps(stm).encode()).hexdigest()
        self.assertEqual(got, self.EXPECT)
        self.assertNotIn("layout", json.loads((ext / "manifest.json").read_text()))


if __name__ == "__main__":
    unittest.main()
