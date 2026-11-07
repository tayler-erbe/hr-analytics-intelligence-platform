# Workforce Analytics Intelligence Platform: pre-registered modeling protocol

**Protocol label:** `wap-protocol-v1`
**Status:** pre-registered, frozen on 2026-11-07, before any Phase 2 model is fitted on the Phase 1 feature tables.
**Scope:** the ESGC work request (236 AITS hours). Phase 2 productionizes two POC models as governed, validated pipelines; Phase 3 delivers Power BI dashboards on the existing reporting stack. This document fixes the units of reporting, learners, validation design, pass thresholds, fairness tests, leakage rules, publication rules and the HB 3773 position **before results exist**. Anything that changes after results exist requires a new label (section 8).

Everything here reuses the design already proven in `succession_models/` (out-of-time backtest, calibration, Brier skill against a base-rate baseline, a no-age ablation, four-fifths plus Fisher adverse-impact audit, k ≥ 10 suppression, person-level outputs gated) and `turnover_forecast/` (rolling-origin backtest, MASE against seasonal naive, 80/95% interval coverage). Where this protocol says "as in succession_models" it means the implementation in that module is the reference semantics; `protocol/scorers.py` re-implements the metrics without that module's dependencies and is tested against hand-computed values.

---

## 0. Reading guide and binding rules

| Rule | Where |
|---|---|
| Thresholds, baselines and metrics are fixed here and may not be loosened to improve results (AGENTS.md rule 4) | sections 2.6, 3.6 |
| Nothing person-level or position-level leaves the approved machine; published outputs are role/unit aggregates with k ≥ 10 and complementary suppression (AGENTS.md rule 3) | section 6 |
| Protected attributes (`sex`, `race_eth_rpt_cd`) and age enter the fairness audit only, never a feature matrix (age-band enters one named ablation) | sections 2.3, 4 |
| Leakage firewall: features at snapshot S use only data effective **and recorded** on or before S; labels are joined on keys only | section 5 |
| Every published number carries `model_version`, `protocol_version`, `run_id`, `data_as_of` and a suppression flag | section 6, `delivery/star_schema.yaml` |
| Failed runs, null results and threshold failures are preserved and reported, not re-run until they pass | section 8 |

### 0.1 Inputs from Phase 1 (the foundation)

The protocol is written in **logical names** (left column). The Phase 1 foundation (`wap_prototype/features.py`, rule version `wap_phase1_features_v1`, read on 2026-11-07) publishes `person_period_features` with the physical names in the right column; model code binds logical to physical in one mapping and this protocol is unchanged by a rename. If the foundation README or data dictionary later differs from this table, the data dictionary wins and the mapping is updated.

