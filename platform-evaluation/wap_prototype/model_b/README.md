# Model B: workforce growth and attrition-risk forecast (wap-protocol-v1 section 3)

Synthetic v3 data only (the Phase 1 restricted tables built by `python -m wap_prototype.publish` from the v3
Cookbook longitudinal pack). Built exactly to the pre-registered protocol `protocol/MODEL_PROTOCOL_v1.md`
section 3 with the metrics and thresholds in `protocol/scorers.py`; nothing was loosened after seeing results,
and the places where the protocol could not be applied as written on this population are listed under
*Where the protocol meets this data*. Person- and unit-level unsuppressed series stay in `outputs/restricted/`
(gitignored); everything in `outputs/` is suppressed at k = 10 with complementary suppression and validates
against `delivery/star_schema.yaml`.

```bash
cd platform-evaluation
python -m wap_prototype.publish                       # Phase 1 restricted tables (if outputs/restricted/ is empty)
python -m wap_prototype.model_b.series                # quarterly series panel                     (~1 s)
OMP_NUM_THREADS=1 python -m wap_prototype.model_b.backtest --workers 4   # rolling-origin backtest  (~50 s on 4 cores)
python -m wap_prototype.model_b.forecast              # latest-origin forecasts, risk score, burden check (~15 s)
WAP_RUN_DATE=2026-11-07 python -m wap_prototype.model_b.publish_b   # star-schema tables, manifest, validation, MODEL_CARD.md
python -m unittest discover -s wap_prototype/model_b/tests -t . -v   # 22 tests (~10 s)
```

Python 3.13; numpy, pandas, pyarrow, scipy, statsmodels 0.15, scikit-learn 1.9, lightgbm 4.7 (`requirements.txt`;
nothing new was installed). `turnover_forecast/models.py` is not imported (its `design()` is bound to the 14-state
QWI panel and `H = 8`); its rolling-origin, empirical-interval, COVID-dummy and ensemble patterns are re-implemented
here with the protocol's H = 12 and the metrics taken from `protocol/scorers.py`.

## What is built

| Module | Output | What it does |
|---|---|---|
| `config.py` | | Every fixed setting: seed 20261107, k = 10, H = 12, origin rule, warm-up 8, minimum 12 errors, learner hyper-parameters, cause groups, covariate names. |
| `series.py` | `outputs/restricted/series_panel.parquet`, `series_registry.csv`, `panel_meta.json` | Quarterly series per dept x family and campus x family: headcount, FTE, hires, internal moves in/out, separations by cause group (voluntary = `separation_resignation`; retirement; other = end of appointment + involuntary + death + other; end of appointment also kept alone for the sensitivity target), unit covariates (share 55+, share near SURS eligibility, dept churn, OEWS pay ratio, BLS growth and separation rate) and external covariates by quarter (QWI IL 6113 separation and hire rates lagged 3 quarters, QCEW IL state-government colleges employment growth lagged 2 quarters). Flows come from snapshot membership so conservation holds exactly. Pooling rule: mean headcount < 10 is pooled to campus x family. |
| `learners.py` | | B-snaive, B-ets, B-pooled, B-gbm, B-ens on `log(1 + y)`; design matrix dated at the origin; COVID dummy on training targets only. |
| `backtest.py` | `outputs/restricted/backtest.parquet`, `risk_backtest.parquet`; `outputs/metrics_b.json` | Rolling-origin backtest, empirical intervals, MASE / sMAPE / coverage / bias per series x horizon x method, headcount-weighted and unweighted, per-origin values, hierarchy check, attrition-flag backtest, thresholds B1-B7 via `scorers.check_thresholds_b`, pre-registered learner selection. `--summarize-only` recomputes the metrics from the saved rows. |
| `risk.py` | | Attrition-risk score and flag (protocol 3.5) with a seeded path-bootstrap interval; disparate-burden check (protocol 4). |
| `forecast.py` | `outputs/restricted/forecast_latest.parquet`, `risk_latest.parquet`, `disparate_burden_groups.csv`; `outputs/forecast_meta.json` | 1-12 quarter forecasts from 2026-12-31 with P10/P50/P90 (and 2.5/97.5) for every learner plus the `primary` series that follows the selection; risk score and flag; burden check. |
| `publish_b.py` | `outputs/fact_attrition_forecast.csv`, `fact_attrition_risk.csv`, `fact_model_quality.csv`, `dim_model_version.csv` (+ `dim_date`, `dim_org`, `dim_role_family`, `dim_scenario` as a Model B subset), `export_manifest.json`, `validation_report.json`, `MODEL_CARD.md` | Star-schema shape, k >= 10 primary + complementary suppression on every fact, SHA-256 manifest, `validate_star_schema.py` table checks, generated model card. |
| `tests/test_model_b.py` | | 22 tests, listed below. |

