# v2 public-schema sample pack (synthetic)

This pack is Codex's v1 **longitudinal** and **quality/CLEAN** sets, re-expressed with the EDW table names,
column names and code values that public University of Illinois documents show. **All rows are synthetic
and come from v1. No EDW connection, real extract or Data Cookbook content was used.** v1 itself is left
untouched, and DEFECTS is not adapted.

The names and code domains come from `integration/edw_public_reference/`. The mapping that reads this pack
is `integration/edw_mapping_public.yaml`.

```bash
cd platform-evaluation
python sample_datasets/v2_public_schema/build_v2.py           # rebuild from sample_datasets/v1 (~2 s)
python sample_datasets/v2_public_schema/build_v2.py --check   # rebuild in a temp dir; compare content hashes
HR_DATA_SOURCE=edw HR_EDW_MAPPING=integration/edw_mapping_public.yaml \
HR_SAMPLE_PACK_PATH=sample_datasets/v2_public_schema python integration/build_integrated.py --set longitudinal
```

| Path | Contents |
|---|---|
| `longitudinal/`, `CLEAN/` | One `<TABLE>.parquet` per table, `sample.duckdb` (tables plus `_1` views), `schema.json` (`schema_assumptions.json` is the same file under the name `mapping.py` checks) and `manifest.json` (row counts and content SHA-256) |
| `crosswalk_v1_to_v2.csv` | Every table/column rename, added column, added view and value recode, with the rule and the public source key |
| `build_v2.py` | Deterministic adapter (no randomness) |

## What changed from v1

**Tables and columns.** A name is changed only where public evidence exists. Unresolved columns keep their
v1 name.
- `REF_JOB_CLASS` became `T_POSN_CLS_HIST`, with `CLS_CD` → `POSN_CLS_CD` and `CLS_TITLE` → `POSN_CLS_DESC`.
- In `T_JOB_DETL_HIST`:

  | v1 | v2 |
  |---|---|
  | `JOB_STATUS_CD` | `JOB_DETL_STATUS_CD` |
  | `JOB_FTE` | `JOB_DETL_FTE` |
  | `JOB_ANNUAL_SAL_AMT` | `JOB_DETL_ANNUAL_SAL` |
  | `JOB_CLS_CD` | `POSN_CLS_CD` |
  | `JOB_ECLS_CD` | `JOB_DETL_EMPEE_CLS_CD` |

- In `T_EMPEE_HIST`, `CAMPUS_CD` became `HR_CAMPUS_CD`.

**Code values.** Each recode is one-to-one, so the crosswalk inverts exactly.

| Column family | v1 → v2 | Public source |
|---|---|---|
| E-Class (`EMPEE_CLS_CD`, `JOB_DETL_EMPEE_CLS_CD`, `REF_EMPEE_CLS.ECLS_CD`) | C1→**CA** (CS 75Hr/pay N/E Ben Elig), A1→**BA** (Acad/Pro 12mth Ben Elig), F1→**AA** (Acad 9/12mth Ben Elig), G1→**GA** (Graduate Assistants) | kb120378 |
| Local classes → P-Class | AP01..AP10 → RAJAA, SAMBA, SACBA, TAMTA, RALGA, NFJAA, NEPDA, **NAAAA**, LEJAA, **LAAAA**; FA01..FA05 → BAEAA, AACAA, AABAA, **AAAAA**, AAAEA; GA01 → CASAA; OV01 → BEEAA | kb120569 character rules; bold codes are verbatim KB examples |
| Termination reason | RES→**TQ** (Employee Resigned), RET→**TR** (Retired, SURS annuitant), END→**TE** (Terminated/Expired) | kb120385 |
| Payroll ID | MN→**MO** (Monthly) | kb120369 |
| E-Class descriptions | v1 synthetic text → public description | kb120378 |

**Kept unchanged.**
- SUCSS class codes and titles, which are real public codes.
- Synthetic person and position IDs. They deliberately do *not* use the real UIN or `C/S/U/G` + 5-digit
  position-number formats, so they cannot collide with real identifiers.
- Org codes, dates, amounts, FTE, job type P/O/S, job/position status letters A/T/I, SURS Y/N and earn code REG.

**Added columns.** Each is derived from v1 rows and documented publicly by business name:

