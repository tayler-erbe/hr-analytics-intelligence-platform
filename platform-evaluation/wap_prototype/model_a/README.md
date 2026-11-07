# Model A: promotion / role-transition likelihood (wap-protocol-v1)

Phase 2 of the Workforce Analytics Intelligence Platform prototype, built exactly to the pre-registered
[`../protocol/MODEL_PROTOCOL_v1.md`](../protocol/MODEL_PROTOCOL_v1.md) on the Phase 1 feature tables
(`../outputs/restricted/`). **Synthetic v3 data only**; every number below describes the v3 Cookbook longitudinal
generator, not the University. Nothing person-level leaves `outputs/restricted/` (gitignored); everything published is
a ladder-step x unit aggregate with k >= 10 and complementary suppression, in the star-schema shape of
[`../delivery/star_schema.yaml`](../delivery/star_schema.yaml).

**Pre-registered outcome of this run: "no skill beyond base rates".** No learner passes every threshold in protocol 2.6;
the published default is `A-base-step` (base-rate expectations by ladder step, labelled as such). The best candidate,
`A-logit`, fails A1 (AUC gain over the step baseline +0.019 against the required +0.03), A4 (calibration slope 1.66
after the pre-registered Platt step) and A8 (adverse-impact flags on age 40+ and race/ethnicity). Thresholds were not
loosened and no origin was dropped (AGENTS.md rule 4). Full detail in [`MODEL_CARD.md`](MODEL_CARD.md) (generated).

## Run

```bash
cd platform-evaluation
python -m wap_prototype.publish                     # Phase 1 inputs, only if outputs/restricted/ is missing (~8 s)
python -m wap_prototype.model_a.run_all             # train -> fairness -> evaluate -> aggregate -> model cards (~6 min, 4 cores)
# or step by step (same outputs):
python -m wap_prototype.model_a.train               # backtest, sensitivities, ablation, scoring fit  (~5 min)
python -m wap_prototype.model_a.fairness            # protocol 4 audit on every test-year set
python -m wap_prototype.model_a.evaluate            # metrics, thresholds A1-A9, selection, label audit
python -m wap_prototype.model_a.aggregate           # ROLE x UNIT fact tables, dims, contract validation
python -m wap_prototype.model_a.model_card          # MODEL_CARD.md + outputs/restricted/MODEL_CARD_RESTRICTED.md
python -W ignore -m unittest discover -s wap_prototype/model_a/tests -t . -v   # 39 tests (~1 min)
```

Options: `--origins 2022-12-31 2023-12-31`, `--learners A-base-family A-base-step A-gbm`, `--no-sensitivity`,
`--no-ablation`, `--seed`, `--out`. Environment: `WAP_A_UNIT_LEVEL=campus|college|dept` (reporting unit, default
campus), `WAP_A_INPUT_DIR`, `WAP_A_OUTPUT_DIR`, `WAP_ENABLE_PERSON_LEVEL=1` (gate, see below). Python 3.13; numpy,
pandas, scikit-learn, lightgbm, scipy, pyarrow, PyYAML ([`requirements.txt`](requirements.txt); nothing new installed).

## Files