## Series construction and what the data allow

44 quarterly snapshots 2016-03-31 .. 2026-12-31 (`data_as_of` = 2026-12-31, the last snapshot; the pack's
extract date is 2027-01-31), 611 to 821 people. Flows between consecutive snapshots: an entry is a `hire` when a
hire/rehire event falls in the two-quarter window ending at the snapshot, else an internal `move_in`; an exit is a
separation of the matched event's cause group, else `move_out`. The two-quarter window exists because a termination
record posted after the quarter end is not yet known at that snapshot (Phase 1 as-known rule), so the person still
counts at q-1 and leaves the headcount one quarter after the event date; with a one-quarter window 165 of 839
visible separations were misclassified as internal moves. Result: 838 of the 839 separations visible at a prior
snapshot are matched (20 more separate inside the quarter they were hired and never appear in a snapshot), 1,049 of
1,056 snapshot-visible hires, and `headcount[q-1] + hires + moves_in - separations - moves_out = headcount[q]` holds
on every one of the 260 series (max residual 0, tested).

| Grain | Series | Mean headcount >= 10 (modelled) | Note |
|---|---:|---:|---|
| dept x job family | 227 | **0** (largest 9.7) | The protocol's primary grain is empty on an 813-person set; every dept series pools to its campus x family parent. |
| campus x job family | 33 | 29 | The published grain. The four below 10 (U10 Accountant 4.2, U10 Payroll 6.9, U30 Payroll 8.4, U30 Storekeeper 8.7) are published as suppressed rows. |

Quarterly counts per modelled series are small: mean headcount 22, hires 0.6 / quarter, separations 0.5
(voluntary 0.3, other 0.17, retirement 0.01). `sep_retirement` cannot be scored by MASE at all: its in-sample
lag-4 seasonal-naive error is zero on nearly every series (36 retirements in the whole pack), so the scale is 0.

## Backtest (protocol 3.4)

Origins every quarter from 2018Q4 (12 quarters of history) to 2026Q3 (32 origins); the first 8 are warm-up, so
24 scored origins 2020Q4..2026Q3; horizons 1-12; every learner on the common (series, origin) set per horizon;
empirical 80/95% intervals from the method's own log1p errors with target quarter <= origin, minimum 12, **pooled
across series** within target x method x horizon (24 origins x 29 short series do not give 12 resolved errors per
series and horizon early enough; recorded in the card). Metrics are headcount-weighted across series; unweighted
means and per-origin values are in `metrics_b.json` and `fact_model_quality`. The synthetic data has no COVID shock:
the dummy machinery runs (training targets 2020Q1-2021Q2 flagged, 0 at forecast time, tested) and the
"excluding COVID target quarters" metrics are produced, but they differ from the full set only by the quarters
removed.

Relative MASE vs B-snaive (headcount-weighted, < 1 = better), the two gating targets. Full tables for every
target and the sensitivity target are in `MODEL_CARD.md`.

**headcount**

| Method | h1 | h2 | h3 | h4 | h5 | h6 | h7 | h8 | h9 | h10 | h11 | h12 | h1-4 | h5-12 | cov80 | cov95 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| B-snaive | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 0.84 | 0.95 |
| B-ets | 0.82 | 0.91 | 0.96 | 1.01 | 0.84 | 0.89 | 0.91 | 0.95 | 0.79 | 0.82 | 0.85 | 0.88 | 0.93 | 0.87 | 0.84 | 0.95 |
| B-pooled | 0.71 | 0.83 | 0.94 | 1.05 | 0.85 | 0.91 | 0.88 | 0.97 | 0.75 | 0.82 | 0.88 | 0.84 | 0.88 | 0.86 | 0.82 | 0.94 |
| B-gbm | 0.77 | 0.85 | 0.92 | 0.97 | 0.80 | 0.84 | 0.87 | 0.92 | 0.76 | 0.81 | 0.83 | 0.85 | 0.88 | 0.83 | 0.82 | 0.94 |
| B-ens | 0.74 | 0.84 | 0.91 | 0.96 | 0.78 | 0.83 | 0.86 | 0.91 | 0.74 | 0.77 | 0.80 | 0.81 | 0.86 | 0.81 | 0.81 | 0.94 |

