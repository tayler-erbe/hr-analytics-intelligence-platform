# Databricks notebook source
# MAGIC %md
# MAGIC # 07 · Governance: tags, row filters, column masks, lineage, audit, data classification
# MAGIC
# MAGIC Uses the **synthetic** benchmark v1.0 appointments (fictional PERSON1–3). Implements the benchmark's proposed test access policy:
# MAGIC
# MAGIC | Role (account group) | May see |
# MAGIC |---|---|
# MAGIC | `T1_ANALYST` | appointment detail for department T1 only |
# MAGIC | `DS_REVIEWER` | appointment detail for T1 and T2 |
# MAGIC | `AGGREGATE_VIEWER` | approved aggregates only; groups with < 3 distinct people suppressed (whole org = 3 is shown; both departments suppressed) |
# MAGIC
# MAGIC | Feature | Docs status (2026-11-06 search) | Free Edition |
# MAGIC |---|---|---|
# MAGIC | Table-level `SET ROW FILTER` / `SET MASK` | GA | Expected yes (verify) |
# MAGIC | ABAC `CREATE POLICY` on governed tags | Docs: policies need DBR 16.4+; MANAGE on the object + EXECUTE on UDF | **Verify**; governed tags are account-level |
# MAGIC | `system.access.table_lineage` / `column_lineage` | GA; retention 365 vs 395 days (docs disagree) | System tables access in Free Edition: verify |
# MAGIC | `system.access.audit` | GA | Verify |
# MAGIC | Data Classification → `system.data_classification.results` | Release notes say GA; system-table page still says Public Preview | Verify; serverless only |
# MAGIC
# MAGIC **Testing limitation:** a single-user Free Edition account can only test audiences by changing *your own* group membership
# MAGIC between runs. Real multi-user and service-principal tests (apps, Genie, agents) need a paid workspace with test identities.
# MAGIC Rubric evidence: *G1 identity/row-column controls*, *G2 lineage/audit and AI boundary controls*, gate "negative access tests".

# COMMAND ----------

# MAGIC %run ./_config

# COMMAND ----------

