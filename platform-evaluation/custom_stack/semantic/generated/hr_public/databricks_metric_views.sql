-- Generated from hr_public.yaml (sha256 102bec2ac50cb4a9); NOT executed against Databricks here.
CREATE OR REPLACE VIEW hr_analytics.hr_public.qcew_combined AS
SELECT area_fips, own_code, industry_code, year, qtr, disclosure_code,
       month1_emplvl, month2_emplvl, month3_emplvl, total_qtrly_wages, source_id, source_vintage
FROM qcew_industry
UNION ALL
SELECT area_fips, own_code, industry_code, year, qtr, disclosure_code,
       month1_emplvl, month2_emplvl, month3_emplvl, total_qtrly_wages, source_id, source_vintage
FROM qcew_area
WHERE industry_code <> '611310';

CREATE OR REPLACE VIEW hr_analytics.hr_public.staff_eap_metrics
WITH METRICS
LANGUAGE YAML
AS $$
version: '1.1'
comment: 'IPEDS Employees by Assigned Position (EAP), Fall snapshot. Includes total, subtotal and faculty-status rows (is_category_total
  = true) alongside the partition rows. Grain: one row per unitid x survey_year x eapcat_code (occupation category x faculty
  status). Generated from hr_public.yaml sha256 102bec2ac50cb4a9; status development.'
source: hr_analytics.hr_public.ipeds_employees_by_position
joins:
- name: institution
  source: hr_analytics.hr_public.ipeds_institution
  'on': source.unitid = institution.unitid
dimensions:
- name: survey_year
  expr: survey_year
  comment: IPEDS EAP survey year = Fall snapshot year (EAP2023 = Fall 2023).
  synonyms:
  - survey year
- name: unitid
  expr: unitid
  comment: IPEDS unit id (also used to align populations in derived ratios).
  synonyms:
  - unitid
  - unit id
- name: position_category
  expr: position_category
  comment: EAP position category. Non-total rows (is_category_total = false) partition the institution total exactly (lake
    contract rule 4), so grouped rows are additive.
  synonyms:
  - position category
  - position categories
  - occupation category
  - occupational category
  - job category
  - job categories
- name: category_total_row
  expr: is_category_total
  comment: TRUE for published total / subtotal / faculty-status rows; FALSE rows form the exact partition.
  synonyms:
  - category total row
- name: institution_name
  expr: institution.institution_name
  comment: Institution name as published in IPEDS HD.
  synonyms:
  - institution
  - institutions
  - college
  - colleges
  - university
  - universities
  - school
  - schools
  - campus
  - campuses
- name: state
  expr: institution.state_abbr
  comment: Institution state (postal abbreviation).
  synonyms:
  - state
  - states
- name: sector
  expr: institution.sector_code
  comment: IPEDS sector code (1 public 4-year+, 2 private nonprofit 4-year+, 3 private for-profit 4-year+, 4 public 2-year
    ...).
  synonyms:
  - sector
  - sectors
  - control
  - institution type
- name: carnegie
  expr: institution.carnegie
  comment: Carnegie classification label as loaded (HD2024).
  synonyms:
  - carnegie classification
  - carnegie class
  - carnegie
measures:
- name: staff_headcount
  expr: CASE WHEN COUNT(DISTINCT survey_year) <= 1 THEN SUM(CASE WHEN (is_category_total = FALSE) THEN total_employees END)
    END
  comment: 'Full-time plus part-time employees reported in IPEDS EAP for one Fall snapshot. Unit: people. Grain rule: Snapshot
    stock. One survey year at a time. Sums only is_category_total = false rows (exact partition of the institution total);
    never adds total/subtotal rows.'
  synonyms:
  - staff headcount
  - headcount
  - employees
  - employee headcount
  - staff count
  - number of staff
  - number of employees
  - staff
  - workforce
  - employee count
- name: full_time_staff_headcount
  expr: CASE WHEN COUNT(DISTINCT survey_year) <= 1 THEN SUM(CASE WHEN (is_category_total = FALSE) THEN full_time END) END
  comment: 'Full-time employees reported in IPEDS EAP for one Fall snapshot. Unit: people. Grain rule: Snapshot stock; one
    survey year at a time; same category rules as staff_headcount.'
  synonyms:
  - full-time staff
  - full time staff
  - full-time employees
  - full time employees
  - full-time headcount
  - full-time staff headcount
  - full time staff headcount
