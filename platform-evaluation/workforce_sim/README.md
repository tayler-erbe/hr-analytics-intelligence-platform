# Strategic Workforce Planning scenario simulator (prototype)

A quarterly Monte Carlo scenario planner for Strategic Workforce Planning and Succession Planning. It runs on a **synthetic** workforce whose aggregates mirror UIUC's published Fall 2023 IPEDS staff headcount (12,905). Separation hazards are calibrated to Census QWI for Illinois higher education. **No real employee data is used.** The outputs are scenario arithmetic under stated assumptions. They are not predictions about UIUC staff, and no individual is scored.

Open `../output/workforce_sim/scenario_planner.html`. It is a single offline file with no network calls.

## Run

From `platform-evaluation/` (Python 3.13, `pip install -r workforce_sim/requirements.txt`; the public lake must already be built with `scripts/lake_acquire.py`, `lake_build.py` and `lake_contract.py`):

```bash
python workforce_sim/calibrate.py        # lake -> workforce_sim/calibration.json (aggregates + sources + caveats)
python workforce_sim/synthesize.py       # seeded synthetic position/person/appointment tables -> workforce_sim/data/synthetic/
python workforce_sim/simulate.py         # 126-scenario grid x 150 runs x 20 quarters -> workforce_sim/data/scenario_grid.json
python workforce_sim/build_page.py       # -> output/workforce_sim/scenario_planner.html
python -m unittest discover -s workforce_sim/tests -v
```

`simulate.py --workers 4` runs scenarios in parallel. Each scenario takes about 6 s for 150 runs on one core. `data/` is regenerable and git-ignored. `calibration.json` holds public aggregates only.

| File | Role |
|---|---|
| `calibrate.py` | Derives public targets from the lake contract and silver tables. Asserts partition and contract/silver cross-checks |
| `calibration.json` | Targets, sources, the two hazard anchors and caveats |
| `synthesize.py` | Seeded synthetic workforce in three effective-dated, bitemporal tables. All assumptions are in `ASSUMPTIONS` |
| `simulate.py` | As-of snapshot loader (DuckDB), position-slot Monte Carlo engine, percentile summaries, scenario grid |
| `build_page.py` | Embeds the grid and calibration in the offline HTML planner |
| `tests/test_workforce_sim.py` | Reproducibility, conservation, grain/bitemporal, calibration tolerances, identifier hygiene |

## Calibration (public aggregates only)

| Target | Source (lake) | How it is used |
|---|---|---|
| Headcount by family × FT/PT (13 families, 12,905 = 11,712 FT + 1,193 PT) | contract `ipeds_staff_by_occupation`, UIUC 145637, `is_category_total = false`, sex/race = `Total`, FT and PT detail rows | Synthetic counts match exactly. The partition is asserted to equal the grand total |
| FT faculty rank mix (Prof 845, Assoc 587, Asst 764, Instr 96, Lect 176, No rank 30) | contract `ipeds_instructional_staff`, tenure-status × rank leaf rows | Matched exactly |
| Quarterly separation hazard by age group and seasonality, 2023Q3–2025Q2 | silver `qwi_il_sa_gs_n4_oslp` (NAICS 6113, all ownership, `SepS/EmpS`), with contract `qwi_higher_ed` cross-checked (0 mismatches) | QWI anchor uses the rates as published |
| Age mix of incumbents and of new hires | QWI `EmpS` and `HirAS` by age, excluding 14–18 | Population and hire-age draws |
| Family turnover multiplier | contract `ipeds_new_hires` (FT new hires ÷ FT headcount, relative to overall 10.6%), clipped to [0.5, 2] | Multiplies the age hazard and is normalised to a population mean of 1 |
| IPEDS hazard anchor | UIUC FT new-hire rate 10.6%/yr | The QWI age shape is scaled by 0.46 so the expected annual separation rate is 10.6% |
| Pay levels | contract `ipeds_salary_instructional` (by rank), `ipeds_salary_noninstructional` (by group) | Payroll run-rate (FT average × FTE). Not shown as a headline |

