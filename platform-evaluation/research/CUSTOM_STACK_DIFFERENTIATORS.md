# Where an independent data/AI engineer can beat Snowflake and Databricks for higher-ed HR/workforce analytics

**Research date:** 2026-11-06 (web research run that day; vendor features change monthly. Recheck every "status" cell against current release notes before you cite it.)
**Prepared for:** Tayler Erbe, Senior Data Scientist, University of Illinois System AITS
**Status:** Design brief. Nothing here is a benchmark result. All claims of the form "custom beats platform" are hypotheses that the fair tests in Section 4 must confirm.

---

## 1. Thesis and ground rules

Snowflake (Cortex AI Functions, which used to be called AISQL; Cortex Analyst, Search and Agents; Snowflake Intelligence) and Databricks (AI Functions, Genie, Agent Bricks, Vector Search, MLflow, Lakeflow, Unity Catalog) are strong general platforms. They are weakest where HR analytics is hardest:

1. **Time semantics.** Effective-dated, bitemporal "as of" correctness.
2. **Grain discipline.** Position, person and appointment are different grains.
3. **Domain crosswalks with evidence.** Job title to SUCSS class to O*NET-SOC.
4. **Statistical methods that respect censoring and uncertainty.**
5. **Cost and reproducibility you can show an auditor.**
6. **Data residency.** Institutional HR data stays on approved machines and uses local or on-prem inference.

Point 6 changes the comparison in a basic way. Any platform AI feature that sends HR text to a hosted model is out of scope for institutional data, whatever its accuracy. The platform-native track then reduces to SQL, semantic and governance features, plus whatever model hosting the university has approved.

**Fairness rules** (these follow the existing rubric):

| Rule | Implication for this brief |
|---|---|
| Never compare a custom app with an unconfigured vendor tutorial | Every test configures the platform to the vendor's own best practice. That means Genie descriptions, example SQL and benchmarks, and Cortex Analyst semantic views with verified queries. |
| Separate tracks | **Track A, platform-native:** the best configuration a competent platform engineer builds in about the same hours. **Track B, common implementation:** the same open-source stack (dbt, Iceberg, a semantic layer, local LLM) running on both platforms and on-prem. Custom work is credited only for the difference it makes within a track. |
| Equal effort budget | Log hours per arm. A custom arm that took 10 times longer is reported that way. |
| Frozen protocol | Prompts, schemas, scoring, thresholds and failed-case handling are fixed before runs. Every attempted case, error and truncation is kept. No model grades another model; gold labels and deterministic checks do. |
| Data handling | Benchmarks use public or synthetic HR data, or run on approved machines. Publish aggregates only. |

---

## 2. Platform capabilities and documented limits (as found 2026-11-06)

