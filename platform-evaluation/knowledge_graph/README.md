# Integrated workforce data network (prototype)

A knowledge graph that links the public workforce sources in the lake into one network: Illinois civil-service (SUCSS) classes, O*NET occupations, tasks, work activities, skills, knowledge, abilities, technology, IPEDS institutions, geography, industry, labor-market facts, and observed AI-usage evidence. It is the "role ontology" item (§3.4) in [research/CUSTOM_STACK_DIFFERENTIATORS.md](../research/CUSTOM_STACK_DIFFERENTIATORS.md).

**Status: prototype, public data only.** No university employee data is read or stored. SUCSS-to-O*NET links are unreviewed lexical suggestions, and every edge that uses them says so.

| File | What it is |
|---|---|
| [schema.md](schema.md) | Ontology: node and edge types, ID patterns, provenance columns, and placeholders for internal EDW data |
| [build_graph.py](build_graph.py) | Builds `data/lake/graph/nodes.parquet` and `edges.parquet` from the contract and silver layers |
| [graph_query.py](graph_query.py) | DuckDB query layer: `role_neighborhood`, `skill_overlap`, `reskilling_paths`, `sucss_to_tasks`, `institution_peer_context` |
| [export_explorer.py](export_explorer.py) | Writes the offline explorer `output/graph/workforce_graph_explorer.html` |
| [tests/test_graph.py](tests/test_graph.py) | Integrity and query tests (unittest) |
| [build_manifest.json](build_manifest.json) | Counts and timings from the last build. No row data |

## Run it

From `platform-evaluation/`, after `scripts/lake_build.py` and `scripts/lake_contract.py` have run:

```bash
pip install -r knowledge_graph/requirements.txt
python knowledge_graph/build_graph.py                    # about 3 s
python knowledge_graph/graph_query.py                    # demo of the five queries, with timings
python knowledge_graph/export_explorer.py                # about 35-40 s; writes output/graph/workforce_graph_explorer.html
python -m unittest discover -s knowledge_graph/tests -v  # 16 tests, about 2 s
```

`data/lake/` is git-ignored, so the graph tables are rebuilt rather than committed. Rebuilding gives identical node and edge IDs and content: IDs come from publisher codes, and edge IDs are hashes of `type|src|dst|qualifier`.

## What was built (2026-11-06 run)

**122,874 nodes and 399,444 edges.** Parquet files are 3.1 MB (nodes) and 6.5 MB (edges), zstd.

| Nodes | Count | | Edges | Count |
|---|---:|---|---|---:|
| LaborMarketFact | 59,759 | | HAS_ELEMENT_RATING | 146,551 |
| AIUsageEvidence | 20,983 | | HAS_FACT | 36,681 |
| Task | 18,838 | | USES_TECHNOLOGY | 31,821 |
| Technology | 8,753 | | ABOUT_OCCUPATION_GROUP | 30,757 |
| Institution | 6,090 | | ALIGNS_TO_DWA | 24,087 |
| Geography | 3,062 | | ABOUT_GEOGRAPHY / ABOUT_INDUSTRY | 23,078 each |
| DWA | 2,087 | | HAS_AI_USAGE_EVIDENCE | 22,907 |
| Occupation | 1,016 | | PERFORMS_TASK | 18,838 |
| SOC2018 | 890 | | RELATED_TO | 18,460 |
| SUCSSClass | 883 | | IN_CBSA | 7,001 |
| IWA | 332 | | LOCATED_IN | 6,069 |
| Ability / GWA / Skill / Knowledge | 52 / 41 / 35 / 33 | | CANDIDATE_MATCH (unreviewed) | 2,649 |
| IPEDSOccupationGroup / JobZone / Industry | 13 / 4 / 3 | | other (PART_OF, IN_STATE, MAPS_TO_SOC, IN_JOB_ZONE, BROADER, COVERS_SOC_GROUP) | 7,467 |

Edges by review status: 370,330 publisher-asserted, 26,443 derived by a deterministic rule, 22 curated (IPEDS occupation group to SOC major group), and 2,649 unreviewed (SUCSS candidates, with NULL confidence).

Findings from the build:

- **Integrity.** 0 duplicate node IDs, 0 duplicate edge IDs, 0 dangling edges, 0 internal node types. The first build found 43 dangling `HAS_FACT` edges. They came from 18 UNITIDs that reported IPEDS 2023 HR data but are missing from the HD2024 directory (closed or merged). The build now keeps their facts and adds flagged stub `Institution` nodes (`in_hd2024 = false`); it does not drop the rows.
- **AI-usage coverage.** 18,681 of 18,838 O*NET tasks (99.2%) match an Anthropic Economic Index (AEI) record by exact lower-cased text. Of the 21,363 AEI task rows, 1,129 have no O*NET text match and are left out of the graph. 7 rows were exact duplicates and were collapsed. When one AEI text matches several O*NET tasks, the edge records `text_shared_by_tasks`, because the evidence cannot be split between them.
- **Element ratings.** 911 of 1,016 occupations have O*NET element ratings. The other 105 ("All Other" and similar residual occupations) cannot get a similarity score, and the queries say so instead of returning a zero.
- **Suppression.** 15,116 of 22,947 annual QCEW facts (66%) are NULL because at least one quarter is suppressed. Most are county-level private or local-government college cells. They stay NULL and are never filled with zero.

