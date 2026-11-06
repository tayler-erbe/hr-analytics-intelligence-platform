-- =====================================================================
-- 01_load_lake.sql — load the PUBLIC silver lake (parquet) + conformed views
-- Target contract: lake/CONTRACT.md v1.0 (2026-11-06); files at
-- data/lake/contract/<table>.parquet. PUBLIC DATA ONLY.
--
-- Rubric evidence: I1 (source integration), I3 (incremental recovery: re-run
-- COPY is idempotent), B3 (traceability: source_id/source_vintage retained),
-- C1 (load credits). Evidence rows S01a..S01e in evidence_template.csv.
-- =====================================================================

-- ---------------------------------------------------------------------
-- STEP A. Upload the parquet files (run from a terminal, NOT a worksheet)
-- ---------------------------------------------------------------------
-- Option 1 — Snowflake CLI (recommended; `snow --version` ≥ 3.x):
--   snow stage copy "data/lake/contract/*.parquet" @HR_KIT.HR_PUBLIC.LAKE_STAGE \
--        --role HR_KIT_ADMIN --warehouse HR_KIT_WH --overwrite
-- Option 2 — SnowSQL:
--   PUT file://data/lake/contract/*.parquet @HR_KIT.HR_PUBLIC.LAKE_STAGE
--       AUTO_COMPRESS=FALSE OVERWRITE=TRUE PARALLEL=4;
-- Option 3 — Snowsight: Data > Databases > HR_KIT > HR_PUBLIC > Stages >
--   LAKE_STAGE > "+ Files" (drag the .parquet files). PUT is not available
--   from a Snowsight worksheet.
-- Before upload: confirm every file came from data/lake/contract (public
-- sources only) and copy its SHA-256 from the lake manifest into evidence.
-- ---------------------------------------------------------------------

USE ROLE HR_KIT_ADMIN;
USE WAREHOUSE HR_KIT_WH;
USE SCHEMA HR_KIT.HR_PUBLIC;
ALTER SESSION SET QUERY_TAG = 'hr_kit:01_load_lake';

ALTER STAGE HR_KIT.HR_PUBLIC.LAKE_STAGE REFRESH;
SELECT relative_path, size, md5, last_modified
FROM DIRECTORY(@HR_KIT.HR_PUBLIC.LAKE_STAGE)
ORDER BY relative_path;                         -- evidence: file inventory (stage MD5, not SHA-256)

-- ---------------------------------------------------------------------
-- STEP B. Create tables from the parquet schema and COPY by column name
-- ---------------------------------------------------------------------
-- Tables are created with INFER_SCHEMA(... IGNORE_CASE => TRUE) so column
-- names become unquoted UPPERCASE identifiers and types come from parquet.
-- Missing files (e.g. PENDING bls_oews / bls_projections) are skipped and
-- logged as SKIPPED_NO_FILE — record them as a limitation, not a failure.

CREATE TABLE IF NOT EXISTS HR_KIT.HR_PUBLIC.LOAD_LOG (
  run_ts        TIMESTAMP_LTZ DEFAULT CURRENT_TIMESTAMP(),
  table_name    STRING,
  file_name     STRING,
  status        STRING,
  row_count     NUMBER,
  message       STRING
);

EXECUTE IMMEDIATE $$
DECLARE
  tbls ARRAY DEFAULT ARRAY_CONSTRUCT(
    'onet_occupation','onet_task_statement','onet_task_rating','onet_element_rating',
    'onet_technology_skill','onet_alternate_title','onet_job_zone',
    'sucss_class','sucss_onet_candidate',
    'ipeds_institution','ipeds_staff_by_occupation','ipeds_instructional_staff',
    'ipeds_new_hires','ipeds_salary_instructional','ipeds_salary_noninstructional',
    'ipeds_employees_by_position','ipeds_enrollment_12mo',
    'qcew_industry','qcew_area','qwi_higher_ed','acs_county_labor','aei_task_usage',
    'aei_occupation_exposure','onet_soc_crosswalk',
    'bls_oews','bls_projections');
  t STRING;
  f STRING;
  file_cnt NUMBER;
  row_cnt NUMBER;
