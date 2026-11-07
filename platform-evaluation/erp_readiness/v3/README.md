# Conversion-readiness catalog on the v3 Data-Cookbook layout

Binds the unchanged 43-rule catalog (`../rules/catalog.yaml`) to the Cookbook-shaped synthetic EDW pack in
`../../sample_datasets/v3_cookbook/{longitudinal,CLEAN}`, so the same checks run on the verified table layout
(`T_JOB_DETL_HIST`, `T_EMPEE_HIST`, `T_EMPEE_HIST_5`, `T_POSN_HIST`, `T_PERS_HIST`, `T_PAYR_ACCTG_DETL` plus the
v2-layout `REF_*` / `T_POSN_CLS_HIST` / `X_JOB_CONTRACT_TYPE` side tables). **Everything is synthetic.** Nothing in
`../` (core code, v1 source map, tests) was changed; only this folder and `../rules/source_map_v3_cookbook.yaml`
are new.

```bash
cd platform-evaluation
python erp_readiness/v3/run_v3.py --write-results            # both sets, ~3 s -> v3/runs/<set>/ and v3/RESULTS.md
python erp_readiness/v3/run_v3.py --set CLEAN --switch job_change_date=recorded --out-dir erp_readiness/v3/runs/CLEAN_recorded
python -m unittest discover -s erp_readiness/v3/tests -v     # 16 tests, ~15 s
```

`v3/runs/` is git-ignored (the parent `.gitignore` pattern `runs/` covers it); `RESULTS.md` is the committed summary.
Per set the run writes `issue_register.csv` (43 catalog rules + 7 supplementary checks), `issues_detail.csv`,
`summary.json` and `compiled_duckdb.sql` (every statement executed: prepared views, staging views, helpers, rules).

## How the binding works

```
raw Cookbook tables  ->  prepared views (edw.V3_*)  ->  logical views (stg_*/ref_*)  ->  catalog helpers + 43 rules
   Parquet / DuckDB        source_map_v3_cookbook.yaml      common.staging_sql (unchanged)   run_checks (unchanged)
```

`run_v3.py` loads the raw tables, applies the switches (`${token}` substitution), creates the `prepared` views, then
calls the core `staging_sql`, `create_helpers`, `run_rules` and `domain_scores` exactly as `run_checks.py` does. The
core accepts any SQL expression as the physical side of a logical column, which is where the recodes live; row
filters (deleted rows) and the version collapse need the prepared layer. One deliberate extra: rules the pack
cannot support are reported as `unbound`, `not_evaluable` or `vacuous` and are **excluded from the domain scores**,
never counted as passes (`summary.json: domains[].excluded_rules`).

### Binding table (logical view -> Cookbook source)

