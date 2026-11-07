# Dashboard specification: five ESGC success-measure views

Built on the star schema in [`star_schema.yaml`](star_schema.yaml) with the measures in [`POWER_BI_CONTRACT.md`](POWER_BI_CONTRACT.md) section 2.3. One Power BI report, five pages plus a model-quality page. Every page follows the common rules in section 0.

## 0. Rules common to every page

**Footer (text box, every page):** `Protocol wap-protocol-v1 · Model <model_version> · Data as of <data_as_of> · Cells with fewer than 10 people are suppressed; totals cover published cells only · This report shows role- and unit-level expectations. It contains no person-level scores and is not used for any decision about an individual (Illinois HB 3773).`

**Suppression display:** a suppressed cell renders as "n < 10" in grey (`#767676` on white, contrast 4.5:1), never as 0 or blank. Every page shows the `Suppressed Cells` card next to any total.

**Default filters (page level):** `dim_model_version[is_published_default] = TRUE`, `dim_scenario[is_default] = TRUE`, latest `data_as_of`. The scenario slicer is visible on pages 1, 4 and 5 so readers can compare the primary model with the base-rate / seasonal-naive comparator.

**Accessibility (all pages):**
- Colour is never the only encoding: status uses icon + text ("Covered", "Thin", "No internal pipeline") and patterns or markers on lines.
- Palette: a colour-blind-safe sequential ramp for rates and a two-hue diverging ramp (blue/orange) for expected − observed; no red/green pairs. Minimum text contrast 4.5:1; minimum 12 pt.
- Every visual has an alt-text that states the measure, the grain and the as-of date (Format → General → Alt text), and tab order follows reading order.
- Tables are provided for every chart (toggle "Show as table") so screen readers can read values; intervals are stated in text ("5.2 expected, 80% range 3–8").
- Keyboard: all slicers reachable by Tab; no hover-only information (tooltips duplicate on-canvas labels).
- Phone layout defined for pages 1 and 4 (the two leadership views).

**Caveat placement:** each page has a "Read this first" collapsible text box at the top right with the text given under each view.

---

## 1. Promotion / transition expectations by role and unit

**Question:** How many promotions or upward transitions should each unit expect from each ladder step in the next 12 and 18 months, and how did last year's expectation compare with what happened?

| Visual | Type | Fields | Measures |
|---|---|---|---|
| 1a Expectation matrix | Matrix | rows `dim_org` hierarchy (campus → college → dept); columns `dim_role[Ladder Step]`; slicer `fact_promotion_expectation[horizon_months]` | `Expected Promotions`, conditional-format on `Expected Promotion Rate`; tooltip `Expected Promotions P10`, `P90`, `n` |
| 1b Expected vs observed (resolved origins) | Clustered bar + error bars | axis `dim_role[Ladder Step]`; legend expected/observed; filter `resolved = TRUE` and `dim_date` = origin 12 or 18 months before `data_as_of` | `Expected Promotions`, `Observed Promotions`, error bars from P10/P90 |
| 1c Calibration strip | Scatter | x `Expected Promotions`, y `Observed Promotions`, one point per ladder step × unit with n ≥ 10, reference line y = x | per-cell values; tooltip unit, step, n |
| 1d Scenario comparison | Table | rows `dim_scenario[scenario_name]` | `Expected Promotions`, `Expected Promotion Rate` |
| 1e Cards | Cards | | `Expected Promotions` (12 m), `Published Cells`, `Suppressed Cells` |

**Caveat text:** "Expectations are sums of calibrated probabilities over the incumbents of a ladder step in a unit. They are not a list of people and no person-level score is available from this report. The promotion label is derived from change reasons and class changes (`label_name`); if it reads `upward_transition_*` the HR label audit found it does not match HR's definition of promotion. Model skill over the base-rate-by-step comparator is shown on the Model quality page; where the primary model failed the pre-registered thresholds the base-rate scenario is the default."

**Accessibility notes:** matrix cells carry text values, not only shading; error bars are also given in the tooltip table; the calibration scatter has a data table toggle.

---

## 2. Succession risk: roles without an internal pipeline

**Question:** Which critical roles, in which units, have expected internal supply below expected need?

