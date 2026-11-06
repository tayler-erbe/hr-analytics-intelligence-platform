# Integration layer: synthetic EDW-shaped samples + public external data

This folder joins the synthetic sample pack (`sample_datasets/v1`) to every public source in the lake and in the
sibling workstreams, producing one queryable DuckDB database per sample set. **Internal records are synthetic and
not calibrated to EDW. Every SUCSS class → O\*NET link is unreviewed. The campus assignment is synthetic.** The
output proves the plumbing, grains and provenance rules; it is not evidence about University staff.

```bash
cd platform-evaluation
python integration/build_integrated.py --set longitudinal     # ~5 s; also --set CLEAN | DEFECTS | all
python integration/build_integrated.py --set CLEAN
python integration/coverage_report.py                         # integration/coverage/coverage_<set>.{md,json}
python integration/render_explorer.py                         # output/integration/integration_explorer.html
node integration/screenshot.js                                # output/integration/screenshots/*.png (Playwright)
python -m unittest discover -s integration/tests -t . -v      # ~25 s
```

Needs Python 3.13, duckdb, pyarrow, pyyaml; the built lake (`data/lake/contract`, `data/lake/silver`, and
`data/lake/_extract/bls` for the OEWS year fix below); `sucss_mapping/outputs`, `job_evolution/artifacts`,
`class_evolution/outputs` and (optionally) `peer_benchmarks/artifacts`.

Outputs (all gitignored under `data/lake/`): `data/lake/integrated/integrated_<set>.duckdb`, and
`data/lake/integrated/<set>/<table>.parquet` plus `manifest.json` (row counts, content hashes, mapping validation,
no timestamps).

## Network design

```text
 internal (canonical views from edw_mapping.yaml)                     public (bridges.yaml)
 ─────────────────────────────────────────────────                    ──────────────────────────────────────────────
 appointment/position ── job_class ──[exact code]──► SUCSS record ──[rank-1 duty match, UNREVIEWED]──► O*NET-SOC
                                  │                       │                                              │
                                  │                       ├─► job_evolution watch score (unreviewed)    ├─► job zone, tasks, tech
                                  └─[code]──► class_evolution timeline / stale spec / revision risk      └─[crosswalk]─► SOC 2018
                                                                                                              ├─► OEWS 2025 US/IL/MSA/611300
                                                                                                              ├─► Projections 2025-35, OEWS 2015-25 trend
                                                                                                              └─► AEI observed exposure
 org ──[tree walk]──► campus ──[SYNTHETIC assignment]──► IPEDS unitid ──► county FIPS / CBSA ──► QCEW county, OEWS MSA
                                                                     └──► IPEDS Big Ten peer metrics;  Illinois ──► QWI 6113
 calendar date ──► year / quarter ──► QCEW, QWI quarters; JOLTS annual (M13)
```

Every link is a row in `bridges.yaml` with `method`, `source` (source_id, path, vintage) and `review_status`
(`publisher_asserted`, `derived_rule`, `unreviewed`, `synthetic_assignment`). The database also stores them in
`meta_bridges`. A chain is as weak as its weakest link: every fact downstream of the SUCSS → O\*NET link carries
`chain_review_status = unreviewed`, and position-level market pay carries `unreviewed;synthetic_assignment`.

### Tables in `integrated_<set>.duckdb`

| Table | Grain | Notes |
|---|---|---|
| `canon_<concept>` | as the source | Canonical concepts after mapping (restricted fields such as birth date are never exposed) |
| `dim_org_external` | org unit | campus, unitid, county, CBSA, OEWS local MSA key, QCEW/QWI context keys |
| `dim_job_class_external` | job class | SUCSS record; O\*NET match + band + abstain; SOC; OEWS 2025 median/p10/p90/employment for US, IL, the three MSAs, NAICS 611300 (all and state-government); projections; OEWS trend; AEI; job zone/tasks/tech; job-evolution watch; class history, spec age, stale flag, revision risk. Each source group has `<group>_source_id/_vintage/_review_status` and a `<group>_null_reason` |
| `fact_class_external_long` | class × measure | Same facts in long form with provenance and a null reason on every row |
| `br_class_sucss`, `br_sucss_onet`, `br_sucss_onet_topk`, `br_soc_oews`, `br_soc_projections` | bridge rows | Top-k carries `display_weight` (share of evidence_index; **not a probability, never used to allocate headcount**) |
| `fact_position_snapshot` | position × as-of date × known-as-of date | incumbents, appointments, FTE, vacancy, salary vs class range (range position, compa ratio), market pay ratio vs OEWS local MSA and IL medians, with provenance and `market_null_reason` |
| `fact_headcount_asof` | as-of × campus × role family × class | distinct people by primary assignment (highest FTE), so totals equal the sample's own distinct count |
| `fact_appointment_events`, `fact_separation_events` | event | as known today |
| `fact_flows_year` | year × campus × role family | external hires, rehires, internal hires (moves), transfers (cross-org, cross-campus), class transitions, separations by reason, retirements, SURS indicator, separation rate |
| `dim_calendar_quarter` | quarter | date → year/quarter keys for QCEW/QWI, M13 for JOLTS |
| `bench_separation_role_family` | role family | internal rate vs BLS projected occupational separation and exit rates (headcount-weighted), QWI Illinois higher-ed and JOLTS context |
| `bench_pay_role_family_campus` | role family × campus | internal median vs OEWS local / IL medians |
| `bench_ai_pressure_role_family` | role family | headcount, vacancy, AEI exposure, watch score, revision risk, stale-spec share, BLS growth |
| `bench_campus_peers` | campus | synthetic shares and hire rates vs IPEDS unit and Big Ten peer medians, QCEW county context |
| `ext_*` | per source | cleaned public inputs; every row has source_id, vintage, review_status |

