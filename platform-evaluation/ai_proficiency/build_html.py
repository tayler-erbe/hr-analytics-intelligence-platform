"""Render output/ai_proficiency/rubric_toolkit.html: an offline, single-file page
with the rubric, the 12 tasks, a local scoring form (CSV export, no network) and
the synthetic reliability report.

Usage (from platform-evaluation/ai_proficiency/):  python build_html.py
"""
from __future__ import annotations

import json
from pathlib import Path

import rubric_io
import study

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "output" / "ai_proficiency" / "rubric_toolkit.html"
TEMPLATE = HERE / "toolkit_template.html"


def build(out: Path = OUT) -> Path:
    rubric = rubric_io.load_rubric()
    tasks = rubric_io.load_tasks()
    if not study.REPORT_PATH.exists():
        study.run()
    report = json.loads(study.REPORT_PATH.read_text())
    payload = json.dumps({"rubric": rubric, "tasks": tasks, "report": report}, ensure_ascii=False)
    payload = payload.replace("</", "<\\/")  # keep the JSON inert inside <script>
    html = TEMPLATE.read_text(encoding="utf-8").replace("__TOOLKIT_DATA__", payload)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return out


if __name__ == "__main__":
    print(f"wrote {build()}")
