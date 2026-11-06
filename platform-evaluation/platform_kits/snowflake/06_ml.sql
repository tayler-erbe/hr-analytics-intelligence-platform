-- =====================================================================
-- 06_ml.sql — SNOWFLAKE.ML.FORECAST on Census QWI higher-ed turnover
-- Series: Champaign (17019), Cook (17031), Sangamon (17167) counties and
-- Illinois statewide; target = TURNOVRS (stable turnover rate), quarterly.
-- Chronological holdout (last 4 quarters per series) vs naive baselines.
-- PUBLIC DATA ONLY. This is a capability exercise on aggregate public
-- statistics, not a workforce prediction for any institution.
-- Rubric: M1 (reproducible features), M2 (valid evaluation vs baseline,
-- leakage prevention, uncertainty), M3 (scheduled scoring/monitoring/
-- rollback — partly; registry path is in 06_ml_notebook.py). Evidence S06*.
-- Syntax per docs search 2026-11-06: CREATE SNOWFLAKE.ML.FORECAST <name>(
--   INPUT_DATA => SYSTEM$REFERENCE(...), [SERIES_COLNAME =>], TIMESTAMP_COLNAME =>,
--   TARGET_COLNAME => [, CONFIG_OBJECT => {...}]); <name>!FORECAST(FORECASTING_PERIODS => n
--   [, CONFIG_OBJECT => {'prediction_interval': x}]).
-- =====================================================================

USE ROLE ACCOUNTADMIN;
GRANT CREATE SNOWFLAKE.ML.FORECAST ON SCHEMA HR_KIT.ML TO ROLE HR_KIT_ADMIN;
GRANT EXECUTE TASK ON ACCOUNT TO ROLE HR_KIT_ADMIN;     -- only for the optional scheduled task

USE ROLE HR_KIT_ADMIN;
USE WAREHOUSE HR_KIT_WH;
USE SCHEMA HR_KIT.ML;
ALTER SESSION SET QUERY_TAG = 'hr_kit:06_ml';

-- ---------------------------------------------------------------------
-- 1. Series table (one row per series x quarter); frozen snapshot for reproducibility
-- ---------------------------------------------------------------------
CREATE OR REPLACE TABLE QWI_TURNOVER_SERIES AS
SELECT COALESCE(county_fips, 'IL_STATE')       AS series,
       quarter_start::TIMESTAMP_NTZ             AS ts,
       turnovrs::FLOAT                          AS turnovrs
FROM HR_KIT.CURATED.V_QWI_HIGHER_ED
WHERE (county_fips IN ('17019','17031','17167') OR county_fips IS NULL)
  AND turnovrs IS NOT NULL;

-- Evidence: series coverage, gaps and duplicates (must be 0 duplicates)
SELECT series, COUNT(*) n_quarters, MIN(ts) first_q, MAX(ts) last_q,
       COUNT(*) - COUNT(DISTINCT ts) AS duplicate_quarters,
       DATEDIFF(QUARTER, MIN(ts), MAX(ts)) + 1 - COUNT(DISTINCT ts) AS missing_quarters
FROM QWI_TURNOVER_SERIES GROUP BY series ORDER BY series;
-- QWI suppresses/flags some cells; missing quarters are left missing (not imputed). Record them.
SELECT HASH_AGG(*) AS series_snapshot_hash FROM QWI_TURNOVER_SERIES;   -- record (reproducibility)

-- ---------------------------------------------------------------------
-- 2. Chronological split — the holdout is never visible to training
-- ---------------------------------------------------------------------
SET HOLDOUT_QUARTERS = 4;
CREATE OR REPLACE TABLE QWI_SPLIT AS
SELECT s.*,
       IFF(ROW_NUMBER() OVER (PARTITION BY series ORDER BY ts DESC) <= $HOLDOUT_QUARTERS, 'holdout', 'train') AS split
FROM QWI_TURNOVER_SERIES s;
CREATE OR REPLACE VIEW V_QWI_TRAIN AS SELECT series, ts, turnovrs FROM QWI_SPLIT WHERE split = 'train';

-- Leakage check: per series, max(train ts) < min(holdout ts). Must return 0 rows.
SELECT series FROM QWI_SPLIT GROUP BY series
HAVING MAX(IFF(split = 'train', ts, NULL)) >= MIN(IFF(split = 'holdout', ts, NULL));

-- ---------------------------------------------------------------------
-- 3. Train (record wall time + any warnings) and forecast the holdout horizon
-- ---------------------------------------------------------------------
CREATE OR REPLACE SNOWFLAKE.ML.FORECAST QWI_TURNOVER_FCST(
  INPUT_DATA        => SYSTEM$REFERENCE('VIEW', 'HR_KIT.ML.V_QWI_TRAIN'),
  SERIES_COLNAME    => 'SERIES',
  TIMESTAMP_COLNAME => 'TS',
  TARGET_COLNAME    => 'TURNOVRS',
  CONFIG_OBJECT     => {'ON_ERROR': 'SKIP'}       -- skip series that fail rather than abort; verify option name
);
-- Quarterly frequency is inferred from the timestamps. If training errors on frequency
-- or minimum-length rules, record the message verbatim as a limitation.

CREATE OR REPLACE TABLE QWI_FORECAST_HOLDOUT AS
SELECT * FROM TABLE(QWI_TURNOVER_FCST!FORECAST(
  FORECASTING_PERIODS => $HOLDOUT_QUARTERS,
  CONFIG_OBJECT => {'prediction_interval': 0.9}));
