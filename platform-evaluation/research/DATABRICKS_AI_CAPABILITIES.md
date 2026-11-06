# Databricks AI/ML and Data Engineering Capabilities: A Critical Review for HR/ERP Analytics

**Research date:** 2026-11-06
**Prepared for:** University of Illinois System AITS team comparing Databricks and Snowflake for HR/ERP workforce analytics
**Scope:** Capabilities as they stand in November 2026, with release status, how each fits HR use cases, limitations, and open-source alternatives.

---

## 0. Method and confidence

- **How the research was done.** The research used web search over docs.databricks.com, databricks.com (blog, newsroom, pricing), community.databricks.com, and the Azure Databricks mirror on learn.microsoft.com. **Direct page fetches of docs.databricks.com and learn.microsoft.com were blocked in this research environment.** Statuses below therefore come from search-indexed excerpts of those primary pages, not from reading each page in full. Before procurement, re-check every status line against the live release notes: https://docs.databricks.com/aws/en/release-notes/product
- **Status labels used here:**
  - **GA (verified):** a Databricks primary source (docs, blog, newsroom, or official community announcement) states GA.
  - **GA (secondary):** only a third-party recap states GA.
  - **Preview / Beta:** as labelled in the docs.
  - **UNVERIFIED:** no current status could be confirmed.
- **Status varies by cloud and region.** The AWS, Azure, and GCP doc sets often disagree on dates, and Databricks warns that account rollouts can lag a release by a week or more. AWS GovCloud and compliance-profile workspaces usually get features later.
- **Naming has changed a great deal in 2025–2026.** These renames are reflected throughout:
  - Databricks Assistant became **Genie Code** (March 2026).
  - Lakehouse Monitoring became **Data Quality Monitoring**, which has two parts: data profiling and anomaly detection.
  - DLT became **Lakeflow (Spark) Declarative Pipelines**. The engine was contributed to Apache Spark as "Spark Declarative Pipelines".
  - Workflows became **Lakeflow Jobs**.
  - Mosaic AI Gateway became **Unity AI Gateway / "Unity Gateway"**.
  - The Vector Search cost pages now also appear under an **"AI Search"** name.
  - Genie now spans **Genie One, Genie Agents, and Genie Code**.

---

## 1. Executive status table

| Capability | Current status (Nov 2026) | Key date | Confidence |
|---|---|---|---|
| `ai_query` | GA for batch inference on Databricks-hosted models; earlier batch guidance was Public Preview | DBR 15.4 LTS minimum | Medium |
| `ai_classify`, `ai_extract` (v2 signatures) | **GA** | 2026-06-11 (Azure release notes); v2 was Public Preview on 2026-03-27 | High |
| `ai_parse_document` | Widely available, default-on for compliance-security-profile workspaces from 2026-05-13. FILE-column input is still Beta in some doc versions. Overall GA date not found | 2026-05-13 | Medium–Low |
| `ai_forecast` | **UNVERIFIED** (historically Public Preview) | – | Low |
| AI/BI Dashboards | GA (since 2024) | – | High |
| Genie One / Genie Agents / Genie Code | **GA** | 2026-06-16 press release | High |
| Genie App Builder, Genie ZeroOps | Private preview | post-DAIS 2026 | High |
| Genie One MCP server | GA; old Beta endpoint sunset 2026-10-31 | Sept 2026 | High |
| Genie in Teams (Beta) / Slack (Public Preview) | Preview | June 2026 | Medium |
| Agent Bricks: Knowledge Assistant, Supervisor Agent | **GA** (official community announcements) | early 2026 | High |
| Agent Bricks: Information Extraction / "Document Intelligence" | Beta in Azure docs; GA claimed only by a secondary source | – | Low |
| Mosaic AI Agent Framework (ResponsesAgent) | GA (secondary source: "early 2026") | – | Medium |
| Managed agent memory and sessions | Beta | Sept 2026 (GCP notes) | Medium |
| MLflow 3 GenAI eval and tracing | Shipping (`mlflow[databricks]>=3.1`); production monitoring is **Beta** | – | Medium |
| Vector Search (Standard and Storage-Optimized) | Standard is GA. Storage-optimized was announced; its GA status is unverified | – | Medium |
| `ai_search` over Lakebase synced tables | Beta | Sept 2026 | Medium |
| Foundation Model APIs (pay-per-token, provisioned throughput, priority) | GA (pay-per-token and provisioned throughput). Priority mode is newer | – | High |
| Unity AI Gateway | **Conflicting:** Beta on AWS docs, GA on GCP docs, Public Preview on GovCloud | Apr–Jun 2026 | Low |
| Lakeflow Connect | GA for many connectors. Zerobus Ingest is Public Preview | – | High |
| Workday Reports / Workday HCM connectors | Documented; the per-connector GA flag was not confirmed | – | Medium |
| Lakeflow Declarative Pipelines, Lakeflow Jobs | GA | – | High |
| Lakeflow Designer | Available (now also in Free Edition); GA flag unverified | – | Low |
| Lakebase Postgres (Autoscaling) | **GA:** AWS (early 2026), Azure (Mar 2026), GCP (~2026-11-02, secondary source) | – | Medium–High |
| Databricks Apps | Available, billed per hour. Some docs still require admin enablement via Previews | – | Medium |
| UC ABAC, governed tags, data classification | **GA** (Databricks blog) | ~May 2026 | High |
| ABAC on views | Public Preview | Sept 2026 | Medium |
| UC metric views | Core feature. Local metric views GA Aug 2026. Parameters in Public Preview (June 2026) | – | Medium |
| Feature Store / online tables | Legacy online tables **retired** (cutoff late 2025 / Jan 2026). Replacement is the Lakebase-backed Online Feature Store | – | High |
| AutoML | **Deprecated.** Removed from DBR 18.0 ML. Serverless forecasting reportedly still Public Preview | – | High (deprecation) |
| Data Quality Monitoring | Data profiling GA. Anomaly detection Beta on some clouds | – | Medium |
| Delta Sharing / Marketplace | GA | – | High |
| Clean Rooms | GA (AWS/Azure Feb 2025, GCP summer 2025) | – | High |
| Managed MCP servers (UC functions, Vector Search, Genie) | Beta in docs (Genie One MCP now GA) | – | Medium |

