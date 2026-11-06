# Custom stack: governed metrics + deterministic NL-to-metric + MCP

This is the custom-built counterpart to Snowflake Cortex Analyst (semantic views) and Databricks Genie (Unity Catalog metric views). It is a candidate implementation under [rubric v1.0](../PLATFORM_EVALUATION_RUBRIC.md). It is **not** a score, a production approval or evidence that it beats either vendor. No Snowflake or Databricks account was used. Vendor artifacts are generated, not executed.

```
semantic/specs/*.yaml     ONE portable spec per model (entities, grains, dimensions, metrics, rules, synonyms, verified queries)
        |                 (hr_public: the public lake contract layer; benchmark_workforce: frozen benchmark v1.0 fixtures)
        +--> compile_duckdb.py      reference SQL compiler + executor (engine.py)
        +--> compile_snowflake.py   CREATE SEMANTIC VIEW DDL + Cortex Analyst semantic-model YAML
        +--> compile_databricks.py  UC metric view YAML (v1.1) + CREATE VIEW ... WITH METRICS DDL
        +--> portable.py            single-pass measure expressions carrying the grain rules into vendor targets
nl2sql/planner.py         question -> plan (answer | clarify | abstain), SQL, provenance; no LLM needed
nl2sql/llm_backend.py     OPTIONAL local OpenAI-compatible plan proposer (Ollama/vLLM), off by default
mcp_server/server.py      stdio MCP server: list_metrics, describe_metric, query_metric
eval/questions.yaml       44 NL questions with expected plan / clarification / abstention
eval/score.py             scorer for the custom planner AND for recorded Cortex Analyst / Genie answers
tests/                    91 unittest tests; synthetic contract-shaped fixtures in tests/fixtures/contract
```

Generated artifacts for review are in `semantic/generated/<model>/`. `PORTABILITY.md` there lists every metric, which targets can express it, and each rule that was lost.

## Run

From `platform-evaluation/` (Python 3.13; `pip install -r custom_stack/requirements.txt`, which installs only duckdb and pyyaml):

```bash
python -m unittest discover custom_stack/tests                       # or from repo root: ... discover platform-evaluation/custom_stack/tests
python -m custom_stack.semantic.cli check-contract                     # spec columns vs data/lake/contract/*.parquet
python -m custom_stack.semantic.cli compile                            # regenerate DuckDB/Snowflake/Databricks artifacts
python -m custom_stack.nl2sql.cli "Staff FTE by sector in 2023"        # real lake by default; --data-dir to override
python -m custom_stack.eval.score                                      # fixture scoring (hand-fixed answers)
python -m custom_stack.eval.score --real-lake --data-dir data/lake/contract
python -m custom_stack.mcp_server [--data-dir DIR]                     # stdio MCP server
```

Data location: `hr_public` reads `data/lake/contract/<table>.parquet` by default. This is the contract-named layer in lake contract v1.0; the draft contract said `silver/`. Override with `CUSTOM_STACK_LAKE_DIR` or `--data-dir`. `benchmark_workforce` reads `benchmark/fixtures/*.jsonl` read-only. A test checks those files' hashes against the frozen manifest.

MCP client configuration example:

```json
{"command": "python", "args": ["-m", "custom_stack.mcp_server"],
 "cwd": "<repo>/platform-evaluation", "env": {"CUSTOM_STACK_LAKE_DIR": "<repo>/platform-evaluation/data/lake/contract"}}
```

## Design

**One spec, three targets.** Entities declare their table (or a logical SQL view), grain, primary key and typed columns. They also declare dimensions with synonyms and value synonyms, time dimensions, and *constrained dimensions*. Relationships are typed. Only `many_to_one` and `one_to_one` joins are ever followed. `many_to_many` relationships are declared so the system can explain a refusal: for example, AEI task text to O*NET tasks would fan out usage percentages. Metrics are `simple` (sum/count/count_distinct/min/max; `avg` is rejected), `ratio` (ratio of sums at the requested grain) or `derived` (each component aggregated separately, then joined).

