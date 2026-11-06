# Trend-to-reality nowcast (real public data)

This module asks whether public job-posting trends tell us anything about what then happens to **Illinois higher-education employment, hires and separations**, and where Illinois departs from what national trends imply. Every input is real public data. Nothing is synthetic.

**Page:** `output/trend_nowcast/trend_nowcast.html` is a single offline file built with vanilla JS and SVG. It supports light and dark mode and works at phone width. Screenshots are `trend_nowcast.png` (desktop, light) and `trend_nowcast_phone_dark.png` (390 px, dark).

## Run it

From `platform-evaluation/` (the lake must already be built, see `lake/README.md`):

```bash
pip install -r trend_nowcast/requirements.txt
python trend_nowcast/acquire.py        # BLS CPI-U + CES pages, Indeed refresh -> trend_nowcast/data/raw/ (hashes in manifests/)
python trend_nowcast/build.py          # -> trend_nowcast/artifacts/ (panel parquet/csv + results.json), ~10 s
python trend_nowcast/render_html.py    # -> output/trend_nowcast/trend_nowcast.html
python -m unittest discover -s trend_nowcast/tests -v
node trend_nowcast/screenshot.js       # Playwright screenshots; fails on page errors or horizontal overflow
```

The module only reads from `data/lake/` and writes only to `trend_nowcast/` and `output/trend_nowcast/`.

## Inputs

| Input | Where | Use |
|---|---|---|
| Indeed Hiring Lab posting indices (daily, SA, 1 Feb 2020 = 100): US total and new, 47 US sectors, Illinois, Chicago metro | lake silver `indeed_*`. `acquire.py` re-downloads the same files from `raw.githubusercontent.com/hiring-lab/job_postings_tracker`, and `build.py` uses the refresh only if it is newer. On 2026-11-06 both ended 2026-10-30, so the lake copy was used | Signals |
| QCEW NAICS 611310, Illinois and U.S., private (5) and state (2) ownership, 2019Q1–2025Q4 | contract `qcew_industry` | Outcomes: employment (average of 3 months), average weekly wage |
| QWI Illinois NAICS 6113, all ownerships, sex 0, age A00 | contract `qwi_higher_ed` | Outcomes: employment, hires (HirA), separations |
| AEI observed exposure (labor_market_impacts) and conversation share by task (release 2025-03-27) | contract `aei_occupation_exposure`, `aei_task_usage`, silver `aei_onet_task_statements` | Structural overlay |
| CPI-U CUUR0000SA0 | data.bls.gov page | Real wages |
| CES private colleges: Illinois SMU17000006561130001, U.S. CEU6561130001 (NSA); CES6561130001 (SA) downloaded but not used | data.bls.gov pages | Hard-data benchmark and a timely divergence check (through 2026Q3) |

FRED was not reachable: the proxy refused the tunnel with HTTP 403. This is recorded in the manifest. Every download has URL, HTTP status, bytes, SHA-256 and timestamp in `manifests/acquisition_manifest.json`.

## Methods

