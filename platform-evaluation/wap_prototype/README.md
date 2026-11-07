# Workforce Analytics Intelligence Platform prototype, Phase 1: Data Foundation

Synthetic data only. Everything here runs on the v3 Cookbook-shaped sample pack
(`sample_datasets/v3_cookbook`, longitudinal by default, CLEAN selectable) through the same
`integration/edw_mapping_cookbook.yaml` that a real EDW extract would use. No EDW row was read.
Person-level outputs are written only to `outputs/restricted/` (gitignored) and never leave the machine;
everything in `outputs/` is an aggregate with k >= 10 and complementary suppression
(`CODEX_HANDOFF.md` section 2, `AGENTS.md` rule 3, Illinois HB 3773).

```bash
cd platform-evaluation
python -m wap_prototype.publish                                        # v3 longitudinal, quarterly snapshots (~8 s)
python -m wap_prototype.publish --source v3_clean --out /tmp/wap_clean # CLEAN set (rebuild its integrated db first, below)
python -m wap_prototype.publish --date-column JOB_DETL_HIST_EFF_DT --out /tmp/wap_alt   # the alternative date reading
WAP_HIST_MODE_KNOWN_FROM=effective_date python -m wap_prototype.publish --date-column JOB_DETL_HIST_EFF_DT --out /tmp/wap_alt2
HR_EDW_DATA=<extract.duckdb or folder> python -m wap_prototype.publish --source edw       # a real extract, same mapping
python -m unittest discover -s wap_prototype/tests -t . -v             # 21 tests (~20 s)

# the integration layer the prototype joins to (external bridges); rebuild when it was built from v1/v2
HR_DATA_SOURCE=edw HR_EDW_MAPPING=integration/edw_mapping_cookbook.yaml \
HR_SAMPLE_PACK_PATH=sample_datasets/v3_cookbook python integration/build_integrated.py --set longitudinal
HR_DATA_SOURCE=edw HR_EDW_MAPPING=integration/edw_mapping_cookbook.yaml \
HR_EDW_DATA=sample_datasets/v3_cookbook/CLEAN/sample.duckdb python integration/build_integrated.py --set CLEAN
```

Needs Python 3.13, duckdb 2.0, pyarrow, numpy, pandas, PyYAML (`requirements.txt`; nothing new was installed).

## What is built

| Module | Output | What it does |
|---|---|---|
| `config.py` | `run_config.json` | Data source (`v3_longitudinal` default, `v3_clean`, `edw` via `HR_EDW_DATA`), as-of/extract date, the `job_change_date_column` switch, role-family definitions, k = 10 (values below 10 are refused), tenure and age bands (an age-40 boundary for the ADEA cut), the SURS assumption. |
| `extract.py` | working views `x_*` | As-of reader over the six Cookbook tables through `integration/mapping.py`; no physical column name outside the mapping (the only two in code are the two candidate values of the date switch). Applies `*_CUR_INFO_IND` D handling and the as-known rule (`known_from <= K < known_to`) from mapping.py's `lineage_next` / `post_date` modes. `register_restricted` reads birth date and the fairness-only fields straight from the physical person table; only an age band leaves. |
| `transitions.py` | `transition_events` (restricted) | The reusable employee-transition dataset: one row per job event per person, with from/to class key, P-Class, E-Class, ladder and level, role family, org path (campus/college/dept), supervisor, FTE, salary, dates, change-reason code and provenance. Re-derived per knowledge date for the feature table. |
| `features.py` | `person_period_features` (restricted), `person_demographics_restricted` (restricted), `feature_summary` | Point-in-time quarterly (or annual) person-period features, leakage-safe; forward-looking targets for Phase 2; a separate fairness-only demographics frame. |
| `dq_audit.py` | `dq_issue_register.{parquet,csv,md}` | 25 checks: interval overlaps/gaps, orphan jobs, terminated people with active jobs, FTE out of range, pay outside the position range, supervisors missing/cycles/dangling, deleted rows, duplicate keys, referential integrity, reference coverage, future and late-keyed rows, restricted-field leakage. Counts and synthetic example ids only. |
| `reconcile.py` | `reconciliation.{json,md}` | Headcount vs `fact_headcount_asof`; transition counts vs the v3 generator's planted totals and vs the integration layer's own event tables. |
| `publish.py` | everything under `outputs/`, `data_dictionary.md`, `manifest.json` | Driver; `unit_quarter_aggregates` (campus x college x dept x role family x quarter), `unit_year_aggregates` (campus x role family x year), `transition_counts`, `feature_summary`, with suppression; manifest with row counts, column counts and CSV SHA-256 hashes (no timestamps: outputs are deterministic). |

