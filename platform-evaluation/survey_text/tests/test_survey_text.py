"""Tests for survey_text (all on SYNTHETIC data).

Run from platform-evaluation/:  python -m unittest discover -s survey_text/tests -v
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
PKG = HERE.parent
sys.path.insert(0, str(PKG))

import analytics  # noqa: E402
import coding  # noqa: E402
import generate_synthetic as gen  # noqa: E402
import llm_coder  # noqa: E402
import pipeline  # noqa: E402
import quotes  # noqa: E402
import redact  # noqa: E402
import scoring  # noqa: E402

TMP: Path
DATA: Path
PUB_A: dict
PUB_B: dict


def setUpModule():
    global TMP, DATA, PUB_A, PUB_B
    TMP = Path(tempfile.mkdtemp(prefix="survey_text_test_"))
    DATA = TMP / "data"
    gen.main(seed=gen.DEFAULT_SEED, out=DATA)
    PUB_A = pipeline.build(DATA, TMP / "artA", TMP / "a.html", use_presidio=False)
    PUB_B = pipeline.build(DATA, TMP / "artB", TMP / "b.html", use_presidio=False)


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


def raw_comments(data_dir: Path) -> dict[str, str]:
    out = {}
    for f in ("ws_export.csv", "exit_export.csv"):
        for r in pipeline.read_qualtrics(data_dir / f):
            out[r["ResponseId"]] = r["Q_comment"]
    return out


def common_words(texts):
    cb = coding.load_codebook()
    lex = {w for t in cb["themes"] for w in t["lexicon"] if re.fullmatch(r"[a-z ]+", w)}
    return redact.corpus_common_words(texts) | lex


class TestRedaction(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.texts = raw_comments(DATA)
        cls.manifest = json.loads((DATA / "decoy_manifest.json").read_text())["decoys"]
        cls.roster = redact.load_roster(DATA / "roster_names.csv")
        cls.R = redact.Redactor(cls.roster, use_presidio=False)

    def _assert_all_caught(self, R, layers=None):
        self.assertGreater(len(self.manifest), 100)
        for rid, decoys in self.manifest.items():
            out = R.redact(self.texts[rid], layers=layers).text
            for d in decoys:
                self.assertNotIn(d["value"], out, f"{d['type']} decoy leaked in {rid}")
                if d["type"] == "PERSON":  # surname alone must not survive either
                    self.assertNotIn(d["value"].split()[-1], out, f"surname leaked in {rid}")

    def test_regex_cue_roster_catch_every_decoy(self):
        self._assert_all_caught(self.R)

    def test_regex_layer_catches_all_structured_pii(self):
        for rid, decoys in self.manifest.items():
            out = self.R.redact(self.texts[rid], layers=["regex"]).text
            for d in decoys:
                if d["type"] in ("EMAIL", "PHONE", "UIN"):
                    self.assertNotIn(d["value"], out)

    def test_specific_formats(self):
        cases = ["Reach me at jane.q.doe+hr@example.edu please", "call (217) 555-0142 today",
                 "call 217.555.0199", "call +1 217 555 0101", "UIN 657654321 here", "SSN 123-45-6789",
                 "My name is Perrin Oakhurst and I care", "Ask Dr. Galloway about it",
                 "my supervisor Zelda Whitlock is unfair", "see https://intranet.example.edu/x"]
        leaks = ["jane.q.doe", "555-0142", "555.0199", "555 0101", "657654321", "123-45-6789",
                 "Oakhurst", "Galloway", "Whitlock", "intranet"]
        R = redact.Redactor([], use_presidio=False)
        for text, leak in zip(cases, leaks):
            self.assertNotIn(leak, R.redact(text).text, text)

    def test_no_false_positives_on_clean_synthetic_comments(self):
        clean = [t for rid, t in self.texts.items() if rid not in self.manifest and t]
        hits = sum(bool(self.R.redact(t).spans) for t in clean)
        self.assertEqual(hits, 0)

    def test_presidio_layer_if_installed(self):
        R = redact.Redactor(self.roster, use_presidio=True, common_words=common_words(self.texts.values()))
        if R.presidio is None:
            self.skipTest("Presidio or a spaCy English model is not installed")
        self._assert_all_caught(R)
        sample = [t for rid, t in sorted(self.texts.items()) if rid not in self.manifest and t][:300]
        self.assertLessEqual(sum(bool(R.redact(t).spans) for t in sample), 3, "Presidio over-redacts clean text")

    def test_published_outputs_contain_no_decoys_or_ids(self):
        blob = (TMP / "artA" / "published" / "survey_insights.json").read_text() + (TMP / "a.html").read_text()
        for decoys in self.manifest.values():
            for d in decoys:
                self.assertNotIn(d["value"], blob)
        self.assertNotRegex(blob, r"R_SYN(?:WS|EX)\d")

    def test_store_holds_only_redacted_text(self):
        import duckdb
        con = duckdb.connect(str(TMP / "artA" / "survey_text.duckdb"), read_only=True)
        rows = con.execute("SELECT comment_redacted FROM responses_redacted").fetchall()
        con.close()
        blob = "\n".join(r[0] for r in rows)
        for decoys in self.manifest.values():
            for d in decoys:
                self.assertNotIn(d["value"], blob)


class TestSuppression(unittest.TestCase):
    def test_enps_small_cell_and_complementary(self):
        recs = [{"g": "A", "score": 9}] * 50 + [{"g": "B", "score": 3}] * 30 + [{"g": "C", "score": 10}] * 4
        rows = {r["segment"]: r for r in analytics.enps_by(recs, "g", 10)}
        self.assertTrue(rows["C"]["suppressed"])
        self.assertIsNone(rows["C"]["n"])
        self.assertNotIn("enps", rows["C"])
        self.assertTrue(rows["B"]["suppressed"])  # complementary: next-smallest
        self.assertEqual(rows["B"]["reason"], "complementary")
        self.assertFalse(rows["A"]["suppressed"])

    def test_prevalence_masks_small_numerators(self):
        recs = [{"answered": 1, "themes": {"pay"} if i < 4 else {"workload"}} for i in range(40)]
        rows = {r["theme"]: r for r in analytics.prevalence(recs, ["pay", "workload", "ai_tools"], 10)}
        self.assertIsNone(rows["pay"]["count"])
        self.assertIsNone(rows["pay"]["share"])
        self.assertEqual(rows["workload"]["count"], 36)
        self.assertEqual(rows["ai_tools"]["count"], 0)

    def test_driver_needs_full_2x2(self):
        recs = [{"answered": 1, "themes": {"pay"}, "detractor": 1}] * 30 + \
               [{"answered": 1, "themes": {"pay"}, "detractor": 0}] * 5 + \
               [{"answered": 1, "themes": set(), "detractor": d} for d in [0, 1] * 40]
        self.assertTrue(analytics.drivers(recs, ["pay"], 10)[0]["suppressed"])

    def test_published_cells_respect_k(self):
        k = PUB_A["min_cell_size"]
        enps_rows = [r for key in ("by_unit", "by_role_family", "by_tenure_band", "overall_by_wave")
                     for r in PUB_A["enps"][key]]
        self.assertTrue(any(r["suppressed"] for r in enps_rows), "fixture should exercise suppression")
        for r in enps_rows:
            if r["suppressed"]:
                self.assertIsNone(r["n"])
                self.assertNotIn("enps", r)
            else:
                self.assertGreaterEqual(r["n"], k)
        for r in [x for v in PUB_A["prevalence"].values() for x in v] + PUB_A["exit_trend"]:
            c = r.get("count")
            self.assertTrue(c is None or c == 0 or c >= k, r)
        for r in PUB_A["unit_join"]:
            if not r["suppressed"]:
                self.assertTrue(r["exit_responses"] is None or r["exit_responses"] >= k)
        for r in PUB_A["drivers"]["relative_risk"]:
            self.assertTrue(r["n_mention"] is None or r["n_mention"] >= k)


class TestNoVerbatim(unittest.TestCase):
    def test_no_comment_shingles_in_published_outputs(self):
        texts = raw_comments(DATA)
        blob = " ".join(re.findall(r"[a-z']+", ((TMP / "artA" / "published" / "survey_insights.json").read_text()
                                                 + (TMP / "a.html").read_text()).lower()))
        shingles = set()
        for t in texts.values():
            w = re.findall(r"[a-z']+", t.lower())
            shingles.update(" ".join(w[i:i + 6]) for i in range(len(w) - 5))
        leaked = [s for s in shingles if s in blob]
        self.assertEqual(leaked, [], f"verbatim fragments published: {leaked[:5]}")
        self.assertEqual(PUB_A["quotes"]["approved"], [])
        self.assertGreater(PUB_A["quotes"]["status_counts"].get("pending", 0), 0)

    def test_only_human_approved_quotes_are_published(self):
        art = TMP / "artQ"
        shutil.copytree(TMP / "artA", art)
        import duckdb
        con = duckdb.connect(str(art / "survey_text.duckdb"), read_only=True)
        qid, text = con.execute("SELECT quote_id, redacted_text FROM quote_approval ORDER BY quote_id LIMIT 1").fetchall()[0]
        con.close()
        with self.assertRaises(ValueError):
            quotes.decide(art / "survey_text.duckdb", qid, "approved", "  ")
        quotes.decide(art / "survey_text.duckdb", qid, "approved", "Test Reviewer (synthetic)")
        pub = pipeline.build(DATA, art, None, use_presidio=False)
        self.assertEqual([q["quote_id"] for q in pub["quotes"]["approved"]], [qid])
        self.assertEqual(pub["quotes"]["approved"][0]["text"], text)


class TestReproducibility(unittest.TestCase):
    def test_generator_is_seeded(self):
        d1, d2, d3 = TMP / "g1", TMP / "g2", TMP / "g3"
        gen.main(seed=gen.DEFAULT_SEED, out=d1)
        gen.main(seed=gen.DEFAULT_SEED, out=d2)
        gen.main(seed=7, out=d3)
        for f in ("ws_export.csv", "exit_export.csv", "decoy_manifest.json", "gold/gold_sample.csv"):
            self.assertEqual((d1 / f).read_bytes(), (d2 / f).read_bytes(), f)
            self.assertEqual((d1 / f).read_bytes(), (DATA / f).read_bytes(), f)
        self.assertNotEqual((d1 / "ws_export.csv").read_bytes(), (d3 / "ws_export.csv").read_bytes())

    def test_pipeline_is_deterministic(self):
        a = (TMP / "artA" / "published" / "survey_insights.json").read_bytes()
        b = (TMP / "artB" / "published" / "survey_insights.json").read_bytes()
        self.assertEqual(hashlib.sha256(a).hexdigest(), hashlib.sha256(b).hexdigest())
        self.assertEqual((TMP / "a.html").read_bytes(), (TMP / "b.html").read_bytes())

    def test_dataset_shape_and_labels(self):
        ws = pipeline.read_qualtrics(DATA / "ws_export.csv")
        ex = pipeline.read_qualtrics(DATA / "exit_export.csv")
        self.assertEqual(len(ws), 3000)
        self.assertEqual(len(ex), 800)
        self.assertTrue(all(r["synthetic"] == "True" for r in ws + ex))
        self.assertTrue(all(0 <= int(r["Q_eNPS"]) <= 10 for r in ws))
        self.assertTrue(PUB_A["synthetic"])
        self.assertIn("SYNTHETIC", PUB_A["data_label"])


class TestLocalLLMInterface(unittest.TestCase):
    def setUp(self):
        self.cb = coding.load_codebook()
        self.R = redact.Redactor([], use_presidio=False)

    def test_off_by_default(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SURVEY_TEXT_LLM_ENABLED", None)
            c = llm_coder.LocalLLMCoder(self.cb, self.R)
            self.assertFalse(c.enabled)
            with self.assertRaises(llm_coder.LLMDisabled):
                c.code("pay is low")
        self.assertFalse(PUB_A["llm"]["enabled"])

    def test_refuses_non_loopback_hosts(self):
        bad = ["https://api.openai.com/v1", "http://10.0.0.5:8000/v1", "http://192.168.1.20/v1",
               "http://localhost.evil.example/v1", "http://localhost@evil.example/v1",
               "http://user:pw@127.0.0.1/v1", "http://127.0.0.1.nip.io/v1", "http://0.0.0.0:8000/v1",
               "http://[::ffff:8.8.8.8]/v1", "ftp://localhost/v1", "file:///etc/passwd", "http:///v1",
               "http://gpu-box.illinois.edu:8000/v1"]
        for url in bad:
            with self.assertRaises(llm_coder.RemoteEndpointRefused, msg=url):
                llm_coder.validate_endpoint(url)
            with self.assertRaises(llm_coder.RemoteEndpointRefused, msg=url):
                llm_coder.LocalLLMCoder(self.cb, self.R, endpoint=url, enabled=True)
        with mock.patch.dict(os.environ, {"SURVEY_TEXT_LLM_ENDPOINT": "https://example.com/v1"}):
            with self.assertRaises(llm_coder.RemoteEndpointRefused):
                llm_coder.LocalLLMCoder(self.cb, self.R)

    def test_accepts_loopback(self):
        for url in ["http://localhost:8000/v1", "http://127.0.0.1:11434/v1", "http://[::1]:8000/v1",
                    "https://127.0.0.2/v1", "http://LOCALHOST./v1"]:
            llm_coder.validate_endpoint(url)

    def test_round_trip_with_local_fake_server_sends_redacted_text_only(self):
        received = []

        class H(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                received.append(body)
                out = {"choices": [{"message": {"content": '{"themes": ["pay", "workload", "not_a_theme"]}'}}]}
                data = json.dumps(out).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *a):
                pass

        srv = HTTPServer(("127.0.0.1", 0), H)
        th = threading.Thread(target=srv.serve_forever, daemon=True)
        th.start()
        try:
            # a bogus proxy proves requests bypass HTTP(S)_PROXY
            with mock.patch.dict(os.environ, {"HTTP_PROXY": "http://10.255.255.1:9", "http_proxy": "http://10.255.255.1:9"}):
                c = llm_coder.LocalLLMCoder(self.cb, self.R, endpoint=f"http://127.0.0.1:{srv.server_port}/v1",
                                            enabled=True, timeout=5)
                got = c.code("Pay is low and we are short-staffed. Email me at pat.q@example.edu or 217-555-0100.")
        finally:
            srv.shutdown()
        self.assertEqual(got, {"pay", "workload"})
        self.assertEqual(c.dropped_labels, 1)
        sent = received[0]["messages"][1]["content"]
        self.assertNotIn("pat.q@example.edu", sent)
        self.assertNotIn("555-0100", sent)
        self.assertIn("[EMAIL]", sent)
        self.assertEqual(received[0]["temperature"], 0)


class TestScoring(unittest.TestCase):
    def test_kappa_and_prf(self):
        self.assertAlmostEqual(scoring.cohen_kappa([1, 1, 0, 0], [1, 1, 0, 0]), 1.0)
        self.assertAlmostEqual(scoring.cohen_kappa([1, 0, 1, 0], [0, 1, 0, 1]), -1.0)
        # textbook example: po=0.7, pe=0.5 -> 0.4
        a = [1] * 25 + [1] * 25 + [0] * 25 + [0] * 25
        b = [1] * 25 + [0] * 25 + [1] * 10 + [0] * 15 + [0] * 25
        a, b = a[:100], b[:100]
        k = scoring.cohen_kappa(a, b)
        po = sum(x == y for x, y in zip(a, b)) / 100
        pa, pb = sum(a) / 100, sum(b) / 100
        pe = pa * pb + (1 - pa) * (1 - pb)
        self.assertAlmostEqual(k, (po - pe) / (1 - pe))
        p, r, f = scoring.prf(8, 2, 2)
        self.assertAlmostEqual(p, 0.8)
        self.assertAlmostEqual(f, 0.8)

    def test_gold_reference_prefers_adjudicated(self):
        path = TMP / "gold_test.csv"
        with path.open("w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["ResponseId", "coder_id", "themes", "coded_on", "codebook_version"])
            w.writerow(["r1", "coder_A", "pay", "", "0.1"])
            w.writerow(["r1", "coder_B", "pay;workload", "", "0.1"])
            w.writerow(["r1", "ADJUDICATED", "workload", "", "0.1"])
            w.writerow(["r2", "coder_A", "", "", "0.1"])
            w.writerow(["r2", "coder_B", "", "", "0.1"])
        g = scoring.load_gold(path)
        ref = scoring.reference(g)
        self.assertEqual(ref["r1"], {"workload"})
        self.assertEqual(ref["r2"], set())
        s = scoring.score({"r1": {"workload"}, "r2": set()}, ref, ["pay", "workload"])
        self.assertEqual(s["micro"]["f1"], 1.0)
        self.assertEqual(scoring.inter_rater(g, ["pay"])["coders"], ["coder_A", "coder_B"])

    def test_evaluation_published_and_marked_simulated(self):
        ev = PUB_A["evaluation"]
        self.assertTrue(ev["simulated_gold"])
        self.assertEqual(ev["coders"]["lexicon_v0.1"]["n_responses"], 400)
        f1 = ev["coders"]["lexicon_v0.1"]["micro"]["f1"]
        self.assertTrue(0.5 < f1 < 1.0, f1)  # lexicon is imperfect even on its own synthetic data


if __name__ == "__main__":
    unittest.main()
