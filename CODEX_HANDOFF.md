# Codex handoff: run the succession models on real EDW data

Prepared 2026-11-06 for Codex, working with Tayler Erbe (AITS Decision Support) on a University-approved AITS machine. This document is the task. Read it fully, then read [`AGENTS.md`](AGENTS.md), [`platform-evaluation/ARCHITECTURE.md`](platform-evaluation/ARCHITECTURE.md) and [`platform-evaluation/succession_models/run_real.md`](platform-evaluation/succession_models/run_real.md) before changing anything.


## 0. Update 2026-11-06: start from the Cookbook-verified layout

Six EDW tables are now transcribed from the Data Cookbook in `platform-evaluation/integration/edw_cookbook_reference/` (T_JOB_DETL_HIST, T_EMPEE_HIST, T_EMPEE_HIST_5, T_POSN_HIST, T_PERS_HIST, T_PAYR_ACCTG_DETL), with conventions and handling rules in its README. `platform-evaluation/integration/edw_mapping_cookbook.yaml` maps every canonical concept to those verified names, and `platform-evaluation/sample_datasets/v3_cookbook/` is synthetic data in exactly that layout.

Consequences for this task:
- Bind `succession_models/config.SOURCE_MAP` and `extract.sql` to the Cookbook names. `sample_datasets/v3_cookbook/README.md` lists the exact edits (row-version end dates from `JOB_DETL_HIST_EFF_DT` via a window function, terminations from T_EMPEE_HIST, status comparisons on descriptions). Prove the edits on v3 first; then point at EDW.
- Settled: `*_EXP_DT` is inclusive with 12/31/9999 open end; current indicators are Y/N/D; terminations and the retirement flag (TR/TF) are in T_EMPEE_HIST (secured copy in T_EMPEE_HIST_5); vacancy is `OPEN_POSN_IND`; position status A/C/F/I.
- Still to confirm on real metadata or data: FTE stored as fraction vs percent; meaning of `JOB_DETL_HIST_EFF_DT`; terminated status letter; `PAPE_CIV_SVC_ID` value format; code lists for termination and job-change reasons; position-class and org reference tables.
- Person fields such as UIN, SSN, names and birthplace are never extracted (see the reference README).

## 1. Goal

Run the succession planning pipeline in `platform-evaluation/succession_models/` on real EDW HR history. It must produce validated, **role- and unit-level** succession outputs that Illinois HR can use for planning:
- vacancy risk at 6, 12 and 24 months;
- career-transition flows;
- bench strength for critical role families.

The code already runs end to end on synthetic EDW-shaped data. It passes 18 tests, and the synthetic results are in `succession_models/README.md`. Your job is to bind it to the real EDW, pass the data and model gates, and produce an export that reviewers can approve.

**Done means:**
- all validation gates pass or are documented as failed;
- the pre-registered model gates in `run_real.md` §5 are recorded;
- an aggregate-only export (k ≥ 10) is ready for human review;
- a short results memo exists (template in §8 below).

Person-level readiness scoring stays **off**.

## 2. Rules that override everything else

1. **Data location.** Real employee data stays on the approved machine or inside EDW/Denodo. Never commit it, paste it into chat, push it to GitHub, or put it in a synced folder (Box, OneDrive).
2. **Your own access to rows.** Before you read any real rows, confirm in writing with Tayler that the University's approval of Codex covers **Sensitive / HR employee data** on this machine. If the approval covers only code assistance, you may edit code and SQL, but a person runs the extract and reviews outputs. You then work only from schema metadata, row counts and validation-gate results, never row values. Record which mode applies in the memo.
3. **No person-level outputs.** `succession_models/governance.py` blocks person-level scoring unless `governance/approval.json` exists, and that file needs sign-off from Counsel, the Office for Access and Equity and Illinois HR. Do not create that file, and do not weaken the gate.
4. **What leaves the machine.** Only `runs/<label>/export/` aggregates leave, each cell with k ≥ 10 and complementary suppression, after a human reviews them. `restricted/`, the extract folder, notebooks with outputs and screenshots of restricted data never leave.
5. **Gates and thresholds.** Never loosen a validation gate, threshold or suppression rule to make a run pass. A change needs a new labelled protocol version and a note in the memo.
6. **Legal context.** Illinois HB 3773 (in effect 2026-01-01) covers AI in employment decisions. Outputs are decision support for role/unit planning only. They never rank or pre-select people for postings, registers, promotions or discipline.
7. **Read-only assets.** Do not modify `platform-evaluation/benchmark/` (frozen hashes) or any other module's code to make this one work. Fix bindings in `succession_models/config.py` and `extract.sql` only.

