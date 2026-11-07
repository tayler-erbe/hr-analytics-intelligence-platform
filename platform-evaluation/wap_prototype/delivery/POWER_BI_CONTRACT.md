# Power BI delivery contract: Workforce Analytics Intelligence Platform

**Contract version:** `wap-star-v1` (machine-readable form: [`star_schema.yaml`](star_schema.yaml); checker: [`validate_star_schema.py`](validate_star_schema.py)).
**Protocol:** [`../protocol/MODEL_PROTOCOL_v1.md`](../protocol/MODEL_PROTOCOL_v1.md) (`wap-protocol-v1`).
**Audience:** the Phase 2 model builders (what they must publish), the Phase 3 Power BI author (what they can rely on), and the AITS reporting-stack owner (refresh, security, handover).

Phase 3 builds on the **existing reporting stack**: Power BI Desktop → Power BI Service workspace already used by AITS Decision Support, refreshed from a published-outputs folder (or the equivalent EDW/Denodo schema once the tables are materialised there). No new platform is introduced by this work request.

---

## 1. What Phase 2 must produce

A single outputs folder (`export/` on the approved machine, mirrored to the reporting-stack landing location) containing exactly the tables below, one file each, `<table>.csv` (UTF-8, header, ISO dates, `true`/`false` booleans) or `<table>.parquet`, plus `export_manifest.json` (row counts, suppressed counts, `k_min`, SHA-256 per file, `data_as_of`, `protocol_version`, `run_id`).

`validate_star_schema.py <folder>` must exit 0 before anything is loaded into Power BI. It is part of the publish step, not an optional check.

### 1.1 Table inventory

| Table | Kind | Grain (one row per) | Primary key | Suppression |
|---|---|---|---|---|
| `dim_date` | dim | quarter-end date (history + forecast window) | `date_key` | n/a |
| `dim_org` | dim | org node at every admin level (campus, college, dept) | `org_key` | n/a |
| `dim_role` | dim | position class (`e_class` × `p_class`) with ladder step and SUCSS/O*NET/SOC bridge | `role_key` | n/a |
| `dim_role_family` | dim | job family | `role_family_key` | n/a |
| `dim_model_version` | dim | model version that produced any published row | `model_version` | n/a |
| `dim_scenario` | dim | published comparator scenario | `scenario_key` | n/a |
| `fact_headcount_quarter` | fact | quarter × dept × role | `date_key, org_key, role_key` | k ≥ 10 on `n` |
| `fact_transitions_quarter` | fact | quarter × origin college × from-role × to-role × transition type | 5 keys | k ≥ 10 on `n` and on `n_transitions` (0 < x < 10) |
| `fact_promotion_expectation` | fact | origin quarter × unit × ladder step × horizon × model version × scenario | 6 keys | k ≥ 10 on `n` |
| `fact_attrition_forecast` | fact | origin × target quarter × dept (or campus roll-up) × job family × model version × scenario | 6 keys | k ≥ 10 on `n` (mean headcount) |
| `fact_attrition_risk` | fact | origin quarter × unit × job family × model version | 4 keys | k ≥ 10 on `n` |
| `fact_external_context` | fact | role × vintage quarter | `date_key, role_key` | public (flag always false) |
| `fact_model_quality` | fact | model version × scenario × origin (0 = mean) × horizon (0 = n/a) × metric × attribute | 6 keys | k ≥ 10 on `n` |

Column-level types, nullability and descriptions are in `star_schema.yaml` and are not repeated here. `fact_attrition_risk` is the attrition-risk score the work request asks for, kept as its own fact so the forecast fact stays at one grain.

### 1.2 Grain statements the builders must honour

