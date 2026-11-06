-- Gold analytic views over the public HR data lake.
-- Written in portable SQL (CREATE OR REPLACE VIEW, CASE, CAST, standard aggregates) so the
-- same definitions can be replayed on DuckDB, Snowflake and Databricks for the common-
-- implementation track. Every view states its grain. Published suppression flags are
-- carried through; suppressed or missing values stay NULL, never zero.

-- ---------------------------------------------------------------------------------
-- Institutions: University of Illinois System campuses + a documented peer panel.
-- Grain: one row per UNITID. Peer list = Big Ten public members + System Offices.
-- The panel is a starting proposal, not an approved HR peer group.
CREATE OR REPLACE VIEW gold_institution_panel AS
SELECT
  h.unitid,
  h.instnm                                   AS institution_name,
  h.stabbr                                   AS state,
  CAST(h.countycd AS VARCHAR)                AS county_fips,
  CAST(h.cbsa AS VARCHAR)                    AS cbsa_code,
  TRIM(h.f1sysnam)                           AS system_name,
  CASE WHEN h.unitid IN ('145637','145600','148654','149587') THEN 'uofi_system'
       ELSE 'big_ten_peer' END               AS panel_role,
  CASE h.unitid WHEN '145637' THEN 'UIUC' WHEN '145600' THEN 'UIC'
                WHEN '148654' THEN 'UIS'  WHEN '149587' THEN 'System Offices' END AS uofi_campus,
  h.hospital, h.medical, h.landgrnt, h.c21basic AS carnegie_basic_2021, h.instsize
FROM ipeds_hd2024 h
WHERE h.unitid IN (
  '145637','145600','148654','149587',            -- University of Illinois System
  '170976','240444','204796','243780','174066',  -- Michigan, Wisconsin, Ohio State, Purdue, Minnesota
  '151351','153658','171100','214777','186380',  -- Indiana, Iowa, Michigan State, Penn State, Rutgers NB
  '163286','181464','110662','209551','236948'   -- Maryland, Nebraska, UCLA, Oregon, Washington
);

-- ---------------------------------------------------------------------------------
-- Fall 2023 staff headcount by IPEDS occupational category and full/part-time status.
-- Grain: unitid x staffcat. Headcount (not FTE). Source: IPEDS S2023_OC.
CREATE OR REPLACE VIEW gold_ipeds_staff_by_occupation AS
SELECT
  s.unitid,
  CAST(s.staffcat AS VARCHAR)   AS staffcat_code,
  l.valuelabel                  AS staff_category,
  CASE CAST(s.ftpt AS VARCHAR) WHEN '1' THEN 'total' WHEN '2' THEN 'full_time' WHEN '3' THEN 'part_time'
       ELSE CAST(s.ftpt AS VARCHAR) END AS ftpt_status,
  s.hrtotlt AS headcount_total, s.hrtotlm AS headcount_men, s.hrtotlw AS headcount_women,
  s.xhrtotlt AS headcount_total_flag,
  '2023-11-01' AS snapshot_date
FROM ipeds_s2023_oc s
LEFT JOIN ipeds_value_label l
  ON l.survey = 'S2023_OC' AND l.varname = 'STAFFCAT' AND l.codevalue = CAST(s.staffcat AS VARCHAR);

-- ---------------------------------------------------------------------------------
-- Non-instructional full-time staff: count, salary outlays and average salary by occupation.
-- Grain: unitid x occupation group (13 groups + total). Source: IPEDS SAL2023_NIS.
-- Average = outlays / number, computed only where number > 0.
CREATE OR REPLACE VIEW gold_ipeds_noninstructional_pay AS
WITH long AS (
  SELECT unitid, '01' AS grp, 'All full-time non-instructional staff' AS occupation_group, sanin01 AS n, sanit01 AS outlays FROM ipeds_sal2023_nis
  UNION ALL SELECT unitid, '02', 'Research', sanin02, sanit02 FROM ipeds_sal2023_nis
  UNION ALL SELECT unitid, '03', 'Public service', sanin03, sanit03 FROM ipeds_sal2023_nis
  UNION ALL SELECT unitid, '04', 'Library, curators, archivists, academic affairs and other education services', sanin04, sanit04 FROM ipeds_sal2023_nis
  UNION ALL SELECT unitid, '05', 'Management', sanin05, sanit05 FROM ipeds_sal2023_nis
  UNION ALL SELECT unitid, '06', 'Business and financial operations', sanin06, sanit06 FROM ipeds_sal2023_nis
  UNION ALL SELECT unitid, '07', 'Computer, engineering and science', sanin07, sanit07 FROM ipeds_sal2023_nis
  UNION ALL SELECT unitid, '08', 'Community/social service, legal, arts, design, media', sanin08, sanit08 FROM ipeds_sal2023_nis
  UNION ALL SELECT unitid, '09', 'Healthcare practitioners and technical', sanin09, sanit09 FROM ipeds_sal2023_nis
  UNION ALL SELECT unitid, '10', 'Service', sanin10, sanit10 FROM ipeds_sal2023_nis
  UNION ALL SELECT unitid, '11', 'Sales and related', sanin11, sanit11 FROM ipeds_sal2023_nis
  UNION ALL SELECT unitid, '12', 'Office and administrative support', sanin12, sanit12 FROM ipeds_sal2023_nis
  UNION ALL SELECT unitid, '13', 'Natural resources, construction and maintenance', sanin13, sanit13 FROM ipeds_sal2023_nis
  UNION ALL SELECT unitid, '14', 'Production, transportation and material moving', sanin14, sanit14 FROM ipeds_sal2023_nis
)
SELECT unitid, grp AS occupation_group_code, occupation_group,
       n AS fulltime_staff, outlays AS salary_outlays,
       CASE WHEN n > 0 THEN ROUND(CAST(outlays AS DOUBLE) / n, 0) END AS avg_salary