| Column | Rule |
|---|---|
| `EMPEE_CUR_INFO_IND`, `PERS_CUR_INFO_IND` | `Y` on each person's latest effective row among currently recorded rows, else `N`. Exactly one `Y` per person |
| `ACTIVE_EMPEE_IND` | `Y` unless `EMPEE_STATUS_CD = 'T'` |
| `COA_CD` | Home campus chart code from the synthetic campus: U1→1, U2→2, U3→4, U0→9. Follows the labelled synthetic campus assignment in `bridges.yaml` |
| `JOB_DETL_STATUS_DESC` | Active / Terminated |
| `JOB_DETL_APPT_PCT` | 100 |
| `EMPEE_GROUP_CD`, `EMPEE_GROUP_DESC` | From the E-Class. Group codes are v1's CS/AP/FA/GA, because the real values are not public |
| `POSN_STATUS_DESC` | Active / Inactive |
| `POSN_MIN_SAL`, `POSN_MAX_SAL` | The position class's synthetic range |

**Added objects.**
- `REF_ECLS_PUBLIC`: all 68 published E-Classes.
- Views `V_EMPEE_HIST_1` and `V_JOB_DETL_HIST_1`: full pass-through views.
- View `V_EMPEE_PERS_HIST_1`: excludes the restricted demographics.

**Changed meaning.** In v1 longitudinal, `V_EMPEE_HIST_1` was a current-effective filter as of 2026-10-31.
In v2 it is the full history, as in rc2009, where "Employee History 1" is filtered with
`EMPEE_CUR_INFO_IND = 'Y'`.

**Semantics kept.**
- Every v1 row (row counts equal) and every key and relationship.
- Inclusive effective end dates, exclusive recorded end dates, and `9999-12-31` as the open end.

Quirks of v1 are not "fixed". For example, longitudinal gives academic-professional classes to civil-service
E-Class jobs; that becomes `CA` with `NAAAA`/`SAMBA`.

## Row counts (equal to v1)

| Set | Table (v2) | Rows |
|---|---|---:|
| longitudinal | T_PERS_HIST / T_EMPEE_HIST / T_EMPEE_HIST_5 | 2,302 / 5,257 / 1,480 |
| longitudinal | T_JOB_DETL_HIST / T_POSN_HIST / T_POSN_CLS_HIST | 36,699 / 1,256 / 38 |
| longitudinal | REF_ORG / REF_ROLE_FAMILY | 52 / 38 |
| CLEAN | T_PERS_HIST / T_EMPEE_HIST / T_EMPEE_HIST_5 | 1,951 / 2,268 / 612 |
| CLEAN | T_JOB_DETL_HIST / T_POSN_HIST / T_POSN_CLS_HIST | 17,775 / 2,705 / 899 |
| CLEAN | T_PAYR_ACCTG_DETL / REF_ORG / REF_EMPEE_CLS / REF_HIERARCHY_ROOT | 25,571 / 52 / 4 / 1 |

Both sets also contain `REF_ECLS_PUBLIC` (68 rows), which is new.

## Proof that the swap works (integration build, as of 2026-06-30)

`integration/build_integrated.py` was run on v1 with the default mapping, then on v2 with
`HR_DATA_SOURCE=edw HR_EDW_MAPPING=integration/edw_mapping_public.yaml HR_SAMPLE_PACK_PATH=sample_datasets/v2_public_schema`.
`HR_EDW_DATA=sample_datasets/v2_public_schema/CLEAN/sample.duckdb` gives the same CLEAN result.

| Headline | longitudinal v1 = v2 | CLEAN v1 = v2 |
|---|---|---|
| Position snapshot rows / filled / vacant / incumbents (latest as-of) | 1,051 / 813 / 46 / 813 | 1,896 / 1,079 / 50 / 1,079 |
| Distinct people (headcount, latest) | 813 | 1,035 |
| Flows: external hires / internal moves / separations (all years) | 1,822 / 1,396 / 1,389 | 1,343 / 760 / 610 |
| Separations: resignation / retirement / end of appointment | 905 / 34 / 450 | 201 / 198 / 211 |
| Class → SUCSS coverage (exact / local no record) | 34 / 4 | 881 + 1 title-resolved / 17 |
| Exported tables with equal row counts | 18 of 18 | 18 of 18 |
| Byte-identical tables | 13 of 18 | 9 of 18 |

The tables that differ change only `job_class_code`, `class_title` and `role_family`. These are the
recoded local class codes and titles, and CLEAN's role-family fallback, which uses the E-Class
description: "Academic professional (synthetic)" became "Acad/Pro 12mth Ben Elig". When those labels are
mapped back through `crosswalk_v1_to_v2.csv`, every exported table equals the v1 output row for row.
`integration/tests/test_public_reference.py` checks all of this.

## Limits

- This pack is synthetic. Public names are 2009-2026 documentation, and 60 of the column names are
  inferred from business names. See `integration/edw_public_reference/README.md`.
- These are illustrative assignments, not facts about any real position or person:
  - which P-Class each local class receives;
  - E-Class CA rather than CB/CG/...;
  - TE for civil-service end of appointment (no CS-specific code is published).
- `COA_CD` and `HR_CAMPUS_CD` follow the synthetic campus assignment.
