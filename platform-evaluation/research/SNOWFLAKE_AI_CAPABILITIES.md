# Snowflake AI/ML and Data Engineering: Capability Deep-Dive for HR/ERP Analytics

**Prepared for:** University of Illinois System AITS, as input to a Snowflake vs Databricks evaluation for HR/ERP (workforce) analytics
**Research date:** 2026-11-06
**Scope:** Snowflake capabilities as of the research date: status, HR use, limitations, and open-source/custom alternatives.

---

## 0. Method and how to read the status labels

The research used web search over primary sources: docs.snowflake.com release notes and user guides, snowflake.com blogs, press releases and legal pages. Direct page fetches of docs.snowflake.com were blocked by this research environment's network policy. As a result, **every status below comes from a search-engine snippet of the named page, not from reading the full page.** Before AITS cites any item in a decision document, it should be re-checked against the live page or with `SHOW CORTEX BASE MODELS` and similar commands in a real account.

| Label | Meaning |
|---|---|
| **GA (RN date)** | A docs.snowflake.com release note with that date and "General availability" in its title appeared in search results |
| **Preview (RN date)** | A docs.snowflake.com release note marked Preview appeared |
| **GA (secondary)** | Only reported as GA by press or third-party recaps (SiliconANGLE, Atlan, Medium, select.dev and similar) |
| **Unverified** | No primary confirmation found; treat as a claim only |

**Naming change to know about (June 2026):** several outlets report that at Summit 2026 (June 1-4, 2026) **Snowflake Intelligence was renamed "Snowflake CoWork"** and **Cortex Code was renamed "CoCo"**. *(Secondary sources. A docs release note dated 2026-06-17, "Artifacts in Snowflake CoWork (GA)", uses the new name, which corroborates the rename. No primary rename announcement was found.)* Older documentation, partner material and sales decks will use both sets of names.

---

## 1. Status at a glance

| Capability | Current status (best evidence) | Key date(s) |
|---|---|---|
| Cortex AI Functions ("AISQL"): AI_CLASSIFY, AI_FILTER, AI_AGG, AI_SUMMARIZE_AGG, AI_EMBED, AI_SIMILARITY and others | Preview 2025-06-02; **GA 2025-11-04** (RN) | AI_EMBED and AI_SIMILARITY are named in the GA batch; AI_SENTIMENT, AI_TRANSLATE and AI_EXTRACT are listed as already GA by then |
| AI_COMPLETE | Core generative function; GA (implied by the AI Functions GA; exact RN not isolated) | — |
| AI_EXTRACT | Preview 2025-08-22 (RN); listed as GA in the 2025-11-04 note; scale-factor parameter GA 2026-03-12; extraction scores GA 2026-05-22; accuracy update 2026-11-02 | |
| AI_PARSE_DOCUMENT (layout mode) | **GA 2025-08-21** (RN); replaces SNOWFLAKE.CORTEX.PARSE_DOCUMENT | |
| AI_TRANSCRIBE | Available. AAC support added 2026-07-15 and M4A/MOV 2026-07-31 (RN). **Original GA date unverified** | |
| AI_REDACT (PII) | **GA 2025-12-08** (RN) | |
| Document AI (UI + `!PREDICT`) | **Being decommissioned** (BCR-2156); replaced by AI_EXTRACT. Sources give conflicting dates (2026-02-20 / 2026-03-16) | |
| Cortex Analyst (text-to-SQL) | GA. Semantic views GA (Summit 2025, secondary); SQL querying of semantic views GA 2026-03-02 (secondary) | |
| Cortex Search (hybrid RAG) | GA (since 2024; GA RN not isolated in this search) | |
| Cortex Agents | **GA 2025-11-04** (RN); Teams/M365 Copilot integration GA 2025-11-05 (RN); Agents/MCP in Native Apps GA 2026-08-07 (RN); "Coding Agent" GA 2026-08-26 (RN) | |
| Snowflake Intelligence, now "CoWork" | **GA 2025-11-04** (RN); renamed June 2026 (secondary) | |
| Snowflake-managed MCP server | **GA 2025-11-04** (RN) | |
| Cortex Code, now "CoCo" | Snowsight **GA 2026-03-09** (RN); CLI GA approx. 2026-02-02/03 (secondary) | |
| Cortex Knowledge Extensions | GA approx. Aug 2025 (secondary; announced at Summit 2025) | |
| Snowflake ML: Model Registry | **GA 2024-05-03** (RN) | |
| Snowflake ML: Feature Store | **GA 2024-09-25** (RN) | |
| Snowflake ML: ML Jobs | **GA 2025-08-12** (RN) | |
| Snowflake ML: ML Observability (model monitors) | Documented (limit 250 monitors/account). **GA status unverified** | |
| Notebooks on Container Runtime | AWS **GA 2025-03-17** (RN); Notebooks in Workspaces **GA 2026-02-05** (RN) | |
| Snowpark Container Services | GA on AWS/Azure (blog); Google Cloud **GA 2025-08-01** (RN); new instance families GA 2026-05-05 (RN) | |
| Streamlit in Snowflake, container runtime | **GA 2026-03-09** (RN); not in Gov/China regions | |
| Openflow | **GA 2025-05-30** (RN); some connectors remain preview. Reported GA across AWS, Azure and GCP at Summit 2026 (secondary) | |
| Workday Data Cloud zero-copy integration | **GA 2026-10-07** (RN) | Highly relevant to HR |
| Dynamic Tables | GA (core approx. 2024-04, secondary); dynamic Iceberg tables GA 2024-11-12 (RN) | |
| Horizon: external lineage | **GA 2026-09-03** (RN); "Horizon Context" **Preview 2026-10-12** (RN) | |
| Sensitive data classification / custom classifiers | Documented with auto-tagging via classification profiles. **Exact GA date unverified in this search** | |
| AI pricing: "AI Credits" | Separate AI Credit meter from approx. 2026-04-01 (docs snippet plus secondary sources) | |
| Cross-region inference default | `ANY_REGION` default for new orgs after 2026-03-09 (docs snippet); BCR-2376 pending | |