---

## 2. Capability-by-capability analysis

HR use cases referenced below:

- **(H)** headcount
- **(A)** attrition
- **(S)** succession
- **(O)** job-classification mapping to O*NET
- **(P)** job-posting text extraction
- **(E)** pay equity
- **(Q)** HR policy question answering

### 2.1 AI Functions (`ai_query`, `ai_classify`, `ai_extract`, `ai_parse_document`, `ai_forecast`, and others)

**What it does.** These are SQL and PySpark functions that call LLMs or task models from a query.

- `ai_query`: a general prompt to any serving endpoint.
- `ai_classify`: assigns labels you supply; supports multi-label output.
- `ai_extract`: pulls fields into a schema you provide.
- `ai_parse_document`: converts PDFs and scans into layout-aware text.
- `ai_forecast`: a table-valued time-series projection.

**HR use.**
- **(O)** `ai_classify` can map university job titles and descriptions to O*NET-SOC codes or job families.
- **(P)** `ai_parse_document` followed by `ai_extract` can turn posting PDFs into fields such as minimum qualifications, salary range, FTE, and union status.
- **(Q)** `ai_parse_document` can chunk the HR policy manual for retrieval.
- **(H)** `ai_forecast` can project headcount by unit.

**Limitations.**
- **Cost is billed in two places.** The warehouse or cluster is billed, and model inference is billed separately under the `AI_FUNCTIONS` / `BATCH_INFERENCE` product types. Costs are only visible after the fact, in system billing tables.
- **Model and region limits.** Docs recommend the `databricks-`-hosted endpoints for batch work; other hosted models are "not recommended for large production batch". Some functions are region-limited.
- **No built-in quality metrics.** `ai_classify` gives no calibrated confidence, so mapping to 1,000+ O*NET codes needs a retrieval-then-rerank design and a human-labelled gold set, not a single call.
- **Status gaps.** `ai_forecast` status is unverified. The FILE input of `ai_parse_document` is still Beta in some doc versions.
- **Data leaves the workspace boundary unless restricted.** Requests go to Databricks-hosted (or external) models. Whether a function's model runs in-geo must be confirmed per function.

**Open-source replication.**
- Run DuckDB or Polars user-defined functions that call a local **vLLM** or **Ollama** endpoint, with structured output enforced by **Outlines**, **XGrammar**, or **Instructor** with Pydantic schemas.
- For parsing, use **Docling**, **Marker**, **Unstructured**, or **PaddleOCR**.
- For O*NET mapping, embed O*NET occupation titles and task statements with **sentence-transformers** (for example bge or e5), retrieve the top-k candidates, then let an LLM pick among them with a constrained choice. This is typically more accurate and auditable than a one-shot `ai_classify` over the full taxonomy.
- For forecasting, use **statsforecast**, **Prophet**, or **Darts**.
- This approach keeps institutional data fully on-prem, which `ai_*` cannot guarantee.

### 2.2 Genie (Genie One, Genie spaces, Genie Agents, Genie Code) and AI/BI Dashboards

**What it does.**
- **AI/BI Dashboards (GA):** low-code dashboards that run on SQL warehouses.
- **Genie spaces:** curated natural-language-to-SQL rooms over up to **30 tables or views per space** (a hard limit), with instructions and "trusted assets" (verified SQL functions and example queries).
- **Genie One (GA, June 16, 2026):** a business-user "agentic coworker" across data. **Genie Ontology** extracts business context continuously.
- **Genie Agents (GA):** turn conversations into reusable agents.
- **Genie Code (GA):** replaced Databricks Assistant in March 2026. It has Chat and **Agent mode** (the default); in Agent mode it asks approval before running code or editing tables.

**HR use.**
- **(H/A/E)** A Genie space over curated `fact_headcount`, `fact_separations`, and `dim_position` tables, backed by metric views. HR business partners can ask "voluntary attrition rate for Urbana tenure-track faculty, FY24 vs FY25".
- Trusted assets can pin the official attrition and FTE definitions.
- Genie Code helps engineers write the pipelines.

**Limitations.**
- **Accuracy depends on curation.** Databricks publishes no accuracy benchmark. Text-to-SQL can silently pick a wrong join or filter, which is dangerous for pay-equity numbers. Benchmarks and trusted assets are mandatory, not optional.
- **Small-cell disclosure.** Natural-language access to row-level HR data can return small groups (n<5) by demographic. Genie has no built-in suppression, so ABAC, aggregate-only views, or metric views must enforce it.
- **Pricing is changing.** Per Azure docs, user usage of Genie One and Genie Agents is free through Jan 31, 2027 (another Databricks page said July 31, 2026). After that it is consumption-based, with a ~150 DBU/user/month allowance; the "$10 free per user" figure comes from the press release. Service principals are billed. The SQL warehouse is always billed separately.
- **Preview channels.** Teams (Beta) and Slack (Public Preview) integrations are still preview. App Builder and ZeroOps are private preview.