- **Headcount** is incumbents of primary appointments at the quarter-end snapshot; it is not appointment count and not FTE. `fte_sum` is published beside it. (Rubric: "Headcount differs correctly from appointment count and FTE".)
- **Transitions** are Phase 1 `transition_events` rows aggregated per quarter, keyed by the **origin** unit and the from/to roles; `transition_type` carries the Phase 1 `event_type` (`promotion`, `transfer_lateral`, `transfer_down`, `reclassification`, `separation_<group>`, `retirement`, `hire`, `rehire`). Separations use the external-sink role row in `dim_role` (`p_class = "EXT"`, `role_family = "EXTERNAL"`) as `to_role_key`; external hires use it as `from_role_key`.
- **Promotion expectation** rows exist for every ladder step × unit with ≥ 1 incumbent at the origin (so suppressed rows are visible as suppressed, not missing), for both horizons, for the primary model version and every published scenario.
- **Attrition forecast** rows exist for every modelled series × horizon 1–12. Campus × family rows with `is_bottom_up = true` are sums of dept rows; the directly modelled campus rows carry `is_bottom_up = false` and are published for the hierarchy check only (`fact_model_quality.hierarchy_discrepancy`).
- **Model quality** is long-format. Mean-over-origins rows use `origin_date_key = 0`; non-horizon rows use `horizon = 0`; non-fairness rows use `attribute = "all"`. Keys are never null.
- Every fact row carries `model_version` (descriptive tables use the `DESCRIPTIVE-<yyyymmdd>` version) and `data_as_of`.

### 1.3 Suppression rules (binding)

1. `n` on every k-anonymity fact is the count the cell is based on; `n < 10` → `suppressed = true` and every measure column null. Keys stay.
2. Complementary suppression is applied by the producer within the parent group (unit within college; ladder step within ladder; family within campus) using the succession_models `governance.suppress` rule, so a suppressed cell cannot be recovered by subtraction from a published total. Totals shown on dashboards are therefore computed from **published rows only** and labelled "published cells" (see measures in 3.3).
3. `fact_transitions_quarter`: any `0 < n_transitions < 10` is also suppressed. Zero flows may be published.
4. Nothing keyed by `edw_pers_id`, `posn_nbr`, or carrying sex, race/ethnicity, birth date, ZIP, address or name is ever in the folder. The validator refuses such columns by name; the producer's export gate refuses them by content.
5. Fairness rows in `fact_model_quality` are per-attribute summaries only (`min_impact_ratio`, `max_tpr_gap`, `max_fpr_gap`, `groups_suppressed`, `fairness_flag`). Group-level rows stay in the restricted model card.

### 1.4 Refresh cadence

| Table group | Refresh | Trigger | Owner |
|---|---|---|---|
| `dim_*` | quarterly, with the facts; `dim_role` also when HR updates the ladder or critical-role list | Phase 1 refresh | Phase 1 / HR analyst |
| `fact_headcount_quarter`, `fact_transitions_quarter` | quarterly after EDW quarter close + Phase 1 DQ audit pass | Phase 1 publish | Phase 1 |
| `fact_promotion_expectation` | quarterly re-score; `observed` back-filled as horizons resolve | Model A re-score | Phase 2 |
| `fact_attrition_forecast`, `fact_attrition_risk` | quarterly re-forecast; `*_actual` back-filled | Model B re-forecast | Phase 2 |
| `fact_external_context` | when a public source vintage changes (OEWS annual, BLS projections biennial, O*NET release, AEI release) | source refresh | Phase 1 |
| `fact_model_quality`, `dim_model_version` | every re-score and every retrain (annual or on drift, protocol section 9) | Phase 2 | Phase 2 |
| Power BI dataset | scheduled refresh the business day after the folder passes validation; one refresh per quarter plus ad-hoc after an external-context update | Service schedule | AITS reporting owner |

A refresh that reads a folder which fails `validate_star_schema.py` must not run; the previous dataset stays live and the failure is logged.

---

## 2. Model guide for the Power BI author

### 2.1 Relationships (all single-direction, dimension → fact, one-to-many)

