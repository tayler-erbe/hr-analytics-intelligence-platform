# Lake contract v1.1

The contract layer (`data/lake/contract/<table>.parquet`, built by `scripts/lake_contract.py`) is the **one input** the Snowflake kit, the Databricks kit and the custom stack load. Silver tables mirror each publisher's file layout. The contract fixes table names, grains and column names so the same business question means the same thing on every platform.

Generated table definitions: [`ddl/snowflake_contract_tables.sql`](ddl/snowflake_contract_tables.sql), [`ddl/databricks_contract_tables.sql`](ddl/databricks_contract_tables.sql). Exact column lists and row counts: [`manifests/contract_manifest.json`](manifests/contract_manifest.json).

## Tables

| Table | Grain | Rows | Vintage |
|---|---|---:|---|
| `onet_occupation` | O*NET-SOC occupation | 1,016 | O*NET 31.0 |
| `onet_task_statement` | occupation × task | 18,838 | O*NET 31.0 |
| `onet_task_rating` | occupation × task × scale (× category) | 165,780 | O*NET 31.0 |
| `onet_element_rating` | domain × occupation × element × scale | 411,893 | O*NET 31.0 |
| `onet_technology_skill` | occupation × technology example | 31,821 | O*NET 31.0 |
| `onet_alternate_title` | occupation × alternate title | 54,269 | O*NET 31.0 |
| `onet_job_zone` | occupation | 923 | O*NET 31.0 |
| `onet_soc_crosswalk` | O*NET-SOC × SOC 2018 | 1,016 | O*NET-SOC 2019 to SOC 2018 |
| `sucss_class` | SUCSS catalog record (class 1164 has two records) | 883 | acquired 2026-10-29 |
| `sucss_onet_candidate` | SUCSS record × candidate occupation (unreviewed) | 2,649 | title_lexical_baseline_v1 |
| `ipeds_institution` | institution (unitid) | 6,072 | HD2024 |
| `ipeds_staff_by_occupation` | unitid × staff category × sex × race/ethnicity | 5,407,980 | S2023_OC (Fall 2023) |
| `ipeds_instructional_staff` | unitid × instructional category × sex × race/ethnicity | 1,911,960 | S2023_IS (Fall 2023) |
| `ipeds_new_hires` | unitid × new-hire category × sex × race/ethnicity | 1,234,230 | S2023_NH (Fall 2023) |
| `ipeds_salary_instructional` | unitid × academic rank × contract length (9/10/11/12-month) | 45,928 | SAL2023_IS (2023-24) |
| `ipeds_salary_noninstructional` | unitid × occupation group (13 groups) | 51,493 | SAL2023_NIS (2023-24) |
| `ipeds_employees_by_position` | unitid × position category (category × faculty status) | 288,192 | EAP2023 (Fall 2023) |
| `ipeds_enrollment_12mo` | unitid × student level | 115,026 | EFFY2024 (2023-24) |
| `qcew_industry` | area × ownership × size × year × quarter, NAICS 611310 | 91,368 | 2019Q1 onward |
| `qcew_area` | county × ownership × industry × size × year × quarter | 149,984 | 2019Q1 onward |
| `qwi_higher_ed` | Illinois × NAICS 6113 × sex × age group × quarter | 3,537 | LEHD latest_release |
| `aei_task_usage` | task text × release | 21,363 | release_2025_03_27 + labor_market_impacts |
| `aei_occupation_exposure` | SOC 2018 occupation | 756 | labor_market_impacts |

Not yet published (kits skip them and log a limitation): `bls_oews`, `bls_projections` (BLS requires a contact User-Agent), `acs_county_labor` (Census API key).

## Rules every consumer must follow

1. **Provenance.** Every table has `source_id` and `source_vintage`. Carry them into results.
2. **Codes are strings.** UNITID, FIPS, NAICS, SOC, O*NET-SOC, SUCSS class codes and QWI demographic codes keep leading zeros.
3. **IPEDS totals.** The long IPEDS HR tables include published total rows: `sex = 'Total' AND race_ethnicity = 'Total'`. Detail rows sum exactly to them.
4. **No double counting across categories.** In `ipeds_staff_by_occupation`, `ipeds_employees_by_position`, `ipeds_instructional_staff` (rank detail 101–106 plus 500, without faculty status) and `ipeds_new_hires` (faculty-status detail plus occupation groups), rows with `is_category_total = false` form an exact partition of the institution total. This was verified for every institution (17,192 staff totals, 5,924 position totals, 3,552 instructional totals and 3,324 new-hire totals, 0 mismatches). Contract 1.1 corrected the instructional-staff and new-hire flags, which in 1.0 did not form a partition. Filter on it before summing across categories. `ipeds_staff_by_occupation.category_level` distinguishes `total`, `group`, `detail`, `subdetail` and `graduate_assistant`. Graduate assistants are outside the IPEDS grand total.
5. **Salary tables are pre-partitioned.** `ipeds_salary_noninstructional` excludes the all-occupations row; `ipeds_salary_instructional` excludes the all-ranks row. Summing `staff_count` and `salary_outlays` over categories reproduces the published institution totals exactly. Average salary = outlays ÷ count, computed only where count > 0.
6. **Suppression stays NULL.** QCEW cells with `disclosure_code = 'N'` have NULL measures. QWI status flags (`s_*`) are kept. Never coalesce suppressed values to zero.
7. **QCEW overlap.** `qcew_area` (county files, all industries) contains the county rows for NAICS 611310 that also appear in `qcew_industry`. Exclude `industry_code = '611310'` from `qcew_area` when unioning them.
8. **QWI scope.** `qwi_higher_ed` is statewide Illinois, NAICS 6113, all ownerships (`A00`): public and private colleges combined. Totals are `sex = '0' AND agegrp = 'A00'`. The two most recent quarters are partially published.
9. **Unreviewed mappings.** `sucss_onet_candidate` rows are lexical title suggestions with `review_status`; `score`/`title_similarity` is not a probability or an allocation weight.
10. **AI usage is evidence, not prediction.** `aei_*` tables describe observed Claude usage by task and occupation. Do not combine them into a job-loss score.

## Changing the contract

Bump the version, rebuild, and rerun `python -m unittest scripts/test_lake.py`. A change that alters any reported number on a platform must be applied to all three implementations before they are compared.
