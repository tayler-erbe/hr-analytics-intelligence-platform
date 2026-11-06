# AITS Decision Support: Snowflake and Databricks evaluation rubric

Version 1.0 — frozen baseline following user approval on November 2, 2026. Research date: November 2, 2026. No platform scores have been earned; no vendor environment has been tested. Changes require a new rubric version applied to every competitor. See benchmark/README.md for the initial fixture and answer-key pack. Performance targets remain pending team requirements.

## Decision to make

Which implementation best helps the AITS Decision Support team produce correct, governed, maintainable ERP analytics, apply data science, and create and revise useful dashboards with AI assistance?

Evaluate Snowflake and Databricks as data/AI platforms supporting ERP decision support. Installing either does not itself supply university payroll, HR, finance, grants administration, business definitions, or approval workflows. If an ERP replacement is later considered, transaction processing, statutory processing, reconciliation and operational controls require a separate rubric.

The workloads below come from the user's project context: workforce planning, proposals and awards, and job-execution monitoring. Their actual server code, database engines, volumes, runtime requirements and production BI tools remain uninspected. Do not assume the existing ERP, warehouse or visualization stack. The synthetic HR explorer already built is a fixture, not proof of either platform's capabilities.

## Evidence rules before scoring

Use the same frozen source fixtures, approved reference answers, change requests and user roles. Agree weights and acceptance thresholds before implementation. Keep the business questions platform-independent; allow each product's supported idiomatic implementation.

Run two comparisons separately:

1. **Platform-native delivery:** the supported vendor stack, including its own AI, ML and visualization surfaces. Record every added product, edition, preview, connector and license.
2. **Common implementation:** the same business logic and, where feasible, the same model/retrieval configuration and external BI front end. This distinguishes platform effects from model or dashboard-tool differences.

The custom implementation can later enter both applicable tracks under exactly the same business tests. Do not compare a fully customized application against an unconfigured vendor tutorial or credit only the custom solution for engineering labor.

Document capability and implementation effort separately. Use these implementation labels: native; configured native; custom code; third-party dependency; unavailable in tested environment. A correct result requiring code is not automatically a capability failure; its effort, maintenance and costs must be visible. Avoid duplicate penalties for the same limitation.

For each test retain source hashes, approved expected results, code/configuration versions, execution timestamps, execution role, generated SQL and tool traces, screenshots or exported artifacts, elapsed time, analyst labor, failures/retries and billed usage. Documentation shows a capability is documented, not that our implementation passed.

## Proposed 100-point rubric

Each subcriterion receives a 0–5 rating. Points earned = subcriterion weight × rating / 5. Category points are the sum of its subcriteria. Weights total 100.

| Category | Points | Subcriteria and weights | Concrete acceptance evidence |
|---|---:|---|---|
| ERP ingestion and transformation | 15 | Source integration 5; temporal/grain correctness 5; incremental recovery 5 | Ingest approved ERP-like fixtures plus an external source. Handle multiple appointments, department histories and late changes. Restart interrupted loads without duplicate facts; quarantine incompatible schema changes |
| Business definitions and trustworthy answers | 15 | Metric reconciliation 5; cross-domain joins 5; traceability 5 | Headcount differs correctly from appointment count and FTE. Proposal/award amounts do not multiply through one-to-many joins. Trace a dashboard value to its definition, source and as-of period |
| AI tools and analytical agents | 15 | Structured question accuracy 5; document evidence and abstention 5; controlled tool use and maintainable context 5 | Answer approved natural-language questions, show SQL/evidence, ask about ambiguous periods, reject unsupported conclusions, and revise answers after a source is superseded. Audit any proposed actions |
| Data science and model lifecycle | 15 | Reproducible exploration/features 5; valid evaluation 5; deployment/monitoring 5 | Reproduce a feature set, prevent future-data leakage, compare a model against a baseline, record versions and uncertainty, schedule batch scoring and demonstrate monitoring/rollback |
| Dashboard creation and transformation | 20 | Initial authoring 5; iterative change 5; faithful migration 5; consumption and delivery 5 | Build agreed views, revise dimensions/metrics/filters using AI and manual tools, migrate an existing dashboard specification, validate permissions, freshness, accessibility and version recovery |
| Governance and responsible access | 10 | Identity/row-column controls 5; lineage/audit and AI boundary controls 5 | Different audiences see only permitted data across SQL, dashboards and agents. Trace privileged execution paths, exports and agent tools; inspect audit evidence |
| Operations and maintainability | 5 | Deployment/recovery 3; independent analyst handover 2 | Deploy from version-controlled artifacts, inject a failure and recover. A second analyst performs an agreed change using the documentation |
| Total cost and exit effort | 5 | Measured operating cost 3; portability/recovery 2 | Account for compute, storage, AI, refresh/index costs, external tools and labor. Export code, definitions, data and model artifacts and exercise an agreed restore/migration procedure |
| **Total** | **100** | | |