---

## 2. Cortex AI Functions ("AISQL")

**What it does.** These are SQL functions that call hosted LLMs row by row or as aggregates:
- `AI_COMPLETE`: generic prompt to model.
- `AI_CLASSIFY`: labels from a list you supply.
- `AI_FILTER`: boolean predicate usable in WHERE/JOIN, on text or images.
- `AI_AGG` and `AI_SUMMARIZE_AGG`: aggregate insight across many rows. Snowflake says these are "not subject to context window limitations", which in practice means map-reduce chunking.
- `AI_EXTRACT`: structured fields from text or documents, built on the `arctic-extract` model.
- `AI_SENTIMENT`: overall and per-category sentiment.
- `AI_TRANSLATE`.
- `AI_TRANSCRIBE`: audio and video.
- `AI_PARSE_DOCUMENT`: OCR/layout to Markdown with tables and reading order.
- `AI_EMBED` and `AI_SIMILARITY`: vectors.
- `AI_REDACT`: PII detect/redact.

Snowflake published an arXiv paper ("Cortex AISQL: A Production SQL Engine for Unstructured Data", 2511.07663) describing the query-optimizer treatment of these functions, for example cost-aware predicate ordering for AI_FILTER.

**HR workforce uses.**

| HR task | Function pattern |
|---|---|
| Map job titles/descriptions to O*NET-SOC codes | `AI_CLASSIFY(job_desc, [list of SOC titles])` for a coarse level. Better: `AI_EMBED` both sides, take the top-k by `VECTOR_COSINE_SIMILARITY`, then `AI_COMPLETE` to adjudicate among candidates |
| Job-posting text extraction (min quals, salary range, FLSA status, remote flag) | `AI_EXTRACT(text, {'salary_min': ..., 'degree_required': ...})` or `AI_PARSE_DOCUMENT` on PDFs first |
| Exit-interview / engagement survey themes | `AI_SENTIMENT` with categories, `AI_AGG` for "top reasons for leaving by college" |
| Attrition-risk features from free text | `AI_EMBED` comments, feeding a Snowflake ML model |
| De-identify free text before sharing | `AI_REDACT` |

**Limitations.**
- **Model choice is curated, not open.** You get the models Snowflake hosts in your region. Search snippets show Anthropic Claude, OpenAI GPT-5-family, Meta Llama, Mistral, DeepSeek, and (since Summit 2026, secondary) xAI Grok and Gemini models. Availability differs by region. The authoritative check is `SHOW CORTEX BASE MODELS IN SCHEMA SNOWFLAKE.MODELS`.
- **Context windows vary by model and region.** One doc snippet shows llama3.1-8b at 128K in general but 16,384 tokens in AWS Sydney/Ireland. Inputs over the window error out, and outputs are truncated.
- **Cross-region inference.** If your region lacks a model, an ACCOUNTADMIN must set `CORTEX_ENABLED_CROSS_REGION`. Data at rest stays in-region, but **prompts are processed in another region**, crossing the public internet with mTLS when the regions sit on different clouds. Docs say new orgs created after 2026-03-09 default to `ANY_REGION`. **AITS must check and likely restrict this to `AWS_US` or similar for HR data.**
- **Accuracy is best-effort.** Snowflake itself says AI_REDACT redaction is "best-effort… always review the output". Older docs said only US (and some UK/CA) PII was covered.
- **Error handling.** Row failures can abort a query unless `AI_SQL_ERROR_HANDLING_USE_FAIL_ON_ERROR = FALSE`. That setting lets failures pass silently, so log them.
- **Cost opacity.** Billing is per input and output token at model-specific rates (Service Consumption Table), now in AI Credits. A large `AI_COMPLETE` over 100k employee rows is easy to launch and hard to predict.
- **Governance.** Access is controlled by the `SNOWFLAKE.CORTEX_USER` database role plus (2026-02-20 RN) a new account privilege `USE AI FUNCTIONS`, and by model allow-lists. Prompt and output logging for audit is your responsibility.
- **Lock-in.** Function syntax is proprietary. Prompts are portable; the SQL is not.

**Open-source replication.**
- Use DuckDB or Polars, with a Python UDF (DuckDB) or `map_batches` (Polars) that calls a local **vLLM** or **Ollama** OpenAI-compatible endpoint, with Llama, Qwen or Mistral weights.
- For structured output, use **Outlines**, **Instructor** or vLLM guided JSON. These give schema-guaranteed extraction, which is stricter than AI_EXTRACT.
- For classification at scale, a fine-tuned **SetFit** or **ModernBERT** classifier on approx. 1-2k labelled job descriptions is typically cheaper and more consistent than per-row LLM calls.
- For embeddings, **sentence-transformers** (bge, e5, gte, nomic) or **Text Embeddings Inference**.
- For document parsing, **Docling**, **Unstructured**, **Marker**, PaddleOCR or Tesseract.
- For audio, **faster-whisper / WhisperX**.
- For PII, **Microsoft Presidio** plus spaCy NER, which gives deterministic, auditable rules plus ML.
- For orchestration and caching, **dbt** Python models or Dagster, keyed by a content hash so you only re-run changed rows.
- **Exceeding it:** you control model versions (frozen weights give reproducible results), can run fully on-prem for FERPA/HR text, and pay GPU-hours instead of tokens.

---

## 3. Cortex Analyst and Semantic Views (text-to-SQL)

**What it does.** Natural-language questions are translated to SQL against a **semantic view**. A semantic view is a first-class schema object holding tables, relationships, dimensions, facts, metrics, synonyms and **verified queries**; it can be created via DDL or YAML. Legacy staged YAML semantic models still work, but semantic views are recommended. The service is exposed via REST API and used as a tool by Cortex Agents and MCP. A 2026-03-05 RN adds semantic views export to Tableau TDS. A built-in **evaluation** feature runs the generated SQL against verified queries as ground truth. It temporarily removes the selected verified queries from the view so they don't leak into their own answers, and reports accuracy and regressions.