**Open-source replication.**
- **Dashboards:** **Evidence.dev**, **Streamlit**, **Apache Superset**, or **Metabase** on **DuckDB** or Postgres.
- **Natural-language-to-SQL:** **Vanna.ai**, or a custom LangGraph or PydanticAI agent constrained to a semantic layer (**dbt Semantic Layer / MetricFlow**, **Cube**), with a local LLM via vLLM.
- **Grounding:** a fixed question-SQL benchmark set in pytest. An independent engineer can enforce small-cell suppression and "metric-only" query paths more strictly than Genie's default.
- **Genie Code:** comparable to an IDE plus a coding agent.

### 2.3 Mosaic AI Agent Framework and Agent Bricks

**What it does.**
- **Agent Framework:** an MLflow `ResponsesAgent` interface for authoring agents (any framework, such as LangGraph or OpenAI SDK), deployable to Model Serving or **Databricks Apps**.
- **Agent Bricks:** declarative, auto-optimized agents.
  - **Knowledge Assistant (GA):** retrieval Q&A over documents.
  - **Supervisor Agent (GA):** routes across Genie spaces, Knowledge Assistants, and MCP servers.
  - **Information Extraction:** Beta per Azure docs. A secondary source says "Document Intelligence" is GA.
- **Managed agent memory and sessions:** Beta (Sept 2026).
- Agent Bricks first launched as Beta on June 11, 2025. Recaps claim 100k+ agents built.

**HR use.**
- **(Q)** A Knowledge Assistant over HR policies, the Civil Service rules (SUCSS), and benefits documents, with citations.
- A Supervisor Agent combining policy Q&A with Genie headcount answers.
- **(P)** Information Extraction for job postings.

**Limitations.**
- **Opaque optimization.** "Auto-optimization" uses LLM judges and synthetic data. It conflicts with protocols that forbid model-graded evaluation, and the tuned prompts and model choices are not fully transparent.
- **Lock-in.** Agents depend on UC, Vector Search, Model Serving, and MLflow-on-Databricks.
- **Preview components.** Memory and Information Extraction are preview.
- **Free Edition.** Agent Bricks was added to Free Edition in June 2026, but mirror pages disagree on support. Verify before relying on it.

**Open-source replication.**
- **Orchestration:** **LangGraph**, **PydanticAI**, or **LlamaIndex**.
- **Retrieval:** **pgvector**, **LanceDB**, or **Qdrant**.
- **Serving and embeddings:** **vLLM** with sentence-transformers embeddings, plus a reranker (bge-reranker).
- **Tracing:** **MLflow OSS** tracing, or **Langfuse** / **Arize Phoenix**.
- **UI:** Streamlit or Chainlit.
- Explicit, versioned prompts and human-labelled evaluation are achievable and more auditable than Agent Bricks' auto-tuning.

### 2.4 Agent Evaluation, MLflow 3 GenAI evaluation, and tracing

**What it does.**
- `mlflow.genai.evaluate()` runs built-in and custom LLM judges (correctness, relevance, safety, retrieval groundedness), evaluation datasets, and human labelling sessions.
- MLflow Tracing captures each step.
- Production monitoring runs scorers on live traces (**Beta**).
- The Agent Evaluation SDK has merged into `mlflow[databricks]>=3.1`.

**HR use.**
- Regression-test the HR policy assistant against a SME-labelled question set.
- Trace which policy chunk answered each question, for audit.

**Limitations.**
- **Judge bias.** Built-in judges are LLM-as-judge, with known bias and drift. They are not a substitute for human-labelled ground truth, and under this project's rules ("no model grades another model") they cannot be the published metric.
- **Managed features are Databricks-only.** Some features (labelling UI, managed monitoring) exist only in managed MLflow.

**Open-source replication.**
- **MLflow OSS 3.x** includes tracing and `genai.evaluate` (judges are optional; deterministic scorers are supported).
- Alternatives: **Langfuse**, **Arize Phoenix**, **promptfoo**, **DeepEval**, or **Ragas** (use deterministic and reference-based metrics only).
- **Label Studio** or **Argilla** for human labels.
- This parity is high. MLflow is Databricks' own open-source project.

### 2.5 Vector Search (also surfaced as "AI Search")

**What it does.** A managed vector index synced from Delta tables, with hybrid keyword and vector search. There are two endpoint types:

| Endpoint type | Capacity per unit (from docs) | Hourly rate (unverified third-party figures) |
|---|---|---|
| **Standard** | ~2M 768-dimension vectors | ~$0.28/hr |
| **Storage-Optimized** | up to ~64M 768-dimension vectors | ~$1.28/hr |

`ai_search` over Lakebase synced tables is in Beta.

**HR use.**
- **(Q)** Policy retrieval.
- **(O)** Nearest-neighbour matching of position descriptions to O*NET task statements.
- **(S)** Skills-similarity search for succession candidates. This needs strong governance.

**Limitations.**
- **Always-on billing.** Endpoints bill hourly, with no scale-to-zero, which is costly for small HR corpora.
- **MCP restriction.** The managed MCP Vector Search server supports only indexes with Databricks-managed embeddings.
- **Overkill at HR scale.** HR document corpora (thousands of documents) do not need billion-scale infrastructure.

**Open-source replication.**
- **pgvector** in existing Postgres, **LanceDB** (embedded, file-based), **DuckDB VSS**, or **Qdrant**.
- **sentence-transformers** embeddings run locally.
- At HR scale these are effectively free and fully on-prem.

