# v3 Data Cookbook sample pack (synthetic)

This pack re-expresses the v2 **longitudinal** and **CLEAN** sets in the exact table layouts that the University of
Illinois **Data Cookbook** gives for six EDW tables. **Every row is synthetic and comes from v2 (and so from Codex's
v1). No EDW row, extract or login-protected content was used.** The Cookbook transcriptions are metadata only
(`integration/edw_cookbook_reference/*.tsv`). v1 and v2 are left untouched. DEFECTS is not adapted.

```bash
cd platform-evaluation
python sample_datasets/v3_cookbook/build_v3.py           # rebuild from v2 (~7 s, deterministic)
python sample_datasets/v3_cookbook/build_v3.py --check   # rebuild in a temp dir; compare content hashes
python sample_datasets/v3_cookbook/build_v3.py --v2-root <dir> --out <dir> --sets longitudinal --no-id-crosswalk
                                                          # the same builder on another v2-layout world
                                                          # (sample_datasets/v3_cookbook_large/build_large.py uses it)
HR_DATA_SOURCE=edw HR_EDW_MAPPING=integration/edw_mapping_cookbook.yaml \
HR_SAMPLE_PACK_PATH=sample_datasets/v3_cookbook python integration/build_integrated.py --set longitudinal
HR_DATA_SOURCE=edw HR_EDW_MAPPING=integration/edw_mapping_cookbook.yaml \
HR_EDW_DATA=sample_datasets/v3_cookbook/CLEAN/sample.duckdb python integration/build_integrated.py --set CLEAN
python -m unittest integration.tests.test_cookbook_v3 -v  # 38 tests (~20 s)
```

| Path | Contents |
|---|---|
| `longitudinal/`, `CLEAN/` | One `<TABLE>.parquet` per table; `sample.duckdb` (tables plus pass-through views `V_JOB_DETL_HIST_1`, `V_EMPEE_HIST_1`, `V_EMPEE_PERS_HIST_1`); `schema.json` (per column: DuckDB type, Oracle type, VARCHAR2 length, PK flag, provenance, `value_status`); `schema_assumptions.json` (same file, the name `mapping.py` reads); `manifest.json` (row counts, v2 row counts, content SHA-256, planted counts, change-reason and termination counts, extract date) |
| `crosswalk_v2_to_v3.csv` | Every v2 → v3 id mapping (6,776 rows), P-Class assignment, added/dropped/moved column, added row and table reshape |
| `build_v3.py` | Deterministic builder. "Random" choices use an MD5 fraction of a text key |

## What is Cookbook-verified and what is still assumed

| Table | Columns | Layout | Rows (longitudinal / CLEAN) |
|---|---:|---|---|
| `T_JOB_DETL_HIST` | 79 | **Cookbook, exact** | 36,815 / 17,872 |
| `T_EMPEE_HIST` | 71 | **Cookbook, exact** | 3,888 / 2,354 |
| `T_EMPEE_HIST_5` (secured) | 27 | **Cookbook, exact** | 1,480 / 612 |
| `T_POSN_HIST` | 52 | **Cookbook, exact** | 1,256 / 2,705 |
| `T_PERS_HIST` | 62 | **Cookbook, exact** | 2,302 / 1,951 |
| `T_PAYR_ACCTG_DETL` | 47 | **Cookbook, exact** (CLEAN only, as in v1/v2) | – / 38,489 |
| `T_POSN_CLS_HIST`, `REF_ROLE_FAMILY`, `REF_EMPEE_CLS`, `REF_HIERARCHY_ROOT`, `REF_ECLS_PUBLIC` | v2 | v2 names and values (not yet transcribed); keys moved to v3 ids | equal to v2 |
| `REF_ORG` | v2 + 2 | v2 columns plus `ORG_HIER_LEVEL_NBR`, `COA_CD`; 6 synthetic admin-level-2 rows | 58 / 58 |
| `REF_PCLS_SUCSS_XWALK` | 7 | new, synthetic (fallback P-Class → class-key bridge) | 38 / 899 |
| `X_JOB_CONTRACT_TYPE` | 4 | new, holds job type P/O/S (not a Cookbook column) | 3,764 / 1,905 |

