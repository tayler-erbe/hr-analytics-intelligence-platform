# Databricks notebook source
# MAGIC %md
# MAGIC # 02 · AI Functions on public occupation data
# MAGIC
# MAGIC | Part | Function | Release state (docs, checked 2026-11-06 via search) | Free Edition |
# MAGIC |---|---|---|---|
# MAGIC | A | `ai_classify(content, labels [, options])` v2.1 | GA function; pin `version`. Default version differs between SQL and REST docs | Expected yes (verify) |
# MAGIC | B | `ai_extract(content, schema [, options])` v2.1 | GA function; pin `version` | Expected yes (verify) |
# MAGIC | C | `ai_query(endpoint, request, ...)` chat | GA; `failOnError` needs DBR 15.3+ | Pay-per-token FMAPI; Free Edition limits some models/batch (verify) |
# MAGIC | D | `ai_query(<embedding endpoint>, text)` | GA; return type inferred on DBR 15.2+ | as C |
# MAGIC | E | `ai_forecast(observed => TABLE(...), horizon, time_col, value_col, group_col, ...)` | Preview; v2 needs the *Predictive AI Functions* preview | **Verify**; may need a SQL warehouse |
# MAGIC
# MAGIC Rubric evidence: *A1 structured accuracy* (agreement vs deterministic references), *A2 evidence/abstention*,
# MAGIC *M2 valid evaluation* (forecast backtest vs naive baseline), *C1 measured operating cost* (rows sent, elapsed time, billing).
# MAGIC
# MAGIC **Scoring rule (repo policy):** no model grades another model. Every score here is a deterministic comparison:
# MAGIC SOC major-group agreement with the lexical baseline, overlap with O*NET's own technology/skill lists, overlap with
# MAGIC human-reviewed labels (`review_labels`), or numeric error against held-out actuals. Agreement with the lexical baseline
# MAGIC is **not accuracy**; only human-reviewed labels support an accuracy statement, and only for the reviewed sample.
# MAGIC All attempted rows, errors and unparseable outputs are kept.

# COMMAND ----------

# MAGIC %run ./_config

# COMMAND ----------

import json, time
from pyspark.sql import functions as F, types as T

def sql_str(s: str) -> str:
    return "'" + s.replace("\\", "\\\\").replace("'", "\\'") + "'"

def timed(step, fn):
    t0 = time.time()
    try:
        out = fn()
        log_run(step, "pass", f"elapsed_s={time.time()-t0:.1f}")
        return out
    except Exception as e:
        log_run(step, "error", f"elapsed_s={time.time()-t0:.1f} {type(e).__name__}: {str(e)[:1500]}")
        raise

