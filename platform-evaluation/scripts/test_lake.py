"""Invariant tests for the public HR data lake.

Run after scripts/lake_acquire.py and scripts/lake_build.py:
    python -m unittest scripts/test_lake.py -v
Tests skip (not pass) when the lake has not been built locally.
"""
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "lake" / "hr_public.duckdb"
MANIFEST = ROOT / "lake" / "manifests" / "silver_manifest.json"

try:
    import duckdb
except ImportError:  # pragma: no cover
    duckdb = None


@unittest.skipUnless(duckdb and DB.exists(), "lake not built locally")
class LakeInvariants(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.con = duckdb.connect(str(DB), read_only=True)

    @classmethod
    def tearDownClass(cls):
        cls.con.close()

    def one(self, sql):
        return self.con.sql(sql).fetchall()[0]

    def assertUnique(self, table, cols):
        dupes = self.one(f"SELECT count(*) FROM (SELECT {cols} FROM {table} GROUP BY {cols} HAVING count(*) > 1)")[0]
        self.assertEqual(dupes, 0, f"{table} not unique on {cols}")

    # --- manifest ---------------------------------------------------------------
    def test_manifest_matches_catalog(self):
        tables = json.loads(MANIFEST.read_text())["tables"]
        for name, meta in tables.items():
            self.assertEqual(self.one(f"SELECT count(*) FROM {name}")[0], meta["rows"], name)
            self.assertTrue(all(meta["source_sha256"].values()), f"{name} has a source without a hash")

    # --- keys and grain -----------------------------------------------------------
    def test_primary_keys(self):
        self.assertUnique("onet_occupation_data", "onetsoc_code")
        self.assertUnique("onet_task_statements", "onetsoc_code, task_id")
        self.assertUnique("onet_soc_crosswalk", "onetsoc_code, soc_2018_code")
        self.assertUnique("ipeds_hd2024", "unitid")
        self.assertUnique("ipeds_s2023_oc", "unitid, staffcat")
        self.assertUnique("ipeds_sal2023_is", "unitid, arank")
        self.assertUnique("ipeds_sal2023_nis", "unitid")
        self.assertUnique("qcew_colleges_annual", "area_fips, own_code, industry_code, year, qtr, size_code")
        self.assertUnique("gold_qwi_il_higher_ed_flows", "year, quarter")
        self.assertUnique("gold_institution_panel", "unitid")

    def test_codes_keep_leading_zeros(self):
        # Alabama state FIPS 01000 must survive as a string.
        self.assertEqual(self.one("SELECT typeof(area_fips) FROM qcew_colleges_annual LIMIT 1")[0], "VARCHAR")
        self.assertGreater(self.one("SELECT count(*) FROM qcew_colleges_annual WHERE area_fips = '01000'")[0], 0)
        self.assertEqual(self.one("SELECT typeof(unitid) FROM ipeds_hd2024 LIMIT 1")[0], "VARCHAR")

    # --- business facts that must hold -------------------------------------------
    def test_uofi_campuses_present(self):
        rows = self.con.sql("SELECT unitid, uofi_campus FROM gold_institution_panel "
                            "WHERE panel_role = 'uofi_system' ORDER BY unitid").fetchall()
        self.assertEqual(rows, [("145600", "UIC"), ("145637", "UIUC"), ("148654", "UIS"),
                                ("149587", "System Offices")])
        self.assertEqual(self.one("SELECT count(*) FROM gold_institution_panel")[0], 19)

    def test_noninstructional_total_is_not_double_counted(self):
        # Group 01 is the institution total; groups 02-14 must not exceed it.
        bad = self.one("""
            SELECT count(*) FROM (
              SELECT unitid,
                     max(CASE WHEN occupation_group_code = '01' THEN fulltime_staff END) AS total,
                     sum(CASE WHEN occupation_group_code <> '01' THEN fulltime_staff END) AS parts
              FROM gold_ipeds_noninstructional_pay GROUP BY unitid) t
            WHERE parts > total""")[0]
        self.assertEqual(bad, 0)

    def test_occupation_profile_does_not_fan_out(self):
        self.assertEqual(self.one("SELECT count(*) FROM gold_occupation_profile")[0],
                         self.one("SELECT count(*) FROM onet_occupation_data")[0])

    def test_sucss_candidates_are_labeled_unreviewed(self):
        self.assertEqual(self.one("SELECT count(DISTINCT mapping_status) FROM gold_sucss_onet_candidates")[0], 1)
        self.assertEqual(self.one("SELECT max(mapping_status) FROM gold_sucss_onet_candidates")[0],
                         "unreviewed_lexical_suggestion")

    def test_suppressed_qcew_values_are_null_not_zero(self):
        self.assertEqual(self.one("SELECT count(*) FROM gold_qcew_higher_ed_trend "
                                  "WHERE disclosure_code = 'N' AND employment IS NOT NULL")[0], 0)

    def test_qwi_rates_are_rates(self):
        lo, hi = self.one("SELECT min(stable_turnover_rate), max(stable_turnover_rate) FROM gold_qwi_il_higher_ed_flows")
        self.assertGreaterEqual(lo, 0)
        self.assertLess(hi, 1)


CONTRACT = ROOT / "data" / "lake" / "contract"


@unittest.skipUnless(duckdb and (CONTRACT / "ipeds_institution.parquet").exists(), "contract layer not built")
class ContractInvariants(unittest.TestCase):
    """The contract layer must reproduce IPEDS published totals exactly (no double counting)."""

    @classmethod
    def setUpClass(cls):
        cls.con = duckdb.connect()
        for p in CONTRACT.glob("*.parquet"):
            cls.con.sql(f"CREATE VIEW c_{p.stem} AS SELECT * FROM '{p}'")
        silver = ROOT / "data" / "lake" / "silver"
        for t in ("ipeds_s2023_oc", "ipeds_sal2023_nis", "ipeds_sal2023_is", "ipeds_eap2023"):
            cls.con.sql(f"CREATE VIEW s_{t} AS SELECT * FROM '{silver / (t + '.parquet')}'")

    def zero(self, sql, msg):
        self.assertEqual(self.con.sql(sql).fetchall()[0][0], 0, msg)

    def test_every_table_has_provenance(self):
        for p in CONTRACT.glob("*.parquet"):
            cols = self.con.sql(f"SELECT * FROM 'c_{p.stem}' LIMIT 0".replace("'", "")).columns
            self.assertIn("source_id", cols, p.stem)
            self.assertIn("source_vintage", cols, p.stem)

    def test_staff_detail_partition_equals_grand_total(self):
        self.zero("""SELECT count(*) FROM (
              SELECT unitid, left(staffcat_code, 1) AS ftpt,
                     sum(CASE WHEN NOT is_category_total THEN headcount END) AS parts,
                     max(CASE WHEN category_level = 'total' THEN headcount END) AS total
              FROM c_ipeds_staff_by_occupation
              WHERE sex = 'Total' AND race_ethnicity = 'Total' AND category_level <> 'graduate_assistant'
              GROUP BY 1, 2) WHERE total IS NOT NULL AND parts <> total""", "staff detail != total")

    def test_staff_totals_match_published(self):
        self.zero("""SELECT count(*) FROM c_ipeds_staff_by_occupation a JOIN s_ipeds_s2023_oc b
              ON a.unitid = b.unitid AND a.staffcat_code = CAST(b.staffcat AS VARCHAR)
              WHERE a.sex = 'Total' AND a.race_ethnicity = 'Total' AND a.headcount <> b.hrtotlt""", "staff totals")

    def test_race_detail_sums_to_total(self):
        self.zero("""SELECT count(*) FROM (
              SELECT unitid, staffcat_code, sex,
                     sum(CASE WHEN race_ethnicity <> 'Total' THEN headcount END) AS r,
                     max(CASE WHEN race_ethnicity = 'Total' THEN headcount END) AS t
              FROM c_ipeds_staff_by_occupation GROUP BY 1, 2, 3) WHERE r <> t""", "race detail != total")

    def test_noninstructional_salary_partition(self):
        self.zero("""SELECT count(*) FROM (SELECT unitid, sum(staff_count) n, sum(salary_outlays) o
              FROM c_ipeds_salary_noninstructional GROUP BY 1) a JOIN s_ipeds_sal2023_nis b USING (unitid)
              WHERE a.n <> b.sanin01 OR a.o <> b.sanit01""", "NIS groups != institution total")

    def test_instructional_salary_partition(self):
        self.zero("""SELECT count(*) FROM (SELECT unitid, arank_code, sum(staff_count) n
              FROM c_ipeds_salary_instructional GROUP BY 1, 2) a JOIN s_ipeds_sal2023_is b
              ON a.unitid = b.unitid AND a.arank_code = CAST(b.arank AS VARCHAR) WHERE a.n <> b.satotlt""",
                  "contract lengths != rank total")

    def test_eap_partition(self):
        self.zero("""SELECT count(*) FROM (SELECT unitid,
                     sum(CASE WHEN NOT is_category_total THEN total_employees END) s,
                     max(CASE WHEN eapcat_code = '10000' THEN total_employees END) t
              FROM c_ipeds_employees_by_position GROUP BY 1) WHERE t IS NOT NULL AND s <> t""", "EAP partition")

    def test_qcew_suppressed_is_null(self):
        self.zero("SELECT count(*) FROM c_qcew_industry WHERE disclosure_code = 'N' AND month3_emplvl IS NOT NULL",
                  "suppressed QCEW value leaked")

    def test_contract_keys_unique(self):
        for table, cols in {"onet_occupation": "onetsoc_code", "onet_task_statement": "onetsoc_code, task_id",
                            "ipeds_institution": "unitid", "sucss_class": "source_record_id",
                            "qcew_industry": "area_fips, own_code, industry_code, size_code, year, qtr",
                            "qwi_higher_ed": "geography, industry, ownercode, sex, agegrp, year, quarter"}.items():
            self.zero(f"SELECT count(*) FROM (SELECT {cols} FROM c_{table} GROUP BY {cols} HAVING count(*) > 1)",
                      f"{table} key not unique")


if __name__ == "__main__":
    unittest.main()