"Verified" means the **names, order, Oracle types and keys**. Many **values** are still synthetic or unconfirmed;
`schema.json` marks each column's `value_status` (`cookbook_listed`, `public_code_domain`, `derived`, `synthetic`,
`identifier_synthetic`, `null_not_synthesized`, `null_prohibited`, `free_value`, with mixed cases spelled out).

Types: `NUMBER(p,0)` → `INTEGER` (p ≤ 9), `BIGINT` (p ≤ 18), `DECIMAL(p,0)` (p > 18); `NUMBER(p,s)` → `DECIMAL(p,s)`;
bare `NUMBER` → `DOUBLE`; `VARCHAR2(n)` → `VARCHAR` with the length checked at build time and in tests; `DATE` → `DATE`.

## Identifiers (synthetic ranges, recorded in the crosswalk)

- `EDW_PERS_ID` NUMBER(9): `991000000 + n` for longitudinal `SYN000000n`, `992000000 + n` for CLEAN `SP00000n`.
  Nine digits beginning `99`. Supervisor ids use the same map.
- `POSN_NBR` VARCHAR2(6): letter + 5 digits. v2 `Q000001` → `Q00001`; letters `Q`, `R`, `O` kept; `S` → `V`, so no id
  uses a real campus letter (C/S/U/G + 5 digits is the public position-number format).
- `JOB_SUFFIX` VARCHAR2(2): v2 `00`/`01` unchanged.
- P-Class for SUCSS civil-service classes: `Y` + the 4-digit SUCSS code (`Y4990`). `Y` is a reserved-for-growth
  first character, so it cannot collide with a real P-Class. Local academic classes keep v2's P-Classes (built with
  the public kb120569 character rules).

## Time semantics

- `*_EXP_DT` is inclusive; current records use 9999-12-31 (Cookbook).
- **Job record history.** v2's recorded versions (`ROW_REC_START_DT`/`ROW_REC_END_DT`) become history rows of the
  same lineage. The lineage is the primary key without the history date: `EDW_PERS_ID, POSN_NBR, JOB_SUFFIX,
  JOB_DETL_EFF_DT`.
  - `JOB_DETL_HIST_EFF_DT` is the version's start (v2 `ROW_REC_START_DT`; CLEAN, which has no versions, uses
    `least(JOB_DETL_EFF_DT, extract date)`).
  - `JOB_DETL_HIST_POST_DT` means "inserted or last modified". It is the version's start, or for a superseded
    version the start of the version that replaced it, or for a deleted row the deletion date.
  - Longitudinal keeps all 16,384 superseded versions and 35,576 late-keyed rows. Our reading of
    `JOB_DETL_HIST_EFF_DT` as the source version date **must be confirmed on real data**.
- **Deleted rows (`D`).** 112 longitudinal and 102 CLEAN rows (0.3% and 0.6%) are keyed in error: a copy of a real
  row with an effective date 1–5 days late, deleted 1–3 days after keying, never across a June 30 snapshot date.
  They are new rows; v2 had no deletions.
- **Current indicator / data status** (all tables), relative to the extract date (longitudinal 2027-01-31, after
  its last posting on 2027-01-24; CLEAN 2026-10-31, so its December 2026 rows are `Future`):
  - `Y`/`Current`: the latest version, effective on the extract date (`*_DATA_EXP_DT` ≥ extract);
  - `N`/`Expired`: superseded versions and rows that ended;
  - `N`/`Future`: rows effective after the extract date;
  - `D`/`Deleted`.
  `JOB_DETL_DATA_EXP_DT` is the implied end: the day before the job's next effective row, capped at `JOB_DETL_EXP_DT`.
- **Re-appointment to the same job.** v1 leaves a job's Terminated row open-ended (9999-12-31). When the person is
  later re-appointed to the same position and suffix (5 longitudinal jobs, `RA001`), that open row would overlap
  the new Active row under the Cookbook reading of `JOB_DETL_EXP_DT`. The builder closes it the day before the
  re-appointment, as a new recorded version dated when the re-appointment was keyed (4 jobs; the fifth was keyed
  before the open version and is closed in place), so the as-known reconstruction still sees the open row until
  then. `manifest.json: notes.job_rows_reappointment_closed` / `..._close_versions_added` count them. (Earlier
  builds left the rows open: the erp_readiness J01 finding.)
