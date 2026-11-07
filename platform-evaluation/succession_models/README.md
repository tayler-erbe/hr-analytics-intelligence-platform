# Succession planning models (EDW-ready, synthetic run)

This is a succession-planning modelling pipeline built to the EDW table shapes named in the repository README: `T_PERS_HIST`, `T_EMPEE_HIST`, `T_EMPEE_HIST_5`, `T_JOB_DETL_HIST`, plus position-control and reference tables. Here it runs end to end on **synthetic** history, through two selectable source bindings: the original **v1** layout (assumed column names, `extract.sql`) and the **v3 / Data Cookbook** layout (`--layout v3_cookbook`, `extract_v3_cookbook.sql`), which binds the Cookbook-verified table shapes of [`../sample_datasets/v3_cookbook/`](../sample_datasets/v3_cookbook/README.md). The v3 binding is the one to use on real EDW history on an approved AITS machine ([`run_real.md`](run_real.md)); the model code is the same in both.

**No real employee data is in this folder, and none may be brought into it or into a cloud session.**

Offline page: [`../output/succession_models/succession_planning.html`](../output/succession_models/succession_planning.html). It shows role and unit level only, with cells of n ≥ 10.

## Design principle

The primary outputs are **position- and role-level**: vacancy risk, bench coverage and pipeline flow. They are not person rankings. This follows the research brief:

- talent pools for role families rather than 1:1 replacement charts;
- no 9-box "potential" inputs;
- HB 3773 treats AI used in promotion and selection for training as a covered use.

The one person-level model, candidate readiness, is **disabled by default**. It sits behind a governance gate and comes with a model card and an adverse-impact audit.

## Run

From `platform-evaluation/` (Python 3.13; `pip install -r succession_models/requirements.txt`):

```bash
python succession_models/run_all.py                    # ~1-3 min: generate -> extract.sql -> gates -> backtest -> models -> page
python -m unittest discover -s succession_models/tests -v   # 31 tests, ~30 s (18 v1 + 13 v3)
# optional, synthetic only: demonstrate the gated person-level model and its fairness audit
python succession_models/run_all.py --label synthetic_readiness_audit --with-readiness-audit --no-page --no-erp-smoke
# the same pipeline on the Cookbook-shaped v3 pack (~20 s; --no-page keeps the v1 page in output/)
python succession_models/run_all.py --layout v3_cookbook --edw-dir sample_datasets/v3_cookbook/longitudinal \
       --skip-generate --label v3_cookbook --no-page
```

`--layout` (or `SUCC_LAYOUT=v3_cookbook`) picks the binding; without it everything is the v1 path, byte-identical to before the v3 binding existed (a test pins the hashes). The v3 run takes its extract date (2027-01-31) from the pack's manifest; three environment switches document the unconfirmed Cookbook semantics (`SUCC_V3_JOB_CHANGE_DATE`, `SUCC_V3_INPLACE_KNOWN_FROM`, `SUCC_V3_TERM_SOURCE`; see `config.py` and [`data_contract.md`](data_contract.md) §7).

`data/` and `runs/` are regenerable and git-ignored. Seed 20261106 reproduces every number below; a test checks that the generator is byte-identical between runs.

## Files

