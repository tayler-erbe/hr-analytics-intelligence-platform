# Data dictionary (wap_prototype Phase 1)

Run: source v3_longitudinal, date column JOB_DETL_EFF_DT, snapshots Q, k = 10. Synthetic data (v3 Cookbook pack). Restricted tables stay in outputs/restricted/ and never leave the machine.

## unit_quarter_aggregates  (outputs/)

| Column | Type | Description |
|---|---|---|
| quarter_end | DATE | last day of the calendar quarter (snapshot date) |
| campus_org_code | VARCHAR | campus-level org (child of the org root; synthetic campus assignment) |
| college_org_code | VARCHAR | level-3 (college) ancestor org |
| dept_org_code | VARCHAR | level-5 (department) ancestor org |
| role_family | VARCHAR | role family of the class key (role_family_source says which rule assigned it) |
| headcount | BIGINT | distinct people with an active appointment at the period end (NULL when suppressed) |
| fte | DOUBLE | sum of FTE of the people counted (NULL when suppressed) |
| hires | BIGINT | hire + rehire events in the period (NULL when suppressed or 0 < n < k) |
| separations | BIGINT | separation_* + retirement events in the period |
| retirements | BIGINT | retirement events in the period |
| promotions | BIGINT | candidate promotion events in the period |
| transfers | BIGINT | transfer_lateral + transfer_down events in the period |
| any_suppressed | BOOLEAN | TRUE when any measure in the row is suppressed |
| suppression_reason | VARCHAR | headcount_below_k | complementary | small_count |
| min_cell_size | INTEGER | k used for suppression |

## unit_year_aggregates  (outputs/)

| Column | Type | Description |
|---|---|---|
| year | BIGINT | calendar year |
| campus_org_code | VARCHAR | campus-level org (child of the org root; synthetic campus assignment) |
| role_family | VARCHAR | role family of the class key (role_family_source says which rule assigned it) |
| headcount | BIGINT | distinct people with an active appointment at the period end (NULL when suppressed) |
| fte | DOUBLE | sum of FTE of the people counted (NULL when suppressed) |
| hires | BIGINT | hire + rehire events in the period (NULL when suppressed or 0 < n < k) |
| separations | BIGINT | separation_* + retirement events in the period |
| retirements | BIGINT | retirement events in the period |
| promotions | BIGINT | candidate promotion events in the period |
| transfers | BIGINT | transfer_lateral + transfer_down events in the period |
| any_suppressed | BOOLEAN | TRUE when any measure in the row is suppressed |
| suppression_reason | VARCHAR | headcount_below_k | complementary | small_count |
| min_cell_size | INTEGER | k used for suppression |

## transition_counts  (outputs/)

| Column | Type | Description |
|---|---|---|
| year | BIGINT | calendar year |
| campus_org_code | VARCHAR | campus-level org (child of the org root; synthetic campus assignment) |
| role_family | VARCHAR | role family of the class key (role_family_source says which rule assigned it) |
| event_type | VARCHAR | see transitions.py docstring; promotion/transfer/reclassification are candidate labels |
| n_events | BIGINT | count of events; NULL when 0 < n < k |
| suppressed | BOOLEAN | cell suppressed (headcount below k, complementary, or small count) |
| min_cell_size | INTEGER | k used for suppression |

## feature_summary  (outputs/)

| Column | Type | Description |
|---|---|---|
| snap_date | DATE | snapshot date t; features use only rows effective <= t and known at t |
| campus_org_code | VARCHAR | campus-level org (child of the org root; synthetic campus assignment) |
| role_family | VARCHAR | role family of the class key (role_family_source says which rule assigned it) |
| n_persons | BIGINT | people in the cell (always shown; measures NULL below k) |
| mean_tenure_years | DOUBLE |  |
| mean_time_in_class_years | DOUBLE |  |
| mean_fte | DOUBLE |  |
| median_salary_fte_adjusted | DOUBLE |  |
| mean_pay_range_position | DOUBLE |  |
| mean_moves_per_year | DOUBLE |  |
| mean_dept_churn_12m | DOUBLE |  |
| share_surs_eligible_assumed | DOUBLE |  |
| share_promoted_within_12m | DOUBLE |  |
| share_separated_within_12m | DOUBLE |  |
| mean_bls_growth_pct | DOUBLE |  |
| mean_aei_exposure | DOUBLE |  |
| suppressed | BOOLEAN | cell suppressed (headcount below k, complementary, or small count) |

## dq_issue_register  (outputs/)

