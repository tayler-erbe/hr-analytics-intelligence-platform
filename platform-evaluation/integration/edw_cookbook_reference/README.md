# EDW Data Cookbook reference (verified dictionary)

Table definitions transcribed from the University of Illinois Data Cookbook (EDW data model "EDW : All Tables", schema version updated 2026-11-06), provided by Tayler Erbe on 2026-11-06. Each `<TABLE>.tsv` lists ordinal, column, Oracle datatype, primary-key flag and the Cookbook comment. These are metadata only; no EDW rows are included.

This reference outranks `../edw_public_reference/` (public job aids and search snippets). Where they disagree, the Cookbook wins and the mapping uses `provenance: verified_dictionary`.

| Table | Columns | Status |
|---|---:|---|
| T_JOB_DETL_HIST | 79 | Verified 2026-11-06 |
| T_EMPEE_HIST | 71 | Verified 2026-11-06 |
| T_EMPEE_HIST_5 | 27 | Verified 2026-11-06 (secured) |
| T_POSN_HIST | 52 | Verified 2026-11-06 |
| T_PERS_HIST, payroll accounting detail, reference tables (org, E-Class, P-Class/job class) | — | Pending |

## Conventions confirmed by T_JOB_DETL_HIST

- Primary key: EDW_PERS_ID + POSN_NBR + JOB_SUFFIX + JOB_DETL_EFF_DT + JOB_DETL_HIST_EFF_DT.
- `JOB_DETL_EXP_DT` is **inclusive** (last effective date); current records use 12/31/9999.
- `JOB_DETL_CUR_INFO_IND`: Y current, N no longer current, D deleted in source.
- Record history: `JOB_DETL_HIST_EFF_DT` (history-record effective date) and `JOB_DETL_HIST_POST_DT` (inserted or last modified in EDW). There is no recorded-end column; as-known state is reconstructed from posting dates.
- Job class on the job record is the 5-character position class `JOB_DETL_POSN_CLS_CD` (P-Class) plus the 2-character E-Class `JOB_DETL_EMPEE_CLS_CD`; there is no 4-digit SUCSS class code on this table.
- Status is carried as a description (`JOB_DETL_STATUS_DESC`), not a code.
- `JOB_DETL_FTE` NUMBER(6,3) is described as a percentage; whether stored as 1.000 or 100.000 is still to confirm from data.
- Org hierarchy on the record: COA_CD, ORG_CD, campus, college, department, sub-department levels 6–7, admin level 2.
- Supervisor: SUPV_EDW_PERS_ID + SUPV_POSN_NBR + SUPV_JOB_SUFFIX.

## Conventions confirmed by T_EMPEE_HIST

- Primary key: EDW_PERS_ID + EMPEE_EFF_DT. `EMPEE_EXP_DT` inclusive, 12/31/9999 open end; `EMPEE_CUR_INFO_IND` Y/N/D; `EMPEE_POST_DT`, `EMPEE_DATA_STATUS_DESC`, `EMPEE_DATA_EXP_DT` as in job detail.
- Termination lives here: `TERMN_REASON_CD`/`DESC` (VARCHAR2(2)), `EMPEE_TERMN_DT`. Retirement flag `EMPEE_RET_IND` is derived: 'Y' when termination reason is TR or TF, or E-Class is TR. `T_EMPEE_HIST_5` also exists (Cookbook comment: "THIS SECURED TABLE CONTAINS THE TERMINATION CODE, DESCRIPTION AND DATE FOR AN EMPLOYEE."); Use T_EMPEE_HIST for termination where access allows; T_EMPEE_HIST_5 is the secured source and may be what restricted roles must use.
- `EMPEE_STATUS_CD` examples: A Active, B Leave without pay with benefits, F Leave with pay with benefits (full list still to confirm; terminated status letter not listed).
- `EMPEE_GROUP_CD` is VARCHAR2(4) here ("higher level grouping of employee classes") but VARCHAR2(1) on job detail (first character of E-Class). Treat them as different fields.
- Person-level rollups: `EMPEE_FTE` (sum of FTE across current active jobs) and `EMPEE_ANNL_SAL` (sum of salary, excluding job suffix CE and job number C63998, adjusted by appointment percent).
- Service dates: FIRST_HIRE_DT, CUR_HIRE_DT, ADJ_SVC_DT, UNIV_SNRTY_DT, ORIG_STATUS_HIRE_DT, FIRST_WORK_DT, LAST_WORK_DT.
- Leave of absence: EMPEE_LEAVE_REASON_CD/DESC, EMPEE_LOA_FROM_DT, EMPEE_LOA_TO_DT.
- SURS annuitant fields exist (affected date, max annual earnings, 40% threshold) but there is no SURS tier or service-credit field; retirement eligibility still needs another source.
- Sensitive or operational fields to exclude from analytics extracts and never synthesize as realistic values: E_VERIFY_CASE_NBR, CASE_NBR_ENTRY_USER_ID, HIRETOUCH_ID, SURS_LAST_UPDATE_CHG_ID, SURS_ENTR_FULL_NAME, SURS_UPDATE_NOTE_TXT, EMPEE_USER_ID. Synthetic samples keep these columns NULL.

