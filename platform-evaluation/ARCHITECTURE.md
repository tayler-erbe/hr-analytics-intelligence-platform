# Project map: how the whole workspace fits together

Written 2026-11-06. This page is the map. Each folder's own README has the details, the exact counts and the caveats. Where this page and a component README disagree, the component README wins. Please report the mismatch so this page can be corrected.

Offline portal to every demo page: [output/index.html](output/index.html).

## 1. Purpose and audiences

The project turns workforce data into evidence that HR leaders can check. It also tests, fairly, whether Snowflake, Databricks or a custom stack is the best home for that work. There are three strands:

1. **The original POC idea** (root [README](../README.md)): internal mobility, succession readiness and workforce forecasting from EDW HR history. The POC notebooks are not in this repository. They live in an internal Box folder.
2. **A public evidence layer** that needs no employee data: a public HR data lake, a role knowledge graph, a reskilling map, an external-evidence page and a synthetic scenario planner.
3. **A neutral platform evaluation**: a frozen rubric, a synthetic benchmark with answer keys, trial-run kits for Snowflake and Databricks, and a custom stack that competes under the same tests.

| Audience | What they need | Start here |
|---|---|---|
| HR leaders (Illinois HR Strategic Programs & Partnerships) | What can be shown today, what it means, and what it must not be used for | [research/IHR_STRATEGIC_PROGRAMS_OPPORTUNITY_BRIEF.md](research/IHR_STRATEGIC_PROGRAMS_OPPORTUNITY_BRIEF.md), then [output/index.html](output/index.html) |
| AITS Decision Support / platform decision makers | A fair comparison and its rules | [PLATFORM_EVALUATION_RUBRIC.md](PLATFORM_EVALUATION_RUBRIC.md), [benchmark/README.md](benchmark/README.md), [research/README.md](research/README.md) |
| Engineers and analysts joining the project | How to rebuild everything and where data may and may not go | This page, §8 run order, then [lake/README.md](lake/README.md) and [lake/CONTRACT.md](lake/CONTRACT.md) |
| Governance, privacy and legal reviewers | What data is used, where it lives, and which uses are excluded | §6 governance, [research/HR_USE_CASES_AND_GUARDRAILS.md](research/HR_USE_CASES_AND_GUARDRAILS.md), [DATA_INTAKE.md](DATA_INTAKE.md) |

## 2. Layered architecture

Read from top to bottom. Solid boxes exist and run today. Boxes marked `[not populated]` are designed but hold no data in this repository.

```text
 SOURCES
 ├─ Public (downloaded by scripts)        O*NET 31.0 · IPEDS HR 2023 + HD2024 · BLS QCEW · Census LEHD QWI
 │                                        Indeed Hiring Lab · Anthropic Economic Index · Illinois SUCSS catalog
 │                                        [pending: BLS OEWS/Projections/JOLTS · Census ACS API · IPEDS 2024 HR]
 ├─ Synthetic (generated, seeded)         benchmark v1.0 fixtures · Demo University IT org · workforce_sim population
 └─ Internal [not populated]              EDW person/position/appointment history · JDX descriptions · requisitions
                                          learning records · survey text  → approved machines only (data/local/)
        │
        ▼
 RAW        data/lake/raw/<source>/        byte-for-byte downloads, SHA-256 + HTTP status in acquisition_manifest
        │                                  (also data/raw/ for the Oct 29 pilot: O*NET JSON + SUCSS response)
        ▼
 SILVER     data/lake/silver/*.parquet     80 typed tables, one per published file; codes kept as strings
        ▼
 CONTRACT   data/lake/contract/*.parquet   23 tables, fixed names/grains; source_id + source_vintage on every row
        │   (lake/CONTRACT.md v1.0)        ← the ONE input for Snowflake kit, Databricks kit and custom stack
        ▼
 GOLD /     lake/gold/gold_views.sql       11 portable views (peer pay, QCEW trend, QWI flows, AI evidence ...)
 SEMANTIC   custom_stack/semantic/specs    one metric spec → DuckDB SQL · Snowflake semantic view · Databricks metric view
        ▼
 GRAPH      knowledge_graph/               122,874 nodes · 399,444 edges · provenance + review_status on every edge
        │                                  [internal Person/Appointment/Position nodes: specified, not populated]
        ▼
 APPLICATIONS
   output/lake/external_evidence.html      public peer pay, employment, turnover, AI-usage evidence
   output/graph/workforce_graph_explorer   role ontology explorer (SUCSS ↔ O*NET ↔ tasks ↔ facts)
   output/reskilling/...                   role evolution + AI-literacy reskilling map (role grain only)
   output/workforce_sim/scenario_planner   Monte Carlo scenarios on a synthetic, publicly calibrated workforce
   output/demo/role-evolution.html         fictional IT organization, deterministic "agent" proposals
   custom_stack nl2sql + MCP server        governed metric questions: answer | clarify | abstain
        ▼
 EVALUATION
   PLATFORM_EVALUATION_RUBRIC v1.0 (100 pts + gates) · benchmark v1.0 (30 cases, answer keys, 6 blank scorecards)
   platform_kits/snowflake · platform_kits/databricks (written, not executed) · custom_stack/eval (44 questions)
```

