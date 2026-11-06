# Higher education IT workforce intelligence: synthetic demonstration

Prepared November 2, 2026. Research reflects publicly accessible primary sources reviewed on that date. This is a prototype and research design, not a current assessment of AITS, its employees, or vendor performance.

## What we are building

A role and service intelligence system for university enterprise IT. It connects what an organization delivers, how its work flows, which positions own that work, what tools support it, and which capabilities need development. The central output is a testable improvement proposal with evidence and an accountable reviewer.

The supplied October 2025 chart was reviewed across nine pages of extracted text, with visual inspection of the organization overview, application development, and decision-support pages. It provides historical functional context. We use broad functions as inspiration, not a one-to-one reconstruction. We do not claim that it reflects the current organization or that it contains complete job descriptions.

**Demo University Shared IT is fictional.** Its eight teams, 57 fictional colleagues/positions, reporting structure, 2023/2025/2026 histories, duties, software choices, and recommendations are invented. It has 171 role snapshots and 48 illustrative development recommendations. No source-person identity mapping is retained. Synthetic names are deliberately marked with Demo surnames. Renaming alone would not anonymize a real org chart; team sizes, topology, and detailed assignments were also changed. This does not establish permission to publish the original chart.

The generated example contains 36 changed position titles and 12 unchanged titles with changed duties between 2025 and 2026. These are designed test cases, not empirical rates. No title is labeled obsolete solely because it is old. Legacy technology knowledge may remain essential during a long university migration.

## Eight specific demonstration cases

| Team/service | Illustrative evolution | Agent question | Evidence needed before a real recommendation |
|---|---|---|---|
| Analytics and decision support | Report Writer to Analytics Engineer | Is repetitive reporting really duplicate data modeling, conflicting definitions, or unmet stakeholder need? | Metric definitions, report usage, refresh failures, decision requirements |
| Data platforms/integration | ETL Developer to Data Product Engineer | Should we invest in data contracts and ownership rather than add another extract? | Source changes, pipeline failures, downstream dependencies, owner agreements |
| Software/experience | ColdFusion Developer to Application Modernization Engineer | Which workflows can migrate while preserving valuable legacy knowledge? | Application dependencies, supported lifecycles, regression tests, migration cost |
| Enterprise applications | Batch Scheduler to Production Operations Engineer; stable title thereafter | Did the work move from restarting jobs to dependency-aware recovery? | Scheduler events, incident records, recovery runbooks, delivery objectives |
| Infrastructure/reliability | Server Administrator to Platform Reliability Engineer | Is manual provisioning delaying service delivery? | Change lead times, automation coverage, incident/recovery outcomes |
| Process/portfolio | Business Process Analyst to Service Optimization Analyst | Is an approval queue the bottleneck, or does it provide a required control? | Event timestamps, control requirements, service owner review |
| Service enablement | Help Desk Technician to Knowledge and Service Automation Analyst | Can retrieval and workflow assistance improve resolution quality? | Resolved/reopened cases, escalation quality, approved knowledge, answer evaluations |
| IT business operations | HR Liaison to Workforce Capability Partner | Which training closes a verified service capability gap? | Service roadmap, tool inventory, role duties, skill assessment and a practical validation task |

Other seeded cases deliberately retain Decision Support Analyst, Database Platform Engineer, Cloud Network Engineer, and Digital Adoption Specialist titles while changing work. The system must distinguish a renamed position from a substantive capability change. All snapshot headcounts remain fixed; the starter cannot claim workforce growth or decline.

## The data connections that matter

```text
Organization -> Team -> Service -> Business process -> Work step
                    -> Position -> Role version -> Task -> Skill -> Tool
                               -> Appointment -> Synthetic person
Task/skill -> Reviewed O*NET bridge -> External occupation context
Peer organization -> Comparable service -> Dated role/posting evidence
Training -> Assessed capability -> Validation artifact -> Service outcome
Every conclusion -> Evidence -> Date -> Source scope -> Review status
```

A single person can hold multiple appointments; a position can outlive its incumbent. A job ad describes an intended role, not necessarily current practice. A chart describes reporting and labeled functions, not observed skill proficiency. Procurement indicates a purchase, not adoption. Certification indicates completion of a credential, not successful service delivery. Preserve all these distinctions in the model.

Use two times: when a claim was observed and when it was effective. Preserve source revision IDs, hashes and source locations. An apparent title change can be a directory correction or a reorganization rather than a promotion. A tool name extracted from a vendor page must never become a local installed-tool fact.

The existing local evidence store accepts the generated appointment observations and keeps their synthetic marker. Use a separate synthetic database. Its current position coverage view is diagnostic; a production as-of workforce model and versioned reference migrations remain to be built. Skills, services, processes and evidence links in this document describe the target model; not all are implemented as relational tables yet.

## Specialist agent contracts

These are proposed product agents, not live deployed agents. The current generator uses deterministic scenario rules. No model, private connector, background monitor or automated retraining is running.