- name: staff_fte
  expr: CASE WHEN COUNT(DISTINCT survey_year) <= 1 THEN SUM(CASE WHEN (is_category_total = FALSE) THEN full_time + part_time
    / 3.0 END) END
  comment: 'IPEDS FTE convention = full-time + one third of part-time. Not payroll FTE. Unit: FTE. Grain rule: Snapshot stock;
    FTE is not headcount. One survey year at a time.'
  synonyms:
  - staff fte
  - fte
  - full-time equivalent
  - full time equivalent
  - fte staff
  - full-time equivalent staff
$$;

CREATE OR REPLACE VIEW hr_analytics.hr_public.salary_instructional_metrics
WITH METRICS
LANGUAGE YAML
AS $$
version: '1.1'
comment: 'IPEDS SAL_IS full-time instructional staff salary outlays by rank and contract length. Grain: one row per unitid
  x survey_year x arank_code x contract_length. Generated from hr_public.yaml sha256 102bec2ac50cb4a9; status development.'
source: hr_analytics.hr_public.ipeds_salary_instructional
joins:
- name: institution
  source: hr_analytics.hr_public.ipeds_institution
  'on': source.unitid = institution.unitid
dimensions:
- name: survey_year
  expr: survey_year
  comment: IPEDS salary survey year (SAL2023 = academic year 2023-24).
  synonyms:
  - survey year
- name: academic_rank
  expr: academic_rank
  comment: Academic rank (no published all-ranks row; ranks partition staff).
  synonyms:
  - rank
  - ranks
  - academic rank
  - faculty rank
- name: contract_length
  expr: contract_length
  comment: Contract length (9-, 10-, 11-, 12-month). Partitions staff; salaries are not comparable across lengths.
  synonyms:
  - contract length
  - contract
- name: institution_name
  expr: institution.institution_name
  comment: Institution name as published in IPEDS HD.
  synonyms:
  - institution
  - institutions
  - college
  - colleges
  - university
  - universities
  - school
  - schools
  - campus
  - campuses
- name: state
  expr: institution.state_abbr
  comment: Institution state (postal abbreviation).
  synonyms:
  - state
  - states
- name: sector
  expr: institution.sector_code
  comment: IPEDS sector code (1 public 4-year+, 2 private nonprofit 4-year+, 3 private for-profit 4-year+, 4 public 2-year
    ...).
  synonyms:
  - sector
  - sectors
  - control
  - institution type
- name: carnegie
  expr: institution.carnegie
  comment: Carnegie classification label as loaded (HD2024).
  synonyms:
  - carnegie classification
  - carnegie class
  - carnegie
measures:
- name: instructional_staff_count
  expr: CASE WHEN COUNT(DISTINCT survey_year) <= 1 THEN SUM(staff_count) END
  comment: 'Full-time instructional staff counted in the salary survey, all contract lengths (differs from EAP instructional
    headcount). Unit: people. Grain rule: Snapshot stock; ranks and contract lengths partition staff and are additive.'
  synonyms:
  - faculty count
  - number of faculty
  - instructional staff count
  - full-time faculty
- name: avg_instructional_salary
  expr: CAST(SUM(CASE WHEN (contract_length = '9-month') THEN salary_outlays END) AS DOUBLE) / NULLIF(SUM(CASE WHEN (contract_length
    = '9-month') THEN staff_count END), 0)
  comment: 'Salary outlays divided by full-time instructional staff at the requested grain; 9-month contracts unless another
    contract length is requested. Unit: USD per person. Grain rule: Ratio of sums. Never average institution averages, never
    mix contract lengths, never sum salaries across a join fan-out.'
  synonyms:
  - average faculty salary
  - average instructional salary
  - faculty salary
  - faculty salaries
  - mean faculty salary
  - instructional salary
$$;

CREATE OR REPLACE VIEW hr_analytics.hr_public.salary_noninstructional_metrics
WITH METRICS
LANGUAGE YAML
AS $$
version: '1.1'
comment: 'IPEDS SAL_NIS full-time non-instructional staff salary outlays (13 categories that partition staff). Grain: one
  row per unitid x survey_year x occupation_category_code. Generated from hr_public.yaml sha256 102bec2ac50cb4a9; status development.'
source: hr_analytics.hr_public.ipeds_salary_noninstructional
joins:
- name: institution
  source: hr_analytics.hr_public.ipeds_institution
  'on': source.unitid = institution.unitid
dimensions:
- name: survey_year
  expr: survey_year
  comment: IPEDS salary survey year (SAL2023 = 2023-24).
  synonyms:
  - survey year
