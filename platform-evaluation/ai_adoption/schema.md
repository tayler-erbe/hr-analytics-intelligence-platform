# AI Adoption Impact Scorecard: schema and data contract (v0.1-draft)

The machine-readable contract is [`contract.py`](contract.py). `metrics.py` checks every input against it (column names, types and enumerations) before computing anything and stops with `ContractError` on any mismatch. This file explains the same contract in prose, with the privacy rules every output has to meet.

**Status:** a draft for agreement with SP&P, the series partners (OCIO, Technology Services, CITL, Library) and the data owners. Nothing in this folder has touched real data. The prototype runs on the synthetic tables from `synthesize.py`.

## 1. Program structure the contract assumes

Tier names come from the public AI Professional Development Series pages, checked 2026-11-06. Formats and prerequisites below are modelling assumptions that need confirming with the program team.

| Track | Level | Tier | Core component | Applied component | Badge rule (assumed) |
|---|---:|---|---|---|---|
| Staff | 1 | AI Explorer | Self-directed modules in Canvas (4) | — | All modules complete |
| Staff | 2 | AI Catalyst | Tool deep-dive workshop | Role-scenario session | Both complete |
| Staff | 3 | AI Practitioner | Intermediate tool workshop (2 sessions) | Role-aligned cohort (≥3 of 4 meetings) | Both complete |
| Leaders | 1 | AI Ready Leaders | E-learning (modules include AI fluency and responsible AI leadership) | — | All modules complete |
| Leaders | 2 | AI Adaptive Leaders | Leader workshop (2) | Leader cohort (≥3 of 4) | Both complete |
| Leaders | 3 | AI Forward Strategies | Strategy workshop (2) | Leader cohort (≥2 of 3) | Both complete |
| Staff | — | Unit Training | Session requested by a unit for its own staff | — | Counts toward reach, no badge |

"Super AI users" (a phrase from the series goals page) are defined here as holders of the top badge on either track. Changing the badge rules means editing `TIERS` in `contract.py`. The metrics read the required counts from there.

## 2. Event tables

`pii` columns are pseudonymous person, rater or event keys. They may exist only on an approved university machine and must never appear in any output (see §4). **`person_key`** is a salted hash produced on the approved machine from the UIN. The salt stays there, and the same salt is used across all tables so they can be joined.

| Table | Grain | Real source | Required |
|---|---|---|---|
| `workforce_denominator` | unit × role family × track (an **aggregate** headcount, not a roster) | EDW/Banner headcount extract at a fixed date | yes |
| `registration` | person × offering × component (`core`, `applied`, `unit_training`) | AI PD registration system | yes |
| `attendance` | person × session attended, or × Canvas module completed | Check-in or Zoom attendance export; Canvas module completions | yes |
| `badge` | person × badge issued | Digital badge platform | yes |
| `assessment_score` | artifact × rater × rubric criterion (1–4) | Human rubric scoring sheet. No model grading | yes |
| `pulse_response` | response × item (long format) | Qualtrics: post-session reaction, 30/60/90-day follow-ups, facilitator observation form, quarterly campus AI pulse | yes |
| `use_case` | use case submitted to the Joint Innovation in AI Team | Use-case intake form or registry | yes |
| `tool_usage_unit_month` | unit × month × tool (an **aggregate at source**) | Copilot Chat usage report, ChatGPT Edu workspace analytics, Illinois Chat admin logs | optional |
| `mobility_event` | internal talent event (application, transfer, promotion, successor nomination) | Cornerstone internal requisitions, EDW job changes, succession slates | optional |
| `ai_skill_demand` | unit type × role family: positions the workforce plan flags as needing applied AI skills (an **aggregate**) | Strategic workforce plan and JDXpert review | optional |

### Columns

