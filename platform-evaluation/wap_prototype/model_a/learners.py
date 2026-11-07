"""The pre-registered Model A learners (protocol 2.4) and Platt recalibration.

Every learner exposes fit(X, y) and predict(X) -> probabilities, where X is the logical-name frame from
data.feature_frame. Hyper-parameters come from config.LEARNERS and are not tuned on test years; the only data-driven
choice (the logistic C) is a 5-fold CV inside the training rows.
"""
from __future__ import annotations

import os

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import GridSearchCV, StratifiedKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from wap_prototype.model_a import config as C

CV_JOBS = min(4, os.cpu_count() or 1)   # CV folds are independent; parallel folds do not change the chosen C


def _logit(p, eps=1e-6):
    p = np.clip(np.asarray(p, float), eps, 1 - eps)
    return np.log(p / (1 - p))


def _expit(z):
    return 1.0 / (1.0 + np.exp(-np.asarray(z, float)))


# ------------------------------------------------------------------------------------------- baselines
class BaseFamily:
    """Base rate by role_family in the training years; unseen family -> overall training rate."""
    kind = "base_family"

    def fit(self, X: pd.DataFrame, y: np.ndarray):
        d = pd.DataFrame({"g": X["role_family"].astype(object), "y": y})
        self.global_rate = float(d["y"].mean())
        self.rates = d.groupby("g")["y"].mean().to_dict()
        self.n = d.groupby("g")["y"].size().to_dict()
        return self

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return X["role_family"].astype(object).map(self.rates).fillna(self.global_rate).to_numpy(float)

    def info(self) -> dict:
        return {"global_rate": self.global_rate, "n_groups": len(self.rates)}


class BaseStep:
    """Base rate by (ladder, level) in the training years, backing off to the family rate below `backoff_min_n`."""
    kind = "base_step"

    def __init__(self, backoff_min_n: int = C.STEP_BACKOFF_MIN_N):
        self.backoff_min_n = backoff_min_n

    def fit(self, X: pd.DataFrame, y: np.ndarray):
        self.family = BaseFamily().fit(X, y)
        d = pd.DataFrame({"l": X["ladder"].astype(object), "v": X["level"].astype(float), "y": y})
        g = d.groupby(["l", "v"])["y"].agg(["mean", "size"])
        self.rates = {k: float(r["mean"]) for k, r in g.iterrows() if r["size"] >= self.backoff_min_n}
        self.n_backed_off = int((g["size"] < self.backoff_min_n).sum())
        return self

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        fam = self.family.predict(X)
        keys = list(zip(X["ladder"].astype(object), X["level"].astype(float)))
        return np.array([self.rates.get(k, f) for k, f in zip(keys, fam)], float)

    def info(self) -> dict:
        return {"n_steps_with_rate": len(self.rates), "n_steps_backed_off": self.n_backed_off}


# ------------------------------------------------------------------------------------------- sklearn learners
def _preprocessor(num: list[str], cat: list[str], scale: bool) -> ColumnTransformer:
    num_steps = [("impute", SimpleImputer(strategy="median", add_indicator=True))]
    if scale:
        num_steps.append(("scale", StandardScaler()))
    return ColumnTransformer([
        ("num", Pipeline(num_steps), num),
        ("cat", Pipeline([("impute", SimpleImputer(strategy="constant", fill_value="__missing__")),
                          ("onehot", OneHotEncoder(handle_unknown="ignore", sparse_output=False))]), cat),
    ])


class Logit:
    kind = "logit"

    def __init__(self, num: list[str], cat: list[str], seed: int, spec: dict):
        self.num, self.cat, self.seed, self.spec = num, cat, seed, spec

    def fit(self, X: pd.DataFrame, y: np.ndarray):
        pipe = Pipeline([("prep", _preprocessor(self.num, self.cat, scale=True)),
                         ("clf", LogisticRegression(solver="lbfgs", max_iter=5000))])   # L2 (sklearn default; spec["penalty"])
        cv = StratifiedKFold(n_splits=self.spec["cv_folds"], shuffle=True, random_state=self.seed)
        gs = GridSearchCV(pipe, {"clf__C": list(self.spec["C_grid"])}, cv=cv, scoring="neg_log_loss", n_jobs=CV_JOBS, refit=True)
        gs.fit(X, y)
        self.model, self.C = gs.best_estimator_, float(gs.best_params_["clf__C"])
        return self

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return self.model.predict_proba(X)[:, 1]

    def info(self) -> dict:
        return {"C": self.C}


