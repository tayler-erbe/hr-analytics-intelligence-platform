"""Phase 1 inputs for Model A: the restricted feature table, transition events and the fairness-only
demographics frame; labels as known at an origin; the out-of-time windows of protocol 2.5; feature frames in
logical names with the protocol's exclusions enforced.

Leakage rules implemented here (protocol 5.1):
  1. features at snapshot S are the Phase 1 point-in-time rows (effective and known on or before S);
  2. labels are computed separately from transition_events and joined on (person_id, snap_date) only;
     training labels count an event only if its source row was known (`row_known_from`) on or before the
     origin; evaluation labels use the latest knowledge (the Phase 1 target columns);
  3. training snapshots satisfy snap_date + 18 months <= origin;
  5. recalibration and hyper-parameter choice see training-period data only (learners.py, train.py).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from wap_prototype.model_a import config as C


@dataclass
class Inputs:
    features: pd.DataFrame
    events: pd.DataFrame
    demographics: pd.DataFrame
    data_as_of: dt.date
    feature_table_hash: str
    pack_manifest: Path
    bitemporal_mode: str
    source: dict


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_inputs(input_dir: Path | None = None) -> Inputs:
    d = Path(input_dir) if input_dir else C.input_dir()
    fp = d / "person_period_features.parquet"
    if not fp.exists():
        raise FileNotFoundError(f"{fp} missing: run `python -m wap_prototype.publish` from platform-evaluation/ first")
    f = pd.read_parquet(fp)
    f["snap_date"] = pd.to_datetime(f["snap_date"]).dt.date
    f["knowledge_date"] = pd.to_datetime(f["knowledge_date"]).dt.date
    f = f.sort_values(["snap_date", "person_id", "position_id"], kind="mergesort").reset_index(drop=True)
    e = pd.read_parquet(d / "transition_events.parquet")
    for c in ("event_date", "row_known_from", "known_as_of"):
        e[c] = pd.to_datetime(e[c]).dt.date
    e = e[~e["is_future"].astype(bool)].sort_values(["person_id", "event_date", "event_id"], kind="mergesort").reset_index(drop=True)
    demo = pd.read_parquet(d / "person_demographics_restricted.parquet")
    data_as_of = f["knowledge_date"].iloc[0]
    run_cfg = {}
    rc = d.parent / "run_config.json"
    if rc.exists():
        run_cfg = json.loads(rc.read_text(encoding="utf-8"))
    pack = Path(run_cfg.get("sample_pack_path", C.PE_ROOT / "sample_datasets" / "v3_cookbook")) / run_cfg.get("set_name", "longitudinal") / "manifest.json"
    # Phase 1 reconstructs as-known state from known_from / known_to (bitemporal); the alternative date reading with
    # hist_mode_known_from = effective_date would be the effective-only fallback (protocol 5.1 rule 1).
    mode = "bitemporal" if run_cfg.get("hist_mode_known_from", "post_date") == "post_date" else "effective_only"
    return Inputs(features=f, events=e, demographics=demo, data_as_of=data_as_of, feature_table_hash=_sha256(fp),
                  pack_manifest=pack, bitemporal_mode=mode, source=run_cfg)


# ------------------------------------------------------------------------------------------- labels
EVENT_KINDS = {
    "promotion": lambda et: et == "promotion",
    "transition": lambda et: et.isin(C.TRANSITION_EVENT_TYPES),
    "separation": lambda et: et.str.startswith(C.SEPARATION_EVENT_PREFIX) | (et == "retirement"),
}


def event_label(features: pd.DataFrame, events: pd.DataFrame, known_at: dt.date, horizon: int, kind: str) -> pd.Series:
    """1/0 label per feature row: an event of `kind` in (snap_date, snap_date + horizon months] whose source row
    was known on or before `known_at`; NaN when the horizon passes `known_at` (censored)."""
    ev = events[EVENT_KINDS[kind](events["event_type"]) & (events["row_known_from"] <= known_at)][["person_id", "event_date"]]
    snaps = sorted(features["snap_date"].unique())
    end = {s: C.add_months(s, horizon) for s in snaps}
    f = features[["snap_date", "person_id"]].copy()
    f["_i"] = np.arange(len(f))
    f["_end"] = f["snap_date"].map(end)
    m = f.merge(ev, on="person_id", how="inner")
    hit = m[(m["event_date"] > m["snap_date"]) & (m["event_date"] <= m["_end"])]["_i"].unique()
    y = np.zeros(len(f), dtype=float)
    y[hit] = 1.0
    censored = f["_end"].map(lambda d: d > known_at).to_numpy()
    y[censored] = np.nan
    return pd.Series(y, index=features.index)


def latest_label(features: pd.DataFrame, horizon: int) -> pd.Series:
    """Evaluation label: the Phase 1 target column (latest knowledge), NaN when censored."""
    col = C.LABELS[horizon]
    s = features[col]
    return pd.Series(np.where(s.isna(), np.nan, s.astype(float)), index=features.index)


# ------------------------------------------------------------------------------------------- windows
def _snap_dates(features: pd.DataFrame) -> pd.Series:
    return features["snap_date"]


def train_mask(features: pd.DataFrame, origin: dt.date) -> pd.Series:
    """Snapshots whose 18-month horizon ends on or before the origin (protocol 2.5 / 5.1 rule 3)."""
    end = {s: C.add_months(s, C.TRAIN_HORIZON_MONTHS) for s in features["snap_date"].unique()}
    return _snap_dates(features).map(end) <= origin


def test_mask(features: pd.DataFrame, origin: dt.date, horizon: int, data_as_of: dt.date, resolved_only: bool = True) -> pd.Series:
    """Snapshots in Y+1 .. Y+2; with resolved_only, only those whose horizon has resolved by data_as_of (the
    evaluation set). Unresolved rows inside the window are still scored for the fact table, with a null label."""
    s = _snap_dates(features)
    hi = dt.date(origin.year + C.TEST_WINDOW_YEARS, origin.month, origin.day)
    m = (s > origin) & (s <= hi)
    if resolved_only:
        end = {d: C.add_months(d, horizon) for d in s.unique()}
        m = m & (s.map(end) <= data_as_of)
    return m


def resolved(features: pd.DataFrame, horizon: int, data_as_of: dt.date) -> pd.Series:
    end = {d: C.add_months(d, horizon) for d in features["snap_date"].unique()}
    return features["snap_date"].map(end) <= data_as_of


def recal_mask(features: pd.DataFrame, origin: dt.date, horizon: int) -> pd.Series:
    """Recalibration rows for a test origin Y: snapshots in (Y-2, Y] whose horizon resolved by Y; scored by the
    model fitted at origin Y-2, labelled as known at Y."""
    r = recal_origin(origin)
    s = _snap_dates(features)
    end = {d: C.add_months(d, horizon) for d in s.unique()}
    return (s > r) & (s <= origin) & (s.map(end) <= origin)


def recal_origin(origin: dt.date) -> dt.date:
    return dt.date(origin.year - C.RECAL_OFFSET_YEARS, origin.month, origin.day)


def scoring_mask(features: pd.DataFrame, last_backtest_origin: dt.date) -> pd.Series:
    """Snapshots after the last backtest window: scored by the model fitted at data_as_of (unresolved)."""
    hi = dt.date(last_backtest_origin.year + C.TEST_WINDOW_YEARS, last_backtest_origin.month, last_backtest_origin.day)
    return _snap_dates(features) > hi


# ------------------------------------------------------------------------------------------- feature frames
def feature_names(with_age: bool = False, drop: tuple = ()) -> tuple[list[str], list[str]]:
    num = [f for f in C.NUMERIC_FEATURES if f not in drop]
    cat = [f for f in C.CATEGORICAL_FEATURES if f not in drop]
    if with_age:
        cat = cat + [C.AGE_FEATURE[0]]
    return num, cat


def feature_frame(features: pd.DataFrame, with_age: bool = False, drop: tuple = ()) -> pd.DataFrame:
    """The model matrix in logical names. Protected attributes, age (outside the ablation), college and dept never
    appear; a programming error that adds one raises."""
    num, cat = feature_names(with_age, drop)
    mapping = dict(C.FEATURE_MAP)
    if with_age:
        mapping[C.AGE_FEATURE[0]] = C.AGE_FEATURE[1]
    cols = {logical: mapping[logical] for logical in num + cat}
    physical = list(cols.values())
    forbidden = [p for p in physical if p in C.EXCLUDED_ALWAYS and not (with_age and p == C.AGE_FEATURE[1])]
    if forbidden:
        raise ValueError(f"excluded columns in a Model A feature matrix: {forbidden}")
    X = features[physical].copy()
    X.columns = list(cols.keys())
    for c in num:
        X[c] = pd.to_numeric(X[c], errors="coerce").astype(float)
    for c in cat:
        X[c] = X[c].astype(object).where(X[c].notna(), None).astype(object)
    return X


def reporting_frame(features: pd.DataFrame) -> pd.DataFrame:
    return features[list(C.KEY_COLS) + list(C.REPORTING_COLS)].copy()


def age_40_plus(features: pd.DataFrame) -> pd.Series:
    band = features["age_band"]
    out = pd.Series([None] * len(band), index=features.index, dtype=object)
    out[band.isin(C.AGE_40_PLUS_BANDS)] = "40_plus"
    out[band.isin(C.AGE_UNDER_40_BANDS)] = "under_40"
    return out
