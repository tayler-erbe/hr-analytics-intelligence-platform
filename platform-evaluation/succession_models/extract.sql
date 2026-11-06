-- =============================================================================================
-- Minimal EDW extract for the succession-planning models (see data_contract.md).
--
-- Runs INSIDE the warehouse on an approved machine. Each statement is introduced by a line
--   -- @extract <OUTPUT_NAME>
-- and its result set is saved as <OUTPUT_NAME>.parquet in the extract directory, keeping the
-- physical column names so config.SOURCE_MAP binds them unchanged.
--
-- Tokens filled by extract.py:
--   {{SCHEMA}}          EDW owner schema (synthetic: "edw", a DuckDB schema of views over Parquet)
--   {{HISTORY_START}}   ANSI DATE literal; rows that ended before it are not extracted
--   {{EXTRACT_DATE}}    ANSI DATE literal; the business date of the extract
--
-- Portability: ANSI subset only (no LIMIT/QUALIFY/ILIKE/::). Column names are ASSUMPTIONS shared
-- with erp_readiness/rules/source_map.yaml; ROW_REC_START_DT / ROW_REC_END_DT are the ASSUMED
-- transaction-time (row-version) columns. If the EDW has no row versions, drop those two columns
-- here and set SOURCE_MAP["bitemporal"] = False (see data_contract.md section 4).
--
-- Data minimisation: no names, national-ID hash, addresses, ZIP codes, leave, or payroll detail
-- are extracted. Protected attributes go to a separate restricted output (X_PROTECTED_ATTR)
-- that only the fairness audit reads.
-- =============================================================================================

-- @extract T_PERS_HIST
SELECT p.EDW_PERS_ID, p.PERS_EFF_DT, p.PERS_EXP_DT, p.BIRTH_DT,
       p.ROW_REC_START_DT, p.ROW_REC_END_DT
FROM {{SCHEMA}}.T_PERS_HIST p
WHERE EXISTS (SELECT 1 FROM {{SCHEMA}}.T_JOB_DETL_HIST j
              WHERE j.EDW_PERS_ID = p.EDW_PERS_ID AND j.JOB_CONTRACT_TYPE_CD = 'P'
                AND COALESCE(j.JOB_DETL_EXP_DT, DATE '9999-12-31') >= {{HISTORY_START}});

-- @extract X_PROTECTED_ATTR
-- RESTRICTED. Current-version demographics for the governed fairness audit only.
SELECT p.EDW_PERS_ID, p.SEX_CD, p.RACE_ETH_CD
FROM {{SCHEMA}}.T_PERS_HIST p
WHERE COALESCE(p.ROW_REC_END_DT, DATE '9999-12-31') = DATE '9999-12-31'
  AND COALESCE(p.PERS_EXP_DT, DATE '9999-12-31') = DATE '9999-12-31';

-- @extract T_EMPEE_HIST
SELECT e.EDW_PERS_ID, e.EMPEE_EFF_DT, e.EMPEE_EXP_DT, e.EMPEE_STATUS_CD, e.FIRST_HIRE_DT, e.CUR_HIRE_DT,
       e.ROW_REC_START_DT, e.ROW_REC_END_DT
FROM {{SCHEMA}}.T_EMPEE_HIST e
WHERE COALESCE(e.EMPEE_EXP_DT, DATE '9999-12-31') >= {{HISTORY_START}}
  AND e.EMPEE_EFF_DT <= {{EXTRACT_DATE}};

-- @extract T_EMPEE_HIST_5
SELECT t.EDW_PERS_ID, t.TERM_DT, t.TERM_REASON_CD, t.SURS_RETIR_IND,
       t.ROW_REC_START_DT, t.ROW_REC_END_DT
FROM {{SCHEMA}}.T_EMPEE_HIST_5 t
WHERE t.TERM_DT >= {{HISTORY_START}} AND t.TERM_DT <= {{EXTRACT_DATE}};

-- @extract T_JOB_DETL_HIST
-- Primary (P) appointments only: succession is about primary positions. Secondary (S) and
-- overload (O) jobs are out of scope for the vacancy and mobility models.
SELECT j.EDW_PERS_ID, j.POSN_NBR, j.JOB_SUFFIX, j.JOB_DETL_EFF_DT, j.JOB_DETL_EXP_DT,
       j.JOB_CONTRACT_TYPE_CD, j.JOB_STATUS_CD, j.JOB_FTE, j.JOB_ANNUAL_SAL_AMT, j.JOB_CLS_CD, j.JOB_ORG_CD,
       j.ROW_REC_START_DT, j.ROW_REC_END_DT
FROM {{SCHEMA}}.T_JOB_DETL_HIST j
WHERE j.JOB_CONTRACT_TYPE_CD = 'P'
  AND COALESCE(j.JOB_DETL_EXP_DT, DATE '9999-12-31') >= {{HISTORY_START}}
  AND j.JOB_DETL_EFF_DT <= {{EXTRACT_DATE}};

-- @extract T_POSN_HIST
SELECT s.POSN_NBR, s.POSN_EFF_DT, s.POSN_EXP_DT, s.POSN_STATUS_CD, s.POSN_CLS_CD, s.POSN_ORG_CD,
       s.ROW_REC_START_DT, s.ROW_REC_END_DT
FROM {{SCHEMA}}.T_POSN_HIST s
WHERE COALESCE(s.POSN_EXP_DT, DATE '9999-12-31') >= {{HISTORY_START}};

-- @extract REF_JOB_CLASS
SELECT c.CLS_CD, c.CLS_TITLE, c.MIN_ANNUAL_AMT, c.MAX_ANNUAL_AMT
FROM {{SCHEMA}}.REF_JOB_CLASS c;

-- @extract REF_ORG
SELECT o.ORG_CD, o.PARENT_ORG_CD, o.ORG_TITLE
FROM {{SCHEMA}}.REF_ORG o;

-- @extract REF_ROLE_FAMILY
-- HR-owned job architecture and approved critical-role list (not an EDW table on real data:
-- load the steward-approved file into the schema, or supply it directly as Parquet).
SELECT r.CLS_CD, r.ROLE_FAMILY, r.ROLE_LEVEL, r.CRITICAL_IND
FROM {{SCHEMA}}.REF_ROLE_FAMILY r;