### Results on this build (v3 longitudinal, extract date 2027-01-31, quarterly 2016-03-31 .. 2026-12-31)

| Table | Rows | Where |
|---|---:|---|
| transition_events | 20,367 | restricted |
| person_period_features | 31,993 (1,668 people x 44 snapshots) | restricted |
| person_demographics_restricted | 2,302 | restricted |
| unit_quarter_aggregates | 9,375 cells; 9,237 suppressed (headcount below 10), 10 complementary, 68 small counts, 60 fully published | outputs |
| unit_year_aggregates | 363 cells; 40 headcount-suppressed, 4 complementary, 318 with at least one small count | outputs |
| transition_counts | 3,969 cells; 625 published | outputs |
| feature_summary | 1,452 cells (snapshot x campus x role family) | outputs |

Event counts (as known on the extract date): hire 2,302; promotion 804; transfer_lateral 592; transfer_down 66;
reactivation 5; pay_change 13,546; no_change 57; leave 48; job_end 1,467; separation_resignation 972;
separation_end_of_appointment 472; retirement 36. No rehires, reclassifications, org, FTE or status changes exist
in the longitudinal generator.

Reconciliation (25 checks, 25 pass): headcount equals `fact_headcount_asof` on every June 30 from 2016 (611) to
2026 (813), FTE included; promotions 804 = planted 626 OT010 + 178 PR001; transfers 658 = 422 OT012 + 236 OT009;
separations 972 TQ + 36 TR + 472 TE = 1,480; internal moves 1,467 once the 5 re-appointments to an earlier job
(`reactivation`) are added; the integration layer's own `fact_appointment_events` / `fact_separation_events` agree
exactly. `transition_rule_agreement.csv` shows the event type against the source change-reason label: the only
disagreements are intended (the generator's OT009 "campus transfer" is a sub-type here; TE separations carry the
EJ001 job-end code on the job row).

CLEAN (`--source v3_clean`, extract 2026-10-31, 38,284 feature rows, supervisor data present): headcount matches
on all six common June-30 dates (718 .. 1,035); separations 201 TQ / 199 TR / 212 TE = 612 exact; hires 1,500
exact; rehires 143 (planted HR002 150: the other seven HR002 rows start while an earlier appointment of the
person is still open, so the rule calls them `additional_job`); promotions 42 vs planted 38 and transfers 152 vs 156, i.e. 4 of 194 moves where the
range-minimum ladder rank disagrees with the generator's fixed AP/faculty ladder (a transcribed JOB_PRGS level
column would replace that rule). The integration layer's 762 "internal moves" on CLEAN are not comparable: its
rule looks at the person's previous row, so concurrent-job pay cycles count as moves (reported as `info`).

Data quality (longitudinal): 2 errors, 5 warnings, 18 passes. The errors are real properties of the pack: DQ01,
5 Terminated rows with an open `JOB_DETL_EXP_DT` that overlap a later re-appointment (the v3 README's "five
longitudinal Terminated rows"; their `JOB_DETL_DATA_EXP_DT` closes them), and DQ03, 41 appointment rows that start
before their position's first version. Warnings: 822 current rows without a supervisor (longitudinal carries
none), 112 deleted job rows and 10 deleted employment rows (planted), 1 employment row not covered by an
appointment, and late keying measured on the lineage's first version. CLEAN adds DQ05: 394 overload (`O*`)
appointment rows with FTE 0.000 (36 people), which the FTE check flags as out of range.