**There are two hazard levels because the sources disagree.** QWI statewide stable-job separations are about 22% a year. UIUC's IPEDS full-time new-hire rate is 10.6%. QWI covers every Illinois college and university and every stable job. IPEDS covers only UIUC full-time hires and needs a steady-state assumption. Neither source is "the" UIUC turnover rate. The planner lets you switch between them, and the switch moves results more than any Monte Carlo band does.

Stated tolerances (unit-tested): family × FT/PT and rank counts exact (0); age-group shares within 0.5 pp of QWI; simulated quarterly separation rate by age within 5% (relative) of the QWI target; IPEDS-anchored annual separation rate within 10% of 10.6%.

No public UIUC source exists for reporting levels, tenure, critical-role flags, promotion probabilities, time-to-fill, retirement eligibility or part-time FTE. These are labelled `ASSUMPTIONS` in `synthesize.py` and `simulate.py`, are shown on the page, and are the first things to replace with EDW estimates.

## Synthetic layer: grain and bitemporality

There are three tables with separate grains, each with `eff_start` (inclusive), `eff_end` (exclusive), `recorded_at` and `revision`:

- `position`: one authorized line (family, level, FT/PT, authorized FTE, critical flag, primary/secondary). Closed historical lines carry prior-level appointments.
- `person`: one synthetic person (age band, age at snapshot, service start). There are no names, birth dates, UINs or emails. IDs are sequential `SYN-*` strings.
- `appointment`: one person in one position, with rank for faculty. It includes prior-level segments, 2% effective-start corrections (revision 2), about 1.2% secondary part-time appointments, and 24 back-dated hires recorded after the knowledge cutoff.

The as-of query takes the latest revision recorded on or before the cutoff, then filters to records effective on the snapshot date. As known on 2023-11-15, the snapshot shows 12,905 persons, 13,060 appointments and 13,060 filled positions. As known on 2024-01-31, it shows 12,929 persons because the late-recorded hires appear. Headcount counts distinct persons, not appointments or positions. The simulation uses primary appointments, one per person, and reports secondary appointments separately.

## Engine

Every authorized primary position is a slot that an incumbent holds or that is vacant. Each quarter runs these steps for all runs at once in numpy:

1. **Separations.** Hazard = age-group rate (anchor) × family multiplier × calendar-quarter seasonality. A retirement incentive multiplies the hazard for eligible people in Q+2–Q+3. Eligibility is illustrative: age ≥ 60 with ≥ 10 years, or age ≥ 55 with ≥ 30 years. These are not SURS rules.
2. **Promotions from a Markov transition matrix.** The staff level-up probabilities per quarter are L1→L2 5%, L2→L3 3.5% and L3→L4 2%, once a person has been in level ≥ 8 quarters. A staff promotion is a vacancy chain: the person moves into a vacant higher-level line in the same family and leaves a vacancy behind. If no line is vacant, the promotion is blocked and counted. Faculty rank changes in place (Asst→Assoc 10%/qtr after 5 years; Assoc→Prof 6%/qtr after 6 years).
3. **Reskilling.** X%/yr of the full-time Office & Administrative Support level 1–2 pool moves into new level-1 lines in Computer/Engineering/Science and Business/Financial Ops over Q+2–Q+9. The source lines are abolished.
4. **External hires.** A vacant line fills with probability 0.65 per quarter. A freeze withholds X% of non-critical fills for 4 or 8 quarters. Critical lines are exempt. Vacant tenure-track lines refill at Assistant rank.
5. **Ageing.**

Outputs are P10/P50/P90 across runs of headcount (total and by family), FTE, critical-role vacancy share, bench strength (ready-now candidates per critical role, and the share of critical roles whose pool covers them), knowledge-loss exposure, cumulative flows and payroll run-rate. Knowledge-loss exposure is the share of the Fall-2023 stock of service-years held by people who have since left. Bench strength is pooled by family × level: full-time incumbents one level below, at least 8 quarters in level and not retirement-eligible. It is a pool size, not a ranking of people.

The **AI-augmentation lever** is applied after the simulation: capacity-equivalent FTE = FTE × (1 + uplift) on a chosen set of families, compared with Fall-2023 FTE. The uplift is something you type in, from 0–30% in 5% steps. It is not estimated from AI usage data. The lake contract forbids turning the Anthropic Economic Index into a job-loss score. The lever never changes simulated headcount.

