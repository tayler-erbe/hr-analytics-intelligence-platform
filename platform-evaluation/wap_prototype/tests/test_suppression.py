"""k >= 10 with complementary suppression on everything published outside outputs/restricted/."""
from __future__ import annotations

import csv
import unittest

from wap_prototype.publish import PUBLIC_TABLES, RESTRICTED_TABLES
from wap_prototype.tests.common import full_run

K = 10
ID_COLUMNS = {"person_id", "supervisor_person_id", "from_supervisor_person_id", "to_supervisor_person_id", "birth_date"}


class TestSuppression(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = full_run()
        cls.con = cls.ctx["src"].con

    def test_unit_aggregates_never_show_cells_below_k(self):
        for t in ("unit_quarter_aggregates", "unit_year_aggregates"):
            n = self.con.execute(f"""SELECT count(*) FROM {t} WHERE (headcount IS NOT NULL AND headcount < {K})
                OR (hires > 0 AND hires < {K}) OR (separations > 0 AND separations < {K}) OR (retirements > 0 AND retirements < {K})
                OR (promotions > 0 AND promotions < {K}) OR (transfers > 0 AND transfers < {K})""").fetchall()[0][0]
            self.assertEqual(n, 0, t)
            self.assertGreater(self.con.execute(f"SELECT count(*) FROM {t} WHERE suppression_reason = 'headcount_below_k'").fetchall()[0][0], 0)

    def test_complementary_suppression(self):
        # within a parent group with siblings, a single headcount-suppressed cell never stands alone
        n = self.con.execute(f"""SELECT count(*) FROM (
            SELECT quarter_end, campus_org_code, college_org_code, role_family,
                   count(*) FILTER (WHERE suppression_reason = 'headcount_below_k') AS a,
                   count(*) FILTER (WHERE suppression_reason = 'complementary') AS c
            FROM unit_quarter_aggregates GROUP BY ALL HAVING count(*) > 1) WHERE a = 1 AND c = 0""").fetchall()[0][0]
        self.assertEqual(n, 0)
        n = self.con.execute(f"""SELECT count(*) FROM (
            SELECT year, campus_org_code, count(*) FILTER (WHERE suppression_reason = 'headcount_below_k') AS a,
                   count(*) FILTER (WHERE suppression_reason = 'complementary') AS c
            FROM unit_year_aggregates GROUP BY ALL HAVING count(*) > 1) WHERE a = 1 AND c = 0""").fetchall()[0][0]
        self.assertEqual(n, 0)

    def test_transition_counts_and_feature_summary(self):
        n = self.con.execute(f"SELECT count(*) FROM transition_counts WHERE n_events IS NOT NULL AND n_events > 0 AND n_events < {K}").fetchall()[0][0]
        self.assertEqual(n, 0)
        n = self.con.execute(f"SELECT count(*) FROM feature_summary WHERE n_persons < {K} AND NOT suppressed").fetchall()[0][0]
        self.assertEqual(n, 0)
        n = self.con.execute(f"SELECT count(*) FROM feature_summary WHERE n_persons < {K} AND mean_tenure_years IS NOT NULL").fetchall()[0][0]
        self.assertEqual(n, 0)

    def test_public_files_carry_no_person_ids(self):
        out = self.ctx["out"]
        for t in PUBLIC_TABLES:
            with open(out / f"{t}.csv", newline="", encoding="utf-8") as fh:
                header = set(next(csv.reader(fh)))
            self.assertFalse(header & ID_COLUMNS, t)
        for t in RESTRICTED_TABLES:
            self.assertTrue((out / "restricted" / f"{t}.csv").exists())
            self.assertFalse((out / f"{t}.csv").exists())
        self.assertEqual((out / "restricted" / ".gitignore").read_text().split(), ["*", "!.gitignore"])

    def test_config_refuses_k_below_10(self):
        from wap_prototype.config import Config
        with self.assertRaises(ValueError):
            Config(min_cell_size=5).validate()


if __name__ == "__main__":
    unittest.main()
