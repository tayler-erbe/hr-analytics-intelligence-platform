# Snowflake trial-run kit (public data only)

Kit v0.1 — drafted 2026-11-06 for rubric v1.0 / benchmark v1.0. **Not yet executed in any Snowflake account.** Every script was written from the documentation and syntax-reviewed only. No platform score has been earned.

This kit lets you exercise Snowflake's main AI and data capabilities in a trial account: Cortex AI Functions, Cortex Search, semantic views with Cortex Analyst, Cortex Agents and Snowflake Intelligence, ML forecasting and the Model Registry, governance policies, and Streamlit. It uses only public workforce data: O*NET, the SUCSS class catalog, IPEDS, BLS QCEW and Census QWI. Each step writes its results to tables and to `evidence_template.csv`, so they can be scored against [rubric v1.0](../../PLATFORM_EVALUATION_RUBRIC.md).

## Scope and data rules

- **Public data only.** Never upload institutional HR, payroll, appointment, applicant, org-chart or any other non-public university data to a trial account. That applies even after de-identification and even "just to test". Trial accounts are not an authorized destination, and the production gate *"environment and data destinations are institutionally authorized"* has not been met.
- The only non-public-source table is `HR_KIT.GOV_DEMO.SYNTH_APPOINTMENTS` in 07. It is invented and labelled synthetic.
- Inputs are the public silver lake tables from `data/lake/contract/*.parquet`, under lake contract v1.0 (`lake/CONTRACT.md`). Load them unchanged.
- **This kit is capability exploration, not benchmark scoring.** Official ratings for I/B/G and the AI suite must use the frozen fixtures in `../../benchmark/` (`fixtures/`, `cases.json`, `answer_keys.json`, `documents.md`), verified against `benchmark/manifest.json` hashes. Do not edit anything under `benchmark/`. Where this kit touches the benchmark (05 §5 copies `documents.md` into a table), it reads the file and records its hash. It never modifies it.
- Track: **platform-native** (rubric "Evidence rules"). Record every product, edition, preview feature and model you use.
- Scoring rules: no model grades another model. Human reviewer columns (`reviewer_*`) are left blank on purpose. Agreement between two methods is not accuracy. Keep every attempted row, error and truncation.

## Files

| File | What it does | Rubric criteria |
|---|---|---|
| `00_setup.sql` | Resource monitor, XSMALL warehouse (60 s auto-suspend, 15 min statement timeout), roles, `HR_KIT` database and schemas, parquet file format, stages, Cortex role grants | O1, C1 |
| `01_load_lake.sql` | Upload instructions (CLI/SnowSQL/Snowsight); `INFER_SCHEMA` + `COPY INTO … MATCH_BY_COLUMN_NAME`; load log; row-count reconciliation; grain checks; idempotent re-run; **conformed `CURATED` views (the only place lake column names are assumed)** | I1, I3, B3 |
| `02_ai_functions.sql` | AI_CLASSIFY (job families); AI_COMPLETE structured output with task-id citations; AI_EXTRACT; AI_EMBED + VECTOR_COSINE_SIMILARITY and AI_SIMILARITY vs the lexical candidates; AI_AGG / AI_SUMMARIZE_AGG; AI_FILTER vs keyword baseline; repeatability; cost and latency queries. Every step is capped, and each writes a result table with reviewer columns | A1, A2, C1 |
| `03_cortex_search.sql` | Search corpus (occupation and task chunks), Cortex Search service, `SEARCH_PREVIEW`, 17 retrieval tests with hit@1/hit@5/MRR | A2, A3, C1 |
| `semantic_model_hr_public.yaml` | Semantic model (IPEDS institution/staff/salary, QCEW, QWI, area), with 10 verified-query **drafts** | B1, B3 |
| `04_semantic_view_and_analyst.sql` | Creates the semantic view from YAML, exports DDL, checks semantic-layer vs hand-SQL reconciliation, defines the 15 accuracy questions with expected SQL plus 5 clarification/abstention probes, a run log and a result-set comparison procedure | A1, A2, B1, C2 |
| `05_agents_intelligence.md` | Cortex Agent spec (Analyst + Search tools), Snowflake Intelligence publishing, REST runs, 14 agent prompts, instruction-boundary test, audit queries | A1–A3, G2 |
| `06_ml.sql` | `SNOWFLAKE.ML.FORECAST` on QWI turnover, with chronological holdout, leakage check, baselines, interval coverage, and a scheduled task (suspended) | M1–M3 |
| `06_ml_notebook.py` | Snowflake Notebook: lag features, Ridge vs naive baselines, Model Registry log/version/run, rollback drill | M1–M3, O1 |
| `07_governance.sql` | Tags, tag-based masking, row access policy, aggregation policy (min group 3), role tests with expected results, AI-boundary probe, classification, ACCESS_HISTORY read/write lineage | G1, G2, B3 |
| `08_streamlit_app.py` | Streamlit-in-Snowflake role explorer (class → occupation, search, labor-market charts, Analyst test harness) | D1, D2, D4, A1 |
| `evidence_template.csv` | One row per step: timings, credits, tokens, errors, hashes, reviewer minutes, limitations | all |