| Table | Columns (type) |
|---|---|
| `workforce_denominator` | unit_id, unit_label, unit_type, role_family, track (VARCHAR); headcount (BIGINT); as_of (DATE) |
| `registration` | registration_id\*, person_key\*, offering_id, tier, track, wave, component, status (`active`/`cancelled`), unit_id, role_family (VARCHAR); registered_at (DATE) |
| `attendance` | attendance_id\*, person_key\*, offering_id, component, modality (`in_person`/`online`/`self_paced`) (VARCHAR); session_no, minutes (BIGINT); session_date (DATE) |
| `badge` | badge_id\*, person_key\*, tier, offering_id (VARCHAR); issued_at (DATE); core_complete, applied_complete (BOOLEAN) |
| `assessment_score` | score_id\*, person_key\*, tier, offering_id, rater_id\*, criterion (VARCHAR); score (BIGINT 1–4); scored_at (DATE) |
| `pulse_response` | response_id\*, person_key\*, instrument, wave, tier, unit_id, role_family, track, item_id (VARCHAR); responded_at (DATE); value (DOUBLE) |
| `use_case` | use_case_id\*, submitter_person_key\*, unit_id, role_family, track, category, data_classification (VARCHAR); submitted_at, triaged_at, pilot_started_at, adopted_at, first_reuse_at (DATE); reuse_unit_count (BIGINT); hitl_checklist_complete (BOOLEAN); est_hours_per_month, validated_hours_per_month (DOUBLE) |
| `tool_usage_unit_month` | unit_id, tool (VARCHAR); month (DATE); licensed_users, active_users, repeat_users (BIGINT) |
| `mobility_event` | event_id\*, person_key\*, event_type, unit_id, role_family, track (VARCHAR); event_date (DATE) |
| `ai_skill_demand` | unit_type, role_family, plan_year (VARCHAR); positions_flagged (BIGINT) |

\* = identifier or `pii` column: allowed in inputs, forbidden in outputs.

`unit_id`, `role_family` and `track` on event rows are attributes as of the event. They come from the source system's embedded data, such as Qualtrics embedded data or the registration form. That way unit-level aggregation does not need a person roster. Role families are FAC, AP, CS_ADM, CS_TECH and RES, with labels in `contract.py`. Real data needs a reviewed crosswalk from Banner employee class to these families.

### Survey items (`pulse_response.item_id`)

| Item | Scale | Instruments | Level |
|---|---|---|---|
| satisfaction, relevance, confidence_to_apply | 1–5 | reaction | L1 |
| recommend | 0–10 (NPS) | reaction | L1 |
| tool_use_days | 0–5 workdays/week | followup, campus_pulse | L3 |
| tasks_augmented | 0–15 tasks in last 2 weeks | followup | L3 |
| prompt_soph_self | 1–5 anchored scale | followup | L3 |
| prompt_soph_observed | 1–5, same anchors | facilitator_obs | L3 |
| hitl_practices | 0–4 count: verify output; no sensitive data in non-approved tools; disclose AI use; human makes the final decision | followup | L3 |
| trust_ai, psych_safety, manager_support | 1–5 | followup (baseline, d90), campus_pulse | enabling |

Follow-up waves are `baseline` (at registration), then `d30`, `d60` and `d90` after the entry tier's core completion. Campus pulse waves are quarterly and labelled `P2025_06` … `P2026_10`. The pulse goes to a random sample of the whole workforce, so non-participants form a comparison group.

### Rubric criteria (`assessment_score.criterion`)

`task_framing`, `output_verification`, `responsible_use` and `workflow_integration`, each scored 1–4 by trained human raters. About 25% of artifacts are double-scored for agreement statistics: exact agreement, ±1 agreement and quadratic-weighted κ.

## 3. Derived measures (computed in `metrics.py`)

