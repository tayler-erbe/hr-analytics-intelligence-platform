# Faculty pipeline model (gap G2, prototype)

This prototype builds gap **G2** from `research/TOOLS_BEYOND_SNOWFLAKE_DATABRICKS.md`: rank progression, the tenure clock, SURS retirement eligibility, separations and hiring for full-time instructional faculty. It is an annual **cohort-component Markov model** with Monte Carlo uncertainty, for UIUC, UIC and UIS. Generic workforce-planning tools model headcount and cost by job. They do not model tenure states, an up-or-out clock, promotion-only access to senior ranks, or pension-tier eligibility.

**Only public data and synthetic detail are used.** The Fall 2023 start state matches IPEDS exactly. Ages, SURS tiers and years in rank are synthetic. Transition rates come from published literature and from steady-state flow balance on one year of IPEDS hires. **The outputs are scenarios, not forecasts.**

Open `../output/faculty_pipeline/faculty_pipeline.html`. It is a single offline file (vanilla JS/SVG, light and dark themes, works at phone width) with no network calls. Screenshots: `../output/faculty_pipeline/screenshot_desktop.png` and `screenshot_phone_dark.png`.

## Run

Run from `platform-evaluation/` with Python 3.13 and `pip install -r faculty_pipeline/requirements.txt`. The public lake must already be built (`scripts/lake_acquire.py`, `lake_build.py`, `lake_contract.py`).

```bash
python faculty_pipeline/calibrate.py        # lake + IPEDS Completions C2023_A -> faculty_pipeline/calibration.json
python faculty_pipeline/simulate.py         # 225 scenarios x 300 runs x 15 years -> faculty_pipeline/data/scenario_grid.json (~4 min on 4 cores)
python faculty_pipeline/build_page.py       # -> output/faculty_pipeline/faculty_pipeline.html
python -m unittest discover -s faculty_pipeline/tests -v
NODE_PATH=$(npm root -g) node faculty_pipeline/screenshot.js output/faculty_pipeline   # optional Playwright check
```

The first run of `calibrate.py` downloads IPEDS Completions `C2023_A.zip` (9.3 MB) from nces.ed.gov into `faculty_pipeline/data/raw/`. Its SHA-256 is recorded in `calibration.json`. Use `--offline` to forbid the download. `data/` is regenerable and git-ignored. `workforce_sim/` is not modified or imported.

| File | Role |
|---|---|
| `calibrate.py` | Public inputs: IPEDS start states with partition asserts, hires, salaries, enrollment, completions by discipline group, Big Ten peer ratios, literature parameters and SURS rules with citations |
| `calibration.json` | The resulting aggregates, sources and caveats. No person-level data |
| `model.py` | Hazards, solved rates, synthetic start state, the stochastic engine, cell and state transition matrices, enrollment paths. All non-public inputs are in `ASSUMPTIONS` |
| `simulate.py` | Scenario grid, percentile summaries, enrollment post-processing, diagnostics |
| `build_page.py` | Embeds the grid in the offline page |
| `screenshot.js` | Playwright desktop (light) and phone (dark) screenshots. Fails on JS errors and checks horizontal overflow |
| `tests/test_faculty_pipeline.py` | 16 unittest cases (see Tests) |

## Model

**States.** There are five working states plus two absorbing states, RETIRED and SEPARATED.

| State | Meaning | IPEDS S2023_IS leaf rows (`siscat`) |
|---|---|---|
| PRE | pre-tenure, on tenure track (clock years 0–7) | 301–306 |
| ASC | associate professor, tenured (years in rank 0–15+) | 202–206 (tenured assistant/instructor rows fold here) |
| FUL | full professor, tenured | 201 |
| NTP | NTT professorial titles (clinical, teaching or research assistant/associate/full) | 411–413, 421–423, 431–433 |
| NTL | NTT lecturer, instructor or no academic rank | 414–416, 424–426, 434–436 |

Each Fall census cell is state × single-year age (25–84) × completed years in rank × SURS tier.

**One annual step**, applied to every cell in this order:

