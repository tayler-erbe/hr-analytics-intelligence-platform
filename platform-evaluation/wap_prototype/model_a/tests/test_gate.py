"""Person-level scores are off by default (protocol 6.3) and the restricted folder stays restricted."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from wap_prototype.model_a import config as C
from wap_prototype.model_a import governance_bridge as G
from wap_prototype.model_a.tests import common


class TestGate(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.synthetic = self.tmp / "synthetic" / "manifest.json"
        self.synthetic.parent.mkdir()
        self.synthetic.write_text(json.dumps({"synthetic": True}))
        self.real = self.tmp / "real" / "manifest.json"
        self.real.parent.mkdir()
        self.real.write_text(json.dumps({"synthetic": False}))

    def test_closed_by_default(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(C.PERSON_LEVEL_ENV, None)
            ok, why = G.person_level_gate(self.synthetic)
        self.assertFalse(ok)
        self.assertIn("disabled", why)

    def test_env_alone_is_not_enough_on_real_data(self):
        with mock.patch.dict(os.environ, {C.PERSON_LEVEL_ENV: "1"}):
            ok, why = G.person_level_gate(self.real, approval_file=self.tmp / "no_approval.json")
        self.assertFalse(ok)
        self.assertIn("approval", why)

    def test_env_plus_synthetic_opens_for_audit_demonstration(self):
        with mock.patch.dict(os.environ, {C.PERSON_LEVEL_ENV: "1"}):
            ok, why = G.person_level_gate(self.synthetic)
        self.assertTrue(ok)
        self.assertIn("SYNTHETIC", why)

    def test_env_plus_complete_approval_opens(self):
        rec = {k: {"name": "x", "date": "2027-01-01", "reference": "r"} for k in G.REQUIRED_SIGNOFFS}
        f = self.tmp / "approval.json"
        f.write_text(json.dumps(rec))
        with mock.patch.dict(os.environ, {C.PERSON_LEVEL_ENV: "1"}):
            self.assertTrue(G.person_level_gate(self.real, approval_file=f)[0])
        rec["illinois_human_resources"] = {"name": "", "date": ""}
        f.write_text(json.dumps(rec))
        with mock.patch.dict(os.environ, {C.PERSON_LEVEL_ENV: "1"}):
            ok, why = G.person_level_gate(self.real, approval_file=f)
        self.assertFalse(ok)
        self.assertIn("illinois_human_resources", why)


class TestPipelineKeepsPersonLevelOff(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = common.small_run("a")

    def test_no_person_scores_written_and_gate_recorded_closed(self):
        out = self.ctx["out"]
        self.assertFalse((out / "restricted" / "person_scores.parquet").exists())
        summary = json.loads((out / "aggregate_summary.json").read_text())
        self.assertFalse(summary["person_level_gate"]["open"])

    def test_nothing_person_level_outside_restricted(self):
        out = self.ctx["out"]
        for p in list(out.glob("*.csv")) + list((out / "star").glob("*.csv")):
            head = p.read_text(encoding="utf-8").splitlines()[0].lower()
            for bad in ("person_id", "position_id", "pers_id", "posn", "sex", "race", "birth"):
                self.assertNotIn(bad, head, f"{p.name}: {bad}")

    def test_restricted_folder_is_gitignored_and_bannered(self):
        res = self.ctx["out"] / "restricted"
        self.assertEqual((res / ".gitignore").read_text(), "*\n!.gitignore\n")
        self.assertTrue((res / "intermediate" / "README_RESTRICTED.txt").exists())
        self.assertTrue((res / "intermediate" / "predictions.parquet").exists())
        self.assertTrue((res / "label_audit_sheet.csv").exists())
        self.assertTrue((res / "fairness_groups.csv").exists())


if __name__ == "__main__":
    unittest.main()
