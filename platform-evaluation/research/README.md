# Research synthesis: Snowflake, Databricks, and the independent engineer

Research date: 2026-11-06. This page condenses five detailed reports. Read them for evidence and source URLs:

| Report | Question it answers |
|---|---|
| [SNOWFLAKE_AI_CAPABILITIES.md](SNOWFLAKE_AI_CAPABILITIES.md) | What Snowflake's AI and data-engineering stack does today, its status, cost model, compliance posture and limits |
| [DATABRICKS_AI_CAPABILITIES.md](DATABRICKS_AI_CAPABILITIES.md) | The same for Databricks |
| [CUSTOM_STACK_DIFFERENTIATORS.md](CUSTOM_STACK_DIFFERENTIATORS.md) | Where independent engineering can match or exceed both, how to prove it fairly, and where it probably will not win |
| [HR_USE_CASES_AND_GUARDRAILS.md](HR_USE_CASES_AND_GUARDRAILS.md) | 18 prioritized HR use cases, ERP-conversion data-quality work, and Illinois legal guardrails |
| [IHR_STRATEGIC_PROGRAMS_OPPORTUNITY_BRIEF.md](IHR_STRATEGIC_PROGRAMS_OPPORTUNITY_BRIEF.md) | **Start here for the HR partnership:** what to build for Illinois HR Strategic Programs & Partnerships, why the platforms do not provide it, a 90-day plan |
| [UIUC_HR_AND_AI_TOOL_LANDSCAPE.md](UIUC_HR_AND_AI_TOOL_LANDSCAPE.md) | Current UIUC/System HR systems, approved AI tools, ERP transformation status, and the gap analysis |
| [TOOLS_BEYOND_SNOWFLAKE_DATABRICKS.md](TOOLS_BEYOND_SNOWFLAKE_DATABRICKS.md) | HR-native, general and open-source alternatives; best tool per job; 12 gaps no product fills |
| [SKILLS_RESKILLING_AND_WORKFORCE_PLANNING.md](SKILLS_RESKILLING_AND_WORKFORCE_PLANNING.md) | Practice for skills-based organizations, AI reskilling, competency frameworks, workforce planning and succession |
| [PUBLIC_DATA_SOURCE_CATALOG.md](PUBLIC_DATA_SOURCE_CATALOG.md) | 31 public data sources, tiers, join keys and hosts ([JSON](public_data_source_catalog.json)) |

**Evidence quality.** The research agents could not open docs.snowflake.com or docs.databricks.com directly. Feature statuses come from search-result excerpts of vendor release notes and docs, and each report marks its confidence and unverified items. Re-check any status against a live account before it goes into a procurement or decision document. Nothing here is a measured result: no vendor account has been tested.

## The two platforms in one paragraph each

**Snowflake.** SQL-first. AI functions (`AI_COMPLETE`, `AI_CLASSIFY`, `AI_EXTRACT`, `AI_AGG` and others), Cortex Analyst over semantic views, Cortex Search, Cortex Agents and Snowflake Intelligence were reported GA around November 2025. Summit 2026 press reports renamed parts of the stack (Intelligence to "CoWork", Cortex Code to "CoCo"). The strongest fit is a SQL-heavy decision-support team that wants governed natural-language answers without running infrastructure. The risks to watch:
- **Cross-region inference.** Organizations created after March 2026 default to `ANY_REGION`, so prompts can leave the region. Restrict it for HR data.
- **Separate AI billing.** AI usage moved to a separate AI Credits meter in 2026, and costs per agent question are hard to forecast.
- **Document AI** is being replaced by `AI_EXTRACT`, which cannot be fine-tuned.
- **Narrow ML monitoring.** Model monitoring covers only classification and regression, not survival models.

**Databricks.** Notebook- and pipeline-first, broader for data science. AI Functions (`ai_classify` and `ai_extract` reported GA in June 2026), Genie for natural-language BI (Genie One/Agents/Code reported GA in June 2026), Agent Bricks, MLflow 3 tracing and evaluation, Vector Search, Lakeflow pipelines, Lakebase Postgres, Apps, and Unity Catalog with attribute-based access control (ABAC), governed tags and data classification. The strongest fit is a team that will build and operate models and pipelines. The risks to watch:
- **Product churn.** AutoML was removed from ML Runtime 18, legacy online tables were retired, the Beta Genie MCP endpoint was shut off on 2026-10-31, and Lakehouse Monitoring was split and renamed.
- **Billing complexity.** Billing is spread across many DBU meters.
- **Genie limits.** A Genie space holds at most 30 tables, and Databricks advises far fewer for accuracy.
- **LLM-judge tuning.** Agent Bricks auto-tuning relies on LLM judges, which conflicts with this project's rule that no model grades another.

**What neither product supplies.** Neither ships a FERPA attestation, an Illinois civil-service (SUCSS) model, effective-dated HR semantics, minimum-cell-size suppression for pay questions, or a Banner HR connector. The University's business definitions, role ontology and review workflow must be built on either platform.

