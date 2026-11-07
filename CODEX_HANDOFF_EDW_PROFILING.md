# Codex handoff: profile real EDW HR data to build realistic synthetic data

Prepared 2026-11-06 for Codex, working with Tayler Erbe (AITS Decision Support) on a University-approved AITS machine with EDW access. Read [`AGENTS.md`](AGENTS.md) and [`platform-evaluation/ARCHITECTURE.md`](platform-evaluation/ARCHITECTURE.md) first. This task comes **before** [`CODEX_HANDOFF.md`](CODEX_HANDOFF.md) (the real succession run) and makes it easier.

## 0. Update 2026-11-06

Six tables are already transcribed from the Data Cookbook (`platform-evaluation/integration/edw_cookbook_reference/`), with a verified mapping (`integration/edw_mapping_cookbook.yaml`) and a matching synthetic pack (`sample_datasets/v3_cookbook/`). Step 1 (schema inventory) and Step 2 (mapping) are therefore largely done for those tables: confirm them against `ALL_TAB_COLUMNS`, fill in the remaining reference tables and code lists, and move straight to the Step 3 statistical profile. Extend `integration/edw_mapping_cookbook.yaml` rather than creating a new mapping file.


### First check: which job date is the change date?

Tayler confirmed that `JOB_DETL_HIST_EFF_DT` is an effective date and that `JOB_DETL_FTE` is full-time equivalent (1.0 = full time). The Cookbook describes both `JOB_DETL_EFF_DT` and `JOB_DETL_HIST_EFF_DT` as effective dates, and the v3 synthetic pack currently treats `JOB_DETL_EFF_DT` as the change date and `JOB_DETL_HIST_EFF_DT` as a record-version date. Run this aggregate-only query (no rows leave EDW) and record the result in the memo before anything else:

```sql
SELECT COUNT(*)                                                         AS job_rows,
       COUNT(DISTINCT EDW_PERS_ID || '|' || POSN_NBR || '|' || JOB_SUFFIX) AS jobs,
       COUNT(DISTINCT EDW_PERS_ID || '|' || POSN_NBR || '|' || JOB_SUFFIX || '|' || TO_CHAR(JOB_DETL_EFF_DT,'YYYY-MM-DD')) AS job_eff_values,
       COUNT(DISTINCT EDW_PERS_ID || '|' || POSN_NBR || '|' || JOB_SUFFIX || '|' || TO_CHAR(JOB_DETL_HIST_EFF_DT,'YYYY-MM-DD')) AS hist_eff_values,
       SUM(CASE WHEN JOB_DETL_HIST_EFF_DT < JOB_DETL_EFF_DT THEN 1 ELSE 0 END) AS hist_before_job_eff,
       AVG(CASE WHEN JOB_DETL_FTE > 1.5 THEN 1 ELSE 0 END)                 AS share_fte_above_1_5
FROM   T_JOB_DETL_HIST
WHERE  JOB_DETL_CUR_INFO_IND <> 'D';
```

Reading it: if `job_eff_values` is close to `jobs` (one `JOB_DETL_EFF_DT` per job) while `hist_eff_values` is much larger, then `JOB_DETL_EFF_DT` is the job begin date and `JOB_DETL_HIST_EFF_DT` is the change date; report it so `sample_datasets/v3_cookbook/build_v3.py` and `integration/edw_mapping_cookbook.yaml` can be switched. `share_fte_above_1_5` near 0 means FTE is stored as a fraction (1.000), near 1 means a percent (100.000).

## 1. Why we are doing this

This repository already has many HR analytics modules (succession models, ERP readiness checks, workforce planning workbench, scenario simulator, faculty pipeline and others). Their synthetic data was invented from public aggregates and guessed EDW layouts. The column names, code values and history patterns are guesses.

The goal is a **ground-truth profile of the real EDW HR tables**, and a synthetic data generator calibrated to that profile. Three outcomes follow:

1. **Realistic synthetic data.** Synthetic tables use the real table and column names, real code domains, and realistic distributions, relationships and effective-dating behaviour. Every module can then be developed, tested and demonstrated on data that behaves like EDW, without exposing anyone's records.
2. **Easy swap to real data.** One mapping file translates the modules' canonical concepts to real EDW tables and columns. Recreating the project on real data then means switching `HR_DATA_SOURCE=synthetic` to `HR_DATA_SOURCE=edw`, with no code rewrites.
3. **Augmentation that holds up on real data.** Fidelity checks show that what we simulate (turnover, promotions, appointment changes, data defects) matches real patterns closely enough that comparisons made on synthetic data carry over.

**Raw real rows are only a means to build the profile.** They never leave the approved machine.

## 2. Rules that override everything else

1. **Confirm your data access first.** Before reading any real rows, confirm with Tayler that the University's approval of Codex covers **Sensitive / HR employee data** on this machine.
   - If it does: you may run the profiling queries and inspect small samples locally.
   - If it covers code only: you write the SQL and scripts, a person runs them, and you work from the aggregate outputs only.

   Record which mode applied.
2. **Credentials.** No usernames, passwords, DSNs with embedded passwords, tokens or wallet files go in code, notebooks, commit messages, logs, chat or this repository. Use the approved mechanism already on the machine: an Oracle wallet / `tnsnames.ora` alias, the OS keychain via `keyring`, or environment variables set in the shell session (`EDW_DSN`, `EDW_USER`, `EDW_PASSWORD`). Read them at run time. If Tayler has not set them up, ask. Do not guess.
3. **Data steward approval.** Pulling samples needs the HR data stewards' approval (IHR Records, Classification and Compensation, Position Control, AITS Decision Support). Tayler confirms this before you start.
4. **Raw samples stay local.** Raw extracts and row samples are written only to encrypted, access-controlled storage on the approved machine (e.g. `/secure/edw_profile/raw/`). They must not go to Git, Box/OneDrive, cloud notebooks, issues, chat or any AI service other than this approved deployment. Delete them when profiling is done, or keep them under the steward-approved retention period.
5. **What may be committed** (after Tayler reviews it):
   - the profile, with small cells suppressed;
   - the generator code;
   - the mapping file;
   - synthetic data;
   - test results.

   Schema metadata (table and column names, types) is internal University information, and this repository is on a personal GitHub account. Commit schema files only if Tayler confirms that destination is approved. Otherwise keep them in an approved repository or storage location and commit only the generic mapping keys.
6. **No identifiers anywhere outside the machine.** No real UINs, EDW person IDs, names, emails, addresses, birth dates, SSNs, free-text comments, or position numbers that point to one person. Synthetic IDs use a distinct format (`SYN-…`) that can never collide with real ones.
7. **Small-cell rule.** Every published frequency, crosstab or transition count has k ≥ 10, with complementary suppression. Values with fewer than 10 occurrences are grouped as `__RARE__` or dropped. Numeric extremes are top/bottom-coded at the 1st/99th percentile.
8. **Never loosen these rules to get a better profile.**

## 3. Tables to profile

The project's known EDW HR tables and canonical joins are in the root [`README.md`](README.md):

| Table | Contents (as documented) | Use |
|---|---|---|
| `T_PERS_HIST` | Biographical and demographic history | Person grain; demographics for fairness audits only (restricted) |
| `V_EMPEE_HIST_1` | Current employment view | Active-employee snapshots |
| `T_EMPEE_HIST` | Employment lifecycle: hire date, FTE, job class | Tenure, FTE, employment continuity |
| `T_EMPEE_HIST_5` | Termination and SURS retirement details | Separation types, retirement |
| `T_JOB_DETL_HIST` | Job history: title, pay rate, department, supervisor | Appointments, transitions, pay, reporting lines |
| `T_PAYR_ACCTG_DETL` | Payroll accounting distribution | Funding sources (grant-funded positions), pay totals |

Documented joins: `T_PERS_HIST.EDW_PERS_ID = T_EMPEE_HIST.EDW_PERS_ID`; `T_EMPEE_HIST.EDW_PERS_ID = T_JOB_DETL_HIST.EDW_PERS_ID`; `T_JOB_DETL_HIST.POSN_NBR = T_PAYR_ACCTG_DETL.POSN_NBR`. Effective dating uses `*_EFF_DT` / `*_EXP_DT`.

