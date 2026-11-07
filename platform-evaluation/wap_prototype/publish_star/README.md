# Phase 3 (Delivery): star schema assembly and offline dashboard

Synthetic data only (v3 Cookbook-shaped sample pack). This folder turns the Phase 1 outputs and, when present,
the Phase 2 model outputs into the `wap-star-v1` star schema that Power BI loads
([`../delivery/star_schema.yaml`](../delivery/star_schema.yaml), [`../delivery/POWER_BI_CONTRACT.md`](../delivery/POWER_BI_CONTRACT.md)),
and renders an offline prototype of the five ESGC views in [`../delivery/dashboard_spec.md`](../delivery/dashboard_spec.md).

```bash
cd platform-evaluation
python -m wap_prototype.publish                      # Phase 1 (if outputs/ is missing)
python -m wap_prototype.publish_star.assemble        # -> wap_prototype/star/ (CSV + Parquet + export_manifest.json), ~3 s
python -m wap_prototype.publish_star.render_dashboard   # -> output/wap_prototype/wap_dashboard.html
node wap_prototype/publish_star/screenshot.js        # -> output/wap_prototype/screenshots/ (desktop + phone, light + dark)
python -m unittest discover -s wap_prototype/publish_star/tests -t . -v   # 12 tests, ~15 s
python wap_prototype/delivery/validate_star_schema.py wap_prototype/star  # the contract validator on its own
```

Options: `--model-a` / `--model-b` (default `wap_prototype/model_a/outputs`, `model_b/outputs`), `--out`, `--integrated-db`,
`--strict` (exit 1 while any model fact is absent). Re-run `assemble` then `render_dashboard` whenever a model folder lands.

## What is assembled from what

| Star table | Built from | Notes |
|---|---|---|
| `dim_date` | the 44 quarterly snapshot dates in Phase 1 `person_period_features` + 12 forecast quarters (+ any date key a model fact uses) | FY July-June; `is_forecast_period` = after `data_as_of` (2027-01-31, the Phase 1 knowledge date) |
| `dim_org` | `dim_org_external` in `data/lake/integrated/integrated_longitudinal.duckdb` (v3 `REF_ORG` through the integration build); falls back to the sample pack's `REF_ORG.parquet` | campus (depth 1) -> college (depth 3) -> dept (depth 4); the depth-2 Provost / VC Admin units are skipped so colleges key to their campus, as the Phase 1 aggregates do. `org_code` is kept as an extra natural-key column |
| `dim_role` | e_class x p_class seen in Phase 1 features and transition events; class title, SUCSS code, O*NET / SOC, job zone, review status and `critical_ind` from `dim_job_class_external` | `mapping_status` = `unreviewed` for every linked class (AGENTS.md rule 7), `none` for the 4 local AP classes and 2 abstained SUCSS classes; `ladder_desc` is the ladder's role family (the pack has no ladder title); role 0 = `EXT` external sink; `class_key` kept as an extra column |
| `dim_role_family` | Phase 1 role families (+ `EXTERNAL` = 0) | `critical_ind` = any class in the family is critical |
| `dim_model_version` | `DESCRIPTIVE-20270131` (Phase 1 run id, SHA-256 of the feature table) + every row of the model folders' `dim_model_version` | one `is_published_default` per model id (validator check) |
| `dim_scenario` | the six contract scenarios with fixed keys; extra codes from a model folder's `dim_scenario` are appended | a model folder's own scenario keys are rekeyed by `scenario_cd` |
| `fact_headcount_quarter` | Phase 1 `person_period_features` (incumbents of the primary appointment per quarter end x dept x role, FTE of the primary appointment) and `transition_events` (hires / separations / promotions / transfers in the quarter, keyed to the dept of the mover, or of the hire) | `headcount_prior_quarter` = the same cell at the previous snapshot (null for the first snapshot) |
| `fact_transitions_quarter` | `transition_events` per quarter x origin college x from-role x to-role x type; `n` = incumbents of the from-role (to-role for hires) in the college at the previous snapshot; median years in from-role from the movers' `time_in_class_years` at the previous snapshot | separations and retirements go to role 0 (`EXT`), hires come from it; the first snapshot quarter has no population at risk and is not published; only `job_end`, `leave`, `pay_change`, `no_change`, `reactivation` events are outside the contract's type list and are excluded |
| `fact_external_context` | one row per role at the last snapshot: BLS projections, O*NET job zone, AEI exposure and job-evolution watch score from `dim_job_class_external`; `oews_pay_ratio_local` = median of the Phase 1 `pay_ratio_oews_local` over the role's incumbents, published only where the role has >= 10 incumbents at that snapshot (29 of 38 roles) | public mode, `suppressed` always false |
| `fact_promotion_expectation`, `fact_attrition_forecast`, `fact_attrition_risk`, `fact_model_quality` | the model folders, read as is | surrogate keys are rekeyed through the folder's own `dim_org` / `dim_role_family` / `dim_scenario` when it ships them (Model B does); natural keys (`org_code`, `e_class`+`p_class`, `role_family`, `scenario_cd`, dates) are accepted too. The contract's primary suppression is re-applied (never loosened); the builder's own flags are kept |

