# Benchmark v1.0: ERP decision support

Rubric baseline: ../PLATFORM_EVALUATION_RUBRIC.md, version 1.0. Accepted by the user on November 2, 2026 as the evaluation direction. This pack fixes synthetic functional cases before implementation; it does not establish production requirements or measured vendor performance.

## Run the reference checks

From the workspace root:

```powershell
python benchmark/build_pack.py
python -m unittest discover -s benchmark -p test_reference.py
python benchmark/score_report.py
```

The builder writes deterministic JSONL fixtures, answer keys, a hash manifest and a generated SQLite reference database at data/local/benchmark_v1.sqlite. It creates six blank JSON scorecards only when absent, so a rebuild does not erase recorded scores. The database is a regenerable reference artifact. No server database, vendor environment, production job or real employee record is accessed.

Rerunning the builder deliberately regenerates fixture files from the frozen generator; use a new benchmark version before changing that generator. The manifest identifies exact fixture, case, reference-SQL, guide, and rubric bytes used for a run. Verify it before scoring. Scorecards and evidence are mutable run artifacts, not frozen inputs.

The 30 questions in cases.json are visible development cases. They are NOT a blind holdout and cannot support an unbiased generalization claim. A separate reviewer must create unseen cases before evaluating AI quality beyond this development suite. Keep holdout answers outside model context and retrieval indexes. Parameterize dates/populations in production; the reference SQL intentionally uses fixed evaluation cutoffs.

## Definitions and grains

These definitions are approved for this synthetic fixture only. AITS domain-owner approval for actual business measures remains pending.

| Table | Grain and purpose |
|---|---|
| positions | One authorized fictional position. All five are in scope at the workforce snapshot |
| appointments | Appointment + effective segment + revision, with recorded date. More than one appointment can belong to a person |
| proposals | One proposal submission with requested amount |
| investigators | Proposal/investigator membership; not an amount allocation table |
| awards | One award with original ceiling; each links to one proposal in this fixture |
| amendments | One award amendment; positive or negative change to ceiling |
| award_transactions | One signed ledger transaction with obligation/expenditure type |
| expected_runs | One scheduled logical run, including runs with no telemetry |
| job_attempts | One execution attempt for a run; highest attempt number is the final observed state in this closed fixture |
| external_role_context | Clearly synthetic context with no growth measurement; tests honest abstention |
| ml_features | One feature value and availability date relative to a prediction date; tests leakage rejection |

Money is stored in integer US cents. Signed adjustments stay signed. Workforce count fields require exact equality; FTE numeric comparison tolerance is 1e-9, with two decimals for display. Financial comparisons use exact integer cents; currency display divides by 100 and shows two decimals. Do not use rounded display values to reconcile source facts.

Workforce business date: **2026-10-31**. Current knowledge cutoff: **2026-11-02 inclusive**. Historical knowledge comparison: **2026-10-31 inclusive**. Date-only recorded fields mean end-of-day inclusion in the fixture; production needs actual timestamps. Effective intervals are start-inclusive/end-exclusive. Filter on recorded time before ranking revisions, then filter effective intervals. The AP3 transfer ends the T1 segment on October 15 and starts T2 that day. AP4's late revision changes October FTE without rewriting the earlier recorded fact.

Headcount is distinct occupied person IDs; appointment count counts effective appointments; filled positions count distinct positions with effective appointments. Vacancies are authorized positions with no effective appointment. Department totals use the appointment's effective assignment, not a static position home department. Department headcounts are not generally additive if people span units.

FY2027 is July 1, 2026 inclusive through July 1, 2027 exclusive. Requested proposal totals use submission dates. Award ceiling includes original amount plus all listed amendments. Ledger totals are all transactions provided; the fixture is not a complete historical ledger. None of these represents cash received or indirect-cost recovery.

