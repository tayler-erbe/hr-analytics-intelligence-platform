"""Leakage firewall (protocol 5.1): features and labels at an origin use nothing recorded after it."""
from __future__ import annotations

import datetime as dt
import unittest
from dataclasses import replace
from unittest import mock

import numpy as np
import pandas as pd

from wap_prototype.model_a import config as C
from wap_prototype.model_a import data as D
from wap_prototype.model_a import train as TR
from wap_prototype.model_a.tests.common import inputs

ORIGIN = dt.date(2021, 12, 31)


class TestWindows(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inp = inputs()

    def test_training_snapshots_resolve_before_the_origin(self):
        f = self.inp.features
        tr = D.train_mask(f, ORIGIN)
        self.assertGreater(tr.sum(), 0)
        ends = f.loc[tr, "snap_date"].map(lambda s: C.add_months(s, C.TRAIN_HORIZON_MONTHS))
        self.assertTrue((ends <= ORIGIN).all())
        self.assertEqual(f.loc[tr, "snap_date"].max(), dt.date(2020, 6, 30))

    def test_recalibration_rows_resolve_before_the_origin_and_after_the_recal_origin(self):
        f = self.inp.features
        for h in C.HORIZONS:
            rm = D.recal_mask(f, ORIGIN, h)
            s = f.loc[rm, "snap_date"]
            self.assertTrue((s > D.recal_origin(ORIGIN)).all())
            self.assertTrue((s.map(lambda d: C.add_months(d, h)) <= ORIGIN).all())

    def test_test_window_is_the_two_years_after_the_origin(self):
        f = self.inp.features
        tm = D.test_mask(f, ORIGIN, 12, self.inp.data_as_of)
        s = f.loc[tm, "snap_date"]
        self.assertEqual((s.min(), s.max()), (dt.date(2022, 3, 31), dt.date(2023, 12, 31)))

    def test_training_labels_as_known_at_origin_ignore_rows_keyed_later(self):
        inp = self.inp
        y_known = D.event_label(inp.features, inp.events, ORIGIN, 12, "promotion")
        y_latest = D.event_label(inp.features, inp.events, inp.data_as_of, 12, "promotion")
        tr = D.train_mask(inp.features, ORIGIN)
        # as-known labels can only miss positives that were keyed after the origin, never add any
        self.assertTrue(((y_known[tr] == 1) <= (y_latest[tr] == 1)).all())
        self.assertLessEqual(y_known[tr].sum(), y_latest[tr].sum())

    def test_latest_event_label_matches_phase1_targets(self):
        inp = self.inp
        for h in C.HORIZONS:
            mine = D.event_label(inp.features, inp.events, inp.data_as_of, h, "promotion")
            phase1 = D.latest_label(inp.features, h)
            self.assertTrue(np.array_equal(mine.isna(), phase1.isna()))
            ok = mine.notna()
            self.assertTrue(np.array_equal(mine[ok].to_numpy(int), phase1[ok].to_numpy(int)))


class TestFeatureMatrix(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inp = inputs()

    def test_no_protected_attribute_age_or_unit_in_the_matrix(self):
        X = D.feature_frame(self.inp.features.head(500))
        for bad in ("age_band", "sex", "race", "surs", "college", "dept", "person_id", "position_id", "birth"):
            self.assertFalse(any(bad in c for c in X.columns), bad)
        self.assertEqual(set(X.columns), set(C.NUMERIC_FEATURES) | set(C.CATEGORICAL_FEATURES))

    def test_age_only_in_the_ablation(self):
        X = D.feature_frame(self.inp.features.head(500), with_age=True)
        self.assertIn("age_band", X.columns)
        # a feature map that smuggles an excluded physical column in is refused
        with mock.patch.dict(C.FEATURE_MAP, {"tenure_years": "age_band"}):
            with self.assertRaises(ValueError):
                D.feature_frame(self.inp.features.head(5))
        with mock.patch.dict(C.FEATURE_MAP, {"campus": "college_org_code"}):
            with self.assertRaises(ValueError):
                D.feature_frame(self.inp.features.head(5))

    def test_sensitivity_drops(self):
        X2 = D.feature_frame(self.inp.features.head(50), drop=C.EXTERNAL_FEATURES)
        self.assertFalse(set(C.EXTERNAL_FEATURES) & set(X2.columns))
        X3 = D.feature_frame(self.inp.features.head(50), drop=C.TENURE_PROXIES)
        self.assertFalse(set(C.TENURE_PROXIES) & set(X3.columns))


class TestTruncation(unittest.TestCase):
    """Fit at the origin on the full inputs and on inputs truncated / scrambled after the origin: identical."""

    @classmethod
    def setUpClass(cls):
        cls.inp = inputs()

    def _fit_predict(self, inp: D.Inputs, run: str):
        tr = TR.Trainer(inp, C.SEED)
        spec = TR.variant(run)
        model, platt = tr.calibrated(spec, ORIGIN, 12)
        rows = inp.features[D.train_mask(inp.features, ORIGIN)]
        X = D.feature_frame(rows, spec["with_age"], spec["drop"])
        return platt.apply(model.predict(X)), tr.label(ORIGIN, 12, "promotion")[D.train_mask(inp.features, ORIGIN)].to_numpy()

    def test_truncating_everything_after_the_origin_changes_nothing(self):
        inp = self.inp
        f_cut = inp.features[inp.features["snap_date"] <= ORIGIN].reset_index(drop=True)
        e_cut = inp.events[inp.events["row_known_from"] <= ORIGIN].reset_index(drop=True)
        cut = replace(inp, features=f_cut, events=e_cut)
        for run in ("A-base-step", "A-gbm"):
            p_full, y_full = self._fit_predict(inp, run)
            p_cut, y_cut = self._fit_predict(cut, run)
            self.assertTrue(np.array_equal(y_full, y_cut), run)
            self.assertTrue(np.allclose(p_full, p_cut, rtol=0, atol=0), run)

    def test_scrambling_rows_after_the_origin_changes_nothing(self):
        inp = self.inp
        f = inp.features.copy()
        after = f["snap_date"] > ORIGIN
        rng = np.random.default_rng(1)
        for c in C.FEATURE_MAP.values():
            if pd.api.types.is_numeric_dtype(f[c]):
                f.loc[after, c] = rng.random(after.sum()) * 100
            else:
                f.loc[after, c] = "SCRAMBLED"
        e = inp.events.copy()
        late = e["row_known_from"] > ORIGIN
        e.loc[late, "event_type"] = "promotion"       # a flood of future promotions must not reach the origin's fit
        scrambled = replace(inp, features=f, events=e)
        p_full, y_full = self._fit_predict(inp, "A-gbm")
        p_scr, y_scr = self._fit_predict(scrambled, "A-gbm")
        self.assertTrue(np.array_equal(y_full, y_scr))
        self.assertTrue(np.array_equal(p_full, p_scr))


if __name__ == "__main__":
    unittest.main()
