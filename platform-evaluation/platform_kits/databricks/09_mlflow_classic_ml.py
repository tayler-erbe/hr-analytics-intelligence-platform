# Databricks notebook source
# MAGIC %md
# MAGIC # 09 · Classic ML lifecycle: discrete-time attrition hazard on SYNTHETIC data, with MLflow
# MAGIC
# MAGIC **All people here are invented by a seeded generator in this notebook.** The generator's true hazard is known, which lets us
# MAGIC check whether the pipeline recovers it. This is a lifecycle test (features → leakage gate → chronological evaluation vs
# MAGIC baseline → tracking → registry → batch scoring → rollback), **not** a finding about any real workforce.
# MAGIC Real attrition modelling needs approved institutional data on an approved machine, never in Free Edition.
# MAGIC
# MAGIC The frozen benchmark fixture `ml_features` (read-only copy `bm_ml_features`) is used for the leakage gate (case M01/M02):
# MAGIC only `prior_failures` is eligible at prediction time 2026-09-01. `next_month_resolution` must be rejected.
# MAGIC
# MAGIC **Free Edition:** MLflow tracking and Unity Catalog model registry expected to work (verify); real-time serving is limited,
# MAGIC so this notebook uses batch scoring. Rubric evidence: *M1 reproducible features*, *M2 valid evaluation*, *M3 deployment/monitoring*.

# COMMAND ----------

# MAGIC %pip install -q -U "mlflow[databricks]>=3.1" scikit-learn
# MAGIC %restart_python

# COMMAND ----------

# MAGIC %run ./_config

# COMMAND ----------

import json, numpy as np, pandas as pd, mlflow
from mlflow.models import infer_signature
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score, brier_score_loss, log_loss

mlflow.set_registry_uri("databricks-uc")
user = spark.sql("SELECT current_user()").first()[0]
mlflow.set_experiment(f"/Users/{user}/hr_platform_eval_classic_ml")
MODEL_NAME = FQE("synthetic_attrition_hazard")
GEN_SEED = 20261106

# COMMAND ----------

# MAGIC %md ## 1 · Leakage gate on the frozen benchmark fixture (must pass before any training)

# COMMAND ----------

feat = spark.table(FQG("bm_ml_features")).toPandas()
feat["eligible"] = pd.to_datetime(feat["available_on"]) <= pd.to_datetime(feat["prediction_on"])
display(feat)
eligible = sorted(feat.loc[feat.eligible, "feature_name"])
leakage_gate_pass = eligible == ["prior_failures"]
log_run("09_leakage_gate_fixture", "pass" if leakage_gate_pass else "fail", json.dumps(eligible))
assert leakage_gate_pass, "Leakage gate failed on the benchmark fixture; stop."

# COMMAND ----------

# MAGIC %md ## 2 · Seeded synthetic person-quarter panel (known data-generating process)

# COMMAND ----------

def generate_panel(n_people=4000, start="2018-01-01", n_quarters=32, seed=GEN_SEED):
    rng = np.random.default_rng(seed)
    families = list(SOC_MAJOR_GROUPS)[:12]
    fam_effect = dict(zip(families, rng.normal(0, 0.25, len(families))))
    quarters = pd.period_range(start=start, periods=n_quarters, freq="Q")
    rows = []
    for pid in range(n_people):
        hire_q = int(rng.integers(0, n_quarters - 2))
        fam = families[int(rng.integers(0, len(families)))]
        pay_ratio = float(np.clip(rng.normal(1.0, 0.12), 0.6, 1.5))
        fte = float(rng.choice([1.0, 1.0, 1.0, 0.75, 0.5]))
        transfers = 0
        for t in range(hire_q, n_quarters):
            tenure = t - hire_q + 1
            if rng.random() < 0.02:
                transfers += 1
            # TRUE hazard (logit). Kept here so the evaluation can compare against it.
            logit = (-3.4 + 0.6 * (tenure <= 4) - 0.12 * np.log(tenure) + 1.2 * max(0.9 - pay_ratio, 0) * 5
                     + 0.35 * (fte < 1) + fam_effect[fam] + 0.15 * min(transfers, 3) + 0.2 * (quarters[t].quarter == 2))
            p = 1 / (1 + np.exp(-logit))
            left = rng.random() < p
            rows.append(dict(person_key=f"SYN-{pid:05d}", period=str(quarters[t]), period_index=t, tenure_q=tenure,
                             job_family=fam, pay_ratio_lag1=pay_ratio, fte_lag1=fte, transfers_to_date_lag1=transfers,
                             q2=int(quarters[t].quarter == 2), true_hazard=p, separated=int(left)))
            if left:
                break
    return pd.DataFrame(rows)