### Shared rating anchors

| Rating | Meaning |
|---:|---|
| 0 | Tested and cannot complete the essential task, or produces a materially wrong result |
| 1 | A happy-path demonstration works, but critical edge cases or controls fail |
| 2 | Partial usable result; repeated manual repair or major missing evidence remains |
| 3 | Meets all essential acceptance checks on the agreed fixture; limitations documented |
| 4 | Also passes the specified failure/change cases reproducibly, within pre-agreed effort/service targets |
| 5 | Also demonstrates independent handover, repeatable operation and sustained results across the expanded fixture, with complete evidence |

Translate these anchors into per-test checklists before executing, rather than selecting a rating after watching a demo. Ratings 4–5 require numerical effort/latency/reliability targets agreed in advance; these are not set from vendor marketing.

**Not tested is blank, not zero.** Show tested weight / 100 and provisional earned points; do not rescale missing tests to make a complete score. Record an account restriction as unavailable in this environment, not proof of a universal product limitation. An unavailable required feature still affects suitability of that proposed deployment. Do not publish a final winner without all mandatory tests and adequate coverage of both platforms.

## Gates that cannot be averaged away

Before calling a deployment suitable for production, require:

- All critical financial and workforce reconciliation cases pass against the approved reference results. Use exact comparisons for counts and agreed tolerances only for appropriate numeric measures.
- All specified negative access tests pass; SQL, dashboard, agent and export paths cannot expose the restricted fixture to the wrong role.
- AI does not invent a source, employee competency, causal finding or completed action in the critical evidence tests. Appropriate abstention is a successful response.
- Recoverability is demonstrated, not merely described.
- The proposed environment and data destinations are institutionally authorized for the intended classification.

A gate failure means not production-ready for that tested configuration, even with a high weighted score. Preserve the diagnostic score and explain the failed gate. Synthetic-data experiments may continue without implying production approval.

## The initial benchmark pack

These are proposed fixtures, not existing production data. Create answer keys before building the platform implementations. Keep holdout cases separate from prompt tuning and development.

### Workforce planning

- One person with two appointments, a vacant position, an interim title, a department transfer, and a late effective-date correction.
- Expected outputs: distinct people, appointments, filled/vacant positions and FTE by as-of date, each defined separately.
- Questions: “How many employees do we have?” must trigger clarification if population or period is ambiguous. “Which roles are becoming obsolete?” must not infer obsolescence from title age or the synthetic role history.

### Proposals and awards

- A proposal with multiple investigators, a linked award with amendments and multiple transactions, and different submission/award/transaction dates.
- Expected outputs: approved proposal and award measures at their declared grains, without fanout or conflating obligations with expenditures. Domain owners must approve definitions before scoring.
- Question: “Did funding increase this year?” must identify the measure and fiscal/calendar basis before comparing.

### Job-execution monitoring

- Successful runs, failed runs, retries, a late success, an upstream dependency delay and timezone/day-boundary cases.
- Expected outputs: documented job-versus-attempt failure rates, freshness and recovery indicators. Missing telemetry is unknown, not automatic success.
- Question: “Why did this pipeline fail?” must separate an observed log cause from an unverified hypothesis.

### Cross-cutting AI suite

