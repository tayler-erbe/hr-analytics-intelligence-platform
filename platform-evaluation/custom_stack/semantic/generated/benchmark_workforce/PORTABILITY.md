# Portability report: benchmark_workforce

Generated from `benchmark_workforce.yaml` (sha256 `165342455c6b88cda6b29a13ffd3dc7cbdbd19c6cc0dbb6a9bc78fab45570ff5`). Status: fixture_only.
Vendor artefacts were generated, not executed against Snowflake or Databricks.

| metric | type | DuckDB (reference) | Snowflake semantic view | Cortex YAML | Databricks metric view |
|---|---|---|---|---|---|
| wf_headcount | simple | exact | emitted with caveat | emitted with caveat | emitted with caveat |
| wf_appointment_count | simple | exact | emitted with caveat | emitted with caveat | emitted with caveat |
| wf_fte | simple | exact | emitted with caveat | emitted with caveat | emitted with caveat |
| wf_filled_positions | simple | exact | emitted with caveat | emitted with caveat | emitted with caveat |
| wf_vacant_positions | simple | exact | emitted | emitted | emitted |

## Warnings

### Snowflake semantic view
- entity appointment_segment: logical SQL view emitted verbatim; Snowflake dialect not executed here
- entity position_status: logical SQL view emitted verbatim; Snowflake dialect not executed here
- wf_headcount: knowledge_basis pinned to 'current' in this target; other values need a separate metric (the custom compiler allows an explicit filter)
- wf_appointment_count: knowledge_basis pinned to 'current' in this target; other values need a separate metric (the custom compiler allows an explicit filter)
- wf_fte: knowledge_basis pinned to 'current' in this target; other values need a separate metric (the custom compiler allows an explicit filter)
- wf_filled_positions: knowledge_basis pinned to 'current' in this target; other values need a separate metric (the custom compiler allows an explicit filter)

### Cortex Analyst YAML
- wf_headcount: knowledge_basis pinned to 'current' in this target; other values need a separate metric (the custom compiler allows an explicit filter)
- wf_appointment_count: knowledge_basis pinned to 'current' in this target; other values need a separate metric (the custom compiler allows an explicit filter)
- wf_fte: knowledge_basis pinned to 'current' in this target; other values need a separate metric (the custom compiler allows an explicit filter)
- wf_filled_positions: knowledge_basis pinned to 'current' in this target; other values need a separate metric (the custom compiler allows an explicit filter)

### Databricks metric views
- wf_headcount: knowledge_basis pinned to 'current' in this target; other values need a separate metric (the custom compiler allows an explicit filter)
- wf_appointment_count: knowledge_basis pinned to 'current' in this target; other values need a separate metric (the custom compiler allows an explicit filter)
- wf_fte: knowledge_basis pinned to 'current' in this target; other values need a separate metric (the custom compiler allows an explicit filter)
- wf_filled_positions: knowledge_basis pinned to 'current' in this target; other values need a separate metric (the custom compiler allows an explicit filter)
- entity appointment_segment: logical SQL view must be created in Unity Catalog first (dialect not executed here)
- entity position_status: logical SQL view must be created in Unity Catalog first (dialect not executed here)
