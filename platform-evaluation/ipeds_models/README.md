# IPEDS institution-level predictive models (Fall 2015–2023)

These models are trained on the national IPEDS HR panel: every degree-granting four-year institution that reports HR data, which comes to **25,211 institution-years and 3,462 institutions**. They are checked with forward-in-time validation. Then they score the University of Illinois campuses (UIUC 145637, UIC 145600, UIS 148654) leave-institution-out: "what national patterns predict vs what actually happened". The module also proposes a peer group built from nearest neighbours.

**Page:** `output/ipeds_models/ipeds_models.html` (one offline file: vanilla JS and SVG, light/dark, works at phone width).

> **Caveats first.** These are self-reported, public **institution-level aggregates**, not person-level or payroll records. Year-to-year changes mix real change with reporting changes: the 2018 SOC recoding, hospital/branch payroll scope, management recoding, and the 4-month new-hire window in 2015. The flags below catch only some of these. The models show **associations, not causes**. A residual means a campus moved differently from institutions that looked like it. It does not say why. "Turnover" is proxied by new-hire rates, which mix replacement with growth.

## Run it

From `platform-evaluation/`, after `peer_benchmarks/acquire.py` has filled `data/lake/raw/ipeds_history/` (reused read-only):

```bash
pip install -r ipeds_models/requirements.txt
python ipeds_models/acquire_finance.py   # 36 Finance files (F1415..F2223 F1A/F2 + dictionaries), SHA-256 in manifests/
python ipeds_models/build_panel.py       # ~40 s  -> artifacts/panel.parquet, comparability_flags.parquet
python ipeds_models/peers.py             # ~10 s  -> artifacts/peers.json
python ipeds_models/models.py            # ~23 min (single-threaded LightGBM) -> results.json, *_predictions.parquet
python ipeds_models/render_html.py       # -> output/ipeds_models/ipeds_models.html
python -m unittest discover -s ipeds_models/tests -v     # 16 tests, ~30 s
NODE_PATH=$(npm root -g) node ipeds_models/screenshot.js <dir>   # optional Playwright check
```

`models.py --quick` runs a smoke test with fewer folds and trees. Note: multi-threaded LightGBM (OpenMP) hung in the build sandbox, so the code sets `n_jobs=1`. Raw finance files and parquet outputs are Git-ignored and can be regenerated. Code, manifests, `results.json` and `peers.json` are small.

## Panel (`build_panel.py`)

- **Universe.** For each year, an institution is in the universe when its HD record is `ICLEVEL=1`, `DEGGRANT=1` and `SECTOR` is 1–3, and its published staff grand total is > 0. Fall 2023: 811 public, 1,595 private nonprofit and 281 for-profit institutions.
- **Parsing.** The readers are imported from `peer_benchmarks/build.py` and that module is not modified. They prefer `_rv` revised members, keep codes as strings and keep NULLs as NULL. The partitions follow `lake/CONTRACT.md` v1.1:
  - 14 occupation groups × FT/PT sum to the grand total;
  - tenure statuses (S_IS arank 0, facstat 20/30/40/50) sum to FT instructional staff;
  - the 14 new-hire groups sum to all FT new hires (an absent group row counts as 0 when the institution filed new hires).

  Every non-excluded row is checked in the tests. For the 18 Big Ten / U of I institutions in both modules, totals equal `peer_benchmarks` exactly and the shares differ only by its 2-decimal rounding.
- **Variables.**
  - Staff by occupation group (total and FT).
  - Tenure counts and shares.
  - New-hire rates per 100 FT staff, all occupations and by group (group rate only when the group has ≥ 20 FT staff).
  - Faculty 9-month pay by rank: all ranks, professor, associate and assistant, with ≥ 10 in the rank. 2015 uses 9 × the monthly average, as in peer_benchmarks.
  - Non-instructional average pay.
  - 12-month FTE (EFIA Y+1) and fall FTE.
  - Staff per 100 FTE (only with ≥ 200 FTE).
  - Sector; Carnegie basic as published in that year's HD (2018 classification from HD2018 onward, else 2015, so there is no look-ahead); size; hospital, medical school, land-grant and HBCU flags.
  - **Research-expense proxy**: F1C021 (GASB) or F2E021 (FASB) for the fiscal year ending in June of the fall year, used only when `PRCH_F` says the record holds the institution's own expenses.

  All dollar values are in 2023-24 dollars (CPI-U July–June average, same method as peer_benchmarks).