**HR use.** Define `headcount` (with point-in-time logic), `fte`, `voluntary_attrition_rate`, `time_to_fill`, `median_salary_by_job_family`, and dimensions such as campus/college/department, job classification (civil service vs academic professional vs faculty), and EEO category. HR analysts then ask "voluntary attrition among civil-service staff at UIC in FY25 vs FY24". Verified queries lock in the canonical definitions of headcount and turnover, which matters because HR metric definitions are contested.

**Limitations.**
- Accuracy depends on semantic-model quality. Snowflake publishes **no public benchmark** (Spider/BIRD) results for Analyst that this search found; you must measure it on your own question set with the evaluation tool.
- Third-party guidance (AtScale; unverified) cites a 1 MB YAML limit and a recommended approx. 50-100 columns. Wide HR star schemas need splitting.
- Point-in-time / effective-dated HR logic (job records with effective dates, concurrent appointments) is hard for any text-to-SQL. Expect to encode it in views rather than relying on the LLM.
- A third-party source (single source, unverified) reports that from late Aug 2026 Snowflake recommends Cortex Agents over calling Analyst directly. **Watch for API churn.**
- The Snowflake AI Trust FAQ notes a footnote exception: customers can *opt in* to send Analyst inputs to **Azure-hosted OpenAI** models, which takes data outside Snowflake's boundary. Disable this for HR.
- Row access and masking policies are enforced at query time because generated SQL runs as the user. That is a strength, but aggregated answers over small cells can still leak (e.g., the pay of a 1-person department). You need **minimum-cell-size suppression** in the views.

**Open-source replication.**
- Semantic layer: **dbt Semantic Layer / MetricFlow** or **Cube**, which are portable across warehouses.
- Text-to-SQL: **Vanna**, **WrenAI**, LlamaIndex NL-SQL, or a custom agent that only emits MetricFlow queries (metric + dimension + filter) instead of raw SQL. That design is safer than free-form SQL.
- Evaluation: a pytest harness that executes golden questions and compares result sets.
- Engines: DuckDB or Postgres.
- This can **exceed** Analyst on governance, by constraining the LLM to a metric API with no raw SQL, and on portability.

---

## 4. Cortex Search (hybrid retrieval / RAG)

**What it does.** A managed index over a text column, with incremental refresh from a source query. Each query runs vector search, keyword search and semantic re-ranking, plus optional filters on attribute columns. Snowflake's engineering blog reports internal NDCG@10 rising from 0.22 (lexical) to 0.49 (vector), 0.53 (hybrid) and 0.59 (hybrid + reranker); **these are vendor benchmarks**. Search services can be shared on Marketplace as **Cortex Knowledge Extensions**.

**HR use.** HR policy Q&A over the policy manuals, Civil Service rules (SUCSS), collective bargaining agreements, benefits guides and campus administrative procedures, with filters by campus and employee group so a Springfield AP employee doesn't get a Chicago union-contract answer.

**Limitations.**
- **Always-on serving cost:** a third-party analysis (Oct 2025) cites approx. **6.3 credits per GB/month of indexed data**, billed whether or not anyone queries, plus embedding tokens and warehouse refresh.
- Limited control over chunking, reranker and embedding-model choice compared with DIY.
- Cross-region inference for Search "is not supported in all regions".
- No built-in answer-faithfulness evaluation. Retrieval quality on legal-style policy text should be tested.
- Document-level ACLs must be modelled as filter attributes. There is no native per-document entitlement sync from SharePoint, although Openflow SharePoint connectors exist.

**Open-source replication.**
- Storage: **pgvector** (with `tsvector` for BM25-ish keyword search) or **ParadeDB**, **LanceDB** (hybrid FTS + vector), **Qdrant**, **Weaviate**, **OpenSearch**.
- Models: embeddings via sentence-transformers or **BGE-M3**, reranking via **bge-reranker** / cross-encoders.
- Retrieval scheme: reciprocal-rank fusion.
- Evaluation: **Ragas** or **TruLens** offline, with a human-labelled golden set.
- At university policy scale (thousands of documents) this runs on a single VM at near-zero marginal cost and **exceeds** Cortex Search in chunking control and evaluation transparency.

---

## 5. Cortex Agents, Snowflake Intelligence ("CoWork"), and MCP

**What it does.**
- **Cortex Agents** (GA 2025-11-04) orchestrate LLM planning over tools: Cortex Analyst (structured), Cortex Search (unstructured), custom tools and stored procedures.
- **Snowflake Intelligence** (GA 2025-11-04; renamed **CoWork** June 2026 per secondary sources) is the end-user chat UI for those agents. Artifacts went GA 2026-06-17 (RN). Secondary sources list Deep Research, Cortex Sense, User Memory and Automations as preview or "coming".
- Integrations: Microsoft Teams / M365 Copilot (GA 2025-11-05).
- The **Snowflake-managed MCP server** (GA 2025-11-04) exposes `CORTEX_ANALYST_MESSAGE` and `CORTEX_SEARCH_SERVICE_QUERY` tools to external MCP clients (Claude, Cursor, CrewAI and others) under RBAC. A third-party blog says only semantic views are supported, not legacy YAML.
- Summit 2026 (secondary): "Agent Identity" (per-agent identity and permissions), AI Security Posture Management in Trust Center, and an announced Natoma acquisition for governed agent access.

**HR use.** A single "HR Insights" agent that answers "How many open faculty searches in Engineering exceed 180 days, and what does policy say about extending a search?", combining Analyst over requisition data with Search over the policy library. MCP lets AITS developers query the governed semantic views from their own IDE agents.

**Limitations.**
- Agent behaviour is non-deterministic. Snowflake provides observability/trace features (details unverified), but **no published accuracy guarantees**.
- Cost stacks up: orchestration tokens, tool tokens and warehouse SQL. Third parties (Revefi, definite.app) warn of "hidden" agentic costs.
- Orchestration-model choice is limited to the hosted catalogue.
- Rapid renaming and API churn (Intelligence to CoWork, Analyst to Agents) means maintenance risk.
- Many newer agent features are preview-only. Do not plan production HR use on preview features.

