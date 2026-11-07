"""Thresholds, seeds and hyper-parameters are pinned to the protocol constants (AGENTS.md rule 4)."""
from __future__ import annotations

import datetime as dt
import json
import unittest

import pandas as pd

from wap_prototype.model_a import config as C
from wap_prototype.model_a import evaluate as EV
from wap_prototype.protocol import scorers as S


class TestPinnedConstants(unittest.TestCase):
    def test_scorer_thresholds_match_protocol_2_6(self):
        self.assertEqual(S.THRESHOLDS_A["A1_auc_roc_min"], 0.62)
        self.assertEqual(S.THRESHOLDS_A["A1_auc_roc_gain_over_step"], 0.03)
        self.assertEqual(S.THRESHOLDS_A["A2_auc_pr_prevalence_multiple"], 1.5)
        self.assertEqual(S.THRESHOLDS_A["A3_brier_skill_vs_family_min"], 0.02)
        self.assertEqual(S.THRESHOLDS_A["A3b_brier_skill_vs_step_min"], 0.0)
        self.assertEqual(tuple(S.THRESHOLDS_A["A4_cal_slope_range"]), (0.85, 1.15))
        self.assertEqual(S.THRESHOLDS_A["A5_citl_abs_max"], 0.01)
        self.assertEqual(S.THRESHOLDS_A["A6_ece_max"], 0.02)
        self.assertEqual(S.THRESHOLDS_A["A7_grain_coverage_min"], 0.70)
        self.assertEqual(S.THRESHOLDS_A["A9_age_ablation_gain_review"], 0.03)
        self.assertEqual(S.K_MIN, 10)
        self.assertEqual(S.PROTOCOL_VERSION, "wap-protocol-v1")

    def test_model_a_constants_match_protocol(self):
        self.assertEqual(C.SEED, 20261107)
        self.assertEqual(C.K_MIN, 10)
        self.assertEqual(C.HORIZONS, (12, 18))
        self.assertEqual(C.ORIGINS, tuple(dt.date(y, 12, 31) for y in (2019, 2020, 2021, 2022, 2023)))
        self.assertEqual(C.TRAIN_HORIZON_MONTHS, 18)
        self.assertEqual((C.TEST_WINDOW_YEARS, C.RECAL_OFFSET_YEARS), (2, 2))
        self.assertEqual(C.STEP_BACKOFF_MIN_N, 30)
        self.assertEqual(C.LEARNERS["A-logit"]["C_grid"], (0.01, 0.1, 1.0, 10.0))
        self.assertEqual(C.LEARNERS["A-logit"]["cv_folds"], 5)
        rf = C.LEARNERS["A-rf"]
        self.assertEqual((rf["n_estimators"], rf["min_samples_leaf"], rf["max_features"], rf["class_weight"]), (500, 50, "sqrt", "balanced"))
        g = C.LEARNERS["A-gbm"]
        self.assertEqual((g["n_estimators"], g["learning_rate"], g["num_leaves"], g["min_child_samples"], g["deterministic"], g["num_threads"]),
                         (300, 0.05, 15, 100, True, 1))
        self.assertEqual((C.LABEL_AUDIT_N, C.LABEL_AUDIT_MIN_AGREEMENT, C.TOP_SHARE_SELECTION, C.CAL_BY_GROUP_MIN_N), (200, 0.85, 0.10, 50))
        self.assertEqual(C.TIE_MARGIN, 0.005)
        self.assertEqual(C.SIMPLICITY_ORDER, ("A-logit", "A-rf", "A-gbm"))

    def test_protocol_feature_list_is_bound_exactly(self):
        logical = set(C.NUMERIC_FEATURES) | set(C.CATEGORICAL_FEATURES)
        expected = {"tenure_years", "time_in_class_years", "time_in_position_years", "fte", "pay_position_in_range", "moves_per_year",
                    "time_since_last_move", "unit_churn_12m", "e_class", "p_class", "role_family", "ladder", "level", "campus", "onet_job_zone",
                    "bls_projected_growth_pct", "bls_separation_rate", "oews_pay_ratio_local", "aei_exposure", "job_evolution_watch"}
        self.assertEqual(logical, expected)
        self.assertEqual(set(C.FEATURE_MAP), expected)
        for bad in ("college", "dept", "age_band", "surs_eligibility_band", "sex", "race_eth_rpt_cd"):
            self.assertNotIn(bad, logical)