**separations (total)**

| Method | h1 | h2 | h3 | h4 | h5 | h6 | h7 | h8 | h9 | h10 | h11 | h12 | h1-4 | h5-12 | cov80 | cov95 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| B-snaive | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 0.85 | 0.96 |
| B-ets | 0.86 | 0.86 | 0.84 | 0.85 | 0.91 | 0.90 | 0.90 | 0.88 | 0.88 | 0.88 | 0.85 | 0.85 | 0.85 | 0.88 | 0.78 | 0.95 |
| B-pooled | 0.84 | 0.85 | 0.84 | 0.85 | 0.89 | 0.90 | 0.92 | 0.93 | 0.97 | 0.88 | 0.97 | 0.92 | 0.85 | 0.92 | 0.71 | 0.88 |
| B-gbm | 0.87 | 0.87 | 0.87 | 0.89 | 0.93 | 0.92 | 0.93 | 0.95 | 0.94 | 0.94 | 0.95 | 0.91 | 0.87 | 0.93 | 0.73 | 0.92 |
| B-ens | 0.85 | 0.85 | 0.84 | 0.85 | 0.89 | 0.89 | 0.89 | 0.90 | 0.90 | 0.88 | 0.91 | 0.88 | 0.85 | 0.89 | 0.74 | 0.94 |

Other targets (h1-4 / h5-12 relative MASE, B-ens): hires 0.82 / 0.84, sep_voluntary 0.88 / 0.94, sep_other 0.90 /
0.94, sep_voluntary_incl_eoa 0.86 / 0.89; sep_retirement not scorable (scale 0). Every learner beats seasonal naive
on every gating band; the gains are 7-19% at h1-4 and shrink with horizon, and B-ets is *worse* than seasonal naive
on headcount at exactly h = 4 (1.01) while B-pooled is at 1.05 there. Unweighted means (`h1-12 u` in the card) are
within 0.03 of the weighted ones. Weighted 80% coverage is 0.79-0.84 for the learners and 95% coverage 0.94-0.95;
seasonal naive's own empirical intervals cover 0.84-0.96, slightly over-wide. sMAPE is in the card but is dominated
by zero quarters on count targets (0 vs 0 scores 0, anything vs 0 scores 200), which is why B-snaive looks best on
it; MASE is the gating metric.

### Thresholds (protocol 3.6) and the pre-registered choice

| Id | Criterion | B-snaive | B-ets | B-pooled | B-gbm | B-ens |
|---|---|---|---|---|---|---|
| B1 rel. MASE h1-4 <= 0.95 (worst of headcount, separations) | 1.000 FAIL | 0.927 PASS | 0.882 PASS | 0.879 PASS | 0.861 PASS |
| B2 rel. MASE h5-12 <= 1.00 | 1.000 PASS | 0.881 PASS | 0.923 PASS | 0.935 PASS | 0.894 PASS |
| B3 80% coverage in [0.70, 0.90] | 0.885 PASS | 0.810 PASS | 0.788 PASS | 0.795 PASS | 0.794 PASS |
| B4 95% coverage >= 0.88 | 0.959 PASS | 0.952 PASS | 0.946 PASS | 0.937 PASS | 0.943 PASS |
| B5 headcount bias at h=4 within 2% | -0.024 FAIL | -0.014 PASS | 0.020 PASS | 0.004 PASS | 0.003 PASS |
| B6 hierarchy discrepancy <= 5% | not testable | not testable | not testable | not testable | not testable |
| B7 attrition-flag precision >= 0.60 | 0.238 FAIL (5/21) | **0.600 PASS (6/10)** | 0.143 FAIL (1/7) | 0.357 FAIL (5/14) | 0.300 FAIL (3/10) |

- **B6 is not testable**: no dept series is modelled, so there is no bottom-up sum to compare with the direct
  campus x family forecast. `check_thresholds_b` receives NaN and records a FAIL for every method; it does not
  separate the methods and is excluded from the selection rule. `passes_all_thresholds` is therefore `false` for
  every version in `dim_model_version`.
