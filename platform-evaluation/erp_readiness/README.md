# HR data conversion-readiness toolkit (ERP Business Transformation)

A vendor-neutral toolkit a data engineer can run against EDW HR history to measure how ready HR data is to convert off Ellucian Banner HR/Payroll into a cloud ERP. **Everything in this repository runs on synthetic data.** No real person, ID, salary or org code is used or shown.

- Rule catalog: 43 checks in `rules/catalog.yaml`.
- Synthetic EDW-shaped history generator with injected defects.
- Issue register with readiness scores by domain.
- Mock-conversion reconciliation harness.
- Offline dashboard: [`../output/erp_readiness/readiness_dashboard.html`](../output/erp_readiness/readiness_dashboard.html).

## Context

In April 2026 the University of Illinois System announced an **ERP Business Transformation** to move HR/payroll and finance off Banner, which has been in production since December 2003. HR transactions are keyed through the custom **HR Front End (HRFE)**, and AITS publishes reporting through the **EDW**. The candidate platforms are Ellucian Cloud, Workday and Oracle Fusion Cloud HCM. As of the latest sources found, **no vendor had been selected**, and a consultant-led readiness phase was under way. See [`../research/UIUC_HR_AND_AI_TOOL_LANDSCAPE.md`](../research/UIUC_HR_AND_AI_TOOL_LANDSCAPE.md) §2 and [`../research/HR_USE_CASES_AND_GUARDRAILS.md`](../research/HR_USE_CASES_AND_GUARDRAILS.md) §2. Those are search-snippet-level sources; confirm them at <https://www.uillinois.edu/erp>.

## Run it

From `platform-evaluation/` (Python 3.13, `duckdb` 2.0, `pyarrow`, `pyyaml`; `sqlglot` is optional and only used to transpile and parse-check the compiled dialect SQL):

```bash
python erp_readiness/run_all.py                          # ~20 s: CLEAN + M1..M4, checks, reconciliation, compile, dashboard
python -m unittest discover -s erp_readiness/tests -v   # 20 tests, ~30 s
```

Individual steps:

```bash
python erp_readiness/generate_synthetic.py --label M1 --defect-scale 1.0 [--seed N] [--n-persons N]
python erp_readiness/run_checks.py --label M1          # runs/M1/{issue_register.csv, issues_detail.csv, summary.json}
python erp_readiness/reconcile.py --label M1           # runs/M1/{reconciliation.json, reconciliation_exceptions.csv}
python erp_readiness/compile_rules.py                  # rules/compiled/{duckdb,snowflake,databricks,oracle}.sql
python erp_readiness/build_dashboard.py                # ../output/erp_readiness/readiness_dashboard.html
```

`data/` and `runs/` are regenerable and git-ignored. Seed 20261106 reproduces every number below byte-for-byte.

## What is in the folder

| Path | What it is |
|---|---|
| `generate_synthetic.py` | Seeded generator for EDW-shaped tables: `T_PERS_HIST`, `T_EMPEE_HIST`, `T_EMPEE_HIST_5`, `T_JOB_DETL_HIST`, `T_PAYR_ACCTG_DETL`, an assumed position-control table `T_POSN_HIST`, and reference tables. It builds a consistent world first, then applies 44 defect injections. Each injection writes the exact entity IDs it should trip, including documented collateral, to `manifest.json` |
| `rules/catalog.yaml` | 43 declarative rules. Each has an ID, domain, severity, proposed owner, rationale, Workday and Oracle target concept, remediation, cited sources and portable SQL. The file also defines populations (rule denominators), helper views and the severity weights and tolerances used for scoring |
| `rules/source_map.yaml` | The only file you edit on an approved machine. It binds the logical views the rules use (`stg_person`, `stg_job`, `ref_org` ...) to physical EDW tables and columns, and records the Banner source table for each (SPRIDEN/SPBPERS, PEBEMPL, NBRBJOB/NBRJOBS, NBBPOSN/NBRPTOT, PTRECLS, PHRHIST/PERJTOT, FTVORGN) |
| `rules/compiled/*.sql` | Generated scripts per dialect: staging views, helpers and all 43 rules |
| `run_checks.py` | Runs the catalog and writes the issue register (counts, failure rate, examples as synthetic IDs), domain readiness scores and gates, and the trend across mock cycles |
| `reconcile.py`, `reconciliation/` | Mock converter plus pre/post reconciliation. Tolerance rules are in `tolerances.yaml` and the design in [`reconciliation/RECONCILIATION.md`](reconciliation/RECONCILIATION.md) |
| `build_dashboard.py` | Builds a single offline HTML file: vanilla JS and inline SVG, light and dark themes, works at phone width, no network requests |
| `tests/test_erp_readiness.py` | Catalog contract, portability lint, exact defect detection, clean-seed zero findings, determinism, reconciliation, dashboard |

