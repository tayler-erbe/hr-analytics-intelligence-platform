-- Generated from hr_public.yaml (sha256 102bec2ac50cb4a9) by custom_stack.semantic.compile_snowflake
-- NOT executed against Snowflake from this repository; validate before use.
USE SCHEMA HR_ANALYTICS.HR_PUBLIC;

-- logical entity qcew: SQL emitted verbatim (DuckDB-tested); review dialect
CREATE OR REPLACE VIEW HR_ANALYTICS.HR_PUBLIC.QCEW_COMBINED AS
SELECT area_fips, own_code, industry_code, year, qtr, disclosure_code,
       month1_emplvl, month2_emplvl, month3_emplvl, total_qtrly_wages, source_id, source_vintage
FROM qcew_industry
UNION ALL
SELECT area_fips, own_code, industry_code, year, qtr, disclosure_code,
       month1_emplvl, month2_emplvl, month3_emplvl, total_qtrly_wages, source_id, source_vintage
FROM qcew_area
WHERE industry_code <> '611310';

CREATE OR REPLACE SEMANTIC VIEW HR_ANALYTICS.HR_PUBLIC.HR_PUBLIC_METRICS
  TABLES (
    institution AS HR_ANALYTICS.HR_PUBLIC.IPEDS_INSTITUTION
      PRIMARY KEY (unitid)
      COMMENT = 'IPEDS institutional characteristics (HD2024). Grain: one row per IPEDS institution (unitid).',
    staff_eap AS HR_ANALYTICS.HR_PUBLIC.IPEDS_EMPLOYEES_BY_POSITION
      PRIMARY KEY (unitid, survey_year, eapcat_code) WITH SYNONYMS = ('eap', 'ipeds eap', 'employees by assigned position')
      COMMENT = 'IPEDS Employees by Assigned Position (EAP), Fall snapshot. Includes total, subtotal and faculty-status rows (is_category_total = true) alongside the partition rows. Grain: one row per unitid x survey_year x eapcat_code (occupation category x faculty status).',
    salary_instructional AS HR_ANALYTICS.HR_PUBLIC.IPEDS_SALARY_INSTRUCTIONAL
      PRIMARY KEY (unitid, survey_year, arank_code, contract_length) WITH SYNONYMS = ('sal_is', 'ipeds salary survey')
      COMMENT = 'IPEDS SAL_IS full-time instructional staff salary outlays by rank and contract length. Grain: one row per unitid x survey_year x arank_code x contract_length.',
    salary_noninstructional AS HR_ANALYTICS.HR_PUBLIC.IPEDS_SALARY_NONINSTRUCTIONAL
      PRIMARY KEY (unitid, survey_year, occupation_category_code) WITH SYNONYMS = ('sal_nis')
      COMMENT = 'IPEDS SAL_NIS full-time non-instructional staff salary outlays (13 categories that partition staff). Grain: one row per unitid x survey_year x occupation_category_code.',
    enrollment AS HR_ANALYTICS.HR_PUBLIC.IPEDS_ENROLLMENT_12MO
      PRIMARY KEY (unitid, survey_year, level_code) WITH SYNONYMS = ('effy')
      COMMENT = 'IPEDS EFFY 12-month unduplicated enrollment by student level (levels nest). Grain: one row per unitid x survey_year x level_code.',
    qcew AS HR_ANALYTICS.HR_PUBLIC.QCEW_COMBINED
      PRIMARY KEY (area_fips, own_code, industry_code, year, qtr) WITH SYNONYMS = ('qcew', 'bls qcew', 'quarterly census of employment and wages')
      COMMENT = 'BLS QCEW. Union of the national/state/county NAICS 611310 file and the IL county all-industry file, excluding industry_code ''611310'' from the county file (those rows duplicate the industry file; lake contract rule 7). Grain: one row per area_fips x own_code x industry_code x year x qtr.',
    qwi AS HR_ANALYTICS.HR_PUBLIC.QWI_HIGHER_ED
      PRIMARY KEY (geography, industry, ownercode, year, quarter, sex, agegrp) WITH SYNONYMS = ('qwi', 'census qwi', 'quarterly workforce indicators')
      COMMENT = 'Census QWI, Illinois, NAICS 6113, by sex x age group (published totals sex 0 / agegrp A00). Grain: one row per geography x industry x ownercode x year x quarter x sex x agegrp.',
    onet_occupation AS HR_ANALYTICS.HR_PUBLIC.ONET_OCCUPATION
      PRIMARY KEY (onetsoc_code) WITH SYNONYMS = ('o*net', 'onet')
      COMMENT = 'O*NET 31.0 occupations. Grain: one row per O*NET-SOC occupation.',
    onet_task AS HR_ANALYTICS.HR_PUBLIC.ONET_TASK_STATEMENT
      PRIMARY KEY (onetsoc_code, task_id)
      COMMENT = 'O*NET task statements. Grain: one row per onetsoc_code x task_id.',
    aei_task_usage AS HR_ANALYTICS.HR_PUBLIC.AEI_TASK_USAGE
      PRIMARY KEY (task_name, release) WITH SYNONYMS = ('aei', 'anthropic economic index', 'economic index')
      COMMENT = 'Anthropic Economic Index task usage percentage by release (lower-cased O*NET task text). Grain: one row per task_name x release.',
    sucss_class AS HR_ANALYTICS.HR_PUBLIC.SUCSS_CLASS
      PRIMARY KEY (source_record_id) WITH SYNONYMS = ('sucss')
      COMMENT = 'Illinois SUCSS civil-service class catalog records (not employees, not vacancies). Grain: one row per source class record (a class code can have several records).'
  )
  RELATIONSHIPS (
    eap_institution AS staff_eap (unitid) REFERENCES institution (unitid),
    sal_is_institution AS salary_instructional (unitid) REFERENCES institution (unitid),
    sal_nis_institution AS salary_noninstructional (unitid) REFERENCES institution (unitid),
    enrollment_institution AS enrollment (unitid) REFERENCES institution (unitid),
    task_occupation AS onet_task (onetsoc_code) REFERENCES onet_occupation (onetsoc_code)
  )
  DIMENSIONS (
    institution.institution_name AS institution.institution_name WITH SYNONYMS = ('institution', 'institutions', 'college', 'colleges', 'university', 'universities', 'school', 'schools', 'campus', 'campuses')
      COMMENT = 'Institution name as published in IPEDS HD. Values: University of Illinois Urbana-Champaign = uiuc, university of illinois urbana-champaign, urbana-champaign, illinois urbana-champaign; University of Illinois Chicago = uic, university of illinois chicago; University of Illinois Springfield = uis, university of illinois springfield',
    institution.state AS institution.state_abbr WITH SYNONYMS = ('state', 'states')
      COMMENT = 'Institution state (postal abbreviation). Values: IL = illinois; IN = indiana; WI = wisconsin; MI = michigan; IA = iowa; MO = missouri',
    institution.sector AS institution.sector_code WITH SYNONYMS = ('sector', 'sectors', 'control', 'institution type')
      COMMENT = 'IPEDS sector code (1 public 4-year+, 2 private nonprofit 4-year+, 3 private for-profit 4-year+, 4 public 2-year ...). Values: 1 = public four-year, public 4-year, public 4 year, public universities, public university; 2 = private nonprofit four-year, private nonprofit 4-year, private nonprofit, private not-for-profit; 3 = private for-profit four-year, for-profit, for profit; 4 = public two-year, public 2-year, community college, community colleges',
    institution.carnegie AS institution.carnegie WITH SYNONYMS = ('carnegie classification', 'carnegie class', 'carnegie')
      COMMENT = 'Carnegie classification label as loaded (HD2024).',
    staff_eap.survey_year AS staff_eap.survey_year WITH SYNONYMS = ('survey year')
      COMMENT = 'IPEDS EAP survey year = Fall snapshot year (EAP2023 = Fall 2023).',
    staff_eap.unitid AS staff_eap.unitid WITH SYNONYMS = ('unitid', 'unit id')
      COMMENT = 'IPEDS unit id (also used to align populations in derived ratios).',
    staff_eap.position_category AS staff_eap.position_category WITH SYNONYMS = ('position category', 'position categories', 'occupation category', 'occupational category', 'job category', 'job categories')
      COMMENT = 'EAP position category. Non-total rows (is_category_total = false) partition the institution total exactly (lake contract rule 4), so grouped rows are additive. Values: Instructional staff, total = instructional staff, instructional; Management = management, managers; Computer, Engineering, and Science = computer engineering and science, it staff, computing staff; Research = research staff; Office and Administrative Support = office and administrative support, administrative support',
    staff_eap.category_total_row AS staff_eap.is_category_total WITH SYNONYMS = ('category total row')
      COMMENT = 'TRUE for published total / subtotal / faculty-status rows; FALSE rows form the exact partition.',
    salary_instructional.survey_year AS salary_instructional.survey_year WITH SYNONYMS = ('survey year')
      COMMENT = 'IPEDS salary survey year (SAL2023 = academic year 2023-24).',
    salary_instructional.academic_rank AS salary_instructional.academic_rank WITH SYNONYMS = ('rank', 'ranks', 'academic rank', 'faculty rank')
      COMMENT = 'Academic rank (no published all-ranks row; ranks partition staff). Values: Professor = full professor, full professors, professors; Associate professor = associate professor, associate professors; Assistant professor = assistant professor, assistant professors; Instructor = instructor, instructors; Lecturer = lecturer, lecturers',
    salary_instructional.contract_length AS salary_instructional.contract_length WITH SYNONYMS = ('contract length', 'contract')
      COMMENT = 'Contract length (9-, 10-, 11-, 12-month). Partitions staff; salaries are not comparable across lengths. Values: 9-month = 9-month, nine-month, 9-month contracts; 12-month = 12-month, twelve-month, 12-month contracts',
    salary_noninstructional.survey_year AS salary_noninstructional.survey_year WITH SYNONYMS = ('survey year')
      COMMENT = 'IPEDS salary survey year (SAL2023 = 2023-24).',
    salary_noninstructional.occupation_category AS salary_noninstructional.occupation_category WITH SYNONYMS = ('occupation category', 'occupation categories', 'staff category', 'staff categories')
      COMMENT = 'Non-instructional occupation category (partition; no total row). Values: Management = management staff; Computer, engineering and science = computer engineering and science staff, it staff',
    enrollment.survey_year AS enrollment.survey_year - 1 WITH SYNONYMS = ('survey year')
      COMMENT = 'ALIGNED fall-year label. EFFY N covers academic year (N-1)-(N), so EFFY2024 (2023-24) is labelled 2023 to align with the EAP Fall 2023 snapshot.',
    enrollment.unitid AS enrollment.unitid WITH SYNONYMS = ('unitid', 'unit id')
      COMMENT = 'IPEDS unit id.',
    enrollment.effy_year AS enrollment.survey_year WITH SYNONYMS = ('effy year')
      COMMENT = 'Raw EFFY survey year as published (EFFY2024 = 2023-24).',
    enrollment.student_level AS enrollment.level_code WITH SYNONYMS = ('student level', 'level', 'levels')
      COMMENT = 'EFFY student level code (1 all students, 2 undergraduate, 12 graduate). Levels nest. Values: 2 = undergraduate, undergraduates, undergraduate students; 12 = graduate, graduate students',
    qcew.year AS qcew.year WITH SYNONYMS = ('calendar year')
      COMMENT = 'Calendar year.',
    qcew.quarter AS qcew.qtr WITH SYNONYMS = ('calendar quarter')
      COMMENT = 'Calendar quarter 1-4.',
    qcew.area AS qcew.area_fips WITH SYNONYMS = ('area', 'areas', 'county', 'counties', 'geography')
      COMMENT = 'QCEW area FIPS (US000 national, 17000 Illinois statewide, 5-digit counties). Values: US000 = united states, national, nationwide, u.s.; 17000 = illinois, illinois statewide, statewide; 17019 = champaign county, champaign; 17031 = cook county, cook; 17167 = sangamon county, sangamon',
    qcew.ownership AS qcew.own_code WITH SYNONYMS = ('ownership', 'owner', 'public or private')
      COMMENT = 'QCEW ownership code (0 total covered, 1 federal, 2 state, 3 local, 5 private). Values: 1 = federal government, federal; 2 = state government, state-owned, state owned; 3 = local government; 5 = private, private sector',
    qcew.industry AS qcew.industry_code WITH SYNONYMS = ('industry', 'industries', 'naics')
      COMMENT = 'NAICS industry code (nested levels in the county file). Values: 611310 = colleges and universities, colleges universities and professional schools, higher education, naics 611310; 10 = all industries, total all industries',
    qwi.year AS qwi.year WITH SYNONYMS = ('calendar year')
      COMMENT = 'Calendar year.',
    qwi.quarter AS qwi.quarter WITH SYNONYMS = ('calendar quarter')
      COMMENT = 'Calendar quarter 1-4.',
    qwi.geography AS qwi.geography WITH SYNONYMS = ('geography')
      COMMENT = 'QWI geography (2-digit state FIPS; counties if loaded). Values: 17 = illinois, illinois statewide, statewide',
    qwi.industry AS qwi.industry WITH SYNONYMS = ('industry', 'naics')
      COMMENT = 'NAICS industry code. Values: 6113 = colleges and universities, higher education, naics 6113',
    qwi.ownership AS qwi.ownercode WITH SYNONYMS = ('ownership')
      COMMENT = 'QWI ownership code (A00 all).',
    qwi.sex AS qwi.sex WITH SYNONYMS = ('sex', 'gender')
      COMMENT = 'QWI sex code (0 all, 1 male, 2 female). Values: 1 = male, men; 2 = female, women',
    qwi.age_group AS qwi.agegrp WITH SYNONYMS = ('age group', 'age groups', 'age')
      COMMENT = 'QWI age group (A00 all ages, A01 14-18 ... A08 65-99).',
    onet_occupation.occupation_title AS onet_occupation.title WITH SYNONYMS = ('occupation', 'occupations', 'occupation title')
      COMMENT = 'O*NET occupation title. Values: Database Administrators = database administrators, database administrator; Postsecondary Teachers, All Other = postsecondary teachers',
    onet_occupation.occupation_code AS onet_occupation.onetsoc_code WITH SYNONYMS = ('onet code', 'soc code', 'occupation code')
      COMMENT = 'O*NET-SOC code.',
    onet_task.task_type AS onet_task.task_type WITH SYNONYMS = ('task type')
      COMMENT = 'Core, Supplemental or n/a. Values: Core = core; Supplemental = supplemental',
    aei_task_usage.release AS aei_task_usage.release WITH SYNONYMS = ('release', 'releases')
      COMMENT = 'AEI data release label. Values: release_2025_03_27 = march 2025 release, 2025-03-27 release, 2025-03-27, release 2025-03-27; labor_market_impacts = labor market impacts release, labor market impacts'
  )
  METRICS (
    staff_eap.staff_headcount AS CASE WHEN COUNT(DISTINCT staff_eap.survey_year) <= 1 THEN SUM(CASE WHEN (staff_eap.is_category_total = FALSE) THEN staff_eap.total_employees END) END WITH SYNONYMS = ('staff headcount', 'headcount', 'employees', 'employee headcount', 'staff count', 'number of staff', 'number of employees', 'staff', 'workforce', 'employee count')
      COMMENT = 'Full-time plus part-time employees reported in IPEDS EAP for one Fall snapshot. Unit: people. Grain rule: Snapshot stock. One survey year at a time. Sums only is_category_total = false rows (exact partition of the institution total); never adds total/subtotal rows. Folded rules: category_total_row: pinned to ''false''; returns NULL when more than one period is aggregated.',
    staff_eap.full_time_staff_headcount AS CASE WHEN COUNT(DISTINCT staff_eap.survey_year) <= 1 THEN SUM(CASE WHEN (staff_eap.is_category_total = FALSE) THEN staff_eap.full_time END) END WITH SYNONYMS = ('full-time staff', 'full time staff', 'full-time employees', 'full time employees', 'full-time headcount', 'full-time staff headcount', 'full time staff headcount')
      COMMENT = 'Full-time employees reported in IPEDS EAP for one Fall snapshot. Unit: people. Grain rule: Snapshot stock; one survey year at a time; same category rules as staff_headcount. Folded rules: category_total_row: pinned to ''false''; returns NULL when more than one period is aggregated.',
    staff_eap.staff_fte AS CASE WHEN COUNT(DISTINCT staff_eap.survey_year) <= 1 THEN SUM(CASE WHEN (staff_eap.is_category_total = FALSE) THEN staff_eap.full_time + staff_eap.part_time / 3.0 END) END WITH SYNONYMS = ('staff fte', 'fte', 'full-time equivalent', 'full time equivalent', 'fte staff', 'full-time equivalent staff')
      COMMENT = 'IPEDS FTE convention = full-time + one third of part-time. Not payroll FTE. Unit: FTE. Grain rule: Snapshot stock; FTE is not headcount. One survey year at a time. Folded rules: category_total_row: pinned to ''false''; returns NULL when more than one period is aggregated.',
    salary_instructional.instructional_staff_count AS CASE WHEN COUNT(DISTINCT salary_instructional.survey_year) <= 1 THEN SUM(salary_instructional.staff_count) END WITH SYNONYMS = ('faculty count', 'number of faculty', 'instructional staff count', 'full-time faculty')
      COMMENT = 'Full-time instructional staff counted in the salary survey, all contract lengths (differs from EAP instructional headcount). Unit: people. Grain rule: Snapshot stock; ranks and contract lengths partition staff and are additive. Folded rules: returns NULL when more than one period is aggregated.',
    salary_instructional.avg_instructional_salary AS CAST(SUM(CASE WHEN (salary_instructional.contract_length = '9-month') THEN salary_instructional.salary_outlays END) AS DOUBLE) / NULLIF(SUM(CASE WHEN (salary_instructional.contract_length = '9-month') THEN salary_instructional.staff_count END), 0) WITH SYNONYMS = ('average faculty salary', 'average instructional salary', 'faculty salary', 'faculty salaries', 'mean faculty salary', 'instructional salary')
      COMMENT = 'Salary outlays divided by full-time instructional staff at the requested grain; 9-month contracts unless another contract length is requested. Unit: USD per person. Grain rule: Ratio of sums. Never average institution averages, never mix contract lengths, never sum salaries across a join fan-out. Folded rules: contract_length: pinned to ''9-month''.',
    salary_noninstructional.avg_noninstructional_salary AS CAST(SUM(salary_noninstructional.salary_outlays) AS DOUBLE) / NULLIF(SUM(salary_noninstructional.staff_count), 0) WITH SYNONYMS = ('average staff salary', 'average non-instructional salary', 'average noninstructional salary', 'non-instructional salary', 'staff salary')
      COMMENT = 'Non-instructional salary outlays divided by full-time non-instructional staff. Unit: USD per person. Grain rule: Ratio of sums at the requested grain. Folded rules: none.',
    salary_noninstructional.noninstructional_salary_outlays AS SUM(salary_noninstructional.salary_outlays) WITH SYNONYMS = ('salary outlays', 'non-instructional salary outlays', 'staff payroll', 'payroll')
      COMMENT = 'Total salary outlays for full-time non-instructional staff. Unit: USD. Grain rule: Additive across institutions and the 13 categories (they partition staff). Folded rules: none.',
    enrollment.enrollment_12mo AS CASE WHEN COUNT(DISTINCT enrollment.survey_year - 1) <= 1 THEN SUM(CASE WHEN (enrollment.level_code = '1') THEN enrollment.enrollment_total END) END WITH SYNONYMS = ('enrollment', 'enrolment', 'students', 'student headcount', '12-month enrollment', 'unduplicated enrollment')
      COMMENT = 'IPEDS EFFY unduplicated headcount for the 12-month period, all students unless a level is requested. Unit: students. Grain rule: Do not sum across years (students recur) or across nested levels. Folded rules: student_level: only published total row ''1'' counted; returns NULL when more than one period is aggregated.',
    staff_fte_per_100_students AS staff_eap.staff_fte * 100.0 / NULLIF(enrollment.enrollment_12mo, 0) WITH SYNONYMS = ('staff per 100 students', 'staff fte per 100 students', 'staff to student ratio', 'staffing ratio')
      COMMENT = 'EAP staff FTE (Fall N) divided by EFFY 12-month enrollment for academic year N to N+1, each aggregated separately then joined on the aligned year. Grain rule: Components aggregate separately per institution (no row-level join between EAP and EFFY rows), then only institutions reporting BOTH are summed, so staff of institutions without enrollment never inflate the ratio.',
    qcew.qcew_employment AS CAST(CASE WHEN COUNT(CASE WHEN (qcew.own_code <> '0') AND (qcew.industry_code = '611310') THEN 1 END) = COUNT(CASE WHEN (qcew.own_code <> '0') AND (qcew.industry_code = '611310') THEN (qcew.month1_emplvl + qcew.month2_emplvl + qcew.month3_emplvl) / 3.0 END) THEN SUM(CASE WHEN (qcew.own_code <> '0') AND (qcew.industry_code = '611310') THEN (qcew.month1_emplvl + qcew.month2_emplvl + qcew.month3_emplvl) / 3.0 END) END AS DOUBLE) / NULLIF(COUNT(DISTINCT CONCAT(CAST(qcew.year AS STRING), '-', CAST(qcew.qtr AS STRING))), 0) WITH SYNONYMS = ('qcew employment', 'covered employment', 'jobs', 'employment', 'employees', 'employment level')
      COMMENT = 'Covered employment, average of the three monthly levels; averaged over quarters for a year. Returns NULL when any contributing cell is disclosure-suppressed. Unit: jobs. Grain rule: Stock. Sum across ownership members within one area; average (not sum) over quarters. Area must be chosen. Suppressed cells propagate as NULL instead of silently understating. Folded rules: ownership: total row ''0'' never counted; industry: pinned to ''611310''; NULL (suppressed) inputs propagate to a NULL result; stock averaged across periods: SUM / COUNT(DISTINCT period).',
    qcew.qcew_total_wages AS CASE WHEN COUNT(CASE WHEN (qcew.own_code <> '0') AND (qcew.industry_code = '611310') THEN 1 END) = COUNT(CASE WHEN (qcew.own_code <> '0') AND (qcew.industry_code = '611310') THEN qcew.total_qtrly_wages END) THEN SUM(CASE WHEN (qcew.own_code <> '0') AND (qcew.industry_code = '611310') THEN qcew.total_qtrly_wages END) END WITH SYNONYMS = ('total wages', 'qcew wages', 'wages paid', 'quarterly wages')
      COMMENT = 'Total covered quarterly wages, additive over quarters. NULL when any contributing cell is suppressed. Unit: USD. Grain rule: Flow. Sum over quarters and ownership members within one area; suppressed cells propagate as NULL. Folded rules: ownership: total row ''0'' never counted; industry: pinned to ''611310''; NULL (suppressed) inputs propagate to a NULL result.',
    qwi.qwi_employment AS CAST(CASE WHEN COUNT(CASE WHEN (qwi.geography = '17') AND (qwi.sex = '0') AND (qwi.agegrp = 'A00') AND (qwi.industry = '6113') AND (qwi.ownercode = 'A00') THEN 1 END) = COUNT(CASE WHEN (qwi.geography = '17') AND (qwi.sex = '0') AND (qwi.agegrp = 'A00') AND (qwi.industry = '6113') AND (qwi.ownercode = 'A00') THEN qwi.emp END) THEN SUM(CASE WHEN (qwi.geography = '17') AND (qwi.sex = '0') AND (qwi.agegrp = 'A00') AND (qwi.industry = '6113') AND (qwi.ownercode = 'A00') THEN qwi.emp END) END AS DOUBLE) / NULLIF(COUNT(DISTINCT CONCAT(CAST(qwi.year AS STRING), '-', CAST(qwi.quarter AS STRING))), 0) WITH SYNONYMS = ('qwi employment', 'beginning of quarter employment', 'employment', 'employees', 'jobs')
      COMMENT = 'Census QWI Emp (beginning-of-quarter jobs); averaged over quarters. Unit: jobs. Grain rule: Stock; average over quarters; all-sex/all-age row by default. Folded rules: geography: pinned to ''17''; sex: only published total row ''0'' counted; age_group: only published total row ''A00'' counted; industry: pinned to ''6113''; ownership: pinned to ''A00''; NULL (suppressed) inputs propagate to a NULL result; stock averaged across periods: SUM / COUNT(DISTINCT period).',
    qwi.qwi_hires AS CASE WHEN COUNT(CASE WHEN (qwi.geography = '17') AND (qwi.sex = '0') AND (qwi.agegrp = 'A00') AND (qwi.industry = '6113') AND (qwi.ownercode = 'A00') THEN 1 END) = COUNT(CASE WHEN (qwi.geography = '17') AND (qwi.sex = '0') AND (qwi.agegrp = 'A00') AND (qwi.industry = '6113') AND (qwi.ownercode = 'A00') THEN qwi.hira END) THEN SUM(CASE WHEN (qwi.geography = '17') AND (qwi.sex = '0') AND (qwi.agegrp = 'A00') AND (qwi.industry = '6113') AND (qwi.ownercode = 'A00') THEN qwi.hira END) END WITH SYNONYMS = ('hires', 'hiring', 'new hires', 'all hires')
      COMMENT = 'Census QWI HirA, summed over quarters; NULL if any quarter is not yet published. Unit: hires. Grain rule: Flow; additive over quarters. Folded rules: geography: pinned to ''17''; sex: only published total row ''0'' counted; age_group: only published total row ''A00'' counted; industry: pinned to ''6113''; ownership: pinned to ''A00''; NULL (suppressed) inputs propagate to a NULL result.',
    qwi.qwi_separations AS CASE WHEN COUNT(CASE WHEN (qwi.geography = '17') AND (qwi.sex = '0') AND (qwi.agegrp = 'A00') AND (qwi.industry = '6113') AND (qwi.ownercode = 'A00') THEN 1 END) = COUNT(CASE WHEN (qwi.geography = '17') AND (qwi.sex = '0') AND (qwi.agegrp = 'A00') AND (qwi.industry = '6113') AND (qwi.ownercode = 'A00') THEN qwi.sep END) THEN SUM(CASE WHEN (qwi.geography = '17') AND (qwi.sex = '0') AND (qwi.agegrp = 'A00') AND (qwi.industry = '6113') AND (qwi.ownercode = 'A00') THEN qwi.sep END) END WITH SYNONYMS = ('separations', 'exits', 'departures')
      COMMENT = 'Census QWI Sep, summed over quarters; NULL if any quarter is not yet published (latest quarter lags). Unit: separations. Grain rule: Flow; additive over quarters. Folded rules: geography: pinned to ''17''; sex: only published total row ''0'' counted; age_group: only published total row ''A00'' counted; industry: pinned to ''6113''; ownership: pinned to ''A00''; NULL (suppressed) inputs propagate to a NULL result.',
    qwi.qwi_avg_monthly_earnings AS CAST(SUM(CASE WHEN (qwi.geography = '17') AND (qwi.sex = '0') AND (qwi.agegrp = 'A00') AND (qwi.industry = '6113') AND (qwi.ownercode = 'A00') THEN qwi.earns * qwi.emp_s END) AS DOUBLE) / NULLIF(SUM(CASE WHEN (qwi.geography = '17') AND (qwi.sex = '0') AND (qwi.agegrp = 'A00') AND (qwi.industry = '6113') AND (qwi.ownercode = 'A00') THEN CASE WHEN qwi.earns IS NOT NULL THEN qwi.emp_s END END), 0) WITH SYNONYMS = ('average monthly earnings', 'monthly earnings', 'earnings')
      COMMENT = 'EarnS weighted by EmpS over the requested grain (quarters without published earnings excluded from both sides). Unit: USD per month. Grain rule: Employment-weighted ratio; never average the published averages. Folded rules: geography: pinned to ''17''; sex: only published total row ''0'' counted; age_group: only published total row ''A00'' counted; industry: pinned to ''6113''; ownership: pinned to ''A00''.',
    onet_occupation.occupation_count AS COUNT(DISTINCT onet_occupation.onetsoc_code) WITH SYNONYMS = ('occupation count', 'number of occupations', 'onet occupations', 'o*net occupations')
      COMMENT = 'Distinct O*NET-SOC occupations. Unit: occupations. Grain rule: Count distinct; not additive across groupings. Folded rules: none.',
    onet_task.task_statement_count AS COUNT(*) WITH SYNONYMS = ('task count', 'task statements', 'number of tasks', 'tasks')
      COMMENT = 'Number of task statements (rows). Unit: task statements. Grain rule: Additive across occupations. Folded rules: none.',
    onet_task.core_task_count AS COUNT(CASE WHEN (onet_task.task_type = 'Core') THEN 1 END) WITH SYNONYMS = ('core tasks', 'core task count', 'number of core tasks')
      COMMENT = 'Task statements typed Core. Unit: task statements. Grain rule: Additive; metric-level filter task_type = ''Core''. Folded rules: metric filter task_type = ''Core''.',
    aei_task_usage.ai_task_usage_pct AS SUM(aei_task_usage.usage_pct) WITH SYNONYMS = ('ai usage share', 'ai usage percentage', 'ai task usage', 'ai usage', 'economic index usage')
      COMMENT = 'Sum of AEI usage percentages for tasks within ONE release. Usage is not automation, displacement or obsolescence. Unit: percent of AEI conversations. Grain rule: Additive across tasks within a release only; cannot be sliced by occupation (task-text join fans out). Folded rules: none.',
    sucss_class.sucss_class_record_count AS COUNT(*) WITH SYNONYMS = ('class records', 'sucss class records', 'civil service class records', 'catalog records')
      COMMENT = 'Catalog records. A class code can have several records (e.g. 1164); records are not employees or vacancies. Unit: catalog records. Grain rule: Count rows. Folded rules: none.',
    sucss_class.sucss_class_code_count AS COUNT(DISTINCT sucss_class.class_code) WITH SYNONYMS = ('civil service classes', 'sucss classes', 'class codes', 'civil service class codes', 'number of classes')
      COMMENT = 'Distinct civil-service class codes. Unit: class codes. Grain rule: Count distinct; differs from record count where a code has multiple records. Folded rules: none.'
  )
  COMMENT = 'Governed metrics over public IPEDS, BLS QCEW, Census QWI, O*NET, SUCSS and Anthropic Economic Index tables. Every metric declares its grain, its additivity and the rows it must never double count. Status: development';
