# AI Adoption Impact Scorecard (prototype)

Solution #1 in the [SP&P opportunity brief](../research/IHR_STRATEGIC_PROGRAMS_OPPORTUNITY_BRIEF.md) is a measurement model for the University's AI Professional Development Series. It follows people from registration through tier badges to applied AI use at 30, 60 and 90 days, then to use cases and hours returned, and finally to the badge → talent-marketplace and workforce-planning link the series' goals page describes. Results are reported by unit, role family, track and cohort, **never by person**.

**All data here is synthetic.** `synthesize.py` invents a 12,905-person workforce and a year of program activity. No real person, unit roster, registration, badge, survey response, talent event or tool log was used. Unit labels are archetypes ("Academic college: large STEM"), not real units. The page carries a "Synthetic demonstration data" banner.

Open `../output/ai_adoption/ai_adoption_scorecard.html`. It is a single 90 KB offline file with no network requests, a light/dark theme, and a layout that works at phone width.

## Run

From `platform-evaluation/` (Python 3.13, duckdb 2.0, pyarrow and numpy, the same requirements as `workforce_sim/requirements.txt`):

```bash
python ai_adoption/synthesize.py          # seeded synthetic event tables -> ai_adoption/data/synthetic/ (+ manifest, ground truth)
python ai_adoption/metrics.py             # contract check -> metrics -> suppression -> audit -> ai_adoption/data/published/scorecard.json
python ai_adoption/build_page.py          # -> output/ai_adoption/ai_adoption_scorecard.html
python -m unittest discover -s ai_adoption/tests -v    # 28 tests, ~14 s
```

Options: `synthesize.py --seed N --no-telemetry --no-talent` and `metrics.py --data-dir DIR --no-telemetry --no-talent`. The two optional input groups can be left out, and the page then shows "not connected" for those panels.

| File | Role |
|---|---|
| `contract.py` | Machine-readable data contract: tables, columns, types, enumerations, tiers, survey items, rubric criteria, forbidden output keys, k |
| `schema.md` | The contract and privacy rules in prose |
| `synthesize.py` | Seeded synthetic program. All behavioural parameters are listed in `ASSUMPTIONS` |
| `privacy.py` | k = 10 cell rules, rates and means, bootstrap CI, complementary suppression with a rank test, and `audit()` |
| `metrics.py` | DuckDB metrics over the contract tables, plus numpy bootstrap. Writes one aggregate JSON |
| `build_page.py` | Embeds the audited JSON in a vanilla JS/SVG page. Re-audits before writing |
| `tests/test_ai_adoption.py` | Suppression, reproducibility, absence of person-level output, funnel monotonicity, contract checks, optional inputs |

## The measurement model

The model takes Kirkpatrick/Phillips and points it at adoption rather than course completion. That is the argument of the unit's own talk, "Measuring AI Adoption in Practice: Moving Beyond Traditional Learning Metrics".

| Level | Question | Evidence | Where it shows |
|---|---|---|---|
| **L0 Reach** | Who is the series reaching, and who is it missing? | Registrations, sessions and module completions against an aggregate EDW headcount by unit, role family and track. Unit Training is counted separately | Funnel, heat map, unit × role crosstab |
| **L1 Reaction** | Was it relevant to the job? | Post-session Qualtrics: satisfaction, relevance, confidence to apply, NPS | Reaction table; relevance by role family |
| **L2 Proficiency** | Can people actually do it? | Badges, plus a **human-scored** 4-criterion rubric on the applied artifact, with double scoring and weighted κ | Tier progression, rubric and agreement tables |
| **L3 Behavior** | Did work practice change? | 30/60/90-day follow-ups: approved-tool use days, tasks augmented, prompt sophistication (self-rated and facilitator-observed), human-in-the-loop practices. Combined into a 0–100 Behavior Change Index. Paired change uses bootstrap CIs. A quarterly campus pulse gives a non-participant comparison and an early-vs-later difference-in-differences | Behavior panel, DiD panel, cohort retention |
| **L4 Results** | Did it return capacity, and does it spread? | Use cases submitted to the Joint Innovation in AI Team, through triage, pilot, adoption and reuse in other units; estimated hours per month, discounted by the time-study ratio where one exists | Use-case pipeline |
| **Enabling conditions** | Does the environment allow adoption? | Trust in AI, psychological safety and manager support (campus pulse and follow-up), and their association with behavior change | Enabling panel, heat map |
| **Telemetry** (optional) | Is use real and repeated? | Unit-month active and repeat users from the Copilot Chat, ChatGPT Edu and Illinois Chat admin reports | Telemetry panel, heat map |
| **Talent linkage** (optional) | Do badges feed the talent marketplace, workforce planning and succession, and fairly? | Applied-badge rate by role family (access equity); talent events per 100 person-years before and after the badge vs comparison groups; badge supply vs plan demand; badge share on successor slates | Talent panel |