| Visual | Type | Fields | Measures |
|---|---|---|---|
| 2a Pipeline coverage table | Table, sorted by `Bench Coverage` ascending | `dim_org[campus_name]`, `dim_org[college_name]`, `dim_role[Ladder Step]`, `dim_role[critical_ind]` (filter default TRUE), `fact_promotion_expectation[horizon_months]` = 18 | `Bench Coverage`, `Bench Coverage P10`, `Bench Coverage P90`, `Bench Status` (icon + text), `Expected Promotions`, `n` |
| 2b Need vs supply | Stacked bar | axis `dim_role[Ladder Step]` | `SUM(pipeline_need_expected)` vs `SUM(pipeline_supply_expected)` |
| 2c Roles-without-pipeline count by campus | Bar | axis `dim_org[campus_name]` | `Roles Without Pipeline` |
| 2d Feeder map for the selected role | Matrix from `fact_transitions_quarter` | rows `dim_role[Ladder Step]` (from), column = selected to-role, trailing 8 quarters, `transition_type = promotion` | `Transitions`, `Transition Rate` |
| 2e Cards | Cards | | `Roles Without Pipeline`, `Suppressed Cells` |

**Caveat text:** "Coverage is expected internal entrants divided by expected exits (promotion out plus separation) over 18 months. 'No internal pipeline' means the 90th percentile of coverage is below 1, so even an optimistic draw does not fill expected need from inside. This is a talent-pool statement about a role, not a readiness ranking of named employees. The critical-role list is HR-owned; where it is still the assumed list from the synthetic run the page title says 'assumed critical-role list'."

**Accessibility notes:** `Bench Status` uses three distinct icons (filled circle, half circle, empty circle) with text; sort order is explicit in the table caption.

---

## 3. Internal-mobility summary (role-to-role transition volumes)

**Question:** Where do people actually move, how often, and which roles are feeders or dead ends?

| Visual | Type | Fields | Measures |
|---|---|---|---|
| 3a Transition matrix | Matrix | rows `dim_role[Ladder Step]` (from, active relationship); columns `dim_role_to[Ladder Step]`; slicer `transition_type` (promotion / transfer_lateral / transfer_down / reclassification / separation_* / retirement); period slicer by fiscal year | `Transitions` (count), tooltip `Transition Rate`, `median_years_in_from_role` |
| 3b Flow chart | Sankey (certified custom visual) or, when custom visuals are not allowed on the stack, a ribbon chart | source `dim_role[role_family]`, destination `dim_role_to[role_family]` | `Transitions` |
| 3c Move rate by ladder step | Bar | axis `dim_role[Ladder Step]` | `Transition Rate` (all internal types), with the share going up a level as a second bar |
| 3d Time-in-step before a promotion | Bar | axis `dim_role[Ladder Step]` | `AVERAGE(median_years_in_from_role)` where `transition_type = promotion` |
| 3e Cards | Cards | | `Transitions` (fiscal year to date), `Suppressed Cells` |

**Caveat text:** "Counts below 10 movers are suppressed, so rare paths are not shown and totals are partial. Flows are historical volumes, not probabilities of any person's next move. `transfer_lateral` and `transfer_down` labels come from the same ladder-level comparison and inherit the promotion-label caveat on page 1."

**Accessibility notes:** the Sankey must be paired with the matrix (3a) which is the accessible equivalent; link colours are not the only encoding (labels on links); if the custom visual is not certified for the tenant, omit it and use the matrix only.

---

## 4. Growth forecasts by department and job family

**Question:** How many people, hires and separations should each department × job family plan for over the next 1–3 years, and how good has the forecast been?

| Visual | Type | Fields | Measures |
|---|---|---|---|
| 4a Headcount history and forecast | Line + shaded band | x `dim_date[quarter_label]` (target quarter); slicers `dim_org` hierarchy, `dim_role_family[role_family_name]`, scenario | `Headcount` (history, from fact_headcount_quarter), `Headcount Forecast`, band `Headcount Forecast P10`–`P90`; forecast segment dashed |
| 4b Separations by cause, forecast | Stacked column | x target quarter, legend voluntary / retirement / other | `SUM(sep_voluntary_point)`, `Retirements Forecast`, `SUM(sep_other_point)`; tooltip P10/P90 |
| 4c Hires needed to hold headcount | Column | x target quarter | `Hires Forecast`, with `Separations Forecast` as a line |
| 4d Forecast vs actual (resolved) | Line | x target quarter, filter `actual_known = TRUE` | `Headcount Forecast`, `Headcount Actual`, `Forecast Error %` |
| 4e Model vs seasonal naive | Table | rows `dim_scenario[scenario_name]` | `Headcount Forecast` at h = 4, `Separations Forecast` at h = 4, and from `fact_model_quality`: `mase_rel`, `cov80` |
| 4f Cards | Cards | | `Headcount Forecast` at h = 4 and h = 12, `Suppressed Cells` |

**Caveat text:** "Forecasts are for departments and job families with an average headcount of at least 10; smaller series are pooled into their campus × family row. Bands are the 10th–90th percentiles of the model's own backtest errors and were, in the reference backtest, somewhat narrow (coverage below nominal at long horizons). Seasonal naive is shown as a comparator: at horizons where the model did not beat it in the backtest, the page shows seasonal naive by default. Age structure enters as the unit's share of retirement-eligible staff, never as a person feature."

