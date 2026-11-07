"""Tests for delivery/validate_star_schema.py on a tiny generated fixture.

    python -m unittest discover -s wap_prototype/delivery/tests -v     # from platform-evaluation/
"""
from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import validate_star_schema as V  # noqa: E402

AS_OF = "2026-09-30"


def make_fixture(folder: Path) -> dict[str, pd.DataFrame]:
    """A minimal valid outputs folder: every required table with 1-3 rows, all k >= 10 unless suppressed."""
    t = {}
    t["dim_date"] = pd.DataFrame([
        dict(date_key=20250930, date="2025-09-30", calendar_year=2025, calendar_quarter=3, fiscal_year=2026, fiscal_quarter=1, quarter_label="FY2026 Q1", is_forecast_period=False),
        dict(date_key=20251231, date="2025-12-31", calendar_year=2025, calendar_quarter=4, fiscal_year=2026, fiscal_quarter=2, quarter_label="FY2026 Q2", is_forecast_period=False),
        dict(date_key=20261231, date="2026-12-31", calendar_year=2026, calendar_quarter=4, fiscal_year=2027, fiscal_quarter=2, quarter_label="FY2027 Q2", is_forecast_period=True),
    ])
    t["dim_org"] = pd.DataFrame([
        dict(org_key=1, admin_level="campus", campus_cd="1", campus_name="Urbana", college_cd=None, college_name=None, dept_cd=None, dept_name=None, parent_org_key=None, is_active=True),
        dict(org_key=2, admin_level="college", campus_cd="1", campus_name="Urbana", college_cd="KL", college_name="Engineering", dept_cd=None, dept_name=None, parent_org_key=1, is_active=True),
        dict(org_key=3, admin_level="dept", campus_cd="1", campus_name="Urbana", college_cd="KL", college_name="Engineering", dept_cd="434", dept_name="Computer Science", parent_org_key=2, is_active=True),
    ])
    t["dim_role_family"] = pd.DataFrame([dict(role_family_key=1, role_family="ACCT", role_family_name="Accounting", critical_ind=False)])
    t["dim_role"] = pd.DataFrame([
        dict(role_key=10, e_class="CA", p_class="0051", class_title="Accountant I", role_family="ACCT", role_family_key=1, ladder="JP001", ladder_desc="Accountant", level=1, is_top_of_ladder=False, sucss_class_cd="0051", onet_soc_code="13-2011.00", soc_code="13-2011", onet_job_zone=4, mapping_status="unreviewed", critical_ind=False),
        dict(role_key=11, e_class="CA", p_class="0052", class_title="Accountant II", role_family="ACCT", role_family_key=1, ladder="JP001", ladder_desc="Accountant", level=2, is_top_of_ladder=True, sucss_class_cd="0052", onet_soc_code="13-2011.00", soc_code="13-2011", onet_job_zone=4, mapping_status="unreviewed", critical_ind=True),
    ])
    t["dim_model_version"] = pd.DataFrame([
        dict(model_version="DESCRIPTIVE-20260930", model_id="DESCRIPTIVE", method="phase1", protocol_version="wap-protocol-v1", run_id="r1", seed=20261107, data_as_of=AS_OF, train_start=None, train_end=None, feature_table_hash="abc", bitemporal_mode="bitemporal", passes_all_thresholds=None, fairness_flag="not_applicable", is_published_default=True, model_card_path="model_cards/descriptive.md", created_at=AS_OF),
        dict(model_version="A-gbm-20260930", model_id="A", method="A-gbm", protocol_version="wap-protocol-v1", run_id="r1", seed=20261107, data_as_of=AS_OF, train_start="2015-12-31", train_end="2024-12-31", feature_table_hash="abc", bitemporal_mode="bitemporal", passes_all_thresholds=True, fairness_flag="none", is_published_default=True, model_card_path="model_cards/a.md", created_at=AS_OF),
        dict(model_version="B-ens-20260930", model_id="B", method="B-ens", protocol_version="wap-protocol-v1", run_id="r1", seed=20261107, data_as_of=AS_OF, train_start="2012-03-31", train_end="2025-09-30", feature_table_hash="abc", bitemporal_mode="bitemporal", passes_all_thresholds=True, fairness_flag="not_applicable", is_published_default=True, model_card_path="model_cards/b.md", created_at=AS_OF),
    ])
    t["dim_scenario"] = pd.DataFrame([dict(scenario_key=1, scenario_cd="primary", scenario_name="Primary model", description="x", is_default=True)])
    t["fact_headcount_quarter"] = pd.DataFrame([
        dict(date_key=20250930, org_key=3, role_key=10, model_version="DESCRIPTIVE-20260930", n=25, headcount=25, headcount_prior_quarter=24, fte_sum=24.5, hires=2, sep_voluntary=1, sep_retirement=0, sep_other=0, separations_total=1, promotions_in=0, promotions_out=1, transfers_in=0, transfers_out=0, suppressed=False, data_as_of=AS_OF),
        dict(date_key=20250930, org_key=3, role_key=11, model_version="DESCRIPTIVE-20260930", n=4, headcount=None, headcount_prior_quarter=None, fte_sum=None, hires=None, sep_voluntary=None, sep_retirement=None, sep_other=None, separations_total=None, promotions_in=None, promotions_out=None, transfers_in=None, transfers_out=None, suppressed=True, data_as_of=AS_OF),
    ])
    t["fact_transitions_quarter"] = pd.DataFrame([
        dict(date_key=20250930, org_key=2, from_role_key=10, to_role_key=11, transition_type="promotion", model_version="DESCRIPTIVE-20260930", n=40, n_transitions=12, transition_rate=0.3, median_years_in_from_role=3.5, suppressed=False, data_as_of=AS_OF),
    ])
    t["fact_promotion_expectation"] = pd.DataFrame([
        dict(date_key=20250930, org_key=2, role_key=10, horizon_months=12, model_version="A-gbm-20260930", scenario_key=1, n=40, expected=5.2, expected_p10=3, expected_p90=8, expected_rate=0.13, observed=None, resolved=False, pipeline_supply_expected=4.0, pipeline_need_expected=6.0, pipeline_coverage=0.67, pipeline_coverage_p10=0.4, pipeline_coverage_p90=1.0, label_name="promoted_12m", suppressed=False, data_as_of=AS_OF),
    ])
    t["fact_attrition_forecast"] = pd.DataFrame([
        dict(origin_date_key=20250930, target_date_key=20251231, horizon_q=1, org_key=3, role_family_key=1, model_version="B-ens-20260930", scenario_key=1, n=25, headcount_point=25.3, headcount_p10=23, headcount_p90=27, hires_point=1.2, hires_p10=0, hires_p90=3, sep_voluntary_point=0.8, sep_voluntary_p10=0, sep_voluntary_p90=2, sep_retirement_point=0.3, sep_retirement_p10=0, sep_retirement_p90=1, sep_other_point=0.1, sep_other_p10=0, sep_other_p90=1, separations_point=1.2, separations_p10=0, separations_p90=3, headcount_actual=25, hires_actual=1, separations_actual=1, actual_known=True, is_bottom_up=False, suppressed=False, data_as_of=AS_OF),
    ])
    t["fact_attrition_risk"] = pd.DataFrame([
        dict(origin_date_key=20250930, org_key=3, role_family_key=1, model_version="B-ens-20260930", n=25, expected_sep_rate_4q=0.12, expected_sep_rate_p10=0.06, expected_sep_rate_p90=0.2, observed_sep_rate_trailing_4q=0.1, peer_median_rate=0.11, peer_p75_rate=0.15, n_peer_units=8, attrition_flag=False, suppressed=False, data_as_of=AS_OF),
    ])
    t["fact_external_context"] = pd.DataFrame([
        dict(date_key=20250930, role_key=10, oews_pay_ratio_local=0.93, bls_projected_growth_pct=4.1, bls_separation_rate=0.09, onet_job_zone=4, aei_exposure=0.42, job_evolution_watch=0.3, source_vintage="OEWS May 2025", mapping_status="unreviewed", suppressed=False, data_as_of=AS_OF),
    ])
    t["fact_model_quality"] = pd.DataFrame([
        dict(model_version="A-gbm-20260930", scenario_key=1, origin_date_key=0, horizon=12, metric_name="auc_roc", attribute="all", metric_value=0.66, baseline_value=0.58, threshold_id="A1", threshold_value=0.62, threshold_pass=True, fairness_flag=None, n=12000, suppressed=False, data_as_of=AS_OF),
        dict(model_version="A-gbm-20260930", scenario_key=1, origin_date_key=0, horizon=12, metric_name="min_impact_ratio", attribute="sex", metric_value=0.91, baseline_value=None, threshold_id="A8", threshold_value=0.8, threshold_pass=True, fairness_flag="none", n=12000, suppressed=False, data_as_of=AS_OF),
    ])
    for name, df in t.items():
        df.to_csv(folder / f"{name}.csv", index=False)
    return t


