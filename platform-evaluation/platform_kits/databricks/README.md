# Databricks trial-run kit: public HR and labor-market data

Kit version `databricks_kit_v0.1`, protocol `dbx-public-ai-protocol-v1`. Written 2026-11-06. **Not executed in any Databricks workspace yet.** Every notebook still needs a first real run, and the items marked *verify in workspace* need checking.

This kit is a step-by-step way to exercise Databricks' main AI and data capabilities against [rubric v1.0](../../PLATFORM_EVALUATION_RUBRIC.md). It records evidence in the rubric's result format, using **public data only**:

- O*NET 31.0
- IPEDS
- BLS QCEW
- Census QWI
- the Illinois SUCSS public class catalog
- the frozen **synthetic** [benchmark v1.0](../../benchmark/README.md) fixtures, used read-only

> **Never load institutional HR, payroll, appointment, applicant or employee data into Free Edition or a trial workspace.** The governance and ML steps use fictional data only. A result from this kit does not show production suitability; the rubric's gates still apply.

## Ground rules carried over from the repository

- **No model grades another model.** Every reported score comes from one of:
  - exact or result-set comparison
  - overlap with O*NET's own lists
  - human-reviewed labels
  - numeric error against held-out actuals

  Genie's Agent-mode benchmark (an LLM judge) and MLflow LLM judges are not used for any reported score.
- **Frozen protocol.** Prompts, label sets, row caps, question sets and scorers live in `_config.py` and the notebooks under `PROTOCOL`. Changing any of them to improve a result needs a new protocol label, and both runs must be kept.
- **Keep everything.** Every attempted row, error, unparseable output and failed query stays in the result tables. Nothing is deduplicated or retried away silently.
- **Agreement is not accuracy.** Agreement with the lexical baseline is reported as agreement. Accuracy is only claimed against human-reviewed labels (`review_labels`), and only for the reviewed sample.
- **Leave the frozen benchmark alone.** Do not touch `benchmark/` files, hashes or contracts. The kit uploads *copies* and checks their SHA-256 against `benchmark/manifest.json`.

## Files

| File | What it exercises | Free Edition? |
|---|---|---|
| `_config.py` | Catalog names, lake-contract column mapping, model endpoints, cost caps, frozen prompts, run log helper | — |
| `00_setup.py` | Catalog/schemas/volume, schema tags, benchmark hash check | Yes |
| `01_load_lake.py` | Parquet in UC Volume → Delta, contract check, row counts, file hashes, comments, tags, grain checks | Yes |
| `02_ai_functions.py` | `ai_classify`, `ai_extract`, `ai_query` (chat + embeddings), `ai_forecast`; deterministic scoring | Mostly; `ai_forecast` is a verify item |
| `03_vector_search.py` | AI Search (formerly Vector Search) Delta Sync index over O*NET; retrieval scoring | Yes (one endpoint) |
| `04_metric_views_and_genie.py` | UC metric views (YAML), a trusted SQL function, Genie Agent setup, 15 questions with expected SQL, 6 ambiguity/abstention cases, API-driven scoring | Verify Genie |
| `05_agent_framework.py` | Tool-calling agent (Genie + AI Search + document tool + decoy export tool), MLflow tracing, `mlflow.genai.evaluate` with code scorers | Verify tool-calling endpoint |
| `06_lakeflow_pipeline.py` | Lakeflow Spark Declarative Pipeline source (bronze → validated view → silver, quarantine, expectations) | Yes (one active pipeline per type) |
| `06b_pipeline_runbook.py` | Landing batches, bad-row injection, replay, event-log evidence | Yes |
| `07_governance.py` | Tags, row filter, column mask, aggregate suppression, negative access tests, optional ABAC, lineage, audit, data classification | Partly; real multi-user tests need paid |
| `08_app/` | Databricks App (Streamlit) role explorer: `app.py`, `app.yaml`, `requirements.txt`, `README.md` | Yes (3 apps, 24 h auto-stop) |
| `09_mlflow_classic_ml.py` | Leakage gate on benchmark `ml_features`, seeded synthetic attrition panel, chronological evaluation vs baseline, UC registry, batch scoring, rollback | Yes (batch only) |
| `99_cost_and_cleanup.py` | `system.billing.usage` + `list_prices` snapshot, guardrails, cleanup, export list | Billing tables: verify |
| `evidence_template.csv` | One row per kit test in the rubric's result-template columns | — |
| `review_labels_template.csv` | Human mapping labels (SUCSS class → approved O*NET code) | — |