def _unwrap(v):
    """ai_extract/ai_classify v2.1 wrap values as {"value": ...}; unwrap recursively."""
    if isinstance(v, dict):
        if set(v.keys()) >= {"value"} and len(v) <= 3:
            return _unwrap(v["value"])
        return {k: _unwrap(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_unwrap(x) for x in v]
    return v

def _find_key(obj, key):
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for x in obj.values():
            r = _find_key(x, key)
            if r is not None:
                return r
    if isinstance(obj, list):
        for x in obj:
            r = _find_key(x, key)
            if r is not None:
                return r
    return None

@F.udf(T.ArrayType(T.StringType()))
def json_array_field(raw, key):
    """Return a string array field from a raw JSON response; None if unparseable (kept as evidence)."""
    if raw is None:
        return None
    try:
        txt = raw
        if "{" in txt:
            txt = txt[txt.index("{"): txt.rindex("}") + 1]
        v = _unwrap(_find_key(json.loads(txt), key))
        return [str(x) for x in v] if isinstance(v, list) else None
    except Exception:
        return None

spark.sql(f"USE CATALOG {CATALOG}")
print("Rows that will be sent to AI services this run (caps):",
      dict(classify=CAP_CLASSIFY, extract=CAP_EXTRACT, query=CAP_QUERY,
           embed=CAP_EMBED_CLASSES + CAP_EMBED_OCC))

# COMMAND ----------

# MAGIC %md
# MAGIC ## A · `ai_classify`: SUCSS class titles → SOC 2018 major group
# MAGIC Deterministic reference: the first two digits of the rank-1 lexical O*NET candidate. Labels and instructions are frozen in `_config`.

# COMMAND ----------

labels_json = json.dumps(SOC_MAJOR_GROUPS)
classify_sql = f"""
WITH s AS (
  SELECT source_record_id, {COL['class_code']} AS class_code, {COL['class_title']} AS class_title
  FROM {FQ('sucss_class')}
  ORDER BY {sample_order('source_record_id')}
  LIMIT {CAP_CLASSIFY}
)
SELECT s.*,
       CAST(ai_classify(class_title, {sql_str(labels_json)},
            map('version', '2.1', 'instructions', {sql_str(CLASSIFY_INSTRUCTIONS)})) AS STRING) AS raw_output
FROM s
"""
classified = timed("02A_ai_classify", lambda: spark.sql(classify_sql).cache())
classified = (classified
    # Robust to output shape: the first "NN Title" label string in the raw output is the predicted group.
    .withColumn("pred_major_group", F.regexp_extract("raw_output", r"(\d{2}) [A-Z]", 1))
    .withColumn("parse_ok", F.col("pred_major_group") != "")
    .withColumn("run_id", F.lit(RUN_ID)).withColumn("protocol", F.lit(PROTOCOL))
    .withColumn("function", F.lit("ai_classify v2.1")).withColumn("executed_at", F.current_timestamp()))
classified.write.mode("append").option("mergeSchema", "true").saveAsTable(FQE("ai_classify_results"))
display(classified.limit(20))

# COMMAND ----------

# Inspect the raw output shape ONCE and record it (the v2.1 response shape is a 'verify in workspace' item).
print(classified.select("raw_output").first()[0])

# COMMAND ----------

score_a = spark.sql(f"""
WITH r AS (SELECT * FROM {FQE('ai_classify_results')} WHERE run_id = '{RUN_ID}'),
lex AS (SELECT source_record_id, substr(onetsoc_code, 1, 2) AS lex_group
        FROM {FQ('sucss_onet_candidate')} WHERE {COL['cand_rank']} = 1)
SELECT COUNT(*) AS attempted,
       SUM(CASE WHEN parse_ok THEN 1 ELSE 0 END) AS parsed,
       SUM(CASE WHEN r.pred_major_group = lex.lex_group THEN 1 ELSE 0 END) AS agree_with_lexical_rank1,
       ROUND(AVG(CASE WHEN r.pred_major_group = lex.lex_group THEN 1.0 ELSE 0.0 END), 3) AS agreement_rate
FROM r LEFT JOIN lex USING (source_record_id)
""")
display(score_a)
score_a.withColumn("run_id", F.lit(RUN_ID)).withColumn("metric_set", F.lit("02A_classify_vs_lexical")) \
    .write.mode("append").option("mergeSchema", "true").saveAsTable(FQE("ai_scores"))

# COMMAND ----------

# Export a stratified human-review sample (classes where AI and lexical disagree first). A person labels these
# using the README procedure; the labels are uploaded as review_labels and then used for accuracy scoring.
review_sample = spark.sql(f"""
SELECT r.source_record_id, r.class_code, r.class_title, r.pred_major_group AS ai_group,
       substr(c.onetsoc_code,1,2) AS lexical_group, c.onetsoc_code AS lexical_rank1_code
FROM {FQE('ai_classify_results')} r
LEFT JOIN {FQ('sucss_onet_candidate')} c ON c.source_record_id = r.source_record_id AND c.{COL['cand_rank']} = 1
WHERE r.run_id = '{RUN_ID}'
ORDER BY CASE WHEN r.pred_major_group = substr(c.onetsoc_code,1,2) THEN 1 ELSE 0 END, {sample_order('r.source_record_id')}
LIMIT 60
""")
display(review_sample)   # download as CSV, label with review_labels_template.csv columns

# COMMAND ----------

# MAGIC %md
# MAGIC ## B · `ai_extract`: structured fields from O*NET task statements
# MAGIC Deterministic check: extracted `tools_or_software` vs the occupation's own O*NET technology-skill examples.

# COMMAND ----------

extract_sql = f"""
WITH t AS (
  SELECT onetsoc_code, task_id, {COL['task_text']} AS task
  FROM {FQ('onet_task_statement')}
  ORDER BY {sample_order("concat(onetsoc_code, '|', task_id)")}
  LIMIT {CAP_EXTRACT}
)
SELECT t.*, CAST(ai_extract(task, {sql_str(EXTRACT_SCHEMA_JSON)}, map('version', '2.1')) AS STRING) AS raw_output
FROM t
"""
extracted = timed("02B_ai_extract", lambda: spark.sql(extract_sql).cache())
extracted = (extracted
    .withColumn("tools", json_array_field("raw_output", F.lit("tools_or_software")))
    .withColumn("parse_ok", F.col("tools").isNotNull())
    .withColumn("run_id", F.lit(RUN_ID)).withColumn("protocol", F.lit(PROTOCOL))
    .withColumn("function", F.lit("ai_extract v2.1")).withColumn("executed_at", F.current_timestamp()))
extracted.write.mode("append").option("mergeSchema", "true").saveAsTable(FQE("ai_extract_results"))
display(extracted.limit(20))

# COMMAND ----------

score_b = spark.sql(f"""
WITH r AS (SELECT * FROM {FQE('ai_extract_results')} WHERE run_id = '{RUN_ID}'),
e AS (SELECT r.onetsoc_code, r.task_id, lower(trim(tool)) AS tool FROM r LATERAL VIEW OUTER explode(tools) x AS tool),
ts AS (SELECT onetsoc_code, lower(example) AS example FROM {FQ('onet_technology_skill')})
SELECT COUNT(DISTINCT concat(e.onetsoc_code, e.task_id)) AS tasks_attempted,
       COUNT(e.tool) AS tools_extracted,
       COUNT(DISTINCT CASE WHEN ts.example IS NOT NULL THEN concat(e.onetsoc_code, e.task_id, e.tool) END) AS tools_matching_onet_tech_list,
       (SELECT SUM(CASE WHEN parse_ok THEN 0 ELSE 1 END) FROM r) AS unparseable_rows
FROM e LEFT JOIN ts ON ts.onetsoc_code = e.onetsoc_code AND e.tool IS NOT NULL AND length(e.tool) > 2
                    AND (ts.example LIKE concat('%', e.tool, '%') OR e.tool LIKE concat('%', ts.example, '%'))
""")
display(score_b)
score_b.withColumn("run_id", F.lit(RUN_ID)).withColumn("metric_set", F.lit("02B_extract_vs_onet_tech")) \
    .write.mode("append").option("mergeSchema", "true").saveAsTable(FQE("ai_scores"))
# Interpretation: a low match rate can mean O*NET lists tools at occupation (not task) level. Review a sample by hand.

# COMMAND ----------

# MAGIC %md
# MAGIC ## C · `ai_query` (chat model): skills per task
# MAGIC `failOnError => false` keeps failed rows with their error (DBR 15.3+). Temperature 0, max 200 tokens.
# MAGIC Deterministic consistency check vs O*NET's own skill element names for the occupation (top 10 by importance).

# COMMAND ----------

query_sql = f"""
WITH t AS (
  SELECT onetsoc_code, task_id, {COL['task_text']} AS task
  FROM {FQ('onet_task_statement')}
  ORDER BY {sample_order("concat('q', onetsoc_code, '|', task_id)")}
  LIMIT {CAP_QUERY}
)
SELECT t.*,
  to_json(ai_query({sql_str(CHAT_ENDPOINT)}, concat({sql_str(QUERY_PROMPT_PREFIX)}, task),
          modelParameters => named_struct('max_tokens', 200, 'temperature', 0.0),
          failOnError => false)) AS raw_output
FROM t
"""
queried = timed("02C_ai_query_chat", lambda: spark.sql(query_sql).cache())
queried = (queried
    .withColumn("skills", json_array_field(F.get_json_object("raw_output", "$.result"), F.lit("skills")))
    .withColumn("error_message", F.get_json_object("raw_output", "$.errorMessage"))   # field name: verify in workspace
    .withColumn("parse_ok", F.col("skills").isNotNull())
    .withColumn("model_endpoint", F.lit(CHAT_ENDPOINT))
    .withColumn("run_id", F.lit(RUN_ID)).withColumn("protocol", F.lit(PROTOCOL)).withColumn("executed_at", F.current_timestamp()))
queried.write.mode("append").option("mergeSchema", "true").saveAsTable(FQE("ai_query_skill_results"))
display(queried.limit(20))

# COMMAND ----------

score_c = spark.sql(f"""
WITH r AS (SELECT * FROM {FQE('ai_query_skill_results')} WHERE run_id = '{RUN_ID}'),
s AS (SELECT r.onetsoc_code, r.task_id, lower(trim(sk)) AS skill FROM r LATERAL VIEW OUTER explode(skills) x AS sk),
onet AS (
  SELECT onetsoc_code, lower({COL['element_name']}) AS element_name FROM (
    SELECT onetsoc_code, {COL['element_name']}, ROW_NUMBER() OVER (PARTITION BY onetsoc_code ORDER BY {COL['element_value']} DESC) AS rk
    FROM {FQ('onet_element_rating')} WHERE domain = 'skills' AND scale_id = 'IM') WHERE rk <= 10)
SELECT COUNT(skill) AS skills_returned,
       (SELECT COUNT(*) FROM r WHERE NOT parse_ok) AS unparseable_or_failed_rows,
       (SELECT COUNT(*) FROM r WHERE error_message IS NOT NULL) AS rows_with_error,
       SUM(CASE WHEN onet.element_name IS NOT NULL THEN 1 ELSE 0 END) AS skills_matching_onet_top10
FROM s LEFT JOIN onet ON onet.onetsoc_code = s.onetsoc_code AND onet.element_name = s.skill
""")
display(score_c)
score_c.withColumn("run_id", F.lit(RUN_ID)).withColumn("metric_set", F.lit("02C_query_vs_onet_skills")) \
    .write.mode("append").option("mergeSchema", "true").saveAsTable(FQE("ai_scores"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## D · Embeddings via `ai_query`: SUCSS class → O*NET occupation candidates
# MAGIC Compare semantic top-5 against the existing **lexical** top-5 (`sucss_onet_candidate`) and, where available,
# MAGIC against human-reviewed labels. Cosine similarity is computed in SQL; it is a ranking score, not a probability.

# COMMAND ----------

emb_occ_sql = f"""
SELECT onetsoc_code, {COL['occ_title']} AS title,
       ai_query({sql_str(EMBED_ENDPOINT)}, concat({COL['occ_title']}, '. ', {COL['occ_desc']})) AS emb
FROM (SELECT * FROM {FQ('onet_occupation')} ORDER BY onetsoc_code LIMIT {CAP_EMBED_OCC})
"""
emb_cls_sql = f"""
SELECT source_record_id, {COL['class_title']} AS class_title,
       ai_query({sql_str(EMBED_ENDPOINT)}, {COL['class_title']}) AS emb
FROM (SELECT * FROM {FQ('sucss_class')} ORDER BY {sample_order('source_record_id')} LIMIT {CAP_EMBED_CLASSES})
"""
occ_emb = timed("02D_embed_onet", lambda: spark.sql(emb_occ_sql))
occ_emb.withColumn("model_endpoint", F.lit(EMBED_ENDPOINT)).withColumn("run_id", F.lit(RUN_ID)) \
    .write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(FQE("emb_onet_occupation"))
cls_emb = timed("02D_embed_sucss", lambda: spark.sql(emb_cls_sql))
cls_emb.withColumn("model_endpoint", F.lit(EMBED_ENDPOINT)).withColumn("run_id", F.lit(RUN_ID)) \
    .write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(FQE("emb_sucss_class"))
print(spark.sql(f"SELECT size(emb) AS dims, COUNT(*) FROM {FQE('emb_onet_occupation')} GROUP BY 1").collect())

# COMMAND ----------

sem = spark.sql(f"""
WITH pairs AS (
  SELECT c.source_record_id, c.class_title, o.onetsoc_code, o.title,
         aggregate(zip_with(c.emb, o.emb, (x, y) -> x * y), 0D, (a, v) -> a + v) /
         (sqrt(aggregate(c.emb, 0D, (a, v) -> a + v * v)) * sqrt(aggregate(o.emb, 0D, (a, v) -> a + v * v))) AS cosine
  FROM {FQE('emb_sucss_class')} c CROSS JOIN {FQE('emb_onet_occupation')} o)
SELECT * FROM (
  SELECT *, ROW_NUMBER() OVER (PARTITION BY source_record_id ORDER BY cosine DESC, onetsoc_code) AS sem_rank FROM pairs)
WHERE sem_rank <= 5
""").withColumn("run_id", F.lit(RUN_ID)).withColumn("method", F.lit(f"embedding_cosine:{EMBED_ENDPOINT}"))
sem.write.mode("append").option("mergeSchema", "true").saveAsTable(FQE("semantic_candidates"))

score_d = spark.sql(f"""
WITH s AS (SELECT * FROM {FQE('semantic_candidates')} WHERE run_id = '{RUN_ID}'),
l AS (SELECT source_record_id, onetsoc_code, {COL['cand_rank']} AS lex_rank FROM {FQ('sucss_onet_candidate')} WHERE {COL['cand_rank']} <= 5),
per AS (
  SELECT s.source_record_id,
         MAX(CASE WHEN s.sem_rank = 1 AND l.lex_rank = 1 THEN 1 ELSE 0 END) AS rank1_agree,
         COUNT(l.onetsoc_code) AS overlap_at_5
  FROM s LEFT JOIN l ON l.source_record_id = s.source_record_id AND l.onetsoc_code = s.onetsoc_code
  GROUP BY s.source_record_id)
SELECT COUNT(*) AS classes, ROUND(AVG(rank1_agree), 3) AS rank1_agreement_with_lexical,
       ROUND(AVG(overlap_at_5) / 5, 3) AS mean_overlap_at_5
FROM per
""")
display(score_d)
score_d.withColumn("run_id", F.lit(RUN_ID)).withColumn("metric_set", F.lit("02D_semantic_vs_lexical")) \
    .write.mode("append").option("mergeSchema", "true").saveAsTable(FQE("ai_scores"))

# COMMAND ----------

# Accuracy ONLY against human-reviewed labels (README: review_labels_template.csv -> table review_labels).
if spark.catalog.tableExists(FQE("review_labels")):
    acc = spark.sql(f"""
    WITH lab AS (SELECT source_record_id, approved_onetsoc_code FROM {FQE('review_labels')}
                 WHERE reviewer_decision = 'approved' AND approved_onetsoc_code IS NOT NULL
                   AND source_record_id IN (SELECT source_record_id FROM {FQE('semantic_candidates')} WHERE run_id = '{RUN_ID}')),
    sem AS (SELECT source_record_id, onetsoc_code, sem_rank AS r FROM {FQE('semantic_candidates')} WHERE run_id = '{RUN_ID}'),
    lex AS (SELECT source_record_id, onetsoc_code, {COL['cand_rank']} AS r FROM {FQ('sucss_onet_candidate')} WHERE {COL['cand_rank']} <= 5),
    hit AS (
      SELECT lab.source_record_id,
             MIN(sem.r) AS sem_rank_of_label, MIN(lex.r) AS lex_rank_of_label
      FROM lab
      LEFT JOIN sem ON sem.source_record_id = lab.source_record_id AND sem.onetsoc_code = lab.approved_onetsoc_code
      LEFT JOIN lex ON lex.source_record_id = lab.source_record_id AND lex.onetsoc_code = lab.approved_onetsoc_code
      GROUP BY lab.source_record_id)
    SELECT COUNT(*) AS labelled_classes_in_sample,
           AVG(CASE WHEN sem_rank_of_label = 1 THEN 1.0 ELSE 0 END) AS semantic_top1,
           AVG(CASE WHEN sem_rank_of_label <= 5 THEN 1.0 ELSE 0 END) AS semantic_recall_at_5,
           AVG(CASE WHEN lex_rank_of_label = 1 THEN 1.0 ELSE 0 END) AS lexical_top1,
           AVG(CASE WHEN lex_rank_of_label <= 5 THEN 1.0 ELSE 0 END) AS lexical_recall_at_5
    FROM hit
    """)
    display(acc)
    acc.withColumn("run_id", F.lit(RUN_ID)).withColumn("metric_set", F.lit("02D_vs_human_labels")) \
        .write.mode("append").option("mergeSchema", "true").saveAsTable(FQE("ai_scores"))
else:
    print("No review_labels table yet: report agreement only, not accuracy.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## E · `ai_forecast`: Census QWI higher-education turnover (Illinois counties)
# MAGIC Backtest design: hold out the last 4 observed quarters, forecast them, compare with actuals, and compare against a
# MAGIC seasonal-naive baseline (same quarter one year earlier). The forecast is **not** an institutional attrition prediction.
# MAGIC
# MAGIC If `spark.sql` rejects `ai_forecast` in a notebook, run the same SQL in the SQL editor on a serverless/pro SQL warehouse
# MAGIC and record that as an implementation note (verify in workspace).

# COMMAND ----------

QWI_FILTER = (f"{COL['qwi_sex']} IN ('0', 0) AND {COL['qwi_agegrp']} IN ('A00')")   # all sexes, all ages (QWI codes; verify)
spark.sql(f"""
CREATE OR REPLACE TEMP VIEW qwi_series AS
SELECT make_date(CAST({COL['qwi_year']} AS INT), (CAST({COL['qwi_quarter']} AS INT) - 1) * 3 + 1, 1) AS ds,
       CAST({COL['qwi_geo']} AS STRING) AS geo,
       CAST({COL['qwi_turnover']} AS DOUBLE) AS turnover
FROM {FQ('qwi_higher_ed')}
WHERE {QWI_FILTER} AND {COL['qwi_turnover']} IS NOT NULL
""")
bounds = spark.sql("SELECT max(ds) AS max_ds, add_months(max(ds), -9) AS cutoff, date_add(max(ds), 1) AS horizon FROM qwi_series").first()
# cutoff = first of the last 4 quarterly observations; horizon is right-exclusive, so max_ds + 1 day includes max_ds.
print("last quarter:", bounds.max_ds, " holdout starts:", bounds.cutoff)
display(spark.sql("SELECT geo, count(*) n, min(ds), max(ds) FROM qwi_series GROUP BY geo ORDER BY n DESC"))

# COMMAND ----------

forecast_sql = f"""
SELECT * FROM ai_forecast(
  observed => TABLE(SELECT ds, geo, turnover FROM qwi_series WHERE ds < DATE'{bounds.cutoff}'),
  horizon => '{bounds.horizon}',
  time_col => 'ds',
  value_col => 'turnover',
  group_col => 'geo',
  prediction_interval_width => 0.8
)
"""
fc = timed("02E_ai_forecast", lambda: spark.sql(forecast_sql))
fc = fc.withColumn("run_id", F.lit(RUN_ID)).withColumn("protocol", F.lit(PROTOCOL))
fc.write.mode("append").option("mergeSchema", "true").saveAsTable(FQE("ai_forecast_qwi"))
display(fc)

# COMMAND ----------

bt = spark.sql(f"""
WITH f AS (SELECT * FROM {FQE('ai_forecast_qwi')} WHERE run_id = '{RUN_ID}'),
a AS (SELECT * FROM qwi_series WHERE ds >= DATE'{bounds.cutoff}'),
naive AS (SELECT a.geo, a.ds, p.turnover AS naive FROM a JOIN qwi_series p ON p.geo = a.geo AND p.ds = add_months(a.ds, -12))
SELECT COUNT(*) AS holdout_points,
       ROUND(AVG(abs(f.turnover_forecast - a.turnover)), 4) AS mae_ai_forecast,
       ROUND(AVG(abs(n.naive - a.turnover)), 4) AS mae_seasonal_naive,
       ROUND(AVG(CASE WHEN a.turnover BETWEEN f.turnover_lower AND f.turnover_upper THEN 1.0 ELSE 0 END), 3) AS interval80_coverage
FROM a JOIN f ON f.geo = a.geo AND CAST(f.ds AS DATE) = a.ds
LEFT JOIN naive n ON n.geo = a.geo AND n.ds = a.ds
""")
display(bt)
bt.withColumn("run_id", F.lit(RUN_ID)).withColumn("metric_set", F.lit("02E_forecast_backtest")) \
    .write.mode("append").option("mergeSchema", "true").saveAsTable(FQE("ai_scores"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Evidence to capture
# MAGIC - `ai_scores` rows for this `RUN_ID` and one raw output per function (shape is a verify item).
# MAGIC - Elapsed seconds from `run_log`; billed usage from `99_cost_and_cleanup` (filter `usage_date` to today).
# MAGIC - Record whether each function ran in Free Edition, needed a preview toggle, or needed a SQL warehouse.
# MAGIC - If the forecast loses to the seasonal-naive baseline, record it plainly. Do not tune and re-run under the same protocol.