| Logical name (used here) | Foundation column | Protocol use |
|---|---|---|
| `edw_pers_id`, `posn_nbr`, `snapshot_date`, `knowledge_date` | `person_id`, `position_id`, `snap_date`, `knowledge_date` | Keys and the as-of rule; identifiers never exported |
| `tenure_years` | `tenure_first_hire_years` (`tenure_current_hire_years` as a sensitivity) | Model A feature (age-correlated proxy, see 2.3) |
| `time_in_class_years`, `time_in_position_years` | same | Model A features |
| `moves_per_year`, `time_since_last_move` | `moves_per_year`, `time_since_last_move_years` | Model A features |
| `fte` | `fte_primary` (`fte_total` for the FTE-weighted headcount) | Model A feature; `fact_headcount_quarter.fte_sum` |
| `pay_position_in_range` | `pay_range_position` (`compa_ratio`, `pay_ceiling_gap` available) | Model A feature (POC "pay-band ceiling" signal = `pay_ceiling_gap`) |
| `unit_churn_12m` | `dept_churn_12m` (with `dept_headcount`, `dept_separations_12m`, `dept_hires_12m`) | Both models |
| `e_class`, `p_class`, `role_family`, `ladder`, `level` | `e_class`, `p_class_code`, `role_family` (+ `role_family_source`), `ladder_code`, `ladder_level` (+ `ladder_level_source`; `role_level` as fallback) | Model A features; `dim_role` |
| `campus`, `college`, `dept` | `campus_org_code`, `college_org_code`, `dept_org_code` (`admin_level_2`) | Reporting dimensions (`dim_org`), not Model A features |
| `surs_eligibility_band` | `surs_eligibility_band` (values `eligible_unreduced`, `eligible_reduced`, `within_5_years`, `not_eligible`, `unknown`; `surs_rule_version = assumption_v1`) | Model B population covariate; Model A excluded except in the ablation |
| `age_band` | `age_band` (bands `<25, 25-34, 35-44, 45-54, 55-59, 60-64, 65+`) | Fairness audit and the ablation only. The foundation bands have no cut at 40, so the `age_40_plus` audit attribute is implemented as **age 45+** (bands 45-54 and above) and labelled as such in every output until Phase 1 adds a 40 cut; the protocol label stays `age_40_plus` so the ADEA intent is explicit |
| `onet_job_zone` | `onet_job_zone` | Both models; `dim_role` |
| `bls_projected_growth_pct` | `proj_growth_pct_2025_35` | Both; `fact_external_context` |
| `bls_separation_rate` | `proj_occ_separations_rate_pct` (`proj_labor_force_exit_rate_pct` also carried) | Both; `fact_external_context` |
| `oews_pay_ratio_local` | `pay_ratio_oews_local` (`pay_ratio_oews_il` as the state comparator) | Both; `fact_external_context` |
| `aei_exposure`, `job_evolution_watch` | `aei_observed_exposure`, `je_watch_score` | Both; `fact_external_context` |
| SUCSS/O*NET/SOC bridge | `onet_code`, `soc_2018_code`, `external_chain_review_status`, `external_null_reason` | `dim_role` bridge fields; `mapping_status` = `external_chain_review_status` |
| `promoted_12m`, `promoted_18m` | `promoted_within_12m`, `promoted_within_18m` (null when the horizon passes `knowledge_date`) | Model A labels; candidate rule `candidate_v1_ladder_or_role_family_level_up` (section 2.7) |
| `separated_6m`, `separated_12m`, `retired_12m` | `separated_within_6m`, `separated_within_12m`, `retired_within_12m` | Model B series validation and the sensitivity checks |
| Transition events | `transition_events` with `event_type` in {`hire`, `rehire`, `promotion`, `transfer_lateral`, `transfer_down`, `reclassification`, `separation_resignation`, `separation_end_of_appointment`, `separation_involuntary`, `separation_death`, `separation_other`, `retirement`, ...} | Model B series (section 3.2) and `fact_transitions_quarter.transition_type` |
| Restricted demographics frame | `person_demographics_restricted` (`person_id` plus the mapping's `fairness_fields`; role `restricted_fairness_only`) | Fairness audit **only**, loaded by the fairness code and nowhere else |

Model B cause groups map as: voluntary = `separation_resignation` (+ `separation_end_of_appointment` reported separately as a sensitivity because end-of-appointment is partly involuntary); retirement = `retirement`; other = `separation_involuntary`, `separation_death`, `separation_other`.

---

## 1. Decision questions and what the models answer

| ESGC success measure | Model | Unit of reporting (published) |
|---|---|---|
| Promotion / role-transition expectations by role and unit | A | ladder step × unit × horizon |
| Succession risk: roles without an internal pipeline | A + Phase 1 transition events | role (ladder step or role family) × unit |
| Internal-mobility summary | Phase 1 transition events (descriptive) | from-role × to-role × year |
| Growth forecasts by department and job family | B | dept × job family (× campus) × quarter × horizon |
| Proactive-decision indicators | A + B + external context | unit × role family |

Neither model produces a decision about a person. Model A's person-level scores exist only as an intermediate that is summed into expected counts and that may be inspected under the same governance gate as the succession readiness model (section 6.3).

---

## 2. Model A: promotion / role-transition likelihood

### 2.1 Purpose and unit of reporting

Model A estimates, for each incumbent person-period, the probability of a promotion or role transition within 12 and 18 months, and then **reports only aggregates**: expected number of promotions/transitions per **ladder step (`ladder`, `level`) × unit (campus/college/dept at the reporting level) × horizon**, with an interval, the observed count when the horizon has elapsed, and **pipeline coverage** (expected internal entrants into a step ÷ expected exits from that step, as in succession_models `bench.py`).

The primary unit of reporting is **ROLE × UNIT**. Person-level scores are restricted (section 6.3).

### 2.2 Labels

| Label | Definition (from Phase 1) | Status |
|---|---|---|
| `promoted_12m`, `promoted_18m` | A transition event within h months of the snapshot whose change reason, class change or `level` increase marks it as a promotion or upward role transition | **Candidate label.** Change-reason-derived promotions have not been verified against HR's own definition. The first Phase 2 deliverable is a label audit (section 2.7) |
| `transition_12m` (derived) | Any primary-position class change within 12 months (promotion, lateral, demotion), excluding separations | Secondary target used for the mobility summary and for a sensitivity check of the promotion label |

Labels are computed from the latest data for evaluation and as-known-at-origin for training (section 5). A person-period whose horizon ends after `data_as_of` is censored and dropped from evaluation at that horizon.

### 2.3 Features

**Included** (all as of the snapshot, from `person_period_features`):

`tenure_years`, `time_in_class_years`, `time_in_position_years`, `fte`, `pay_position_in_range`, `moves_per_year`, `time_since_last_move`, `unit_churn_12m`, `e_class`, `p_class`, `role_family`, `ladder`, `level`, `campus`, `onet_job_zone`, `bls_projected_growth_pct`, `bls_separation_rate`, `oews_pay_ratio_local`, `aei_exposure`, `job_evolution_watch`.

Logical names; the physical columns are in section 0.1. Categorical columns are one-hot (logistic) or native-categorical (tree learners). `college` and `dept` are **not** features: they are reporting dimensions. Using them as features would let the model learn unit-specific promotion rates that the audit cannot separate from unit composition; the unit-level baseline (section 2.5) captures them instead.

**Excluded from every Model A feature matrix:** `age_band`, birth date, `surs_eligibility_band` and any other age-derived field; `sex`, `race_eth_rpt_cd`; ZIP code, address, commute; leave usage; performance ratings; names and identifiers. `tenure_years` and `time_in_class_years` are age-correlated proxies and are kept **only because** the age-40+ audit (section 4) tests them; if that audit fails and the no-tenure sensitivity run (section 2.6, S3) passes, the tenure features are dropped in the next protocol version.

**Ablation (named run `A-age-ablation`):** the primary learner refitted with `age_band` added. It exists to measure how much predictive information age carries beyond the proxies. Its outputs are never published and never feed any fact table.

### 2.4 Candidate learners

| Run id | Learner | Fixed hyper-parameters (no tuning on test years) |
|---|---|---|
| `A-base-family` | Baseline: base rate by `role_family` in the training years | none |
| `A-base-step` | Baseline: base rate by (`ladder`, `level`) in the training years, backing off to `A-base-family` when the cell has < 30 person-periods | backoff threshold 30 |
| `A-logit` | Logistic regression, L2, `C` chosen by 5-fold CV **within the training years only**, standardized numerics | `C ∈ {0.01, 0.1, 1, 10}` |
| `A-rf` | Random Forest, `class_weight="balanced"` (the POC learner), 500 trees, `min_samples_leaf=50`, `max_features="sqrt"` | fixed |
| `A-gbm` | Gradient boosting (LightGBM or sklearn HistGradientBoosting), 300 rounds, learning rate 0.05, `num_leaves=15`, `min_child_samples=100`, `deterministic=True` | fixed |
| `A-age-ablation` | `A-gbm` plus `age_band` | fixed |

All learners are followed by **Platt recalibration** fitted out-of-time on the origin two years earlier than the test origin (as in succession_models `vacancy.py`), never on the test years. Primary learner = the one with the best mean Brier skill at 12 months across origins **among those that pass every threshold in 2.6**. Ties (< 0.5 percentage point of Brier skill) go to the simpler learner in the order logistic → RF → GBM.

### 2.5 Validation design

- **Out-of-time backtest.** Origins `Y` = 2019-12-31, 2020-12-31, 2021-12-31, 2022-12-31, 2023-12-31 (quarter-end snapshot closest to Dec 31; drop an origin if Phase 1 history does not cover it and record why). Train on snapshots whose 18-month horizon ends on or before `Y`; evaluate on snapshots in `Y+1 .. Y+2` whose horizon has resolved by `data_as_of`.
- **Metrics per origin, horizon and learner** (all in `scorers.py`): AUC-ROC, AUC-PR (average precision), Brier, Brier skill vs `A-base-family` and vs `A-base-step`, calibration intercept (calibration-in-the-large, `obs − mean pred`) and logistic calibration slope, ECE (10 equal-count bins), Spiegelhalter-style decile table.
- **Aggregated evaluation at the reporting grain.** For each ladder step × unit × horizon cell with n ≥ 10 person-periods in the test years: expected count (sum of probabilities), Poisson-binomial P10/P90, observed count; report the share of cells whose observed count falls inside P10–P90 and the mean signed bias. This is the number that matters for the dashboard.
- **Report means and per-origin values.** The protocol does not allow dropping an origin after seeing its result.

### 2.6 Pass thresholds (fixed now)

A learner **passes** for a horizon only if, averaged over origins:

| Id | Criterion | Threshold |
|---|---|---|
| A1 | AUC-ROC | ≥ 0.62, and ≥ `A-base-step` AUC + 0.03 |
| A2 | AUC-PR | ≥ 1.5 × prevalence (the no-skill AUC-PR), and ≥ `A-base-step` AUC-PR |
| A3 | Brier skill vs `A-base-family` | ≥ +2.0% |
| A3b | Brier skill vs `A-base-step` | ≥ 0% (not worse than the step baseline) |
| A4 | Calibration slope after recalibration | in [0.85, 1.15] |
| A5 | Calibration-in-the-large | within ±1.0 percentage point of the observed rate |
| A6 | ECE (10 equal-count bins) | ≤ 0.02 |
| A7 | Reporting-grain coverage | ≥ 70% of eligible cells have the observed count inside P10–P90 |
| A8 | Fairness (section 4) | no "adverse impact indicated" flag on the published selection rule, or the flag is documented and the person-level gate stays closed |
| A9 | Age ablation | the ablation's AUC-ROC gain over the primary learner is reported; if the gain is > 0.03, the model card must state that administrative features do not capture what age captures and the proxy review (S3) is mandatory |

If no learner passes A1–A7, the protocol outcome is **"no skill beyond base rates"**; the dashboard then shows `A-base-step` expected counts, labelled as base-rate expectations, and the result is published as such. This is a legitimate outcome (succession_models found AUC ≈ 0.6 even for the oracle).

**Sensitivity runs** (reported, not gating): S1 label = `transition_12m`; S2 drop external covariates; S3 drop `tenure_years` and `time_in_class_years`.

### 2.7 Label caveat and label audit

Promotion derived from change reasons, class changes or `level` increases is a **candidate label**. Before any Model A result is reported, Phase 2 performs a label audit: a stratified sample of 200 transition events (synthetic in this repo; real only on the approved machine with HR review) is compared with HR's definition of promotion vs reclassification vs lateral. The model card records agreement; if agreement is below 85% the label is renamed `upward_transition_12m` in every output and the dashboard caveat (dashboard_spec.md, view 1) says so.

---

## 3. Model B: workforce growth and attrition-risk forecast

### 3.1 Purpose and unit of reporting

Model B forecasts quarterly **headcount, hires and separations (voluntary, retirement, other)** at the **department × job family** grain (with campus as a roll-up and a separately scored campus × job family grain), over 1–12 quarters (1–3 years). It also publishes an **attrition-risk score at the unit × job family level only**: the expected 4-quarter separation rate with an 80% interval, flagged when the interval's lower bound exceeds the peer distribution of comparable units (section 3.5).

### 3.2 Series construction

From Phase 1 transition events and headcount snapshots:

| Series | Definition |
|---|---|
| `headcount` | Incumbent count at quarter end (primary appointments; FTE-weighted headcount reported alongside, not forecast) |
| `hires` | External entries into the unit × family in the quarter |
| `sep_voluntary` | Separations with a resignation / other-voluntary reason |
| `sep_retirement` | Separations with `retired` flag (SURS retirement indicator) |
| `sep_other` | Involuntary, end of contract, death, other |
| `separation_rate` | separations ÷ mean(headcount start, headcount end) |

Job family = Phase 1 `role_family`. Series with fewer than 10 average headcount are **not modelled individually**; they are pooled to the parent (campus × family) and published only at that level.

### 3.3 Methods

| Run id | Method | Notes |
|---|---|---|
| `B-snaive` | Seasonal naive (same quarter last year) | The reference for MASE |
| `B-ets` | ETS, additive damped trend, additive seasonality, on log(1+y) | Fixed specification |
| `B-pooled` | Pooled hierarchical model: one ridge regression per horizon across all dept × family series, target log((y_{T+h}+1) ÷ (mean of last 4 quarters + 1)), with series intercepts shrunk to a common intercept; features = recent level, 4- and 8-quarter trend, same-quarter seasonal profile, **age structure** (share of incumbents in `surs_eligibility_band` ∈ {unreduced, reduced-only, within-3y}, share age 55+ from `age_band`), `unit_churn_12m`, and **external covariates** dated at T or earlier: QWI Illinois NAICS 6113 separation and hire rates (`turnover_forecast/` panel), `bls_projected_growth_pct`, `bls_separation_rate`, QCEW higher-ed employment growth, `oews_pay_ratio_local` | Age structure is a **population** covariate here (share of a unit), not a person feature; this is the one place `age_band` is allowed outside the audit |
| `B-gbm` | Global gradient-boosted model on the same features with horizon, series and quarter as features, fixed seed, `deterministic=True` | |
| `B-ens` | Equal-weight geometric mean of `B-ets`, `B-pooled`, `B-gbm`, weights fixed now | The default published model unless it fails a threshold that another method passes |

COVID handling as in turnover_forecast: a dummy on training targets 2020Q1–2021Q2, always 0 at forecast time; metrics reported with and without COVID target quarters.

### 3.4 Validation design

- **Rolling-origin backtest.** Origins every quarter from the first quarter with 12 quarters of history up to `data_as_of − 1 quarter`; the first 8 origins are warm-up for empirical intervals. At each origin T all series are truncated at T; forecasts for h = 1..12.
- **Metrics per series, horizon and method** (`scorers.py`): MASE (scale = in-sample mean absolute lag-4 seasonal-naive error up to T), sMAPE, 80% and 95% interval coverage, mean signed error. Intervals: empirical quantiles of the method's own log errors resolved by T (minimum 12 errors), as in turnover_forecast.
- **Aggregation.** Metrics are averaged across series weighted by mean headcount, and also reported unweighted; both must be in the model card.
- **Hierarchy check.** Dept forecasts summed to campus × family are compared with the directly modelled campus × family forecast; the published value is the bottom-up sum and the discrepancy is reported.

### 3.5 Attrition-risk score

For each unit × family with headcount ≥ 10: `expected_sep_rate_4q` = sum of forecast separations h=1..4 ÷ forecast mean headcount, with the P10/P90 from the interval simulation. **Flag rule (fixed now):** `attrition_flag = 1` when P10 of the unit's expected rate exceeds the **75th percentile** of expected rates across peer units (same campus, same job family, headcount ≥ 10) **and** the unit's trailing 4-quarter observed rate also exceeds that percentile. The flag is informational and unit-level; no person is identified.

### 3.6 Pass thresholds (fixed now)

Averaged over scored origins and headcount-weighted across series:

| Id | Criterion | Threshold |
|---|---|---|
| B1 | MASE relative to `B-snaive`, h = 1–4 | ≤ 0.95 for `headcount` and total separations |
| B2 | MASE relative to `B-snaive`, h = 5–12 | ≤ 1.00 (not worse than seasonal naive) |
| B3 | 80% interval coverage | in [70%, 90%] |
| B4 | 95% interval coverage | ≥ 88% |
| B5 | Mean signed error of headcount at h = 4 | within ±2% of mean headcount |
| B6 | Hierarchy discrepancy (bottom-up vs direct) at h = 4 | ≤ 5% of campus × family headcount |
| B7 | Attrition flag precision in backtest | among flagged unit × family × origin cells, ≥ 60% have realized 4-quarter separation rate above the peer 75th percentile |

A method that fails B1 but passes B2–B5 may still be published for h ≥ 5 only, with `B-snaive` shown for h ≤ 4; the model card says so. If every method fails B1 and B2, the published forecast **is** seasonal naive with its native interval, labelled as such.

---

## 4. Fairness review (both models; mandatory before any publication)

Reuses succession_models `fairness.py` semantics; `scorers.four_fifths()` and `scorers.equalized_odds_gaps()` implement them.

**Attributes:** `sex`, `race_eth_rpt_cd` (as reported; groups as coded, no re-grouping without OAE agreement), `age_40_plus` derived from `age_band`. Whether each attribute may lawfully be used for the audit is a Counsel decision recorded in the model card.

**Model A.** On every test-year person-period set:

1. **Selection rule under test.** Because the published output is aggregate, the audited "selection" is the rule that would be used if the gate were ever opened: top 10% of scores within each ladder step. The audit is run anyway, every retrain, because the aggregates are sums of those scores.
2. **Selection-rate ratios** (four-fifths): each group's selection rate ÷ the highest-rate group's, among groups with n ≥ 10; Fisher exact test (group vs all others), two-sided.
3. **Equalized-odds gaps**: TPR and FPR by group against the realized label; max gap per attribute. TPR requires ≥ 10 positives in the group, FPR ≥ 10 negatives.
4. **Calibration by group**: calibration-in-the-large and slope per group with n ≥ 50.
5. **Historical base-rate disparity**: the same four-fifths test on the realized label itself in the training years, so the card distinguishes "the model reproduces history" from "the model adds disparity".
6. **Flags**: `adverse impact indicated` when impact ratio < 0.8 and Fisher p < 0.05; `below 4/5, not significant` when ratio < 0.8 only. Any `adverse impact indicated` flag on sex, race/ethnicity or age 40+ keeps the person-level gate closed and is printed in the model card and in `fact_model_quality`.
7. **Suppression**: groups with n < 10 are not reported.

**Model B.** No person-level scores exist, so the audit is a **disparate-burden check**: for each attribute, compare the distribution of `attrition_flag` units against the group composition of units; if flagged units have a group share more than 10 percentage points above the unflagged units' share, the model card says so and HR reviews whether the flag targets a concentrated group. Reported, not gating.

**Published fairness summary:** `fact_model_quality` carries, per model version and attribute, `min_impact_ratio`, `max_tpr_gap`, `max_fpr_gap`, `fairness_flag` and `groups_suppressed`. Group-level rows (per sex / race group) stay in the restricted model card, because small institutions could re-identify.

---

## 5. Shared rules

### 5.1 Leakage firewall

1. Features at snapshot S use only row versions with `eff_dt ≤ S` **and** `rec_start ≤ S < rec_end` (bitemporal; effective-only fallback is allowed with a WARN gate as in succession_models G4, and the model card records which mode ran).
2. Labels are computed separately and joined on (`edw_pers_id`, `posn_nbr`, `snapshot_date`) only. Training labels are as known at the origin; evaluation labels use the latest data.
3. Training snapshots must satisfy `snapshot_date + horizon ≤ origin`.
4. External covariates must be dated at or before the snapshot (QWI arrives ~3 quarters late: use the vintage that was available at T when vintages exist; otherwise record "pseudo-out-of-sample" in the card, as turnover_forecast does).
5. Recalibration, hyper-parameter choice, series pooling and interval quantiles use training-period data only.
6. Tests: truncation and scrambling tests (features at S unchanged when every row recorded after S is scrambled), future-perturbation test for the forecaster, COVID-dummy-zero-at-forecast test. Phase 2 copies the test patterns from `succession_models/tests` and `turnover_forecast/tests`.

### 5.2 Seed policy

- One integer seed per run, recorded in `run_manifest.json`; default `20261107`.
- RF, GBM and Monte Carlo intervals take the seed explicitly; LightGBM with `deterministic=True, num_threads=1`.
- A test runs the full pipeline twice on the synthetic fixture and asserts byte-identical published tables.

### 5.3 Data as-of, versions and identifiers

Every published row carries `model_version` (`A-<learner>-<yyyymmdd>` / `B-<method>-<yyyymmdd>`), `protocol_version` (`wap-protocol-v1`), `run_id`, `data_as_of`. `dim_model_version` records the seed, the Phase 1 feature-table hash, the training window, the pass/fail of every threshold above and the fairness flags.

---

## 6. Publication and restriction

### 6.1 Published (export folder → Power BI)

Only the tables in `delivery/star_schema.yaml`, with:

- `n` (the count the cell is based on) on every fact row; primary suppression when `n < 10`; complementary suppression within the parent group (succession_models `governance.suppress` rule: if a group has exactly one suppressed cell and other published cells, the next-smallest cell is also suppressed);
- suppressed rows keep their keys and `suppressed = true`, with every measure null;
- no `edw_pers_id`, `posn_nbr`, name, birth date, sex, race/ethnicity, ZIP or address column (the export gate refuses them; `delivery/validate_star_schema.py` checks);
- a manifest with row counts, suppressed counts, `k_min`, hashes.

### 6.2 Restricted (approved machine only)

Position-level expected counts, per-person scores, per-group fairness tables with n < 50, any table keyed by `edw_pers_id` or `posn_nbr`, the demographics frame. Written only via a `write_restricted` path with the `README_RESTRICTED.txt` banner.

### 6.3 Person-level gate

Person-level Model A scores are **disabled by default**. They run only when `WAP_ENABLE_PERSON_LEVEL=1` **and** either the input is the synthetic fixture or `governance/approval.json` records sign-off by University Counsel, the Office for Access and Equity and Illinois Human Resources. Even then they go to the restricted folder only and never to a dashboard. This is the succession_models gate, reused as is.

---

## 7. Model card template (one per model version; generated, not hand-edited)

```
# Model card: <model name> (<model_version>, <protocol_version>)
> Generated by <script> on <date> from the <run label> run. Synthetic / real: <which>.
## Intended use            (unit of reporting; who reads it; what it must not be used for)
## Governance              (gate status; HB 3773 statement; Counsel/OAE/IHR status; notice status)
## Data                    (Phase 1 table hash; data_as_of; bitemporal or effective-only; rows; label audit result)
## Features                (included; excluded with reason; proxies retained for audit)
## Method                  (learner, fixed hyper-parameters, recalibration, seed)
## Validation              (design; per-origin and mean metrics vs baselines; threshold table with PASS/FAIL per id)
## Calibration             (slope, intercept, ECE; decile table; reporting-grain coverage)
## Fairness                (four-fifths and Fisher by attribute; equalized-odds gaps; calibration by group; historical disparity; flags)
## Ablations / sensitivity (age ablation; S1–S3 or B hierarchy check)
## Limitations             (honest reading; what failed; what is assumed)
## Monitoring              (next retrain date; drift metrics; who is notified)
```

---

## 8. Protocol-version bump rule

Any of the following requires a new label (`wap-protocol-v2`, …) and a line in the change log below, **before** the new run; the old results stay in the repository:

- a threshold, baseline, metric definition, suppression rule or gate changes;
- a feature is added or removed (except the pre-registered S1–S3 sensitivity runs and the age ablation);
- a label definition changes (including the rename in 2.7);
- the origin set, horizon set or reporting grain changes;
- a learner's fixed hyper-parameters change.

Re-running the same protocol on new data (a scheduled retrain) is a new `model_version`, not a new protocol version. Results that fail thresholds are published as failures in `fact_model_quality`; they are never deleted or re-run with altered settings under the same label.

| Version | Date | Change |
|---|---|---|
| wap-protocol-v1 | 2026-11-07 | Initial pre-registration |

---

## 9. Monitoring and retrain cadence

| What | Cadence | Action |
|---|---|---|
| Phase 1 feature refresh and DQ audit | quarterly, after the EDW quarter close | Blocks scoring if a DQ gate fails |
| Model B re-forecast | quarterly (new origin, same fitted protocol) | Published with the new `data_as_of`; backtest metrics appended |
| Model A re-score | quarterly | Expected counts refreshed; fairness audit re-run on the new scored set |
| Full retrain (both models) | annually, or when drift triggers | New `model_version`, new model cards, thresholds re-checked |
| Drift triggers | checked each quarter | Model A: ECE > 0.03 or calibration-in-the-large beyond ±1.5 pts on the most recent resolved horizon; Model B: rolling 4-quarter MASE relative > 1.05; either: any new `adverse impact indicated` flag |
| Fairness re-audit | every retrain and every re-score | Required by section 4 |
| Suppression check | every publish | `validate_star_schema.py` runs before the Power BI refresh |

---

## 10. HB 3773 statement (Illinois Public Act 103-0804, effective 2026-01-01)

The Act makes it a civil-rights violation for an employer to use AI that has a discriminatory effect in recruitment, hiring, promotion, discharge, discipline, tenure or terms of employment, bars ZIP code as a proxy, and requires notice to employees.

This protocol's position, which the Phase 2 and Phase 3 builders must keep:

1. **No employment decision.** No output of Model A or Model B is used, or is designed to be used, to make or influence a decision about a named employee: not promotion, not selection for training, not assignment, not pay, not discharge, not encouragement to retire. The published outputs are role- and unit-level expectations and forecasts.
2. **Person-level scores are a gated intermediate.** They are disabled by default and, if ever enabled after Counsel, OAE and IHR sign-off, they are an advisory input to a human-led talent-pool discussion with notice, a human decision-maker, logging of the AI suggestion versus the final decision, and periodic adverse-impact review.
3. **Proxies.** ZIP code, address, commute, leave usage, performance ratings and age-derived fields are excluded from feature matrices. Tenure fields are age-correlated and are retained only under an explicit audit (section 4) with a pre-registered removal path (S3).
4. **Testing.** Four-fifths selection-rate ratios with Fisher exact tests, equalized-odds gaps and calibration by group are run at every retrain and every re-score, with results recorded in the model card and `fact_model_quality`.
5. **Notice and registry.** The models are entered in the University's AI tool registry; employee notice is given even though IDHR's notice rules were withdrawn (status **[UNVERIFIED: check the Illinois Register]**, see `research/HR_USE_CASES_AND_GUARDRAILS.md`).
6. **Age (ADEA).** Age enters Model B only as a unit-level population share for retirement forecasting and Model A only in a non-published ablation.
7. **Mapping status.** SUCSS → O*NET → SOC bridge fields are unreviewed suggestions until an HR analyst confirms them; external context derived through them is labelled as such.
