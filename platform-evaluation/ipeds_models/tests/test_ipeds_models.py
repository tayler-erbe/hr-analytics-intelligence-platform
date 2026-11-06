"""Tests for the IPEDS institution models.

    python -m unittest discover -s ipeds_models/tests -v     # from platform-evaluation/

Needs artifacts from build_panel.py and models.py (full run, not --quick, for the stored-fold check).
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import features as F  # noqa: E402
import models as M  # noqa: E402

ART = HERE / "artifacts"
UOFI = list(M.UOFI)
PANEL = pd.read_parquet(ART / "panel.parquet")
NUMERIC = [c for c in PANEL.columns if c not in ("unitid", "year") and pd.api.types.is_numeric_dtype(PANEL[c])
           and not pd.api.types.is_bool_dtype(PANEL[c])]


def perturb(panel: pd.DataFrame, mask: pd.Series, seed: int = 7) -> pd.DataFrame:
    """Scramble every numeric value and flip exclusion flags in the masked rows."""
    rng = np.random.default_rng(seed)
    p = panel.copy()
    idx = p.index[mask]
    for c in NUMERIC:
        if c in ("sector",):
            continue
        v = p.loc[idx, c].astype(float)
        p[c] = p[c].astype(float)
        p.loc[idx, c] = v * rng.uniform(0.3, 3.0, len(idx)) + rng.normal(0, 5, len(idx))
    for c in [c for c in p.columns if c.startswith("excl_")]:
        p.loc[idx, c] = rng.random(len(idx)) < 0.5
    p.loc[idx, "carnegie_group"] = rng.choice(F.CARNEGIE_GROUPS, len(idx))
    return p


def assert_frames_equal(tc, a: pd.DataFrame, b: pd.DataFrame, cols):
    for c in cols:
        x, y = a[c].to_numpy(), b[c].to_numpy()
        if x.dtype.kind in "fc" or y.dtype.kind in "fc":
            np.testing.assert_allclose(x.astype(float), y.astype(float), rtol=0, atol=1e-9, equal_nan=True, err_msg=c)
        else:
            sx = ["NA" if pd.isna(v) else str(v) for v in x]
            sy = ["NA" if pd.isna(v) else str(v) for v in y]
            tc.assertEqual(sx, sy, c)


class TestPanel(unittest.TestCase):
    def test_unique_grain_and_universe(self):
        self.assertFalse(PANEL.duplicated(["unitid", "year"]).any())
        self.assertTrue(PANEL["unitid"].str.len().eq(6).all())
        self.assertEqual(sorted(PANEL["year"].unique()), list(range(2015, 2024)))
        self.assertTrue(PANEL["sector"].isin([1, 2, 3]).all())
        for u in UOFI:
            self.assertEqual(PANEL[PANEL["unitid"] == u]["year"].nunique(), 9, u)

    def test_occupation_partition(self):
        ok = ~PANEL["excl_staff"]
        groups = PANEL.loc[ok, [f"staff_{g}" for g in F.GROUP_CODES]].fillna(0).sum(axis=1)
        self.assertTrue((groups == PANEL.loc[ok, "published_grand_total"]).all())
        self.assertTrue((PANEL.loc[ok, "staff_total"] == PANEL.loc[ok, "published_grand_total"]).all())
        nh = PANEL["nh_filed"] & ~PANEL["excl_new_hires"]
        s = PANEL.loc[nh, [f"nh_{g}" for g in F.GROUP_CODES]].sum(axis=1)
        self.assertTrue((s == PANEL.loc[nh, "nh_total_published"]).all())
        t = ~PANEL["excl_tenure"] & PANEL["ft_instr"].notna()
        self.assertTrue((PANEL.loc[t, "ft_instr"] == PANEL.loc[t, "ft_instr_published"]).all())

    def test_matches_peer_benchmarks(self):
        pb = ROOT_PB / "fact_institution_metrics.parquet"
        if not pb.exists():
            self.skipTest("peer_benchmarks artifacts not built")
        b = pd.read_parquet(pb)
        m = PANEL.merge(b, on=["unitid", "year"])
        self.assertGreater(len(m), 150)
        self.assertTrue((m["staff_total_x"] == m["staff_total_y"]).all())
        d = (m["tenured_share"] - m["tenured_share_pct"]).abs().dropna()
        self.assertLess(d.max(), 0.006)

    def test_2015_new_hires_excluded(self):
        self.assertTrue(PANEL.loc[PANEL["year"] == 2015, "excl_new_hires"].all())
        self.assertTrue(PANEL.loc[PANEL["year"] == 2015, "nh_rate_all"].isna().all())

    def test_peer_benchmarks_excludes_carried(self):
        flags = pd.read_parquet(ART / "comparability_flags.parquet")
        pb = flags[flags["source"] == "peer_benchmarks"]
        for u, y in pb[["unitid", "year"]].itertuples(index=False):
            row = PANEL[(PANEL["unitid"] == u) & (PANEL["year"] == y)]
            if len(row):
                self.assertTrue(row["excl_staff"].iloc[0], (u, y))


ROOT_PB = HERE.parent / "peer_benchmarks" / "artifacts"


class TestNoTemporalLeakage(unittest.TestCase):
    """Scrambling every value after year T must not change any feature at origin <= T, or any target <= T."""

    @classmethod
    def setUpClass(cls):
        cls.T = 2019
        cls.base_m = F.mask_excluded(PANEL)
        cls.pert_m = F.mask_excluded(perturb(PANEL, PANEL["year"] > cls.T))
        cls.base = F.build_features(cls.base_m)
        cls.pert = F.build_features(cls.pert_m)

    def test_features_unchanged(self):
        a = self.base[self.base.index.get_level_values("year") <= self.T]
        b = self.pert[self.pert.index.get_level_values("year") <= self.T]
        self.assertEqual(len(a), len(b))
        assert_frames_equal(self, a.reset_index(), b.reset_index(), list(a.columns))
        # sanity: later years did change
        c = self.base[self.base.index.get_level_values("year") > self.T]["log_staff"].to_numpy()
        d = self.pert[self.pert.index.get_level_values("year") > self.T]["log_staff"].to_numpy()
        self.assertFalse(np.allclose(c, d, equal_nan=True))

    def test_targets_unchanged(self):
        for task in F.TASKS:
            for h in (1, 2):
                a = F.make_task(task, h, self.base, self.base_m)
                b = F.make_task(task, h, self.pert, self.pert_m)
                a = a[a["target_year"] <= self.T].reset_index(drop=True)
                b = b[b["target_year"] <= self.T].reset_index(drop=True)
                self.assertEqual(len(a), len(b), (task, h))
                assert_frames_equal(self, a, b, ["unitid", "year", "cat", "y", "persist"] + F.numeric_columns(task))

    def test_validation_folds_respect_cutoff(self):
        res = json.loads((ART / "results.json").read_text())
        P = pd.read_parquet(ART / "validation_predictions.parquet")
        for task, t in res["tasks"].items():
            for h, s in t["horizons"].items():
                h = int(h)
                for f in s["folds"]:
                    self.assertLessEqual(f["train_target_years"][1], f["cutoff"])
                    self.assertEqual(f["test_target_year"], f["cutoff"] + h)
                sub = P[(P["task"] == task) & (P["h"] == h)]
                self.assertTrue((sub["target_year"] == sub["year"] + h).all())
                self.assertTrue(set(sub["year"]) <= {f["cutoff"] for f in s["folds"]})

    def test_lio_training_cutoffs(self):
        res = json.loads((ART / "results.json").read_text())
        for key, trains in res["lio_training"].items():
            for tr in trains:
                self.assertLessEqual(tr["max_train_target_year"], tr["cutoff"], key)


class TestLeaveInstitutionOut(unittest.TestCase):
    def test_context_excludes_uofi(self):
        """With U of I excluded from context, no other institution's features depend on U of I data."""
        pert = perturb(PANEL, PANEL["unitid"].isin(UOFI))
        a = F.build_features(F.mask_excluded(PANEL), frozenset(UOFI))
        b = F.build_features(F.mask_excluded(pert), frozenset(UOFI))
        keep = ~a.index.get_level_values("unitid").isin(UOFI)
        ctx = [c for c in a.columns if c.startswith("ctx_")]
        assert_frames_equal(self, a[keep].reset_index(), b[keep].reset_index(), ctx + ["log_staff", "tenured_share"])
        # and without the exclusion they DO depend on it (the test can fail)
        c = F.build_features(F.mask_excluded(PANEL)).loc[a[keep].index]
        d = F.build_features(F.mask_excluded(pert)).loc[a[keep].index]
        self.assertFalse(np.allclose(c["ctx_tenured_share"], d["ctx_tenured_share"], equal_nan=True))

    def test_scores_trained_without_uofi(self):
        """UIUC's scores are identical when UIC and UIS data (all years) are scrambled."""
        pert = perturb(PANEL, PANEL["unitid"].isin(["145600", "148654"]))
        outs = []
        for p in (PANEL, pert):
            m = F.mask_excluded(p)
            rows = F.make_task("tenure", 1, F.build_features(m, frozenset(UOFI)), m)
            U, trains = M.score_uofi("tenure", 1, rows, "ridge", True, lambda s: None)
            outs.append(U[U["unitid"] == "145637"].sort_values("year").reset_index(drop=True))
            for tr in trains:
                self.assertGreater(tr["n_train"], 1000)
        np.testing.assert_allclose(outs[0]["pred"], outs[1]["pred"], atol=1e-9)
        np.testing.assert_allclose(outs[0]["q90"], outs[1]["q90"], atol=1e-9)

    def test_stored_scores_cover_campuses(self):
        U = pd.read_parquet(ART / "uofi_scores.parquet")
        self.assertEqual(set(U["unitid"]), set(UOFI))
        f = U[U["year"] == 2023]
        for task in F.TASKS:
            self.assertEqual(set(f[f["task"] == task]["target_year"]), {2024, 2025}, task)