### 2.6 Model Serving, Foundation Model APIs, and Unity AI Gateway

**What it does.**
- **Model Serving:** hosts custom MLflow models and agents.
- **Foundation Model APIs:**
  - Pay-per-token, priced in DBU per million tokens. Example from the pricing page: Llama 4 Maverick at 7.143 DBU/M input and 21.429 DBU/M output, about $0.50 / $1.50 at $0.07/DBU (third-party conversion).
  - Provisioned throughput, priced in DBU per hour.
  - A newer priority pay-per-token tier at a higher rate.
  - External models (OpenAI, Anthropic, and others) can be proxied.
- **Unity AI Gateway:** extends UC to model and MCP traffic with rate limits, spend tracking, guardrails, usage logging, and policies. Partners include CrowdStrike, Palo Alto Networks, Zscaler, Okta, SailPoint, and Cyera.

**HR use.** Serve an attrition-risk model, if it is ethically approved. Govern all LLM calls from HR apps with per-group rate limits and payload logging for audit.

**Limitations.**
- **Cost opacity.** The DBU-to-token conversion varies by model, region, and contract. Provisioned-throughput units have model-dependent throughput.
- **Data residency.** Pay-per-token models may be hosted cross-region or by partners; check per model.
- **Gateway status conflicts.** AI Gateway is Beta on AWS docs, GA on GCP, and Public Preview on GovCloud.
- **Payload logging creates a new store of sensitive data.** Logged prompts and responses about named employees become sensitive HR data, which must be governed and retained accordingly.

**Open-source replication.**
- **Serving:** **vLLM**, **SGLang**, **Ollama**, or **llama.cpp** on university GPUs.
- **Gateway:** **LiteLLM Proxy** (rate limits, budgets, logging) or **Envoy AI Gateway**.
- **Classic ML serving:** BentoML, or MLflow OSS `mlflow models serve`.
- Per-token cost becomes the cost of owning GPUs: predictable, but capacity-bound.

### 2.7 Lakeflow: Connect, Declarative Pipelines (formerly DLT), Jobs, and Designer

**What it does.**
- **Lakeflow Connect:** managed ingestion from databases, SaaS apps, files, and streams. Zerobus Ingest is Public Preview. Data-freshness monitoring for database connectors is Public Preview (Oct 2026).
- **Workday connectors.** Two exist:
  - *Workday Reports* (RaaS): custom and tenant fields allowed.
  - *Workday HCM*: raw workforce and payroll objects, no report configuration needed.
- **Lakeflow (Spark) Declarative Pipelines:** declarative batch and streaming tables with expectations (data-quality rules). The engine is now in Apache Spark as Spark Declarative Pipelines.
- **Lakeflow Jobs:** orchestration. Pipeline system tables went GA in Oct 2026.
- **Lakeflow Designer:** drag-and-drop or natural-language data prep that produces governed code.

**HR use.** Ingest Workday or Banner HR and payroll data, then build SCD2 position and job history tables, which support **(H/A/S)** point-in-time headcount and turnover cohorts. Use expectations to enforce "every active employee has exactly one primary position". (Note: the U of I System runs Banner HR, so confirm whether a managed Banner/Oracle connector or a JDBC/Oracle CDC path applies; no Banner-specific connector was found.)

**Limitations.**
- **Workday Reports connector:**
  - Full refresh only, no incremental.
  - Reports must be under 2 GB or under 1M records.
  - Duplicate primary keys are rejected.
  - Recommended maximum of 250 reports per pipeline.
  - One doc page says the pipeline is API-only to create.
- **Managed connectors bill serverless DBUs** per run.
- **Lock-in.** Declarative Pipelines semantics are now open in Spark, but the expectations UI, serverless pipelines, and Designer are Databricks-only.

**Open-source replication.**
- **Ingestion:** **dlt (dlthub)**, **Airbyte**, or **Meltano/Singer** for Workday RaaS and Oracle; **Debezium** for CDC.
- **Transformation:** **dbt-core** (snapshots for SCD2, tests) on **DuckDB** or Postgres, or **SQLMesh**.
- **Dataframes:** **Polars**.
- **Orchestration:** **Dagster**, with asset lineage and freshness checks, or **Prefect**.
- **Data quality:** **Great Expectations**, **Soda Core**, or **Pandera**.

### 2.8 Lakebase (managed Postgres)

**What it does.** Serverless Postgres (16/17) with autoscaling, scale-to-zero, instant copy-on-write branching, point-in-time recovery, UC governance, and "synced tables" from Delta.

- GA on AWS (early 2026) and on Azure (March 2026).
- GA on GCP around 2026-11-02 per a secondary source; this is unverified.
- New instances are "Autoscaling projects" (rollout from 2026-03-12). "Provisioned" is the older model.
- Inbound Private Link went GA June 2026.

**HR use.** The backing store for a Databricks App, for example a job-classification review workflow where analysts approve O*NET mappings. It also serves low-latency lookups and pgvector-style retrieval.

**Limitations.**
- **Young product.** The release-note dates conflict (GA vs. "Beta" dates for different variants).
- **Free Edition.** One project only, with database instances unsupported.
- **Proprietary branching.** The branching is Databricks' implementation, from the Neon acquisition.

**Open-source replication.** Self-hosted or campus **PostgreSQL** with pgvector; **Neon** OSS or **Supabase** for branching; **pgBackRest** for PITR. These are mature and inexpensive.

### 2.9 Databricks Apps

**What it does.** Hosts Streamlit, Dash, Gradio, Flask, or Node apps inside the workspace with UC auth.

