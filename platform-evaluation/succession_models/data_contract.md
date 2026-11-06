# Data contract: succession-planning models

This is the minimum EDW data the pipeline needs, how it is interpreted, and the as-of (bitemporal) rule that prevents leakage. `extract.sql` implements the extract. `config.SOURCE_MAP` binds logical names to physical columns. `extract.py` runs the validation gates.

**Status of every physical name below:** the table names come from the repository README. The column names are **assumptions** shared with `erp_readiness/rules/source_map.yaml`, and none have been checked against the AITS EDW data dictionary. On the approved machine, confirm them and edit only `SOURCE_MAP` and `extract.sql`.

## 1. Scope and minimisation

| Need | Source | Fields (physical, assumed) | Used for |
|---|---|---|---|
| Primary appointment history | `T_JOB_DETL_HIST` (P contract type only) | `EDW_PERS_ID, POSN_NBR, JOB_SUFFIX, JOB_DETL_EFF_DT, JOB_DETL_EXP_DT, JOB_CONTRACT_TYPE_CD, JOB_STATUS_CD, JOB_FTE, JOB_ANNUAL_SAL_AMT, JOB_CLS_CD, JOB_ORG_CD` | Spells, role tenure, recent changes, FTE, pay position, unit churn, transitions, labels |
| Employment status | `T_EMPEE_HIST` | `EDW_PERS_ID, EMPEE_EFF_DT, EMPEE_EXP_DT, EMPEE_STATUS_CD, FIRST_HIRE_DT, CUR_HIRE_DT` | Service (SURS proxy), tenure since current hire |
| Separations | `T_EMPEE_HIST_5` | `EDW_PERS_ID, TERM_DT, TERM_REASON_CD, SURS_RETIR_IND` | Cause of exit (separation vs internal move) |
| Birth date | `T_PERS_HIST` | `EDW_PERS_ID, PERS_EFF_DT, PERS_EXP_DT, BIRTH_DT` | Age, used **only** inside SURS-eligibility bands |
| Protected attributes (restricted) | `T_PERS_HIST` → separate output `X_PROTECTED_ATTR` | `EDW_PERS_ID, SEX_CD, RACE_ETH_CD` | Fairness audit **only**; never joined into features |
| Position control | `T_POSN_HIST` (assumed table, as in erp_readiness) | `POSN_NBR, POSN_EFF_DT, POSN_EXP_DT, POSN_STATUS_CD, POSN_CLS_CD, POSN_ORG_CD` | Currently vacant positions (job history only shows filled lines) |
| Class pay ranges | `REF_JOB_CLASS` | `CLS_CD, CLS_TITLE, MIN_ANNUAL_AMT, MAX_ANNUAL_AMT` | Pay position in class range |
| Org tree | `REF_ORG` | `ORG_CD, PARENT_ORG_CD, ORG_TITLE` | Roll-up to reporting unit (`SOURCE_MAP["unit_level"]`) |
| Job architecture | `REF_ROLE_FAMILY` (**HR-owned file, not an EDW table**) | `CLS_CD, ROLE_FAMILY, ROLE_LEVEL, CRITICAL_IND` | Role families, levels, steward-approved critical-role list |
| Row versions (all history tables) | Transaction-time columns, assumed `ROW_REC_START_DT`, `ROW_REC_END_DT` | — | As-of (bitemporal) snapshots |

Deliberately **not** extracted:
- names, national-ID hash, UIN, e-mail, address, ZIP/postal code, commute;
- leave and absence history;
- performance or 9-box ratings;
- payroll detail (`T_PAYR_ACCTG_DETL`): pay position comes from the job record, so the payroll table is not needed. Add it only if an earnings-trend feature is approved and shown to add value.
- secondary and overload jobs.

ZIP code is a proxy that HB 3773 explicitly bars. The other items are proxies or outside the purpose. Gate G2 fails if any name, national-ID, address or ZIP-like column appears in the extract.

## 2. Conventions

- **Valid time.** `*_EFF_DT` is inclusive. `*_EXP_DT` is inclusive, and NULL or 9999-12-31 means open. erp_readiness has the same unresolved question: confirm that `*_EXP_DT` really is inclusive. `knowledge_graph/schema.md` assumes half-open intervals.
- **Transaction time.** `ROW_REC_START_DT` is when a row version became known to the EDW. `ROW_REC_END_DT` is when it was superseded (NULL or 9999-12-31 means current). On real data, map these to the EDW load or activity timestamps, or to audit/snapshot tables, whichever records when HR keyed the change. **Never map them to effective dates.**
- **Spell.** A spell is one person in one primary position: the earliest `A` row for that (person, position) up to the first `T` row, or up to the end of the last `A` row.
  - **Exit cause** is `SEP` when `T_EMPEE_HIST_5.TERM_DT` equals the exit date. It is `MOVE` when the same person starts another primary position on the exit date.
  - **Destination** is the class of that next position.
  - A rehire into the *same* position merges two spells. This is rare, and is documented as a limitation.