- name: occupation_category
  expr: occupation_category
  comment: Non-instructional occupation category (partition; no total row).
  synonyms:
  - occupation category
  - occupation categories
  - staff category
  - staff categories
- name: institution_name
  expr: institution.institution_name
  comment: Institution name as published in IPEDS HD.
  synonyms:
  - institution
  - institutions
  - college
  - colleges
  - university
  - universities
  - school
  - schools
  - campus
  - campuses
- name: state
  expr: institution.state_abbr
  comment: Institution state (postal abbreviation).
  synonyms:
  - state
  - states
- name: sector
  expr: institution.sector_code
  comment: IPEDS sector code (1 public 4-year+, 2 private nonprofit 4-year+, 3 private for-profit 4-year+, 4 public 2-year
    ...).
  synonyms:
  - sector
  - sectors
  - control
  - institution type
- name: carnegie
  expr: institution.carnegie
  comment: Carnegie classification label as loaded (HD2024).
  synonyms:
  - carnegie classification
  - carnegie class
  - carnegie
measures:
- name: avg_noninstructional_salary
  expr: CAST(SUM(salary_outlays) AS DOUBLE) / NULLIF(SUM(staff_count), 0)
  comment: 'Non-instructional salary outlays divided by full-time non-instructional staff. Unit: USD per person. Grain rule:
    Ratio of sums at the requested grain.'
  synonyms:
  - average staff salary
  - average non-instructional salary
  - average noninstructional salary
  - non-instructional salary
  - staff salary
- name: noninstructional_salary_outlays
  expr: SUM(salary_outlays)
  comment: 'Total salary outlays for full-time non-instructional staff. Unit: USD. Grain rule: Additive across institutions
    and the 13 categories (they partition staff).'
  synonyms:
  - salary outlays
  - non-instructional salary outlays
  - staff payroll
  - payroll
$$;

CREATE OR REPLACE VIEW hr_analytics.hr_public.enrollment_metrics
WITH METRICS
LANGUAGE YAML
AS $$
version: '1.1'
comment: 'IPEDS EFFY 12-month unduplicated enrollment by student level (levels nest). Grain: one row per unitid x survey_year
  x level_code. Generated from hr_public.yaml sha256 102bec2ac50cb4a9; status development.'
source: hr_analytics.hr_public.ipeds_enrollment_12mo
joins:
- name: institution
  source: hr_analytics.hr_public.ipeds_institution
  'on': source.unitid = institution.unitid
dimensions:
- name: survey_year
  expr: survey_year - 1
  comment: ALIGNED fall-year label. EFFY N covers academic year (N-1)-(N), so EFFY2024 (2023-24) is labelled 2023 to align
    with the EAP Fall 2023 snapshot.
  synonyms:
  - survey year
- name: unitid
  expr: unitid
  comment: IPEDS unit id.
  synonyms:
  - unitid
  - unit id
- name: effy_year
  expr: survey_year
  comment: Raw EFFY survey year as published (EFFY2024 = 2023-24).
  synonyms:
  - effy year
- name: student_level
  expr: level_code
  comment: EFFY student level code (1 all students, 2 undergraduate, 12 graduate). Levels nest.
  synonyms:
  - student level
  - level
  - levels
- name: institution_name
  expr: institution.institution_name
  comment: Institution name as published in IPEDS HD.
  synonyms:
  - institution
  - institutions
  - college
  - colleges
  - university
  - universities
  - school
  - schools
  - campus
  - campuses
- name: state
  expr: institution.state_abbr
  comment: Institution state (postal abbreviation).
  synonyms:
  - state
  - states
- name: sector
  expr: institution.sector_code
  comment: IPEDS sector code (1 public 4-year+, 2 private nonprofit 4-year+, 3 private for-profit 4-year+, 4 public 2-year
    ...).
  synonyms:
  - sector
  - sectors
  - control
  - institution type
- name: carnegie
  expr: institution.carnegie
  comment: Carnegie classification label as loaded (HD2024).
  synonyms:
  - carnegie classification
  - carnegie class
  - carnegie
measures:
- name: enrollment_12mo
  expr: CASE WHEN COUNT(DISTINCT survey_year - 1) <= 1 THEN SUM(CASE WHEN (level_code = '1') THEN enrollment_total END) END
  comment: 'IPEDS EFFY unduplicated headcount for the 12-month period, all students unless a level is requested. Unit: students.
    Grain rule: Do not sum across years (students recur) or across nested levels.'
  synonyms:
  - enrollment
  - enrolment
  - students
  - student headcount
  - 12-month enrollment
  - unduplicated enrollment
