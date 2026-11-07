-- =============================================================================================
-- EDW extract for the succession-planning models: v3 / Data Cookbook layout.
--
-- Same contract as extract.sql (one `-- @extract NAME` block per output, physical column names
-- kept so config.SOURCE_MAP_V3_COOKBOOK binds them), but written against the six Cookbook-shaped
-- tables (integration/edw_cookbook_reference) and the reference tables of sample_datasets/v3_cookbook.
-- This is the binding Codex uses on the real EDW: change the right-hand sides of SOURCE_MAP_V3_COOKBOOK
-- and the column lists here, nothing in the model code.
--
-- Tokens filled by extract.py:
--   {{SCHEMA}} {{HISTORY_START}} {{EXTRACT_DATE}}     as in extract.sql
--   {{JOB_REC_START}}     JOB_DETL_HIST_EFF_DT (default) | JOB_DETL_HIST_POST_DT   (SUCC_V3_JOB_CHANGE_DATE)
--   {{EMPEE_REC_START}}   EMPEE_EFF_DT (default) | EMPEE_POST_DT                   (SUCC_V3_INPLACE_KNOWN_FROM)
--   {{PERS_REC_START}}    PERS_HIST_EFF_DT (default) | PERS_HIST_POST_DT
--   {{POSN_REC_START}}    POSN_HIST_EFF_DT (default) | POSN_HIST_POST_DT
--
-- Derived columns (the only non-Cookbook names in the output):
--   ROW_REC_START_DT / ROW_REC_END_DT   transaction-time interval, half-open, 9999-12-31 = still current.
--       T_JOB_DETL_HIST: a version is known from JOB_DETL_HIST_EFF_DT until the next JOB_DETL_HIST_EFF_DT
--       of the same lineage (EDW_PERS_ID, POSN_NBR, JOB_SUFFIX, JOB_DETL_EFF_DT) -- a window function,
--       ANSI. A CUR_INFO_IND = 'D' version is known until its JOB_DETL_HIST_POST_DT (the deletion date).
--       Update-in-place tables: known from {{*_REC_START}} and never superseded; their 'D' rows are dropped.
--   SUCSS_CLS_CD        class key: PAPE_CIV_SVC_ID of the P-Class's positions when it is the 4-digit SUCSS
--                       code (VALUE FORMAT TO CONFIRM), else REF_PCLS_SUCSS_XWALK (synthetic fallback
--                       bridge), else the P-Class itself (local academic classes).
--   POSN_ORG_CD         T_POSN_HIST has no org: the org of the position's latest non-deleted job row.
--   JOB_CONTRACT_TYPE_CD  job type P/O/S from X_JOB_CONTRACT_TYPE (synthetic side table). On the real
--                       EDW replace the join with the primary-job rule (Banner NBRBJOB) and default to 'P'.
--   EMPEE_RET_IND (T_EMPEE_HIST_5 only)  TR/TF rule, because the secured table has no retirement flag.
--
-- Portability: ANSI subset (window functions, COALESCE, CASE, EXISTS). No regex: the 4-digit test on
-- PAPE_CIV_SVC_ID is LENGTH() = 4, so confirm the value format before trusting the bridge on real data.
-- Data minimisation as in extract.sql: no names, UIN/SSN, addresses, ZIP, leave, supervisor or payroll
-- columns. Protected attributes go to the separate restricted output X_PROTECTED_ATTR.
-- =============================================================================================

-- @extract T_PERS_HIST
SELECT p.EDW_PERS_ID, p.PERS_HIST_EFF_DT, p.PERS_EXP_DT, p.BIRTH_DT, p.PERS_CUR_INFO_IND, p.PERS_HIST_POST_DT,
       p.{{PERS_REC_START}} AS ROW_REC_START_DT, DATE '9999-12-31' AS ROW_REC_END_DT
FROM {{SCHEMA}}.T_PERS_HIST p
WHERE COALESCE(p.PERS_CUR_INFO_IND, 'Y') <> 'D'
  AND EXISTS (SELECT 1 FROM {{SCHEMA}}.T_JOB_DETL_HIST j
              WHERE j.EDW_PERS_ID = p.EDW_PERS_ID
                AND COALESCE(j.JOB_DETL_EXP_DT, DATE '9999-12-31') >= {{HISTORY_START}});

-- @extract X_PROTECTED_ATTR
-- RESTRICTED. Current-version demographics for the governed fairness audit only. RACE_ETH_RPT_CD is the
-- University's derived reporting code (U, 9, H, M, 1-5).
SELECT p.EDW_PERS_ID, p.SEX_CD, p.RACE_ETH_RPT_CD
FROM {{SCHEMA}}.T_PERS_HIST p
WHERE p.PERS_CUR_INFO_IND = 'Y'
  AND COALESCE(p.PERS_EXP_DT, DATE '9999-12-31') = DATE '9999-12-31';

