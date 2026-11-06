# AI proficiency assessment toolkit (human-scored)

Solution #2 in [`research/IHR_STRATEGIC_PROGRAMS_OPPORTUNITY_BRIEF.md`](../research/IHR_STRATEGIC_PROGRAMS_OPPORTUNITY_BRIEF.md). It is a work-sample assessment of applied AI proficiency and "prompt sophistication," aligned to the staff tiers of the AI Professional Development Series. **Trained human raters score every work sample.** The software computes reliability, rater drift, item statistics, cut scores, decision consistency and fairness checks.

Status: **draft for SME and rater-panel review**. Badge thresholds are provisional. All ratings in this folder are synthetic, and no real person, rater or work sample is involved.

> **Tier names (corrected 2026-11-06 from primary sources).**
> - Staff: **AI Explorer** (self-directed, Canvas) → **AI Catalyst** (tool deep-dive plus a role-scenario session) → **AI Practitioner**.
> - Leaders: AI Ready Leaders → AI Adaptive Leaders → AI Forward Strategies.
>

## What is here

| File | What it is |
|---|---|
| `rubric.yaml` | 8 dimensions × 4 anchored levels with behavioral examples. Includes gate dimensions, auto-floor rules, badge rules for Explorer / Catalyst / Practitioner, the mapping to the reskilling competency framework and to the IHR HR Competency Model, and the double-scoring policy |
| `tasks.yaml` | 12 scenario tasks covering HR (3), Finance (2), Advising (2), IT support (2), Admin (2) and one common judgment task. Each task has synthetic materials, planted errors and sensitive fields, auto-floor triggers and a scoring guide for every dimension |
| `reliability.py` | Statistics library (stdlib + numpy): weighted Cohen's kappa; Krippendorff's alpha (nominal / ordinal / interval, missing data allowed); Shrout–Fleiss ICCs including ICC(2,1) and ICC(2,k); bootstrap CIs; rater severity; rater drift against anchor papers; Cronbach's alpha and item analysis; SEM; modified-Angoff cut and impact; decision consistency; Mantel–Haenszel and standardization DIF; Fisher exact test; four-fifths impact ratios with small-cell suppression |
| `rubric_io.py` | Stdlib reader for the YAML subset used here, rubric and task validation, and badge classification |
| `synth.py` | Seeded synthetic rating study with known, planted properties |
| `study.py` | Runs every analysis, checks that the planted properties are recovered, runs a 20-seed sensitivity analysis, and writes `artifacts/reliability_report.json` |
| `build_html.py`, `toolkit_template.html` | Render `../output/ai_proficiency/rubric_toolkit.html` |
| `CALIBRATION_WORKFLOW.md` | Rater training, anchor papers, 20% double-scoring, adjudication, drift monitoring, Angoff procedure |
| `tests/` | `test_reliability.py`: every statistic checked against hand-computed examples (worked in the docstrings) and published values (Krippendorff 2011; Shrout & Fleiss 1979). `test_toolkit.py`: rubric, tasks, YAML reader, badge rules, synthetic recovery, offline HTML |
| `screenshot_check.js` | Playwright check: no console errors or network requests, no horizontal scroll at 375 px, form save, CSV export; light and dark screenshots |
| `data/`, `artifacts/` | Synthetic study inputs and the report (regenerated deterministically) |

## Run

```bash
cd platform-evaluation/ai_proficiency
pip install -r requirements.txt          # numpy only
python study.py                          # synthetic data, analyses, 20-seed sensitivity, report JSON
python build_html.py                     # ../output/ai_proficiency/rubric_toolkit.html
python -m unittest discover -s tests -v  # 42 tests
node screenshot_check.js                 # optional; needs the playwright npm package
```

The HTML page is a single file with no external requests; a Content-Security-Policy blocks network access. It has five tabs:
- **Rubric:** the dimensions and badge tiers.
- **Tasks:** the 12 tasks, filterable by role family.
- **Score:** a scoring form for raters using pseudonymous codes. It rejects email- or ID-like entries and keeps rows in browser storage when available. It exports a long-format CSV with the same columns as `data/ratings_long.csv`, so `study.py` can analyze a pilot export, plus a candidate summary.
- **Reliability report:** the synthetic study.
- **About.**

## How it answers "measure beyond attendance"

The unit's IT Pro Forum talk asks for behavior change, task augmentation and **prompt sophistication** rather than registrations and satisfaction. This instrument measures performance on realistic work, which is Kirkpatrick level 2 evidence gathered with level 3 tasks:

