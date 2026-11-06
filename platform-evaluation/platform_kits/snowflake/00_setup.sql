-- =====================================================================
-- 00_setup.sql  —  Snowflake trial-run kit: account objects + guardrails
-- Kit version: snowflake-kit v0.1 (2026-11-06). PUBLIC DATA ONLY.
--
-- Run as ACCOUNTADMIN in a Snowsight SQL worksheet (Enterprise-edition
-- trial recommended: masking / row access / classification need Enterprise).
-- Every statement is idempotent (IF NOT EXISTS / OR REPLACE) so the file
-- can be re-run. Record the run in evidence_template.csv (step S00).
--
-- NEVER load institutional HR, payroll, appointment, applicant or any
-- non-public university data into a trial account. Only the public lake
-- tables (O*NET, IPEDS, QCEW, Census QWI, ACS, SUCSS class catalog, AEI)
-- and the clearly synthetic governance table in 07_governance.sql.
-- =====================================================================

USE ROLE ACCOUNTADMIN;

-- ---------------------------------------------------------------------
-- 1. Cost guardrails FIRST (before any warehouse is used)
-- ---------------------------------------------------------------------
-- Resource monitor: caps WAREHOUSE credits only. It does NOT cap serverless
-- AI usage (Cortex AI Functions, Cortex Search serving, Analyst, Agents) —
-- those are tracked separately in ACCOUNT_USAGE views (see README §Cost).
CREATE RESOURCE MONITOR IF NOT EXISTS HR_KIT_MONITOR
  WITH CREDIT_QUOTA = 25                -- adjust to your trial balance; ~25 credits is ample for this kit
       FREQUENCY = MONTHLY
       START_TIMESTAMP = IMMEDIATELY
       TRIGGERS ON 50 PERCENT DO NOTIFY
                ON 80 PERCENT DO NOTIFY
                ON 95 PERCENT DO SUSPEND
                ON 100 PERCENT DO SUSPEND_IMMEDIATE;

-- XSMALL is enough for every step in this kit. AUTO_SUSPEND 60 s.
CREATE WAREHOUSE IF NOT EXISTS HR_KIT_WH
  WAREHOUSE_SIZE = 'XSMALL'
  AUTO_SUSPEND = 60
  AUTO_RESUME = TRUE
  INITIALLY_SUSPENDED = TRUE
  STATEMENT_TIMEOUT_IN_SECONDS = 900      -- kill runaway AI-function scans after 15 min
  COMMENT = 'HR analytics Snowflake trial kit (public data only)';

ALTER WAREHOUSE HR_KIT_WH SET RESOURCE_MONITOR = HR_KIT_MONITOR;

-- Optional: account-wide statement timeout as a second backstop
-- ALTER ACCOUNT SET STATEMENT_TIMEOUT_IN_SECONDS = 1800;

-- ---------------------------------------------------------------------
-- 2. Cortex region availability (verify in account)
-- ---------------------------------------------------------------------
-- Some models are not hosted in every region. If an AI function returns
-- "model unavailable in your region", cross-region inference must be enabled.
-- This sends prompts (PUBLIC data only here) to another region of the same
-- cloud. Record the value you use in evidence (it is a deployment condition).
SHOW PARAMETERS LIKE 'CORTEX_ENABLED_CROSS_REGION' IN ACCOUNT;
-- ALTER ACCOUNT SET CORTEX_ENABLED_CROSS_REGION = 'AWS_US';   -- or 'ANY_REGION'; uncomment only if needed and record it
SHOW PARAMETERS LIKE 'ENABLE_CORTEX_ANALYST' IN ACCOUNT;           -- must not be FALSE for 04/05

