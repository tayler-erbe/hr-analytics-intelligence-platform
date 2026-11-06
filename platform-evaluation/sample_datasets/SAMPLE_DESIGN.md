# Sample design and interpretation

The aim is a useful placeholder for workforce reporting and pipeline development while preserving a clear boundary between invented behavior and verified data definitions.

## Relationships to preserve

Person, employment, appointment, position, department and payroll transaction are different grains. A person can hold multiple appointments. A position can remain authorized while vacant. A pay change does not necessarily mean a role change. Payroll transactions cannot be joined to every historical job row and then summed without a temporal and grain rule.

The quality sets exercise those relationships and planted failures. The longitudinal set supports synthetic transitions, separations and retroactive recording. Its `truth.json` records planted coefficients and scenarios. That is simulation truth, not empirical evidence about the university.

## Time conventions

These generators assume inclusive effective-end dates and exclusive recorded-version end dates, using 9999-12-31 as the open-end marker. Effective business dates and when a record became known are separate concepts. The date and version fields are test assumptions; do not automatically map a source system's posting date to full transaction-time history.

## Values and derived fields

Pay ranges, class distributions, exit hazards, role-family criticality and retirement eligibility simplifications are invented. Synthetic demographic codes support an audit experiment; they are not observed group statistics. Title or grade changes are candidate transition signals, not verified promotion labels. Skill clusters, learning records and job-description evidence cannot be claimed as observed merely because a prototype expects them.

When building examples, distinguish changes to titles from changes to tasks, and changes to salary from changes to appointment or position. Use a separate reviewed event ledger for planted cases when extending the generator. Avoid teaching a model that a random label is a real personnel outcome.

## What these samples cannot establish

They do not establish actual turnover, compensation, retirement, mobility or skill distributions. They cannot prove real-data prediction accuracy, causality, retention savings, comparative vendor performance or current field semantics. Matching synthetic and real model conclusions is not a guaranteed property of good synthetic data.

Future calibration should evaluate structural fidelity, marginal and relational distributions, temporal behavior, utility on specified tasks, and disclosure risk separately. It requires appropriate evidence and a separately reviewed protocol. The current sample package does not require or initiate any EDW connection.

## Versioning

Keep v1 intact as an assumed-layout sample. A later historically documented or dictionary-verified schema adapter should have its own version, mapping provenance, unresolved fields and tests. Do not silently rewrite the frozen platform benchmark or change acceptance gates to make a revised sample pass.
