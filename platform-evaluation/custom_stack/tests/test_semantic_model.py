import tempfile
import unittest
from pathlib import Path

import _bootstrap  # noqa: F401
import yaml

from custom_stack.semantic.model import SpecError, load_all, load_model, qualify

SPECS = _bootstrap.PLATFORM_EVAL / "custom_stack" / "semantic" / "specs"


class ModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.models = load_all()
        cls.hr = cls.models["hr_public"]

    def test_specs_load(self):
        self.assertEqual(set(self.models), {"hr_public", "benchmark_workforce"})
        self.assertGreaterEqual(len(self.hr.metrics), 20)
        self.assertEqual(len(self.hr.sha256), 64)

    def test_headcount_fte_appointments_are_distinct_metrics(self):
        b = self.models["benchmark_workforce"]
        self.assertEqual(b.metrics["wf_headcount"].agg, "count_distinct")
        self.assertEqual(b.metrics["wf_appointment_count"].agg, "count")
        self.assertEqual(b.metrics["wf_fte"].agg, "sum")
        self.assertEqual(b.metrics["wf_headcount"].additivity, "non_additive")

    def test_fan_out_relationships_not_reachable(self):
        reach = self.hr.reachable("aei_task_usage")
        self.assertEqual(set(reach), {"aei_task_usage"})
        self.assertNotIn("occupation_title", self.hr.available_dimensions("ai_task_usage_pct"))
        self.assertIsNotNone(self.hr.blocked_relationship("aei_task_usage", "occupation_title"))

    def test_joined_dimensions_available(self):
        dims = self.hr.available_dimensions("staff_fte")
        for d in ("state", "sector", "survey_year", "position_category"):
            self.assertIn(d, dims)

    def test_derived_metric_conformed_dimensions(self):
        dims = self.hr.available_dimensions("staff_fte_per_100_students")
        self.assertIn("state", dims)
        self.assertNotIn("position_category", dims)  # not on enrollment

    def test_qualify_skips_string_literals(self):
        self.assertEqual(qualify("task_type = 'task_type'", "t", {"task_type"}), "t.task_type = 'task_type'")

    def _bad(self, mutate):
        raw = yaml.safe_load((SPECS / "hr_public.yaml").read_text())
        mutate(raw)
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "bad.yaml"
            p.write_text(yaml.safe_dump(raw))
            with self.assertRaises(SpecError):
                load_model(p)

    def test_rejects_average_aggregation(self):
        self._bad(lambda r: r["metrics"]["staff_headcount"].update(agg="avg"))

    def test_rejects_many_to_one_not_on_primary_key(self):
        self._bad(lambda r: r["relationships"][0].update(keys=[["position_category", "institution_name"]]))

    def test_rejects_semi_additive_without_rollup(self):
        self._bad(lambda r: r["metrics"]["staff_headcount"].pop("time_rollup"))

    def test_rejects_unknown_entity(self):
        self._bad(lambda r: r["metrics"]["staff_fte"].update(entity="nope"))


if __name__ == "__main__":
    unittest.main()