| Agent | Read scope and work | Persisted result | Required rejection behavior |
|---|---|---|---|
| Organization researcher | Approved public service catalogs, strategies, org pages | Institution profile with service scope, source date and claim-level citations | Reject cross-campus scope assumptions; mark historical pages historical |
| Team/service researcher | Approved unit descriptions, service inventory, dated role descriptions | Team dossier: users served, outcomes, dependencies, owners, tools, open questions | Cannot infer duties or software from title alone |
| Role evolution analyst | Comparable role versions, tasks and peer postings | Title/task/skill/tool changes with evidence and uncertainty | Cannot turn keyword changes into headcount or displacement claims |
| Peer comparator | Matched institution services, employment types, scale and geography | Comparable-role evidence panel with inclusion/exclusion reasons | Do not compare research computing with ERP operations merely because both are IT |
| Process analyst | Approved service event logs and controls | Bottleneck hypotheses, validation query, measured pilot design | No efficiency percentage without a denominator, time window and baseline |
| Learning planner | Verified tool roadmap, task gap, role assessment, official learning resources | Conditional training plan, alternative, practical assessment, review date | No certification recommendation from title or vendor popularity alone |
| Evidence reviewer | All proposed claims, source permissions, versions and conflicting evidence | Approve, revise, abstain, or request evidence | Synthetic evidence cannot establish a real organizational finding |
| Coordinator | Reviewed outputs only | Prioritized improvement backlog with owner and measurement plan | No automatic job-classification, compensation, access or staffing changes |

Suggested agent output schema: claim_id, organization_id, team_id, service_id, position_id (optional), claim_type, claim_text, evidence_ids, source_scope, effective_from, observed_at, evidence_status, limitations, counterevidence_ids, reviewer_status, proposed_action, validation_plan, expiry_or_review_date.

Evidence status is one of synthetic, direct observation, public contextual evidence, inferred, or disputed. Keep it separate from review status. A source can be reviewed and still insufficient to support a particular conclusion.

## How domain knowledge improves over time

Use a versioned evidence store and retrieval, not an agent silently rewriting its beliefs. A refresh proposes new claims; a verifier compares them with existing claims. Newer dates do not automatically override authoritative older specifications. Preserve superseded versions and disagreement. Only reviewed facts enter the approved team dossier. Human corrections update the dossier and regression examples, rather than automatically becoming model training data.

For a public pilot, proposed refresh intervals are weekly for approved job feeds, monthly for service/strategy pages, and release-driven for O*NET and BLS. These are design defaults, not scheduled jobs. Store fetched_at, published_at if available, content hash, permitted use, snapshot location, extraction version, reviewer and next_review_at. Do not acquire restricted material through an agent merely because its title is relevant.

The persistent context for a team should contain its mission, services, stakeholders, control obligations, seasonal cycles, validated tools, role/task map, known constraints, previous decisions and unresolved questions. A university IT team needs knowledge of payroll deadlines, academic calendars, audit controls and distributed governance, not just generic software terminology.

## Peer evidence: what is established and what remains open