class TestCheckAndSelect(unittest.TestCase):
    def _mean(self, run, h, skill, auc=0.75, slope=1.0, citl=0.0, ece=0.01, cov=0.8):
        return dict(run=run, horizon=h, auc_roc=auc, auc_roc_step=0.70, auc_pr=0.12, auc_pr_step=0.09, prevalence=0.05,
                    brier_skill_family=skill, brier_skill_step=0.01, cal_slope=slope, citl=citl, cal_intercept=0.0, ece=ece, grain_coverage=cov)

    def test_check_thresholds_a_uses_the_scorer(self):
        m = self._mean("A-logit", 12, 0.03)
        checks = S.check_thresholds_a({**m, "fairness_flag": "none", "age_ablation_gain": 0.0})
        self.assertTrue(S.passes_all(checks))
        self.assertFalse(S.check_thresholds_a({**m, "auc_roc": 0.72, "fairness_flag": "none"})["A1"])   # < step + 0.03
        self.assertFalse(S.check_thresholds_a({**m, "fairness_flag": "adverse"})["A8"])
        self.assertTrue(S.check_thresholds_a({**m, "fairness_flag": "below_4_5"})["A8"])
        self.assertTrue(S.check_thresholds_a({**m, "age_ablation_gain": 0.031})["A9_review_required"])

    def test_selection_rule_and_tie_break(self):
        rows = [self._mean("A-logit", 12, 0.030), self._mean("A-rf", 12, 0.034), self._mean("A-gbm", 12, 0.040),
                self._mean("A-base-step", 12, 0.0, auc=0.70), self._mean("A-base-family", 12, 0.0, auc=0.6)]
        mean = pd.DataFrame(rows)
        fair = pd.DataFrame([dict(run=r, horizon=12, attribute="sex", fairness_flag="none") for r in ("A-logit", "A-rf", "A-gbm", "A-base-step", "A-base-family")])
        thr = EV.threshold_table(mean, fair)
        sel = EV.select_primary(mean, thr)
        self.assertEqual(sel["primary"], "A-gbm")                       # best skill, no tie within 0.5 pp
        mean.loc[mean["run"] == "A-gbm", "brier_skill_family"] = 0.038   # within 0.5 pp of RF -> simpler learner wins
        thr = EV.threshold_table(mean, fair)
        self.assertEqual(EV.select_primary(mean, thr)["primary"], "A-rf")
        fair.loc[fair["run"] == "A-rf", "fairness_flag"] = "adverse"      # A8 removes RF
        thr = EV.threshold_table(mean, fair)
        self.assertEqual(EV.select_primary(mean, thr)["primary"], "A-gbm")
        fair["fairness_flag"] = "adverse"
        thr = EV.threshold_table(mean, fair)
        sel = EV.select_primary(mean, thr)
        self.assertIsNone(sel["primary"])
        self.assertEqual(sel["published_default"], "A-base-step")

    def test_evaluation_json_records_the_pinned_constants(self):
        p = C.HERE / "outputs" / "evaluation.json"
        if not p.exists():
            self.skipTest("no full run outputs present")
        ev = json.loads(p.read_text(encoding="utf-8"))
        rec = {k: (tuple(v) if isinstance(v, list) else v) for k, v in ev["thresholds_constants"].items()}
        self.assertEqual(rec, dict(S.THRESHOLDS_A))
        self.assertEqual(ev["protocol_version"], "wap-protocol-v1")
        self.assertEqual(ev["origins"], [o.isoformat() for o in C.ORIGINS])


if __name__ == "__main__":
    unittest.main()
