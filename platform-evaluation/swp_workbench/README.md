# Strategic Workforce Planning workbench (data layer + offline page)

IHR's [Strategic Workforce Planning Services](https://humanresources.illinois.edu/strategic-workforce-planning/) page (published 2026-10-27) offers Succession Planning, Knowledge Stewardship, Bench Strength Analysis, Capability Planning and Upskilling & Reskilling. It does this through nine conversation-starter worksheets. Their download links are still `#` (live fetch, 2026-11-06), and no data sits behind them. This folder builds that missing layer: unit-level, suppressed, evidence-backed numbers for each of the nine tools, and an offline page where a unit fills in the discussion and exports its notes.

**Status: prototype on synthetic data.** The workforce is the seeded synthetic workforce from `../workforce_sim`: 12,905 people whose campus totals match UIUC's public Fall 2023 IPEDS headcount by construction. It has been split into 15 **synthetic unit archetypes**. The role evidence is public (O*NET 31.0 and the Anthropic Economic Index, via `../reskilling`). No real employee data is used, no individual appears in any output, and nothing scores or ranks a person.

Open `../output/swp_workbench/swp_workbench.html`. It is a single 0.5 MB file with no network calls, vanilla JS, light and dark themes, and it works at 390 px.

## Run

From `platform-evaluation/` (Python 3.13, duckdb, pyarrow, numpy). The lake contract and `reskilling/artifacts` must exist. The workforce_sim synthetic tables are used if present and their manifest hashes verify; otherwise they are regenerated in memory with workforce_sim's own generator into `swp_workbench/data/_synthetic_cache/`. `../workforce_sim` is never written to.

```bash
python swp_workbench/build_workbench.py      # ~1 s  -> swp_workbench/data/workbench.json + manifest.json
python swp_workbench/render_workbench.py     #       -> output/swp_workbench/swp_workbench.html
python -m unittest discover -s swp_workbench/tests -v       # 27 tests, ~6 s
node swp_workbench/screenshot.js "$PWD/output/swp_workbench/swp_workbench.html" "$PWD/output/swp_workbench/screenshots"
```

| File | Role |
|---|---|
| `protocol.py` | Every threshold, crosswalk, unit archetype, SURS rule and assumption (`swp_workbench_v1`). Fixed before results were read; changes need a v2 |
| `disclosure.py` | k = 10 suppression: D1 small counts, D2 rates, D3 continuous shares, D4 complementary suppression with linked subtotals and public totals, D5 sums over published cells only, D6 audit for identifiers and person attributes |
| `evidence.py` | Role-family evidence: representative O*NET occupations, skill core-shares, observed-AI-usage shares, the ERP task proxy, adjacent families, learning themes and competency targets |
| `build_workbench.py` | Reads the as-of snapshot (same bitemporal SQL as workforce_sim), assigns synthetic units, computes everything in memory, then publishes only suppressed aggregates. It asserts reconciliation and the audit before writing |
| `render_workbench.py` | Writes the page. The nine tools appear in the page's order and wording |
| `worksheet_map.md` | Each tool → questions, data, grain-correct metric definitions, output |
| `tests/test_swp_workbench.py` | Suppression, absence of person-level output, reconciliation, reproducibility |
| `screenshot.js` | Playwright check: console errors, outbound requests, overflow at 390 px, export round-trip, screenshots |

## How it would sit under IHR's service

The SWP team's model is facilitated conversations with Colleges and MAUs that can start from any tool. The workbench does not replace that. It makes sure each conversation starts with the unit's own numbers rather than a blank worksheet.

1. **Intake.** A College or MAU contacts `ihr-swp@illinois.edu` with a starting point (a key vacancy, a new priority, the ERP, AI tools, critical knowledge). The SWP consultant picks the matching tools.
2. **Prepare.** HR analytics staff run the build on an approved machine for that unit. The consultant receives the pre-filled page or a printout. Suppressed cells stay suppressed; small units see `<10` and are pointed to the campus view or a combined unit.
3. **Conversation.** Unit leaders and their HR contact work through the tools. The evidence sets the frame; the discussion fields capture judgment. For example: which roles do we *confirm* as critical, and where does the data disagree with our experience?
4. **Export and plan.** Notes export as JSON or CSV with the protocol version and evidence hash. The SWP team turns them into the unit's plan (succession cover, knowledge capture, learning, ERP backfill). A person decides every action.
5. **Repeat.** The same protocol rerun on a later snapshot shows movement without changing definitions.

Ownership: the SWP team owns the conversation and the critical-role confirmations. HR Analytics / HRAIS own the build, the definitions and the disclosure review. Units own their notes.

## What the synthetic run shows (campus view; describes the synthetic model, not UIUC)

