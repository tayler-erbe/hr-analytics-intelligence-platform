"""Tests for the job-evolution model.

    cd platform-evaluation && python -m unittest discover -s job_evolution/tests -v

1. Harmonization correctness on small fixtures (task matching thresholds, and/or
   folding, technology renames, taxonomy link cardinality, crosswalk chaining).
2. No future leakage: features computed from a panel truncated at the origin equal
   features from the full panel; every backtest fold trains only on labels
   published by its origin; AEI is absent from primary feature sets.
3. Reproducibility: deterministic matching and model fits; re-running model.py on
   copies of its inputs reproduces the stored report and predictions byte for byte
   (set JE_SKIP_SLOW=1 to skip that ~90 s check); stored artifacts match manifest.json.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

from common import ART, PROTOCOL, REL_INDEX, RELEASES, ROOT, sha256_file  # noqa: E402
from harmonize import (chain_to_target, is_rename, link_pairs, match_examples, match_tasks,  # noqa: E402
                       normalize_task)


class TestHarmonization(unittest.TestCase):
    def test_and_or_editorial_rewrite_is_unchanged(self):
        a = "Direct and coordinate an organization's financial and budget activities."
        b = "Direct or coordinate an organization's financial or budget activities."
        self.assertEqual(normalize_task(a), normalize_task(b))
        m = match_tasks([("1", a)], [("1", b)])
        self.assertEqual((m["n_unchanged"], m["n_added"], m["n_removed"], m["task_churn"]), (1, 0, 0, 0.0))

    def test_match_tasks_fixture(self):
        old = [("1", "Prepare payroll reports for management."),
               ("2", "Maintain employee records in filing systems."),
               ("3", "Answer telephone calls from applicants."),
               ("4", "Schedule interviews with job candidates.")]
        new = [("1", "Prepare payroll reports for management review."),        # minor edit, same id
               ("22", "Maintain employee records in electronic filing systems and HRIS."),  # revised, new id
               ("5", "Configure workflows in the human resources information system."),    # added
               ("4", "Schedule interviews with job candidates.")]              # unchanged
        m = match_tasks(old, new)
        self.assertEqual(m["n_unchanged"], 1)
        self.assertEqual(m["n_minor_edit"], 1)
        self.assertEqual(m["n_revised"], 1)
        self.assertEqual(m["removed"], ["3"])
        self.assertEqual(m["added"], ["5"])
        self.assertAlmostEqual(m["task_churn"], (1 + 1 + 2 * 1) / 8)

    def test_same_id_rewritten_beyond_threshold_is_remove_plus_add(self):
        m = match_tasks([("9", "Operate forklifts in the warehouse.")],
                        [("9", "Negotiate vendor contracts for software licences.")])
        self.assertEqual((m["n_removed"], m["n_added"], m["n_revised"]), (1, 1, 0))
        self.assertEqual(m["task_churn"], 1.0)

    def test_thresholds_are_protocol_values(self):
        self.assertGreater(PROTOCOL["task_minor_edit_min"], PROTOCOL["task_revision_min"])
        m = match_tasks([], [])
        self.assertIsNone(m["task_churn"])

    def test_technology_renames_are_not_adoption(self):
        m = match_examples(["Adobe Systems Adobe Acrobat", "SAP software", "SAS", "Microsoft Excel"],
                           ["Adobe Acrobat", "SAP", "SAS statistical software", "Microsoft Excel", "Python"])
        self.assertEqual(m["added"], ["Python"])
        self.assertEqual(m["removed"], [])
        self.assertEqual(len(m["renamed"]), 3)
        self.assertFalse(is_rename("microsoft excel", "microsoft word")[0])

    def test_link_pairs_cardinality(self):
        xw = [("A", "A1"), ("B", "B1"), ("B", "B2"), ("C", "M"), ("D", "M"), ("E", "E")]
        links = {(a, b): t for a, b, t in link_pairs({"A", "B", "C", "D", "E"}, {"A1", "B1", "B2", "M", "E"}, xw)}
        self.assertEqual(links[("A", "A1")], "one_to_one")
        self.assertEqual(links[("B", "B1")], "split")
        self.assertEqual(links[("C", "M")], "merge")
        self.assertEqual(links[("E", "E")], "identity")
        same = link_pairs({"X", "Y"}, {"Y", "Z"}, None)
        self.assertEqual(same, [("Y", "Y", "identity")])

    def test_chain_to_target(self):
        codes = {"2006": {"a"}, "2009": {"a", "b"}, "2010": {"c"}, "2019": {"c1", "c2"}}
        xw = {("2006", "2009"): [("a", "a")], ("2009", "2010"): [("a", "c"), ("b", "c")],
              ("2010", "2019"): [("c", "c1"), ("c", "c2")]}
        m = chain_to_target(codes, xw, ["2006", "2009", "2010", "2019"])
        self.assertEqual(m["2006"]["a"], {"c1", "c2"})
        self.assertEqual(m["2009"]["b"], {"c1", "c2"})

    def test_release_taxonomy_matches_built_inventory(self):
        inv = json.loads((ART / "release_inventory.json").read_text())
        for r in inv["releases"]:
            self.assertGreaterEqual(r["taxonomy_code_overlap"][r["taxonomy"]], 0.99, r["release"])

    def test_detected_updates_agree_with_onet_longitudinal_file(self):
        v = json.loads((ART / "update_validation.json").read_text())
        self.assertGreater(v["tasks"]["agreement_rate"], 0.97)
        self.assertGreater(v["gwa"]["agreement_rate"], 0.97)


class TestNoFutureLeakage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import model
        cls.M = model
        cls.states, cls.trans, cls.gwa, cls.aei = model.load_panel()

    def test_features_identical_on_truncated_panel(self):
        M = self.M
        for origin in ("16.0", "21.0", "26.0"):
            o = REL_INDEX[origin]
            st_t = {k: {r: s for r, s in v.items() if REL_INDEX[r] <= o} for k, v in self.states.items()}
            tr_t = {k: [t for t in v if REL_INDEX[t["rel"]] <= o] for k, v in self.trans.items()}
            gw_t = {k: v for k, v in self.gwa.items() if REL_INDEX[k[1]] <= o}
            n = 0
            for lid in sorted(self.states)[::7]:
                full = M.features_at(lid, o, self.states, self.trans, self.gwa, self.aei)
                trunc = M.features_at(lid, o, st_t, tr_t, gw_t, self.aei)
                self.assertEqual(full, trunc, (lid, origin))
                n += full is not None
            self.assertGreater(n, 50)

    def test_folds_train_only_on_published_labels(self):
        rep = json.loads((ART / "backtest_report.json").read_text())
        for kind in ("task", "tech"):
            self.assertTrue(rep[kind]["all_leakage_checks_ok"])
            for c in rep[kind]["leakage_checks"]:
                self.assertLessEqual(REL_INDEX[c["max_train_event_release"]], REL_INDEX[c["origin"]])
                self.assertLess(REL_INDEX[c["max_train_origin"]], REL_INDEX[c["origin"]])

    def test_fold_filter_logic(self):
        rows = [{"origin": 3, "event_idx": 5}, {"origin": 3, "event_idx": 7}, {"origin": 6, "event_idx": 6},
                {"origin": 5, "event_idx": 6}]
        T = 6
        train = [r for r in rows if r["origin"] < T and r["event_idx"] <= T]
        self.assertEqual(train, [rows[0], rows[3]])

    def test_aei_only_in_expost_variant(self):
        self.assertNotIn("aei_exposure_expost", self.M.feature_names(False))
        self.assertIn("aei_exposure_expost", self.M.feature_names(True))

    def test_threshold_uses_training_rows_only(self):
        rows = [{"lineage_id": "a", "event_idx": 1, "y_value": 0.0},
                {"lineage_id": "b", "event_idx": 1, "y_value": 0.1},
                {"lineage_id": "c", "event_idx": 2, "y_value": 0.3}]
        self.assertAlmostEqual(self.M.threshold_from(rows), float(__import__("numpy").quantile([0, .1, .3], .67)))


class TestReproducibility(unittest.TestCase):
    def test_matching_deterministic(self):
        old = [(str(i), f"Review budget item number {i} for compliance.") for i in range(20)]
        new = [(str(i + 100), f"Review budget item number {i} for policy compliance.") for i in range(20)]
        self.assertEqual(match_tasks(old, new), match_tasks(old, new))

    def test_artifacts_match_manifest(self):
        man = json.loads((ART / "manifest.json").read_text())
        for rel, h in man["outputs"].items():
            self.assertEqual(sha256_file(ROOT / rel), h, rel)
        for rel, h in man["inputs"].items():
            self.assertEqual(sha256_file(ROOT / rel), h, rel)

    @unittest.skipIf(os.environ.get("JE_SKIP_SLOW"), "slow end-to-end rerun skipped")
    def test_model_rerun_is_byte_identical(self):
        with tempfile.TemporaryDirectory() as tmp:
            for f in ("occ_state.parquet", "transitions.parquet"):
                shutil.copy(ART / f, Path(tmp) / f)
            env = dict(os.environ, JE_ART=tmp)
            r = subprocess.run([sys.executable, str(HERE / "model.py")], cwd=HERE, env=env,
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr[-2000:])
            for f in ("backtest_report.json", "predictions_latest.parquet", "timing_model.json"):
                self.assertEqual(sha256_file(Path(tmp) / f), sha256_file(ART / f), f)

    def test_explorer_is_offline(self):
        html = (ROOT / "output" / "job_evolution" / "job_evolution_explorer.html").read_text(encoding="utf-8")
        for bad in ("<script src", "<link rel=\"stylesheet\"", "fetch(", "XMLHttpRequest", "@import"):
            self.assertNotIn(bad, html)

    def test_no_person_level_fields(self):
        import pyarrow.parquet as pq
        keys = set()

        def walk(x):
            if isinstance(x, dict):
                for k, v in x.items():
                    keys.add(str(k).lower())
                    walk(v)
            elif isinstance(x, list):
                for v in x:
                    walk(v)
        walk(json.loads((ART / "watchlist.json").read_text()))
        for f in ART.glob("*.parquet"):
            keys |= {c.lower() for c in pq.read_schema(f).names}
        banned = {"employee_id", "uin", "netid", "name", "salary", "date_of_birth", "person_id", "edw_pers_id"}
        self.assertEqual(keys & banned, set())


if __name__ == "__main__":
    unittest.main()