## Where an independent engineer wins, and how to show it

The defensible argument is not "custom beats platform." It is that **the hard part of HR analytics is domain modeling, evidence and evaluation, and that work is portable.** Work built well once runs on Snowflake, Databricks or on-prem. Concretely, each item below is detailed in CUSTOM_STACK_DIFFERENTIATORS.md with a fair test.

1. **As-of correct, effective-dated HR modeling.** Snowflake Time Travel and Delta time travel are storage recovery windows (at most 90 days, often far less), not business-valid time. EDW `*_EFF_DT`/`*_EXP_DT` logic, late corrections, multiple appointments, and the separation of person, position and appointment grain are modeling work no platform does for you.
2. **Evidence-linked classification.** Title → SUCSS class → O*NET mapping with source spans, abstention and a human review queue. Platform AI functions return a label with no evidence trail.
3. **One semantic layer compiled to every target.** Define headcount, FTE and pay metrics once, then emit DuckDB SQL, a Snowflake semantic view and a Databricks metric view from the same spec ([custom_stack/](../custom_stack/)). Each vendor's semantic layer is native to it; an interchange standard has been announced but is not confirmed as shipped.
4. **Deterministic evaluation without LLM judges.** Score Cortex Analyst, Genie and the custom planner on one question set by comparing result sets, with explicit clarification and abstention cases.
5. **Methods that fit HR questions.** Survival models for time-to-separation, Markov career-path simulation, conformal prediction intervals and fairness audits before any individual-level use. Platform AutoML and monitoring target generic classification.
6. **Local inference for restricted data.** Open-weight models served on approved university hardware keep FERPA, HR and Illinois HB 3773-sensitive data on-prem. Platform AI is vendor-hosted and, on Snowflake, may cross regions by default.
7. **Cost and exit transparency.** An open table format (Parquet/Iceberg/Delta), version-controlled SQL and recorded run costs, with no per-question AI meter.

**Be honest about where the platforms win.** They are faster to a first natural-language answer, ship enterprise identity and governance plumbing, scale elastically, and provide managed search and serving. Non-technical teams across AITS will value those strengths, and the rubric must credit them.

## Proposed role

Position the work as the **workforce data product and evaluation layer** that sits above whichever platform AITS buys:

- Build and own the HR semantic model and effective-dated history, so ERP conversion and any platform inherit correct definitions.
- Run the public external-evidence lake (this repository's `lake/`) and the role ontology linking SUCSS, O*NET, IPEDS peers, QCEW and QWI.
- Run the neutral benchmark that grades vendor AI against approved answers, and publish where each tool fails.
- Deliver flagship views the platforms do not offer out of the box (detailed in CUSTOM_STACK_DIFFERENTIATORS.md §5):
  - **Time-travel workforce explorer:** look at the workforce as of any date, and see what was corrected later.
  - **Role-evolution and AI-task map:** SUCSS classes linked to O*NET tasks and observed AI usage.
  - **Labor-market competitiveness radar:** IPEDS peer pay, QCEW and QWI turnover side by side.

## Guardrails that shape every deliverable

From HR_USE_CASES_AND_GUARDRAILS.md (each item needs counsel or HR confirmation where marked there):

- **Illinois HB 3773** (AI in employment decisions, in effect January 1, 2026). Retention-risk scoring and AI-assisted classification are high-risk uses. Keep individual-level predictions out of decisions until legal review.
- **Pay transparency (HB 3129, 2025) and the Equal Pay Act.** Whether these apply to a public university is unverified.
- **Other constraints:** collective-bargaining duties, civil-service law and BIPA.
- **Data handling:** publish aggregates only, with minimum cell sizes for pay and demographic views.

## Corrections surfaced by the research

- **Luanne Mayorga's title (confirmed 2026-11-06 from her LinkedIn profile, provided by the project lead).** Assistant Chancellor, Strategic Programs & Partnerships, Illinois Human Resources, UIUC (since October 2023), and Senior Enterprise AI Advisor, Office of the CIO. She sits on the IHR Cabinet and leads Strategic Transformation, HR Data & Analytics, Strategic Workforce Planning, Talent Mobility, Succession Planning, AI Professional Development and Reskilling. She reports within IHR to Shari Mickey-Boggs, Senior Associate Chancellor for Human Resources. The repository README previously said "Assistant Chancellor for Illinois HR"; it has been corrected. Her role is UIUC (Illinois HR), which is distinct from System Office HR (System Human Resource Services).
- **ERP replacement.** No vendor choice or go-live date was found publicly. The candidates discussed are Ellucian Cloud, Workday and Oracle.
- **Workday zero-copy integration.** It reached GA on both platforms (Snowflake 2026-10-07; Databricks has a similar partnership), so it differentiates neither. It matters only if Workday becomes the HR system of record.
