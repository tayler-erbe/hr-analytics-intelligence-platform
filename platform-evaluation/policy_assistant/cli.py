"""Command line: crawl | build | ask | eval | demo.

    python -m policy_assistant.cli crawl                 # network; polite; <= 300 pages
    python -m policy_assistant.cli build                 # chunks.jsonl + DuckDB
    python -m policy_assistant.cli ask "How many paid holidays ...?" [--json] [--embeddings lsa]
    python -m policy_assistant.cli eval [--embeddings lsa]
    python -m policy_assistant.cli demo                  # output/policy_assistant/index.html
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import textwrap

from . import config


def _retriever(embeddings: str | None):
    from .build import load_or_build
    from .retrieval import LsaEmbedder, Retriever, embedder_from_env
    emb = LsaEmbedder() if embeddings == "lsa" else (None if embeddings == "off" else embedder_from_env())
    return Retriever(load_or_build(), embedder=emb)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="policy_assistant")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("crawl")
    c.add_argument("--max-pages", type=int, default=config.MAX_PAGES)
    sub.add_parser("build")
    a = sub.add_parser("ask")
    a.add_argument("question")
    a.add_argument("--json", action="store_true")
    a.add_argument("--embeddings", choices=["off", "lsa"], default=None)
    e = sub.add_parser("eval")
    e.add_argument("--embeddings", choices=["off", "lsa"], default="off")
    e.add_argument("--out", default=None)
    sub.add_parser("demo")
    args = ap.parse_args(argv)

    if args.cmd == "crawl":
        from .crawler import crawl
        print(json.dumps(crawl(min(args.max_pages, config.MAX_PAGES)), indent=2))
    elif args.cmd == "build":
        from .build import build
        print(json.dumps(build(), indent=2))
    elif args.cmd == "ask":
        from .answerer import answer
        from .llm import LocalLLMSynthesizer
        retr = _retriever(args.embeddings)
        ans = answer(args.question, retr, synthesizer=LocalLLMSynthesizer.from_env())
        if args.json:
            print(json.dumps(ans.to_dict(), indent=2))
            return
        print(f"[{ans.status.upper()}: {ans.reason}] {ans.message}")
        if ans.summary:
            print("\n" + textwrap.fill(ans.summary, 100))
        if ans.synthesis and ans.synthesis.get("used"):
            print(f"\nLocal LLM synthesis ({ans.synthesis['model']}):\n" + ans.synthesis["text"])
        for ci in ans.citations:
            print(f"\n[{ci.n}] {' > '.join(ci.heading_path)}\n    {ci.cite_url}\n    bm25={ci.bm25} coverage={ci.coverage}")
            print(textwrap.indent(textwrap.fill(ci.text[:600], 96), "    "))
        for r in ans.related:
            print(f"  (related page, not an answer) {r['title']}: {r['url']}")
    elif args.cmd == "eval":
        from .eval.score import main as score_main
        score_main(["--embeddings", args.embeddings] + (["--out", args.out] if args.out else []))
    elif args.cmd == "demo":
        from .demo import build_demo
        print(json.dumps(build_demo(), indent=2))


if __name__ == "__main__":
    sys.exit(main())