**Accessibility notes:** forecast and history segments differ by line style and marker, not only colour; the band has 30% opacity and its bounds are listed in the tooltip and table; the x-axis uses `quarter_label` text, not date serials.

---

## 5. Proactive-decision indicators

**Question:** Where should HR act first? Which unit × job family combinations show elevated expected attrition, thin pipelines, retirement exposure and external market pressure at the same time?

| Visual | Type | Fields | Measures |
|---|---|---|---|
| 5a Indicator table | Table, one row per unit × job family (n ≥ 10), sorted by number of indicators on | `dim_org[campus_name]`, `dim_org[dept_name]`, `dim_role_family[role_family_name]` | `Expected Sep Rate 4Q` with P10–P90; `attrition_flag` (icon + text "Above peer units"); `Retirement Rate (4Q)` and `Retirements Forecast` (next 4 q); `Bench Status` (worst step in the family); from `fact_external_context` averaged over the family's roles: `oews_pay_ratio_local` ("Pay vs local market"), `bls_projected_growth_pct`, `bls_separation_rate`, `aei_exposure`, `job_evolution_watch`; `Mapping Caveat` |
| 5b Attrition flag map | Matrix heat | rows `dim_org[dept_name]`, columns `dim_role_family[role_family_name]` | `Expected Sep Rate 4Q`, with the flag as an icon |
| 5c Retirement exposure | Bar | axis `dim_role_family[role_family_name]` | `Retirements Forecast` (next 4 q) vs `Retirements` (last 4 q) |
| 5d Market pressure | Scatter | x `oews_pay_ratio_local`, y `bls_projected_growth_pct`, size `Headcount`, one point per role family | from `fact_external_context` joined through `dim_role` |
| 5e Cards | Cards | | `Attrition Flagged Units`, `Roles Without Pipeline`, `Suppressed Cells` |

**Indicator definitions (shown in a "How indicators are set" text box):**
- *Above peer units*: `attrition_flag` from `fact_attrition_risk`, protocol section 3.5 (P10 of the expected 4-quarter separation rate above the 75th percentile of peer units, and the trailing observed rate also above it).
- *Retirement exposure*: forecast retirements next 4 quarters ≥ 10% of headcount.
- *Thin pipeline*: `Bench Status` is "Thin" or "No internal pipeline" for any critical step in the family.
- *Market pressure*: `oews_pay_ratio_local` < 0.90 or `bls_projected_growth_pct` above the median across families.
- *Role evolution watch*: `job_evolution_watch` or `aei_exposure` in the top quartile across families (evidence about tasks, never a job-loss forecast, AGENTS.md rule 7).

**Caveat text:** "Indicators are unit- and family-level prompts for a planning conversation, not findings about individuals and not a ranking of employees. External context is joined through SUCSS → O*NET → SOC links that are unreviewed suggestions until an HR analyst confirms them; rows with `Mapping Caveat` text should be read accordingly. AI-exposure and job-evolution scores describe tasks, not people, and are not a forecast of job loss."

**Accessibility notes:** indicators are rendered as text labels in the table in addition to icons; the heat matrix shows the numeric value in every cell; the scatter has a data table toggle and point labels for the ten largest families.

---

## 6. Model quality (supporting page, not an ESGC view)

| Visual | Fields | Measures |
|---|---|---|
| Threshold table | `fact_model_quality` rows with `threshold_id` not null, `origin_date_key = 0`; columns metric, value, baseline, threshold, PASS/FAIL (text) | `Metric Value`, `Thresholds Failed` |
| Per-origin lines | x origin quarter, y `auc_roc` / `brier_skill_step` (Model A) or `mase_rel` / `cov80` (Model B) | `Metric Value` |
| Fairness summary | rows `attribute` (sex, race_eth_rpt_cd, age_40_plus); columns `min_impact_ratio`, `max_tpr_gap`, `max_fpr_gap`, `groups_suppressed`, `fairness_flag` | from `fact_model_quality` |
| Version list | `dim_model_version` table with `model_card_path` link, `passes_all_thresholds`, `fairness_flag`, `bitemporal_mode` | |

**Caveat text:** "Failed thresholds are published, not hidden; a failed model is shown only as a comparator scenario. Fairness rows are per-attribute summaries from the audit of the hypothetical top-10%-per-step selection rule; group-level tables are in the restricted model card. 'adverse' means impact ratio below four-fifths with Fisher p < 0.05 and keeps the person-level gate closed."