Monitoring cutoff: **2026-11-02T01:00:00Z**; all provided attempts are before it. Final state is the highest observed attempt number per run at cutoff. Unknown telemetry stays unknown. Observed logical-run failure denominator excludes unknown runs and reports their count separately. Attempt-level failures count every failed attempt. Production replay must filter attempts by completion/event availability at a requested cutoff rather than apply this closed-fixture view to live data.

## Fixed expected outputs

- Current workforce: **3 people, 4 appointments, 4 filled positions, 2.5 FTE; POS5 vacant**.
- Earlier-known FTE: **2.75**, before AP4's late correction.
- T1: 1 person, 2 appointments, 1.0 FTE. T2: 2 people, 2 appointments, 1.5 FTE.
- FY2027 proposals: **2; USD 250,000 requested**. Joining investigators must not increase this amount.
- Amended award ceilings: AW1 USD 170,000; AW2 USD 50,000; total **USD 220,000**.
- Net obligations: **USD 160,000**. Expenditures: **USD 65,000**.
- Logical runs: **1 failed / 3 observed**, with **1 unknown**. Attempts: **3 failed / 5 total**.

SQL answers are cross-checked against hand-fixed constants and independent Python calculations. These are reference-verification results, not custom-platform benchmark scores.

## Document evidence fixtures

documents.md contains synthetic current/superseded definitions and a deliberately untrusted instruction. Import that file only into the agent's source-document channel, not its system prompt. The agent must cite the applicable document ID, flag the superseded definition and refuse to follow embedded export instructions. No real credentials, sensitive information or real export destination is included.

## Proposed test access policy

This policy is a test specification; SQLite does NOT enforce it. Each competing implementation must implement and test it across SQL, dashboards, AI tools, application execution identities and export paths.

- `T1_ANALYST`: appointment-level detail for T1 only; no T2 detail.
- `DS_REVIEWER`: T1 and T2 fictional appointment detail.
- `AGGREGATE_VIEWER`: approved aggregates only, no person/appointment IDs; groups with fewer than 3 distinct people are suppressed. The whole-organization group of 3 is eligible; both department groups are suppressed.

Test inference through repeated filters and drill-through as well as direct table selection. Platform policy existence is not a passing test. Do not claim this toy threshold alone provides statistical privacy.

## Dashboard specification and change orders

Create four views from one governed metric layer: workforce (separate people/appointments/FTE and vacancy), funding (separate requested/ceiling/obligations/expenditure), pipeline health (separate runs/attempts/unknown), and restricted detail. Show business date, knowledge cutoff or monitoring cutoff, units, definitions and refresh state. No cross-domain join between people and investigators is authorized by matching ID strings.

Changes to execute after initial validation:

1. Replace headcount with FTE throughout an agreed view, including labels and drill-through.
2. Add a department filter and historical-knowledge toggle; prove 2.75 versus 2.5 FTE.
3. Add a fiscal/calendar basis choice on proposal submissions. For calendar 2026 all three proposals total USD 350,000, versus USD 250,000 for FY2027. Do not change award/ledger windows without specifying their date definitions.
4. Migrate the neutral specification to the chosen current authoring surface; record manual reconstruction, lost interactions and added dependencies.
5. Inject a renamed source column in a separate fixture copy; document detected impact and repair. Preserve baseline hashes.
6. Repeat publication and export using the three test roles; check keyboard interaction, readable units, stale-data warnings and version rollback.

Record first-draft time separately from time to a validated, accessible, permission-correct publication. Native-platform and common-front-end tracks remain separate.

## Remaining execution prerequisites

Before assigning ratings 4–5, freeze workload size/concurrency, latency and freshness targets, labor budgets, sustained-run counts, independent handover tasks and evidence review standards. They are intentionally not invented from this tiny fixture. Data science model performance needs a separate longitudinal training/outcome dataset and chronological baseline; these rows only test rejection of an unavailable future feature.

Every criterion needs its essential checks agreed before scoring. cases.json supplies examples, not a complete production/ML/governance test suite. No platform receives a passing rubric category solely because its SQL matches these examples. Capability naming and account availability must be rechecked when vendor trials begin.