| Size | vCPUs | Memory | Billing |
|---|---|---|---|
| Medium (default) | 2 | 6 GB | 0.5 DBU/hr |
| Large | 4 | 12 GB | 1 DBU/hr |

Apps are billed for uptime, not per request. A custom MCP server can be hosted as an App.

**HR use.** An internal app for HR analysts, such as a pay-equity cohort explorer or a job-mapping review queue, with SSO and row-level policies inherited from UC.

**Limitations.**
- **Idle cost.** Uptime billing is wasteful for low-traffic internal tools.
- **Workspace caps.** There is a per-workspace app cap.
- **Tier restriction.** Not supported in Azure Standard tier.
- **Free Edition.** Apps stop after 24 hours, with a maximum of 3.
- **Enablement.** Some docs still describe enabling Apps via the Previews page.

**Open-source replication.** **Streamlit**, **Evidence.dev**, **Shiny for Python**, or **NiceGUI**, deployed on campus Kubernetes or a VM behind Shibboleth/Entra SSO.

### 2.10 Unity Catalog: lineage, ABAC, governed tags, data classification, metric views

**What it does.**
- **Lineage:** column-level lineage across notebooks, jobs, and dashboards.
- **ABAC (GA, ~May 2026):** row filters and column masks driven by **governed tags**, so one policy covers many tables. ABAC on views is Public Preview (Sept 2026).
- **Data classification (GA):** an AI agent continuously tags PII and regulated data. Tag families include PII, GDPR, HIPAA, GLBA, and DPDPA.
- **Metric views:** YAML-defined measures queried with `MEASURE()`, consumed by dashboards, Genie, alerts, Power BI, and Tableau.
  - Local metric views GA Aug 2026.
  - Parameters in Public Preview.
  - Metric views cannot be Delta Shared or profiled.
  - Joins must be defined in the YAML.
  - `SELECT *` is not supported.
- **Discover page and domains:** GA (Oct 2026).

**HR use.**
- **(E)** Mask SSN, DOB, and base salary except for the compensation-analytics group.
- Row-filter by college or unit for HR business partners.
- **(H/A)** Define "Headcount (FTE)", "Voluntary Turnover Rate", and "Time-to-Fill" once as metric views, so Genie and dashboards agree.
- Data classification can find PII in newly landed Workday extracts.

**Limitations.**
- **No FERPA tag family.** Classification tag families do not include FERPA. Student-employee records (graduate assistants, student hourly workers) carry FERPA overlap, so custom tags and rules are needed.
- **Classification is probabilistic.** Treat it as discovery, not a control.
- **Lock-in.** ABAC and metric views are Databricks-specific. UC OSS exists, but these features are not in it.

**Open-source replication.**
- **Lineage:** **OpenLineage + Marquez**, or dbt docs lineage, or **DataHub** / **OpenMetadata** (which also cover tags and classification).
- **Access control:** Postgres RLS and column privileges, or **Apache Ranger**.
- **Metrics:** **dbt MetricFlow** or **Cube**.
- **PII scanning:** **Microsoft Presidio**.
- This is achievable, but takes notable integration effort. UC's single control plane is a genuine strength.

### 2.11 Feature Store, online tables, and AutoML

**What it does.**
- **Feature Store:** UC feature tables with point-in-time joins.
- **Online tables are retired.** The legacy online tables were retired (cutoff dates cited as Nov 11, 2025 or Jan 15, 2026). Replacements are the **Online Feature Store on Lakebase** or Lakebase synced tables.
- **AutoML is deprecated.** It was removed from DBR 18.0 ML. Databricks points users to the Data Science Agent (Beta) and AI Functions. Serverless forecasting is reportedly still Public Preview (forum source only).

**HR use.** **(A)** Point-in-time-correct attrition features (tenure, last raise, supervisor changes) without leakage.

**Limitations.**
- **Churn.** Deprecations and migrations (online tables, AutoML) show this area changes quickly.
- **Ethics.** Individual attrition-risk scoring is ethically and legally sensitive. It needs adverse-impact testing, which no Databricks feature provides out of the box.

**Open-source replication.**
- **Features:** **Feast** (with Postgres or Redis online store), or plain dbt tables with `as_of` joins in DuckDB.
- **AutoML:** **FLAML**, **AutoGluon**, or scikit-learn with Optuna.
- **Explainability:** **SHAP**.
- **Fairness:** **Fairlearn** for adverse-impact and pay-equity checks.

### 2.12 Data Quality Monitoring (formerly Lakehouse Monitoring)

**What it does.**
- **Data profiling:** profile and drift metrics stored in metric tables. This is the former Lakehouse Monitoring.
- **Anomaly detection:** freshness and completeness checks that predict expected row counts, enabled per schema. It does not support views and is Beta on some clouds.
- Monitoring does not modify the monitored tables.

**HR use.** Alert when the biweekly payroll extract arrives late or with 30% fewer rows. Detect drift in the job-code distribution after a reorganization.

**Limitations.**
- Anomaly detection is Beta on some clouds.
- The heuristics are row-count and freshness only. Business-rule checks still need expectations or SQL alerts.
- Each run costs serverless compute.

**Open-source replication.** **Evidently** for drift; **Great Expectations**, **Soda Core**, or **dbt tests / dbt-expectations**; **Elementary** for dbt anomaly detection; Dagster freshness policies.

### 2.13 Delta Sharing, Marketplace, and Clean Rooms

