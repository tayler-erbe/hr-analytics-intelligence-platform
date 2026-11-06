# Databricks notebook source
# MAGIC %md
# MAGIC # 99 · Cost evidence and cleanup
# MAGIC
# MAGIC Run after each session. `system.billing.usage` is the source of truth for billable usage (budget alert emails can differ).
# MAGIC In Free Edition, system billing tables may be unavailable or show no dollar charges. Record that, and record quota
# MAGIC messages instead. Rubric evidence: *C1 measured operating cost*, *C2 portability/recovery* (export list), *O1*.

# COMMAND ----------

# MAGIC %run ./_config

# COMMAND ----------

def try_display(title, sql):
    print("==", title)
    try:
        df = spark.sql(sql); display(df); return df
    except Exception as e:
        print("unavailable:", type(e).__name__, str(e)[:300]); log_run("99_" + title[:40], "unavailable", str(e)[:500]); return None

# Usage by product and SKU over the trial window (list price estimate; institutional pricing differs).
usage = try_display("usage by product/sku (14 days)", """
SELECT u.usage_date, u.billing_origin_product, u.sku_name, u.usage_unit,
       SUM(u.usage_quantity) AS quantity,
       ROUND(SUM(u.usage_quantity * lp.pricing.default), 2) AS est_list_cost   -- docs also show pricing.effective_list.default; verify
FROM system.billing.usage u
LEFT JOIN system.billing.list_prices lp
  ON lp.sku_name = u.sku_name AND lp.cloud = u.cloud AND lp.usage_unit = u.usage_unit
 AND u.usage_start_time >= lp.price_start_time AND (lp.price_end_time IS NULL OR u.usage_start_time < lp.price_end_time)
WHERE u.usage_date >= current_date() - 14
GROUP BY ALL ORDER BY u.usage_date DESC, est_list_cost DESC NULLS LAST""")

try_display("usage attributed to me (serverless notebooks/jobs)", """
SELECT usage_date, billing_origin_product, SUM(usage_quantity) AS dbus
FROM system.billing.usage
WHERE usage_date >= current_date() - 14 AND identity_metadata.run_as = current_user()
GROUP BY ALL ORDER BY usage_date DESC""")

try_display("usage by custom tag project=hr_platform_eval (via usage policy)", """
SELECT usage_date, billing_origin_product, SUM(usage_quantity) AS dbus
FROM system.billing.usage
WHERE usage_date >= current_date() - 14 AND custom_tags['project'] = 'hr_platform_eval'
GROUP BY ALL ORDER BY usage_date DESC""")

# COMMAND ----------

# Save the snapshot with the run id so cost evidence is reproducible.
if usage is not None:
    from pyspark.sql import functions as F
    usage.withColumn("run_id", F.lit(RUN_ID)).withColumn("captured_at", F.current_timestamp()) \
        .write.mode("append").option("mergeSchema", "true").saveAsTable(FQE("cost_snapshots"))
display(spark.sql(f"SELECT step, status, rows_sent_to_ai, detail, executed_at FROM {FQE('run_log')} ORDER BY executed_at DESC LIMIT 100"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Cost guardrails (set these up BEFORE step 02 on a paid workspace)
# MAGIC 1. **Serverless usage policy** (formerly *budget policy*; the billing column `budget_policy_id` is deprecated in favour of
# MAGIC    `usage_policy_id`). Create one with the tag `project = hr_platform_eval` and assign it to yourself, so serverless usage
# MAGIC    is attributable in `custom_tags`.
# MAGIC 2. **Budget** (account console → Budgets) scoped to that tag, with an email alert at a small threshold, such as USD 25.
# MAGIC 3. Keep the `CAP_*` row caps in `_config`. AI Search endpoints and Apps cost money while they exist or run, so delete or stop them below.
# MAGIC 4. Use triggered (not continuous) pipelines and AI Search sync.

# COMMAND ----------

# MAGIC %md ## Cleanup (uncomment what you want to remove; keep result tables as evidence)

# COMMAND ----------

# AI Search index and endpoint (billed while they exist on paid workspaces; Free Edition allows one endpoint):
# %pip install databricks-ai-search  (run in a separate cell first)
# from databricks.ai_search.client import AISearchClient
# c = AISearchClient()
# c.delete_index(endpoint_name=AI_SEARCH_ENDPOINT, index_name=FQ("onet_occupation_doc_idx"))
# c.delete_endpoint(name=AI_SEARCH_ENDPOINT)

# App:   databricks apps stop hr-role-explorer      (CLI; verify)
# Pipeline: delete from Jobs & Pipelines UI, or keep stopped (triggered pipelines do not run between updates).
# Data (only after evidence is exported):
# spark.sql(f"DROP SCHEMA {CATALOG}.{PIPELINE_SCHEMA} CASCADE")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Exit / portability evidence (C2)
# MAGIC Export and store with the evidence pack:
# MAGIC - Notebooks: these files are already in Git; export any UI-edited copy as source (`.py`).
# MAGIC - Metric view YAML: `SHOW CREATE TABLE <catalog>.hr_public.mv_ipeds_staffing`.
# MAGIC - Genie Agent configuration: the API/CLI export if available (`databricks genie ...`; verify), else screenshots and the instruction text.
# MAGIC - Pipeline: export as a bundle (YAML). App: source folder plus `app.yaml`.
# MAGIC - Results: `hr_eval_results.*` tables as Parquet/CSV (`spark.table(...).write.parquet('/Volumes/.../exports/...')`).
# MAGIC - MLflow: runs and model artifacts via `mlflow.artifacts.download_artifacts`.
# MAGIC Then try restoring into a clean schema and record the time it takes and anything that would not restore.