### Rules enforced

- **Time.** Effective intervals are inclusive (`valid_from <= d AND valid_to >= d`); recorded versions are half-open
  (`known_from <= k AND known_to > k`); `9999-12-31` is the open end. Snapshots default to *as recorded on the
  as-of date* (`--known as_of`); `--known latest` restates history with today's knowledge. Flows use today's knowledge.
- **Grain.** Person, appointment, position and class stay separate. Each class resolves to one SUCSS record and one
  O\*NET code, so no bridge multiplies headcount (tested against the sample's own as-of counts).
- **Suppression.** BLS `*`, `**`, `#`, `~` become NULL with a `*_flag`; QCEW `disclosure_code = 'N'` quarters make the
  year NULL; QWI's provisional quarters stay NULL. Nothing is coalesced to zero.
- **Abstention.** An abstained O\*NET match gives NULL SOC/OEWS/projection/AEI/job-evolution facts with
  `external_null_reason = 'onet_match_abstained: <reason>'`. Class-evolution facts (which do not depend on O\*NET) remain.
- **Separate worlds.** Each set is built into its own database; nothing joins people across sets.

## Switching to cookbook-verified or real EDW names (edit `edw_mapping.yaml` only)

`edw_mapping.yaml` is the single switch point. It maps the concepts proposed in
`CODEX_HANDOFF_EDW_PROFILING.md` (person, employment, appointment, position, separation, payroll line, job class, org,
role family, employee class) to `table.column`, with a type, optional `transform` (`percent_to_fraction`, `trim`,
`yyyymmdd_to_date`), date `convention` (`inclusive`/`exclusive`) and `open_end`, and a `provenance` flag on every entry
(`assumed_synthetic_layout` today; `verified_dictionary` once confirmed). Code domains the layer interprets (active
status codes, separation reason groups, SURS indicator, public class source) are in `code_values`.

1. Copy the file, edit table/column names, conventions and code values, and mark each verified entry
   `provenance: verified_dictionary`. Optional concepts/fields (`optional: true`) may be absent.
2. Run with `HR_DATA_SOURCE=edw HR_EDW_MAPPING=<that file> HR_EDW_DATA=<duckdb file or parquet/jsonl folder>`
   (`HR_DATA_SOURCE=sample` is the default; `synthetic` is accepted as an alias). `HR_SAMPLE_PACK_PATH` moves the
   sample pack; `HR_LAKE_PATH` moves the lake.
3. `mapping.resolve()` validates every concept against the physical schema and refuses to build if a required column
   is missing. No other file names a physical table or column; `test_swapping_mapping_files_gives_identical_outputs`
   renames every table and column, stores FTE as a percent and switches to exclusive end dates, changes only the
   mapping, and gets byte-identical tables.

Keep the real-name mapping wherever the steward-approved metadata rule in the handoff says it may live.

### Data Cookbook mapping (v3)

`edw_mapping_cookbook.yaml` maps the same concepts to the six tables transcribed from the Data Cookbook
(`edw_cookbook_reference/`: T_JOB_DETL_HIST, T_EMPEE_HIST, T_EMPEE_HIST_5, T_POSN_HIST, T_PERS_HIST, T_PAYR_ACCTG_DETL;
`provenance: verified_dictionary`). It runs on `sample_datasets/v3_cookbook` (see its README for the proof against v2).
Loader features it uses:

- `recorded_time.mode: lineage_next`. There is no recorded-end column, so known_to is the next
  `JOB_DETL_HIST_EFF_DT` in the primary-key lineage, and deleted (`D`) rows end at their post date.
- `recorded_time.mode: post_date`. For tables updated in place.
- Field `derive`. Used for the SUCSS bridge: `T_POSN_HIST.PAPE_CIV_SVC_ID` first, the synthetic P-Class crosswalk
  as fallback.
- Role `restricted_fairness_only`. These demographics are never exposed in canonical views.

The Cookbook's T_POSN_HIST has no org column, so `build_integrated.py` derives a position's org from its jobs.
`bench_funding_mix_role_family_campus` is built when payroll carries a funding source.

## Confidence of each bridge

| Bridge | Status | Confidence |
|---|---|---|
| job class → SUCSS record | derived_rule | High for code identity (sample codes are real SUCSS codes). 1164 has two catalog records; the record whose normalized title matches is chosen, else the lowest record id, flagged. LOCAL AP/FA/GA/OV classes have no SUCSS record by design. |
| SUCSS → O\*NET | **unreviewed** | Directional: provisional 60-class gold sample, top-1 acceptable 65% (CI 52–76%). `evidence_index` is ordinal. Title-lexical fallback is off (`allow_title_lexical_fallback: false`); turning it on flags every use. |
| O\*NET → SOC 2018 | publisher_asserted | Exact crosswalk. |
| SOC → OEWS / Projections / trend | publisher_asserted | Exact code; broad-code roll-up flagged `broad_rollup`. National history before 2019 uses SOC 2010 codes. |
| SOC → AEI | publisher_asserted | Observed usage evidence, not a displacement forecast. |
| SUCSS → job_evolution | unreviewed | Rides the same rank-1 link; a rank, not a probability. |
| class code → class_evolution | derived_rule | Machine-parsed notices; counts are lower bounds; revision risk is a descriptive index. |
| org → campus → unitid | **synthetic_assignment** | None as a fact: Campus 1/2/3 → UIUC/UIC/UIS and U00 → System Offices only to attach context. |
| unitid → county/CBSA → QCEW, QWI, peers | publisher_asserted | IPEDS directory. QWI is statewide, public + private. Peer panel is a proposal. |
| calendar → period | derived_rule | Exact. |

## Results on this build (latest snapshot 2026-06-30)

| | longitudinal | CLEAN |
|---|---:|---:|
| Distinct people / active-or-filled positions | 813 / 859 | 1,035 / 1,129 |
| Classes in use (no SUCSS record: local) | 38 (4) | 57 (17) |
| Headcount reaching a SUCSS record / class history | 83.0% | 46.4% |
| Headcount reaching O\*NET, SOC, OEWS US/IL/MSA/611300, projections | 78.0% | 44.0% |
| Headcount reaching AEI exposure | 70.1% | 41.4% |
| Headcount reaching job zone and job-evolution watch | 78.0% | 42.7% |
| Abstained classes in use (headcount) | 2 (41) | 2 (25) |
| Filled positions with a local-MSA market pay ratio / IL ratio | 73.4% / 78.0% | 38.3% / 42.8% |

CLEAN's low reach is structural: 54% of its people hold synthetic LOCAL academic-professional, faculty and
graduate-assistant classes with no SUCSS record (and no defensible O\*NET bridge). On longitudinal the layer
reproduces the generator's planted totals exactly for internal moves (1,467) and separations (1,480); its 2,302
"external hires" are first observed appointments and include the generator's initial stock (planted: 1,928 hires
during the simulation). Full numbers: `coverage/coverage_<set>.md`.