## Prerequisites

1. **A Snowflake trial account, Enterprise edition.** Choose this at sign-up: masking, row access, aggregation policies, classification and ACCESS_HISTORY need Enterprise. An AWS US region (for example us-west-2 or us-east-1) gives the widest Cortex model coverage. Verify current model availability per region on the AI Functions page. Record the edition, cloud and region in evidence row S00.
2. An `ACCOUNTADMIN` login for setup. Day-to-day work runs as `HR_KIT_ADMIN` and `HR_KIT_ANALYST`.
3. One way to upload files: Snowflake CLI (`snow`), SnowSQL, or the Snowsight file upload UI.
4. The lake parquet files and the lake manifest, with SHA-256 hashes and row counts, from the data-lake build.
5. A human reviewer for the `reviewer_*` columns, and for approving expected codes and expected SQL before scoring.

## Trial-account restrictions (record whatever you actually hit)

| Item | What the docs say (searched 2026-11-06) | Status |
|---|---|---|
| Trial credit / duration | Free trial credits for a limited period, shown at sign-up | Record the actual amount and end date |
| Cortex LLM function cap | Accounts **without a payment method (for example, trials)** are limited to **about 1 credit/day** of Cortex LLM function usage | Documented; can block 02 if you raise the caps |
| Cross-region inference | `CORTEX_ENABLED_CROSS_REGION` (ACCOUNTADMIN). New commercial accounts created on or after 2026-03-09 reportedly default to `ANY_REGION`; others default to `DISABLED`. A pending 2026_06 behavior change sets it automatically for eligible accounts unless a value was already set | Check `SHOW PARAMETERS` in 00 and record the value used |
| AI Functions access | Account-level `USE AI FUNCTIONS` (granted to PUBLIC by default since 2026-02) plus the `SNOWFLAKE.CORTEX_USER` or `AI_FUNCTIONS_USER` database role; per-model RBAC rollout in 2026 | Granted in 00 |
| Cortex Analyst | Controlled by the `ENABLE_CORTEX_ANALYST` account parameter | Check in 00 |
| Snowflake Intelligence / Agents | Not confirmed for trials | If missing: "unavailable in tested environment" |
| Streamlit runtime | Warehouse runtime and container runtime (compute pool). The 2026_06 BCR makes container runtime the default for new apps; this kit pins `SYSTEM$WAREHOUSE_RUNTIME`. Container apps need an external access integration for PyPI | Record the runtime you used |
| External network access / compute pools in trials | Not confirmed | Not needed by this kit |
| Classification / ACCESS_HISTORY | Enterprise; ACCOUNT_USAGE latency up to about 3 h; automatic classification can take an hour or more to start | Plan the 07 evidence capture for later the same day |

## Cost guardrails

1. **Resource monitor `HR_KIT_MONITOR`** (25 credits/month): notifies at 50% and 80%, suspends at 95%, and suspends immediately at 100%. It caps **warehouse** credits only. It does **not** cap serverless AI spend (AI Functions, Search serving and indexing, Analyst, Agents).
2. **Warehouse `HR_KIT_WH`**: XSMALL, `AUTO_SUSPEND = 60`, `INITIALLY_SUSPENDED`, `STATEMENT_TIMEOUT_IN_SECONDS = 900`. Never resize it for this kit.
3. **AI caps** live at the top of 02 (`N_CLASSES=50`, `N_OCC=20`, `N_TASKS=200`, `N_AGG_GRPS=5`). Embeddings cover about 1k O*NET occupations once, and the table is reused on re-runs. AI_SIMILARITY runs only on the lexical top-5 pairs, never on a full cross join. Run 02 with the defaults and check the credits before raising any cap.
4. **Cortex Search** accrues serving cost while the service exists. Drop or suspend `ONET_ROLE_SEARCH` (and `BENCH_DOC_SEARCH`) when 03 and 05 are finished.
5. **Task** `QWI_FORECAST_TASK` is created suspended and executed once by hand. Leave it suspended.
6. **Query tags** (`hr_kit:<step>`) isolate kit activity in QUERY_HISTORY.
7. **Usage views to check after each session** (ACCOUNT_USAGE latency is minutes to hours; view names marked * should be verified in your account):