**Grain rules are enforced by the compiler, not the NL layer.** That means MCP clients and direct plans get the same rules:

| Rule | Example in the spec |
|---|---|
| Headcount, FTE and appointment count are separate metrics | `wf_headcount` = COUNT DISTINCT person; `wf_appointment_count` = COUNT; `wf_fte` = SUM. Reproduces benchmark v1.0: 3 / 4 / 4 filled / 2.5 FTE (2.75 as known on Oct 31), POS5 vacant |
| Never sum salaries or averages across a fan-out | Salary averages are `SUM(outlays)/SUM(staff)` ratios; spec validation rejects joins that are not to a full primary key |
| Published total rows are never added to their members | EAP: only `is_category_total = false` rows (lake contract rule 4; UIUC Fall 2023 = 12,905). QWI: `sex='0'`, `agegrp='A00'` unless the user asks for a breakdown. QCEW: ownership `0` excluded when summing members |
| Stocks are not summed over time | EAP/EFFY headcounts need one period (else **clarify**). QCEW/QWI employment is summed within a quarter, then averaged across quarters |
| Overlapping geographies need a choice | QCEW `area` unconstrained → **clarify** (national, state and county rows overlap) |
| Suppressed cells are not silently dropped | `null_policy: propagate`: any NULL (QCEW disclosure `N`, unpublished QWI quarter) makes the result NULL instead of an understated sum |
| Metric-specific rules | Average instructional salary defaults to 9-month contracts; the count metric on the same table does not |
| Derived ratios use a common population | `staff_fte_per_100_students` aligns EAP Fall *N* with EFFY *N+1*. It aligns on `unitid`, so the 176 EAP institutions without enrollment do not inflate the ratio |
| Hierarchical dimensions are labelled | Grouping by nested levels (enrollment level, NAICS) adds an explicit "do not add these rows" assumption |

**Planner (no LLM).** Every token must map to a metric or source synonym, a dimension, a dimension value, a time expression, a ranking word or a spec-listed ignorable word. Otherwise the planner abstains and names the unmapped words. Nothing is silently dropped. Policy rules run first: causal, obsolescence, forecast, person-level and instruction-injection questions, plus pending sources. An ambiguous term ("employees") yields a clarification listing governed options. Context such as "Sangamon County" or "QWI" can narrow the options. Each answer carries the plan, SQL, a token-level trace and assumptions such as defaults applied, as well as provenance: definitions, spec SHA-256, tables, joins, source vintages from the data, and join coverage (e.g. 18 EAP unitids with no HD2024 record).

**Optional LLM backend.** It is off unless `CUSTOM_STACK_LLM_ENDPOINT` and `CUSTOM_STACK_LLM_MODEL` are set. Non-local hosts are refused unless `CUSTOM_STACK_LLM_ALLOW_REMOTE=1`. It sees only the metric catalog, never data. It may propose only a structured plan, clarification or abstention, and only after the deterministic parser abstained for lexical reasons. Its plan goes through the same validator and compiler, is labelled `planner: llm:<model>`, and cannot override a policy abstention. Tests use a fake backend; no network calls are made.

## How it compares with Cortex Analyst and Genie

| Aspect | Custom stack | Cortex Analyst (semantic view) | Genie (UC metric views + space) |
|---|---|---|---|
| Definition source | Portable YAML, compiled to all three | Snowflake-native object | Databricks-native object(s) |
| SQL generation | Deterministic compiler; no LLM required | LLM over the semantic model | LLM over tables/metric views and instructions |
| Grain rules | Enforced structurally (two-stage rollups, partition filters, alignment, NULL propagation) | Partly expressible. The generated DDL folds rules into measures (`portable.py`); "choose an area" survives only as instructions | Same; one source per metric view, so the cross-entity ratio is not emitted |
| Clarify / abstain | Explicit, rule-based, auditable | Model behavior; must be tested | Model behavior; must be tested |
| Paraphrase robustness | Lexical. It abstains on unknown words (3 of 12 untuned paraphrases abstained safely, 9 answered correctly) | Likely stronger (LLM) | Likely stronger (LLM) |
| Ops and cost | Our code to maintain; runs anywhere DuckDB runs | Managed; credits | Managed; DBUs |