| From (dim column) | To (fact column) | Notes |
|---|---|---|
| `dim_date[date_key]` | `fact_headcount_quarter[date_key]`, `fact_transitions_quarter[date_key]`, `fact_promotion_expectation[date_key]`, `fact_external_context[date_key]` | active |
| `dim_date[date_key]` | `fact_attrition_forecast[target_date_key]` | **active** (forecast charts are by target quarter) |
| `dim_date[date_key]` | `fact_attrition_forecast[origin_date_key]`, `fact_attrition_risk[origin_date_key]` | inactive; use `USERELATIONSHIP` for origin slicers, or add a second date dimension `dim_origin_date` (a copy of `dim_date`) for the origin selector. The second copy is the simpler choice |
| `dim_org[org_key]` | every fact with `org_key` | mark `dim_org` as a hierarchy campus → college → dept using `campus_name`, `college_name`, `dept_name`; `parent_org_key` is for `PATH()` calculations if a ragged hierarchy is needed |
| `dim_role[role_key]` | `fact_headcount_quarter[role_key]`, `fact_promotion_expectation[role_key]`, `fact_external_context[role_key]`, `fact_transitions_quarter[from_role_key]` (active), `fact_transitions_quarter[to_role_key]` (inactive) | for the mobility matrix add `dim_role_to` as a copy of `dim_role` with an active relationship to `to_role_key` |
| `dim_role_family[role_family_key]` | `dim_role[role_family_key]` (snowflake), `fact_attrition_forecast`, `fact_attrition_risk` | |
| `dim_model_version[model_version]` | every fact | default filter: `is_published_default = TRUE` on the page level, exposed as a slicer only on the model-quality page |
| `dim_scenario[scenario_key]` | `fact_promotion_expectation`, `fact_attrition_forecast`, `fact_model_quality` | default filter `is_default = TRUE` |

Do not create bidirectional relationships; do not relate facts to each other. Hide every key column from report view.

### 2.2 Calculated columns (dimension side only)

```DAX
-- dim_date
Quarter Sort = dim_date[calendar_year] * 10 + dim_date[calendar_quarter]

-- dim_role
Ladder Step = IF ( ISBLANK ( dim_role[ladder] ), "Not on a ladder",
                   dim_role[ladder_desc] & " L" & FORMAT ( dim_role[level], "0" ) )
Mapping Caveat = SWITCH ( dim_role[mapping_status],
                   "analyst_confirmed", "", "unreviewed", "O*NET/SOC link unreviewed", "No O*NET/SOC link" )
```

### 2.3 Measures (DAX)

All measures count **published cells only**: suppressed rows have null measures and `n` is never summed on its own. Each page shows `Suppressed Cells` next to any total so readers know the total is partial.

