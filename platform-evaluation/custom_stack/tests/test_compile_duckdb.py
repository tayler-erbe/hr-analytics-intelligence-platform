import unittest

import _bootstrap

from custom_stack.semantic.compile_duckdb import NeedsClarification, PlanError, Unsupported, compile_plan
from custom_stack.semantic.engine import DataUnavailable, Engine
from custom_stack.semantic.model import load_all


class CompileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = load_all()["hr_public"]
        cls.eng = Engine(cls.model, _bootstrap.ensure_fixtures())

    @classmethod
    def tearDownClass(cls):
        cls.eng.close()

    def q(self, plan):
        return self.eng.query(plan)[1]["rows"]

    def test_all_fixture_tables_present(self):
        self.assertEqual(self.eng.missing_tables, [])

    def test_headcount_excludes_total_row(self):
        rows = self.q({"metric": "staff_headcount", "filters": [
            {"dimension": "state", "op": "eq", "value": "IL"}, {"dimension": "survey_year", "op": "eq", "value": 2023}]})
        self.assertEqual(rows, [[293]])  # total + faculty-status rows (is_category_total) would double count

    def test_explicit_total_row_filter_respected(self):
        rows = self.q({"metric": "staff_headcount", "filters": [
            {"dimension": "category_total_row", "op": "eq", "value": "true"},
            {"dimension": "position_category", "op": "eq", "value": "All staff"},
            {"dimension": "survey_year", "op": "eq", "value": 2023}]})
        self.assertEqual(rows, [[403]])  # published total equals the partition sum

    def test_category_breakdown_is_additive(self):
        rows = self.q({"metric": "staff_headcount", "dimensions": ["position_category"],
                       "filters": [{"dimension": "survey_year", "op": "eq", "value": 2023}]})
        self.assertEqual(sum(r[1] for r in rows), 403)
        self.assertNotIn("All staff", [r[0] for r in rows])

    def test_fte_differs_from_headcount(self):
        hc = self.q({"metric": "staff_headcount", "filters": [{"dimension": "survey_year", "op": "eq", "value": 2023}]})[0][0]
        fte = self.q({"metric": "staff_fte", "filters": [{"dimension": "survey_year", "op": "eq", "value": 2023}]})[0][0]
        self.assertEqual(hc, 403)
        self.assertAlmostEqual(fte, 334.3333333333, places=6)

    def test_ratio_is_ratio_of_sums(self):
        rows = self.q({"metric": "avg_instructional_salary", "filters": [{"dimension": "state", "op": "eq", "value": "IL"}]})
        self.assertAlmostEqual(rows[0][0], 13_450_000 / 115, places=6)  # 9-month default; 12-month row excluded
        # mean of institution averages would differ: (128571.4 + 107142.9 + 70000) / 3
        self.assertNotAlmostEqual(rows[0][0], (9e6 / 70 + 3.75e6 / 35 + 7e5 / 10) / 3, places=0)

    def test_contract_length_rule_is_metric_specific(self):
        by_len = dict(self.q({"metric": "avg_instructional_salary", "dimensions": ["contract_length"],
                              "filters": [{"dimension": "institution_name", "op": "eq", "value": "Fixture Flagship University"}]}))
        self.assertAlmostEqual(by_len["12-month"], 200_000.0)
        self.assertAlmostEqual(by_len["9-month"], 9_000_000 / 70)
        # the count metric on the same entity is NOT restricted to 9-month contracts
        self.assertEqual(self.q({"metric": "instructional_staff_count", "filters": [
            {"dimension": "survey_year", "op": "eq", "value": 2023}]}), [[175]])  # 170 nine-month + 5 twelve-month

    def test_suppressed_cells_propagate_null(self):
        cook = {"dimension": "area", "op": "eq", "value": "17031"}
        self.assertEqual(self.q({"metric": "qcew_employment", "filters": [cook, {"dimension": "year", "op": "eq", "value": 2024}]}), [[None]])
        self.assertEqual(self.q({"metric": "qcew_employment", "filters": [cook, {"dimension": "quarter", "op": "eq", "value": 1}]}), [[10000.0]])
        self.assertEqual(self.q({"metric": "qwi_separations", "filters": [{"dimension": "year", "op": "eq", "value": 2025}]}), [[None]])
        self.assertEqual(self.q({"metric": "qwi_separations", "filters": [{"dimension": "year", "op": "eq", "value": 2024}]}), [[17500]])

    def test_enrollment_year_alignment_and_levels(self):
        y = {"dimension": "survey_year", "op": "eq", "value": 2023}
        self.assertEqual(self.q({"metric": "enrollment_12mo", "filters": [y]}), [[120000]])  # EFFY2024 (2023-24)
        self.assertEqual(self.q({"metric": "enrollment_12mo", "filters": [y, {"dimension": "student_level", "op": "eq", "value": "2"}]}), [[96000]])
        c = compile_plan(self.model, {"metric": "enrollment_12mo", "dimensions": ["student_level"], "filters": [y]})
        self.assertTrue(any("hierarchical" in a for a in c.assumptions))

    def test_stock_requires_single_period(self):
        with self.assertRaises(NeedsClarification) as cm:
            compile_plan(self.model, {"metric": "staff_headcount"})
        self.assertEqual(cm.exception.kind, "time")
        with self.assertRaises(NeedsClarification):
            compile_plan(self.model, {"metric": "staff_headcount", "filters": [
                {"dimension": "survey_year", "op": "in", "values": [2022, 2023]}]})
        rows = self.q({"metric": "staff_headcount", "dimensions": ["survey_year"]})
        self.assertEqual(rows, [[2022, 383], [2023, 403]])

    def test_semi_additive_average_over_quarters(self):
        rows = self.q({"metric": "qcew_employment", "filters": [
            {"dimension": "area", "op": "eq", "value": "17019"}, {"dimension": "year", "op": "eq", "value": 2024}]})
        self.assertEqual(rows, [[15600.0]])
        wages = self.q({"metric": "qcew_total_wages", "filters": [
            {"dimension": "area", "op": "eq", "value": "17019"}, {"dimension": "year", "op": "eq", "value": 2024}]})
        self.assertEqual(wages, [[1.22e9]])  # flow: summed over quarters, ownership total row excluded

    def test_overlapping_geography_requires_clarification(self):
        with self.assertRaises(NeedsClarification) as cm:
            compile_plan(self.model, {"metric": "qcew_employment", "filters": [{"dimension": "year", "op": "eq", "value": 2024}]})
        self.assertEqual(cm.exception.dimension, "area")

    def test_union_drops_duplicate_county_rows(self):
        rows = self.q({"metric": "qcew_total_wages", "filters": [
            {"dimension": "area", "op": "eq", "value": "17019"}, {"dimension": "quarter", "op": "eq", "value": 1}]})
        self.assertEqual(rows, [[305_000_000]])  # county-file 611310 duplicate (wages 1) excluded

    def test_ownership_total_row_excluded(self):
        rows = self.q({"metric": "qcew_employment", "filters": [
            {"dimension": "area", "op": "eq", "value": "17019"}, {"dimension": "industry", "op": "eq", "value": "10"}]})
        self.assertEqual(rows, [[90000.0]])  # own 0 total (90000) not added to own 2 + own 5

    def test_use_total_row_unless_grouped(self):
        y = {"dimension": "year", "op": "eq", "value": 2024}
        tot = self.q({"metric": "qwi_hires", "filters": [y]})
        self.assertEqual(tot, [[18500]])  # geography defaults to Illinois; A01 age row not added
        by_sex = self.q({"metric": "qwi_hires", "dimensions": ["sex"], "filters": [y]})
        self.assertEqual(sorted(r[0] for r in by_sex), ["1", "2"])
        self.assertEqual(sum(r[1] for r in by_sex), 18500)

    def test_derived_metric_components_not_joined_row_level(self):
        rows = self.q({"metric": "staff_fte_per_100_students", "dimensions": ["state"],
                       "filters": [{"dimension": "survey_year", "op": "eq", "value": 2023}]})
        d = dict(rows)
        self.assertAlmostEqual(d["IL"], (130 + 66 + 25 + 40 / 3) * 100 / 80000, places=9)
        c = compile_plan(self.model, {"metric": "staff_fte_per_100_students", "filters": [{"dimension": "survey_year", "op": "eq", "value": 2023}]})
        self.assertTrue(any("aligned on unitid" in a for a in c.assumptions))
        self.assertAlmostEqual(d["IN"], 100 * 100 / 40000, places=9)

    def test_fan_out_breakdown_refused(self):
        with self.assertRaises(Unsupported) as cm:
            compile_plan(self.model, {"metric": "ai_task_usage_pct", "dimensions": ["occupation_title"],
                                      "filters": [{"dimension": "release", "op": "eq", "value": "release_2025_03_27"}]})
        self.assertIn("fan out", cm.exception.reason)

    def test_count_distinct_vs_records(self):
        self.assertEqual(self.q({"metric": "sucss_class_record_count"}), [[4]])
        self.assertEqual(self.q({"metric": "sucss_class_code_count"}), [[3]])

    def test_latest_resolved_in_sql(self):
        c = compile_plan(self.model, {"metric": "staff_headcount", "filters": [{"dimension": "survey_year", "op": "latest"}]})
        self.assertIn("SELECT MAX(", c.sql)
        self.assertEqual(self.eng.execute(c)["rows"], [[403]])

    def test_order_and_limit(self):
        rows = self.q({"metric": "staff_headcount", "dimensions": ["institution_name"],
                       "filters": [{"dimension": "survey_year", "op": "eq", "value": 2023}],
                       "order_by": {"field": "staff_headcount", "direction": "desc"}, "limit": 1})
        self.assertEqual(rows, [["Fixture Flagship University", 150]])

    def test_values_are_escaped(self):
        c = compile_plan(self.model, {"metric": "sucss_class_record_count"})
        self.assertNotIn(";", c.sql)
        c = compile_plan(self.model, {"metric": "enrollment_12mo", "filters": [
            {"dimension": "state", "op": "eq", "value": "IL' OR 1=1 --"},
            {"dimension": "survey_year", "op": "eq", "value": 2023}]})
        self.assertIn("'IL'' OR 1=1 --'", c.sql)
        self.assertEqual(self.eng.execute(c)["rows"], [[None]])
        with self.assertRaises(PlanError):
            compile_plan(self.model, {"metric": "enrollment_12mo", "filters": [
                {"dimension": "survey_year", "op": "eq", "value": "2023 OR 1=1"}]})

    def test_invalid_plans(self):
        for bad in ({"metric": "nope"}, {"metric": "staff_fte", "dimensions": "state"},
                    {"metric": "staff_fte", "filters": [{"dimension": "state", "op": "like", "value": "I%"}]},
                    {"metric": "staff_fte", "limit": 0}):
            with self.assertRaises(PlanError):
                compile_plan(self.model, bad)
        with self.assertRaises(Unsupported):
            compile_plan(self.model, {"metric": "staff_fte", "dimensions": ["area"]})

    def test_provenance_vintages(self):
        c, _ = self.eng.query({"metric": "avg_instructional_salary", "filters": [{"dimension": "state", "op": "eq", "value": "IL"}]})
        vint = self.eng.source_vintages(c)
        self.assertEqual({v["table"] for v in vint}, {"ipeds_salary_instructional", "ipeds_institution"})
        cov = self.eng.join_coverage(c)
        self.assertEqual(cov[0]["relationship"], "sal_is_institution")
        self.assertEqual(cov[0]["unmatched_rows"], 0)

    def test_missing_data_reported(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            eng = Engine(self.model, d)
            with self.assertRaises(DataUnavailable):
                eng.query({"metric": "sucss_class_record_count"})


if __name__ == "__main__":
    unittest.main()
