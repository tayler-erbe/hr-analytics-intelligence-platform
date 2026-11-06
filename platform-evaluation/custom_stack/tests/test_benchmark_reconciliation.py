"""The same compiler reproduces the FROZEN benchmark v1.0 workforce answers.

Reads benchmark/fixtures read-only and checks their manifest hashes first.
"""
import hashlib
import json
import unittest

import _bootstrap

from custom_stack.semantic.engine import Engine
from custom_stack.semantic.model import load_all


class BenchmarkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = load_all()["benchmark_workforce"]
        cls.eng = Engine(cls.model, _bootstrap.BENCHMARK_FIXTURES)

    @classmethod
    def tearDownClass(cls):
        cls.eng.close()

    def v(self, plan):
        return self.eng.query(plan)[1]["rows"]

    def test_fixture_hashes_match_frozen_manifest(self):
        manifest = json.loads((_bootstrap.PLATFORM_EVAL / "benchmark" / "manifest.json").read_text())
        hashes = {f["path"]: f["sha256"] for f in manifest["files"]}
        for name in ("appointments", "positions"):
            rel = f"benchmark/fixtures/{name}.jsonl"
            got = hashlib.sha256((_bootstrap.PLATFORM_EVAL / rel).read_bytes()).hexdigest()
            self.assertEqual(got, hashes[rel], rel)

    def test_current_workforce(self):
        self.assertEqual(self.v({"metric": "wf_headcount"}), [[3]])
        self.assertEqual(self.v({"metric": "wf_appointment_count"}), [[4]])
        self.assertEqual(self.v({"metric": "wf_filled_positions"}), [[4]])
        self.assertAlmostEqual(self.v({"metric": "wf_fte"})[0][0], 2.5, delta=1e-9)
        self.assertEqual(self.v({"metric": "wf_vacant_positions"}), [[1]])

    def test_earlier_known_fte(self):
        rows = self.v({"metric": "wf_fte", "filters": [{"dimension": "knowledge_basis", "op": "eq", "value": "as_known_2026_10_31"}]})
        self.assertAlmostEqual(rows[0][0], 2.75, delta=1e-9)

    def test_department_split_uses_effective_assignment(self):
        self.assertEqual(self.v({"metric": "wf_headcount", "dimensions": ["department"]}), [["T1", 1], ["T2", 2]])
        self.assertEqual(self.v({"metric": "wf_appointment_count", "dimensions": ["department"]}), [["T1", 2], ["T2", 2]])
        fte = dict(self.v({"metric": "wf_fte", "dimensions": ["department"]}))
        self.assertAlmostEqual(fte["T1"], 1.0, delta=1e-9)
        self.assertAlmostEqual(fte["T2"], 1.5, delta=1e-9)

    def test_knowledge_bases_never_summed(self):
        rows = self.v({"metric": "wf_fte", "dimensions": ["knowledge_basis"]})
        self.assertEqual(len(rows), 2)  # grouped: shown side by side, not added


if __name__ == "__main__":
    unittest.main()
