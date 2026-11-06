import json
import tempfile
import unittest
from pathlib import Path

import _bootstrap

from custom_stack.eval.score import compare_results, load_questions, score_custom, score_external


class CompareTests(unittest.TestCase):
    def test_order_and_names_ignored(self):
        self.assertTrue(compare_results([["IL", 1.0], ["IN", 2]], [[2, "IN"], [1, "IL"]])["equal"])

    def test_extra_columns_allowed(self):
        r = compare_results([["IL", 5]], [["Illinois", "IL", 5]])
        self.assertTrue(r["equal"])
        self.assertEqual(r["extra_columns"], 1)

    def test_rounded_values_fail(self):
        self.assertFalse(compare_results([[116956.52173913043]], [[116956.52]])["equal"])
        self.assertTrue(compare_results([[0.1 + 0.2]], [[0.3]])["equal"])

    def test_row_count_and_values(self):
        self.assertFalse(compare_results([[1], [2]], [[1]])["equal"])
        self.assertFalse(compare_results([["a", 1]], [["a", 2]])["equal"])


class EvalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.questions = load_questions()
        cls.dirs = {"hr_public": str(_bootstrap.ensure_fixtures()), "benchmark_workforce": None}

    def test_question_set_size_and_mix(self):
        self.assertGreaterEqual(len(self.questions), 25)
        statuses = {q["expected"]["status"] for q in self.questions}
        self.assertEqual(statuses, {"answer", "clarify", "abstain"})
        self.assertEqual(len({q["id"] for q in self.questions}), len(self.questions))

    def test_custom_stack_regression(self):
        rep = score_custom(self.questions, self.dirs)
        s = rep["summary"]
        failing = [d["id"] for d in rep["details"] if not d["status_match"] or d.get("result_equal") is False]
        self.assertEqual(failing, [], json.dumps([d for d in rep["details"] if d["id"] in failing], default=str)[:2000])
        self.assertEqual(s["exact_plan_accuracy"], 1.0)
        self.assertEqual(s["unsafe_answer_rate"], 0.0)

    def test_external_scoring(self):
        lines = [
            {"id": "Q01", "status": "answer", "rows": [[293]], "sql": "select ..."},
            {"id": "Q02", "status": "answer", "rows": [[38.333333333333336, "4"], [296.0, "1"]]},  # reordered
            {"id": "Q06", "status": "answer", "rows": [[116956.52]]},  # rounded -> not equal
            {"id": "Q20", "status": "answer", "rows": [[403]]},          # should have clarified -> unsafe
            {"id": "Q26", "status": "abstain"},
        ]
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "a.jsonl"
            p.write_text("\n".join(json.dumps(x) for x in lines))
            rep = score_external(self.questions, str(p), "fake_vendor", self.dirs)
        det = {x["id"]: x for x in rep["details"]}
        self.assertTrue(det["Q01"]["result_equal"])
        self.assertTrue(det["Q02"]["result_equal"])
        self.assertFalse(det["Q06"]["result_equal"])
        self.assertEqual(det["Q03"]["status"], "missing")
        self.assertGreater(rep["summary"]["unsafe_answer_rate"], 0)
        self.assertNotIn("exact_plan_accuracy", rep["summary"])

    def test_external_template_parses(self):
        tpl = _bootstrap.PLATFORM_EVAL / "custom_stack" / "eval" / "external_answers_template.jsonl"
        for line in tpl.read_text().splitlines():
            if line.strip() and not line.startswith("//"):
                self.assertIn("id", json.loads(line))


if __name__ == "__main__":
    unittest.main()