**Open-source replication.**
- Agent frameworks: **LangGraph**, **PydanticAI**, **LlamaIndex agents**, or the OpenAI/Anthropic Agents SDKs pointed at local vLLM.
- Tools: an MCP server you write with the official MCP Python SDK, exposing the same MetricFlow and pgvector tools.
- UI: **Open WebUI** or **Chainlit**.
- Tracing and evaluation: **Langfuse** or **Arize Phoenix** (self-hosted).
- Doing this yourself gives full trace retention, the ability to pin models, and deterministic tool routing for high-stakes questions.

---

## 6. Snowflake ML (Feature Store, Model Registry, ML Jobs, Observability, Notebooks)

**What it does.**
- `snowflake-ml-python` provides sklearn/XGBoost/LightGBM-style modelling with pushdown.
- **Feature Store** (GA 2024-09-25), with entities and feature views backed by Dynamic Tables.
- **Model Registry** (GA 2024-05-03), with versioned models callable from SQL and serving on SPCS.
- **ML Jobs** (GA 2025-08-12) dispatch Python from any IDE to Snowflake compute, including distributed and GPU runs.
- **ML Observability** model monitors: drift, performance and statistics via `MODEL_MONITOR_DRIFT_METRIC`; regression and binary/multiclass only; max 250 monitors per account; auto-suspend after 5 refresh failures. **GA status unverified.**
- **Notebooks on Container Runtime** (AWS GA 2025-03-17; Notebooks in Workspaces GA 2026-02-05) give preconfigured CPU/GPU containers with sessions of up to 7 days.
- **Cortex Training** (fine-tuning) is reported as preview at Summit 2026 (secondary).

**HR use.**
- Voluntary-attrition model at the employee-month grain: features for tenure, pay compa-ratio, time since last promotion, supervisor changes, FTE changes and survey sentiment.
- Succession-risk scoring: retirement eligibility from SURS service credit, plus critical-role flags.
- Pay-equity regression: log salary on legitimate factors plus protected class, with residual analysis. This is a statistical model, not ML. Snowpark Python with statsmodels works, but it is not a Cortex feature.
- Feature Store keeps point-in-time-correct features. This is critical to avoid leakage in attrition models.

**Limitations.**
- The observability model types are narrow (no survival models, which are the natural fit for attrition).
- Package availability on the warehouse runtime is limited to the Anaconda channel unless you use the Container Runtime.
- GPU availability is region-dependent.
- Fairness and explainability tooling is thin compared with dedicated libraries.
- The Registry and Feature Store APIs are Snowflake-specific (less portable than MLflow, which Databricks uses natively).
- Small-cell privacy in model outputs is your problem.

**Open-source replication.**
- Tracking and registry: **MLflow**.
- Features: **Feast** (feature store) or simply dbt point-in-time snapshot tables.
- Modelling: scikit-learn, XGBoost/LightGBM, **lifelines** or **scikit-survival** for time-to-attrition, **statsmodels** for pay-equity OLS with robust SEs, and **Fairlearn** / **AIF360** plus **SHAP** for fairness and explanations.
- Monitoring: **Evidently** or **NannyML** (performance estimation without labels, useful because attrition labels lag).
- Data tests: **Great Expectations** or **Pandera**.
- Notebooks: **JupyterHub** or **marimo**.
- This stack **exceeds** Snowflake in model breadth, especially survival analysis and fairness, and in portability.

---

## 7. Document AI and AI_EXTRACT

**What it does.** The legacy Document AI (UI model builds plus `!PREDICT`) is being **decommissioned** (BCR-2156). Existing models must be migrated to the Model Registry, and inference moves to **AI_EXTRACT** on `arctic-extract`. The new version **cannot be fine-tuned**, and model builds are no longer created in the UI. AI_EXTRACT is token-billed and got "extraction scores" (confidence) GA on 2026-05-22.

**HR use.** Extract fields from scanned position descriptions, offer letters, I-9-adjacent documents (be careful), and job postings, then land the results in tables.

**Limitations.** No fine-tuning means you cannot adapt it to idiosyncratic UIS position-description templates. You must also handle the forced migration.

**Open-source replication.** **Docling** or **Marker**, then an LLM with Outlines/Instructor JSON schemas. Or fine-tune **Donut** / **LayoutLMv3** / a small VLM (Qwen2.5-VL) on your own forms. Keep human-in-the-loop review with **Label Studio**.

---

## 8. Snowpark and Snowpark Container Services (SPCS)

**What it does.**
- **Snowpark** provides DataFrame APIs (Python/Java/Scala) and UDFs/UDTFs/stored procedures that run inside warehouses.
- **SPCS** runs OCI containers on Snowflake-managed compute pools (CPU/GPU) for services, jobs and model serving. It is GA on AWS/Azure and on Google Cloud (2025-08-01 RN). New instance families went GA 2026-05-05 and ARM 2026-05-15. Large A100 instances exist only in some regions, and Snowflake notes "GPU availability may be limited in certain regions".

**HR use.** Host a self-chosen open-weights model (e.g., via vLLM) inside the Snowflake boundary when Cortex's catalogue doesn't fit, or host a custom O*NET matcher service.

**Limitations.** Compute-pool billing runs while nodes are up. Image registry, networking and egress (External Access Integrations) add configuration overhead. Region-dependent GPUs.

**Open-source replication.** Kubernetes or Nomad on campus or cloud VMs, running vLLM/TGI. **Ray** for distributed Python. **Polars/DuckDB** usually replace Snowpark DataFrames for single-node HR-scale data, which is millions of rows at most for UIS HR: small data.

---

## 9. Openflow (ingestion)

