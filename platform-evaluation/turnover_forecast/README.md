# Higher-ed turnover and retirement-wave forecast (real QWI data)

This module forecasts separations, age-55+ separations (the retirement-wave proxy), hires and turnover for **Illinois colleges and universities (NAICS 6113)**. It uses published Census LEHD Quarterly Workforce Indicators (QWI) for Illinois and 13 peer states. Every model is scored with a rolling-origin backtest against seasonal naive. Illinois is also compared with the peer-state distribution.

Open `../output/turnover_forecast/turnover_forecast.html`. It is a single offline file (vanilla JS/SVG, light and dark themes, works at phone width) and makes no network calls. Screenshots: `screenshot_desktop.png` (light), `screenshot_phone.png` (dark, 390 px) and `screenshot_forecast_hover.png` in the same folder.

## Caveats (read first)

- **QWI covers all ownerships (A00).** Public and private colleges are combined, so this is not the University of Illinois System and not "state universities". QCEW in the lake has the ownership split for employment and pay, but not for flows.
- **Published quarters are revised.** Each LEHD release revises earlier quarters. The backtest uses today's vintage (R2026Q3, R2026Q4 for MI and PA) at every origin, so it is pseudo-out-of-sample, not real-time. Real QWI also arrives about three quarters late, and the backtest ignores that lag. Both effects make the backtest somewhat optimistic for every model.
- **The latest quarters are partial.** 2025Q4 separations and 2025Q3–Q4 TurnOvrS are not yet published for Illinois. 2025Q2–Q3 values are provisional and are drawn as such on the page. MI QWI currently ends in 2021Q4. PA runs to 2026Q1.
- **Age 55+ separations are a proxy for retirement.** QWI does not record why a job ended. They include quits, layoffs and contract ends.
- **QWI has no unemployment rate.** The "macro" covariates are slack proxies built from QWI all-industry totals: employment growth, hire and separation rates.
- **"Best model" is chosen on the same backtest that scores it.** That selection is mildly optimistic. The ensemble's weights were fixed before scoring and it is the safer default.

## Run

Run from `platform-evaluation/` with Python 3.13 and `pip install -r turnover_forecast/requirements.txt`. The Illinois QWI silver table must already exist (`scripts/lake_build.py`).

```bash
python turnover_forecast/acquire.py      # 13 peer-state QWI files -> data/lake/raw/qwi_states/<st>/ (~681 MB, ~1 min); MD5 vs publisher + SHA-256
python turnover_forecast/panel.py        # -> turnover_forecast/data/panel.parquet (+ panel_manifest.json)
OMP_NUM_THREADS=1 python turnover_forecast/backtest.py   # 629 origin x target jobs, ~2 min on 4 cores -> backtest.parquet, metrics.json
python turnover_forecast/forecast.py     # final forecasts + peer view -> results.json
python turnover_forecast/build_page.py   # -> output/turnover_forecast/turnover_forecast.html
python -m unittest discover -s turnover_forecast/tests -v
NODE_PATH=$(npm root -g) node turnover_forecast/screenshot.js output/turnover_forecast
```

`turnover_forecast/data/` is regenerable. Two consecutive runs of `backtest.py` produced byte-identical `backtest.parquet` (SHA-256 `686cb636…0350`) and `metrics.json`.