Query latency on this container (DuckDB in memory, graph load 0.24 s):

| Query | Example | Time |
|---|---|---:|
| `role_neighborhood` | `onet:43-6011.00`, 2 hops, ≤ 10 neighbors per node → 85 nodes | 36 ms |
| `skill_overlap` | 15-1211.00 vs 15-1212.00 → cosine 0.963 (first call builds the vector table) | 190 ms |
| `reskilling_paths` | 43-6011.00 (Executive Secretaries), top 5 | 89 ms |
| `sucss_to_tasks` | class 4755, 3 candidates × 3 tasks | 35 ms |
| `institution_peer_context` | UIUC (145637): 106 Carnegie/sector peers, 13 salary groups | 103 ms |

### How the scores are defined

- **Element vector** (for `skill_overlap` and `reskilling_paths`): one component for each of the 161 rated elements (52 abilities, 33 knowledge areas, 10 essential and 25 transferable skills, 41 work activities). Each component is `((importance − 1) / 4) × (level / 7)`: the element's level, weighted by its importance. Across all 414,505 occupation pairs the cosine ranges from 0.229 to 0.99 (median 0.815, 5th percentile 0.633, 95th percentile 0.920). The vectors are all non-negative, so even unrelated jobs score around 0.6. Read the scores relative to each other, not as absolute values.
- **Reskilling gap:** for knowledge and skills only (abilities are treated as enduring traits), and only where the target occupation rates the element at importance 3 or higher, the gap sums `max(0, target level − current level) × (target importance − 1) / 4`.
- **Reskilling order:** the candidates are O*NET's own related occupations. They are ordered by O*NET tier, then the smallest gap, then the highest cosine, then the code. The order is deterministic (tested). AI-usage evidence is attached to each result as context, with a note, and the test checks that it never affects the order.

## The explorer

`output/graph/workforce_graph_explorer.html` (1.3 MB, one file, no network, vanilla JS and inline SVG). Pick a SUCSS class or an O*NET occupation to see:

- the unreviewed candidate list, with flags;
- a role network of tasks, technology, skills and related roles (click a related role to open it);
- observed AI-usage evidence, with the metrics kept side by side;
- the top tasks, skills, knowledge and work activities;
- related roles with cosine, skill gap and the largest gaps;
- labor-market context: IPEDS non-instructional pay for the matching occupation group at UIUC, UIC and UIS against public R1 peers (hidden below 5 staff); QCEW higher-ed employment and pay in Champaign, Cook and Sangamon counties; and QWI Illinois hires and separations, with provisional quarters flagged.

The explorer has light and dark themes and was checked by screenshot at 1280 px and 390 px wide. It covers 306 occupations in the administration and business, IT, HR, finance, library, and facilities and trades families, and the 543 SUCSS classes with at least one candidate among them.

## Why a graph, and where it does not help

**Where it helps.**

1. **The questions are paths.** "Which tasks does civil-service class X probably involve, and which of those show AI usage?" is the path `SUCSSClass → Occupation → Task → AIUsageEvidence`. "What pay context goes with this role?" is `Occupation → SOC → SOC major → IPEDS group ← fact ← Institution`. In flat tables each question is a hand-written chain of 4 to 6 joins, and each new question is a new chain. In the graph, each one is a traversal over two tables.
2. **Provenance lives on the relationship.** A SUCSS-to-O*NET link, an AEI text match and a curated IPEDS-to-SOC rule differ in how far you can trust them. Every edge carries `method`, `confidence` and `review_status`, so a query can include or exclude unreviewed links explicitly. In flat tables, provenance usually sits at the table level and is lost after a join.
3. **One schema for many sources.** New sources add node and edge types, not new join logic. Internal data (Section "Internal data" below) attaches through the same two tables.
4. **Portability.** Two Parquet tables load into any engine listed below.

**Honest limits.**