The role x unit grain the contract needs is not available from the Phase 1 *published* aggregates (role-family grain), so the
assembler is the "producer" in the sense of the contract: it reads the Phase 1 restricted tables on this machine and
publishes only k >= 10 aggregates. Nothing person-level is written outside `outputs/restricted/`, the embedded dashboard
data is checked for identifier columns, and the tests check both.

## Suppression applied

- Primary: `n < 10` -> `suppressed = true`, every measure null, keys kept.
- Small counts: `0 < n_transitions < 10` suppresses the transition row (contract 1.3 rule 3). In `fact_headcount_quarter`
  a published row's event counts between 1 and 9 are nulled while the row stays published (the Phase 1 `publish.py`
  rule, kept so no count below 10 leaves the machine); `export_manifest.json` counts them as
  `small_counts_withheld_in_published_rows`.
- Complementary (succession_models `governance.suppress`): inside the parent group (dept within college x role x quarter
  for headcount; to-role within from-role x college x type x quarter for transitions) a group with exactly one suppressed
  cell and at least one published cell loses its smallest published cell too.
- Model facts: the builder applies complementary suppression at its grain; the assembler re-checks `n < 10` and any
  small-count column and forces the flag where needed.
- `fact_external_context` is public data; the only internal-derived value (the pay ratio) is published only for roles
  with >= 10 incumbents.

## Results on this build (v3 longitudinal, 813 people at the last snapshot)

| Table | Rows | Suppressed | Published |
|---|---:|---:|---:|
| `fact_headcount_quarter` (quarter x dept x role) | 20,945 | 20,945 (all `n < 10`) | 0 |
| `fact_transitions_quarter` (quarter x college x from x to x type) | 2,697 | 2,697 (2,695 `n < 10`, 2 small counts) | 0 |
| `fact_external_context` | 38 | 0 (public) | 38 (pay ratio on 29) |
| `fact_attrition_forecast` (Model B, campus x family) | 2,376 | 288 | 2,160 |
| `fact_attrition_risk` (Model B) | 29 | 0 | 29 |
| `fact_model_quality` (Model B) | 4,741 | 0 | 4,741 |
| `fact_promotion_expectation` (Model A) | absent at the time of this build | | |

Validator: `PARTIAL: model outputs not yet published` - the only error is the absent `fact_promotion_expectation`
(recorded in `export_manifest.json` under `validator.expected_absent_model_tables`; `other_errors` is empty); warnings are
the two documented extra natural-key columns and Model B's extra `n_mean_headcount_4q`. With every model folder present
the same command prints `OK` (the test `TestModelOutputsPath` checks that path with a labelled synthetic fixture in a
temp folder). The reconciliation test shows the unsuppressed transition cells equal the Phase 1 `transition_counts` for
every fully covered year and the Phase 1 event counts per type (hire 1,071; promotion 429; transfer_lateral 360;
separation_resignation 545; separation_end_of_appointment 288; transfer_down 44; retirement 26 inside the snapshot
window), and that the headcount cells sum to each snapshot's person count.