## Honest limits

- **Synthetic internal data.** Pay ranges, behaviour, org tree and codes are invented and not calibrated to EDW.
  Internal-vs-market and internal-vs-BLS comparisons test the pipeline, not the University.
- **Unreviewed SUCSS mappings.** Everything SOC-level depends on a rank-1 machine suggestion no HR analyst has checked.
- **Synthetic campus assignment.** The campus → unitid link is labelled `synthetic_assignment` everywhere it is used.
- **OEWS is not class pay.** OEWS SOC-level wages describe an occupation across employers; a civil-service class's
  range and duties can differ sharply. Small MSAs leave many occupations unpublished (local ratio coverage < IL).
- **Different separation concepts.** BLS projected separations are *occupational* (exits + transfers out of the
  occupation); QWI counts every job ending in Illinois NAICS 6113 (public + private, including short jobs, ~42%/yr);
  JOLTS is a national state-and-local-education rate. Shown as context, not as a target.
- **Lake defect found and worked around.** `silver/bls_oews_all.survey_year` and
  `silver/bls_oews_national_history.survey_year` hold the literal text `survey_year` on every row
  (`lake_build.xlsx_to_csv` writes each data row through its header branch when `header_match` is None). The layer
  recovers the year from the sorted per-year extract CSVs in `data/lake/_extract/bls/`, verifying row totals and each
  file's first row; if those files are absent it leaves the year NULL (`method: unrecoverable`) rather than guess.
  The fix belongs in `scripts/lake_build.py` (not modified here).
- **Event rules are approximations.** An appointment starting the day after another ends is an internal move; an
  overlapping one is an additional appointment; a first observed appointment is an external hire (left-censored).
  CLEAN has no recorded-version columns, so recorded-as-of logic is a no-op there; DEFECTS builds but its planted
  defects flow through (it is for detection tests, not benchmarks).
- **Role families.** Longitudinal uses the sample's `REF_ROLE_FAMILY`; CLEAN has none, so it falls back to
  class_evolution's title-keyword family for SUCSS codes and the employee-class description for local classes
  (`role_family_source` says which).
