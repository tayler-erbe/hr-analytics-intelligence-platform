# Rater calibration workflow

How human raters are trained, checked and kept consistent when they score AI-proficiency work samples against `rubric.yaml`. Every score comes from a trained person. Software (`reliability.py`, `study.py`) only measures agreement and drift.

Status: draft for the 3–6-week pilot in the opportunity brief (§6: "two human raters, agreement statistics, revisions"). The thresholds below are starting values; the first pilot should confirm or change them, and every change should be recorded with a rubric version bump.

## Roles

| Role | Who | Responsibilities |
|---|---|---|
| Scoring lead | One SP&P or CITL assessment staff member | Owns anchor papers, runs calibration, reviews the drift report each session, assigns adjudication |
| Raters | 4–8 staff who hold AI Practitioner themselves or completed rater training; at least two role families represented | Score work samples; take part in calibration and recalibration |
| Adjudicators | 1–2 experienced raters who are not in the operational pool for that session | Resolve discrepant scores |
| Expert panel | 5–8 people including role-family SMEs, an HR partner and a data-security/IT representative | Set master scores for anchor papers; run the modified-Angoff standard setting |

Raters never score a candidate they supervise, work beside or know personally. Candidate work samples carry only pseudonymous codes (for example `C014`). The scoring lead keeps the code key on an approved university system, separate from the scores.

## 1. Build the anchor set (before any scoring)

1. Collect 30–40 practice work samples written by volunteers or by the design team (no live candidates), spread across all 12 tasks and all four score levels.
2. Each panel member scores every sample independently. Discuss disagreements and agree a **master score** per dimension with a written rationale that cites the rubric anchor language.
3. Sort the samples:
   - **Benchmark papers** (about 8): clear, typical examples of each level, used to teach the scale.
   - **Range-finders** (about 8): samples at the 2/3 boundary and at the gate floors (D5 = 3, D6 = 3), used to teach the hard calls.
   - **Calibration set** (20): used for the qualifying test. This is the fully crossed set from which `study.py` computes ICC(2,1), ICC(2,k), Krippendorff's alpha and pairwise weighted kappa.
   - **Seeded anchors** (10 per scoring session): mixed blind into each rater's operational queue, used for drift checks.
4. Retire any sample on which the panel cannot reach a master score. Ambiguity in a sample usually means ambiguity in an anchor; log it as a rubric issue.

## 2. Rater training (about 3 hours)

1. **Construct (30 min).** What each dimension measures and what it does not. Example: D4 credits *checking*, not output quality. Cover the gates and auto-floor rules, the data-classification categories (Public / Internal / Sensitive, per the current campus standard) and the approved-tool classes.
2. **Benchmark walk-through (45 min).** Score the benchmark papers together, reading the anchor text aloud for each level.
3. **Range-finders (45 min).** Score independently, then compare. Focus on known traps:
   - Halo: a polished final output pulls up D4 and D8 without evidence.
   - Length bias: long prompt logs are not automatically better on D1 or D3.
   - Tool bias: the candidate's choice of an approved tool is not a reason to mark down.
   - Leniency on gates: "they probably would have checked" earns no credit. Score the evidence.
   - Construct-irrelevant writing quality: grammar and fluency are not scored. This matters for raters scoring candidates who use English as an additional language or who use assistive technology.
4. **Qualifying test (60 min).** The rater scores the 20-paper calibration set alone.

**Qualifying standard** (provisional):
- exact agreement with master scores ≥ 60% and within-one-point agreement ≥ 95%, across all dimension cells;
- mean signed deviation from master between −0.30 and +0.30 (`rater_drift` bias flag threshold);
- no gate-dimension (D5, D6) cell more than one point from master.

A rater who misses the standard retrains on the range-finders and retests on a different calibration subset. A rater who misses twice does not score operationally that cycle.

## 3. Operational scoring

