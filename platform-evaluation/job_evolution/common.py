"""Shared paths, protocol constants and small helpers for the job-evolution model.

Protocol: job_evolution_v1. Every threshold the pipeline uses is in PROTOCOL.
Thresholds that define the *prediction targets* are not fixed numbers: they are
quantiles computed from training data only (see model.py), so no test-period
information sets them.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent  # platform-evaluation/
RAW = ROOT / "data" / "lake" / "raw" / "onet_history"
DERIVED = RAW / "derived"            # large parsed panel tables (gitignored lake area)
CONTRACT = ROOT / "data" / "lake" / "contract"
ART = Path(os.environ.get("JE_ART", HERE / "artifacts"))  # small, reviewable outputs (JE_ART overrides, for tests)
OUT_HTML = ROOT / "output" / "job_evolution" / "job_evolution_explorer.html"
SUCSS_CANDIDATES = ROOT / "sucss_mapping" / "outputs" / "candidates.parquet"

# (version, release month, O*NET-SOC taxonomy). Taxonomy per release is checked
# against the code sets at build time (build_panel.detect_taxonomy).
RELEASES = [
    ("13.0", "2008-06", "2006"), ("14.0", "2009-06", "2009"), ("15.0", "2010-07", "2009"),
    ("15.1", "2011-02", "2010"), ("16.0", "2011-07", "2010"), ("17.0", "2012-07", "2010"),
    ("18.0", "2013-07", "2010"), ("19.0", "2014-07", "2010"), ("20.0", "2015-08", "2010"),
    ("21.0", "2016-08", "2010"), ("22.0", "2017-08", "2010"), ("23.0", "2018-08", "2010"),
    ("24.0", "2019-08", "2010"), ("25.0", "2020-08", "2010"), ("26.0", "2021-08", "2019"),
    ("27.0", "2022-08", "2019"), ("28.0", "2023-08", "2019"), ("29.0", "2024-08", "2019"),
    ("30.0", "2025-08", "2019"), ("31.0", "2026-08", "2019"),
]
REL_INDEX = {v: i for i, (v, _, _) in enumerate(RELEASES)}


def release_year(version: str) -> float:
    """Decimal year of a release (e.g. '28.0' -> 2023.583)."""
    month = dict((v, m) for v, m, _ in RELEASES)[version]
    y, m = month.split("-")
    return int(y) + (int(m) - 1) / 12.0


def onet_date_year(mmyyyy: str | None) -> float | None:
    """O*NET 'MM/YYYY' date -> decimal year."""
    if not mmyyyy or "/" not in mmyyyy:
        return None
    m, y = mmyyyy.split("/")
    return int(y) + (int(m) - 1) / 12.0


PROTOCOL = {
    "version": "job_evolution_v1",
    # --- task-statement matching (harmonize.match_tasks) ---
    # similarity = difflib ratio on normalized text (lower-case, punctuation
    # stripped, 'and'/'or'/'and/or' folded to one token).
    "task_minor_edit_min": 0.90,     # >= this: wording edit, counted as stable
    "task_revision_min": 0.70,       # [0.70, 0.90): substantive revision
    #                                  < 0.70 and unmatched: removed + added
    # --- technology example matching (harmonize.match_examples) ---
    "tech_rename_min": 0.85,         # similarity >= this, or token containment: a rename
    # --- skill-profile drift ---
    "drift_domains": ["skills", "gwa"],
    "drift_scales": {"IM": (1.0, 5.0), "LV": (0.0, 7.0)},  # rescaled to 0-1 before distance
    # --- prediction targets ---
    "target_quantile": 0.67,         # "high churn" = above the training-period 67th percentile
    "task_test_origins": ["17.0", "18.0", "19.0", "20.0", "21.0", "22.0", "23.0", "24.0", "25.0", "26.0"],
    "tech_test_origins": ["24.0", "25.0", "26.0", "27.0", "28.0", "29.0"],
    "min_train_rows": 150,
    "bootstrap_reps": 400,
    "ensemble_reps": 60,
    "random_seed": 20261106,
    # --- AI / data tool vocabulary for technology examples (case-insensitive regex) ---
    "ai_ml_regex": (r"machine learning|deep learning|artificial intelligence|\bai\b|tensorflow|pytorch|"
                    r"\bkeras\b|scikit|chatgpt|openai|\bgpt\b|github copilot|microsoft copilot|365 copilot|\bclaude\b|large language|\bllm|"
                    r"neural net|natural language|\bnlp\b|computer vision|\bwatson\b|\bh2o\b|datarobot|"
                    r"sagemaker|azure machine|vertex ai|hugging ?face|\bcaffe\b|theano|xgboost|lightgbm|"
                    r"\bspacy\b|\bnltk\b|opencv|rapidminer|\bknime\b|generative|gemini|midjourney|"
                    r"dall-e|stable diffusion|langchain|\bbard\b"),
    "data_tool_regex": (r"\bpython\b|\br\b|\bsql\b|mysql|postgres|tableau|power ?bi|\bsas\b|spss|\bstata\b|"
                        r"hadoop|\bspark\b|databricks|snowflake|alteryx|\bqlik|looker|bigquery|redshift|"
                        r"mongodb|jupyter|pandas|numpy|matlab|\bscala\b|apache hive|apache kafka|"
                        r"elasticsearch|\bdbt\b|microsoft azure|amazon web services|google cloud"),
    "rounding": 4,
}

CAVEATS = {
    "rolling_updates": ("O*NET updates occupations on a rolling schedule (each occupation's tasks are re-surveyed "
                        "roughly every 5-10 years). Release-to-release change therefore mostly reflects WHEN an "
                        "occupation was updated, not how fast the work changed. Indicators here are measured at "
                        "real update events, and the timing of updates is modelled separately."),
    "editorial_change": ("Some change is editorial: O*NET rewrote 'and' as 'or' in many task statements, stripped "
                         "vendor prefixes and generic suffixes from software names (about 7,000 renames across 2017-2024 releases), and moved to the O*NET-SOC 2010 and "
                         "2019 taxonomies. Matching rules fold these, but residual editorial change remains."),
    "technology_method": ("Technology examples exist in the database files only from O*NET 21.0 (2016). From about "
                          "2018 O*NET adds software examples from job-posting data in bulk, so technology adoption "
                          "partly reflects O*NET's collection method, not only employer adoption."),
    "observed_usage_not_displacement": ("AI usage exposure (Anthropic Economic Index) is observed Claude usage. It "
                                        "was published in 2025-2026, after every backtest origin, so it is used only "
                                        "as a clearly flagged ex-post feature. It is not a forecast of job loss."),
    "unreviewed_mapping": ("SUCSS classes are linked through the rank-1 candidate in "
                           "sucss_mapping/outputs/candidates.parquet (review_status = unreviewed). Validate before use."),
    "role_level_only": ("Role-level evidence only: no person is read, stored or scored. Do not use for hiring, "
                        "promotion, discipline, pay or any decision about an individual (Illinois HB 3773)."),
    "national_data": "O*NET describes occupations nationally, not University positions.",
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def dump_json(obj, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=1, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n",
                    encoding="utf-8")


def rnd(x, n=None):
    if x is None:
        return None
    try:
        import math
        if isinstance(x, float) and (math.isnan(x) or math.isinf(x)):
            return None
    except Exception:
        pass
    return round(float(x), PROTOCOL["rounding"] if n is None else n)
