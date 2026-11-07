# Loading the WAP star into the existing Power BI stack

Short handover for the AITS reporting-stack owner. Everything here follows
[`../../delivery/POWER_BI_CONTRACT.md`](../../delivery/POWER_BI_CONTRACT.md) (`wap-star-v1`); nothing new is introduced.
The folder is produced by `python -m wap_prototype.publish_star.assemble` and must pass
`python wap_prototype/delivery/validate_star_schema.py wap_prototype/star` (exit 0) before a refresh runs.
On this synthetic build the validator reports `PARTIAL` until the Phase 2 model facts land (see `export_manifest.json`
`validator.status`); a refresh must not run on a `PARTIAL` or `FAIL` folder.

## 1. Files to load (`wap_prototype/star/`, CSV or Parquet, one per table)

| File | Load as | Rows (synthetic build) | Notes |
|---|---|---:|---|
| `dim_date.csv` | `dim_date` | 56 | mark as date table on `date`; add a second query `dim_origin_date` from the same file |
| `dim_org.csv` | `dim_org` | 51 | hierarchy campus_name -> college_name -> dept_name; `org_code` is an extra natural key (hide) |
| `dim_role.csv` | `dim_role` | 39 | add `dim_role_to` as a second query from the same file; `class_key` is an extra natural key (hide); role_key 0 = external sink |
| `dim_role_family.csv` | `dim_role_family` | 12 | role_family_key 0 = EXTERNAL |
| `dim_model_version.csv` | `dim_model_version` | 1 (+ model versions) | `is_published_default` page filter |
| `dim_scenario.csv` | `dim_scenario` | 6 | `is_default` page filter |
| `fact_headcount_quarter.csv` | fact | 20,945 | quarter x dept x role |
| `fact_transitions_quarter.csv` | fact | 2,697 | quarter x origin college x from-role x to-role x type |
| `fact_external_context.csv` | fact | 38 | public mode |
| `fact_promotion_expectation.csv` | fact | from Model A | absent until Phase 2 publishes |
| `fact_attrition_forecast.csv` | fact | from Model B | absent until Phase 2 publishes |
| `fact_attrition_risk.csv` | fact | from Model B | absent until Phase 2 publishes |
| `fact_model_quality.csv` | fact | from A and B | absent until Phase 2 publishes |
| `export_manifest.json` | not loaded | | `data_as_of`, `run_id`, `protocol_version`, hashes -> dataset description and page footer |

Power Query: `Csv.Document` with `Encoding = 65001`, first row as header, then set types from `star_schema.yaml`
(`int` -> Whole Number, `float` -> Decimal Number, `date` -> Date, `bool` -> True/False, `string` -> Text). Empty
strings are nulls (suppressed measures). Storage mode Import.

## 2. Relationships

`relationships.csv` lists every relationship (all one-to-many, single direction, dimension -> fact). Two copies of
dimensions are used instead of inactive relationships where that is simpler: `dim_origin_date` (origin slicers for
`fact_attrition_forecast[origin_date_key]` and `fact_attrition_risk[origin_date_key]`) and `dim_role_to` (the
to-role axis of the mobility matrix). Keep the inactive `dim_role -> fact_transitions_quarter[to_role_key]`
relationship as well for `[Transitions To Role]`. No bidirectional relationships; facts are never related to each other.

## 3. Measures and calculated columns

`measures.dax` holds every measure and calculated column from the contract, section 2.2-2.3, as text to paste into
the model (one measure per `Name = expression` block). All measures count published cells only; `n` is never summed
on its own; `[Suppressed Cells]` sits next to every total. Summed P10/P90 bands are labelled "sum of cell intervals
(conservative)".

Hide from report view: every `*_key`, `model_version`, `scenario_key`, `suppressed`, `n`, `org_code`, `class_key`.

## 4. Row-level security

1. Create the mapping tables `sec_user_campus (upn, campus_cd)` and optionally `sec_user_org (upn, college_cd)` as
   hidden queries with **no relationship** to the model (maintained by the reporting owner).
2. Modeling -> Manage roles:
   - `System`: no filter.
   - `Campus`: on `dim_org`, `[campus_cd] = LOOKUPVALUE ( sec_user_campus[campus_cd], sec_user_campus[upn], USERPRINCIPALNAME () )`.
   - `College` (optional): on `dim_org`, `[college_cd] IN CALCULATETABLE ( VALUES ( sec_user_org[college_cd] ), sec_user_org[upn] = USERPRINCIPALNAME () )`.
3. `dim_model_version`, `dim_scenario`, `fact_model_quality` and `fact_external_context` are not row-filtered.
4. Test with "View as" for one campus user on every page of `dashboard_spec.md`; keep the screenshots as rubric evidence.
   Suppression is applied before publication, so RLS never reveals a cell below k = 10.

## 5. Dataset settings and refresh

- Mark `dim_date` as the date table; sensitivity label Internal (no personal data by construction).
- Dataset description = `protocol_version`, `data_as_of`, `run_id` from `export_manifest.json`; every page footer carries
  the text in `dashboard_spec.md` section 0.
- Page-level defaults: `dim_model_version[is_published_default] = TRUE`, `dim_scenario[is_default] = TRUE`, latest `data_as_of`.
- Scheduled refresh the business day after the folder passes validation; a folder that fails (or is `PARTIAL`) must not
  be refreshed, the previous dataset stays live and the failure is logged.
- The offline prototype of the five pages (`output/wap_prototype/wap_dashboard.html`) is the visual reference for the report.

## 6. Keys the model builders use

`date_key` = YYYYMMDD; `org_key` = numeric part of the org code (U111 -> 111); `role_key` = 1.. in (e_class, p_class)
order with 0 = EXT; `role_family_key` = 1.. alphabetical with 0 = EXTERNAL; `scenario_key` 1..6 = primary, base_step,
base_family, snaive, ets, no_external. The assembler also accepts natural keys in the model facts and maps them.