class RF:
    kind = "rf"

    def __init__(self, num: list[str], cat: list[str], seed: int, spec: dict):
        self.num, self.cat, self.seed, self.spec = num, cat, seed, spec

    def fit(self, X: pd.DataFrame, y: np.ndarray):
        s = self.spec
        self.model = Pipeline([("prep", _preprocessor(self.num, self.cat, scale=False)),
                               ("clf", RandomForestClassifier(n_estimators=s["n_estimators"], min_samples_leaf=s["min_samples_leaf"],
                                                              max_features=s["max_features"], class_weight=s["class_weight"],
                                                              random_state=self.seed, n_jobs=1))]).fit(X, y)
        return self

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return self.model.predict_proba(X)[:, 1]

    def info(self) -> dict:
        return {}


class GBM:
    """LightGBM with native categoricals; categories are fixed from the training rows (unseen -> missing)."""
    kind = "gbm"

    def __init__(self, num: list[str], cat: list[str], seed: int, spec: dict):
        self.num, self.cat, self.seed, self.spec = num, cat, seed, spec

    def _frame(self, X: pd.DataFrame) -> pd.DataFrame:
        out = X[self.num].astype(float).copy()
        for c in self.cat:
            out[c] = pd.Categorical(X[c].astype(object), categories=self.categories[c])
        return out

    def fit(self, X: pd.DataFrame, y: np.ndarray):
        import lightgbm as lgb
        self.categories = {c: sorted(v for v in X[c].dropna().unique()) for c in self.cat}
        s = self.spec
        self.model = lgb.LGBMClassifier(n_estimators=s["n_estimators"], learning_rate=s["learning_rate"], num_leaves=s["num_leaves"],
                                        min_child_samples=s["min_child_samples"], deterministic=s["deterministic"],
                                        num_threads=s["num_threads"], force_row_wise=True, random_state=self.seed, verbose=-1)
        self.model.fit(self._frame(X), y, categorical_feature=self.cat)
        return self

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return self.model.predict_proba(self._frame(X))[:, 1]

    def info(self) -> dict:
        return {}


def make_learner(run_id: str, num: list[str], cat: list[str], seed: int = C.SEED):
    spec = C.LEARNERS[run_id]
    k = spec["kind"]
    if k == "base_family":
        return BaseFamily()
    if k == "base_step":
        return BaseStep(spec["backoff_min_n"])
    if k == "logit":
        return Logit(num, cat, seed, spec)
    if k == "rf":
        return RF(num, cat, seed, spec)
    if k == "gbm":
        return GBM(num, cat, seed, spec)
    raise ValueError(run_id)


# ------------------------------------------------------------------------------------------- Platt
class Platt:
    """logit(p') = a + b * logit(p), fitted by unpenalised logistic regression on out-of-time rows
    (succession_models vacancy.Recalibrator semantics). Falls back to the identity when the recalibration set
    has fewer than two classes or fewer than `min_n` rows; the fallback is recorded."""

    def __init__(self, min_n: int = 50):
        self.min_n = min_n

    def fit(self, p: np.ndarray, y: np.ndarray):
        p, y = np.asarray(p, float), np.asarray(y, int)
        self.n, self.n_pos = int(len(y)), int(y.sum())
        if len(y) < self.min_n or len(np.unique(y)) < 2:
            self.a, self.b, self.fallback = 0.0, 1.0, True
            return self
        m = LogisticRegression(C=1e6, max_iter=5000).fit(_logit(p)[:, None], y)
        self.a, self.b, self.fallback = float(m.intercept_[0]), float(m.coef_[0, 0]), False
        return self

    def apply(self, p: np.ndarray) -> np.ndarray:
        return _expit(self.a + self.b * _logit(p))

    def info(self) -> dict:
        return {"a": self.a, "b": self.b, "n_recal": self.n, "n_recal_pos": self.n_pos, "fallback_identity": self.fallback}
