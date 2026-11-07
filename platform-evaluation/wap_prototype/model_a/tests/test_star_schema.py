"""The Model A tables have the delivery/star_schema.yaml shape and pass validate_star_schema per table."""
from __future__ import annotations

import json
import unittest

import pandas as pd
import yaml

from wap_prototype.model_a import aggregate as A
from wap_prototype.model_a import config as C
from wap_prototype.model_a.tests import common


class TestStarSchema(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = common.small_run("a")
        cls.star = cls.ctx["out"] / "star"
        cls.schema = yaml.safe_load(C.STAR_SCHEMA.read_text(encoding="utf-8"))
        cls.tables = {t: pd.read_csv(cls.star / f"{t}.csv") for t in A.STAR_TABLES}

    def test_validator_report_has_no_errors(self):
        rep = json.loads((self.star / "validation_report.json").read_text())
        self.assertTrue(rep["ok"], rep["errors"])
        self.assertEqual(set(rep["tables"]), set(A.STAR_TABLES))

    def test_every_contract_column_present_and_keys_unique(self):
        for name, df in self.tables.items():
            spec = self.schema["tables"][name]
            cols = [c["name"] for c in spec["columns"]]
            self.assertEqual([c for c in cols if c not in df.columns], [], name)
            self.assertEqual([c for c in df.columns if c not in cols], [], f"{name}: extra columns")
            pk = spec["primary_key"]
            self.assertFalse(df.duplicated(subset=pk).any(), f"{name}: grain")

    def test_no_forbidden_columns(self):
        forbidden = [f.lower() for f in self.schema["forbidden_columns"]]
        for name, df in self.tables.items():
            for c in df.columns:
                self.assertFalse(any(f in c.lower() for f in forbidden), f"{name}.{c}")

    def test_foreign_keys_resolve(self):
        f = self.tables["fact_promotion_expectation"]
        self.assertTrue(f["date_key"].isin(self.tables["dim_date"]["date_key"]).all())
        self.assertTrue(f["org_key"].isin(self.tables["dim_org"]["org_key"]).all())
        self.assertTrue(f["role_key"].isin(self.tables["dim_role"]["role_key"]).all())
        self.assertTrue(f["model_version"].isin(self.tables["dim_model_version"]["model_version"]).all())
        self.assertTrue(f["scenario_key"].isin(self.tables["dim_scenario"]["scenario_key"]).all())
        q = self.tables["fact_model_quality"]
        self.assertTrue(q["model_version"].isin(self.tables["dim_model_version"]["model_version"]).all())
        self.assertTrue(q["scenario_key"].isin(self.tables["dim_scenario"]["scenario_key"]).all())

    def test_model_version_and_scenario_conventions(self):
        dmv = self.tables["dim_model_version"]
        self.assertEqual(dmv["is_published_default"].sum(), 1)
        self.assertTrue((dmv["protocol_version"] == "wap-protocol-v1").all())
        self.assertTrue((dmv["model_id"] == "A").all())
        self.assertTrue(dmv["model_version"].str.match(r"^A-[a-z-]+-\d{8}$").all())
        self.assertTrue((dmv["seed"] == C.SEED).all())
        sc = self.tables["dim_scenario"]
        self.assertEqual(sc["is_default"].sum(), 1)
        self.assertEqual(sc.loc[sc["is_default"], "scenario_cd"].iloc[0], "primary")
        f = self.tables["fact_promotion_expectation"]
        self.assertEqual(set(f["horizon_months"]), {12, 18})
        self.assertTrue(f["label_name"].isin(["promoted_12m", "promoted_18m", "upward_transition_12m", "upward_transition_18m"]).all())
        self.assertTrue(set(f["scenario_key"]) >= {1, 2, 3})

    def test_model_quality_long_format_sentinels(self):
        q = self.tables["fact_model_quality"]
        self.assertIn(0, set(q["origin_date_key"]))
        self.assertTrue(((q["origin_date_key"] == 0) | (q["origin_date_key"] > 20000000)).all())
        self.assertIn("all", set(q["attribute"]))
        self.assertEqual(set(q[q["attribute"] != "all"]["attribute"]), {"sex", "race_eth_rpt_cd", "age_40_plus"})
        self.assertEqual(set(q[q["attribute"] != "all"]["metric_name"]), {"min_impact_ratio", "max_tpr_gap", "max_fpr_gap", "groups_suppressed"})
        thr = q[q["threshold_id"].notna()]
        self.assertTrue((thr["origin_date_key"] == 0).all())                 # thresholds only on mean rows
        self.assertEqual(set(thr["threshold_id"]) - {"A1", "A2", "A3", "A3b", "A4", "A5", "A6", "A7", "A8", "A9"}, set())
        self.assertIn("label_audit_agreement", set(q["metric_name"]))

    def test_expectation_rows_exist_for_every_step_unit_with_an_incumbent(self):
        f = self.tables["fact_promotion_expectation"]
        self.assertTrue((f["n"] >= 1).all())
        pub = f[~f["suppressed"]]
        # exact Poisson-binomial quantiles are integers in [0, n] with P10 <= P90 (the mean may sit outside the
        # interval for very small probabilities, e.g. mean 0.1 with P90 = 0)
        self.assertTrue((pub["expected_p10"] <= pub["expected_p90"]).all())
        self.assertTrue(((pub["expected_p10"] >= 0) & (pub["expected_p90"] <= pub["n"])).all())
        self.assertTrue(((pub["expected"] >= 0) & (pub["expected"] <= pub["n"])).all())
        self.assertTrue(((pub["expected_rate"] - pub["expected"] / pub["n"]).abs() < 1e-9).all())
        res = pub[pub["resolved"]]
        self.assertTrue(res["observed"].notna().all())
        self.assertTrue(pub[~pub["resolved"]]["observed"].isna().all())


if __name__ == "__main__":
    unittest.main()
