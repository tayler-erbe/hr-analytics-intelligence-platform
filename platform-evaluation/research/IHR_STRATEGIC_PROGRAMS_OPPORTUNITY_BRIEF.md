# Workforce intelligence for Illinois HR Strategic Programs & Partnerships

Opportunity brief, 2026-11-06. It answers one question: **what data and AI work would be most valuable to the Strategic Programs & Partnerships (SP&P) unit of Illinois Human Resources, and which of it can Snowflake, Databricks or the HR vendors not provide?**

Sources are public pages, cited inline. On 2026-11-06 a second pass read the humanresources.illinois.edu and ihr-hub.illinois.edu pages directly and corrected this brief. Claims that rest only on search excerpts of blocked hosts (genai, itproforum, techservices, uillinois.edu) are marked *search-only*. Supporting research is in this folder; working prototypes are elsewhere in this repository. Nothing here uses university employee data.

## 1. The unit and its public priorities

SP&P is led by Luanne Mayorga, Ed.D., MBA, Assistant Chancellor for Strategic Programs & Partnerships. She is one of four Assistant Chancellors on the IHR Cabinet under Shari Mickey-Boggs, Senior Associate Chancellor for Human Resources ([IHR administration](https://humanresources.illinois.edu/about/administration/), [IHR org chart](https://ihr-hub.illinois.edu/documents/org-charts/ihr-organzational-chart-accessible.html)). The current org chart lists one area under SP&P, Strategic Transformation Programs. Her LinkedIn profile also lists the role of Senior Enterprise AI Advisor, Office of the CIO; no other public source names that role.

The portfolio she describes covers:
- Strategic Transformation
- HR Data & Analytics
- Strategic Workforce Planning
- Talent Mobility
- Succession Planning
- AI Professional Development
- Reskilling

The [SP&P site](https://humanresources.illinois.edu/about/strategic-programs-partnerships/) covers HR Analytics and the HR Competency Model. Its Artificial Intelligence heading links to the AI Professional Development Series page. The public staff directory lists two people in the unit; IHR's HR data analysts sit in a separate unit, HR Applications & Information Services.

What the public record shows:

| Initiative | What is public | Source |
|---|---|---|
| **AI Professional Development Series** (IHR with OCIO, Technology Services, CITL and the Library) | Launched Oct–Nov 2025 on separate employee and leader tracks; about 1,380 initial registrations (other session and registration counts are *search-only*). IHR's FY25 report lists 36 AI PD sessions. **Staff tiers:** AI Explorer (self-directed, Canvas) → AI Catalyst (tool deep-dive plus role-scenario session) → AI Practitioner, plus Unit Training. **Leader tiers:** AI Ready Leaders (e-learning, October 2026; modules include AI fluency and responsible AI leadership) → AI Adaptive Leaders → AI Forward Strategies. The series' goals page says badges should "guide internal talent marketplace opportunities, and inform workforce planning and succession strategies" and aims to develop "super AI users" | [GenAI news, Feb 2026](https://genai.illinois.edu/2026/02/06/ai-professional-development-builds-momentum-expands-to-intermediate-series/), [Tech Services, Mar 2026](https://www.techservices.illinois.edu/2026/03/03/illinois-ai-professional-development-series/), [IHR series page](https://humanresources.illinois.edu/ai-professional-development-series/) |
| Talk: **"Measuring AI Adoption in Practice: Moving Beyond Traditional Learning Metrics"** (IT Pro Forum, Spring 2026) | Argues that attendance and satisfaction miss the picture. Proposes tracking behavior change, task augmentation, prompt sophistication and collaboration signals. Names trust, psychological safety and data collection as the hard parts | [IT Pro Forum session](https://itproforum.illinois.edu/eventdesc/past-events/2-spring2026/2-3-15pm/measuring-ai-adoption-in-practice-moving-beyond-traditional-learning-metrics/) |
| Talk: **"Make It So: Turning AI Strategy into Enterprise Reality"** (IT Pro Forum, Spring 2026, with OCIO, Technology Services and BTAA) | Covers the enterprise GenAI operating model, tiered training, a Joint Innovation in AI Team, reusable AI solutions and human-in-the-loop safeguards | [IT Pro Forum session](https://itproforum.illinois.edu/eventdesc/past-events/1-spring-2026/1-11am/make-it-so-turning-ai-strategy-into-enterprise-reality/) |
| Talk: **"Beyond AI Training: Building an AI Learning Ecosystem for Staff"** (IT Pro Forum, Nov 4, 2026; presenter not confirmed) | Moves from awareness training toward an ecosystem | [IT Pro Forum schedule](https://itproforum.illinois.edu/schedule/) |
| **HR Analytics** | Workplace Satisfaction dashboard (eNPS 14.02 from 3,095 responses in 2025) and a campus-wide exit survey | [SP&P HR Analytics](https://humanresources.illinois.edu/about/strategic-programs-partnerships/hr-analytics/), [IHR by the numbers (FY25)](https://ihr-hub.illinois.edu/ihr-by-the-numbers/). The exit-survey documentation says responses are stored with SP&P, so the unit holds that data |
| **HR Competency Model** | Cohort program (about 9–15 people) for senior and next-generation HR leaders; the first cohort started March 6, 2026. Six competencies: Strategic Influence; Cognitive Flexibility; Change & Agility Leadership; Digital Proficiency & Data Savviness; Talent Management & Organizational Fluidity; Culture & People Champions. Offered to other units as a template with measurement tools | [HR Competency Model](https://humanresources.illinois.edu/hr-competency-model/) |
| **Strategic Workforce Planning Services** (published Oct 27, 2026) | An IHR Strategic Workforce Planning team offers Succession Planning, Knowledge Stewardship, Bench Strength Analysis, Capability Planning and Upskilling & Reskilling. Named starting points include "a major transformation, such as the ERP" and "growing use of AI tools". Its nine tools are discussion worksheets whose download links were still placeholders; no data product sits behind the service yet. The page does not name the owning unit | [Strategic Workforce Planning](https://humanresources.illinois.edu/strategic-workforce-planning/) |
| Scholarship | Ed.D. (NIU, 2019) on experiential learning in business incubators. *Industry and Higher Education* (2019) article on career-readiness attributes | [Dissertation](https://huskiecommons.lib.niu.edu/allgraduate-thesesdissertations/7414/), [ERIC](https://eric.ed.gov/?id=EJ1235329) |

**Recurring themes:**
- Move from AI awareness to job-embedded capability.
- Measure behavior change, not attendance.
- Keep human judgment in the loop.
- Offer tiered, credentialed pathways.
- Work through partnerships across units.
- Treat AI as reshaping roles and talent needs, not as a reason to cut headcount.

**The evidence gaps.** Public reporting on the AI series is registration and session counts, and the unit's own talk says that is not enough. The new Strategic Workforce Planning service offers succession, bench-strength, knowledge-stewardship and capability planning through worksheets, with no data product behind them. These two gaps, between the measurement and planning the unit has committed to and the data it can show, are where data engineering helps most.

## 2. The landscape that constrains every solution

From [UIUC_HR_AND_AI_TOOL_LANDSCAPE.md](UIUC_HR_AND_AI_TOOL_LANDSCAPE.md):

- **Systems of record:** Banner HR/Payroll (since 2003) behind the HR Front End.
- **Position and recruiting:** JDXpert for position descriptions and Cornerstone for recruiting.
- **Learning:** LinkedIn Learning and Coursera for content. No campus-wide employee LMS was confirmed.
- **Other tools:** Qualtrics for surveys and TeamDynamix for ticketing.
- **Reporting:** AITS runs the EDW, Tableau and Denodo.
- **Approved AI tools:** Microsoft Copilot Chat, Illinois ChatGPT EDU and Illinois Chat. Illinois Chat's locally hosted models are the option approved for Sensitive data.
- **ERP Business Transformation:** announced April 2026. It moves the System off Banner to a cloud ERP, HR and finance first, and is in a consultant-led readiness phase with no vendor selected.
- **Illinois HB 3773:** in effect January 1, 2026. It restricts AI in employment decisions and requires notice.

Three consequences follow:
1. **Build portably.** HR data stays in Banner for two to four years, and the target ERP is unknown. Definitions, history rules and mappings built now must survive the cutover. They should also feed the data conversion.
2. **Never score individuals.** Work at role, unit and program level, use human review, and suppress small cells. Recommendations about people are advisory, explained and logged.
3. **Keep sensitive text on approved, local inference.** This applies to position descriptions, survey comments and exit interviews.

## 3. What to build, ranked by value to SP&P

Each item names the SP&P priority it serves, what exists in this repository, and why the platforms do not provide it. "Platforms" means Snowflake and Databricks, plus the HR vendors reviewed in [TOOLS_BEYOND_SNOWFLAKE_DATABRICKS.md](TOOLS_BEYOND_SNOWFLAKE_DATABRICKS.md).

| # | Solution | Serves | Starting point here | Why a platform does not do this |
|---:|---|---|---|---|
| 1 | **AI Adoption Impact Scorecard.** Measures from registration to tier progression, then 30/60/90-day applied-use follow-ups, use cases submitted and time returned. Results are shown by unit and cohort, never by person | AI Professional Development; the "beyond traditional learning metrics" talk | Semantic layer and metric compiler (`custom_stack/`); evaluation discipline from `benchmark/` | Platforms supply compute and dashboards, not a measurement model for learning impact. HR suites report course completions |
| 2 | **Prompt and AI-proficiency assessment instrument.** A human-scored rubric aligned to the Explorer → Catalyst → Practitioner badges and to the HR Competency Model's Digital Proficiency & Data Savviness competency, with reliability statistics. The AI-literacy rubric is a start | AI PD badges; "prompt sophistication" | `reskilling/competency_framework.yaml` (Aware → Practitioner → Integrator → Leader) | Vendor AI evaluation relies on LLM judges. A credible HR instrument needs human scoring and validation |
| 3 | **AI task-exposure and role-evolution map** of UIUC job families and SUCSS classes. Shows tasks with observed AI use versus durable human work, and links to role-aligned cohorts | AI Forward Strategies ("how AI reshapes roles, structures, and talent needs"); role-scenario sessions; Capability Planning and Upskilling & Reskilling services | `reskilling/` explorer (1,056 roles); `knowledge_graph/` | No product ships a SUCSS ↔ O*NET ↔ task ↔ AI-usage bridge. Gaps G1 and G11 in the tool research |
| 4 | **Future-forward competency framework builder.** Extracts skills from JDX position descriptions on local models, with evidence spans and human review, and connects them to the HR Competency Model and career architecture | Competency frameworks; HR Competency Model | Taxonomy graph (`knowledge_graph/`); extraction design in `CUSTOM_STACK_DIFFERENTIATORS.md` §3.3 | Workday, Oracle and SAP extraction runs in the vendor cloud on proprietary ontologies. Lightcast's free tier allows 50 calls a month (gap G5) |
| 5 | **Workforce scenario planner.** Retirement waves, hiring freezes, reskilling flows and AI-capacity assumptions with P10/P50/P90 ranges, using correct position, person and appointment grain | Strategic Workforce Planning Services (Capability Planning; "a major transformation, such as the ERP") | `workforce_sim/` (synthetic, calibrated to UIUC IPEDS 12,905 and Illinois QWI) | Platform forecasting functions extrapolate one series. Planning tools such as Anaplan or Adaptive cost $100k+ and know nothing about civil-service or tenure states (gap G2) |
| 6 | **Talent-mobility pathways.** Skill-overlap paths between job families with transparent gaps and learning themes. Opt-in, advisory, explained | Talent Mobility; Reskilling | `knowledge_graph/` `reskilling_paths`; `reskilling/` adjacent roles | Black-box marketplaces rank people (see the Eightfold FCRA suit, gaps G8 and G10). Only 26% of higher-ed leaders are satisfied with internal mobility |
| 7 | **Critical-role and succession coverage view.** Bench strength by unit, knowledge-loss exposure and retirement-eligibility bands, aggregated and suppressed. A data layer under the SWP service's worksheets | Succession Planning, Bench Strength Analysis and Knowledge Stewardship services | `workforce_sim/` metrics; original POC succession design (repository README) | Succession modules assume a single HCM with talent reviews. They do not join Banner history, SURS eligibility and position control |
| 8 | **Exit-survey and Workplace Satisfaction text intelligence.** Local-model theme extraction from open text, joined to eNPS and turnover by aggregated segment | HR Analytics | Local-inference rule; evaluation approach in `custom_stack/eval` | Platform AI functions send text to hosted models (Snowflake cross-region inference defaults to on for new accounts). Qualtrics text analytics stays inside Qualtrics |
| 9 | **AI use-case registry for the Joint Innovation in AI Team.** Intake, human-in-the-loop checklist, time-saved estimate, reuse tracking | Strategic Transformation; "reusable AI solutions" | — | Not a data-platform feature. Ticketing tools do not hold the ROI model |
| 10 | **Governed HR metrics assistant.** Natural-language questions answered from approved definitions, with clarification, abstention, small-cell suppression and provenance. Runs on Illinois Chat local models or any platform | HR Data & Analytics; CIO enterprise AI | `custom_stack/nl2sql` + `mcp_server` (44-question evaluation set, 0 unsafe answers on the development set) | Cortex Analyst and Genie publish no HR accuracy benchmark and do not enforce minimum cell sizes (gaps G6 and G7). Their semantic layers lock to each vendor |

**Suggested order.**
1. Items 1 and 2 first: low data risk, and they directly answer the unit's stated measurement problem. In parallel, offer item 7 as the data layer under the new Strategic Workforce Planning worksheets; that service launched on Oct 27, 2026 without one.
2. Item 8 next, using existing survey data.
3. Then items 3 and 4, the framework layer.
4. Then items 5–7, which need the HR history governance agreed first.
5. Items 9 and 10 run alongside the enterprise AI work.

## 4. The integrated workforce data network

The asset no product provides is a governed network linking the University's own workforce records to public labor-market and task evidence. It has three properties:
- every link carries its source, date, method and review status;
- it is portable to whichever ERP and platform the System chooses;
- it is the reference model for converting Banner data to the new ERP.

```text
 INTERNAL (approved machines only)                       PUBLIC (this repository's lake)
 Banner/EDW person, position, appointment (effective-dated) ─┐
 JDX position descriptions and versions ─────────────────────┤        O*NET 31.0 tasks, skills, technology
 Cornerstone requisitions and outcomes ──────────────────────┤        SUCSS civil-service classes
 Learning: AI PD registrations, badges, LinkedIn Learning ───┼── role ontology ── IPEDS HR peers (staff, pay, hires)
 Qualtrics: Workplace Satisfaction, exit survey (aggregated) ┤   (reviewed       QCEW higher-ed employment and pay
 Enterprise AI tool usage (unit-level aggregates) ───────────┤    crosswalks)     Census QWI hires/separations by age
 SURS eligibility bands, position control, funding sources ──┘        Anthropic Economic Index task usage
                                    │
         semantic layer (one definition → DuckDB / Snowflake / Databricks / ERP)
                                    │
   scorecards · scenario planner · role-evolution map · mobility paths · governed assistant
```

**What is built today:**
- **Public data lake** (`lake/`): 80 silver tables, 23 contract tables, 11 gold views.
- **Knowledge graph** (`knowledge_graph/`): 122,874 nodes and 399,444 edges, with provenance on every edge. Internal node types are specified but not populated.
- **Semantic layer** (`custom_stack/`): compiles one specification to DuckDB, Snowflake semantic views and Databricks metric views.

Internal sources attach only on approved machines. `knowledge_graph/schema.md` describes how the EDW history tables would attach with effective dating.

## 5. Where Snowflake and Databricks fit

Both platforms are capable hosts, and the comparison work continues (`platform_kits/`, `PLATFORM_EVALUATION_RUBRIC.md`). The point for SP&P is that **neither supplies the parts above that create value**: the role ontology, the learning-impact measurement model, the reviewed crosswalks, the scenario logic with civil-service and tenure states, small-cell suppression in AI answers, or the human-review workflow. Those must be built whichever platform is chosen.

Building them portably (open formats, one semantic specification, deterministic evaluation) means the work moves with the ERP decision instead of waiting for it. The custom stack also runs on approved on-prem machines with local models, which is where sensitive HR text belongs.

Other tools to weigh honestly:
- **Power BI** on the campus tenant is the practical delivery surface for HR leaders.
- **Visier and One Model** are faster to standard metrics, but cost roughly $100k a year and run in the cloud only.
- **Workday Skills Cloud or Oracle Dynamic Skills** matter if one of them becomes the HCM.
- **CUPA-HR DataOnDemand** is the sector benchmark.

The [tools research](TOOLS_BEYOND_SNOWFLAKE_DATABRICKS.md) recommends the best tool for each job.

## 6. A 90-day plan

| Weeks | Deliverable | Data needed | Risk controls |
|---|---|---|---|
| 1–3 | Agree definitions and success measures for the AI series with SP&P. Draft the impact scorecard on registration and badge data | Series registrations, attendance, badges (unit-level) | Aggregates only; minimum cell size agreed in writing |
| 3–6 | Proficiency rubric pilot with one Intermediate cohort: two human raters, agreement statistics, revisions | Cohort exercise artifacts (consented) | Human scoring; no model grading |
| 4–8 | Role-evolution map for 2–3 job families chosen by SP&P. SME review of task splits and SUCSS mappings | Public data plus JDX descriptions for selected classes (approved machine) | Local inference; reviewed mappings only |
| 6–10 | Exit and satisfaction text themes, with trends and drivers by segment | Qualtrics exports (approved machine) | Local models; suppression; no verbatim publication |
| 8–12 | Scenario planner on real position and appointment history for one division, backtested on prior years | EDW history extract (approved, minimal fields) | Effective-dated grain checks; aggregate outputs; HB 3773 review before any individual-level use |

Each deliverable ships with its definitions, tests, a data-use note and a written list of what it does not show.

## 7. Guardrails

- **No individual scoring:** no attrition, readiness or "AI replaceability" scores for people. HB 3773, disparate-impact law, collective bargaining and civil-service rules all apply. Mobility and succession tools are advisory and explained, with human decisions logged.
- **Observed AI usage is evidence about tasks, not a forecast of job loss.** Frame role evolution as capacity and reskilling.
- **Data on approved systems only:** HR records, survey text and position descriptions stay on approved university systems and local or enterprise-approved models. Only aggregates are published.
- **Write down the mapping status:** SUCSS → O*NET links are unreviewed until an HR analyst confirms them. In the public data, 623 of 883 rank-1 title matches have similarity below 0.35.

## 8. Original POC ideas, carried forward

The POC workstreams in the repository README remain the analytical core and map onto the SP&P portfolio:

| Original idea | Becomes |
|---|---|
| Internal mobility: transition matrix, Markov simulation, career communities | Talent-mobility pathways (#6) and promotion flows in the scenario planner (#5) |
| Succession readiness: departure risk, candidate readiness, Succession Readiness Index | Critical-role coverage and bench strength (#7), at aggregate level until legal review |
| Workforce growth forecasting with O*NET/BLS enrichment | Scenario planner (#5) with QWI/QCEW/IPEDS calibration; BLS OEWS and projections once downloaded |
| LLM skill enrichment with O*NET mapping and embeddings | Competency framework builder (#4) on local models with evidence spans |
| Equity audit view | Fairness and suppression checks built into every output (§7) |