G = lambda t: FQG(t)
spark.sql(f"""
CREATE OR REPLACE TABLE {G('appointments_governed')}
COMMENT 'SYNTHETIC benchmark v1.0 appointments (fictional). Governance test fixture only.'
AS SELECT appointment_id, department_id, CAST(effective_from AS DATE) effective_from, CAST(effective_to AS DATE) effective_to,
          CAST(fte AS DECIMAL(5,2)) fte, person_id, position_id, CAST(recorded_on AS DATE) recorded_on, CAST(revision AS INT) revision, title
FROM {G('bm_appointments')}
""")
# Tags (key/value). For ABAC, create governed tags at account level first (Catalog → Governed tags; verify UI name).
spark.sql(f"ALTER TABLE {G('appointments_governed')} SET TAGS ('data_classification' = 'synthetic_restricted', 'domain' = 'workforce')")
spark.sql(f"ALTER TABLE {G('appointments_governed')} ALTER COLUMN person_id SET TAGS ('pii' = 'person_identifier_synthetic')")
spark.sql(f"ALTER TABLE {G('appointments_governed')} ALTER COLUMN appointment_id SET TAGS ('pii' = 'record_identifier_synthetic')")
display(spark.sql(f"SELECT * FROM {CATALOG}.information_schema.column_tags WHERE schema_name = '{GOV_SCHEMA}'"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Groups
# MAGIC Create account groups `T1_ANALYST`, `DS_REVIEWER`, `AGGREGATE_VIEWER` (Settings → Identity and access → Groups; Free Edition
# MAGIC workspace admins can usually do this — verify). Grant catalog `USE CATALOG` and schema `USE SCHEMA` to all three.

# COMMAND ----------

for grp in ["T1_ANALYST", "DS_REVIEWER", "AGGREGATE_VIEWER"]:
    try:
        spark.sql(f"GRANT USE CATALOG ON CATALOG {CATALOG} TO `{grp}`")
        spark.sql(f"GRANT USE SCHEMA ON SCHEMA {CATALOG}.{GOV_SCHEMA} TO `{grp}`")
    except Exception as e:
        print(grp, "grant failed (create the group first):", str(e)[:200])
for grp in ["T1_ANALYST", "DS_REVIEWER"]:
    spark.sql(f"GRANT SELECT ON TABLE {G('appointments_governed')} TO `{grp}`")
# AGGREGATE_VIEWER gets NO grant on the detail table — only on the aggregate snapshot below.

# COMMAND ----------

# Row filter + column mask (table-level). Functions run as the querying user.
spark.sql(f"""
CREATE OR REPLACE FUNCTION {G('rf_department')}(department_id STRING)
RETURNS BOOLEAN
COMMENT 'Row filter: DS_REVIEWER sees all; T1_ANALYST sees T1 only; everyone else sees nothing.'
RETURN is_account_group_member('DS_REVIEWER')
    OR (is_account_group_member('T1_ANALYST') AND department_id = 'T1')
""")
spark.sql(f"""
CREATE OR REPLACE FUNCTION {G('cm_person_id')}(person_id STRING)
RETURNS STRING
COMMENT 'Column mask: identifiers visible to DS_REVIEWER/T1_ANALYST; otherwise redacted.'
RETURN CASE WHEN is_account_group_member('DS_REVIEWER') OR is_account_group_member('T1_ANALYST') THEN person_id ELSE '***' END
""")
spark.sql(f"ALTER TABLE {G('appointments_governed')} SET ROW FILTER {G('rf_department')} ON (department_id)")
spark.sql(f"ALTER TABLE {G('appointments_governed')} ALTER COLUMN person_id SET MASK {G('cm_person_id')}")
for grp in ["T1_ANALYST", "DS_REVIEWER", "AGGREGATE_VIEWER"]:
    try:
        spark.sql(f"GRANT EXECUTE ON FUNCTION {G('rf_department')} TO `{grp}`")
        spark.sql(f"GRANT EXECUTE ON FUNCTION {G('cm_person_id')} TO `{grp}`")
    except Exception as e:
        print(grp, str(e)[:150])

# COMMAND ----------

# MAGIC %md
# MAGIC ## Aggregate snapshot with small-cell suppression (owner-computed)
# MAGIC Built by the table owner from an **unfiltered** source (the original fixture copy), using the benchmark's frozen as-of logic
# MAGIC (business date 2026-10-31, knowledge cutoff 2026-11-02). Expected: org = 3 people / 4 appointments / 2.5 FTE; T1 and T2 suppressed.

# COMMAND ----------

spark.sql(f"""
CREATE OR REPLACE TABLE {G('workforce_aggregate_snapshot')}
COMMENT 'Approved aggregates for AGGREGATE_VIEWER. Groups with < 3 distinct people suppressed. Synthetic.'
AS
WITH ranked AS (
  SELECT *, ROW_NUMBER() OVER (PARTITION BY appointment_id, effective_from ORDER BY recorded_on DESC, revision DESC) AS rk
  FROM {G('bm_appointments')} WHERE recorded_on <= '2026-11-02'),
cur AS (SELECT * FROM ranked WHERE rk = 1 AND effective_from <= '2026-10-31' AND (effective_to IS NULL OR effective_to > '2026-10-31')),
grp AS (
  SELECT 'ALL' AS group_level, 'ALL' AS department_id, COUNT(DISTINCT person_id) hc, COUNT(*) appts, SUM(fte) fte FROM cur
  UNION ALL
  SELECT 'DEPARTMENT', department_id, COUNT(DISTINCT person_id), COUNT(*), SUM(fte) FROM cur GROUP BY department_id)
SELECT group_level, department_id,
       CASE WHEN hc >= 3 THEN hc END AS headcount,
       CASE WHEN hc >= 3 THEN appts END AS appointments,
       CASE WHEN hc >= 3 THEN ROUND(fte, 2) END AS fte,
       hc < 3 AS suppressed,
       DATE'2026-10-31' AS business_date, DATE'2026-11-02' AS knowledge_cutoff
FROM grp
""")
spark.sql(f"GRANT SELECT ON TABLE {G('workforce_aggregate_snapshot')} TO `AGGREGATE_VIEWER`")
snap = spark.table(G("workforce_aggregate_snapshot"))
display(snap)
org = snap.where("group_level = 'ALL'").first()
ok = (org.headcount == 3 and org.appointments == 4 and float(org.fte) == 2.5
      and snap.where("group_level = 'DEPARTMENT' AND NOT suppressed").count() == 0)
log_run("07_aggregate_snapshot_reconcile", "pass" if ok else "fail", str(snap.collect()))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Negative access tests (repeat once per role)
# MAGIC Put yourself in exactly ONE of the three groups (remove the others), wait ~1 minute, re-run from here, and record the result.
# MAGIC Expected outcomes:
# MAGIC
# MAGIC | Test | T1_ANALYST | DS_REVIEWER | AGGREGATE_VIEWER |
# MAGIC |---|---|---|---|
# MAGIC | detail rows visible | 3 (T1 rows only) | 6 | permission denied (no grant)* |
# MAGIC | T2 rows visible | 0 | 3 | — |
# MAGIC | person_id unmasked | yes (T1 only) | yes | — |
# MAGIC | aggregate snapshot | no grant | no grant | org row only, departments suppressed |
# MAGIC
# MAGIC \* As workspace admin/owner you may bypass grants: the owner can always read their own table, so **ownership** must be moved
# MAGIC to another principal (or tests run as a non-owner test user) for a valid negative test. Record this as a Free Edition limitation.

# COMMAND ----------

import json
role_now = [g for g in ["T1_ANALYST", "DS_REVIEWER", "AGGREGATE_VIEWER"]
            if spark.sql(f"SELECT is_account_group_member('{g}') AS m").first().m]
tests = {}
for name, sql in {
    "detail_rows": f"SELECT COUNT(*) FROM {G('appointments_governed')}",
    "t2_rows": f"SELECT COUNT(*) FROM {G('appointments_governed')} WHERE department_id = 'T2'",
    "masked_person_ids": f"SELECT COUNT(*) FROM {G('appointments_governed')} WHERE person_id = '***'",
    "aggregate_rows_visible": f"SELECT COUNT(*) FROM {G('workforce_aggregate_snapshot')} WHERE NOT suppressed",
}.items():
    try:
        tests[name] = spark.sql(sql).first()[0]
    except Exception as e:
        tests[name] = f"denied/error: {type(e).__name__}"
print("current groups:", role_now, json.dumps(tests, default=str))
spark.createDataFrame([(RUN_ID, ",".join(role_now), json.dumps(tests, default=str))], "run_id STRING, groups STRING, results STRING") \
    .selectExpr("*", "current_user() AS tested_by", "current_timestamp() AS tested_at") \
    .write.mode("append").saveAsTable(FQE("governance_access_tests"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Optional ABAC policy (verify in workspace; may need a paid workspace and governed tags)
# MAGIC ```sql
# MAGIC -- governed tag 'pii' must exist at account level with value 'person_identifier_synthetic'
# MAGIC CREATE OR REPLACE POLICY mask_synthetic_person_ids
# MAGIC ON SCHEMA <catalog>.hr_gov_synthetic
# MAGIC COMMENT 'Mask synthetic person identifiers for everyone except DS_REVIEWER'
# MAGIC COLUMN MASK <catalog>.hr_gov_synthetic.cm_person_id
# MAGIC TO `account users` EXCEPT `DS_REVIEWER`
# MAGIC FOR TABLES
# MAGIC MATCH COLUMNS has_tag_value('pii', 'person_identifier_synthetic') AS pid
# MAGIC ON COLUMN pid;
# MAGIC ```
# MAGIC If you test ABAC, first drop the table-level mask on `person_id` so you can tell which control fired.

# COMMAND ----------

# MAGIC %md ## Lineage and audit (system tables; may need account admin to grant access)

# COMMAND ----------

for title, sql in {
    "table lineage into kit schemas (7 days)": f"""
        SELECT event_time, source_table_full_name, target_table_full_name, entity_type, created_by
        FROM system.access.table_lineage
        WHERE event_date >= current_date() - 7
          AND (target_table_full_name LIKE '{CATALOG}.{SCHEMA}.%' OR target_table_full_name LIKE '{CATALOG}.{EVAL_SCHEMA}.%'
               OR target_table_full_name LIKE '{CATALOG}.{GOV_SCHEMA}.%' OR target_table_full_name LIKE '{CATALOG}.{PIPELINE_SCHEMA}.%')
        ORDER BY event_time DESC LIMIT 200""",
    "column lineage for the aggregate snapshot": f"""
        SELECT source_table_full_name, source_column_name, target_column_name, entity_type
        FROM system.access.column_lineage
        WHERE target_table_full_name = '{G('workforce_aggregate_snapshot')}' AND event_date >= current_date() - 7""",
    "who read the governed detail table (audit)": f"""
        SELECT event_time, user_identity.email, action_name, request_params
        FROM system.access.audit
        WHERE event_date >= current_date() - 2 AND service_name = 'unityCatalog'
          AND to_json(request_params) LIKE '%appointments_governed%'
        ORDER BY event_time DESC LIMIT 100""",
}.items():
    print("==", title)
    try:
        display(spark.sql(sql))
    except Exception as e:
        print("unavailable:", type(e).__name__, str(e)[:300])
        log_run("07_system_table", "unavailable", f"{title}: {str(e)[:500]}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Data classification
# MAGIC 1. Catalog Explorer → your catalog → enable **Data Classification** (verify location; requires serverless).
# MAGIC 2. Wait for the scan, then query the results. The synthetic `person_id` values are not real PII, so the scanner may
# MAGIC    **not** flag them — record what it found and did not find; do not seed fake PII to make it fire.
# MAGIC 3. Note: never put a row filter or column mask on `system.data_classification.results` (it breaks scanning).

# COMMAND ----------

try:
    display(spark.sql(f"""
    SELECT * FROM system.data_classification.results
    WHERE catalog_name = '{CATALOG}' ORDER BY schema_name, table_name"""))   # column names: verify
except Exception as e:
    print("Data classification results unavailable:", str(e)[:300])
    log_run("07_data_classification", "unavailable", str(e)[:500])

# COMMAND ----------

# MAGIC %md
# MAGIC ## Evidence to capture
# MAGIC - `governance_access_tests` rows for all three roles, run as a **non-owner** identity where possible.
# MAGIC - Screenshots: table tags, row filter/mask on the table page, lineage graph for `workforce_aggregate_snapshot`.
# MAGIC - Whether the Genie Agent (04), the app (08) and the agent (05) honour the same filter: ask each for T2 detail as T1_ANALYST.
# MAGIC - Every "unavailable" system table → limitation "unavailable in tested environment", not "unsupported by Databricks".
