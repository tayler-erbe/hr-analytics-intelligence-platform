# AI reskilling and role evolution prototype

This prototype supports Strategic Workforce Planning, Talent Mobility, Succession Planning and AI Professional Development and Reskilling at Illinois HR. It answers role-level questions: which tasks in a job family already show observed AI use, which skills hold up, which adjacent roles a class could move into and what the gap would be, and what AI-literacy behaviour each role should be trained for.

It uses **public data only**. It never reads, stores or scores an individual employee. The grain is a role: an O*NET-SOC occupation or a SUCSS civil-service class record. That is deliberate, because Illinois HB 3773 (Public Act 103-0804) makes AI that influences hiring, promotion, discipline, discharge or terms of employment a civil-rights exposure. See [research/HR_USE_CASES_AND_GUARDRAILS.md](../research/HR_USE_CASES_AND_GUARDRAILS.md) §3.

| File | What it is |
|---|---|
| `build_pathways.py` | Builds every role profile from `data/lake/contract` and `data/lake/silver` (protocol `reskilling_pathways_v1`) |
| `competency_framework.yaml` | The AI-literacy rubric (Aware / Practitioner / Integrator / Leader), with behavioural indicators, anchor work activities and target rules |
| `render_explorer.py` | Writes the offline explorer to `../output/reskilling/role_evolution_reskilling.html` (one file, about 3.8 MB, no network calls) |
| `tests/test_pathways.py` | Checks determinism, absence of person-level fields, provenance on every recommendation, and caveat flags |
| `artifacts/` | Generated Parquet tables, `pathways.json` and `manifest.json` (input and output SHA-256) |

```bash
cd platform-evaluation
python reskilling/build_pathways.py          # about 5 s
python reskilling/render_explorer.py
python -m unittest discover -s reskilling/tests -v
```

## Scope

- **173 O*NET occupations** in nine families: admin/IT/HR/finance/facilities management; HR and training; finance and accounting; business operations; IT and data; library and archives; student services; office and administrative support; facilities and building services. The SOC prefixes are listed in `FAMILIES` in `build_pathways.py`.
- **883 SUCSS catalog records.** Each is linked through its rank-1 `title_lexical_baseline_v1` candidate, which has `review_status = unreviewed`. Class 1164 has two records, and both are kept.
- **433 occupation profiles** in total: the union of the two sets above.

## Method

Every threshold sits in `PROTOCOL` in `build_pathways.py` and was fixed before results were inspected. Changing one requires a new labelled version (`reskilling_pathways_v2`). Do not edit v1 in place.

### (a) Task portfolio

Each O*NET 31.0 task is matched to the Anthropic Economic Index on lower-cased task text:

- **Primary metric:** `task_penetration` from the `labor_market_impacts` release. A task is in the **high observed-usage** band if penetration ≥ 0.5, and **low** otherwise.
- **No match:** the task is marked `no_record`. This applies to 65 of 8,449 tasks.
- **Secondary evidence:** `task_pct_v2` from `release_2025_03_27` (share of sampled conversations, in percent) is shown next to the task but does not set the band.
- **Weighting:** shares are weighted by O*NET task importance (IM).

Every task row cites the metric and release it came from.

### (b) Durable skills and augmentable activities