## 3. Repository orientation

| Path | What it is | Why you need it |
|---|---|---|
| `platform-evaluation/succession_models/` | The pipeline: `data_contract.md`, `extract.sql`, `extract.py`, `snapshot.py`, models, `governance.py`, `run_all.py`, `run_real.md`, model cards, tests | **Main work area** |
| `platform-evaluation/erp_readiness/` | 43 HR data-quality rules (`rules/catalog.yaml`, compiled SQL for DuckDB/Snowflake/Databricks/Oracle) and `rules/source_map.yaml` | Run before modelling (gate 3.2). The job- and employee-history rules block modelling on critical failures |
| `platform-evaluation/lake/` | Public data lake (O*NET, IPEDS, QCEW, QWI, BLS) and `CONTRACT.md` | Context only; not needed for the real run |
| `platform-evaluation/ARCHITECTURE.md` | Map of every component, status and data class | Orientation |
| Root `README.md` | EDW tables and canonical joins (`T_PERS_HIST`, `T_EMPEE_HIST`, `T_EMPEE_HIST_5`, `T_JOB_DETL_HIST`, `T_PAYR_ACCTG_DETL`) | The source tables |

Other folders (`workforce_sim/`, `swp_workbench/`, `turnover_forecast/` and so on) are prototypes on public or synthetic data. Leave them alone for this task.

## 4. Step-by-step

### Step 0: Confirm approvals and inputs

Get these from Tayler before any extract. Do not invent them.

- [ ] A one-page protocol (purpose, data, outputs, retention, access) per `run_real.md` §0, with the §5 thresholds pre-registered.
- [ ] EDW access approved by the data stewards (IHR Records, Classification and Compensation, Position Control, AITS Decision Support).
- [ ] HR-owned reference inputs:
  - `REF_ROLE_FAMILY` (class → role family, level);
  - the approved critical-role list (`CRITICAL_IND`);
  - confirmed SURS Tier 1 / Tier 2 eligibility rules, or an approved SURS feed.

  The SURS rules in the code are assumptions from public web text.
- [ ] A labor-relations answer on whether outputs touch any bargaining unit's terms and conditions.
- [ ] The Codex data-access mode (rule 2 above).

### Step 1: Environment

Follow `run_real.md` §1. Python 3.13, a virtual environment, `pip install -r platform-evaluation/succession_models/requirements.txt`. lifelines may need `pip install -U "setuptools>=75" && pip install --no-build-isolation autograd-gamma`. Set `RUNS_DIR` in `config.py` to encrypted, access-controlled storage. Run the synthetic tests first to prove the environment:

```bash
cd platform-evaluation
python -m unittest discover -s succession_models/tests -v
```

### Step 2: Bind to the real EDW (the main engineering work)

The EDW column names in this repository are **assumptions**. Confirm each one from the EDW data dictionary or `ALL_TAB_COLUMNS` (schema metadata, not data), then edit only:
- the right-hand sides of `succession_models/config.SOURCE_MAP`;
- the column lists and bind variables in `succession_models/extract.sql`.

Resolve these known open questions and write down the answers:

1. **`*_EXP_DT` convention.** `erp_readiness` assumes inclusive end dates; `knowledge_graph/schema.md` §4.2 assumes exclusive. Confirm the real convention and the open-end value (e.g. 12/31/9999). End-exclusive sources currently raise `NotImplementedError` in `erp_readiness` rather than being checked wrongly. If the EDW is exclusive, implement that branch with tests.
2. **Transaction-time (recorded-date) columns.** If the EDW keeps no row versions, set `bitemporal = False` and follow `data_contract.md` §4 for the leakage check.
3. **Position control.** Confirm the source of authorized positions; the pipeline assumes a `T_POSN_HIST`-like table.
4. **Termination and SURS.** Confirm the termination reason codes in `T_EMPEE_HIST_5` that separate voluntary separations, retirements and other exits, and how SURS tier and service appear (if at all).
5. **Multiple appointments.** Confirm how primary vs secondary appointments are flagged.

Also bind `erp_readiness/rules/source_map.yaml` to the same tables, so the data-quality catalog runs on the real extract.

### Step 3: Extract and validate

```bash
python succession_models/extract.py --engine dbapi --dbapi-module oracledb --dsn "<approved DSN>" \
       --schema <EDW_OWNER> --out /secure/succession/extract
python succession_models/extract.py --validate-only --out /secure/succession/extract
```