Tier names follow the public series pages, verified 2026-11-06. Staff: **AI Explorer** (self-directed, Canvas) → **AI Catalyst** (tool deep-dive plus role-scenario session) → **AI Practitioner** (intermediate workshop plus role-aligned cohort), plus **Unit Training**. Leaders: **AI Ready Leaders** (e-learning whose modules include AI fluency and responsible AI leadership) → **AI Adaptive Leaders** → **AI Forward Strategies**. Prerequisites, badge rules and module or meeting counts are assumptions recorded in `contract.TIERS`. The synthetic calendar offers some tiers earlier than their real launch (AI Ready Leaders e-learning is publicly dated October 2026) so every panel has data. The public FY25 figure of 36 AI PD sessions is context only and is not used as a target.

## What the synthetic run shows (seed 20251006, as of 2026-10-31)

These numbers describe invented data. They show what the scorecard would surface, not anything about the University.

- **Reach.** 4,006 of 12,905 people (31%) registered for a badge tier, and 430 more attended Unit Training. 2,103 earned an entry badge, 616 an applied badge and 145 a top badge ("super AI users").
- **Behavior.** Paired BCI change at day 90 was +17.5 points (95% CI 16.5–18.5, n = 674). Applied use at day 90 was 47% of respondents. Day-90 response runs 40–50% of eligible completers, so these figures lean optimistic.
- **The DiD panel is the honest part.** The generator built in a true average effect of **+0.43** workdays per week at the January 2026 pulse. The naive pre/post for the early cohort reads **+0.85**, because it absorbs campus-wide growth. The DiD reads **+0.56** (CI 0.15–0.97); it still overstates because early adopters' use was already rising faster. The placebo check (+0.06, CI −0.29 to +0.41) **failed to detect** that built-in pre-trend: one short pre-period has little power. That is why the page labels the panel "descriptive, not causal" and recommends a lottery-based rollout of seats if SP&P ever needs a causal answer.
- **Proficiency.** Inter-rater weighted κ was about 0.38–0.45 across criteria in the synthetic rater model. That level means "recalibrate raters before scores carry weight". It is the kind of finding item #2 in the brief, the assessment instrument, exists to produce.
- **Self vs observed.** In this seed, facilitator-observed sophistication was slightly *above* self-ratings (gap −0.15). The page states the direction from the data and does not assume self-ratings run high.
- **Talent linkage.** Applied-badge holders had 11.9 internal applications per 100 person-years after the badge vs 10.4 for the *same people before* it, against 8.1 for non-registrants. Most of the gap to non-registrants is self-selection. Access varies 2.2× across role families (technical, trades and service lowest), so using badges as a screening criterion would carry that gap into hiring.
- **Privacy.** 69 values were suppressed. In the unit × role-family crosstab, 29 cells were suppressed as primary and 10 more as complementary. The two smallest units are "<10" on most measures.

## How real sources would plug in (approved machines only)

Nothing below should run in this repository. The intended deployment is the same code on an approved university machine. Raw extracts and `person_key` salts stay there, and only `scorecard.json` and the HTML built from it leave.

