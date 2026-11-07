"""Two runs on the same input give identical content hashes."""
from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from wap_prototype import publish as P
from wap_prototype.config import Config
from wap_prototype.tests.common import full_run


class TestReproducibility(unittest.TestCase):
    def test_second_run_has_identical_hashes_and_row_counts(self):
        first = full_run()["manifest"]
        tmp = Path(tempfile.mkdtemp(prefix="wap_repro_"))
        try:
            man = P.run(Config.from_env(output_dir=tmp))
            man.pop("_source").close()
            for t, v in first["tables"].items():
                self.assertEqual(v["rows"], man["tables"][t]["rows"], t)
                self.assertEqual(v["csv_sha256"], man["tables"][t]["csv_sha256"], t)
            self.assertEqual(first["event_counts"], man["event_counts"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_manifest_records_config_and_counts(self):
        man = full_run()["manifest"]
        self.assertEqual(man["config"]["job_change_date_column"], "JOB_DETL_EFF_DT")
        self.assertEqual(man["config"]["min_cell_size"], 10)
        self.assertIn("person_period_features", man["tables"])
        self.assertTrue(man["tables"]["person_period_features"]["location"].startswith("outputs/restricted/"))
        self.assertTrue(man["tables"]["transition_events"]["location"].startswith("outputs/restricted/"))


if __name__ == "__main__":
    unittest.main()