The portability report counts what is lost. For `hr_public`, 8 of 21 metrics compile to every target without caveat. The cross-entity derived ratio is not emitted to Cortex YAML or to a single metric view. Rules such as "area must be chosen" or "use member rows when grouped by sex" cannot be folded into one aggregate, so those vendor artifacts carry them as comments or instructions. Tests execute the folded single-pass expressions on DuckDB and check they equal the reference compiler (stock averaging, NULL-on-multi-period, suppression, total-row exclusion, metric filters).

## Evaluation

`eval/questions.yaml` has 44 questions: 34 on `hr_public` and 10 on the frozen benchmark. 28 expect answers, 7 a clarification and 9 an abstention. **It is a visible development set.** The planner's synonyms were written while these questions were visible: one synonym (`full-time staff headcount`) was added after a dev-set miss, and another fix landed after the time parser consumed a value phrase. These scores are not a holdout result. Rubric v1.0 requires separately authored held-out questions before any generalization claim.

| Run | behaviour | exact plan | result equality | clarification recall | abstention recall | unsafe answers |
|---|---|---|---|---|---|---|
| Fixtures (hand-fixed values), `eval/results_fixture.*` | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 0.00 |
| Real lake contract layer, `eval/results_real_lake.*` | 1.00 | 1.00 | 1.00* | 1.00 | 1.00 | 0.00 |

\*On the real lake, hand-fixed values do not apply. The `hr_public` reference is the expected plan executed by the same compiler, so result equality there mostly re-checks plan equality. Real-data values were checked independently in `tests/test_real_lake.py`: the UIUC total, partition = published total for Illinois, SUCSS 883/882, AEI release sums to 100%, and suppressed Champaign cells stay NULL.

**Scoring Cortex Analyst and Genie with the same set.** Load the same `data/lake/contract` snapshot into `HR_PUBLIC` / `hr_analytics.hr_public`, and deploy the generated semantic view or metric views (or the vendor team's own definitions, labelled as such). Then ask each question verbatim and record one JSON line per question (`eval/external_answers_template.jsonl`):

- `status` (`answer` / `clarify` / `abstain` / `error`) is assigned by a **human reviewer** from the transcript. No model grades another model.
- `rows` is the full-precision result exported from the vendor (not a screenshot or rounded display), and `sql` is the generated SQL verbatim.

Score with `python -m custom_stack.eval.score --external answers.jsonl --system cortex_analyst --real-lake --data-dir data/lake/contract`. Result sets are compared to the reference rows ignoring row order, column order and names. Numbers must match within 1e-6 (no rounding), and extra columns are allowed and reported. Exact-plan accuracy applies only to the custom planner; vendors are scored on behavior and result equality. Record run IDs, latency and cost separately per the rubric result template. Repeat a subset to expose variability.

## Known limitations

- Definitions are development definitions over public data and have not been approved by any domain owner. `benchmark_workforce` definitions are approved for that fixture only.
- The Snowflake and Databricks syntax follows documentation as understood on 2026-11-06 and has not been executed. Validate in the vendor before scoring, and record failures as findings.
- One real-lake quirk remains visible: unitid `113537` (318,020 EAP staff) has no HD2024 institution record. It appears as a NULL institution group and is reported in join coverage.
- Illinois statewide QCEW 611310 totals are NULL for 2024 because local-government cells are suppressed. That is correct under the "suppression stays NULL" rule; group by `ownership` to see published cells.
- The planner is lexical. It fails safe (abstains) on unseen vocabulary, which costs coverage. The LLM fallback exists for that but has not been evaluated.
- No access control is implemented here. The rubric's role tests (T1_ANALYST etc.) remain a separate requirement.
