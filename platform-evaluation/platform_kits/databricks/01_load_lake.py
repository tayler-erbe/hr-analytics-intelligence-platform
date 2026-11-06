# Databricks notebook source
# MAGIC %md
# MAGIC # 01 · Load the public lake into Delta tables
# MAGIC
# MAGIC **Free Edition:** yes. **Compute:** serverless notebook.
# MAGIC Rubric evidence: *I1 source integration*, *I2 temporal/grain correctness* (key uniqueness),
# MAGIC *B3 traceability* (comments, source_id/source_vintage, file hashes), *O2 handover*.
# MAGIC
# MAGIC Reads `silver/<table>.parquet` from the volume, checks the planned contract, writes managed Delta tables in
# MAGIC `<catalog>.hr_public`, records row counts and file hashes, and adds table/column comments and tags.
# MAGIC Synthetic benchmark fixtures are loaded into the governance schema for 07 and 09 (read-only copies).

# COMMAND ----------

# MAGIC %run ./_config

# COMMAND ----------

import hashlib, os, json
from pyspark.sql import functions as F

def _parquet_location(table: str):
    """Contract: data/lake/contract/<table>.parquet. Accept a single file or a directory of part files."""
    p = f"{SILVER_PATH}/{table}.parquet"
    return p if os.path.exists(p) else None