| Area | Snowflake | Databricks | Source |
|---|---|---|---|
| NL-to-SQL scope | Cortex Analyst runs over semantic views or YAML models. A derived metric cannot reference physical columns from other tables. Third-party reports say multi-table relationships are often missing until you add them by hand, and that semantic views did not support replication as of Aug 2025. | A Genie space holds **at most 30 tables or views**. Docs recommend **five or fewer**, and warn that extra tables "can cause Genie to provide confusing or incorrect answers." Answers are marked "Trusted" only when they match parameterized example SQL. In Databricks' own Feb 2026 blog example, join queries failed until context was fixed. | [SF semantic spec](https://docs.snowflake.com/user-guide/snowflake-cortex/cortex-analyst/semantic-model-spec), [phData](https://www.phdata.io/blog/snowflake-semantic-views-real-world-insights-best-practices-and-phdatas-approach/), [Genie docs](https://docs.databricks.com/genie/index.html), [Genie best practices](https://docs.databricks.com/gcp/en/genie/best-practices), [DBX blog](https://www.databricks.com/en/blog/how-build-production-ready-genie-spaces-and-build-trust-along-way) |
| Agent accuracy | The Cortex Agents docs say the accuracy of responses and citations "is not guaranteed" and tell you to review every answer. Model availability varies by region. | Genie benchmarks (up to about 500 questions per space, per a third-party source) measure accuracy but **do not feed back into context**. | [Cortex Agents](https://docs.snowflake.com/user-guide/snowflake-cortex/cortex-agents), [Addepto](https://addepto.com/blog/databricks-genie-pricing-capabilities-and-roi-requirements/) |
| Extraction | AI_EXTRACT and AI_COMPLETE are billed in **AI Credits per million tokens**, input and output. A separate AI Credit took effect Apr 2026, about $2.00 global per a third-party report. Warehouse compute is billed on top. | Agent Bricks Information Extraction requires serverless compute and Unity Catalog. Limits: **128k-token context, no union schema types**, Beta, not in Free Edition. | [SF AI cost](https://docs.snowflake.com/en/user-guide/snowflake-cortex/aisql-cost), [SF AI pricing](https://docs.snowflake.com/en/user-guide/snowflake-cortex/pricing), [Agent Bricks IE](https://docs.databricks.com/aws/en/generative-ai/agent-bricks/info-extraction), [forum](https://community.databricks.com/t5/databricks-free-trial-help/questions-about-the-knowledge-assistant-during-agentbrick/m-p/121689) |
| Time travel (not business history) | Time Travel lasts up to **90 days** on Enterprise and **1 day** on Standard, then Fail-safe, which cannot be queried. | Defaults: **7 days of data files and 30 days of log**. Databricks "does not recommend using Delta Lake table history as a long-term backup solution." | [SF Time Travel](https://docs.snowflake.com/en/user-guide/data-time-travel), [Delta retention thread](https://community.databricks.com/t5/warehousing-analytics/dela-table-and-history/td-p/110710), [Substack summary](https://mbvyn.substack.com/p/understanding-databricks-time-travel) |
| Semantic layer | Semantic views live inside Snowflake. Snowflake co-founded the Open Semantic Interchange (OSI). | Unity Catalog metric views are being open-sourced into Apache Spark, with Unity Catalog OSS support planned. A dbt metric-view integration exists only as a GitHub proposal. One source says no product ships OSI import or export yet. | [Atlan on UC semantics](https://atlan.com/know/ai-agent/semantic-layer/unity-catalog-semantic-layer/), [DBX semantics blog](https://www.databricks.com/blog/redefining-semantics-data-layer-future-bi-and-ai), [dbt-databricks #1106](https://github.com/databricks/dbt-databricks/issues/1106) |
| Table-format portability | Iceberg REST catalog-linked databases can point at Unity Catalog. CTAS into Unity Catalog Iceberg became GA on 2026-03-31. | The Unity Catalog Iceberg REST endpoint is Public Preview on DBR 16.4+ per the docs page; a blog says managed Iceberg is GA, a conflict to confirm. Clients need `EXTERNAL USE SCHEMA`. | [SF release note](https://docs.snowflake.com/En/release-notes/2026/other/2026-03-31-ctas-unity-catalog-external-volumes), [DBX Iceberg access](https://docs.databricks.com/gcp/external-access/iceberg), [Iceberg catalogs Jun 2026](https://dev.to/alexmercedcoder/the-state-of-apache-iceberg-catalogs-in-june-2026-265e) |

**What this means.** Neither platform has an HR time model, an HR occupational crosswalk, or survival or conformal tooling as a product feature. You can build all of them on either platform. That is the point: the edge comes from engineering, not from avoiding the platform. The honest pitch is "custom engineering that runs on either platform, or off both," not "replace Snowflake or Databricks."

---

## 3. Differentiators

Effort assumes one senior engineer with access to synthetic or public data. The ranges are estimates, not commitments.

### 3.1 Bitemporal, effective-dated HR modeling and as-of correctness

- **Platform default.** Time Travel and Delta history are *system-time, short-retention recovery* tools. They do not track when a fact was true in the business (valid time), which is what `*_EFF_DT` / `*_EXP_DT` encode. Genie and Cortex Analyst will write `WHERE eff_dt <= :d AND exp_dt > :d` only if examples teach them to. Typical failures are open-ended `EXP_DT` sentinels (`9999-12-31` vs NULL), same-day multiple actions (an effective-sequence column), and retroactive corrections. A retro-dated pay change keyed into payroll in March for January is the classic case.
- **Custom.** A bitemporal core:
  - valid time from EDW `EFF_DT`/`EXP_DT`;
  - transaction time from load timestamps, using dbt snapshots or SCD2 from Lakeflow, Snowpipe or Streams;
  - a single `as_of(valid_date, known_date)` macro or table function;
  - interval-integrity tests: no gaps or overlaps per key, and exactly one current row.

  This answers questions that are otherwise impossible, such as "headcount on 2025-10-01 *as we believed it on 2025-10-15* vs as corrected today," which is what IPEDS resubmission and audit questions need.
- **Effort.** 2–3 weeks for the core marts and macros, plus 1 week of tests.
- **Fair test.** Write 40 gold as-of questions on a synthetic EDW-shaped dataset seeded with retro corrections, sentinel dates and same-day multi-actions. Track A: a Genie space and a Cortex Analyst semantic view, each with up to 10 example queries written by a platform engineer. Track B: the same LLM over the bitemporal semantic layer. Score exact-match result sets against gold computed by hand-verified SQL. Report the error breakdown by trap type.

### 3.2 Position vs person vs appointment grain

- **Platform default.** Both NL-to-SQL tools join whatever tables are in scope. Docs advise prejoining into views to reduce confusion, and prejoining silently picks a grain. "How many employees" can mean distinct persons, active appointments (a person may hold several, such as 50% staff plus 25% academic hourly), funded positions (including vacant ones), or FTE. Summing appointment FTE across a person-grain join double-counts.
- **Custom.** Explicit grain-typed entities in the semantic layer, MetricFlow entity types or a Cube `primary_key` per cube. Metrics are declared only at their legal grain (`headcount_person`, `appointment_count`, `fte_sum`, `vacant_positions`). The query layer *refuses* ambiguous requests and returns a clarification instead of guessing. Abstention is a feature.
- **Effort.** 1–2 weeks once 3.1 exists.
- **Fair test.** 30 ambiguous and 30 unambiguous grain questions, scored on correct answer *or* correct clarification request. Both tracks get the same metric definitions, Track A as platform metric views or semantic views. Measure the fan-out error rate.

### 3.3 Entity resolution: job title to SUCSS class to O*NET-SOC, with evidence spans and review queues

- **Platform default.** AI_CLASSIFY / AI_EXTRACT and `ai_classify` / `ai_extract` / Agent Bricks IE return labels, but there is no built-in crosswalk memory, evidence-span contract or adjudication queue. Agent Bricks IE has a 128k context limit and no union schemas. Hosted inference is disallowed for institutional text anyway.
- **Custom.** Three stages:
  - **Candidate generation.** Lexical (BM25 / rapidfuzz) plus embeddings (local `bge` / `gte` / `nomic` class) over SUCSS class specs and O*NET titles, alternate titles and task statements.
  - **Local LLM adjudicator.** vLLM structured outputs (xgrammar or guidance backends; in vLLM ≥ 0.12 use `structured_outputs` / `response_format`, because `guided_*` was removed) with a schema of `{sucss_class, onet_soc, evidence_spans[], confidence, abstain_reason}`.
  - **Human review queue** for low-confidence or abstained items. Decisions persist as versioned crosswalk rows with reviewer and date, so the crosswalk is itself bitemporal.
- **Effort.** 3–5 weeks, including the review UI. The repo's existing evidence-span and review patterns can be reused.
- **Fair test.** A public gold set: O*NET alternate-titles and Sample-of-Reported-Titles files, mapped to SOC, with held-out titles. A SUCSS-class gold set built only from public class specifications. Report top-1 and top-3 accuracy, **coverage at fixed precision** (for example 95%), abstention rate and evidence-span validity, which is checked deterministically against source text. Track A gets a platform AI function with the same prompt and label list. Track B gets the same open model on platform-hosted serving vs on-prem. No model grades another model.

### 3.4 Knowledge graph of roles, skills and tasks

- **Platform default.** No native property-graph engine. Recursive CTEs work but are awkward for paths like "class to task to skill to adjacent class."
- **Custom.** An embedded graph. Note that **Kùzu was archived on 2025-10-11**. Its MIT-licensed revival fork is **LadybugDB** (`real_ladybug` on PyPI). The other options are DuckDB with the DuckPGQ extension (SQL/PGQ) or Neo4j Community. Nodes: SUCSS class, O*NET-SOC, task, DWA, skill, unit, position. Edges carry provenance and validity intervals.
- **Effort.** 1–2 weeks on top of 3.3.
- **Fair test.** 20 path questions, such as "which classes share ≥ 60% of tasks with X" or "nearest retraining target," with gold answers computed by brute force. Compare correctness, latency and lines of code against a recursive-CTE implementation on each platform.

Sources: [FreshPorts kuzu](https://www.freshports.org/databases/kuzu/), [LadybugDB PyPI](https://pypi.org/project/real_ladybug/), [DBDB LadybugDB](https://dbdb.io/db/ladybugdb).

### 3.5 Local LLMs for FERPA- and HR-safe extraction

- **Platform default.** Cortex and Mosaic serving are hosted in the vendor's cloud. Whether that is acceptable for HR content is a legal and compliance question. The project rule is already local or on-prem.
- **Custom.**
  - **Serving:** vLLM for GPU servers, llama.cpp or Ollama for laptops and edge.
  - **Models:** Qwen3-, Llama-, Gemma-class open weights.
  - **Decoding:** grammar-constrained decoding. Watch the Qwen3 reasoning-parser caveat: structured output can silently turn off when reasoning is enabled.
  - **Pinning:** model, quantization and decoding parameters are pinned in a run manifest.
- **Effort.** 1 week to stand up and pin.
- **Fair test.** Same documents, schema and scoring as the existing protocol. Report field accuracy, schema-valid rate, abstention, tokens per second and dollars per 1k documents. Hosted-platform arms run **only on public benchmark data**.

Source: [vLLM structured outputs](https://docs.vllm.ai/en/latest/features/structured_outputs/).

### 3.6 Evaluation harness with abstention and gold sets

- **Platform default.** Genie benchmarks, Snowflake AI observability and MLflow evaluation exist, and MLflow is excellent for tracking. Platform evaluations, however, often default to LLM-as-judge scorers, which the rubric forbids for grading.
- **Custom.** A harness-as-code with frozen protocol files and hashes:
  - deterministic scorers (result-set equality, field-level exact or normalized match);
  - selective-prediction curves (accuracy vs coverage);
  - per-trap error taxonomy;
  - all failures retained.

  MLflow can be the tracking store, open source and usable on both platforms, so this is not a "vs MLflow" claim.
- **Effort.** 1–2 weeks. Much of it already exists in this repo's conformance tooling.
- **Fair test.** This harness *is* the referee for 3.1–3.5. Its contribution is measured by reproducibility: rerun determinism, and matching hashes across environments.

### 3.7 Survival analysis for attrition vs generic classifiers

- **Platform default.** AutoML and generic classifiers predict "leaves within 12 months." They discard censoring (recent hires, people still employed) and give no hazard over time.
- **Custom.** `lifelines` (Cox PH, Weibull AFT) and `scikit-survival` (random survival forests, gradient-boosted Cox) on person-spell data built from 3.1. Time-varying covariates come straight from effective-dated rows (pay changes, supervisor changes, FTE). Outputs are hazard curves by class, unit and tenure band, plus the expected remaining tenure.
- **Effort.** 2–3 weeks.
- **Fair test.** Synthetic or public turnover data with a known generating hazard. If you run on real data, do it on approved machines and publish aggregates only. Compare the Harrell / Uno C-index, the integrated Brier score and calibration at 6, 12 and 24 months against the platform AutoML classifier scored on the same horizons. Use identical features and splits, with a temporal holdout.

### 3.8 Markov and career-path simulation

- **Platform default.** No native modeling. Either platform runs Python, so the edge is in the modeling.
- **Custom.** Estimate transition matrices between grade, class and status states from effective-dated history: semi-Markov with duration dependence, stratified by unit. Run Monte Carlo workforce projections (retirement waves, promotion bottlenecks, the hiring needed to hold FTE).
- **Effort.** 2–3 weeks.
- **Fair test.** Backtest: fit on years ≤ T, project T+1..T+3 and compare with actual aggregates. Report MAPE and interval coverage. The baseline is a naive carry-forward or linear trend.

### 3.9 Fairness auditing

- **Platform default.** No built-in disparity audit for HR models. Unity Catalog and Snowflake governance cover access, not outcomes.
- **Custom.** Fairlearn `MetricFrame` and Aequitas group metrics on model outputs *and* on raw processes (promotion rates, time-to-fill, pay-band position). Use intersectional slices, suppress small cells (n < 10), and report bootstrap CIs.
- **Effort.** 1 week.
- **Fair test.** On synthetic data with *injected* disparities of known size, measure detection power and false-alarm rate. The comparison is "audit pipeline vs no audit," so report capability presence plus calibration, not a win over the vendor.

### 3.10 Conformal prediction for uncertainty

- **Custom.** MAPIE v1 (new API) adds distribution-free prediction intervals to headcount and salary forecasts and prediction *sets* to the 3.3 classifier: "SOC is in {15-1211, 15-1299} with 90% coverage." Adding conformal risk control to the abstention threshold lets "precision ≥ 95%" become a guarantee rather than a tuned constant.
- **Effort.** 1 week.
- **Fair test.** Empirical coverage vs nominal (90/95%) on held-out data, and set size. The platform baseline is a point prediction or a softmax confidence threshold.

Source: [MAPIE](https://github.com/scikit-learn-contrib/MAPIE).

### 3.11 Data contracts

- **Platform default.** Lakeflow expectations and Snowflake data metric functions handle row-level quality inside each platform.
- **Custom (portable).** dbt model contracts (enforced column types and constraints), Soda or Great Expectations checks, and Pandera for Python frames. HR-specific contracts include:
  - no overlapping effective intervals;
  - FTE ≤ 1.0 per person, summed across appointments, as of any date;
  - every position has a valid SUCSS class as of its effective date;
  - suppression flags on small cells.
- **Effort.** 1 week.
- **Fair test.** Mutation testing. Inject 50 known defects into synthetic data and measure the detection rate and time to detect for each arm.

### 3.12 Portable semantic layer

- **Platform default.** Snowflake semantic views and Databricks metric views are each native to their platform. OSI aims to bridge them, but shipped import or export was not confirmed as of 2026.
- **Custom.** One definition source in dbt MetricFlow (Apache 2.0; generates SQL for Snowflake, Databricks, Postgres and others), Cube, or the lightweight Ibis-based "boring semantic layer." Compile it to both platforms' native objects where feasible, with generated YAML for semantic views and metric views.
- **Effort.** 2 weeks.
- **Fair test.** The same 60 metric questions on both platforms. Report result parity (should be 100%), time to add a new metric everywhere, and drift incidents.

### 3.13 MCP servers exposing governed metrics

- **Platform default.** Each vendor's agent works within its own walls.
- **Custom.** The dbt MCP server exposes `list_metrics`, `get_dimensions` and `query_metrics`. Note that its Semantic Layer tools require dbt Platform, and the free Developer plan lacks them. Alternatives are a small custom MCP server over MetricFlow or Cube that exposes only governed metrics and grain-checked queries, with `execute_sql` disabled per the security guidance, or community MCP servers. Any approved local LLM or client can then query governed numbers without raw-row access.
- **Effort.** 1 week.
- **Fair test.** Use the same question set as 3.2. Compare the MCP-governed path with free-form SQL agents on accuracy, policy violations (attempted raw-row access, unsuppressed small cells) and abstention correctness.

Sources: [dbt MCP blog](https://docs.getdbt.com/blog/introducing-dbt-mcp-server), [Atlan on dbt MCP](https://atlan.com/know/mcp/mcp-server-for-dbt/), [TrueFoundry](https://www.truefoundry.com/blog/dbt-mcp-server).

### 3.14 Open table formats, cost transparency and reproducibility

- **Portability.** Iceberg tables in one catalog, readable from Snowflake through catalog-linked databases and from Databricks through Unity Catalog Iceberg REST, plus DuckDB on-prem. *Fair test:* query the same snapshot ID from three engines and check that result hashes match.
- **Cost.** Per-question and per-document cost ledger: tokens × published AI Credit rates, warehouse or DBU seconds, and on-prem GPU amortization from the existing hardware budget doc. *Fair test:* report $/correct answer per arm, using list prices and recording the date.
- **Reproducibility.** Lockfiles, pinned model hashes, Iceberg snapshot IDs and protocol hashes. *Fair test:* rerun 30 days later and compare outputs byte-for-byte or within a declared tolerance. Hosted models that change silently under a stable name fail this by construction, so report that as a finding, not a gotcha.

### 3.15 Summary table

| # | Differentiator | Platform gap (documented or structural) | Custom edge | Effort | Primary metric |
|---|---|---|---|---|---|
| 1 | Bitemporal as-of | Time Travel ≤ 90d / Delta 7–30d; no valid-time model | `as_of(valid, known)` + interval tests | 3–4 wk | As-of exact-match % by trap |
| 2 | Grain discipline | Prejoined views hide grain | Grain-typed metrics + clarification | 1–2 wk | Fan-out error rate; clarification F1 |
| 3 | Title→SUCSS→O*NET | No crosswalk memory or review loop; IE 128k, Beta | Retrieval + local LLM + evidence + queue | 3–5 wk | Coverage @ 95% precision |
| 4 | Role/skill graph | No native graph | LadybugDB / DuckPGQ / Neo4j | 1–2 wk | Path-query correctness, latency |
| 5 | Local LLM | Hosted inference | vLLM / llama.cpp, pinned | 1 wk | Field accuracy, $/1k docs |
| 6 | Eval harness | Judge-centric defaults | Deterministic, abstention curves | 1–2 wk | Rerun determinism |
| 7 | Survival | Classifiers ignore censoring | Cox / AFT / RSF, time-varying | 2–3 wk | C-index, IBS, calibration |
| 8 | Career Markov | None native | Semi-Markov Monte Carlo | 2–3 wk | Backtest MAPE, coverage |
| 9 | Fairness | Access governance, not outcomes | Fairlearn / Aequitas + CIs | 1 wk | Detection power / false alarms |
| 10 | Conformal | Point estimates | MAPIE sets and intervals | 1 wk | Empirical coverage |
| 11 | Contracts | Platform-local | dbt / Soda / GX / Pandera HR rules | 1 wk | Mutation detection % |
| 12 | Semantic layer | Platform-native objects | MetricFlow / Cube single source | 2 wk | Cross-platform parity |
| 13 | MCP metrics | Walled agents | Governed metric tools | 1 wk | Policy violations, accuracy |
| 14 | Portability / cost / repro | Opaque, drifting | Iceberg + ledger + pins | 1–2 wk | Hash parity, $/correct |

---

## 4. How to run the proof without cheating

1. **Dataset.** A synthetic, EDW-shaped HR dataset of about 20k persons and 10 years of effective-dated rows. It is generated from published distributions (IPEDS HR counts, OEWS wages) and seeded with documented traps: retro corrections, multi-appointment people, vacant positions, sentinel dates, reorganized units and reclassified titles. Publish the generator and its hash. The existing public benchmark case_pack and exports stay frozen and untouched. This is a **new labelled protocol**, not a change to the existing one.
2. **Arms.**
   - A1: Snowflake-native (Cortex Analyst semantic view, verified queries, Snowflake Intelligence agent).
   - A2: Databricks-native (Genie with ≤ 5 tables, example SQL, metric views, benchmarks used per the docs).
   - B1/B2: the common-implementation stack on each platform.
   - C: the same stack fully on-prem.

   Each arm gets equal configuration hours, logged.
3. **Scoring.** Deterministic gold: result-set equality, field match and coverage curves. Clarification or abstention counts as correct only where gold marks the question ambiguous.
4. **Reporting.** Per-trap breakdowns, every failure, $/correct, hours spent, version and date stamps. Name a winner only per question type, never overall.

---

## 5. Three flagship demos for the Vice Chancellor / Assistant Chancellor of HR

Each demo runs on approved machines and shows aggregates only, with small-cell suppression. They combine the differentiators above in ways no off-the-shelf vendor demo does. The "never been done" claim is a scan-level judgement from this research, not an exhaustive literature review.

### Demo 1: Time-Travel Workforce Explorer

**What the leader sees.** A slider for *valid date* and a second slider for *knowledge date*. Drag the first to see the System's workforce on any day in the past decade: headcount, FTE and vacancies by campus, unit and SUCSS family, with person, appointment and position toggles that never double-count. Drag the second to see how that picture was *revised* by later corrections. A "restatement ribbon" highlights every number that changed after it was first reported, and why. A natural-language box routes through the MCP-governed metric layer, answers only with governed metrics, and asks for clarification ("persons or appointments?") instead of guessing.

**Why it's new.** Commercial HR BI shows current state or snapshots. Platform time travel stops at 90 days or less and tracks system time, not business time. A two-axis bitemporal explorer for a university system's workforce, with grain-safe NL, has no public precedent that this research found.

**Builds on** 3.1, 3.2, 3.11, 3.12 and 3.13. **Effort** about 6–8 weeks.

### Demo 2: Role-Evolution and AI-Task-Exposure Map

**What the leader sees.** Every SUCSS class mapped, with evidence and review status, to O*NET-SOC and then down to O*NET task statements. Each task is overlaid with **Anthropic Economic Index** usage shares, released on Hugging Face under CC-BY with O*NET-task-level fields such as `onet_task_count` / `onet_task_pct` and several 2026 releases, so the *trend* across releases can be shown. The view is a graph: classes cluster by shared tasks. Colour shows the share of a class's task mix with observed AI usage, split into augmentation vs automation where the release provides it. Clicking a class shows:

- the tasks most and least exposed;
- adjacent classes by task overlap, which are candidate reskilling paths;
- headcount and time-varying survival curves from 3.7, so leaders see exposure next to actual turnover.

**Guardrails.** AEI measures *Claude usage patterns*, not job loss and not university work. The demo labels it as an "observed-usage signal" and does not forecast displacement. The crosswalk carries conformal prediction sets, and low-confidence mappings appear in grey with a review-queue badge.

**Why it's new.** AEI analyses are economy-wide. A crosswalk from a public university's civil-service class system (SUCSS) to O*NET tasks to AEI, with evidence spans and human adjudication, does not appear in public work found in this scan.

**Builds on** 3.3, 3.4, 3.7 and 3.10. **Effort** about 6–9 weeks.

Sources: [AEI R package (CRAN)](https://cran.r-project.org/web/packages/aieconindex/index.html), [AEI data documentation mirror](https://hugface-5b9.pages.dev/datasets/Anthropic/EconomicIndex/blob/main/release_2026_01_15/data_documentation.md?code=true). Verify against the official `huggingface.co/datasets/Anthropic/EconomicIndex`.

### Demo 3: Labor-Market Competitiveness Radar

**What the leader sees.** For each SUCSS family, a radar comparing the System with its local and peer labor markets on five axes:

1. **Pay position.** Internal pay-band midpoints vs **BLS OEWS** percentiles for the mapped SOC in Champaign-Urbana, Chicago and Springfield MSAs, and statewide.
2. **Peer pay.** **IPEDS HR** salary and staff counts for a defined peer set. IPEDS occupational categories now align with 2018 SOC, which makes the crosswalk tractable.
3. **Market churn.** **Census QWI** separations, hires and turnover for NAICS 611 and competing industries by county. The 2026Q1 release is out.
4. **Internal hazard.** Survival-model hazard by family (3.7).
5. **Time-to-fill.** From effective-dated position vacancies (3.1).

A "pressure index" flags families where internal pay lags the market *and* market churn is high *and* internal hazard is rising. Each flag shows its uncertainty band (conformal) and a fairness slice (3.9).

**Why it's new.** Compensation surveys such as CUPA-HR benchmark pay alone. Combining OEWS, IPEDS and QWI with internal bitemporal hazard into one per-class radar, reproducible from public data plus governed internal aggregates, is uncommon at the level of a university system.

**Builds on** 3.1, 3.3, 3.7, 3.9 and 3.10. **Effort** about 5–7 weeks. Public-data ingestion is about 1 week.

Sources: [QWI 2026Q1 release notice](https://content.govdelivery.com/accounts/USCENSUS/bulletins/40f1a0f), [QWI overview](https://datacatalog.med.nyu.edu/dataset/10147), [IPEDS HR 2025-26 package](https://nces.ed.gov/IPEDS/use-the-data/download-survey-material/2025/human%20resources/package_1_45.pdf). The OEWS release date was not verified in this research; check bls.gov/oes.

---

## 6. Recommended sequence (about 16–20 weeks part-time)

| Phase | Weeks | Deliverable | Proves |
|---|---|---|---|
| 0 | 1–2 | Synthetic HR generator, new labelled protocol, harness (3.6) | Fair referee exists |
| 1 | 3–6 | Bitemporal core, grain-typed semantic layer, contracts (3.1, 3.2, 3.11, 3.12) | As-of and grain wins vs A1/A2 |
| 2 | 7–9 | MCP metrics + Demo 1 (3.13) | Governed NL beats walled NL on policy and accuracy |
| 3 | 10–14 | Crosswalk + graph + conformal + Demo 2 (3.3, 3.4, 3.10) | Coverage @ precision with evidence |
| 4 | 15–20 | Survival, Markov, fairness + Demo 3 (3.7–3.9) | Better calibrated attrition and workforce projections |

## 7. Where custom will probably *not* win (state this up front)

- **Breadth and speed to a first answer.** Genie and Snowflake Intelligence go from table to chat in hours.
- **Security plumbing.** Row and column policies, lineage, SSO and audit come with the platform. Custom work should reuse them, not rebuild them.
- **Elastic scale and operations.** Serverless pipelines, monitoring and on-call.
- **Unstructured search at scale.** Cortex Search and Vector Search are mature. Custom only wins where local inference is mandatory.

The credible message for leadership: *"The platforms are the plumbing. The institution-specific intelligence (time, grain, crosswalks, uncertainty, fairness) is engineering we own, and it can run on either platform or on-prem."*

---

## 8. Source list (accessed 2026-11-06)

- Snowflake: [Cortex Analyst semantic model spec](https://docs.snowflake.com/user-guide/snowflake-cortex/cortex-analyst/semantic-model-spec) · [Cortex Agents](https://docs.snowflake.com/user-guide/snowflake-cortex/cortex-agents) · [AI Functions cost](https://docs.snowflake.com/en/user-guide/snowflake-cortex/aisql-cost) · [AI pricing](https://docs.snowflake.com/en/user-guide/snowflake-cortex/pricing) · [Time Travel](https://docs.snowflake.com/en/user-guide/data-time-travel) · [CTAS to Unity Catalog GA 2026-03-31](https://docs.snowflake.com/En/release-notes/2026/other/2026-03-31-ctas-unity-catalog-external-volumes) · [phData semantic views](https://www.phdata.io/blog/snowflake-semantic-views-real-world-insights-best-practices-and-phdatas-approach/) · [Coefficient: Intelligence cost 2026](https://coefficient.io/snowflake/snowflake-intelligence-cost)
- Databricks: [Genie](https://docs.databricks.com/genie/index.html) · [Genie best practices](https://docs.databricks.com/gcp/en/genie/best-practices) · [Production-ready Genie blog](https://www.databricks.com/en/blog/how-build-production-ready-genie-spaces-and-build-trust-along-way) · [Agent Bricks Information Extraction](https://docs.databricks.com/aws/en/generative-ai/agent-bricks/info-extraction) · [Iceberg external access](https://docs.databricks.com/gcp/external-access/iceberg) · [Semantics blog](https://www.databricks.com/blog/redefining-semantics-data-layer-future-bi-and-ai) · [Delta history forum](https://community.databricks.com/t5/warehousing-analytics/dela-table-and-history/td-p/110710) · [dbt-databricks #1106](https://github.com/databricks/dbt-databricks/issues/1106) · [Addepto Genie review](https://addepto.com/blog/databricks-genie-pricing-capabilities-and-roi-requirements/)
- Open source: [vLLM structured outputs](https://docs.vllm.ai/en/latest/features/structured_outputs/) · [MAPIE](https://github.com/scikit-learn-contrib/MAPIE) · [LadybugDB](https://pypi.org/project/real_ladybug/) · [Kùzu archive note](https://www.freshports.org/databases/kuzu/) · [dbt MCP server](https://docs.getdbt.com/blog/introducing-dbt-mcp-server) · [Atlan: dbt MCP gaps](https://atlan.com/know/mcp/mcp-server-for-dbt/) · [Atlan: UC semantic layer](https://atlan.com/know/ai-agent/semantic-layer/unity-catalog-semantic-layer/) · [Iceberg catalogs, June 2026](https://dev.to/alexmercedcoder/the-state-of-apache-iceberg-catalogs-in-june-2026-265e)
- Public labor data: [Anthropic Economic Index (CRAN accessor)](https://cran.r-project.org/web/packages/aieconindex/index.html) · [QWI 2026Q1 notice](https://content.govdelivery.com/accounts/USCENSUS/bulletins/40f1a0f) · [IPEDS HR 2025-26 materials](https://nces.ed.gov/IPEDS/use-the-data/download-survey-material/2025/human%20resources/package_1_45.pdf)
- Named but not separately verified in this research run (stable, well-known projects): lifelines, scikit-survival, Fairlearn, Aequitas, dbt contracts, Soda, Great Expectations, Pandera, Cube, boring-semantic-layer, DuckPGQ, Neo4j, Ollama, llama.cpp, BLS OEWS, O*NET database.

**Verification flags:**
- Databricks managed-Iceberg GA vs Public Preview: sources conflict.
- Delta time-travel retention enforcement: changed in 2025–26, per a community post.
- Snowflake AI Credit dollar rate: third-party figure.
- The Genie limit of about 500 benchmark questions: third-party figure.
- OSI shipping status: single commercial source.
