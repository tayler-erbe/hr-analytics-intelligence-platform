"""Ask a question from the command line.

  python -m custom_stack.nl2sql.cli "Staff FTE by sector in 2023" [--model hr_public] [--data-dir DIR] [--plan-only]

Prints status (answer/clarify/abstain), plan, SQL, result rows and provenance as JSON.
The LLM fallback is used only if CUSTOM_STACK_LLM_ENDPOINT and _MODEL are set.
"""
from __future__ import annotations

import argparse
import json
import sys

from ..semantic.model import load_all
from .llm_backend import backend_from_env
from .planner import Planner, answer


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="custom_stack.nl2sql.cli")
    ap.add_argument("question")
    ap.add_argument("--model", default="hr_public")
    ap.add_argument("--data-dir")
    ap.add_argument("--plan-only", action="store_true")
    a = ap.parse_args(argv)
    model = load_all()[a.model]
    planner = Planner(model, llm=backend_from_env())
    if a.plan_only:
        res = planner.plan(a.question)
    else:
        from ..semantic.engine import Engine
        res = answer(planner, Engine(model, a.data_dir), a.question)
    print(json.dumps(res.to_dict(), indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
