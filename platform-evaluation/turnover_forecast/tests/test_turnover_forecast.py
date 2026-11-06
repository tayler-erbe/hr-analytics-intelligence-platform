"""Tests: no look-ahead in backtests, reproducibility, metric correctness, panel integrity.

Run from platform-evaluation/:  python -m unittest discover -s turnover_forecast/tests -v
Needs data/panel.parquet (panel.py); the stored-backtest checks also need backtest.parquet.
"""
from __future__ import annotations

import json
import math
import sys
import unittest
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import backtest as B  # noqa: E402
import models as M  # noqa: E402
import series as S  # noqa: E402

D = S.load()
T0 = S.parse_label("2014Q3")


def _perturbed(d: S.Data, T: int, seed: int = 0) -> S.Data:
    """Same data up to T; every later value replaced by noise (or deleted)."""
    rng = np.random.default_rng(seed)
    out = S.Data(d.states, d.n_q)
    for k, a in d.raw.items():
        b = a.copy()
        tail = b[:, T + 1:]
        b[:, T + 1:] = np.where(rng.random(tail.shape) < 0.2, np.nan, tail * rng.uniform(0.2, 5.0, tail.shape))
        out.raw[k] = b
    return out


class NoLeakage(unittest.TestCase):
    def test_truncate_blanks_future(self):
        t = S.truncate(D, T0)
        for a in t.raw.values():
            self.assertTrue(np.all(np.isnan(a[:, T0 + 1:])))
        self.assertTrue(np.array_equal(t.get("6113", "A00", "sep")[:, : T0 + 1],
                                       D.get("6113", "A00", "sep")[:, : T0 + 1], equal_nan=True))

    def test_design_ignores_future_even_without_truncation(self):
        for name in ("sep_rate", "sep_55p"):
            a, b = M.design(D, name, T0), M.design(_perturbed(D, T0), name, T0)
            for k in ("X", "y", "Xp", "base_p"):
                self.assertTrue(np.array_equal(a[k], b[k], equal_nan=True), (name, k))

    def test_design_training_targets_end_at_origin(self):
        des = M.design(D, "sep_rate", T0)
        # rebuild target quarters: base quarter s satisfies lL[s] = base; check via the h column and
        # the fact that no row's target can be reconstructed past T0 by perturbing only T0+1..
        b = M.design(_perturbed(D, T0, seed=3), "sep_rate", T0)
        self.assertEqual(len(des["y"]), len(b["y"]))
        self.assertGreater(len(des["y"]), 1000)

    def test_prediction_rows_have_no_covid_oracle(self):
        T = S.parse_label("2021Q1")
        des = M.design(D, "sep_rate", T)
        col = des["names"].index("covid_target")
        self.assertTrue(np.all(des["Xp"][:, col] == 0))  # forecasts never get the shock dummy
        self.assertTrue(np.any(des["X"][:, col] == 1))   # training rows inside the window do
        pre = M.design(D, "sep_rate", S.parse_label("2019Q4"))
        self.assertFalse(np.any(pre["X"][:, col] == 1))   # and before 2020 nothing is marked

    def test_univariate_models_ignore_future(self):
        for name in ("sep_rate", "turnover"):
            y, yp = S.target(D, name)[0], S.target(_perturbed(D, T0), name)[0]
            for fn in (M.seasonal_naive, M.ets, M.arima):
                a, b = fn(y, T0), fn(yp, T0)
                self.assertTrue(np.allclose(a["point"], b["point"]), (name, fn.__name__))

    def test_full_forecast_identical_under_future_perturbation(self):
        T = S.parse_label("2012Q1")
        a = B.forecast_at(S.truncate(D, T), "sep_65p", T)
        b = B.forecast_at(S.truncate(_perturbed(D, T, seed=5), T), "sep_65p", T)
        self.assertEqual(set(a), set(b))
        for m in a:
            self.assertTrue(np.allclose(a[m]["point"], b[m]["point"], equal_nan=True), m)

    def test_empirical_intervals_only_use_resolved_errors(self):
        recs = []
        for o in range(40):
            for h in (1, 4):
                recs.append({"target": "x", "model": "m", "origin": o, "h": h, "tq": o + h,
                             "actual": 1.0 + 0.1 * math.sin(o), "point": 1.0})
        B.add_empirical_intervals(recs)
        before = {(r["origin"], r["h"]): r["emp_hi80"] for r in recs}
        for r in recs:  # change actuals whose target quarter is after origin 25
            if r["tq"] > 25:
                r["actual"] = 50.0
            r.pop("emp_hi80")
        B.add_empirical_intervals(recs)
        for r in recs:
            if r["origin"] <= 25:
                self.assertEqual(before[(r["origin"], r["h"])], r["emp_hi80"])
        first = min(r["origin"] for r in recs if r["h"] == 4 and r["emp_hi80"] is not None)
        self.assertEqual(first, B.MIN_ERRORS - 1 + 4)  # 12 errors with tq <= origin need origin >= 15