| File | Role |
|---|---|
| `acquire.py` | Reads each state's LEHD directory listing (availability, size), downloads `qwi_<st>_sa_f_gs_n4_oslp_u.csv.gz` and the publisher md5sum, verifies MD5 and records SHA-256 in `data/acquisition_manifest.json`. Illinois reuses the lake raw file and is checked against the current md5sum |
| `panel.py` | State × NAICS {6113, 6111, 6221, all} × age group A00–A08 × quarter. Emp, EmpEnd, HirA, HirN, Sep, SepBeg, TurnOvrS and EarnS, each with its `s_*` status flag |
| `series.py` | Dense arrays, targets, forecast-time covariates, and `truncate()` |
| `models.py` | Seasonal naive, ETS, SARIMA, pooled ridge, LightGBM, plus metrics (MASE, sMAPE, coverage, Diebold–Mariano) |
| `backtest.py` | Rolling-origin backtest, empirical intervals, per-horizon evaluation |
| `forecast.py` | 8-quarter forecasts from the last published quarter, and the Illinois-vs-peers residuals |
| `build_page.py`, `screenshot.js` | Offline dashboard and the Playwright check (fails on JS errors and reports horizontal overflow) |
| `tests/test_turnover_forecast.py` | 19 unittest cases |

## Data

All 14 files come from `https://lehd.ces.census.gov/data/qwi/latest_release/<st>/` and are QWI V4.14.0. Every file's decompressed MD5 matches the publisher's `qwi_<st>.md5sum`. Sizes and SHA-256 hashes are in `data/acquisition_manifest.json` and on the page. The panel has 62,028 rows (panel SHA-256 `e479c95b…eabf`).

A value is used only when its QWI status flag is 1, 6, 9, 10 or 12. Flags −2, −1, 5 and 11 stay missing and are never set to zero. Within the 6113/6111/6221/total rows, the only non-OK flags are the unpublished trailing quarters and a few suppressed MD cells.

**Targets** (Illinois 6113, sex = all):

| Target | Definition |
|---|---|
| Separation rate | Sep ÷ mean(Emp, EmpEnd) |
| Separations | Count |
| Separations 55–64, 65+, 55+ | Counts for A07, A08 and their sum |
| Hire rate | HirA ÷ mean(Emp, EmpEnd) |
| Turnover | TurnOvrS, as published |

## Models and backtest

- **Rolling origin.** Origins run every quarter from 2003Q1. 2003–2009 is a warm-up used only to accumulate errors for the empirical intervals. Scoring covers origins from 2010Q1 to 2025Q2: 62 origins, 61 for turnover. At each origin T, every model receives `truncate(panel, T)`, so all 14 states are cut at T, and it forecasts T+1…T+8. All models are scored on the same (origin, horizon) pairs.
- **Baselines.**
  - Seasonal naive (same quarter last year).
  - ETS with additive damped trend and additive seasonality on logs.
  - SARIMA(1,0,1)(0,1,1)₄ with drift on logs. This is a fixed specification, not auto-selected.
- **Pooled ridge (partial pooling).** One ridge regression per horizon, fit across all 14 states. The target is log(y_{T+h} ÷ mean of the last 4 quarters), which makes states of different sizes comparable. Features:
  - Quarter-of-target and state intercepts. Ridge shrinks the state intercepts toward a common intercept, which is the MAP estimate of a random-intercept model.
  - Recent level and 4- and 8-quarter trend, and the same-quarter seasonal profile for the last two years.
  - **Age structure:** the 55+ and 65+ shares of 6113 employment at T, and the 4-quarter change in the 55+ share.
  - **Forecast-time covariates** from QWI totals, all dated at T or earlier: all-industry employment growth, all-industry 4-quarter hire and separation rates and the change in the hire rate, and 4-quarter separation rates for hospitals (6221) and K-12 (6111).
  - The regularisation strength comes from RidgeCV fit on training rows only.
