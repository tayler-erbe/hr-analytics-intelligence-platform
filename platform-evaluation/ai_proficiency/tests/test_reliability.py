"""Statistics checked against small hand-computed examples and published values.

Run from platform-evaluation/ai_proficiency/:
    python -m unittest discover -s tests -v

Each hand computation is written out in the docstring so a reviewer can redo it
on paper.
"""
import math
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import reliability as R  # noqa: E402

NAN = np.nan


class WeightedKappa(unittest.TestCase):
    """Rater 1 = [1,2,3,1,2,3], rater 2 = [1,2,2,1,3,3], categories 1..3.

    Pairs: (1,1)(2,2)(3,2)(1,1)(2,3)(3,3) -> 4 exact, 2 off by one.
    Both raters' marginals are 1/3 each, so every expected cell is 1/9.
    Quadratic w = d^2/4: observed = 2 * (1/4) / 6 = 1/12;
      expected = (1/9) * (4 cells * 1/4 + 2 cells * 1) = 1/3; kappa = 1 - (1/12)/(1/3) = 0.75.
    Linear w = d/2: observed = 2 * (1/2) / 6 = 1/6; expected = (1/9)(4*1/2 + 2*1) = 4/9;
      kappa = 1 - (1/6)/(4/9) = 0.625.
    Unweighted: p0 = 4/6, pe = 1/3, kappa = (2/3 - 1/3)/(2/3) = 0.5.
    """
    a = [1, 2, 3, 1, 2, 3]
    b = [1, 2, 2, 1, 3, 3]

    def test_quadratic(self):
        self.assertAlmostEqual(R.weighted_kappa(self.a, self.b, [1, 2, 3], "quadratic"), 0.75)

    def test_linear(self):
        self.assertAlmostEqual(R.weighted_kappa(self.a, self.b, [1, 2, 3], "linear"), 0.625)

    def test_unweighted(self):
        self.assertAlmostEqual(R.cohen_kappa(self.a, self.b, [1, 2, 3]), 0.5)

    def test_perfect_agreement(self):
        self.assertAlmostEqual(R.weighted_kappa([1, 2, 3, 4], [1, 2, 3, 4], [1, 2, 3, 4]), 1.0)

    def test_missing_pairs_dropped(self):
        self.assertAlmostEqual(R.weighted_kappa(self.a + [NAN], self.b + [2], [1, 2, 3]), 0.75)

    def test_unused_category_leaves_kappa_unchanged(self):
        # Declaring a 4th, unused category rescales quadratic weights by (k-1)^2 in
        # both numerator and denominator, so kappa is unchanged.
        self.assertAlmostEqual(R.weighted_kappa(self.a, self.b, [1, 2, 3, 4]), 0.75)


