"""Seed policy (protocol 5.2): the same seed gives identical metrics and byte-identical published tables."""
from __future__ import annotations

import unittest

import pandas as pd

from wap_prototype.model_a import aggregate as A
from wap_prototype.model_a import config as C
from wap_prototype.model_a import evaluate as EV
from wap_prototype.model_a import train as TR
from wap_prototype.model_a.tests import common


class TestDeterminism(unittest.TestCase):
    @classmethod
    def tearDownClass(cls):
        common.cleanup()

    def test_same_seed_identical_predictions_and_metrics(self):
        inp = common.inputs()
        a = TR.run(inp, (C.ORIGINS[-1],), ("A-base-family", "A-base-step", "A-gbm"), sensitivity=False, ablation=False, write=False)
        b = TR.run(inp, (C.ORIGINS[-1],), ("A-base-family", "A-base-step", "A-gbm"), sensitivity=False, ablation=False, write=False)
        pd.testing.assert_frame_equal(a["predictions"], b["predictions"], check_exact=True)
        pd.testing.assert_frame_equal(a["scoring"], b["scoring"], check_exact=True)
        ma = EV.by_origin(a["predictions"], "campus_org_code")
        mb = EV.by_origin(b["predictions"], "campus_org_code")
        pd.testing.assert_frame_equal(ma, mb, check_exact=True)

    def test_full_pipeline_twice_gives_byte_identical_published_tables(self):
        r1, r2 = common.small_run("a"), common.small_run("b")
        for name in A.STAR_TABLES:
            self.assertEqual((r1["out"] / "star" / f"{name}.csv").read_bytes(), (r2["out"] / "star" / f"{name}.csv").read_bytes(), name)
        for name in ("metrics_by_origin.csv", "metrics_mean.csv", "thresholds.csv", "fairness_summary.csv", "grain_cells_backtest.csv"):
            self.assertEqual((r1["out"] / name).read_bytes(), (r2["out"] / name).read_bytes(), name)
        m1 = (r1["out"] / "star" / "export_manifest.json").read_text()
        m2 = (r2["out"] / "star" / "export_manifest.json").read_text()
        self.assertEqual(m1, m2)

    def test_a_different_seed_is_recorded(self):
        inp = common.inputs()
        r = TR.run(inp, (C.ORIGINS[-1],), ("A-base-family", "A-base-step"), sensitivity=False, ablation=False, seed=7, write=False)
        self.assertEqual(r["manifest"]["seed"], 7)
        self.assertIn("-s7", r["manifest"]["run_id"])


if __name__ == "__main__":
    unittest.main()