| Level | Measure | Definition |
|---|---|---|
| L0 | Reach | Distinct people registered for any badge tier ÷ `workforce_denominator` headcount. Unit Training attendance is reported separately |
| L0–L2 | Funnel | Eligible → registered → started → entry tier completed with badge → applied badge (level ≥2) → top badge (level 3). Each stage is filtered on the previous one, so the funnel is monotone by construction (tested) |
| L1 | Reaction | Item means and NPS by tier; relevance by role family |
| L2 | Proficiency | Rubric mean per criterion (raters averaged per artifact). "Proficient" means an artifact mean ≥2.5 with no criterion below 2. Inter-rater agreement is computed on double-scored artifacts |
| L3 | Behavior Change Index (BCI, 0–100) | Mean of tool_use_days/5, min(tasks,8)/8, (prompt_soph_self−1)/4 and hitl_practices/4. Paired change is the same person's BCI at d30/d60/d90 minus their baseline. Percentile-bootstrap 95% CI, 2,000 resamples of people |
| L3 | Applied use at d90 | tool_use_days ≥2, tasks ≥1 and hitl ≥3, among d90 respondents |
| L3 | Early vs later DiD | Campus-pulse tool_use_days. Early = entry tier completed Oct–Dec 2025; later = completed Apr–Jun 2026. Pre = Sep 2025, post = Jan 2026. The placebo uses Jun→Sep 2025. Bootstrap clusters on person. **Descriptive, not causal** |
| L4 | Use-case pipeline | Furthest stage reached; submissions by quarter and unit type; estimated hours per month for adopted use cases; median validated-to-estimated ratio where time studies exist |
| Enabling | Conditions | % favorable (4–5) by campus-pulse wave; d90 BCI change by baseline manager-support band (associational) |
| Telemetry | Active and repeat rates | active ÷ licensed and repeat ÷ active, by tool and month. Not de-duplicated across tools |
| Talent | Badge linkage | Applied-badge rate by role family (access equity); talent events per 100 person-years before and after the badge vs comparison groups; badge supply vs plan demand; badge share among successor nominees vs the eligible pool |

## 4. Privacy rules (enforced by `privacy.py`, tested)

| Rule | Requirement |
|---|---|
| **P1 minimum cell** | Every published count is 0 or ≥ k (k = 10). Counts of 1–9 become `null` and show as "<10" |
| **P2 rates** | A rate is published only when its denominator is ≥ k and its numerator is 0 or ≥ k |
| **P3 statistics** | A mean, index, change, CI, DiD or event rate is published only when it rests on ≥ k distinct people or use cases |
| **P4 complementary suppression** | Count tables published with margins (unit × role family) get secondary suppression. The algorithm iterates a line pass (no row or column with exactly one hidden item) and a rank test (no hidden cell exactly determined by the table's linear constraints). Random tables are tested |
| **P5 no person-level output** | No identifier column (`FORBIDDEN_OUTPUT_KEYS`), no string matching an identifier pattern, and no list long enough to be a record dump appears in the JSON or HTML. `audit()` runs before the JSON is written and again before the page is rendered; either refuses on any violation |
| **P6 approved machines** | Event tables with `pii` columns live only on an approved university machine. Only the aggregate `scorecard.json` (and the page built from it) may leave |
| **P7 synthetic labelling** | Outputs carry the input's data label. The page shows a "Synthetic demonstration data" banner whenever the label says SYNTHETIC |

Known residual risks, which need a disclosure review before real publication:
- **Differencing across overlapping slices.** A unit total and a unit × track figure could be subtracted. Only the unit × role-family crosstab is protected as a table today.
- **Interval disclosure.** P4 prevents exact recovery, not narrow bounds. Confirm with τ-ARGUS or sdcTable.
- **Complement disclosure.** A rate near 100% of a small group reveals that nearly everyone did something. P2 does not test n − numerator.
- **Repeated releases.** Successive monthly scorecards can be differenced. Publish on a fixed cadence and keep the suppression pattern stable.

## 5. Outputs

| File | Content |
|---|---|
| `data/published/scorecard.json` | The only artifact meant to leave the approved machine: aggregates, suppressed and audited |
| `../output/ai_adoption/ai_adoption_scorecard.html` | Offline page built from that JSON only |
| `data/synthetic/*.parquet` | Synthetic person-level event tables. Regenerable and git-ignored. They **must never be replaced with real extracts in this repository** |