- **Reconciliation:** 12,905 distinct people = sum of the 15 unit headcounts = sum of the SURS band cells = sum of the service-band cells = IPEDS Fall 2023. There are 13,101 authorized primary lines, 1,548 of them critical (1,519 filled), 12,308.5 primary FTE and 155 secondary appointments. Filled lines (12,905 + 155) equal workforce_sim's own count of 13,060.
- **Bench:** 0.91 ready-now candidates per critical line within units (MGT 1.11; SAA, CSL, HLT 0.71). 1.9% of critical lines are vacant. Faculty are excluded.
- **Knowledge:** median service 4.9 years. People with 20+ years hold 27.5% of service-years; the longest-serving 10% hold 33.5%. 44.6% of service-years sit with people SURS-eligible now or within 5 years. There are 46 single-incumbent roles and 34 coverage-thin senior roles.
- **Tier 1 vs Tier 2:** 19.2% of headcount is eligible now or within 5 years under each person's (proxied) tier. With the same people, that would be 34.9% if everyone were under Tier 1 rules and 13.9% under Tier 2 rules. As Tier 2 grows, the near-term eligibility wave shrinks and moves later.
- **ERP lens:** MGT (16.4%) and BFO (15.3%) cross the 15% HR/finance task-share threshold, with 2,296 people. OAS is at 12.3%, **just under the threshold**, so its classification is fragile and should be decided by Banner security-class data, not this proxy.
- **AI lens:** CES (24%) and SAA (15%) are high-usage families, with 2,363 people. SAA rests on only 3 occupations.
- **Capability, default target:** moving 118.6 FTE out of OAS into CES/BFO raises capacity most for Critical Thinking (+97 FTE), Complex Problem Solving (+67) and Judgment and Decision Making (+65). This is a consequence of the chosen target, not a finding about need.
- **Suppression:** 380 primary small cells force 87 complementary cells across the 12 published tables. Unit 15 (15 people) is almost entirely suppressed, by design.

## Disclosure control and its limits

Counts of people of 1–9 never appear. Tables published with margins get complementary suppression. The safety check computes everything an attacker can derive by exact subtraction: published entries, then repeatedly any additive line with one unknown. It requires that no suppressed small cell becomes derivable, and that the still-unknown cells in any line with a known total sum to 0 or at least 10. Declared linkages are part of the check:

- the near-retirement columns of the SURS band table, whose total the family table publishes;
- the critical columns of the role table, whose total the readiness check publishes;
- unit headcount, which four tables partition;
- the public IPEDS campus family totals, which are never suppressed.

A backward pass removes greedy over-suppression; it cut secondary cells from 610 to 87. Two attacks are not covered. One is a full linear-programming (interval) attack across all tables; a production release should also pass a formal tool such as sdcTable or τ-ARGUS. The other is differencing between different breakdowns that are not declared as linked, for example role-level C3 rates against family-level eligibility (mitigated by rounding C3 to 5 points).

**Deliberate exception:** criterion C2 (coverage-thin) necessarily says a role has one or two incumbents. That is a staffing-structure fact needed for continuity planning. No attribute of those people (age, eligibility, tenure, readiness) is shown. Governance should sign off on this exception explicitly.

## Plugging in real EDW, Banner and JDX data (approved machines only)

Nothing below may enter this repository, a public AI service or a vendor-hosted model. Person-level extracts, intermediate tables and logs stay on the approved machine. Only `workbench.json` after the audit leaves, and only after a human disclosure review.

| Workbench input | Synthetic today | Real source | Notes |
|---|---|---|---|
| Person (age, service start) | `person.parquet` | EDW `T_PERS_HIST` (age band from birth date, computed and dropped), original/continuous service dates | Keep only the age and service values needed for bands; never names or UINs |
| Appointment (FTE, start, primary/secondary) | `appointment.parquet` | EDW `T_EMPEE_HIST`, `V_EMPEE_HIST_1`, `T_JOB_DETL_HIST` (`*_EFF_DT`/`*_EXP_DT`) | Use EDW load timestamps as `recorded_at`; the as-of SQL is unchanged |
| Position line, vacancy | `position.parquet` | `T_JOB_DETL_HIST.POSN_NBR` plus the position-control or budget source | Vacant lines need position control; job history shows filled lines only |
| **Unit** | hash-assigned archetype | Banner organization hierarchy (COAS/org codes rolled up to College/MAU) | Replace `assign_unit()`; keep units mutually exclusive by primary appointment |
| Family / level / role | IPEDS family × synthetic level | Banner employee class + job code, SUCSS class, JDX position and career-architecture level | Role grain becomes job class × unit, which makes C2 and single-incumbent counts meaningful |
| Critical flag | illustrative rule | Units' confirmed critical-role list from the Bench Strength conversation | Store each confirmation with who confirmed it and when |
| SURS tier and service credit | proxy from service start, assumed participation | Benefits feed: SURS tier, plan (Traditional, Portable, RSP), service credit incl. reciprocal and purchased service | Removes the four SURS assumptions; re-verify the rules on surs.org |
| Time in level / readiness | appointment start | Effective-dated job and level history; promotion records | Readiness stays a pool size. Any individual readiness judgment is a supervisor's, outside this tool |
| ERP lens | O*NET keyword proxy | Banner security classes and HRFE role assignments, counted by unit and family | Aggregate counts only; AITS supplies them |
| Task/skill evidence | national O*NET + AEI | JDX position descriptions → O*NET tasks on **local** models with evidence spans and an SME review queue (see `../reskilling/README.md`) | Reviewed mappings only; SUCSS links stay "unreviewed" until an analyst confirms them |
| Learning | competency targets | AI PD Series badges and LinkedIn Learning completions, aggregated by unit and family | Report completions as distributions, not per person |

