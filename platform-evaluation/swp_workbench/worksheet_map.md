# Worksheet map: IHR's nine conversation-starter tools → questions, data, metrics, outputs

Source: [IHR Strategic Workforce Planning Services](https://humanresources.illinois.edu/strategic-workforce-planning/), published 2026-10-27 and modified 2026-11-04. The live page was read through the proxy on 2026-11-06. All nine "Download …" links point to `#`, so **the worksheets' own contents are not public**. Below, each tool's headline question is quoted from the page. The working sub-questions are inferred from that question, the five service descriptions and the page's three perspectives (Position, Person, Future). Swap in IHR's wording when the files are published.

Data is the synthetic workforce (`workforce_sim`, 12,905 people as of 2023-11-01 with knowledge cutoff 2023-11-15) assigned to 15 synthetic units, plus public O*NET/AEI evidence carried through `reskilling/`. JSON paths are relative to `data/workbench.json` → `by_unit.<U01..U15|ALL>`.

## Grain rules (apply to every metric)

| Term | Definition |
|---|---|
| **Person** | A distinct synthetic `person_id` with an effective primary appointment at the snapshot (latest revision recorded on or before the cutoff). Headcount counts people, never appointments or positions |
| **Unit** | The unit of the person's primary position line. Units partition headcount exactly. A secondary appointment never adds a person; secondary appointments are counted separately |
| **Line** | An authorized primary position line effective at the snapshot. Filled = it has an effective appointment |
| **Role** | Unit × family × level × FT/PT over lines. The synthetic data has no job class; real data would use Banner job class / JDX position |
| **FTE** | Sum of primary-appointment FTE (PT = 0.5 in the synthetic data) |
| **Service** | Snapshot date minus `service_start`, in years |
| **Time in level** | Snapshot date minus the start of the current primary appointment (the level or rank start) |
| **Suppression** | Counts of people of 1–9 are shown as `<10`. Tables get complementary suppression, with linked subtotals and public totals declared. A rate needs n ≥ 10 and a numerator of 0 or ≥ 10. Derived sums use published cells only (`disclosure.py` D1–D6) |

## 1. Strategic Context & Future Direction (Future)

> "What priorities and changes may shape our future workforce needs?"

| | |
|---|---|
| Working questions | What is the unit's current shape (size, FT/PT, role-family mix, open lines)? How does that compare with campus? Which of the five named starting points apply (key vacancy, new priority, ERP, AI tools, critical knowledge)? |
| Data | Synthetic `person`/`appointment`/`position` as-of snapshot. Public IPEDS S2023_OC family totals (campus only) |
| Metrics | `headcount_n` = distinct people. `ft_n`/`pt_n` by line FT/PT. `family_headcount_n[f]`. Unit share = family ÷ unit headcount, shown only where the cell is published. `family_fte[f]`, published only where the headcount cell is published. `authorized_primary_lines`. `vacant_primary_lines` = authorized − filled, published only with the headcount. `secondary_appointments_n` |
| Output | `profile`. Starting-point checkboxes and three discussion fields |

## 2. Future Work Reflection (Position) — includes the **AI-tool lens**

> "How might the work itself change over the next few years?"

| | |
|---|---|
| Working questions | Which tasks in our role families already show observed AI use? Where does human judgment remain essential? Which work activities could be augmented? |
| Data | `reskilling/role_profile` (`high_share_w`), `role_task_split` (AEI band per task), `role_skill_durability`, `role_activity_augmentation`. Each family is represented by its O*NET occupations (`protocol.FAMILY_SOC_PREFIXES`; curated reskilling roles plus SUCSS rank-1 links with title similarity ≥ 0.35, equal weights) |
| Metrics | Family `median_high_share_w` = median across representative occupations of the importance-weighted share of O*NET tasks in AEI's high observed-usage band. A family is high-usage at a median ≥ 0.15. `high_ai_headcount_published` = Σ published headcount cells of high-usage families, with the count of suppressed cells left out. Top high-band tasks are ranked by O*NET importance. Durable skills and augmentable activities are counted by occupations |
| Output | `ai`, `families.<f>.top_high_usage_tasks / top_durable_skills / top_augmentable_activities` |
| Caveat | Observed usage is evidence about tasks, not a forecast of job loss. Faculty have no evidence (out of reskilling's scope) |

## 3. Future Capability Discovery Exercise (Position) — **capability gaps**

> "What will our team need to be able to do well to meet future priorities?"

| | |
|---|---|
| Working questions | What skills does our current role mix supply? What would a target mix need? Where is the gap? What AI-literacy levels does the mix imply? |
| Data | O*NET 31.0 skills (35 essential + transferable; IM and LV) for the representative occupations. Reskilling `competency_target`. Published family FTE |
| Metrics | `core_share[f][s]` = share of family f's rated occupations with importance ≥ 3.5 for skill s. Skill capacity = Σ_f FTE_f × core_share[f][s] ("FTE in roles where the skill is core"). Gap = target − current. The **default target** is the workforce_sim reskilling lever: 10% of FT OAS level 1–2 FTE moves into level-1 lines, half CES and half BFO, applied only where that source count is published. AI-literacy demand = Σ_f FTE_f × share of the family's occupations at each target level. Families with suppressed headcount or no evidence are excluded and listed |
| Output | `capability`. The page lets the unit edit the target FTE and recomputes gaps in the browser from published numbers only |

## 4. Workforce Readiness Quick Check (all perspectives)

> "Where do we feel prepared, and where should we look more closely?"

| | |
|---|---|
| Working questions | Compared with campus, where are we thin: open critical lines, bench cover, near-term retirement eligibility, concentrated service, ERP-heavy work, AI-exposed work? |
| Metrics | `critical_vacancy_share` = (critical lines − critical filled) ÷ critical lines. Critical filled is a protected subtotal of the role table. `ready_now_per_critical_line` = unit ready-now margin ÷ critical lines. `near_retirement_share_of_headcount` = eligible now or ≤ 5 yrs ÷ headcount (D2). `long_service_share_of_service_years`. ERP-heavy and high-AI headcount shares are published only when every contributing cell is published. A "look more closely" prompt appears when the unit is ≥ 25% worse than campus |
| Output | `readiness`. Not a score; units are not ranked |

## 5. Bench Strength Worksheet (Person) — **critical-role inventory + bench strength**

> "How broadly is important work covered, and where could organizational continuity be vulnerable?"

| | |
|---|---|
| Working questions | Which roles are critical, and why? How deep is the ready-now and ready-later pool for each critical role family, within the unit and across campus? |
| Critical-role criteria | **C1** the role holds lines flagged critical by workforce_sim's illustrative rule (FT level 4 in any staff family; FT level 3 in CES and HLT). **C2** coverage-thin: level ≥ 3 with 1–2 filled lines. **C3** retirement exposure: ≥ 30% of incumbents SURS-eligible now or within 5 years, assessed only with ≥ 10 incumbents, with the rate rounded to 5 points |
| Metrics | Per role: authorized lines, critical lines (positions), `filled_n` (from a units × roles table with complementary suppression and campus margins), vacant lines (only where filled is published). Per critical family: **ready now** = distinct FT incumbents in the same unit and family at one level below a critical level, with ≥ 8 quarters in level and not SURS-eligible now. **Ready later** = one level below with < 8 quarters, or two levels below with ≥ 8 quarters. `ready_now_per_critical_line`; `lines_without_ready_now_cover` = max(lines − ready now, 0). Campus view adds the any-unit pool |
| Output | `critical_roles`, `bench`. Pools are counts, never lists or rankings. Faculty are excluded (the critical rule excludes them) |

## 6. Knowledge Stewardship Planning Tool (Position) — **knowledge-stewardship risk**

> "What knowledge does our work depend on, and how is it sustained or shared?"

| | |
|---|---|
| Working questions | How concentrated is experience? Which roles have one incumbent? How much service is held by people near SURS eligibility, under Tier 1 versus Tier 2 rules? |
| Data | Synthetic age and service. SURS rules from [Retirement Eligibility](https://surs.org/retirement-eligibility/) and the [Tier I](https://surs.org/wp-content/uploads/Plan_Choice_TierI.pdf) / [Tier II](https://surs.org/wp-content/uploads/Plan_Choice_TierII.pdf) Plan Choice Guides. surs.org is blocked from this sandbox, so the rules were read from search text on 2026-11-06 and must be re-checked |
| SURS bands (ASSUMPTION-labelled) | Tier 1 (service start before 2011-01-01, a proxy): unreduced at 62 with 5 yrs, 60 with 8, or any age with 30; reduced at 55 with 8. Tier 2: unreduced at 67 with 10; reduced at 62 with 10. A 30-years-any-age Tier 2 option seen in one search excerpt is **not** applied. Bands: `unreduced_now`, `reduced_now`, `within_5y` (meets any rule at age + 5 and service + 5), `not_within_5y`. All people are assumed to be Traditional or Portable participants with no reciprocal or purchased service |
| Metrics | `median_service_years` (n ≥ 10). `service_band_n`. `long_service_share_of_service_years` = service-years of people with ≥ 20 yrs ÷ all service-years (D3). `top10pct_share_of_service_years` (longest-serving decile ≥ 10 people). `near_retirement_share_of_service_years`. `single_incumbent_roles_n` = roles with 1 line and 1 filled. `thin_senior_roles_n`. `retirement_band_n[tier][band]` (complementary suppression; the near columns are a declared linked subtotal). Counterfactual `near_retirement_share_if_all_tier{1,2}_rules` (same people, rules swapped; withheld if the cross-tier remainder is a small count). `family_near_retirement_n` |
| Output | `knowledge`. Eligibility is when a pension could start, not intent |

## 7. Preparing for Career Conversations with Staff (Person) — **upskilling/reskilling pathways**

> "How might an employee's interests and growth connect with evolving work?"

| | |
|---|---|
| Working questions | For each role family in the unit, which adjacent families are realistic directions, what would people need to learn, and what AI-literacy level does the work call for? |
| Data | `reskilling/adjacent_role` (O*NET Related Occupations, gap index, job-zone step), `learning_theme`, `competency_target` |
| Metrics | Adjacent families: related occupations mapped to families by SOC prefix, with `pairs` and `median_gap_index` (gap index = average importance-weighted level shortfall). The top learning themes are counted by occupations. The competency-target mix is the share of the family's occupations at each target level |
| Output | `families.<f>.adjacent_families / top_learning_themes / competency_target_share` |
| Guardrail | This worksheet is about one person, so the workbench deliberately provides **role-family** information only. It never shows, stores or infers anything about an employee. The note fields warn on email, UIN or ID patterns |

## 8. Workforce Planning for Major Transformations or Changes (Future) — **ERP-transformation lens**

> "How could workforce needs and employee pathways shift across a major change?"

| | |
|---|---|
| Working questions | Which role families run on Banner / HRFE transaction work today? How many people are in them, how many are near SURS eligibility, and how many carry pre- or early-Banner process history that matters for data conversion? |
| Data | `reskilling/role_task_split` task text. O*NET technology (ERP, HR, accounting and time software commodities) |
| Metrics (ASSUMPTION-labelled) | `hr_fin_task_share` = importance-weighted share of a family's O*NET tasks matching HR, payroll, procurement, budget or accounting transaction patterns (`protocol.ERP_HR_FIN_PATTERNS`), averaged over occupations. ERP-heavy at ≥ 0.15 (result: MGT 16.4%, BFO 15.3%; OAS 12.3% falls just below). Per family: headcount, `near_retirement_n`, `pre_banner_cohort_n` (service began before 2004-01-01). `erp_heavy_headcount_published` |
| Output | `erp`. A keyword proxy on national task text. Replace it with Banner security-class and HRFE-role counts by unit on approved machines |

## 9. Learning for What's Next (Person) — **upskilling/reskilling candidate pools**

> "What will our team need to learn, and how can we make room for it?"

| | |
|---|---|
| Working questions | Which role families form upskilling or reskilling pools, and why? What themes would they learn? How much AI-literacy training does the mix imply, and at which AI PD tier? |
| Metrics | A pool family is one that is high AI-usage, ERP-heavy, or the workforce_sim reskilling source (OAS). Pool size = family headcount and FT level 1–2 headcount (published cells). Learning themes and adjacent families come from reskilling. AI-literacy demand in FTE is as in tool 3, mapped Aware → AI Explorer, Practitioner → AI Catalyst, Integrator → AI Practitioner, Leader → AI Practitioner + leader track (**assumed crosswalk**, not reviewed by the series owners) |
| Output | `pools`, `capability.ai_literacy_target_fte` |
| Guardrail | Pools are counts of people in a family, never a selection of named people |

## Discussion fields and export

Every tool has three free-text fields; tool 1 also has the starting-point checkboxes, and tool 3 stores the edited target mix. Notes are kept in the viewer's browser (`localStorage`, best effort) and export locally as JSON or CSV with the columns `unit, tool, field, value`. Evidence numbers are not exported. The export records the protocol version and the evidence file's SHA-256, so the evidence can be regenerated.