-- @extract T_EMPEE_HIST
-- Employee rows (service dates) AND termination rows (EMPEE_TERMN_DT not null) in one output. The term
-- binding reads the same file with rec_start = EMPEE_POST_DT (SOURCE_MAP_V3_COOKBOOK["tables"]["term"]).
SELECT e.EDW_PERS_ID, e.EMPEE_EFF_DT, e.EMPEE_EXP_DT, e.EMPEE_STATUS_CD, e.FIRST_HIRE_DT, e.CUR_HIRE_DT,
       e.TERMN_REASON_CD, e.EMPEE_TERMN_DT, e.EMPEE_RET_IND, e.EMPEE_CUR_INFO_IND, e.EMPEE_POST_DT,
       e.{{EMPEE_REC_START}} AS ROW_REC_START_DT, DATE '9999-12-31' AS ROW_REC_END_DT
FROM {{SCHEMA}}.T_EMPEE_HIST e
WHERE COALESCE(e.EMPEE_CUR_INFO_IND, 'Y') <> 'D'
  AND COALESCE(e.EMPEE_EXP_DT, DATE '9999-12-31') >= {{HISTORY_START}}
  AND e.EMPEE_EFF_DT <= {{EXTRACT_DATE}};

-- @extract T_EMPEE_HIST_5
-- Secured alternative separation source (SUCC_V3_TERM_SOURCE=T_EMPEE_HIST_5). Skip this block if the
-- role cannot read the table; it is optional unless that switch is set.
SELECT t.EDW_PERS_ID, t.EMPEE_EFF_DT, t.EMPEE_EXP_DT, t.TERMN_REASON_CD, t.EMPEE_TERMN_DT,
       CASE WHEN t.TERMN_REASON_CD IN ('TR', 'TF') THEN 'Y' ELSE 'N' END AS EMPEE_RET_IND,
       t.EMPEE_CUR_INFO_IND, t.EMPEE_5_POST_DT,
       t.EMPEE_5_POST_DT AS ROW_REC_START_DT, DATE '9999-12-31' AS ROW_REC_END_DT
FROM {{SCHEMA}}.T_EMPEE_HIST_5 t
WHERE COALESCE(t.EMPEE_CUR_INFO_IND, 'Y') <> 'D'
  AND t.EMPEE_TERMN_DT IS NOT NULL
  AND t.EMPEE_TERMN_DT >= {{HISTORY_START}} AND t.EMPEE_TERMN_DT <= {{EXTRACT_DATE}};

-- @extract T_JOB_DETL_HIST
-- All history versions of primary (P) jobs, with the as-known interval derived from the lineage.
-- The window runs over the whole table BEFORE any filter, so a lineage's versions are never split.
SELECT v.EDW_PERS_ID, v.POSN_NBR, v.JOB_SUFFIX, v.JOB_DETL_EFF_DT, v.JOB_DETL_HIST_EFF_DT, v.JOB_DETL_HIST_POST_DT,
       v.JOB_DETL_EXP_DT, v.JOB_DETL_CUR_INFO_IND, v.JOB_DETL_STATUS_DESC,
       v.JOB_DETL_FTE, v.JOB_DETL_APPT_PCT, v.JOB_DETL_ANNL_SAL, v.JOB_DETL_POSN_CLS_CD,
       COALESCE(pc.SUCSS_CLS_CD, xw.POSN_CLS_CD, v.JOB_DETL_POSN_CLS_CD) AS SUCSS_CLS_CD,
       v.ORG_CD, COALESCE(x.JOB_CONTRACT_TYPE_CD, 'P') AS JOB_CONTRACT_TYPE_CD,
       v.ROW_REC_START_DT, v.ROW_REC_END_DT
FROM (
    SELECT j.*,
           j.{{JOB_REC_START}} AS ROW_REC_START_DT,
           CASE WHEN j.JOB_DETL_CUR_INFO_IND = 'D' THEN j.JOB_DETL_HIST_POST_DT
                ELSE COALESCE(LEAD(j.{{JOB_REC_START}}) OVER (PARTITION BY j.EDW_PERS_ID, j.POSN_NBR, j.JOB_SUFFIX, j.JOB_DETL_EFF_DT
                                                             ORDER BY j.{{JOB_REC_START}}), DATE '9999-12-31') END AS ROW_REC_END_DT
    FROM {{SCHEMA}}.T_JOB_DETL_HIST j
) v
LEFT JOIN (SELECT POSN_CLS_CD, MIN(PAPE_CIV_SVC_ID) AS SUCSS_CLS_CD
           FROM {{SCHEMA}}.T_POSN_HIST WHERE LENGTH(PAPE_CIV_SVC_ID) = 4 GROUP BY POSN_CLS_CD) pc
       ON pc.POSN_CLS_CD = v.JOB_DETL_POSN_CLS_CD
