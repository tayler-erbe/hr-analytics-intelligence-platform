# Databricks notebook source
# MAGIC %md
# MAGIC # 06b · Pipeline runbook: landing batches, failure injection, replay and event-log evidence
# MAGIC
# MAGIC Runs interactively (serverless notebook). Drives the pipeline defined in `06_lakeflow_pipeline` through four updates:
# MAGIC
# MAGIC | Update | Action before the update | Expected evidence |
# MAGIC |---|---|---|
# MAGIC | U1 | Land QWI batch 1 (older years), QCEW, SUCSS | Bronze = landed rows; silver keys unique |
# MAGIC | U2 | Land QWI batch 2 (latest year) | Only new file ingested (Auto Loader); silver grows by batch-2 keys |
# MAGIC | U3 | Land an **injected bad file** (invalid quarter, negative hires, turnover > 1, extra column) | Rows dropped from silver, visible in quarantine and expectation metrics |
# MAGIC | U4 | **Replay**: land a copy of batch 2 under a new file name | Bronze grows (append-only), silver row count **unchanged** (dedup on natural key) |
# MAGIC
# MAGIC Then: interrupt an update mid-run (Stop button) and re-run → record whether bronze duplicates appeared (should not; checkpointed).

# COMMAND ----------

# MAGIC %run ./_config

# COMMAND ----------

LANDING = f"{VOLUME_ROOT}/landing"
for d in ["qwi_higher_ed", "qcew_area", "sucss_class"]:
    dbutils.fs.mkdirs(f"{LANDING}/{d}")

qwi = spark.read.parquet(f"{SILVER_PATH}/qwi_higher_ed.parquet")
yr = COL["qwi_year"]
latest = qwi.agg({yr: "max"}).first()[0]
print("QWI latest year:", latest)

def land(df, folder, name):
    # Write a single parquet file per batch so Auto Loader sees one new file.
    tmp = f"{LANDING}/_tmp_{name}"
    df.coalesce(1).write.mode("overwrite").parquet(tmp)
    part = [f.path for f in dbutils.fs.ls(tmp) if f.name.endswith(".parquet")][0]
    dbutils.fs.cp(part, f"{LANDING}/{folder}/{name}.parquet")
    dbutils.fs.rm(tmp, recurse=True)
    print("landed", folder, name, df.count())

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step U1 — land batch 1, then create and run the pipeline
# MAGIC 1. Run the next cell.
# MAGIC 2. **Jobs & Pipelines → Create → ETL pipeline** (UI label may differ; verify). Name `hr_public_lake_pipeline`.
# MAGIC    Source: this kit's `06_lakeflow_pipeline` notebook/file. Default catalog = your catalog, schema = `hr_public_pipeline`.
# MAGIC    Compute: serverless. Mode: triggered. Configuration: `kit.volume_root` = the `VOLUME_ROOT` printed by `_config`.
# MAGIC 3. Click **Start**. Record duration and screenshot the graph. Optionally export the pipeline as a bundle (YAML) for O1 evidence.

# COMMAND ----------

land(qwi.where(f"{yr} < {latest}"), "qwi_higher_ed", "qwi_batch1")
land(spark.read.parquet(f"{SILVER_PATH}/qcew_area.parquet"), "qcew_area", "qcew_batch1")
land(spark.read.parquet(f"{SILVER_PATH}/sucss_class.parquet"), "sucss_class", "sucss_batch1")

# COMMAND ----------

# MAGIC %md ## Step U2 — land batch 2, then Start the pipeline again

# COMMAND ----------

land(qwi.where(f"{yr} = {latest}"), "qwi_higher_ed", "qwi_batch2")

# COMMAND ----------

# MAGIC %md ## Step U3 — inject bad rows, then Start

# COMMAND ----------

from pyspark.sql import functions as F
base = qwi.where(f"{yr} = {latest}").limit(4)
bad = (base.withColumn(COL["qwi_quarter"], F.when(F.monotonically_increasing_id() % 4 == 0, F.lit(7)).otherwise(F.col(COL["qwi_quarter"])))
           .withColumn(COL["qwi_hires"], F.lit(-5))
           .withColumn(COL["qwi_turnover"], F.lit(1.7))
           .withColumn("unexpected_column", F.lit("schema drift test")))
land(bad, "qwi_higher_ed", "qwi_injected_bad")

# COMMAND ----------

# MAGIC %md ## Step U4 — replay batch 2 under a new name, then Start

# COMMAND ----------

land(qwi.where(f"{yr} = {latest}"), "qwi_higher_ed", "qwi_batch2_replay")

# COMMAND ----------

# MAGIC %md ## Evidence queries (after each update)

# COMMAND ----------

P = f"{CATALOG}.{PIPELINE_SCHEMA}"
display(spark.sql(f"""
SELECT 'bronze_qwi' t, COUNT(*) n FROM {P}.bronze_qwi_higher_ed UNION ALL
SELECT 'silver_qwi', COUNT(*) FROM {P}.silver_qwi_higher_ed UNION ALL
SELECT 'quarantine_qwi', COUNT(*) FROM {P}.quarantine_qwi_higher_ed UNION ALL
SELECT 'silver_qwi_distinct_keys', COUNT(DISTINCT geography, industry, year, quarter, sex, agegrp) FROM {P}.silver_qwi_higher_ed UNION ALL
SELECT 'bronze_files', COUNT(DISTINCT _source_file) FROM {P}.bronze_qwi_higher_ed"""))

# COMMAND ----------

# Expectation metrics from the pipeline event log (table-valued function; verify accepted argument form in workspace).
display(spark.sql(f"""
SELECT timestamp, details:flow_progress.data_quality.expectations AS expectations
FROM event_log(TABLE({P}.silver_qwi_higher_ed))   -- expectation metrics are reported on the qwi_validated flow
WHERE event_type = 'flow_progress' AND details:flow_progress.data_quality IS NOT NULL
ORDER BY timestamp DESC"""))

# COMMAND ----------

# Record the outcome of each update (fill in after looking at the numbers above).
log_run("06_pipeline_U1_U4", "recorded", "bronze/silver/quarantine counts captured; see screenshots")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Evidence to capture
# MAGIC - Counts after U1–U4 (expect silver unchanged at U4 and quarantine > 0 at U3), event-log expectation metrics.
# MAGIC - Pipeline graph screenshot, update durations, and the interrupted-update recovery result.
# MAGIC - Schema drift: whether `unexpected_column` landed in `_rescued_data` and was quarantined.