panel = generate_panel()
# Features use only values known at the START of the quarter (suffix _lag1); the outcome is separation during the quarter.
from pyspark.sql import functions as F
sdf = spark.createDataFrame(panel).withColumn("synthetic", F.lit(True))
sdf.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(FQG("synthetic_attrition_panel"))
spark.sql(f"COMMENT ON TABLE {FQG('synthetic_attrition_panel')} IS 'SYNTHETIC person-quarter panel from a seeded generator (seed {GEN_SEED}). Not real people.'")
print(panel.shape, "separation rate per person-quarter:", round(panel.separated.mean(), 4))

# COMMAND ----------

# MAGIC %md ## 3 · Chronological split, baseline vs models, uncertainty

# COMMAND ----------

SPLIT_INDEX = 24   # train: first 24 quarters; test: last 8 quarters (no shuffling across time)
FEATURES = ["tenure_q", "pay_ratio_lag1", "fte_lag1", "transfers_to_date_lag1", "q2", "job_family"]
train, test = panel[panel.period_index < SPLIT_INDEX], panel[panel.period_index >= SPLIT_INDEX]

def design(df, cols=None):
    X = pd.get_dummies(df[FEATURES].assign(log_tenure=np.log(df.tenure_q), early=(df.tenure_q <= 4).astype(int)),
                       columns=["job_family"], dtype=float)
    return X.reindex(columns=cols, fill_value=0.0) if cols is not None else X

Xtr = design(train); Xte = design(test, Xtr.columns)
ytr, yte = train.separated.values, test.separated.values

# Baseline: empirical hazard by tenure band from the training window only.
band = lambda t: np.minimum(t, 12)
base_rates = train.assign(b=band(train.tenure_q)).groupby("b").separated.mean()
p_base = band(test.tenure_q).map(base_rates).fillna(ytr.mean()).values

def metrics(y, p):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return dict(auc=roc_auc_score(y, p), brier=brier_score_loss(y, p), log_loss=log_loss(y, p))

def bootstrap_ci(df, p, n=300, seed=7):
    """Person-level cluster bootstrap of the AUC difference model - baseline (not row-level)."""
    rng = np.random.default_rng(seed)
    people = df.person_key.unique()
    idx_by = df.reset_index(drop=True).groupby("person_key").indices
    diffs = []
    for _ in range(n):
        ids = np.concatenate([idx_by[k] for k in rng.choice(people, len(people), replace=True)])
        y = df.separated.values[ids]
        if y.min() == y.max():
            continue
        diffs.append(roc_auc_score(y, p[ids]) - roc_auc_score(y, p_base[ids]))
    return np.percentile(diffs, [2.5, 97.5]).tolist()

# COMMAND ----------