| File | What it does |
|---|---|
| `config.py` | Protocol constants: seed 20261107, origins, horizons, learners' fixed hyper-parameters, the logical -> physical feature map (protocol 0.1), exclusions, fairness attributes, star-schema scenarios, gate variable |
| `governance_bridge.py` | Imports (does not copy) `succession_models` `governance.suppress`, `check_exportable`, `write_restricted` and `config.approval_ok`; `person_level_gate` (protocol 6.3 with `WAP_ENABLE_PERSON_LEVEL`); `suppress_multi` = the same complementary rule over several parent groupings |
| `data.py` | Inputs, labels as known at an origin (events whose source row was known on or before it) vs latest (Phase 1 targets), the train / recalibration / test / scoring windows, feature frames in logical names with the exclusions enforced |
| `learners.py` | `A-base-family`, `A-base-step` (backoff 30), `A-logit` (L2, C by 5-fold CV inside training rows), `A-rf` (500 trees, leaf 50, sqrt, balanced), `A-gbm` (LightGBM 300 / 0.05 / 15 leaves / 100, deterministic, 1 thread), Platt recalibration |
| `train.py` | Out-of-time backtest for every learner, S1-S3 and the age ablation per ML learner, the scoring fit at data_as_of; predictions to `outputs/restricted/intermediate/` |
| `fairness.py` | Four-fifths + Fisher, equalized odds, calibration by group, historical base-rate disparity, n < 10 suppression; group rows restricted, per-attribute summaries public |
| `evaluate.py` | All protocol metrics through `protocol/scorers.py`, reporting-grain coverage, `check_thresholds_a`, the selection rule, sensitivities, A9, calibration tables, the 200-event label audit |
| `aggregate.py` | ROLE x UNIT expected counts with exact Poisson-binomial P10/P90, observed where resolved, pipeline coverage; suppression; `fact_promotion_expectation`, `fact_model_quality`, `dim_model_version` (+ minimal dims); per-table contract validation; person-level gate |
| `model_card.py`, `run_all.py` | Card generator (protocol 7 template) and the driver |
| `tests/` | Leakage (truncation and scrambling), determinism (byte-identical tables), pinned thresholds and selection rule, suppression, gate off by default, star-schema shape |

Outputs: `outputs/` (aggregates: `metrics_by_origin.csv`, `metrics_mean.csv`, `thresholds.csv`, `evaluation.json`,
`sensitivity.csv`, `calibration_deciles.csv`, `grain_cells_backtest.csv`, `fairness_summary*.csv`, `label_audit.json`,
`fit_log.csv`, `recalibration_log.csv`, `run_manifest.json`, `aggregate_summary.json`, `star/`), and
`outputs/restricted/` (gitignored, banner file: intermediate predictions, fairness group rows, the HR label-audit sheet,
the restricted model card, and `person_scores.parquet` only when the gate is open).

## How the protocol is bound

- **Origins and windows (2.5).** Origins Y = 2019-12-31 .. 2023-12-31 (all covered by Phase 1 history, none dropped).
  Train on snapshots with `snap_date + 18 months <= Y`; evaluate snapshots in (Y, Y+2] whose horizon resolved by
  data_as_of (2027-01-31). Platt recalibration is fitted on rows in (Y-2, Y] resolved by Y, scored by the model fitted at
  Y-2 (its own window ends at Y-2 minus 18 months), labels as known at Y; the model at Y-2 is the backtest model of that
  origin when Y-2 is itself an origin.
- **Labels (2.2, 5.1).** Training labels count a promotion event only if its source row was known
  (`row_known_from`) on or before the origin; evaluation labels are the Phase 1 target columns (latest knowledge). A
  test asserts the latest-knowledge derivation equals Phase 1's columns exactly.
- **Features (2.3).** The twenty logical features, bound to Phase 1 columns in `config.FEATURE_MAP`; `college` and `dept`
  are reporting dimensions; `age_band` enters only the `:age` ablation; `feature_frame` raises if an excluded column
  is requested. Categoricals one-hot (logit, RF) or native (LightGBM); numerics median-imputed with an indicator (logit,
  RF), native NaN (LightGBM). `level` is treated as an ordinal numeric.
- **Ablation and sensitivities.** Protocol 2.3 defines the ablation as "the primary learner refitted with age_band" and
  the 2.4 table names it "A-gbm plus age_band"; both are fitted (`<learner>:age` for each ML learner) and A9 is evaluated
  on the primary (or A-gbm when there is none). S1 (label `transition_12m` = promotion, lateral, down or
  reclassification within 12 months), S2 (external covariates dropped) and S3 (tenure proxies dropped) are fitted for
  every ML learner and reported, not gating.