- **Comparability flags** (`comparability_flags.parquet`, 20,438 rows). The rules are the peer_benchmarks rules applied nationally. Its own `exclude` flags (Penn State 2019–2021) are unioned in. A domain's values are **dropped**, not imputed, in an institution-year flagged `exclude` for that domain:
  - `PRCH_HR` parent/child;
  - `STAT_HR` not a respondent, or `IMP_HR` carry-forward/nearest-neighbour;
  - imputed cells;
  - partition mismatch (none found);
  - 2015 new hires (4-month window);
  - a year-over-year change of **≥ 35%** in total staff, 12-month FTE, FT instructional staff or all-ranks real pay (compared with the previous year present).

  Shifts of 15–35% are flagged `caution` and kept. Rank pay outside $25k–$450k is set to NULL. Exclusion shares: staff 2.1%, tenure 1.3%, new hires 13.0% (mostly 2015), faculty pay 1.3%, enrollment 2.9%. UIUC, UIC and UIS have no exclude flags.

## Tasks, validation and models (`features.py`, `models.py`)

| Task | Target at t+h | Rows (h=1 test) |
|---|---|---|
| (a) tenure | tenured share(t+h) − share(t), pp of FT instructional staff (needs ≥ 20 FT instructional) | 7,285 |
| (b) newhire | FT new-hire rate per 100 FT staff, stacked over 14 occupation groups | 55,404 |
| (c) staffratio | staff per 100 FTE(t+h) − (t); origins above 300 per 100 FTE (stand-alone health-science centres) left out | 10,111 |
| (d) pay | real 9-month pay growth %, stacked over all ranks / professor / associate / assistant | 32,686 |

- **Strict temporal validation.** For each cutoff T = 2018 … 2023−h, training uses origins t with t + h ≤ T, so every training target is observed by T. Testing uses origin T, whose targets are in T + h. That gives 5 folds for h=1 and 4 folds for h=2.
- **Features use only years ≤ origin:** levels, one-year changes and their lags, structure shares, research per FTE, pay, the SOC-2018 and pandemic indicators, and **peer-group context**. Context is the leave-one-out same-year mean over sector × Carnegie group, falling back to sector when n < 3.
- **Tests (no leakage).** One test scrambles every value after 2019 and asserts that every feature at origins ≤ 2019 and every target ≤ 2019 is unchanged.
- **Baselines.**
  - *Persistence*: level carried forward (zero change; for new hires, the current rate).
  - *Sector-year mean*: mean outcome by sector (× group/rank) in the latest observed target year.
  - *Repeat-last-change* is also reported. It is always worst.
- **Models.**
  - *Ridge*: RidgeCV with median imputation plus missing indicators, standardised.
  - *LightGBM*: L1 loss, 500 trees, deterministic.
  - In both, training targets are winsorised at the training 1st/99th percentiles. Test targets are not touched.
- **Uncertainty.**
  - MAE CIs come from a 1,000-draw **institution-cluster bootstrap**.
  - Prediction intervals come from **temporal split conformal**: fit on targets < T, take the signed residual quantiles in target year T, then refit on everything.
- **Calibration.** Decile plots, plus the OLS slope of actual on predicted with HC1 CIs.
- **Importance.** Permutation importance (MAE increase, one-hot blocks permuted together), weighted across folds.

### Results (pooled test folds; MAE in task units; Δ = best model − baseline, 95% cluster-bootstrap CI)