| Logical view | Physical source | Handling |
|---|---|---|
| `stg_person` | `V3_PERSON` = `T_PERS_HIST` minus `PERS_CUR_INFO_IND = 'D'` | `PERS_HIST_EFF_DT`/`PERS_EXP_DT`; ids cast to VARCHAR; `natl_id_hash` has no source (P01 unbound); names are NULL by policy (P02 unbound) |
| `stg_employee` | `V3_EMPLOYEE` = `T_EMPEE_HIST` minus D rows | `EMPEE_STATUS_CD` A/B/F/T with B and F recoded to the catalog's `L`; `ORG_CD` as home org |
| `stg_termination` | `V3_TERMINATION` = `T_EMPEE_HIST_5` (switch `termination_source=secured`) or the termination columns of `T_EMPEE_HIST` | `EMPEE_TERMN_DT`, `TERMN_REASON_CD`; retirement flag derived TR/TF -> Y (the secured table has no `EMPEE_RET_IND`); X04 checks the two sources agree |
| `stg_job` | `V3_JOB` = `V3_JOB_ROWS` + `X_JOB_CONTRACT_TYPE` + class bridge | see *two-date key* below; `JOB_DETL_STATUS_DESC` recoded Active->A, Terminated->T, Leave*->L; `fte = JOB_DETL_FTE * JOB_DETL_APPT_PCT / 100`; `SUPV_EDW_PERS_ID` as supervisor; `ORG_CD` as org |
| `stg_position` | `V3_POSN` = `T_POSN_HIST` minus D rows + class bridge + derived org | `POSN_HIST_EFF_DT`/`POSN_HIST_EXP_DT`; `POSN_STATUS_CD` A/C/F/I (rules only test `= 'A'`); `POSN_APPT_PCT` as budget FTE (no budgeted-FTE column); org = latest job's org, else the chart's campus org (no org column on the Cookbook table) |
| `stg_pay` | `V3_PAY` = `T_PAYR_ACCTG_DETL` where `PAYR_ACCTG_CATGRY_CD = 'E'` | `PAYR_ACCTG_EFF_DT` as period end (meaning unconfirmed); `earn_cd = PAYR_ACCTG_EARNS_CD || '/' || PAYR_EVENT_TYPE_CD` so void+reissue pairs are not Y05 duplicates; `PAYR_ACCTG_EXPS_AMT` as amount; `PAYR_ACCTG_TRAN_NBR` as sequence |
| `ref_class` | `T_POSN_CLS_HIST` | keyed by the 4-digit SUCSS code (`CLS_SOURCE = 'SUCSS'`) or the local P-Class |
| `ref_ecls` | `V3_ECLS` from `REF_ECLS_PUBLIC` (present in both sets) | group recoded civil_service->CS etc.; **pay basis assumed SAL for every class** (no column in the pack) |
| `ref_org` | `REF_ORG` | v2 layout plus hierarchy level and chart |
| `ref_hierarchy_root` | `REF_HIERARCHY_ROOT` (CLEAN only) | empty fallback in longitudinal -> O01 not evaluable there |

Every rule's dependency on logical columns is recorded in `rule_bindings` in the map; a test checks the record covers all
43 rules and that every column exists.

### The two-date job key (switch `job_change_date`)

`T_JOB_DETL_HIST` is keyed by `EDW_PERS_ID, POSN_NBR, JOB_SUFFIX, JOB_DETL_EFF_DT, JOB_DETL_HIST_EFF_DT`. The overlap,
gap and inversion rules (J01-J03) run per job key `(person, position, suffix)` on one row per **lineage** (the key
without the history date):

- `business` (default): the change date is `JOB_DETL_EFF_DT`; each lineage collapses to its latest non-deleted record
  version (`MAX(JOB_DETL_HIST_EFF_DT)`), i.e. current knowledge. End date = `JOB_DETL_EXP_DT` (switch `job_end_date`,
  alternative `JOB_DETL_DATA_EXP_DT`).
- `recorded`: the hypothesis that `JOB_DETL_HIST_EFF_DT` is the source version date. Every non-deleted version is a
  row; a superseded version ends the day before the next version of its lineage.

The pack decides between them: under `recorded`, longitudinal (where versions are late-keyed up to a year after the
business date) reports J03 inverted on 3,701 of 3,764 keys and J02 gaps on 3,664, and CLEAN's 26 `Future` rows
(whose `JOB_DETL_HIST_EFF_DT` is clamped to the extract date) collide with the current rows (J01 26, J04 23, J07 21,
S02 21, X03 26). Under `business` both sets are coherent. So `business` is the default and `recorded` stays available
for the day the real EDW shows `JOB_DETL_HIST_EFF_DT` behaves like a change date.

### Other switches

| Switch | Default | Alternative | Why it exists |
|---|---|---|---|
| `job_end_date` | `exp_dt` | `data_exp_dt` | if `JOB_DETL_EXP_DT` turns out not to be maintained on superseded rows |
| `class_key_source` | `bridge` | `pclass` | bridge: 4-digit `PAPE_CIV_SVC_ID` on positions, `REF_PCLS_SUCSS_XWALK` on jobs, P-Class fallback; pclass: raw P-Class both sides, only if the class table is keyed by P-Class |
| `fte_unit` | `fraction` | `percent` | Cookbook calls `JOB_DETL_FTE` a percentage; the pack stores 1.000 |
| `termination_source` | `secured` | `primary` | `T_EMPEE_HIST_5` vs `T_EMPEE_HIST` |
| `pay_earnings_category` | `E` | - | the earnings/expense category letter is synthetic |

