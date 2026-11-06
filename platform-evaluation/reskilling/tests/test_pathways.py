"""Tests for reskilling/build_pathways.py and render_explorer.py.

Run from platform-evaluation/:  python -m unittest discover -s reskilling/tests -v
"""
import hashlib
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
RESKILL = HERE.parent
sys.path.insert(0, str(RESKILL))

import build_pathways  # noqa: E402
import render_explorer  # noqa: E402

# Column-name tokens that would indicate person-level data. Matched on whole
# underscore-separated tokens so that e.g. "element_name" is not flagged.
PERSON_TOKENS = {"employee", "employees", "person", "uin", "netid", "email", "ssn", "dob", "birth",
                 "age", "gender", "sex", "race", "ethnicity", "zip", "address", "phone", "salary",
                 "rating_of", "performance", "supervisor", "manager_id", "emplid", "banner", "pidm"}
ROLE_KEYS = {"role_id", "onetsoc_code", "view"}


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


class PathwaysTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.a = Path(cls.tmp.name) / "a"
        cls.b = Path(cls.tmp.name) / "b"
        build_pathways.build(cls.a)
        build_pathways.build(cls.b)
        cls.bundle = json.loads((cls.a / "pathways.json").read_text(encoding="utf-8"))
        cls.reg = cls.bundle["meta"]["provenance_registry"]
        cls.html = Path(cls.tmp.name) / "page.html"
        data = render_explorer.compact(cls.bundle)
        cls.html.write_text(render_explorer.PAGE.replace("__DATA__", json.dumps(data, sort_keys=True)), encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    # -- determinism -------------------------------------------------------
    def test_byte_identical_rebuild(self):
        fa = sorted(p.name for p in self.a.iterdir())
        self.assertEqual(fa, sorted(p.name for p in self.b.iterdir()))
        for name in fa:
            self.assertEqual(sha(self.a / name), sha(self.b / name), name)

    def test_no_wall_clock_in_outputs(self):
        text = (self.a / "pathways.json").read_text(encoding="utf-8") + (self.a / "manifest.json").read_text()
        self.assertIsNone(re.search(r"20\d\d-\d\d-\d\dT\d\d:\d\d", text), "timestamp leaked into outputs")

    # -- no individual-level data -----------------------------------------
    def test_no_person_level_columns(self):
        for f in self.a.glob("*.parquet"):
            cols = pq.read_schema(f).names
            for c in cols:
                self.assertFalse(set(c.lower().split("_")) & PERSON_TOKENS, f"{f.name}.{c}")
            self.assertTrue(set(cols) & ROLE_KEYS, f"{f.name} has no role-level key")

    def test_grain_is_role(self):
        roles = self.bundle["roles"]
        self.assertEqual(len(roles), len({r["role_id"] for r in roles}))
        self.assertTrue(all(r["role_type"] in ("onet_occupation", "sucss_class") for r in roles))
        self.assertIn("No person-level data", self.bundle["meta"]["grain"])

    # -- provenance ---------------------------------------------------------
    def _check_prov(self, ref, what):
        self.assertIsInstance(ref, str, what)
        p = self.reg.get(ref)
        self.assertIsNotNone(p, f"{what}: unresolved provenance {ref}")
        self.assertEqual(p["method"], build_pathways.PROTOCOL["version"])
        self.assertTrue(p["sources"], what)
        for s in p["sources"]:
            self.assertTrue(s.get("source_id") and s.get("source_vintage"), what)

    def test_every_recommendation_has_provenance(self):
        n = 0
        for code, p in self.bundle["profiles"].items():
            for key in ("tasks", "skills", "activities", "adjacent", "learning_themes"):
                for item in p[key]:
                    self._check_prov(item["provenance"], f"{code}.{key}"); n += 1
                    for g in item.get("top_gaps", []):
                        self._check_prov(g["provenance"], f"{code}.gap"); n += 1
            self._check_prov(p["competency"]["provenance"], f"{code}.competency")
            for a in p["competency"]["activities"]:
                self._check_prov(a["provenance"], f"{code}.competency.activity"); n += 1
        for r in self.bundle["roles"] + self.bundle["family_summary"]:
            self._check_prov(r["provenance"], "role/family")
        self.assertGreater(n, 1000)

    def test_ai_usage_cites_metric_and_release(self):
        for p in self.bundle["profiles"].values():
            for t in p["tasks"]:
                srcs = self.reg[t["provenance"]]["sources"]
                self.assertTrue(any(s.get("metric") == "task_penetration" and s["source_vintage"] == "labor_market_impacts" for s in srcs))
                self.assertIn(t["ai_usage_band"], ("high", "low", "no_record"))
                if t["ai_usage_band"] == "high":
                    self.assertGreaterEqual(t["aei_task_penetration"], build_pathways.PROTOCOL["high_usage_penetration_min"])

    def test_parquet_provenance_columns_nonempty(self):
        for f in self.a.glob("*.parquet"):
            t = pq.read_table(f)
            self.assertIn("provenance", t.column_names, f.name)
            for v in t.column("provenance").to_pylist():
                self.assertTrue(json.loads(v)["sources"], f.name)

    def test_learning_themes_are_onet_elements(self):
        import duckdb
        names = {r[0] for r in duckdb.sql(
            f"SELECT DISTINCT element_name FROM '{build_pathways.CONTRACT / 'onet_element_rating.parquet'}'").fetchall()}
        for p in self.bundle["profiles"].values():
            for th in p["learning_themes"]:
                self.assertIn(th["theme"], names)

    # -- caveats ------------------------------------------------------------
    def test_caveat_flags_present(self):
        cav = self.bundle["meta"]["caveats"]
        for k in ("observed_usage_not_displacement", "unreviewed_mapping", "not_for_individual_decisions"):
            self.assertIn(k, cav)
        for r in self.bundle["roles"]:
            self.assertIn("not_for_individual_decisions", r["caveat_keys"])
            self.assertIn("observed_usage_not_displacement", r["caveat_keys"])
            if r["role_type"] == "sucss_class":
                self.assertEqual(r["mapping_status"], "unreviewed_lexical_candidate")
                self.assertIn("unreviewed_mapping", r["flags"])
                self.assertIn("unreviewed_mapping", r["caveat_keys"])

    def test_html_caveats_and_budget(self):
        html = self.html.read_text(encoding="utf-8")
        for s in ("Observed usage is not displacement", "SUCSS mappings are unreviewed", "Not for individual decisions", "HB 3773"):
            self.assertIn(s, html)
        self.assertNotRegex(html, r"<script[^>]+src=|<link[^>]+href=\"http")
        self.assertLess(self.html.stat().st_size, render_explorer.MAX_BYTES)

    def test_rule_language(self):
        ev = build_pathways.eval_rule
        self.assertTrue(ev("a >= 3 and b >= 4", {"a": 3, "b": 4}))
        self.assertFalse(ev("a >= 3 and b >= 4", {"a": 3, "b": None}))
        with self.assertRaises(ValueError):
            ev("__import__('os')", {})


if __name__ == "__main__":
    unittest.main()
