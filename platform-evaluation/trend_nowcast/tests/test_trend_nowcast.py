"""Tests for the trend-to-reality nowcast.

Run from platform-evaluation/:  python -m unittest discover -s trend_nowcast/tests -v
Unit tests use synthetic series with known answers; integration tests read the built
artifacts (run build.py and render_html.py first) and skip if they are missing.
"""
import json
import math
import re
import sys
import unittest
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import tn_lib as L  # noqa: E402

RESULTS = HERE / "artifacts" / "results.json"
PANEL = HERE / "artifacts" / "aligned_quarterly_panel.parquet"
HTML = ROOT / "output" / "trend_nowcast" / "trend_nowcast.html"


def seasonal_level(n=40, start=L.qkey(2010, 1), growth=0.0, noise=0.0, seed=0):
    rng = np.random.default_rng(seed)
    season = {1: 0.0, 2: 0.05, 3: 0.30, 4: 0.02}
    return {start + i: math.exp(9 + growth * i + season[L.qtr_of(start + i)] + noise * rng.standard_normal()) for i in range(n)}


class QuarterKeys(unittest.TestCase):
    def test_roundtrip(self):
        for lab in ("2019Q1", "2020Q4", "2026Q3"):
            self.assertEqual(L.qlabel(L.qparse(lab)), lab)
        self.assertEqual(L.qkey(2021, 1) - L.qkey(2020, 4), 1)

    def test_covid_window(self):
        self.assertEqual(sorted(L.qlabel(k) for k in L.COVID_FIT_EXCLUDE), ["2020Q2", "2020Q3", "2020Q4", "2021Q1", "2021Q2"])


class Transforms(unittest.TestCase):
    def test_yoy_removes_fixed_seasonality(self):
        g = L.yoy(seasonal_level(growth=0.01))
        self.assertTrue(all(abs(v - 0.04) < 1e-12 for v in g.values()))

    def test_deseasonalize_by_quarter(self):
        d = L.diff(L.log_series(seasonal_level()), 1)
        sa = L.deseasonalize_by_quarter(d)
        self.assertLess(max(abs(v) for v in sa.values()), 1e-12)

    def test_quarter_mean_counts(self):
        qm = L.quarter_mean([(1, 2.0), (1, 4.0), (2, 5.0), (2, None)])
        self.assertEqual(qm[1], (3.0, 2))
        self.assertEqual(qm[2], (5.0, 1))


