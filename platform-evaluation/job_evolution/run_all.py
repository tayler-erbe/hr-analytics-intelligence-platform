"""Run the whole job-evolution pipeline and write artifacts/manifest.json.

    python job_evolution/run_all.py [--download]

Steps: (acquire) -> build_panel -> indicators -> model -> watchlist -> render_explorer.
The manifest records SHA-256 of every input (raw O*NET zips, crosswalks, lake
contract tables and SUCSS candidates) and every output, with no wall-clock time,
so two runs on the same inputs produce the same manifest.
"""
from __future__ import annotations

import subprocess
import sys

from common import ART, CONTRACT, HERE, OUT_HTML, PROTOCOL, RAW, ROOT, SUCSS_CANDIDATES, dump_json, sha256_file

STEPS = ["build_panel.py", "indicators.py", "model.py", "watchlist.py", "render_explorer.py"]


def main() -> int:
    steps = (["acquire.py"] if "--download" in sys.argv else []) + STEPS
    for s in steps:
        print(f"== {s}", flush=True)
        r = subprocess.run([sys.executable, str(HERE / s)], cwd=HERE)
        if r.returncode:
            print(f"step {s} failed", file=sys.stderr)
            return r.returncode
    inputs = sorted(list((RAW / "releases").glob("*.zip")) + list((RAW / "crosswalks").glob("*"))) + [
        CONTRACT / "aei_occupation_exposure.parquet", CONTRACT / "sucss_class.parquet", SUCSS_CANDIDATES]
    outputs = sorted(p for p in ART.iterdir() if p.is_file() and p.name != "manifest.json") + [OUT_HTML]
    rel = lambda p: str(p.relative_to(ROOT))
    dump_json({"protocol": PROTOCOL["version"],
               "inputs": {rel(p): sha256_file(p) for p in inputs},
               "outputs": {rel(p): sha256_file(p) for p in outputs}}, ART / "manifest.json")
    print(f"manifest: {len(inputs)} inputs, {len(outputs)} outputs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
