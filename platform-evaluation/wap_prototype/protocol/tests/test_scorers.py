"""Hand-computed checks of protocol/scorers.py.

    python -m unittest discover -s wap_prototype/protocol/tests -v     # from platform-evaluation/

Every expected value below is worked by hand (or by an independent closed form written in the
test), not copied from the function under test.
"""
from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import scorers as S  # noqa: E402


def hypergeom_two_sided_p(a, b, c, d):
    """Independent Fisher exact two-sided p for [[a, b], [c, d]]: sum of hypergeometric
    probabilities of tables (with the same margins) no more probable than the observed one."""
    r1, r2, c1 = a + b, c + d, a + c
    n = r1 + r2

    def prob(x):
        return math.comb(r1, x) * math.comb(r2, c1 - x) / math.comb(n, c1)

    p_obs = prob(a)
    lo, hi = max(0, c1 - r2), min(r1, c1)
    return sum(prob(x) for x in range(lo, hi + 1) if prob(x) <= p_obs * (1 + 1e-9))


class TestDiscrimination(unittest.TestCase):
    def test_auc_roc_hand(self):
        # positives scores {0.9, 0.4}, negatives {0.6, 0.3, 0.2}: pairs where pos > neg:
        # 0.9 beats 3, 0.4 beats 2 -> 5 of 6 = 0.8333
        y = [1, 0, 1, 0, 0]
        p = [0.9, 0.6, 0.4, 0.3, 0.2]
        self.assertAlmostEqual(S.auc_roc(y, p), 5 / 6, places=12)

    def test_auc_roc_ties_half_credit(self):
        # pos {0.5, 0.5}, neg {0.5, 0.1}: pairs: (0.5 vs 0.5) tie x2 = 1.0, (0.5 vs 0.1) win x2 = 2 -> 3/4
        self.assertAlmostEqual(S.auc_roc([1, 1, 0, 0], [0.5, 0.5, 0.5, 0.1]), 0.75)

    def test_auc_roc_perfect_and_random(self):
        self.assertEqual(S.auc_roc([0, 0, 1, 1], [0.1, 0.2, 0.8, 0.9]), 1.0)
        self.assertEqual(S.auc_roc([0, 1, 0, 1], [0.5, 0.5, 0.5, 0.5]), 0.5)
        self.assertTrue(math.isnan(S.auc_roc([0, 0], [0.1, 0.2])))

    def test_auc_pr_hand(self):
        # descending: (0.9,1) P=1 R=1/2 -> +0.5*1; (0.6,0); (0.4,1) P=2/3 R=1 -> +0.5*2/3; rest add 0
        y = [1, 0, 1, 0, 0]
        p = [0.9, 0.6, 0.4, 0.3, 0.2]
        self.assertAlmostEqual(S.auc_pr(y, p), 0.5 + 0.5 * 2 / 3, places=12)

    def test_auc_pr_ties_grouped(self):
        # all tied: one threshold with recall 1 and precision = prevalence
        self.assertAlmostEqual(S.auc_pr([1, 0, 0, 1], [0.3, 0.3, 0.3, 0.3]), 0.5)

    def test_prevalence(self):
        self.assertAlmostEqual(S.prevalence([1, 0, 0, 0]), 0.25)


