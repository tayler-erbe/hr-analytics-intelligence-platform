# Public HR data lake

A reproducible, versioned lake of **public** workforce and labor-market data, built once and loaded identically into a local DuckDB stack, Snowflake and Databricks. It is the shared fixture for the platform comparison and the external evidence layer for HR decision support. It holds no university employee data.

Built 2026-11-06: **80 silver tables (8.3 million rows, 211 MB of Parquet), 11 gold views, and 23 contract tables** for the platform kits ([CONTRACT.md](CONTRACT.md)). Counts per table are in [manifests/silver_manifest.json](manifests/silver_manifest.json).

## Run it

```bash
pip install duckdb pyarrow openpyxl
python scripts/lake_acquire.py        # download raw files and hash them (~300 MB, under 1 minute on a good link)
python scripts/lake_build.py          # raw -> silver Parquet -> DuckDB catalog with gold views (~2 minutes)
python scripts/lake_contract.py       # silver -> contract tables the Snowflake/Databricks kits load
python -m unittest scripts/test_lake.py -v
```

Run from `platform-evaluation/`. Raw files, Parquet and the DuckDB file go to `data/lake/`, which Git ignores. Git keeps the registry, manifests, DDL and SQL, so anyone can rebuild the lake and check it against the recorded hashes.

## Layers

| Layer | Location | Contents |
|---|---|---|
| Registry | `lake/sources.json` | Every source file: URL, publisher, license, vintage, grain, tier |
| Raw | `data/lake/raw/<source>/` | Byte-for-byte downloads, never edited. Each attempt is recorded in `manifests/acquisition_manifest.json` with HTTP status, size, SHA-256 and timestamp |
| Silver | `data/lake/silver/<table>.parquet` | One typed table per published file, snake_case columns. Code columns (FIPS, NAICS, UNITID, SOC) stay strings. Suppression and imputation flags are kept |
| Contract | `data/lake/contract/<table>.parquet` | Stable, tidy tables with fixed grains and names, loaded identically by the Snowflake kit, Databricks kit and custom stack. Rules in [CONTRACT.md](CONTRACT.md) |
| Gold | `lake/gold/gold_views.sql` | Analytic views in portable SQL, each with a stated grain, for replay on Snowflake and Databricks |
| DDL | `lake/ddl/` | Generated `CREATE TABLE` statements for Snowflake and Databricks from the same silver schemas |

## What is in it

| Domain | Tables | Use for HR |
|---|---|---|
| O*NET 31.0 (USDOL/ETA) | 45 `onet_*` tables, plus `onet_element_rating` (412K rows across all rating domains) and `onet_soc_crosswalk` | Task, skill, knowledge, work-activity and technology profiles for any role; job zones; alternate titles for title matching |
| IPEDS (NCES), Fall 2023 HR and 2024 directory | `ipeds_s2023_oc`, `_is`, `_sis`, `_nh`, `ipeds_sal2023_is`, `_nis`, `ipeds_eap2023`, `ipeds_hd2024`, `ipeds_ic2024`, `ipeds_effy2024`, `ipeds_value_label`, `ipeds_variable` | Peer staffing mix, new hires, faculty pay by rank and sex, non-instructional pay by occupation group, staff-to-student ratios for every U.S. institution |
| BLS QCEW, annual 2015–2024 and quarterly 2019 Q1–2025 Q4 | `qcew_colleges_annual`/`_quarterly` (NAICS 611310, all areas), `qcew_il_county_annual`/`_quarterly` (Champaign, Cook, Sangamon) | Higher-ed employment and pay trends by ownership; local labor-market competition |
| Census LEHD QWI, Illinois, through 2025 | `qwi_il_*` (5 tables, 3.8M rows) | Hires, separations and turnover for Illinois colleges and universities (NAICS 6113), by quarter, age, sex, race and education, back to 1993 |
| Indeed Hiring Lab | `indeed_*` | Daily posting-index trends by sector, state and metro (Chicago only; Champaign and Springfield metros are too small to be covered) |
| Anthropic Economic Index | `aei_*` | Observed AI usage by O*NET task and SOC occupation, kept as evidence and never presented as a displacement forecast |
| Illinois SUCSS | `sucss_class`, `sucss_onet_candidate` | Civil-service class catalog and unreviewed title-match suggestions |

