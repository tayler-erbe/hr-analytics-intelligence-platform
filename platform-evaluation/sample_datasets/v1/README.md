# Synthetic workforce sample datasets

All people, identifiers, histories, compensation, organizations and demographic
attributes are invented. Public SUCSS codes/titles are reference labels only.
These data have NOT been calibrated against EDW. Physical layouts and code meanings
remain assumptions. The proposal documents and any internal links are not included.

## Three sets

- quality/CLEAN: coherent small workforce for joins, validation and reporting.
- quality/DEFECTS: same seeded source world plus deliberately planted defects.
  Its manifest lists injected cases; do not interpret them as real defect rates.
- longitudinal: multi-year bitemporal history for mobility, separation, vacancy,
  temporal validation and leakage tests. truth.json records the planted assumptions.

Each set has typed Parquet, JSONL copies, a DuckDB database and schema_assumptions.json.
The longitudinal database also defines a synthetic V_EMPEE_HIST_1 view at 2026-10-31.
Do not join the CLEAN, DEFECTS and longitudinal populations to one another: they are
separate worlds, and matching synthetic IDs do not establish a cross-world identity.

Start with inventory.json, scope_and_assumptions.json and generation_summary.json.
Use role/unit aggregate outputs for demonstrations; no individual employee scoring
is enabled by generating these files. Synthetic demographic columns belong in an
audit experiment, not automatically in predictive features.

This is structural and scenario ground truth only. Matching synthetic and actual
model conclusions is not guaranteed. A future approved metadata/profile exercise
must verify fields, temporal conventions, distributions and appropriate use.