| Task | h | Persistence | Sector-yr mean | Ridge | LightGBM | Δ vs persistence | Δ vs sector mean | 80% / 90% coverage | Calib. slope |
|---|---|---|---|---|---|---|---|---|---|
| Tenured share change (pp) | 1 | 2.93 | 2.94 | 2.90 | **2.85** | −2.5% [−0.10, −0.05] | −3.1% [−0.11, −0.07] | 79% / 89% | 1.03 |
| | 2 | 4.29 | 4.42 | 4.29 | **4.24** | −1.1% [−0.10, 0.00] | −4.1% | 75% / 87% | 0.75 |
| New-hire rate by group | 1 | 6.41 | 6.48 | **5.52** | 5.55 | **−13.9%** [−0.95, −0.83] | −14.8% | 75% / 87% | 1.02 |
| | 2 | 7.13 | 6.87 | 6.86 | **6.72** | −5.7% [−0.48, −0.34] | −2.2% [−0.22, −0.08] | 61% / 76% | 0.70 |
| Staff per 100 FTE change | 1 | 1.95 | 2.00 | **1.95** | 1.95 | −0.1% [−0.01, +0.01] (n.s.) | −2.6% | 78% / 89% | 0.93 |
| | 2 | 2.76 | 2.78 | 2.80 | **2.76** | +0.2% [−0.01, +0.02] (n.s.) | −0.5% (n.s.) | 75% / 87% | 0.88 |
| Real pay growth % | 1 | 4.29 | 4.05 | 4.02 | **3.95** | −7.8% [−0.36, −0.30] | −2.3% [−0.12, −0.07] | 70% / 86% | 0.79 |
| | 2 | 6.76 | 6.35 | 6.22 | **5.96** | −11.8% [−0.85, −0.74] | −6.1% [−0.44, −0.34] | 55% / 79% | 0.65 |

What this means:

- **New-hire rates are the one task where the models clearly help.** One year ahead, MAE falls by about 14% against both baselines. The gain is spread across groups. The exception is **Research** staff, where the models do worse than persistence (7.7 vs 6.2): research hiring follows grants and is lumpy.
- **Real pay growth** gains 8–12% over persistence. Most of that gain comes from learning the national inflation-driven decline in 2021–2022, not from institution detail.
- **Tenured-share change** is barely predictable. The 2.5% gain is statistically real but small. The main signal is mean reversion and the "pipeline" effect: a larger on-track share means future tenure growth.
- **Staff-per-student change cannot be predicted** better than "no change" at either horizon.
- **Intervals under-cover at h=2** (55–61% for a nominal 80%) and for pay. When the latest calibration year falls in a regime shift (the 2021–22 inflation surprise), the signed-residual quantiles shift with it. In some pay years the point forecast even falls outside its own interval. Treat the intervals as indicative.
- **Top permutation features:**
  - Tenure: on-track share, tenured share, FT instructional size.
  - New hires: the group's current and lagged rate, the group identity, peer-context group rate (h=2).
  - Pay: the rank's pay level and last change, and non-instructional pay level.

## U of I: expected vs actual (leave-institution-out)

For every cutoff year, the model chosen in validation is retrained on **non-U-of-I institutions only**. All three campuses are held out, not just the one being scored, and they are also removed from every other institution's peer-context features. Only outcomes observed by that cutoff are used. The model then scores each campus. Tests verify two things: scrambling all UIC/UIS data leaves UIUC's scores identical, and with the exclusion on, no other institution's features depend on U of I values.

Mean residual (actual − expected) over scored years, and the share outside the 80% interval:

| | UIUC | UIC | UIS |
|---|---|---|---|
| Tenured-share change, h=1 (6 yrs, pp) | +0.07 (0/6) | +0.22 (0/6) | +0.86 (0/6) |
| New-hire rate, all groups, h=1 (per 100) | −1.39 (3%) | −2.25 (8%) | −0.44 (13%) |
| Staff per 100 FTE change, h=1 | −0.27 (0/6) | −0.35 (0/6) | −0.49 (1/6) |
| Real pay growth, ranks, h=1 (%) | −0.94 (12%) | +0.80 (33%) | −0.57 (33%) |
| Real pay growth, h=2 (%) | **−4.67** (50%) | −0.55 (56%) | −2.42 (50%) |