class TestCalibration(unittest.TestCase):
    def test_brier_and_skill(self):
        y, p = [1, 0, 1, 0], [0.8, 0.2, 0.6, 0.4]
        # (0.2^2 + 0.2^2 + 0.4^2 + 0.4^2)/4 = (0.04+0.04+0.16+0.16)/4 = 0.1
        self.assertAlmostEqual(S.brier(y, p), 0.1, places=12)
        ref = [0.5] * 4  # Brier 0.25
        self.assertAlmostEqual(S.brier_skill(y, p, ref), 1 - 0.1 / 0.25, places=12)

    def test_citl(self):
        c = S.calibration([1, 0, 0, 0], [0.5, 0.5, 0.5, 0.5])
        self.assertAlmostEqual(c["citl"], 0.25 - 0.5)

    def test_slope_one_when_group_rates_match(self):
        # Within each prediction value the observed rate equals the prediction, so the logistic
        # score equations are satisfied exactly at intercept 0, slope 1.
        y = [1, 0, 0, 0, 0] + [1, 1, 1, 0, 0] + [1, 1, 1, 1, 0]
        p = [0.2] * 5 + [0.6] * 5 + [0.8] * 5
        c = S.calibration(y, p)
        self.assertAlmostEqual(c["slope"], 1.0, places=6)
        self.assertAlmostEqual(c["intercept"], 0.0, places=6)

    def test_slope_two_when_predictions_are_underconfident(self):
        # true logit = 2 * predicted logit: p=0.5 -> rate 0.5; logit(p)=+1 -> rate sigmoid(2)
        z = 1.0
        q = 1 / (1 + math.exp(-2 * z))  # 0.8808
        pz = 1 / (1 + math.exp(-z))     # 0.7311
        n = 10000
        k_hi = round(q * n)
        y = [1] * k_hi + [0] * (n - k_hi) + [1] * (n // 2) + [0] * (n // 2)
        p = [pz] * n + [0.5] * n
        c = S.calibration(y, p)
        # rounding k_hi perturbs the rate by < 1e-4, so the MLE slope is 2 to ~3 decimals
        self.assertAlmostEqual(c["slope"], 2.0, places=2)
        self.assertAlmostEqual(c["intercept"], 0.0, places=2)

    def test_ece_hand(self):
        # 2 bins of 2: bin1 preds (0.1,0.2) mean 0.15 obs 0 -> 0.15; bin2 preds (0.7,0.9) mean 0.8 obs 0.5 -> 0.3
        # ECE = 0.5*0.15 + 0.5*0.3 = 0.225
        self.assertAlmostEqual(S.ece([0, 0, 1, 0], [0.1, 0.2, 0.7, 0.9], bins=2), 0.225, places=12)

    def test_decile_table(self):
        rows = S.decile_table([0, 1, 1, 1], [0.1, 0.4, 0.6, 0.9], bins=2)
        self.assertEqual([r["n"] for r in rows], [2, 2])
        self.assertAlmostEqual(rows[0]["obs_rate"], 0.5)
        self.assertAlmostEqual(rows[1]["mean_pred"], 0.75)


class TestReportingGrain(unittest.TestCase):
    def test_poisson_binomial_two_coins(self):
        pmf = S.poisson_binomial_pmf([0.5, 0.5])
        np.testing.assert_allclose(pmf, [0.25, 0.5, 0.25])
        self.assertEqual(S.poisson_binomial_quantiles([0.5, 0.5], (0.1, 0.5, 0.9)), [0, 1, 2])

    def test_poisson_binomial_unequal(self):
        # p = 0.2, 0.9: P0 = 0.8*0.1 = 0.08, P1 = 0.2*0.1 + 0.8*0.9 = 0.74, P2 = 0.18
        np.testing.assert_allclose(S.poisson_binomial_pmf([0.2, 0.9]), [0.08, 0.74, 0.18])

    def test_expected_count_cell_suppressed_and_inside(self):
        self.assertTrue(S.expected_count_cell([0.5] * 9)["suppressed"])
        cell = S.expected_count_cell([0.5] * 20, observed=10)
        self.assertFalse(cell["suppressed"])
        self.assertAlmostEqual(cell["expected"], 10.0)
        # Binomial(20, .5): CDF(7)=0.1316 >= 0.1 -> p10 = 7; CDF(12)=0.8684, CDF(13)=0.9423 -> p90 = 13
        self.assertEqual((cell["p10"], cell["p90"]), (7, 13))
        self.assertTrue(cell["inside"])

    def test_reporting_grain_coverage(self):
        cells = [S.expected_count_cell([0.5] * 20, observed=10), S.expected_count_cell([0.5] * 20, observed=20),
                 S.expected_count_cell([0.5] * 5, observed=1), S.expected_count_cell([0.5] * 20)]
        cov = S.reporting_grain_coverage(cells)
        self.assertEqual(cov["n_cells"], 2)
        self.assertAlmostEqual(cov["coverage"], 0.5)
        self.assertAlmostEqual(cov["mean_bias"], ((10 - 10) + (10 - 20)) / 2)


class TestFairness(unittest.TestCase):
    def setUp(self):
        # A: 10 of 20 selected (0.50); B: 3 of 15 selected (0.20); C: 4 of 5 (n < 10, suppressed)
        self.group = ["A"] * 20 + ["B"] * 15 + ["C"] * 5
        self.sel = [1] * 10 + [0] * 10 + [1] * 3 + [0] * 12 + [1] * 4 + [0]

    def test_four_fifths_rows(self):
        rows = {r["group"]: r for r in S.four_fifths(self.group, self.sel)}
        self.assertTrue(rows["C"]["suppressed"])
        self.assertIsNone(rows["C"]["selection_rate"])
        self.assertAlmostEqual(rows["A"]["selection_rate"], 0.5)
        self.assertAlmostEqual(rows["B"]["impact_ratio"], 0.2 / 0.5)
        self.assertAlmostEqual(rows["A"]["impact_ratio"], 1.0)
        # Fisher for B vs others: [[3, 12], [14, 11]]
        self.assertAlmostEqual(rows["B"]["fisher_p"], hypergeom_two_sided_p(3, 12, 14, 11), places=10)
        # suppressed group C (highest raw rate) must not set the reference rate
        self.assertEqual(max(r["impact_ratio"] for r in rows.values() if not r["suppressed"]), 1.0)

    def test_four_fifths_flags(self):
        rows = {r["group"]: r for r in S.four_fifths(self.group, self.sel)}
        p_b = hypergeom_two_sided_p(3, 12, 14, 11)
        self.assertEqual(rows["B"]["flag"], S.FLAG_ADVERSE if p_b < 0.05 else S.FLAG_BELOW)
        # a ratio below 0.8 with a clearly non-significant test -> "below 4/5, not significant"
        g = ["A"] * 10 + ["B"] * 10
        s = [1, 1, 1, 1, 1, 0, 0, 0, 0, 0] + [1, 1, 1, 0, 0, 0, 0, 0, 0, 0]  # 0.5 vs 0.3 -> ratio 0.6
        rows = {r["group"]: r for r in S.four_fifths(g, s)}
        self.assertEqual(rows["B"]["flag"], S.FLAG_BELOW)
        self.assertEqual(rows["A"]["flag"], "")

    def test_equalized_odds_hand(self):
        # group X: 10 positives (TPR 8/10), 10 negatives (FPR 2/10); group Y: 10 pos (TPR 4/10), 10 neg (FPR 1/10)
        group = ["X"] * 20 + ["Y"] * 20
        label = ([1] * 10 + [0] * 10) * 2
        sel = [1] * 8 + [0] * 2 + [1] * 2 + [0] * 8 + [1] * 4 + [0] * 6 + [1] * 1 + [0] * 9
        eo = S.equalized_odds_gaps(group, sel, label)
        self.assertAlmostEqual(eo["by_group"]["X"]["tpr"], 0.8)
        self.assertAlmostEqual(eo["by_group"]["Y"]["fpr"], 0.1)
        self.assertAlmostEqual(eo["tpr_gap"], 0.4)
        self.assertAlmostEqual(eo["fpr_gap"], 0.1)
        self.assertEqual(eo["groups_suppressed"], 0)

    def test_equalized_odds_tpr_needs_k_positives(self):
        group = ["X"] * 12
        label = [1] * 5 + [0] * 7
        sel = [1] * 5 + [0] * 7
        eo = S.equalized_odds_gaps(group, sel, label)
        self.assertIsNone(eo["by_group"]["X"]["tpr"])   # only 5 positives
        self.assertIsNone(eo["by_group"]["X"]["fpr"])   # only 7 negatives

    def test_fairness_summary(self):
        ff = S.four_fifths(self.group, self.sel)
        eo = S.equalized_odds_gaps(self.group, self.sel, self.sel)
        summ = S.fairness_summary(ff, eo)
        self.assertEqual(summ["groups_suppressed"], 1)
        self.assertAlmostEqual(summ["min_impact_ratio"], 0.4)
        self.assertIn(summ["fairness_flag"], ("adverse", "below_4_5"))


class TestForecast(unittest.TestCase):
    def test_mase_scale_and_mase(self):
        y_train = [10, 12, 14, 16, 11, 13, 15, 17]
        # lag-4 differences: 1, 1, 1, 1 -> scale 1
        self.assertAlmostEqual(S.mase_scale(y_train, m=4), 1.0)
        np.testing.assert_allclose(S.mase([20, 30], [18, 33], 1.0), [2.0, 3.0])
        np.testing.assert_allclose(S.mase([20, 30], [18, 33], [2.0, 1.5]), [1.0, 2.0])

    def test_mase_scale_nan_aware(self):
        self.assertAlmostEqual(S.mase_scale([1, 2, 3, 4, 3, np.nan, 5, 6], m=4), (2 + 2 + 2) / 3)
        self.assertTrue(math.isnan(S.mase_scale([1, 2, 3], m=4)))

    def test_smape_hand(self):
        # 200*|100-80|/(180) = 22.222...; both zero -> 0
        np.testing.assert_allclose(S.smape([100, 0], [80, 0]), [200 * 20 / 180, 0.0])

    def test_interval_coverage(self):
        self.assertAlmostEqual(S.interval_coverage([1, 5, 10, np.nan], [0, 6, 9, 0], [2, 7, 11, 1]), 2 / 3)
        self.assertTrue(math.isnan(S.interval_coverage([np.nan], [0], [1])))

    def test_relative_mase(self):
        self.assertAlmostEqual(S.relative_mase([0.8, 1.0], [1.0, 1.0]), 0.9)


class TestThresholds(unittest.TestCase):
    def test_model_a_pass_and_fail(self):
        good = dict(auc_roc=0.70, auc_roc_step=0.60, auc_pr=0.30, prevalence=0.10, auc_pr_step=0.15,
                    brier_skill_family=0.05, brier_skill_step=0.01, cal_slope=1.0, citl=0.002, ece=0.01,
                    grain_coverage=0.8, fairness_flag="none", age_ablation_gain=0.01)
        checks = S.check_thresholds_a(good)
        self.assertTrue(S.passes_all(checks))
        self.assertFalse(checks["A9_review_required"])
        bad = good | dict(cal_slope=0.8, fairness_flag="adverse", age_ablation_gain=0.05)
        checks = S.check_thresholds_a(bad)
        self.assertFalse(checks["A4"])
        self.assertFalse(checks["A8"])
        self.assertTrue(checks["A9_review_required"])
        self.assertFalse(S.passes_all(checks))

    def test_model_b_pass_and_fail(self):
        good = dict(rel_mase_h1_4=0.9, rel_mase_h5_12=0.98, cov80=0.78, cov95=0.93, h4_bias_share=0.01,
                    hierarchy_discrepancy=0.02, flag_precision=0.7)
        self.assertTrue(S.passes_all(S.check_thresholds_b(good)))
        bad = good | dict(rel_mase_h1_4=0.96, cov80=0.95)
        checks = S.check_thresholds_b(bad)
        self.assertFalse(checks["B1"])
        self.assertFalse(checks["B3"])

    def test_thresholds_are_the_protocol_values(self):
        # pinned so a silent edit of scorers.py fails a test (AGENTS.md rule 4)
        self.assertEqual(S.THRESHOLDS_A["A1_auc_roc_min"], 0.62)
        self.assertEqual(S.THRESHOLDS_A["A6_ece_max"], 0.02)
        self.assertEqual(S.THRESHOLDS_B["B1_rel_mase_h1_4_max"], 0.95)
        self.assertEqual(S.THRESHOLDS_B["B4_cov95_min"], 0.88)
        self.assertEqual(S.K_MIN, 10)
        self.assertEqual(S.PROTOCOL_VERSION, "wap-protocol-v1")


if __name__ == "__main__":
    unittest.main()
