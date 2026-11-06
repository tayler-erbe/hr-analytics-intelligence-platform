# Workforce data network: ontology v0.1

This is the node and edge model behind `build_graph.py`. Two Parquet tables hold the whole graph:

- `data/lake/graph/nodes.parquet`
- `data/lake/graph/edges.parquet`

Git ignores both because they sit under `data/lake/`. Rebuild them from the contract and silver layers with `python knowledge_graph/build_graph.py`, run from `platform-evaluation/`.

Everything populated here is **public data**. The internal node types in [Section 4](#4-internal-node-types-placeholders-not-populated) are placeholders only. Their tables are empty, and they stay empty in this repository.

## 1. Table shapes

### nodes

| Column | Type | Meaning |
|---|---|---|
| `node_id` | VARCHAR, unique | Stable, human-readable ID with a namespace prefix (see 2) |
| `node_type` | VARCHAR | One of the node types in 2 |
| `label` | VARCHAR | Display name |
| `code` | VARCHAR | Publisher code without the prefix (O*NET-SOC, UNITID, FIPS and so on). Always a string; leading zeros are kept |
| `props` | VARCHAR (JSON) | Type-specific attributes |
| `source_id`, `source_vintage` | VARCHAR | Provenance carried from the contract table (contract rule 1) |

### edges

| Column | Type | Meaning |
|---|---|---|
| `edge_id` | VARCHAR, unique | `e:` plus the first 20 hex characters of `md5(edge_type|src|dst|qualifier)`, so the same fact keeps the same ID on every rebuild |
| `src_id`, `dst_id` | VARCHAR | Must exist in `nodes` (tested) |
| `edge_type` | VARCHAR | One of the edge types in 3 |
| `weight` | DOUBLE, nullable | Type-specific numeric value, such as O*NET importance or lexical similarity. Never a probability unless 3 says so |
| `props` | VARCHAR (JSON) | Type-specific attributes |
| `source_id`, `source_vintage` | VARCHAR, required | Where the fact came from |
| `method` | VARCHAR, required | How the edge was produced, such as `onet_published_rating:Incumbent`, `exact_lowercase_task_text_match` or `title_lexical_baseline_v1` |
| `confidence` | DOUBLE, nullable | 1.0 when the publisher asserts the link or a deterministic rule derives it exactly. **NULL when nobody has assessed it**, which is the case for every unreviewed lexical suggestion. It is never a lexical score relabelled as a probability |
| `review_status` | VARCHAR, required | `publisher_asserted`, `derived_rule`, `curated_rule` or `unreviewed` (see below) |
| `valid_from`, `valid_to` | DATE, nullable | Business-valid interval. NULL for snapshot public data, whose time is in `source_vintage`. Required for the internal effective-dated edges in 4 |

`review_status` values:

| Value | Meaning | Example |
|---|---|---|
| `publisher_asserted` | The publisher states the relationship | O*NET task belongs to occupation; IPEDS institution is in county 17019 |
| `derived_rule` | This build derives it with a deterministic, documented rule | AEI task text equals the lower-cased O*NET task text; county is in CBSA because IPEDS lists them together |
| `curated_rule` | A hand-written mapping in `build_graph.py`, reviewable in code | IPEDS non-instructional occupation group 06 covers SOC major group 13-0000 |
| `unreviewed` | A machine suggestion that no person has checked | SUCSS class to O*NET candidate (`title_lexical_baseline_v1`) |
| `reviewed` | Reserved, not used in the public build. A person adjudicated the link on an approved machine; recorded as a new edge version with reviewer and date | Future reviewed SUCSS class to O*NET mapping |

## 2. Node types (populated)

| Node type | ID pattern | Source table | Notes |
|---|---|---|---|
| `Occupation` | `onet:15-1211.00` | `onet_occupation` | O*NET-SOC 2019 occupation. Props: description, job zone, a sample of alternate titles, alternate-title count |
| `SOC2018` | `soc:15-1211` (detailed), `soc:15-0000` (major group) | `onet_soc_crosswalk` | `props.level` is `detailed` or `major`. Major-group titles are the published SOC 2018 major groups |
| `SUCSSClass` | `sucss:<source_record_id>` | `sucss_class` | Keyed by record, not class code, because class 1164 has two records. Props: class code, occupational line |
| `Task` | `task:<task_id>` | `onet_task_statement` | O*NET task IDs are unique across occupations (18,838 of 18,838) |
| `DWA` | `dwa:4.A.1.a.1.a.1` | silver `onet_gwas_to_iwas_to_dwas` | Detailed work activity |
| `IWA` | `iwa:4.A.1.a.1.a` | silver `onet_gwas_to_iwas` | Intermediate work activity |
| `GWA` | `gwa:4.A.1.a.1` | `onet_element_rating` (work_activities) | Generalized work activity. O*NET rates the **Work Activities** domain at the GWA level, so the `WorkActivity` element and the `GWA` are one node, not two |
| `Skill` | `element:2.A.1.a` | `onet_element_rating` | O*NET 31.0 splits skills into `essential_skills` (10) and `transferable_skills` (25); `props.domain` keeps the split |
| `Knowledge` | `element:2.C.1.a` | `onet_element_rating` | 33 elements |
| `Ability` | `element:1.A.1.a.1` | `onet_element_rating` | 52 elements |
| `Technology` | `tech:<slug of example>` | `onet_technology_skill` | One node per named technology example (for example "Microsoft Excel"). Props: UNSPSC commodity code and title |
| `JobZone` | `jobzone:3` | silver `onet_job_zone_reference` | O*NET 31.0 publishes zones 2 to 5; zone 2 is labelled "Job Zone 1-2" |
| `Institution` | `ipeds:145637` | `ipeds_institution` | Props: sector, Carnegie class, system, land-grant flag, coordinates |
| `Geography` | `fips:17` (state), `fips:17019` (county), `cbsa:16580`, `geo:US000` (nation) | `ipeds_institution`, `qcew_*` | `props.level` is `nation`, `state`, `county` or `cbsa`. QCEW MSA area `C1658` maps to `cbsa:16580` (QCEW drops the CBSA code's last digit) |
| `Industry` | `naics:611310`, `naics:6113`, `naics:10` | `qcew_*`, `qwi_higher_ed` | `naics:10` is QCEW's "Total, all industries" aggregate code, not a NAICS code; `props.is_naics` says so |
| `IPEDSOccupationGroup` | `ipedsocc:06` | `ipeds_salary_noninstructional` | The 13 non-instructional salary occupation groups. Added because it is the only public bridge from a SOC major group to institution-level pay |
| `LaborMarketFact` | `lmf:qcew:<area>:<own>:<industry>:<year>`, `lmf:qwi:17:6113:<yyyy>q<q>`, `lmf:ipeds_sal_nis:<unitid>:<group>`, `lmf:ipeds_staff:<unitid>` | `qcew_industry`, `qcew_area`, `qwi_higher_ed`, `ipeds_salary_noninstructional`, `ipeds_staff_by_occupation` | Aggregated public measures reified as nodes so they can carry their own provenance and attach to several dimensions (area, industry, institution, occupation group). See 2.1 |
| `AIUsageEvidence` | `aei:task:<release>:<md5-12>`, `aei:occ:<soc>` | `aei_task_usage`, `aei_occupation_exposure` | Observed Claude usage. Evidence, never a prediction (contract rule 10). Metrics are kept side by side and never combined into one score |

### 2.1 Labor-market fact rules

- **QCEW annual facts** are computed from quarterly contract rows for 2019 to 2025: average employment is the mean of the twelve monthly levels; average weekly wage is total wages ÷ average employment ÷ 52. If any quarter in the year is suppressed (`disclosure_code = 'N'`) or missing, the measures stay NULL and `props.suppressed` or `props.quarters < 4` says why (contract rule 6). County rows for NAICS 611310 come only from `qcew_industry`. From `qcew_area` the build takes only the all-industry totals (`industry_code = '10'`), which avoids the overlap in contract rule 7.
- **QWI facts** are statewide Illinois, NAICS 6113, all ownerships, totals (`sex = '0' AND agegrp = 'A00'`), one node per quarter. The status flags (`s_*`) are kept in props, and the last two published quarters are marked `provisional` (contract rule 8).
- **IPEDS salary facts** are written only where `staff_count > 0`. Average salary is outlays ÷ count (contract rule 5).
- **IPEDS staff facts** hold the published grand totals (`staffcat_code` 1100, 2100 and 3100 with `sex = 'Total' AND race_ethnicity = 'Total'`), so nothing is summed across categories.

### 2.2 Not modelled yet

O*NET work styles, interests, work context, education and training categories, emerging tasks, alternate titles as separate nodes, Indeed postings, IPEDS instructional staff and new hires, and BLS OEWS and projections (not yet in the lake). Each would add nodes and edges without changing the two table shapes.

## 3. Edge types

Direction is `src → dst`. All edges carry the provenance columns in 1.

| Edge type | From → To | Weight | Method / review status | Key props |
|---|---|---|---|---|
| `MAPS_TO_SOC` | Occupation → SOC2018 (detailed) | — | `onet_soc_crosswalk` / publisher_asserted | |
| `BROADER` | SOC2018 detailed → SOC2018 major; county → state (`IN_STATE` below); `naics:611310 → naics:6113` | — | `soc_code_prefix` or `naics_code_prefix` / derived_rule | |
| `IN_JOB_ZONE` | Occupation → JobZone | — | publisher_asserted | |
| `PERFORMS_TASK` | Occupation → Task | Task importance (IM, 1 to 5) | publisher_asserted | `task_type` (Core/Supplemental), `relevance` (RT) |
| `ALIGNS_TO_DWA` | Task → DWA | — | publisher_asserted | |
| `PART_OF` | DWA → IWA; IWA → GWA | — | publisher_asserted | |
| `HAS_ELEMENT_RATING` | Occupation → Skill / Knowledge / Ability / GWA | Importance (IM, 1 to 5) | `onet_published_rating:<domain_source>` (Incumbent, Analyst, AI/Expert, Machine Learning…) / publisher_asserted | `level` (LV), `level_suppress_flag`, `n`, `domain` |
| `USES_TECHNOLOGY` | Occupation → Technology | — | publisher_asserted | `hot_technology`, `in_demand` |
| `RELATED_TO` | Occupation → Occupation | — | `onet_related_occupations` / publisher_asserted | `tier` (Primary-Short, Primary-Long, Supplemental), `index` |
| `CANDIDATE_MATCH` | SUCSSClass → Occupation | Lexical score | `title_lexical_baseline_v1` / **unreviewed**, confidence NULL | `rank`, `title_similarity`, `warning` |
| `HAS_AI_USAGE_EVIDENCE` | Task → AIUsageEvidence; SOC2018 → AIUsageEvidence | — | Task: `exact_lowercase_task_text_match` / derived_rule. SOC: publisher_asserted | Task: `text_shared_by_tasks` (AEI publishes by task text; when several O*NET tasks share one text, the evidence cannot be split between them) |
| `LOCATED_IN` | Institution → Geography (county) | — | publisher_asserted | |
| `IN_CBSA` | Institution → Geography (CBSA); county → CBSA | — | Institution: publisher_asserted. County: `ipeds_hd_county_cbsa_cooccurrence` / derived_rule, only where the county maps to exactly one CBSA | |
| `IN_STATE` | Geography (county) → Geography (state) | — | `fips_prefix` / derived_rule | |
| `HAS_FACT` | Institution → LaborMarketFact | — | publisher_asserted | |
| `ABOUT_GEOGRAPHY` | LaborMarketFact → Geography | — | publisher_asserted | |
| `ABOUT_INDUSTRY` | LaborMarketFact → Industry | — | publisher_asserted | |
| `ABOUT_OCCUPATION_GROUP` | LaborMarketFact → IPEDSOccupationGroup | — | publisher_asserted | |
| `COVERS_SOC_GROUP` | IPEDSOccupationGroup → SOC2018 (major) | — | `ipeds_occupation_category_definition` / curated_rule | `coverage` (`full` or `partial`, with the SOC ranges in `scope`) |

## 4. Internal node types (placeholders, not populated)

These types are reserved so internal data can attach to the public graph on approved machines without changing the shapes in 1. Nothing in this repository creates them, and `tests/test_graph.py` checks that none exist in the public build.

| Node type | ID pattern (internal only) | Grain | Would come from |
|---|---|---|---|
| `Person` | `person:<EDW_PERS_ID hash>` | Person | `T_PERS_HIST` |
| `Appointment` | `appt:<EDW_PERS_ID hash>:<posn_nbr>:<suffix>:<eff_seq>` | Person × position × job suffix × effective row | `T_JOB_DETL_HIST` |
| `Position` | `posn:<POSN_NBR>` | Funded position, filled or vacant | `T_JOB_DETL_HIST`, position control |
| `Department` | `dept:<org code>` | Organizational unit | EDW org hierarchy |
| `LearningActivity` | `learn:<course id>` | Course, certificate or training | LMS export |
| `Requisition` | `req:<id>` | Approved hiring request | Applicant tracking system |
| `Posting` | `post:<id>` | Public job ad tied to a requisition | Applicant tracking system |

### 4.1 How the EDW tables would attach

The repository's root README lists the EDW history tables and their join keys: `T_PERS_HIST.EDW_PERS_ID = T_EMPEE_HIST.EDW_PERS_ID = T_JOB_DETL_HIST.EDW_PERS_ID`, and `T_JOB_DETL_HIST.POSN_NBR` to payroll accounting. The graph would use them like this:

| EDW table | Becomes | Edges (all effective-dated) |
|---|---|---|
| `T_PERS_HIST` | `Person` node. Biographical and demographic attributes stay in a restricted side table, never in `props`, so the graph can be shared at the appointment level without exposing protected attributes | — |
| `T_EMPEE_HIST` | Employment spells on `Person` (hire, FTE, employee class, status) | `Person -EMPLOYED_BY-> Institution` (`ipeds:145637` and so on) with `valid_from = EFF_DT`, `valid_to = EXP_DT` |
| `T_JOB_DETL_HIST` | `Appointment` node per effective row | `Person -HOLDS-> Appointment`, `Appointment -FILLS-> Position`, `Appointment -IN_DEPARTMENT-> Department`, `Appointment -CLASSIFIED_AS-> SUCSSClass` (the class code on the job record, `review_status = publisher_asserted`) |
| Position control | `Position` node | `Position -CLASSIFIED_AS-> SUCSSClass`, `Position -IN_DEPARTMENT-> Department` |

Once `CLASSIFIED_AS` exists, every public path in this graph opens up to internal roles: appointment → SUCSS class → (reviewed) O*NET occupation → tasks, skills, technology, AI-usage evidence and labor-market facts.

### 4.2 Effective dating rules for internal edges

1. `valid_from` = the row's `*_EFF_DT`. `valid_to` = `*_EXP_DT`, with the EDW open-ended sentinel (`9999-12-31` or NULL, whichever the table uses) normalized to NULL. The interval is half-open: `[valid_from, valid_to)`.
2. Same-day actions keep the EDW effective-sequence column in the edge qualifier, so each action gets its own `edge_id`.
3. Retroactive corrections are new edge versions with a `props.known_from` load timestamp (transaction time). An as-of query filters on both: `valid_from <= :valid_date AND (valid_to IS NULL OR valid_to > :valid_date) AND known_from <= :known_date`.
4. Interval tests per key: no overlaps, no gaps inside a spell, exactly one open row per active appointment.
5. Person, appointment and position are separate grains. A count of `Person` nodes is headcount; a count of open `HOLDS` edges is appointments; a count of `Position` nodes includes vacancies. No metric sums FTE across a person-grain join.

### 4.3 Where internal data may live

Only on approved university machines, in `data/local/` or the EDW itself, using local or on-prem inference for any text. The public `nodes.parquet` and `edges.parquet` in this repository never receive internal rows. Shared outputs are aggregates with minimum cell sizes.