- **Tenure and staffing** moved about as national patterns predicted at all three campuses. UIUC's 2023 tenured-share drop (−2.25 pp vs −0.88 expected) is its largest single miss, but it is still inside the interval.
- **New hires** ran somewhat below expectation at UIUC and UIC, on average across groups. This is consistent with peer_benchmarks finding UIUC below the Big Ten median in every year.
- **Faculty real pay at UIUC fell more than national patterns predicted over two-year windows** (−4.7 pp on average). This is the clearest gap. The one-year misses are concentrated in the 2020 and 2021 target years (−2.3% and −4.7% actual vs +0.7% and +0.8% expected). Raises then lagged a CPI spike the models had not yet seen.
- **2024/2025 forecasts** (origin Fall 2023; Fall 2024 HR had not been published, so none of these can be checked yet):
  - tenured share: about −0.2 pp (UIUC), −0.1 (UIC), −0.5 (UIS) for 2024, with 80% intervals of roughly ±4 pp;
  - all-ranks real pay growth: −1.3% (UIUC), −1.6% (UIC), −1.4% (UIS) for 2024. The **2025 two-year forecasts of −3% to −6% carry the 2021–23 inflation regime**, which has since eased, so they are probably too pessimistic.

  Full tables, including new-hire rates by group, are on the page and in `artifacts/uofi_scores.parquet`.

## Peer similarity (`peers.py`)

Each institution in the Fall 2023 universe (2,687) gets a profile from its 2021–2023 averages:

- log FTE and log staff;
- staff per 100 FTE;
- graduate share of FTE;
- log research $ per FTE and research share of expenses;
- research, instructional and healthcare staff shares;
- tenured share;
- log faculty pay;
- graduate assistants per 100 FTE;
- medical-school, hospital, public, R1 and land-grant flags.

Features are z-scored, missing values are set to the median, and distance is Euclidean with equal weights. k = 15.

- **UIUC.** Its nearest neighbours are land-grant R1 publics without hospitals: NC State, Virginia Tech, Purdue, Georgia, Arizona, Michigan State, Minnesota, LSU, Tennessee, Washington State, Hawaii, Texas A&M, Auburn, Kansas State and Iowa State. Only **3 of 15** are Big Ten (Purdue rank 3, Michigan State 6, Minnesota 7). The median Big Ten rank is **78**. Ohio State (473), Washington (266) and Penn State (179) are far away, mostly because of hospital scope and staff per student. Without the medical/hospital features, 4 of 15 neighbours are Big Ten and the median rank is 40.
- **UIC.** Its neighbours are urban research universities with academic medical centres: Toledo, Mississippi, Ohio State, Louisville, Iowa, Utah, Colorado Denver/Anschutz and others. 2 of 15 are Big Ten, and the median Big Ten rank is 82.
- **UIS.** It has no Big Ten neighbours: the median Big Ten rank is about 2,615 of 2,686. Its neighbours are regional comprehensive universities (Western, Northern and Eastern Illinois, Northern Colorado, Indiana State and others).

Conclusion: the Big Ten list is a reasonable comparison group for UIUC on reputation and research scale. Structurally, though, a land-grant R1 set without hospitals fits UIUC better. UIC needs a medical-centre peer set. The Big Ten is the wrong comparison for UIS. These groups are proposals, not approved peer groups.

## Tests (`tests/test_ipeds_models.py`, 16 tests)

| Area | What is checked |
|---|---|
| Panel | Unique unitid × year grain, the three partitions, matching the peer_benchmarks values, 2015 new hires excluded, peer_benchmarks excludes carried over |
| **No temporal leakage** | Scrambling later years leaves earlier features and targets unchanged; stored folds have every training target ≤ the cutoff and test target = cutoff + h; leave-institution-out cutoffs hold |
| **Leave-institution-out integrity** | Peer context is independent of U of I data when they are excluded (and is shown to depend on it when they are not); UIUC scores are invariant to scrambling UIC/UIS; forecasts exist for 2024 and 2025 |
| **Reproducibility** | Deterministic Ridge and LightGBM; a stored validation fold is refit to 1e-8; the bootstrap is deterministic; the panel hash matches the model manifest |

## Files

`acquire_finance.py`, `build_panel.py`, `features.py`, `models.py`, `peers.py`, `render_html.py`, `screenshot.js`, `requirements.txt`, `tests/`.

`manifests/` holds:

- `acquisition_manifest.json`: URL, status, bytes, SHA-256 and time for each download;
- `panel_manifest.json`: thresholds, summary and the source members used;
- `model_manifest.json`: seed, package versions, panel hash and runtime.

`artifacts/` holds `panel.parquet`, `comparability_flags.parquet`, `validation_predictions.parquet`, `uofi_scores.parquet`, `results.json` and `peers.json`.