- **Tables without a history date** (`T_EMPEE_HIST`, `T_POSN_HIST`, `T_PERS_HIST`) are updated in place. Their key is
  (id, effective date), so only the currently stored version survives. 1,475 superseded longitudinal
  `T_EMPEE_HIST` versions were dropped, and `EMPEE_POST_DT` is when the surviving version was written.
  `T_POSN_HIST` and `T_PERS_HIST` had no superseded versions.

## Rules by table

### T_JOB_DETL_HIST
- Org columns come from the synthetic org tree, now on the Cookbook levels: 1 campus, 2 admin, 3 college,
  4 school (unused), 5 department, 6–8 sub-org (unused). The tree gained six admin units: `U1A`/`U2A`/`U3A` (Provost)
  above colleges 1 and 3, and `U1B`/`U2B`/`U3B` (VC Admin) above colleges 2 and 4.
  - `JOB_DETL_COLL_CD` is the level-3 ancestor, `JOB_DETL_DEPT_CD` level 5 and `JOB_DETL_ADMIN_LEVEL_2_CD` level 2.
    Sub-department levels 6 and 7 are NULL.
  - Campus follows the integration layer's synthetic assignment in `bridges.yaml`: U10 → UIUC, U20 → UIC,
    U30 → UIS, U00 → System Offices. `COA_CD` and `JOB_DETL_CAMPUS_CD` are 1/2/4/9 (public chart codes; that campus
    code equals chart code is synthetic).
- **E-Class follows the class type.** v1 longitudinal codes every job `C1` (v2 `CA`) although four of its classes
  (`SAMBA`, `TAMTA`, `NFJAA`, `NAAAA`, from the synthetic Academic Professional role family) are local
  academic-professional classes. A job on a local class takes its ladder's E-Class: AP → `BA`, faculty → `AA`,
  graduate assistant → `GA`; SUCSS classes keep the source E-Class (`CA`). Longitudinal: 6,626 `BA` job rows
  (`MO` pay), 30,189 `CA` (`BW`); CLEAN is unchanged (its classes and E-Classes already agree). Positions take the
  E-Class of their jobs and the employee record the E-Class of its primary appointment on the row's reference
  date (715 longitudinal employee rows). `manifest.json: notes.job_rows_eclass_recoded_to_class_type` counts the
  recodes. (Earlier builds coded those jobs `CA`: the erp_readiness C01 / X07 finding.)
- `JOB_DETL_EMPEE_GROUP_CD` is the first character of the E-Class. `JOB_DETL_CIV_SVC_IND` is `Y` iff the E-Class
  begins with C or D (rc2009 rule).
- Pay. Civil service (E-Class C*) is biweekly: `BW`, 26 pays, 7.5 h/day × FTE, 75 h/pay × FTE. Academic is
  monthly: `MO`, 12 pays, 8 h/day × FTE, 173.33 h/pay × FTE.
  - `PAY_PERD_SAL = round(ANNL_SAL / ANNL_PAY_COUNT, 2)` and `REGULAR_RT = PAY_PERD_SAL / PAY_HOURS`.
  - `PAYS_YR = ANNL_PAY_COUNT`.
  - Tested within a cent of rounding.
- `JOB_DETL_FTE` is stored as a **fraction** (1.000). The Cookbook calls it a percentage; **fraction vs percent is
  unconfirmed** (noted in `schema.json`). `JOB_DETL_APPT_PCT` = 100 on every row, so actual FTE = FTE × pct / 100 =
  FTE. If real data varies the percent, the canonical FTE needs the product.
- Supervisor columns: v2 `SUPERVISOR_PERS_ID` (CLEAN only; longitudinal has none) becomes
  `SUPV_EDW_PERS_ID` + `SUPV_POSN_NBR` + `SUPV_JOB_SUFFIX`. The job is the supervisor's primary active job on the
  row's effective date, else their latest earlier job, else their first job. All 10,494 CLEAN supervisor references
  resolve to existing jobs.