## Conventions confirmed by T_EMPEE_HIST_5 (secured)

- Same key and dating as T_EMPEE_HIST (EDW_PERS_ID + EMPEE_EFF_DT; EMPEE_EXP_DT open end 12/31/9999; EMPEE_CUR_INFO_IND), with its own post date `EMPEE_5_POST_DT`.
- Carries termination (TERMN_REASON_CD/DESC, EMPEE_TERMN_DT) and the SURS annuitant fields, plus the full org-hierarchy ancestor path of the employee's organization: CAMPUS_LEVEL_1_CD, ADMIN_LEVEL_2_CD, COLL_LEVEL_3_CD, SCHOOL_SUB_COLL_LEVEL_4_CD, DEPT_LEVEL_5_CD, DEPT_SUB_ORG_LEVEL_6/7/8_CD. These names reveal the EDW org-hierarchy levels (1 campus, 2 admin, 3 college, 4 school/sub-college, 5 department, 6–8 sub-org).
- Termination fields duplicate T_EMPEE_HIST; use whichever the access role permits. For the models, prefer T_EMPEE_HIST and reconcile against _5 where both are readable.
- The SURS user/name/note fields are operational and stay NULL in synthetic data.

## Conventions confirmed by T_POSN_HIST

- Primary key: POSN_NBR + POSN_HIST_EFF_DT. `POSN_HIST_EXP_DT` inclusive, 12/31/9999 open end; `POSN_HIST_CUR_INFO_IND` Y/N/D; `POSN_HIST_POST_DT`; data status and data expiration date as in the other tables.
- Position status: `POSN_STATUS_CD` A Active, C Cancelled, F Frozen, I Inactive (with `POSN_STATUS_DESC`).
- Vacancy: `OPEN_POSN_IND` (open vs filled). Use it alongside job history; do not infer vacancy only from missing incumbents.
- Term vs permanent: `POSN_BGN_DT`, `POSN_END_DT` (null = presumed permanent). `POSN_TYPE_DESC` single vs pooled.
- Class links: `POSN_CLS_CD` (5-char P-Class), `POSN_EMPEE_CLS_CD` (E-Class), and `PAPE_CIV_SVC_ID`/`_DESC` (VARCHAR2(6); populated with the PAPE code or the Civil Service Identifier). `PAPE_CIV_SVC_ID` is the most likely bridge from positions to SUCSS civil-service classes and is the preferred source for the SUCSS -> O*NET bridge once its value format is confirmed. `OCCUP_TITLE_CD` (Dictionary of Positions occupational title) and `CIPC_CD` (CIP) are additional classification codes.
- Career ladder: `POSN_JOB_PRGS_CD`/`_DESC` groups related position classes in sequential order (job progression); a ready-made source for promotion paths.
- Pay structure: salary table/group/grade/step, `POSN_MIN_SAL`/`MIDPT_SAL`/`MAX_SAL` with `POSN_SAL_RANGE_TYPE_DESC` (hourly vs annual), `POSN_SAL_RT_TYPE_DESC`, `POSN_EXEMPT_IND`, bargaining unit (`POSN_BRGN_UNIT_CD`/`DESC`), seniority accrual.
- Position appointment percent `POSN_APPT_PCT` is NUMBER(5,4) (a fraction, e.g. 1.0000); there is no separate budgeted FTE column.
- Position-description freshness: `POSN_DESC_UPDATE_DT` (last review of the physical position description).
- Supervision: `SUPV_POSN_NBR`.
- There is no organization column on the position table; a position's org comes from its job records (or a position-funding/labor-distribution table not yet transcribed).