## ESGC Phase 1 mapping

| ESGC Phase 1 item (hours in the proposal) | Here |
|---|---|
| EDW extraction (44 h) | `config.py` + `extract.py`: the six Cookbook tables read through the verified mapping with as-known reconstruction, D-row handling, the date switch and the restricted-field boundary; `dq_audit.py` for the data-quality analysis; reconciliation against the integration layer. On real data the same code runs with `--source edw` and `HR_EDW_DATA`; the remaining work is confirming the value conventions listed under *Limitations*. |
| Transition dataset construction | `transitions.py` (the "Reusable HR Data Asset"). |
| Feature engineering + O*NET/BLS join (16 h) | `features.py`: the POC features (tenure buckets 0-3/3-7/7-15/15+, move rate per year, departure-risk signals: SURS band, pay-ceiling proximity, unit churn trailing 12 months, time since last move) plus pay position in range, supervisor span, class/E-Class/role family/org path, and the external context through the integration bridges (O*NET job zone, BLS projected growth and separation/exit rates, OEWS local-MSA and Illinois pay ratios, AEI exposure, job-evolution watch score), each with the chain's review status and a null reason. |
| Targets for Phase 2 | promoted within 12/18 months, separated within 6/12 months, retired within 12 months, censored past the extract date. The transition matrix, Markov simulation and models are Phase 2 and are not built here. |

## Rules worth knowing

- **Promotion is a candidate label.** A promotion is a new appointment starting the day after another appointment
  of the person ended (or an in-place class change) whose job-progression level rises on the same
  `POSN_JOB_PRGS_CD` ladder, or whose role family is the same and `REF_ROLE_FAMILY.ROLE_LEVEL` rises. The level on
  a ladder is `ROLE_LEVEL` when every class on the ladder has one, else the rank of the class's position range
  minimum within the ladder (`ladder_level_source` says which). A level fall is `transfer_down`; no rise is
  `transfer_lateral` with cross-org / cross-campus sub-types. HR has confirmed none of this; `label_status` says
  `candidate_rule` on every such row, and the source `JOB_DETL_CHG_REASON_CD` is carried alongside, never used to
  derive the label (so the rule can be checked against it: `transition_rule_agreement.csv`).
- **Separations** come from the termination record in T_EMPEE_HIST (`TERMN_REASON_CD`, grouped by the mapping's
  `separation_reason_group`), matched to the Terminated job row on the same date; retirement follows the Cookbook
  rule (TR/TF or `EMPEE_RET_IND`). A Terminated job row with no termination record that day is `job_end`.
- **Leakage safety.** A snapshot at t sees only rows effective on or before t and known on t. The events used for
  history features are re-derived from those rows, so a late-keyed or corrected row changes a feature only from
  its post date (fixture test), and deleting every row posted after t leaves the 2024-06-30 feature rows
  byte-identical (full-run test). Consequence on update-in-place tables (T_EMPEE_HIST): 35% of feature rows see no
  employment row yet (its post date is later), so tenure falls back to the first observed appointment
  (`hire_date_source`). Targets use the latest knowledge on purpose.
- **Demographics never enter the features.** Sex, gender, race/ethnicity reporting code, IPEDS category,
  citizenship group and veteran class go to `person_demographics_restricted` (role `restricted_fairness_only`), for
  the fairness review only. Birth date is read only to produce `age_band` (DQ13 checks that no restricted field
  reaches the canonical person view).
- **SURS eligibility band is an assumption** (`surs_rule_version = assumption_v1`): tier 1 when the hire-date proxy
  is before 2011-01-01, service credit approximated by university service; EDW has no SURS tier or service credit.
- **Headcount** counts one primary appointment per person (highest FTE, then lowest position), the integration
  layer's rule, which is why the two agree exactly.

## The date-column question (`job_change_date_column`)