$$;

CREATE OR REPLACE VIEW hr_analytics.hr_public.qcew_metrics
WITH METRICS
LANGUAGE YAML
AS $$
version: '1.1'
comment: 'BLS QCEW. Union of the national/state/county NAICS 611310 file and the IL county all-industry file, excluding industry_code
  ''611310'' from the county file (those rows duplicate the industry file; lake contract rule 7). Grain: one row per area_fips
  x own_code x industry_code x year x qtr. Generated from hr_public.yaml sha256 102bec2ac50cb4a9; status development.'
source: hr_analytics.hr_public.qcew_combined
dimensions:
- name: year
  expr: year
  comment: Calendar year.
  synonyms:
  - calendar year
- name: quarter
  expr: qtr
  comment: Calendar quarter 1-4.
  synonyms:
  - calendar quarter
- name: area
  expr: area_fips
  comment: QCEW area FIPS (US000 national, 17000 Illinois statewide, 5-digit counties).
  synonyms:
  - area
  - areas
  - county
  - counties
  - geography
- name: ownership
  expr: own_code
  comment: QCEW ownership code (0 total covered, 1 federal, 2 state, 3 local, 5 private).
  synonyms:
  - ownership
  - owner
  - public or private
- name: industry
  expr: industry_code
  comment: NAICS industry code (nested levels in the county file).
  synonyms:
  - industry
  - industries
  - naics
measures:
- name: qcew_employment
  expr: CAST(CASE WHEN COUNT(CASE WHEN (own_code <> '0') AND (industry_code = '611310') THEN 1 END) = COUNT(CASE WHEN (own_code
    <> '0') AND (industry_code = '611310') THEN (month1_emplvl + month2_emplvl + month3_emplvl) / 3.0 END) THEN SUM(CASE WHEN
    (own_code <> '0') AND (industry_code = '611310') THEN (month1_emplvl + month2_emplvl + month3_emplvl) / 3.0 END) END AS
    DOUBLE) / NULLIF(COUNT(DISTINCT CONCAT(CAST(year AS STRING), '-', CAST(qtr AS STRING))), 0)
  comment: 'Covered employment, average of the three monthly levels; averaged over quarters for a year. Returns NULL when
    any contributing cell is disclosure-suppressed. Unit: jobs. Grain rule: Stock. Sum across ownership members within one
    area; average (not sum) over quarters. Area must be chosen. Suppressed cells propagate as NULL instead of silently understating.'
  synonyms:
  - qcew employment
  - covered employment
  - jobs
  - employment
  - employees
  - employment level
- name: qcew_total_wages
  expr: CASE WHEN COUNT(CASE WHEN (own_code <> '0') AND (industry_code = '611310') THEN 1 END) = COUNT(CASE WHEN (own_code
    <> '0') AND (industry_code = '611310') THEN total_qtrly_wages END) THEN SUM(CASE WHEN (own_code <> '0') AND (industry_code
    = '611310') THEN total_qtrly_wages END) END
  comment: 'Total covered quarterly wages, additive over quarters. NULL when any contributing cell is suppressed. Unit: USD.
    Grain rule: Flow. Sum over quarters and ownership members within one area; suppressed cells propagate as NULL.'
  synonyms:
  - total wages
  - qcew wages
  - wages paid
  - quarterly wages
$$;

CREATE OR REPLACE VIEW hr_analytics.hr_public.qwi_metrics
WITH METRICS
LANGUAGE YAML
AS $$
version: '1.1'
comment: 'Census QWI, Illinois, NAICS 6113, by sex x age group (published totals sex 0 / agegrp A00). Grain: one row per geography
  x industry x ownercode x year x quarter x sex x agegrp. Generated from hr_public.yaml sha256 102bec2ac50cb4a9; status development.'
source: hr_analytics.hr_public.qwi_higher_ed
dimensions:
- name: year
  expr: year
  comment: Calendar year.
  synonyms:
  - calendar year
- name: quarter
  expr: quarter
  comment: Calendar quarter 1-4.
  synonyms:
  - calendar quarter
- name: geography
  expr: geography
  comment: QWI geography (2-digit state FIPS; counties if loaded).
  synonyms:
  - geography
- name: industry
  expr: industry
  comment: NAICS industry code.
  synonyms:
  - industry
  - naics
