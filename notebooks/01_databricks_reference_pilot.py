# Databricks notebook source
# MAGIC %md
# MAGIC # Illinois higher education: reference data practice run
# MAGIC Upload data/prepared/*.jsonl to a Unity Catalog Volume, set the path below,
# MAGIC then run on serverless compute. This notebook has not been executed in Databricks.
# MAGIC Candidates are unreviewed. This demonstrates ingestion and review, not labor forecasts.

# COMMAND ----------
VOLUME_PATH = '/Volumes/YOUR_CATALOG/YOUR_SCHEMA/YOUR_VOLUME/prepared'
assert 'YOUR_' not in VOLUME_PATH, 'Set VOLUME_PATH to the uploaded pilot files.'

# COMMAND ----------
from pyspark.sql import functions as F

# Session temporary views avoid requiring permission to create a catalog or tables.
for name in ['occupations', 'classes', 'mapping_review_queue']:
    frame = spark.read.json(f'{VOLUME_PATH}/{name}.jsonl')
    frame.createOrReplaceTempView(name)
    print(name, frame.count())

# COMMAND ----------
# Review the title baseline alongside authoritative O*NET descriptions.
display(spark.sql('''
SELECT m.class_code, m.class_title, m.occupation_title,
       m.title_similarity, o.description, m.review_status
FROM mapping_review_queue m
JOIN occupations o ON m.onet_code = o.onetsoc_code
WHERE m.candidate_rank = 1
ORDER BY m.title_similarity DESC, m.class_code
'''))

# COMMAND ----------
# Identify ambiguous title matches for manual review.
display(spark.sql('''
SELECT source_record_id, class_code, class_title,
       MAX(CASE WHEN candidate_rank = 1 THEN title_similarity END) AS best_score,
       MAX(CASE WHEN candidate_rank = 1 THEN title_similarity END) -
       MAX(CASE WHEN candidate_rank = 2 THEN title_similarity END) AS score_margin
FROM mapping_review_queue GROUP BY source_record_id, class_code, class_title
ORDER BY score_margin, class_code
'''))

# COMMAND ----------
# Optional next step after choosing a dedicated pilot schema:
# spark.table('classes').write.format('delta').mode('errorifexists').saveAsTable(
#     'YOUR_CATALOG.YOUR_PILOT_SCHEMA.sucss_classes')
# Keep raw source snapshots, reviewed bridges, and analytical facts in separate tables.
