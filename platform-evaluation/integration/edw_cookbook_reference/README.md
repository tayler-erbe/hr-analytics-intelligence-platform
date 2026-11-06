# EDW Data Cookbook reference (verified dictionary)

Table definitions transcribed from the University of Illinois Data Cookbook (EDW data model "EDW : All Tables", schema version updated 2026-11-06), provided by Tayler Erbe on 2026-11-06. Each `<TABLE>.tsv` lists ordinal, column, Oracle datatype, primary-key flag and the Cookbook comment. These are metadata only; no EDW rows are included.

This reference outranks `../edw_public_reference/` (public job aids and search snippets). Where they disagree, the Cookbook wins and the mapping uses `provenance: verified_dictionary`.

| Table | Columns | Status |
|---|---:|---|
| T_JOB_DETL_HIST | 79 | Verified 2026-11-06 |
| T_EMPEE_HIST | 71 | Verified 2026-11-06 |
| T_PERS_HIST, position history, payroll accounting detail, reference tables (org, E-Class, P-Class/job class) | — | Pending |

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
- Termination lives here: `TERMN_REASON_CD`/`DESC` (VARCHAR2(2)), `EMPEE_TERMN_DT`. Retirement flag `EMPEE_RET_IND` is derived: 'Y' when termination reason is TR or TF, or E-Class is TR. A separate `T_EMPEE_HIST_5` table is therefore not required for separations; this repo's earlier assumption is superseded.
- `EMPEE_STATUS_CD` examples: A Active, B Leave without pay with benefits, F Leave with pay with benefits (full list still to confirm; terminated status letter not listed).
- `EMPEE_GROUP_CD` is VARCHAR2(4) here ("higher level grouping of employee classes") but VARCHAR2(1) on job detail (first character of E-Class). Treat them as different fields.
- Person-level rollups: `EMPEE_FTE` (sum of FTE across current active jobs) and `EMPEE_ANNL_SAL` (sum of salary, excluding job suffix CE and job number C63998, adjusted by appointment percent).
- Service dates: FIRST_HIRE_DT, CUR_HIRE_DT, ADJ_SVC_DT, UNIV_SNRTY_DT, ORIG_STATUS_HIRE_DT, FIRST_WORK_DT, LAST_WORK_DT.
- Leave of absence: EMPEE_LEAVE_REASON_CD/DESC, EMPEE_LOA_FROM_DT, EMPEE_LOA_TO_DT.
- SURS annuitant fields exist (affected date, max annual earnings, 40% threshold) but there is no SURS tier or service-credit field; retirement eligibility still needs another source.
- Sensitive or operational fields to exclude from analytics extracts and never synthesize as realistic values: E_VERIFY_CASE_NBR, CASE_NBR_ENTRY_USER_ID, HIRETOUCH_ID, SURS_LAST_UPDATE_CHG_ID, SURS_ENTR_FULL_NAME, SURS_UPDATE_NOTE_TXT, EMPEE_USER_ID. Synthetic samples keep these columns NULL.