- **Assignment.** Work samples are assigned to raters at random within the session. No rater scores more than about 40% of one role family's samples, so rater effects do not line up with role family.
- **Blinding.** Raters see the task, the work sample and the pseudonymous code only. They do not see role, unit, the other rater's scores or the badge consequence.
- **Double-scoring.** A random **20% of candidate sittings** are fully double-scored: both tasks, all dimensions, by two raters chosen independently. These cases feed the operational agreement estimates (Krippendorff's alpha with rotating raters, slot-based weighted kappa, decision consistency).
  - Sampling by sitting rather than by single artifact is deliberate: decision consistency needs a complete second scoring of the candidate.
- **Targeted second reads**, in addition to the random 20%:
  - every sitting whose total is within 1.0 point of a badge cut;
  - every sitting with an auto-floor (D5 or D6 forced to 1);
  - every sitting whose single read decides a gate (D5 or D6 exactly at a floor).

  These targeted reads protect individual decisions. Exclude them from agreement statistics, because they are not a random sample.
- **Seeded anchors.** Every rater scores the 10 session anchors blind, mixed into the queue.

## 4. Adjudication

Adjudication is triggered when any of these holds:
- two reads differ by more than 1 point on any dimension (`adjudicate_if_abs_diff_gt: 1`);
- two reads fall on opposite sides of a gate floor (D5 or D6);
- the two reads lead to different badge tiers.

The adjudicator scores the triggered dimensions blind to both earlier reads, with the anchor papers at hand. The adjudicated score replaces both reads for that dimension. When there is no trigger, the dimension score is the mean of the two reads. The adjudicator records which rubric language decided the case. If the same dimension is adjudicated repeatedly for the same task, the scoring lead takes it to the panel as a possible anchor or task-guide fix.

Candidates may ask for a review of a "Not yet" outcome. A fresh adjudicator re-scores the full sitting blind. The review can confirm or raise the outcome, never lower it.

## 5. Drift monitoring (every session)

After each session the scoring lead runs `python study.py` on the session export (from the scoring form CSV) and reads the rater section:

| Signal | Statistic | Action threshold (provisional) | Action |
|---|---|---|---|
| Drift | OLS slope of anchor bias across sessions (`rater_drift`) | \|slope\| ≥ 0.15 points/session | Recalibrate on range-finders before the next session; re-read that rater's sessions where the bias exceeded 0.30 |
| Static severity or leniency | Latest-session bias vs master | \|bias\| ≥ 0.30 | Individual feedback session with benchmark papers |
| Low agreement | Latest-session exact agreement with master | < 60% | Recalibrate; pause operational scoring if it repeats |
| Severity relative to peers | Mean deviation from other raters on shared artifacts (`rater_severity`) | \|mean dev\| ≥ 0.30 with 2 SE excluding 0 | Discuss at the next calibration meeting |
| Dimension agreement | Krippendorff's alpha (ordinal) per dimension on double reads | < 0.67 (tentative-conclusions floor) | Review the anchor language and task guides for that dimension |

The synthetic study shows why this table matters. With one severe rater, one lenient rater and one drifting rater out of six, two independent scorings put a candidate in the same badge tier only about 55% of the time. Removing severity and drift alone raises that to about 74%. These are synthetic figures; the pilot must produce its own.

Do not correct scores statistically for rater severity (for example with a many-facet Rasch model) until the pilot has enough double reads to estimate rater parameters stably and the panel agrees to the adjustment. Recalibrating raters is preferred to adjusting scores.

## 6. Standard setting (modified Angoff)

1. The panel writes a one-paragraph description of the **borderline** candidate for each tier: just-qualified Explorer, just-qualified Catalyst, just-qualified Practitioner.
2. **Round 1.** Each panelist estimates, for each dimension, the mean score (1.0–4.0, to one decimal) that a borderline candidate would earn. They do this alone.
3. **Discussion.** Show the spread of panelist estimates per dimension, discuss the outliers, and show **impact data**: the share of pilot candidates who would reach each cut.
4. **Round 2.** Panelists revise their estimates alone.
5. `reliability.angoff` gives the cut score (mean of panelist totals), its SE (SD of totals / √n) and the pass rate at cut ± 2 SE. The recommended cut is rounded to the nearest 0.5. The gate floors in `rubric.yaml` are set by policy and are not changed by the Angoff procedure.
6. Record the panel composition, both rounds, the impact data shown and the final decision in the rubric change log.

## 7. Session checklist

- [ ] Code key stored separately from scores, on an approved system
- [ ] Anchor papers seeded in every rater's queue
- [ ] Random 20% of sittings flagged for double-scoring before scoring starts
- [ ] Targeted second reads queued (near-cut, auto-floor, gate-deciding)
- [ ] Adjudications complete before any badge is issued
- [ ] Drift report reviewed and actions logged
- [ ] Program-level aggregates exported with cells of n < 10 suppressed
- [ ] Rubric issues logged for the next panel meeting