## 3. Component table

Status: **built** = runs end to end and has produced its outputs; **prototype** = runs and is tested, but its method or mappings are not reviewed for real use; **design-only** = written or specified, not executed; **in progress** = folder exists, no README yet.

Data class: **public** = published open data; **synthetic** = invented or generated; **internal-only** = may hold university records and must stay on approved machines, never in Git.

| Folder / file | What it does | Inputs | Outputs | Tests | Status | Data class |
|---|---|---|---|---|---|---|
| [`lake/`](lake/README.md) + `scripts/lake_*.py` | Downloads, hashes and types public workforce data; builds the contract layer and gold views; generates vendor DDL | Public URLs in `lake/sources.json` | `data/lake/{raw,silver,contract}`, `hr_public.duckdb`, `lake/manifests/`, `lake/ddl/` | `scripts/test_lake.py` (18) | built | public |
| `scripts/build_external_evidence_page.py` | Renders the external-evidence page from gold views | `data/lake/hr_public.duckdb` | `output/lake/external_evidence.html` | none dedicated | built | public |
| [`knowledge_graph/`](knowledge_graph/README.md) ([schema](knowledge_graph/schema.md)) | Role ontology linking SUCSS, O*NET, IPEDS, QCEW, QWI and AI-usage evidence | Contract + silver tables | `data/lake/graph/{nodes,edges}.parquet`, `output/graph/workforce_graph_explorer.html` | `knowledge_graph/tests` (16) | prototype | public (internal node types reserved, not populated) |
| [`reskilling/`](reskilling/README.md) | Task portfolio, durable skills, adjacent roles and AI-literacy targets per role | Contract + silver tables, `competency_framework.yaml` | `reskilling/artifacts/`, `output/reskilling/role_evolution_reskilling.html` | `reskilling/tests` (11) | prototype | public |
| [`workforce_sim/`](workforce_sim/README.md) | Quarterly Monte Carlo scenario planner with P10/P50/P90 ranges | Public aggregates (IPEDS 12,905 UIUC staff, QWI hazards) → `calibration.json` | Synthetic tables, `scenario_grid.json`, `output/workforce_sim/scenario_planner.html` | `workforce_sim/tests` (17) | prototype | synthetic, calibrated to public |
| [`custom_stack/`](custom_stack/README.md) | One semantic spec compiled to DuckDB/Snowflake/Databricks; deterministic NL-to-metric planner; MCP server; scorer for vendor answers | Contract tables; benchmark fixtures (read-only) | `semantic/generated/`, `eval/results_*` | `custom_stack/tests` (91) | prototype | public + synthetic |
| [`benchmark/`](benchmark/README.md) | Frozen synthetic ERP fixtures, 30 cases, reference SQL, answer keys, access-policy spec, 6 blank scorecards | Frozen generator | `benchmark/fixtures`, `manifest.json`, `data/local/benchmark_v1.sqlite`, `scorecards/` | `benchmark/test_reference.py` (9) | built (scorecards ungraded) | synthetic |
| [`platform_kits/snowflake`](platform_kits/snowflake/README.md) | Trial-run scripts for Cortex AI functions, Search, Analyst, Agents, ML, governance, Streamlit | Contract parquet; benchmark copies | Evidence CSV rows, result tables (once run) | none (syntax-reviewed only) | design-only | public + synthetic |
| [`platform_kits/databricks`](platform_kits/databricks/README.md) | Trial-run notebooks for AI Functions, Vector Search, metric views + Genie, agents, Lakeflow, governance, MLflow | Contract parquet; benchmark copies | Evidence CSV rows, result tables (once run) | none (not executed) | design-only | public + synthetic |
| [`research/`](research/README.md) | Platform capability reviews, custom-stack differentiators, HR use cases and guardrails, SP&P opportunity brief, 31-source catalog | Public web sources (search excerpts) | Markdown reports, `public_data_source_catalog.json` | n/a | built (documents) | public |
| `scripts/prepare_pilot.py`, `data/raw`, `data/prepared` | Oct 29 pilot: O*NET + SUCSS reference tables and a title-only review queue | `data/raw/` | `data/prepared/*.jsonl`, `manifest.json` | none dedicated | built | public |
| `notebooks/01_databricks_reference_pilot.py` | Imports the pilot JSONL into Databricks and shows the review queue | `data/prepared/*.jsonl` in a UC Volume | Delta tables (optional) | syntax-checked only | design-only | public |
| `scripts/workforce_store.py` ([DATA_INTAKE.md](DATA_INTAKE.md)) | Local SQLite evidence store for dated org-chart, directory, appointment, description and posting observations | Public reference tables; JSONL observations in `data/local/` | `data/local/*.sqlite`, coverage report | `scripts/test_workforce_store.py` (4) | built | public reference; imported observations internal-only |
| `scripts/build_synthetic_demo.py`, `build_demo_explorer.py`, `templates/` ([design](SYNTHETIC_DEMO_AND_AGENT_DESIGN.md)) | Fictional "Demo University Shared IT" (57 positions, 171 role snapshots, 48 proposals) | Seeded generator | `data/synthetic/*.jsonl`, `output/demo/role-evolution.html` | none dedicated | built | synthetic |
| `ai_proficiency/` | Human-scored AI proficiency rubric and 12 work tasks aligned to AI Explorer/Catalyst/Practitioner; reliability, Angoff, DIF | Synthetic ratings (real work samples internal-only) | `output/ai_proficiency/rubric_toolkit.html`, reliability report | 42 | prototype | synthetic |
| `ai_usecases/` | AI use-case registry: intake schema, 17 triage rules (HB 3773 to Tier 4), measured-time ROI, reuse map | Fictional entries | `output/ai_usecases/registry.html` | 68 | prototype | synthetic |
| `survey_text/` | Exit and satisfaction comment pipeline: layered redaction, lexicon/NMF themes, loopback-only LLM coder, eNPS drivers, quote approval | Synthetic Qualtrics-style exports (real text internal-only) | `output/survey_text/survey_insights.html` | 23 | prototype | synthetic |
| `ai_adoption/` | AI Adoption Impact Scorecard: reach → proficiency → 30/60/90-day behavior → results, badge-to-talent view, complementary suppression | Synthetic program events (real extracts internal-only) | `output/ai_adoption/ai_adoption_scorecard.html` | 28 | prototype | synthetic |
| `sucss_mapping/` | Duty-based SUCSS class → O*NET matcher with evidence pairs and abstention; 4,415-row HR review queue; no spec text in Git | Public SUCSS series pages (cached, gitignored) | `outputs/review_queue.*`, `summary.json` | 13 | prototype | public |
| `peer_benchmarks/` | Fall 2015–2023 IPEDS trends for U of I vs Big Ten publics, CPI-adjusted pay, comparability flags | Public NCES files, BLS CPI-U | `output/peer_benchmarks/peer_trends.html` | 20 | built | public |
| `policy_assistant/` | Cited HR policy Q&A over public IHR/SUCSS pages with refusal rules and deterministic eval | Public pages (crawl gitignored) | Local demo page (gitignored), eval results | 27 | prototype | public |
| `erp_readiness/` | 43 HR conversion-readiness checks compiled to 4 SQL dialects, readiness gates, mock-conversion reconciliation | Synthetic EDW-shaped history | `output/erp_readiness/readiness_dashboard.html` | 20 | prototype | synthetic |
| `sponsored_funding/` | Federal grant run-rate and expiry cliff for UIUC/UIC; designed labor-distribution join | USAspending, NIH RePORTER | `output/sponsored_funding/funding_cliff.html` | 20 | built | public |
| `faculty_pipeline/` | Faculty rank/tenure/SURS retirement Markov model with 225 scenarios | IPEDS, literature, synthetic ages/tiers | `output/faculty_pipeline/faculty_pipeline.html` | 16 | prototype | public + synthetic |
| `swp_workbench/` | Evidence layer under IHR's nine Strategic Workforce Planning worksheets | Synthetic workforce (workforce_sim), reskilling outputs | `output/swp_workbench/swp_workbench.html` | 27 | prototype | synthetic |
| `SERVER_PROJECT_PRESERVATION_HANDOFF.md` | Separate handoff for backing up server pipeline projects | — | — | — | design-only | n/a |

