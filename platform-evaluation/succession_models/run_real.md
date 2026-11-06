# Runbook: running the succession models on real EDW history

**Run only on a University-approved AITS machine, or inside the EDW/Denodo environment.** Real employee data must never enter this repository, a laptop outside policy, a cloud session or any AI service. The code is the same as the synthetic run; only `config.SOURCE_MAP`, `extract.sql` bindings and the HR reference files change.

## 0. Before anything is extracted

1. **Purpose and approvals.** Write a one-page protocol: purpose (role- and unit-level succession planning), data, models, outputs, retention and who sees what. Pre-register the metrics and thresholds below; changes need a new labelled version.
2. **Access.** Request EDW access through the Unit Security Contact. The data stewards must approve the purpose: IHR Records, Classification and Compensation, Position Control and AITS Decision Support.
3. **HR-owned inputs.**
   - The job architecture file `REF_ROLE_FAMILY` (class → role family, level).
   - The approved critical-role list (`CRITICAL_IND`).
   - Confirmed SURS rules, or an approved SURS tier/service feed.
4. **Labor relations.** Ask whether the outputs touch terms and conditions for any bargaining unit (IELRA).

## 1. Environment (approved machine)

```bash
python3.13 -m venv .venv && . .venv/bin/activate
pip install -r succession_models/requirements.txt
# if lifelines fails on autograd-gamma: pip install -U "setuptools>=75" && pip install --no-build-isolation autograd-gamma
```

- Keep the working directory on encrypted, access-controlled storage.
- Do not run inside a synced folder (Box, OneDrive) and do not use a cloud notebook.
- Set `RUNS_DIR` (in `config.py`) to that secure location, or run from a clone that lives there.

## 2. Bind and extract

1. Read the EDW data dictionary and confirm, for each table in `data_contract.md`:
   - the column names;
   - the `*_EXP_DT` convention (inclusive or exclusive, open-end value);
   - the transaction-time columns.

   Edit the right-hand sides of `config.SOURCE_MAP` and the column lists in `extract.sql`. If there are no row versions, set `bitemporal = False` (see data_contract §4).
2. Load `REF_ROLE_FAMILY` into a schema the SQL can read, or save it as Parquet in the extract folder.
3. Run the extract inside the warehouse:

   ```bash
   python succession_models/extract.py --engine dbapi --dbapi-module oracledb --dsn "<approved DSN>" \
          --schema <EDW_OWNER> --out /secure/succession/extract
   ```

   The DB-API path is **untested here** (there is no EDW in this repository). Alternatively, paste each `-- @extract` statement into the approved SQL client and save each result as `<NAME>.parquet` in the extract folder.
4. Write `manifest.json` in the extract folder with `"synthetic": false`.

## 3. Validation gates (all must PASS before modelling)

```bash
python succession_models/extract.py --validate-only --out /secure/succession/extract
```

1. **G1–G7 from data_contract §5.** Any FAIL stops the run. Fix the source or the bindings. Never loosen a gate silently.
2. **Data quality.** Run the erp_readiness rule catalog on the same tables (J01–J04, E01–E04, S01–S04). Critical failures in job or employee history block modelling, because overlapping or gapped intervals corrupt spells.
3. **Reconciliation.** As-of headcount at 3 dates must match the IHR official headcount within an agreed tolerance, with scope differences documented.
4. **Retro-keying (I1).** Record the rate. If in effective-only mode, run the snapshot comparison in data_contract §4.

## 4. Run

```bash
python succession_models/run_all.py --extract-dir /secure/succession/extract --skip-generate --no-page \
       --label real_<yyyymmdd> --extract-date <business date of the extract>
```

Defaults that must stay as they are:
- The person-level readiness model is **not** run.
- No parameter-recovery output exists (no truth file).
- The erp_readiness compatibility check is skipped.

## 5. Model validation gates (pre-registered; record the results)

| Gate | Threshold | Action if missed |
|---|---|---|
| Backtest coverage | ≥ 4 origins with full 24-month follow-up | Shorten horizons; do not report 24-month results |
| Calibration | Mean absolute calibration-in-the-large ≤ 2 percentage points at 12 and 24 months; slope within 0.8–1.2 | Recalibrate; report as uncalibrated |
| Value over baseline | Brier skill vs role-family base rate > 0 at 12 and 24 months on ≥ 3 of 4 origins | Publish the base rate instead of the model |
| No-age ablation | Report the gain from the age-derived features | If the gain is negligible, drop them (Counsel's preference governs) |
| Subgroup calibration | Calibration by sex, race/ethnicity and age 40+ (n ≥ 10 per group). **Restricted.** | Investigate; publish nothing until resolved |
| Bench backtest | Realized need and internal supply inside the P10–P90 band in about 80% of family × origin cells | Widen the intervals (add hazard-parameter uncertainty) |
| Stability | Role-family rankings by expected 24-month vacancy rate stable across adjacent origins (Spearman ≥ 0.7) | Report the instability |

## 6. Governance sign-off checklist

Record names, dates and references in the protocol. Person-level scoring additionally needs `governance/approval.json` (template: `governance/approval.template.json`; never committed).

**University Counsel**
- [ ] Use is decision support for role/unit planning, not an employment decision. HB 3773 (P.A. 103-0804) applicability is assessed for each output.
- [ ] Age-derived inputs (SURS bands) are acceptable at role/unit level under the ADEA and the IHRA, or have been removed.
- [ ] Each protected attribute used for adverse-impact testing is lawful to use for that purpose.
- [ ] The employee AI-use notice covers this tool. The AI tool registry has an entry.
- [ ] Retention period and access list for `restricted/` are set.
- [ ] Person-level readiness is either **not approved** (the default) or approved with a written scope.

**Office for Access and Equity**
- [ ] Audit design reviewed:
  - four-fifths rule plus Fisher's exact test;
  - equalized odds;
  - n ≥ 10 suppression;
  - intersectional checks where n allows.
- [ ] Bench and pool metrics reviewed for diversity of feeder pools versus the feeder population, at aggregate level.
- [ ] Re-audit at every retrain and annually.

**Illinois Human Resources**
- [ ] The job architecture and critical-role list are the approved versions.
- [ ] Civil-service and merit rules: outputs never pre-select or rank candidates for a posting or register (SUCSS, 110 ILCS 70).
- [ ] Position-level output access is limited to named planning staff, and no incumbent-level action is based on it.
- [ ] Communication plan for units receiving role/unit results.
- [ ] Labor-relations consultation where bargaining units are affected.

## 7. What may leave the machine

**Allowed, after reviewer sign-off:** files in `runs/<label>/export/`. These are role-, role-family-, unit- and unit × family-level aggregates. Every published cell has **k ≥ 10** incumbents (or moves/exits), with complementary suppression. `governance.export_table` enforces this and refuses identifier columns.

The page can be rebuilt from an export folder with:

```bash
python build_page.py --export <dir>
```

Before any export, check the outputs manually for small-cell disclosure risk that the gate cannot see. For example, a unit with one role family can reveal that family's figures through the unit total. Suppress such cells by hand and document the decision.

**Never allowed:**
- `restricted/` (position-level and person-level files);
- the extract folder;
- intermediate DataFrames, notebooks with outputs, or screenshots of restricted data;
- anything sent to a cloud or AI service;
- governance audit tables, unless Counsel approves.

## 8. Operate

- Refresh quarterly. Keep each run's `metrics/summary.json` so results can be compared over time.
- Re-run the gates on every refresh.
- Retire the model if a validation gate fails twice in a row.
- Log every use of an output in a planning decision, with the model version (protocol rule: humans decide, outputs are advisory).