| Column | Type | Description |
|---|---|---|
| check_id | VARCHAR | audit check id |
| severity | VARCHAR | error | warn | info |
| concept | VARCHAR | source table (mapping) |
| description | VARCHAR |  |
| rule | VARCHAR |  |
| n_rows | INTEGER | rows flagged |
| n_entities | INTEGER | distinct entities flagged |
| example_ids | VARCHAR | up to 5 synthetic example ids |
| status | VARCHAR | pass | warn | fail |
| rule_version | VARCHAR | rule version of the module that built the table |

## transition_events  (outputs/restricted/)

| Column | Type | Description |
|---|---|---|
| event_id | VARCHAR | md5 of the event key (snapshot, person, position, suffix, row dates, source table) |
| known_as_of | DATE | knowledge date used to derive the event (the extract date for the published table) |
| person_id | VARCHAR | EDW_PERS_ID (synthetic 99xxxxxxx ids in this pack) |
| position_id | VARCHAR | POSN_NBR |
| job_suffix | VARCHAR | JOB_SUFFIX |
| event_date | DATE | effective date of the event: the column chosen by config.job_change_date_column |
| event_type | VARCHAR | see transitions.py docstring; promotion/transfer/reclassification are candidate labels |
| event_subtype | VARCHAR | move: cross_org/cross_campus/same_org; promotion/reclassification: level_<direction>; separation: termination code; hire: first_observed_appointment |
| move_kind | VARCHAR | job_change (new appointment), in_place (same appointment), job_start, job_stop, leave_spell |
| level_direction | VARCHAR | up / same / down / different_ladder / unknown, comparing ladder level then role level |
| is_future | BOOLEAN | event dated after the knowledge date (Future rows) |
| from_p_class | VARCHAR | P-Class before |
| to_p_class | VARCHAR | P-Class after |
| from_class_key | VARCHAR | canonical class key before the event (SUCSS 4-digit code via PAPE_CIV_SVC_ID, else P-Class) |
| to_class_key | VARCHAR | canonical class key after the event |
| from_e_class | VARCHAR | E-Class before |
| to_e_class | VARCHAR | E-Class after |
| from_ladder | VARCHAR | ladder before |
| to_ladder | VARCHAR | ladder after |
| from_ladder_level | BIGINT | job-progression level before (x_ladder rule: ROLE_LEVEL, else rank of range minimum) |
| to_ladder_level | BIGINT | ladder level after |
| from_role_family | VARCHAR | role family before |
| to_role_family | VARCHAR | role family after |
| from_role_level | INTEGER | role level before |
| to_role_level | INTEGER | role level after |
| from_position_id | VARCHAR | position before the event (the from-job for a move) |
| from_org_code | VARCHAR | org before |
| to_org_code | VARCHAR | org after |
| from_campus_org_code | VARCHAR | campus before |
| to_campus_org_code | VARCHAR | campus after |
| from_college_org_code | VARCHAR | college before |
| to_college_org_code | VARCHAR | college after |
| from_dept_org_code | VARCHAR | department before |
| to_dept_org_code | VARCHAR | department after |
| cross_org | BOOLEAN | org changed |
| cross_campus | BOOLEAN | campus changed |
| cross_college | BOOLEAN | college changed |
| cross_dept | BOOLEAN | department changed |
| from_supervisor_person_id | VARCHAR | supervisor before |
| to_supervisor_person_id | VARCHAR | supervisor after |
| from_fte | DOUBLE | FTE before |
| to_fte | DOUBLE | FTE after |
| from_salary | DOUBLE | annual salary before |
| to_salary | DOUBLE | annual salary after |
| state_valid_to | DATE | last effective date of the row that produced the event (9999-12-31 if open) |
| row_eff_date | DATE | JOB_DETL_EFF_DT of the source row (mapping appointment.eff_date) |
| row_recorded_start | DATE | JOB_DETL_HIST_EFF_DT of the source row (mapping appointment.recorded_start) |
| row_post_date | DATE | post date of the source row |
| row_known_from | DATE | start of the recorded interval of the version used |
| current_info_ind | VARCHAR | CUR_INFO_IND of the source row |
| change_reason_code | VARCHAR | source JOB_DETL_CHG_REASON_CD (not used to derive event_type; kept for comparison) |
| change_reason_desc | VARCHAR | JOB_DETL_CHG_REASON_DESC |
| change_reason_label | VARCHAR | mapping code_values.job_change_reason_labels for the code |
| term_reason_code | VARCHAR | TERMN_REASON_CD for separation / retirement events |
| leave_reason_code | VARCHAR | EMPEE_LEAVE_REASON_CD for leave events |
| label_status | VARCHAR | candidate_rule | derived_from_row_diff | source_termination_code | source_status_code | candidate_rule_left_censored |
| date_column_used | VARCHAR | value of config.job_change_date_column for this run |
| source_table | VARCHAR | physical source table (mapping) |
| rule_version | VARCHAR | rule version of the module that built the table |

## person_period_features  (outputs/restricted/)

