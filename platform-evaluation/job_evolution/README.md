# Job evolution model (real O*NET history)

This prototype measures how the O*NET occupations behind University role families have changed across **20 archived O*NET database releases**, from 13.0 (June 2008) to 31.0 (August 2026). It also backtests a model that predicts which occupations will change at their next O*NET update, and it builds a role-family watchlist.

It uses **public data only** and works at **role level only**. The grain is an O*NET-SOC occupation, a University role family, or a SUCSS class linked through an unreviewed candidate. No person is read, stored or scored. Do not use any output for a decision about an individual (Illinois HB 3773).

Explorer: [`../output/job_evolution/job_evolution_explorer.html`](../output/job_evolution/job_evolution_explorer.html). It is one 1.7 MB file that makes no network calls, and screenshots are in `../output/job_evolution/screenshots/`.

```bash
cd platform-evaluation
pip install -r job_evolution/requirements.txt
python job_evolution/run_all.py --download   # downloads about 300 MB, one file at a time with 4 s delays; omit --download to reuse it
python -m unittest discover -s job_evolution/tests -v   # about 2 min; JE_SKIP_SLOW=1 skips the end-to-end rerun
node job_evolution/screenshot.js                       # Playwright: desktop and phone, light and dark
```

The full pipeline takes about 3 minutes. `run_all.py` writes `artifacts/manifest.json`, which holds the SHA-256 of 28 inputs and 15 outputs. Outputs contain no wall-clock time, and a test checks that rerunning the model reproduces the stored report and predictions byte for byte.

| File | Role |
|---|---|
| `acquire.py` | Downloads releases, the crosswalks for 2000→2006, 2006→2009, 2009→2010 and 2010→2019, and O*NET's *Longitudinal Data Updates* workbook. Writes `data/lake/raw/onet_history/manifest.json`, which records the URL, size and SHA-256 of each file. That folder is gitignored. |
| `build_panel.py` | Parses each release into long tables in `data/lake/raw/onet_history/derived/`: tasks, skill and work-activity ratings, technology examples, job zones and emerging tasks. It also checks each release's taxonomy against the crosswalk code lists and writes `artifacts/release_inventory.json`. |
| `harmonize.py` | Pure functions: text normalization, task matching, technology rename detection, taxonomy link cardinality and crosswalk chaining. |
| `indicators.py` | Builds lineages and computes per-interval indicators, then validates detected updates against O*NET's own update file. |
| `model.py` | Rolling-origin backtest, update-timing hazard model, and final predictions at O*NET 31.0. |
| `watchlist.py` | Maps results to University families and SUCSS classes and writes the explorer bundle. |
| `render_explorer.py`, `screenshot.js` | Build the offline page and screenshot it. |
| `tests/test_job_evolution.py` | 19 tests covering harmonization fixtures, leakage, reproducibility and the absence of person-level fields. |

## Data

- **Releases.** The pipeline uses one summer production release per year (13.0, 14.0, 15.0, 16.0 … 31.0), plus 15.1, the first release on O*NET-SOC 2010. Every release was matched against the code lists, which corrected one assumption:
  - 13.0 uses the 2006 taxonomy.
  - 14.0 and 15.0 use 2009.
  - 15.1 to **25.0** use 2010. Release 25.0 is still on 2010; the first 2019-taxonomy release was 25.1.
  - 26.0 to 31.0 use 2019.
- **Technology examples.** These exist in the database files **only from 21.0 (2016)**. The archived 13.0–20.0 zips contain no Tools & Technology file. Hot Technology flags are present from 21.0.
- **Schema changes handled:**
  - *Tools and Technology* (T2 Type = Technology) in 21.0–23.0.
  - *Technology Skills* in 24.0–30.0.
  - *Software Skills* in 31.0, which uses content-model element IDs instead of UNSPSC codes.
  - In 31.0, `Skills.txt` was split into *Essential Skills* and *Transferable Skills*. They are recombined by element ID, giving the same 35 elements.
- **Update source and date.** Every task statement and rating carries O*NET's `Date` and `Domain Source`:
  - Task sources are Incumbent, Occupational Expert, Analyst and Analyst - Transition.
  - Skills were incumbent-rated until 15.0 and analyst-rated afterwards.

## Harmonization