O*NET does not rate skills per task, so the link to tasks is indirect: skill → work activity (O*NET's essential and transferable skills-to-work-activities tables) → detailed work activity → task.

- **Durable skill:** importance ≥ 3.5, and at most 25% of linked tasks (importance-weighted) are in the high band.
- **Augmentable activity:** a work activity with importance ≥ 3.0 where at least 50% of linked tasks are in the high band. Activities between these two thresholds are shown as "mixed".

### (c) Adjacent roles and skill gaps

Adjacent roles are the first five O*NET Related Occupations by index that have ratings. The comparison uses the importance (IM) and level (LV) vectors over 68 elements: essential skills, transferable skills and knowledge.

- **Element gap:** `weighted_gap = (target IM / 5) × (target LV − source LV)`, for differences of at least 0.25 level points. The page shows the top five.
- **Gap index:** `Σ (target IM/5) × max(0, ΔLV) / Σ (target IM/5)`, the average importance-weighted shortfall.
- **Job-zone step:** target job zone minus source job zone.
- **Also shown:**
  - cosine similarity of the two importance vectors;
  - "carry-over" strengths, meaning elements of importance ≥ 3.5 where the source level is already at least the target level;
  - O*NET hot-technology categories used in the target role but not listed for the source role;
  - the target role's most common required education.

### (d) Learning themes

A learning theme is the name of an O*NET element, ranked by its positive weighted gap summed across the adjacent roles and divided by the number of those roles. The page lists which adjacent roles need each theme. No course, vendor or provider is named, and none was invented.

### (e) AI-literacy competency profile

See `competency_framework.yaml`. The rubric has four levels, each with behavioural indicators tied to O*NET work activities such as Processing Information, Analyzing Data or Information, and Documenting/Recording Information.

The role target comes from ordered rules over:

- `info_index`: the mean importance of six information-work activities;
- `lead_index`: the mean importance of three leadership activities;
- the importance of Analyzing Data or Information;
- the O*NET job zone.

Each anchor activity also gets its own target level from its importance. The rules are evaluated by a small parser in `eval_rule`, not by `eval()`. These targets are for designing training for a role. They are not ratings of people.

### Institution view

- **O*NET families:** for each family, the median and interquartile range of the high-band task share, the distribution of competency targets, and the most common durable skills, augmentable activities and learning themes.
- **IPEDS context:** each family is shown next to UIUC Fall 2023 IPEDS headcount for the closest IPEDS occupation category (unitid 145637, S2023_OC). This is context only. IPEDS categories are broader than the families, and headcount is never allocated to roles.
- **SUCSS lines:** the same summary is repeated for each SUCSS occupational line, through the unreviewed links.
- **Labour-market context:** a statewide QWI strip (Illinois, NAICS 6113, all ownerships) shows the latest four fully published quarters of employment, hires and separations.

### Provenance and determinism

- **Parquet:** every row carries a full `provenance` JSON object: the method version, each `source_id` + `source_vintage` (and metric where relevant), and the rule applied.
- **JSON:** `pathways.json` interns identical provenance objects into `meta.provenance_registry` and refers to them by id, which keeps the file at about 10 MB instead of 20 MB.
- **Determinism:** outputs contain no wall-clock time, and two builds from the same inputs are byte-identical (tested). `manifest.json` records the SHA-256 of the 20 input files and of every output.

## What the first run shows

These are observations about public occupation data, not about University staff:

- 884 of 8,449 tasks (10.5%) are in the high band.
- Median importance-weighted high-band share by family:
  - IT and data: 32%
  - HR and training: 23%
  - Finance: 19%
  - Office and administrative support: 12%
  - Business operations: 10%
  - Facilities: 0%
- AI-literacy targets across all 1,056 roles: 77 Aware, 375 Practitioner, 458 Integrator, 94 Leader, and 52 not rated because O*NET has no work-activity ratings for the occupation.

## Known weaknesses, stated plainly

1. **The penetration metric is close to binary.** About 92% of all AEI task rows have penetration 0, and the median of the non-zero values is 0.91. In practice the band means "this task text appears in observed Claude usage". It does not grade intensity.
2. **Lexical SUCSS links are often wrong.** 623 of 883 rank-1 links have title similarity below 0.35 and carry a `weak_lexical_match` display flag. Examples:
   - Assistant Chief Accountant → Chief Executives
   - Human Resource Assistant → Human Resources Managers
   - Office Support Specialist → Computer User Support Specialists

   SUCSS rows are only as good as these links. They must be reviewed before anyone acts on them.
3. **Skill-to-task linkage is indirect.** It produces some odd results. For example, "Assisting and Caring for Others" appears as augmentable for Secretaries and Administrative Assistants because some of its detailed work activities touch high-usage tasks.
4. **One adjacent role can dominate the themes.** A single distant adjacent role can lead the theme ranking. For Human Resources Managers, "Science" ranks first because of the gap to Industrial-Organizational Psychologists. The page shows the "needed for" list so a reviewer can see why.
5. **Ratings are national.** O*NET ratings and job zones describe each occupation nationally, not the University's positions.
6. **The rubric and thresholds are drafts.** Neither has been validated by HR subject-matter experts.

## How real inputs would plug in (approved University machines only)

None of the following may enter this repository, a public AI service or a vendor-hosted model. Processing stays on approved University systems with local or on-prem inference. Results are published only as aggregates, with cells of n < 10 suppressed.

| Input | Where it plugs in | Notes |
|---|---|---|
| **SUCSS class specifications and University position descriptions** | Replace the lexical O*NET link with an evidence-linked mapping: duties text → O*NET tasks, with source spans, abstention and an SME review queue. Then build each role's task portfolio from the reviewed tasks, not the national list. | Mapping review is a human decision. The model only proposes. |
| **Illinois Learning Center / LinkedIn Learning completions** | Aggregate to the role or unit level, never per person, and map course topics to O*NET elements, so a learning theme can show "share of role incumbents who completed related content". | Map course catalog topics once, with SME sign-off. Suppress small cells. |
| **Competency self-assessments** | Collect against `competency_framework.yaml` levels and compare the **distribution** for a role with its target level to size training demand. | Voluntary, with notice, never linked to performance or pay, and reported only as suppressed aggregates. Labor Relations reviews first (IELRA). |
| **EDW appointments and headcount** | Weight institution-view summaries by actual headcount per class, using effective-dated appointment grain. | Counts by class only. No names or identifiers leave HR. |

The interface stays the same: each of these feeds `role_profile` at role grain. The code paths that compute role-level evidence do not need person-level columns, and the tests block such columns.

## Evaluation plan with HR SMEs

The steps below should be pre-registered before results are looked at. No model grades another model.

1. **Mapping review.** Draw a stratified sample of SUCSS classes (by occupational line and similarity decile). Two SMEs label the correct O*NET occupation independently. Measure top-1 and top-3 agreement of the lexical baseline, then inter-rater agreement (Cohen's κ). Adjudicate disagreements, and record abstentions and errors without dropping them.
2. **Task-band face validity.** For 20 high-volume classes, SMEs mark each task as "AI already used here", "could be assisted" or "not suitable", blind to the band. Report a confusion matrix against the band, not a single accuracy figure.
3. **Durable and augmentable review.** SMEs rate each listed skill or activity as agree, disagree or unsure. Report the agreement rate per family and collect the disagreements as cases for protocol v2.
4. **Adjacent-role usefulness.** Talent Mobility staff rank the five adjacent roles for 30 classes against real historic mobility paths. Those paths come from aggregated EDW transitions on approved machines and are summarised only at class-to-class level with n ≥ 10. Report rank correlation.
5. **Rubric validation.** SMEs check each behavioural indicator for clarity and observability, and check that the role targets are sensible for 40 classes. Changes produce `ai_literacy_rubric_v2`.
6. **Governance checkpoints.** Counsel reviews against HB 3773. Labor Relations reviews before any self-assessment. Add an entry to the AI tool registry, and give notice to employees if anything moves beyond aggregate planning.

## Why Snowflake or Databricks do not provide this out of the box

Both platforms supply compute, storage and governed SQL. Snowflake adds AI functions such as `AI_CLASSIFY`, `AI_EXTRACT` and `AI_COMPLETE`, Cortex Analyst and agents. Databricks adds `ai_classify`, `ai_extract`, Genie, Agent Bricks and MLflow. See [research/README.md](../research/README.md).

What neither ships:

- **The ontology.** There is no SUCSS class model, no class → O*NET task crosswalk, and no skill → work activity → task linkage logic. These are domain modelling, and they come from O*NET's own tables plus University review.
- **The evidence model.** Neither platform tracks per-task AI-usage evidence with its metric and release cited. Neither has rules for what counts as "durable" or "augmentable", or provenance attached to every recommendation. A platform AI function returns a label without an evidence trail.
- **The review workflow.** Neither provides an SME queue for unreviewed mappings, abstention, versioned protocols, or deterministic rebuilds with input hashes.
- **The guardrails.** Neither enforces role-level grain, suppressed aggregates or HB 3773-aware caveats. Snowflake inference may also cross regions by default, which matters if restricted HR text is ever involved.

The code here is plain Python, DuckDB and Parquet over the lake contract, so the same logic can run as SQL and UDFs on either platform. The modelling and review design are the portable, valuable part, and they have to be built regardless of the platform.