**What it does.**
- **Delta Sharing:** an open protocol for sharing tables, views, volumes, and models across platforms. It adds OIDC token federation, cross-platform view sharing, and Iceberg sharing (preview in 2025).
- **Marketplace:** distributes data products.
- **Clean Rooms (GA):** run governed joint computation on shared data on serverless compute, with HIPAA support. Per a forum post, the per-collaborator fee was dropped in Jan 2026 (unverified). AWS Clean Rooms gained Databricks as a data source in Oct 2026.

**HR use.**
- Share aggregated workforce metrics with the System Office or Illinois state reporting.
- Peer salary benchmarking (for example CUPA-HR-style comparisons) via a clean room without exposing row-level pay.

**Limitations.** Clean rooms need all parties on Databricks (or AWS Clean Rooms). Peer institutions on Snowflake would use Snowflake's own clean rooms.

**Open-source replication.**
- The **Delta Sharing protocol and server are open source**.
- Alternatives: Parquet or Iceberg exports to S3 with signed URLs.
- For privacy-preserving benchmarking: aggregate-only exports with k-anonymity and small-cell suppression, or **OpenDP** differential privacy.

### 2.14 MCP support

**What it does.**
- **Managed MCP servers:** UC functions (including the `system.ai` Python interpreter), Vector Search, Genie (read-only; no conversation history passed), and DBSQL. These are Beta in docs.
- **Genie One MCP:** GA (Sept 2026); the old endpoint sunset 2026-10-31.
- **External MCP servers:** proxied with UC-connection OAuth.
- **Custom MCP:** hosted on Databricks Apps.
- **Governance:** UC permissions and the Unity AI Gateway govern MCP traffic.

**HR use.** Let an approved desktop assistant query aggregate HR metric views through the Genie MCP, with UC enforcing masks.

**Limitations.**
- Beta status, and endpoint churn (the Genie MCP endpoint was deprecated within months).
- Connecting external assistants to HR data needs a data-use review, especially where the external assistant's model is hosted by a third party.

**Open-source replication.** The MCP Python/TS SDKs or **FastMCP** over DuckDB or Postgres, with read-only roles; LiteLLM or an MCP gateway for logging.

### 2.15 Free Edition limits

Source: the Databricks Free Edition limitations page (via Azure mirror excerpts) and the June 17, 2026 blog post.

**What is included.**
- Serverless compute only, with a fair-usage policy. If the limit is exceeded, compute shuts off for the rest of the day, or the month in extreme cases.
- One SQL warehouse, 2X-Small only.
- At most 5 concurrent job tasks.
- At most 3 Apps, which auto-stop after 24 hours.
- One active pipeline per type.
- One Lakebase project.
- One workspace and one metastore.
- June 2026 additions: Genie Code, serverless GPUs, Lakebase, Lakeflow Designer, and Agent Bricks. LinkedIn verification unlocks limited serverless GPU and outbound internet access.

**What is not included.**
- **No SSO or SCIM.** Sign-in is email OTP or Microsoft only.
- No R or Scala.
- No online tables.
- No custom storage.
- No legacy features.
- No Lakebase database instances.
- Restricted outbound internet.
- **No SLA.**
- **No commercial use.**

**Implication.** Free Edition is suitable only for a skills sandbox with **synthetic or public data** (for example O*NET and BLS OEWS). It must never hold institutional HR data: no SSO, no SLA, no BAA or DPA, and no commercial or production terms.

### 2.16 Pricing model for AI

**How it is billed.** Everything is in **DBUs** at a per-SKU dollar rate that depends on cloud, tier, region, and commitment:

- **AI Functions and batch inference:** compute DBUs plus `AI_FUNCTIONS` / `BATCH_INFERENCE` DBUs.
- **Foundation Model APIs:** DBU per million tokens (pay-per-token), DBU per hour (provisioned throughput), or a priority tier.
- **Vector Search:** units per hour plus storage.
- **Apps:** 0.5–1 DBU per hour of uptime.
- **Genie One:** consumption-based after the promotion. Users are free until the promo ends (Jan 31, 2027 per Azure docs), with a ~150 DBU/user/month allowance. Service principals are billed.
- **Genie Code:** pay-as-you-go with its own promotion.
- **Lakebase:** compute units plus storage.
- **SQL warehouses:** always billed separately.

**The main risk is cost opacity across many SKUs.** Mitigations:
- Budget policies and tags.
- `system.billing.usage` dashboards.
- Hard rate limits via the AI Gateway.
- Modelling cost per HR question answered before rollout.

### 2.17 Compliance posture (public-university HR context)

| Regime | Databricks posture (as found) | University implication |
|---|---|---|
| **HIPAA** | Supported via the **compliance security profile**. Enabling it accepts Databricks' BAA if none is separately signed. On Azure, the profile becomes **required for HIPAA data from 2026-09-01** (one Azure page; another says "recommended") | HR holds PHI-adjacent data (FMLA, ADA accommodations, self-funded health plan files). Use a compliance-profile workspace. Note that some features arrive late there (for example `ai_parse_document` default-on only from May 2026) |
| **FedRAMP** | Moderate on AWS US East-1; **High on AWS GovCloud** (authorized) | Relevant for federally funded research HR data. GovCloud lags on features |
| **FERPA** | **No Databricks FERPA attestation found.** FERPA has no certification; the institution remains responsible. Tooling (UC ABAC, audit logs, encryption) supports compliance | Student-employee records need FERPA-aware tags and policies. Obtain a DPA and the university's "school official" contract language |
| **StateRAMP / TX-RAMP, Illinois-specific** | **Not found** (unverified) | Check with Illinois procurement and the University's security office. Illinois BIPA, PIPA, and the Illinois State Records Act apply to retention |
| **GLBA** | Classification tags include GLBA | Relevant to financial-aid-adjacent payroll data |
| SOC 2 / ISO 27001 | Standard for the platform (from the Databricks trust center; not re-verified here) | Request current reports under NDA |

