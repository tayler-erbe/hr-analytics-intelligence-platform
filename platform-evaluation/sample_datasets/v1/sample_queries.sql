-- DuckDB queries for longitudinal/sample.duckdb only.
-- All data and physical layouts are synthetic. No connection to real EDW.

-- Effective primary jobs as known on the stated date.
-- Effective end is inclusive; recorded end is exclusive in this generator.
WITH snapshot AS (
 SELECT * FROM T_JOB_DETL_HIST
 WHERE JOB_DETL_EFF_DT <= DATE '2026-10-31'
   AND JOB_DETL_EXP_DT >= DATE '2026-10-31'
   AND ROW_REC_START_DT <= DATE '2026-10-31'
   AND ROW_REC_END_DT > DATE '2026-10-31'
   AND JOB_STATUS_CD='A' AND JOB_CONTRACT_TYPE_CD='P'
)
SELECT COUNT(DISTINCT EDW_PERS_ID) AS people,
       COUNT(DISTINCT POSN_NBR) AS filled_positions,
       COUNT(*) AS primary_appointment_rows,
       SUM(JOB_FTE) AS total_fte
FROM snapshot;

-- Separation-event counts by year and synthetic reason code.
-- This is event history, not an employee risk score or a measured turnover rate.
SELECT EXTRACT(YEAR FROM TERM_DT) AS separation_year,TERM_REASON_CD,COUNT(*) AS events
FROM T_EMPEE_HIST_5
WHERE ROW_REC_END_DT=DATE '9999-12-31'
GROUP BY 1,2 ORDER BY 1,2;

-- Reference mapping is synthetic HR-owned architecture, not an EDW discovery.
SELECT ROLE_FAMILY,COUNT(*) AS classes
FROM REF_ROLE_FAMILY GROUP BY ROLE_FAMILY ORDER BY ROLE_FAMILY;
