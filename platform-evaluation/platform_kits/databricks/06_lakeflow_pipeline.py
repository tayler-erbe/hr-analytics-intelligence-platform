# Databricks notebook source
# MAGIC %md
# MAGIC # 06 · Lakeflow Spark Declarative Pipeline source: bronze → silver with expectations
# MAGIC
# MAGIC **Do not run this notebook interactively.** Add it as the source file of a pipeline (see `06b_pipeline_runbook`).
# MAGIC API: `from pyspark import pipelines as dp` (the older `import dlt` still works but is superseded).
# MAGIC Expectation decorators sit between the dataset decorator and the function.
# MAGIC
# MAGIC **Free Edition:** pipelines are serverless-only with one active pipeline per type (verify current quota).
# MAGIC Pipeline configuration key required: `kit.volume_root` = `/Volumes/<catalog>/hr_public/lake`.
# MAGIC
# MAGIC Rubric evidence: *I1 source integration*, *I2 grain*, *I3 incremental recovery* (Auto Loader file tracking + replay test),
# MAGIC *O1 deployment/recovery* (pipeline definition in version control), *B3 traceability* (`_source_file`, `_ingested_at`).

# COMMAND ----------

from pyspark import pipelines as dp
from pyspark.sql import functions as F
from pyspark.sql.window import Window

VOLUME_ROOT = spark.conf.get("kit.volume_root")
LANDING = f"{VOLUME_ROOT}/landing"

def _autoload(folder: str):
    return (spark.readStream.format("cloudFiles")
            .option("cloudFiles.format", "parquet")
            .option("cloudFiles.schemaEvolutionMode", "rescue")      # unexpected columns land in _rescued_data
            .load(f"{LANDING}/{folder}")
            .withColumn("_source_file", F.col("_metadata.file_path"))
            .withColumn("_ingested_at", F.current_timestamp()))

# ---------------- Bronze (append-only, one row per source row per file) ----------------

@dp.table(name="bronze_qwi_higher_ed", comment="Raw Census QWI NAICS 6113 rows as landed. Append-only; file path retained.")
def bronze_qwi_higher_ed():
    return _autoload("qwi_higher_ed")

@dp.table(name="bronze_qcew_area", comment="Raw BLS QCEW IL county rows as landed.")
def bronze_qcew_area():
    return _autoload("qcew_area")

@dp.table(name="bronze_sucss_class", comment="Raw SUCSS public class catalog rows as landed.")
def bronze_sucss_class():
    return _autoload("sucss_class")

# ---------------- Silver (validated, deduplicated on natural key) ----------------
# Column names follow the lake contract draft; adjust here if 01's contract check reported differences.

QWI_RULES = {
    "valid_year": "CAST(year AS INT) BETWEEN 1990 AND 2030",
    "valid_quarter": "CAST(quarter AS INT) BETWEEN 1 AND 4",
    "geography_present": "geography IS NOT NULL",
    "nonneg_emp": "emp IS NULL OR emp >= 0",
    "nonneg_flows": "(hira IS NULL OR hira >= 0) AND (sep IS NULL OR sep >= 0)",
    "turnover_is_rate": "turnovrs IS NULL OR (turnovrs >= 0 AND turnovrs <= 1)",
    "no_rescued_columns": "_rescued_data IS NULL",
}

# Validation runs BEFORE deduplication: otherwise a later invalid row could win the dedup and displace a valid one.

@dp.temporary_view(name="qwi_validated")
@dp.expect_all_or_drop(QWI_RULES)
def qwi_validated():
    return spark.read.table("bronze_qwi_higher_ed")

@dp.materialized_view(name="silver_qwi_higher_ed",
                      comment="Validated QWI rows, one per geography x industry x year x quarter x sex x agegrp (latest valid landed file wins).")
def silver_qwi_higher_ed():
    key = ["geography", "industry", "year", "quarter", "sex", "agegrp"]
    w = Window.partitionBy(*key).orderBy(F.col("_ingested_at").desc(), F.col("_source_file").desc())
    return spark.read.table("qwi_validated").withColumn("_rn", F.row_number().over(w)).where("_rn = 1").drop("_rn")

@dp.materialized_view(name="quarantine_qwi_higher_ed", comment="QWI rows failing any silver rule (kept for review, never deleted).")
def quarantine_qwi_higher_ed():
    failed = " OR ".join(f"NOT coalesce({r}, false)" for r in QWI_RULES.values())
    return spark.read.table("bronze_qwi_higher_ed").where(failed)

@dp.temporary_view(name="qcew_area_validated")
@dp.expect_or_drop("valid_qtr", "CAST(qtr AS INT) BETWEEN 1 AND 4")
@dp.expect_or_drop("area_present", "area_fips IS NOT NULL")
@dp.expect("nonneg_employment", "month3_emplvl IS NULL OR month3_emplvl >= 0")   # warn only
def qcew_area_validated():
    return spark.read.table("bronze_qcew_area")

@dp.materialized_view(name="silver_qcew_area", comment="Validated QCEW county rows; suppressed cells (disclosure_code = 'N') kept with null values.")
def silver_qcew_area():
    key = ["area_fips", "own_code", "industry_code", "year", "qtr"]
    w = Window.partitionBy(*key).orderBy(F.col("_ingested_at").desc(), F.col("_source_file").desc())
    return spark.read.table("qcew_area_validated").withColumn("_rn", F.row_number().over(w)).where("_rn = 1").drop("_rn")

@dp.temporary_view(name="sucss_validated")
@dp.expect_or_fail("record_id_present", "source_record_id IS NOT NULL")   # structural failure stops the update
@dp.expect_or_drop("title_present", "class_title IS NOT NULL AND length(trim(class_title)) > 0")
def sucss_validated():
    return spark.read.table("bronze_sucss_class")

@dp.materialized_view(name="silver_sucss_class", comment="SUCSS class catalog; unique on source_record_id. class_code 1164 legitimately appears twice.")
def silver_sucss_class():
    w = Window.partitionBy("source_record_id").orderBy(F.col("_ingested_at").desc())
    return spark.read.table("sucss_validated").withColumn("_rn", F.row_number().over(w)).where("_rn = 1").drop("_rn")