AI-specific compliance concerns:
- Where each hosted foundation model is processed, including partner-hosted models.
- Retention of AI Gateway payload logs.
- Whether Genie and the Assistant send metadata or samples to model providers.

Request written confirmations for all three.

---

## 3. Build-vs-buy summary for an independent engineer

| Databricks capability | OSS / custom stack that matches or exceeds it at university HR scale | Where Databricks clearly wins |
|---|---|---|
| AI Functions | DuckDB/Polars + vLLM/Ollama + Outlines/Instructor + Docling | Zero-ops scaling over billions of rows; SQL-native |
| Genie / AI/BI | Evidence.dev/Superset + dbt MetricFlow/Cube + Vanna or custom agent | Integrated governance; business-user polish |
| Agent Bricks / Agent Framework | LangGraph/PydanticAI + pgvector/LanceDB + vLLM | Managed deployment, UC-governed tools |
| MLflow 3 eval/tracing | MLflow OSS / Langfuse / Phoenix + Label Studio | Managed labelling UI; tight integration |
| Vector Search | pgvector, LanceDB, Qdrant | Billion-scale; Delta auto-sync |
| Model Serving / AI Gateway | vLLM + LiteLLM Proxy | Elastic GPU capacity; partner models in one bill |
| Lakeflow Connect | dlt/Airbyte/Debezium | Managed Workday HCM connector |
| Declarative Pipelines / Jobs | dbt/SQLMesh + Dagster/Prefect | Unified streaming + batch, serverless |
| Lakebase | Postgres + pgvector (+ Neon for branching) | Delta↔Postgres synced tables |
| Apps | Streamlit/Shiny on campus k8s | SSO + UC auth with zero setup |
| UC (lineage, ABAC, tags, classification, metrics) | OpenMetadata/DataHub + OpenLineage + Postgres RLS + Presidio + MetricFlow | **Single governance plane: hardest to replicate** |
| Feature Store / AutoML | Feast, FLAML/AutoGluon, Fairlearn | Point-in-time joins integrated with UC |
| Data quality monitoring | Great Expectations/Soda + Evidently + Elementary | Auto-profiling with no config |
| Delta Sharing / Clean Rooms | Open Delta Sharing server; aggregate exports with OpenDP | Cross-org clean rooms |

**Bottom line.** For HR workforce analytics at U of I System scale (tens of thousands of employees, millions of rows, thousands of documents), the data volume does not require a lakehouse.

- **A skilled engineer can match most features.** Use DuckDB/Postgres + dbt + Dagster + local vLLM + pgvector + Evidence/Streamlit.
- **On-prem inference keeps institutional data in-house,** which is an advantage over the managed platform.
- **Databricks' real differentiators:**
  - Unity Catalog's unified governance (ABAC, lineage, classification, metric views feeding Genie).
  - Managed Workday connectors.
  - Reduced operational staffing.
- **Its real risks:**
  - DBU cost opacity across many SKUs.
  - Fast product churn (renames, deprecations of online tables, AutoML, and the Genie MCP endpoint).
  - Many AI features still Beta/Preview, often later in compliance-profile and GovCloud workspaces.
  - LLM-judge-centric evaluation tooling.

---

## 4. Items explicitly unverified (check before relying on them)

1. Overall GA date of `ai_parse_document`, and current status of `ai_forecast`.
2. GA of Agent Bricks Information Extraction ("Document Intelligence").
3. Unity AI Gateway GA on AWS (the docs conflict).
4. Storage-Optimized Vector Search GA and official per-hour prices (only third-party figures were found).
5. Lakebase GA on GCP (2026-11-02, secondary source).
6. Genie One promo end date (Jan 31, 2027 vs. July 31, 2026), and the exact per-user allowance after the promo.
7. Clean Rooms collaborator fee removal (forum only).
8. A Banner HR / Oracle-specific managed connector (none found).
9. StateRAMP / TX-RAMP / Illinois-specific attestations (none found).
10. Whether Workday Reports pipelines can be created in the UI or only via API (the docs conflict).
11. AutoML serverless forecasting status (forum only).

---

## 5. Sources