- **Prompt sophistication is broken into observable parts:** framing (D1), constraints and format (D2) and purposeful iteration (D3). Each is scored from the candidate's actual prompt log, not from self-report.
- **Judgment about when humans stay in control is scored directly** through data-sensitivity judgment (D5), the human-in-the-loop decision (D6) and appropriate tool choice, including choosing not to use AI (D7). D5 and D6 are non-compensatory gates. A fluent prompter who pastes Sensitive data into an unapproved tool does not earn a badge.
- **Verification (D4) and documentation for reuse (D8)** link to the "reusable AI solutions" theme and the use-case registry (brief #9).
- **Program-level reporting.** The Adoption Impact Scorecard (brief #1) can report dimension-level distributions by cohort and unit: for example, the share of a cohort at Proficient on D4, or pre/post change on parallel tasks. These reports use aggregates only, with n < 10 suppressed, and are never reported by person.

## Validity argument (outline, Kane's interpretation/use argument)

| Inference | Claim | Evidence in this folder | Evidence still needed |
|---|---|---|---|
| **Scoring** | Scores reflect the rubric, applied consistently | Anchored levels with examples; auto-floor rules; rater training and adjudication; agreement statistics (κw, α, ICC); drift monitoring | Pilot agreement on real samples; anchor papers with panel master scores |
| **Generalization** | A sitting's score generalizes across tasks and raters | ICC(2,1) vs ICC(2,k); item analysis; decision-consistency estimate; seed sensitivity | A generalizability study (persons × tasks × raters) on pilot data to choose the number of tasks and reads; parallel-form equating across role-family tasks |
| **Extrapolation** | Performance on scenarios reflects performance on the job | Tasks built from real role situations, with Sensitive fields and planted errors that mirror real risks | SME content-validity ratings (Lawshe CVR) per task; 60/90-day follow-up linking badge level to observed work-practice indicators, aggregated |
| **Decision** | Badge cut scores separate the tiers defensibly | Modified-Angoff helper with SE and impact; non-compensatory gates; targeted second reads near cuts | A real Angoff panel; decision consistency of at least about 80% at each cut before badges carry weight |
| **Consequences** | Use is beneficial and not harmful | Learner-owned credential; no employment use; fairness checks; appeals | Monitoring of participation and pass rates by role family and accommodation use; staff survey on trust and psychological safety (named as a hard part in the unit's own talk) |

## Fairness checks

- **DIF by role family.** For each dimension, each family (focal) is compared with all others (reference), matched on the rest score in 5 quantile bands. The analysis computes the Mantel–Haenszel common odds ratio (score ≥ 3), the ETS delta and class, and the standardized mean difference (SMD). A second stage purifies the analysis: dimensions flagged in stage 1 are dropped from the matching score, and families flagged in the opposite direction are dropped from the reference group. A flag triggers SME review of the task and anchor wording, never an automatic score change. With about 30 candidates per family, power is limited. In the 20-seed study, the planted DIF (D7, Advising) was detected in 18 of 20 seeds, and the false-flag rate was 2.1% per null comparison.
- **Pass-rate impact ratios** by role family use the four-fifths rule with a Fisher exact p-value, and groups under 10 are suppressed.
  - In the synthetic study, Practitioner rates differ by family (IT support 7% vs Admin 30%, Fisher p = 0.04) **even though no group difference was planted**. The cause is the role-family tasks themselves: they differ in difficulty (task means 2.07–2.92), and each family takes a different task.
  - **This is a real design risk.** Role-family tasks are not equated forms. Before operational use, the pilot must estimate task difficulty, then revise tasks or equate them, for example by anchoring on the common task T12.
- **Accommodations.**
  - Extended time.
  - A paper or transcript mode: the candidate writes the prompts they would use and the tool responses are supplied. Score D1–D3 from the prompts.
  - Screen-reader-compatible materials.
  - Raters are trained not to score writing fluency.

  Record accommodation use, without type and kept separate from scores, so outcomes can be compared in aggregate (suppressed when n < 10).
- **Rater assignment and blinding** keep rater effects from lining up with role family (see `CALIBRATION_WORKFLOW.md`).

## Privacy and appropriate use

- **Voluntary, learner-owned credential.** Results are not shared with supervisors without the learner's consent. They are not used for hiring, promotion, pay, discipline, tenure or **selection for training**, which Illinois HB 3773 / P.A. 103-0804 covers. Get a written legal and HB 3773 review before the pilot, because a badge that gates entry to a later cohort could count as selection for training.
- This does not conflict with the reskilling framework's rule against scoring people. That framework (`reskilling/competency_framework.yaml`) sets **role-level** design targets. This instrument is a separate, opt-in credential, and its program reporting stays aggregate.
- **Data handling:**
  - Use pseudonymous candidate codes, with the key held separately.
  - Work samples are scrubbed by design, because tasks reward candidates for not including personal data.
  - Store data only on approved university systems, with retention set by the program.
  - Publish aggregates only, with n < 10 suppressed.
- **Materials are synthetic by construction.** Tests check that the task files contain no email addresses or 9-digit IDs.

## Why platform AI functions or LLM judges are not a substitute

1. **The construct includes judgment about AI.** Several dimensions (D4 verification, D6 human-in-the-loop, D7 when not to use AI) reward people for *not* trusting model output. Having a model grade that behavior asks the measured technology to certify scepticism toward itself.
2. **Validity evidence.** A credential needs documented rater agreement, standard setting and fairness analysis. LLM-judge scores shift with model version, prompt wording, output order and length. They can prefer fluent or model-like text (self-preference and verbosity bias), and a vendor can change the judge without notice. That breaks the scoring and generalization inferences above.
3. **Fairness and law.** Automated scoring of employees feeds HB 3773's notice and adverse-impact obligations, and could be challenged if used later for selection. Human scoring with logged rationales is explainable and appealable.
4. **Data.** Work samples may contain the Sensitive fields the tasks plant. Sending them to hosted platform AI functions moves employee-generated content off approved inference; the brief notes Snowflake cross-region inference defaults to on for new accounts.
5. **What software is allowed to do here:** compute statistics, flag drift, sample double reads and render reports. Any future machine pre-scoring would need to be evaluated *against* this human-scored dataset, as a separate study, and could only ever be an advisory second read.

## Synthetic study: results (seed 20261106)

Synthetic data with planted properties:
- 6 raters: R3 severe (−0.55), R5 lenient (+0.50), R6 drifting lenient (+0.25 per session).
- 150 candidates, 30 in each of 5 role families, each taking 2 tasks.
- A 20-artifact fully crossed calibration set, 10 anchors per session, and 20% of sittings double-scored.
- An 8-member Angoff panel over 2 rounds.

| Result | Value |
|---|---|
| Recovery checks (severe, lenient, drifting, static-bias raters; weakest item D8; planted DIF; Angoff cuts; panel convergence) | 11/11 pass on the main seed. Over 20 seeds: drift recovery 18/20, DIF detection 18/20, all others 20/20 |
| Calibration total score ICC(2,k), 6 raters | 0.94 (95% CI 0.86–0.96) |
| Calibration total score ICC(2,1), single rater | 0.71 (0.50–0.81) |
| Krippendorff's α (ordinal), calibration, all dimension cells | 0.58 |
| Operational double reads: QWK; exact / within-1 agreement | 0.45; 45% / 93%. Per-dimension α 0.37–0.63, and −0.06 for D8 |
| Internal consistency (8 dimensions) | α 0.94; SEM 1.18 points on the 8–32 total |
| Angoff recommended cuts (round 2) | Explorer 13.5, Catalyst 18.5, Practitioner 25.0 (provisional values: 13 / 18 / 25) |
| Badge decision agreement, double-scored candidates (n = 30) | 47% (κ 0.23) |
| Same, synthetic replication of all 150 | 55% (κ 0.35). With severity and drift removed: 74% |

**Honest reading:**
- The instrument's internal structure holds up, and the toolkit finds every planted problem.
- **Badge decisions from one or two reads are not dependable under these rater conditions.** Four ordered tiers sit only about 5 points apart, and the SEM is about 1.2. The calibration workflow, targeted second reads near cuts and possibly a third task are what would close the gap. A real pilot must measure this before any badge relies on the instrument.
- D8 (documentation/reuse) behaves as planted: low variance and low discrimination. In a real pilot that pattern would point to revising its anchors.

**Choices made after seeing the synthetic results** (disclosed so nobody mistakes them for pre-registered settings):
- The rater bias flag threshold was lowered from 0.5 to 0.3 points, because rounding to the 1–4 scale attenuates a 0.5-point latent bias to about 0.45 observed.
- The two-stage DIF purification was added after the one-stage analysis produced a spurious D7/HR flag and extra Advising flags. Both are standard methods, but the pilot should fix its thresholds before looking at real data.

## Limitations and open items

- The data are synthetic. The generating model (a common latent factor, rater offsets, Gaussian noise rounded to 1–4) is simpler than real rating behavior, so none of the numbers predict a real pilot.
- The YAML reader supports only the subset these files use. Tests cross-check it against PyYAML when PyYAML is installed.
- Not yet built:
  - a generalizability study (G-study / D-study);
  - a many-facet Rasch model;
  - IRT for polytomous items;
  - polytomous Mantel DIF (only dichotomized MH plus SMD are implemented).
- To confirm with SP&P:
  - the exact wording of the six HR Competency Model competencies (only "Digital Proficiency & Data Savviness" and "Cognitive Flexibility" are mapped);
  - the current campus data-classification categories and approved-tool list;
  - whether Explorer is awarded on Canvas completion alone.
