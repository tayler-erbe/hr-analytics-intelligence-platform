"""Model A end to end: train -> fairness -> evaluate -> aggregate -> model cards.

    cd platform-evaluation
    python -m wap_prototype.model_a.run_all                 # full protocol run (~6 min)
    python -m wap_prototype.model_a.run_all --origins 2022-12-31 2023-12-31 --no-sensitivity --no-ablation --out /tmp/ma
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import warnings
from pathlib import Path

import pandas as pd

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from wap_prototype.model_a import aggregate as A  # noqa: E402
from wap_prototype.model_a import config as C  # noqa: E402
from wap_prototype.model_a import data as D  # noqa: E402
from wap_prototype.model_a import evaluate as EV  # noqa: E402
from wap_prototype.model_a import fairness as FA  # noqa: E402
from wap_prototype.model_a import model_card as MC  # noqa: E402
from wap_prototype.model_a import train as TR  # noqa: E402


def run(origins=C.ORIGINS, learners=tuple(C.LEARNERS), sensitivity: bool = True, ablation: bool = True, seed: int = C.SEED,
        out_dir: Path | None = None, card_path: Path | None = None, draws: int = C.COVERAGE_MC_DRAWS) -> dict:
    out_dir = Path(out_dir) if out_dir else C.output_dir()
    inputs = D.load_inputs()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        t = TR.run(inputs, origins, learners, sensitivity, ablation, seed, out_dir)
        fa = FA.run_audit(t["predictions"], inputs)
        FA.write(fa, out_dir)
        ev = EV.run(t["predictions"], inputs, fa["summary"], C.UNIT_COLUMN[C.unit_level()], out_dir, seed=seed)
        ag = A.run(inputs, out_dir, seed=seed, draws=draws)
    d = MC.load(out_dir)
    card = Path(card_path) if card_path else C.HERE / "MODEL_CARD.md"
    card.write_text(MC.card(d, restricted=False), encoding="utf-8")
    (out_dir / "restricted" / "MODEL_CARD_RESTRICTED.md").write_text(MC.card(d, restricted=True), encoding="utf-8")
    return {"train": t, "fairness": fa, "evaluation": ev, "aggregate": ag}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--origins", nargs="*", default=None)
    ap.add_argument("--learners", nargs="*", default=None, help="subset of protocol learners (baselines are always needed)")
    ap.add_argument("--no-sensitivity", action="store_true")
    ap.add_argument("--no-ablation", action="store_true")
    ap.add_argument("--seed", type=int, default=C.SEED)
    ap.add_argument("--out", default=None)
    ap.add_argument("--card", default=None)
    a = ap.parse_args(argv)
    origins = tuple(dt.date.fromisoformat(o) for o in a.origins) if a.origins else C.ORIGINS
    r = run(origins, tuple(a.learners) if a.learners else tuple(C.LEARNERS), sensitivity=not a.no_sensitivity, ablation=not a.no_ablation, seed=a.seed,
            out_dir=Path(a.out) if a.out else None, card_path=Path(a.card) if a.card else None)
    pd.set_option("display.width", 200)
    print(r["evaluation"]["thresholds"].to_string())
    print(json.dumps(r["evaluation"]["selection"], indent=1))
    print(json.dumps(r["aggregate"]["summary"], indent=1, default=str))
    return 0 if r["aggregate"]["validation"]["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
