"""Runs the semantic layer against the REAL lake contract layer when it exists
(platform-evaluation/data/lake/contract). Skipped otherwise. Values asserted
here were cross-checked by direct SQL or stated by the lake contract."""
import unittest

import _bootstrap

from custom_stack.eval.score import load_questions, score_custom
from custom_stack.semantic.cli import check_contract
from custom_stack.semantic.engine import Engine
from custom_stack.semantic.model import load_all

LAKE = _bootstrap.PLATFORM_EVAL / "data" / "lake" / "contract"


@unittest.skipUnless((LAKE / "ipeds_employees_by_position.parquet").exists(), "real lake contract layer not built")
class RealLakeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = load_all()["hr_public"]
        cls.eng = Engine(cls.model, LAKE)

    def q(self, plan):
        return self.eng.query(plan)[1]["rows"]

    def test_contract_columns_match_spec(self):
        res = check_contract(self.model, LAKE)
        self.assertTrue(res["ok"], res)

    def test_uiuc_fall_2023_total(self):
        rows = self.q({"metric": "staff_headcount", "filters": [
            {"dimension": "institution_name", "op": "eq", "value": "University of Illinois Urbana-Champaign"},
            {"dimension": "survey_year", "op": "eq", "value": 2023}]})
        self.assertEqual(rows, [[12905]])  # lake contract: UIUC grand total

    def test_partition_equals_published_total_for_illinois(self):
        y = {"dimension": "survey_year", "op": "eq", "value": 2023}
        il = {"dimension": "state", "op": "eq", "value": "IL"}
        part = self.q({"metric": "staff_headcount", "filters": [il, y]})[0][0]
        published = self.q({"metric": "staff_headcount", "filters": [il, y,
                            {"dimension": "category_total_row", "op": "eq", "value": "true"},
                            {"dimension": "position_category", "op": "eq", "value": "All staff"}]})[0][0]
        self.assertEqual(part, published)

    def test_sucss_record_vs_code_counts(self):
        self.assertEqual(self.q({"metric": "sucss_class_record_count"}), [[883]])
        self.assertEqual(self.q({"metric": "sucss_class_code_count"}), [[882]])

    def test_aei_release_sums_to_100_percent(self):
        rows = self.q({"metric": "ai_task_usage_pct", "filters": [
            {"dimension": "release", "op": "eq", "value": "release_2025_03_27"}]})
        self.assertAlmostEqual(rows[0][0], 100.0, places=6)

    def test_suppressed_champaign_cells_stay_null(self):
        rows = self.q({"metric": "qcew_employment", "filters": [
            {"dimension": "area", "op": "eq", "value": "17019"}, {"dimension": "year", "op": "eq", "value": 2024}]})
        self.assertEqual(rows, [[None]])

    def test_question_set_behaviour_on_real_lake(self):
        rep = score_custom(load_questions(), {"hr_public": str(LAKE), "benchmark_workforce": None}, use_fixed=False)
        bad = [d["id"] for d in rep["details"] if not d["status_match"] or d.get("result_equal") is False]
        self.assertEqual(bad, [])


if __name__ == "__main__":
    unittest.main()