1. **Retirement.** The hazard depends on age × tier. It is multiplied by a per-run level and, if an incentive is on, by the incentive for SURS-eligible cells in years 1–2.
2. **Non-retirement separation.**
3. **Promotion**, PRE→ASC (tenure) or ASC→FUL.
4. **Ageing** by one year. Promoted faculty restart at years-in-rank 0.
5. **Hiring.** All new hires are Tier 2.

The draws are sequential binomials, which is exactly a multinomial on the cell's row [stay, promote, retire, separate]. The rows sum to 1, and this is unit-tested. The page shows the 7×7 state-level matrix implied at t0.

- **Tenure clock.** Exit hazard is 4–7% a year in clock years 1–5, highest in years 4–5. Early promotions run at 2% and 5%. The dossier is mandatory in year 6 (UIUC Provost Communication #9), and 15% of reviews are deferred one year. Denied candidates exit. The review pass rate is **solved per run** so that cohort tenure probability equals the drawn tenure-success rate.
- **Associate → full.** The hazard is 1%/yr in years 1–4, *h* in years 5–10 and 0.4*h* after that. *h* is **solved per run** so that the mean years in rank among those promoted equals the drawn literature value.
- **Retirement (SURS).** Tier 1 (first SURS service before 2011) is eligible from 55. Hazards rise from 3% at 55–59 to 13–15% at 65–69, 20% at 70–74 and 30% at 75+. Tier 2 is eligible from 62 with a low 4% hazard at 62–66, because of the 0.5%/month reduction below 67, then follows the same schedule from 67. Anyone still employed at 84 exits at the model boundary.
- **Hiring is budget-driven.** Hires per year = budget ÷ average salary at the chosen mix. At 100%, the budget buys exactly the Fall 2023 IPEDS hires at IPEDS 2023-24 average salaries: $21.5M for 201 hires at UIUC. The TT side splits into assistant and senior (tenured on arrival, half associate and half full) in the IPEDS 2023 proportion. The NTT side splits into NTP and NTL in proportion to the existing stock.
- **Enrollment** changes demand only. It sets the student–faculty ratio (FTE proxy ÷ faculty) and the hires needed to hold the 2023 ratio, which is exits plus the change in the constant-ratio target. Discipline groups are 2-digit CIP families.

**Levers (page grid).** Each institution has 75 scenarios, 225 in total, each with 300 runs over 15 years:

- **Hiring budget:** 70%, 85%, 100%, 115% or 130% of 2023.
- **NTT share of hires:** the 2023 share plus −20, −10, 0, +10 or +20 points.
- **Retirement incentive:** none, 1.5× or 2× the eligible hazard in years 1–2.

The four enrollment scenarios (flat, −1%/yr demographic decline, computing and engineering surge, +1.5%/yr growth) are applied to every run.

**Uncertainty.** Each run draws:

- tenure success U(0.50, 0.72);
- associate→full years U(6.5, 8.2);
- retirement level ×U(0.80, 1.25);
- tenured separation level ×U(0.7, 1.3);
- NTT separation level ×U(0.8, 1.2).

Flows are then binomial. The bands are P10–P90. All scenarios of an institution use **common random numbers**, so the difference between two scenarios is the effect of the levers. For the baseline, the page also shows a flow-noise-only band with parameters fixed. At UIUC in 2038 that band is **77 people wide against 302** with parameter uncertainty. **Not knowing the rates dominates the uncertainty.**

## Calibration sources

### Public data (lake contract unless noted)

| Input | Source | Handling |
|---|---|---|
| Start state by state | `ipeds_instructional_staff` (S2023_IS, Fall 2023), `sex='Total' AND race_ethnicity='Total'` | Scope is full-time instructional staff *with faculty status* (siscat 100). The leaf rows are 20r+30r+41r+42r+43r, asserted equal to the published total for UIUC, UIC, UIS and all 18 Big Ten peers. **`is_category_total = false` is not a partition in this table:** the 44x rows (multi-year) are nested in 41x (multi-year and indefinite) and equal them at UIUC, so summing every non-total row double counts. Staff without faculty status (siscat 500, e.g. 235 at Michigan State) are excluded and recorded. UIUC, UIC and UIS have none. |
| Hires by faculty status | `ipeds_new_hires` (S2023_NH) | 21020 tenured, 21030 on track, 21040 NTT. Asserted 21010 = sum and 21040 = 21041+21042+21043. 21044 is nested in 21041 |
| Cost per hire | `ipeds_salary_instructional` (SAL2023_IS) | Average by rank = Σoutlays ÷ Σcount across contract lengths |
| Enrollment | `ipeds_enrollment_12mo` (EFFY2024) | FTE proxy = full-time + part-time ÷ 3. UIUC proxy ratio 21.4 at the start. This is *not* IPEDS's published ratio, which uses fall FTE and includes part-time faculty |
| Discipline mix | IPEDS Completions C2023_A, revised (`nces.ed.gov/ipeds/datacenter/data/C2023_A.zip`, not in the lake) | First-major awards by 6-digit CIP, rolled up to 6 groups and weighted by enrollment-years per award (bachelor 4, master 1.5, research doctorate 5, professional doctorate 4, certificates 0.5) |
| Peer ratios | the same tables for the 18 Big Ten main campuses | Tenure density, NTT share, full share, new-hire rate, NTT share of hires, TT hires ÷ pre-tenure stock |

Fall 2023 start states (IPEDS):

| | PRE | ASC | FUL | NTP | NTL | Total | Hires (ten / TT / NTT) |
|---|---:|---:|---:|---:|---:|---:|---|
| UIUC | 527 | 477 | 799 | 393 | 302 | 2,498 | 23 / 95 / 83 |
| UIC | 445 | 398 | 547 | 650 | 364 | 2,404 | 9 / 40 / 105 |
| UIS | 47 | 75 | 39 | 8 | 25 | 194 | 1 / 5 / 3 |

Against the Big Ten, UIUC's tenure density is 51.1% (peer median 45.5%, IQR 37.9–50.4%), its NTT share is 27.8% (median 39.1%) and its NTT share of new hires is 41.3% (median 57.8%).

### Literature (from web search; cited in `calibration.json` and on the page)

- **Tenure success:** 0.62, range 0.50–0.72.
  - Kaminski & Geisler 2012 (*Science*): 64% of 2,966 S&E assistant professors at 14 universities were promoted at the same institution, and median time to departure was 10.9 years.
  - Virginia Tech hires 1998–2005: about 64%.
  - Michigan ADVANCE 2026: 72–73% for the AY2008–12 cohort.
  - University of Missouri, 1980s: 39% within 6 years.
- **Tenure clock:** UIUC Provost Communication #9, which makes the dossier mandatory in the sixth probationary year.
- **Associate → full:** 7.0 years, range 6.5–8.2. MLA *Standing Still* gives 6.6 (men) and 8.2 (women). AHA 2012 gives 7.6.
- **Age profile:** CUPA-HR (McChesney & Bichsel 2020): 37% of tenure-track faculty are 55+ and 13% are 65+. These two shares are the only targets for the synthetic start ages, and they are met within 0.1 pp for UIUC and UIC and 2.2 pp for UIS (55+), which is small and integer-limited.
- **Retirement behaviour:**
  - Ashenfelter & Card 2002 (NBER w8378): retirement rates at 70–71 fell to under 30% after uncapping.
  - TIAA Institute (Yakoboski 2015): about two-thirds of tenured faculty aged 50+ expect to work past normal retirement age.
  - NRC 1991, chapter 5 on retirement incentive programs.
- **SURS eligibility:**
  - Sources: surs.org/retirement-eligibility, the FAQ "When am I eligible to retire" and the Traditional Plan page.
  - Tier 1: 62 with 5 years, 55 with 8 years (reduced), or any age with 30 years.
  - Tier 2: 67 with 10 years, or 62 with 10 years reduced 0.5% per month under 67.
  - **Verification limit:** surs.org and archive.cupahr.org could not be fetched from the build sandbox because the hosts were not allowed. Their content was read from page text returned by web search. Re-check them before relying on the rules.
- **Enrollment demography:** WICHE *Knocking at the College Door* (Dec 2024). High-school graduates peak in 2025, then fall about 13% by 2041, with Illinois about −32% over 2023–2041. The −1%/yr scenario is illustrative, not a WICHE projection for UIUC.

### Derived by flow balance (steady-state assumption on one year of hires)

- **Tenured separation** = (TT hires × tenure success + tenured hires − expected tenured retirements) ÷ tenured stock, clipped to 1–5%. This gives UIUC **1.6%**. UIC solves to −1.3% and UIS to −0.4%, and both are clipped to 1%: their 2023 hires cannot even replace expected retirements.
- **NTT separation:** NTL is 1.5× NTP, with the level solved so that NTT exits equal NTT hires. This gives UIUC 8.9% (NTP) and 13.3% (NTL), UIC 7.8% and 11.7%, and UIS 6.0% and 9.0%.
- **Pre-tenure flow check:** TT hires × expected years on track (5.33) gives the steady-state stock to compare with the observed one.
  - **UIUC:** 506 against 527 observed. This is consistent.
  - **UIC:** 213 against 445. 2023 TT hiring was far below the rate that built the current pipeline, so UIC's pre-tenure stock halves in every scenario that keeps the 2023 mix.
  - **UIS:** 27 against 47. The same pattern holds.

  One year of IPEDS hires is a weak anchor. Pulling 2019–2024 IPEDS S_NH would be the first public-data improvement.

## Results on this model (honest reading)

P50 values at 2038 unless stated. These describe the model under the stated assumptions, not the University.

- **UIUC baseline** (2023 budget and mix, no incentive):
  - Headcount 2,498 → **2,770** (P10–P90 2,627–2,929). The model grows because retirements fall from about 70/yr to about 37/yr while hires stay at 201. That decline comes from the synthetic age profile: 13% aged 65+ from CUPA-HR is more than these hazards sustain, and new hires are Tier 2.
  - Tenure density 51.1% → 55.2%.
  - Cumulative retirements: 744 over 15 years, 307 in the first 5.
  - The SURS-eligible pool falls from 709 to 341 as Tier 1 faculty leave and Tier 2 eligibility starts at 62.
- **NTT mix lever (UIUC):**
  - At 61% NTT hiring: tenure density 47.4% and pre-tenure stock 349.
  - At 21% NTT hiring: tenure density 62.1% and pre-tenure stock 656.
  - Headcount moves the other way, because NTT hires cost less.
- **Budget lever (UIUC):** at 70% the faculty count reaches 2,202, and at 130% it reaches 3,358. P50 headcount is monotone in budget, and this is unit-tested.
- **Retirement incentive (2×):** retirements in years 1–2 go from 70/65 to 140/106. Over 15 years the total moves only 744 → 764, because the incentive pulls retirements forward. Headcount barely changes, because hiring is budget-driven.
- **Enrollment (UIUC baseline supply):**

  | Scenario | Ratio in 2038 (from 21.4) | Hires/yr needed to hold the 2023 ratio |
  |---|---:|---:|
  | Flat | 19.3 | 182 |
  | Decline | 16.8 | 160 |
  | Computing and engineering surge | 22.9 | 214 |
  | Broad growth | 23.8 | 221 |

  Discipline-group ratios are indices because faculty-by-discipline is not public.
- **UIC baseline:** 2,404 → 2,226. Pre-tenure stock 445 → 212 and NTT share 42% → 48%, both driven by the low 2023 TT hiring noted above.

## Tests (`python -m unittest discover -s faculty_pipeline/tests -v`, 16 pass)

- **Calibration to the IPEDS start state.**
  - Model t0 counts equal IPEDS for every state at all three institutions, and the tenured count equals siscat 200.
  - UIUC counts are pinned to the published numbers.
  - The leaf partition equals siscat 100 against the lake, and the sex-detail rows sum to it.
  - Start ages are within tolerance of the CUPA-HR shares.
- **Stochastic matrices.** Every cell row [stay, promote, retire, separate] lies in [0, 1] and sums to 1 (atol 1e-12) under random parameter draws and a 2× incentive. The 7×7 aggregate matrix rows sum to 1, the absorbing rows are identity, there are no demotions, and nobody survives the age-84 boundary.
- **Solved rates.** The review pass rate reproduces tenure success exactly, and the associate→full hazard reproduces the target mean within 0.02 years.
- **Conservation.** In every run and year, total end = start + hires − retirements − separations. By state: ΔPRE = PRE hires − exits − tenure, Δ(ASC+FUL) = senior hires + tenure − exits, and ΔNTT = hires − exits. Cells never go negative.
- **Reproducibility.** The same seed gives identical arrays, and a different seed gives different ones.
- **Levers.** Hires equal the IPEDS count at 100% budget. Headcount is monotone in budget under common random numbers. The incentive raises retirements in years 1–2. The NTT-share lever is honoured within 3 points.

## Limits

- **No internal data.** Transition rates are literature values or flow-balance values, not UIUC, UIC or UIS estimates. Ages, tiers and years in rank are synthetic. Discipline-level faculty counts do not exist publicly, so the group results are indices.
- **One IPEDS year.** Hires from a single year anchor separation levels and the budget, and the UIC and UIS checks show how fragile that is.
- **IPEDS scope.** The model covers full-time instructional staff with faculty status only. It excludes part-time faculty, research-only appointments and clinical staff outside instruction.
- **Simplifications:**
  - SURS eligibility uses age and tier only; the 30-years-any-age rule and reciprocal service are not modelled.
  - Tenured mobility is uniform in age.
  - NTT promotions within title series, NTT→TT conversions, phased retirement, return-to-work limits, sabbatical cycles and teaching-load coupling are not modelled. Sabbatical and teaching-load effects are the remaining parts of the G2 scope.
- **Costs** are incumbent averages in constant 2023 dollars, not offers or start-up packages.
- **Enrollment scenarios** are illustrative growth paths, not projections.
- **Calibration and validation.** The model has not been benchmarked against CUPA-HR survey rates, which require a subscription. It is not validated against observed history (see the EDW plan below).

## Estimating real transition rates from EDW appointment histories (approved machines only)

Do this only on approved work machines. Person-level data, intermediate tables and fitted models stay there, and only reviewed aggregates leave, with small cells suppressed. The source tables are those named in the original POC and in `workforce_sim/README.md`:

- `T_EMPEE_HIST` and `V_EMPEE_HIST_1` (appointments with effective and expiration dates);
- `T_JOB_DETL_HIST` (job class and title, FTE);
- `T_PERS_HIST` (age band only);
- `T_EMPEE_HIST_5` (terminations and SURS retirement details).

Add the academic appointment and tenure-status source that records rank, tenure-track status, tenure clock start and extensions.

1. **Build spells.** Construct one row per person × rank-state spell, giving state, start, end and exit reason (promotion, retirement, separation, still active). Use as-of logic with EDW record timestamps, not effective dates alone. Keep every revision so that back-dated changes do not leak.
2. **Annual person-period file.** Use Fall census dates from 2010 to 2024, with covariates for state, years in rank (the tenure clock year for PRE), single-year age, SURS tier (from first SURS-covered service date) and college or CIP group. Right-censor active spells.
3. **Estimate competing-risk discrete-time hazards** per state, with multinomial logit or cause-specific hazards for promotion, retirement and separation. Use smooth terms in age and clock year and pool sparse cells hierarchically by college. Estimate tenure success as cohort cumulative incidence, which accounts for censoring. Do not use a raw "tenured ÷ hired" ratio. Model clock extensions explicitly.
4. **Replace the inputs** `PRE_EXIT`, `PRE_EARLY`, `EXT`, the solved review rate, `asc_schedule`, `retirement_base`, `s_ten` and the NTT rates with fitted hazards. Replace the synthetic start state with the actual Fall 2024 cell counts and the parameter draws with the posterior or bootstrap distribution of the fitted hazards. The engine, tests and page stay unchanged.
5. **Validate.** Reconcile the EDW Fall census with IPEDS S_IS for 2019–2024. Run a hold-out backtest: fit to 2010–2019, simulate 2019–2024 with the actual hires, and report coverage of the P10–P90 bands (target about 80%) and the median absolute percentage error by state. Benchmark against CUPA-HR aggregate rates where licensed.
6. **Governance.** Produce aggregate outputs only. Run an equity review of the fitted hazards (for example tenure success by sex and race/ethnicity) as a separate, governed analysis. Produce no individual retirement or departure scores.