- **Chosen learner: `B-ets`**, by the protocol rule "B-ens is the default unless it fails a threshold that another
  method passes": B-ens fails B7 and B-ets passes it. Tie-break (not in the protocol; fixed in `select_learner`):
  most gating thresholds passed, then lowest gating relative MASE. Published for all horizons 1-12 (B-ets passes
  B1, so no seasonal-naive substitution for h <= 4).
- **That choice is fragile and the card says so.** B7 rests on 10 flags for B-ets (6 above the realised peer p75)
  against 10 for B-ens (3). With a same-campus peer set of 9-11 units, about 25% of units exceed the p75 by
  construction, so every method except B-ets sits at the base rate and B-ets passes at exactly 0.60. On point
  accuracy B-ens is better than B-ets on every band of both gating targets. The result is reported as the protocol
  requires and not re-run; a v2 protocol should give B7 a minimum number of flags.

## Forecasts from 2026-12-31 (published, `primary` = B-ets)

348 of 396 primary cells are published (the 48 suppressed cells are the four unmodelled campus x family series).
Summed over published cells, headcount at h = 4 (2027Q4) is forecast at 231 (P10-P90 of the per-cell sums 213-256)
for U10 against 225 modelled now, 286 (263-316) vs 282 for U20 and 287 (265-317) vs 285 for U30: flat to slightly
up, with the usual Q2 / Q4 separation seasonality. Four-quarter separations 24 / 22 / 19 against 29 / 29 / 14 in
the trailing four quarters. ETS on 44 points of a 20-person series is a smoother, not an oracle.

**Attrition risk** (`fact_attrition_risk`, 29 units, all published): expected 4-quarter separation rates 0.02-0.24
with 80% intervals typically 0.03-0.25; one unit is flagged (U10, a 14-person family whose P10 0.12 and trailing
observed 0.16 both exceed the campus p75 of 0.115). The peer set is the same campus (9-11 modelled families),
because the protocol's "same campus, same family" peers of a dept unit collapse to the unit itself at the pooled
grain; `risk.py` switches to the protocol's rule automatically when dept series exist.

**Disparate-burden check** (protocol 4, reported not gating): with one flagged unit of 14 people against 778
in unflagged units, sex and age-45+ show share gaps of 15.0 and 14.1 points (burden flag raised; race/ethnicity
groups all below 10 on the flagged side, suppressed). A 10-point gap on a 14-person unit is one or two people; the
flag is a statement about that unit, not the model, and the prescribed response is HR review of the unit.
`dim_model_version.fairness_flag` carries `burden_flag` for this version.

## Published outputs and the Phase 3 contract

`outputs/` holds the four required tables and four supporting dimensions, all passing `validate_star_schema.py`'s
table checks (`validation_report.json`: 0 errors; the warning lists the tables the Phase 3 assembler owns). Every
fact row carries `n`, `suppressed`, `model_version`, `data_as_of`; `export_manifest.json` has row counts, suppressed
counts, `k_min`, SHA-256 per file, `run_id`, seed and the Phase 1 feature-table hash.

| Table | Rows | Suppressed | Notes for the assembler |
|---|---:|---:|---|
| `fact_attrition_forecast` | 2,376 | 288 | 33 campus x family series x 12 horizons x 6 scenarios (`primary`, `snaive`, `ets`, `pooled`, `gbm`, `ens`). `n` = mean headcount over the 4 quarters before the origin. `org_key` points at campus nodes (`dim_org` has campus rows only); `is_bottom_up = false` everywhere because no dept series exists. `*_actual` null, `actual_known = false` (target quarters are after `data_as_of`). |
| `fact_attrition_risk` | 29 | 0 | `n` = headcount at the origin; `attrition_flag` null when fewer than 5 peers or no interval. |
| `fact_model_quality` | 4,741 | 0 | `origin_date_key = 0` mean rows per horizon and metric, per-origin `mase_rel_<target>` rows for the gating targets, threshold rows B1-B7 (`threshold_pass` null for B6), `*_xcovid` band rows, `burden_share_gap_pp` / `groups_suppressed` fairness rows with `fairness_flag` in {none, burden_flag, not_applicable}. Metric names carry the target as a suffix (`mase_rel_headcount`, `cov80_separations`, ...): the contract's enumerated list needs these additions, which the validator does not check. |
| `dim_model_version` | 5 | | One row per learner (`B-<method>-20261231`); `is_published_default` on `B-ets`; `fairness_flag` uses the Model B value `burden_flag` (an addition to the contract vocabulary). |
| `dim_date`, `dim_org`, `dim_role_family`, `dim_scenario` | 56 / 3 / 11 / 6 | | Model B subset so the foreign keys resolve here; the assembler replaces them and re-keys `org_key` / `role_family_key` (both are assigned by sorted code here, mapping in the dimension files). `scenario_cd` values `pooled`, `gbm`, `ens` are additions to the contract's list. |