| Contract table | Real source | Extraction notes |
|---|---|---|
| `workforce_denominator` | EDW / Banner HR headcount at a fixed date | An aggregate query by unit, role family and leader flag. No roster needed. Role-family crosswalk from employee class, reviewed by HR |
| `registration`, `attendance` | AI PD registration system; session check-in or Zoom reports; Canvas module completions for AI Explorer and AI Ready Leaders | Hash UIN → `person_key` with a salt held on the machine. Unit and role family at event time come from the HR lookup on that machine |
| `badge` | Digital badge platform export | One row per issued badge; core and applied completion flags from the program team |
| `assessment_score` | Rubric scoring sheet from trained raters | Consented artifacts only; rater IDs pseudonymous; no model grading |
| `pulse_response` | Qualtrics: reaction, 30/60/90-day follow-ups, facilitator form, quarterly campus pulse | Embedded data carries unit, role family and track. Export numeric codes only, never open text, which belongs to the local-model text pipeline (brief item #8) |
| `use_case` | Joint Innovation in AI Team intake or registry | Add a time-study field so `validated_hours_per_month` exists |
| `tool_usage_unit_month` | Microsoft 365 admin center Copilot Chat usage; ChatGPT Edu workspace analytics; Illinois Chat admin logs | Aggregate to unit-month on the machine before export. Vendor reports are per user, so drop the user columns after aggregation |
| `mobility_event`, `ai_skill_demand` | Cornerstone internal applications; EDW job changes; succession slates; workforce-plan position flags | Needs HR legal and labor-relations sign-off first (HB 3773, civil-service and bargaining-unit rules) |

`metrics.py --data-dir <approved path>` refuses any extract that does not match the contract, and `audit()` refuses to write output that breaks a privacy rule. The minimum cell size (k = 10) should be agreed in writing with SP&P before the first real run (90-day plan, weeks 1–3).

## Why Snowflake, Databricks or LMS reporting do not provide this

- **Snowflake and Databricks** supply storage, compute, dashboards and LLM SQL assistants. The model on this page is not part of either platform: L0–L4 definitions, the behavior index, nested funnel rules, the staggered comparison with a placebo check, human-rater agreement, k-anonymity with complementary suppression, and a pre-publication audit. Neither platform enforces minimum cell sizes in AI answers (gaps G6 and G7 in the tool research). The code here can run on either platform's SQL engine because the logic is plain DuckDB SQL, but the measurement design has to be built in either case.
- **LMS and learning-platform reporting** (Canvas analytics, LinkedIn Learning or Coursera admin reports, HR-suite learning modules) reports enrolments, completions and minutes, which is L0 and part of L2. It has no 30/60/90-day behavior follow-up, no human-scored proficiency, no link to use cases, AI-tool telemetry or talent events, and no comparison group. Its exports are person-level, so small-cell suppression is left to the user.
- **Vendor AI-adoption dashboards** (Copilot and ChatGPT Edu admin analytics) count active accounts per tool. They do not know who was trained, so they cannot separate training effects from general growth, and they cannot de-duplicate across tools.

## Limitations

- Every parameter is invented (`synthesize.ASSUMPTIONS`). Funnel shapes match only two public anchors: about 1,380 first-wave and about 838 December registrants. Tier formats and badge rules are assumptions to confirm.
- The BCI is a development index. Its weights are equal and unvalidated. Item wording and anchors need cognitive testing and a pilot.
- Follow-up nonresponse is not corrected. Weighting or bounds should be added once real response patterns are known.
- The DiD rests on self-selected groups and has one pre-period of three months. It does not identify a causal effect, and the synthetic run shows it overstating the effect.
- Complementary suppression covers the one published crosstab. Differencing across overlapping slices and across successive releases is not yet controlled (`schema.md` §4).
- Talent-event rates are associations with Poisson-approximate CIs. "Before vs after" is within-person but not adjusted for time trends. Nothing in this view may feed decisions about individuals.
- The page's SVG text is small at phone width. Tables scroll inside their own containers; the page itself does not scroll sideways.