results = {}
for name, est in [("logistic", LogisticRegression(max_iter=2000, C=1.0)),
                  ("hist_gbm", HistGradientBoostingClassifier(max_depth=3, learning_rate=0.05, max_iter=200, random_state=0))]:
    with mlflow.start_run(run_name=f"{name}_{RUN_ID}") as run:
        est.fit(Xtr, ytr)
        p = est.predict_proba(Xte)[:, 1]
        m, mb, mt = metrics(yte, p), metrics(yte, p_base), metrics(yte, test.true_hazard.values)
        ci = bootstrap_ci(test, p)
        mlflow.log_params({"model": name, "features": ",".join(FEATURES), "split_index": SPLIT_INDEX, "generator_seed": GEN_SEED,
                           "protocol": PROTOCOL, "train_rows": len(Xtr), "test_rows": len(Xte)})
        mlflow.log_metrics({**{f"test_{k}": v for k, v in m.items()}, **{f"baseline_{k}": v for k, v in mb.items()},
                            **{f"oracle_{k}": v for k, v in mt.items()},
                            "auc_lift_ci_low": ci[0], "auc_lift_ci_high": ci[1]})
        mlflow.set_tags({"data": "synthetic_only", "leakage_gate_fixture": str(leakage_gate_pass), "run_id_kit": RUN_ID})
        # Calibration table by decile (evidence for uncertainty/calibration).
        cal = pd.DataFrame({"p": p, "y": yte}).assign(decile=lambda d: pd.qcut(d.p, 10, labels=False, duplicates="drop")) \
                .groupby("decile").agg(mean_pred=("p", "mean"), observed=("y", "mean"), n=("y", "size")).reset_index()
        mlflow.log_table(cal, "calibration_by_decile.json")
        mlflow.sklearn.log_model(est, name="model", signature=infer_signature(Xte.head(50), p[:50]),
                                 input_example=Xte.head(3), registered_model_name=MODEL_NAME)
        results[name] = dict(run_id=run.info.run_id, **m, baseline_auc=mb["auc"], oracle_auc=mt["auc"], auc_lift_ci=ci)
display(pd.DataFrame(results).T)
log_run("09_train_eval", "pass", json.dumps(results, default=float)[:3000])

# COMMAND ----------

# MAGIC %md
# MAGIC Interpretation rules: the oracle AUC (true generator hazard) is the ceiling. If the bootstrap CI for lift over the baseline
# MAGIC includes 0, report "no demonstrated lift". Do not change features or the split after seeing test metrics under this protocol.

# COMMAND ----------

# MAGIC %md ## 4 · Registry aliases, batch scoring and rollback

# COMMAND ----------

from mlflow import MlflowClient
mc = MlflowClient()
versions = sorted(mc.search_model_versions(f"name = '{MODEL_NAME}'"), key=lambda v: int(v.version))
champion = versions[-1]
mc.set_registered_model_alias(MODEL_NAME, "champion", champion.version)
if len(versions) > 1:
    mc.set_registered_model_alias(MODEL_NAME, "previous", versions[-2].version)
print("champion =", champion.version)

# Batch scoring of the latest synthetic quarter (as-of scoring: only rows for people active at its start).
latest = panel.period_index.max()
score_df = design(panel[panel.period_index == latest], Xtr.columns)
model = mlflow.sklearn.load_model(f"models:/{MODEL_NAME}@champion")   # sklearn flavor -> predict_proba
scored = panel[panel.period_index == latest][["person_key", "period"]].assign(
    hazard=model.predict_proba(score_df)[:, 1], model_version=str(champion.version), run_id=RUN_ID)
spark.createDataFrame(scored).write.mode("append").option("mergeSchema", "true").saveAsTable(FQE("synthetic_attrition_scores"))
display(spark.table(FQE("synthetic_attrition_scores")).where(f"run_id = '{RUN_ID}'").limit(20))

# COMMAND ----------

# Rollback drill: point champion back to the previous version, re-load, confirm the version changed, then restore.
if len(versions) > 1:
    mc.set_registered_model_alias(MODEL_NAME, "champion", versions[-2].version)
    rolled = mc.get_model_version_by_alias(MODEL_NAME, "champion").version
    mc.set_registered_model_alias(MODEL_NAME, "champion", champion.version)
    log_run("09_rollback_drill", "pass" if rolled == versions[-2].version else "fail", f"rolled_to={rolled} restored={champion.version}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5 · Scheduling and monitoring (record what you did)
# MAGIC - Schedule this notebook's scoring cell as a Job (Jobs & Pipelines → Create job; serverless). Free Edition allows a limited
# MAGIC   number of concurrent job tasks (docs: up to 5; verify).
# MAGIC - Monitoring: Databricks' data/model quality monitoring on `synthetic_attrition_scores` (product naming and Free Edition
# MAGIC   availability: verify in workspace). If unavailable, compute drift manually (score distribution by period) and record the gap.
# MAGIC
# MAGIC ## Evidence to capture
# MAGIC - MLflow runs (params, metrics, calibration table, model signature), UC model versions and aliases, rollback drill row in `run_log`.
# MAGIC - The leakage-gate result and the statement that all data is synthetic.