-- ---------------------------------------------------------------------
-- 3. Roles (mirrors the benchmark's proposed test roles + a kit admin)
-- ---------------------------------------------------------------------
CREATE ROLE IF NOT EXISTS HR_KIT_ADMIN      COMMENT = 'Owns kit objects; builds AI/ML/search assets';
CREATE ROLE IF NOT EXISTS HR_KIT_ANALYST    COMMENT = 'Reads public lake + uses Analyst/Agent/Search';
-- Governance demo roles (07_governance.sql) — names match benchmark/README.md access policy
CREATE ROLE IF NOT EXISTS T1_ANALYST        COMMENT = 'Synthetic governance demo: T1 detail only';
CREATE ROLE IF NOT EXISTS DS_REVIEWER       COMMENT = 'Synthetic governance demo: T1+T2 detail';
CREATE ROLE IF NOT EXISTS AGGREGATE_VIEWER  COMMENT = 'Synthetic governance demo: aggregates only';

GRANT ROLE HR_KIT_ANALYST   TO ROLE HR_KIT_ADMIN;
GRANT ROLE T1_ANALYST       TO ROLE HR_KIT_ADMIN;
GRANT ROLE DS_REVIEWER      TO ROLE HR_KIT_ADMIN;
GRANT ROLE AGGREGATE_VIEWER TO ROLE HR_KIT_ADMIN;
GRANT ROLE HR_KIT_ADMIN     TO ROLE SYSADMIN;

-- Grant the kit roles to yourself (replace with your trial user name)
SET MY_USER = CURRENT_USER();
GRANT ROLE HR_KIT_ADMIN     TO USER IDENTIFIER($MY_USER);
GRANT ROLE HR_KIT_ANALYST   TO USER IDENTIFIER($MY_USER);
GRANT ROLE T1_ANALYST       TO USER IDENTIFIER($MY_USER);
GRANT ROLE DS_REVIEWER      TO USER IDENTIFIER($MY_USER);
GRANT ROLE AGGREGATE_VIEWER TO USER IDENTIFIER($MY_USER);

-- Cortex AI access. Current docs: users need the account-level USE AI FUNCTIONS
-- privilege (granted to PUBLIC by default since 2026-02) AND one of the
-- SNOWFLAKE.CORTEX_USER / SNOWFLAKE.AI_FUNCTIONS_USER database roles.
GRANT DATABASE ROLE SNOWFLAKE.CORTEX_USER TO ROLE HR_KIT_ADMIN;
GRANT DATABASE ROLE SNOWFLAKE.CORTEX_USER TO ROLE HR_KIT_ANALYST;
-- GRANT USE AI FUNCTIONS ON ACCOUNT TO ROLE HR_KIT_ANALYST;   -- verify in account: only needed if revoked from PUBLIC

-- Cost-visibility for the admin role (ACCOUNT_USAGE views)
GRANT IMPORTED PRIVILEGES ON DATABASE SNOWFLAKE TO ROLE HR_KIT_ADMIN;

-- ML forecasting class (06_ml.sql)
-- (CREATE SNOWFLAKE.ML.FORECAST privilege is granted at schema level below)

-- ---------------------------------------------------------------------
-- 4. Database / schemas
-- ---------------------------------------------------------------------
CREATE DATABASE IF NOT EXISTS HR_KIT COMMENT = 'Public HR analytics trial kit — public data only';
CREATE SCHEMA IF NOT EXISTS HR_KIT.HR_PUBLIC  COMMENT = 'Raw public lake tables (silver parquet, unchanged)';
CREATE SCHEMA IF NOT EXISTS HR_KIT.CURATED    COMMENT = 'Conformed views used by every downstream script';
CREATE SCHEMA IF NOT EXISTS HR_KIT.AI_EVAL    COMMENT = 'AI-function, search, analyst, agent result tables for scoring';
CREATE SCHEMA IF NOT EXISTS HR_KIT.ML         COMMENT = 'Forecast models and outputs';
CREATE SCHEMA IF NOT EXISTS HR_KIT.GOV_DEMO   COMMENT = 'SYNTHETIC governance demo only';
CREATE SCHEMA IF NOT EXISTS HR_KIT.APPS       COMMENT = 'Streamlit apps, agents, stages for app code';

GRANT OWNERSHIP ON DATABASE HR_KIT TO ROLE HR_KIT_ADMIN COPY CURRENT GRANTS;
GRANT OWNERSHIP ON ALL SCHEMAS IN DATABASE HR_KIT TO ROLE HR_KIT_ADMIN COPY CURRENT GRANTS;
GRANT USAGE ON WAREHOUSE HR_KIT_WH TO ROLE HR_KIT_ADMIN;
GRANT USAGE ON WAREHOUSE HR_KIT_WH TO ROLE HR_KIT_ANALYST;
GRANT USAGE ON WAREHOUSE HR_KIT_WH TO ROLE T1_ANALYST;
GRANT USAGE ON WAREHOUSE HR_KIT_WH TO ROLE DS_REVIEWER;
GRANT USAGE ON WAREHOUSE HR_KIT_WH TO ROLE AGGREGATE_VIEWER;

-- Snowflake Intelligence object (05_agents_intelligence.md) needs ACCOUNTADMIN;
-- create it there, not here.

-- ---------------------------------------------------------------------
-- 5. Stage + file format (as kit admin)
-- ---------------------------------------------------------------------
USE ROLE HR_KIT_ADMIN;
USE WAREHOUSE HR_KIT_WH;
USE SCHEMA HR_KIT.HR_PUBLIC;

CREATE FILE FORMAT IF NOT EXISTS HR_KIT.HR_PUBLIC.FF_PARQUET
  TYPE = PARQUET
  BINARY_AS_TEXT = FALSE
  USE_LOGICAL_TYPE = TRUE           -- keep parquet DATE/TIMESTAMP/DECIMAL logical types
  COMMENT = 'Silver lake parquet';

CREATE STAGE IF NOT EXISTS HR_KIT.HR_PUBLIC.LAKE_STAGE
  FILE_FORMAT = HR_KIT.HR_PUBLIC.FF_PARQUET
  DIRECTORY = (ENABLE = TRUE)
  COMMENT = 'Upload data/lake/contract/*.parquet here (public data only)';

CREATE STAGE IF NOT EXISTS HR_KIT.APPS.APP_STAGE
  DIRECTORY = (ENABLE = TRUE)
  COMMENT = 'Streamlit app code + semantic model YAML';

-- Allow analyst to read curated + eval outputs (granted again after objects exist in 01)
GRANT USAGE ON DATABASE HR_KIT TO ROLE HR_KIT_ANALYST;
GRANT USAGE ON SCHEMA HR_KIT.HR_PUBLIC TO ROLE HR_KIT_ANALYST;
GRANT USAGE ON SCHEMA HR_KIT.CURATED   TO ROLE HR_KIT_ANALYST;
GRANT USAGE ON SCHEMA HR_KIT.AI_EVAL   TO ROLE HR_KIT_ANALYST;
GRANT USAGE ON SCHEMA HR_KIT.ML        TO ROLE HR_KIT_ANALYST;
GRANT USAGE ON SCHEMA HR_KIT.APPS      TO ROLE HR_KIT_ANALYST;
GRANT SELECT ON FUTURE TABLES IN SCHEMA HR_KIT.HR_PUBLIC TO ROLE HR_KIT_ANALYST;
GRANT SELECT ON FUTURE VIEWS  IN SCHEMA HR_KIT.CURATED   TO ROLE HR_KIT_ANALYST;
GRANT SELECT ON FUTURE TABLES IN SCHEMA HR_KIT.AI_EVAL   TO ROLE HR_KIT_ANALYST;
GRANT SELECT ON FUTURE TABLES IN SCHEMA HR_KIT.ML        TO ROLE HR_KIT_ANALYST;
GRANT USAGE ON SCHEMA HR_KIT.GOV_DEMO TO ROLE T1_ANALYST;
GRANT USAGE ON SCHEMA HR_KIT.GOV_DEMO TO ROLE DS_REVIEWER;
GRANT USAGE ON SCHEMA HR_KIT.GOV_DEMO TO ROLE AGGREGATE_VIEWER;
GRANT USAGE ON DATABASE HR_KIT TO ROLE T1_ANALYST;
GRANT USAGE ON DATABASE HR_KIT TO ROLE DS_REVIEWER;
GRANT USAGE ON DATABASE HR_KIT TO ROLE AGGREGATE_VIEWER;

-- Query tag so kit activity can be isolated in QUERY_HISTORY / cost views
ALTER SESSION SET QUERY_TAG = 'hr_kit:00_setup';

-- ---------------------------------------------------------------------
-- 6. Evidence: capture environment facts
-- ---------------------------------------------------------------------
SELECT CURRENT_ACCOUNT() AS account_locator, CURRENT_REGION() AS region,
       CURRENT_VERSION() AS snowflake_version, CURRENT_USER() AS run_user,
       CURRENT_ROLE() AS run_role, CURRENT_TIMESTAMP() AS run_ts;
SHOW WAREHOUSES LIKE 'HR_KIT_WH';
SHOW RESOURCE MONITORS LIKE 'HR_KIT_MONITOR';
-- Edition is shown in Snowsight > Admin > Accounts (or ORGANIZATION_USAGE if available). Record it.
