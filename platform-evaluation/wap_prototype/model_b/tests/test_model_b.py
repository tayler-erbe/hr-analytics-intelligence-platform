"""Model B tests (run from platform-evaluation/):  python -m unittest discover -s wap_prototype/model_b/tests -t . -v

Leakage (future perturbation, COVID dummy, empirical intervals), determinism, pinned thresholds and the
pre-registered selection rule, suppression (rule and published tables), star-schema shape, conservation on the
series used, the pooling rule, the attrition-flag rule and the learners' basic behaviour. Tests that need the
restricted artefacts of a full run (series_panel, backtest, forecast, published tables) skip when they are absent.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

PE_ROOT = Path(__file__).resolve().parents[3]
if str(PE_ROOT) not in sys.path:
    sys.path.insert(0, str(PE_ROOT))

from wap_prototype.model_b import backtest as B  # noqa: E402
from wap_prototype.model_b import config as C  # noqa: E402
from wap_prototype.model_b import learners as L  # noqa: E402
from wap_prototype.model_b import publish_b as P  # noqa: E402
from wap_prototype.model_b import risk as R  # noqa: E402
from wap_prototype.model_b import series as S  # noqa: E402
from wap_prototype.protocol import scorers as SC  # noqa: E402

_PANEL: dict = {}


def have_restricted() -> bool:
    return (C.RESTRICTED / "series_panel.parquet").exists()


def have_published() -> bool:
    return (C.OUT / "fact_attrition_forecast.csv").exists() and (C.OUT / "metrics_b.json").exists()


def panel() -> S.Panel:
    if "p" not in _PANEL:
        _PANEL["p"] = S.load_panel()[0]
    return _PANEL["p"]


def perturb_future(p: S.Panel, T: int, seed: int = 1) -> S.Panel:
    """Everything after T replaced by noise (not blanked), so a learner that peeks would change."""
    rng = np.random.default_rng(seed)
    q = S.Panel(list(p.quarters), p.registry.copy(), data_as_of=p.data_as_of)
    for k, a in p.y.items():
        b = a.copy(); b[:, T + 1:] = rng.integers(0, 200, size=b[:, T + 1:].shape); q.y[k] = b
    for k, a in p.cov.items():
        b = a.copy(); b[:, T + 1:] = rng.normal(size=b[:, T + 1:].shape); q.cov[k] = b
    return q


def synthetic_panel(n_series: int = 6, n_q: int = 40, seed: int = 3) -> S.Panel:
    """Small deterministic panel (one campus, several families) for rule tests."""
    rng = np.random.default_rng(seed)
    quarters = [(pd.Timestamp("2015-03-31") + pd.offsets.QuarterEnd(i)).date() for i in range(n_q)]
    rows, reg = [], []
    for i in range(n_series):
        fam = f"F{i}"
        hc = 20 + 3 * i + rng.integers(-2, 3, size=n_q)
        reg.append(dict(series_id=f"C|U10|{fam}", level="campus", campus="U10", dept=None, role_family=fam, mean_headcount=float(hc.mean()),
                        n_dept_series=1, modelled=True))
        for q in range(n_q):
            seps = rng.poisson(1.0 + 0.4 * (q % 4 == 1))
            rows.append(dict(series_id=f"C|U10|{fam}", qi=q, headcount=float(hc[q]), fte=float(hc[q]), hires=float(rng.poisson(1.2)), moves_in=0.0,
                             sep_voluntary=float(seps), sep_retirement=0.0, sep_end_of_appointment=0.0, sep_other=0.0, separations=float(seps), moves_out=0.0,
                             share_55plus=0.05, share_surs_near=0.05, unit_churn_12m=0.1, oews_pay_ratio_local=1.0, bls_projected_growth_pct=3.0,
                             bls_separation_rate=8.0, qwi_sep_rate=0.1, qwi_hire_rate=0.1, qcew_he_emp_yoy=0.01, sep_voluntary_incl_eoa=float(seps)))
    return S.panel_from_long(pd.DataFrame(rows), pd.DataFrame(reg), quarters)


# ------------------------------------------------------------------------------------------- conservation
class TestSeries(unittest.TestCase):
    @unittest.skipUnless(have_restricted(), "run series.py first")
    def test_conservation_holds_on_every_series_used(self):
        p, long = S.load_panel()
        self.assertEqual(float(S.conservation_residual(long).abs().max()), 0.0)
        hc, hi, mi, se, mo = (p.y["headcount"], p.y["hires"], p.cov.get("moves_in"), p.y["separations"], None)
        # on the dense arrays: headcount[q-1] + hires - separations + net internal moves == headcount[q]
        net = long.pivot(index="series_id", columns="qi", values="moves_in").reindex(p.registry["series_id"]).to_numpy() - \
              long.pivot(index="series_id", columns="qi", values="moves_out").reindex(p.registry["series_id"]).to_numpy()
        lhs = hc[:, :-1] + hi[:, 1:] - se[:, 1:] + net[:, 1:]
        self.assertTrue(np.allclose(lhs, hc[:, 1:]))

    def test_flow_classification_on_fixture(self):
        q = [dt.date(2020, 3, 31), dt.date(2020, 6, 30), dt.date(2020, 9, 30)]
        base = dict(knowledge_date=dt.date(2021, 1, 1), fte_total=1.0, age_band="25-34", surs_eligibility_band="not_eligible", dept_churn_12m=0.1,
                    pay_ratio_oews_local=1.0, proj_growth_pct_2025_35=1.0, proj_occ_separations_rate_pct=5.0)
        f = pd.DataFrame([  # A stays; B resigns (posted late: still present at Q2, gone at Q3); C hired in Q2; D moves dept in Q3
            dict(snap_date=q[0], person_id="A", campus_org_code="U10", dept_org_code="D1", role_family="F", **base),
            dict(snap_date=q[1], person_id="A", campus_org_code="U10", dept_org_code="D1", role_family="F", **base),
            dict(snap_date=q[2], person_id="A", campus_org_code="U10", dept_org_code="D1", role_family="F", **base),
            dict(snap_date=q[0], person_id="B", campus_org_code="U10", dept_org_code="D1", role_family="F", **base),
            dict(snap_date=q[1], person_id="B", campus_org_code="U10", dept_org_code="D1", role_family="F", **base),
            dict(snap_date=q[1], person_id="C", campus_org_code="U10", dept_org_code="D1", role_family="F", **base),
            dict(snap_date=q[2], person_id="C", campus_org_code="U10", dept_org_code="D1", role_family="F", **base),
            dict(snap_date=q[0], person_id="D", campus_org_code="U10", dept_org_code="D1", role_family="F", **base),
            dict(snap_date=q[1], person_id="D", campus_org_code="U10", dept_org_code="D1", role_family="F", **base),
            dict(snap_date=q[2], person_id="D", campus_org_code="U10", dept_org_code="D2", role_family="F", **base),
        ])
        e = pd.DataFrame([dict(person_id="B", event_date=dt.date(2020, 6, 25), event_type="separation_resignation", is_future=False),
                          dict(person_id="C", event_date=dt.date(2020, 5, 1), event_type="hire", is_future=False),
                          dict(person_id="D", event_date=dt.date(2020, 8, 1), event_type="transfer_lateral", is_future=False)])
        cells = S.cell_table(f, e, q)
        d1 = cells[(cells.dept_org_code == "D1")].set_index("qi")
        self.assertEqual(d1.loc[1, "hires"], 1); self.assertEqual(d1.loc[1, "separations"], 0)
        self.assertEqual(d1.loc[2, "sep_voluntary"], 1)   # the late-posted resignation lands where the headcount drops
        self.assertEqual(d1.loc[2, "moves_out"], 1)
        d2 = cells[(cells.dept_org_code == "D2")].set_index("qi")
        self.assertEqual(d2.loc[2, "moves_in"], 1); self.assertEqual(d2.loc[2, "headcount"], 1)
        self.assertEqual(float(S.conservation_residual(cells).abs().max()), 0.0)

    @unittest.skipUnless(have_restricted(), "run series.py first")
    def test_pooling_rule(self):
        reg = panel().registry
        self.assertTrue(((reg["mean_headcount"] >= C.POOL_THRESHOLD) == reg["modelled"]).all())
        self.assertEqual(int(reg[reg.level == "dept"]["modelled"].sum()), 0)   # a fact about this population, stated in the card
        self.assertEqual(int(reg[reg.level == "campus"]["modelled"].sum()), 29)


# ------------------------------------------------------------------------------------------- leakage
class TestLeakage(unittest.TestCase):
    def test_truncate_blanks_future(self):
        p = synthetic_panel()
        t = S.truncate(p, 20)
        self.assertTrue(np.isnan(t.y["headcount"][:, 21:]).all()); self.assertFalse(np.isnan(t.y["headcount"][:, :21]).any())

    def test_design_ignores_future_even_without_truncation(self):
        p = synthetic_panel()
        a, b = L.design(p, "separations", 25), L.design(perturb_future(p, 25), "separations", 25)
        np.testing.assert_array_equal(a["X"], b["X"]); np.testing.assert_array_equal(a["y"], b["y"]); np.testing.assert_array_equal(a["Xp"], b["Xp"])
        h = a["names"].index("h")
        self.assertTrue((a["X"][:, h] <= 25).all())

    def test_full_forecast_unchanged_under_future_perturbation(self):
        p = synthetic_panel()
        T = 28
        a = L.forecast_at(S.truncate(p, T), "separations", T)
        b = L.forecast_at(S.truncate(perturb_future(p, T), T), "separations", T)
        c = L.forecast_at(perturb_future(p, T), "separations", T)   # no truncation at all: learners must still only read <= T
        for m in C.METHODS:
            for i in a[m]:
                np.testing.assert_allclose(a[m][i]["point"], b[m][i]["point"], rtol=1e-9, equal_nan=True)
                np.testing.assert_allclose(a[m][i]["point"], c[m][i]["point"], rtol=1e-9, equal_nan=True)

    @unittest.skipUnless(have_restricted(), "run series.py first")
    def test_real_panel_forecast_unchanged_under_future_perturbation(self):
        p = panel(); T = 30
        first = [int(np.where(p.registry.modelled)[0][0])]
        a = B.records_at(p, "headcount", T, series_idx=first)
        b = B.records_at(perturb_future(p, T), "headcount", T, series_idx=first)
        self.assertEqual([r["point"] for r in a], [r["point"] for r in b])
        self.assertNotEqual([r["actual"] for r in a], [r["actual"] for r in b])   # the actuals did change, the forecasts did not

    def test_covid_dummy_zero_at_forecast_and_marked_in_training(self):
        p = synthetic_panel(n_q=44)   # 2015Q1..2025Q4 covers the 2020Q1-2021Q2 window
        T = 30
        d = L.design(p, "headcount", T)
        ct = d["names"].index("covid_target")
        self.assertTrue((d["Xp"][:, ct] == 0).all())
        self.assertTrue((d["X"][:, ct] == 1).any())
        self.assertFalse(S.is_covid(p, T + 1))

    def test_empirical_intervals_only_use_resolved_errors(self):
        rows = []
        rng = np.random.default_rng(0)
        for o in range(10, 40):
            for s in range(3):
                rows.append(dict(target="headcount", method="B-ets", series_idx=s, origin=o, h=1, tq=o + 1, point=20.0, actual=20.0 + rng.normal()))
        df = pd.DataFrame(rows)
        a = B.add_empirical_intervals(df.copy())
        df2 = df.copy(); df2.loc[df2["tq"] > 25, "actual"] += 50.0
        b = B.add_empirical_intervals(df2)
        at = a[a.origin == 25].sort_values("series_idx"); bt = b[b.origin == 25].sort_values("series_idx")
        np.testing.assert_allclose(at["emp_lo80"].to_numpy(), bt["emp_lo80"].to_numpy())
        self.assertTrue(np.isnan(a[a.origin == 11]["emp_lo80"]).all())     # fewer than 12 resolved errors
        self.assertFalse(np.isnan(a[a.origin == 25]["emp_lo80"]).any())
        self.assertNotEqual(float(a[a.origin == 35]["emp_lo80"].iloc[0]), float(b[b.origin == 35]["emp_lo80"].iloc[0]))


# ------------------------------------------------------------------------------------------- determinism
class TestDeterminism(unittest.TestCase):
    def test_learners_deterministic(self):
        p = synthetic_panel(); T = 30
        a, b = L.forecast_at(S.truncate(p, T), "hires", T), L.forecast_at(S.truncate(p, T), "hires", T)
        for m in C.METHODS:
            for i in a[m]:
                self.assertEqual(a[m][i]["point"], b[m][i]["point"])

    @unittest.skipUnless(have_restricted() and (C.RESTRICTED / "forecast_latest.parquet").exists(), "run the pipeline first")
    def test_publish_twice_is_byte_identical(self):
        os.environ["WAP_RUN_DATE"] = "2026-11-07"
        d1, d2 = Path(tempfile.mkdtemp(prefix="mb1_")), Path(tempfile.mkdtemp(prefix="mb2_"))
        try:
            for d in (d1, d2):
                for f in ("metrics_b.json", "forecast_meta.json"):
                    shutil.copy(C.OUT / f, d / f)
                P.main(out=d, restricted=C.RESTRICTED, card_path=d / "MODEL_CARD.md")
            for f in sorted(d1.glob("*.csv")):
                self.assertEqual(f.read_bytes(), (d2 / f.name).read_bytes(), f.name)
            self.assertEqual((d1 / "export_manifest.json").read_bytes(), (d2 / "export_manifest.json").read_bytes())
        finally:
            shutil.rmtree(d1, ignore_errors=True); shutil.rmtree(d2, ignore_errors=True)

    @unittest.skipUnless(have_restricted() and (C.RESTRICTED / "backtest.parquet").exists(), "run the backtest first")
    def test_stored_backtest_rows_reproduce(self):
        p = panel()
        bt = pd.read_parquet(C.RESTRICTED / "backtest.parquet")
        T = 32
        fresh = pd.DataFrame(B.records_at(p, "separations", T))
        stored = bt[(bt.target == "separations") & (bt.origin == T)]
        m = fresh.merge(stored, on=["method", "series_idx", "h"], suffixes=("_f", "_s"))
        self.assertEqual(len(m), len(fresh))
        np.testing.assert_allclose(m["point_f"], m["point_s"], rtol=1e-9)


# ------------------------------------------------------------------------------------------- thresholds
class TestThresholds(unittest.TestCase):
    def test_thresholds_pinned_to_protocol(self):
        self.assertEqual(SC.THRESHOLDS_B, {"B1_rel_mase_h1_4_max": 0.95, "B2_rel_mase_h5_12_max": 1.00, "B3_cov80_range": (0.70, 0.90), "B4_cov95_min": 0.88,
                                           "B5_h4_bias_share_max": 0.02, "B6_hierarchy_discrepancy_max": 0.05, "B7_flag_precision_min": 0.60})
        self.assertEqual(C.ENSEMBLE_OF, ["B-ets", "B-pooled", "B-gbm"]); self.assertEqual(C.H, 12); self.assertEqual(C.K_MIN, 10)

    @unittest.skipUnless(have_published(), "run the pipeline first")
    def test_published_checks_recompute_from_inputs(self):
        met = json.loads((C.OUT / "metrics_b.json").read_text())
        inputs = {m: {k: (float("nan") if v is None else v) for k, v in met["threshold_inputs"][m].items() if not isinstance(v, dict)} for m in C.METHODS}
        for m in C.METHODS:
            self.assertEqual(SC.check_thresholds_b(inputs[m]), met["checks"][m], m)
        self.assertEqual(B.select_learner(met["checks"], inputs)["chosen"], met["selection"]["chosen"])
        self.assertFalse(met["checks"]["B-snaive"]["B1"])   # the reference cannot beat itself

    def test_selection_rule_cases(self):
        ok = {k: True for k in ("B1", "B2", "B3", "B4", "B5", "B6", "B7")}
        inp = {m: {"rel_mase_h1_4": 0.9} for m in C.METHODS}
        checks = {m: dict(ok) for m in C.METHODS}
        self.assertEqual(B.select_learner(checks, inp)["chosen"], "B-ens")
        checks["B-ens"]["B7"] = False; checks["B-pooled"]["B7"] = False; checks["B-gbm"]["B7"] = False
        self.assertEqual(B.select_learner(checks, inp)["chosen"], "B-ets")
        checks = {m: dict(ok) for m in C.METHODS}; checks["B-ens"]["B1"] = False
        checks["B-ets"]["B1"] = checks["B-pooled"]["B1"] = checks["B-gbm"]["B1"] = False
        sel = B.select_learner(checks, inp)
        self.assertEqual(sel["chosen"], "B-ens"); self.assertEqual(sel["by_horizon"]["4"], "B-snaive"); self.assertEqual(sel["by_horizon"]["5"], "B-ens")
        for m in C.METHODS:
            checks[m]["B2"] = False
        self.assertEqual(B.select_learner(checks, inp)["chosen"], "B-snaive")


# ------------------------------------------------------------------------------------------- suppression and schema
class TestSuppression(unittest.TestCase):
    def test_suppress_rule(self):
        df = pd.DataFrame({"g": ["a"] * 3 + ["b"] * 3, "n": [5, 12, 30, 4, 6, 40], "x": [1.0] * 6})
        out = P.suppress(df, "n", ["x"], ["g"])
        self.assertEqual(out["suppressed"].tolist(), [True, True, False, True, True, False])   # a: complementary on the 12; b: two primary, no complementary
        self.assertTrue(out.loc[out["suppressed"], "x"].isna().all()); self.assertEqual(out.loc[~out["suppressed"], "x"].tolist(), [1.0, 1.0])

    @unittest.skipUnless(have_published(), "run the pipeline first")
    def test_published_facts_are_suppressed(self):
        for name, measures in (("fact_attrition_forecast", P.FORECAST_MEASURES), ("fact_attrition_risk", P.RISK_MEASURES), ("fact_model_quality", P.QUALITY_MEASURES)):
            df = pd.read_csv(C.OUT / f"{name}.csv")
            sup = df["suppressed"].astype(str).str.lower() == "true"
            self.assertFalse(((df["n"] < C.K_MIN) & ~sup).any(), name)
            self.assertTrue(df.loc[sup, [m for m in measures if m in df.columns]].isna().all().all(), name)
        fc = pd.read_csv(C.OUT / "fact_attrition_forecast.csv")
        reg = panel().registry
        n_unmodelled = int(((reg.level == "campus") & ~reg.modelled).sum())
        self.assertEqual(int((fc["suppressed"].astype(str).str.lower() == "true").sum()), n_unmodelled * C.H * len(P.SCENARIOS))

    @unittest.skipUnless(have_published(), "run the pipeline first")
    def test_star_schema_shape_and_forbidden_columns(self):
        rep = P.validate(C.OUT)
        self.assertTrue(rep["ok"], rep["errors"])
        import yaml
        schema = yaml.safe_load((C.WAP / "delivery" / "star_schema.yaml").read_text())
        for t in ("fact_attrition_forecast", "fact_attrition_risk", "fact_model_quality", "dim_model_version"):
            cols = [c["name"] for c in schema["tables"][t]["columns"]]
            self.assertEqual(sorted(pd.read_csv(C.OUT / f"{t}.csv", nrows=1).columns), sorted(cols), t)
        forb = [f.lower() for f in schema["forbidden_columns"]]
        for f in C.OUT.glob("*.csv"):
            for c in pd.read_csv(f, nrows=1).columns:
                self.assertFalse(any(x in c.lower() for x in forb), f"{f.name}.{c}")
        dmv = pd.read_csv(C.OUT / "dim_model_version.csv")
        self.assertEqual(int((dmv["is_published_default"].astype(str).str.lower() == "true").sum()), 1)
        man = json.loads((C.OUT / "export_manifest.json").read_text())
        self.assertEqual(man["k_min"], C.K_MIN); self.assertTrue(man["validation_ok"])


# ------------------------------------------------------------------------------------------- learners and risk
class TestLearnersAndRisk(unittest.TestCase):
    def test_seasonal_naive_exact_on_periodic_series(self):
        y = np.array([3, 5, 7, 9] * 6, float)
        f = L.seasonal_naive(y, 20)
        self.assertEqual(f["point"], [5, 7, 9, 3, 5, 7, 9, 3, 5, 7, 9, 3])

    def test_ensemble_geometric_mean_and_missing(self):
        e = L.ensemble([{"point": [1.0] * 12}, {"point": [3.0] * 12}, {"point": [7.0] * 12}])
        self.assertAlmostEqual(e["point"][0], np.expm1(np.mean(np.log1p([1, 3, 7]))))
        miss = L.ensemble([{"point": [1.0] * 12}, {"point": [np.nan] + [3.0] * 11}, {"point": [7.0] * 12}])
        self.assertTrue(np.isnan(miss["point"][0])); self.assertFalse(np.isnan(miss["point"][1]))

    def test_scorers_agree_with_hand_values(self):
        self.assertAlmostEqual(SC.mase_scale([1, 2, 3, 4, 3, 4, 5, 6]), 2.0)
        self.assertEqual(SC.smape([10], [10])[0], 0.0)
        self.assertEqual(SC.interval_coverage([1, 2, 3], [0, 3, 2], [2, 4, 4]), 2 / 3)

    def test_attrition_flag_rule(self):
        p = synthetic_panel(n_series=6, n_q=40)
        T = 39
        points = {i: {"separations": [1.0] * 4, "headcount": [20.0] * 4} for i in range(6)}
        points[5] = {"separations": [6.0] * 4, "headcount": [20.0] * 4}        # expected rate 1.2 vs peers 0.2
        p.y["separations"][5, T - 3: T + 1] = 8.0                               # trailing observed also high
        rng = np.random.default_rng(0)
        paths = rng.normal(0, 0.05, size=(30, 4))
        sc = R.score_units(p, T, points, paths, paths, seed=1).set_index("series_id")
        self.assertEqual(sc["n_peer_units"].iloc[0], 6)
        self.assertTrue(bool(sc.loc["C|U10|F5", "attrition_flag"])); self.assertFalse(bool(sc.loc["C|U10|F0", "attrition_flag"]))
        self.assertTrue((sc["expected_sep_rate_p10"] <= sc["expected_sep_rate_4q"]).all())
        # fewer than MIN_PATHS error paths -> no interval -> no flag decision
        sc2 = R.score_units(p, T, points, paths[:5], paths[:5], seed=1)
        self.assertTrue(sc2["attrition_flag"].isna().all())


if __name__ == "__main__":
    unittest.main()
