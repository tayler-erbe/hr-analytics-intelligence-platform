# Mock-conversion reconciliation harness: design

Status: development draft, demonstrated on synthetic data only (`../reconcile.py`). The tolerances in `tolerances.yaml` are proposals. No data steward or integrator has agreed them.

## Purpose

Every mock conversion has to answer one question: **did everything that should have arrived in the target arrive, and can we explain everything that did not?** Readiness rules (`../rules/catalog.yaml`) find defects in the *source*. Reconciliation finds defects in the *conversion*: crosswalk gaps, transformation bugs, silent defaults and dropped rows. Neither replaces the other. The synthetic M1 cycle shows why. One org is missing from the org crosswalk and silently defaults to `UNMAPPED`. All 43 source rules are blind to that defect, and reconciliation flags it immediately.

## Three numbers per group

For every metric and grain group the harness computes:

| Symbol | Meaning | Where it comes from |
|---|---|---|
| **L** (legacy) | The measure on the legacy snapshot at the cutover date | EDW staging views (the same `stg_*` views the rules use) |
| **E** (expected) | L minus the records the load *documented* as rejected | Legacy rows joined to the reject log. Each reject carries the readiness rule ID that predicted it |
| **T** (target) | The same measure computed from the converted data | Integrator extract of the loaded tenant or pod. In this repo it comes from the mock converter's `tgt_*` tables |

Classification (implemented in `reconcile.classify`, unit-tested):

- **match**: \|T − L\| ≤ tolerance
- **explained**: otherwise, if \|T − E\| ≤ tolerance. The gap is fully accounted for by documented rejections, and each rejection names a rule (S04, E03, C01 ...) so the fix goes to the right owner.
- **unexplained**: anything else. This blocks steward sign-off for the conversion object.

Tolerance is `max(abs_tol, rel_tol × |reference|)`.

## Metrics and grains (v0.1)

| Metric | Definition | Grain | Tolerance | Why |
|---|---|---|---|---|
| headcount | distinct workers with an active assignment on cutover date | org × worker group (employee-class group) | 0 | People are counted, not estimated |
| appointments | active assignments (Banner jobs) | org × class | 0 | One Banner job maps to one assignment or position fill |
| fte | sum of assignment FTE | org × class | 0.01 per group | Allows FTE ↔ scheduled-hours rounding in the target |
| pay_total | historical pay loaded as pay results or balances, last 12 periods | org × period | $0.00 | Loaded history is not recomputed, so it must tie to the cent |

Definitions follow the separation already used in this repository's semantic layer and benchmark. Headcount (distinct people), appointment count and FTE are different metrics. Department headcount is not additive across departments. See `../../custom_stack/semantic/specs/benchmark_workforce.yaml` (`wf_headcount`, `wf_appointment_count`, `wf_fte`) and `../../benchmark/README.md`.

Before the first real mock, add these metrics. They are listed in `../../research/HR_USE_CASES_AND_GUARDRAILS.md` §2.4 and need source tables this toolkit does not model yet:

- headcount by bargaining unit
- YTD earnings and deductions per employee
- benefit enrollments and SURS tier
- leave balances
- labor-distribution totals by fund or grant

**Parallel payroll** (gross-to-net recomputed in the target) is a separate test with its own per-employee tolerance. `tolerances.yaml` records it, but it cannot run without a target tenant. The UChicago HCM deck reports >99 % pay accuracy, so a target like that should be agreed explicitly with University Payroll.

## Process per mock cycle

1. Freeze the legacy snapshot (EDW extract date = cutover date) and record its row counts and hashes.
2. Run the readiness rules on the snapshot. Publish the issue register to owners.
3. The integrator loads the target and returns (a) the reject log with legacy keys and (b) a target extract at the same grains. Ask for both in the statement of work.
4. Run reconciliation. Every *explained* gap has a rule ID and an owner. Every *unexplained* gap gets a defect ticket against the converter or the crosswalk.
5. Data stewards sign off per conversion object (worker, position, assignment, compensation, pay history). Record the sign-off with the cycle label.
6. Trend: rule failures, rejections and unexplained groups across cycles (dashboard). Plan at least four cycles. Richmond converted its Banner data into Workday four times.

## Synthetic demonstration (what `reconcile.py` actually does)

- The mock converter maps workers with survivorship on the national-ID hash. It maps orgs through a crosswalk to `SO-<org>` (inactive orgs included, because pay history references them) and classes to `JP-<class>`.
- It rejects assignments in this order: no person (P05), position missing (S04), employee terminated (E03), FTE > 1 (J06), no class (C04), unmappable class (C01), inactive or unknown org (O06).
- It rejects pay rows with no person (P05) or with a position missing from position control (Y03).
- Results on seed 20261106:
  - CLEAN: all groups match.
  - M1: *unexplained*, and only for org U111 and `UNMAPPED` (the planted crosswalk bug).
  - M2–M3: *explained*.
  - M4: *match*.

  The tests assert the M1 result and assert that every M1 gap is explained once the bug is removed.

Limitations:

- The converter is a stand-in, so its rejection logic is our hypothesis of loader behavior, not Workday or Oracle documentation.
- Metrics run at the snapshot date only, not over full history.
- No bitemporal (as-known) comparison.
- Surrogate keys: real reconciliation must also compare at the record level (legacy key ↔ target ID crosswalk), not only aggregates.

## Portability

L and E are SQL over the same logical staging views as the rules, so they run wherever the rules run (DuckDB here; Snowflake, Databricks or Oracle on an approved platform). T is a query over whatever extract the integrator provides. Only that query changes when the vendor is chosen.
