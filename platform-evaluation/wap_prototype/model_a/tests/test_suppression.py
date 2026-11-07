"""k >= 10 primary and complementary suppression on everything published (protocol 6.1)."""
from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from wap_prototype.model_a import aggregate as A
from wap_prototype.model_a import config as C
from wap_prototype.model_a import governance_bridge as G
from wap_prototype.model_a.tests import common

K = C.K_MIN


class TestSuppressMulti(unittest.TestCase):
    def test_single_grouping_matches_succession_governance_suppress(self):
        df = pd.DataFrame({"g": ["a"] * 4 + ["b"] * 3 + ["c"] * 2, "cell": list(range(9)),
                           "n": [40, 25, 7, 12, 30, 30, 15, 3, 4], "v": np.arange(9, dtype=float)})
        ref = G.suppress(df, "n", ["v"], group_col="g", k=K)
        mine = G.suppress_multi(df, "n", ["v"], [["g"]], k=K)
        self.assertEqual(ref["suppressed"].tolist(), mine["suppressed"].tolist())
        # group a: one primary (7) -> complementary on the next-smallest published (12)
        self.assertEqual(mine.loc[mine["cell"].isin([2, 3]), "suppression_reason"].tolist(), ["primary", "complementary"])
        self.assertTrue(mine.loc[mine["suppressed"], "v"].isna().all())
        self.assertFalse(mine.loc[~mine["suppressed"], "v"].isna().any())

    def test_two_groupings_reach_a_fixed_point(self):
        # rows: (unit, step) with n; unit grouping and step grouping
        df = pd.DataFrame({"unit": ["u1", "u1", "u2", "u2", "u3", "u3"], "step": ["s1", "s2", "s1", "s2", "s1", "s2"],
                           "n": [5, 20, 30, 25, 40, 50], "v": [1.0] * 6})
        out = G.suppress_multi(df, "n", ["v"], [["unit"], ["step"]], k=K)
        for keys in (["unit"], ["step"]):
            for _, g in out.groupby(keys):
                self.assertFalse(g["suppressed"].sum() == 1 and (~g["suppressed"]).sum() >= 1, keys)


class TestPublishedTables(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = common.small_run("a")
        cls.fpe = pd.read_csv(cls.ctx["out"] / "star" / "fact_promotion_expectation.csv")
        cls.fmq = pd.read_csv(cls.ctx["out"] / "star" / "fact_model_quality.csv")

    def test_no_published_cell_below_k(self):
        pub = self.fpe[~self.fpe["suppressed"]]
        self.assertGreater(len(pub), 0)
        self.assertTrue((pub["n"] >= K).all())
        self.assertTrue((self.fmq[~self.fmq["suppressed"]]["n"] >= K).all())

    def test_suppressed_rows_keep_keys_and_null_measures(self):
        sup = self.fpe[self.fpe["suppressed"]]
        self.assertGreater(len(sup), 0)
        self.assertTrue(sup[A.EXPECTATION_MEASURES].isna().all().all())
        self.assertFalse(sup[["date_key", "org_key", "role_key", "horizon_months", "model_version", "scenario_key", "n"]].isna().any().any())

    def test_complementary_suppression_within_ladder_and_within_step(self):
        f = self.fpe
        dim_role = pd.read_csv(self.ctx["out"] / "star" / "dim_role.csv").set_index("role_key")
        f = f.join(dim_role[["ladder", "level"]], on="role_key")
        for keys in (["date_key", "horizon_months", "scenario_key", "org_key", "ladder"], ["date_key", "horizon_months", "scenario_key", "ladder", "level"]):
            lone = 0
            for _, g in f.groupby(keys):
                if g["suppressed"].sum() == 1 and (~g["suppressed"]).sum() >= 1:
                    lone += 1
            self.assertEqual(lone, 0, keys)
        self.assertGreater(self.ctx["result"]["aggregate"]["summary"]["fact_promotion_expectation"]["complementary"], 0)

    def test_grain_cells_backtest_are_suppressed_too(self):
        cells = pd.read_csv(self.ctx["out"] / "grain_cells_backtest.csv")
        pub = cells[~cells["suppressed"]]
        self.assertTrue((pub["n"] >= K).all())
        self.assertTrue(cells.loc[cells["suppressed"], ["expected", "observed"]].isna().all().all())


if __name__ == "__main__":
    unittest.main()