| Path | What it is |
|---|---|
| [`data_contract.md`](data_contract.md) | Minimal EDW fields, conventions, the bitemporal as-of rule, effective-only fallback, validation gates, output classification; §7 is the v3 / Cookbook binding |
| [`extract.sql`](extract.sql) | v1 extract, one `-- @extract NAME` block per output. Data-minimised: no names, IDs beyond `EDW_PERS_ID`, ZIP, leave or payroll. Protected attributes go to a separate restricted file |
| [`extract_v3_cookbook.sql`](extract_v3_cookbook.sql) | The same contract against the Cookbook tables: row-version interval from a window over `JOB_DETL_HIST_EFF_DT` per key lineage, `D` rows as deletion events, class key via `PAPE_CIV_SVC_ID` → SUCSS → `REF_ROLE_FAMILY` (crosswalk fallback), position org from jobs, ladder fallback for unmapped classes, separations from `T_EMPEE_HIST` (`_5` alternative) |
| `config.py` | Paths, parameters, SURS assumptions, `SOURCE_MAP` (v1) and `SOURCE_MAP_V3_COOKBOOK`, the three v3 switches and `resolve_layout()` |
| `extract.py` | Runs the layout's extract SQL (DuckDB over the synthetic "EDW", or a DB-API driver on the approved machine) and gates G1–G7 |
| `snapshot.py` | **Leakage firewall.** As-of features use only rows effective *and recorded* on or before the snapshot. Separately computes spells and labels, as known at an origin or from the latest data. The view layer maps v3 status descriptions to codes, applies `JOB_DETL_APPT_PCT`, and uses position pay ranges and `OPEN_POSN_IND` when the layout binds them |
| `features.py` | Model matrix, SURS Tier 1/2 eligibility bands (assumption-labelled), roll-forward for multi-period projection |
| `vacancy.py` | (a) Discrete-time cause-specific logistic hazards, Cox PH and Weibull AFT (lifelines), recalibration, baselines, Poisson-binomial aggregation |
| `mobility.py` | (b) Markov class-transition matrix with Dirichlet smoothing and Beta credible intervals; feeder, dead-end and fast-track roles; pathway diversity; reach-critical probability |
| `bench.py` | (c) Bench strength per critical role family: internal supply vs need, Monte Carlo coverage interval, realized-flow backtest |
| `readiness.py`, `fairness.py` | (d) Optional LambdaMART/logistic readiness ranking, **gated**; four-fifths with Fisher test, equalized odds (fairlearn), n ≥ 10 suppression |
| `validate.py`, `metrics.py` | Out-of-time backtest, Brier, IPCW time-dependent AUC, C-index, calibration deciles, parameter recovery, oracle comparator |
| `governance.py` | Suppression (primary and complementary), export gate, restricted writer |
| `synth_edw.py` | Seeded synthetic bitemporal EDW-shaped history with **known** parameters (`truth.json`). Reuses erp_readiness by import |
| `build_page.py` | Offline HTML from the `export/` folder only |
| `model_cards/` | Generated cards: vacancy, mobility and bench, readiness |
| [`run_real.md`](run_real.md) | Runbook for the approved machine: environment, extract, gates, sign-off checklist (Counsel, OAE, IHR), what may leave (k ≥ 10 aggregates only) |
| `governance/approval.template.json` | Template for the sign-off record that, with `SUCC_ENABLE_PERSON_LEVEL=1`, opens the person-level gate. The real `approval.json` is git-ignored |
| `tests/test_succession.py`, `tests/test_v3_cookbook.py` | v1 leakage, reproducibility, calibration, suppression and gate tests; v3 layout resolution, the seven gates on the v3 pack, the as-known snapshot on a tiny Cookbook-shaped fixture (late-keyed correction, late-keyed exit, `D` row), separation / FTE / pay-range / vacancy / ladder semantics, and the v1 hash pin |

### Reuse of erp_readiness (not modified)

`synth_edw.py` imports `erp_readiness/generate_synthetic.py`. It uses that module's `World.build_reference()` for the org tree and the public SUCSS catalog with invented pay ranges, and its `SCHEMAS`, which are extended with row-version columns.

That generator alone cannot test a succession model. It draws exits without age or pay structure, promotions are random, and it has no transaction time. So `synth_edw.py` simulates monthly appointment history with planted hazards, a planted transition matrix and late-keyed rows.

As a second-source check, `run_all.py` also runs `extract.sql`, the as-of builder and the hazard model **unchanged** on erp_readiness's own CLEAN output (900 persons) in effective-only mode. All gates pass except G4, which is the expected WARN for missing row versions. The 24-month AUC is 0.57, because exits in that generator depend on tenure only.

## Synthetic world (known parameters)