class TestValidator(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = V.load_schema()

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.tables = make_fixture(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _rewrite(self, name: str, df: pd.DataFrame) -> None:
        df.to_csv(self.tmp / f"{name}.csv", index=False)

    def test_schema_is_self_consistent(self):
        for name, spec in self.schema["tables"].items():
            cols = {c["name"] for c in spec["columns"]}
            for k in spec.get("primary_key", []):
                self.assertIn(k, cols, f"{name} pk {k}")
            for fk in spec.get("foreign_keys", []) or []:
                self.assertIn(fk["references"], self.schema["tables"], f"{name} fk -> {fk['references']}")
                for c in fk["columns"]:
                    self.assertIn(c, cols, f"{name} fk col {c}")
            if spec["kind"] == "fact":
                self.assertIn("suppression", spec, name)
                self.assertIn(spec["suppression"].get("flag_column", "suppressed"), cols, name)
                for m in spec["suppression"].get("measure_columns", []):
                    self.assertIn(m, cols, f"{name} measure {m}")
                self.assertIn("data_as_of", cols, name)
            for c in spec["columns"]:
                self.assertIn(c["type"], ("int", "float", "string", "date", "bool"), f"{name}.{c['name']}")
            for f in self.schema["forbidden_columns"]:
                for c in cols:
                    self.assertNotIn(f, c.lower(), f"{name}.{c} matches forbidden {f}")

    def test_valid_fixture_passes(self):
        rep = V.validate_outputs(self.tmp, self.schema)
        self.assertEqual(rep.errors, [])
        self.assertTrue(rep.ok)
        self.assertEqual(len(rep.tables), len(self.schema["tables"]))

    def test_parquet_also_accepted(self):
        df = self.tables["fact_external_context"]
        (self.tmp / "fact_external_context.csv").unlink()
        df.to_parquet(self.tmp / "fact_external_context.parquet", index=False)
        rep = V.validate_outputs(self.tmp, self.schema)
        self.assertEqual(rep.errors, [])

    def test_missing_required_table(self):
        (self.tmp / "fact_model_quality.csv").unlink()
        rep = V.validate_outputs(self.tmp, self.schema)
        self.assertTrue(any("fact_model_quality: required table" in e for e in rep.errors))

    def test_duplicate_primary_key_is_grain_violation(self):
        df = self.tables["fact_headcount_quarter"]
        self._rewrite("fact_headcount_quarter", pd.concat([df, df.iloc[[0]]]))
        rep = V.validate_outputs(self.tmp, self.schema)
        self.assertTrue(any("grain violated" in e for e in rep.errors))

    def test_unsuppressed_small_cell_is_error(self):
        df = self.tables["fact_headcount_quarter"].copy()
        df.loc[1, "suppressed"] = False
        self._rewrite("fact_headcount_quarter", df)
        rep = V.validate_outputs(self.tmp, self.schema)
        self.assertTrue(any("not flagged suppressed" in e for e in rep.errors))

    def test_suppressed_row_must_have_null_measures(self):
        df = self.tables["fact_headcount_quarter"].copy()
        df.loc[1, "headcount"] = 4
        self._rewrite("fact_headcount_quarter", df)
        rep = V.validate_outputs(self.tmp, self.schema)
        self.assertTrue(any("still carry measure values" in e for e in rep.errors))

    def test_small_transition_count_is_error(self):
        df = self.tables["fact_transitions_quarter"].copy()
        df.loc[0, "n_transitions"] = 3   # population 40 but only 3 movers: must be suppressed
        self._rewrite("fact_transitions_quarter", df)
        rep = V.validate_outputs(self.tmp, self.schema)
        self.assertTrue(any("fact_transitions_quarter" in e and "not flagged suppressed" in e for e in rep.errors))

    def test_forbidden_identifier_column(self):
        df = self.tables["fact_promotion_expectation"].copy()
        df["edw_pers_id"] = "123"
        self._rewrite("fact_promotion_expectation", df)
        rep = V.validate_outputs(self.tmp, self.schema)
        self.assertTrue(any("forbidden column 'edw_pers_id'" in e for e in rep.errors))

    def test_foreign_key_orphan(self):
        df = self.tables["fact_attrition_forecast"].copy()
        df.loc[0, "org_key"] = 99
        self._rewrite("fact_attrition_forecast", df)
        rep = V.validate_outputs(self.tmp, self.schema)
        self.assertTrue(any("reference dim_org" in e for e in rep.errors))

    def test_type_and_nullability(self):
        df = self.tables["fact_model_quality"].copy().astype({"horizon": object})
        df.loc[0, "horizon"] = "twelve"
        df.loc[1, "data_as_of"] = None
        self._rewrite("fact_model_quality", df)
        rep = V.validate_outputs(self.tmp, self.schema)
        self.assertTrue(any("'horizon'" in e and "not int" in e for e in rep.errors))
        self.assertTrue(any("'data_as_of'" in e and "null" in e for e in rep.errors))

    def test_public_fact_must_not_be_flagged(self):
        df = self.tables["fact_external_context"].copy()
        df.loc[0, "suppressed"] = True
        self._rewrite("fact_external_context", df)
        rep = V.validate_outputs(self.tmp, self.schema)
        self.assertTrue(any("public fact" in e for e in rep.errors))

    def test_missing_column_and_extra_column(self):
        df = self.tables["fact_attrition_risk"].drop(columns=["peer_p75_rate"]).assign(note="x")
        self._rewrite("fact_attrition_risk", df)
        rep = V.validate_outputs(self.tmp, self.schema)
        self.assertTrue(any("missing column 'peer_p75_rate'" in e for e in rep.errors))
        self.assertTrue(any("extra column 'note'" in w for w in rep.warnings))

    def test_cli_exit_codes(self):
        self.assertEqual(V.main([str(self.tmp)]), 0)
        (self.tmp / "dim_date.csv").unlink()
        self.assertEqual(V.main([str(self.tmp), "--json", str(self.tmp / "report.json")]), 1)
        self.assertTrue((self.tmp / "report.json").exists())


if __name__ == "__main__":
    unittest.main()