Test counts are `def test` functions in each file, counted 2026-11-06.

## 4. How components connect

**Data contracts.** Every downstream component reads the contract layer, not silver files or publisher layouts. [lake/CONTRACT.md](lake/CONTRACT.md) v1.0 fixes table names, grains and 10 rules: provenance columns, codes as strings, IPEDS total rows, no double counting across categories, pre-partitioned salary tables, suppressed values stay NULL, QCEW overlap, QWI scope, unreviewed mappings, and AI usage as evidence. A contract change needs a version bump and must be applied to all three implementations before they are compared. The benchmark has its own frozen contract: `benchmark/manifest.json` hashes. Kits and the custom stack copy the fixtures and check those hashes. They never edit them.

**IDs.** Joins use publisher codes, always as strings:

| Key | Joins |
|---|---|
| O*NET-SOC (`15-1211.00`) and SOC 2018 (`15-1211`) | O*NET tables, AEI occupation exposure, crosswalk, reskilling roles |
| O*NET task ID | Tasks; AEI task usage by exact lower-cased text (99.2% match) |
| SUCSS `source_record_id` (not class code; class 1164 has two records) | SUCSS classes and their unreviewed O*NET candidates |
| IPEDS UNITID (UIUC 145637, UIC 145600, UIS 148654, System 149587) | All IPEDS tables, institution nodes |
| FIPS, CBSA, NAICS (611310, 6113) | QCEW and QWI areas and industries |
| Internal (reserved): `EDW_PERS_ID` hash, `POSN_NBR`, effective sequence | Person, Appointment and Position nodes on approved machines ([schema.md §4](knowledge_graph/schema.md)) |