## Prerequisites

1. **A workspace.**
   - Free Edition works for most steps; see the table below for which need paid.
   - For the paid steps, use a workspace where you can create a serverless usage policy and a budget.
   - Free Edition's terms say it **may not be used for commercial purposes**. Confirm with AITS or university policy that an institutional evaluation run there is allowed. If it is not, use an institution-approved trial or paid workspace.
2. **The public lake built locally.** The contract tables are Parquet files in `platform-evaluation/data/lake/contract/<table>.parquet`, built by `scripts/lake_contract.py` to lake contract v1.0 (`lake/CONTRACT.md`).
   - The table names are fixed by the contract.
   - Non-key column names were not final when this kit was written, so they are mapped in `_config.COL`. `01_load_lake` prints a contract check; if it reports a mismatch, edit `COL` there rather than editing notebooks.
   - `bls_oews` and `bls_projections` are *pending* in the contract and are skipped if absent.
3. **Repository access in the workspace.** Import this folder through a Git folder, which keeps `%run ./_config` and `08_app/` paths intact, or import the files individually.
4. **Uploads to the volume** (step 00 creates it):
   - `data/lake/contract/*` → `/Volumes/<catalog>/hr_public/lake/silver/`
   - `benchmark/fixtures/*.jsonl`, `benchmark/manifest.json` and `benchmark/documents.md` → `/Volumes/<catalog>/hr_public/lake/benchmark_v1/`
5. **Endpoint names.** On the Serving page, confirm the model endpoint names and set `CHAT_ENDPOINT`, `EMBED_ENDPOINT` and `AGENT_ENDPOINT` in `_config`. Record the exact model names and versions.

## Free Edition limits (from the Free Edition limitations page, found by docs search on 2026-11-06; recheck before running)

- **Compute:** serverless only. One SQL warehouse (2X-Small). Up to 5 concurrent job tasks. One active pipeline per pipeline type.
- **AI Search:** one endpoint, limited to one search unit. Direct Vector Access indexes are not supported.
- **Model serving:** limited active endpoints. No GPU serving, no provisioned throughput, no custom GPU models, and no batch inference; some models are unavailable. *Whether `ai_query` over a table counts as "batch inference" in Free Edition is a verify item.*
- **Apps:** up to 3 per account. Each stops automatically 24 h after it is started, updated or redeployed.
- **Unsupported products:** Knowledge Assistant and all legacy features. As of October 2026, Knowledge Assistant and Supervisor Agent are themselves legacy, and the Supervisor API reached end of life on 2026-09-30.
- **Genie:** no Free-Edition-specific Genie limits were found. Release notes say Genie usage is free through 2027-01-31, but whether that applies to Free Edition is unconfirmed.

### Steps that need, or may need, a paid workspace

| Step | Why |
|---|---|
| Cost guardrails (usage policy, budget, full `system.billing.*` access) | Account console features; Free Edition has no billing |
| 07 true negative access tests | Need separate non-owner test identities and service principals; a single Free Edition user can only toggle their own groups, and owners bypass grants |
| 07 ABAC `CREATE POLICY`, audit/lineage system tables, data classification | Availability in Free Edition unverified |
| 02 `ai_forecast` v2 | Needs the *Predictive AI Functions* preview enabled; v1 may also need a SQL warehouse |
| 02 large `ai_query` batches, 05 model deployment | Free Edition model-serving restrictions |
| 09 model monitoring and real-time serving | Free Edition restrictions; batch scoring works |

## Cost guardrails