**What it does.** A managed **Apache NiFi**-based integration service (from the Datavolo acquisition). It is **GA 2025-05-30** (RN), with "some connectors remaining in preview", and is reported GA on AWS/Azure/GCP at Summit 2026 (secondary). Deployment is BYOC or Snowflake-managed (on SPCS). Connectors include **Workday (via RaaS reports)**, **SharePoint**, **Google Drive**, databases and SaaS sources. Some connector docs carry "LIMITEDACCESS" labels.

**Separately and more importantly for HR:** **Zero-copy integration for Workday Data Cloud is GA as of 2026-10-07** (RN; the Snowflake blog dates the announcement 2026-10-12 at Workday Rising). Curated Workday HR objects (Worker, Position, Payroll; "money data coming soon") appear in Snowflake as **externally managed Iceberg tables** in a catalog-linked database, with no pipeline. This requires a Workday tenant on Public Cloud. A separate "Workday Live Data Query for Snowflake" (Python connector from Notebooks) also exists. Workday announced equivalent zero-copy partnerships with **Databricks** and Salesforce, so this is **not a Snowflake differentiator by itself**. Compare the maturity of both.

**Relevance caveat for UIS:** this only matters if the System's HR system of record is (or will be) Workday. If HR/ERP is Banner or another ERP, the Openflow database CDC connectors and generic NiFi processors are the relevant path.

**Limitations.** Openflow runtime costs (SPCS or BYOC infrastructure plus credits); trial accounts cap Openflow at 10 credits/day. NiFi flows are a different skill set from SQL. Workday RaaS has pagination and timeouts.

**Open-source replication.** **Apache NiFi** itself (the same engine), **Airbyte**, **dlt** (data load tool), **Meltano/Singer**, **Debezium** for CDC. The Workday RaaS/SOAP API can be pulled with Python + dlt on a schedule (Dagster/Airflow). Zero-copy Iceberg from Workday could in principle be read by any Iceberg engine (DuckDB, Trino, Spark) if Workday exposes the catalog to it. **Unverified:** whether Workday Data Cloud exposes Iceberg to non-partner engines.

---

## 10. Dynamic Tables

**What it does.** Declarative SQL tables with a target lag, refreshed automatically (incremental or full). Dynamic Iceberg tables have been GA since 2024-11-12. A 2026 aggregator lists a `CUSTOM_INCREMENTAL` mode (unverified).

**HR use.** Daily-refreshed `employee_month` snapshot, `headcount_by_org_by_day`, and attrition event tables feeding the semantic views.

**Limitations (official docs).**
- `REFRESH_MODE=AUTO` silently falls back to **full refresh**, which costs more, on unsupported constructs (PIVOT/UNPIVOT, SAMPLE, non-deterministic functions). Set the mode explicitly and check `refresh_mode_reason`.
- **Incremental refresh is blocked when base-table masking or row-access policies query a mapping table.** That is a common HR governance pattern.
- Policy changes force reinitialization.
- Dynamic Iceberg tables cannot be cloned.

**Open-source replication.** **dbt incremental models** (+ snapshots for SCD2 job history) on DuckDB/Postgres, orchestrated by Dagster/Airflow. Materialize or RisingWave for true streaming incremental views. **SQLMesh** for change-aware incremental planning.

---

## 11. Horizon governance (masking, row access, tags, lineage, classification)

**What it does.**
- Dynamic **masking policies** and **row access policies**, including tag-based masking.
- **Object tagging**.
- **Sensitive data classification**: system tags such as `SEMANTIC_CATEGORY`, **custom classifiers** (regex-based, `SNOWFLAKE.DATA_PRIVACY.CUSTOM_CLASSIFIER`, default 0.8 threshold), and **classification profiles** with `auto_tag` and `classify_views` options plus tag mapping.
- **Access History**.
- **Lineage** in Snowsight: column-level, external lineage GA 2026-09-03 (RN), lineage through temporary tables (2026-10 RN), and OpenLineage ingestion.
- **Trust Center**. "Horizon Context" is preview (2026-10-12 RN), and AI Security Posture Management was announced at Summit 2026 (secondary).
- Many governance features require **Enterprise edition or higher**.

**HR use.**
- Mask SSN, DOB, home address and medical-leave flags by role.
- Row-access by campus/college for unit HR partners.
- Tag columns `PII`, `FERPA` (student employees), `HIPAA` (benefit claims).
- Custom classifiers for UIN (University ID number) patterns.
- Lineage from Workday/Banner objects to the dashboards that show salary.

**Limitations.**
- Classification is pattern- and sample-based: a 0.8 match threshold over a *sample*. Free-text comment fields with embedded PII are poorly served; you need AI_REDACT or similar.
- ACCESS_HISTORY lag of up to approx. 3 hours (third-party).
- External lineage was historically table-level only (Atlan, pre-GA; may have changed).
- Policies interact badly with Dynamic Table incremental refresh (see §10).
- Governance does not extend to copies once data leaves Snowflake (extracts, Excel exports).
- AI outputs, such as an agent's summary text, are new data that the original column tags don't follow automatically. **Unverified whether Horizon propagates tags to AI-derived columns.**

**Open-source replication.**
- Policies: Postgres **row-level security** plus views or **pgcrypto**, or Trino with **Apache Ranger**.
- Catalog and lineage: **OpenMetadata** or **DataHub** (both have PII auto-classification), **OpenLineage + Marquez**, and dbt docs/exposures for lineage.
- PII discovery: **Presidio**.
- These match Snowflake's feature set but require you to operate them; integrated enforcement in one engine is Snowflake's real advantage here.

---

## 12. Marketplace and Cortex Knowledge Extensions

**What it does.** Data/app Marketplace; CKEs are Cortex Search services shared from providers (news, research and Snowflake documentation), GA approx. Aug 2025 (secondary). They are used as grounding sources in agents.

**HR use.** Limited. Potential sources are labour-market datasets (e.g., BLS-derived or Lightcast-type postings data, if listed) and compensation benchmarks. **O*NET itself is free public data** (onetcenter.org), so a Marketplace listing is not needed. Whether specific HR datasets exist on Marketplace today is **unverified**.

**Replication.** Download O*NET/BLS OES/CPS directly. Load with dlt or DuckDB `read_csv`.