The University of Illinois System is identified in IPEDS by UNITIDs 145637 (UIUC), 145600 (UIC), 148654 (UIS) and 149587 (System Offices). These were confirmed from `ipeds_hd2024`.

## Gold views

| View | Grain | Answers |
|---|---|---|
| `gold_institution_panel` | institution | The U of I campuses plus a proposed peer panel of 15 Big Ten publics (not an approved HR peer group) |
| `gold_ipeds_staff_by_occupation` | institution × staff category | Fall 2023 headcount by occupation, full/part time, men/women |
| `gold_ipeds_noninstructional_pay` / `gold_peer_noninstructional_pay` | institution × occupation group | Full-time staff count, salary outlays and average salary |
| `gold_ipeds_faculty_pay` | institution × academic rank | Nine-month-equated average salary by sex, and the raw women-to-men ratio (unadjusted, not a pay-equity finding) |
| `gold_qcew_higher_ed_trend` | area × ownership × year | Illinois and U.S. college/university employment and pay. Suppressed cells are NULL |
| `gold_qwi_il_higher_ed_flows` (`_by_age`) | quarter (× age group) | Illinois higher-ed hires, separations, stable turnover rate and earnings; the age profile of separations |
| `gold_occupation_profile` | O*NET occupation | Job zone, SOC 2018 code, task counts, observed AI exposure |
| `gold_task_ai_evidence` | O*NET task | Task-level AI usage metrics, kept side by side rather than combined into a score |
| `gold_sucss_onet_candidates` | SUCSS record × candidate | Candidate O*NET matches for civil-service classes, labeled unreviewed |

## Known gaps

- **BLS OEWS, Employment Projections and JOLTS** are registered but not downloaded. BLS file servers return HTTP 403 unless the User-Agent includes a contact email. To enable them, set an environment variable with your own contact details and rerun:
  ```bash
  BLS_USER_AGENT="hr-analytics-lab your.name@illinois.edu" python scripts/lake_acquire.py --only bls_oews bls_projections bls_jolts
  ```
  Silver tables for these sources are not written yet.
- **Anthropic Economic Index 2026-06-26 release** (219 MB). The download redirects to a CDN host the session network does not allow, so it is recorded as failed. The smaller task and occupation files are loaded.
- **Census API** sources (ACS, the QWI API) now require a key passed in the URL. QWI comes from LEHD bulk files instead, which need no key.
- **IPEDS 2024 HR** files (S2024, SAL2024, EAP2024) return 404 on the NCES server as of 2026-11-06. Fall 2023 is the latest HR collection loaded.
- **QWI ownership:** the Illinois files carry all-ownership (A00) only, so state-university flows cannot be separated from private colleges in this source. QCEW ownership splits fill that gap for employment and pay.
- Latest quarters of QWI are partially published (for example, 2025-Q4 separations are NULL). Treat the trailing two quarters as provisional.

## Rules

Public data only. Do not add university employee, payroll or org-chart exports here: those belong in `data/local/` on approved machines. Keep the raw layer immutable. Change a gold definition by editing the SQL and rerunning the tests; record anything that changes reported numbers.

## Attribution

O*NET 31.0 Database by USDOL/ETA, used under CC BY 4.0; O*NET is a trademark of USDOL/ETA. IPEDS (NCES), QCEW (BLS) and QWI (U.S. Census Bureau LEHD) are U.S. federal public data. Indeed Hiring Lab data and the Anthropic Economic Index are each used under their published licenses (CC BY 4.0 per their repositories; verify before republishing).