```sql
USE ROLE HR_KIT_ADMIN;   -- has IMPORTED PRIVILEGES on SNOWFLAKE
-- Warehouse credits
SELECT start_time::DATE d, SUM(credits_used) credits FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
WHERE warehouse_name = 'HR_KIT_WH' GROUP BY 1 ORDER BY 1;
-- All services by type (AI services appear as their own service_type)
SELECT usage_date, service_type, SUM(credits_used) FROM SNOWFLAKE.ACCOUNT_USAGE.METERING_DAILY_HISTORY
WHERE usage_date >= DATEADD(DAY, -14, CURRENT_DATE()) GROUP BY 1, 2 ORDER BY 1, 2;
-- AI Functions per query (GA 2025-12-01; replaces CORTEX_FUNCTIONS_QUERY_USAGE_HISTORY)
SELECT * FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_AISQL_USAGE_HISTORY ORDER BY 1 DESC LIMIT 200;
-- Search, Analyst, Agents (*)
SELECT * FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_SEARCH_DAILY_USAGE_HISTORY ORDER BY 1 DESC;
SELECT * FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_ANALYST_USAGE_HISTORY ORDER BY 1 DESC;
SELECT * FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_AGENT_USAGE_HISTORY ORDER BY 1 DESC;
```

Also screenshot Snowsight → Admin → Cost management at the end of each day. Do not project production costs from trial usage. The rubric forbids precise projections without institutional pricing.

## Column assumptions (fix once, in 01 STEP D)

The lake contract fixes the table names but not every column name. All downstream scripts read only the `HR_KIT.CURATED` views. If `DESCRIBE TABLE` shows different names, edit the views in `01_load_lake.sql` STEP D and nothing else.

| View | Assumed source columns |
|---|---|
| `V_ONET_OCCUPATION` / `V_ONET_TASK` | `onetsoc_code, title, description`; `task_id, task, task_type` (from the contract) |
| `V_ONET_TECH_SKILL` | `example, commodity_code, hot_technology, in_demand` |
| `V_SUCSS_ONET_CANDIDATE` | `source_record_id, onetsoc_code, rank, score` |
| `V_IPEDS_INSTITUTION` | `unitid, name, state, sector, carnegie` |
| `V_IPEDS_SALARY_NONINSTR` / `_INSTR` | `unitid, survey_year, occupation_category / academic_rank, contract_length, staff_count, salary_outlays` |
| `V_IPEDS_STAFF` | `unitid, survey_year, occupation_category, headcount` (filter to total rows if the long format has them) |
| `V_QCEW` | BLS names `area_fips, own_code, industry_code, year, qtr, qtrly_estabs, month3_emplvl, total_qtrly_wages, avg_wkly_wage` |
| `V_QWI_HIGHER_ED` | `state_fips, county_fips` (5-digit; NULL = statewide), `industry, year, quarter, sex, agegrp, emp, hira, sep, turnovrs, earns` |

## Run order

| # | Step | Role | Notes |
|---|---|---|---|
| 1 | `00_setup.sql` | ACCOUNTADMIN, then HR_KIT_ADMIN | Record edition, region and the cross-region parameter |
| 2 | Upload parquet (01 STEP A) | HR_KIT_ADMIN | From a terminal or the Snowsight UI |
| 3 | `01_load_lake.sql` B–D | HR_KIT_ADMIN | Fix view column names until the smoke test passes. Re-run B to show idempotency |
| 4 | `02_ai_functions.sql` | HR_KIT_ADMIN | Run section by section and check credits after 2a. Reviewers fill `reviewer_*` later |
| 5 | `03_cortex_search.sql` | HR_KIT_ADMIN | A reviewer approves `SEARCH_TESTS.expected_codes` before the metrics count |
| 6 | `04_semantic_view_and_analyst.sql` | HR_KIT_ADMIN | Paste the YAML, verify it, then create. A reviewer approves the expected SQL |
| 7 | `08_streamlit_app.py` deploy | HR_KIT_ADMIN | Used as the Analyst test harness for step 8 |
| 8 | Analyst tests T01–T15, C01–C05 | HR_KIT_ANALYST | ≥ 1 run each; 3 runs for T02, T03, T09, T12, C01, C03 |
| 9 | `05_agents_intelligence.md` | HR_KIT_ADMIN / ACCOUNTADMIN, then HR_KIT_ANALYST | Agent, Intelligence, AG01–AG14, boundary test |
| 10 | `06_ml.sql`, then `06_ml_notebook.py` | HR_KIT_ADMIN | The notebook needs 06_ml.sql steps 1–2 |
| 11 | `07_governance.sql` | HR_KIT_ADMIN + each test role | Run the lineage queries 3 h or more later |
| 12 | Cost queries above; fill row S99; cleanup | HR_KIT_ADMIN | |