- **Change reasons** (`JOB_DETL_CHG_REASON_CD`/`DESC`). Computed on the current-knowledge chain and copied to the
  row's other versions:
  - first job of a person: `HR001` New Hire, or `HR002` Rehire after a separation or gap;
  - new job the day after another ends: a promotion code when the job-progression level rises in the same ladder
    (`OT010` CS, `FA002` faculty, `PR001` AP), else `OT009` Campus Transfer or `OT012` Lateral Transfer;
  - concurrent added job: `JB001`;
  - Active → Terminated: `EJ002` resignation (TQ), `SP003` retired (TR), `EJ001` end job (TE, and the old job of an
    internal move);
  - class change in place: `RC001` (CS), `FA002`, or `PR001` when the level rises, else `RC003`;
  - org change: `OT013`; FTE change: `FT001`; pay change: `SA001`; reactivation: `RA001`.

  `SA001`, `JB001`, `PR001` and `RA001` are **synthetic codes** (only the SA/JB families are public); the others are
  kb120563 codes. **Real codes must be confirmed.**

  Counts on the current-knowledge chain:

  | Code | longitudinal | CLEAN |
  |---|---:|---:|
  | HR001 | 2,302 | 1,500 |
  | HR002 | 0 | 150 |
  | OT010 / PR001 / FA002 (promotion) | 626 / 178 / 0 | 0 / 23 / 15 |
  | OT012 / OT009 | 422 / 236 | 156 / 0 |
  | EJ002 / SP003 / EJ001 | 972 / 36 / 1,939 | 210 / 206 / 413 |
  | SA001 | 13,546 | 12,898 |
  | JB001 | 0 | 61 |
  | none | 57 | 2,143 |

  Longitudinal planted 1,467 internal moves. Promotions and transfers total 1,462 here, and the integration layer
  counts 1,396 internal moves inside its 20-year flow window. HR001 = 1,928 planted hires plus the initial stock.
- Job type P/O/S is not a Cookbook column. It is kept per job in `X_JOB_CONTRACT_TYPE`.

### T_EMPEE_HIST and T_EMPEE_HIST_5
- **Termination** moved here: `TERMN_REASON_CD`/`DESC` and `EMPEE_TERMN_DT` sit on the status-T row that starts on
  the termination date (all 1,480 / 612 v2 separations).
  - `EMPEE_RET_IND = Y` iff the reason is TR or TF, or the E-Class is TR (Cookbook rule).
  - `T_EMPEE_HIST_5` holds the same key and termination values (tested equal) plus the org ancestor path
    (`CAMPUS_LEVEL_1_CD` … `DEPT_SUB_ORG_LEVEL_8_CD`) from the synthetic tree.
- `EMPEE_STATUS_CD`: A, B, F (Cookbook) and **T, a synthetic and unconfirmed letter** for terminated.
- Leave of absence: 48 / 40 people (3%) have one Active row split into A / leave / A. The leave row is B (60%) or
  F (40%), 60–180 days long, with `EMPEE_LEAVE_REASON_CD` (synthetic codes FM/PL/ML/SB) and
  `EMPEE_LOA_FROM_DT`/`TO_DT` equal to the row's dates. Job records are unchanged during leave.
- `EMPEE_FTE` and `EMPEE_ANNL_SAL` are sums over the person's Active, current-knowledge jobs (excluding suffix CE;
  salary × appt pct / 100). They are evaluated on the row's reference date: the extract date for current rows, the
  last effective day for expired rows, and the effective date for future rows.
- Service dates:
  - `FIRST_WORK_DT` = first job effective date;
  - `FIRST_HIRE_DT` = the earlier of v2's first hire and first work;
  - `CUR_HIRE_DT` = `ADJ_SVC_DT` = start of the latest employment spell, or the first hire date while still in the
    first spell;
  - `UNIV_SNRTY_DT` = first hire;
  - `ORIG_STATUS_HIRE_DT` = first civil-service job;
  - `LAST_WORK_DT` (T rows only) = last active job day on or before termination.
