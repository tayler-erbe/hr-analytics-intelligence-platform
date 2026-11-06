"""Unit tests for the succession-planning pipeline (synthetic data only).

    python -m unittest discover -s succession_models/tests -v      # from platform-evaluation/

Covers: no leakage (bitemporal truncation and scrambling of post-snapshot rows, effective-only mode,
labels as known at the origin), reproducibility, calibration sanity, Markov/metric sanity,
suppression and the export gate, and person-level outputs disabled by default.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import config  # noqa: E402
import extract as X  # noqa: E402
import governance as G  # noqa: E402
import metrics as M  # noqa: E402
import readiness as R  # noqa: E402
import snapshot as S  # noqa: E402
import synth_edw  # noqa: E402
import validate as V  # noqa: E402
from mobility import Mobility  # noqa: E402
from vacancy import DiscreteHazard, outcomes_at  # noqa: E402

SCALE = 0.3
SNAP = dt.date(2018, 7, 1)
_TMP: Path | None = None
EXT: Path | None = None


def setUpModule():
    global _TMP, EXT
    _TMP = Path(tempfile.mkdtemp(prefix="succ_test_"))
    synth_edw.generate(config.SEED, SCALE, _TMP / "edw")
    EXT = _TMP / "extract"
    X.run_duckdb(_TMP / "edw", EXT)


def tearDownModule():
    shutil.rmtree(_TMP, ignore_errors=True)


def _features(ext: Path, d: dt.date, smap=None) -> pd.DataFrame:
    con = S.open_source(ext, smap or config.SOURCE_MAP)
    f = S.incumbents_asof(con, [d])
    return f.sort_values(["pers_id", "posn_nbr"]).reset_index(drop=True)


def _gt(col: pd.Series, d: dt.date) -> pd.Series:
    """Element-wise `col > d` for object columns of datetime.date (9999-12-31 is out of pandas' range)."""
    return col.map(lambda v: v is not None and v > d).astype(bool)


def _rewrite(src: Path, dst: Path, fn) -> None:
    """Copy an extract, applying fn(table_name, DataFrame) -> DataFrame to every history table."""
    dst.mkdir(parents=True, exist_ok=True)
    for f in src.iterdir():
        if f.suffix != ".parquet":
            shutil.copy(f, dst / f.name)
            continue
        t = pq.read_table(f)
        if "ROW_REC_START_DT" in t.column_names:
            df = fn(f.stem, t.to_pandas())
            t = pa.Table.from_pandas(df, schema=t.schema, preserve_index=False)
        pq.write_table(t, dst / f.name)


class TestNoLeakage(unittest.TestCase):
    def test_truncated_history_gives_identical_features(self):
        """Features at S from the full extract == features from the extract as it existed at S."""
        open_end = config.OPEN_END

        def as_of_s(name, df):
            df = df[_gt(df["ROW_REC_START_DT"], SNAP) == False].copy()  # noqa: E712
            later = _gt(df["ROW_REC_END_DT"], SNAP)
            df.loc[later, "ROW_REC_END_DT"] = open_end
            return df
        trunc = _TMP / "trunc"
        _rewrite(EXT, trunc, as_of_s)
        a, b = _features(EXT, SNAP), _features(trunc, SNAP)
        self.assertGreater(len(a), 100)
        pd.testing.assert_frame_equal(a, b)

    def test_scrambling_post_snapshot_rows_changes_nothing(self):
        """Rows recorded after S may contain anything -- even back-dated effective dates -- without effect."""
        rng = np.random.default_rng(1)

        def scramble(name, df):
            df = df.copy()
            late = _gt(df["ROW_REC_START_DT"], SNAP)
            for c in df.columns:
                if c.endswith("_DT") and not c.startswith("ROW_REC"):
                    df.loc[late, c] = [v if v is None or v.year > 2100 else v - dt.timedelta(days=int(rng.integers(0, 4000)))
                                       for v in df.loc[late, c]]
                elif c in ("JOB_CLS_CD", "JOB_ORG_CD"):
                    df.loc[late, c] = rng.permutation(df.loc[late, c].to_numpy())
                elif c == "JOB_ANNUAL_SAL_AMT":
                    df.loc[late, c] = df.loc[late, c].map(lambda v: v * 0 if v is not None else v)
            return df
        scr = _TMP / "scrambled"
        _rewrite(EXT, scr, scramble)
        pd.testing.assert_frame_equal(_features(EXT, SNAP), _features(scr, SNAP))

    def test_late_keyed_exits_are_invisible_at_snapshot(self):
        """An incumbent whose exit was effective before S but recorded after S is still an incumbent at S."""
        con = S.open_source(EXT)
        sp = S.spells(con)
        f = _features(EXT, SNAP).merge(sp[["pers_id", "posn_nbr", "exit_dt"]], on=["pers_id", "posn_nbr"])
        gone = pd.to_datetime(f["exit_dt"]) <= pd.Timestamp(SNAP)
        self.assertGreater(int(gone.sum()), 0, "fixture should contain late-keyed exits")

    def test_effective_only_mode_ignores_future_effective_rows(self):
        smap = json.loads(json.dumps(config.SOURCE_MAP))
        smap["bitemporal"] = False

        def scramble_future(name, df):
            df = df.copy()
            eff = {"T_JOB_DETL_HIST": "JOB_DETL_EFF_DT", "T_EMPEE_HIST": "EMPEE_EFF_DT", "T_EMPEE_HIST_5": "TERM_DT",
                   "T_PERS_HIST": "PERS_EFF_DT", "T_POSN_HIST": "POSN_EFF_DT"}[name]
            fut = _gt(df[eff], SNAP)
            if "JOB_CLS_CD" in df:
                df.loc[fut, "JOB_CLS_CD"] = "XXXX"
                df.loc[fut, "JOB_STATUS_CD"] = "T"
            return df
        a = _features(EXT, SNAP, smap)
        fx = _TMP / "eff_only"
        _rewrite(EXT, fx, scramble_future)
        pd.testing.assert_frame_equal(a, _features(fx, SNAP, smap))

    def test_training_labels_are_censored_at_origin(self):
        con = S.open_source(EXT)
        o = dt.date(2019, 1, 1)
        sp = S.spells(con, o)
        self.assertTrue((pd.to_datetime(sp["exit_dt"].dropna()) <= pd.Timestamp(o)).all())
        self.assertTrue((pd.to_datetime(sp["start_dt"]) <= pd.Timestamp(o)).all())


class TestReproducibility(unittest.TestCase):
    def test_generator_is_byte_identical(self):
        a, b = _TMP / "rep_a", _TMP / "rep_b"
        synth_edw.generate(123, 0.12, a)
        synth_edw.generate(123, 0.12, b)
        for f in sorted(a.glob("*.parquet")):
            ha = hashlib.sha256(f.read_bytes()).hexdigest()
            hb = hashlib.sha256((b / f.name).read_bytes()).hexdigest()
            self.assertEqual(ha, hb, f.name)

    def test_model_and_bench_are_deterministic(self):
        con = S.open_source(EXT)
        raw = S.incumbents_asof(con, S.semiannual(dt.date(2008, 1, 1), dt.date(2020, 1, 1)))
        fams = sorted(raw["role_family"].unique())
        o = dt.date(2020, 1, 1)
        m1, r1, _, _ = V.fit_calibrated(con, raw, fams, o)
        m2, r2, _, _ = V.fit_calibrated(con, raw, fams, o)
        pd.testing.assert_frame_equal(m1.coef_sep, m2.coef_sep)
        ro = V.at(raw, o)
        pd.testing.assert_frame_equal(r1.apply(m1.predict(ro)), r2.apply(m2.predict(ro)))


class TestCalibrationSanity(unittest.TestCase):
    def test_probabilities_valid_monotone_and_calibrated_in_the_large(self):
        con = S.open_source(EXT)
        raw = S.incumbents_asof(con, S.semiannual(dt.date(2008, 1, 1), dt.date(2022, 1, 1)))
        fams = sorted(raw["role_family"].unique())
        o = dt.date(2022, 1, 1)
        m, rc, _, _ = V.fit_calibrated(con, raw, fams, o)
        ro = V.at(raw, o)
        p = rc.apply(m.predict(ro))
        for h in config.HORIZONS:
            self.assertTrue(((p[f"p{h}"] >= 0) & (p[f"p{h}"] <= 1)).all())
        self.assertTrue((p["p6"] <= p["p12"] + 1e-12).all() and (p["p12"] <= p["p24"] + 1e-12).all())
        _, _, ys, _ = outcomes_at(ro, S.spells(con), o)
        for h in (12, 24):
            self.assertLess(abs(p[f"p{h}"].mean() - ys[h].mean()), 0.06, f"calibration-in-the-large at {h} months")

    def test_auc_cd_equals_auc_without_censoring(self):
        from sklearn.metrics import roc_auc_score
        rng = np.random.default_rng(0)
        risk = rng.random(500)
        t = np.where(rng.random(500) < risk * 0.6, rng.uniform(0, 24, 500), 24.01)
        ev = (t <= 24).astype(int)
        self.assertAlmostEqual(M.auc_cd(t, ev, risk, 12), roc_auc_score((t <= 12).astype(int), risk), places=10)


class TestMobility(unittest.TestCase):
    def test_transition_rows_are_distributions_with_valid_intervals(self):
        con = S.open_source(EXT)
        roles = con.sql("SELECT class_cd, role_family, role_level, critical_ind FROM v_role").df()
        mob = Mobility(roles).fit(S.spells(con), dt.date(2026, 10, 31))
        np.testing.assert_allclose(mob.P.sum(axis=1), 1.0)
        self.assertTrue((mob.P_lo <= mob.P + 1e-12).all() and (mob.P <= mob.P_hi + 1e-12).all())
        self.assertGreater(mob.N.sum(), 100)


class TestSuppressionAndExport(unittest.TestCase):
    def test_primary_and_complementary_suppression(self):
        df = pd.DataFrame({"unit": ["A", "A", "A", "B", "B"], "n": [4, 25, 30, 50, 60], "rate": [.1, .2, .3, .4, .5]})
        out = G.suppress(df, "n", ["rate"], group_col="unit")
        self.assertEqual(out["suppressed"].tolist(), [True, True, False, False, False])
        self.assertTrue(out.loc[out["suppressed"], ["n", "rate"]].isna().all().all())

    def test_export_gate_blocks_small_cells_and_identifiers(self):
        d = _TMP / "exp"
        with self.assertRaises(G.ExportBlocked):
            G.export_table(pd.DataFrame({"role": ["x"], "n": [9]}), "t", d, "n")
        with self.assertRaises(G.ExportBlocked):
            G.export_table(pd.DataFrame({"pers_id": ["SYN1"], "n": [50]}), "t", d, "n")
        with self.assertRaises(G.ExportBlocked):
            G.export_table(pd.DataFrame({"posn_nbr": ["Q1"], "n": [50]}), "t", d, "n")
        G.export_table(G.suppress(pd.DataFrame({"role": ["x", "y"], "n": [9, 40]}), "n", []), "ok", d, "n")
        self.assertTrue((d / "ok.csv").exists())

    def test_published_outputs_contain_no_identifiers(self):
        page = config.HTML_OUT
        exp = config.RUNS_DIR / "synthetic" / "export"
        if not page.exists() or not exp.exists():
            self.skipTest("run run_all.py first")
        pat = re.compile(r"SYN\d{7}|\bQ\d{6}\b")
        self.assertIsNone(pat.search(page.read_text()))
        for f in exp.glob("*.csv"):
            self.assertIsNone(pat.search(f.read_text()), f.name)
            cols = pd.read_csv(f, nrows=0).columns
            G.check_exportable(pd.read_csv(f), next(c for c in ("n", "n_incumbents", "n_moves", "n_exits") if c in cols))


class TestPersonLevelDisabledByDefault(unittest.TestCase):
    def setUp(self):
        self._env = os.environ.pop(config.PERSON_LEVEL_ENV, None)

    def tearDown(self):
        os.environ.pop(config.PERSON_LEVEL_ENV, None)
        if self._env is not None:
            os.environ[config.PERSON_LEVEL_ENV] = self._env

    def test_gate_closed_without_flag(self):
        ok, why = config.person_level_gate(EXT)
        self.assertFalse(ok)
        with self.assertRaises(config.PersonLevelDisabled):
            R.run(EXT, pd.DataFrame(), pd.DataFrame(), None)

    def test_flag_alone_is_not_enough_on_non_synthetic_data(self):
        real_like = _TMP / "real_like"
        real_like.mkdir(exist_ok=True)
        (real_like / "manifest.json").write_text(json.dumps({"synthetic": False}))
        os.environ[config.PERSON_LEVEL_ENV] = "1"
        ok, why = config.person_level_gate(real_like)
        if config.APPROVAL_FILE.exists():
            self.skipTest("an approval record exists in this checkout")
        self.assertFalse(ok, why)

    def test_incomplete_approval_is_rejected(self):
        p = _TMP / "approval.json"
        p.write_text(json.dumps({"university_counsel": {"name": "x", "date": "2026-01-01"}}))
        ok, why = config.approval_ok(p)
        self.assertFalse(ok)
        self.assertIn("office_for_access_and_equity", why)

    def test_readiness_features_exclude_protected_and_age(self):
        self.assertFalse(R.FORBIDDEN & set(R.FEATURES))
        for c in config.PROTECTED_COLS:
            self.assertNotIn(c, R.FEATURES)

    def test_default_run_writes_no_person_level_files(self):
        run = config.RUNS_DIR / "synthetic"
        if not (run / "metrics" / "summary.json").exists():
            self.skipTest("run run_all.py first")
        summ = json.loads((run / "metrics" / "summary.json").read_text())
        if summ.get("readiness", {}).get("enabled"):
            self.skipTest("last run was an explicit synthetic readiness audit")
        self.assertFalse((run / "restricted" / "person_level").exists())
        self.assertFalse(summ["readiness"]["enabled"])


if __name__ == "__main__":
    unittest.main()
