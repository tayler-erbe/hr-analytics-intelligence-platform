-- =====================================================================
-- 02_ai_functions.sql — Cortex AI Functions on PUBLIC data, cost-capped
-- Functions exercised: AI_CLASSIFY, AI_COMPLETE (structured output),
-- AI_EXTRACT, AI_EMBED (+ VECTOR_COSINE_SIMILARITY), AI_SIMILARITY,
-- AI_AGG, AI_SUMMARIZE_AGG, AI_FILTER (+ PROMPT).
--
-- Status (docs searched 2026-11-06; re-check the AI Functions page in your
-- account's docs): AI_CLASSIFY, AI_FILTER, AI_AGG, AI_SIMILARITY reached GA
-- 2025-11-04; AI_EXTRACT, AI_TRANSLATE, AI_SENTIMENT were already GA.
-- AI_COMPLETE / AI_EMBED / AI_SUMMARIZE_AGG status: verify in account.
-- Trial accounts without a payment method were documented as limited to
-- ~1 credit/day of Cortex LLM function usage — keep the caps below.
--
-- Scoring rules (project policy): no model grades another model. Every
-- result table has blank reviewer_* columns for a HUMAN reviewer, plus
-- deterministic checks (agreement with the lexical baseline, hallucinated
-- task-id rate, parse-failure rate). Agreement is NOT accuracy.
-- Preserve every attempted row, including NULL/error outputs.
-- Rubric: A1 (structured accuracy—indirect), A2 (evidence/abstention),
-- A3 (controlled tool use), C1 (AI credits). Evidence rows S02*.
-- =====================================================================

USE ROLE HR_KIT_ADMIN;
USE WAREHOUSE HR_KIT_WH;
USE SCHEMA HR_KIT.AI_EVAL;
ALTER SESSION SET QUERY_TAG = 'hr_kit:02_ai_functions';

-- ---------------------------------------------------------------------
-- 0. Caps and model choice (EDIT HERE ONLY; record values in evidence)
-- ---------------------------------------------------------------------
SET N_CLASSES  = 50;    -- SUCSS classes sent to AI_CLASSIFY / embedding mapping
SET N_OCC      = 20;    -- O*NET occupations sent to AI_COMPLETE / AI_EXTRACT
SET N_TASKS    = 200;   -- O*NET tasks sent to AI_FILTER
SET N_AGG_GRPS = 5;     -- groups for AI_AGG / AI_SUMMARIZE_AGG
SET LLM_MODEL  = 'llama3.3-70b';                  -- verify availability in your region (see below)
SET EMBED_MODEL = 'snowflake-arctic-embed-l-v2.0'; -- 1024-dim; verify in account
SET KIT_RUN_ID = (SELECT 'run_' || TO_CHAR(CURRENT_TIMESTAMP(), 'YYYYMMDD_HH24MISS'));

-- Model availability (2026 model RBAC). One of these should list models — verify in account:
-- SHOW MODELS IN SNOWFLAKE.MODELS;
-- If a model is "unavailable in your region", see 00_setup.sql §2 (cross-region).

-- Run log: one row per AI step, with the query id for later cost/latency joins
CREATE TABLE IF NOT EXISTS AI_RUN_LOG (
  kit_run_id STRING, step STRING, ai_function STRING, model STRING,
  n_input_rows NUMBER, query_id STRING, logged_at TIMESTAMP_LTZ DEFAULT CURRENT_TIMESTAMP());

-- Deterministic samples (HASH ordering is stable across runs; record N)
CREATE OR REPLACE TABLE SAMPLE_SUCSS AS
SELECT source_record_id, class_code, class_title
FROM HR_KIT.CURATED.V_SUCSS_CLASS
ORDER BY HASH(source_record_id), source_record_id
LIMIT $N_CLASSES;

CREATE OR REPLACE TABLE SAMPLE_OCC AS
SELECT o.onetsoc_code, o.occupation_title, o.occupation_description,
       LISTAGG('[' || t.task_id || '] ' || t.task_text, '\n') WITHIN GROUP (ORDER BY t.task_id) AS task_block,
       COUNT(*) AS n_tasks
FROM HR_KIT.CURATED.V_ONET_OCCUPATION o
JOIN HR_KIT.CURATED.V_ONET_TASK t USING (onetsoc_code)
WHERE LEFT(o.onetsoc_code, 2) IN ('11','13','15','25','43')   -- mgmt, business ops, computing, education, office support
GROUP BY 1,2,3
ORDER BY HASH(o.onetsoc_code), o.onetsoc_code
LIMIT $N_OCC;

-- =====================================================================
-- 2a. AI_CLASSIFY — SUCSS class titles into job families
-- =====================================================================
-- Families are a kit-defined, unapproved taxonomy for exercising the
-- function. Descriptions ≤ 25 words; task_description ≤ 50 words (doc limits).
CREATE OR REPLACE TABLE R_CLASSIFY_FAMILY AS
SELECT $KIT_RUN_ID AS kit_run_id,
       s.source_record_id, s.class_code, s.class_title,
       AI_CLASSIFY(
         s.class_title,
         [
           {'label': 'information_technology',  'description': 'software, networks, systems, data, telecommunications, computer support'},
           {'label': 'finance_accounting',      'description': 'accounting, auditing, budgeting, payroll, purchasing, grants and contracts finance'},
           {'label': 'human_resources',         'description': 'personnel, recruiting, classification, benefits, training, labor relations'},
           {'label': 'administrative_clerical', 'description': 'office support, clerks, secretaries, records, data entry, reception'},
           {'label': 'facilities_trades',       'description': 'building maintenance, skilled trades, grounds, custodial, utilities, construction'},
           {'label': 'health_medical',          'description': 'nursing, clinical, pharmacy, laboratory, veterinary, health services'},
           {'label': 'public_safety',           'description': 'police, security, fire, emergency management, safety inspection'},
           {'label': 'food_residential',        'description': 'food service, dining, housing, residence hall operations'},
           {'label': 'academic_student_support','description': 'advising, admissions, library, student services, instructional support'},
           {'label': 'research_science',        'description': 'research, laboratory science, engineering, agriculture, environmental science'},
           {'label': 'communications_creative', 'description': 'media, public relations, graphics, photography, editing, broadcasting'},
           {'label': 'management_supervision',  'description': 'directors, managers, supervisors, administrators leading units'},
           {'label': 'other_unclear',           'description': 'title alone is insufficient to choose a family'}
         ],
         {'task_description': 'Assign an Illinois university civil-service job class title to one broad job family. Use other_unclear when the title alone is ambiguous.'}
       ) AS raw_output,
       raw_output:labels[0]::STRING AS predicted_family,
       ARRAY_SIZE(raw_output:labels) AS n_labels,
       CAST(NULL AS STRING) AS reviewer_family,       -- HUMAN fills
       CAST(NULL AS STRING) AS reviewer_id,
       CAST(NULL AS STRING) AS review_note
FROM SAMPLE_SUCSS s;
INSERT INTO AI_RUN_LOG(kit_run_id, step, ai_function, model, n_input_rows, query_id)
  SELECT $KIT_RUN_ID, '2a', 'AI_CLASSIFY', 'default', $N_CLASSES, LAST_QUERY_ID(-1);
-- NOTE: LAST_QUERY_ID(-1) inside an INSERT refers to the CTAS just before it; verify in account,
-- or copy the query id from Query History into evidence manually.

-- Deterministic checks (no model grading)
SELECT COUNT(*) AS attempted,
       COUNT_IF(predicted_family IS NULL)         AS null_or_failed,
       COUNT_IF(predicted_family = 'other_unclear') AS abstained,
       COUNT_IF(n_labels > 1)                      AS multi_label_in_single_mode
FROM R_CLASSIFY_FAMILY;
SELECT predicted_family, COUNT(*) n FROM R_CLASSIFY_FAMILY GROUP BY 1 ORDER BY 2 DESC;
-- After human review: accuracy = matches / reviewed (report reviewed count separately)
SELECT COUNT_IF(reviewer_family IS NOT NULL) AS reviewed,
       COUNT_IF(reviewer_family = predicted_family) AS agree,
       DIV0(agree, reviewed) AS human_agreement_rate
FROM R_CLASSIFY_FAMILY;

-- =====================================================================
-- 2b. AI_COMPLETE with structured output — skills/tools from O*NET tasks
-- =====================================================================
-- The model must cite the task_id(s) behind each item. A deterministic
-- check then measures cited ids that do not exist for that occupation.
CREATE OR REPLACE TABLE R_COMPLETE_SKILLS AS
SELECT $KIT_RUN_ID AS kit_run_id, o.onetsoc_code, o.occupation_title, o.n_tasks,
       AI_COMPLETE(
         model => $LLM_MODEL,
         prompt => 'You extract skills and tools ONLY from the O*NET task statements below. '
                || 'Cite the bracketed task ids that support each item. If no tools are named, return an empty list. '
                || 'Do not infer automation risk, obsolescence or competency of any person.\n\n'
                || 'Occupation: ' || o.occupation_title || '\nTasks:\n' || o.task_block,
         model_parameters => {'temperature': 0, 'max_tokens': 800},
         response_format => {
           'type': 'json',
           'schema': {
             'type': 'object',
             'properties': {
               'skills': {'type': 'array', 'items': {'type': 'object', 'properties': {
                    'skill': {'type': 'string'},
                    'task_ids': {'type': 'array', 'items': {'type': 'string'}}},
                    'required': ['skill', 'task_ids']}},
               'tools': {'type': 'array', 'items': {'type': 'object', 'properties': {
                    'tool': {'type': 'string'},
                    'task_ids': {'type': 'array', 'items': {'type': 'string'}}},
                    'required': ['tool', 'task_ids']}}
             },
             'required': ['skills', 'tools']
           }
         }
       ) AS raw_output,
       CAST(NULL AS NUMBER) AS reviewer_precision_0_5,   -- HUMAN fills
       CAST(NULL AS STRING) AS reviewer_id,
       CAST(NULL AS STRING) AS review_note
FROM SAMPLE_OCC o;
INSERT INTO AI_RUN_LOG(kit_run_id, step, ai_function, model, n_input_rows, query_id)
  SELECT $KIT_RUN_ID, '2b', 'AI_COMPLETE(structured)', $LLM_MODEL, $N_OCC, LAST_QUERY_ID(-1);

-- Normalize output (works whether AI_COMPLETE returns OBJECT or a JSON string — verify in account)
CREATE OR REPLACE VIEW V_COMPLETE_SKILLS_PARSED AS
SELECT r.*, IFF(IS_VARCHAR(TO_VARIANT(r.raw_output)),
                TRY_PARSE_JSON(TO_VARIANT(r.raw_output)::STRING),
                TO_VARIANT(r.raw_output)) AS parsed
FROM R_COMPLETE_SKILLS r;

-- Grounding check: cited task ids that do not exist for that occupation
WITH cited AS (
  SELECT p.onetsoc_code, 'skill' AS kind, f.value:skill::STRING AS item, c.value::STRING AS cited_task_id
  FROM V_COMPLETE_SKILLS_PARSED p,
       LATERAL FLATTEN(input => p.parsed:skills) f,
       LATERAL FLATTEN(input => f.value:task_ids, OUTER => TRUE) c
  UNION ALL
  SELECT p.onetsoc_code, 'tool', f.value:tool::STRING, c.value::STRING
  FROM V_COMPLETE_SKILLS_PARSED p,
       LATERAL FLATTEN(input => p.parsed:tools) f,
       LATERAL FLATTEN(input => f.value:task_ids, OUTER => TRUE) c
)
SELECT COUNT(*) AS citations,
       COUNT_IF(cited_task_id IS NULL) AS items_without_citation,
       COUNT_IF(cited_task_id IS NOT NULL AND t.task_id IS NULL) AS invalid_task_id,
       DIV0(invalid_task_id, COUNT_IF(cited_task_id IS NOT NULL)) AS invalid_citation_rate
FROM cited c
LEFT JOIN HR_KIT.CURATED.V_ONET_TASK t
  ON t.onetsoc_code = c.onetsoc_code
 AND t.task_id::STRING = REGEXP_REPLACE(c.cited_task_id, '[^0-9]', '');
SELECT COUNT(*) attempted, COUNT_IF(parsed IS NULL) AS parse_failures FROM V_COMPLETE_SKILLS_PARSED;

-- Optional: tool items vs O*NET's own technology-skill list (lexical overlap, not accuracy)
-- SELECT ... JOIN HR_KIT.CURATED.V_ONET_TECH_SKILL ON CONTAINS(LOWER(technology_example), LOWER(item))

-- =====================================================================
-- 2c. AI_EXTRACT — targeted fields from the same task text
-- =====================================================================
-- responseFormat simple object form {label: question}. Output shape is
-- {"response": {...}, "error": ...} per docs — verify in account.
CREATE OR REPLACE TABLE R_EXTRACT_TASKS AS
SELECT $KIT_RUN_ID AS kit_run_id, o.onetsoc_code, o.occupation_title,
       AI_EXTRACT(
         text => o.task_block,
         responseFormat => {
           'primary_work_object': 'What is the main thing this occupation works on (e.g., data, buildings, students, budgets)?',
           'software_or_equipment': 'Which software, systems, tools or equipment are explicitly named? Answer "none named" if none.',
           'people_interaction': 'Which groups of people does the work involve (e.g., students, customers, staff)?'
         }
       ) AS raw_output,
       raw_output:response AS extracted,
       CAST(NULL AS NUMBER) AS reviewer_correct_fields_0_3,
       CAST(NULL AS STRING) AS reviewer_id
FROM SAMPLE_OCC o;
INSERT INTO AI_RUN_LOG(kit_run_id, step, ai_function, model, n_input_rows, query_id)
  SELECT $KIT_RUN_ID, '2c', 'AI_EXTRACT', 'default', $N_OCC, LAST_QUERY_ID(-1);

-- Literal-grounding check for the "named software" field (did the answer appear in the source text?)
SELECT onetsoc_code, extracted:software_or_equipment::STRING AS sw,
       IFF(sw IS NULL OR LOWER(sw) LIKE '%none%', 'none_claimed',
           IFF(CONTAINS(LOWER(task_block), LOWER(SPLIT_PART(sw, ',', 1))), 'first_item_in_text', 'first_item_not_in_text')) AS grounding
FROM R_EXTRACT_TASKS JOIN SAMPLE_OCC USING (onetsoc_code);

-- =====================================================================
-- 2d. Embeddings / AI_SIMILARITY — SUCSS → O*NET mapping vs lexical baseline
-- =====================================================================
-- Embedding every occupation once (≈1k rows) is cheaper than AI_SIMILARITY
-- on a full cross join. AI_SIMILARITY is then used only to re-score the
-- existing lexical top-5 pairs.
CREATE TABLE IF NOT EXISTS EMB_ONET_OCC (onetsoc_code STRING, emb_model STRING, emb VECTOR(FLOAT, 1024), embedded_at TIMESTAMP_LTZ);
INSERT INTO EMB_ONET_OCC
SELECT onetsoc_code, $EMBED_MODEL,
       AI_EMBED($EMBED_MODEL, occupation_title || '. ' || occupation_description),
       CURRENT_TIMESTAMP()
FROM HR_KIT.CURATED.V_ONET_OCCUPATION
WHERE onetsoc_code NOT IN (SELECT onetsoc_code FROM EMB_ONET_OCC WHERE emb_model = $EMBED_MODEL);
INSERT INTO AI_RUN_LOG(kit_run_id, step, ai_function, model, n_input_rows, query_id)
  SELECT $KIT_RUN_ID, '2d-occ', 'AI_EMBED', $EMBED_MODEL, (SELECT COUNT(*) FROM EMB_ONET_OCC), LAST_QUERY_ID(-1);

CREATE OR REPLACE TABLE EMB_SUCSS AS
SELECT source_record_id, class_title, $EMBED_MODEL AS emb_model,
       AI_EMBED($EMBED_MODEL, class_title)::VECTOR(FLOAT, 1024) AS emb
FROM SAMPLE_SUCSS;
INSERT INTO AI_RUN_LOG(kit_run_id, step, ai_function, model, n_input_rows, query_id)
  SELECT $KIT_RUN_ID, '2d-cls', 'AI_EMBED', $EMBED_MODEL, $N_CLASSES, LAST_QUERY_ID(-1);

CREATE OR REPLACE TABLE R_EMBED_TOP5 AS
SELECT $KIT_RUN_ID AS kit_run_id, s.source_record_id, s.class_title, o.onetsoc_code,
       VECTOR_COSINE_SIMILARITY(s.emb, o.emb) AS cosine_sim,
       ROW_NUMBER() OVER (PARTITION BY s.source_record_id ORDER BY cosine_sim DESC, o.onetsoc_code) AS embed_rank
FROM EMB_SUCSS s CROSS JOIN EMB_ONET_OCC o
WHERE o.emb_model = $EMBED_MODEL
QUALIFY embed_rank <= 5;

-- AI_SIMILARITY on the existing lexical top-5 candidates only (≤ 5 × N_CLASSES calls)
CREATE OR REPLACE TABLE R_SIMILARITY_RESCORE AS
SELECT $KIT_RUN_ID AS kit_run_id, c.source_record_id, s.class_title, c.onetsoc_code,
       o.occupation_title, c.candidate_rank AS lexical_rank, c.lexical_score,
       AI_SIMILARITY(s.class_title, o.occupation_title) AS ai_similarity,   -- optional 3rd arg {'model': ...}: verify in account
       ROW_NUMBER() OVER (PARTITION BY c.source_record_id ORDER BY ai_similarity DESC, c.onetsoc_code) AS ai_rank
FROM HR_KIT.CURATED.V_SUCSS_ONET_CANDIDATE c
JOIN SAMPLE_SUCSS s USING (source_record_id)
JOIN HR_KIT.CURATED.V_ONET_OCCUPATION o USING (onetsoc_code)
WHERE c.candidate_rank <= 5;
INSERT INTO AI_RUN_LOG(kit_run_id, step, ai_function, model, n_input_rows, query_id)
  SELECT $KIT_RUN_ID, '2d-sim', 'AI_SIMILARITY', 'default', (SELECT COUNT(*) FROM R_SIMILARITY_RESCORE), LAST_QUERY_ID(-1);

-- Comparison table for HUMAN review: one row per class with the three top-1 picks
CREATE OR REPLACE TABLE R_MAPPING_COMPARE AS
SELECT s.source_record_id, s.class_code, s.class_title,
       lx.onetsoc_code AS lexical_top1,
       em.onetsoc_code AS embed_top1,
       rs.onetsoc_code AS ai_similarity_top1_within_lexical5,
       (SELECT COUNT(*) FROM R_EMBED_TOP5 e
          JOIN HR_KIT.CURATED.V_SUCSS_ONET_CANDIDATE c2
            ON c2.source_record_id = e.source_record_id AND c2.onetsoc_code = e.onetsoc_code AND c2.candidate_rank <= 5
         WHERE e.source_record_id = s.source_record_id) AS overlap_at_5,
       CAST(NULL AS STRING) AS reviewer_best_onetsoc,     -- HUMAN fills ('none' allowed)
       CAST(NULL AS STRING) AS reviewer_id,
       CAST(NULL AS STRING) AS review_note
FROM SAMPLE_SUCSS s
LEFT JOIN HR_KIT.CURATED.V_SUCSS_ONET_CANDIDATE lx ON lx.source_record_id = s.source_record_id AND lx.candidate_rank = 1
LEFT JOIN R_EMBED_TOP5 em ON em.source_record_id = s.source_record_id AND em.embed_rank = 1
LEFT JOIN R_SIMILARITY_RESCORE rs ON rs.source_record_id = s.source_record_id AND rs.ai_rank = 1;
-- If the correlated subquery is rejected, compute overlap_at_5 in a CTE (verify in account).

SELECT COUNT(*) AS classes,
       COUNT_IF(lexical_top1 = embed_top1) AS lexical_embed_top1_agree,
       COUNT_IF(lexical_top1 = ai_similarity_top1_within_lexical5) AS lexical_aisim_top1_agree,
       AVG(overlap_at_5) AS mean_overlap_at_5,
       COUNT_IF(reviewer_best_onetsoc IS NOT NULL) AS reviewed,
       COUNT_IF(reviewer_best_onetsoc = lexical_top1) AS lexical_correct,
       COUNT_IF(reviewer_best_onetsoc = embed_top1)   AS embed_correct,
       COUNT_IF(reviewer_best_onetsoc = ai_similarity_top1_within_lexical5) AS aisim_correct
FROM R_MAPPING_COMPARE;
-- Agreement between methods is NOT accuracy; only the reviewed columns are.

-- =====================================================================
-- 2e. AI_AGG and AI_SUMMARIZE_AGG — cross-row summaries
-- =====================================================================
CREATE OR REPLACE TABLE R_AGG AS
WITH grp AS (
  SELECT LEFT(onetsoc_code, 4) AS soc_minor_group, task_text
  FROM HR_KIT.CURATED.V_ONET_TASK
  WHERE LEFT(onetsoc_code, 4) IN (
    SELECT DISTINCT LEFT(onetsoc_code, 4) FROM HR_KIT.CURATED.V_ONET_TASK
    WHERE LEFT(onetsoc_code, 2) IN ('15','25','43')
    ORDER BY 1 LIMIT $N_AGG_GRPS)
)
SELECT $KIT_RUN_ID AS kit_run_id, soc_minor_group, COUNT(*) AS n_tasks,
       AI_AGG(task_text, 'List the five most common kinds of work activity in these O*NET task statements, as short phrases. Use only the statements provided.') AS ai_agg_output,
       AI_SUMMARIZE_AGG(task_text) AS ai_summarize_agg_output,
       CAST(NULL AS NUMBER) AS reviewer_faithfulness_0_5,
       CAST(NULL AS STRING) AS reviewer_id
FROM grp
GROUP BY soc_minor_group;
INSERT INTO AI_RUN_LOG(kit_run_id, step, ai_function, model, n_input_rows, query_id)
  SELECT $KIT_RUN_ID, '2e', 'AI_AGG+AI_SUMMARIZE_AGG', 'default', (SELECT SUM(n_tasks) FROM R_AGG), LAST_QUERY_ID(-1);
SELECT * FROM R_AGG;

-- =====================================================================
-- 2f. AI_FILTER — boolean screen vs a deterministic keyword baseline
-- =====================================================================
CREATE OR REPLACE TABLE R_FILTER_DATA_TASKS AS
WITH t AS (
  SELECT onetsoc_code, task_id, task_text
  FROM HR_KIT.CURATED.V_ONET_TASK
  ORDER BY HASH(onetsoc_code, task_id) LIMIT $N_TASKS
)
SELECT $KIT_RUN_ID AS kit_run_id, onetsoc_code, task_id, task_text,
       AI_FILTER(PROMPT('Does this job task primarily involve collecting, analyzing, managing or reporting data or records? Task: {0}', task_text)) AS ai_filter_data_task,
       REGEXP_LIKE(LOWER(task_text), '.*(data|database|record|report|statistic|spreadsheet|analy).*') AS keyword_baseline,
       CAST(NULL AS BOOLEAN) AS reviewer_label,
       CAST(NULL AS STRING)  AS reviewer_id
FROM t;
INSERT INTO AI_RUN_LOG(kit_run_id, step, ai_function, model, n_input_rows, query_id)
  SELECT $KIT_RUN_ID, '2f', 'AI_FILTER', 'default', $N_TASKS, LAST_QUERY_ID(-1);

SELECT COUNT(*) attempted,
       COUNT_IF(ai_filter_data_task IS NULL) AS null_outputs,
       COUNT_IF(ai_filter_data_task AND keyword_baseline) AS both_true,
       COUNT_IF(ai_filter_data_task AND NOT keyword_baseline) AS ai_only,
       COUNT_IF(NOT ai_filter_data_task AND keyword_baseline) AS keyword_only,
       COUNT_IF(reviewer_label IS NOT NULL) AS reviewed,
       COUNT_IF(reviewer_label = ai_filter_data_task) AS ai_correct,
       COUNT_IF(reviewer_label = keyword_baseline)    AS keyword_correct
FROM R_FILTER_DATA_TASKS;

-- =====================================================================
-- 2g. Repeatability (variability) — re-run one step and diff
-- =====================================================================
-- Rubric asks for multiple runs on a subset. Re-run 2a with the same input:
CREATE OR REPLACE TABLE R_CLASSIFY_FAMILY_RERUN AS
SELECT source_record_id, AI_CLASSIFY(class_title,
         ['information_technology','finance_accounting','human_resources','administrative_clerical',
          'facilities_trades','health_medical','public_safety','food_residential',
          'academic_student_support','research_science','communications_creative',
          'management_supervision','other_unclear'])
       :labels[0]::STRING AS predicted_family_rerun_labels_only
FROM SAMPLE_SUCSS;
-- NB: this rerun deliberately drops descriptions; it measures sensitivity to
-- label descriptions as well as run-to-run variation. For a pure repeat,
-- copy the 2a statement verbatim into a new table instead.
SELECT COUNT(*) n, COUNT_IF(a.predicted_family = b.predicted_family_rerun_labels_only) AS same_label
FROM R_CLASSIFY_FAMILY a JOIN R_CLASSIFY_FAMILY_RERUN b USING (source_record_id);

-- =====================================================================
-- 2h. Cost & latency evidence for this script
-- =====================================================================
-- Latency from QUERY_HISTORY (near real-time via INFORMATION_SCHEMA)
SELECT query_id, LEFT(query_text, 80) AS stmt, total_elapsed_time / 1000 AS seconds,
       rows_produced, execution_status, error_message
FROM TABLE(HR_KIT.INFORMATION_SCHEMA.QUERY_HISTORY_BY_SESSION(RESULT_LIMIT => 200))
WHERE query_tag = 'hr_kit:02_ai_functions'
ORDER BY start_time;

-- AI credits (ACCOUNT_USAGE latency can be up to a few hours). Column names: verify in account.
SELECT * FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_AISQL_USAGE_HISTORY
WHERE query_id IN (SELECT query_id FROM HR_KIT.AI_EVAL.AI_RUN_LOG WHERE kit_run_id = $KIT_RUN_ID);
-- Daily roll-up of all AI services credits:
SELECT usage_date, service_type, SUM(credits_used) AS credits
FROM SNOWFLAKE.ACCOUNT_USAGE.METERING_DAILY_HISTORY
WHERE usage_date >= DATEADD(DAY, -7, CURRENT_DATE()) AND service_type ILIKE '%AI%'
GROUP BY 1, 2 ORDER BY 1, 2;

GRANT SELECT ON ALL TABLES IN SCHEMA HR_KIT.AI_EVAL TO ROLE HR_KIT_ANALYST;
GRANT SELECT ON ALL VIEWS  IN SCHEMA HR_KIT.AI_EVAL TO ROLE HR_KIT_ANALYST;