- **Not faster on a single engine.** Everything here runs as SQL joins in DuckDB, and a well-indexed star schema would answer the same fixed questions at least as fast. The research brief's fair test (20 path questions, compared against recursive CTEs for correctness, latency and lines of code) **has not been run.** No speed or accuracy advantage is claimed.
- **The weakest link is the most important one.** SUCSS-to-O*NET candidates come from title similarity only and are unreviewed. Any SUCSS-to-task result is a hypothesis until a person validates duties, ideally against class specifications.
- **O*NET describes national occupations, not University jobs.** Tasks and skills describe the typical U.S. worker in an occupation, not a specific position or person.
- **AEI is observed Claude usage.** It is not job loss, not University work, and not a forecast. It is never combined into a score here and never attached to people.
- **The IPEDS group bridge is coarse.** One salary group covers whole SOC major groups (for example, all of 13-0000). It is context, not the pay of an occupation.
- **`props` is JSON.** That keeps the schema stable, but typed queries need `json_extract`. A production version would promote heavily used properties to typed columns or per-type tables.
- **Cosine similarity of non-negative O*NET vectors compresses toward 0.6 to 0.95.** Mean-centering per element would spread the scores. That would be a new labelled method version, not a silent change.

## Hosting the same node and edge tables elsewhere

The two tables are the interchange format. Every target below loads them unchanged. `node_type` becomes a label or table, and `edge_type` becomes a relationship type.

| Target | How |
|---|---|
| **Neo4j** (Community or Aura) | Export each `node_type` and `edge_type` to CSV (one DuckDB `COPY ... WHERE node_type = ...` per type) and load with `neo4j-admin database import full`. Put `node_id` in an `:ID` column, `node_type` in `:LABEL`, and `edge_type` in `:TYPE`. Flatten `props` with `json_extract` into typed columns during export. Add a uniqueness constraint on `node_id`. Path questions become Cypher, for example `MATCH (s:SUCSSClass)-[c:CANDIDATE_MATCH]->(:Occupation)-[:PERFORMS_TASK]->(t:Task) WHERE c.review_status = 'unreviewed' ...` |
| **LadybugDB** (MIT fork of the archived Kùzu) | Embedded and in-process, like DuckDB. Create one `NODE TABLE` per node type with `node_id` as the primary key and one `REL TABLE` per edge type, then bulk-load from Parquet (Kùzu supported `COPY ... FROM` Parquet; confirm in the current LadybugDB release). Cypher queries run locally, which suits approved on-prem machines |
| **DuckDB + DuckPGQ** | Keep the Parquet files and declare a SQL/PGQ property graph over `nodes` and `edges` for `MATCH` path syntax. This is the smallest step from this prototype; the extension is community-maintained |
| **Snowflake** | Two tables, with `props` as `VARIANT`, loaded with `COPY INTO` from a stage of the Parquet files (or as Iceberg tables). Traversals are joins or recursive CTEs, since Snowflake has no native property-graph engine. The `graph_query.py` SQL ports with mostly mechanical changes (`json_extract` → `props:key::type`) |
| **Databricks** | Two Delta tables registered in Unity Catalog, with `props` as `STRING` or `VARIANT`. Use SQL joins for the fixed queries and GraphFrames for algorithms such as connected components or PageRank on the role network. Unity Catalog lineage and ABAC can enforce that internal node types stay in a restricted schema |

On every target, the provenance columns and the "unreviewed" rule travel with the data rather than living in one tool.

## Internal data: approved machines only

[schema.md §4](schema.md#4-internal-node-types-placeholders-not-populated) defines `Person`, `Appointment`, `Position`, `Department`, `LearningActivity`, `Requisition` and `Posting`. These are placeholders: nothing in this repository creates them, and a test fails if one appears.

On an approved University machine, an internal build would:

1. Read `T_PERS_HIST`, `T_EMPEE_HIST` and `T_JOB_DETL_HIST` from the EDW into `data/local/` (git-ignored), never into `data/lake/`.
2. Write internal nodes and edges to a separate pair of tables (for example `data/local/graph/internal_{nodes,edges}.parquet`) that point *into* the public graph by its stable IDs: `Appointment -CLASSIFIED_AS-> sucss:<id>` and `Person -EMPLOYED_BY-> ipeds:145637`. The public tables stay unchanged and shareable.
3. Effective-date every internal edge: `valid_from` / `valid_to` come from `*_EFF_DT` / `*_EXP_DT`, with sentinels normalized, effective sequence in the qualifier, and load time as transaction time. Answer as-of questions with an interval filter.
4. Keep person, appointment and position as separate grains, and keep demographic attributes in a restricted side table rather than in `props`.
5. Use local or on-prem models for any text work (such as reviewing SUCSS-to-O*NET candidates against class specifications), record reviewer decisions as new edge versions with `review_status = 'reviewed'`, and publish only aggregates with minimum cell sizes.
6. Under Illinois HB 3773, do not use reskilling or AI-usage outputs to score or rank individuals without legal review.

## Attribution

O*NET 31.0 Database by USDOL/ETA, used under CC BY 4.0; O*NET is a trademark of USDOL/ETA. IPEDS (NCES), QCEW (BLS) and QWI (Census LEHD) are U.S. federal public data. The Anthropic Economic Index is used under its published license. The SUCSS class catalog is public.