- **Lineages, not codes.** A lineage follows native O*NET-SOC codes across releases only through **identity or 1:1 crosswalk links**. A split, merge or complex link ends the lineage, so change is never measured across a taxonomy break. There are 222 1:1 code changes across the three taxonomy transitions. Each lineage is mapped to O*NET-SOC 2019 codes by chaining the crosswalks.
- **Task matching** (`PROTOCOL` in `common.py`):
  1. Same Task ID.
  2. Then identical normalized text under a new ID.
  3. Then the greedy best fuzzy pair, using difflib similarity on lower-cased text with punctuation removed and `and`, `or` and `and/or` folded together. O*NET rewrote "and" as "or" in many statements around 2014–2016, and folding keeps that from counting as change.

  Similarity bands:
  - **≥ 0.90:** a minor edit, counted as stable.
  - **0.70–0.90:** a substantive revision.
  - **< 0.70:** a removal plus an addition.

  **Task churn** = (added + removed + 2 × revised) / (old + new). This equals 1 minus the Dice overlap of the stable statements.
- **Technology renames** are not adoption. Two example names count as a rename when one of these holds:
  - their token sets are equal after dropping noise words ("SAP software" → "SAP");
  - one name's tokens contain the other's, as with "Adobe Systems Adobe Acrobat" → "Adobe Acrobat" or "SAS" → "SAS statistical software";
  - their similarity is ≥ 0.85.

  This removed **7,072 renames** that would otherwise appear as 7,072 additions and 7,072 removals.
- **Real updates.** A task (or skills, or GWA) update is detected when the maximum O*NET `Date` on that occupation's statements or ratings increases between sampled releases. Checked against O*NET's *Longitudinal Data Updates* file, the detected updates agree in **99.4% of 13,097** comparable task intervals and **99.95% of 12,886** GWA intervals.

## Rolling updates dominate release-to-release change

O*NET updates occupations on a rolling schedule. The table compares the 20,164 lineage × release intervals with and without a real task update:

| | Intervals with a real task update | Intervals without one |
|---|---:|---:|
| Count | 2,018 | 15,850 |
| Share with any task statement change | 43.1% | 2.0% |
| Mean task churn | 0.038 | 0.0012 |
| Task statement changes (added + removed + revised) | 2,673 | 618 |

The 618 changes outside update events are editorial or analyst actions. 507 of them are removals in O*NET 29.0, made without a new date.

**How this is modelled:**

1. Indicators are measured **at update events**, not per release.
2. A **discrete-time hazard model** of update timing is fitted: a binomial GLM with a complementary log-log link and a log(interval years) offset, with years since the last update, job zone and data source as covariates.
   - The annual update rate rises from 4.6% at 0–2 years since the last update to 27% at 8 or more years.
   - Trained on releases up to 23.0, it ranks updates in 24.0–31.0 with AUC **0.789**. The base rate in that period is 11.3%.
3. Predictions condition on the next update, and the watchlist combines P(update within 2 years) × P(change at that update).

Most O*NET updates leave task lists almost intact: 57% of real updates change no task statement. The mean churn per update fell from about 0.09 (2011) to about 0.01–0.03 (2021–2026).

## Indicators

These indicators are in `artifacts/occupation_indicators.parquet` and `transitions.parquet`:

- **Task churn at each real update.** Added, removed and revised statement text is kept in `task_changes.parquet`.
- **Skill-profile drift.** This is the RMS difference between the importance and level vectors after rescaling each to 0–1, over 35 skills and 41 GWAs, computed at successive real re-ratings.
  - Re-ratings where the source changed are excluded: 786 skill re-ratings, mainly the switch from incumbent to analyst skills in 15.0.
  - Drift between releases without a re-rating is exactly 0.
  - Mean skill drift is 0.04–0.05 per re-rating, and GWA drift is about 0.10.
- **Technology adoption velocity.** This is new examples per year, with AI/ML and data/analytics tools tagged by a transparent regex in `PROTOCOL`.
  - 2016–2026: 8,413 additions, 2,580 removals and 7,072 renames.
  - Only **18** of the additions are AI/ML tools, all from 28.0 onward: ChatGPT (6), TensorFlow (4), PyTorch (3), SageMaker, Hugging Face, LangChain, and others.
  - 1,181 additions are data tools.
  - Occupations listing an example, 21.0 → 31.0: Python 71 → 132; Power BI 1 → 27; Microsoft Teams 0 → 32; any AI/ML tool 14 → 23.