LEFT JOIN (SELECT JOB_DETL_POSN_CLS_CD, MIN(POSN_CLS_CD) AS POSN_CLS_CD
           FROM {{SCHEMA}}.REF_PCLS_SUCSS_XWALK GROUP BY JOB_DETL_POSN_CLS_CD) xw
       ON xw.JOB_DETL_POSN_CLS_CD = v.JOB_DETL_POSN_CLS_CD
LEFT JOIN {{SCHEMA}}.X_JOB_CONTRACT_TYPE x
       ON x.EDW_PERS_ID = v.EDW_PERS_ID AND x.POSN_NBR = v.POSN_NBR AND x.JOB_SUFFIX = v.JOB_SUFFIX
WHERE COALESCE(x.JOB_CONTRACT_TYPE_CD, 'P') = 'P'
  AND COALESCE(v.JOB_DETL_EXP_DT, DATE '9999-12-31') >= {{HISTORY_START}}
  AND v.JOB_DETL_EFF_DT <= {{EXTRACT_DATE}}
  AND v.ROW_REC_START_DT < v.ROW_REC_END_DT;      -- a row keyed and deleted the same day was never visible

-- @extract T_POSN_HIST
-- Position versions with vacancy, status, pay range and ladder; class key and org derived as above.
SELECT s.POSN_NBR, s.POSN_HIST_EFF_DT, s.POSN_HIST_EXP_DT, s.POSN_STATUS_CD, s.POSN_CLS_CD, s.PAPE_CIV_SVC_ID,
       CASE WHEN LENGTH(s.PAPE_CIV_SVC_ID) = 4 THEN s.PAPE_CIV_SVC_ID ELSE COALESCE(xw.POSN_CLS_CD, s.POSN_CLS_CD) END AS SUCSS_CLS_CD,
       s.POSN_JOB_PRGS_CD, s.OPEN_POSN_IND, s.POSN_MIN_SAL, s.POSN_MIDPT_SAL, s.POSN_MAX_SAL,
       jo.ORG_CD AS POSN_ORG_CD, s.POSN_HIST_CUR_INFO_IND, s.POSN_HIST_POST_DT,
       s.{{POSN_REC_START}} AS ROW_REC_START_DT, DATE '9999-12-31' AS ROW_REC_END_DT
FROM {{SCHEMA}}.T_POSN_HIST s
LEFT JOIN (SELECT JOB_DETL_POSN_CLS_CD, MIN(POSN_CLS_CD) AS POSN_CLS_CD
           FROM {{SCHEMA}}.REF_PCLS_SUCSS_XWALK GROUP BY JOB_DETL_POSN_CLS_CD) xw
       ON xw.JOB_DETL_POSN_CLS_CD = s.POSN_CLS_CD
LEFT JOIN (SELECT POSN_NBR, ORG_CD FROM (
               SELECT j.POSN_NBR, j.ORG_CD,
                      ROW_NUMBER() OVER (PARTITION BY j.POSN_NBR ORDER BY j.JOB_DETL_EFF_DT DESC, j.JOB_DETL_HIST_EFF_DT DESC, j.EDW_PERS_ID) AS rn
               FROM {{SCHEMA}}.T_JOB_DETL_HIST j WHERE COALESCE(j.JOB_DETL_CUR_INFO_IND, 'Y') <> 'D') r
           WHERE r.rn = 1) jo
       ON jo.POSN_NBR = s.POSN_NBR
WHERE COALESCE(s.POSN_HIST_CUR_INFO_IND, 'Y') <> 'D'
  AND COALESCE(s.POSN_HIST_EXP_DT, DATE '9999-12-31') >= {{HISTORY_START}};

-- @extract T_POSN_CLS_HIST
-- Class pay range: the fallback when a position version carries no range of its own.
SELECT c.POSN_CLS_CD, c.POSN_CLS_DESC, c.MIN_ANNUAL_AMT, c.MAX_ANNUAL_AMT
FROM {{SCHEMA}}.T_POSN_CLS_HIST c;

-- @extract REF_ORG
SELECT o.ORG_CD, o.PARENT_ORG_CD, o.ORG_TITLE, o.ORG_HIER_LEVEL_NBR
FROM {{SCHEMA}}.REF_ORG o;

