"""The offline demo's JS engine must reproduce the Python answerer, and the HTML must stay < 8 MB.

Uses node when available (skipped otherwise). The real-corpus parity check runs only when the
crawled corpus has been built (it is gitignored), so a fresh clone still passes offline.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from policy_assistant import config
from policy_assistant.answerer import answer
from policy_assistant.demo import ENGINE_JS, build_demo, demo_payload
from policy_assistant.retrieval import Retriever
from policy_assistant.tests.test_pipeline import toy_chunks

NODE = shutil.which("node")

NODE_SCRIPT = r"""
const fs = require('fs');
const api = require(process.argv[2]);
const data = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
const qs = JSON.parse(fs.readFileSync(process.argv[4], 'utf8'));
const eng = new api.Engine(data);
const out = qs.map(q => { const a = eng.answer(q);
  return {status: a.status, reason: a.reason, urls: a.citations.map(c => c.url),
          tokens: eng.tokenize(q), picked: (a.picked || []).map(p => p.s)}; });
process.stdout.write(JSON.stringify(out));
"""


def run_node(chunks, questions, min_score=None):
    payload = demo_payload(chunks)
    if min_score is not None:
        payload["config"]["min_score"] = min_score
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        (td / "data.json").write_text(json.dumps(payload))
        (td / "qs.json").write_text(json.dumps(questions))
        (td / "run.js").write_text(NODE_SCRIPT)
        r = subprocess.run([NODE, str(td / "run.js"), str(ENGINE_JS), str(td / "data.json"), str(td / "qs.json")],
                           capture_output=True, text=True, timeout=300)
        if r.returncode:
            raise AssertionError(r.stderr)
        return json.loads(r.stdout)


def python_view(a):
    from policy_assistant.answerer import best_sentences  # noqa: F401
    return {"status": a.status, "reason": a.reason, "urls": [c.url for c in a.citations]}


@unittest.skipUnless(NODE, "node not installed")
class TestParity(unittest.TestCase):
    QUESTIONS = ["When must new employees make benefit elections?", "What is the campus holiday schedule?",
                 "Should I retire now?", "What is the parking permit price?", "Is it legal to deny my leave?",
                 "Which employees should be laid off?", "", "AI Ready Leader track for supervisors"]

    def test_toy_parity(self):
        chunks = toy_chunks()
        r = Retriever(chunks)
        js = run_node(chunks, self.QUESTIONS, min_score=1.0)
        from policy_assistant.text import tokenize
        for q, j in zip(self.QUESTIONS, js):
            a = answer(q, r, min_score=1.0)
            self.assertEqual(python_view(a), {k: j[k] for k in ("status", "reason", "urls")}, q)
            self.assertEqual(tokenize(q), j["tokens"], q)

    @unittest.skipUnless(config.CHUNKS_PATH.exists(), "crawled corpus not built")
    def test_real_corpus_eval_parity(self):
        from policy_assistant.chunker import load_chunks
        from policy_assistant.eval.score import load_questions
        chunks = load_chunks()
        qs = [q["question"] for q in load_questions()]
        r = Retriever(chunks)
        js = run_node(chunks, qs)
        mism = []
        for q, j in zip(qs, js):
            p = python_view(answer(q, r))
            if p != {k: j[k] for k in ("status", "reason", "urls")}:
                mism.append((q, p, j))
        self.assertEqual(mism, [])


class TestDemoBuild(unittest.TestCase):
    def test_html_size_and_contents(self):
        with tempfile.TemporaryDirectory() as td:
            info = build_demo(Path(td), chunks=toy_chunks())
            html = (Path(td) / "index.html").read_text()
            self.assertLess(info["bytes"], 8 * 1024 * 1024)
            self.assertIn("prefers-color-scheme:dark", html)
            self.assertIn('name="viewport"', html)
            self.assertNotIn("__DATA__", html)
            self.assertNotIn("/*__ENGINE__*/", html)
            self.assertNotIn("http://", html.split("<script>")[0].replace("http://www.w3.org", ""))  # no external CSS
            self.assertNotRegex(html, r"<script[^>]+src=")   # nothing loaded from the network

    @unittest.skipUnless((config.OUTPUT_DIR / "index.html").exists(), "demo not built")
    def test_built_demo_under_budget(self):
        self.assertLess((config.OUTPUT_DIR / "index.html").stat().st_size, 8 * 1024 * 1024)


if __name__ == "__main__":
    unittest.main()