Steps: point `synthetic_dir()` and `load_snapshot()` at the EDW-derived Parquet with the same columns. Replace `assign_unit()` with the org hierarchy. Rerun the tests: reconciliation should now compare with the EDW snapshot and IPEDS after scope differences. Then do the disclosure review and publish.

## Governance

- **Illinois HB 3773 (Public Act 103-0804, effective 2026-01-01)** amends the Illinois Human Rights Act. An employer may not use AI in recruitment, hiring, promotion, discipline, discharge or terms of employment in a way that has a discriminatory effect, and must give notice when AI is used for those purposes. The workbench is built so that it is not such a use: all outputs are unit or role-family aggregates, the readiness pool is a count, and nothing feeds a decision about a person. Any move toward individual-level use (named succession slates, readiness ratings, talent-marketplace matching) needs counsel review, notice, and a separate approval.
- **No individual scoring.** No departure-risk, readiness or "AI replaceability" score exists anywhere in the code. Tests fail if person identifiers, person attributes or record-shaped lists appear in the outputs.
- **A human decides.** The page frames the evidence as discussion prompts ("look more closely", "confirm or drop this critical role"). The default critical rule and the default capability target are explicitly provisional, and units' confirmations are recorded as their own.
- **Collective bargaining and civil service.** Pathway information is role-family level and does not alter SUCSS class rules or bargaining-unit terms. Labor & Employee Relations reviews before any learning self-assessment is collected.
- **Equity review.** Before real use, run the bench and eligibility aggregates by protected group on the approved machine, inside a governed equity audit. Do not publish the results without suppression.
- **Data minimization.** Only the fields in the table above. Notes are unit-level; the page warns when a note looks like an email, UIN or record ID.

## Why Snowflake, Databricks, Workday or Visier don't provide this out of the box

- **Snowflake and Databricks** supply storage, governed SQL, AI functions and dashboards, and either could run this code unchanged (DuckDB SQL plus Python). They do not ship:
  - the content: the nine-worksheet structure;
  - SURS Tier 1/2 eligibility rules;
  - a Banner/HRFE-aware ERP lens;
  - an IPEDS-family ↔ O*NET ↔ observed-AI-usage bridge;
  - bench definitions tied to position lines;
  - complementary small-cell suppression with linked subtotals. Row access policies and masking hide rows; they do not prevent recovering a suppressed cell by subtraction.
- **Workday** (Succession, Skills Cloud, Talent Marketplace, Adaptive Planning) works when Workday is the HCM and its talent-review data is populated. UIUC runs Banner, the ERP replacement has no selected vendor yet, and these modules center on individual talent profiles, which is the opposite of the aggregate-only posture HB 3773 makes prudent here. It also has no SURS or SUCSS model.
- **Visier** offers prebuilt HR metrics and planning on a vendor cloud at roughly $100k a year. It would need the Banner history loaded, and it does not provide SURS tier logic, the IHR worksheets, the O*NET/AEI task evidence or this repository's reviewed-mapping workflow.
- **What transfers:** the protocol, the definitions, the disclosure rules and the tests are plain Python and SQL over Parquet. They move to whichever platform and ERP the University chooses, and they double as a specification for the ERP data conversion: effective dating, the grain of person, appointment and position, and service dates.

## Limitations (stated plainly)

1. **Units are synthetic.** workforce_sim has no department dimension. Units come from hashing position IDs with assumed family weights, so unit differences reflect the weights and random assignment, not real units.
2. **Levels, critical flags, tenure and time in level are workforce_sim assumptions**, not calibrated. Bench numbers mostly echo the synthetic level mix and time-in-level distribution.
3. **The readiness proxy is weak.** Time in level is not readiness, and readiness is a human judgment.
4. **The ERP lens is a keyword proxy** on national O*NET task text. Families near the 15% threshold (OAS) are fragile.
5. **Family evidence weights occupations equally** and includes unreviewed SUCSS lexical links (similarity ≥ 0.35). Some, such as "Gambling Cage Workers" in OAS, are plainly not University work. Faculty have no evidence. SAA rests on 3 occupations.
6. **SURS rules were not verified on surs.org** (blocked from this sandbox) and rest on stated assumptions about participation, service credit and tier.
7. **Observed AI usage is not displacement.** AEI penetration is close to binary (see `../reskilling/README.md`).
8. **The IHR worksheets' contents are unknown.** The working sub-questions in `worksheet_map.md` are inferred and should be replaced with IHR's wording once the files are published.
9. **Disclosure control is heuristic** (see above). A formal tool should audit a real release.
