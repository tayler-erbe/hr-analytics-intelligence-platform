"""Unit tests for the workforce scenario simulator.

Run from platform-evaluation/:
    python -m unittest discover -s workforce_sim/tests -v
"""
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
PKG = HERE.parent
sys.path.insert(0, str(PKG))

import synthesize as syn  # noqa: E402
import simulate as sim    # noqa: E402

# Stated calibration tolerances (also documented in README.md)
TOL = {
    "family_ftpt_count_abs": 0,        # synthetic family x FT/PT counts = IPEDS exactly
    "rank_count_abs": 0,               # FT faculty rank counts = IPEDS exactly
    "age_share_abs": 0.005,            # synthetic age-group share vs QWI stable-employment share
    "sim_age_sep_rate_rel": 0.05,      # simulated quarterly separation rate vs QWI target, by age group
    "sim_annual_sep_vs_ipeds_rel": 0.10,  # IPEDS-anchored annual separation rate vs UIUC FT new-hire rate
}

CAL = sim.load_cal()


class _Synthetic(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls.tmp.name) / "a"
        syn.write(syn.synthesize(syn.DEFAULT_SEED, CAL), cls.dir, syn.DEFAULT_SEED)
        cls.snap = sim.load_snapshot(cls.dir)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()


class TestReproducibility(_Synthetic):
    def test_synthesis_same_seed_identical(self):
        d2 = Path(self.tmp.name) / "b"
        syn.write(syn.synthesize(syn.DEFAULT_SEED, CAL), d2, syn.DEFAULT_SEED)
        for t in ("position", "person", "appointment"):
            self.assertTrue(pq.read_table(self.dir / f"{t}.parquet").equals(pq.read_table(d2 / f"{t}.parquet")), t)

    def test_synthesis_different_seed_differs(self):
        d3 = Path(self.tmp.name) / "c"
        syn.write(syn.synthesize(syn.DEFAULT_SEED + 1, CAL), d3, syn.DEFAULT_SEED + 1)
        a = pq.read_table(self.dir / "person.parquet").column("age_at_snapshot").to_pylist()
        b = pq.read_table(d3 / "person.parquet").column("age_at_snapshot").to_pylist()
        self.assertNotEqual(a, b)

    def test_simulation_same_seed_identical(self):
        scn = sim.Scenario(freeze_pct=25, freeze_quarters=4, retire_incentive="moderate", reskill_pct=5, horizon=8)
        r1 = sim.simulate(scn, runs=6, seed=11, cal=CAL, snap=self.snap)
        r2 = sim.simulate(scn, runs=6, seed=11, cal=CAL, snap=self.snap)
        r3 = sim.simulate(scn, runs=6, seed=12, cal=CAL, snap=self.snap)
        for k in r1["out"]:
            np.testing.assert_array_equal(r1["out"][k], r2["out"][k])
        np.testing.assert_array_equal(r1["hc_fam"], r2["hc_fam"])
        self.assertEqual(sim.summarise(r1), sim.summarise(r2))
        self.assertFalse(np.array_equal(r1["flows"]["separations"], r3["flows"]["separations"]))


class TestConservation(_Synthetic):
    def _check(self, scn):
        r = sim.simulate(scn, runs=8, seed=3, cal=CAL, snap=self.snap)
        hc, fl = r["out"]["headcount"], r["flows"]
        # per quarter: start + hires - separations = end (promotions/transfers are internal)
        delta = hc[:, 1:] - hc[:, :-1]
        np.testing.assert_array_equal(delta, fl["hires"][:, 1:] - fl["separations"][:, 1:])
        # whole horizon, per run
        np.testing.assert_array_equal(hc[:, 0] + fl["hires"].sum(1) - fl["separations"].sum(1), hc[:, -1])
        self.assertTrue(r["ledger_ok"])
        # family headcounts add to the total
        np.testing.assert_array_equal(r["hc_fam"].sum(1), hc)
        return r

    def test_baseline(self):
        self._check(sim.Scenario(horizon=12))

    def test_all_levers(self):
        r = self._check(sim.Scenario("qwi", 50, 8, "strong", 5, horizon=12))
        self.assertGreater(r["flows"]["transfers"].sum(), 0)
        self.assertGreater(r["flows"]["promotions"].sum(), 0)

    def test_freeze_lowers_headcount_during_window(self):
        base = sim.simulate(sim.Scenario(horizon=6), runs=12, seed=9, cal=CAL, snap=self.snap)
        frz = sim.simulate(sim.Scenario(freeze_pct=50, freeze_quarters=4, horizon=6), runs=12, seed=9,
                           cal=CAL, snap=self.snap)
        hb, hf = base["out"]["headcount"], frz["out"]["headcount"]
        self.assertTrue(np.all(hf[:, 1:5].mean(0) < hb[:, 1:5].mean(0)))
        # common random numbers: identical separations in quarter 1 (before any lever acts)
        np.testing.assert_array_equal(base["flows"]["separations"][:, 1], frz["flows"]["separations"][:, 1])

    def test_start_matches_ipeds_headcount(self):
        r = sim.simulate(sim.Scenario(horizon=1), runs=2, seed=1, cal=CAL, snap=self.snap)
        self.assertEqual(int(r["out"]["headcount"][0, 0]), CAL["uiuc_ipeds"]["grand_total_headcount"])