def _sha256_path(p: str) -> str:
    h = hashlib.sha256()
    files = [p] if os.path.isfile(p) else sorted(
        os.path.join(r, f) for r, _, fs in os.walk(p) for f in fs if f.endswith(".parquet"))
    for f in files:
        with open(f, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
    return h.hexdigest()

# COMMAND ----------

# MAGIC %md
# MAGIC ## Contract check (run before loading)
# MAGIC Strict on contract key columns and `source_id`/`source_vintage`; advisory on the assumed non-key names in `_config.COL`.

# COMMAND ----------

contract_rows = []
assumed = set(COL.values())
for t in LAKE_TABLES + PENDING_TABLES:
    loc = _parquet_location(t)
    if loc is None:
        contract_rows.append((t, "missing", None, None, None, t in PENDING_TABLES))
        continue
    cols = spark.read.parquet(loc).columns
    missing_keys = [c for c in CONTRACT_KEYS.get(t, []) + COMMON_COLS if c not in cols]
    seen_assumed = sorted(assumed.intersection(cols))
    contract_rows.append((t, "present", ",".join(cols), ",".join(missing_keys), ",".join(seen_assumed), t in PENDING_TABLES))

contract_df = spark.createDataFrame(contract_rows,
    "table STRING, status STRING, columns STRING, missing_contract_cols STRING, assumed_cols_found STRING, pending BOOLEAN")
display(contract_df)
bad = [r for r in contract_rows if r[1] == "present" and r[3]]
missing_required = [r[0] for r in contract_rows if r[1] == "missing" and not r[5]]
print("Missing (non-pending) tables:", missing_required)
print("Tables missing contract columns:", [(r[0], r[3]) for r in bad])
# Record the mismatch as a limitation instead of silently renaming columns.
log_run("01_contract_check", "pass" if not bad else "mismatch",
        json.dumps({"missing_tables": missing_required, "missing_cols": {r[0]: r[3] for r in bad}}))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Load to Delta (full refresh; idempotent)
# MAGIC `CREATE OR REPLACE TABLE` keeps Delta history, so a re-run is recoverable with `DESCRIBE HISTORY` / `RESTORE`.

# COMMAND ----------

TABLE_COMMENTS = {
    "onet_occupation": "O*NET 31.0 occupations (CC BY 4.0, USDOL/ETA). One row per O*NET-SOC code.",
    "onet_task_statement": "O*NET task statements. Grain: onetsoc_code x task_id.",
    "onet_task_rating": "O*NET task ratings. Grain: onetsoc_code x task_id x scale_id.",
    "onet_element_rating": "O*NET element ratings (skills, knowledge, abilities, work activities/context/styles).",
    "onet_technology_skill": "O*NET technology skills with hot/in-demand flags.",
    "onet_alternate_title": "O*NET alternate titles.",
    "onet_job_zone": "O*NET job zone (1-5) per occupation.",
    "sucss_class": "Illinois SUCSS public class catalog. Catalog records are NOT employees or vacancies. Code 1164 has two records.",
    "sucss_onet_candidate": "Unreviewed lexical SUCSS->O*NET title candidates. Score is similarity, not probability.",
    "ipeds_institution": "IPEDS HD institution directory. Grain: unitid.",
    "ipeds_staff_by_occupation": "IPEDS Fall staff by occupation (S_OC), long format.",
    "ipeds_instructional_staff": "IPEDS instructional staff by rank/tenure (S_IS).",
    "ipeds_new_hires": "IPEDS new hires by occupation (S_NH).",
    "ipeds_salary_instructional": "IPEDS instructional salaries (SAL_IS).",
    "ipeds_salary_noninstructional": "IPEDS non-instructional salary outlays (SAL_NIS).",
    "ipeds_employees_by_position": "IPEDS employees by assigned position (EAP).",
    "ipeds_enrollment_12mo": "IPEDS 12-month enrollment (EFFY); context for staff ratios.",
    "qcew_industry": "BLS QCEW by industry (incl. NAICS 611310), US + IL. Suppressed cells stay suppressed.",
    "qcew_area": "BLS QCEW for IL counties (Champaign 17019, Cook 17031, Sangamon 17167).",
    "qwi_higher_ed": "Census QWI for NAICS 6113: employment, hires, separations, turnover, earnings.",
    "acs_county_labor": "ACS 5-year county labor force / earnings context.",
    "aei_task_usage": "Anthropic Economic Index task usage share. Usage share is not automation or job risk.",
    "bls_oews": "BLS OEWS (pending in lake contract).",
    "bls_projections": "BLS employment projections (pending in lake contract).",
}
COLUMN_COMMENTS = {
    "source_id": "Lake source identifier (see lake/sources.json).",
    "source_vintage": "Release or vintage of the source extract.",
    "onetsoc_code": "O*NET-SOC 2019 code (string, leading zeros preserved).",
    "unitid": "IPEDS institution identifier.",
    "area_fips": "FIPS area code (string).",
    "source_record_id": "SUCSS catalog source record id (preserved from the public response).",
}

load_rows = []
for t in LAKE_TABLES + PENDING_TABLES:
    loc = _parquet_location(t)
    if loc is None:
        load_rows.append((t, "skipped_missing", None, None, None))
        continue
    try:
        df = spark.read.parquet(loc)
        df.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(FQ(t))
        n = spark.table(FQ(t)).count()
        spark.sql(f"COMMENT ON TABLE {FQ(t)} IS '{TABLE_COMMENTS.get(t, 'Public lake table').replace(chr(39), '')}'")
        for c, txt in COLUMN_COMMENTS.items():
            if c in df.columns:
                spark.sql(f"ALTER TABLE {FQ(t)} ALTER COLUMN {c} COMMENT '{txt}'")
        spark.sql(f"ALTER TABLE {FQ(t)} SET TAGS ('data_classification'='public', 'lake_layer'='silver', "
                  f"'lake_contract'='draft_v0.1')")
        load_rows.append((t, "loaded", n, _sha256_path(loc), loc))
    except Exception as e:
        load_rows.append((t, f"error: {type(e).__name__}: {str(e)[:300]}", None, None, loc))

load_df = spark.createDataFrame(load_rows, "table STRING, status STRING, row_count BIGINT, file_sha256 STRING, source_path STRING") \
    .withColumn("run_id", F.lit(RUN_ID)).withColumn("loaded_at", F.current_timestamp())
load_df.write.mode("append").saveAsTable(FQE("load_manifest"))
display(load_df)
log_run("01_load", "pass" if all(r[1] in ("loaded", "skipped_missing") for r in load_rows) else "partial",
        json.dumps({r[0]: r[1] for r in load_rows}))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Grain checks
# MAGIC Duplicate keys are reported, never silently deduplicated. Expect `sucss_class` to be unique on
# MAGIC `source_record_id` while `class_code` 1164 appears twice by design.

# COMMAND ----------

grain_rows = []
existing = {r.tableName for r in spark.sql(f"SHOW TABLES IN {CATALOG}.{SCHEMA}").collect()}
for t, keys in CONTRACT_KEYS.items():
    if t not in existing:
        continue
    cols = spark.table(FQ(t)).columns
    if not all(k in cols for k in keys):
        grain_rows.append((t, ",".join(keys), None, None, "key columns missing"))
        continue
    k = ", ".join(keys)
    r = spark.sql(f"SELECT COUNT(*) AS n, COUNT(DISTINCT {k}) AS d FROM {FQ(t)}").first()
    grain_rows.append((t, k, r.n, r.d, "unique" if r.n == r.d else "DUPLICATE KEYS - investigate"))
grain_df = spark.createDataFrame(grain_rows, "table STRING, key STRING, rows BIGINT, distinct_keys BIGINT, result STRING")
display(grain_df)
grain_df.withColumn("run_id", F.lit(RUN_ID)).write.mode("append").saveAsTable(FQE("grain_checks"))

# COMMAND ----------

# Known SUCSS edge case: expect 2 rows for class_code 1164 (two source records, different titles).
display(spark.sql(f"SELECT * FROM {FQ('sucss_class')} WHERE {COL['class_code']} = '1164'"))

# COMMAND ----------

# Load the synthetic benchmark fixtures (read-only copies) for 07 governance and 09 leakage checks.
fixture_rows = []
for name in ["positions", "appointments", "ml_features", "expected_runs", "job_attempts"]:
    p = f"{BENCHMARK_PATH}/{name}.jsonl"
    if not os.path.exists(p):
        fixture_rows.append((name, "missing", None)); continue
    df = spark.read.json(p)
    df.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(FQG(f"bm_{name}"))
    spark.sql(f"COMMENT ON TABLE {FQG('bm_' + name)} IS 'Benchmark v1.0 synthetic fixture copy (fictional). Source of truth is the repo file + manifest hash.'")
    fixture_rows.append((name, "loaded", df.count()))
display(spark.createDataFrame(fixture_rows, "fixture STRING, status STRING, rows BIGINT"))
# Expected from benchmark manifest: positions 5, appointments 6, ml_features 2, expected_runs 4, job_attempts 5.

# COMMAND ----------

# MAGIC %md
# MAGIC ## Evidence to capture
# MAGIC - Screenshot of the contract check and `load_manifest` (row counts + file hashes).
# MAGIC - `DESCRIBE HISTORY <catalog>.hr_public.onet_occupation` after a second run (shows replace is versioned).
# MAGIC - Catalog Explorer screenshot of comments and tags on one table.
# MAGIC - Record any contract mismatches as limitations of the lake build, not of Databricks.
