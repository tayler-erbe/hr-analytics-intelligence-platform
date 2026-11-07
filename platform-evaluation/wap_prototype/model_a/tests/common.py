"""Shared helpers: the Phase 1 inputs and one cached reduced pipeline run (two origins, baselines + A-gbm, no
sensitivity / ablation) in a temp folder, shared by the suppression, gate and star-schema tests.

    python -m unittest discover -s wap_prototype/model_a/tests -t . -v      # from platform-evaluation/
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

PE_ROOT = Path(__file__).resolve().parents[3]
if str(PE_ROOT) not in sys.path:
    sys.path.insert(0, str(PE_ROOT))

from wap_prototype.model_a import config as C  # noqa: E402
from wap_prototype.model_a import data as D  # noqa: E402

_CACHE: dict = {}
SMALL_ORIGINS = (C.ORIGINS[-2], C.ORIGINS[-1])
SMALL_LEARNERS = ("A-base-family", "A-base-step", "A-gbm")
SMALL_DRAWS = 300


def inputs() -> D.Inputs:
    if "inputs" not in _CACHE:
        _CACHE["inputs"] = D.load_inputs()
    return _CACHE["inputs"]


def small_run(tag: str = "a") -> dict:
    """A full pipeline run with reduced settings into a temp folder; cached per tag."""
    key = f"run_{tag}"
    if key not in _CACHE:
        from wap_prototype.model_a import run_all as R
        tmp = Path(tempfile.mkdtemp(prefix=f"wap_model_a_{tag}_"))
        os.environ.pop(C.PERSON_LEVEL_ENV, None)
        r = R.run(SMALL_ORIGINS, SMALL_LEARNERS, sensitivity=False, ablation=False, out_dir=tmp, card_path=tmp / "MODEL_CARD.md", draws=SMALL_DRAWS)
        _CACHE[key] = {"result": r, "out": tmp}
    return _CACHE[key]


def cleanup():
    for k in list(_CACHE):
        if k.startswith("run_"):
            shutil.rmtree(_CACHE.pop(k)["out"], ignore_errors=True)