---

## 13. Streamlit in Snowflake

**What it does.** Hosted Streamlit apps under Snowflake RBAC. The **container runtime** went **GA 2026-03-09** (RN): SPCS compute pools, GPUs, broad pip packages, no sleep timers, `st.secrets`, viewer URLs and logging. It is **not available in Government or China regions**.

**HR use.** Internal apps: O*NET mapping review queue (human-in-the-loop accept/reject), pay-equity what-if tool, succession slate viewer.

**Limitations.** UI customization is limited to Streamlit's model. Compute-pool cost runs while apps are warm. Gov-region unavailability matters if AITS chooses a GovCloud/FedRAMP High deployment.

**Replication.** Self-hosted **Streamlit**, **Dash**, **Shiny for Python**, **Evidence.dev** (SQL+Markdown BI), **Superset** or **Metabase**, behind campus SSO (Shibboleth/Entra) via oauth2-proxy.

---

## 14. Coding assistants: Cortex Code / "CoCo"

**What it does.** A Snowflake-aware coding agent (SQL, Python, ML, admin) in Snowsight Workspaces (**GA 2026-03-09**, RN), a CLI (GA approx. Feb 2026, secondary), a desktop app, and VS Code / Claude Code plugins. It requires cross-region inference to be enabled (per BCR-2376 snippet). Billing is in token-based AI Credits after the free preview ended (secondary). Trial: a separate CoCo CLI trial with $40 of inference (Snowflake trial page).

**Limitations.** The cross-region requirement can conflict with HR data-residency rules. Output quality is not independently benchmarked. Usage-based cost.

**Replication.** **Claude Code**, Cursor, Continue.dev or Aider against your repo, with the dbt + DuckDB stack and a schema-aware MCP server (e.g., a Postgres or DuckDB MCP server, or the Snowflake MCP server itself if you do adopt Snowflake).

---

## 15. Pricing model for AI

- **AI Credits.** Since approx. **2026-04-01**, AI usage is metered in **AI Credits, separate from platform credits**, with "consistent pricing regardless of edition" (docs snippet). Several secondary sources cite **$2.00 (global) / $2.20 (regional) per AI Credit**, and one cites $5.20 in a specific context. **Unverified; get a quote.** One guide warns that **platform-credit discounts on an order form do not apply to AI Credits**, while ACV-based AI discounts exist.
- **Per-token rates** differ per model. See the **Service Consumption Table** (PDF effective 2026-07-14 per snippet).
- **Other cost lines:** Cortex Search (serving GB-month plus embeddings plus refresh warehouse), Agents (orchestration plus tool tokens plus SQL), SPCS compute pools, Openflow runtime, Streamlit container pools.
- **Cost controls:** the ai-cost-management docs page and ACCOUNT_USAGE views. Snowflake docs say usage quotas are **not** applied at account level by default, so build budgets/resource monitors and per-role allow-lists.
- **Assessment:** pricing is transparent per token but **opaque per question**. A single agent answer can fan out into many model and SQL calls. Run a metered pilot.

**Open-source comparison.** A single on-prem or reserved GPU server (e.g., 1-2x L40S/H100) running vLLM with a 30-70B open model has a fixed monthly cost. For batch HR text jobs (tens of thousands of job descriptions) that is typically far cheaper per token once utilisation is reasonable, but you take on ops, patching and model evaluation.

---

## 16. Trial account restrictions (for a proof of concept)

- **$400 credits / 30 days**, ending at whichever comes first (Snowflake trial page; verify).
- Without a payment method, **Cortex AI Functions are capped at approx. 10 credits/day**. External network access, hybrid tables and **Openflow are also capped at 10 credits/day** (trial docs and page).
- Trial edition and region choice determine model availability. Business Critical features (HIPAA/PHI, FedRAMP) are not available on trial accounts in a usable compliance sense: no BAA.
- **Never load real UIS HR data into a trial.** Use synthetic or public data (e.g., OPM FedScope, or public university salary databases) for the POC.

---

## 17. FERPA, HIPAA, data residency, and public-sector posture

| Topic | Evidence | Implication for UIS HR |
|---|---|---|
| HIPAA | A **BAA must be signed before storing PHI**; HIPAA-eligible accounts are tied to **Business Critical** edition (docs + third party) | Benefits claims, FMLA medical documentation and EAP data need Business Critical + BAA, or should be kept out |
| FedRAMP / StateRAMP | Security Addendum: FedRAMP Moderate and High in certain US regions for **Business Critical and VPS only**; StateRAMP/TX-RAMP referenced | Illinois has no StateRAMP mandate known to this research (**unverified**); check UIS procurement policy |
| FERPA | 2023 Snowflake press release: platform "supports FERPA workloads across its U.S. regions". **No current FERPA attestation found**; FERPA obligations sit with the institution | Student-employee records (GAs, hourly students) are FERPA education records in many contexts. Treat them as such; contract via a FERPA "school official" clause |
| AI data use | AI Trust & Safety FAQ: customer data **not used to train models for other customers**; data stays in the Snowflake security boundary, **except** opt-in Azure OpenAI for Cortex Analyst | Disable the opt-in; document the model allow-list |
| Residency | Data at rest stays in-region; **cross-region inference sends prompts to other regions** (and possibly other clouds over the internet with mTLS) | Restrict `CORTEX_ENABLED_CROSS_REGION` to a US scope (e.g., `AWS_US`), or `DISABLED` if needed |
| Illinois-specific | Illinois PIPA (breach notification), BIPA (biometrics; relevant if HR stores badge or biometric data), Illinois AI in employment law (HB 3773, amending the Human Rights Act, effective 2026-01-01; **verify applicability to public universities with counsel**) | Using AI in attrition or succession decisions about individuals may trigger notice and anti-discrimination obligations, independent of platform |

**Open-source posture.** Running on UIS-controlled infrastructure keeps everything inside existing institutional security controls and eliminates the cross-region and third-party-model questions entirely. The cost is self-certifying controls instead of inheriting Snowflake's SOC 2 / FedRAMP evidence.