- name: ownership
  expr: ownercode
  comment: QWI ownership code (A00 all).
  synonyms:
  - ownership
- name: sex
  expr: sex
  comment: QWI sex code (0 all, 1 male, 2 female).
  synonyms:
  - sex
  - gender
- name: age_group
  expr: agegrp
  comment: QWI age group (A00 all ages, A01 14-18 ... A08 65-99).
  synonyms:
  - age group
  - age groups
  - age
measures:
- name: qwi_employment
  expr: CAST(CASE WHEN COUNT(CASE WHEN (geography = '17') AND (sex = '0') AND (agegrp = 'A00') AND (industry = '6113') AND
    (ownercode = 'A00') THEN 1 END) = COUNT(CASE WHEN (geography = '17') AND (sex = '0') AND (agegrp = 'A00') AND (industry
    = '6113') AND (ownercode = 'A00') THEN emp END) THEN SUM(CASE WHEN (geography = '17') AND (sex = '0') AND (agegrp = 'A00')
    AND (industry = '6113') AND (ownercode = 'A00') THEN emp END) END AS DOUBLE) / NULLIF(COUNT(DISTINCT CONCAT(CAST(year
    AS STRING), '-', CAST(quarter AS STRING))), 0)
  comment: 'Census QWI Emp (beginning-of-quarter jobs); averaged over quarters. Unit: jobs. Grain rule: Stock; average over
    quarters; all-sex/all-age row by default.'
  synonyms:
  - qwi employment
  - beginning of quarter employment
  - employment
  - employees
  - jobs
- name: qwi_hires
  expr: CASE WHEN COUNT(CASE WHEN (geography = '17') AND (sex = '0') AND (agegrp = 'A00') AND (industry = '6113') AND (ownercode
    = 'A00') THEN 1 END) = COUNT(CASE WHEN (geography = '17') AND (sex = '0') AND (agegrp = 'A00') AND (industry = '6113')
    AND (ownercode = 'A00') THEN hira END) THEN SUM(CASE WHEN (geography = '17') AND (sex = '0') AND (agegrp = 'A00') AND
    (industry = '6113') AND (ownercode = 'A00') THEN hira END) END
  comment: 'Census QWI HirA, summed over quarters; NULL if any quarter is not yet published. Unit: hires. Grain rule: Flow;
    additive over quarters.'
  synonyms:
  - hires
  - hiring
  - new hires
  - all hires
- name: qwi_separations
  expr: CASE WHEN COUNT(CASE WHEN (geography = '17') AND (sex = '0') AND (agegrp = 'A00') AND (industry = '6113') AND (ownercode
    = 'A00') THEN 1 END) = COUNT(CASE WHEN (geography = '17') AND (sex = '0') AND (agegrp = 'A00') AND (industry = '6113')
    AND (ownercode = 'A00') THEN sep END) THEN SUM(CASE WHEN (geography = '17') AND (sex = '0') AND (agegrp = 'A00') AND (industry
    = '6113') AND (ownercode = 'A00') THEN sep END) END
  comment: 'Census QWI Sep, summed over quarters; NULL if any quarter is not yet published (latest quarter lags). Unit: separations.
    Grain rule: Flow; additive over quarters.'
  synonyms:
  - separations
  - exits
  - departures
- name: qwi_avg_monthly_earnings
  expr: CAST(SUM(CASE WHEN (geography = '17') AND (sex = '0') AND (agegrp = 'A00') AND (industry = '6113') AND (ownercode
    = 'A00') THEN earns * emp_s END) AS DOUBLE) / NULLIF(SUM(CASE WHEN (geography = '17') AND (sex = '0') AND (agegrp = 'A00')
    AND (industry = '6113') AND (ownercode = 'A00') THEN CASE WHEN earns IS NOT NULL THEN emp_s END END), 0)
  comment: 'EarnS weighted by EmpS over the requested grain (quarters without published earnings excluded from both sides).
    Unit: USD per month. Grain rule: Employment-weighted ratio; never average the published averages.'
  synonyms:
  - average monthly earnings
  - monthly earnings
  - earnings
$$;

CREATE OR REPLACE VIEW hr_analytics.hr_public.onet_occupation_metrics
WITH METRICS
LANGUAGE YAML
AS $$
version: '1.1'
comment: 'O*NET 31.0 occupations. Grain: one row per O*NET-SOC occupation. Generated from hr_public.yaml sha256 102bec2ac50cb4a9;
  status development.'