Proposed minimum: 30 held-out questions spanning metrics, joins, time, document evidence, ambiguity and unanswerable requests; multiple independent runs for a subset to expose variability. Report correctness, supporting evidence, abstention and latency separately. Define numerical tolerances and whether answer keys allow alternative equivalent SQL. No sole reliance on a second model's subjective grading; require domain review for consequential outputs.

Include a document containing instructions that contradict the task. A data-retrieval agent must treat it as source content rather than an authorization to change its tools, access or behavior. Include superseded source definitions to test temporal reasoning.

### Dashboard transformation suite

Use a neutral dashboard specification first; use an actual approved existing artifact when available. Do not imply one-click migration from an unknown BI tool.

1. Create four agreed views: workforce overview, funding overview, pipeline health, and a drill-through detail view. Show definitions and refresh timestamps.
2. Request a metric change from headcount to appointment FTE; validate all affected charts, labels, totals and filters.
3. Add a department hierarchy, an as-of control and a fiscal/calendar toggle. Preserve definitions across drill-through and AI answers.
4. Change a source column and add a new department; measure repair effort and regression failures.
5. Migrate the neutral specification while preserving calculations, interactions and audience access. Record manual rebuilding and unavailable visual features.
6. Have an analyst make one change through natural language and another manually; report both time to first draft and time to validated publication.
7. Test a second audience, keyboard use, readable labels/contrast, freshness warnings, export behavior, scheduled delivery if required, and rollback from version control.

The visual appearance, the semantic model, and the deployment/security setup are separate migration tasks. “AI generated a chart” does not establish any of the latter two.

## Documented strengths and likely differentiators

The following assessment is an interpretation of product architecture and current documentation, not measured superiority. Differentiators mean distinctive combinations and workflows, not features exclusive to one vendor.

### Snowflake

**Promising fit:** governed SQL-centric decision-support data products, shared business definitions and AI questions over those definitions. [Cortex Analyst](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-analyst) uses semantic views describing metrics, dimensions and relationships. This gives us a concrete place to test the consistency of “employee,” “FTE,” “award,” and “fiscal year.” It does not supply the institution's definitions or guarantee correct answers without validated configuration.

[Cortex Agents](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-agents) combines structured analysis, document search and additional tools in a managed agent workflow. Test whether it can reconcile a table answer with a dated policy document and abstain where evidence is missing. Orchestration is a documented capability; quality and permissions must be tested in the chosen configuration.

