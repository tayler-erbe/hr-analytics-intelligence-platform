"""Tests for the AI Adoption Impact Scorecard.

Run from platform-evaluation/:
    python -m unittest discover -s ai_adoption/tests -v
"""
import json
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
PKG = HERE.parent
sys.path.insert(0, str(PKG))

import build_page  # noqa: E402
import contract as C  # noqa: E402
import metrics as M  # noqa: E402
import privacy as P  # noqa: E402
import synthesize as syn  # noqa: E402

K = C.K_MIN_CELL
PERSON_PATTERNS = [re.compile(r"SYN-P\d+"), re.compile(r"\b(REG|ATT|BDG|SCR|RSP|EVT)\d{7}\b"),
                   re.compile(r"\bUC\d{5}\b"), re.compile(r"\bR0\d\b")]


def _walk(o, path="$"):
    if isinstance(o, dict):
        for k, v in o.items():
            yield path, k, v, o
            yield from _walk(v, f"{path}.{k}")
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from _walk(v, f"{path}[{i}]")


_FIX = {}


def setUpModule():
    """Build the fixtures once for every test class (synthesis + metrics take a few seconds each)."""
    tmp = tempfile.TemporaryDirectory()
    root = Path(tmp.name)
    f = {"tmp": tmp, "dir_a": root / "a", "dir_b": root / "b", "dir_c": root / "c", "dir_min": root / "min"}
    f["man_a"] = syn.write(syn.synthesize(syn.DEFAULT_SEED), f["dir_a"], syn.DEFAULT_SEED)
    f["man_b"] = syn.write(syn.synthesize(syn.DEFAULT_SEED), f["dir_b"], syn.DEFAULT_SEED)
    f["man_c"] = syn.write(syn.synthesize(syn.DEFAULT_SEED + 1), f["dir_c"], syn.DEFAULT_SEED + 1)
    syn.write(syn.synthesize(syn.DEFAULT_SEED, telemetry=False, talent=False), f["dir_min"], syn.DEFAULT_SEED)
    f["out_a"] = M.build(f["dir_a"])
    f["out_b"] = M.build(f["dir_b"])
    f["out_min"] = M.build(f["dir_min"])
    f["html"] = build_page.render(f["out_a"])
    _FIX.update(f)


def tearDownModule():
    _FIX["tmp"].cleanup()


class _Fixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        for k, v in _FIX.items():
            setattr(cls, k, v)


class TestReproducibility(_Fixture):
    def test_same_seed_same_bytes(self):
        self.assertEqual({k: v["sha256"] for k, v in self.man_a["tables"].items()},
                         {k: v["sha256"] for k, v in self.man_b["tables"].items()})

    def test_different_seed_differs(self):
        self.assertNotEqual(self.man_a["tables"]["registration"]["sha256"], self.man_c["tables"]["registration"]["sha256"])

    def test_metrics_deterministic(self):
        self.assertEqual(json.dumps(self.out_a, sort_keys=True, default=str), json.dumps(self.out_b, sort_keys=True, default=str))

    def test_page_deterministic(self):
        self.assertEqual(self.html, build_page.render(self.out_b))


class TestContract(_Fixture):
    def test_tables_match_contract(self):
        for name, spec in C.TABLES.items():
            t = pq.read_table(self.dir_a / f"{name}.parquet")
            self.assertEqual(t.column_names, list(spec["columns"]), name)

    def test_contract_violation_rejected(self):
        bad = Path(self.tmp.name) / "bad"
        shutil.copytree(self.dir_a, bad)
        t = pq.read_table(bad / "badge.parquet").drop(["applied_complete"])
        pq.write_table(t, bad / "badge.parquet")
        with self.assertRaises(M.ContractError):
            M.build(bad)

    def test_unknown_enum_rejected(self):
        bad = Path(self.tmp.name) / "bad_enum"
        shutil.copytree(self.dir_a, bad)
        t = pq.read_table(bad / "attendance.parquet")
        import pyarrow as pa
        col = t.column("modality").to_pylist()
        col[0] = "carrier_pigeon"
        t = t.set_column(t.column_names.index("modality"), "modality", pa.array(col))
        pq.write_table(t, bad / "attendance.parquet")
        with self.assertRaises(M.ContractError):
            M.build(bad)

    def test_tier_names_follow_public_series(self):
        self.assertEqual([C.TIERS[t]["label"] for t in C.PATHS["staff"]], ["AI Explorer", "AI Catalyst", "AI Practitioner"])
        self.assertEqual([C.TIERS[t]["label"] for t in C.PATHS["leader"]], ["AI Ready Leaders", "AI Adaptive Leaders", "AI Forward Strategies"])

    def test_population_size(self):
        self.assertEqual(self.out_a["funnel"]["all"][0]["n"], syn.TOTAL_HEADCOUNT)