1. **Aligned panel** (`artifacts/aligned_quarterly_panel.parquet`, long format, 2019Q1–2026Q3, 71 series). Daily indices become quarterly means. 2020Q1 covers only 1 Feb–31 Mar because the index starts at its base date. The incomplete current quarter (2026Q4) is dropped. QCEW suppressed cells stay missing (Illinois state-university 2025; Illinois local government in every quarter). QWI's two latest quarters (2025Q3, 2025Q4) are flagged provisional.
2. **Lead-lag.** Outcomes are converted to Δlog with quarter-of-year effects removed. Postings, which Indeed already seasonally adjusts, are converted to Δlog. Prewhitened cross-correlations: an AR(1) is fitted to the posting series and applied to both series, for lags −2…+4. Granger F-tests regress the outcome on a constant, three quarter dummies, p own lags and p posting lags, with p = 1 and 2. They run on the full sample (dependent quarters 2020Q3 onward) and a post-COVID sample (2022Q1 onward). Benjamini–Hochberg q-values are computed within each sample, covering 7 outcomes × 13 signals. ADF p-values are stored for the transformed series; at this n they have little power.
3. **Nowcast and forecast.** Each model is a direct h-step regression of YoY log growth, for h = 1 and 2. Baselines are the seasonal naive (same quarter last year) and a model on the outcome's own lag. Posting variants add US, Illinois, or Education & Instruction postings YoY, or a ridge model over Illinois plus 10 sectors (α chosen by leave-one-out). CES Illinois is a hard-data benchmark. Postings for the target quarter count as known at the origin, because Indeed publishes daily while QCEW and QWI arrive 5–9 months late. The backtest uses rolling origins on an expanding window, with training from 2021Q1, at least 8 rows, and scoring from 2022Q1 onward. All models are scored on the same quarters, and provisional QWI quarters are excluded. Metrics: RMSE and MAE in log points, skill versus naive and versus own lag, and the Diebold–Mariano test with the Harvey correction. A robustness run trains from 2022Q1 only. Live forecasts start from the latest actual quarter, with 80% intervals of ±1.28 × backtest RMSE.
4. **Divergence monitor.** Illinois YoY growth is regressed on a national comparison: QCEW US by ownership, CES US, QCEW US all ownerships, or US postings for hires and separations. Each quarter's z-score uses a fit that leaves that quarter out, and 2020Q2–2021Q2 are excluded from every fit. For the latest quarter this means only earlier data is used, as a real-time monitor would. |z| ≥ 2 is flagged.
5. **Occupation context.** An analyst mapping, unreviewed, links 25 Indeed sectors to SOC 2018 occupations using Indeed's example titles. For each sector the page shows the national posting index, its YoY change and its change from the 2022 peak, beside AEI observed exposure (unweighted mean and range over mapped occupations) and AEI conversation share. To get the share, AEI task text is matched to O*NET 31.0 task statements and then to SOC 2018 through the lake crosswalk. This covers 78.5% of conversations. A task shared by several occupations has its share split evenly between them. Spearman rank correlations come with permutation p-values. The panel is descriptive only, and no score is combined.

## Results (build of 2026-11-06)

- **Lead-lag: no stable lead.** 12 of 182 full-sample Granger tests pass q < 0.10. All 12 use 2 lags, and they involve QCEW Illinois private employment (7 signals), Illinois state-university employment (4) and QWI employment (1). For state-university employment the summed posting coefficients are *negative*, which is hard to read as a demand lead. **0 of 169** post-COVID tests pass (the smallest q is 0.18). Most prewhitened cross-correlations lie inside the ±1.96/√n band. The full-sample signal is the 2020–21 shock.
- **Nowcasts: postings add little or no reliable skill.**
  - *QCEW Illinois private employment.* Own lag plus Illinois postings had the lowest RMSE: 0.70 log points against 1.14 for naive and 0.91 for own lag at h=1 (12 quarters); 0.71 against 1.00 and 1.34 at h=2. It beats the naive model significantly at h=1 (DM p = 0.005), but not the own-lag model (p = 0.50). CES Illinois does equally well (0.71). With training from 2022 the gain over own lag almost vanishes at h=1 (0.72 vs 0.73) and reverses at h=2.
  - *QWI hires.* The sector ridge model has a lower h=1 RMSE (12.7 vs naive 14.3), but the gain is not significant (DM p = 0.59 vs naive). It disappears when training starts in 2022, and at h=2 nothing beats the naive model.
  - *QWI separations.* The seasonal naive is best. Posting models are much worse: RMSE 13.7–24 vs 7.0. They extrapolate from the 2021 rebound.
  - *QWI employment.* Own lag is best (0.54 vs naive 2.57). Adding postings makes it worse in the main backtest (0.80–0.96) and only ties it when training starts in 2022 (0.61–0.66 vs 0.65).