- **Emerging tasks.** O*NET's *Emerging Tasks* file (21.0 onward) lists incumbent write-ins that have not yet been adopted, and the timelines show the statements added at updates.

## Predictive model and backtest

### Targets

- **Task target.** At the lineage's next real task update after origin release *t*: is task churn above the 67th percentile of the training labels? Because most updates change nothing, this means "any substantive change". The final threshold is 0.029, and there are 1,922 label events.
- **Technology target.** In the next release interval: is technology-example churn above the training 67th percentile? O*NET publishes no technology update date, so the next release is the update unit. There are 8,298 rows.

### Features

All features are available at *t*:

- past task churn (last value, mean, and share of updates with any change), number of past updates, and non-update edits;
- years since the last update and the source of the last update (incumbent, occupational expert or analyst);
- job zone, number of tasks and share of core tasks;
- GWA importance vector, used as task composition by GWA (41 values);
- last skill drift and last GWA drift;
- technology intensity: number of examples, hot-technology share, data-tool share, AI/ML count, past technology churn and adoption rate;
- number of emerging tasks listed;
- SOC major group.

### Leakage controls

These are asserted in code and tested:

1. `features_at()` filters to releases ≤ *t*. A test checks that features computed on a panel truncated at *t* are identical to those computed on the full panel.
2. Fold *T* trains only on rows with origin < *T* whose label event was published in a release ≤ *T*.
3. The threshold is computed from training labels only.
4. Rows that share one label event are down-weighted to a total weight of 1.
5. Hyperparameters are fixed, and the primary model, an L2 logistic regression, was pre-specified.
6. **The Anthropic Economic Index (AEI) exposure was published in 2025–2026, after every test origin**, so it appears only in the separately reported, flagged `logit_aei_expost` variant.

### Censoring

Test and training rows need an observed next event:

- 3,879 task rows had no update by 31.0;
- 2,202 rows ended at a taxonomy split or merge;
- these rows are excluded, which biases later folds toward occupations that update faster.

### Results

Rolling origins are 17.0–26.0 for the task target and 24.0–29.0 for the technology target. Confidence intervals are 95% intervals from 400 bootstrap resamples of lineages.

| Target | Model | Pooled AUC [95% CI] | Mean fold AUC | Avg precision | Brier | ECE |
|---|---|---|---:|---:|---:|---:|
| Task | **Logit (primary)** | **0.641 [0.607, 0.674]** | 0.678 | 0.228 | 0.184 | 0.191 |
| Task | Logit, recalibrated (post hoc) | 0.629 [0.596, 0.660] | | 0.199 | **0.142** | **0.096** |
| Task | LightGBM | 0.599 [0.561, 0.632] | 0.641 | 0.186 | 0.169 | 0.154 |
| Task | Logit + AEI (**ex post**) | 0.641 | | 0.228 | 0.184 | 0.191 |
| Task | Baseline: family mean | 0.540 [0.497, 0.579] | 0.537 | 0.152 | 0.162 | 0.186 |
| Task | Baseline: last change | 0.459 [0.429, 0.491] | 0.483 | 0.117 | 0.208 | 0.270 |
| Task | Baseline: training base rate | n/a | | 0.138 | 0.153 | |
| Tech | **Logit (primary)** | **0.575 [0.557, 0.593]** | 0.607 | 0.442 | 0.226 | 0.132 |
| Tech | LightGBM | 0.583 [0.564, 0.602] | 0.612 | 0.467 | 0.222 | 0.135 |
| Tech | Baseline: family mean | 0.573 [0.556, 0.592] | 0.614 | 0.409 | 0.214 | 0.059 |
| Tech | Baseline: last change | 0.377 | 0.481 | 0.244 | 0.225 | 0.087 |

For the task target, the test-period base rate is 13.4%. A constant equal to that test base rate would have a Brier score of 0.116. That value is an oracle reference, because it uses test information.

### What the results mean

- **Task change: modest but real signal.**
  - The primary logit beats the family-mean baseline by +0.063 to +0.142 AUC (paired bootstrap CI) and the last-change baseline by +0.14 to +0.22.
  - Folds from 22.0 onward reach AUC 0.73–0.78, compared with 0.49–0.65 before. The strongest feature is the number of **emerging tasks** O*NET lists at the origin, which is available only from 21.0.
  - Past churn is *not* predictive: the last-change baseline scores below 0.5.