class KrippendorffAlpha(unittest.TestCase):
    """Hand example: 2 raters x 3 units: (1,1), (2,3), (3,3).

    Coincidences: o11 = 2, o23 = o32 = 1, o33 = 2; n1 = 2, n2 = 1, n3 = 3, n = 6.
    alpha = 1 - (n-1) * sum(o*d2) / sum(n_c n_k d2).
    Nominal: sum(o d) = 2; sum(nn d) = 2*(2*1 + 2*3 + 1*3) = 22 -> 1 - 5*2/22 = 6/11.
    Interval: sum(o d2) = 2; sum(nn d2) = 2*(2*1*1 + 2*3*4 + 1*3*1) = 58 -> 1 - 10/58 = 24/29.
    Ordinal: d2(1,2) = (3 - 1.5)^2 = 2.25; d2(2,3) = (4 - 2)^2 = 4; d2(1,3) = (6 - 2.5)^2 = 12.25.
      sum(o d2) = 2*4 = 8; sum(nn d2) = 2*(2*2.25 + 6*12.25 + 3*4) = 180 -> 1 - 40/180 = 7/9.
    """
    data = [[1, 2, 3], [1, 3, 3]]

    def test_nominal(self):
        self.assertAlmostEqual(R.krippendorff_alpha(self.data, "nominal"), 6 / 11)

    def test_interval(self):
        self.assertAlmostEqual(R.krippendorff_alpha(self.data, "interval"), 24 / 29)

    def test_ordinal(self):
        self.assertAlmostEqual(R.krippendorff_alpha(self.data, "ordinal"), 7 / 9)

    def test_published_example(self):
        """Krippendorff (2011), 4 observers x 12 units with missing data:
        nominal .743, ordinal .815, interval .849 (published, to 3 dp)."""
        d = [[1, 2, 3, 3, 2, 1, 4, 1, 2, NAN, NAN, NAN],
             [1, 2, 3, 3, 2, 2, 4, 1, 2, 5, NAN, 3],
             [NAN, 3, 3, 3, 2, 3, 4, 2, 2, 5, 1, NAN],
             [1, 2, 3, 3, 2, 4, 4, 1, 2, 5, 1, NAN]]
        self.assertAlmostEqual(R.krippendorff_alpha(d, "nominal"), 0.743, places=3)
        self.assertAlmostEqual(R.krippendorff_alpha(d, "ordinal"), 0.815, places=3)
        self.assertAlmostEqual(R.krippendorff_alpha(d, "interval"), 0.849, places=3)

    def test_unpairable_units_ignored(self):
        with_single = [[1, 2, 3, 4], [1, 3, 3, NAN]]
        self.assertAlmostEqual(R.krippendorff_alpha(with_single, "ordinal"), 7 / 9)


class ICC(unittest.TestCase):
    """Hand example: 3 subjects x 2 raters: [1,2], [3,3], [4,5].

    Grand mean 3; row means 1.5, 3, 4.5; column means 8/3, 10/3.
    SST = 10, SSR = 2*(2.25+0+2.25) = 9, SSC = 3*(1/9+1/9) = 2/3, SSE = 1/3.
    MSR = 4.5, MSC = 2/3, MSE = (1/3)/2 = 1/6.
    ICC(2,1) = (4.5 - 1/6) / (4.5 + 1/6 + 2*(2/3 - 1/6)/3) = (13/3)/5 = 13/15.
    ICC(2,k) = (4.5 - 1/6) / (4.5 + (2/3 - 1/6)/3) = (13/3)/(14/3) = 13/14.
    ICC(3,1) = (13/3)/(4.5 + 1/6) = 13/14.
    """
    x = [[1, 2], [3, 3], [4, 5]]

    def test_hand(self):
        r = R.icc(self.x)
        self.assertAlmostEqual(r["MSR"], 4.5)
        self.assertAlmostEqual(r["MSC"], 2 / 3)
        self.assertAlmostEqual(r["MSE"], 1 / 6)
        self.assertAlmostEqual(r["ICC(2,1)"], 13 / 15)
        self.assertAlmostEqual(r["ICC(2,k)"], 13 / 14)
        self.assertAlmostEqual(r["ICC(3,1)"], 13 / 14)

    def test_shrout_fleiss_1979(self):
        """Shrout & Fleiss (1979) Table 2: ICC(1,1)=.17, (2,1)=.29, (3,1)=.71,
        (1,4)=.44, (2,4)=.62, (3,4)=.91."""
        sf = [[9, 2, 5, 8], [6, 1, 3, 2], [8, 4, 6, 8], [7, 1, 2, 6], [10, 5, 6, 9], [6, 2, 4, 7]]
        r = R.icc(sf)
        for key, val in [("ICC(1,1)", .17), ("ICC(2,1)", .29), ("ICC(3,1)", .71),
                         ("ICC(1,k)", .44), ("ICC(2,k)", .62), ("ICC(3,k)", .91)]:
            self.assertAlmostEqual(r[key], val, delta=0.006, msg=key)

    def test_requires_complete_matrix(self):
        with self.assertRaises(ValueError):
            R.icc([[1, NAN], [2, 3]])