## Dashboard (`output/wap_prototype/wap_dashboard.html`, 4.2 MB, offline)

Vanilla JS + inline SVG, CSS variables with light / dark / auto theme, no network requests (the Playwright smoke test
fails on any), works at 390 px. Views: 1 promotion expectations, 2 succession risk, 3 internal mobility, 4 growth
forecasts, 5 proactive-decision indicators, the model-quality page, and a data-quality / provenance panel (DQ register
counts, data_as_of, model versions, suppression counts per table, validator status, file hashes). Every view carries the
spec's caveat in a "Read this first" box, the SYNTHETIC banner, the page footer text, `Suppressed Cells` next to totals,
and renders a suppressed cell as "n < 10" in grey, never as 0. Views 1, 2 and 4 and the model-quality page show an
explicit "Model outputs not yet published" state for each absent fact; the parts that do not depend on the model
(view 2's feeder map, view 4's history line, view 5's external-context indicators) render anyway.

Screenshots: `output/wap_prototype/screenshots/<view>_{desktop,phone}_{light,dark}.png`.

## Power BI handover

[`power_bi/LOADING_GUIDE.md`](power_bi/LOADING_GUIDE.md) (file list, Power Query types, relationships, RLS steps,
dataset settings, refresh rule), [`power_bi/relationships.csv`](power_bi/relationships.csv) and
[`power_bi/measures.dax`](power_bi/measures.dax) (every measure and calculated column of contract section 2.2-2.3).

## Limitations (read before showing anyone the numbers)

- **Synthetic.** The pack proves the plumbing. Org names, campus assignment, ladders, critical-role list and the
  O*NET links are synthetic or unreviewed; the dashboard's view 2 title says "assumed critical-role list".
- **The contract grains are empty on 813 people.** Zero quarter x dept x role headcount cells and zero
  quarter x college x role transition cells reach k = 10, so views 3 and 5 show only suppression counts and the public
  external context; the usable descriptive grain (annual campus x role family, Phase 1 `unit_year_aggregates`) is not in
  the star. The suppression rule was not loosened to change this; on real data (tens of thousands of people) the dept x
  role grain is expected to publish for the larger classes. Model B's campus x family forecasts do publish (2,160
  cells) because that grain is coarser - so view 4 shows a forecast with no published history line beside it.
- **Which views need model outputs.** View 1 and view 2 (coverage table, need vs supply, roles without pipeline) need
  `fact_promotion_expectation` (Model A); view 4 needs `fact_attrition_forecast`; view 5's "above peer units",
  retirement-forecast and thin-pipeline indicators need `fact_attrition_risk`, `fact_attrition_forecast` and
  `fact_promotion_expectation`; the model-quality page needs `fact_model_quality`. All are read whenever present.
- **Zero flows are not emitted** in `fact_transitions_quarter` (the contract allows publishing them); a from x to pair
  with no event in a quarter has no row.
- **The first snapshot quarter** (events up to 2016-03-31) has no population at risk and no transition rows.
- The level-2 administrative units of the org tree are not in `dim_org`; `is_active` comes from `canon_org.status_code`.
- Model B's `data_as_of` (2026-12-31) differs from the descriptive `data_as_of` (2027-01-31, the Phase 1 extract date);
  each fact carries its own, and the page footer shows the version of the fact a page is built on.
- The dashboard sums P10 / P90 across cells for the band and labels it "sum of cell intervals (conservative)".
- The embedded data is the suppressed star only; if the page would exceed 6 MB the renderer drops non-default
  scenarios, then older origins, then suppressed headcount rows, and says so in the provenance panel.