Also locate (names unknown; find them in the EDW data dictionary or ask AITS):
- position control / authorized positions;
- organization hierarchy (org codes, colleges, units);
- job class / employee class reference (SUCSS class codes, AP and faculty classes, pay ranges);
- labor distribution / FOAPAL to grant;
- any row-version or transaction-time ("recorded date") columns.

The schema owner, exact column names and the `*_EXP_DT` convention are **not known in this repository**. Discover them from metadata (`ALL_TAB_COLUMNS`, `ALL_CONSTRAINTS`, `ALL_COL_COMMENTS`, or the AITS data dictionary). Do not invent them.

The modules already declare what they expect; use these as the starting checklist:
- `platform-evaluation/succession_models/data_contract.md` and `config.SOURCE_MAP`;
- `platform-evaluation/erp_readiness/rules/source_map.yaml`;
- `platform-evaluation/workforce_sim/README.md` (position/person/appointment grain);
- `platform-evaluation/sponsored_funding/hr_join_design.sql`.

## 4. Work plan

### Step 1: Schema inventory (metadata only, no rows)

For each table: columns, data types, lengths, nullability, keys, comments, indexes and row count. Write to `/secure/edw_profile/schema/` and, if approved per rule 5, to `platform-evaluation/edw_profile/schema/<table>.json`.

### Step 2: Canonical mapping file

Create `platform-evaluation/edw_profile/edw_mapping.yaml`. It maps the project's **canonical concepts** to real `table.column`, with transformations:

```yaml
person:
  person_id:        {table: T_PERS_HIST, column: EDW_PERS_ID, role: key}
  birth_date:       {table: T_PERS_HIST, column: <confirm>, role: restricted, use: age_band_only}
appointment:
  person_id:        {table: T_JOB_DETL_HIST, column: EDW_PERS_ID}
  position_id:      {table: T_JOB_DETL_HIST, column: POSN_NBR}
  eff_date:         {table: T_JOB_DETL_HIST, column: <confirm>_EFF_DT}
  exp_date:         {table: T_JOB_DETL_HIST, column: <confirm>_EXP_DT, convention: <inclusive|exclusive>, open_end: <e.g. 9999-12-31>}
  fte:              {table: ..., column: ..., transform: "percent_to_fraction"}
  ...
```

Every concept used by `succession_models`, `erp_readiness`, `workforce_sim`, `swp_workbench`, `faculty_pipeline` and `sponsored_funding` must appear. Add a small loader (`edw_profile/mapping.py`) that each module can call, and wire `HR_DATA_SOURCE=synthetic|edw` into each module's config without changing its logic. Keep each module's tests passing.

### Step 3: Statistical profile (aggregates only, k ≥ 10)

Write `/secure/edw_profile/profile/` (raw profile) and a reviewed, suppressed copy at `platform-evaluation/edw_profile/profile/`. For each table and column:

- **Basics:** null rate, distinct-count bucket (1, 2–10, 11–100, …), data-type conformance (e.g. dates stored as text).
- **Code columns** (class codes, employee class, org codes, termination reasons, pay basis, campus): value frequencies with k ≥ 10 and rare values grouped. Include the label tables where they exist.
- **Numeric columns** (FTE, pay rate, annual salary): quantiles (1, 5, 10, 25, 50, 75, 90, 95, 99), top/bottom-coded, by employee class and campus where k allows.
- **Dates:** min/max by year, rows effective by year, the open-end value, the `*_EXP_DT` convention evidence, and the share of future-dated rows.
- **Structure:**
  - rows per person;
  - appointments per person at a snapshot;
  - share of multiple concurrent appointments;
  - persons per position;
  - vacancy share of positions;
  - history length per person;
  - gap and overlap rates between consecutive effective intervals;
  - retro-keying lag distribution (if recorded dates exist).
- **Flows (by year, campus, employee class or role family, k ≥ 10):** hires, separations by reason group, retirements, transfers, promotions, class-to-class transition matrix (class-family level if class level fails k), FTE changes and pay-change distributions.
- **Workforce shape:** age band × tenure band × employee class headcounts at 3 snapshot dates (k ≥ 10; restricted; used only to calibrate the generator).
- **Data quality:** run the `erp_readiness` rule catalog on the real tables and record **counts per rule only**. Real defect rates calibrate the generator's defect injection.