---

## 18. Cross-cutting assessment for Snowflake vs Databricks (HR/ERP)

**Where Snowflake is strong for this use case**
1. Governed SQL-first analytics: masking, row access and classification are integrated in one engine, which suits HR's many sensitive columns and business-analyst user base.
2. Semantic views plus Analyst, Agents and MCP give a coherent, governed natural-language path, now exportable to Tableau.
3. Workday Data Cloud zero-copy (GA Oct 2026) if Workday is in scope. Databricks has an equivalent partnership, so compare both hands-on.
4. Low ops burden: serverless AI functions, no GPU management.

**Where to be careful**
1. **Cross-region inference defaults** and opt-in external models: a residency trap for HR data.
2. **Cost predictability** of agentic and AI-function workloads under the new AI Credit meter.
3. **Product churn**: Document AI decommissioned; Intelligence renamed CoWork; Analyst steered toward Agents; many 2026 features still preview.
4. **Model catalogue is curated and regional.** Reproducibility requires pinning model names, and those models can be retired.
5. ML depth (survival models, fairness tooling) is weaker than an open Python/MLflow stack. Databricks is MLflow-native.
6. No independent accuracy evidence for Analyst, Agents or AI_EXTRACT on HR data. Build your own golden sets and **do not let one model grade another**. Use human-labelled ground truth.

**A credible independent-engineer alternative stack (small-data HR scale)**
- Ingestion: dlt / Airbyte / NiFi (Workday RaaS, Banner DB)
- Storage and engine: Postgres (+pgvector, RLS) and/or DuckDB/Parquet/Iceberg
- Transform: dbt (+ snapshots), Great Expectations / Pandera tests
- Semantic layer: dbt MetricFlow or Cube
- LLM serving: vLLM / Ollama on an on-prem GPU, with open-weights models pinned by hash
- Extraction: Docling + Outlines/Instructor; Presidio for PII
- Retrieval: pgvector/LanceDB + BGE-M3 + bge-reranker; Ragas evaluation
- ML: scikit-learn, lifelines, statsmodels, Fairlearn, SHAP; MLflow; Evidently/NannyML
- Catalog and lineage: OpenMetadata or DataHub + OpenLineage
- Apps: Streamlit/Evidence/Superset behind campus SSO
- Agents: LangGraph or PydanticAI + a custom MCP server; Langfuse tracing

This matches or exceeds Snowflake on transparency, reproducibility, cost at small scale and data locality. It is weaker on integrated governance, vendor-provided compliance attestations, support SLAs and bus-factor risk. **For a university IT shop, the realistic decision is often hybrid:** a governed warehouse (Snowflake or Databricks) for HR data and policies, plus self-hosted open models (via SPCS on Snowflake, Model Serving on Databricks, or on-prem) for sensitive text processing.

---

## 19. Open questions to resolve with Snowflake (and Databricks) account teams

1. Exact model list and context windows in the candidate region (run `SHOW CORTEX BASE MODELS`).
2. Written confirmation of AI Credit price, discounts, and whether committed-capacity credits cover AI.
3. Whether `CORTEX_ENABLED_CROSS_REGION` can be locked by policy, and the BCR-2376 rollout date for the account.
4. FERPA contract language ("school official" designation) and BAA terms for Business Critical.
5. ML Observability GA status, and survival-model support.
6. Workday Data Cloud: which HR objects are available today, refresh latency, costs, and whether UIS's HR system is in scope at all.
7. Long-term support for Cortex Analyst REST vs Agents, and deprecation policy for hosted models.

---

## Sources