### CUR_INFO_IND Y/N/D

D rows are excluded from every prepared view, so no catalog rule sees them (in the pack a D row is a copy of a real row
keyed 1-5 days late; included, it would overlap its lineage). The catalog has no hook for adding rules by configuration,
so the D-row and indicator checks live in `supplementary_rules.yaml` (X01-X07), run by `run_v3.py` after the catalog
and reported separately (not scored):

| Check | What it tests |
|---|---|
| X01 | `*_CUR_INFO_IND` vs `*_DATA_STATUS_DESC` consistency on all five history tables (Y=Current, D=Deleted, N=Expired/Future) |
| X02 | job key or employee known only through D rows (silently out of scope) |
| X03 | job `Y` flag vs the as-of state computed from effective dates (`cur_job`) |
| X04 | termination on `T_EMPEE_HIST` vs the secured copy `T_EMPEE_HIST_5` |
| X05 | `OPEN_POSN_IND` vs active incumbents on the extract date |
| X06 | live job key with no contract type in `X_JOB_CONTRACT_TYPE` |
| X07 | class bridge: PAPE vs P-Class crosswalk disagreement, or civil-service position without a 4-digit identifier |

## Results (default switches; `RESULTS.md` has the full tables)

| Set | as-of | Overall | Scored | Failing rules | Entities | Unbound / not evaluable / vacuous |
|---|---|---:|---:|---:|---:|---|
| longitudinal | 2027-01-31 | 92.2 | 31 / 43 | 2 (J01, C01) | 140 | 3 / 6 / 3 |
| CLEAN | 2026-10-31 | 100.0 | 40 / 43 | 0 | 0 | 3 / 0 / 0 |

CLEAN: every one of the 40 scored rules and all 7 supplementary checks pass, so the semantic drift between v1 and v3
produces **no false positives** once the bindings above are applied (void/reissue folding for Y05, leave recode for
E06/P04, status-description recode, FTE x appointment percent, class bridge). The population sizes confirm the rules
saw data (job keys 1,905; pay keys 37,899; active employees 1,031 of 1,500 persons).

### Rules that could not be bound (3, both sets)

| Rule | Why |
|---|---|
| P01 duplicate national-ID hash | the Cookbook person table carries SSN/UIN, which must never be extracted; the pack keeps them NULL and has no hash. On the real EDW, bind `natl_id_hash` to a hash computed inside the warehouse |
| P02 probable duplicate (name + birth date) | `PERS_FNAME`/`PERS_LNAME` exist but are NULL by policy (never synthesized) |
| S06 job org vs position org | `T_POSN_HIST` has no organization column; a position's org is derived from its jobs, so the comparison is circular |

### Rules not evaluable or vacuous in longitudinal (9)

- Y01-Y05: no `T_PAYR_ACCTG_DETL` in longitudinal (as in v1/v2).
- O01: no `REF_HIERARCHY_ROOT`; with the empty fallback every primary job (822) would fire, so it is reported as
  `not_evaluable`, not as 822 critical failures.
- O02-O04: `SUPV_EDW_PERS_ID` is NULL on every longitudinal row (the v3 README says longitudinal has no supervisors), so
  the reporting-line rules cannot fire; reported as `vacuous`.

The org/supervisory and payroll domains therefore show `ready` for longitudinal only because nothing scored failed;
`excluded_rules` in the summary says which rules were left out.

### Findings on longitudinal, and what they say about the v3 pack (feedback for build_v3.py; nothing was changed)

1. **J01, 5 job keys (critical):** the five Terminated rows that keep an open `JOB_DETL_EXP_DT` although the person was
   re-appointed to the same job (documented in the v3 README). `JOB_DETL_DATA_EXP_DT` closes them, so with
   `--switch job_end_date=data_exp_dt` J01 is clean. Under the Cookbook reading (`JOB_DETL_EXP_DT` = last effective
   date) these are genuine overlaps; the builder should close `JOB_DETL_EXP_DT` on a re-appointment, or the pack's
   README should state that `JOB_DETL_EXP_DT` is not maintained.