| Item | Value |
|---|---|
| History | 2004-01 to 2026-10, monthly simulation, 36 departments in 12 college-level units |
| Role families | 11: ten public SUCSS class ladders (Accountant I–III, Steam and Power Plant I–IV, …) plus a synthetic academic-professional ladder; 38 classes |
| Critical tiers | 7 families' senior levels (an **assumed** critical-role list) |
| Size | ~2,500 incumbents at the extract date; 7,904 synthetic persons in the extract; 5,382 separations; 5,570 internal moves |
| Bitemporal | Keying lag 0–14 days (70%), 15–60 (25%), 61–150 (5%); 6.3% of job rows first recorded more than 30 days late |
| Separation hazard (6-month logit) | intercept −3.3; tenure < 2 y +0.55; SURS unreduced-eligible +1.5; reduced-only +0.6; part-time +0.35; pay position −0.7; recent role change −0.35; family effects; unobserved department frailty SD 0.3 |
| Move hazard | intercept −2.9; ≥ 2 y in role +0.6; top level −0.9; pay position +0.5; SURS-eligible −0.8; two planted **dead-end** families −1.3 |
| Planted disparity (for the audit) | Synthetic group G2: move log-odds −0.45 and starting pay position −0.08 |

## Results on synthetic data (honest reading)

All figures describe the synthetic generator, not the University.

### (a) Vacancy risk: out-of-time backtest

Five origins (Jan 1 2020–2024). Each trains through Y on data *as known* and evaluates Y+1..Y+2, 2,370–2,462 incumbents per origin. Values are means over origins.

| Model | Brier 24 mo | Brier skill vs family rate | AUC(t) 12 / 24 mo | C-index | Calibration slope 24 mo |
|---|---|---|---|---|---|
| Logistic hazard, recalibrated | 0.2238 | +1.6% | 0.589 / 0.599 | 0.580 | 1.01 |
| Logistic hazard, no age/SURS features | 0.2245 | +1.3% | 0.585 / 0.593 | 0.575 | 0.97 |
| Cox PH | 0.2243 | +1.3% | 0.582 / 0.592 | 0.574 | 0.95 |
| Weibull AFT | 0.2243 | +1.3% | 0.582 / 0.592 | 0.574 | 0.95 |
| Baseline: role-family base rate | 0.2273 | 0 | 0.546 / 0.551 | 0.541 | 1.04 |
| Baseline: age band only | 0.2298 | −1.1% | 0.524 / 0.524 | 0.519 | 0.91 |
| Oracle: true generator parameters | 0.2235 | +1.7% | 0.589 / 0.600 | 0.580 | 0.92 |

What this means:

- **The hazard model is as good as the oracle**, and the oracle is not good: AUC is about 0.60. In this world, as in real HR data, most exits are not predictable from administrative fields.
- The useful output is therefore **calibrated expected counts for groups**, not a ranking of people.
- Calibration-in-the-large is within 0.3 percentage points at every horizon.
- Recalibration improves the 6-month slope from 0.90 to 1.00, and changes little else.
- Removing the age-derived SURS features costs 0.006 AUC. Reviewers can weigh that against ADEA and HB 3773 concerns.
- **Parameter recovery.** 35 of 40 planted hazard terms fall inside the 95% CI, with mean absolute error 0.084. The misses come from discretisation: the generator updates covariates monthly, while the model sees them at the start of each 6-month period. They are recent-change (−0.18 vs −0.35), the move intercept and in-role ≥ 2 y (0.43 vs 0.60), and two family contrasts.

At the extract date (2026-10-31), the model expects:

| Horizon | Expected vacancies | P10–P90 |
|---|---|---|
| 12 months | 519 | 493–544 |
| 24 months | 926 | 896–956 |

The P10–P90 ranges cover event noise only. Role-family 24-month rates run from 24% (Storekeeper) to 42%. Of the 129 unit × family cells, 29 are suppressed.

### (b) Mobility

- **Markov recovery.** Mean total-variation distance to the true destination rows is 0.090 (0.076 when weighted by moves). 96% of true non-zero cells fall inside their 95% interval.
- **Dead-end rule.** It flagged 2 classes, both in the planted dead-end families. It flagged none elsewhere, but it missed the other 4 classes of those families, so it is conservative.

### (c) Bench strength

Internal coverage (P50) runs from 0.44 (Health Care Administrator) to 0.79 (Client Relations Representative). Every critical tier is "Thin": P(coverage < 1) is at least 75%. That is expected in a world where most vacancies are filled externally.

Backtest over 35 family × origin cells:

| Quantity | Inside P10–P90 | Mean bias |
|---|---|---|
| Realized 24-month need | 28 of 35 (80%) | +1.0 |
| Realized internal supply | 33 of 35 (94%) | −1.3: supply is slightly over-forecast and the band is a little wide |

