"""Tests for the multi-year IPEDS peer benchmark.

    python peer_benchmarks/acquire.py && python peer_benchmarks/build.py && python peer_benchmarks/render_html.py
    python -m unittest discover -s peer_benchmarks/tests -v      # from platform-evaluation/
"""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

import duckdb
import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parent
ART = HERE / "artifacts"
YEARS = list(range(2015, 2024))
PANEL_SIZE = 19
PENN_STATE = "214777"


def q(sql: str):
    return duckdb.sql(sql.replace("@", str(ART) + "/")).fetchall()


class Reconciliation(unittest.TestCase):
    def test_parsed_files_match_published_dictionary_sums(self):
        rows = q("SELECT file, variable, published_sum, parsed_sum, published_n, parsed_n FROM '@published_reconciliation.parquet'")
        self.assertGreaterEqual(len(rows), 100)
        for file, var, pub, parsed, pn, n in rows:
            with self.subTest(file=file, var=var):
                self.assertAlmostEqual(pub, parsed, delta=0.5)
                self.assertEqual(pn, n)

    def test_every_year_reconciled_for_each_family(self):
        fam = q("""SELECT regexp_extract(file, '^([A-Z]+)\\d{4}(_?[A-Z]*)', 1) || regexp_extract(file, '\\d{4}(.*)$', 1) AS fam,
                          count(DISTINCT fall_year) FROM '@published_reconciliation.parquet' GROUP BY 1""")
        self.assertEqual({f for f, _ in fam}, {"S_OC", "S_IS", "S_NH", "SAL_IS", "SAL_NIS", "EFA", "EFIA", "EFFY"})
        for f, n in fam:
            self.assertEqual(n, len(YEARS), f)

    def test_occupation_partition_reproduces_published_totals_every_year(self):
        rows = q("SELECT year, count(*), count(*) FILTER (WHERE published_grand_total = sum_groups_all "
                 "AND published_full_time = sum_groups_full_time AND published_part_time = sum_groups_part_time) "
                 "FROM '@panel_total_reconciliation.parquet' GROUP BY year ORDER BY year")
        self.assertEqual([r[0] for r in rows], YEARS)
        for year, n, ok in rows:
            self.assertEqual(n, ok, year)
            self.assertGreaterEqual(n, PANEL_SIZE - 1, year)  # Penn State has no Fall 2020/2021 HR

    def test_other_partitions_reproduce_published_totals(self):
        bad = q("""SELECT unitid, year FROM '@panel_total_reconciliation.parquet'
                   WHERE published_fulltime_instructional IS DISTINCT FROM sum_tenure_status
                      OR published_fulltime_new_hires IS DISTINCT FROM sum_new_hire_groups
                      OR published_noninstructional_n IS DISTINCT FROM sum_noninstructional_n
                      OR abs(published_noninstructional_outlays - sum_noninstructional_outlays) > 0.5""")
        self.assertEqual(bad, [])

    def test_metrics_table_matches_published_grand_total(self):
        self.assertEqual(q("SELECT count(*) FROM '@fact_institution_metrics.parquet' "
                           "WHERE staff_total IS DISTINCT FROM published_grand_total"), [(0,)])


class Grain(unittest.TestCase):
    KEYS = {
        "dim_institution_year": "unitid, year",
        "fact_staff_occupation": "unitid, year, group_code, ftpt",
        "fact_staff_totals": "unitid, year",
        "fact_faculty_tenure": "unitid, year, tenure_status_code",
        "fact_new_hires": "unitid, year, group_code",
        "fact_faculty_salary": "unitid, year, arank_code",
        "fact_noninstructional_pay": "unitid, year, group_code",
        "fact_enrollment": "unitid, year",
        "fact_institution_metrics": "unitid, year",
        "cpi_academic_year": "fall_year",
    }

    def test_primary_keys_unique(self):
        for t, k in self.KEYS.items():
            with self.subTest(table=t):
                total, distinct = q(f"SELECT count(*), count(DISTINCT ({k})) FROM '@{t}.parquet'")[0]
                self.assertEqual(total, distinct)

    def test_no_fan_out_in_panel_level_tables(self):
        for t in ("dim_institution_year", "fact_enrollment", "fact_institution_metrics"):
            self.assertEqual(q(f"SELECT count(*) FROM '@{t}.parquet'"), [(PANEL_SIZE * len(YEARS),)], t)

    def test_enrollment_has_one_total_row_per_source(self):
        # A fan-out from EF/EFFY level rows would inflate FTE well beyond headcount.
        self.assertEqual(q("SELECT count(*) FROM '@fact_enrollment.parquet' WHERE fte12_total > 1.5 * unduplicated_12mo_headcount"),
                         [(0,)])

    def test_salary_groups_exclude_total_rows(self):
        self.assertEqual(q("SELECT count(*) FROM '@fact_noninstructional_pay.parquet' WHERE group_code IN ('01', '100', '210')"),
                         [(0,)])


class Codes(unittest.TestCase):
    def test_codes_are_strings_with_leading_zeros(self):
        for t in ("dim_institution_year", "fact_staff_occupation", "fact_faculty_salary", "fact_noninstructional_pay",
                  "fact_new_hires", "comparability_flags"):
            schema = pq.read_schema(ART / f"{t}.parquet")
            self.assertEqual(str(schema.field("unitid").type), "string", t)
        self.assertEqual(q("SELECT count(*) FROM '@dim_institution_year.parquet' WHERE length(unitid) <> 6"), [(0,)])
        fips = dict(q("SELECT DISTINCT unitid, county_fips FROM '@dim_institution_year.parquet' WHERE year = 2023"))
        self.assertEqual(fips["110662"], "06037")  # UCLA, Los Angeles County: leading zero kept
        self.assertTrue(all(re.fullmatch(r"\d{5}", v) for v in fips.values()))
        self.assertEqual(sorted(r[0] for r in q("SELECT DISTINCT arank_code FROM '@fact_faculty_salary.parquet'")),
                         ["1", "2", "3", "4", "5", "6", "7"])
        self.assertEqual(q("SELECT count(*) FROM '@fact_staff_occupation.parquet' WHERE NOT regexp_full_match(staffcat_code, '[23]\\d{3}')"),
                         [(0,)])