## The rule catalog

Seven domains: person (5), employment (8), job history (8), position (7), classification and compensation (4), org and supervisory (6), payroll (5). Severities: 13 critical, 20 high, 10 medium.

Each brief defect family maps to a rule as follows:

| Defect family | Rule(s) |
|---|---|
| Overlapping effective-date intervals | J01 job, E01 employee, P03 person, S03 position |
| Gaps | J02 job, E02 employee |
| Inverted intervals | J03 |
| Orphan positions | S01 |
| Jobs without positions | S04 (Y03 for their pay) |
| Multiple primary jobs | J04 (J05 for the mirror case) |
| FTE > 1 | J06 per job, J07 per person, S02 position over-filled |
| Terminated persons with active jobs | E03 (E04, E06 related) |
| Class codes not in the SUCSS catalog | C01, against the public SUCSS catalog already in `../data/prepared/classes.jsonl` |
| Pay below class range | C02 (C03 above range, C04 class missing) |
| Duplicate persons | P01 exact national-ID hash, P02 probable (name + birth date) |
| Future-dated rows | E08, J08 (beyond a 180-day pending-action horizon; legitimate near-term pending rows are generated and must *not* fire) |
| Inconsistent org codes | S06 job vs position org, O05 broken parent, O06 unknown or inactive org |
| Missing supervisors and cycles in reporting lines | O01, O02 inactive supervisor, O03 cycle (recursive CTE), O04 self |
| Payroll history | Y01 pay with no job, Y02 pay after termination, Y05 duplicates, Y04 negative net |

The target concepts are mapping hypotheses, not vendor documentation. Workday examples are supervisory organization, position vs job management, job profile and additional job. Oracle examples are the primary assignment flag, position, job and work relationship. Oracle table names such as `PER_ALL_ASSIGNMENTS_M` should be verified against the release in use. Ellucian Cloud keeps the Banner data model, so most rules apply unchanged there.

**Scoring.** For each rule:

- rule score = 1 if no entity fails;
- otherwise rule score = max(0, 1 − failure rate ÷ tolerance), where tolerance is 0 for critical, 0.1 % for high, 0.5 % for medium and 2 % for low.

Domain score = the severity-weighted mean of its rule scores (weights 5/3/2/1). Domain gate:

- **blocked** if any critical rule fails;
- **at risk** if any high rule fails;
- **watch** if any other rule fails;
- **ready** otherwise.

The score is a triage signal for stewards, not a quality certificate. The weights and tolerances are placeholders until data owners agree real values.

## Results on synthetic data (seed 20261106, 1,500 synthetic persons)

| Extract | Overall | Failing rules | Failing entities (crit/high/med) | Reconciliation |
|---|---|---|---|---|
| CLEAN | 100.0 | 0 / 43 | 0 | match |
| M1 (all defects) | 9.2 | 43 / 43 | 63 / 168 / 45 | **unexplained** (planted crosswalk bug, U111 → UNMAPPED) |
| M2 (55 %) | 12.7 | 43 / 43 | 33 / 99 / 26 | explained |
| M3 (25 %) | 20.8 | 42 / 43 | 18 / 50 / 13 | explained |
| M4 (8 %) | 96.8 | 3 / 43 | 1 / 1 / 1 | match (but the job-history domain is still *blocked*) |

The defect rates and remediation between cycles are **simulated**. They say nothing about the real condition of Illinois HR data.

M4 shows why the score and the gate are reported separately. One remaining critical defect (an overlapping job-history interval, J01) leaves reconciliation clean, because the snapshot reconciliation does not look at history and the defect rejects nothing at load time. It would still double-count salary history once history is converted.

## How this de-risks the ERP program

1. **Gives the readiness phase a measured baseline.** The program is in a consultant-led readiness phase. The landscape research lists "no quantified data-quality baseline for HR" as a gap (`UIUC_HR_AND_AI_TOOL_LANDSCAPE.md` §7). This catalog quantifies that baseline, assigns each defect class an owner, and produces worklists (`issues_detail.csv`) that can go to units today, before any vendor is chosen.
2. **Acts on peer lessons.**
   - Penn found conversion problems were mostly stale data needing cleanup, so this toolkit starts the cleanup years ahead.
   - Ohio State had to clean up positions retroactively after switching staffing models. S01–S07 and the position-management decision should come *before* the first mock.
   - UChicago underestimated testing. The reconciliation harness and explicit tolerances make testing repeatable.
   - Richmond converted four times. The mock-cycle trend is built in.
   - UW's lessons learned warned against a big-bang cutover with no room to adapt. Running the rules every month lets the program watch the trend rather than discover problems at cutover.
   - UW–Madison's IAM team asked for published conversion logic. The catalog and crosswalks are that logic, in reviewable form.