**Scenario grid.** 2 anchors × 7 freeze settings × 3 incentives × 3 reskilling rates = 126 scenarios, each with 150 runs over 20 quarters. All scenarios use **common random numbers** (the same seed), so the gap between two scenarios reflects the levers and not sampling noise. The page reads the grid and does not re-simulate.

## Why this beats a generic platform AutoML or forecast function

- **Levers are causal inputs, not covariates.** A time-series or AutoML forecast learns how headcount moved in the past. It cannot answer "what if we freeze 25% of non-critical hiring for 8 quarters and offer a retirement window?" because those policies are absent from the training data. Here each lever acts directly on a named mechanism, such as fill probability, hazard for eligible people or line reallocation.
- **Uncertainty is explicit and split into kinds.** Fans show stochastic variation given the assumptions. The hazard-anchor switch shows structural uncertainty, which is larger. A point forecast from a platform function hides both.
- **Counts are grain-correct.** Headcount counts distinct persons at an as-of date with a knowledge cutoff. Positions, appointments and persons are separate. Promotions and transfers cannot create or destroy people: start + hires − separations = end, exactly, in every run (unit-tested). Generic forecasts on a flat monthly "headcount" column double-count multi-appointment people and ignore late-recorded corrections.
- **Succession metrics come from the same state.** Vacancy chains, blocked promotions, bench pools and knowledge loss all come from one simulated workforce, so they stay consistent with each other. Separate per-metric models do not guarantee that.
- **Aggregate-only by design.** The engine never emits individual risk scores. That matches the repository's guardrails and avoids building an employee-level departure model before governance approves one.
- **Portable.** It runs as numpy plus DuckDB on Parquet, so the same code runs on the custom stack or inside a Snowflake or Databricks Python runtime. It is a candidate benchmark task for the platform evaluation, not a vendor feature.

What platforms do better: managed scheduling, governance, lineage and scale. The engine can run inside either one.

## Replacing the synthetic layer with EDW tables (approved machines only)

Do this only on approved work machines. Real person-level data, intermediate tables and run outputs stay there, and only reviewed aggregates leave. Suppress small cells before publishing.

| Synthetic table | EDW source (from the original POC) | Notes |
|---|---|---|
| `person` | `T_PERS_HIST` (`EDW_PERS_ID`) | Age band only; drop names/demographics from the simulation inputs. Demographics are needed only for a separate, governed equity audit |
| `appointment` | `T_EMPEE_HIST`, `V_EMPEE_HIST_1`, `T_JOB_DETL_HIST` (`*_EFF_DT`/`*_EXP_DT`, FTE, job class) | Use EDW load/record timestamps as `recorded_at`, never effective dates. Keep every revision |
| `position` | `T_JOB_DETL_HIST.POSN_NBR` plus the position/budget authorization source | Vacant authorized lines need a position-control source; job history alone shows filled lines only |
| separations, retirements | `T_EMPEE_HIST_5` (termination and SURS retirement details) | Replaces the illustrative eligibility rule and QWI hazards with estimated hazards by age, service, family and appointment type |
| pay | `T_PAYR_ACCTG_DETL` | Replaces IPEDS family averages |

Steps:

1. Point `load_snapshot()` at the EDW-derived Parquet or views with the same columns. The as-of SQL is unchanged.
2. Re-estimate the hazards, the level transition matrix and time-to-fill from 2016–2023 history.
3. Replace the critical-role rule with the institution's approved critical-role list.
4. Keep `calibrate.py` as an external sanity check. IPEDS counts should still reconcile with the EDW snapshot at 2023-11-01, after scope differences such as graduate assistants and medical/hospital staff.

## Validation and backtest plan

1. **Reconciliation.** The EDW as-of headcount on IPEDS snapshot dates (2019–2023) must reconcile with published IPEDS totals by occupation category. Document the scope differences.
2. **Hold-out backtest.** Estimate the parameters on history up to 2022-11-01. Simulate 8 quarters with the levers set to what actually happened, for example a known freeze. Compare with observed 2023–2024 values: headcount by family, separations, retirements, promotions, critical vacancies.
   - Coverage: the share of observed values inside the P10–P90 band (target about 80%).
   - Error: median absolute percentage error of the P50.
   - Sharpness: band width.
   Repeat with rolling origins.
