"""Model A training: the out-of-time backtest of protocol 2.5 for every pre-registered learner, plus the
sensitivity runs (S1-S3), the age ablation and the scoring fit at data_as_of.

    cd platform-evaluation
    python -m wap_prototype.model_a.train                      # all origins, all learners (~10 min)
    python -m wap_prototype.model_a.train --origins 2022-12-31 2023-12-31 --no-sensitivity --no-ablation

For each origin Y (2019-12-31 .. 2023-12-31) and horizon h in {12, 18}:
  * train on snapshots with snap_date + 18 months <= Y, labels as known at Y;
  * Platt recalibration fitted on snapshots in (Y-2, Y] whose horizon resolved by Y, scored by the model fitted
    at origin Y-2 (its own training window ends at Y-2 - 18 months), labels as known at Y;
  * predict snapshots in (Y, Y+2] whose horizon resolved by data_as_of; evaluation labels are the latest.
Person-level predictions are a pipeline intermediate and go to outputs/restricted/intermediate/ only.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import platform
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from wap_prototype.model_a import config as C  # noqa: E402
from wap_prototype.model_a import data as D  # noqa: E402
from wap_prototype.model_a import governance_bridge as G  # noqa: E402
from wap_prototype.model_a import learners as L  # noqa: E402


# ------------------------------------------------------------------------------------------- run variants
def variant(run: str) -> dict:
    """'A-gbm' -> main; 'A-gbm:S2' -> sensitivity; 'A-gbm:age' -> ablation."""
    base, _, suffix = run.partition(":")
    spec = {"run": run, "learner": base, "label_kind": "promotion", "with_age": False, "drop": (), "horizons": C.HORIZONS}
    if suffix == "":
        return spec
    if suffix == "age":
        return spec | {"with_age": True}
    if suffix == "S1":
        return spec | {"label_kind": "transition", "horizons": (12,)}
    if suffix == "S2":
        return spec | {"drop": C.EXTERNAL_FEATURES}
    if suffix == "S3":
        return spec | {"drop": C.TENURE_PROXIES}
    raise ValueError(run)


def run_list(learners=tuple(C.LEARNERS), sensitivity: bool = True, ablation: bool = True) -> list[str]:
    runs = list(learners)
    for lr in learners:
        if lr in C.ML_LEARNERS:
            if sensitivity:
                runs += [f"{lr}:{s}" for s in C.SENSITIVITIES]
            if ablation:
                runs.append(f"{lr}{C.ABLATION_SUFFIX}")
    return runs


# ------------------------------------------------------------------------------------------- fitting
class Trainer:
    def __init__(self, inputs: D.Inputs, seed: int = C.SEED):
        self.inp, self.seed = inputs, seed
        self.f = inputs.features
        self._models: dict = {}
        self._labels: dict = {}
        self.fit_log: list[dict] = []

    def label(self, known_at: dt.date, horizon: int, kind: str) -> pd.Series:
        key = (known_at, horizon, kind)
        if key not in self._labels:
            self._labels[key] = D.event_label(self.f, self.inp.events, known_at, horizon, kind)
        return self._labels[key]

    def model_at(self, spec: dict, origin: dt.date, horizon: int):
        """The learner fitted on snapshots with snap_date + 18m <= origin, labels as known at origin. Cached."""
        key = (spec["run"], origin, horizon)
        if key in self._models:
            return self._models[key]
        tr = D.train_mask(self.f, origin)
        if tr.sum() == 0:
            self._models[key] = None
            return None
        y = self.label(origin, horizon, spec["label_kind"])[tr]
        assert not y.isna().any(), "training labels must be resolved at the origin (snap + 18m <= origin)"
        X = D.feature_frame(self.f[tr], spec["with_age"], spec["drop"])
        num, cat = D.feature_names(spec["with_age"], spec["drop"])
        t0 = time.time()
        model = L.make_learner(spec["learner"], num, cat, self.seed).fit(X, y.to_numpy(int))
        snaps = self.f.loc[tr, "snap_date"]
        self.fit_log.append(dict(run=spec["run"], fit_origin=origin.isoformat(), horizon=horizon, n_train=int(tr.sum()),
                                 n_train_pos=int(y.sum()), train_prevalence_as_known=float(y.mean()),
                                 train_start=snaps.min().isoformat(), train_end=snaps.max().isoformat(),
                                 seconds=round(time.time() - t0, 2), **model.info()))
        self._models[key] = model
        return model

    def calibrated(self, spec: dict, origin: dt.date, horizon: int):
        """(model at origin, Platt fitted out-of-time on the origin two years earlier)."""
        model = self.model_at(spec, origin, horizon)
        platt = L.Platt()
        r = D.recal_origin(origin)
        model_r = self.model_at(spec, r, horizon)
        rm = D.recal_mask(self.f, origin, horizon)
        if model_r is None or rm.sum() == 0:
            platt.fit(np.array([]), np.array([]))
        else:
            y = self.label(origin, horizon, spec["label_kind"])[rm]
            ok = y.notna()
            X = D.feature_frame(self.f[rm][ok], spec["with_age"], spec["drop"])
            platt.fit(model_r.predict(X), y[ok].to_numpy(int))
        return model, platt

    def predict_rows(self, spec: dict, origin: dt.date, horizon: int, mask: pd.Series, label: pd.Series | None) -> pd.DataFrame:
        model, platt = self.calibrated(spec, origin, horizon)
        rows = self.f[mask]
        X = D.feature_frame(rows, spec["with_age"], spec["drop"])
        p_raw = model.predict(X)
        out = D.reporting_frame(rows)
        out.insert(0, "horizon", horizon)
        out.insert(0, "origin", origin)
        out.insert(0, "run", spec["run"])
        out["p_raw"] = p_raw
        out["p_cal"] = platt.apply(p_raw)
        out["y"] = label[mask].to_numpy(float) if label is not None else np.nan
        info = platt.info() | {"run": spec["run"], "origin": origin.isoformat(), "horizon": horizon, "n_predict": int(mask.sum())}
        if hasattr(model, "info"):
            info |= {f"model_{k}": v for k, v in model.info().items()}
        return out, info


def backtest(trainer: Trainer, runs: list[str], origins=C.ORIGINS) -> tuple[pd.DataFrame, list[dict]]:
    preds, recal_log = [], []
    for run in runs:
        spec = variant(run)
        for origin in origins:
            for h in spec["horizons"]:
                tm = D.test_mask(trainer.f, origin, h, trainer.inp.data_as_of, resolved_only=False)
                if tm.sum() == 0:
                    recal_log.append(dict(run=run, origin=origin.isoformat(), horizon=h, n_predict=0, note="no test rows"))
                    continue
                y_eval = D.latest_label(trainer.f, h) if spec["label_kind"] == "promotion" else \
                    trainer.label(trainer.inp.data_as_of, h, spec["label_kind"])
                out, info = trainer.predict_rows(spec, origin, h, tm, y_eval)
                preds.append(out)
                recal_log.append(info)
    return pd.concat(preds, ignore_index=True), recal_log


def scoring(trainer: Trainer, learners=tuple(C.LEARNERS)) -> tuple[pd.DataFrame, list[dict]]:
    """The live scoring fit at data_as_of for the snapshots after the last backtest window (unresolved labels)."""
    preds, log = [], []
    sm = D.scoring_mask(trainer.f, C.ORIGINS[-1])
    for run in learners:
        spec = variant(run)
        for h in C.HORIZONS:
            out, info = trainer.predict_rows(spec, trainer.inp.data_as_of, h, sm, D.latest_label(trainer.f, h))
            preds.append(out)
            log.append(info | {"scoring": True})
    return pd.concat(preds, ignore_index=True), log


# ------------------------------------------------------------------------------------------- driver
def run(inputs: D.Inputs, origins=C.ORIGINS, learners=tuple(C.LEARNERS), sensitivity: bool = True, ablation: bool = True,
        seed: int = C.SEED, out_dir: Path | None = None, write: bool = True) -> dict:
    out_dir = Path(out_dir) if out_dir else C.output_dir()
    restricted = out_dir / "restricted"
    runs = run_list(learners, sensitivity, ablation)
    tr = Trainer(inputs, seed)
    t0 = time.time()
    preds, recal_log = backtest(tr, runs, origins)
    score, score_log = scoring(tr, [lr for lr in learners if lr in C.LEARNERS])
    preds = preds.sort_values(["run", "origin", "horizon", "snap_date", "person_id", "position_id"], kind="mergesort").reset_index(drop=True)
    score = score.sort_values(["run", "origin", "horizon", "snap_date", "person_id", "position_id"], kind="mergesort").reset_index(drop=True)
    import sklearn
    import lightgbm
    manifest = {
        "protocol_version": C.PROTOCOL_VERSION, "model_id": C.MODEL_ID, "seed": seed, "data_as_of": inputs.data_as_of.isoformat(),
        "run_id": f"A-{inputs.data_as_of:%Y%m%d}-s{seed}", "origins": [o.isoformat() for o in origins], "horizons": list(C.HORIZONS),
        "runs": runs, "feature_table_hash": inputs.feature_table_hash, "bitemporal_mode": inputs.bitemporal_mode,
        "phase1_run_config": inputs.source, "feature_map": C.FEATURE_MAP, "numeric_features": list(C.NUMERIC_FEATURES),
        "categorical_features": list(C.CATEGORICAL_FEATURES), "learners": {k: v for k, v in C.LEARNERS.items() if k in learners},
        "training_label_rule": "event of the kind in (snap, snap+h] whose source row was known (row_known_from) on or before the origin",
        "evaluation_label_rule": "Phase 1 target columns (latest knowledge); censored rows dropped",
        "recalibration": "Platt (logit-linear) fitted on (Y-2, Y] rows scored by the model fitted at Y-2; labels as known at Y",
        "n_backtest_rows": int(len(preds)), "n_scoring_rows": int(len(score)), "seconds": round(time.time() - t0, 1),
        "versions": {"python": platform.python_version(), "numpy": np.__version__, "pandas": pd.__version__,
                     "scikit_learn": sklearn.__version__, "lightgbm": lightgbm.__version__},
        "no_timestamps_note": "outputs are deterministic for a given input and seed; the manifest carries no wall-clock time",
    }
    result = {"predictions": preds, "scoring": score, "fit_log": pd.DataFrame(tr.fit_log), "recal_log": pd.DataFrame(recal_log + score_log),
              "manifest": manifest}
    if write:
        out_dir.mkdir(parents=True, exist_ok=True)
        (restricted / "intermediate").mkdir(parents=True, exist_ok=True)
        (restricted / ".gitignore").write_text("*\n!.gitignore\n", encoding="utf-8")
        G.write_restricted(preds, "predictions", restricted / "intermediate")
        G.write_restricted(score, "scoring_predictions", restricted / "intermediate")
        result["fit_log"].to_csv(out_dir / "fit_log.csv", index=False)
        result["recal_log"].to_csv(out_dir / "recalibration_log.csv", index=False)
        (out_dir / "run_manifest.json").write_text(json.dumps(manifest, indent=1, sort_keys=True, default=str), encoding="utf-8")
    return result


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--origins", nargs="*", default=None, help="subset of protocol origins (YYYY-MM-DD); default all five")
    ap.add_argument("--learners", nargs="*", default=None)
    ap.add_argument("--no-sensitivity", action="store_true")
    ap.add_argument("--no-ablation", action="store_true")
    ap.add_argument("--seed", type=int, default=C.SEED)
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    origins = tuple(dt.date.fromisoformat(o) for o in a.origins) if a.origins else C.ORIGINS
    bad = [o for o in origins if o not in C.ORIGINS]
    if bad:
        raise SystemExit(f"origins outside the protocol set: {bad}")
    inputs = D.load_inputs()
    r = run(inputs, origins, tuple(a.learners) if a.learners else tuple(C.LEARNERS), not a.no_sensitivity, not a.no_ablation,
            a.seed, Path(a.out) if a.out else None)
    m = r["manifest"]
    print(json.dumps({k: m[k] for k in ("run_id", "origins", "runs", "n_backtest_rows", "n_scoring_rows", "seconds")}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