- **LightGBM global model.** One model on the same features, with horizon, state and quarter as features. It uses a fixed seed and `deterministic=True`.
- **COVID handling.** A dummy marks *training targets* in 2020Q1–2021Q2 so the shock does not bend the coefficients. It is set to 0 for every forecast, because a forecaster cannot know a shock is coming; a test enforces this. An "origin within COVID" indicator is a legitimate forecast-time feature. Metrics are reported with and without COVID target quarters.
- **Ensemble.** Equal-weight geometric mean of ETS, SARIMA, pooled ridge and LightGBM, fixed before scoring.
- **Metrics.**
  - MASE: absolute error ÷ the in-sample mean lag-4 seasonal-naive error of the Illinois series up to T. Values above 1 are normal here because multi-step errors exceed in-sample one-season-ahead errors.
  - sMAPE: 200·|y−ŷ|/(|y|+|ŷ|).
  - Interval coverage: the share of actuals inside the 80% and 95% intervals.
  - **Empirical intervals** at origin T are the 10/90 and 2.5/97.5 percentiles of that model's own Illinois log errors whose target quarter is ≤ T, using at least 12 errors.
  - **Native intervals** (seasonal naive, ETS, SARIMA) come from the model itself.
  - Diebold–Mariano tests compare each model's absolute scaled errors with seasonal naive, using Newey–West variance with h−1 lags and the HLN correction. Overlapping origins make these p-values approximate.

## Results: does anything beat seasonal naive?

**Yes, but modestly.** For every target the best model's mean MASE is **11–16% below seasonal naive**, and 12–17% below when COVID target quarters are excluded. Gains are largest and most often significant at h = 1–2. At longer horizons they are seldom statistically distinguishable. **No model is best everywhere.** SARIMA *loses* to seasonal naive for the 55+ counts beyond h = 2.

Cells below are MASE relative to seasonal naive (< 1 = better). `*` marks DM p < 0.05. All scored origins, 2010Q1–2025Q2.

**Separation rate (all ages)**

| Model | h1 | h2 | h3 | h4 | h5 | h6 | h7 | h8 | Mean MASE | Rel. excl. COVID | sMAPE | Empirical cov80 / cov95 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Seasonal naive | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.17 | 1.00 | 9.7% | 72% / 90% |
| ETS | 1.01 | 0.98 | 1.02 | 1.00 | 1.00 | 1.00 | 1.03 | 1.04 | 1.18 | 1.08 | 9.6% | 65% / 87% |
| SARIMA | 0.91 | 0.86 | 0.86 | 0.86 | 0.86 | 0.88 | 0.90 | 0.92 | 1.03 | 0.90 | 8.6% | 69% / 90% |
| Pooled ridge | 0.93 | 1.01 | 0.90 | 0.90 | 0.86 | 0.84 | 0.88 | 0.82* | 1.04 | 0.91 | 8.6% | 70% / 88% |
| LightGBM | 0.82 | 0.84 | 0.89 | 0.91 | 0.93 | 0.92 | 0.94 | 0.93 | 1.05 | 0.93 | 8.7% | 68% / 90% |
| Ensemble | 0.83 | 0.85 | 0.86 | 0.85 | 0.86 | 0.86 | 0.90 | 0.86 | 1.00 | 0.87 | 8.2% | 66% / 90% |

**Separations, age 55+ (count)**

| Model | h1 | h2 | h3 | h4 | h5 | h6 | h7 | h8 | Mean MASE | Rel. excl. COVID | sMAPE | Empirical cov80 / cov95 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Seasonal naive | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.66 | 1.00 | 9.8% | 69% / 84% |
| ETS | 0.81* | 0.82* | 0.88 | 0.88 | 0.82 | 0.86 | 0.94 | 0.98 | 1.45 | 0.83 | 8.3% | 66% / 83% |
| SARIMA | 0.90 | 0.92 | 1.05 | 1.14 | 1.04 | 1.09 | 1.22 | 1.31 | 1.81 | 1.04 | 10.2% | 65% / 81% |
| Pooled ridge | 0.88 | 0.92 | 0.96 | 0.99 | 0.84 | 0.85 | 0.85 | 0.91 | 1.48 | 0.89 | 8.8% | 69% / 86% |
| LightGBM | 0.83* | 0.82* | 0.83* | 0.86 | 0.85 | 0.87 | 0.89 | 0.93 | 1.43 | 0.85 | 8.4% | 72% / 85% |
| Ensemble | 0.80* | 0.83* | 0.88 | 0.92 | 0.84 | 0.87 | 0.94 | 0.97 | 1.46 | 0.85 | 8.4% | 68% / 83% |