Graph IDs add a namespace prefix (`onet:`, `sucss:`, `ipeds:`, `fips:`, `task:`). Edge IDs are hashes of `type|src|dst|qualifier`, so rebuilds give the same IDs. The intake store never merges people by name. Position links use `institution_id + position_id` only.

**Provenance.** Raw downloads carry URL, HTTP status, size, SHA-256 and timestamp. Contract rows carry `source_id` and `source_vintage`. Graph edges add `method`, `confidence` (NULL when nobody has assessed it) and `review_status` (`publisher_asserted`, `derived_rule`, `curated_rule`, `unreviewed`). Reskilling recommendations cite the metric and release. Generated pages print their source, grain and caveat on each panel. Manifests (`lake/manifests`, `knowledge_graph/build_manifest.json`, `reskilling/artifacts/manifest.json`) record counts and hashes, not row data.

**Time.** Public data is a snapshot whose time is in `source_vintage`. Internal data must be effective-dated and bitemporal: `[valid_from, valid_to)` plus `known_from`. The benchmark tests this (2.75 FTE known earlier against 2.5 FTE after a late correction). The workforce simulator's synthetic tables use the same shape.

## 5. Three evaluation tracks

Rubric v1.0 is frozen: 100 points across seven categories, plus gates that a high score cannot override. All six scorecards are blank. No platform has earned a score.