class ItemAnalysis(unittest.TestCase):
    """Cronbach: persons [1,2],[2,2],[3,4]. Item variances 1 and 4/3; total [3,4,7]
    variance 13/3. alpha = 2 * (1 - (7/3)/(13/3)) = 12/13."""

    def test_cronbach(self):
        self.assertAlmostEqual(R.cronbach_alpha([[1, 2], [2, 2], [3, 4]]), 12 / 13)

    def test_item_rest_and_flags(self):
        rng = np.random.default_rng(0)
        theta = rng.normal(size=300)
        good = np.column_stack([theta + rng.normal(0, .5, 300) for _ in range(4)])
        noise = rng.normal(size=(300, 1))
        res = R.item_analysis(np.hstack([good, noise]), ["a", "b", "c", "d", "junk"])
        junk = res["items"][-1]
        self.assertLess(junk["item_rest_r"], 0.3)
        self.assertTrue(any("item-rest" in f for f in junk["flags"]))
        self.assertGreater(junk["alpha_if_deleted"], res["alpha"])

    def test_sem(self):
        self.assertAlmostEqual(R.sem(4.0, 0.75), 2.0)


class Angoff(unittest.TestCase):
    """Panelists (2.5, 3.0), (3.0, 3.0), (2.0, 3.5): totals 5.5, 6.0, 5.5.
    Cut = 17/3. SD of totals = sqrt(((-1/6)^2 + (1/3)^2 + (-1/6)^2)/2) = sqrt(1/12).
    SE = sqrt(1/12)/sqrt(3) = 1/6. Item means 2.5 and 19/6."""

    def test_hand(self):
        r = R.angoff([[2.5, 3.0], [3.0, 3.0], [2.0, 3.5]], ["x", "y"])
        self.assertAlmostEqual(r["cut"], 17 / 3)
        self.assertAlmostEqual(r["sd_totals"], math.sqrt(1 / 12))
        self.assertAlmostEqual(r["se_cut"], 1 / 6)
        self.assertAlmostEqual(r["item_means"]["x"], 2.5)
        self.assertAlmostEqual(r["item_means"]["y"], 19 / 6)

    def test_impact(self):
        r = R.angoff_impact([10, 12, 14, 16], 13, se=0.5)
        self.assertEqual(r["pass_rate"], 0.5)
        self.assertEqual(r["pass_rate_cut_minus_2se"], 0.75)  # cut 12
        self.assertEqual(r["pass_rate_cut_plus_2se"], 0.5)    # cut 14


class DecisionConsistency(unittest.TestCase):
    """A = [N,C,C,P,P,N], B = [N,C,P,P,P,C]. p0 = 4/6.
    Marginals A: 2,2,2; B: 1,2,3. pe = (2*1 + 2*2 + 2*3)/36 = 1/3.
    kappa = (2/3 - 1/3)/(2/3) = 0.5."""

    def test_hand(self):
        r = R.decision_consistency(list("NCCPPN"), list("NCPPPC"), ["N", "C", "P"])
        self.assertAlmostEqual(r["p0"], 4 / 6)
        self.assertAlmostEqual(r["kappa"], 0.5)
        self.assertEqual(r["confusion"], [[1, 1, 0], [0, 1, 1], [0, 0, 2]])