Use SQL aggregation inside EDW wherever possible, so raw rows never leave the database. Pull row samples (≤ 500 rows per table, random, stored only under `/secure/edw_profile/raw/`) only when you need to see formats or edge cases. Never commit or summarise individual rows.

### Step 4: Calibrated synthetic generator

Build `platform-evaluation/edw_synth/`:
- **Inputs:** only the suppressed profile and the mapping file, never raw rows.
- **Output:** synthetic tables with the **real table and column names and types**, real code domains (rare values replaced by plausible common ones), and realistic effective-dated histories:
  - multiple appointments, transfers, promotions, separations by reason, rehires and retro-keyed corrections;
  - realistic defect rates taken from the step 3 counts.
- **Scale and determinism:** configurable (default about 13,000 people), with a seeded generator.
- **Feeding the modules:** a writer for Parquet and DuckDB, plus a compatibility layer that produces the inputs each module expects (`succession_models` extract folder, `erp_readiness` tables, `workforce_sim` tables).

### Step 5: Fidelity and privacy checks

Run the profiler from step 3 on the synthetic data and compare it with the real profile:
- **Fidelity:** marginal distributions (total variation distance / KS), key pairwise relationships, structural statistics, flow rates and transition matrices, and erp_readiness defect rates. Set the pass thresholds with Tayler before generating, and report them per column and table.
- **Utility:** run `succession_models` and `erp_readiness` on synthetic data and, on the approved machine only, on real data. Compare the aggregate results: vacancy rates by role family, bench coverage, rule failure rates. The goal is that conclusions drawn on synthetic data hold on real data.
- **Privacy:**
  - no real identifiers appear;
  - no synthetic record exactly matches a real record on a quasi-identifier set (campus, class, org, age band, hire year, FTE, pay band);
  - distance-to-closest-record is not lower than holdout-to-real;
  - every rare combination is suppressed.

  These checks run on the approved machine. Only the pass/fail summary is committed.

### Step 6: Switch modules to the calibrated data

Regenerate each module's synthetic inputs from `edw_synth`, re-run its tests, and update its README to say its synthetic data is calibrated to a suppressed EDW profile (date, version). Document the one-line switch to real data (`HR_DATA_SOURCE=edw`) and what stays restricted.

## 5. Deliverables

| Path | Contents | Committed? |
|---|---|---|
| `/secure/edw_profile/raw/` | Row samples, raw profiles | **Never** |
| `platform-evaluation/edw_profile/schema/` | Table and column metadata | Only if Tayler confirms the repository is approved for internal metadata |
| `platform-evaluation/edw_profile/edw_mapping.yaml`, `mapping.py` | Canonical concept → EDW mapping and loader | Yes (column names are subject to the same approval as schema files) |
| `platform-evaluation/edw_profile/profile/` | Suppressed statistical profile (k ≥ 10) | Yes, after review |
| `platform-evaluation/edw_synth/` | Generator, tests, fidelity/privacy report (summary only) | Yes |
| `platform-evaluation/edw_profile/MEMO.md` | Access mode, approvals, tables found, conventions confirmed, fidelity results, open questions | Yes, redacted |

## 6. Questions to answer in the memo

- Schema owner and actual table names for position control, org hierarchy, class reference and labor distribution.
- The `*_EXP_DT` convention and open-end value. Two modules disagree: `erp_readiness` assumes inclusive end dates, `knowledge_graph/schema.md` §4.2 assumes exclusive.
- Whether row-version (recorded-date) history exists.
- How primary vs secondary appointments, FTE and pay basis are encoded.
- Termination reason codes that separate retirements, voluntary separations and other exits; how SURS tier and service appear.
- Real defect rates per erp_readiness rule (counts only).

## 7. What not to do

- Don't commit or print credentials, raw rows, identifiers or free text.
- Don't train any model on real data in this task; this task is profiling and synthesis only.
- Don't copy real rows into the synthetic generator, its tests or fixtures.
- Don't modify `platform-evaluation/benchmark/`.
- Don't loosen k, suppression or privacy checks to improve fidelity.

Questions about approvals, credentials, data stewards or HR definitions go to Tayler.