class Reproducibility(unittest.TestCase):
    def test_gbm_and_ridge_deterministic(self):
        des = M.design(S.truncate(D, T0), "hire_rate", T0)
        self.assertEqual(M.gbm(des)["point"], M.gbm(des)["point"])
        self.assertEqual(M.pooled_ridge(des)["point"], M.pooled_ridge(des)["point"])

    @unittest.skipUnless((B.DATA / "backtest.parquet").exists(), "run backtest.py first")
    def test_stored_backtest_rows_reproduce(self):
        import pyarrow.parquet as pq
        bt = pq.read_table(B.DATA / "backtest.parquet").to_pylist()
        B._D = D
        T = S.parse_label("2016Q2")
        fresh = {(r["model"], r["h"]): r["point"] for r in B._job(("sep_55p", T))}
        stored = {(r["model"], r["h"]): r["point"] for r in bt if r["target"] == "sep_55p" and r["origin"] == T}
        self.assertEqual(set(fresh), set(stored))
        for k in fresh:
            self.assertAlmostEqual(fresh[k], stored[k], places=9, msg=k)

    @unittest.skipUnless((B.DATA / "panel_manifest.json").exists(), "run panel.py first")
    def test_panel_hash_matches_manifest(self):
        import hashlib
        man = json.loads((B.DATA / "panel_manifest.json").read_text())
        self.assertEqual(hashlib.sha256((B.DATA / "panel.parquet").read_bytes()).hexdigest(), man["sha256"])


class Metrics(unittest.TestCase):
    def test_smape(self):
        self.assertAlmostEqual(float(M.smape([100], [110])[0]), 200 * 10 / 210)
        self.assertEqual(float(M.smape([5], [5])[0]), 0.0)
        self.assertAlmostEqual(float(M.smape([1], [0])[0]), 200.0)

    def test_mase_scale_and_value(self):
        y = np.array([1, 2, 3, 4, 2, 4, 6, 8, np.nan, 1, 1, 1, 1.0])
        # lag-4 abs diffs: 1,2,3,4 then nan..., |1-2|... computed by hand over non-missing pairs
        diffs = [abs(y[i] - y[i - 4]) for i in range(4, len(y)) if not (np.isnan(y[i]) or np.isnan(y[i - 4]))]
        self.assertAlmostEqual(M.mase_scale(y), float(np.mean(diffs)))
        self.assertAlmostEqual(float(M.mase(10, 12, 4)), 0.5)

    def test_seasonal_naive_is_exact_on_periodic_series(self):
        y = np.tile([1.0, 2.0, 3.0, 4.0], 6) * 1.0
        f = M.seasonal_naive(y, len(y) - 1)
        self.assertEqual(f["point"], [1.0, 2.0, 3.0, 4.0, 1.0, 2.0, 3.0, 4.0])
        self.assertAlmostEqual(M.mase_scale(y), 0.0)

    def test_coverage(self):
        self.assertAlmostEqual(M.coverage([1, 2, 3, 4], [0, 0, 0, 5], [2, 2, 2, 6]), 0.5)
        self.assertAlmostEqual(M.coverage([1, np.nan], [0, 0], [2, 2]), 1.0)

    def test_dm_sign_and_null(self):
        rng = np.random.default_rng(1)
        a = rng.random(200)
        stat, p = M.dm_test(a, a + 0.5, 1)
        self.assertLess(stat, 0)
        self.assertLess(p, 1e-6)
        stat, p = M.dm_test(a, rng.permutation(a), 1)
        self.assertGreater(p, 0.01)


class Panel(unittest.TestCase):
    def test_age_groups_sum_to_total_employment(self):
        tot = D.get("6113", "A00", "emp")[0]
        parts = sum(D.get("6113", f"A0{i}", "emp")[0] for i in range(1, 9))
        ok = ~np.isnan(tot) & ~np.isnan(parts)
        self.assertGreater(ok.sum(), 100)
        self.assertLess(np.max(np.abs(parts[ok] - tot[ok]) / tot[ok]), 0.01)

    def test_sep_55p_definition(self):
        self.assertTrue(np.array_equal(S.target(D, "sep_55p"),
                                       D.get("6113", "A07", "sep") + D.get("6113", "A08", "sep"), equal_nan=True))

    def test_illinois_matches_lake_silver(self):
        import duckdb
        silver = HERE.parent / "data" / "lake" / "silver" / "qwi_il_sa_gs_n4_oslp.parquet"
        r = duckdb.connect().execute(f"""SELECT sep FROM read_parquet('{silver.as_posix()}')
            WHERE industry='6113' AND sex='0' AND agegrp='A00' AND "year"=2019 AND "quarter"=2""").fetchall()
        self.assertEqual(r[0][0], D.get("6113", "A00", "sep")[0, S.parse_label("2019Q2")])

    def test_quarter_index_roundtrip(self):
        for lab in ("1990Q1", "2020Q2", "2025Q4"):
            self.assertEqual(S.q_label(S.parse_label(lab)), lab)


if __name__ == "__main__":
    unittest.main()