source: hr_analytics.hr_public.onet_occupation
dimensions:
- name: occupation_title
  expr: title
  comment: O*NET occupation title.
  synonyms:
  - occupation
  - occupations
  - occupation title
- name: occupation_code
  expr: onetsoc_code
  comment: O*NET-SOC code.
  synonyms:
  - onet code
  - soc code
  - occupation code
measures:
- name: occupation_count
  expr: COUNT(DISTINCT onetsoc_code)
  comment: 'Distinct O*NET-SOC occupations. Unit: occupations. Grain rule: Count distinct; not additive across groupings.'
  synonyms:
  - occupation count
  - number of occupations
  - onet occupations
  - o*net occupations
$$;

CREATE OR REPLACE VIEW hr_analytics.hr_public.onet_task_metrics
WITH METRICS
LANGUAGE YAML
AS $$
version: '1.1'
comment: 'O*NET task statements. Grain: one row per onetsoc_code x task_id. Generated from hr_public.yaml sha256 102bec2ac50cb4a9;
  status development.'
source: hr_analytics.hr_public.onet_task_statement
joins:
- name: onet_occupation
  source: hr_analytics.hr_public.onet_occupation
  'on': source.onetsoc_code = onet_occupation.onetsoc_code
dimensions:
- name: task_type
  expr: task_type
  comment: Core, Supplemental or n/a.
  synonyms:
  - task type
- name: occupation_title
  expr: onet_occupation.title
  comment: O*NET occupation title.
  synonyms:
  - occupation
  - occupations
  - occupation title
- name: occupation_code
  expr: onet_occupation.onetsoc_code
  comment: O*NET-SOC code.
  synonyms:
  - onet code
  - soc code
  - occupation code
measures:
- name: task_statement_count
  expr: COUNT(*)
  comment: 'Number of task statements (rows). Unit: task statements. Grain rule: Additive across occupations.'
  synonyms:
  - task count
  - task statements
  - number of tasks
  - tasks
- name: core_task_count
  expr: COUNT(CASE WHEN (task_type = 'Core') THEN 1 END)
  comment: 'Task statements typed Core. Unit: task statements. Grain rule: Additive; metric-level filter task_type = ''Core''.'
  synonyms:
  - core tasks
  - core task count
  - number of core tasks
$$;

CREATE OR REPLACE VIEW hr_analytics.hr_public.aei_task_usage_metrics
WITH METRICS
LANGUAGE YAML
AS $$
version: '1.1'
comment: 'Anthropic Economic Index task usage percentage by release (lower-cased O*NET task text). Grain: one row per task_name
  x release. Generated from hr_public.yaml sha256 102bec2ac50cb4a9; status development.'
source: hr_analytics.hr_public.aei_task_usage
dimensions:
- name: release
  expr: release
  comment: AEI data release label.
  synonyms:
  - release
  - releases
measures:
- name: ai_task_usage_pct
  expr: SUM(usage_pct)
  comment: 'Sum of AEI usage percentages for tasks within ONE release. Usage is not automation, displacement or obsolescence.
    Unit: percent of AEI conversations. Grain rule: Additive across tasks within a release only; cannot be sliced by occupation
    (task-text join fans out).'
  synonyms:
  - ai usage share
  - ai usage percentage
  - ai task usage
  - ai usage
  - economic index usage
$$;

CREATE OR REPLACE VIEW hr_analytics.hr_public.sucss_class_metrics
WITH METRICS
LANGUAGE YAML
AS $$
version: '1.1'
comment: 'Illinois SUCSS civil-service class catalog records (not employees, not vacancies). Grain: one row per source class
  record (a class code can have several records). Generated from hr_public.yaml sha256 102bec2ac50cb4a9; status development.'
source: hr_analytics.hr_public.sucss_class
dimensions: []
measures:
- name: sucss_class_record_count
  expr: COUNT(*)
  comment: 'Catalog records. A class code can have several records (e.g. 1164); records are not employees or vacancies. Unit:
    catalog records. Grain rule: Count rows.'
  synonyms:
  - class records
  - sucss class records
  - civil service class records
  - catalog records
- name: sucss_class_code_count
  expr: COUNT(DISTINCT class_code)
  comment: 'Distinct civil-service class codes. Unit: class codes. Grain rule: Count distinct; differs from record count where
    a code has multiple records.'
  synonyms:
  - civil service classes
  - sucss classes
  - class codes
  - civil service class codes
  - number of classes
$$;