The DB-API path has never run against a real database. Expect to debug it, or have a person run each `-- @extract` statement in the approved SQL client and save Parquet files. Then pass, in order:
- [ ] Gates G1–G7 (`data_contract.md` §5). Any FAIL stops the run.
- [ ] The erp_readiness catalog on the same tables. Critical failures in job or employee history (J01–J04, E01–E04) block modelling.
- [ ] As-of headcount reconciliation against the IHR official headcount at 3 dates, within a tolerance agreed with Tayler.
- [ ] Retro-keying rate (I1) recorded.

### Step 4: Run

```bash
python succession_models/run_all.py --extract-dir /secure/succession/extract --skip-generate --no-page \
       --label real_<yyyymmdd> --extract-date <business date of the extract>
```

Keep the defaults: no person-level readiness model, no truth file, erp_readiness compatibility check skipped.

### Step 5: Model validation gates

Record every row of the `run_real.md` §5 table: backtest coverage, calibration, Brier skill vs the role-family base rate, the no-age ablation, restricted subgroup calibration, bench backtest coverage, and stability.

If the model does not beat the base rate on at least 3 of 4 origins, **publish the base rate instead**. On synthetic data even an oracle reached AUC of only about 0.60, so a modest result is expected and acceptable.

### Step 6: Export for review

Build `runs/<label>/export/` with `governance.export_table`. Then check by hand for disclosure through totals (e.g. a unit with a single role family). Suppress and document. A person reviews the export before anything leaves the machine. The page can be rebuilt from the export with `python succession_models/build_page.py --export <dir>`.

## 5. Known issues to watch

- **lifelines build** may fail on autograd-gamma (workaround above).
- **Supply over-forecast.** In the synthetic bench backtest, internal supply was over-forecast by about 1.3 people per family. Check this on real data.
- **Age adverse impact.** The synthetic readiness audit found adverse impact against age 40+ through tenure and service. That is one reason the ranking stays off; the vacancy model's no-age ablation result matters for Counsel.
- **Unrun SQL dialects.** Only DuckDB has run `extract.sql`. Oracle needs `NLS_DATE_FORMAT='YYYY-MM-DD'` for ISO IDs, and other dialects are untested.
- **Contract tables.** In `platform-evaluation/lake/`, BLS silver tables exist but `bls_oews` / `bls_projections` contract tables are not yet published. This is not needed for this task.

## 6. After succession: the next real-data runs, in order

Do these only after the succession run is reviewed, each under the same rules:
1. **ERP conversion readiness** (`erp_readiness/`). The full 43-rule catalog on real EDW history, producing an issue register for the ERP Business Transformation program. Low risk: aggregate counts plus restricted example IDs.
2. **Strategic Workforce Planning workbench** (`swp_workbench/`). Swap workforce_sim's synthetic tables for the succession extract (same grain), so IHR's nine planning worksheets show real unit evidence.
3. **Faculty pipeline** (`faculty_pipeline/`). Replace assumed rank-transition and retirement rates with rates estimated from appointment histories, then backtest.
4. **Sponsored-funding join** (`sponsored_funding/hr_join_design.sql`). Labor distribution → grants → public award end dates, giving grant-funded positions at risk (aggregate, k ≥ 5 per the design; confirm k with Counsel).

AI adoption, survey text and use-case registry use data owned by IHR's Strategic Programs & Partnerships unit, not EDW. They need that unit's agreement first.

## 7. What not to do

- Don't change gate thresholds, suppression k, prompts or scoring to improve results.
- Don't enable person-level readiness or create `governance/approval.json`.
- Don't copy real rows, IDs or names into code, tests, commit messages, issues or chat.
- Don't refactor other modules or the frozen benchmark.
- Don't claim accuracy you have not measured. Report failed gates plainly.

## 8. Results memo template

Write it to `/secure/succession/runs/<label>/MEMO.md` on the machine. Commit only a redacted version with aggregates and gate outcomes, after Tayler approves.

```
Run label / extract business date / code commit
Codex data-access mode (rule 2): full | code-only
Bindings confirmed (table, column, convention) and open questions
Gate results: G1–G7, erp_readiness critical rules, reconciliation, retro-keying
Model gates (run_real.md §5): each row with value and pass/fail
Headline aggregates (k ≥ 10): expected 12/24-month vacancies by role family; bench coverage
What failed or was skipped, and why
Reviewer sign-offs obtained / pending
```

Questions about scope, approvals or HR definitions go to Tayler. Do not guess them.
