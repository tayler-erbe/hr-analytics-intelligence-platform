# %% [markdown]
# # 06 — Snowflake ML notebook: QWI turnover features, chronological evaluation, Model Registry
# Kit v0.1, 2026-11-06. PUBLIC DATA ONLY (Census QWI aggregates).
#
# Run inside a **Snowflake Notebook** (Snowsight > Projects > Notebooks; create with
# role HR_KIT_ADMIN, warehouse HR_KIT_WH, location HR_KIT.ML). Paste each `# %%` cell
# into its own notebook cell, or convert locally with `jupytext --to ipynb`.
# Packages: snowflake-ml-python, scikit-learn, pandas (add via the notebook Packages menu
# in the warehouse runtime; record exact versions shown there).
#
# Rubric: M1 (reproducible features), M2 (valid chronological evaluation vs baseline,
# uncertainty), M3 (registry versions, default version = rollback, batch scoring).
# Prerequisite: 06_ml.sql step 1-2 (tables HR_KIT.ML.QWI_TURNOVER_SERIES / QWI_SPLIT).
# Model Registry API names (Registry, log_model, show_versions, set_metric, default)
# follow snowflake-ml-python 1.x docs as remembered — verify in account.

# %%
from snowflake.snowpark.context import get_active_session
import pandas as pd
import numpy as np
import sklearn, snowflake.ml

session = get_active_session()
session.query_tag = "hr_kit:06_ml_notebook"
session.use_schema("HR_KIT.ML")
print("sklearn", sklearn.__version__, "| snowflake-ml-python", snowflake.ml.version.VERSION
      if hasattr(snowflake.ml, "version") else "check Packages panel")

# %% Feature table: lags only from strictly earlier quarters (no future leakage)
FEATURE_SQL = """
SELECT series, ts, turnovrs AS y, split,
       LAG(turnovrs, 1) OVER (PARTITION BY series ORDER BY ts) AS lag1,
       LAG(turnovrs, 2) OVER (PARTITION BY series ORDER BY ts) AS lag2,
       LAG(turnovrs, 4) OVER (PARTITION BY series ORDER BY ts) AS lag4,
       QUARTER(ts) AS qtr
FROM HR_KIT.ML.QWI_SPLIT
"""
feat = session.sql(FEATURE_SQL).to_pandas()
feat.columns = [c.lower() for c in feat.columns]
feat = feat.dropna(subset=["lag1", "lag2", "lag4"]).sort_values(["series", "ts"])
print(feat.groupby(["series", "split"]).size())

# Persist the exact feature snapshot used (reproducibility evidence)
session.write_pandas(feat, "QWI_FEATURES_SNAPSHOT", auto_create_table=True, overwrite=True,
                     quote_identifiers=False)
print(session.sql("SELECT HASH_AGG(*) FROM HR_KIT.ML.QWI_FEATURES_SNAPSHOT").collect())

# %% Chronological train/holdout (split was assigned in SQL from the latest 4 quarters)
X_cols = ["lag1", "lag2", "lag4", "qtr"]
train, hold = feat[feat.split == "train"], feat[feat.split == "holdout"]
assert train.groupby("series").ts.max().lt(hold.groupby("series").ts.min()).all(), "leakage!"

from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.compose import ColumnTransformer

pipe = Pipeline([
    ("prep", ColumnTransformer([("num", StandardScaler(), ["lag1", "lag2", "lag4"]),
                                ("q", OneHotEncoder(handle_unknown="ignore"), ["qtr"])])),
    ("model", Ridge(alpha=1.0)),
])
pipe.fit(train[X_cols], train["y"])
hold = hold.assign(pred=pipe.predict(hold[X_cols]))

def mae(a, b): return float(np.mean(np.abs(np.asarray(a) - np.asarray(b))))
metrics = {
    "n_holdout": int(len(hold)),
    "mae_ridge": mae(hold.pred, hold.y),
    "mae_last_value": mae(hold.lag1, hold.y),        # lag1 = previous quarter (naive)
    "mae_seasonal_naive": mae(hold.lag4, hold.y),    # same quarter last year
}
# Residual-based uncertainty band from TRAIN residuals (simple, documented)
resid = train["y"] - pipe.predict(train[X_cols])
metrics["train_resid_q05"], metrics["train_resid_q95"] = map(float, np.quantile(resid, [0.05, 0.95]))
print(metrics)
# NOTE: holdout lag1/lag2 for the 2nd+ holdout quarter use actual holdout values (one-step-ahead
# evaluation). State this; a multi-step recursive evaluation is stricter and comparable to FORECAST.

# %% Model Registry: log, version, metrics, default version (rollback path)
from snowflake.ml.registry import Registry

reg = Registry(session=session, database_name="HR_KIT", schema_name="ML")
MODEL_NAME = "QWI_TURNOVER_RIDGE"
version = "v" + pd.Timestamp.utcnow().strftime("%Y%m%d_%H%M%S")
mv = reg.log_model(
    pipe,
    model_name=MODEL_NAME,
    version_name=version,
    sample_input_data=train[X_cols].head(20),
    comment="Public QWI turnover; lag features; chronological holdout of 4 quarters; kit v0.1",
    metrics=metrics,
    conda_dependencies=["scikit-learn"],
)
print(reg.get_model(MODEL_NAME).show_versions())

# %% Batch scoring through the registered version (warehouse inference)
hold_sp = session.create_dataframe(hold[["series", "ts"] + X_cols])
scored = mv.run(hold_sp, function_name="predict")
scored.write.save_as_table("HR_KIT.ML.QWI_RIDGE_SCORED", mode="overwrite")
session.table("HR_KIT.ML.QWI_RIDGE_SCORED").show()

# %% Rollback drill: set the default to a previous version (if one exists), then back
m = reg.get_model(MODEL_NAME)
versions = m.show_versions()
print(versions[["name", "created_on"]] if "name" in versions.columns else versions)
# m.default = "<previous_version_name>"   # roll back
# m.default = version                     # restore
# Record: time taken, who did it, and that scoring used the expected version (mv.version_name).

# %% Evidence summary row for evidence_template.csv
print({"step": "S06c", "model": MODEL_NAME, "version": version, **metrics})