- **Unit.** The unit is the org ancestor at depth `unit_level` (2 = college in the synthetic tree).
- **SURS.** The tier is derived from `FIRST_HIRE_DT`: before 2011-01-01 is Tier 1, otherwise Tier 2. Service is years since first hire. Eligibility follows simplified Tier 1 and Tier 2 age and service rules (see `config.SURS_RULES`). **These are assumptions.** Replace them with an approved SURS service-credit feed if one exists.

## 3. The as-of rule (leakage firewall)

Features at snapshot date S use only row versions with:

```
eff_dt <= S                      -- effective on or before S
AND rec_start <= S < rec_end     -- the version that was current in the EDW at S
```

`snapshot.incumbents_asof()` applies this predicate to every table it reads: job, employee and person rows, and the trailing-12-month unit exits. An incumbent at S is a person whose known primary `A` row covers S (`exp_dt >= S`). A termination keyed after S for an exit before S therefore leaves that person an incumbent at S, which is what HR saw at the time.

Labels are kept apart from features:

- `spells(known_at=C)` gives training labels for a backtest origin C. These are exits effective and recorded by C, censored at C.
- `spells()` gives the latest data and is used only for evaluation outcomes.
- Labels join features on (person, position) keys only.
- Training periods must end on or before the origin: `snap + 6 months <= C`.

Tests in `tests/test_succession.py` enforce the rule:

- **Truncation.** Features at S from the full extract equal features from the extract truncated to what existed at S.
- **Scrambling.** Every row version recorded after S is scrambled: dates are back-dated, classes and orgs permuted, salaries zeroed. Features at S do not change.
- **Mutation check.** A "latest version" builder fails three of the five leakage tests.
- **Late-keyed exits.** The fixture contains late-keyed exits, and they stay invisible at S.
- **Labels.** Training labels contain no exit after the origin.

## 4. If the EDW has no row versions (effective-only mode)

Set `SOURCE_MAP["bitemporal"] = False` and drop the two `ROW_REC_*` columns from `extract.sql`. The builder then treats every row as known from its effective date, and gate G4 reports **WARN**.

What is still protected:
- Rows effective after S are ignored.
- Exits after S are invisible, because status is evaluated at S.

Residual risk:
- Corrections keyed later are visible as if they had always been known. This covers retro-dated terminations, back-dated hires and class corrections.
- If the EDW overwrites rows in place, the extract shows history as corrected, not as known.

Quantify this before relying on backtests. Compare monthly EDW snapshots, if any are archived, with the current history for a sample of dates. Report the share of rows that differ. Gate I1 (retro-keying rate) only works in bitemporal mode.

The compatibility run in `run_all.py` runs this mode, unchanged, on erp_readiness's CLEAN extract, which has no transaction time.

## 5. Validation gates (`extract.py`)

| Gate | Rule | On failure |
|---|---|---|
| G1 required columns | Every `SOURCE_MAP` column is present, plus row-version columns in bitemporal mode | stop |
| G2 no identity columns | No NAME, NATL, SSN, UIN, EMAIL, ADDR, ZIP, POSTAL or PHONE columns | stop; fix `extract.sql` |
| G3 interval order | EFF_DT > EXP_DT on at most 0.1% of job rows | stop; run erp_readiness J03 |
| G4 row versions | No version with REC_START >= REC_END; at most one current version per key | stop (bitemporal) / WARN (effective-only) |
| I1 retro-keying rate | Share of job rows first recorded more than 30 days after their effective date | information: shows how much leakage protection matters |
| G5 history depth | At least 8 years of job history | stop |
| G6 role-family coverage | At least 95% of open primary rows map to `REF_ROLE_FAMILY` | stop; HR completes the mapping |
| G7 one primary job | At most 1% of persons hold more than one open primary position | stop; run erp_readiness J04 |

## 6. Outputs and their classification

| Output | Grain | Classification | May leave the approved machine? |
|---|---|---|---|
| `runs/<label>/export/*.csv`, `summary.json` | role, role family, unit, unit × family; backtest and recovery aggregates | aggregate; cells with n < 10 suppressed, plus complementary suppression | yes, after review |
| `restricted/position_vacancy_risk.parquet` | position (no person ID) | **restricted**: a single-incumbent position describes its incumbent | no |
| `restricted/person_level/*` | person × target family | **restricted, gated**: exists only when the governance gate is open | no |
| `restricted/governance/*` | protected-group audit tables (n < 10 suppressed) | restricted to Counsel, OAE and IHR reviewers | no, unless Counsel approves |
