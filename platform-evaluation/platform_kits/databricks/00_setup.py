# Databricks notebook source
# MAGIC %md
# MAGIC # 00 · Setup: catalog, schemas, volume
# MAGIC
# MAGIC **Free Edition:** yes. **Compute:** serverless notebook.
# MAGIC Rubric evidence: *Operations — deployment from version-controlled artifacts* (O1), *Governance* (G1 baseline).
# MAGIC
# MAGIC Creates the schemas and the managed volume that hold the uploaded public lake files and the read-only
# MAGIC synthetic benchmark fixtures. The upload itself is done outside this notebook (see README step 2).

# COMMAND ----------

# MAGIC %run ./_config

# COMMAND ----------

# Free Edition normally lets you create schemas in the default `workspace` catalog.
# Creating a NEW catalog may need metastore admin / a paid workspace; on failure keep CATALOG="workspace".
try:
    spark.sql(f"CREATE CATALOG IF NOT EXISTS {CATALOG}")
except Exception as e:
    print(f"CREATE CATALOG skipped ({type(e).__name__}): use an existing catalog. Detail: {str(e)[:300]}")

for s, comment in [
    (SCHEMA, "Public HR / labor-market reference data (O*NET, IPEDS, QCEW, QWI, SUCSS). No institutional data."),
    (EVAL_SCHEMA, "Trial-run outputs, AI results, scores and run logs for the platform evaluation kit."),
    (GOV_SCHEMA, "Synthetic fixtures for governance tests only. Fictional people; no institutional data."),
    (PIPELINE_SCHEMA, "Lakeflow declarative pipeline target for the public lake (bronze/silver)."),
]:
    spark.sql(f"CREATE SCHEMA IF NOT EXISTS {CATALOG}.{s} COMMENT '{comment}'")

spark.sql(f"CREATE VOLUME IF NOT EXISTS {CATALOG}.{SCHEMA}.{VOLUME} "
          "COMMENT 'Uploaded public lake Parquet (silver/) and synthetic benchmark fixtures (benchmark_v1/)'")

# Tags on schemas (key/value strings). Governed tags (account-level allowed values) are optional; see 07.
spark.sql(f"ALTER SCHEMA {CATALOG}.{SCHEMA} SET TAGS ('data_classification' = 'public', 'project' = 'hr_platform_eval')")
spark.sql(f"ALTER SCHEMA {CATALOG}.{GOV_SCHEMA} SET TAGS ('data_classification' = 'synthetic', 'project' = 'hr_platform_eval')")

# COMMAND ----------

# Create the volume folders (uploads go into these).
for p in [SILVER_PATH, BENCHMARK_PATH, INJECT_PATH]:
    dbutils.fs.mkdirs(p)
display(dbutils.fs.ls(VOLUME_ROOT))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Upload (do this now, then re-run the listing cell above)
# MAGIC
# MAGIC Option A — Catalog Explorer → the volume → **Upload to this volume**.
# MAGIC
# MAGIC Option B — Databricks CLI from the repository root on your laptop (verify flags with `databricks fs cp --help`):
# MAGIC ```
# MAGIC databricks fs cp -r platform-evaluation/data/lake/contract  dbfs:/Volumes/<catalog>/hr_public/lake/silver
# MAGIC databricks fs cp -r platform-evaluation/benchmark/fixtures dbfs:/Volumes/<catalog>/hr_public/lake/benchmark_v1
# MAGIC databricks fs cp    platform-evaluation/benchmark/manifest.json dbfs:/Volumes/<catalog>/hr_public/lake/benchmark_v1/manifest.json
# MAGIC databricks fs cp    platform-evaluation/benchmark/documents.md  dbfs:/Volumes/<catalog>/hr_public/lake/benchmark_v1/documents.md
# MAGIC ```
# MAGIC Upload **copies**. Never edit the benchmark files in the repository; the manifest hashes are frozen.

# COMMAND ----------

# Verify uploaded benchmark fixtures against the frozen manifest hashes (read-only check).
import hashlib, json, os
man_path = f"{BENCHMARK_PATH}/manifest.json"
if os.path.exists(man_path):
    manifest = json.load(open(man_path))
    rows = []
    for f in manifest["files"]:
        if not (f["path"].startswith("benchmark/fixtures/") or f["path"] == "benchmark/documents.md"):
            continue
        name = f["path"].split("/")[-1]
        local = f"{BENCHMARK_PATH}/{name}"
        got = hashlib.sha256(open(local, "rb").read()).hexdigest() if os.path.exists(local) else None
        rows.append((name, f["sha256"], got, got == f["sha256"]))
    hash_df = spark.createDataFrame(rows, "file STRING, expected_sha256 STRING, uploaded_sha256 STRING, match BOOLEAN")
    display(hash_df)
    ok = all(r[3] for r in rows)
    log_run("00_benchmark_hash_check", "pass" if ok else "fail", json.dumps([r[0] for r in rows if not r[3]]))
    assert ok, "Uploaded fixtures do not match benchmark/manifest.json. Re-upload; do not edit the manifest."
else:
    print("manifest.json not uploaded yet; hash check skipped (re-run after upload).")

# COMMAND ----------

log_run("00_setup", "pass", f"{CATALOG}.{SCHEMA}, {VOLUME_ROOT}")