Primary (Databricks / Microsoft docs, blog, newsroom, official community announcements):
- https://docs.databricks.com/aws/en/release-notes/product
- https://docs.databricks.com/aws/en/release-notes/product/2026/june
- https://docs.databricks.com/aws/en/release-notes/product/2026/september
- https://docs.databricks.com/aws/en/release-notes/product/2026/october
- https://learn.microsoft.com/en-us/azure/databricks/release-notes/product/2026/june
- https://learn.microsoft.com/en-us/azure/databricks/release-notes/product/2026/october
- https://learn.microsoft.com/is-is/Azure/databricks/release-notes/product/2026/may
- https://docs.databricks.com/aws/fr/release-notes/product/2026/march
- https://docs.databricks.com/aws/en/ai-bi/release-notes/2026
- https://docs.databricks.com/aws/en/release-notes/lakebase/
- https://docs.databricks.com/aws/en/release-notes/gov-cloud/2026
- https://learn.microsoft.com/en-us/azure/databricks/large-language-models/ai-functions
- https://learn.microsoft.com/azure/databricks/sql/language-manual/functions/ai_parse_document
- https://www.databricks.com/company/newsroom/press-releases/databricks-launches-genie-one-all-new-agentic-coworker-every-team
- https://www.databricks.com/blog/whats-coming-next-free-edition
- https://learn.microsoft.com/en-us/azure/databricks/genie-one/
- https://docs.databricks.com/aws/en/genie/monitor-cost
- https://docs.databricks.com/genie/trusted-assets.html
- https://docs.databricks.com/aws/en/resources/limits
- https://docs.databricks.com/aws/en/notebooks/use-databricks-assistant
- https://learn.microsoft.com/en-au/azure/databricks/genie-code/
- https://www.databricks.com/company/newsroom/press-releases/databricks-launches-agent-bricks-new-approach-building-ai-agents
- https://community.databricks.com/t5/announcements/databricks-agent-bricks-knowledge-assistant-is-now-generally/td-p/148506
- https://community.databricks.com/t5/announcements/databricks-agent-bricks-supervisor-agent-is-now-generally/td-p/148898
- https://learn.microsoft.com/da-dk/azure/databricks/generative-ai/agent-bricks
- https://learn.microsoft.com/ja-jp/azure/databricks/generative-ai/agent-framework/author-agent
- https://docs.databricks.com/mlflow3/genai/eval-monitor/
- https://docs.databricks.com/aws/mlflow/mlflow-3-install
- https://docs.databricks.com/aws/en/vector-search/vector-search-cost-management
- https://docs.databricks.com/aws/en/ai-search/cost-management
- https://docs.databricks.com/machine-learning/foundation-models/index.html
- https://www.databricks.com/product/pricing/foundation-model-serving
- https://docs.databricks.com/aws/en/machine-learning/foundation-model-apis/priority-mode
- https://docs.databricks.com/aws/en/ai-gateway/
- https://docs.databricks.com/gcp/en/ai-gateway/
- https://databricks.com/blog/ai-governance-data-ai-summit-2026-whats-new-unity-ai-gateway
- https://docs.databricks.com/aws/en/data-engineering
- https://docs.databricks.com/aws/en/ingestion/lakeflow-connect/workday-reports
- https://docs.databricks.com/aws/en/ingestion/lakeflow-connect/workday-reports-faq
- https://docs.databricks.com/aws/en/ingestion/lakeflow-connect/workday-hcm-faq
- https://docs.databricks.com/aws/en/ingestion/lakeflow-connect/workday/workday-reports/limitations
- https://www.databricks.com/blog/azure-databricks-lakebase-generally-available
- https://community.databricks.com/t5/announcements/databricks-lakebase-is-now-generally-available/td-p/147678
- https://docs.databricks.com/aws/en/dev-tools/databricks-apps/compute-size
- https://www.databricks.com/blog/abac-row-filtering-and-column-masking-policies-governed-tags-and-data-classification-are-now
- https://community.databricks.com/t5/announcements/unity-catalog-new-abac-amp-data-classification-tools-now-ga/td-p/157231
- https://docs.databricks.com/aws/en/metric-views
- https://docs.databricks.com/aws/en/machine-learning/feature-store/migrate-from-online-tables
- https://docs.databricks.com/aws/machine-learning/feature-store/online-tables
- https://docs.databricks.com/en/machine-learning/automl.html
- https://docs.databricks.com/aws/en/data-quality-monitoring
- https://www.databricks.com/blog/lakehouse-monitoring-ga-profiling-diagnosing-and-enforcing-data-quality-intelligence
- https://docs.databricks.com/aws/en/clean-rooms/index.html
- https://databricks.com/en/blog/databricks-clean-rooms-now-generally-available-aws-and-azure
- https://databricks.com/blog/whats-new-data-sharing-collaboration
- https://docs.databricks.com/aws/generative-ai/mcp/managed-mcp
- https://docs.databricks.com/aws/en/getting-started/free-edition-limitations (via https://learn.microsoft.com/en-us/azure/databricks/getting-started/free-edition-limitations and https://docs.azure.cn/databricks/getting-started/free-edition-limitations)
- https://docs.databricks.com/aws/en/security/privacy/security-profile
- https://learn.microsoft.com/en-gb/azure/databricks/security/privacy/hipaa
- https://docs.databricks.com/aws/en/security/privacy/fedramp-high

Secondary (used only where marked; lower confidence):
- https://atlan.com/know/ai-agent/databricks/databricks-data-ai-summit-2026-announcements/
- https://qubika.com/blog/everything-databricks-announced-dais-data-ai-summit-2026/
- https://www.flexera.com/blog/perspectives/databricks-data-ai-summit-2026/
- https://letsdatascience.com/news/databricks-makes-lakebase-postgres-generally-available-on-go-455e7d6b
- https://www.dbta.com/Editorial/News-Flashes/Databricks-Lakebase-is-Now-Generally-Available-Delivering-Reliability-Performance-and-Governance-173362.aspx
- https://www.startuphub.ai/news/databricks-agents-get-smarter-document-readers
- https://databrickspricing.pages.dev/ai-pricing
- https://dev.to/mr_manushukla/databricks-genie-billing-starts-july-6-2026-a-cost-control-playbook-for-admins-1404
- https://community.databricks.com/t5/machine-learning/automl-on-azure-databricks-as-of-june-2026/td-p/160244
- https://community.databricks.com/t5/get-started-discussions/databricks-cleanroom-functionality-and-billing/m-p/165293
- https://aws-news.com/article/2026-10-20-aws-clean-rooms-now-supports-databricks-as-a-data-source
- https://www.royalcyber.com/blogs/databricks/ai-agent-platforms-salesforce-microsoft-copilot-studio-2/
- https://learn.microsoft.com/en-us/answers/questions/2006989/us-government-regulations-with-azure