class LeadLag(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(1)
        ks = [L.qkey(2000, 1) + i for i in range(60)]
        x = rng.standard_normal(60)
        y = np.r_[0, 0, 0.9 * x[:-2]] + 0.3 * rng.standard_normal(60)  # x leads y by 2 quarters
        self.x = dict(zip(ks, x))
        self.y = dict(zip(ks, y))
        self.noise = dict(zip(ks, rng.standard_normal(60)))

    def test_prewhitened_ccf_peaks_at_true_lead(self):
        c = L.prewhitened_ccf(self.x, self.y, range(-2, 5))
        self.assertEqual(max(c["ccf"], key=lambda k: abs(c["ccf"][k])), 2)
        self.assertGreater(c["ccf"][2], c["band"])

    def test_granger_detects_and_rejects(self):
        self.assertLess(L.granger_test(self.y, self.x, 2)["pvalue"], 0.001)
        self.assertGreater(L.granger_test(self.noise, self.x, 2)["pvalue"], 0.01)

    def test_granger_needs_degrees_of_freedom(self):
        few = {k: v for k, v in list(self.y.items())[:9]}
        self.assertIsNone(L.granger_test(few, self.x, 2))

    def test_bh_qvalues(self):
        q = L.bh_qvalues([0.01, 0.04, 0.03, 0.5])
        self.assertAlmostEqual(q[0], 0.04)
        self.assertAlmostEqual(q[1], 0.04 * 4 / 3)
        self.assertAlmostEqual(q[2], 0.04 * 4 / 3)
        self.assertAlmostEqual(q[3], 0.5)
        self.assertTrue(all(a <= 1 for a in q))


class Forecasting(unittest.TestCase):
    def test_seasonal_naive_is_exact_on_pure_seasonal_series(self):
        lv = seasonal_level()
        bt = L.rolling_origin_backtest(lv, 1, {"seasonal_naive": {"kind": "naive"}}, list(lv)[20:])
        self.assertAlmostEqual(bt["models"]["seasonal_naive"]["rmse"], 0.0, places=12)

    def test_informative_signal_adds_skill_and_no_lookahead(self):
        rng = np.random.default_rng(3)
        ks = [L.qkey(2005, 1) + i for i in range(48)]
        sig = {k: 0.05 * rng.standard_normal() for k in ks}
        lv, cur = {}, 10.0
        for i, k in enumerate(ks):  # YoY growth driven by the signal of the same quarter
            lv[k] = math.exp(cur) if i < 4 else lv[ks[i - 4]] * math.exp(sig[k] + 0.002 * rng.standard_normal())
        models = {"seasonal_naive": {"kind": "naive"}, "own_lag": {"kind": "ols", "extra": []},
                  "with_signal": {"kind": "ols", "extra": [sig]}}
        bt = L.rolling_origin_backtest(lv, 1, models, ks[20:])
        self.assertGreater(bt["models"]["with_signal"]["skill_vs_naive"], 0.9)
        self.assertLess(bt["models"]["with_signal"]["dm_vs_naive"]["pvalue"], 0.05)
        # changing a future value must not change an earlier forecast (expanding window only)
        lv2 = dict(lv)
        lv2[ks[-1]] *= 5
        bt2 = L.rolling_origin_backtest(lv2, 1, models, ks[20:])
        self.assertEqual(bt["models"]["with_signal"]["forecast_growth"][:-1], bt2["models"]["with_signal"]["forecast_growth"][:-1])

    def test_dm_sign(self):
        rng = np.random.default_rng(5)
        e_small, e_big = 0.1 * rng.standard_normal(30), rng.standard_normal(30)
        r = L.dm_test(e_small, e_big, 1)
        self.assertLess(r["stat"], 0)
        self.assertLess(r["pvalue"], 0.01)


class Divergence(unittest.TestCase):
    def test_outlier_is_flagged_and_fit_excludes_covid(self):
        rng = np.random.default_rng(9)
        ks = [L.qkey(2017, 1) + i for i in range(36)]
        drv = {k: rng.standard_normal() * 0.02 for k in ks}
        act = {k: 0.01 + 0.8 * drv[k] + 0.002 * rng.standard_normal() for k in ks}
        act[ks[-1]] += 0.05
        for k in L.COVID_FIT_EXCLUDE:
            act[k] = -0.5  # wild values that must not move the fit
        rows = L.divergence_z(act, drv, fit_exclude=L.COVID_FIT_EXCLUDE)
        self.assertGreater(rows[-1]["z"], 5)
        self.assertAlmostEqual(rows[0]["beta"], 0.8, delta=0.05)
        self.assertTrue(all(abs(r["z"]) < 4 for r in rows[:-1] if not r["covid"]))

    def test_spearman_perm(self):
        r = L.spearman_with_perm(list(range(20)), list(range(20)), n_perm=500)
        self.assertAlmostEqual(r["rho"], 1.0)
        self.assertLess(r["pvalue"], 0.01)


@unittest.skipUnless(RESULTS.exists(), "run trend_nowcast/build.py first")
class Artifacts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = json.loads(RESULTS.read_text())

    def test_panel_alignment(self):
        import duckdb
        rows = duckdb.sql(f"SELECT series_id, min(year*4+qtr-1), max(year*4+qtr-1), count(*) FROM '{PANEL}' GROUP BY 1").fetchall()
        d = {r[0]: r[1:] for r in rows}
        self.assertEqual(L.qlabel(d["qcew_il_priv_emp"][0]), "2019Q1")
        self.assertEqual(L.qlabel(d["qcew_il_priv_emp"][1]), "2025Q4")
        self.assertEqual(L.qlabel(d["us_total"][0]), "2020Q1")  # Indeed starts 1 Feb 2020
        # no incomplete Indeed quarter other than 2020Q1
        self.assertTrue(set(self.r["provenance"]["indeed_partial_quarters"]) - {"2020Q1"} <= {"2026Q4"})
        self.assertLessEqual(d["us_total"][1], L.qkey(2026, 3))
        # QCEW IL state 2025 cells are suppressed and must stay missing, not zero
        self.assertEqual(L.qlabel(d["qcew_il_state_emp"][1]), "2024Q4")
        zero = duckdb.sql(f"SELECT count(*) FROM '{PANEL}' WHERE value = 0").fetchall()[0][0]
        self.assertEqual(zero, 0)

    def test_qwi_known_value(self):
        # 2024Q3 QWI hires (sex 0, agegrp A00) from the lake contract table
        pts = {p["q"]: p["v"] for p in self.r["series"]["qwi_il_hires"]["points"]}
        self.assertEqual(pts["2024Q3"], 17123.0)

    def test_provisional_quarters_not_scored(self):
        prov = set(self.r["provenance"]["qwi_provisional_quarters"])
        self.assertEqual(len(prov), 2)
        for t, tr in self.r["nowcast"]["results"].items():
            for h, bt in tr["backtest"].items():
                if t.startswith("qwi"):
                    self.assertFalse(prov & set(bt["eval_quarters"]), (t, h))
                self.assertGreaterEqual(len(bt["eval_quarters"]), 8)

    def test_all_models_scored_on_same_quarters(self):
        for tr in self.r["nowcast"]["results"].values():
            for bt in tr["backtest"].values():
                ns = {m["n"] for m in bt["models"].values()}
                self.assertEqual(ns, {len(bt["eval_quarters"])})

    def test_granger_qvalues_present(self):
        g = self.r["lead_lag"]["granger"]
        self.assertTrue(g)
        self.assertTrue(all(0 <= x["pvalue"] <= 1 and x["pvalue"] <= x["qvalue"] + 1e-12 for x in g))
        self.assertTrue(all(L.qparse(x["first"]) >= L.qkey(2022, 1) for x in g if x["sample"] == "post_covid"))

    def test_occupation_context_is_descriptive(self):
        oc = self.r["occupation"]
        self.assertGreaterEqual(len(oc["rows"]), 20)
        for row in oc["rows"]:
            self.assertTrue(0 <= row["aei_observed_exposure_mean"] <= 1)
            self.assertNotIn("score", " ".join(row))  # no combined job-loss score
        # conversation shares are percents of all conversations: no double counting across sectors
        total = sum(r["aei_usage_share_pct"] for r in oc["rows"])
        self.assertLessEqual(total, oc["aei_usage_share_matched_pct"] + 1e-9)
        self.assertLessEqual(oc["aei_usage_share_matched_pct"], 100 + 1e-9)

    @unittest.skipUnless(HTML.exists(), "run render_html.py first")
    def test_html_is_offline(self):
        page = HTML.read_text()
        self.assertIsNone(re.search(r'(src|href)=["\']https?://', page))
        self.assertIn("prefers-color-scheme:dark", page)
        self.assertIn('name="viewport"', page)
        self.assertIn("General trend vs what's actually happening", page)


if __name__ == "__main__":
    unittest.main()
