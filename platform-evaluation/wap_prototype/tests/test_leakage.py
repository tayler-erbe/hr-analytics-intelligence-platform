"""Leakage: features at snapshot t use nothing effective or posted after t."""
from __future__ import annotations

import datetime as dt
import unittest

from wap_prototype import extract as E
from wap_prototype import features as F
from wap_prototype import transitions as T
from wap_prototype.tests.common import FixtureMixin, full_run

d = dt.date


class TestLeakageFixture(FixtureMixin, unittest.TestCase):
    def test_late_keyed_correction_is_invisible_until_posted(self):
        src = E.open_source(self.cfg, attach_integrated=False)
        E.register_restricted(src)
        T.build_latest(src)
        snaps = [d(2020, 7, 2), d(2020, 7, 4), d(2020, 7, 6), d(2020, 7, 8)]
        F.build_features(src, snaps)
        rows = {r[0]: r[1:] for r in src.con.execute(
            "SELECT snap_date, class_key, annual_salary, n_promotions, n_active_jobs FROM person_period_features ORDER BY 1").fetchall()}
        # 07-02 and 07-04: the July row was keyed on 07-05, so the January state (L1, 40000) is all that is known
        self.assertEqual(rows[d(2020, 7, 2)], ("L1", 40000.0, 0, 1))
        self.assertEqual(rows[d(2020, 7, 4)], ("L1", 40000.0, 0, 1))
        # 07-06: the correction and the July row are known (L2, promotion); the bad 07-03 copy is still known too
        self.assertEqual(rows[d(2020, 7, 6)][:3], ("L2", 52000.0, 1))
        # 07-08: the deletion is posted; still L2 with one promotion
        self.assertEqual(rows[d(2020, 7, 8)][:3], ("L2", 52000.0, 1))
        src.close()

    def test_age_band_only_and_no_demographics_in_features(self):
        src = E.open_source(self.cfg, attach_integrated=False)
        E.register_restricted(src)
        T.build_latest(src)
        F.build_features(src, [d(2020, 7, 8)])
        cols = {r[0] for r in src.con.execute("DESCRIBE person_period_features").fetchall()}
        self.assertIn("age_band", cols)
        for forbidden in ("birth_date", "age_years", "sex_code", "gender_code", "race_eth_rpt_code", "ipeds_race_eth", "citizenship_group", "veteran_class"):
            self.assertNotIn(forbidden, cols)
        self.assertEqual(src.con.execute("SELECT age_band FROM person_period_features").fetchall(), [("40-44",)])
        src.close()


class TestLeakageFullRun(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = full_run()
        cls.con = cls.ctx["src"].con

    def test_every_feature_row_uses_rows_known_and_effective_by_t(self):
        n = self.con.execute("SELECT count(*) FROM person_period_features WHERE primary_row_known_from > snap_date OR primary_row_start > snap_date").fetchall()[0][0]
        self.assertEqual(n, 0)

    def test_removing_rows_posted_after_t_does_not_change_features(self):
        """Direct test: rebuild one snapshot after deleting everything known after t; the non-target features
        must be byte-identical (targets are allowed to use later knowledge by design)."""
        src = self.ctx["src"]
        con = src.con
        t = d(2024, 6, 30)
        F.build_features(src, [t], out_table="lk_a")
        con.execute("CREATE OR REPLACE TEMP TABLE lk_backup_appt AS SELECT * FROM x_appointment")
        con.execute("CREATE OR REPLACE TEMP TABLE lk_backup_emp AS SELECT * FROM x_employment")
        con.execute("CREATE OR REPLACE TEMP TABLE lk_backup_pos AS SELECT * FROM x_position")
        con.execute("CREATE OR REPLACE TEMP TABLE lk_backup_sep AS SELECT * FROM x_separation")
        con.execute("CREATE OR REPLACE TEMP TABLE lk_backup_leave AS SELECT * FROM x_leave")
        try:
            for tbl in ("x_appointment", "x_employment", "x_position", "x_separation", "x_leave"):
                con.execute(f"DELETE FROM {tbl} WHERE known_from > DATE '{t}'")
            con.execute(f"DELETE FROM x_appointment WHERE valid_from > DATE '{t}'")
            F.build_features(src, [t], out_table="lk_b")
            cols = [r[0] for r in con.execute("DESCRIBE lk_a").fetchall()
                    if not (r[0].endswith("_censored") or "_within_" in r[0])]
            sel = ", ".join(cols)
            diff = con.execute(f"SELECT count(*) FROM ((SELECT {sel} FROM lk_a) EXCEPT (SELECT {sel} FROM lk_b))").fetchall()[0][0]
            diff2 = con.execute(f"SELECT count(*) FROM ((SELECT {sel} FROM lk_b) EXCEPT (SELECT {sel} FROM lk_a))").fetchall()[0][0]
            self.assertEqual((diff, diff2), (0, 0))
            self.assertGreater(con.execute("SELECT count(*) FROM lk_a").fetchall()[0][0], 700)
        finally:
            for tbl, bk in (("x_appointment", "lk_backup_appt"), ("x_employment", "lk_backup_emp"), ("x_position", "lk_backup_pos"),
                            ("x_separation", "lk_backup_sep"), ("x_leave", "lk_backup_leave")):
                con.execute(f"CREATE OR REPLACE TEMP TABLE {tbl} AS SELECT * FROM {bk}")
                con.execute(f"DROP TABLE {bk}")
            for tbl in ("lk_a", "lk_b"):
                con.execute(f"DROP TABLE IF EXISTS {tbl}")

    def test_targets_are_censored_beyond_the_knowledge_date(self):
        k = self.ctx["src"].knowledge_date
        bad = self.con.execute(f"""SELECT count(*) FROM person_period_features
            WHERE (snap_date + INTERVAL 12 MONTH > DATE '{k}' AND (promoted_within_12m IS NOT NULL OR NOT promoted_within_12m_censored))
               OR (snap_date + INTERVAL 12 MONTH <= DATE '{k}' AND (promoted_within_12m IS NULL OR promoted_within_12m_censored))""").fetchall()[0][0]
        self.assertEqual(bad, 0)


if __name__ == "__main__":
    unittest.main()