**Best model by target.** Ranges are relative MASE across horizons 1–8; "significant" counts horizons with DM p < 0.05.

| Target | Best model (mean MASE) | Gain vs seasonal naive | Range h1–h8 | Significant horizons |
|---|---|---|---|---|
| Separation rate | Ensemble | 14% | 0.83–0.90 | 0 of 8 |
| Separations, 55+ | LightGBM | 14% | 0.82–0.93 | 3 of 8 |
| Separations, 55–64 | LightGBM | 16% | 0.80–0.90 | 5 of 8 |
| Separations, 65+ | Pooled ridge | 14% | 0.78–0.96 | 0 of 8 (ensemble: 13%, significant at h1) |
| Separations, all ages (count) | Ensemble | 14% | 0.81–0.89 | 0 of 8 |
| Hire rate | Ensemble | 16% | 0.81–0.86 | 5 of 8 |
| Turnover (TurnOvrS) | Ensemble | 11% | 0.81–0.96 | 1 of 8 |

All per-horizon tables, including the version that excludes COVID targets, are in `data/metrics.json` and on the page.

**Interval coverage is the weak point.** Rolling empirical 80% intervals covered **63–77%** of outcomes, and 95% intervals covered **81–92%**. Errors before 2010 were smaller than errors after 2019, so intervals calibrated on earlier errors are too narrow. Native intervals from seasonal naive, ETS and SARIMA cover closer to nominal at short horizons: about 76–85% at h = 1 for the 80% interval. Treat the published bands as somewhat narrow.

## Forecasts (Illinois 6113, next 8 quarters)

The origin is 2025Q3, the last quarter with published separations; for turnover it is 2025Q2. The intervals below are quantiles of the model's full set of Illinois backtest errors, so they are about 80% and 95% within that backtest and probably narrower than true out-of-sample uncertainty.

**Separations, all ages: ensemble**

| Quarter | Forecast | 80% | 95% | Seasonal naive |
|---|---:|---:|---:|---:|
| 2025Q4 | 11,660 | 10,560–12,660 | 9,598–15,220 | 12,140 |
| 2026Q1 | 7,893 | 7,064–8,696 | 6,580–9,597 | 7,705 |
| 2026Q2 | 16,150 | 14,500–17,640 | 12,940–19,770 | 15,960 |
| 2026Q3 | 14,070 | 12,540–15,540 | 11,390–16,890 | 13,450 |
| 2026Q4 | 11,560 | 10,160–12,820 | 9,261–14,210 | 12,140 |
| 2027Q1 | 7,883 | 6,940–8,710 | 6,285–9,699 | 7,705 |
| 2027Q2 | 16,120 | 14,140–17,950 | 12,620–19,980 | 15,960 |
| 2027Q3 | 14,040 | 12,230–15,690 | 10,950–17,310 | 13,450 |

The next four quarters total 49,770 separations, against 49,257 in the last four published quarters (+1.0%).

**Separations, age 55+: LightGBM**

| Quarter | Forecast | 80% | 95% | Seasonal naive |
|---|---:|---:|---:|---:|
| 2025Q4 | 2,612 | 2,306–2,858 | 2,128–3,082 | 2,742 |
| 2026Q1 | 1,863 | 1,639–2,039 | 1,517–2,323 | 1,829 |
| 2026Q2 | 3,245 | 2,862–3,539 | 2,646–3,942 | 3,017 |
| 2026Q3 | 2,355 | 2,072–2,600 | 1,931–2,864 | 2,303 |
| 2026Q4 | 2,626 | 2,273–2,930 | 2,105–3,351 | 2,742 |
| 2027Q1 | 1,866 | 1,622–2,027 | 1,458–2,308 | 1,829 |
| 2027Q2 | 3,250 | 2,791–3,581 | 2,543–3,923 | 3,017 |
| 2027Q3 | 2,363 | 1,999–2,552 | 1,850–2,904 | 2,303 |