### (d) Readiness ranking: synthetic audit run only, disabled by default

| Model | AUC | NDCG@10 | Precision in top 10% |
|---|---|---|---|
| LambdaMART | 0.76 | 0.20 | 0.16 |
| Logistic | 0.77 | 0.25 | 0.15 |
| Random | 0.46 | — | 0.04 |

The base rate of moving into the target tier is 0.033. **The simple logistic model is at least as good as LambdaMART.**

The audit found:

- **Age 40+.** Selection-rate ratio 0.51, Fisher p < 10⁻⁸: *adverse impact indicated*. The model reaches age through the tenure and service proxies, even though age itself is excluded.
- **Sex.** Ratio 0.80 for F, p = 0.04, just at the four-fifths line.
- **Race/ethnicity.** The model did *not* reproduce the planted historical disparity: G2's historical move-rate ratio was 0.59, but its model selection ratio is 1.00. Groups G3 and G4 fall below four-fifths without statistical significance.

This is exactly why the model stays off by default. Full tables are in [`model_cards/readiness_model_card.md`](model_cards/readiness_model_card.md).

## Results on the v3 Cookbook-shaped pack (`runs/v3_cookbook`)

The same pipeline, default settings, on `sample_datasets/v3_cookbook/longitudinal` (`--layout v3_cookbook`, extract date 2027-01-31, person-level readiness off). All seven gates PASS; I1 reports 7.2% of job rows first recorded more than 30 days late. The pack re-expresses the integration layer's v2 longitudinal world, **not** the succession generator above, so the two runs describe two different synthetic populations: 2,302 persons and 822 incumbents (v1: 7,904 and ~2,500), 1,480 separations (v1: 5,382), 1,461 internal moves, 112 deleted (`D`) job versions, two-date job keys, Cookbook termination coding (TQ/TE/TR on `T_EMPEE_HIST`), 11 role families and 7 critical tiers from the same public SUCSS ladders. There is no `truth.json`, so no oracle and no parameter recovery.

### (a) Vacancy risk, five origins (Jan 1 2020–2024), 703–779 incumbents per origin

| Model | Brier 24 mo | Brier skill vs family rate | AUC(t) 12 / 24 mo | C-index | Calibration slope 24 mo | CITL 24 mo |
|---|---|---|---|---|---|---|
| Logistic hazard, recalibrated | 0.2287 | +2.7% | 0.602 / 0.610 | 0.587 | 0.89 | +1.7 pp |
| Logistic hazard, no age/SURS features | 0.2299 | +2.2% | 0.599 / 0.609 | 0.586 | 1.02 | +3.6 pp |
| Cox PH | 0.2311 | +1.7% | 0.590 / 0.601 | 0.580 | 0.88 | +2.7 pp |
| Weibull AFT | 0.2310 | +1.8% | 0.591 / 0.601 | 0.580 | 0.88 | +2.6 pp |
| Baseline: role-family base rate | 0.2352 | 0 | 0.544 / 0.552 | 0.539 | 0.93 | +2.9 pp |
| Baseline: age band only | 0.2378 | −1.1% | 0.506 / 0.506 | 0.505 | 0.31 | +3.0 pp |

Against the v1 run (Brier 0.2238, skill +1.6%, AUC 0.589 / 0.599, C-index 0.580, slope 1.01):

- **Discrimination is slightly higher (AUC 0.61 vs 0.60) and the Brier skill over the family base rate is larger (+2.7% vs +1.6%).** The v2-derived world has fewer exit drivers than the succession generator (no planted age structure: the age-only baseline is at chance, 0.506, and dropping the age-derived features costs 0.002–0.003 AUC against 0.006 in v1), but its base rates differ more by tenure and pay, which the hazard model picks up. Brier skill is positive at 12 and 24 months on all five origins (24-month skill +1.9% to +3.2%).
- **Absolute Brier is higher (0.229 vs 0.224)** because the 24-month exit rate is higher (37–40% per origin vs 35–37% in v1), so the outcome variance is larger. That is not a worse model.
- **Calibration is worse.** Calibration-in-the-large at 24 months is +1.7 pp on average (mean absolute 2.4 pp, against the pre-registered gate of ≤ 2 pp; 1.8 pp at 12 months passes) and ranges from −1.7 to +3.9 pp by origin; the 24-month slope is 0.89 (0.76–1.00 by origin, inside the 0.8–1.2 band on average). The likely reason is size: with roughly 700 incumbents and 270–300 events per origin, the recalibration set (the origin 24 months earlier) is about a quarter of v1's, so the intercept and slope estimates are noisier. Recalibration still improves the 24-month CITL from +3.4 pp to +1.7 pp. On real data the 24-month CITL miss would trigger the "recalibrate; report as uncalibrated" action in `run_real.md` §5.
- **The hazard model is no better than its own ceiling here either:** without planted parameters there is no oracle, but Cox, Weibull and the logistic hazard agree to 0.01 AUC, as they did in v1.