| Track | What is compared | Who competes | Current state |
|---|---|---|---|
| **Platform-native** | Each vendor's supported stack, including its own AI, ML and dashboard tools. Every added product, edition and preview is recorded | Snowflake (Cortex, Analyst, Agents, Streamlit), Databricks (AI Functions, Genie, Agent Bricks, MLflow, AI/BI) | Kits written; not executed in any vendor account |
| **Common implementation** | The same business logic and, where feasible, the same model, retrieval and BI front end on each platform, so platform effects are separated from model or tool effects | Snowflake, Databricks, custom | Generated semantic view and metric view DDL from `custom_stack`; not deployed |
| **Custom** | The independent stack under exactly the same tests and labor accounting, entered in whichever track applies | `custom_stack` (DuckDB, deterministic planner, MCP, optional local model) | 44-question development set, 0 unsafe answers. This is a **visible** dev set, not a holdout |

Shared rules: the same frozen fixtures and answer keys; no model grades another model; agreement is not accuracy; every attempt, error and retry is kept; capability and implementation effort are reported separately.

## 6. Governance rules

1. **Public only in Git.** The lake, graph, reskilling map and pages use public data. University HR, payroll, org-chart, appointment, applicant and survey exports go in `data/local/` (git-ignored) on approved machines. `data/lake/` is also git-ignored and rebuilt from the registry and hashes.
2. **Synthetic demos are labeled.** The benchmark, Demo University IT and the workforce simulator are invented or generated. Each page says so. None supports a conclusion about real staff.
3. **Illinois HB 3773 (P.A. 103-0804, in effect 2026-01-01).** AI that influences hiring, promotion, discipline, discharge or terms of employment is high-risk. Retention-risk scoring and AI-assisted classification need legal review before any individual-level use.
4. **No individual scoring.** No attrition, readiness or "AI replaceability" score for a person. Outputs are at role, class, unit or cohort grain. Mobility and succession views are advisory and explained. Pay and demographic views use minimum cell sizes.
5. **Local inference for restricted text.** Position descriptions, survey text and HR records go only to on-prem or enterprise-approved models. Snowflake cross-region inference must be restricted for HR data. Trial and Free Edition accounts receive public or synthetic data only.
6. **AI usage is evidence, not a forecast.** Anthropic Economic Index metrics describe observed use of tasks. They are never combined into a job-loss score.
7. **Mapping status is written down.** SUCSS → O*NET links stay `unreviewed` until an HR analyst confirms them. A similarity score is not a probability.

## 7. What is real, what is synthetic, what is not yet built

| Real (public data, actually downloaded and processed) | Synthetic (invented or generated) | Not yet built or not yet run |
|---|---|---|
| O*NET 31.0 (1,016 occupations, 18,838 tasks) | Benchmark v1.0 ERP fixtures (5 positions, proposals, awards, job runs) | Any Snowflake or Databricks execution; any earned rubric score |
| SUCSS catalog (883 records) and its 2,649 *unreviewed* candidates | Demo University Shared IT (57 positions, 171 snapshots, 48 proposals) | Reviewed SUCSS → O*NET mappings |
| IPEDS Fall 2023 HR, HD2024, EFFY2024 | `workforce_sim` population (12,905 people, totals matched to IPEDS) | BLS OEWS, Employment Projections, JOLTS silver tables |
| QCEW 2015–2025, QWI Illinois higher ed, Indeed, AEI | `custom_stack/tests/fixtures/contract` | Census ACS county labor table; IPEDS 2024 HR |
| 80 silver, 23 contract, 11 gold; graph with 122,874 nodes | All SP&P prototypes run on synthetic data | Internal EDW history, JDX, requisitions, learning, survey data (none present) |
| Research reports (from search excerpts; vendor feature status unverified) | Scenario assumptions such as hiring freezes and AI capacity (user-set) | Blind holdout question sets for AI evaluation |
| | | Reviewed SUCSS mappings; vendor-account runs of both kits; a blind holdout question set |
| | | Live autonomous agents; POC models (Markov, SRI, departure risk) on real data |

