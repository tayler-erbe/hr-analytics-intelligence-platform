"""The JOB_DETL_EFF_DT vs JOB_DETL_HIST_EFF_DT switch on a tiny fixture."""
from __future__ import annotations

import datetime as dt
import unittest

from wap_prototype import extract as E
from wap_prototype import transitions as T
from wap_prototype.config import Config
from wap_prototype.tests.common import FixtureMixin

d = dt.date


class TestDateSwitch(FixtureMixin, unittest.TestCase):
    def events(self, column: str):
        cfg = Config(**{**self.cfg.__dict__, "job_change_date_column": column})
        src = E.open_source(cfg, attach_integrated=False)
        T.build_latest(src)
        rows = src.con.execute("SELECT event_date, event_type, to_class_key, date_column_used, row_eff_date, row_recorded_start "
                               "FROM transition_events ORDER BY event_date, event_type").fetchall()
        src.close()
        return src.date_mode, rows

    def test_default_reads_eff_date_as_the_change_date(self):
        mode, rows = self.events("JOB_DETL_EFF_DT")
        self.assertEqual(mode, "eff_date")
        self.assertEqual([(r[0], r[1], r[2]) for r in rows], [(d(2020, 1, 1), "hire", "L1"), (d(2020, 7, 1), "promotion", "L2")])
        self.assertTrue(all(r[3] == "JOB_DETL_EFF_DT" for r in rows))
        # the deleted copy (eff 2020-07-03) is not an event under current knowledge
        self.assertNotIn(d(2020, 7, 3), [r[0] for r in rows])

    def test_alternative_reads_hist_eff_date_as_the_change_date(self):
        mode, rows = self.events("JOB_DETL_HIST_EFF_DT")
        self.assertEqual(mode, "recorded_start")
        dates = sorted({r[0] for r in rows})
        self.assertEqual(dates, [d(2020, 1, 10), d(2020, 7, 5)])          # version dates become event dates
        self.assertEqual([r[1] for r in rows if r[0] == d(2020, 1, 10)], ["hire"])
        change = [r for r in rows if r[2] == "L2" and r[1] in ("promotion", "reclassification")]
        self.assertEqual(len(change), 1)
        self.assertEqual(change[0][0], d(2020, 7, 5))
        self.assertTrue(all(r[3] == "JOB_DETL_HIST_EFF_DT" for r in rows))

    def test_alternative_known_from_effective_date_keeps_history_visible(self):
        from wap_prototype import features as F
        strict = Config(**{**self.cfg.__dict__, "job_change_date_column": "JOB_DETL_HIST_EFF_DT"})
        loose = Config(**{**self.cfg.__dict__, "job_change_date_column": "JOB_DETL_HIST_EFF_DT", "hist_mode_known_from": "effective_date"})
        out = {}
        for name, cfg in (("strict", strict), ("loose", loose)):
            src = E.open_source(cfg, attach_integrated=False)
            E.register_restricted(src)
            T.build_latest(src)
            F.build_features(src, [d(2020, 3, 31)])
            out[name] = src.con.execute("SELECT count(*) FROM person_period_features").fetchall()[0][0]
            src.close()
        # the January row's post date is 2020-07-05 (it was modified then), so under the strict post-date reading
        # nothing is known on 2020-03-31; assuming posting on the effective date makes it visible
        self.assertEqual((out["strict"], out["loose"]), (0, 1))

    def test_switch_is_validated(self):
        with self.assertRaises(ValueError):
            Config(job_change_date_column="JOB_DETL_HIST_POST_DT").validate()
        cfg = Config(**{**self.cfg.__dict__})
        cfg.job_change_date_column = "JOB_DETL_HIST_EFF_DT"
        self.assertEqual(cfg.to_dict()["job_change_date_column"], "JOB_DETL_HIST_EFF_DT")

    def test_switch_is_resolved_through_the_mapping_only(self):
        import yaml
        m = yaml.safe_load(self.cfg.mapping_file.read_text(encoding="utf-8"))
        m["concepts"]["appointment"]["fields"]["recorded_start"]["column"] = "HZ"     # mapping no longer names the column
        m["_path"] = "fixture"
        with self.assertRaises(E.M.MappingError):
            E.resolve_date_mode(Config(**{**self.cfg.__dict__, "job_change_date_column": "JOB_DETL_HIST_EFF_DT"}), m)


if __name__ == "__main__":
    unittest.main()
