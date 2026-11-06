# Databricks notebook source
# MAGIC %md
# MAGIC # 03 · AI Search (formerly Vector Search) over O*NET occupations and tasks
# MAGIC
# MAGIC **Naming (docs, 2026):** the product is now *Databricks AI Search*. The current Python package is `databricks-ai-search`
# MAGIC (`from databricks.ai_search.client import AISearchClient`); `databricks-vectorsearch` is a deprecated shim and
# MAGIC `VectorSearchClient` is kept as an alias. API/CLI paths still use `vector-search`. This notebook tries the new package
# MAGIC and falls back to the old one.
# MAGIC
# MAGIC **Free Edition:** one AI Search endpoint limited to one search unit; Direct Vector Access indexes are not supported.
# MAGIC This notebook uses a **Delta Sync index with Databricks-managed embeddings**, which should fit (verify).
# MAGIC
# MAGIC Rubric evidence: *A2 document evidence/abstention* (retrieval with source ids), *A3 controlled tool use*
# MAGIC (the index becomes an agent tool in 05), *C1 measured operating cost* (endpoint is billed while it exists; delete in 99).

# COMMAND ----------

# MAGIC %pip install -q databricks-ai-search
# MAGIC %restart_python

# COMMAND ----------

# MAGIC %run ./_config

# COMMAND ----------

try:
    from databricks.ai_search.client import AISearchClient as SearchClient
    CLIENT_PKG = "databricks-ai-search"
except ImportError:  # older runtime / package name
    from databricks.vector_search.client import VectorSearchClient as SearchClient
    CLIENT_PKG = "databricks-vectorsearch (deprecated shim)"
print("client package:", CLIENT_PKG)
vsc = SearchClient()   # notebook auth; verify constructor args in workspace if this raises

INDEX_SOURCE = FQ("onet_occupation_doc")
INDEX_NAME = FQ("onet_occupation_doc_idx")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Source table: one document per O*NET occupation
# MAGIC Text = title + description + up to 15 Core task statements + up to 10 alternate titles. Change Data Feed is required for Delta Sync.

# COMMAND ----------