```DAX
-- ---------- descriptive (fact_headcount_quarter)
Headcount = SUM ( fact_headcount_quarter[headcount] )
FTE = SUM ( fact_headcount_quarter[fte_sum] )
Headcount Prior Q = SUM ( fact_headcount_quarter[headcount_prior_quarter] )
Separations = SUM ( fact_headcount_quarter[separations_total] )
Retirements = SUM ( fact_headcount_quarter[sep_retirement] )
Hires = SUM ( fact_headcount_quarter[hires] )
Promotions Out = SUM ( fact_headcount_quarter[promotions_out] )

Suppressed Cells = CALCULATE ( COUNTROWS ( fact_headcount_quarter ), fact_headcount_quarter[suppressed] = TRUE () )
Published Cells  = CALCULATE ( COUNTROWS ( fact_headcount_quarter ), fact_headcount_quarter[suppressed] = FALSE () )

Avg Headcount = DIVIDE ( [Headcount] + [Headcount Prior Q], 2 )

-- quarterly rate; the annualised version multiplies by 4 and is labelled "annualised"
Turnover Rate (Q) = DIVIDE ( [Separations], [Avg Headcount] )
Turnover Rate (4Q) =
    VAR seps = CALCULATE ( [Separations], DATESINPERIOD ( dim_date[date], MAX ( dim_date[date] ), -12, MONTH ) )
    VAR hc   = CALCULATE ( AVERAGEX ( VALUES ( dim_date[date_key] ), [Headcount] ),
                           DATESINPERIOD ( dim_date[date], MAX ( dim_date[date] ), -12, MONTH ) )
    RETURN DIVIDE ( seps, hc )
Retirement Rate (4Q) =
    VAR r = CALCULATE ( [Retirements], DATESINPERIOD ( dim_date[date], MAX ( dim_date[date] ), -12, MONTH ) )
    VAR hc = CALCULATE ( AVERAGEX ( VALUES ( dim_date[date_key] ), [Headcount] ),
                         DATESINPERIOD ( dim_date[date], MAX ( dim_date[date] ), -12, MONTH ) )
    RETURN DIVIDE ( r, hc )
Promotion Rate (4Q) =
    VAR p = CALCULATE ( [Promotions Out], DATESINPERIOD ( dim_date[date], MAX ( dim_date[date] ), -12, MONTH ) )
    VAR hc = CALCULATE ( AVERAGEX ( VALUES ( dim_date[date_key] ), [Headcount] ),
                         DATESINPERIOD ( dim_date[date], MAX ( dim_date[date] ), -12, MONTH ) )
    RETURN DIVIDE ( p, hc )

-- ---------- mobility (fact_transitions_quarter)
Transitions = SUM ( fact_transitions_quarter[n_transitions] )
Transition Rate = DIVIDE ( [Transitions], SUM ( fact_transitions_quarter[n] ) )
Transitions To Role =
    CALCULATE ( [Transitions], USERELATIONSHIP ( dim_role[role_key], fact_transitions_quarter[to_role_key] ) )

-- ---------- Model A (fact_promotion_expectation), primary version and default scenario via page filters
Expected Promotions = SUM ( fact_promotion_expectation[expected] )
Expected Promotions P10 = SUM ( fact_promotion_expectation[expected_p10] )
Expected Promotions P90 = SUM ( fact_promotion_expectation[expected_p90] )
Observed Promotions = CALCULATE ( SUM ( fact_promotion_expectation[observed] ), fact_promotion_expectation[resolved] = TRUE () )
Expected Promotion Rate = DIVIDE ( [Expected Promotions], CALCULATE ( SUM ( fact_promotion_expectation[n] ), fact_promotion_expectation[suppressed] = FALSE () ) )
Expected vs Observed = [Expected Promotions] - [Observed Promotions]

-- bench coverage: expected internal supply / expected need; shown as a ratio, with P10-P90
Bench Coverage = DIVIDE ( SUM ( fact_promotion_expectation[pipeline_supply_expected] ), SUM ( fact_promotion_expectation[pipeline_need_expected] ) )
Bench Coverage P10 = MIN ( fact_promotion_expectation[pipeline_coverage_p10] )
Bench Coverage P90 = MAX ( fact_promotion_expectation[pipeline_coverage_p90] )
Bench Status =
    SWITCH ( TRUE (),
        ISBLANK ( [Bench Coverage] ), "Suppressed / n < 10",
        [Bench Coverage P90] < 1, "No internal pipeline",
        [Bench Coverage] < 1, "Thin",
        "Covered" )
Roles Without Pipeline =
    CALCULATE ( DISTINCTCOUNT ( fact_promotion_expectation[role_key] ),
                FILTER ( fact_promotion_expectation, fact_promotion_expectation[pipeline_coverage_p90] < 1 ) )

-- ---------- Model B (fact_attrition_forecast, fact_attrition_risk)
Headcount Forecast = SUM ( fact_attrition_forecast[headcount_point] )
Headcount Forecast P10 = SUM ( fact_attrition_forecast[headcount_p10] )
Headcount Forecast P90 = SUM ( fact_attrition_forecast[headcount_p90] )
Separations Forecast = SUM ( fact_attrition_forecast[separations_point] )
Retirements Forecast = SUM ( fact_attrition_forecast[sep_retirement_point] )
Hires Forecast = SUM ( fact_attrition_forecast[hires_point] )
Headcount Actual = SUM ( fact_attrition_forecast[headcount_actual] )
Forecast Error % = DIVIDE ( [Headcount Forecast] - [Headcount Actual], [Headcount Actual] )

Expected Sep Rate 4Q = AVERAGE ( fact_attrition_risk[expected_sep_rate_4q] )
Attrition Flagged Units = CALCULATE ( COUNTROWS ( fact_attrition_risk ), fact_attrition_risk[attrition_flag] = TRUE () )

-- ---------- model quality (fact_model_quality)
Metric Value = AVERAGE ( fact_model_quality[metric_value] )
Thresholds Failed = CALCULATE ( COUNTROWS ( fact_model_quality ), fact_model_quality[threshold_pass] = FALSE () )
Fairness Flag = CALCULATE ( MAX ( fact_model_quality[fairness_flag] ), fact_model_quality[attribute] <> "all" )
```