FROM long;

-- ---------------------------------------------------------------------------------
-- Full-time instructional staff average salary equated to 9 months, by academic rank and sex.
-- Grain: unitid x academic rank. Source: IPEDS SAL2023_IS.
CREATE OR REPLACE VIEW gold_ipeds_faculty_pay AS
SELECT s.unitid,
       CAST(s.arank AS VARCHAR) AS arank_code,
       l.valuelabel             AS academic_rank,
       s.sainstt AS fulltime_instructional_staff,
       s.saeq9at AS avg_salary_9mo_equated_total,
       s.saeq9am AS avg_salary_9mo_equated_men,
       s.saeq9aw AS avg_salary_9mo_equated_women,
       CASE WHEN s.saeq9am > 0 AND s.saeq9aw IS NOT NULL
            THEN ROUND(CAST(s.saeq9aw AS DOUBLE) / s.saeq9am, 4) END AS women_to_men_avg_ratio
FROM ipeds_sal2023_is s
LEFT JOIN ipeds_value_label l
  ON l.survey = 'SAL2023_IS' AND l.varname = 'ARANK' AND l.codevalue = CAST(s.arank AS VARCHAR);

-- ---------------------------------------------------------------------------------
-- Peer comparison: staff mix and pay for the institution panel.
-- Grain: unitid x occupation group. Joins at matching grain only (no fan-out).
CREATE OR REPLACE VIEW gold_peer_noninstructional_pay AS
SELECT p.institution_name, p.panel_role, p.uofi_campus, n.*
FROM gold_institution_panel p
JOIN gold_ipeds_noninstructional_pay n ON n.unitid = p.unitid;

-- ---------------------------------------------------------------------------------
-- Colleges & universities (NAICS 611310) employment and pay, Illinois and U.S., by ownership.
-- Grain: area x ownership x year. Source: BLS QCEW annual averages.
-- own_code: 0 total, 1 federal, 2 state, 3 local, 5 private. disclosure_code 'N' = suppressed.
CREATE OR REPLACE VIEW gold_qcew_higher_ed_trend AS
SELECT area_fips,
       CASE area_fips WHEN 'US000' THEN 'United States' WHEN '17000' THEN 'Illinois' END AS area_name,
       own_code,
       CASE own_code WHEN '0' THEN 'Total' WHEN '1' THEN 'Federal' WHEN '2' THEN 'State government'
                     WHEN '3' THEN 'Local government' WHEN '5' THEN 'Private' END AS ownership,
       year, disclosure_code,
       CASE WHEN disclosure_code = 'N' THEN NULL ELSE annual_avg_emplvl END AS employment,
       CASE WHEN disclosure_code = 'N' THEN NULL ELSE avg_annual_pay END    AS avg_annual_pay,
       annual_avg_estabs AS establishments
FROM qcew_colleges_annual
WHERE area_fips IN ('US000', '17000');

-- ---------------------------------------------------------------------------------
-- Illinois higher-education (NAICS 6113) labor-flow indicators from Census QWI.
-- Grain: quarter (statewide, all ownerships, all sexes/ages). Rates are QWI-defined.
-- Status flags (s*) are retained; QWI cells can be suppressed or imputed.
CREATE OR REPLACE VIEW gold_qwi_il_higher_ed_flows AS
SELECT year, quarter,
       CAST(year AS VARCHAR) || '-Q' || CAST(quarter AS VARCHAR) AS period,
       emp        AS beginning_of_quarter_employment,
       emp_s      AS stable_employment,
       hir_a      AS all_hires,
       hir_n      AS new_hires,
       sep        AS separations,
       turn_ovr_s AS stable_turnover_rate,
       earn_s     AS avg_monthly_earnings_stable,
       s_emp      AS emp_flag,
       s_sep      AS sep_flag