- **Selection (2.4).** Best mean 12-month Brier skill vs `A-base-family` among ML learners passing A1-A8 at 12 months;
  ties within 0.5 pp go to logit -> RF -> GBM. A8 is applied as `scorers.check_thresholds_a` reads it (any "adverse
  impact indicated" flag fails); the protocol text's alternative ("documented flag and the gate stays closed") also
  holds here but is not the binding implementation, and the outcome does not depend on the reading (every learner also
  fails A1).
- **Fairness (4).** `age_40_plus` is implemented as age 40+ from the Phase 1 band, which carries a cut at 40 (the
  protocol's 45+ fallback is not needed; the data dictionary wins). Selection rule under test: top 10% of calibrated
  scores within each ladder step (ceil), ties broken by a seeded random draw. Per-origin audits are summarised as
  worst flag / min ratio / max gap across origins.
- **Reporting grain (2.1, 2.5, 6).** Unit = campus by default: on this 813-person population the ladder-step x college
  grain has no cell with n >= 10 (Phase 1 found the same for its dept grain), so the campus is the first grain with
  publishable cells. A7 pools a cell's test-year person-periods per origin, as the protocol words it. Published rows
  exist for every step x unit with >= 1 incumbent (suppressed rows visible as suppressed), both horizons, scenarios
  `primary`, `base_step`, `base_family`. Complementary suppression runs within ladder (steps) and within step (units).
- **Published snapshots.** Each origin quarter 2020-03-31 .. 2025-12-31 carries the out-of-time expectation of the
  backtest model whose window contains it (the latest origin Y with Y < snapshot <= Y+2), so `expected` vs `observed`
  is an honest out-of-sample comparison; 2026 quarters carry the live scoring fit at data_as_of (train through
  2025-06-30, recalibrated on the 2025-01-31 origin).
- **Pipeline coverage.** need = sum over incumbents of 1 - (1 - P(promotion)) (1 - P(separation)), with P(separation) the
  step base rate (backoff 30) of the separation label in the training years; supply = sum over the unit's other-step
  incumbents of P(promotion) x destination share into the step (training-year promotions). Coverage interval: seeded
  Monte Carlo (4,000 draws) over Bernoulli exits and entries.

## Results (means over the five origins; per-origin values in the card)

| Learner | h | AUC-ROC | AUC-ROC step | AUC-PR | prevalence | Brier skill vs family | vs step | CITL (pp) | slope | ECE | grain coverage |
|---|---|---|---|---|---|---|---|---|---|---|---|
| A-base-family | 12 | 0.581 | 0.703 | 0.065 | 0.053 | 0 | -2.5% | +0.72 | 2.80 | 0.018 | 0.52 |
| A-base-step | 12 | 0.703 | 0.703 | 0.087 | 0.053 | +2.4% | 0 | +0.83 | 2.23 | 0.018 | 0.74 |
| A-logit | 12 | **0.722** | 0.703 | 0.108 | 0.053 | **+2.7%** | +0.3% | +0.84 | 1.66 | 0.018 | 0.73 |
| A-rf | 12 | 0.718 | 0.703 | 0.106 | 0.053 | +2.3% | -0.1% | +0.94 | 1.05 | 0.016 | 0.73 |
| A-gbm | 12 | 0.702 | 0.703 | 0.096 | 0.053 | +2.1% | -0.4% | +0.18 | 1.38 | 0.016 | 0.70 |
| A-base-family | 18 | 0.578 | 0.704 | 0.093 | 0.077 | 0 | -3.4% | +1.13 | 2.44 | 0.025 | 0.44 |
| A-base-step | 18 | 0.704 | 0.704 | 0.125 | 0.077 | +3.3% | 0 | +1.35 | 2.13 | 0.026 | 0.64 |
| A-logit | 18 | 0.720 | 0.704 | 0.148 | 0.077 | +3.5% | +0.2% | +1.36 | 1.83 | 0.027 | 0.63 |
| A-rf | 18 | 0.720 | 0.704 | 0.153 | 0.077 | +3.3% | -0.1% | +1.50 | 1.10 | 0.026 | 0.63 |
| A-gbm | 18 | 0.699 | 0.704 | 0.136 | 0.077 | +2.8% | -0.5% | +0.53 | 1.49 | 0.023 | 0.57 |

Threshold checks (`outputs/thresholds.csv`; PASS/FAIL per id, means over origins):

| Learner | h | A1 | A2 | A3 | A3b | A4 | A5 | A6 | A7 | A8 | A9 review | all |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A-logit | 12 | FAIL | PASS | PASS | PASS | FAIL | PASS | PASS | PASS | FAIL | no | FAIL |
| A-rf | 12 | FAIL | PASS | PASS | FAIL | PASS | PASS | PASS | PASS | FAIL | no | FAIL |
| A-gbm | 12 | FAIL | PASS | PASS | FAIL | FAIL | PASS | PASS | PASS | FAIL | no | FAIL |
| A-base-step | 12 | FAIL | PASS | PASS | PASS | FAIL | PASS | PASS | PASS | PASS | no | FAIL |
| A-logit | 18 | FAIL | PASS | PASS | PASS | FAIL | FAIL | FAIL | FAIL | FAIL | no | FAIL |
| A-rf | 18 | FAIL | PASS | PASS | FAIL | PASS | FAIL | FAIL | FAIL | FAIL | no | FAIL |
| A-gbm | 18 | FAIL | PASS | PASS | FAIL | FAIL | PASS | FAIL | FAIL | FAIL | no | FAIL |
| A-base-step | 18 | FAIL | PASS | PASS | PASS | FAIL | FAIL | FAIL | FAIL | PASS | no | FAIL |

Reading: the ladder-step base rate is a strong comparator (AUC 0.70: promotion propensity in this generator is mostly a
property of the step). A-logit and A-rf add about +0.02 AUC and +0.2-0.3% Brier skill over it, below the A1 bar (+0.03).
The calibration slope failures are a property of the pre-registered recalibration design on a small population: the
Platt fit on the origin two years earlier has 1,300-3,000 rows and 78-142 positives, and for the 2019 / 2020 origins it
shrinks the scores to slopes of 0.1-0.4, so the test-year slope is far above 1; the raw (unrecalibrated) logit was in
fact better calibrated (CITL +0.55 pp, ECE 0.015). At 18 months every learner also misses A5-A7. Candidates ranked by
12-month Brier skill: A-logit, A-rf, A-gbm; none passes; published default A-base-step.

Sensitivities (12 months): S2 (no external covariates) and S3 (no tenure proxies) change AUC by < 0.005 for every
learner, so neither the unreviewed external bridge nor the age-correlated tenure fields carry information here; S1
(`transition_12m`, prevalence 10.4%) gives AUC 0.62-0.64 with Brier skill +3.8-4.3% vs family. Age ablation: A-gbm:age
minus A-gbm = -0.002 AUC (12 m), A-logit:age -0.001, A-rf:age +0.002; no A9 review triggered.

Reporting-grain backtest of the published default (A-base-step, campus x step, pooled test years, n >= 10): 74% of
cells inside P10-P90 at 12 months (A7 passes), 64% at 18 months (fails), mean signed bias -0.5 / -0.7 (expected below
observed per cell). On the published fact table the 12-month expectation over published resolved rows sums to 226
against 199 observed promotions.

## Fairness (protocol 4; group rows only in the restricted card)

| Learner | attribute | min impact ratio (12 m) | max TPR gap | max FPR gap | origins adverse / below 4/5 (of 5) | flag |
|---|---|---|---|---|---|---|
| A-logit | sex | 0.88 | 0.09 | 0.01 | 0 / 0 | none |
| A-logit | race_eth_rpt_cd | 0.00 | 0.45 | 0.15 | 5 / 0 | **adverse** |
| A-logit | age_40_plus | 0.38 | 0.26 | 0.11 | 5 / 0 | **adverse** |
| A-rf | sex | 0.79 | 0.12 | 0.03 | 1 / 0 | **adverse** |
| A-rf | race_eth_rpt_cd | 0.00 | 0.32 | 0.27 | 5 / 0 | **adverse** |
| A-rf | age_40_plus | 0.50 | 0.19 | 0.08 | 3 / 0 | **adverse** |
| A-gbm | sex | 0.77 | 0.11 | 0.03 | 1 / 0 | **adverse** |
| A-gbm | race_eth_rpt_cd | 0.00 | 0.67 | 0.22 | 3 / 2 | **adverse** |
| A-gbm | age_40_plus | 0.66 | 0.06 | 0.05 | 4 / 0 | **adverse** |
| A-base-step | sex / race / age | 0.91 / 0.49 / 0.91 | | | 0 / 5 (race) | none / below_4_5 / none |

Every ML learner selects people aged 40+ at well under four-fifths of the under-40 rate (p < 0.05 on most origins)
and at least one race/ethnicity group (n >= 10) at a zero or near-zero rate, under the top-10%-within-step rule. The
learner reaches age through administrative features even though age is excluded (as the succession_models readiness
audit found). Dropping the tenure proxies (S3) does not clear it: A-logit:S3 and A-rf:S3 keep the age flag, A-gbm:S3
clears it at 12 months only, and race stays flagged in every S3 run. The baselines show only chance-level "below
4/5, not significant" rows (their within-step scores are tied, so the selection is a lottery). The historical
base-rate test on the realized label itself (training years to 2023-12-31, 12 months) is also "adverse impact
indicated" for age 40+ (ratio 0.79), race/ethnicity (two groups, ratios 0.20 and 0.45) and sex (F 0.74): the synthetic
generator's promotion history is itself unequal and the learners reproduce and amplify it. Group-level rows are in
`outputs/restricted/MODEL_CARD_RESTRICTED.md`. The
person-level gate stays closed; `fact_model_quality` carries the per-attribute summaries and flags.

## Label audit (protocol 2.7) - PROVISIONAL

200 of the 804 candidate promotion events were sampled (stratified by `to_ladder`, seed 20261107) into
`outputs/restricted/label_audit_sheet.csv` with the rule evidence (from/to class, ladder and level, role family and
level, org, salary and FTE before/after, `level_direction`, `change_reason_code/desc/label`, `label_status`) and blank
`hr_classification` (promotion | reclassification | lateral | other), `hr_reviewer`, `hr_review_date`, `hr_notes`
columns. As a **provisional stand-in** for HR's review, the rule was compared with the generator's planted change-reason
codes: 200 / 200 sampled rule-promotions carry a source code labelled promotion (OT010 or PR001), and 804 / 804 source
promotion codes are called promotion by the rule (agreement 1.00, both directions), so the label keeps the name
`promoted_12m` / `promoted_18m`. This says the rule reproduces the generator, not that it matches HR's definition: on
real data HR completes the sheet on the approved machine and `evaluate.py` recomputes agreement from
`hr_classification`; below 0.85 every output is renamed `upward_transition_*`.

## Star-schema handoff (Phase 3)

`outputs/star/` holds `fact_promotion_expectation` (19,092 rows: 28 origin quarters x 3 campuses x 38 steps x 2 horizons
x 3 scenarios; 2,472 published, 16,620 suppressed of which 1,182 complementary), `fact_model_quality` (721 rows:
per-origin and mean metrics for the five learners, thresholds on the mean rows, per-attribute fairness rows,
`age_ablation_gain`, `label_audit_agreement`, the primary's S2 under `no_external` when a primary exists),
`dim_model_version` (5 rows, `is_published_default` on A-base-step), plus the minimal dimensions they key to
(`dim_date`, `dim_org` with the campus/college/dept hierarchy and titles from the pack's REF_ORG, `dim_role` one row per
class = ladder step with the O*NET/SOC bridge and `mapping_status`, `dim_role_family`, `dim_scenario`) and
`export_manifest.json` (row counts, suppressed counts, k_min, SHA-256 per file, run_id, data_as_of).

Validation: **each Model A table is validated here** against its contract spec with
`delivery/validate_star_schema.validate_table` (types, nullability, grain, foreign keys against the dims produced here,
forbidden columns, suppression), report in `outputs/star/validation_report.json` (0 errors). The full-folder check
(`validate_star_schema.py <folder>`, which requires every fact of the contract) is the Phase 3 assembler's step; the
assembler replaces the minimal dims with the canonical ones and remaps `org_key` / `role_key` (they are local sequential
keys here) through the natural keys (`campus_cd`/`college_cd`/`dept_cd`, `e_class` x `p_class`). Two notes for the
contract owner: `dim_scenario` carries an extra code `candidate` (scenario_key 4) so that non-selected learners' failed
thresholds are published in `fact_model_quality` as protocol 8 requires, and `critical_ind` comes from the synthetic
pack's REF_ROLE_FAMILY (an assumed critical-role list).

## Person-level gate (protocol 6.3)

Off by default. `aggregate.py` writes `outputs/restricted/person_scores.parquet` (scoring-run scores of the published
default with a rank within step) only when `WAP_ENABLE_PERSON_LEVEL=1` **and** either the input pack's manifest says
synthetic or `succession_models/governance/approval.json` records the Counsel, OAE and IHR sign-offs
(`succession_models.config.approval_ok`, imported). It never reaches `outputs/star/`. The intermediate backtest
predictions needed by `evaluate.py`, `fairness.py` and `aggregate.py` are written to `outputs/restricted/intermediate/`
through `succession_models.governance.write_restricted` (banner file); they are a pipeline intermediate, not the gated
product, and they stay on the machine.

## Limitations

- **Candidate label**, unconfirmed by HR; the audit is a provisional stand-in (see above).
- **Small synthetic population**: 813 incumbents, ~5% annual promotion rate, 78-142 positives per recalibration set; the
  ladder-step x college grain is fully suppressed at k = 10 and 87% of step x campus rows are suppressed. Suppression was
  not loosened.
- **Pre-registered recalibration design** over-shrinks on this population (slopes well above 1 after Platt); reported,
  not changed; a protocol v2 could reconsider the Y-2 recalibration origin.
- **Unreviewed SUCSS -> O*NET -> SOC bridge** behind the external features (`mapping_status = unreviewed` in `dim_role`);
  S2 shows they add nothing here.
- **A7** treats a person's repeated quarterly rows in a cell as independent Bernoulli draws.
- **Pipeline need** uses a separation base rate by step, not a fitted separation model (Model B's job); supply counts
  within-unit entrants only.
- **No real data path exercised**: the same code reads a real Phase 1 extract through `WAP_A_INPUT_DIR` on the approved
  machine; Counsel / OAE / IHR review, the HR label audit and the notice/registry status are open.

## Tests

`python -W ignore -m unittest discover -s wap_prototype/model_a/tests -t .` (39 tests): windows and as-known labels
(training snapshots resolve before the origin; recalibration rows in (Y-2, Y]; as-known labels never add positives;
latest labels equal Phase 1's); truncation and scrambling (deleting or scrambling every row after the origin, and
flooding later-keyed events, leaves the origin's fitted predictions byte-identical); the feature matrix never carries
age, protected attributes, college or dept and refuses them; determinism (same seed -> identical predictions and
metrics; the full pipeline twice -> byte-identical published tables and manifest); thresholds pinned to the protocol
constants and the selection / tie-break / A8 rules; suppression (`suppress_multi` equals `governance.suppress` for one
grouping, fixed point over two, no published cell below k, null measures and kept keys on suppressed rows, no lone
suppressed cell within ladder or step); the gate (closed by default, env alone insufficient on real data, synthetic or
complete approval opens it, no person-level file or column outside restricted); star-schema shape (validator report,
contract columns, grains, foreign keys, sentinels, one published default).
