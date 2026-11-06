-- =====================================================================
-- 07_governance.sql — tags, masking, row access, aggregation policy,
-- classification and ACCESS_HISTORY lineage on a SYNTHETIC table.
-- The table below is invented (no real people, no institutional data).
-- Role names mirror benchmark/README.md's proposed test access policy, but
-- this is a capability demo. Official G1/G2 scoring must use the frozen
-- benchmark fixtures (benchmark/fixtures/*, hashes in benchmark/manifest.json).
-- Requires Enterprise edition (masking, row access, aggregation policies,
-- classification, ACCESS_HISTORY). Evidence rows S07*.
-- =====================================================================

USE ROLE HR_KIT_ADMIN;
USE WAREHOUSE HR_KIT_WH;
USE SCHEMA HR_KIT.GOV_DEMO;
ALTER SESSION SET QUERY_TAG = 'hr_kit:07_governance';

-- ---------------------------------------------------------------------
-- 1. Synthetic table (5 fictional people, 6 appointments, departments T1/T2)
-- ---------------------------------------------------------------------
CREATE OR REPLACE TABLE SYNTH_APPOINTMENTS (
  appointment_id STRING, person_id STRING, person_name STRING, email STRING,
  department_id STRING, title STRING, fte NUMBER(4,2), annual_salary_usd NUMBER(10,0))
  COMMENT = 'SYNTHETIC governance demo data — invented values, not employees';
INSERT INTO SYNTH_APPOINTMENTS VALUES
  ('SA1','SP1','Synthetic Person One',  'sp1@example.invalid','T1','Analyst',        0.60, 61000),
  ('SA2','SP1','Synthetic Person One',  'sp1@example.invalid','T1','Interim Lead',   0.40, 30000),
  ('SA3','SP2','Synthetic Person Two',  'sp2@example.invalid','T1','Engineer',       1.00, 88000),
  ('SA4','SP3','Synthetic Person Three','sp3@example.invalid','T1','Coordinator',    1.00, 52000),
  ('SA5','SP4','Synthetic Person Four', 'sp4@example.invalid','T2','Engineer',       1.00, 91000),
  ('SA6','SP5','Synthetic Person Five', 'sp5@example.invalid','T2','Data Specialist',0.50, 34000);
-- Expected (hand-computed): org = 5 people / 6 appts / 4.5 FTE; T1 = 3 people / 4 appts / 3.0 FTE;
-- T2 = 2 people / 2 appts / 1.5 FTE.

-- ---------------------------------------------------------------------
-- 2. Tags
-- ---------------------------------------------------------------------
CREATE TAG IF NOT EXISTS HR_KIT.GOV_DEMO.SENSITIVITY ALLOWED_VALUES 'public', 'internal', 'confidential'
  COMMENT = 'Kit demo sensitivity tag';
CREATE TAG IF NOT EXISTS HR_KIT.GOV_DEMO.DATA_ORIGIN ALLOWED_VALUES 'public_source', 'synthetic'
  COMMENT = 'Provenance tag';

ALTER TABLE SYNTH_APPOINTMENTS SET TAG HR_KIT.GOV_DEMO.DATA_ORIGIN = 'synthetic';
ALTER TABLE SYNTH_APPOINTMENTS MODIFY COLUMN annual_salary_usd SET TAG HR_KIT.GOV_DEMO.SENSITIVITY = 'confidential';
ALTER TABLE SYNTH_APPOINTMENTS MODIFY COLUMN person_name       SET TAG HR_KIT.GOV_DEMO.SENSITIVITY = 'confidential';
ALTER TABLE SYNTH_APPOINTMENTS MODIFY COLUMN email             SET TAG HR_KIT.GOV_DEMO.SENSITIVITY = 'confidential';
-- Public lake tables get the provenance tag too
ALTER SCHEMA HR_KIT.HR_PUBLIC SET TAG HR_KIT.GOV_DEMO.DATA_ORIGIN = 'public_source';

-- ---------------------------------------------------------------------
-- 3. Masking policies (tag-based: any column tagged 'confidential' is masked)
-- ---------------------------------------------------------------------
CREATE OR REPLACE MASKING POLICY MASK_CONFIDENTIAL_STRING AS (val STRING) RETURNS STRING ->
  CASE WHEN IS_ROLE_IN_SESSION('DS_REVIEWER') THEN val
       WHEN SYSTEM$GET_TAG_ON_CURRENT_COLUMN('HR_KIT.GOV_DEMO.SENSITIVITY') = 'confidential' THEN '***MASKED***'
       ELSE val END;
CREATE OR REPLACE MASKING POLICY MASK_CONFIDENTIAL_NUMBER AS (val NUMBER) RETURNS NUMBER ->
  CASE WHEN IS_ROLE_IN_SESSION('DS_REVIEWER') THEN val
       WHEN SYSTEM$GET_TAG_ON_CURRENT_COLUMN('HR_KIT.GOV_DEMO.SENSITIVITY') = 'confidential' THEN NULL
       ELSE val END;
ALTER TAG HR_KIT.GOV_DEMO.SENSITIVITY SET MASKING POLICY MASK_CONFIDENTIAL_STRING,
                                          MASKING POLICY MASK_CONFIDENTIAL_NUMBER;
-- NB: HR_KIT_ADMIN inherits DS_REVIEWER (00_setup), so the admin sees clear values.
-- Test with USE SECONDARY ROLES NONE so only the primary role counts.

-- ---------------------------------------------------------------------
-- 4. Row access policy (mapping table: which role sees which department)
-- ---------------------------------------------------------------------
CREATE OR REPLACE TABLE ROLE_DEPT_ACCESS (role_name STRING, department_id STRING);
INSERT INTO ROLE_DEPT_ACCESS VALUES
  ('T1_ANALYST','T1'), ('DS_REVIEWER','T1'), ('DS_REVIEWER','T2'),
  ('AGGREGATE_VIEWER','T1'), ('AGGREGATE_VIEWER','T2'),
  ('HR_KIT_ADMIN','T1'), ('HR_KIT_ADMIN','T2');

CREATE OR REPLACE ROW ACCESS POLICY RAP_DEPARTMENT AS (dept STRING) RETURNS BOOLEAN ->
  EXISTS (SELECT 1 FROM HR_KIT.GOV_DEMO.ROLE_DEPT_ACCESS m
          WHERE m.department_id = dept AND m.role_name = CURRENT_ROLE());
-- CURRENT_ROLE() (not IS_ROLE_IN_SESSION) so the inherited-role hierarchy does not widen access.
ALTER TABLE SYNTH_APPOINTMENTS ADD ROW ACCESS POLICY RAP_DEPARTMENT ON (department_id);

-- ---------------------------------------------------------------------
-- 5. Aggregation policy: AGGREGATE_VIEWER gets aggregates only, min group 3
-- ---------------------------------------------------------------------
-- Aggregation policies: Enterprise; behavior: groups under the minimum are
-- folded into a NULL "remainder" group rather than dropped — record what you see.
CREATE OR REPLACE AGGREGATION POLICY AGG_MIN3 AS () RETURNS AGGREGATION_CONSTRAINT ->
  CASE WHEN CURRENT_ROLE() = 'AGGREGATE_VIEWER' THEN AGGREGATION_CONSTRAINT(MIN_GROUP_SIZE => 3)
       ELSE NO_AGGREGATION_CONSTRAINT() END;
ALTER TABLE SYNTH_APPOINTMENTS SET AGGREGATION POLICY AGG_MIN3;
-- NB: MIN_GROUP_SIZE counts ROWS (appointments), not distinct people. The benchmark rule
-- is "fewer than 3 distinct people" — an entity-key aggregation policy (ENTITY KEY) may be
-- needed to match it exactly. Verify in account and record the gap if it cannot be matched.

-- Grants for the test roles
GRANT SELECT ON TABLE SYNTH_APPOINTMENTS TO ROLE T1_ANALYST;
GRANT SELECT ON TABLE SYNTH_APPOINTMENTS TO ROLE DS_REVIEWER;
GRANT SELECT ON TABLE SYNTH_APPOINTMENTS TO ROLE AGGREGATE_VIEWER;

-- ---------------------------------------------------------------------
-- 6. Negative/positive access tests — run each block, record actual vs expected
-- ---------------------------------------------------------------------
USE SECONDARY ROLES NONE;

USE ROLE T1_ANALYST;   USE WAREHOUSE HR_KIT_WH;
SELECT department_id, COUNT(*) appts, COUNT(DISTINCT person_id) people, SUM(fte) fte FROM HR_KIT.GOV_DEMO.SYNTH_APPOINTMENTS GROUP BY 1;
-- EXPECT: only T1 → 4 appts, 3 people, 3.0 FTE
SELECT person_name, annual_salary_usd FROM HR_KIT.GOV_DEMO.SYNTH_APPOINTMENTS LIMIT 3;
-- EXPECT: '***MASKED***' and NULL
SELECT COUNT(*) FROM HR_KIT.GOV_DEMO.SYNTH_APPOINTMENTS WHERE department_id = 'T2';
-- EXPECT: 0 (row policy, not an error)

USE ROLE DS_REVIEWER;  USE WAREHOUSE HR_KIT_WH;
SELECT department_id, COUNT(*) appts, COUNT(DISTINCT person_id) people, SUM(fte) fte FROM HR_KIT.GOV_DEMO.SYNTH_APPOINTMENTS GROUP BY 1 ORDER BY 1;
-- EXPECT: T1 4/3/3.0 and T2 2/2/1.5; names and salaries visible

USE ROLE AGGREGATE_VIEWER; USE WAREHOUSE HR_KIT_WH;
SELECT * FROM HR_KIT.GOV_DEMO.SYNTH_APPOINTMENTS;
-- EXPECT: error — non-aggregate query rejected by aggregation policy
SELECT COUNT(DISTINCT person_id) people, SUM(fte) fte FROM HR_KIT.GOV_DEMO.SYNTH_APPOINTMENTS;
-- EXPECT: 5 people, 4.5 FTE (whole org eligible)
SELECT department_id, COUNT(DISTINCT person_id) people, SUM(fte) fte FROM HR_KIT.GOV_DEMO.SYNTH_APPOINTMENTS GROUP BY 1;
-- EXPECT (benchmark-style rule): T1 shown (3 people); T2 suppressed (2 people).
-- Record exactly what Snowflake returns (rows vs people threshold, remainder group).
SELECT department_id, COUNT(*) FROM HR_KIT.GOV_DEMO.SYNTH_APPOINTMENTS WHERE person_id = 'SP4' GROUP BY 1;
-- Inference probe via filter: EXPECT suppressed/remainder, not a single-person group.

-- AI boundary probe (G2): masked values must be what the AI function receives
USE ROLE T1_ANALYST;
-- T1_ANALYST lacks CORTEX_USER in 00_setup; if you grant it temporarily for this probe, revoke afterwards.
-- SELECT AI_COMPLETE('llama3.3-70b', 'Repeat exactly: ' || person_name || ' earns ' || COALESCE(annual_salary_usd::STRING,'unknown'))
-- FROM HR_KIT.GOV_DEMO.SYNTH_APPOINTMENTS LIMIT 2;
-- EXPECT: the output contains ***MASKED*** / unknown, never the clear values.

USE ROLE HR_KIT_ADMIN;
USE SECONDARY ROLES ALL;

-- ---------------------------------------------------------------------
-- 7. Sensitive-data classification (Enterprise; results can take time)
-- ---------------------------------------------------------------------
-- Manual one-table classification (verify option names in account):
CALL SYSTEM$CLASSIFY('HR_KIT.GOV_DEMO.SYNTH_APPOINTMENTS', {'auto_tag': false});
SELECT SYSTEM$GET_CLASSIFICATION_RESULT('HR_KIT.GOV_DEMO.SYNTH_APPOINTMENTS');   -- verify function availability
-- EXPECT to detect: person_name (NAME), email (EMAIL); possibly salary (quasi/sensitive).
-- Also classify one PUBLIC table and record false positives (e.g., institution names):
CALL SYSTEM$CLASSIFY('HR_KIT.HR_PUBLIC.IPEDS_INSTITUTION', {'auto_tag': false});
-- Automatic classification uses a classification profile (SNOWFLAKE.DATA_PRIVACY.CLASSIFICATION_PROFILE)
-- set on a database/schema; docs note ~1 h delay before it starts. Optional for the trial.

-- ---------------------------------------------------------------------
-- 8. Policy inventory and lineage evidence
-- ---------------------------------------------------------------------
SELECT policy_name, policy_kind, ref_entity_name, ref_column_name, tag_name
FROM TABLE(HR_KIT.INFORMATION_SCHEMA.POLICY_REFERENCES(
  REF_ENTITY_NAME => 'HR_KIT.GOV_DEMO.SYNTH_APPOINTMENTS', REF_ENTITY_DOMAIN => 'table'));

SELECT * FROM TABLE(HR_KIT.INFORMATION_SCHEMA.TAG_REFERENCES_ALL_COLUMNS('HR_KIT.GOV_DEMO.SYNTH_APPOINTMENTS', 'table'));

-- Object dependencies (view → table), latency up to ~3 h
SELECT referencing_object_name, referencing_object_domain, referenced_object_name, referenced_object_domain
FROM SNOWFLAKE.ACCOUNT_USAGE.OBJECT_DEPENDENCIES
WHERE referencing_database = 'HR_KIT' ORDER BY 1;

-- ACCESS_HISTORY: who read which base objects/columns (latency up to ~3 h; Enterprise)
SELECT ah.query_start_time, ah.user_name, q.role_name,
       obj.value:"objectName"::STRING AS base_object,
       col.value:"columnName"::STRING  AS column_name
FROM SNOWFLAKE.ACCOUNT_USAGE.ACCESS_HISTORY ah
JOIN SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q ON q.query_id = ah.query_id,
     LATERAL FLATTEN(ah.base_objects_accessed) obj,
     LATERAL FLATTEN(obj.value:"columns", OUTER => TRUE) col
WHERE ah.query_start_time > DATEADD(DAY, -2, CURRENT_TIMESTAMP())
  AND obj.value:"objectName"::STRING ILIKE 'HR_KIT.GOV_DEMO.SYNTH_APPOINTMENTS'
ORDER BY ah.query_start_time DESC;

-- Write lineage: which source objects fed which target (e.g., HR_PUBLIC → AI_EVAL CTAS in 02)
SELECT ah.query_start_time,
       src.value:"objectName"::STRING AS source_object,
       tgt.value:"objectName"::STRING AS target_object
FROM SNOWFLAKE.ACCOUNT_USAGE.ACCESS_HISTORY ah,
     LATERAL FLATTEN(ah.objects_modified) tgt,
     LATERAL FLATTEN(ah.base_objects_accessed) src
WHERE ah.query_start_time > DATEADD(DAY, -2, CURRENT_TIMESTAMP())
  AND tgt.value:"objectName"::STRING ILIKE 'HR_KIT.%'
ORDER BY ah.query_start_time DESC;
-- Also screenshot Snowsight > Catalog > HR_KIT.AI_EVAL.R_MAPPING_COMPARE > Lineage.

-- Policy-protected access attempts (did the policies fire?)
SELECT ah.query_start_time, ah.user_name, pol.value:"policyName"::STRING AS policy_name
FROM SNOWFLAKE.ACCOUNT_USAGE.ACCESS_HISTORY ah,
     LATERAL FLATTEN(ah.policies_referenced) p,
     LATERAL FLATTEN(p.value:"policies", OUTER => TRUE) pol
WHERE ah.query_start_time > DATEADD(DAY, -2, CURRENT_TIMESTAMP())
ORDER BY 1 DESC;   -- column/JSON paths: verify in account