Primary (Snowflake). Statuses were taken from search-result snippets of these pages, because direct fetch was blocked in this environment.
- https://docs.snowflake.com/release-notes/2025/other/2025-06-02-cortex-aisql-public-preview
- https://docs.snowflake.com/en/release-notes/2025/other/2025-11-04-cortex-aisql-operators-ga
- https://docs.snowflake.com/user-guide/snowflake-cortex/aisql
- https://docs.snowflake.com/en/user-guide/snowflake-cortex/aisql-regional-availability
- https://docs.snowflake.com/en/user-guide/snowflake-cortex/model-availability
- https://docs.snowflake.com/user-guide/snowflake-cortex/cortex-rest-api
- https://docs.snowflake.com/en/release-notes/2025/other/2025-08-21-aisql-ai-parse-document-layout-ga
- https://docs.snowflake.com/en/release-notes/2025/other/2025-12-08-ai-redact-ga
- https://docs.snowflake.com/user-guide/snowflake-cortex/redact-pii
- https://docs.snowflake.com/release-notes/all-release-notes
- https://docs.snowflake.com/en/release-notes/bcr-bundles/un-bundled/bcr-2156
- https://docs.snowflake.com/release-notes/2025/other/2025-11-04-snowflake-intelligence
- https://docs.snowflake.com/en/release-notes/2025/other/2025-11-04-cortex-agents
- https://docs.snowflake.com/en/release-notes/2025/other/2025-11-05-cortex-agents-teams-ga
- https://docs.snowflake.com/release-notes/2025/other/2025-11-04-cortex-agents-mcp
- https://docs.snowflake.com/user-guide/snowflake-cortex/cortex-agents-mcp
- https://docs.snowflake.com/release-notes/2026/other/2026-08-07-native-apps-agents-mcp-ga
- https://docs.snowflake.com/release-notes/2026/other/2026-08-26-cortex-agents-coding-agent-ga
- https://docs.snowflake.com/release-notes/2026/other/2026-06-17-snowflake-cowork-artifacts-ga
- https://docs.snowflake.com/en/release-notes/2026/other/2026-03-09-cortex-code-snowsight-ga
- https://docs.snowflake.com/en/user-guide/cortex-code/cortex-code-cli.html
- https://docs.snowflake.com/en/user-guide/views-semantic/semantic-view-yaml-spec
- https://docs.snowflake.com/en/release-notes/2026/other/2026-03-05-semantic-views-tableau-tds
- https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-analyst-evaluations
- https://www.snowflake.com/blog/cortex-search-ai-hybrid-search
- https://www.snowflake.com/en/engineering-blog/cortex-search-and-retrieval-enterprise-ai/
- https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-knowledge-extensions/cke-overview
- https://snowflake.com/en/blog/easy-button-context-rich-ai-agents
- https://docs.snowflake.com/release-notes/2024/other/2024-05-03-snowflake-model-registry
- https://docs.snowflake.com/release-notes/2024/other/2024-09-25-feature-store-ga
- https://docs.snowflake.com/release-notes/2025/other/2025-08-12-distributed-ml-jobs
- https://docs.snowflake.com/en/developer-guide/snowflake-ml/model-registry/model-observability
- https://docs.snowflake.com/en/release-notes/2025/other/2025-03-17-notebooks-on-spcs-aws
- https://docs.snowflake.com/release-notes/2026/other/2026-02-05-notebooks-in-workspaces
- https://snowflake.com/blog/secure-app-deployment-snowpark-container-services-ga
- https://docs.snowflake.com/release-notes/2025/other/2025-08-01-spcs-google-cloud-ga
- https://docs.snowflake.com/en/release-notes/2026/other/2026-05-05-spcs-new-instance-families-ga
- https://docs.snowflake.com/developer-guide/snowpark-container-services/instance-families-gcp
- https://docs.snowflake.com/release-notes/2026/other/2026-03-09-sis-container-runtime-ga
- https://docs.snowflake.com/release-notes/2025/other/2025-05-30-openflow
- https://docs.snowflake.com/en/user-guide/data-integration/openflow/connectors/about-openflow-connectors
- https://docs.snowflake.com/user-guide/data-integration/zero-copy/about-workday-datacloud
- https://docs.snowflake.com/release-notes/2026/other/2026-10-07-workday-data-cloud-zerocopy-ga
- https://www.snowflake.com/en/blog/workday-data-cloud-snowflake-zero-copy-integration/
- https://docs.snowflake.com/en/user-guide/dynamic-tables-limitations
- https://docs.snowflake.com/en/release-notes/2024/other/2024-11-12-dynamic-iceberg-tables
- https://docs.snowflake.com/en/user-guide/snowflake-horizon
- https://docs.snowflake.com/release-notes/2026/other/2026-09-03-external-lineage-ga
- https://docs.snowflake.com/release-notes/2026/other/2026-10-12-horizon-context-preview
- https://docs.snowflake.com/user-guide/governance-classify-concepts
- https://docs.snowflake.com/en/user-guide/classify-custom
- https://docs.snowflake.com/en/user-guide/snowflake-cortex/pricing
- https://docs.snowflake.com/en/user-guide/snowflake-cortex/governance-and-availability/ai-cost-management-and-governance
- https://www.snowflake.com/legal-files/CreditConsumptionTable.pdf
- https://docs.snowflake.com/en/user-guide/snowflake-cortex/cross-region-inference
- https://docs.snowflake.com/en/release-notes/bcr-bundles/2026_06/bcr-2376
- https://docs.snowflake.com/en/user-guide/admin-trial-account
- https://www.snowflake.com/en/snowflake-trial/
- https://docs.snowflake.com/pt/release-notes/2026/other/2026-02-20-use-ai-functions-privilege
- https://docs.snowflake.com/en/user-guide/intro-editions
- https://www.snowflake.com/en/legal/addenda/security-addendum/2024-10-01/
- https://www.snowflake.com/en/legal/compliance/snowflake-ai-trust-and-safety/
- https://www.businesswire.com/news/home/20230606005484/en (Snowflake Government & Education Data Cloud, FERPA statement)
- https://www.snowflake.com/en/solutions/industries/public-sector/higher-education/

Secondary (press, analysts, practitioners; used only where labelled "secondary")
- https://arxiv.org/html/2511.07663v2 (Cortex AISQL paper, Snowflake authors)
- https://siliconangle.com/?p=768117 (Summit 2026)
- https://dev.to/timothy_spann_a41a639e47c/all-data-and-ai-weekly-245-08-june-2026-5bn1
- https://medium.com/@saurabh.kr/snowflake-summit-2026-what-to-build-on-what-to-watch-065ec28f73c5
- https://www.flexera.com/blog/perspectives/snowflake-summit-2026/
- https://atlan.com/know/snowflake/summit-2026-announcements/
- https://itbrief.com.au/story/snowflake-renames-ai-tools-amid-broader-platform-push
- https://atlan.com/know/snowflake/snowflake-coco/
- https://kanerika.com/blogs/snowflake-coco/
- https://www.phdata.io/blog/snowflake-semantic-views-real-world-insights-best-practices-and-phdatas-approach/
- https://snowflake.atscale.com/glossary/snowflake-semantic-views/
- https://select.dev/posts/snowflake-cortex-search-overview-pricing-and-cost-monitoring
- https://medium.com/towards-data-engineering/breaking-down-snowflakes-ai-pricing-overhaul-credits-caching-and-cost-strategy-bde56f48f53f
- https://www.revefi.com/blog/wait-my-snowflake-bill-did-what-the-hidden-cost-of-agentic-ai-in-snowflake
- https://peliqan.io/blog/snowflake-mcp/
- https://dev.classmethod.jp/articles/snowflake-try-cortex-knowledge-extensions-with-snowflake-intelligence/
- https://datahub.com/?p=15478 (Snowflake lineage limits)
- https://atlan.com/know/how-to-track-data-lineage-for-snowflake-tables/
- https://data.folio3.com/blog/snowflake-hipaa/
- https://en-gb.newsroom.workday.com/2025-09-16-Workday-Introduces-Workday-Data-Cloud-to-Unlock-the-Power-of-People-and-Money-Data-and-Accelerate-AI-Powered-Innovation
- https://studentprivacycompass.org/higher-ed-2-pager

*Research date: 2026-11-06. All statuses are as of this date and should be re-verified on docs.snowflake.com before use in a procurement document.*
