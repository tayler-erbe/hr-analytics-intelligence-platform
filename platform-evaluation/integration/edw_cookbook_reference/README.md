# EDW Data Cookbook reference (verified dictionary)

Table definitions transcribed from the University of Illinois Data Cookbook (EDW data model "EDW : All Tables", schema version updated 2026-11-06), provided by Tayler Erbe on 2026-11-06. Each `<TABLE>.tsv` lists ordinal, column, Oracle datatype, primary-key flag and the Cookbook comment. These are metadata only; no EDW rows are included.

This reference outranks `../edw_public_reference/` (public job aids and search snippets). Where they disagree, the Cookbook wins and the mapping uses `provenance: verified_dictionary`.

| Table | Columns | Status |
|---|---:|---|
| T_JOB_DETL_HIST | 79 | Verified 2026-11-06 |
| T_EMPEE_HIST, T_PERS_HIST, termination/SURS table, position history, payroll accounting detail, reference tables | — | Pending |

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