3. **Splits "bad source data" from "bad conversion".** Rules find the first, reconciliation finds the second. Every explained variance carries a rule ID, which routes it to an owner. Unexplained variances go to the integrator. The planted M1 bug shows a defect that no source rule can see.
4. **Survives the vendor decision.** Rules describe Banner and EDW facts, and target concepts are annotations. Whichever platform wins, only the target-side query in reconciliation changes.

## How it ties to the rest of this repository

- **HR semantic layer** (`../custom_stack/semantic/`). Reconciliation metrics use the same definitions the semantic specs and benchmark fix: headcount is distinct people, appointments and FTE are separate metrics, and headcount is not additive across departments (`benchmark_workforce.yaml`: `wf_headcount`, `wf_appointment_count`, `wf_fte`). On an approved machine the reconciliation's L-side metrics should be served from the governed semantic layer, so pre-conversion counts and the dashboards people already trust are one number. The `source_map.yaml` pattern (logical names over physical tables, compiled per dialect) mirrors the semantic compiler's one-spec-many-targets approach.
- **Workforce graph** (`../knowledge_graph/schema.md` §4). The internal node types reserved there (`Person`, `Appointment`, `Position`, `Department`) come from the same EDW tables. §4.2 rule 4 requires "no overlaps, no gaps inside a spell, exactly one open row per active appointment". J01–J03, E01–E02 and S03 implement exactly those checks, and O03 is the graph-cycle test on reporting edges. Passing the critical rules is a precondition for loading internal edges into the graph, and for loading workers into a cloud HCM.
- **Benchmark** (`../benchmark/`) is frozen and read-only. This toolkit does not read or modify it. It only reuses the benchmark's documented metric separation.

## Why it is platform-neutral

- Rules are an ANSI subset: CTEs, `LEAD`, `CASE`, `EXISTS`, `UNION`, `||`, `CAST(... AS VARCHAR(n))` and `DATE 'yyyy-mm-dd'` literals. A test lints out `LIMIT`, `QUALIFY`, `ILIKE`, `::`, `IS DISTINCT FROM`, `EXCEPT`/`MINUS`, `AS` table aliases (Oracle rejects them) and dialect date functions.
- Only two things vary by dialect. The one-day date addition in the staging views is `+ INTERVAL` in DuckDB, `DATEADD` in Snowflake, `date_add` in Databricks and `+ 1` in Oracle. The recursive-CTE keyword is the other: Oracle uses plain `WITH`. `compile_rules.py` emits a script per dialect. With `sqlglot` installed it also transpiles type spellings (for example `VARCHAR2`) and the tests parse every rule for Snowflake, Databricks and Oracle.
- **Honest limits:**
  - Only DuckDB actually executed the rules here. The Snowflake, Databricks and Oracle scripts are parse-checked, not run.
  - O03 needs recursive CTE support. Databricks SQL added it only recently, so verify it on the workspace or replace it with a fixed-depth self-join.
  - Oracle needs `NLS_DATE_FORMAT='YYYY-MM-DD'` so date-to-text entity IDs come out in ISO format.
  - Execution stays inside the warehouse. Only the issue register (synthetic IDs here, restricted IDs on real data) leaves it.

## What is needed on approved machines

1. **Access and approval.** Use a University-approved machine or the EDW/Denodo environment, with access requested through the Unit Security Contact. Data stewards in IHR Records, Classification and Compensation, Position Control, Payroll and AITS Decision Support must approve the purpose. Real IDs never leave that environment. Share aggregates with small-cell suppression, as in the benchmark access policy.
2. **Confirm the EDW data dictionary and edit `rules/source_map.yaml`.** The table names come from the repository README, but **every column name, the position-control table and the reference tables here are assumptions**. Confirm these points in particular:
   - **Interval convention.** The rules assume an inclusive `*_EXP_DT` with 9999-12-31 or NULL meaning open. `knowledge_graph/schema.md` §4.2 assumes half-open intervals, so one of the two documents is wrong for the real EDW. Resolve this first. Exclusive-end sources currently raise `NotImplementedError` in staging rather than being silently mis-checked.
   - **Same-day sequence.** If the EDW has a same-day effective-sequence column, add it to the `LEAD` ordering in the overlap and gap rules.
   - Where the supervisor lives (job record vs. an HRFE routing table).
   - How the EDW represents Banner contract type (P/S/O) and job suffix. U of I field standards define suffix rules: MM/LP e-class or a T suffix must be overload.
   - Which org hierarchy (FTVORGN level) units use.
