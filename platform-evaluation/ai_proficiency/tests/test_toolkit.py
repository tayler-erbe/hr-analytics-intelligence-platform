"""Tests for the rubric, tasks, YAML reader, badge rules, synthetic study and HTML.

Run from platform-evaluation/ai_proficiency/:
    python -m unittest discover -s tests -v
"""
import csv
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
PKG = HERE.parent
sys.path.insert(0, str(PKG))

import build_html  # noqa: E402
import rubric_io  # noqa: E402
import study  # noqa: E402
import synth  # noqa: E402


class YamlReader(unittest.TestCase):
    def test_matches_pyyaml_when_available(self):
        try:
            import yaml
        except ImportError:
            self.skipTest("PyYAML not installed; stdlib reader is the only reader")
        for p in (rubric_io.RUBRIC_PATH, rubric_io.TASKS_PATH):
            with p.open() as fh:
                self.assertEqual(rubric_io.load_yaml(p), yaml.safe_load(fh), p.name)

    def test_subset_features(self):
        text = ('a: 1\nb: "x: y"\nc: [p, "q, r", 2.5]\nd: {k: v, n: 3}\n'
                'e:\n  - one\n  - k: 1\n    m: two\nf:\n- top\ng: true\n')
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as fh:
            fh.write(text)
        self.assertEqual(rubric_io.load_yaml(fh.name), {
            "a": 1, "b": "x: y", "c": ["p", "q, r", 2.5], "d": {"k": "v", "n": 3},
            "e": ["one", {"k": 1, "m": "two"}], "f": ["top"], "g": True})