class TestReproducibility(unittest.TestCase):
    def test_lgbm_and_ridge_deterministic(self):
        m = F.mask_excluded(PANEL)
        rows = F.make_task("tenure", 1, F.build_features(m), m)
        rows = rows[rows["y"].notna()]
        train, test = rows[rows["target_year"] <= 2021], rows[rows["year"] == 2021]
        for kind in ("lgbm", "ridge"):
            p1 = M.make_model(kind, "tenure", quick=True).fit(train).predict(test)
            p2 = M.make_model(kind, "tenure", quick=True).fit(train).predict(test)
            np.testing.assert_array_equal(p1, p2)

    def test_stored_fold_reproduces(self):
        man = json.loads((HERE / "manifests" / "model_manifest.json").read_text())
        if man.get("quick"):
            self.skipTest("artifacts are from a --quick run")
        m = F.mask_excluded(PANEL)
        rows = F.make_task("tenure", 1, F.build_features(m), m)
        rows = rows[rows["y"].notna()]
        T = 2022
        train, test = rows[rows["target_year"] <= T], rows[rows["year"] == T]
        P = pd.read_parquet(ART / "validation_predictions.parquet")
        P = P[(P["task"] == "tenure") & (P["h"] == 1) & (P["year"] == T)]
        for kind in ("lgbm", "ridge"):
            model, q = M.fit_with_intervals(kind, "tenure", train)
            p = pd.Series(model.predict(test), index=test["unitid"].to_numpy())
            stored = P.set_index("unitid")[kind]
            np.testing.assert_allclose(p.loc[stored.index].to_numpy(), stored.to_numpy(), atol=1e-8)

    def test_bootstrap_deterministic(self):
        rng = np.random.default_rng(1)
        e = {k: rng.random(300) for k in ("persistence", "sector_year_mean", "ridge", "lgbm")}
        u = rng.integers(0, 60, 300).astype(str)
        self.assertEqual(M.cluster_boot(e, u, B=200), M.cluster_boot(e, u, B=200))

    def test_panel_hash_matches_manifest(self):
        man = json.loads((HERE / "manifests" / "model_manifest.json").read_text())
        self.assertEqual(man["panel_sha256"], M.sha(ART / "panel.parquet"))


if __name__ == "__main__":
    unittest.main()