3. **Load the real reference data.**
   - SUCSS class list with effective dates. It keeps changing, so track notices as a change feed.
   - Campus pay ranges. The ranges here are invented.
   - PTRECLS employee classes.
   - A steward-approved `REF_HIERARCHY_ROOT` list of top-of-house positions.
4. **Calibrate.** Expect false positives on real data, for example legitimate concurrent appointments over 1.0 FTE, approved red-circle salaries, and leave statuses. Add exception tables reviewed by owners rather than loosening rules. Agree severities, tolerances and owners with the stewards.
5. **Schedule.** Run monthly during readiness and at every mock conversion. Store each `summary.json` to build the real trend. Ask the integrator, in the statement of work, for a reject log with legacy keys and target extracts at the reconciliation grains.
6. **Not covered yet:**
   - benefits, leave balances, SURS tier
   - bargaining unit / union membership
   - labor distribution by fund or grant
   - YTD tax and deductions
   - address and work-state checks
   - JDX job-description to position linkage
   - bitemporal (as-known) comparisons
   - history-conversion horizon decisions

## Sources

Peer lessons and Banner, Workday and Oracle details. Most were read as search-result summaries, not full documents, so treat them as leads to confirm.

- Penn ISC, Workday conversion and stale data: <https://isc.upenn.edu/node/122>
- Richmond, Banner data converted to Workday four times: <https://workday.richmond.edu/about/history/index.html>; <https://is.richmond.edu/features/article/-/25767/workdayrichmond-technology-support.html>
- UW HR/Payroll Modernization lessons learned (big-bang risk): <https://ocio.wa.gov/sites/default/files/2022-12/UW_TSB%25202.11.16%2520FINAL%2520nn.pdf>
- UChicago HCM symposium deck (testing effort, pay accuracy): <https://uit.stanford.edu/sites/default/files/2022/09/02/Human%20Capital%20Management%20Symposium%20Full%20Slide%20Deck.pdf>
- Ohio State, position data quality for Workday: <https://hr.osu.edu/news/2017/02/20/hr-service-delivery-transitions-to-workday-enterprise-project/>; timeline: <https://busfin.osu.edu/news/2020/05/12/revised-enterprise-project-timeline>
- UW–Madison ATP data mapping and foundation tenant: <https://atp.wisconsin.edu/?p=4602>; launch moved to July 2025: <https://news.wisc.edu/workday-launch-revised-to-july-2025>
- U of I NBAJOBS field data standards (job type P/S/O, suffix rules): <https://www.hr.uillinois.edu/human_resource_systems/reporting_portal/data_assistance/hr_banner_forms_field_data_standards/nbajobs_form>
- USNH key Banner HR terms (one primary job; any number of secondary and overload jobs): <https://usnh.edu/banner/training/active/key_terms.htm>
- Banner ODS metadata (PEBEMPL, PTRECLS; NBBPOSN position definition): <https://bnrordsp.neu.edu/metadata_nfs/EMPLOYEE_ODS_target.html>; <https://odsmetadata.wm.edu/ODST/POSITION_DEFINITION_ODS_target.html>
- Assignments not properly terminated (NBRJOBS_STATUS vs PEBEMPL_EMPL_STATUS): <https://sequoias.atlassian.net/wiki/x/lQBzKQ>
- Workday supervisory organizations and position vs job management: <https://web.uri.edu/workday/supervisory-organizations/>; <https://louisville.edu/workday/resources/resources-pdfs/pdf-organizations-and-staffing>
- Oracle HCM worker assignment primary flag, position loading, assignment effective dates: <https://docs.oracle.com/en/cloud/saas/human-resources/24d/faiau/attributes-for-worker-assignment.html>; <https://docs.oracle.com/en/cloud/saas/human-resources/fahbo/guidelines-for-loading-positions.html>; <https://docs.oracle.com/en/cloud/saas/human-resources/fahbo/example-of-loading-assignment-changes.html>
- SUCSS public class catalog: <https://www.sucss.illinois.gov/pages/classspec/Default.aspx>

The search did not find a public field-level data dictionary for NBRBJOB/NBRJOBS. Field semantics here follow institutional ODS metadata and job aids and must be checked against the Ellucian documentation for the Banner release in use.