class Rubric(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = rubric_io.load_rubric()

    def test_dimensions(self):
        dims = self.r["dimensions"]
        self.assertTrue(6 <= len(dims) <= 8)
        keys = {d["key"] for d in dims}
        for k in ("task_framing", "constraints_format", "iteration", "verification", "data_sensitivity",
                  "human_in_the_loop", "tool_choice", "documentation_reuse"):
            self.assertIn(k, keys)
        for d in dims:
            self.assertEqual([lv["score"] for lv in d["levels"]], [1, 2, 3, 4])
            self.assertTrue(all(lv["examples"] for lv in d["levels"]))
            self.assertTrue(d["ihr_competencies"], d["id"])

    def test_tiers_and_competency_model(self):
        self.assertEqual(self.r["badges"]["order"], ["explorer", "catalyst", "practitioner"])
        self.assertEqual([t["name"] for t in self.r["program_tiers"]["staff"]], ["AI Explorer", "AI Catalyst", "AI Practitioner"])
        names = {c["name"] for c in self.r["ihr_competency_model"]["competencies"]}
        self.assertEqual(names, {"Digital Proficiency & Data Savviness", "Cognitive Flexibility"})

    def test_data_classes(self):
        ids = [c["id"] for c in self.r["data_classification"]["categories"]]
        self.assertEqual(ids, ["Public", "Internal", "Sensitive"])

    def test_classify_ladder_and_gates(self):
        all_ = lambda v: {d: v for d in rubric_io.dimension_ids(self.r)}  # noqa: E731
        self.assertEqual(rubric_io.classify(self.r, all_(4.0)), "Practitioner")
        # 2.5 everywhere: total 20 clears the Catalyst cut, but D5 2.5 misses the Catalyst gate (3.0)
        self.assertEqual(rubric_io.classify(self.r, all_(2.5)), "Explorer")
        s = all_(2.5); s["D5"] = 3.0
        self.assertEqual(rubric_io.classify(self.r, s), "Catalyst")
        self.assertEqual(rubric_io.classify(self.r, all_(1.0)), "Not yet")
        s = all_(4.0); s["D5"] = 1.0   # unsafe data handling: no badge at all, whatever the total
        self.assertEqual(rubric_io.classify(self.r, s), "Not yet")
        s = all_(4.0); s["D6"] = 2.0   # human-in-the-loop below Practitioner floor
        self.assertEqual(rubric_io.classify(self.r, s), "Catalyst")
        s = all_(2.0); s["D5"] = 2.0   # total 16: above Explorer cut, D5 meets Explorer floor only
        self.assertEqual(rubric_io.classify(self.r, s), "Explorer")
        self.assertEqual(rubric_io.classify(self.r, all_(2.0), {"explorer": 17.0}), "Not yet")


class Tasks(unittest.TestCase):
    def test_twelve_tasks_cover_roles(self):
        t = rubric_io.load_tasks()["tasks"]
        self.assertEqual(len(t), 12)
        fams = {x["role_family"] for x in t}
        self.assertTrue({"HR", "Finance", "Advising", "IT support", "Admin"} <= fams)
        for x in t:
            self.assertTrue(x["planted"] and x["auto_floor"], x["id"])

    def test_no_real_identifiers_in_materials(self):
        text = rubric_io.TASKS_PATH.read_text()
        self.assertIsNone(re.search(r"[\w.]+@[\w.]+\.\w+", text))
        self.assertIsNone(re.search(r"\b\d{9}\b", text))


class SyntheticStudy(unittest.TestCase):
    """Runs the full study in a temporary directory so the published data and
    report under data/ and artifacts/ are not overwritten by the test run."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls._saved = (synth.DATA, study.ARTIFACTS, study.REPORT_PATH)
        synth.DATA = Path(cls._tmp.name)
        study.ARTIFACTS, study.REPORT_PATH = Path(cls._tmp.name), Path(cls._tmp.name) / "r.json"
        cls.rep = study.run(regenerate=True)

    @classmethod
    def tearDownClass(cls):
        synth.DATA, study.ARTIFACTS, study.REPORT_PATH = cls._saved
        cls._tmp.cleanup()

    def test_all_planted_properties_recovered(self):
        failed = [c for c in self.rep["recovery_checks"] if not c["pass"]]
        self.assertEqual(failed, [])

    def test_shape(self):
        k = json.loads((synth.DATA / "known_properties.json").read_text())
        self.assertEqual(self.rep["calibration"]["n_artifacts"], k["n_calibration"])
        self.assertAlmostEqual(self.rep["double_scoring"]["double_rate"], 0.20, delta=0.01)
        self.assertEqual(sum(self.rep["badges"]["counts_recommended"].values()), 150)

    def test_reliability_in_planted_range(self):
        cal = self.rep["calibration"]["total_score"]
        self.assertGreater(cal["ICC(2,k)"], 0.85)
        self.assertGreater(cal["ICC(2,k)"], cal["ICC(2,1)"])
        b = self.rep["badges"]
        self.assertGreater(b["decision_consistency_replication_calibrated_raters_synthetic"]["p0"],
                           b["decision_consistency_replication_synthetic"]["p0"])

    def test_deterministic(self):
        a = (synth.DATA / "ratings_long.csv").read_bytes()
        synth.generate(out_dir=synth.DATA)
        self.assertEqual(a, (synth.DATA / "ratings_long.csv").read_bytes())

    def test_no_person_like_columns(self):
        with (synth.DATA / "ratings_long.csv").open() as fh:
            cols = next(csv.reader(fh))
        for bad in ("name", "email", "netid", "uin", "gender", "race", "age"):
            self.assertNotIn(bad, cols)


class Html(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = build_html.build(Path(tempfile.mkdtemp()) / "t.html")
        cls.html = cls.path.read_text()

    def test_offline(self):
        self.assertIsNone(re.search(r"""(src|href)\s*=\s*["']https?:""", self.html))
        for bad in ("fetch(", "XMLHttpRequest", "sendBeacon", "WebSocket", "@import", "<link "):
            self.assertNotIn(bad, self.html)
        self.assertIn("connect-src 'none'", self.html)

    def test_theme_and_mobile(self):
        self.assertIn("prefers-color-scheme: dark", self.html)
        self.assertIn(':root[data-theme="dark"]', self.html)
        self.assertIn('name="viewport"', self.html)

    def test_payload_embedded(self):
        m = re.search(r'<script id="data" type="application/json">(.*?)</script>', self.html, re.S)
        data = json.loads(m.group(1))
        self.assertEqual(len(data["tasks"]["tasks"]), 12)
        self.assertIn("recovery_checks", data["report"])


if __name__ == "__main__":
    unittest.main()