Cleanup when finished: drop the search services, keep the task suspended, export the result tables (`HR_KIT.AI_EVAL.*`, `HR_KIT.ML.*`, LOAD_LOG) to CSV for the evidence folder, then `DROP DATABASE HR_KIT;` and `DROP WAREHOUSE HR_KIT_WH;`. Exporting tests C2 (exit effort). Record how long it took.

## Evidence capture checklist (by rubric category)

For **every** step: fill the matching `evidence_template.csv` row. Capture the query id, start and end time, elapsed time, rows, credits once the usage views catch up, errors and retries, setup, revision and reviewer minutes, and a screenshot or export path. The `implementation_label` must be one of: native; configured native; custom code; third-party dependency; unavailable in tested environment.

- **I — ERP ingestion (public-data proxy only):** stage inventory with MD5s plus the lake manifest SHA-256 values; LOAD_LOG; COPY_HISTORY; row-count MATCH table; duplicate-grain checks; a second COPY run that loads 0 rows (I3); the list of skipped pending tables. *I2 (temporal/grain correctness) needs the benchmark appointments fixture; it is not covered here.*
- **B — Business definitions:** the semantic view DDL export (`GET_DDL`); the reconciliation of semantic view vs hand SQL vs average-of-averages (B1); source_id/source_vintage visible in the CURATED views and the YAML descriptions (B3). *Benchmark B1/B2 cases (headcount vs appointments vs FTE, funding fan-out) must be run on the benchmark fixtures.*
- **A — AI tools and agents:** the `R_*` tables in `HR_KIT.AI_EVAL` with reviewer columns completed; the invalid-citation rate (2b); search metrics on approved expected codes; `R_ANALYST_RUNS` with comparison results, observed behavior and reviewer verdicts; agent traces showing tool calls and SQL; the boundary-test transcript; variability across repeated runs; p50 and p95 latency.
- **M — Data science:** the series snapshot hash and feature snapshot hash; the leakage check with 0 rows; holdout MAE vs both baselines **with n**; interval coverage; model registry versions; the scheduled task history; the rollback drill timing.
- **D — Dashboards:** the deployed Streamlit app (runtime, owner role, URL); time to first working version vs time to a validated version; one change request applied and rolled back (S08c); a keyboard and readability check. *The four benchmark dashboard views and change orders 1–6 use the benchmark fixtures; this app is a public-data proxy.* The legacy Snowsight dashboards have been retired, so do not evaluate them.
- **G — Governance:** role-by-role actual vs expected results for 07 §6; the masked-input AI probe; classification output (true and false positives); POLICY_REFERENCES; ACCESS_HISTORY read lineage, write lineage and policies_referenced; agent RBAC denial (AG14); the Streamlit owner's-rights observation.
- **O — Operations:** all objects created from these version-controlled files; one injected failure and its recovery, for example a renamed column in a *copy* of a lake table fed through 01 STEP D (record the detection and the repair effort); a second analyst re-running one step from this README.
- **C — Cost and exit:** S99 totals by service type; the time to export result tables and DDL (semantic view, agent `DESCRIBE`, Streamlit source); and whether a semantic view or agent spec can be reproduced outside Snowflake. The YAML is portable; the DDL is Snowflake-specific.

## What to record as a limitation

Write these in the `limitation` column and in scorecard `limitations`. A trial restriction is "unavailable in tested environment", not proof that the product lacks the feature.