Snowflake is not limited to SQL or basic reporting. Its [ML platform](https://docs.snowflake.com/en/developer-guide/snowflake-ml/overview) documents feature management, training, experiments, model registry and operational monitoring. Test the actual Python dependencies and workloads rather than assume a data science gap from older comparisons.

**Dashboard distinction:** Snowflake's [retirement notice](https://docs.snowflake.com/en/release-notes/bcr-bundles/un-bundled/bcr-2260) states that the full legacy Snowsight dashboard experience has been removed and describes conversion to Streamlit or third-party BI. For new work, evaluate a supported current surface. [Streamlit in Snowflake](https://docs.snowflake.com/en/developer-guide/streamlit/about-streamlit) supports hosted Python data applications. This may suit a specialized analytical interface; analyst-only maintenance and migration fidelity remain tests, not assumptions.

**Risks to investigate:** semantic-definition upkeep, custom application maintenance, runtime/package constraints, connector fit to our actual ERP, and combined warehouse/AI/index/app costs. [Streamlit limitations](https://docs.snowflake.com/en/developer-guide/streamlit/limitations) depend on runtime; do not generalize one restriction to all deployment options. No Snowflake price/performance or ease-of-use advantage has been established here.

### Databricks

**Promising fit:** a connected engineering, scientific development and AI lifecycle, especially where existing pipelines require substantial Python/Spark customization. [Databricks ML documentation](https://docs.databricks.com/aws/en/machine-learning/) describes notebook development, features, training, serving and monitoring; [MLflow integration](https://docs.databricks.com/aws/en/mlflow/) supports experiment and model/agent evaluation artifacts. This is a strong architectural hypothesis for research-heavy decision-support work, not proof it will outperform Snowflake ML.

For visualization, [AI/BI dashboards](https://docs.databricks.com/aws/en/dashboards/) document AI-assisted authoring, filters, drill-through, publishing and source-control workflows. [Dashboard-linked Genie Agents](https://docs.databricks.com/aws/en/dashboards/genie-spaces) provide a path from a published dashboard to follow-up natural-language questions. Test whether those follow-ups retain the same metric meaning and user permissions. A polished native dashboard is not automatically a replacement for every current BI artifact.

[Agent Bricks](https://docs.databricks.com/aws/en/agents/concepts) documents custom agent runtime, memory/session and tracing capabilities, and distinguishes these from no-code Genie Agents. This supports a test of code-controlled domain agents with measurable behavior. Persistent context must still be maintained and verified; memory is not evidence of correctly learned university business rules.

**Risks to investigate:** administrative/configuration effort across the selected services, skills required for reliable pipelines, native-dashboard parity with our actual requirements, and cost of interactive plus scheduled plus AI workloads. [Lakeflow Connect](https://docs.databricks.com/aws/en/ingestion/lakeflow-connect/) explicitly notes varied connector release states. Validate source-specific support rather than award points for the existence of a connector catalog.

### Shared gaps requiring institutional expertise

Neither product documentation demonstrates automatic understanding of AITS's local ERP meanings, appropriate joins, historical corrections, unit boundaries, or service priorities. Those are implementation and validation responsibilities. Neither a conversational answer nor an attractive chart proves analytical correctness, causal validity or operational readiness.

Both require a deliberate governance design. Evaluate Snowflake [row access policies](https://docs.snowflake.com/en/user-guide/security-row-intro) and Databricks [Unity Catalog](https://docs.databricks.com/aws/en/data-governance/unity-catalog/) through actual audience tests, including application and agent execution contexts. A governed source table does not excuse skipping a test of downstream access paths.

Domain expertise is therefore part of every solution's cost and success, not a missing vendor feature we should claim uniquely to have solved. Our custom implementation must prove that it encodes and maintains these rules more effectively.

## Preliminary fit hypotheses, not grades

| Team priority | First hypothesis to test | What would overturn it |
|---|---|---|
| SQL/semantic reporting and governed business questions dominate | Snowflake may offer an attractive workflow | More setup/review labor, inconsistent answers, or weaker cost/results on identical tests |
| Custom pipelines, scientific experimentation and ML/agent engineering dominate | Databricks may offer an attractive workflow | Dependency, operations or cost friction outweighs its integrated development path |
| Native AI-assisted dashboard authoring is central | Databricks has a directly documented AI/BI authoring path to evaluate | Failure to meet required interactions, access or handover standards |
| Specialized analytical applications are central | Snowflake Streamlit is a credible option to evaluate alongside Databricks app paths | Maintenance/UX/runtime constraints exceed benefit; measure both implementations |
| Existing institutional BI is retained | Compare both as back ends with the same front end | Connector, semantic or permission differences determine actual suitability |

These priorities are not mutually exclusive. Run sensitivity analysis with an agreed reporting-heavy profile and a science-heavy profile after freezing the primary rubric. Show whether the winner changes when priorities change. Do not select alternate weights merely to obtain a desired result.

## Result template

One record per platform/track/subcriterion:

`test_id; criterion; weight; platform; implementation_track; cloud_region; edition_runtime; release_state; test_date; source_fixture_hash; expected_result_version; implementation_label; setup_hours; revision_hours; reviewer_hours; run_count; correctness; latency_p50_p95; billed_usage; rating_0_to_5_or_blank; evidence_location; gate_result; limitations`

A final scorecard must show earned points, tested weight, gate status, implementation dependencies, total cost assumptions and reviewer comments. Do not report precise cost projections without measured usage and applicable institutional pricing.

## Before implementation resumes

Confirm with the team: actual ERP/database sources; current BI/dashboard tools; intended audience and access scope; first representative pipeline; expected data volume/freshness; permitted environments; and the relative priority of reporting, AI and scientific development. This does not block drafting the rubric. It does block claiming that a platform meets AITS's production requirements.

Next deliverable after rubric agreement: the frozen fixture/answer-key pack and an empty per-platform scorecard. Expand the rubric only when new requirements justify it; preserve version history and apply revisions to all competitors.