SELECT * FROM QWI_FORECAST_HOLDOUT ORDER BY 1, 2;    -- columns SERIES, TS, FORECAST, LOWER_BOUND, UPPER_BOUND (verify)

-- Model-internal metrics (cross-validation on training data) and drivers
CALL QWI_TURNOVER_FCST!SHOW_EVALUATION_METRICS();
CALL QWI_TURNOVER_FCST!SHOW_TRAINING_LOGS();
CALL QWI_TURNOVER_FCST!EXPLAIN_FEATURE_IMPORTANCE();

-- ---------------------------------------------------------------------
-- 4. Holdout evaluation vs baselines (deterministic SQL)
-- ---------------------------------------------------------------------
-- Baseline A: last observed training value. Baseline B: seasonal naive (same quarter, prior year).
CREATE OR REPLACE TABLE QWI_EVAL AS
WITH h AS (SELECT series, ts, turnovrs AS actual FROM QWI_SPLIT WHERE split = 'holdout'),
last_train AS (
  SELECT series, turnovrs AS last_value FROM QWI_SPLIT WHERE split = 'train'
  QUALIFY ROW_NUMBER() OVER (PARTITION BY series ORDER BY ts DESC) = 1),
f AS (SELECT series::STRING AS series, ts::TIMESTAMP_NTZ AS ts, forecast, lower_bound, upper_bound
      FROM QWI_FORECAST_HOLDOUT)
SELECT h.series, h.ts, h.actual,
       f.forecast, f.lower_bound, f.upper_bound,
       lt.last_value                               AS baseline_last_value,
       sn.turnovrs                                 AS baseline_seasonal_naive   -- NULL if prior-year quarter missing
FROM h
LEFT JOIN f  ON f.series = h.series AND f.ts = h.ts
LEFT JOIN last_train lt ON lt.series = h.series
LEFT JOIN QWI_SPLIT sn ON sn.series = h.series AND sn.ts = DATEADD(YEAR, -1, h.ts) AND sn.split = 'train';
-- Note: the seasonal-naive value for a holdout quarter must come from TRAIN rows only
-- (it does when the holdout is ≤ 4 quarters).

SELECT series,
       COUNT(*)                                             AS holdout_quarters,
       COUNT(forecast)                                      AS forecast_available,
       AVG(ABS(forecast - actual))                          AS mae_forecast,
       AVG(ABS(baseline_last_value - actual))               AS mae_last_value,
       AVG(ABS(baseline_seasonal_naive - actual))           AS mae_seasonal_naive,
       AVG(IFF(actual BETWEEN lower_bound AND upper_bound, 1, 0)) AS interval_coverage_90
FROM QWI_EVAL GROUP BY ROLLUP(series) ORDER BY series NULLS LAST;
-- Interpretation rule: with ~4 holdout points per series this is a smoke test of the
-- workflow, not evidence of forecasting skill. Report the n alongside every metric.

-- ---------------------------------------------------------------------
-- 5. Versioning, scheduled scoring and rollback (M3) — optional, low cost
-- ---------------------------------------------------------------------
-- Forecast class instances are schema objects, not Model Registry models.
-- "Versioning" here = date-stamped clones; rollback = re-point the task.
-- The Model Registry path (log_model, versions, default version, metrics)
-- is exercised in 06_ml_notebook.py.
SHOW SNOWFLAKE.ML.FORECAST IN SCHEMA HR_KIT.ML;

CREATE TABLE IF NOT EXISTS QWI_FORECAST_SCHEDULED (
  scored_at TIMESTAMP_LTZ, model_name STRING, series STRING, ts TIMESTAMP_NTZ,
  forecast FLOAT, lower_bound FLOAT, upper_bound FLOAT);

CREATE OR REPLACE TASK QWI_FORECAST_TASK
  WAREHOUSE = HR_KIT_WH
  SCHEDULE = 'USING CRON 0 6 1 * * UTC'           -- monthly; QWI updates quarterly
  COMMENT = 'Batch scoring demo; created SUSPENDED to avoid cost'
AS
  INSERT INTO HR_KIT.ML.QWI_FORECAST_SCHEDULED
  SELECT CURRENT_TIMESTAMP(), 'QWI_TURNOVER_FCST', series, ts, forecast, lower_bound, upper_bound
  FROM TABLE(HR_KIT.ML.QWI_TURNOVER_FCST!FORECAST(FORECASTING_PERIODS => 4));
-- Run once manually for evidence, then leave suspended:
EXECUTE TASK QWI_FORECAST_TASK;
SELECT * FROM TABLE(HR_KIT.INFORMATION_SCHEMA.TASK_HISTORY(TASK_NAME => 'QWI_FORECAST_TASK')) ORDER BY scheduled_time DESC;
-- Monitoring query (drift of the newest forecast vs the previous one)
SELECT series, ts, forecast,
       forecast - LAG(forecast) OVER (PARTITION BY series, ts ORDER BY scored_at) AS change_vs_previous_run
FROM QWI_FORECAST_SCHEDULED ORDER BY series, ts, scored_at;

-- ML cost evidence: warehouse credits under this query tag
SELECT query_tag, SUM(credits_used_cloud_services) AS cloud_services_credits, COUNT(*) AS queries,
       SUM(total_elapsed_time) / 1000 AS seconds
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
WHERE query_tag = 'hr_kit:06_ml' AND start_time > DATEADD(DAY, -2, CURRENT_TIMESTAMP())
GROUP BY query_tag;
-- (Warehouse compute credits are per warehouse, see WAREHOUSE_METERING_HISTORY in README §Cost.)