class RaterQuality(unittest.TestCase):
    def test_drift_slope(self):
        """Session biases 0, .5, 1, 1.5 -> OLS slope exactly 0.5 per session."""
        recs = []
        for s, bias in enumerate([0, 0.5, 1.0, 1.5], start=1):
            # two anchor papers per session (master 2) whose deviations average `bias`
            recs += [{"rater": "X", "session": s, "score": 2 + bias - 0.25, "master": 2},
                     {"rater": "X", "session": s, "score": 2 + bias + 0.25, "master": 2}]
            recs += [{"rater": "Y", "session": s, "score": 2, "master": 2}] * 2
        out = R.rater_drift(recs)
        self.assertAlmostEqual(out["X"]["bias"][-1], 1.5)
        self.assertAlmostEqual(out["X"]["slope"], 0.5)
        self.assertTrue(out["X"]["drift_flag"])
        self.assertFalse(out["Y"]["flag"])

    def test_severity(self):
        """One unit, three raters scoring 2, 3, 4: each rater vs mean of the others:
        2 - 3.5 = -1.5, 3 - 3 = 0, 4 - 2.5 = +1.5."""
        recs = [{"rater": r, "unit": "u", "dim": "D1", "score": s} for r, s in (("A", 2), ("B", 3), ("C", 4))]
        sev = R.rater_severity(recs)
        self.assertAlmostEqual(sev["A"]["mean_dev"], -1.5)
        self.assertAlmostEqual(sev["B"]["mean_dev"], 0.0)
        self.assertAlmostEqual(sev["C"]["mean_dev"], 1.5)


class Fairness(unittest.TestCase):
    def _mh_data(self):
        """Stratum 1: ref 10 right/10 wrong, focal 5/15. Stratum 2: ref 15/5, focal 10/10."""
        correct, focal, strata = [], [], []
        for s, (ar, br, cf, df) in {1: (10, 10, 5, 15), 2: (15, 5, 10, 10)}.items():
            correct += [1] * ar + [0] * br + [1] * cf + [0] * df
            focal += [False] * (ar + br) + [True] * (cf + df)
            strata += [s] * (ar + br + cf + df)
        return correct, focal, strata

    def test_mantel_haenszel(self):
        """sum(AD/N) = 3.75 + 3.75, sum(BC/N) = 1.25 + 1.25 -> alpha_MH = 3, delta = -2.35 ln 3.
        E(A) = 7.5 and 12.5; Var(A) = 20*20*15*25/(40^2*39) = 2.4038 in each stratum.
        chi2 = (|25 - 20| - 0.5)^2 / 4.8077 = 4.212."""
        r = R.mantel_haenszel_dif(*self._mh_data())
        self.assertAlmostEqual(r["alpha_mh"], 3.0)
        self.assertAlmostEqual(r["delta_mh"], -2.35 * math.log(3))
        self.assertAlmostEqual(r["chi2"], 20.25 / (2 * 150000 / 62400), places=6)
        self.assertEqual(r["ets_class"], "C")

    def test_smd(self):
        """Stratum a: focal [2,2] (mean 2), ref [3] -> -1, weight 2.
        Stratum b: focal [3] (mean 3), ref [3,3] -> 0, weight 1. SMD = -2/3."""
        r = R.standardized_mean_difference([2, 2, 3, 3, 3, 3], [True, True, False, True, False, False],
                                           ["a", "a", "a", "b", "b", "b"])
        self.assertAlmostEqual(r, -2 / 3)

    def test_fisher_exact(self):
        """Table [[3,1],[1,3]]: P(a=x) over x=0..4 = 1,16,36,16,1 / 70.
        Two-sided p = (1+16+16+1)/70 = 34/70."""
        self.assertAlmostEqual(R.fisher_exact_two_sided(3, 1, 1, 3), 34 / 70)

    def test_impact_ratio_and_suppression(self):
        outcome = [True] * 8 + [False] * 2 + [True] * 5 + [False] * 5 + [True] * 3
        group = ["A"] * 10 + ["B"] * 10 + ["C"] * 3
        r = R.impact_ratios(outcome, group)
        self.assertAlmostEqual(r["B"]["ratio_to_top"], 0.5 / 0.8)
        self.assertTrue(r["B"]["four_fifths_flag"])
        self.assertTrue(r["C"]["suppressed"])
        self.assertNotIn("rate", r["C"])


if __name__ == "__main__":
    unittest.main()