2. **C01, 135 active jobs (critical) and X07, 175 current positions:** longitudinal is "all civil service" (every job
   and position has E-Class `CA`, `JOB_DETL_CIV_SVC_IND = 'Y'`) but four of its classes (`NAAAA`, `NFJAA`, `SAMBA`,
   `TAMTA`) are local academic-professional classes: the crosswalk marks them `LOCAL`, the positions carry 5-digit
   PAPE codes 49901-49904, and `T_POSN_CLS_HIST` holds them as `LOCAL`. A civil-service job whose class is not a SUCSS
   class is exactly what C01 is for. The builder should either give those classes a civil-service E-Class consistent
   with their PAPE/P-Class (they came from v2 role families) or make them AP (`BA`) jobs; X07 reports the same 175
   positions from the position side.
3. **Supervisors:** none in longitudinal (`SUPV_*` NULL everywhere). Four of the six org rules are therefore blind
   on the richer set; if build_v3.py can carry v2's supervisor assignment into longitudinal the rules would run.
4. **`REF_HIERARCHY_ROOT` and `REF_EMPEE_CLS`** exist only in CLEAN; `REF_ROLE_FAMILY` only in longitudinal. A
   consistent reference-table set per pack would remove the empty-table fallbacks.
5. **Employee status `T`** (unconfirmed letter) is what E03/E04/Y02 key on. If the real EDW marks terminated employees
   differently (for example by `ACTIVE_EMPEE_IND` or by the absence of a current row), `stg_employee.status_cd` is the
   one expression to change.
6. CLEAN's `T_POSN_HIST.POSN_APPT_PCT` has rows at 0.0000 but none with a current incumbent, so S02 stays silent;
   worth a note in the pack README since `POSN_APPT_PCT` is the only budget-FTE proxy.

Everything else the catalog checks is coherent in both sets, including the D-row handling (X01, X02), the current
indicator (X03), the secured termination copy (X04), `OPEN_POSN_IND` (X05) and contract-type coverage (X06).

## Tests (`tests/test_v3_cookbook.py`)

- Source map resolves every rule: same logical views and columns as the v1 map; `rule_bindings` covers all 43 ids and
  only P01/P02/S06 are unbound; every view points at a prepared or raw table; every switch option substitutes and
  invalid switches raise.
- Compiled SQL runs on DuckDB: the `compiled_duckdb.sql` script (prepared + staging + helpers + 43 rules + 7 checks)
  executes statement by statement on both sets and under every non-default switch option; every rule returns
  three columns.
- Pack results: CLEAN has zero findings; longitudinal's findings are exactly J01 = 5 and C01 = 135; excluded rules are
  the documented ones; the `recorded` variant runs.
- Planted-defect fixture in the Cookbook layout (a copy of CLEAN modified with DuckDB): J01, J03, J04, J06, E01, E03, S04,
  O01, O03, O04, C01, P05, Y02, Y05, X02 and X04 each detect exactly their planted entity; a deleted (D) copy of a
  current row keyed three days late is **not** reported by J01/J02; the affected domains gate `blocked`.

## Limits

- Executed on DuckDB only. The prepared layer uses `- INTERVAL 1 DAY` in the `recorded` variant and `LENGTH`/`SUBSTR`;
  on Snowflake, Databricks or Oracle treat those like `common.add_one_day`.
- `ref_ecls.pay_basis` is assumed `SAL` for every class; hourly civil-service classes on real data need the PTRECLS
  pay basis or C02/C03 will fire on hourly rates.
- The contract type (primary/secondary/overload) comes from the synthetic `X_JOB_CONTRACT_TYPE`; the real source
  (Banner NBRBJOB) is still to be located, as the v3 README says.
- The as-of date is the pack's `manifest.json: extract_date` (longitudinal 2027-01-31, CLEAN 2026-10-31);
  `--as-of` overrides it.