- Features or models unavailable in the trial, edition or region, and any cross-region setting you had to enable (prompts left the region; public data only).
- Rate limits or caps hit, especially the roughly 1 credit/day Cortex cap. Record any step you shrank to fit, with the original and reduced N.
- Syntax that differed from this kit, marked "verify in account" below. Paste the error text verbatim and the fix you used.
- Preview features you used (rubric "release_state"). Check the AI Functions page on the day of the run.
- Rows with NULL, error or truncated AI output. Keep them; do not re-run selectively to improve results.
- Non-determinism: label changes between repeated runs (2g, the triple Analyst runs).
- Steps where Snowflake needed custom code, such as the Snowflake Scripting loops in 01 and 03, the comparison procedure, and the notebook. These are effort, not failures.
- Governance semantics that did not match the benchmark policy. Examples: aggregation policy counts rows rather than distinct people; the Streamlit app runs with owner's rights; masking under inherited roles.
- ACCOUNT_USAGE latency, which delays the cost and lineage evidence.
- Lake gaps: pending BLS tables, suppressed QCEW/QWI cells, partial years, and IPEDS long-format total rows.
- Evaluation weaknesses: kit-authored expected codes and expected SQL (approved by whom, and when); small holdout n in 06; the 15 Analyst questions are **development** cases, not a blind holdout. Keep them out of the verified queries and agent instructions.
- Anything this kit could not test: real ERP connectors, the benchmark fixtures, dashboard migration fidelity, production identity (SSO/SCIM), private connectivity.

## Verification status of syntax used (docs searched 2026-11-06)

`docs.snowflake.com` could not be fetched from the authoring environment, because the network allowlist blocked it. Syntax was checked against documentation search excerpts. Treat each item below as **verify in account** until it has run.

| Feature | Basis | Confidence |
|---|---|---|
| AI_CLASSIFY (label + description list, `task_description`, `output_mode`, `labels` output) | Function reference excerpts; GA 2025-11-04 | High |
| AI_EXTRACT (`text =>`, `responseFormat =>` object form; `response` wrapper) | Function reference excerpts; GA | Medium (output wrapper) |
| AI_COMPLETE named args with `response_format {'type':'json','schema':…}` | Structured-outputs page excerpts | Medium (named `model_parameters` form, return type) |
| AI_FILTER + PROMPT, AI_AGG, AI_SUMMARIZE_AGG, AI_SIMILARITY, AI_EMBED | Overview excerpts; exact signatures not retrieved | Medium |
| VECTOR(FLOAT,1024) and VECTOR_COSINE_SIMILARITY; embed model `snowflake-arctic-embed-l-v2.0` | Prior knowledge | Medium |
| CORTEX_AISQL_USAGE_HISTORY (GA 2025-12-01); other Cortex usage view names | Release note / prior knowledge | High / Low |
| CREATE CORTEX SEARCH SERVICE … ON … ATTRIBUTES … EMBEDDING_MODEL; SEARCH_PREVIEW JSON | Reference excerpts (newer TEXT/VECTOR INDEXES form exists in some pages) | Medium–High |
| SYSTEM$CREATE_SEMANTIC_VIEW_FROM_YAML(schema, yaml, verify_only) | Reference excerpts | High |
| YAML keys (`base_table`, `primary_key`, `facts`, `metrics`, `relationships`, `verified_queries`) and `__table` names in verified SQL | Prior knowledge of the Analyst spec | Medium |
| SEMANTIC_VIEW(... DIMENSIONS ... METRICS ...) query; `GET_DDL('SEMANTIC_VIEW', …)`; grant privilege on semantic views | Prior knowledge | Medium |
| CREATE AGENT … FROM SPECIFICATION (tools/tool_resources, `cortex_analyst_text_to_sql`, `cortex_search`) | Reference excerpts | Medium (instructions/models/execution_environment keys) |
| Snowflake Intelligence object, `ALTER SNOWFLAKE INTELLIGENCE … ADD AGENT` | Docs excerpts | Medium (exact CREATE form) |
| CREATE SNOWFLAKE.ML.FORECAST / !FORECAST / prediction_interval | Reference excerpts | High; `ON_ERROR` option Medium |
| Model Registry Python API | Prior knowledge (snowflake-ml-python 1.x) | Medium |
| CREATE STREAMLIT … RUNTIME_NAME; owner's rights; `_snowflake.send_snow_api_request` for Analyst REST | Reference + BCR excerpts / prior knowledge | Medium |
| Masking, row access, tag-based masking, aggregation policies, SYSTEM$CLASSIFY, ACCESS_HISTORY JSON paths | Prior knowledge + classification excerpts | Medium |

## Attribution

O*NET 31.0 Database by USDOL/ETA, CC BY 4.0. O*NET is a trademark of USDOL/ETA. Kit mappings and extractions are not endorsed by USDOL/ETA. The SUCSS public class catalog is from the Illinois State Universities Civil Service System. IPEDS (NCES), QCEW (BLS) and QWI (U.S. Census Bureau) are public statistical sources; see the lake manifest for vintages and URLs.
