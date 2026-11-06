"""Unit tests for the faculty pipeline model.

Run from platform-evaluation/:  python -m unittest discover -s faculty_pipeline/tests -v
Needs faculty_pipeline/calibration.json (python faculty_pipeline/calibrate.py). The IPEDS
cross-check against the lake is skipped when the lake is not built.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
PKG = HERE.parent
sys.path.insert(0, str(PKG))

import model as M  # noqa: E402

CAL = M.load_cal()
INSTS = ["UIUC", "UIC", "UIS"]
CONTRACT = PKG.parent / "data" / "lake" / "contract"


class TestCalibrationStartState(unittest.TestCase):
    def test_start_state_matches_ipeds_exactly(self):
        for k in INSTS:
            inst = M.institution(CAL, k)
            X = M.start_state(inst.counts, inst.fit)
            ip = CAL["institutions"][k]["instructional"]
            for s in M.STATES:
                self.assertEqual(int(X[s].sum()), ip["states"][s], (k, s))
                self.assertTrue((X[s] >= 0).all())
            self.assertEqual(sum(int(X[s].sum()) for s in M.STATES), ip["total"], k)
            self.assertEqual(int(X["ASC"].sum() + X["FUL"].sum()), ip["tenured"], k)

    def test_uiuc_published_counts(self):
        ip = CAL["institutions"]["UIUC"]["instructional"]
        self.assertEqual(ip["total"], 2498)
        self.assertEqual(ip["states"], {"PRE": 527, "ASC": 477, "FUL": 799, "NTP": 393, "NTL": 302})
        nh = CAL["institutions"]["UIUC"]["new_hires"]
        self.assertEqual((nh["tenured"], nh["tenure_track"], nh["ntt"]), (23, 95, 83))

    @unittest.skipUnless((CONTRACT / "ipeds_instructional_staff.parquet").exists(), "lake not built")
    def test_leaf_partition_against_lake(self):
        import duckdb
        con = duckdb.connect()
        t = str(CONTRACT / "ipeds_instructional_staff.parquet")
        leaf = [c for v in CAL["state_ipeds_rows"].values() for c in v]
        for k in INSTS:
            u = CAL["institutions"][k]["unitid"]
            got = dict(con.execute(f"""select siscat_code, headcount from '{t}' where unitid = ?
                and sex = 'Total' and race_ethnicity = 'Total'""", [u]).fetchall())
            self.assertEqual(sum(got.get(c, 0) for c in leaf), got["100"], k)
            # sex/race detail rows sum to the published Total for the leaf rows
            det = con.execute(f"""select sum(headcount) from '{t}' where unitid = ? and sex <> 'Total'
                and race_ethnicity = 'Total' and siscat_code in ({','.join('?' * len(leaf))})""", [u] + leaf).fetchall()[0][0]
            self.assertEqual(int(det or 0), got["100"], k)

    def test_start_age_matches_cupa_hr(self):
        lit = CAL["literature"]["faculty_age"]
        for k, tol in (("UIUC", 0.01), ("UIC", 0.01), ("UIS", 0.04)):
            inst = M.institution(CAL, k)
            s55, s65 = M.age_shares(M.start_state(inst.counts, inst.fit))
            self.assertAlmostEqual(s55, lit["share_55_plus"], delta=tol, msg=k)
            self.assertAlmostEqual(s65, lit["share_65_plus"], delta=tol, msg=k)


class TestTransitionRates(unittest.TestCase):
    def test_review_rate_reproduces_tenure_success(self):
        for T in (0.50, 0.62, 0.72):
            self.assertAlmostEqual(float(M.tenure_prob(M.solve_review_rate(T))), T, places=9)

    def test_assoc_timing_reproduces_target(self):
        for m in (6.5, 7.0, 8.2):
            self.assertAlmostEqual(float(M.asc_mean_years(M.solve_asc_rate(m))), m, delta=0.02)

    def test_cell_rows_are_stochastic(self):
        for k in INSTS:
            inst = M.institution(CAL, k)
            p = M.draw_params(50, 7, 0, CAL)
            for inc in (1.0, 2.0):
                for s, rows in M.outcome_rows(inst, p, incentive=inc, t=0).items():
                    self.assertTrue((rows >= -1e-12).all() and (rows <= 1 + 1e-12).all(), (k, s))
                    np.testing.assert_allclose(rows.sum(-1), 1.0, atol=1e-12, err_msg=f"{k} {s}")

    def test_aggregate_matrix_is_stochastic(self):
        for k in INSTS:
            inst = M.institution(CAL, k)
            X = M.start_state(inst.counts, inst.fit)
            mat = M.aggregate_matrix(inst, X, M.draw_params(3, 1, 0, CAL), run=1, incentive=1.5)
            np.testing.assert_allclose(mat.sum(1), 1.0, atol=1e-12)
            self.assertTrue((mat >= 0).all())
            self.assertEqual(mat[5, 5], 1.0)
            self.assertEqual(mat[6, 6], 1.0)
            # no demotions and no flows out of absorbing states
            self.assertEqual(mat[2, 1], 0.0)
            self.assertEqual(mat[1, 0], 0.0)

    def test_nobody_survives_the_age_boundary(self):
        inst = M.institution(CAL, "UIUC")
        rows = M.outcome_rows(inst, M.draw_params(4, 1, 0, CAL))
        for s, r in rows.items():
            np.testing.assert_allclose(r[:, -1, :, :, 2], 1.0)


class TestEngine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inst = M.institution(CAL, "UIUC")
        cls.out = M.simulate(cls.inst, M.Levers(), runs=40, seed=11, horizon=8, cal=CAL)

    def test_conservation_total(self):
        o = self.out
        tot = sum(o["stock"][s] for s in M.STATES)
        f = o["flows"]
        np.testing.assert_array_equal(tot[:, 1:], tot[:, :-1] + f["hire"][:, 1:] - f["retire"][:, 1:] - f["separate"][:, 1:])

    def test_conservation_by_state(self):
        o = self.out
        st, f, hb = o["stock"], o["flows"], o["hires_by"]
        d = lambda s: st[s][:, 1:] - st[s][:, :-1]  # noqa: E731
        out_ = lambda s: o["ret_by"][s][:, 1:] + o["sep_by"][s][:, 1:]  # noqa: E731
        np.testing.assert_array_equal(d("PRE"), hb["PRE"][:, 1:] - out_("PRE") - f["tenure"][:, 1:])
        np.testing.assert_array_equal(d("ASC") + d("FUL"), hb["SEN"][:, 1:] + f["tenure"][:, 1:] - out_("ASC") - out_("FUL"))
        np.testing.assert_array_equal(d("FUL"), (st["FUL"][:, 1:] - st["FUL"][:, :-1]))
        for s in ("NTP", "NTL"):
            np.testing.assert_array_equal(d(s), hb[s][:, 1:] - out_(s))
        for s in M.STATES:
            self.assertTrue((o["final_state"][s] >= 0).all())

    def test_hires_follow_budget(self):
        np.testing.assert_array_equal(self.out["flows"]["hire"][:, 1:], self.out["hires_per_year"])
        self.assertEqual(self.out["hires_per_year"], CAL["institutions"]["UIUC"]["new_hires"]["total_faculty_status"])

    def test_reproducible(self):
        a = M.simulate(self.inst, M.Levers(), runs=40, seed=11, horizon=8, cal=CAL)
        for s in M.STATES:
            np.testing.assert_array_equal(a["stock"][s], self.out["stock"][s])
        np.testing.assert_array_equal(a["flows"]["retire"], self.out["flows"]["retire"])
        b = M.simulate(self.inst, M.Levers(), runs=40, seed=12, horizon=8, cal=CAL)
        self.assertFalse(np.array_equal(b["flows"]["retire"], self.out["flows"]["retire"]))

    def test_budget_lever_monotone_under_crn(self):
        med = []
        for bm in (0.7, 1.0, 1.3):
            o = M.simulate(self.inst, M.Levers(budget_mult=bm), runs=60, seed=3, horizon=6, cal=CAL)
            med.append(np.median(sum(o["stock"][s] for s in M.STATES)[:, 6]))
        self.assertLess(med[0], med[1])
        self.assertLess(med[1], med[2])

    def test_incentive_raises_early_retirements(self):
        base = M.simulate(self.inst, M.Levers(), runs=60, seed=5, horizon=3, cal=CAL)
        inc = M.simulate(self.inst, M.Levers(incentive=2.0), runs=60, seed=5, horizon=3, cal=CAL)
        self.assertGreater(inc["flows"]["retire"][:, 1:3].sum(), base["flows"]["retire"][:, 1:3].sum())

    def test_ntt_mix_lever(self):
        o = M.simulate(self.inst, M.Levers(ntt_share=0.8), runs=20, seed=5, horizon=3, cal=CAL)
        h = o["hires_by"]
        ntt = (h["NTP"] + h["NTL"])[:, 1:].sum()
        allh = sum(v[:, 1:].sum() for v in h.values())
        self.assertAlmostEqual(ntt / allh, 0.8, delta=0.03)


if __name__ == "__main__":
    unittest.main()
