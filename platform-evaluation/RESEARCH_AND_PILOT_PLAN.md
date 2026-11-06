# Higher Education Workforce Intelligence: research and trial plan

Research date: October 29, 2026. Scope: Illinois public higher education, with national higher education peers and selected employers competing for similar skills. Source access and product availability reflect this research date. Recommendations below are proposed research designs, not findings about current hiring.

## Recommended first demonstration

Build one role-level intelligence workflow on the same frozen data in three environments: a custom Python/SQL stack, Databricks, and Snowflake. Ask: **For a university job family, what is changing in recruitment, tasks, skills, pay competition, and institutional demand—and what evidence supports a staffing or training response?**

Start with accounting/payroll, HR, IT/data, admissions/student services, library work, grants administration, and facilities. These are proposed comparison families, not claims about growth or AI risk. Include clinical roles as a separate stratum where academic medical centers are in scope. Faculty recruitment should be modeled separately because appointment cycles, disciplines, and tenure structures differ.

Deliver a role explorer, a peer hiring monitor, a task transformation view, and a reproducible platform scorecard. Keep these distinct from employee attrition and succession predictions until internal longitudinal data and validated outcomes are available.

## Relationship to the original POC

The [original case study](https://taylererbe.com/hr-workforce-analytics.html) and [repository](https://github.com/tayler-erbe/hr-analytics-intelligence-platform) describe internal career transitions, succession readiness, and workforce forecasting. The repository root inspected through GitHub contains README.md only; the described notebooks and synthetic POC files were not present there. This pilot extends the external evidence layer and provides a new reference-data starter; it does not reproduce or validate those earlier models.

Preserve the original internal-data direction, but make three design changes: retain numeric BLS measures and release vintages rather than only growth labels; estimate vacancies and transitions from actual outcomes rather than title similarity; keep evidence about AI task applicability separate from claims about job loss. External sources alone cannot establish internal succession readiness.

## Data acquisition priorities

Each source needs a recorded retrieval time, reference period, publication/revision date, release version, geography, coverage, permitted use, and content hash. An accessible web page does not by itself establish bulk download or redistribution rights. Use public downloads where provided and exports or licensed feeds where needed. No outreach or access applications have been sent.

| Priority and source | What to acquire | Connection and higher education value | Access and material limitation |
|---|---|---|---|
| P0: [O*NET database](https://www.onetcenter.org/database.html) | Occupations, descriptions, tasks and ratings, work activities, skill measures, software skills, alternate titles, metadata | O*NET-SOC occupation code; task and content element IDs. Foundation for task-based role comparison | Public downloadable data. Freeze version 31.0 for this pilot; inspect release dictionaries rather than assume older skill file names |
| P0: [SUCSS classifications](https://www.sucss.illinois.gov/pages/classspec/Default.aspx) and [class index](https://www.sucss.illinois.gov/pages/report/classindex/indexofclass.aspx) | Catalog, individual specifications, characteristic duties, qualifications, series, status and effective dates | Class code plus source record/version; proposed bridge to occupations | Catalog acquired. Individual specifications still pending. Covers civil service classifications, not a census of employees, vacancies, faculty, or all academic professional roles |
| P0: [BLS occupational projections](https://www.bls.gov/emp/tables/occupational-projections-and-characteristics.htm) | Base/projected employment, percent change, annual openings, education/training fields | SOC or National Employment Matrix occupation codes plus vintage | Public tables/downloads. Direct script request returned HTTP 403 in this session; download pending. Ten-year structural context, not a three-month forecast |
| P0: [BLS OEWS](https://www.bls.gov/oes/tables.htm) | National, Illinois and metro occupation wages/employment; available higher education industry profiles | SOC, geography, industry, reference year | Public download tables. Preserve suppression and uncertainty. Do not assume state × detailed industry × occupation is available for every combination |
| P0: [IPEDS](https://nces.ed.gov/ipeds/use-the-data) | Directory/characteristics, HR, enrollment, finance, completions, libraries | UNITID and collection year; CIP for programs | Public complete files. Use released component-specific years and dictionaries. Annual aggregates and broad HR categories cannot substitute for detailed title histories |
| P1: [HigherEdJobs](https://www.higheredjobs.com/) | Posting ID, employer, title, category, location, dates, duties, requirements, salary and appointment attributes | Employer-to-UNITID bridge; reviewed posting-to-role bridge | Intended job board confirmed by user. Research interface returned an iframe rather than usable listings; no current inventory or full-text feed acquired. Establish export/feed and reuse terms before bulk collection |
| P1: [Institutional career sites](https://www.uillinois.edu/) | Official requisitions and statuses from selected institutions' actual career portals | Institution, requisition ID, first/last seen, canonical URL | Identify each campus portal before collection; public listings or approved exports. Preferred reference for deduplicating syndicated posts; no campus feeds collected yet |
| P1: [QCEW](https://www.bls.gov/cew/about-data/data-availability.htm) | Employment, establishments and wages by area, industry, ownership and quarter | NAICS + geography + ownership; higher education sector context | Public downloads/open data. Retain government ownership distinctions and suppression. Not an occupational or employer-level vacancy dataset |
| P1: [BLS industry–occupation matrix](https://www.bls.gov/emp/tables/industry-occupation-matrix-industry.htm) | Occupation mix and projections within relevant education industries | National Employment Matrix occupation and industry definitions | Public table; current page presents 2025–35. Industry codes include special groupings: explicitly inspect public/private education coverage rather than equate all matrix codes with ordinary NAICS |
| P1: [Indeed Hiring Lab tracker](https://github.com/hiring-lab/job_postings_tracker) | Published posting trend series and methodology | Source-defined geography/sector categories; macro comparator | Public aggregate repository. Verify available categories and refresh date; index movements are not raw vacancy counts or a complete employer inventory |
| P1: [NLx Research Hub](https://nlxresearchhub.org/data-access) | Approved historical/real-time posting extracts and job histories | Posting, employer, geography and licensed fields | Access-controlled. Current guidance distinguishes discrete nonprofit research from ongoing platform integration. Approval, fields, history and reuse rights must be established; not an assumed open feed |
| P2: [LinkedIn Economic Graph research](https://engineering.linkedin.com/data/economic-graph-research/economic-graph-details) | Published hiring/skills indicators; partner research if available | Source-defined occupation, employer and skill categories | Public research is useful context; historical program documentation does not establish current eligibility or a raw-postings API. Do not make the initial demo depend on access |
| P2: [CUPA-HR DataOnDemand](https://www.cupahr.org/research-data/dataondemand/) | Higher education role-specific pay, turnover, staffing and hiring benchmarks | Licensed job definitions, peer groups, survey year | Subscription-based. More relevant than all-industry comparisons for many campus roles, but confirm institutional access and rights to export/show results |

O*NET content is provided by USDOL/ETA under [CC BY 4.0, with stated exceptions and attribution requirements](https://www.onetcenter.org/license_db.html). The downloaded occupation file is preserved unmodified. Prepared files reformat source records; the title matching queue adds our own unreviewed suggestions. Those suggestions are not USDOL-approved mappings.

## Additional datasets worth testing

These sources broaden the project beyond counting job advertisements. The proposed uses are hypotheses to evaluate, not established leading indicators.

| Source | Why it may explain higher education staffing | Grain, acquisition and joining caveat |
|---|---|---|
| [NSF HERD public-use files](https://ncses.nsf.gov/explore-data/microdata/higher-education-research-development) | Research spending mix may explain demand for grants administration, labs, research IT and compliance | Annual institution-level CSV/SAS files. Validate institution identifiers and reporting boundaries before joining to UNITID; annual expenditures are lagging context |
| [NSF award API](https://resources.research.gov/common/webapi/awardapisearch-v1.htm) | Award start/end dates and research areas may provide earlier signals of future support needs | Award/institution records. Resolve recipient aliases; award amounts and dates do not equal staff budgets or actual hiring |
| [USAspending API](https://api.usaspending.gov/docs/endpoints) | Federal funding mix and changes can contextualize institutional staffing pressure | Award/transaction, recipient UEI. Build UEI-to-institution bridges; distinguish obligations, outlays, amendments, subawards and total award ceilings |
| [Census PSEO](https://www.census.gov/data/developers/data-sets/pseo.html) | Graduate earnings and employment flows support a separate education-to-workforce view | Institution/program/cohort aggregates where covered. Inspect participating institution coverage and suppression; graduate outcomes do not measure campus staff demand |
| [NCES CIP–SOC guidance](https://nces.ed.gov/Ipeds/cipcode/Files/IES2020_CIP_SOC_Crosswalk_508C.pdf) | Connect degree production to occupational opportunities and possible training pathways | Many-to-many program/occupation links. Not a prediction that graduates enter those jobs or an exact staffing supply estimate |
| [Illinois WARN notices](https://dceo.illinois.gov/workforcedevelopment/warn.html) and [archive](https://www.illinoisworknet.com/LayoffRecovery/Pages/ArchivedWARNReports.aspx) | Nearby announced layoffs may change applicant supply for shared job families | Employer/site/event dates. Notices cover qualifying events, not every reduction; validate later changes and avoid treating announcements as completed layoffs |
| [Anthropic Economic Index](https://www.anthropic.com/news/the-anthropic-economic-index) | Observed AI usage patterns can complement theoretical task exposure | Public released aggregates and associated datasets. Pin a release; Claude usage is a selected population, not representative university adoption or displacement |
| [Microsoft Working with AI](https://github.com/microsoft/working-with-ai) | Occupation/work-activity applicability offers another view of how tasks interact with AI | Public research aggregates. Verify taxonomy vintage and weighting; applicability is not a forecast of job elimination |
| [ILO refined exposure index](https://www.ilo.org/publications/generative-ai-and-jobs-refined-global-index-occupational-exposure) | Independent exposure framing for sensitivity checks | Research publication and associated materials. Check downloadable granularity and taxonomy; an ISCO-to-SOC bridge may introduce additional uncertainty |

Also consider campus operating budgets, board-approved reorganizations, procurement awards for ERP/AI systems, position-control budgets, training catalogs, and dated organizational charts. These are a targeted discovery backlog, not acquired datasets. A software procurement may signal workflow redesign, but does not prove a staffing reduction. Campus directory and org-chart changes need versioning and validation against position records.

For broad employer coverage, evaluate licensed providers such as Lightcast or Revelio only after a sample extract demonstrates Illinois coverage, university employer resolution, history, deduplication, and publication rights. No vendor capabilities or quotes were verified for this deliverable.

## How the data connects

Maintain separate occupation, organization, geography, industry, and time dimensions. Titles are descriptive labels rather than universal keys.

```text
SUCSS class/specification version ── reviewed role bridge ── O*NET occupation/version
Campus position + local working title ─────────────────────┘      │
                                                               tasks/skills
                                                                  │
O*NET occupation/version ── official SOC crosswalk/version ── BLS occupation facts

Posting + employer + requisition ── employer resolution ── institution (UNITID)
             │                                                 │
       reviewed occupation mapping                      IPEDS annual context
             │                                                 │
       daily/weekly hiring facts                     funding recipient bridges
```

Use the [official O*NET–SOC crosswalk](https://www.onetcenter.org/crosswalks.html). A code like 13-2011.00 may share a parent SOC stem, but string truncation is not a substitute for a version-checked bridge. Some BLS matrix codes are aggregates or special categories. Preserve unresolved records rather than silently forcing matches.

Store the class-to-occupation bridge with source record ID, class code, specification version, occupation code/version, proposed match, method, evidence text, reviewer, status, effective dates and optional allocation weight. Multiple occupations can describe a role. Use weights only with defensible evidence; mapping similarity is not an allocation weight or calibrated probability. For headcounts, enforce one counted position or weights summing to one, so a multi-match bridge does not multiply staff totals.

The acquired SUCSS catalog contains **883 records and 882 distinct class codes**. Code **1164** appears as both Police Telecommunicator and Public Safety Telecommunicator, with different source record IDs. Both are retained; classification status and historical meaning require review. This is a concrete reason to keep source identifiers and effective dates.

Add faculty and academic professional taxonomies from campus HR sources. Keep civil service class, working title, functional role, department, position and incumbent separate. Org charts establish reported structure only for their dated coverage; they do not prove what tasks people perform. For a public pilot, role/position-level structure is sufficient without building named employee profiles.

## HigherEdJobs and employer hiring analysis

Proposed sample: Illinois public universities plus a documented peer group matched on institution type, research intensity, medical-center scope, size and geography. Separate employers outside higher education that recruit comparable accountants, analysts, technologists and HR staff. National company hiring trends should be comparators, not substitutes for university trends.

Prefer an export/feed from HigherEdJobs and official career portals. Check source access and collection terms, retain only the fields needed, and record whether full text can be stored or redistributed. If feed access is unavailable, build a permitted small research sample and label coverage explicitly. Public visibility does not settle these operational details.

Capture daily snapshots when feasible: source posting ID, employer and canonical employer ID, requisition ID, URL, original title/text hash, first seen, last seen, stated posting date, deadline, employment type, faculty/staff category, appointment length, location, remote status, salary basis/range, duties, required/preferred skills, named tools and evidence spans. Missing salary is unknown; it is not zero. Normalize annual versus hourly pay only when hours and appointment assumptions are explicit.

Deduplicate first within source, then across sources using institution + requisition ID where available. Use title/location/text similarity as supporting evidence, preserve possible reposts, and distinguish a standing pool from a specific vacancy. One advertisement may represent multiple hires. A failed source refresh is not evidence that every posting closed.

Report new distinct requisitions, active inventory, exits from observed inventory, reposts, observation duration, skill share and salary coverage. Separate administrative, faculty, adjunct, clinical, student and temporary postings. Show coverage by source and institution next to every trend.

For employer comparisons, require consistent capture. Label zero observed postings as zero in the monitored sources, not proof that a company is not hiring. Employer hiring-freeze announcements and annual headcount disclosures are separate evidence types with their own dates and scope.

Treat the proposed **three-to-four-month horizon** as a research target. Postings disappearing can mean a filled role, canceled search, expiration, or source change. Actual hires/time-to-fill need requisition outcomes or another verified label. For faculty, model academic calendar seasonality separately. Collect at least 8–12 weeks for initial descriptive monitoring; year-over-year patterns require historical access or a longer panel. A one-day scrape supports a cross-sectional content study, not a hiring trend.

## AI transformation and durable skills

For each role, separate four observations: task applicability from research, actual tools/skills requested in postings, institution-specific adoption evidence, and observed staffing/role changes. Do not combine them into a job-loss probability.

Proposed workflow: extract task statements with exact source spans; map them to O*NET tasks/work activities; classify possible assistance, automation, or human accountability; review a stratified sample with HR and functional experts. Preserve model/prompt versions and reject unsupported skill assignments. Titles alone are insufficient for detailed skills inference.

Show task clusters and retraining options rather than rank employees by replacement risk. For example, payroll work may include document processing, exception review, system reconciliation and employee support; the share and organizational consequences must be measured locally. This is an illustrative decomposition, not a measured SUCSS assessment.

Candidate durable skill themes to test include data quality and reconciliation, domain judgment, compliance interpretation, stakeholder communication, process design, secure tool use, and verification of AI outputs. Tool-specific mentions change quickly. SQL, Python, BI tools and vendor AI products should be measured in the target posting sample before any claim that one is the most reliable choice.

## Common platform trial

The comparison is between implementation approaches, not three equivalent HR products. Databricks and Snowflake provide data/AI infrastructure; the institution-specific role ontology, mappings, validity rules and HR interface still need to be built.

| Workload | Custom baseline | Databricks experiment | Snowflake experiment |
|---|---|---|---|
| Ingest frozen public snapshots | Python + local JSON/Parquet, DuckDB or PostgreSQL | Notebook ingestion, Delta tables, governed volumes | Staged files, SQL loading and tables |
| Normalize/reference joins | SQL + Python validation | Spark/SQL and Delta workflows | SQL/Snowpark transformations |
| Extract and review skills | Shared extractor, evidence spans, review queue | Run the same baseline; optionally test managed AI separately | Run the same baseline; optionally test Cortex separately |
| Track forecasting experiments | Open-source tracking and explicit packaging | MLflow integration | Snowpark/available ML tooling with equivalent evaluation artifacts |
| Deliver role explorer | Shared app/BI layer | SQL dashboard or supported app path | BI or Streamlit where supported |
| Governance/operations | Assemble and maintain controls | Evaluate Unity Catalog controls and lineage | Evaluate roles, policies, lineage and account capabilities |

These are proposed implementations, not measured winners. Databricks documents [Unity Catalog](https://docs.databricks.com/aws/en/data-governance/unity-catalog/) and [MLflow integration](https://docs.databricks.com/aws/en/mlflow/). Snowflake documents [Snowpark Python](https://docs.snowflake.com/en/developer-guide/snowpark/python/index) and [dynamic tables](https://docs.snowflake.com/en/user-guide/dynamic-tables/overview). Test only capabilities actually enabled in the selected account/edition.

Start learning in [Databricks Free Edition](https://docs.databricks.com/aws/en/getting-started/free-edition), which is serverless and quota-limited. Its [limitations](https://docs.databricks.com/aws/en/getting-started/free-edition-limitations) mean it is not a production reliability benchmark. Use public reference data there. For Snowflake, [trial restrictions](https://docs.snowflake.com/en/en/user-guide/admin-trial-account) currently include unavailable external network access and limits on some AI usage; use the same externally acquired uploaded snapshots on all three systems. Do not score trial-specific unavailable features as proof the paid product lacks them.

Track analyst build hours, repeat-run hours, ingestion failures/recovery, lineage completeness, mapping accuracy, extraction precision/recall, query latency, refresh duration, billed compute/storage/AI usage and administration effort. Compare identical data, queries and extractor versions; distinguish cold from warm runs. Report trial credits separately from estimated recurring cost. Avoid vendor-cost rankings before measuring usage and obtaining institution-specific terms.

Suggested weighted scorecard: correctness/reproducibility 25%, maintainability 20%, governance 20%, operating cost 15%, analyst usability 10%, portability 10%. Agree weights before executing. Score from evidence, with unavailable or untested marked explicitly rather than assigned zero.

## Execution sequence and acceptance criteria

1. **Reference-data run:** acquire and freeze O*NET/SUCSS/BLS/IPEDS; resolve source vintages; create the occupation and institution bridges. Verify IDs, duplicate classes, units, suppression, and mapping fanout.
2. **Mapping review:** select roughly 50–100 roles across pilot families; obtain duties and review the top candidate occupations. Measure top-choice accuracy and abstention on a held-out, independently reviewed sample. The included title-only baseline establishes a starting point, not production quality.
3. **Posting collection:** establish permitted access and create a consistent peer panel. Audit duplicates, coverage, false closures, missing dates and salary fields. Add historical extracts if available.
4. **Common descriptive demo:** show one role's classification, task evidence, BLS context, peer staffing context and current observed recruitment. Missing data stays visible.
5. **Platform replay:** run identical snapshots on the custom stack, Databricks and Snowflake; record correctness, runtime, cost and effort. Keep optional AI features in a separate comparison so model differences do not confound platform differences.
6. **Forecast extension:** with sufficient history and real requisition outcomes, backtest the 90–120 day horizon using chronological splits, seasonal baselines and uncertainty intervals. Keep historical source publication dates to avoid future-data leakage. Compare against last-period and same-season baselines before claiming forecasting value.

The first demonstrable success is a traceable role-to-external-evidence workflow. A defensible predictive result requires longitudinal data and outcomes; it is not established by the reference-data prototype.

## What exists in this workspace

- Real unmodified O*NET 31.0 occupation JSON: 1,016 occupation records.
- Real SUCSS catalog response: 883 records; individual class specification texts are not yet downloaded.
- Source HTML snapshot, prepared JSONL reference tables, a title-only top-three review queue, and a hash manifest with pending acquisition items.
- A locally executable preparation script and an importable Databricks notebook for reference ingestion and review. The notebook needs a real workspace and uploaded Volume path; it has not been run on Databricks.
- No current HigherEdJobs posting inventory, no calculated employment-direction findings, and no measured platform comparison yet.

See README.md for exact local and Databricks practice-run steps.