- `EMPEE_GROUP_CD` (VARCHAR2(4), a different field from the job's 1-character group) uses synthetic CS/AP/FA/GA.
- 10 / 6 `D` rows: Active rows keyed with a wrong effective date and deleted.
- NULL by rule: `E_VERIFY_CASE_NBR`, `CASE_NBR_ENTRY_USER_ID`, `CASE_NBR_ENTRY_DT`, `HIRETOUCH_ID`,
  `E_VERIFY_EFF_DT`, `SURS_LAST_UPDATE_CHG_ID`, `SURS_ENTR_EDW_PERS_ID`, `SURS_ENTR_FULL_NAME`,
  `SURS_UPDATE_NOTE_TXT`, `EMPEE_USER_ID`. `SURS_MAX_ANNL_EARNS_AMT` (max job salary) and the 40% threshold are set
  on TR rows only.

### T_POSN_HIST
- Key `POSN_NBR` + `POSN_HIST_EFF_DT`, from v2's position versions.
- **No org column** (Cookbook). v2's `POSN_ORG_CD` was dropped. The integration layer derives a position's org from
  its jobs (see below). `COA_CD` keeps the chart.
- Status A/C/F/I. v2's Inactive (abolished) versions with no filled job became Cancelled (50%) or Frozen (25%), or
  stayed Inactive (25%): longitudinal 103 C / 53 F / 41 I, CLEAN 397 C / 183 F / 210 I. None has a current filled
  job (tested). Active counts are unchanged.
- `OPEN_POSN_IND` = `Y` iff no Active, current-knowledge job fills the position on the version's reference date
  (extract date, or the last effective day). This is tested.
- `POSN_END_DT` is set only for term positions (CLEAN overload `O*` positions and graduate-assistant positions:
  285 rows). It is the last job end, or 2027-05-15 when still open. Longitudinal has no overload or
  graduate-assistant positions, so none.
- `PAPE_CIV_SVC_ID` (**value format to confirm**):
  - civil-service classes carry the 4-digit SUCSS code;
  - academic-professional local classes (`BA` positions) get the public PAPE codes 49901–49920 in class order;
  - faculty and GA get NULL.
  `PAPE_CIV_SVC_ID_DESC` is the SUCSS title or "PAPE standard title nnnnn (synthetic)".
- `POSN_JOB_PRGS_CD` (`JPnnn`): career ladders.
  - Longitudinal: role family, ordered by `ROLE_LEVEL` (11 ladders).
  - CLEAN SUCSS classes: title series stem, ordered by trailing roman level (750 ladders).
  - Local classes use fixed ladders: AP coordinator/specialist → assistant director → associate director →
    director → associate dean → dean; faculty lecturer → assistant → associate → professor → endowed; GA.
  The ladder levels are in `REF_PCLS_SUCSS_XWALK.JOB_PRGS_LEVEL_NBR` and drive the promotion change reasons.
- `POSN_MIN_SAL`/`MAX_SAL` are the class range, and `POSN_MIDPT_SAL` is their mean. `POSN_SAL_RANGE_TYPE_DESC`
  is `Annual`.
- `POSN_APPT_PCT` (NUMBER(5,4), a fraction) is v2 budget FTE.
- `POSN_DESC_UPDATE_DT` is extract minus 0–10 years (MD5 of the position), not before the position began. 45% /
  48% are older than 5 years ("stale").
- `SUPV_POSN_NBR` is the supervisor position of the position's primary job.
- Exempt `N` and seniority `Y` for civil service. Salary table: open range EA/CA/DA by campus (public codes; System
  Offices → EA is synthetic) and `Open Range` for civil service.

### T_PERS_HIST
- **NULL in every row (no fake values):** UIN, SSN, all name and search-name fields (incl. preferred, prefix,
  suffix), NON_UIN_UNIQUE_ID, BIRTH_CITY/STATE, marital status, legacy, and the verifier/verification fields. Also
  left NULL: AGE_AT_DEATH, citizenship indicator, special disabled veteran, armed forces medal, separation date,
  pronouns.
- Populated:
  - BIRTH_DT (v2), and AGE on current rows only (age at the extract date);
  - SEX (v2 longitudinal; CLEAN synthetic 52/48);
  - GENDER (synthetic codes W/M/NB);
  - citizenship: AS/NR/RA → International, UC → Not Reported (Cookbook); CZ/PR → Domestic (synthetic codes);
  - race/ethnicity indicators and `MULT_RACE_IND`;
  - `RACE_ETH_RPT_CD`/`DESC`, by the documented hierarchy: 9 for AS/NR/RA, U for UC, H if Hispanic, M if more than
    one race, else the single race 1–5, else U;
  - `IPEDS_RACE_ETH_CATGRY` (same code, synthetic);
  - veteran class N/P/O (synthetic);
  - `PERS_CONFIDENTIALITY_IND` (1% Y).
- v1's race groups G1/G2/G3/G4 are mapped to 5/3/H/2 (synthetic). On top of that: 3% international, 2% unknown,
  3% multi-race, 1% AIAN, 1% NHPI. Every code U, 9, H, M, 1–5 occurs in both sets.
- The mapping marks demographics `role: restricted_fairness_only`. They never appear in canonical views.

### T_PAYR_ACCTG_DETL (CLEAN)
- **Regenerated from v3 jobs, so it has more rows than v2.** It covers v2's window (2024-11-30 to 2026-10-31),
  with one earnings row per Active job version in force at each pay-period end.
  - Monthly for MO jobs. Biweekly for BW jobs: 26 periods per calendar year; period k ends Jan 1 + 14k − 1; period
    26 ends Dec 31.
  - The amount is the job's `PAY_PERD_SAL`.
- Extra events, which net out. `PAYR_ACCTG_EXPS_AMT` per job-period always equals the job's annual / pays-per-year
  (tested):
  - 129 voids, each a V row plus an I reissue;
  - 108 J corrections of an original keyed +50.00;
  - 112 encumbrance + liquidation pairs, with `PAYR_ACCTG_ENC_AMT` netting to 0.
- No deduction rows; `PAYR_ACCTG_BNFT_DED_*` and `DED_TYPE` are NULL.
- Full C-FOAPAL, with `ORG_CD` and `COA_CD` from the job.
  - Fund: prefix 1 state / 2 local / 4 grant (public rule), with a synthetic tail.
  - Accounts 999100 (academic) / 999200 (CS), program 999000 (synthetic).
- Funding: 35% of AP positions and 25% of GA positions are grant-funded, with grant codes `SYNG00001`–`SYNG00060`
  (clearly fake). The rest are State Appropriations (60%) or Local Funds (40%).
- `FY_CD` is the Illinois fiscal year (ends Jun 30). `PAYR_EVENT_TYPE_CD` is C/V/I/J. `EDW_VPD_NBR` = 1.
  `PAYR_ACCTG_EFF_DT` = pay-period end (**meaning unconfirmed**). `PAYR_ACCTG_CATGRY_CD` E/C letters are synthetic.

## Synthetic value lists (everything not Cookbook-listed or public)

The following are synthetic:
- P-Class `Y####`;
- the campus code being equal to the chart code;
- campus, college, department and admin names;
- admin units U?A/U?B;
- salary grade (= SUCSS code) and salary group `FY####`;
- leave-category descriptions;
- EEO skill codes 30/40 (12/22/23 are Cookbook);
- work-location descriptions 2 and 5 (1/3/4 Cookbook);
- `JOB_DETL_UNIV_AFFL_IND` = Y;
- change codes SA001/JB001/PR001/RA001;
- employee status T;
- employee group CS/AP/FA/GA;
- benefit categories B1/M1/M4;
- FLSA C/N assignment;
- HR campus U0–U3;
- leave reasons FM/PL/ML/SB;
- `POSN_GROUP_CD`;
- the PAPE assignment;
- job-progression codes;
- citizenship CZ/PR;
- gender codes;
- veteran codes;
- payroll accounts, programs and fund tails;
- grant codes;
- payroll category letters;
- REG earn code;
- VPD 1.

Public code domains (`integration/edw_public_reference/code_domains.yaml`): E-Class and descriptions, leave categories,
termination codes, job-change codes (kb120563), pay IDs BW/MO, salary tables EA/CA/DA, COA 1/2/4/9, PAPE 49901–49920.

## Integration layer

- `integration/edw_mapping_cookbook.yaml` has the same concepts as the other mappings.
  - Fields on the six Cookbook tables are `provenance: verified_dictionary` with a `cookbook:` reference and a
    `value_note` where values are unconfirmed.
  - Non-verified tables keep `assumed_synthetic_layout` with the `public_*` keys.
  - New appointment fields:
    - change reason code/description, status description;
    - campus/college/department, admin level 2;
    - supervisor position and suffix;
    - P-Class, E-Class, employee group, civil-service indicator;
    - appointment percent, current-info indicator;
    - history effective date (`recorded_start`), post date, data status, data expiration date;
    - pay-period salary, pay count, rate, title.
- **SUCSS bridge.** The canonical class key for jobs and positions is `PAPE_CIV_SVC_ID` when it is 4 digits
  (primary), else `REF_PCLS_SUCSS_XWALK` (fallback), else the P-Class itself (local classes).
  - All 34 / 40 SUCSS P-Classes on jobs resolve through the PAPE bridge; the fallback is unused in this data.
- `separation` reads `T_EMPEE_HIST`. `separation_secured` reads `T_EMPEE_HIST_5`, the alternative for restricted
  roles; the termination sets are tested equal.
- `payroll_line` uses the Cookbook payroll names, including `grant_code` and `funding_source`. This is the
  `hr_labor_dist` side of `sponsored_funding/hr_join_design.sql`.
- `mapping.py` (backward compatible; v1/v2 mappings unchanged):
  - `recorded_time.mode`:
    - `lineage_next`: known_to = the next `JOB_DETL_HIST_EFF_DT` in the PK lineage; D rows end at their post date;
    - `post_date`: rows updated in place, known from their post date;
  - field `derive`: an ordered COALESCE over same-row columns and unique-key reference lookups; a non-unique lookup
    is a resolution problem;
  - role `restricted_fairness_only`, hidden like `restricted`.
  - A fixture with late-keyed corrections and a deletion tests the as-known reconstruction.
- `build_integrated.py`:
  - When the position concept has no org, a snapshot position's org comes from its jobs as known at `known_as_of`.
    That is the latest job effective on or before the as-of date, else the earliest job, else the campus org of the
    position's `COA_CD`.
  - New optional table `bench_funding_mix_role_family_campus`: share of salary expense by funding source × role
    family × campus. It is built only when payroll has a funding source; v1/v2 outputs are unchanged.

## Proof: integration build, v2 (public mapping) vs v3 (Cookbook mapping), latest snapshot 2026-06-30

v2 output equals v1 (tested in `test_public_reference.py`). All 18 exported tables have equal row counts except
`dim_org_external`.

| Headline | longitudinal v2 = v3 | CLEAN v2 = v3 |
|---|---|---|
| Position snapshot rows / filled / vacant / incumbents (latest) | 1,051 / 813 / 46 / 813 | 1,896 / 1,079 / 50 / 1,079 |
| Snapshot rows, vacancies and incumbents by campus, every year | equal | equal |
| Distinct people (headcount, latest) | 813 | 1,035 |
| External hires / rehires / internal moves / separations (all years) | 1,822 / 0 / 1,396 / 1,389 | 1,343 / 143 / 760 / 610 |
| Separations: resignation / retirement / end of appointment | 905 / 34 / 450 | 201 / 198 / 211 |
| Class → SUCSS (exact / local) | 34 / 4 | 881 + 1 title-resolved / 17 |
| Headcount reaching a SUCSS record / SOC | 83.0% / 78.0% | 46.4% / 44.0% |
| Market-ratio coverage (local / IL), appointment events by year and type, class external facts | equal | equal |

Differences, all intended:
1. `dim_org_external` has 58 rows (+6 admin-level-2 units), and `org_depth` is one deeper below the campus.
2. `fact_position_snapshot` (same rows and counts) differs only in three ways:
   - new position ids;
   - `position_status_code` I → C/F, which are still inactive, so vacancy is unchanged;
   - the org of 24 / 75 snapshot rows: vacant positions that no job had filled yet as known at that date. Their org
     falls back to the campus org of the position's chart, and their campus is unchanged.
3. CLEAN `fact_flows_year.surs_retirement_ind`: 198 instead of 301. v2's CLEAN `SURS_RETIR_IND` was set independently
   of the reason (TQ and TE rows were flagged). v3 uses the Cookbook `EMPEE_RET_IND` (TR/TF), so the flag equals the
   retirements.
4. New CLEAN table `bench_funding_mix_role_family_campus` (110 rows). Salary expense in the window: State
   $102.0M, Local $61.3M, Grant $23.3M (synthetic).

`TestIntegrationV2vsV3` asserts every one of these. It also checks that the single-database route
(`HR_EDW_DATA=.../CLEAN/sample.duckdb`) gives identical hashes.

## succession_models on v3 (not run; nothing in succession_models was changed)

`succession_models/extract.py --edw-dir sample_datasets/v3_cookbook/longitudinal` fails at bind time. `extract.sql`
hard-codes v1 names (`JOB_CONTRACT_TYPE_CD`, `JOB_FTE`, `ROW_REC_*`, `TERM_DT` …), and `config.SOURCE_MAP` is a module
constant. To point it at v3, Codex would change:

- **extract.sql**, per table:
  - `T_PERS_HIST`: `PERS_EFF_DT` → `PERS_HIST_EFF_DT`.
  - Job type: v3 has no `JOB_CONTRACT_TYPE_CD`. Join `X_JOB_CONTRACT_TYPE` (synthetic), or use the primary-job rule
    on real data.
  - Protected attributes: `RACE_ETH_CD` → `RACE_ETH_RPT_CD`, plus `GENDER_CD`. Read only by the fairness audit.
  - Termination: from `T_EMPEE_HIST` (`EMPEE_TERMN_DT`, `TERMN_REASON_CD`, `EMPEE_RET_IND`), or `T_EMPEE_HIST_5` for
    restricted roles.
  - Job columns: `JOB_DETL_STATUS_DESC`, `JOB_DETL_FTE`, `JOB_DETL_ANNL_SAL`, `JOB_DETL_POSN_CLS_CD` (+ SUCSS via
    `T_POSN_HIST.PAPE_CIV_SVC_ID`), `ORG_CD`.
  - Positions: `POSN_HIST_EFF_DT`/`EXP_DT`, `POSN_STATUS_CD`, org derived from jobs.
  - `REF_JOB_CLASS` → `T_POSN_CLS_HIST`.
  - Recorded time for jobs: emit `JOB_DETL_HIST_EFF_DT AS ROW_REC_START_DT` and `LEAD(JOB_DETL_HIST_EFF_DT) OVER
    (PARTITION BY EDW_PERS_ID, POSN_NBR, JOB_SUFFIX, JOB_DETL_EFF_DT ORDER BY JOB_DETL_HIST_EFF_DT)` (or the post date
    for `D` rows) `AS ROW_REC_END_DT`, which is ANSI. For the update-in-place tables, emit the post date as start and
    9999-12-31 as end.
- **config.SOURCE_MAP**:
  - set the right-hand sides above;
  - `term.file` → `T_EMPEE_HIST`, `term_dt` → `EMPEE_TERMN_DT`, `surs_retir_ind` → `EMPEE_RET_IND`;
  - `job.status_cd` → `JOB_DETL_STATUS_DESC`, with model code comparing to 'Active'/'Terminated' instead of A/T,
    which is a model-side change;
  - keep `bitemporal: True` with the derived `rec_cols`.

## What to fill in next

T_JOB_DETL_HIST, T_EMPEE_HIST, T_EMPEE_HIST_5, T_POSN_HIST, T_PERS_HIST and T_PAYR_ACCTG_DETL are now
Cookbook-shaped. Still to do:

1. **Reference tables** (class/P-Class table, E-Class, org hierarchy, job-change and termination code tables):
   - replace `T_POSN_CLS_HIST`/`REF_ORG`/`REF_EMPEE_CLS` with their Cookbook layouts;
   - check whether `T_POSN_CLS_HIST` is keyed by the 5-character P-Class (likely);
   - replace the synthetic code lists marked above;
   - confirm how the P-Class relates to the SUCSS class code.
2. **PAPE_CIV_SVC_ID values**: confirm that civil-service positions hold the 4-digit SUCSS code. Then retire
   `REF_PCLS_SUCSS_XWALK`.
3. **Job type / primary job**: find the table that holds job type P/O (Banner NBRBJOB) and replace `X_JOB_CONTRACT_TYPE`.
4. **Labor distribution / position funding**: the source for a position's org and the sponsored-funding join, if not
   payroll.
5. **SURS**: tier and service credit (not on T_EMPEE_HIST). The succession SURS rules are still assumptions.
6. **Confirm on data**:
   - FTE fraction vs percent;
   - meaning of `JOB_DETL_HIST_EFF_DT` vs `JOB_DETL_EFF_DT`;
   - the employee terminated status letter;
   - exact `*_DATA_STATUS_DESC` spellings;
   - `PAYR_ACCTG_EFF_DT`;
   - payroll category letters;
   - leave status descriptions on `JOB_DETL_STATUS_DESC`;
   - whether `JOB_DETL_APPT_PCT` varies.