spark.sql(f"""
CREATE OR REPLACE TABLE {INDEX_SOURCE}
TBLPROPERTIES (delta.enableChangeDataFeed = true)
COMMENT 'Retrieval document per O*NET 31.0 occupation (public, CC BY 4.0). Built by platform kit 03.'
AS
WITH tasks AS (
  SELECT onetsoc_code, concat_ws(' ', slice(array_sort(collect_list({COL['task_text']})), 1, 15)) AS task_text
  FROM {FQ('onet_task_statement')}
  WHERE {COL['task_type']} = 'Core' OR {COL['task_type']} IS NULL
  GROUP BY onetsoc_code),
alts AS (
  SELECT onetsoc_code, concat_ws('; ', slice(array_sort(collect_set(alternate_title)), 1, 10)) AS alt_titles
  FROM {FQ('onet_alternate_title')} GROUP BY onetsoc_code)
SELECT o.onetsoc_code,
       o.{COL['occ_title']} AS title,
       concat(o.{COL['occ_title']}, '. Also called: ', coalesce(a.alt_titles, ''), '. ',
              o.{COL['occ_desc']}, ' Tasks: ', coalesce(t.task_text, '')) AS doc_text,
       substr(o.onetsoc_code, 1, 2) AS soc_major_group,
       o.source_vintage
FROM {FQ('onet_occupation')} o
LEFT JOIN tasks t USING (onetsoc_code)
LEFT JOIN alts a USING (onetsoc_code)
""")
display(spark.sql(f"SELECT COUNT(*) AS docs, AVG(length(doc_text)) AS avg_chars FROM {INDEX_SOURCE}"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Endpoint and index
# MAGIC Endpoint creation can take several minutes. Free Edition: only one endpoint; reuse it across runs.

# COMMAND ----------

import time
existing = [e.get("name") for e in vsc.list_endpoints().get("endpoints", [])]
if AI_SEARCH_ENDPOINT not in existing:
    vsc.create_endpoint(name=AI_SEARCH_ENDPOINT, endpoint_type="STANDARD")   # verify endpoint_type values in workspace
    log_run("03_create_endpoint", "submitted", AI_SEARCH_ENDPOINT)
vsc.wait_for_endpoint(name=AI_SEARCH_ENDPOINT, verbose=True)                # verify method exists in installed client

# COMMAND ----------

t0 = time.time()
try:
    index = vsc.get_index(endpoint_name=AI_SEARCH_ENDPOINT, index_name=INDEX_NAME)
    index.sync()
    action = "sync"
except Exception:
    index = vsc.create_delta_sync_index(
        endpoint_name=AI_SEARCH_ENDPOINT,
        source_table_name=INDEX_SOURCE,
        index_name=INDEX_NAME,
        pipeline_type="TRIGGERED",                 # no continuous cost
        primary_key="onetsoc_code",
        embedding_source_column="doc_text",
        embedding_model_endpoint_name=EMBED_ENDPOINT,
        columns_to_sync=["onetsoc_code", "title", "soc_major_group", "source_vintage", "doc_text"],
    )
    action = "create"
index.wait_until_ready(verbose=True)   # verify method name; otherwise poll index.describe()
log_run("03_index_" + action, "pass", f"elapsed_s={time.time()-t0:.0f} index={INDEX_NAME}")
print(index.describe())

# COMMAND ----------

# MAGIC %md
# MAGIC ## Retrieval tests
# MAGIC 1. Smoke queries (public questions). 2. SUCSS class titles → retrieved O*NET codes, scored deterministically
# MAGIC against the lexical baseline and against human-reviewed labels (`review_labels`) when available.

# COMMAND ----------

for q in ["database administrator for a university", "groundskeeper maintaining campus lawns",
          "financial aid counselor", "research laboratory technician", "payroll clerk"]:
    r = index.similarity_search(query_text=q, columns=["onetsoc_code", "title"], num_results=3)
    print(q, "->", r.get("result", {}).get("data_array"))

# COMMAND ----------

import json
from pyspark.sql import functions as F
classes = spark.sql(f"""
SELECT source_record_id, {COL['class_title']} AS class_title FROM {FQ('sucss_class')}
ORDER BY {sample_order('source_record_id')} LIMIT {CAP_EMBED_CLASSES}""").collect()

rows, t0 = [], time.time()
for c in classes:
    try:
        r = index.similarity_search(query_text=c.class_title, columns=["onetsoc_code", "title"], num_results=5)
        data = r.get("result", {}).get("data_array", [])
        for rank, d in enumerate(data, start=1):
            rows.append((str(c.source_record_id), c.class_title, d[0], d[1], float(d[-1]), rank, None))
        if not data:
            rows.append((str(c.source_record_id), c.class_title, None, None, None, None, "no results"))
    except Exception as e:
        rows.append((str(c.source_record_id), c.class_title, None, None, None, None, f"{type(e).__name__}: {str(e)[:200]}"))
elapsed = time.time() - t0
res = spark.createDataFrame(rows, "source_record_id STRING, class_title STRING, onetsoc_code STRING, title STRING, score DOUBLE, ret_rank INT, error STRING") \
    .withColumn("run_id", F.lit(RUN_ID)).withColumn("index_name", F.lit(INDEX_NAME))
res.write.mode("append").option("mergeSchema", "true").saveAsTable(FQE("ai_search_results"))
print(f"{len(classes)} queries in {elapsed:.1f}s ({elapsed/max(len(classes),1)*1000:.0f} ms/query, sequential)")
log_run("03_retrieval_eval", "pass", f"queries={len(classes)} elapsed_s={elapsed:.1f}")

# COMMAND ----------

score = spark.sql(f"""
WITH r AS (SELECT * FROM {FQE('ai_search_results')} WHERE run_id = '{RUN_ID}' AND error IS NULL),
l AS (SELECT source_record_id, onetsoc_code, {COL['cand_rank']} AS lr FROM {FQ('sucss_onet_candidate')} WHERE {COL['cand_rank']} <= 5),
per AS (SELECT r.source_record_id,
               MAX(CASE WHEN r.ret_rank = 1 AND l.lr = 1 THEN 1 ELSE 0 END) AS rank1_agree,
               COUNT(l.onetsoc_code) AS overlap5
        FROM r LEFT JOIN l ON l.source_record_id = r.source_record_id AND l.onetsoc_code = r.onetsoc_code
        GROUP BY r.source_record_id)
SELECT COUNT(*) AS classes, ROUND(AVG(rank1_agree),3) AS rank1_agreement_with_lexical, ROUND(AVG(overlap5)/5,3) AS mean_overlap_at_5,
       (SELECT COUNT(*) FROM {FQE('ai_search_results')} WHERE run_id = '{RUN_ID}' AND error IS NOT NULL) AS failed_queries
FROM per""")
display(score)
score.withColumn("run_id", F.lit(RUN_ID)).withColumn("metric_set", F.lit("03_ai_search_vs_lexical")) \
    .write.mode("append").option("mergeSchema", "true").saveAsTable(FQE("ai_scores"))

if spark.catalog.tableExists(FQE("review_labels")):
    display(spark.sql(f"""
    WITH lab AS (SELECT source_record_id, approved_onetsoc_code FROM {FQE('review_labels')} WHERE reviewer_decision = 'approved'),
    r AS (SELECT source_record_id, onetsoc_code, ret_rank FROM {FQE('ai_search_results')} WHERE run_id = '{RUN_ID}')
    SELECT COUNT(DISTINCT lab.source_record_id) AS labelled,
           COUNT(DISTINCT CASE WHEN r.ret_rank = 1 THEN lab.source_record_id END) AS top1_hits,
           COUNT(DISTINCT CASE WHEN r.ret_rank <= 5 THEN lab.source_record_id END) AS recall5_hits
    FROM lab JOIN (SELECT DISTINCT source_record_id FROM r) q USING (source_record_id)
    LEFT JOIN r ON r.source_record_id = lab.source_record_id AND r.onetsoc_code = lab.approved_onetsoc_code"""))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Optional: SQL access to the index
# MAGIC Docs list an `ai_search` SQL function, and older docs a `vector_search(index => ..., query_text => ..., num_results => ...)`
# MAGIC table function. Which name your workspace accepts is a **verify in workspace** item:
# MAGIC ```sql
# MAGIC SELECT * FROM vector_search(index => '<catalog>.hr_public.onet_occupation_doc_idx', query_text => 'payroll clerk', num_results => 5);
# MAGIC ```
# MAGIC
# MAGIC ## Evidence to capture
# MAGIC - Endpoint + index screenshots (status, row count, embedding model), sync duration from `run_log`.
# MAGIC - `ai_scores` row `03_ai_search_vs_lexical`, latency per query, failed query count.
# MAGIC - Billing rows for the AI Search SKU (99). **Delete the endpoint when finished** if you are on a paid workspace.