FROM qwi_il_sa_gs_n4_oslp
WHERE industry = '6113' AND sex = '0' AND agegrp = 'A00' AND ownercode = 'A00';

-- Same, by age group: the age profile of separations is the public proxy for a retirement wave.
-- Grain: quarter x age group.
CREATE OR REPLACE VIEW gold_qwi_il_higher_ed_flows_by_age AS
SELECT year, quarter, agegrp,
       CASE agegrp WHEN 'A01' THEN '14-18' WHEN 'A02' THEN '19-21' WHEN 'A03' THEN '22-24'
                   WHEN 'A04' THEN '25-34' WHEN 'A05' THEN '35-44' WHEN 'A06' THEN '45-54'
                   WHEN 'A07' THEN '55-64' WHEN 'A08' THEN '65-99' END AS age_group,
       emp AS beginning_of_quarter_employment, hir_a AS all_hires, sep AS separations,
       turn_ovr_s AS stable_turnover_rate, earn_s AS avg_monthly_earnings_stable
FROM qwi_il_sa_gs_n4_oslp
WHERE industry = '6113' AND sex = '0' AND agegrp <> 'A00' AND ownercode = 'A00';

-- ---------------------------------------------------------------------------------
-- Occupation profile: O*NET occupation + job zone + SOC 2018 code + observed AI usage.
-- Grain: O*NET-SOC occupation. AI exposure is Anthropic Economic Index observed usage
-- (a selected population of Claude conversations), not a displacement forecast.
CREATE OR REPLACE VIEW gold_occupation_profile AS
WITH tasks AS (
  SELECT onetsoc_code, COUNT(*) AS n_tasks,
         SUM(CASE WHEN task_type = 'Core' THEN 1 ELSE 0 END) AS n_core_tasks
  FROM onet_task_statements GROUP BY onetsoc_code
), cw AS (
  SELECT onetsoc_code, MIN(soc_2018_code) AS soc_2018_code, COUNT(*) AS n_soc_codes
  FROM onet_soc_crosswalk GROUP BY onetsoc_code
)
SELECT o.onetsoc_code, o.title, o.description,
       jz.job_zone,
       cw.soc_2018_code, cw.n_soc_codes,
       t.n_tasks, t.n_core_tasks,
       ae.observed_exposure AS aei_observed_exposure
FROM onet_occupation_data o
LEFT JOIN onet_job_zones jz ON jz.onetsoc_code = o.onetsoc_code
LEFT JOIN cw ON cw.onetsoc_code = o.onetsoc_code
LEFT JOIN tasks t ON t.onetsoc_code = o.onetsoc_code
LEFT JOIN aei_job_exposure ae ON ae.occ_code = cw.soc_2018_code;

-- ---------------------------------------------------------------------------------
-- Task-level AI usage evidence for each O*NET task (lower-cased text join, as published by AEI).
-- Grain: O*NET task. Multiple metrics are kept side by side, not combined into one score.
CREATE OR REPLACE VIEW gold_task_ai_evidence AS
SELECT ts.onetsoc_code, ts.task_id, ts.task, ts.task_type,
       tp.penetration            AS aei_task_penetration,
       pct.pct                   AS aei_task_share_pct_v2,
       aa.directive              AS aei_directive_share,
       aa.feedback_loop          AS aei_feedback_loop_share,
       aa.task_iteration         AS aei_task_iteration_share,
       aa.validation             AS aei_validation_share,
       aa.learning               AS aei_learning_share
FROM onet_task_statements ts
LEFT JOIN aei_task_penetration tp ON tp.task = ts.task
LEFT JOIN aei_task_pct_v2 pct ON pct.task_name = LOWER(ts.task)
LEFT JOIN aei_automation_vs_augmentation_by_task aa ON aa.task_name = LOWER(ts.task);

-- ---------------------------------------------------------------------------------
-- SUCSS civil-service class -> top unreviewed O*NET candidate with context.
-- Grain: SUCSS source record x candidate rank. These are lexical suggestions awaiting
-- human review; they are NOT mappings and must not be used for headcount allocation.
CREATE OR REPLACE VIEW gold_sucss_onet_candidates AS
SELECT c.*, op.job_zone, op.soc_2018_code, op.aei_observed_exposure,
       'unreviewed_lexical_suggestion' AS mapping_status
FROM sucss_onet_candidate c
LEFT JOIN gold_occupation_profile op ON op.onetsoc_code = c.onet_code;