## Where the protocol meets this data (honest reading)

1. **The dept x family grain is empty.** Not one of 227 dept series averages 10 people. The published grain is
   campus x family, and even there four series are suppressed. On a population this size the annual campus x family
   grain that Phase 1 already publishes is the realistic one; the quarterly cells here are publishable only because
   each modelled series has mean headcount >= 10, and the smallest published quarterly forecasts are for 12-15 people.
2. **B6 cannot be tested and B7 is decided by 10 flags.** See above. Both need a v2 rule (a minimum flag count for
   B7; a statement that B6 is void when no child series is modelled).
3. **The peer set for the risk flag is the campus, not campus x family**, for the reason in 1.
4. **Empirical intervals are pooled across series**, which the protocol does not forbid but does not say.
5. **No COVID shock** in the synthetic data; the mechanism is tested, its effect is not.
6. **External covariates are one vintage** (pseudo-out-of-sample, as turnover_forecast records), and QCEW ends
   2024Q4 so 2025-2026 origins carry a forward-filled value; the BLS projections are static per SOC and enter as a
   series-level mean through the unreviewed SUCSS -> O*NET -> SOC bridge (`external_chain_review_status = unreviewed`
   on every row, 100% null for the synthetic Academic Professional family).
7. **Hires from snapshot membership** exclude the 20 people hired and separated inside one quarter; Phase 1's
   event-count `hires` in `unit_quarter_aggregates` is the higher number.
8. **Determinism.** Two full backtest runs produced byte-identical `backtest.parquet` and `metrics_b.json`
   (hashes in the run record below), and `publish_b.py` run twice gives byte-identical CSVs (tested).

## Tests (22, all passing)

- **Leakage.** `truncate` blanks the future; the design matrix is identical when every quarter after T is replaced
  by noise (not blanked); a full five-learner forecast is identical under that perturbation with and without
  truncation, on the synthetic fixture and on the real panel; prediction rows never carry the COVID dummy while
  training rows inside the window do; empirical intervals at origin T do not move when actuals after T change and
  need 12 resolved errors.
- **Determinism.** Learners give identical output twice; stored backtest rows are recomputed exactly; publishing
  twice gives byte-identical CSVs and manifest.
- **Thresholds.** `THRESHOLDS_B` pinned to the protocol values; the published checks equal
  `check_thresholds_b(threshold_inputs)`; the selection rule's four cases (default B-ens, another method passes
  what B-ens fails, B1-fail-h>=5 publication, all-fail seasonal naive).
- **Suppression and schema.** The complementary rule on a fixture; no published row with n < 10, suppressed rows
  all-null, the four unmodelled series present as suppressed; `validate_star_schema.py` table checks pass; the four
  required tables carry exactly the contract columns; no forbidden column; one default version; manifest k = 10.
- **Series.** Conservation on every series used (long table and dense arrays); a four-person fixture with a
  late-posted resignation, a hire and a dept move classifies as intended; the pooling rule.
- **Learners and risk.** Seasonal naive exact on a periodic series; ensemble geometric mean and missing handling;
  scorer hand values; the flag rule on a six-unit fixture, including "no interval, no decision".

## Run record

Run `B-78b0ef423588`, seed 20261107, `data_as_of` 2026-12-31, Phase 1 feature-table SHA-256
`2a0ee1f8ab19f6a0af0ca296a194f69d7c75566f33b6b7944f17d88a183431d8`. Backtest: 224 (target, origin) jobs, about 50 s on
4 cores. Two full backtest runs gave byte-identical `outputs/restricted/backtest.parquet` (SHA-256
`e652c2cc7a13a969efca4b3a7742eaf2b188de82e5638f2d5579911dc45dbf61`) and `outputs/metrics_b.json`
(`eb220c865224bcec3e9bf4f341db45583db3c21011f2e168e8e703e761fe27a2`).
