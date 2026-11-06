"""Vendor artefacts are generated from the same spec, and the single-pass
measure expressions they carry give the same numbers as the reference compiler
when executed on DuckDB."""
import unittest

import _bootstrap
import yaml

from custom_stack.semantic.compile_databricks import metric_view_ddl, metric_views
from custom_stack.semantic.compile_snowflake import cortex_analyst_yaml, semantic_view_ddl
from custom_stack.semantic.engine import Engine
from custom_stack.semantic.model import load_all, qualify
from custom_stack.semantic.portable import portable_measure


class PortabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.models = load_all()
        cls.hr = cls.models["hr_public"]
        cls.eng = Engine(cls.hr, _bootstrap.ensure_fixtures())

    @classmethod
    def tearDownClass(cls):
        cls.eng.close()

    def portable(self, metric, where="", joins=""):
        m = self.hr.metrics[metric]
        e = self.hr.entities[m.entity]
        expr = portable_measure(self.hr, metric, lambda x: qualify(x, e.name, e.columns)).expr
        sql = f"SELECT {expr} FROM {e.table} AS {e.name} {joins} {('WHERE ' + where) if where else ''}"
        return self.eng.run_sql(sql)["rows"][0][0]

    def reference(self, plan):
        return self.eng.query(plan)[1]["rows"][0][0]

    def test_semi_additive_avg_equivalence(self):
        p = self.portable("qcew_employment", "qcew.area_fips = '17019' AND qcew.year = 2024")
        r = self.reference({"metric": "qcew_employment", "filters": [
            {"dimension": "area", "op": "eq", "value": "17019"}, {"dimension": "year", "op": "eq", "value": 2024}]})
        self.assertAlmostEqual(p, r, places=9)

    def test_suppression_propagates_in_portable_measure(self):
        self.assertIsNone(self.portable("qcew_employment", "qcew.area_fips = '17031' AND qcew.year = 2024"))
        self.assertEqual(self.portable("qcew_employment", "qcew.area_fips = '17031' AND qcew.qtr = 1"), 10000.0)

    def test_require_single_returns_null_across_periods(self):
        self.assertIsNone(self.portable("staff_headcount"))  # two survey years -> NULL, not a wrong sum
        p = self.portable("staff_headcount", "staff_eap.survey_year = 2023")
        self.assertEqual(p, self.reference({"metric": "staff_headcount", "filters": [
            {"dimension": "survey_year", "op": "eq", "value": 2023}]}))

    def test_ratio_and_total_row_equivalence(self):
        j = "LEFT JOIN ipeds_institution AS institution ON salary_instructional.unitid = institution.unitid"
        p = self.portable("avg_instructional_salary", "institution.state_abbr = 'IL'", j)
        r = self.reference({"metric": "avg_instructional_salary", "filters": [{"dimension": "state", "op": "eq", "value": "IL"}]})
        self.assertAlmostEqual(p, r, places=6)

    def test_use_total_and_metric_filter_equivalence(self):
        p = self.portable("qwi_employment", "qwi.geography = '17'")
        r = self.reference({"metric": "qwi_employment", "filters": [{"dimension": "geography", "op": "eq", "value": "17"}]})
        self.assertAlmostEqual(p, r, places=9)
        self.assertEqual(self.portable("core_task_count"), self.reference({"metric": "core_task_count"}))

    def test_snowflake_semantic_view(self):
        ddl, warnings = semantic_view_ddl(self.hr)
        self.assertIn("CREATE OR REPLACE SEMANTIC VIEW HR_ANALYTICS.HR_PUBLIC.HR_PUBLIC_METRICS", ddl)
        self.assertIn("eap_institution AS staff_eap (unitid) REFERENCES institution (unitid)", ddl)
        self.assertNotIn("aei_task_text AS", ddl)  # many-to-many never emitted as a join
        self.assertIn("staff_eap.staff_fte AS", ddl)
        self.assertIn("WITH SYNONYMS", ddl)
        self.assertTrue(any("aei_task_text" in w for w in warnings))

    def test_cortex_yaml(self):
        text, _ = cortex_analyst_yaml(self.hr)
        doc = yaml.safe_load(text)
        names = {t["name"] for t in doc["tables"]}
        self.assertIn("staff_eap", names)
        eap = next(t for t in doc["tables"] if t["name"] == "staff_eap")
        self.assertIn("staff_headcount", {m["name"] for m in eap["metrics"]})
        self.assertTrue(doc["verified_queries"])
        self.assertIn("__staff_eap", doc["verified_queries"][0]["sql"])
        self.assertEqual({r["relationship_type"] for r in doc["relationships"]}, {"many_to_one"})

    def test_databricks_metric_views(self):
        views, warnings = metric_views(self.hr)
        eap = yaml.safe_load(views["staff_eap_metrics"])
        self.assertEqual(eap["source"], "hr_analytics.hr_public.ipeds_employees_by_position")
        self.assertEqual(eap["joins"][0]["name"], "institution")
        self.assertIn("state", {d["name"] for d in eap["dimensions"]})
        self.assertIn("staff_fte", {m["name"] for m in eap["measures"]})
        self.assertTrue(any(w.startswith("staff_fte_per_100_students") for w in warnings))
        self.assertIn("WITH METRICS", metric_view_ddl(self.hr, views))

    def test_same_metric_set_across_targets(self):
        """Every non-derived metric appears in all three targets with the same name."""
        ddl, _ = semantic_view_ddl(self.hr)
        cortex = yaml.safe_load(cortex_analyst_yaml(self.hr)[0])
        views, _ = metric_views(self.hr)
        db = {m["name"] for t in views.values() for m in yaml.safe_load(t)["measures"]}
        cx = {m["name"] for t in cortex["tables"] for m in t.get("metrics", [])}
        for name, m in self.hr.metrics.items():
            if m.type == "derived":
                continue
            self.assertIn(f".{name} AS", ddl)
            self.assertIn(name, cx)
            self.assertIn(name, db)

    def test_benchmark_model_compiles_everywhere(self):
        b = self.models["benchmark_workforce"]
        self.assertIn("CREATE OR REPLACE VIEW", semantic_view_ddl(b)[0])
        self.assertTrue(yaml.safe_load(cortex_analyst_yaml(b)[0])["tables"])
        self.assertIn("appointment_segment_metrics", metric_views(b)[0])


if __name__ == "__main__":
    unittest.main()