| Column | Type | Description |
|---|---|---|
| snap_date | DATE | snapshot date t; features use only rows effective <= t and known at t |
| knowledge_date | DATE | extract date; targets are evaluated with this knowledge |
| person_id | VARCHAR | EDW_PERS_ID (synthetic 99xxxxxxx ids in this pack) |
| position_id | VARCHAR | POSN_NBR |
| job_suffix | VARCHAR | JOB_SUFFIX |
| age_band | VARCHAR | age band at t from the restricted birth date (only derived value that leaves T_PERS_HIST); boundary at 40 for the ADEA cut |
| tenure_first_hire_years | DOUBLE | years from FIRST_HIRE_DT (employment row known at t), else first observed appointment |
| tenure_bucket | VARCHAR | 0-3 | 3-7 | 7-15 | 15+ years |
| tenure_current_hire_years | DOUBLE | years from CUR_HIRE_DT (else first observed appointment) |
| time_in_class_years | DOUBLE | years since the start of the continuous spell in the primary job's class key |
| time_in_class_bucket | VARCHAR | same buckets on time_in_class_years |
| time_in_position_years | DOUBLE | years since the start of the continuous spell in the primary position |
| n_active_jobs | BIGINT | active appointments at t |
| fte_total | DOUBLE | sum of FTE over active appointments at t |
| fte_primary | DOUBLE | FTE of the primary appointment (highest FTE, then lowest position) |
| budget_fte | DOUBLE | POSN_APPT_PCT of the primary position (fraction) |
| annual_salary | DOUBLE | JOB_DETL_ANNL_SAL of the primary appointment |
| annual_salary_fte_adjusted | DOUBLE | annual_salary / fte_primary |
| posn_range_min | DOUBLE | POSN_MIN_SAL |
| posn_range_mid | DOUBLE | POSN_MIDPT_SAL |
| posn_range_max | DOUBLE | POSN_MAX_SAL |
| pay_range_position | DOUBLE | (FTE-adjusted salary - POSN_MIN_SAL) / (POSN_MAX_SAL - POSN_MIN_SAL) |
| compa_ratio | DOUBLE | FTE-adjusted salary / POSN_MIDPT_SAL |
| pay_ceiling_gap | DOUBLE | 1 - FTE-adjusted salary / POSN_MAX_SAL |
| n_promotions | BIGINT | promotions known at t |
| n_transfers | BIGINT | transfers known at t |
| n_reclassifications | BIGINT | reclassifications known at t |
| n_rehires | BIGINT | rehires known at t |
| n_leaves | BIGINT | leave spells known at t |
| n_pay_changes_3y | BIGINT | pay_change events in the trailing 3 years |
| n_positions_held | BIGINT | distinct positions entered through hire/rehire/move/additional-job events |
| moves_per_year | DOUBLE | (promotions + transfers known at t) / tenure_first_hire_years |
| time_since_last_move_years | DOUBLE | years since the last promotion or transfer known at t, else tenure since current hire |
| time_since_last_promotion_years | DOUBLE | years since the last promotion known at t (NULL if none) |
| supervisor_span | BIGINT | distinct people whose active appointment at t names this person as supervisor (NULL: no supervisor data) |
| supervisor_data_available | BOOLEAN | FALSE when the source carries no supervisor ids (longitudinal) |
| has_supervisor | BOOLEAN | the primary appointment names a supervisor |
| dept_headcount | BIGINT | people whose primary appointment is in the department at t |
| dept_separations_12m | BIGINT | separations from the department in the trailing 12 months, as known at t |
| dept_hires_12m | BIGINT | hires into the department in the trailing 12 months |
| dept_outbound_moves_12m | BIGINT | moves out of the department in the trailing 12 months |
| dept_churn_12m | DOUBLE | (separations + outbound moves from the department in the trailing 12 months, as known at t) / department headcount at t |
| e_class | VARCHAR | employee class (E-Class) |
| employee_group | VARCHAR | first character of the E-Class |
| civil_service_ind | VARCHAR | JOB_DETL_CIV_SVC_IND |
| p_class_code | VARCHAR | 5-character position class (P-Class) |
| class_key | VARCHAR | canonical class key (SUCSS code or local P-Class) |
| role_family | VARCHAR | role family of the class key (role_family_source says which rule assigned it) |
| role_family_source | VARCHAR | sample_role_family_reference | integration_dim_job_class_internal | employee_group_fallback | unassigned |
| role_level | INTEGER | REF_ROLE_FAMILY.ROLE_LEVEL of the class key |
| ladder_code | VARCHAR | POSN_JOB_PRGS_CD of the primary position |
| ladder_level | BIGINT | level on that ladder (see x_ladder rule) |
| ladder_level_source | VARCHAR | role_family_role_level | rank_of_range_min_within_ladder | no_ladder |
| org_code | VARCHAR | ORG_CD of the primary appointment |
| campus_org_code | VARCHAR | campus-level org (child of the org root; synthetic campus assignment) |
| admin_level_2 | VARCHAR | level-2 (admin) ancestor org |
| college_org_code | VARCHAR | level-3 (college) ancestor org |
| dept_org_code | VARCHAR | level-5 (department) ancestor org |
| empl_status_code | VARCHAR | EMPEE_STATUS_CD of the employment row known at t (NULL when that row was posted after t) |
| posn_status_code | VARCHAR | POSN_STATUS_CD of the primary position version |
| posn_desc_age_years | DOUBLE | years since POSN_DESC_UPDATE_DT when that date is on or before t |
| hire_date_source | VARCHAR | employment_first_hire_date | first_observed_appointment (the employment row was not yet known at t) |
| surs_tier_assumed | VARCHAR | tier1_assumed when the hire-date proxy is before 2011-01-01 (ASSUMPTION) |
| surs_eligibility_band | VARCHAR | ASSUMPTION assumption_v1: tier by first hire before 2011-01-01, service = university service; not SURS data |
| surs_rule_version | VARCHAR | version of the SURS assumption |
| onet_job_zone | BIGINT | O*NET job zone via class -> SUCSS -> O*NET (unreviewed bridge) |
| proj_growth_pct_2025_35 | DOUBLE | BLS projected employment growth 2025-35 for the SOC code |
| proj_occ_separations_rate_pct | DOUBLE | BLS projected occupational separations rate |
| proj_labor_force_exit_rate_pct | DOUBLE | BLS projected labor-force exit rate |
| oews_local_median | DOUBLE | OEWS median for the campus's MSA |
| oews_il_median | DOUBLE | OEWS Illinois median |
| pay_ratio_oews_local | DOUBLE | FTE-adjusted salary / OEWS local-MSA median (synthetic campus assignment) |
| pay_ratio_oews_il | DOUBLE | FTE-adjusted salary / OEWS Illinois median |
| aei_observed_exposure | DOUBLE | AEI observed AI-usage exposure (evidence about tasks, not a forecast) |
| je_watch_score | DOUBLE | job_evolution watch score (unreviewed) |
| onet_code | VARCHAR | O*NET-SOC code (unreviewed bridge) |
| soc_2018_code | VARCHAR | SOC 2018 code |
| external_chain_review_status | VARCHAR | weakest review status on the class -> SUCSS -> O*NET -> SOC chain |
| external_null_reason | VARCHAR | why external facts are NULL for this class |
| promoted_within_12m | BOOLEAN | TARGET: a promotion event in (t, t+12m] with latest knowledge; NULL when censored |
| promoted_within_12m_censored | BOOLEAN | TRUE when t + horizon is after the knowledge date (target NULL) |
| promoted_within_18m | BOOLEAN |  |
| promoted_within_18m_censored | BOOLEAN | TRUE when t + horizon is after the knowledge date (target NULL) |
| separated_within_6m | BOOLEAN | TARGET: a separation or retirement in (t, t+6m] |
| separated_within_6m_censored | BOOLEAN | TRUE when t + horizon is after the knowledge date (target NULL) |
| separated_within_12m | BOOLEAN |  |
| separated_within_12m_censored | BOOLEAN | TRUE when t + horizon is after the knowledge date (target NULL) |
| retired_within_12m | BOOLEAN | TARGET: a retirement in (t, t+12m] |
| retired_within_12m_censored | BOOLEAN | TRUE when t + horizon is after the knowledge date (target NULL) |
| primary_row_start | DATE | event_date of the primary appointment row |
| primary_row_known_from | DATE | known_from of that row (always <= snap_date) |
| date_column_used | VARCHAR | value of config.job_change_date_column for this run |
| rule_version | VARCHAR | rule version of the module that built the table |

## person_demographics_restricted  (outputs/restricted/)

| Column | Type | Description |
|---|---|---|
| person_id | VARCHAR | EDW_PERS_ID (synthetic 99xxxxxxx ids in this pack) |
| sex_code | VARCHAR | RESTRICTED fairness-only |
| gender_code | VARCHAR | RESTRICTED fairness-only |
| race_eth_rpt_code | VARCHAR | RESTRICTED fairness-only (U, 9, H, M, 1-5) |
| ipeds_race_eth | VARCHAR | RESTRICTED fairness-only |
| citizenship_group | VARCHAR | RESTRICTED fairness-only |
| veteran_class | VARCHAR | RESTRICTED fairness-only |
| role | VARCHAR | mapping role of the demographic fields: restricted_fairness_only |
| source_table | VARCHAR | physical source table (mapping) |