class TestGrainAndBitemporal(_Synthetic):
    def test_asof_counts(self):
        c = sim.snapshot_counts(self.dir)
        k = c["as_known_2023_11_15"]
        self.assertEqual(k["headcount"], 12905)
        self.assertEqual(k["primary_appointments"], 12905)
        self.assertEqual(k["ft_headcount"], CAL["uiuc_ipeds"]["ft_total"])
        self.assertGreater(k["appointments"], k["headcount"])  # secondary appointments exist
        later = c["as_known_2024_01_31"]
        self.assertEqual(later["headcount"] - k["headcount"], syn.ASSUMPTIONS["late_recorded_appointments"])

    def test_corrections_exist_and_resolve(self):
        a = pq.read_table(self.dir / "appointment.parquet").to_pylist()
        revs = [x for x in a if x["revision"] == 2]
        self.assertGreater(len(revs), 100)


class TestCalibration(_Synthetic):
    def test_family_and_ftpt_counts_exact(self):
        fams = CAL["uiuc_ipeds"]["families"]
        occ = self.snap["occ"]
        for f, i in sim.FI.items():
            m = occ & (self.snap["fam"] == i)
            self.assertLessEqual(abs(int((m & self.snap["ft"]).sum()) - fams[f]["ft"]), TOL["family_ftpt_count_abs"], f)
            self.assertLessEqual(abs(int((m & ~self.snap["ft"]).sum()) - fams[f]["pt"]), TOL["family_ftpt_count_abs"], f)

    def test_faculty_rank_counts_exact(self):
        appt = pq.read_table(self.dir / "appointment.parquet").to_pylist()
        cur = {}
        for x in appt:
            if x["eff_end"] is None and x["appointment_type"] == "primary" and x["record_note"] is None:
                cur[x["appointment_id"]] = x["rank_code"]
        for code, r in CAL["uiuc_ipeds"]["faculty_ft_rank"].items():
            n = sum(1 for v in cur.values() if v == code)
            self.assertLessEqual(abs(n - r["ft_headcount"]), TOL["rank_count_abs"], code)

    def test_age_mix_vs_qwi(self):
        qwi = CAL["qwi_il_higher_ed"]["by_age"]
        ages = self.snap["age"][self.snap["occ"]]
        g = np.digitize(ages, sim.AGE_EDGES)
        for i, a in enumerate(sim.AGE_GROUPS):
            share = float((g == i).mean())
            self.assertLessEqual(abs(share - qwi[a]["sim_population_share"]), TOL["age_share_abs"], a)

    def test_simulated_separation_rates_vs_qwi(self):
        r = sim.simulate(sim.Scenario("qwi", horizon=8), runs=40, seed=5, cal=CAL, snap=self.snap,
                         record_age_diag=True)
        rate = r["age_separations"][1:].sum(0) / r["age_exposure"][1:].sum(0)
        target = CAL["hazard_anchors"]["qwi"]["quarterly_rate_by_age"]
        for i, a in enumerate(sim.AGE_GROUPS):
            rel = abs(rate[i] / target[a] - 1)
            self.assertLessEqual(rel, TOL["sim_age_sep_rate_rel"], f"{a}: sim {rate[i]:.4f} vs {target[a]:.4f}")

    def test_ipeds_anchor_annual_rate(self):
        r = sim.simulate(sim.Scenario("ipeds", horizon=8), runs=40, seed=5, cal=CAL, snap=self.snap)
        hc = r["out"]["headcount"][:, :-1].mean()
        annual = r["flows"]["separations"][:, 1:].sum(1).mean() / 2 / hc
        target = CAL["uiuc_ipeds"]["ft_new_hire_rate"]
        self.assertLessEqual(abs(annual / target - 1), TOL["sim_annual_sep_vs_ipeds_rel"], f"{annual:.4f} vs {target}")

    def test_calibration_cross_checks(self):
        self.assertTrue(CAL["uiuc_ipeds"]["cross_check"]["equals_grand_total"])
        self.assertTrue(CAL["uiuc_ipeds"]["cross_check"]["equals_ft_instructional"])
        self.assertEqual(CAL["qwi_il_higher_ed"]["cross_check"]["contract_vs_silver_sep_emp_mismatches"], 0)
        self.assertTrue(CAL["caveats"])


class TestNoRealIdentifiers(_Synthetic):
    FORBIDDEN_COLS = re.compile(r"name|email|ssn|uin|netid|birth|dob|address|phone|gender|sex|race", re.I)
    ID_PAT = {"position_id": r"SYN-POS-\d{6}", "person_id": r"SYN-PER-\d{6}", "appointment_id": r"SYN-APT-\d{7}"}

    def test_identifiers(self):
        for t in ("position", "person", "appointment"):
            tbl = pq.read_table(self.dir / f"{t}.parquet")
            for col in tbl.column_names:
                self.assertIsNone(self.FORBIDDEN_COLS.search(col), f"{t}.{col}")
                vals = tbl.column(col).to_pylist()
                if col in self.ID_PAT:
                    pat = re.compile(self.ID_PAT[col] + r"$")
                    self.assertTrue(all(v is None or pat.match(v) for v in vals), f"{t}.{col}")
                elif tbl.schema.field(col).type == "string":
                    for v in vals:
                        if v is None:
                            continue
                        self.assertNotIn("@", v)
                        self.assertIsNone(re.search(r"\b\d{9}\b", v), f"9-digit number in {t}.{col}")
                        self.assertIsNone(re.search(r"\b[A-Z][a-z]+ [A-Z][a-z]+\b", v), f"name-like '{v}' in {t}.{col}")
        per = pq.read_table(self.dir / "person.parquet")
        self.assertTrue(all(per.column("synthetic").to_pylist()))

    def test_outputs_are_aggregate(self):
        grid = PKG / "data" / "scenario_grid.json"
        if not grid.exists():
            self.skipTest("scenario_grid.json not generated yet")
        txt = grid.read_text()
        self.assertNotIn("SYN-PER-", txt)
        self.assertNotIn("SYN-APT-", txt)
        self.assertNotIn("SYN-POS-", txt)


if __name__ == "__main__":
    unittest.main()