3. **Benchmarks to beat.** Naive persistence (headcount carried forward), seasonal-naive flows, and a platform AutoML/forecast on the same aggregates. Compare MAPE and coverage. Report the lever-response checks separately, because the benchmarks have no levers.
4. **Lever sanity checks.** Monotonicity (a larger freeze never raises headcount under common random numbers). Conservation in every run. Known-answer cases: freeze 100% for one quarter gives end = start − separations.
5. **Sensitivity analysis.** Vary each assumption: fill probability, transition probabilities, eligibility rule, family multipliers. Rank outputs by sensitivity, and report the outputs that are dominated by unvalidated assumptions as such.
6. **Governance.** Before operational use, get domain-owner sign-off on the critical-role definition and the bench rule. Run an equity review of aggregate bench metrics by protected group on approved machines. Produce no individual scores without a separate approval.

## Results on the synthetic data (honest reading)

All figures are P50 at year 5 unless stated, with 150 runs per scenario. They describe the synthetic model, not UIUC.

- **Baseline, IPEDS anchor.** Headcount stays near 12,905: P10–P90 at year 5 is 12,910–12,941. About 7,100 cumulative separations (about 11%/yr) are matched by hires. 518 separations meet the illustrative retirement rule. 3,051 promotions go through; 1,158 are blocked because no higher-level line was vacant. Knowledge-loss exposure reaches 32% of the Fall-2023 service-year stock.
- **Baseline, QWI anchor.** Headcount settles near 12,719 (12,697–12,742) because more lines sit vacant at any time. There are about 15,360 separations, knowledge-loss exposure reaches 56%, critical-role vacancy is about 1.5% against 0.3% under IPEDS, and bench coverage drops from 99% to 94%. **The choice of anchor matters more than any lever or any band.**
- **Hiring freeze** (25% of non-critical fills withheld, 8 quarters, IPEDS anchor). Year-1 headcount falls to 12,763 against 12,924, and to 12,518 at 50%. Headcount recovers within about 2 quarters of the freeze ending. Critical-role vacancy does not change, because critical lines are exempt by design. Under common random numbers, P50 headcount never rises with a bigger freeze inside the freeze window (0 violations across the grid). After the window, the differences are noise of 5 people or fewer.
- **Retirement incentive, strong.** About 59 more separations meet the retirement rule over 5 years (577 vs 518). Knowledge-loss exposure at year 1 is 9.6% vs 7.7%. Headcount hardly moves, because lines refill.
- **Reskilling at 5%/yr.** About 106 transfers over 2 years. Office & Administrative Support is about −105 at year 5, while Computer/Engineering/Science and Business/Financial Ops are each about +52. Total headcount is unchanged.
- **AI uplift.** This is pure arithmetic. A 15% uplift on office and knowledge families raises capacity-equivalent FTE by about 9% over Fall-2023 FTE. Nothing in the model supports or tests any particular uplift.
- **Known artifacts.** Two series drift early on because the model is settling, not because any lever acts:
  - Critical-role vacancy starts at 1.9%, the synthetic vacancy placement, and falls to about 0.3–0.4% within two quarters.
  - Bench strength rises from 1.0 to about 1.2–1.3 ready-now candidates per critical role over the first two years, because the synthetic time-in-level distribution is not at the model's equilibrium.

  The sharp quarterly saw-tooth is calibrated QWI seasonality: separations peak in calendar Q2.

## Limits

- The population is synthetic, so any outcome reflects the assumptions plus public aggregates, not UIUC reality.
- QWI is statewide and includes private institutions. IPEDS new hires cover full-time hires only.
- Levels, tenure, critical flags, promotion rates and time-to-fill are not calibrated.
- Not modelled: position growth or budget, department level, graduate assistants, student workers, bargaining-unit rules and labour-market shocks.
- The bands do not include parameter uncertainty. Bootstrapping the QWI and IPEDS inputs would widen them.