Summing P10/P90 across cells over-states the width of the interval of the sum (cells are not perfectly correlated). The dashboard labels the summed band as "sum of cell intervals (conservative)"; a correctly aggregated band is published only at the grains Phase 2 computes it for (unit × family, ladder step × unit).

### 2.4 Row-level security proposal

Two roles, both on `dim_org` so they propagate to every fact through the single-direction relationships:

| Role | Filter | Who |
|---|---|---|
| `System` | none | IHR leadership, System HR, AITS Decision Support |
| `Campus` | `[campus_cd] = LOOKUPVALUE ( sec_user_campus[campus_cd], sec_user_campus[upn], USERPRINCIPALNAME () )` | campus HR officers |
| `College` (optional) | `[college_cd] IN` the user's rows of `sec_user_org` | college HR officers, if the stack owner wants finer scope |

`sec_user_campus` / `sec_user_org` are small mapping tables maintained by the reporting owner, hidden, with no relationship to the model. `dim_model_version`, `dim_scenario` and `fact_model_quality` are not row-filtered (quality is shown to everyone who can see any page). `fact_external_context` is public data and not filtered. Because suppression is applied before publication, RLS reduces visibility but never reveals a cell below k = 10 to anyone.

Test the roles with "View as" on the pages in `dashboard_spec.md` and record the screenshots as rubric evidence (Governance: identity/row-column controls).

### 2.5 Dataset settings

- Storage mode Import; the folder is small (tens of thousands of rows).
- Mark `dim_date` as the date table (`date`).
- Hide all `*_key`, `model_version`, `scenario_key`, `suppressed`, `n` from report view; expose `Suppressed Cells` instead.
- Dataset description = `protocol_version`, `data_as_of`, `run_id` from `export_manifest.json`, surfaced on every page footer (dashboard_spec.md).
- Sensitivity label: Internal; contains no personal data by construction.
- Version control: the `.pbip`/`.pbix` and this contract live in the repository; a change to any fact's grain or a measure's definition is a contract version bump (`wap-star-v2`) and a dashboard spec update.

---

## 3. Handover checklist (Phase 3 exit)

1. `validate_star_schema.py` passes on the final folder; the JSON report is attached to the handover.
2. Every measure in 2.3 has a traceability note: fact column → Phase 2 script → protocol section (rubric: "Trace a dashboard value to its definition, source and as-of period").
3. The five views in `dashboard_spec.md` exist, with caveat text, footers and accessibility checks done.
4. RLS roles tested with at least one campus user.
5. A second analyst performs the "add a scenario" change from the documentation alone (rubric: independent analyst handover).
6. Model cards for the published `model_version`s are linked from the model-quality page.