class TestSuppression(_Fixture):
    def test_audit_passes(self):
        self.assertEqual(P.audit(self.out_a), [])
        self.assertEqual(P.audit(self.out_min), [])

    def test_no_published_count_below_k(self):
        """Independent of audit(): every count-like field is None, 0 or >= k."""
        seen = 0
        for path, k, v, _ in _walk(self.out_a):
            if (k == "n" or k.endswith("_n")) and v is not None:
                seen += 1
                self.assertTrue(v == 0 or v >= K, f"{path}.{k} = {v}")
        self.assertGreater(seen, 200)
        # crosstab cells and totals too
        xt = self.out_a["heatmap"]["unit_by_role"]
        for v in [c for row in xt["cells"] for c in row] + xt["row_totals"] + xt["col_totals"] + [xt["grand"]]:
            self.assertTrue(v is None or v == 0 or v >= K, v)

    def test_rates_and_means_need_k(self):
        for path, k, v, parent in _walk(self.out_a):
            if k in ("rate", "mean", "per_100_py", "estimate") and v is not None and "n" in parent:
                self.assertIsNotNone(parent["n"], path)
                self.assertGreaterEqual(parent["n"], K, path)
                if parent.get("num_n") is not None:
                    self.assertGreaterEqual(parent["num_n"], K, path)

    def test_suppression_actually_happens(self):
        self.assertGreater(self.out_a["meta"]["suppressed_values"], 0)
        xt = self.out_a["heatmap"]["unit_by_role"]
        self.assertGreater(xt["primary_suppressed"], 0)

    def test_crosstab_not_recoverable(self):
        xt = self.out_a["heatmap"]["unit_by_role"]
        self.assertEqual(P.recoverable_cells(xt), [])

    def test_complementary_suppression_random_tables(self):
        rng = np.random.default_rng(0)
        for trial in range(300):
            r, c = int(rng.integers(1, 7)), int(rng.integers(1, 7))
            T = rng.choice([0, 1, 2, 5, 9, 10, 15, 40, 300], size=(r, c), p=[.1, .1, .1, .1, .1, .1, .15, .15, .1])
            pub = P.complementary_suppress(T)
            flat = [x for row in pub["cells"] for x in row]
            for v, orig in zip(flat, T.ravel()):
                self.assertTrue(v is None or v == orig)
                self.assertFalse(v is not None and 0 < v < K)
                if 0 < orig < K:
                    self.assertIsNone(v)
            for v in pub["row_totals"] + pub["col_totals"] + [pub["grand"]]:
                self.assertFalse(v is not None and 0 < v < K)
            self.assertEqual(P.recoverable_cells(pub), [], f"trial {trial}: {T.tolist()} -> {pub}")

    def test_primitives(self):
        self.assertIsNone(P.count(3))
        self.assertEqual(P.count(0), 0)
        self.assertEqual(P.count(10), 10)
        self.assertEqual(P.rate(4, 100)["rate"], None)   # numerator below k
        self.assertEqual(P.rate(20, 9)["n"], None)       # denominator below k
        self.assertEqual(P.rate(20, 100)["rate"], 0.2)
        self.assertIsNone(P.mean([1.0] * 9)["mean"])
        ci = P.bootstrap_mean_ci(np.arange(50, dtype=float), np.random.default_rng(1))
        self.assertLessEqual(ci["lo"], ci["mean"])
        self.assertLessEqual(ci["mean"], ci["hi"])

    def test_audit_catches_leaks(self):
        self.assertTrue(P.audit({"x": {"n": 3}}))
        self.assertTrue(P.audit({"x": {"num_n": 7}}))
        self.assertTrue(P.audit({"x": {"n": None, "rate": 0.4}}))
        self.assertTrue(P.audit({"person_key": "a"}))
        self.assertTrue(P.audit({"label": "SYN-P000123"}))
        self.assertTrue(P.audit({"rows": list(range(1000))}))
        with self.assertRaises(RuntimeError):
            build_page.render({"meta": {}, "cell": {"n": 4}})


