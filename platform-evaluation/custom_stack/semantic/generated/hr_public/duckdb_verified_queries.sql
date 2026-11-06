-- Verified queries for hr_public (compiled by compile_duckdb)
-- il_staff_headcount_2023: What was the staff headcount in Illinois in 2023?
-- verified_by: custom_stack author against the real lake (146119; EAP2023 'All staff' rows, IL) at 2026-11-06
SELECT
  SUM(staff_eap.total_employees) AS "staff_headcount"
FROM ipeds_employees_by_position AS staff_eap
LEFT JOIN ipeds_institution AS institution ON staff_eap.unitid = institution.unitid
WHERE institution.state_abbr = 'IL'
  AND staff_eap.survey_year = 2023
  AND staff_eap.is_category_total = FALSE;

-- fte_by_sector_2023: Staff FTE by sector in 2023
-- verified_by: custom_stack author (fixture + real lake run; not domain-owner approved) at 2026-11-06
SELECT
  institution.sector_code AS "sector",
  SUM(staff_eap.full_time + staff_eap.part_time / 3.0) AS "staff_fte"
FROM ipeds_employees_by_position AS staff_eap
LEFT JOIN ipeds_institution AS institution ON staff_eap.unitid = institution.unitid
WHERE staff_eap.survey_year = 2023
  AND staff_eap.is_category_total = FALSE
GROUP BY 1
ORDER BY "sector";

-- il_qcew_employment_2024: QCEW employment in Illinois in 2024
-- verified_by: custom_stack author (fixture + real lake run; not domain-owner approved) at 2026-11-06
WITH per_period AS (
  SELECT
    qcew.year AS "__period_year",
    qcew.qtr AS "__period_quarter",
    CASE WHEN COUNT(*) = COUNT((qcew.month1_emplvl + qcew.month2_emplvl + qcew.month3_emplvl) / 3.0) THEN SUM((qcew.month1_emplvl + qcew.month2_emplvl + qcew.month3_emplvl) / 3.0) END AS __v
  FROM qcew_combined AS qcew
  WHERE qcew.area_fips = '17000'
    AND qcew.year = 2024
    AND qcew.own_code <> '0'
    AND qcew.industry_code = '611310'
  GROUP BY 1, 2
)
SELECT
  CASE WHEN COUNT(*) = COUNT(__v) THEN AVG(__v) END AS "qcew_employment"
FROM per_period;