1. **Before step 02 on a paid workspace:**
   - Create a **serverless usage policy** (the docs' newer name for budget policy) with the tag `project = hr_platform_eval`, and assign it to yourself.
   - Create a **budget** scoped to that tag with an email alert at a low threshold.
   - The `budget_policy_id` column in `system.billing.usage` is deprecated in favour of `usage_policy_id`.
2. **AI row caps** are set in `_config` (`CAP_*`). Total rows sent to AI per full run is roughly 200 classify + 150 extract + 100 chat + about 1,300 embeddings + 15–30 Genie questions + 12 agent cases. Raising a cap is a protocol change.
3. **Avoid always-on costs:**
   - Triggered (not continuous) pipeline and AI Search sync.
   - Delete the AI Search endpoint and stop the app when finished (`99`).
   - Serverless compute everywhere.
4. **Snapshot usage after each session.** Run `99_cost_and_cleanup` to save a `system.billing.usage` × `list_prices` snapshot (list-price estimate) into `hr_eval_results.cost_snapshots`. Budget alert emails can differ from `system.billing.usage`, which is the source of truth. Do not project institutional costs from list prices or Free Edition usage.

## Run order

| # | Notebook | Inputs | Output tables (in `<catalog>`) |
|---|---|---|---|
| 0 | `00_setup` | — | schemas `hr_public`, `hr_eval_results`, `hr_gov_synthetic`, `hr_public_pipeline`; volume `hr_public.lake`; `run_log` |
| 1 | upload files | local lake + benchmark copies | volume folders |
| 2 | `00_setup` again (hash check) | `benchmark_v1/manifest.json` | `run_log` pass/fail |
| 3 | `01_load_lake` | `silver/*.parquet` | `hr_public.*` tables, `load_manifest`, `grain_checks`, `hr_gov_synthetic.bm_*` |
| 4 | `02_ai_functions` (A–D first; E separately) | `hr_public` | `ai_classify_results`, `ai_extract_results`, `ai_query_skill_results`, `emb_*`, `semantic_candidates`, `ai_forecast_qwi`, `ai_scores` |
| 5 | Human review | 02's review sample | upload filled `review_labels_template.csv` as table `hr_eval_results.review_labels` (Catalog Explorer → Create table from file), then re-run 02 D and 03 scoring cells |
| 6 | `03_vector_search` | `hr_public` | `onet_occupation_doc`, the index, `ai_search_results` |
| 7 | `04_metric_views_and_genie` | `hr_public` | `mv_*` metric views, `fn_qwi_turnover_by_geo`, `genie_eval_cases`, `genie_eval_results` (run 3×) |
| 8 | `05_agent_framework` | Genie ID, index, `documents.md` | MLflow experiment `hr_platform_eval_agent`, `agent_eval_results` (run 3×) |
| 9 | `06b_pipeline_runbook` + pipeline from `06_lakeflow_pipeline` | silver Parquet | `hr_public_pipeline.bronze_*`, `silver_*`, `quarantine_*` |
| 10 | `07_governance` (once per role) | `bm_appointments` | `appointments_governed`, `workforce_aggregate_snapshot`, `governance_access_tests` |
| 11 | `08_app` | 01 (+02/03) | App `hr-role-explorer` |
| 12 | `09_mlflow_classic_ml` | `bm_ml_features` | `synthetic_attrition_panel`, MLflow experiment, UC model `synthetic_attrition_hazard`, `synthetic_attrition_scores` |
| 13 | `99_cost_and_cleanup` | system tables | `cost_snapshots`; cleanup |

Each notebook writes `run_id`, `protocol`, the executing user and timestamps. Copy each run's `RUN_ID` into the evidence CSV.

## Evidence checklist by rubric category

`evidence_template.csv` has one row per kit test with the rubric's result-template columns. Fill these in for each row:

- `edition_runtime`, `test_date` and `kit_run_id`
- `implementation_label`: *native* / *configured native* / *custom code* / *third-party dependency* / *unavailable in tested environment*
- setup, revision and reviewer hours
- `correctness`, `latency_p50_p95`, `billed_usage`, `evidence_location` and `limitations`

The `weight` column repeats the criterion weight; do not sum it across test rows. **Leave ratings blank until per-test checklists and thresholds are agreed (rubric rule).** "Not tested" stays blank, not zero.

| Rubric category | Kit evidence |
|---|---|
| Ingestion and transformation (I1–I3) | 01 contract check, load manifest with hashes, grain checks; 06/06b expectation metrics, quarantine counts, replay (silver unchanged), interrupted-update recovery |
| Business definitions (B1–B3) | 04 metric-view reconciliation vs base SQL; 07 aggregate snapshot = benchmark (3 people, 4 appointments, 2.5 FTE; departments suppressed); 01 comments/tags/Delta history; metric view YAML export |
| AI tools and agents (A1–A3) | `genie_eval_results` (held-out vs in-context reported separately, 3 runs), `ai_scores`, `ai_search_results`, `agent_eval_results` + MLflow traces, human labels for X01–X06, decoy-tool and DOC-UNTRUSTED results |
| Data science (M1–M3) | 09 leakage gate, seeded generator, chronological split, baseline/oracle comparison, bootstrap CI, calibration table, UC aliases, batch scoring, rollback drill; 02E forecast backtest vs seasonal naive |
| Dashboards (D1–D4) | Optional AI/BI dashboard on the 04 metric views with the Genie Agent attached (follow the benchmark dashboard change orders on synthetic data); 08 app deployment and negative test |
| Governance (G1–G2) | `governance_access_tests` per role; row filter/mask screenshots; lineage/audit query output; classification results; whether Genie, app and agent honour the same controls |
| Operations (O1–O2) | Everything deployed from this Git folder; pipeline bundle export; a second analyst reruns one step from this README alone |
| Cost and exit (C1–C2) | `cost_snapshots`, `run_log` rows sent to AI, endpoint/app lifetimes; 99 export list and restore-into-clean-schema timing |

Capture screenshots for UI-only steps (Genie configuration, pipeline graph, app, lineage graph, classification).

## What to record as a limitation

- **Any feature that fails, is missing or is quota-blocked.** Record it as *unavailable in tested environment (Free Edition)*, not "Databricks cannot". Include the exact error, the date and the runtime.
- **Preview and legacy states** as stated in the docs at test time. Examples:
  - `ai_forecast` v2 preview
  - data classification (GA in release notes, Public Preview on the system-table page)
  - Knowledge Assistant and Supervisor Agent (legacy)
- **Every *verify in workspace* item** that behaved differently from this kit's assumption, and the fix applied (a kit fix, not a protocol change, unless it touches prompts, caps, labels or scoring).
- **Lake contract mismatches** found by 01. These are lake-build issues, not platform issues.
- **Single-user testing:**
  - owner bypass of grants
  - app running as its service principal rather than the viewer
  - Genie and agent running as the notebook user
- **Agreement-only results** where no human labels exist, and the size of the labelled sample.
- **AI behaviours:** a forecast that loses to the seasonal-naive baseline, Genie answers that were "equivalent but differently shaped", and abstention failures.
- **Free Edition non-commercial terms** and any data-classification constraint that prevented a test.
- **Cost figures:** list-price estimates only. Free Edition usage is not a cost measurement.

## Items not verified against live docs

`docs.databricks.com` could not be fetched from the authoring environment, so syntax and status were checked through web-search summaries of the docs pages on 2026-11-06. Check these in the workspace first:

- Response shapes of `ai_classify`/`ai_extract` v2.1. The kit stores the raw output as a string and parses it defensively.
- `ai_query` `failOnError` struct field names (`result`, `errorMessage`) and `modelParameters`.
- The embedding endpoint name. Docs show both `databricks-gte-large-en` and `system.ai.gte-large-en`.
- `ai_forecast` argument names, and whether it runs from a notebook or needs a SQL warehouse.
- AI Search client methods: `create_endpoint(endpoint_type=...)`, `wait_for_endpoint`, `wait_until_ready`, and the `similarity_search` result layout. Also whether the SQL function is `vector_search` or `ai_search`.
- Metric view YAML keys: `dimensions` vs the newer `fields`, `filter`, and join `on: source.x = alias.x`. The spec version 1.1 runtime requirement is cited as DBR 18.2+ on one page and 17.2+ on another.
- Genie Agent ID location in the URL. SDK attributes `attachments[].query.query` / `.text.content`.
- `w.serving_endpoints.get_open_ai_client()`, `mlflow.genai.evaluate` scorer signatures (`trace` vs `traces`), and the `eval_result.tables` key.
- Lakeflow: `pyspark.pipelines` decorators (`dp.table`, `dp.materialized_view`, `dp.temporary_view`, `dp.expect_all_or_drop`) and `event_log(TABLE(...))`.
- `system.data_classification.results` column names, `system.access.audit` filters, and the `list_prices` pricing field (`pricing.default` vs `pricing.effective_list.default`).
- App `app.yaml` keys and on-behalf-of-user authorization; UI menu labels throughout.
- The IPEDS long-format totals filter (`sex = 'Total' AND race_ethnicity = 'Total'`) and the QWI totals codes (`sex = 0`, `agegrp = 'A00'`).

## Sources consulted (2026-11-06, via search)

AI Functions: [ai_classify](https://docs.databricks.com/aws/en/sql/language-manual/functions/ai_classify) · [ai_extract](https://docs.databricks.com/aws/en/sql/language-manual/functions/ai_extract) · [ai_forecast](https://docs.databricks.com/aws/en/sql/language-manual/functions/ai_forecast) · [ai_query](https://docs.databricks.com/aws/en/sql/language-manual/functions/ai_query) · [Query an embedding model](https://docs.databricks.com/aws/en/machine-learning/model-serving/query-embedding-models)

Free Edition: [Free Edition limitations](https://docs.databricks.com/aws/en/getting-started/free-edition-limitations) · [Agent Bricks FAQ](https://docs.databricks.com/aws/en/agents/concepts/faq) · [October 2026 release notes](https://docs.databricks.com/aws/en/release-notes/product/2026/october)

AI Search: [Create AI Search endpoints and indexes](https://docs.databricks.com/aws/en/vector-search/create-vector-search) · [databricks-ai-search (PyPI)](https://pypi.org/project/databricks-ai-search/)

Genie: [Genie Agents concepts](https://docs.databricks.com/aws/en/genie-agents/concepts) · [Tune Genie Agent quality](https://docs.databricks.com/aws/en/genie-agents/tune-quality) · [Genie SDK](https://databricks-sdk-py.readthedocs.io/en/latest/workspace/dashboards/genie.html)

Metric views: [Metric view YAML reference](https://docs.databricks.com/aws/en/uc-semantics/metric-views/yaml-reference) · [CREATE VIEW](https://docs.databricks.com/aws/en/sql/language-manual/sql-ref-syntax-ddl-create-view)

Lakeflow: [Pipeline expectations](https://docs.databricks.com/aws/en/ldp/developer/ldp-python-ref-expectations) · [Pipelines Python reference](https://docs.databricks.com/aws/en/ldp/developer/python-ref)

Governance: [Row filters and column masks](https://docs.databricks.com/aws/en/data-governance/unity-catalog/filters-and-masks/) · [CREATE POLICY](https://docs.databricks.com/aws/en/sql/language-manual/sql-ref-syntax-ddl-create-policy) · [Lineage system tables](https://docs.databricks.com/aws/en/admin/system-tables/lineage) · [Data Classification](https://docs.databricks.com/aws/en/data-governance/unity-catalog/data-classification)

Agents and MLflow: [Author an agent](https://docs.databricks.com/aws/en/agents/agent-framework/author-agent) · [Structured retrieval tools](https://docs.databricks.com/aws/en/generative-ai/agent-framework/structured-retrieval-tools) · [Code-based scorers](https://docs.databricks.com/aws/en/mlflow3/genai/eval-monitor/code-based-scorer-examples)

Apps: [app.yaml](https://docs.databricks.com/aws/en/dev-tools/databricks-apps/app-runtime) · [SQL warehouse resource](https://docs.databricks.com/aws/en/dev-tools/databricks-apps/sql-warehouse)

Billing: [Billable usage table](https://docs.databricks.com/aws/en/admin/system-tables/billing) · [Serverless cost monitoring](https://docs.databricks.com/aws/en/admin/system-tables/serverless-billing) · [Budgets](https://docs.databricks.com/aws/en/admin/account-settings/budgets)

Data attribution follows the parent [platform-evaluation README](../../README.md): O*NET 31.0 (USDOL/ETA, CC BY 4.0; mappings are ours and not endorsed by USDOL/ETA), SUCSS public catalog, IPEDS (NCES), QCEW (BLS), QWI (U.S. Census Bureau).
