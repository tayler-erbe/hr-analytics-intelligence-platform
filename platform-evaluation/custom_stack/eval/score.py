"""Score NL question answering against eval/questions.yaml.

Custom stack (runs the deterministic planner end to end):
  python -m custom_stack.eval.score [--data-dir DIR] [--out results.json]

Any other system (Cortex Analyst, Genie, ...) from recorded answers:
  python -m custom_stack.eval.score --external answers.jsonl --system cortex_analyst

External answers are JSON lines, one per question id (see
external_answers_template.jsonl):
  {"id": "Q01", "status": "answer|clarify|abstain|error", "columns": [...],
   "rows": [[...]], "sql": "...", "run_id": "...", "reviewer": "...", "notes": "..."}
`status` is assigned by a HUMAN reviewer from the vendor transcript (did it
ask a clarifying question, decline, or return a result?). No model grades
another model. Rows are the vendor's full-precision result set exported from
the same data snapshot; they are compared to the reference rows, never to an
LLM opinion.

Metrics:
  behaviour_accuracy     status matches expected (answer/clarify/abstain)
  exact_plan_accuracy    custom planner only: canonical plan == expected plan
  result_equality        answerable questions whose result set equals the reference
  clarification_recall   clarified / expected-clarify
  abstention_recall      abstained / expected-abstain
  false_clarification    clarified on answerable questions
  false_abstention       abstained on answerable questions
  unsafe_answer_rate     returned a result where clarify/abstain was expected
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from itertools import permutations
from pathlib import Path

import yaml

from ..nl2sql.planner import Planner, answer
from ..semantic.compile_duckdb import compile_plan, normalize_plan
from ..semantic.engine import Engine
from ..semantic.model import load_all

HERE = Path(__file__).resolve().parent
QUESTIONS = HERE / "questions.yaml"
FIXTURE_DIR = HERE.parent / "tests" / "fixtures" / "contract"
TOL = 1e-6


# ------------------------------------------------------------ comparison
def _norm(v):
    if isinstance(v, bool):
        return ("b", v)
    if isinstance(v, (int, float)):
        return ("n", float(v))
    if isinstance(v, str):
        s = v.strip()
        try:
            return ("n", float(s))
        except ValueError:
            return ("s", s)
    if v is None:
        return ("z", None)
    return ("s", str(v))


def _eq(a, b) -> bool:
    if a[0] == "n" and b[0] == "n":
        return abs(a[1] - b[1]) <= TOL + 1e-9 * max(abs(a[1]), abs(b[1]))
    return a == b


def _rows_equal(ref: list[list], got: list[list]) -> bool:
    """Multiset equality of rows with tolerant numeric compare."""
    if len(ref) != len(got):
        return False
    remaining = list(got)
    for r in ref:
        for i, g in enumerate(remaining):
            if len(r) == len(g) and all(_eq(x, y) for x, y in zip(r, g)):
                remaining.pop(i)
                break
        else:
            return False
    return True


def compare_results(ref_rows: list[list], got_rows: list[list]) -> dict:
    """Compare result sets ignoring row order, column order and column names.

    Extra columns in `got` are allowed (e.g. a vendor adds a label column) and
    reported. Returns {"equal": bool, "column_mapping": [...], "extra_columns": int}.
    """
    ref = [[_norm(v) for v in r] for r in ref_rows]
    got = [[_norm(v) for v in r] for r in got_rows]
    if not ref and not got:
        return {"equal": True, "column_mapping": [], "extra_columns": 0}
    if len(ref) != len(got):
        return {"equal": False, "reason": f"row count {len(got)} != expected {len(ref)}"}
    k = len(ref[0]) if ref else 0
    n = len(got[0]) if got else 0
    if n < k:
        return {"equal": False, "reason": f"{n} columns < expected {k}"}
    if n > 6 and k > 0:  # keep permutation search small; require prefix order then
        perms = [tuple(range(k))]
    else:
        perms = permutations(range(n), k)
    for p in perms:
        proj = [[row[j] for j in p] for row in got]
        if _rows_equal(ref, proj):
            return {"equal": True, "column_mapping": list(p), "extra_columns": n - k}
    return {"equal": False, "reason": "values differ"}


# --------------------------------------------------------------- scoring
def load_questions(path=QUESTIONS) -> list[dict]:
    return yaml.safe_load(Path(path).read_text())["questions"]


class Reference:
    """Reference rows: hand-fixed `expected.result`, else the expected plan executed."""

    def __init__(self, data_dirs: dict[str, str | None], use_fixed: bool = True):
        self.use_fixed = use_fixed
        self.models = load_all()
        self.engines = {n: Engine(m, data_dirs.get(n)) for n, m in self.models.items()}

    def rows(self, q: dict) -> tuple[list | None, str]:
        exp = q["expected"]
        fixed_applies = self.use_fixed or q["model"] != "hr_public"
        if exp.get("result") is not None and fixed_applies:
            return exp["result"], "hand_fixed"
        if exp.get("plan"):
            c = compile_plan(self.models[q["model"]], exp["plan"])
            return self.engines[q["model"]].execute(c)["rows"], "expected_plan_executed"
        return None, "none"


def _summarise(details: list[dict], with_plan: bool) -> dict:
    by = Counter(d["expected_status"] for d in details)
    n_ans, n_cl, n_ab = by["answer"], by["clarify"], by["abstain"]

    def rate(num, den):
        return None if den == 0 else round(num / den, 4)

    ans = [d for d in details if d["expected_status"] == "answer"]
    s = {
        "n_questions": len(details), "n_answerable": n_ans, "n_expected_clarify": n_cl, "n_expected_abstain": n_ab,
        "behaviour_accuracy": rate(sum(d["status_match"] for d in details), len(details)),
        "result_equality": rate(sum(bool(d.get("result_equal")) for d in ans), n_ans),
        "clarification_recall": rate(sum(d["status"] == "clarify" for d in details if d["expected_status"] == "clarify"), n_cl),
        "abstention_recall": rate(sum(d["status"] == "abstain" for d in details if d["expected_status"] == "abstain"), n_ab),
        "false_clarification": rate(sum(d["status"] == "clarify" for d in ans), n_ans),
        "false_abstention": rate(sum(d["status"] == "abstain" for d in ans), n_ans),
        "unsafe_answer_rate": rate(sum(d["status"] == "answer" for d in details if d["expected_status"] != "answer"), n_cl + n_ab),
        "clarification_rate": rate(sum(d["status"] == "clarify" for d in details), len(details)),
        "abstention_rate": rate(sum(d["status"] == "abstain" for d in details), len(details)),
        "errors": sum(d["status"] == "error" for d in details),
    }
    if with_plan:
        s["exact_plan_accuracy"] = rate(sum(bool(d.get("plan_exact")) for d in ans), n_ans)
    return s


def score_custom(questions: list[dict], data_dirs: dict[str, str | None], use_fixed: bool = True) -> dict:
    ref = Reference(data_dirs, use_fixed)
    planners = {n: Planner(m) for n, m in ref.models.items()}
    details = []
    for q in questions:
        model = ref.models[q["model"]]
        exp = q["expected"]
        try:
            res = answer(planners[q["model"]], ref.engines[q["model"]], q["question"])
            status = res.status
        except Exception as exc:  # preserve errors as attempted cases
            res, status = None, "error"
            err = f"{type(exc).__name__}: {exc}"
        d = {"id": q["id"], "model": q["model"], "category": q.get("category"), "question": q["question"],
             "expected_status": exp["status"], "status": status, "status_match": status == exp["status"]}
        if res is None:
            d["error"] = err
        else:
            d["plan"] = res.plan
            d["sql"] = res.sql
            if res.clarification:
                d["clarification"] = res.clarification.get("question")
                d["clarify_kind"] = res.clarification.get("kind")
            if res.abstention:
                d["abstention"] = res.abstention.get("reason")
                d["abstain_rule"] = res.abstention.get("rule")
        if exp["status"] == "answer":
            d["plan_exact"] = bool(res and res.plan) and normalize_plan(model, exp["plan"]) == res.plan
            ref_rows, src = ref.rows(q)
            d["reference_source"] = src
            if res is not None and res.result is not None:
                cmp = compare_results(ref_rows, res.result["rows"])
                d["result_equal"] = cmp["equal"]
                d["result_rows"] = res.result["rows"]
                if not cmp["equal"]:
                    d["result_diff"] = cmp.get("reason")
                    d["reference_rows"] = ref_rows
            else:
                d["result_equal"] = False
        details.append(d)
    return {"system": "custom_stack_deterministic", "summary": _summarise(details, True), "details": details}


def score_external(questions: list[dict], answers_path: str, system: str, data_dirs: dict[str, str | None],
                   use_fixed: bool = True) -> dict:
    ref = Reference(data_dirs, use_fixed)
    recs = {}
    for line in Path(answers_path).read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("//"):
            r = json.loads(line)
            recs[r["id"]] = r
    details = []
    for q in questions:
        exp = q["expected"]
        r = recs.get(q["id"])
        status = r["status"] if r else "missing"
        d = {"id": q["id"], "model": q["model"], "question": q["question"], "expected_status": exp["status"],
             "status": status, "status_match": status == exp["status"],
             "sql": (r or {}).get("sql"), "run_id": (r or {}).get("run_id"), "reviewer": (r or {}).get("reviewer")}
        if exp["status"] == "answer":
            ref_rows, src = ref.rows(q)
            d["reference_source"] = src
            if r and status == "answer" and r.get("rows") is not None:
                cmp = compare_results(ref_rows, r["rows"])
                d["result_equal"] = cmp["equal"]
                if not cmp["equal"]:
                    d["result_diff"] = cmp.get("reason")
            else:
                d["result_equal"] = False
        details.append(d)
    out = {"system": system, "answers_file": str(answers_path), "summary": _summarise(details, False), "details": details}
    out["summary"]["missing"] = sum(d["status"] == "missing" for d in details)
    return out


def markdown(report: dict) -> str:
    s = report["summary"]
    lines = [f"# NL evaluation: {report['system']}", "",
             "Visible development set (not a holdout). Results compare result sets, not LLM judgments.", "",
             "| metric | value |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in s.items()]
    lines += ["", "| id | expected | got | plan exact | result equal |", "|---|---|---|---|---|"]
    for d in report["details"]:
        lines.append(f"| {d['id']} | {d['expected_status']} | {d['status']} | {d.get('plan_exact', '')} | {d.get('result_equal', '')} |")
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="custom_stack.eval.score")
    ap.add_argument("--questions", default=str(QUESTIONS))
    ap.add_argument("--data-dir", default=str(FIXTURE_DIR),
                    help="hr_public contract-layer dir (default: synthetic fixtures; real lake: data/lake/contract)")
    ap.add_argument("--real-lake", action="store_true",
                    help="ignore hand-fixed hr_public results (fixture-specific); reference = expected plan executed on --data-dir")
    ap.add_argument("--benchmark-dir", default=None)
    ap.add_argument("--external")
    ap.add_argument("--system", default="external")
    ap.add_argument("--out")
    ap.add_argument("--markdown")
    a = ap.parse_args(argv)
    qs = load_questions(a.questions)
    dirs = {"hr_public": a.data_dir, "benchmark_workforce": a.benchmark_dir}
    use_fixed = not a.real_lake
    report = (score_external(qs, a.external, a.system, dirs, use_fixed) if a.external
              else score_custom(qs, dirs, use_fixed))
    text = json.dumps(report, indent=2, default=str)
    if a.out:
        Path(a.out).write_text(text)
    if a.markdown:
        Path(a.markdown).write_text(markdown(report))
    print(json.dumps(report["summary"], indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