## 8. Run order

From `platform-evaluation/` with Python 3.12 or 3.13. Network is needed only for `lake_acquire.py`.

```bash
# 0. dependencies
pip install duckdb pyarrow openpyxl pyyaml
pip install -r custom_stack/requirements.txt -r knowledge_graph/requirements.txt -r workforce_sim/requirements.txt

# 1. public lake: raw -> silver -> contract (+ gold views, DDL)
python scripts/lake_acquire.py
python scripts/lake_build.py
python scripts/lake_contract.py
python scripts/build_external_evidence_page.py          # output/lake/external_evidence.html

# 2. graph and role layers
python knowledge_graph/build_graph.py
python knowledge_graph/export_explorer.py               # output/graph/workforce_graph_explorer.html
python reskilling/build_pathways.py
python reskilling/render_explorer.py                    # output/reskilling/role_evolution_reskilling.html

# 3. scenario planner (synthetic)
python workforce_sim/calibrate.py
python workforce_sim/synthesize.py
python workforce_sim/simulate.py --workers 4
python workforce_sim/build_page.py                      # output/workforce_sim/scenario_planner.html

# 4. synthetic demo, pilot and intake store
python scripts/prepare_pilot.py
python scripts/build_synthetic_demo.py
python scripts/build_demo_explorer.py                   # output/demo/role-evolution.html
python scripts/workforce_store.py

# 5. evaluation
python benchmark/build_pack.py
python benchmark/score_report.py
python -m custom_stack.semantic.cli check-contract
python -m custom_stack.semantic.cli compile
python -m custom_stack.eval.score --real-lake --data-dir data/lake/contract

# 6. tests
python -m unittest scripts/test_lake.py scripts/test_workforce_store.py
python -m unittest discover -s benchmark -p test_reference.py
python -m unittest discover custom_stack/tests
python -m unittest discover -s knowledge_graph/tests
python -m unittest discover -s reskilling/tests
python -m unittest discover -s workforce_sim/tests
```

Platform kits run inside vendor trial accounts by following their READMEs. Use public and synthetic data only.

## 9. Open gaps

- **BLS OEWS, Employment Projections and JOLTS** are not downloaded. BLS returns HTTP 403 unless the User-Agent includes a contact email. Fix: `BLS_USER_AGENT="hr-analytics-lab name@illinois.edu" python scripts/lake_acquire.py --only bls_oews bls_projections bls_jolts`. Silver and contract tables for them still have to be written.
- **The Census API** (ACS county labor) needs a key in the URL. No key is configured. QWI comes from LEHD bulk files instead, which need no key.
- **SUCSS → O*NET mappings are unreviewed.** They are lexical title suggestions; 623 of 883 rank-1 matches have similarity below 0.35. Individual SUCSS class specifications have not been downloaded. Every downstream SUCSS view inherits this caveat.
- **The platform kits have not run in vendor accounts.** Feature status comes from documentation excerpts. No Snowflake or Databricks score exists, and the generated semantic view and metric view DDL has not been deployed.
- **No blind holdout.** The benchmark's 30 cases and the custom stack's 44 questions are visible development sets.
- **Other data gaps:** IPEDS 2024 HR files return 404, so Fall 2023 is the latest. The 219 MB AEI 2026-06-26 release was blocked by the network. QWI cannot separate public from private colleges. The latest two QWI quarters are provisional.
- **Internal data is absent by design.** Real POC models (mobility, succession, forecasting) need approved EDW history, longitudinal outcomes and HB 3773 review first.
- **SP&P prototypes are unvalidated on real data.** Every SP&P component runs on synthetic or public data; each README lists what real data and reviews it needs before use.
- **Business definitions need owners.** Benchmark definitions are approved for the synthetic fixture only. AITS domain-owner approval for real measures, performance targets and the peer panel (a proposal, not an approved HR peer group) is still pending.