-- @extract REF_ROLE_FAMILY
-- HR-owned job architecture (family, level, approved CRITICAL_IND) keyed by the class key above, plus a
-- fallback for classes it does not list: the position job-progression ladder (POSN_JOB_PRGS_CD), with the
-- level = rank of the class's position midpoint within the ladder and CRITICAL_IND = 'N'. The fallback
-- never adds a critical role: only the steward-approved list can.
SELECT r.CLS_CD, r.ROLE_FAMILY, r.ROLE_LEVEL, r.CRITICAL_IND, 'REF_ROLE_FAMILY' AS ROLE_SOURCE
FROM {{SCHEMA}}.REF_ROLE_FAMILY r
UNION ALL
SELECT l.CLS_CD, l.ROLE_FAMILY, l.ROLE_LEVEL, 'N' AS CRITICAL_IND, 'POSN_JOB_PRGS_CD' AS ROLE_SOURCE
FROM (SELECT k.CLS_CD, k.POSN_JOB_PRGS_CD AS ROLE_FAMILY,
             DENSE_RANK() OVER (PARTITION BY k.POSN_JOB_PRGS_CD ORDER BY k.MIDPT) AS ROLE_LEVEL
      FROM (SELECT CASE WHEN LENGTH(s.PAPE_CIV_SVC_ID) = 4 THEN s.PAPE_CIV_SVC_ID ELSE COALESCE(xw.POSN_CLS_CD, s.POSN_CLS_CD) END AS CLS_CD,
                   s.POSN_JOB_PRGS_CD, MAX(s.POSN_MIDPT_SAL) AS MIDPT
            FROM {{SCHEMA}}.T_POSN_HIST s
            LEFT JOIN (SELECT JOB_DETL_POSN_CLS_CD, MIN(POSN_CLS_CD) AS POSN_CLS_CD
                       FROM {{SCHEMA}}.REF_PCLS_SUCSS_XWALK GROUP BY JOB_DETL_POSN_CLS_CD) xw
                   ON xw.JOB_DETL_POSN_CLS_CD = s.POSN_CLS_CD
            WHERE s.POSN_JOB_PRGS_CD IS NOT NULL AND COALESCE(s.POSN_HIST_CUR_INFO_IND, 'Y') <> 'D'
            GROUP BY CASE WHEN LENGTH(s.PAPE_CIV_SVC_ID) = 4 THEN s.PAPE_CIV_SVC_ID ELSE COALESCE(xw.POSN_CLS_CD, s.POSN_CLS_CD) END,
                     s.POSN_JOB_PRGS_CD) k) l
WHERE NOT EXISTS (SELECT 1 FROM {{SCHEMA}}.REF_ROLE_FAMILY r2 WHERE r2.CLS_CD = l.CLS_CD);

-- @extract X_LADDER
-- Ladder cross-check (reporting only): class key -> POSN_JOB_PRGS_CD and the midpoint rank, so the run
-- summary can state how far the HR job architecture and the position ladders agree.
SELECT k.CLS_CD, k.POSN_JOB_PRGS_CD, DENSE_RANK() OVER (PARTITION BY k.POSN_JOB_PRGS_CD ORDER BY k.MIDPT) AS LADDER_LEVEL
FROM (SELECT CASE WHEN LENGTH(s.PAPE_CIV_SVC_ID) = 4 THEN s.PAPE_CIV_SVC_ID ELSE COALESCE(xw.POSN_CLS_CD, s.POSN_CLS_CD) END AS CLS_CD,
             s.POSN_JOB_PRGS_CD, MAX(s.POSN_MIDPT_SAL) AS MIDPT
      FROM {{SCHEMA}}.T_POSN_HIST s
      LEFT JOIN (SELECT JOB_DETL_POSN_CLS_CD, MIN(POSN_CLS_CD) AS POSN_CLS_CD
                 FROM {{SCHEMA}}.REF_PCLS_SUCSS_XWALK GROUP BY JOB_DETL_POSN_CLS_CD) xw
             ON xw.JOB_DETL_POSN_CLS_CD = s.POSN_CLS_CD
      WHERE s.POSN_JOB_PRGS_CD IS NOT NULL AND COALESCE(s.POSN_HIST_CUR_INFO_IND, 'Y') <> 'D'
      GROUP BY CASE WHEN LENGTH(s.PAPE_CIV_SVC_ID) = 4 THEN s.PAPE_CIV_SVC_ID ELSE COALESCE(xw.POSN_CLS_CD, s.POSN_CLS_CD) END,
               s.POSN_JOB_PRGS_CD) k;