- **The primary model is poorly calibrated.**
  - Its calibration slope is 0.27. It is over-dispersed, and it over-predicts because the rate of changes per update fell over time.
  - A post-hoc Platt recalibration helps (Brier 0.142, ECE 0.096). It is leak-free, because it is fitted on the labels published in the two releases before each origin, but it was **added after the first backtest run was inspected** and is labelled as post hoc.
  - Even recalibrated, the model's Brier score is worse than the oracle constant.
- **Technology churn: the model does not beat the family mean.** The paired AUC difference is −0.013 to +0.019. Technology churn is driven by O*NET's bulk technology-update campaigns. The 27.0→28.0 fold has AUC 0.48 for every model, and the base rate swings from 11% to 47% between folds.
- **AEI exposure (ex post) adds nothing.** The AUC difference is 0.000.

## University mapping and watchlist

**Role families.** The 164 O*NET occupations with predictions in nine families use the same SOC prefixes as `reskilling/build_pathways.py` `FAMILIES`. SUCSS classes (883 records) are linked through the rank-1 candidate in `sucss_mapping/outputs/candidates.parquet` (`sucss_duty_tfidf_v1`, all `unreviewed`); 179 of these links have weak evidence and 30 abstained.

**Watch score.** It is the mean of three percentile ranks across the 923 scored occupations:

1. P(task update within 2 years) × P(substantive change at that update);
2. P(high technology churn next release);
3. the number of data and AI tools added from 2016 to 2026, with AI/ML weighted 3×.

The score is a rank for where to look first. It is not a forecast of job loss.

| # | Role family | Roles | Watch | P(update ≤ 2 y) | P(task change \| update), 10–90% | P(high tech churn) | Tech added / yr |
|---|---|---:|---:|---:|---|---:|---:|
| 1 | IT & data | 30 | 0.72 | 24% | 13% (3–24%) | 65% | 5.7 |
| 2 | Admin/IT/HR/finance/facilities management | 11 | 0.69 | 29% | 31% (24–38%) | 39% | 1.7 |
| 3 | Business operations | 28 | 0.68 | 26% | 36% (28–45%) | 45% | 1.6 |
| 4 | HR & training | 5 | 0.67 | 29% | 13% (3–24%) | 45% | 1.9 |
| 5 | Library & archives | 6 | 0.66 | 31% | 39% (29–49%) | 41% | 1.0 |
| 6 | Student services | 2 | 0.63 | 45% | 8% (3–14%) | 43% | 1.6 |
| 7 | Finance & accounting | 23 | 0.61 | 26% | 21% (13–31%) | 40% | 0.9 |
| 8 | Office & administrative support | 42 | 0.50 | 20% | 23% (15–35%) | 36% | 1.0 |
| 9 | Facilities & building services | 17 | 0.40 | 17% | 37% (28–47%) | 26% | 0.5 |

All probabilities above are from the primary, uncalibrated model. They over-predict in absolute terms, so compare them, not their levels; the post-hoc recalibrated values are in `predictions_latest.parquet`.

**Reading the table.**

- IT ranks first on technology adoption, not task change.
- Library and facilities roles rank high on P(task change) but low on technology.
- The student-services and HR families have 2 and 5 occupations, so their means are fragile.
- Family members follow the inherited prefixes. For example, "Coroners" falls under Business operations.

## Known weaknesses, stated plainly

1. **O*NET is a slow, survey-driven instrument.** Task change mostly records O*NET's re-survey calendar. Most real updates change nothing. The tagged AI/ML technology examples are negligible: 18 additions in ten years. This model cannot see AI adoption in University jobs.
2. **The technology history starts in 2016** and mixes employer adoption with O*NET's job-posting-based collection and bulk editorial passes.
3. **Censoring and survivorship.** Occupations that did not update by 31.0, and lineages broken by taxonomy changes, drop out of the backtest.
4. **The thresholds and the regex vocabulary** in `PROTOCOL` are design choices. The recalibrated variant is post hoc.
5. **SUCSS links are unreviewed suggestions.** O*NET data are national, not University positions.
