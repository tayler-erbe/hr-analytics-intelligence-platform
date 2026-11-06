-- =====================================================================
-- 03_cortex_search.sql — Cortex Search over O*NET occupation + task text
-- Purpose: role Q&A retrieval ("which occupations do X?") with citations
-- that an agent (05) can use. PUBLIC DATA ONLY.
-- Rubric: A2 (document evidence/abstention — retrieval half), A3, C1.
-- Evidence rows S03*.
--
-- Syntax checked against docs search results 2026-11-06:
--   CREATE CORTEX SEARCH SERVICE ... ON <col> ATTRIBUTES ... WAREHOUSE ...
--   TARGET_LAG ... [EMBEDDING_MODEL ...] AS <query>
-- EMBEDDING_MODEL cannot be altered after creation (default
-- snowflake-arctic-embed-m-v1.5). Newer docs may show TEXT INDEXES /
-- VECTOR INDEXES clauses instead of ON — the ON form is used here; verify.
-- Cost: index build (warehouse + embedding tokens) and SERVING cost that
-- accrues while the service exists. Drop or suspend it when finished.
-- =====================================================================

USE ROLE HR_KIT_ADMIN;
USE WAREHOUSE HR_KIT_WH;
USE SCHEMA HR_KIT.AI_EVAL;
ALTER SESSION SET QUERY_TAG = 'hr_kit:03_cortex_search';

-- Cortex Search needs change tracking on the base tables behind the source query
ALTER TABLE HR_KIT.HR_PUBLIC.ONET_OCCUPATION      SET CHANGE_TRACKING = TRUE;
ALTER TABLE HR_KIT.HR_PUBLIC.ONET_TASK_STATEMENT  SET CHANGE_TRACKING = TRUE;
ALTER TABLE HR_KIT.HR_PUBLIC.ONET_ALTERNATE_TITLE SET CHANGE_TRACKING = TRUE;
ALTER TABLE HR_KIT.HR_PUBLIC.ONET_JOB_ZONE        SET CHANGE_TRACKING = TRUE;

-- One row per searchable chunk: an occupation profile chunk and one chunk per task.
-- Short chunks (< ~500 tokens) retrieve best; tasks are naturally short.
CREATE OR REPLACE TABLE ONET_SEARCH_CORPUS AS
SELECT 'occ:' || onetsoc_code                          AS doc_id,
       'occupation'                                    AS doc_type,
       onetsoc_code, occupation_title, job_zone::STRING AS job_zone,
       occupation_title || '. Also called: ' || COALESCE(alternate_titles, '') ||
       '. ' || occupation_description                  AS search_text,
       source_vintage
FROM HR_KIT.CURATED.V_ONET_ROLE_DOC
UNION ALL
SELECT 'task:' || t.onetsoc_code || ':' || t.task_id,
       'task',
       t.onetsoc_code, o.occupation_title, NULL,
       o.occupation_title || ' task (' || COALESCE(t.task_type, 'n/a') || '): ' || t.task_text,
       t.source_vintage
FROM HR_KIT.CURATED.V_ONET_TASK t
JOIN HR_KIT.CURATED.V_ONET_OCCUPATION o USING (onetsoc_code);
ALTER TABLE ONET_SEARCH_CORPUS SET CHANGE_TRACKING = TRUE;
SELECT doc_type, COUNT(*) FROM ONET_SEARCH_CORPUS GROUP BY 1;   -- evidence: corpus size

-- Build timing: record wall time of this statement (S03a)
CREATE OR REPLACE CORTEX SEARCH SERVICE HR_KIT.AI_EVAL.ONET_ROLE_SEARCH
  ON search_text
  ATTRIBUTES doc_type, onetsoc_code, occupation_title, job_zone
  WAREHOUSE = HR_KIT_WH
  TARGET_LAG = '7 days'
  EMBEDDING_MODEL = 'snowflake-arctic-embed-l-v2.0'   -- verify availability; omit to use the default
  COMMENT = 'O*NET 31.0 occupation and task text (public). Kit v0.1.'
AS (
  SELECT search_text, doc_id, doc_type, onetsoc_code, occupation_title, job_zone, source_vintage
  FROM HR_KIT.AI_EVAL.ONET_SEARCH_CORPUS
);

