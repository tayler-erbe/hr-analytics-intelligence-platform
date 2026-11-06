"""Unit tests for the ERP conversion-readiness toolkit (synthetic data only).

    python -m unittest discover -s erp_readiness/tests -v        # from platform-evaluation/

Covers: rule-catalog contract, SQL portability lint (+ sqlglot parse for Snowflake/Databricks/
Oracle when installed), exact detection of every injected defect, no false positives on clean
seeds, determinism, reconciliation tolerance logic and the offline dashboard.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import compile_rules  # noqa: E402
import generate_synthetic  # noqa: E402
import reconcile  # noqa: E402
import run_checks  # noqa: E402
from common import DEFAULT_SEED, DIALECTS, HTML_OUT, load_catalog, render_sql  # noqa: E402

N = 1500
_TMP = None
_CACHE = {}


def setUpModule():
    global _TMP
    _TMP = Path(tempfile.mkdtemp(prefix="erp_ready_test_"))


def tearDownModule():
    shutil.rmtree(_TMP, ignore_errors=True)


def build(label, scale, seed=DEFAULT_SEED):
    """Generate + check once per (label, scale, seed); returns (manifest, summary)."""
    key = (label, scale, seed)
    if key not in _CACHE:
        root = _TMP / f"s{seed}"
        out = generate_synthetic.generate(label, scale, seed, N, out_root=root)
        summary = run_checks.run(label, data_dir=out, out_dir=root / "runs" / label)
        _CACHE[key] = (json.loads((out / "manifest.json").read_text()), summary, out)
    return _CACHE[key]


class CatalogContract(unittest.TestCase):
    def setUp(self):
        self.cat = load_catalog()

    def test_at_least_30_rules_with_required_fields(self):
        rules = self.cat["rules"]
        self.assertGreaterEqual(len(rules), 30)
        ids = [r["id"] for r in rules]
        self.assertEqual(len(ids), len(set(ids)), "duplicate rule ids")
        for r in rules:
            for f in ("id", "name", "domain", "severity", "owner", "population", "rationale", "target", "remediation", "sql"):
                self.assertTrue(r.get(f), f"{r['id']} missing {f}")
            self.assertIn(r["severity"], self.cat["severity"])
            self.assertIn(r["domain"], self.cat["domains"])
            self.assertIn(r["population"], self.cat["populations"])
            self.assertTrue(r["target"].get("workday") and r["target"].get("oracle"), r["id"])
            for c in r.get("cites", []):
                self.assertIn(c, self.cat["sources"], f"{r['id']} cites unknown source {c}")

    def test_every_domain_has_rules(self):
        used = {r["domain"] for r in self.cat["rules"]}
        self.assertEqual(used, set(self.cat["domains"]))

    def test_portability_lint(self):
        forbidden = {
            r"\bLIMIT\b": "LIMIT", r"\bTOP\s+\d": "TOP", r"\bQUALIFY\b": "QUALIFY", r"\bILIKE\b": "ILIKE",
            r"::": "'::' cast", r"IS\s+(NOT\s+)?DISTINCT\s+FROM": "IS DISTINCT FROM", r"\bEXCEPT\b": "EXCEPT",
            r"\bMINUS\b": "MINUS", r"(FROM|JOIN)\s+\w+\s+AS\s+\w+": "AS table alias (Oracle)",
            r"\b(DATEADD|DATE_ADD|DATEDIFF|DATE_TRUNC|STRFTIME|TO_CHAR|NVL|IFF|IFNULL)\s*\(": "dialect function",
            r"\bINTERVAL\b": "INTERVAL arithmetic",
        }
        blocks = [(r["id"], r["sql"]) for r in self.cat["rules"]] + list(self.cat["helpers"].items()) \
            + list(self.cat["populations"].items())
        for rid, sql in blocks:
            for pat, name in forbidden.items():
                self.assertIsNone(re.search(pat, sql, re.I), f"{rid}: non-portable construct {name}")

    def test_render_all_dialects(self):
        for d in DIALECTS:
            for r in self.cat["rules"]:
                out = render_sql(r["sql"], d)
                self.assertNotIn("{{", out)
                if d == "oracle":
                    self.assertNotIn("RECURSIVE", out.upper())

    def test_sqlglot_parses_compiled_rules(self):
        try:
            import sqlglot
        except ImportError:
            self.skipTest("sqlglot not installed (optional)")
        compiled = compile_rules.compile_all()
        for d in ("snowflake", "databricks", "oracle"):
            for r in self.cat["rules"]:
                self.assertIn(f"-- {r['id']} [", compiled[d])
                sqlglot.parse_one(render_sql(r["sql"], d), read=None)       # parses as ANSI
                sqlglot.transpile(render_sql(r["sql"], d), read=None, write=d)


class DefectDetection(unittest.TestCase):
    def test_each_injected_defect_detected_exactly(self):
        manifest, summary, _ = build("M1", 1.0)
        found = summary["_entity_ids"]
        expected = manifest["expected"]
        self.assertEqual(set(expected), set(found), "every rule should have at least one injected defect at scale 1.0")
        for rid in sorted(found):
            with self.subTest(rule=rid):
                self.assertEqual(sorted(found[rid]), expected[rid])

    def test_every_defect_type_injected(self):
        manifest, _, _ = build("M1", 1.0)
        kinds = {i["defect"] for i in manifest["injections"]}
        self.assertEqual(kinds, set(generate_synthetic.BASE_COUNTS))

    def test_required_defect_families_map_to_rules(self):
        """The defect families named in the brief each have a detecting rule."""
        manifest, _, _ = build("M1", 1.0)
        need = {"job_overlap": "J01", "emp_overlap": "E01", "job_gap": "J02", "emp_gap": "E02",
                "orphan_position": "S01", "job_without_position": "S04", "multi_primary": "J04",
                "job_fte_gt1": "J06", "term_with_active_job": "E03", "class_not_sucss": "C01",
                "pay_below_min": "C02", "dup_person_exact": "P01", "future_job_row": "J08",
                "org_mismatch": "S06", "missing_supervisor": "O01", "reporting_cycle": "O03"}
        by_kind = {}
        for i in manifest["injections"]:
            by_kind.setdefault(i["defect"], set()).update(i["expected"])
        for kind, rid in need.items():
            self.assertIn(rid, by_kind[kind], kind)

    def test_other_seed_also_exact(self):
        manifest, summary, _ = build("M1", 1.0, seed=7)
        for rid, ids in summary["_entity_ids"].items():
            self.assertEqual(sorted(ids), manifest["expected"].get(rid, []), rid)

    def test_partial_scale_exact(self):
        manifest, summary, _ = build("M3", 0.25)
        for rid, ids in summary["_entity_ids"].items():
            self.assertEqual(sorted(ids), manifest["expected"].get(rid, []), rid)


class NoFalsePositives(unittest.TestCase):
    def test_clean_seed_has_zero_findings(self):
        for seed in (DEFAULT_SEED, 99):
            with self.subTest(seed=seed):
                manifest, summary, _ = build("CLEAN", 0.0, seed=seed)
                self.assertEqual(manifest["expected"], {})
                failing = {k: v[:3] for k, v in summary["_entity_ids"].items() if v}
                self.assertEqual(failing, {}, f"false positives: {failing}")
                self.assertEqual(summary["overall_score"], 100.0)
                self.assertTrue(all(d["gate"] == "ready" for d in summary["domains"]))


class Determinism(unittest.TestCase):
    @staticmethod
    def digest(folder: Path) -> dict:
        return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(folder.glob("*.parquet"))} | \
               {"manifest": hashlib.sha256((folder / "manifest.json").read_bytes()).hexdigest()}

    def test_same_seed_same_bytes(self):
        a = generate_synthetic.generate("M1", 1.0, DEFAULT_SEED, N, out_root=_TMP / "detA")
        b = generate_synthetic.generate("M1", 1.0, DEFAULT_SEED, N, out_root=_TMP / "detB")
        self.assertEqual(self.digest(a), self.digest(b))

    def test_same_input_same_register(self):
        _, s1, out = build("M1", 1.0)
        s2 = run_checks.run("M1", data_dir=out, out_dir=_TMP / "rerun")
        strip = lambda s: {k: v for k, v in s.items() if k != "data_dir"}  # noqa: E731
        self.assertEqual(strip(s1), strip(s2))

    def test_different_seed_differs(self):
        a = generate_synthetic.generate("X", 1.0, 1, N, out_root=_TMP / "detC")
        b = generate_synthetic.generate("X", 1.0, 2, N, out_root=_TMP / "detD")
        self.assertNotEqual(self.digest(a)["T_JOB_DETL_HIST.parquet"], self.digest(b)["T_JOB_DETL_HIST.parquet"])

    def test_synthetic_ids_only(self):
        manifest, summary, _ = build("M1", 1.0)
        self.assertTrue(manifest["synthetic"])
        for r in summary["register"]:
            for e in r["examples"]:
                if e["entity_type"] in ("person", "job", "pay"):
                    self.assertRegex(e["entity_id"], r"^S[PDF]\d{6}")


class Reconciliation(unittest.TestCase):
    def test_classify_tolerance_rules(self):
        c = reconcile.classify
        self.assertEqual(c(10, 9, 10, 0), "match")
        self.assertEqual(c(10, 9, 9, 0), "explained")
        self.assertEqual(c(10, 9, 8, 0), "unexplained")
        self.assertEqual(c(2.50, 2.50, 2.505, 0.01), "match")
        self.assertEqual(c(2.50, 2.0, 2.02, 0.01), "unexplained")
        self.assertEqual(c(1000, 900, 899.5, 0, rel_tol=0.001), "explained")
        self.assertEqual(c("100.00", "90.00", "100.00", 0.0), "match")

    def test_clean_reconciles_exactly(self):
        _, _, out = build("CLEAN", 0.0)
        r = reconcile.reconcile("CLEAN", data_dir=out, out_dir=_TMP / "recCLEAN")
        self.assertEqual(r["status"], "match")
        self.assertEqual(r["rejections"], [])
        for m in r["metrics"]:
            self.assertEqual(m["legacy_total"], m["target_total"], m["metric"])

    def test_m1_unexplained_only_from_planted_converter_bug(self):
        _, _, out = build("M1", 1.0)
        r = reconcile.reconcile("M1", data_dir=out, out_dir=_TMP / "recM1")
        self.assertEqual(r["status"], "unexplained")
        bad = {e["key1"] for e in r["exceptions"] if e["status"] == "unexplained"}
        self.assertEqual(bad, {"U111", "UNMAPPED"})
        rules = {x["rule_id"] for x in r["rejections"]}
        self.assertTrue({"S04", "E03", "J06", "C01", "C04", "O06", "P05", "Y03"} <= rules)

    def test_without_bug_every_gap_is_explained(self):
        _, _, out = build("M1", 1.0)
        r = reconcile.reconcile("M1-nobug", data_dir=out, out_dir=_TMP / "recM1nb")
        self.assertIn(r["status"], ("explained", "match"))
        self.assertFalse([e for e in r["exceptions"] if e["status"] == "unexplained"])


class Dashboard(unittest.TestCase):
    def test_offline_html(self):
        if not HTML_OUT.exists():
            self.skipTest("run erp_readiness/run_all.py first")
        html = HTML_OUT.read_text(encoding="utf-8")
        self.assertNotRegex(html, r"<(script|link|img)[^>]+(src|href)=\"https?://")
        self.assertNotIn("fetch(", html)
        self.assertIn("prefers-color-scheme: dark", html)
        self.assertIn('name="viewport"', html)
        self.assertIn("Synthetic data only", html)
        data = json.loads(re.search(r'<script id="data" type="application/json">(.*?)</script>', html, re.S).group(1).replace("<\\/", "</"))
        self.assertEqual([c["label"] for c in data["cycles"]], ["M1", "M2", "M3", "M4"])
        self.assertEqual(len(data["rules"]), len(load_catalog()["rules"]))


if __name__ == "__main__":
    unittest.main()