BEGIN
  FOR i IN 0 TO ARRAY_SIZE(tbls) - 1 DO
    t := tbls[i]::STRING;
    f := t || '.parquet';
    SELECT COUNT(*) INTO :file_cnt
      FROM DIRECTORY(@HR_KIT.HR_PUBLIC.LAKE_STAGE) WHERE relative_path = :f;
    IF (file_cnt = 0) THEN
      INSERT INTO HR_KIT.HR_PUBLIC.LOAD_LOG(table_name, file_name, status, row_count, message)
        VALUES (:t, :f, 'SKIPPED_NO_FILE', NULL, 'file not on stage (pending source?)');
    ELSE
      EXECUTE IMMEDIATE
        'CREATE TABLE IF NOT EXISTS HR_KIT.HR_PUBLIC.' || t || ' USING TEMPLATE (' ||
        '  SELECT ARRAY_AGG(OBJECT_CONSTRUCT(*)) WITHIN GROUP (ORDER BY ORDER_ID)' ||
        '  FROM TABLE(INFER_SCHEMA(' ||
        '    LOCATION => ''@HR_KIT.HR_PUBLIC.LAKE_STAGE/' || f || ''',' ||
        '    FILE_FORMAT => ''HR_KIT.HR_PUBLIC.FF_PARQUET'',' ||
        '    IGNORE_CASE => TRUE)))';
      EXECUTE IMMEDIATE
        'COPY INTO HR_KIT.HR_PUBLIC.' || t ||
        ' FROM @HR_KIT.HR_PUBLIC.LAKE_STAGE FILES = (''' || f || ''')' ||
        ' FILE_FORMAT = (FORMAT_NAME = ''HR_KIT.HR_PUBLIC.FF_PARQUET'')' ||
        ' MATCH_BY_COLUMN_NAME = CASE_INSENSITIVE ON_ERROR = ABORT_STATEMENT';
      EXECUTE IMMEDIATE 'SELECT COUNT(*) FROM HR_KIT.HR_PUBLIC.' || t;
      SELECT $1 INTO :row_cnt FROM TABLE(RESULT_SCAN(LAST_QUERY_ID()));
      INSERT INTO HR_KIT.HR_PUBLIC.LOAD_LOG(table_name, file_name, status, row_count, message)
        VALUES (:t, :f, 'LOADED', :row_cnt, 'COPY by column name; re-run loads 0 new rows (load metadata)');
    END IF;
  END FOR;
  RETURN 'done — see HR_KIT.HR_PUBLIC.LOAD_LOG';
END;
$$;

-- Evidence: per-table status and row counts for this run
SELECT table_name, status, row_count, run_ts
FROM HR_KIT.HR_PUBLIC.LOAD_LOG
QUALIFY ROW_NUMBER() OVER (PARTITION BY table_name ORDER BY run_ts DESC) = 1
ORDER BY table_name;

-- COPY history (rows parsed/loaded, errors) for the last hour
SELECT table_name, file_name, status, row_count, row_parsed, first_error_message, last_load_time
FROM TABLE(HR_KIT.INFORMATION_SCHEMA.COPY_HISTORY(
       TABLE_NAME => 'HR_KIT.HR_PUBLIC.ONET_OCCUPATION',
       START_TIME => DATEADD(HOUR, -1, CURRENT_TIMESTAMP())));
-- (repeat with another TABLE_NAME as needed, or use ACCOUNT_USAGE.COPY_HISTORY with latency)

-- ---------------------------------------------------------------------
-- STEP C. Row-count reconciliation against the lake manifest
-- ---------------------------------------------------------------------
-- Paste expected counts from the lake manifest (data/lake/manifest*.json)
-- into this table. Exact equality is required; any mismatch is a failure.
CREATE OR REPLACE TABLE HR_KIT.HR_PUBLIC.EXPECTED_ROW_COUNTS (table_name STRING, expected_rows NUMBER, source_sha256 STRING);
-- INSERT INTO HR_KIT.HR_PUBLIC.EXPECTED_ROW_COUNTS VALUES
--   ('onet_occupation', <n>, '<sha256>'),
--   ('onet_task_statement', <n>, '<sha256>'), ... ;

SELECT COALESCE(l.table_name, e.table_name)  AS table_name,
       e.expected_rows, l.row_count AS loaded_rows,
       IFF(e.expected_rows IS NULL, 'NO_EXPECTATION',
           IFF(e.expected_rows = l.row_count, 'MATCH', 'MISMATCH')) AS check_result,
       e.source_sha256
FROM (SELECT * FROM HR_KIT.HR_PUBLIC.LOAD_LOG
      QUALIFY ROW_NUMBER() OVER (PARTITION BY table_name ORDER BY run_ts DESC) = 1) l
FULL OUTER JOIN HR_KIT.HR_PUBLIC.EXPECTED_ROW_COUNTS e ON e.table_name = l.table_name
ORDER BY check_result DESC, table_name;

-- Key/grain sanity checks (duplicates on declared grain must be 0)
SELECT 'onet_occupation'     AS t, COUNT(*) - COUNT(DISTINCT onetsoc_code)            AS dup_rows FROM HR_KIT.HR_PUBLIC.ONET_OCCUPATION
UNION ALL SELECT 'onet_task_statement', COUNT(*) - COUNT(DISTINCT onetsoc_code, task_id) FROM HR_KIT.HR_PUBLIC.ONET_TASK_STATEMENT
UNION ALL SELECT 'sucss_class',          COUNT(*) - COUNT(DISTINCT source_record_id)      FROM HR_KIT.HR_PUBLIC.SUCSS_CLASS
UNION ALL SELECT 'ipeds_institution',    COUNT(*) - COUNT(DISTINCT unitid)                FROM HR_KIT.HR_PUBLIC.IPEDS_INSTITUTION;

-- Leading-zero preservation check: codes must be strings (e.g. class_code '0010', area_fips '17019')
SELECT table_name, column_name, data_type
FROM HR_KIT.INFORMATION_SCHEMA.COLUMNS
WHERE table_schema = 'HR_PUBLIC'
  AND column_name IN ('ONETSOC_CODE','CLASS_CODE','AREA_FIPS','UNITID','INDUSTRY_CODE','OWN_CODE','COUNTY_FIPS','STATE_FIPS','INDUSTRY')
ORDER BY table_name, column_name;    -- expected TEXT for codes (UNITID may be NUMBER — record whichever the lake chose)

-- Incremental-recovery test (I3): re-run STEP B. Expected: COPY reports
-- "Copy executed with 0 files processed" for unchanged files and row counts
-- are unchanged. Record both runs. Do NOT use FORCE=TRUE (it would duplicate).

-- ---------------------------------------------------------------------
-- STEP D. Conformed views (the ONLY place lake column names are assumed)
-- ---------------------------------------------------------------------
-- Column names below match lake/CONTRACT.md v1.0 and data/lake/contract (reconciled 2026-11-06).
-- Run DESCRIBE TABLE on each source and edit only this
-- block if names differ; every later script reads CURATED.* only.
USE SCHEMA HR_KIT.CURATED;

CREATE OR REPLACE VIEW V_ONET_OCCUPATION COMMENT = 'O*NET 31.0 occupations' AS
SELECT onetsoc_code, title AS occupation_title, description AS occupation_description,
       source_id, source_vintage
FROM HR_KIT.HR_PUBLIC.ONET_OCCUPATION;

CREATE OR REPLACE VIEW V_ONET_TASK COMMENT = 'O*NET task statements' AS
SELECT onetsoc_code, task_id, task AS task_text, task_type, source_id, source_vintage
FROM HR_KIT.HR_PUBLIC.ONET_TASK_STATEMENT;

CREATE OR REPLACE VIEW V_ONET_TECH_SKILL COMMENT = 'O*NET 31.0 technology (software) skills' AS
SELECT onetsoc_code, example AS technology_example, commodity_code, commodity_title,
       hot_technology, in_demand, source_id, source_vintage
FROM HR_KIT.HR_PUBLIC.ONET_TECHNOLOGY_SKILL;

CREATE OR REPLACE VIEW V_ONET_ROLE_DOC COMMENT = 'One searchable document per occupation (title, alt titles, description, job zone)' AS
WITH alt AS (
  SELECT onetsoc_code, LISTAGG(alternate_title, '; ') WITHIN GROUP (ORDER BY alternate_title) AS alternate_titles
  FROM HR_KIT.HR_PUBLIC.ONET_ALTERNATE_TITLE GROUP BY onetsoc_code)
SELECT o.onetsoc_code, o.occupation_title, o.occupation_description, z.job_zone,
       alt.alternate_titles, o.source_vintage
FROM V_ONET_OCCUPATION o
LEFT JOIN HR_KIT.HR_PUBLIC.ONET_JOB_ZONE z ON z.onetsoc_code = o.onetsoc_code
LEFT JOIN alt ON alt.onetsoc_code = o.onetsoc_code;

CREATE OR REPLACE VIEW V_SUCSS_CLASS COMMENT = 'Illinois SUCSS class catalog records (not employees/vacancies)' AS
SELECT source_record_id, class_code, class_title, occupational_line, source_id, source_vintage
FROM HR_KIT.HR_PUBLIC.SUCSS_CLASS;

CREATE OR REPLACE VIEW V_SUCSS_ONET_CANDIDATE COMMENT = 'Unreviewed lexical title candidates (title_lexical_baseline_v1); score is not a probability' AS
SELECT source_record_id, onetsoc_code, candidate_rank, title_similarity AS lexical_score, review_status
FROM HR_KIT.HR_PUBLIC.SUCSS_ONET_CANDIDATE;

CREATE OR REPLACE VIEW V_IPEDS_INSTITUTION COMMENT = 'IPEDS HD2024 institution directory' AS
SELECT unitid, institution_name, state_abbr, sector, carnegie_class, county_fips, cbsa_code, system_name
FROM HR_KIT.HR_PUBLIC.IPEDS_INSTITUTION;

-- Contract rows exclude the IPEDS all-occupations total, so SUM over categories = institution total.
CREATE OR REPLACE VIEW V_IPEDS_SALARY_NONINSTR COMMENT = 'IPEDS SAL2023_NIS: FT non-instructional staff and salary outlays by occupation group' AS
SELECT unitid, survey_year, occupation_category, staff_count, salary_outlays,
       IFF(staff_count > 0, salary_outlays / staff_count, NULL) AS avg_salary
FROM HR_KIT.HR_PUBLIC.IPEDS_SALARY_NONINSTRUCTIONAL;

-- Contract rows exclude the all-ranks total; contract_length is 9/10/11/12-month.
CREATE OR REPLACE VIEW V_IPEDS_SALARY_INSTR COMMENT = 'IPEDS SAL2023_IS: FT instructional staff by rank and contract length' AS
SELECT unitid, survey_year, academic_rank, contract_length, staff_count, salary_outlays,
       IFF(staff_count > 0, salary_outlays / staff_count, NULL) AS avg_salary
FROM HR_KIT.HR_PUBLIC.IPEDS_SALARY_INSTRUCTIONAL;

-- Detail categories only (is_category_total = FALSE) and published totals row (sex/race = 'Total'):
-- the detail rows partition the institution grand total exactly, so SUM never double counts.
CREATE OR REPLACE VIEW V_IPEDS_STAFF COMMENT = 'IPEDS S2023_OC headcount by detail occupation category and FT/PT (no subtotals)' AS
SELECT unitid, survey_year, occupation_category, ftpt_status, headcount
FROM HR_KIT.HR_PUBLIC.IPEDS_STAFF_BY_OCCUPATION
WHERE sex = 'Total' AND race_ethnicity = 'Total' AND is_category_total = FALSE;

CREATE OR REPLACE VIEW V_QCEW COMMENT = 'BLS QCEW quarterly: NAICS 611310 all areas (qcew_industry) + Champaign/Cook/Sangamon all industries (qcew_area)' AS
SELECT area_fips, area_title, own_code, industry_code, agglvl_code, size_code, year, qtr,
       qtrly_estabs, month3_emplvl, total_qtrly_wages, avg_wkly_wage, disclosure_code,
       quarter_start, 'qcew_industry' AS source_table
FROM HR_KIT.HR_PUBLIC.QCEW_INDUSTRY
UNION ALL
SELECT area_fips, area_title, own_code, industry_code, agglvl_code, size_code, year, qtr,
       qtrly_estabs, month3_emplvl, total_qtrly_wages, avg_wkly_wage, disclosure_code,
       quarter_start, 'qcew_area'
FROM HR_KIT.HR_PUBLIC.QCEW_AREA
WHERE NOT (industry_code = '611310');   -- these county rows already appear in QCEW_INDUSTRY

CREATE OR REPLACE VIEW V_QWI_HIGHER_ED COMMENT = 'Census QWI Illinois statewide NAICS 6113, all sexes / all ages only' AS
SELECT state_fips, county_fips, geography, industry, year, quarter, quarter_start,
       emp, hira, sep, turnovrs, earns
FROM HR_KIT.HR_PUBLIC.QWI_HIGHER_ED
WHERE sex = '0' AND agegrp = 'A00';

GRANT SELECT ON ALL VIEWS IN SCHEMA HR_KIT.CURATED TO ROLE HR_KIT_ANALYST;
GRANT SELECT ON ALL TABLES IN SCHEMA HR_KIT.HR_PUBLIC TO ROLE HR_KIT_ANALYST;

-- Smoke test every view (a failure here = edit the ASSUMED column names above)
SELECT 'V_ONET_OCCUPATION' v, COUNT(*) n FROM V_ONET_OCCUPATION
UNION ALL SELECT 'V_ONET_TASK', COUNT(*) FROM V_ONET_TASK
UNION ALL SELECT 'V_ONET_ROLE_DOC', COUNT(*) FROM V_ONET_ROLE_DOC
UNION ALL SELECT 'V_SUCSS_CLASS', COUNT(*) FROM V_SUCSS_CLASS
UNION ALL SELECT 'V_SUCSS_ONET_CANDIDATE', COUNT(*) FROM V_SUCSS_ONET_CANDIDATE
UNION ALL SELECT 'V_IPEDS_INSTITUTION', COUNT(*) FROM V_IPEDS_INSTITUTION
UNION ALL SELECT 'V_IPEDS_SALARY_NONINSTR', COUNT(*) FROM V_IPEDS_SALARY_NONINSTR
UNION ALL SELECT 'V_IPEDS_STAFF', COUNT(*) FROM V_IPEDS_STAFF
UNION ALL SELECT 'V_QCEW', COUNT(*) FROM V_QCEW
UNION ALL SELECT 'V_QWI_HIGHER_ED', COUNT(*) FROM V_QWI_HIGHER_ED;