class Comparability(unittest.TestCase):
    def test_soc_2018_flag_on_every_occupation_year_from_2018(self):
        n = q("SELECT count(*) FROM '@comparability_flags.parquet' WHERE flag_code = 'SOC2018_CATEGORY_BASIS' AND domain = 'staff_occupation'")
        self.assertEqual(n, [(PANEL_SIZE * len([y for y in YEARS if y >= 2018]),)])
        self.assertEqual(q("SELECT count(*) FROM '@fact_staff_occupation.parquet' WHERE soc_basis <> "
                           "CASE WHEN year >= 2018 THEN 'SOC 2018' ELSE 'SOC 2010' END"), [(0,)])

    def test_method_and_reporting_flags_present(self):
        codes = {r[0] for r in q("SELECT DISTINCT flag_code FROM '@comparability_flags.parquet'")}
        for c in ("SOC2018_CATEGORY_BASIS", "EQ9_METHOD_2015", "PARENT_INCLUDES_CHILD_CAMPUSES", "MISSING_HR_YEAR",
                  "LEVEL_SHIFT_TOTAL_STAFF", "LEVEL_SHIFT_GROUP", "NO_STUDENT_FTE"):
            self.assertIn(c, codes)
        ps = q(f"SELECT year FROM '@comparability_flags.parquet' WHERE unitid = '{PENN_STATE}' AND severity = 'exclude' ORDER BY 1")
        self.assertEqual(sorted({r[0] for r in ps}), [2019, 2020, 2021])

    def test_2015_salary_marked_as_derived(self):
        rows = q("SELECT DISTINCT year, equating_method FROM '@fact_faculty_salary.parquet' ORDER BY 1")
        self.assertTrue(rows[0][1].startswith("derived"))
        self.assertTrue(all(m.startswith("reported") for y, m in rows if y > 2015))

    def test_2015_new_hire_window_flagged_and_not_charted(self):
        self.assertEqual(q("SELECT count(*) FROM '@comparability_flags.parquet' WHERE flag_code = 'NEW_HIRE_WINDOW_2015'"),
                         [(PANEL_SIZE,)])
        self.assertEqual(q("SELECT DISTINCT hire_window FROM '@fact_new_hires.parquet' WHERE year = 2015"),
                         [("Jul 1-Oct 31 (4 months)",)])
        d = json.loads((ART / "peer_trends.json").read_text())
        for m in d["metrics"]:
            if m["family"] in ("new_hire_rate", "new_hire_rate_all"):
                self.assertTrue(all(v[0] is None for v in m["values"].values()), m["id"])

    def test_imputation_flags_carried(self):
        for t in ("fact_staff_occupation", "fact_faculty_tenure", "fact_faculty_salary", "fact_noninstructional_pay"):
            self.assertEqual(q(f"SELECT count(*) FROM '@{t}.parquet' WHERE imputation_flag IS NULL"), [(0,)], t)

    def test_excluded_years_are_not_charted(self):
        d = json.loads((ART / "peer_trends.json").read_text())
        staff = next(m for m in d["metrics"] if m["id"] == "staff_total")
        ps = dict(zip(d["years"], staff["values"][PENN_STATE]))
        self.assertIsNone(ps[2019])
        self.assertIsNotNone(ps[2018])
        self.assertEqual([b["n"] for b in staff["band"] if b["year"] in (2019, 2020, 2021)], [14, 14, 14])
        for m in d["metrics"]:
            for b in m["band"]:
                if b["median"] is not None:
                    self.assertLessEqual(b["p25"], b["median"])
                    self.assertLessEqual(b["median"], b["p75"])

    def test_peer_band_excludes_uofi(self):
        d = json.loads((ART / "peer_trends.json").read_text())
        self.assertEqual(len(d["peers"]), 15)
        self.assertFalse(set(d["peers"]) & set(d["uofi"]))


class Provenance(unittest.TestCase):
    def test_every_download_hashed(self):
        man = json.loads((HERE / "manifests" / "acquisition_manifest.json").read_text())
        self.assertGreaterEqual(len(man["files"]), 199)
        for r in man["files"]:
            with self.subTest(file=r["filename"]):
                self.assertIn(r["status"], ("downloaded", "cached"))
                self.assertRegex(r["sha256"], r"^[0-9a-f]{64}$")
                self.assertGreater(r["bytes"], 0)

    def test_cpi_base_year(self):
        rows = dict(q("SELECT fall_year, to_2023_24_dollars FROM '@cpi_academic_year.parquet'"))
        self.assertEqual(sorted(rows), YEARS)
        self.assertEqual(rows[2023], 1.0)
        self.assertTrue(all(rows[y] >= rows[y + 1] for y in YEARS[:-1]))

    def test_html_is_offline(self):
        html = (ROOT / "output" / "peer_benchmarks" / "peer_trends.html").read_text()
        self.assertNotRegex(html, r"""(src|href)\s*=\s*["']https?://""")
        self.assertIn("prefers-color-scheme: dark", html)
        self.assertIn("not a pay-equity finding", html)


if __name__ == "__main__":
    unittest.main()