SHOW CORTEX SEARCH SERVICES IN SCHEMA HR_KIT.AI_EVAL;
DESCRIBE CORTEX SEARCH SERVICE HR_KIT.AI_EVAL.ONET_ROLE_SEARCH;   -- record indexing_state, source_data_num_rows

GRANT USAGE ON CORTEX SEARCH SERVICE HR_KIT.AI_EVAL.ONET_ROLE_SEARCH TO ROLE HR_KIT_ANALYST;

-- ---------------------------------------------------------------------
-- Interactive check (SEARCH_PREVIEW takes a constant JSON string)
-- ---------------------------------------------------------------------
SELECT PARSE_JSON(SNOWFLAKE.CORTEX.SEARCH_PREVIEW(
  'HR_KIT.AI_EVAL.ONET_ROLE_SEARCH',
  '{"query": "who backs up and restores databases and tunes performance",
    "columns": ["doc_id","doc_type","onetsoc_code","occupation_title","search_text"],
    "limit": 5}'))['results'] AS results;

-- Filtered to occupation-level chunks only
SELECT PARSE_JSON(SNOWFLAKE.CORTEX.SEARCH_PREVIEW(
  'HR_KIT.AI_EVAL.ONET_ROLE_SEARCH',
  '{"query": "advises students on course selection and academic plans",
    "columns": ["doc_id","onetsoc_code","occupation_title"],
    "filter": {"@eq": {"doc_type": "occupation"}},
    "limit": 5}'))['results'] AS results;

-- ---------------------------------------------------------------------
-- Retrieval test set (kit-authored expected codes = PROPOSED; a human
-- reviewer must approve/edit expected_codes BEFORE scoring). Codes are
-- O*NET-SOC 2019 taxonomy as used by O*NET 31.0.
-- ---------------------------------------------------------------------
CREATE OR REPLACE TABLE SEARCH_TESTS (
  test_id STRING, question STRING, expected_codes ARRAY, expect_abstain BOOLEAN, approved_by STRING);
INSERT INTO SEARCH_TESTS
SELECT column1, column2, PARSE_JSON(column3), column4, NULL FROM VALUES
 ('CS01','who backs up and restores databases and tunes database performance','["15-1242.00","15-1243.00"]', FALSE),
 ('CS02','role that designs data models and database architecture','["15-1243.00","15-1242.00"]', FALSE),
 ('CS03','helps faculty and staff fix computer and software problems at a help desk','["15-1232.00"]', FALSE),
 ('CS04','installs and maintains servers, networks and user accounts','["15-1244.00"]', FALSE),
 ('CS05','monitors systems for security breaches and investigates incidents','["15-1212.00"]', FALSE),
 ('CS06','builds statistical and machine learning models to analyze data','["15-2051.00"]', FALSE),
 ('CS07','recruits, screens and interviews job applicants','["13-1071.00"]', FALSE),
 ('CS08','analyzes job duties to set pay grades and job classifications','["13-1141.00"]', FALSE),
 ('CS09','plans and directs the human resources activities of an organization','["11-3121.00"]', FALSE),
 ('CS10','examines financial records and prepares audit reports','["13-2011.00"]', FALSE),
 ('CS11','advises college students on academic and career plans','["21-1012.00"]', FALSE),
 ('CS12','directs student services or academic affairs at a university','["11-9033.00"]', FALSE),
 ('CS13','manages library collections and helps patrons find information','["25-4022.00"]', FALSE),
 ('CS14','designs and delivers employee training programs','["13-1151.00"]', FALSE),
 ('CS15','writes and tests computer applications','["15-1252.00"]', FALSE),
 -- Out-of-scope / abstention probes: results will still be returned; the
 -- AGENT (05) must say the corpus cannot answer. Here we only log scores.
 ('CS16','what is the current salary of the university registrar','[]', TRUE),
 ('CS17','which of our employees are at risk of being automated','[]', TRUE);

CREATE TABLE IF NOT EXISTS R_SEARCH_RESULTS (
  run_ts TIMESTAMP_LTZ, test_id STRING, question STRING, result_rank NUMBER,
  doc_id STRING, onetsoc_code STRING, occupation_title STRING, elapsed_ms NUMBER);
-- Archive the previous run (keep every attempt), then start clean for this scored run
CREATE TABLE IF NOT EXISTS R_SEARCH_RESULTS_ARCHIVE LIKE R_SEARCH_RESULTS;
INSERT INTO R_SEARCH_RESULTS_ARCHIVE SELECT * FROM R_SEARCH_RESULTS;
TRUNCATE TABLE R_SEARCH_RESULTS;

EXECUTE IMMEDIATE $$
DECLARE
  c1 CURSOR FOR SELECT test_id, question FROM HR_KIT.AI_EVAL.SEARCH_TESTS ORDER BY test_id;
  t0 TIMESTAMP_LTZ;
  sql_txt STRING;
BEGIN
  FOR r IN c1 DO
    t0 := CURRENT_TIMESTAMP();
    sql_txt := 'INSERT INTO HR_KIT.AI_EVAL.R_SEARCH_RESULTS ' ||
      'SELECT CURRENT_TIMESTAMP(), ''' || r.test_id || ''', ''' || REPLACE(r.question, '''', '''''') || ''', ' ||
      '       f.index + 1, f.value:doc_id::STRING, f.value:onetsoc_code::STRING, f.value:occupation_title::STRING, NULL ' ||
      'FROM TABLE(FLATTEN(PARSE_JSON(SNOWFLAKE.CORTEX.SEARCH_PREVIEW(''HR_KIT.AI_EVAL.ONET_ROLE_SEARCH'', ' ||
      '''{"query": "' || REPLACE(r.question, '''', '') || '", "columns": ["doc_id","onetsoc_code","occupation_title"], "limit": 10}''))[''results''])) f';
    EXECUTE IMMEDIATE :sql_txt;
    UPDATE HR_KIT.AI_EVAL.R_SEARCH_RESULTS
       SET elapsed_ms = DATEDIFF(MILLISECOND, :t0, CURRENT_TIMESTAMP())
     WHERE test_id = r.test_id AND elapsed_ms IS NULL;
  END FOR;
  RETURN 'search tests done';
END;
$$;

-- Deterministic retrieval metrics on APPROVED expected codes only
WITH first_hit AS (
  SELECT r.test_id, MIN(r.result_rank) AS first_rank
  FROM R_SEARCH_RESULTS r
  JOIN SEARCH_TESTS t USING (test_id)
  WHERE ARRAY_CONTAINS(r.onetsoc_code::VARIANT, t.expected_codes)
  GROUP BY r.test_id
)
SELECT COUNT(*)                                    AS answerable_tests,
       COUNT_IF(t.approved_by IS NOT NULL)         AS approved_tests,
       COUNT_IF(h.first_rank = 1)                  AS hit_at_1,
       COUNT_IF(h.first_rank <= 5)                 AS hit_at_5,
       AVG(IFF(h.first_rank IS NULL, 0, 1 / h.first_rank)) AS mrr_at_10
FROM SEARCH_TESTS t LEFT JOIN first_hit h USING (test_id)
WHERE NOT t.expect_abstain;
-- Report the metrics only once approved_tests = answerable_tests (reviewer approved the expected codes).

SELECT test_id, MAX(elapsed_ms) AS ms FROM R_SEARCH_RESULTS GROUP BY 1 ORDER BY 1;  -- latency per query (includes SQL overhead)

-- ---------------------------------------------------------------------
-- Cost evidence + cleanup
-- ---------------------------------------------------------------------
-- Views (names verify in account): CORTEX_SEARCH_DAILY_USAGE_HISTORY, CORTEX_SEARCH_SERVING_USAGE_HISTORY
SELECT * FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_SEARCH_DAILY_USAGE_HISTORY
WHERE service_name = 'ONET_ROLE_SEARCH' ORDER BY usage_date DESC;

-- When finished with 03 AND 05, stop serving cost:
-- ALTER CORTEX SEARCH SERVICE HR_KIT.AI_EVAL.ONET_ROLE_SEARCH SUSPEND SERVING;   -- verify in account
-- DROP CORTEX SEARCH SERVICE HR_KIT.AI_EVAL.ONET_ROLE_SEARCH;