- **Divergence now.** Illinois higher-ed **hires in 2025Q2 were −33% YoY** (10,498 vs 14,594), z = −3.1 against the national posting trend. That quarter is not flagged provisional, but it is the third most recent QWI quarter and may still be revised. **State-university average weekly wage in 2024Q4** rose 8.1% YoY against the 4.3% that U.S. state universities imply (z = +2.9). Illinois private and state employment, private wages, QWI employment, CES Illinois (2026Q3) and Illinois postings are all within ±1 SD of the national trend.
- **Live forecasts** (illustrative; see the intervals on the page). QCEW Illinois private employment 2026Q1: posting model 72.7k (+0.7% YoY), CES model 71.0k (−1.8%), naive 72.2k. The hard-data CES signal points to a small decline in 2026H1 that the posting models do not show.
- **Occupations (descriptive).** Across 25 sectors, higher AEI observed exposure goes with lower postings relative to Feb 2020 (ρ = −0.64, permutation p = 0.001) and relative to the 2022 peak (ρ = −0.45, p = 0.025). There is no relationship with the latest YoY change (ρ = +0.21, p = 0.31). The high-exposure sectors (software, data, marketing, media, IT) are also the remote-friendly sectors that boomed in 2021–22 and then contracted. This is a correlation and does not show that AI caused the decline.

## Caveats

- **Indeed indices are not vacancy counts.** They measure posting volume on one site relative to 1 Feb 2020, with Indeed's own seasonal adjustment. Indeed changed that method in Nov 2024 and revised history. No state × sector series exists, so sector signals are national.
- **Higher ed is not an Indeed sector.** "Education & Instruction" mixes K–12, childcare-adjacent and tutoring jobs. Campus jobs are spread across admin, accounting, HR, IT, research, nursing, custodial and other sectors, and most postings in those sectors come from other employers.
- **Short history.** Postings start Feb 2020: 22–24 quarterly changes and 9–12 scored backtest quarters. DM and Granger tests have low power, so a null result is not proof of no relationship. A "win" on 10 quarters is fragile.
- **COVID break.** 2020–21 dominates the variances. Every lead-lag test is repeated post-COVID, divergence fits exclude 2020Q2–2021Q2, and the nowcast reports a training-from-2022 robustness run.
- **Coverage gaps.** QWI is public and private combined (A00 only). QCEW suppresses Illinois state-university cells for 2025 and all local-government cells. CES Illinois covers NAICS 6112–6113 private. Illinois "employment" therefore differs by source: about 71k (QCEW private), about 73–89k depending on the month (CES private incl. junior colleges) and about 123k (QWI all ownerships).
- **Vintages.** Backtests use current, revised data rather than real-time vintages, which flatters every model somewhat.
- **AI usage is evidence, not prediction** (lake contract rule 10). The sector-to-SOC mapping is unreviewed, and exposure averages are unweighted because OEWS employment is not in the lake.

## Files

| Path | Contents |
|---|---|
| `acquire.py` | Downloads and hashes the extra sources |
| `tn_lib.py` | Pure statistics: transforms, prewhitened CCF, Granger F-test, BH q-values, DM test, rolling-origin backtest, LOO divergence z, Spearman permutation |
| `build.py` | Loads lake and raw data, builds the panel, runs all analyses, writes `artifacts/` |
| `render_html.py` | Builds the dashboard and the headline findings from `results.json` |
| `screenshot.js` | Playwright desktop and phone screenshots, with an error and overflow check |
| `tests/test_trend_nowcast.py` | 21 unittest cases: synthetic known-answer tests for the statistics, no-look-ahead check, and artifact and HTML checks |
| `artifacts/` | `aligned_quarterly_panel.parquet/.csv`, `results.json` (regenerable) |
| `data/raw/` | Downloaded files (regenerable; large Indeed CSVs; do not commit) |

Attribution: Indeed Hiring Lab (CC BY 4.0); BLS QCEW, CES and CPI; U.S. Census Bureau LEHD QWI; Anthropic Economic Index (CC BY 4.0, per its repository).