The next four quarters total 10,075, against 9,891 in the last four published quarters (+1.9%). The forecasts show **no retirement wave** in the next two years: age-55+ separations stay flat, with the usual Q2 (end of academic year) peak. The 55+ share of Illinois higher-ed employment is 25.9% (2025Q4, 4-quarter mean). The peer median is 27.0%, and Illinois ranks 9th of 13 (1 = oldest).

The separation-rate forecast (ensemble) moves around the same seasonal pattern: 9.5% in 2025Q4, 6.3% in 2026Q1, 13.1% in 2026Q2 and 11.5% in 2026Q3.

## Illinois against peers ("trend vs actual")

Levels are trailing 4-quarter means against peer p10/p25/median/p75/p90. The residual is Illinois' log year-over-year change minus the median peer log year-over-year change: the part of Illinois' movement that the common peer pattern does not explain. A robust z-score flags |z| > 2. There are no national series in this build, only the 13-state peer distribution.

| Measure | Illinois (latest 4-qtr mean) | Peer median | Rank of 13 (1 = highest) | Mean residual since 2010 | Mean residual since 2022 |
|---|---:|---:|---:|---:|---:|
| Separation rate | 9.99% (2025Q3) | 9.12% | 6 | +0.45 pts | +0.17 pts |
| Separation rate, 55+ | 7.82% | 7.47% | 6 | +0.42 pts | +0.80 pts |
| Hire rate | 9.75% | 9.31% | 6 | −0.04 pts | **−2.47 pts** |
| Turnover (TurnOvrS) | 6.28% (2025Q2) | 5.70% | **2** | +0.61 pts | **+2.37 pts** |

Reading:

- **Hiring.** Since 2022, Illinois' year-over-year hiring change has run about 2.5 log points per quarter below the peer pattern. 2024Q2, 2024Q4 and 2025Q2 are flagged; the 2025 hire rate fell to 7.8% in Q1 and 8.5% in Q2.
- **Turnover.** Stable-job turnover is the second highest of 13 states and has been rising faster than peers.
- **Older workers.** Separation rates for workers 55+ have edged above the peer pattern since 2022 (+0.8 pts per quarter on average); 2022Q3 and 2023Q3 are flagged.
- **COVID.** 2020Q1 is flagged for the all-ages separation rate: Illinois' early-pandemic spike was larger than its peers'.

These deviations hold relative to peer movement, not in absolute terms. Because QWI combines public and private institutions, they cannot be attributed to a particular sector.

## Tests (19, all passing)

- **No leakage.**
  - `truncate` blanks every quarter after T.
  - The design matrix and the univariate models give identical output when every value after T is replaced with noise or deleted, even *without* truncation.
  - A full multi-model forecast is unchanged under that future perturbation.
  - Prediction rows never carry the COVID dummy, while training rows inside the window do.
  - Empirical intervals at origin T do not change when actuals after T change, and need 12 resolved errors.
- **Reproducibility.**
  - Ridge and LightGBM are deterministic.
  - A stored backtest row is recomputed exactly.
  - The panel hash matches its manifest.
- **Metrics.**
  - sMAPE and MASE (including the scale) match hand values.
  - Seasonal naive is exact on a periodic series.
  - Coverage handles NaN.
  - The Diebold–Mariano test detects a real loss difference and does not flag a permutation.
- **Panel.**
  - Age groups sum to total employment.
  - The 55+ target equals A07 + A08.
  - Illinois values equal the lake silver table.

## Sources

U.S. Census Bureau, LEHD Quarterly Workforce Indicators, `latest_release` (R2026Q3, and R2026Q4 for MI and PA), retrieved 2026-11-06. This is U.S. federal public data.