At the extract date (2027-01-31): 822 incumbents, 40 vacant positions (`POSN_STATUS_CD = 'A'`, `OPEN_POSN_IND = 'Y'`, no incumbent; the flag and job history agree on every position). Expected vacancies: **12 months 161 (P10–P90 147–176), 24 months 252 (235–269)**, i.e. 19.6% and 30.7% of incumbents (v1: 519 and 926 of ~2,500, 21% and 37%). Role-family 24-month rates run from 25% (Storekeeper) to 34% (Institutional Compliance Examiner); v1 ran 24–42%. Suppression bites harder in the smaller world: 4 of 38 role cells, and **88 of 119 unit × family cells** (v1: 29 of 129), are suppressed at k = 10; all 12 college-level units publish (54–93 incumbents each).

### (b) Mobility

771 moves in the 10-year window (v1: ~5,500). The dead-end rule flags 4 classes (Payroll Specialist II and all three Storekeeper levels: move rates 2.6–4.8% a year); there is no planted truth to score it against. Feeder tables are mostly suppressed below k = 10 moves: one unsuppressed feeder per critical family.

### (c) Bench strength

All seven critical tiers are "Thin": internal coverage P50 runs from 0.33 (Health Care Administrator) to 0.64 (Client Relations Representative) and P(coverage < 1) is 0.73–0.97 (v1: 0.44–0.79, ≥ 0.75). Backtest over 35 family × origin cells: realized 24-month need inside P10–P90 in **28 of 35 (80%)**, mean bias −0.2; realized internal supply inside in **34 of 35 (97%)**, bias +0.2 (v1: 28/35 and +1.0; 33/35 and −1.3). The bench band is well sized here; v1's slight over-forecast of supply does not recur.

### What the v3 run does and does not show

- The Cookbook binding runs the full pipeline end to end: extract, seven gates, as-known snapshots over `D` rows and two-date keys, hazard models, mobility, bench, backtest and metrics, in about 20 s.
- The differences from v1 are explained by the population (smaller, different exit drivers, higher exit rate), not by the binding: on the tiny fixture in `tests/test_v3_cookbook.py` every as-known reconstruction (late keying, correction, deletion, late-keyed exit) matches what HR would have seen.
- Ladder levels derived from position midpoints agree with the HR file's `ROLE_LEVEL` in only 4 of 11 families, because the pack's pay ranges are invented; the HR file stays authoritative and the ladder is used only as a fallback for unmapped classes (none in this pack).
- Everything still to confirm on real data is listed in `data_contract.md` §7 and in the v3 pack README (FTE fraction vs percent, the meaning of `JOB_DETL_HIST_EFF_DT`, the `PAPE_CIV_SVC_ID` format, the terminated employee status letter, leave status descriptions).

## Limits

- Everything is synthetic. The v1 column names, the row-version columns, `T_POSN_HIST`, the critical-role list, the SURS rules and the pay ranges are **assumptions** to confirm on the approved machine. The v3 binding uses Cookbook-verified names, but several **values** are still unconfirmed (see above).
- The DB-API extract path and the Oracle/Snowflake dialects are **untested**. Only DuckDB executed `extract.sql`.
- Covariate uncertainty in the hazard parameters is not propagated into the vacancy-count intervals. The bench interval includes Markov-matrix uncertainty and event noise only.
- Synthetic moves are push-driven: a line is created when none is vacant. Real moves are pulled by postings and civil-service registers.
- The page shows aggregate backtest tables. Subgroup calibration of the vacancy model by protected group is specified in `run_real.md` but is not computed on the synthetic data.
