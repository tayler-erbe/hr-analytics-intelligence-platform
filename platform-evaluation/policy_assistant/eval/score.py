"""Deterministic scorer. No LLM grading: gold URLs and expected behaviour are fixed in questions.json.

Metrics
* retrieval hit@k (answerable questions): a gold URL is among the top-k retrieved passages,
  regardless of whether the answerer chose to answer.
* answer hit@k (answerable): status == answer AND a gold URL is among the first k cited passages.
* abstention precision / recall, treating "abstain" as the positive class over all questions.
* unsafe answers: questions that must be refused (policy categories) or are unanswerable but were answered.
* over-abstention: answerable questions that were abstained.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from .. import config
from ..answerer import answer
from ..build import load_or_build
from ..crawler import normalize_url
from ..retrieval import LsaEmbedder, Retriever

QUESTIONS = Path(__file__).with_name("questions.json")


def load_questions(path: Path = QUESTIONS) -> list[dict]:
    return json.loads(path.read_text())["questions"]


def _norm(u: str) -> str:
    return normalize_url(u).rstrip("/").lower()


def score(questions: list[dict], retr: Retriever, ks=(1, 3, 5)) -> dict:
    rows = []
    for q in questions:
        t0 = time.perf_counter()
        ans = answer(q["question"], retr)
        ms = (time.perf_counter() - t0) * 1000
        retrieved = [h.chunk["url"] for h in retr.search(q["question"], k=max(ks))]
        gold = {_norm(u) for u in q.get("gold_urls", [])}
        r_rank = next((i + 1 for i, u in enumerate(retrieved) if _norm(u) in gold), None)
        cited = ans.cited_urls()
        a_rank = next((i + 1 for i, u in enumerate(cited) if _norm(u) in gold), None) if ans.status == "answer" else None
        rows.append({"id": q["id"], "expect": q["expect"], "category": q.get("category", ""),
                     "status": ans.status, "reason": ans.reason, "retrieval_rank": r_rank, "answer_rank": a_rank,
                     "top_bm25": ans.trace.get("top_bm25"), "top_coverage": ans.trace.get("top_coverage"),
                     "cited_urls": cited, "latency_ms": round(ms, 1)})
    ans_rows = [r for r in rows if r["expect"] == "answer"]
    abs_rows = [r for r in rows if r["expect"] == "abstain"]
    n_a = max(1, len(ans_rows))
    m = {"n_questions": len(rows), "n_answerable": len(ans_rows), "n_abstain_expected": len(abs_rows),
         "retrieval_mode": retr.mode}
    for k in ks:
        m[f"retrieval_hit@{k}"] = round(sum(1 for r in ans_rows if r["retrieval_rank"] and r["retrieval_rank"] <= k) / n_a, 3)
        m[f"answer_hit@{k}"] = round(sum(1 for r in ans_rows if r["answer_rank"] and r["answer_rank"] <= k) / n_a, 3)
    mrr = sum(1 / r["retrieval_rank"] for r in ans_rows if r["retrieval_rank"]) / n_a
    m["retrieval_mrr@5"] = round(mrr, 3)
    tp = sum(1 for r in rows if r["status"] == "abstain" and r["expect"] == "abstain")
    fp = sum(1 for r in rows if r["status"] == "abstain" and r["expect"] == "answer")
    fn = sum(1 for r in rows if r["status"] == "answer" and r["expect"] == "abstain")
    m["abstention_precision"] = round(tp / (tp + fp), 3) if tp + fp else None
    m["abstention_recall"] = round(tp / (tp + fn), 3) if tp + fn else None
    m["unsafe_answers"] = fn
    m["over_abstentions"] = fp
    m["answered_wrong_source"] = sum(1 for r in ans_rows if r["status"] == "answer" and not r["answer_rank"])
    m["policy_refusals_correct"] = sum(1 for r in abs_rows if r["category"] != "out_of_scope" and r["status"] == "abstain")
    m["median_latency_ms"] = sorted(r["latency_ms"] for r in rows)[len(rows) // 2]
    return {"metrics": m, "rows": rows}


def to_markdown(res: dict) -> str:
    m = res["metrics"]
    lines = [f"# Policy assistant eval ({m['retrieval_mode']})", "",
             "| metric | value |", "|---|---|"] + [f"| {k} | {v} |" for k, v in m.items()] + [
             "", "| id | expect | status | reason | retrieval rank | answer rank | top bm25 | coverage |",
             "|---|---|---|---|---|---|---|---|"]
    for r in res["rows"]:
        lines.append(f"| {r['id']} | {r['expect']} | {r['status']} | {r['reason']} | {r['retrieval_rank'] or '-'} | "
                     f"{r['answer_rank'] or '-'} | {r['top_bm25']} | {r['top_coverage']} |")
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--embeddings", choices=["off", "lsa"], default="off")
    ap.add_argument("--out", default=None, help="results basename (default eval/results_<mode>)")
    ap.add_argument("--questions", default=str(QUESTIONS), help="question file (default eval/questions.json)")
    a = ap.parse_args(argv)
    retr = Retriever(load_or_build(), embedder=LsaEmbedder() if a.embeddings == "lsa" else None)
    qpath = Path(a.questions)
    res = score(load_questions(qpath), retr)
    tag = "" if qpath.resolve() == QUESTIONS.resolve() else qpath.stem + "_"
    base = Path(a.out) if a.out else Path(__file__).with_name(f"results_{tag}{retr.mode.replace('+', '_')}")
    base.with_suffix(".json").write_text(json.dumps(res, indent=2))
    base.with_suffix(".md").write_text(to_markdown(res))
    print(json.dumps(res["metrics"], indent=2))
    for r in res["rows"]:
        flag = "" if (r["status"] == r["expect"] and (r["expect"] == "abstain" or r["answer_rank"])) else "  <-- miss"
        print(f"{r['id']:>4} {r['expect']:<7} {r['status']:<7} {r['reason']:<22} ret@{r['retrieval_rank']} ans@{r['answer_rank']}{flag}")


if __name__ == "__main__":
    main()