class TestNoPersonLevelOutput(_Fixture):
    def test_no_identifier_keys_or_values(self):
        text = json.dumps(self.out_a)
        for _, k, _, _ in _walk(self.out_a):
            self.assertNotIn(k, C.FORBIDDEN_OUTPUT_KEYS)
        for pat in PERSON_PATTERNS:
            self.assertIsNone(pat.search(text), pat.pattern)

    def test_html_has_no_person_level_data(self):
        for pat in PERSON_PATTERNS:
            self.assertIsNone(pat.search(self.html), pat.pattern)
        for col in ("person_key", "submitter_person_key", "rater_id", "response_id"):
            self.assertNotIn(col, self.html)
        self.assertNotIn("http://", self.html.replace("http://www.w3.org/2000/svg", ""))
        self.assertNotIn("https://", self.html)

    def test_no_long_lists(self):
        def lens(o):
            if isinstance(o, list):
                yield len(o)
                for v in o:
                    yield from lens(v)
            elif isinstance(o, dict):
                for v in o.values():
                    yield from lens(v)
        self.assertLess(max(lens(self.out_a)), 100)

    def test_published_file_matches_privacy(self):
        pub = PKG / "data" / "published" / "scorecard.json"
        if pub.exists():
            self.assertEqual(P.audit(json.loads(pub.read_text())), [])


class TestFunnelAndModel(_Fixture):
    def test_funnel_monotonic(self):
        for out in (self.out_a, self.out_min):
            for track, stages in out["funnel"].items():
                vals = [s["n"] for s in stages if s["n"] is not None]
                self.assertEqual(vals, sorted(vals, reverse=True), track)
                self.assertGreaterEqual(len(vals), 5)

    def test_funnel_tracks_add_up(self):
        f = self.out_a["funnel"]
        for i, s in enumerate(f["all"]):
            a, b = f["staff"][i]["n"], f["leader"][i]["n"]
            if None not in (s["n"], a, b):
                self.assertEqual(s["n"], a + b, s["stage"])

    def test_tier_counts_nested(self):
        for t in self.out_a["tiers"]["tiers"]:
            seq = [t["registered_n"], t["started_n"], t["core_n"]] + ([t["applied_n"]] if t["has_applied"] else []) + [t["badged_n"]]
            vals = [v for v in seq if v is not None]
            self.assertEqual(vals, sorted(vals, reverse=True), t["tier"])

    def test_data_quality_clean_on_synthetic(self):
        self.assertEqual(self.out_a["meta"]["data_quality"]["badges_without_required_completion"], 0)
        self.assertEqual(self.out_a["meta"]["data_quality"]["badges_above_entry_without_lower_badge"], 0)

    def test_optional_inputs(self):
        self.assertIsNone(self.out_min["telemetry"])
        self.assertIsNone(self.out_min["talent"])
        self.assertFalse(self.out_min["meta"]["telemetry_included"])
        self.assertIn("not connected", build_page.render(self.out_min).split("<script id=\"data\"")[1])
        self.assertIsNotNone(self.out_a["telemetry"])
        self.assertIsNotNone(self.out_a["talent"])

    def test_did_is_labelled_non_causal(self):
        d = self.out_a["did"]
        self.assertIn("NOT a causal estimate", d["caveat"])
        self.assertLessEqual(d["did"]["lo"], d["did"]["estimate"])
        self.assertLessEqual(d["did"]["estimate"], d["did"]["hi"])
        self.assertIn("synthetic_validation", d)
        # the naive pre/post (which includes campus-wide growth) should overstate the built-in effect
        self.assertGreater(d["naive_pre_post_early"], d["synthetic_validation"]["true_effect"])

    def test_synthetic_label_everywhere(self):
        self.assertTrue(self.out_a["meta"]["synthetic"])
        self.assertIn("SYNTHETIC", self.out_a["meta"]["data_label"])
        self.assertIn("Synthetic demonstration data", self.html)


if __name__ == "__main__":
    unittest.main()