The [University of Michigan ITS departments page](https://its.umich.edu/about/departments) describes enterprise applications, infrastructure, information assurance, support, and administrative functions. It is a good current discovery source for service-aligned comparators. It does not establish role growth or title replacement. Next, collect dated service descriptions and permitted job postings with matching appointment type and service scope.

Penn State's [Enterprise Systems and Services announcement](https://www.psu.edu/news/information-technology/story/enterprise-systems-and-services-launches-penn-state-it), last updated June 29, 2021, documents a transition from major administrative-system deployment to integrated operational management. It provides a concrete historical example of service lifecycle and organizational change. It is not evidence of current staffing, current titles, or measured efficiency gains.

The [2026 EDUCAUSE report](https://www.educause.edu/research/2026/the-impact-of-ai-on-work-in-higher-education), based on a September–October 2025 survey, covers work-related AI strategies, skills development and risks. It supports investigating upskilling and measuring outcomes; it does not validate the synthetic role transitions or establish demand for a particular certificate.

Additional peer discovery should cover system-level shared IT, administrative ERP operations, institutional analytics, and service-management teams separately. Build a matched service panel before publishing rankings. We have not acquired a longitudinal peer job-posting corpus, so growth/decline and changing skill-frequency findings remain unmeasured.

## Conditional learning investments

Keep credential choices tied to the selected stack and a demonstrated capability gap. These are verified credential offerings, not recommendations to spend money yet:

- [Microsoft Azure Administrator Associate](https://learn.microsoft.com/en-us/credentials/certifications/azure-administrator/): candidate option for an Azure-focused infrastructure role. Require a deployment/recovery demonstration.
- [Power BI Data Analyst Associate](https://learn.microsoft.com/en-us/credentials/certifications/data-analyst-associate/): candidate option where Power BI modeling and delivery are actual duties. Require a reconciled semantic model and permissions test.
- [Databricks Data Engineer Associate](https://www.databricks.com/learn/certification/data-engineer-associate): candidate option after Databricks is selected for relevant pipelines. Require restartability, schema-change handling and operational evidence.

For other stacks, use equivalent official learning paths after verifying the current catalog. Do not send a Snowflake-focused engineer through a Databricks credential because the demo happens to include both. Many gaps are better addressed by targeted labs, mentoring, documentation or protected learning time. Prices, prerequisites and expected ROI have not been evaluated here.

## What vendors can already do

This market is not empty. Differentiate with demonstrated quality and domain depth, not a claim that existing vendors cannot build agents.

| Provider | Publicly documented capability as reviewed November 2, 2026 | Implication for our benchmark |
|---|---|---|
| [Databricks Agent Bricks](https://docs.databricks.com/aws/en/agents/concepts) | Custom agent deployment, runtime/session capabilities and tracing; current docs distinguish code-based Agent Bricks from no-code Genie Agents | Strong infrastructure candidate. Test integration effort, evidence retrieval, evaluation, cost and portability; verify account availability |
| [Snowflake Cortex Agents](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-agents) | Tool-based orchestration across structured analysis and unstructured search, with monitoring/evaluation capabilities | Strong candidate for governed data questions and document evidence. Test semantic correctness and citeable source retrieval |
| [Gloat Skills Intelligence Engine](https://gloat.com/use-cases-agents/skill-intelligence-engine-agent/) | Markets dynamic workforce skill discovery, validation and profiles | Overlaps our skill-inventory idea. Marketing examples are not independent accuracy benchmarks |
| [Eightfold Talent Management](https://eightfold.ai/products/talent-management/) | Markets career guidance, skill development, internal mobility and workforce-readiness capabilities | Our comparison needs a university service/task benchmark, rather than assuming internal mobility is novel |
| [ServiceNow Process Mining](https://www.servicenow.com/products/process-mining.html) and [ITSM workforce optimization](https://www.servicenow.com/products/workforce-optimization.html) | Process visibility, workflow improvement and service-team optimization | Relevant benchmark for efficiency claims; process diagnosis already has mature competitors |
| [Workday agent-building documentation](https://developer.workday.com/documentation/GUID-e0052175-0a0f-407b-999b-d278ba15bab7-enHYPHENus) | Describes a talent snapshot, internal-role matching and development-plan example | Agent-supported role/development workflows are feasible on incumbent HR platforms |

Product descriptions establish available or marketed approaches, not independently verified performance or institutional entitlement. No vendor account or trial was accessed for this work. Avoid architecture built around obsolete tutorial naming: current Databricks agent documentation differs from older Supervisor examples. Freeze versions and record the actual account features at test time.

## How we can win a narrowly defined benchmark

Our hypothesis is that a purpose-built higher education IT evidence system can offer more useful, auditable role and process recommendations for this niche. Prove it against the same source set and questions. It may run on Databricks or Snowflake as well as on a custom stack; your contribution is separable from the execution platform.

1. Build a reviewed benchmark of 30 cases across title changes, unchanged-title duty drift, ambiguous roles, legacy continuity, source conflicts, missing tool evidence, expired training information, and misleading process metrics.
2. Use identical approved evidence snapshots for custom, Snowflake and Databricks runs. First compare the same retrieval/model baseline; then report platform-native enhancements separately.
3. Have reviewers score correct role/task links, claim-level source support, false recommendations, appropriate abstention, time to produce a reviewable answer and review effort. Assess retrieval recall on a labeled subset.
4. Test stale-source correction: change a procedure, supersede a job description, introduce contradictory evidence, and require the system to explain which conclusions changed.
5. For training, require a service capability, verified gap, official path, lower-cost alternative, assessment task and follow-up measure. No invented proficiency percentage.
6. For efficiency, evaluate a service pilot with baseline volume, complexity, active handling time, waiting time, rework, control failures and user outcomes. Do not infer a need for job cuts from shorter handling time.
7. Publish total cost including integration, platform usage, model calls, review labor, maintenance and exit/export effort. No winner is scored until measured.

Acceptance targets should be agreed before the real-data run. Suggested starting gates: every consequential claim has a source or an explicit synthetic/inferred label; zero employee conclusions drawn from fabricated histories; no unsupported live-tool claims; all recommended changes include a reviewer and validation task. Quantitative accuracy/latency targets need a labeled baseline before selection.

## What is runnable now

```powershell
python scripts/build_synthetic_demo.py
python scripts/workforce_store.py --db data/local/synthetic_workforce.sqlite --import-jsonl data/synthetic/observations.jsonl
```

The generator creates public-demo JSONL files plus a manifest. The importer stores them in a separate local SQLite database. The offline explorer is generated with `python scripts/build_demo_explorer.py`; open `output/demo/role-evolution.html`. It shows synthetic history and deterministic proposals, not live agent responses.

Implemented: fictional topology, identities, role histories, skills/tools, evidence IDs, conditional development suggestions, lineage to scenario records, deterministic generation, and local ingestion. Not implemented: live autonomous agents, reviewed occupation bridges for these roles, real tool inventory, process mining, peer demand estimates, platform deployments, or proven savings.

The next engineering increment is the claim/evidence store and one team dossier, followed by a read-only evidence agent with a rejection test set. A broad autonomous workforce adviser comes after those pieces can be evaluated.