Tayler reads `JOB_DETL_HIST_EFF_DT` as an effective date; the Cookbook calls both `JOB_DETL_EFF_DT` and
`JOB_DETL_HIST_EFF_DT` effective dates. v3 treats `JOB_DETL_EFF_DT` as the date the change took effect and
`JOB_DETL_HIST_EFF_DT` as the date the stored version of that row started (mapping.py `lineage_next`:
`known_from = JOB_DETL_HIST_EFF_DT`, `known_to` = the next version's date in the same lineage; D rows end at their
post date). The prototype makes this one switch:

| `job_change_date_column` | event date | effective interval | as-known interval |
|---|---|---|---|
| `JOB_DETL_EFF_DT` (default, v3) | `JOB_DETL_EFF_DT` | `JOB_DETL_EFF_DT .. JOB_DETL_EXP_DT` | version date .. next version date |
| `JOB_DETL_HIST_EFF_DT` | `JOB_DETL_HIST_EFF_DT` | `JOB_DETL_HIST_EFF_DT` .. the day before the job's next `JOB_DETL_HIST_EFF_DT`, capped at `JOB_DETL_EXP_DT` | post date .. open (`hist_mode_known_from = post_date`), or effective date .. open (`effective_date`) |

The switch is resolved through the mapping (the configured name must be `appointment.eff_date` or
`appointment.recorded_start`), every output row carries `date_column_used`, and `tests/test_date_switch.py` flips it
on a four-row fixture (a late-keyed row, its correction, the successor row and a deleted copy): the default gives
hire 2020-01-01 and promotion 2020-07-01; the alternative gives hire 2020-01-10 and the class change on 2020-07-05.

On the v3 longitudinal pack, which was generated under the default reading, the alternative gives 2,295 hires,
776 promotions, 625 transfers, 16,298 `no_change` events (every superseded version becomes a state) and
headcounts 2 to 8 people below the integration layer on each June 30. More important is the as-known
consequence: under the alternative reading the only transaction-time column is the post date, which EDW
overwrites when a row is modified, so with the strict `post_date` rule only 2 of 44 snapshots have any rows (the
rest were "not yet known"); `hist_mode_known_from = effective_date` restores the snapshots by assuming rows are
posted on their effective date, i.e. no late-keying model at all. **Decision needed on real data:** compare, for
one lineage, `JOB_DETL_EFF_DT`, `JOB_DETL_HIST_EFF_DT` and `JOB_DETL_HIST_POST_DT` on rows with
`JOB_DETL_CUR_INFO_IND = 'N'`. If superseded versions share the `JOB_DETL_EFF_DT` of the current row and differ
only in `JOB_DETL_HIST_EFF_DT`, the default reading holds; if each row has a distinct `JOB_DETL_HIST_EFF_DT` and
there are no superseded versions, use the alternative with `effective_date` and accept that point-in-time
features cannot be reconstructed from this table.

## Limitations

- Synthetic data: counts prove the plumbing, not the University. Role families, ladders, campus assignment,
  change-reason codes SA001/JB001/PR001/RA001, employee status T, FTE as a fraction and `PAPE_CIV_SVC_ID` values are
  synthetic or unconfirmed (v3 README); the O*NET link is unreviewed and everything downstream of it carries
  `external_chain_review_status = unreviewed`.
- The quarterly campus x college x dept x role family grain is almost entirely suppressed at k = 10 on an
  813-person set (60 of 9,375 cells published); the annual campus x role family grain is the usable one. The
  suppression rule was not loosened to change this.
- Longitudinal has no supervisor ids, so `supervisor_span` is NULL there (`supervisor_data_available = FALSE`);
  CLEAN has them.
- `time_in_class` / `time_in_position` are spells across all of a person's appointment rows; a concurrent
  secondary job in another class ends the class spell.
- `unit_churn` uses the department of the primary appointment and events as known at t; departments are
  level-5 orgs from `ORG_HIER_LEVEL_NBR` (depth fallback otherwise).
- The integration database must exist for the external context; without it the external columns are NULL with
  `external_null_reason = integrated_db_absent`.
- Nothing here is a model; Phase 2 starts from `person_period_features` and `transition_events` inside the
  restricted folder, under the governance in `CODEX_HANDOFF.md`.
