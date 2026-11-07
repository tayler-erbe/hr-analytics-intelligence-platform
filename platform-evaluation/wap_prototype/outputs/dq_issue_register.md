# Data-quality issue register (longitudinal, extract date 2027-01-31, rule version wap_phase1_dq_v1)

Counts only; example ids are synthetic. Severity: error = must be resolved before modelling; warn = review; info = expected behaviour to document.

| Check | Status | Severity | Source table | Description | Rows | Entities | Example ids |
|---|---|---|---|---|---:|---:|---|
| DQ01 | fail | error | T_JOB_DETL_HIST | Overlapping effective intervals within one job (person, position, suffix) | 5 | 5 | 991000076/Q00715/2020-07-15; 991000708/Q00457/2011-03-11; 991000866/Q00115/2020-04-15; 991001071/Q00102/2023-12-05; 991001280/Q00733/2023-02-28 |
| DQ02 | pass | warn | T_JOB_DETL_HIST | Gap between consecutive Active rows of the same job | 0 | 0 |  |
| DQ03 | fail | error | T_JOB_DETL_HIST | Appointment row with no position version effective on its start date | 41 | 41 | Q00003/991000003/1998-08-17; Q00007/991000007/2000-11-30; Q00009/991000009/1999-11-18; Q00010/991000010/1993-07-16; Q00019/991000019/1993-12-16 |
| DQ03b | pass | error | T_JOB_DETL_HIST | Appointment row whose position does not exist at all | 0 | 0 |  |
| DQ04 | pass | error | T_EMPEE_HIST | Terminated person with an Active appointment effective after the termination date | 0 | 0 |  |
| DQ04b | pass | warn | T_EMPEE_HIST | Termination record with no Terminated appointment row on that date | 0 | 0 |  |
| DQ05 | pass | error | T_JOB_DETL_HIST | FTE outside (0, 1.0] on Active rows (fraction assumption) | 0 | 0 |  |
| DQ06 | pass | warn | T_POSN_HIST | FTE-adjusted annual salary outside the position's POSN_MIN_SAL..POSN_MAX_SAL range | 0 | 0 |  |
| DQ06b | pass | warn | T_POSN_HIST | Position version with a missing or inverted salary range | 0 | 0 |  |
| DQ07 | warn | info | T_JOB_DETL_HIST | Active appointment rows with no supervisor (current rows at the extract date) | 822 | 822 | 991000006/Q00522; 991000007/Q01038; 991000022/Q00805; 991000035/Q00005; 991000047/Q00060 |
| DQ07b | pass | error | T_JOB_DETL_HIST | Supervisor cycles (self-supervision or A<->B) among current rows | 0 | 0 |  |
| DQ07c | pass | warn | T_JOB_DETL_HIST | Supervisor id that is not a person with any appointment | 0 | 0 |  |
| DQ08 | warn | info | T_JOB_DETL_HIST | Appointment rows deleted in source (CUR_INFO_IND = D); excluded from current knowledge | 112 | 109 | 991000007/Q00821/2024-07-02; 991000016/Q00473/2009-07-02; 991000018/Q00018/2005-07-04; 991000035/Q00035/2007-07-04; 991000035/Q00035/2010-07-05 |
| DQ08b | warn | info | T_EMPEE_HIST | Employment rows deleted in source (CUR_INFO_IND = D) | 10 | 10 | 991000343/1991-03-31; 991000921/2012-07-23; 991000967/2013-02-23; 991001054/2014-02-10; 991001180/2015-09-29 |
| DQ08c | pass | info | T_POSN_HIST | Position rows deleted in source (CUR_INFO_IND = D) | 0 | 0 |  |
| DQ09 | pass | error | T_JOB_DETL_HIST | Duplicate primary key (person, position, suffix, eff_date, recorded_start) | 0 | 0 |  |
| DQ09b | pass | error | T_JOB_DETL_HIST | Lineage with more than one open (currently known) version | 0 | 0 |  |
| DQ10 | pass | error | T_JOB_DETL_HIST | Appointment person with no person record | 0 | 0 |  |
| DQ10b | pass | warn | T_EMPEE_HIST | Appointment person with no employment record | 0 | 0 |  |
| DQ10c | warn | warn | T_EMPEE_HIST | Employment row whose effective interval is not covered by any appointment of the person (current knowledge) | 1 | 1 | 991000250/1998-03-09 |
| DQ11 | pass | warn | T_JOB_DETL_HIST | Class key with no role family (Unassigned) | 0 | 0 |  |
| DQ11b | pass | info | T_POSN_HIST | Position class with no job-progression ladder | 0 | 0 |  |
| DQ12 | pass | info | T_JOB_DETL_HIST | Rows effective after the extract date (Future) | 0 | 0 |  |
| DQ12b | warn | info | T_JOB_DETL_HIST | Late-keyed rows: first known more than 30 days after they took effect | 1378 | 875 | 991000003/Q00241/2008-06-02; 991000003/Q00406/2008-06-02; 991000003/Q00436/2016-11-05; 991000006/Q00006/2011-03-10; 991000006/Q00272/2011-03-10 |
| DQ13 | pass | error | T_PERS_HIST | Restricted or fairness-only fields exposed in the canonical person view | 0 | 0 |  |
