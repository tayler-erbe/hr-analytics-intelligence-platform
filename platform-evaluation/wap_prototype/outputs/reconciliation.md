# Reconciliation (longitudinal)

pass 25, fail 0, info (mismatch, informational) 0, skipped 0

## headcount

| Check | Expected | Actual | Tolerance | Status | Note |
|---|---:|---:|---:|---|---|
| headcount 2016-06-30 | 611 | 611 | 0.0 | pass | fte feature=586.25 integration=586.25 |
| headcount 2017-06-30 | 640 | 640 | 0.0 | pass | fte feature=613.5 integration=613.5 |
| headcount 2018-06-30 | 671 | 671 | 0.0 | pass | fte feature=642.0 integration=642.0 |
| headcount 2019-06-30 | 684 | 684 | 0.0 | pass | fte feature=653.25 integration=653.25 |
| headcount 2020-06-30 | 715 | 715 | 0.0 | pass | fte feature=684.75 integration=684.75 |
| headcount 2021-06-30 | 724 | 724 | 0.0 | pass | fte feature=694.75 integration=694.75 |
| headcount 2022-06-30 | 733 | 733 | 0.0 | pass | fte feature=702.75 integration=702.75 |
| headcount 2023-06-30 | 763 | 763 | 0.0 | pass | fte feature=728.75 integration=728.75 |
| headcount 2024-06-30 | 788 | 788 | 0.0 | pass | fte feature=756.5 integration=756.5 |
| headcount 2025-06-30 | 808 | 808 | 0.0 | pass | fte feature=774.75 integration=774.75 |
| headcount 2026-06-30 | 813 | 813 | 0.0 | pass | fte feature=780.5 integration=780.5 |

## transitions

| Check | Expected | Actual | Tolerance | Status | Note |
|---|---:|---:|---:|---|---|
| planted promotion | 804 | 804 | 0.02 | pass | candidate rule |
| planted transfer | 658 | 658 | 0.02 | pass | candidate rule |
| planted separation_resignation | 972 | 972 | 0.0 | pass | from source codes |
| planted retirement | 36 | 36 | 0.0 | pass | from source codes |
| planted separation_end_of_appointment | 472 | 472 | 0.0 | pass | from source codes |
| planted separations_total | 1480 | 1480 | 0.0 | pass | from source codes |
| planted internal_moves | 1467 | 1467 | 0.02 | pass | promotions + transfers + reactivations (re-appointment to an earlier job) |
| planted hire | 2302 | 2302 | 0.0 | pass | from source codes |
| planted rehire | 0 | 0 | 0.0 | pass | from source codes |

## integration_events

| Check | Expected | Actual | Tolerance | Status | Note |
|---|---:|---:|---:|---|---|
| internal moves vs fact_appointment_events | 1467 | 1467 | 0.0 | pass | integration rule counts concurrent-job pay cycles as moves (CLEAN); exact on longitudinal |
| resignation vs fact_separation_events | 972 | 972 | 0.0 | pass |  |
| retirement vs fact_separation_events | 36 | 36 | 0.0 | pass |  |
| end_of_appointment vs fact_separation_events | 472 | 472 | 0.0 | pass |  |
| hires + rehires vs fact_appointment_events | 2302 | 2302 | 0.0 | pass | integration rule counts concurrent-job pay cycles as moves (CLEAN); exact on longitudinal |

## Event counts (as known at the extract date)

| Event type | n |
|---|---:|
| hire | 2302 |
| job_end | 1467 |
| leave | 48 |
| no_change | 57 |
| pay_change | 13546 |
| promotion | 804 |
| reactivation | 5 |
| retirement | 36 |
| separation_end_of_appointment | 472 |
| separation_resignation | 972 |
| transfer_down | 66 |
| transfer_lateral | 592 |
