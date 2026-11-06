# Portability report: hr_public

Generated from `hr_public.yaml` (sha256 `102bec2ac50cb4a94f7b417621650769eff132e8ae15c7615c9f69844f0f87d6`). Status: development.
Vendor artefacts were generated, not executed against Snowflake or Databricks.

| metric | type | DuckDB (reference) | Snowflake semantic view | Cortex YAML | Databricks metric view |
|---|---|---|---|---|---|
| staff_headcount | simple | exact | emitted with caveat | emitted with caveat | emitted with caveat |
| full_time_staff_headcount | simple | exact | emitted with caveat | emitted with caveat | emitted with caveat |
| staff_fte | simple | exact | emitted with caveat | emitted with caveat | emitted with caveat |
| instructional_staff_count | simple | exact | emitted | emitted | emitted |
| avg_instructional_salary | ratio | exact | emitted with caveat | emitted with caveat | emitted with caveat |
| avg_noninstructional_salary | ratio | exact | emitted | emitted | emitted |
| noninstructional_salary_outlays | simple | exact | emitted | emitted | emitted |
| enrollment_12mo | simple | exact | emitted with caveat | emitted with caveat | emitted with caveat |
| staff_fte_per_100_students | derived | exact | emitted with caveat | not emitted | not emitted |
| qcew_employment | simple | exact | emitted with caveat | emitted with caveat | emitted with caveat |
| qcew_total_wages | simple | exact | emitted with caveat | emitted with caveat | emitted with caveat |
| qwi_employment | simple | exact | emitted with caveat | emitted with caveat | emitted with caveat |
| qwi_hires | simple | exact | emitted with caveat | emitted with caveat | emitted with caveat |
| qwi_separations | simple | exact | emitted with caveat | emitted with caveat | emitted with caveat |
| qwi_avg_monthly_earnings | ratio | exact | emitted with caveat | emitted with caveat | emitted with caveat |
| occupation_count | simple | exact | emitted | emitted | emitted |
| task_statement_count | simple | exact | emitted | emitted | emitted |
| core_task_count | simple | exact | emitted | emitted | emitted |
| ai_task_usage_pct | simple | exact | emitted with caveat | emitted with caveat | emitted with caveat |
| sucss_class_record_count | simple | exact | emitted | emitted | emitted |
| sucss_class_code_count | simple | exact | emitted | emitted | emitted |

## Warnings

### Snowflake semantic view
- entity qcew: logical SQL view emitted verbatim; Snowflake dialect not executed here
- relationship aei_task_text (many_to_many) intentionally omitted: Task text is not unique across occupations (and AEI lower-cases it); joining would fan out usage percentages. Blocked.
- relationship sucss_onet_candidate (many_to_many) intentionally omitted: Mappings are unreviewed lexical suggestions (sucss_onet_candidate); not an approved join.
- staff_headcount: category_total_row pinned to 'false' in this target; other values need a separate metric (the custom compiler allows an explicit filter)
- full_time_staff_headcount: category_total_row pinned to 'false' in this target; other values need a separate metric (the custom compiler allows an explicit filter)
- staff_fte: category_total_row pinned to 'false' in this target; other values need a separate metric (the custom compiler allows an explicit filter)
- avg_instructional_salary: contract_length pinned to '9-month' in this target; other values need a separate metric (the custom compiler allows an explicit filter)
- enrollment_12mo: breakdown by student_level is lost in this target (measure pinned to total row '1'); the custom compiler switches to member rows when grouped
- staff_fte_per_100_students: emitted as a Snowflake derived (view-level) metric; cross-table aggregation behaviour must be checked by result equality
- staff_fte_per_100_students: population alignment on unitid is NOT expressible; the Snowflake metric divides unaligned totals (can differ from the reference)
- qcew_employment: rule 'area must be chosen' (National, state and county rows overlap; summing areas double counts.) cannot be enforced in a single aggregate; carried only as comment/instructions. Summing across it is possible here.
- qcew_employment: industry pinned to '611310' in this target; other values need a separate metric (the custom compiler allows an explicit filter)
- qcew_total_wages: rule 'area must be chosen' (National, state and county rows overlap; summing areas double counts.) cannot be enforced in a single aggregate; carried only as comment/instructions. Summing across it is possible here.
- qcew_total_wages: industry pinned to '611310' in this target; other values need a separate metric (the custom compiler allows an explicit filter)
- qwi_employment: geography pinned to '17' in this target; other values need a separate metric (the custom compiler allows an explicit filter)
- qwi_employment: breakdown by sex is lost in this target (measure pinned to total row '0'); the custom compiler switches to member rows when grouped
- qwi_employment: breakdown by age_group is lost in this target (measure pinned to total row 'A00'); the custom compiler switches to member rows when grouped
- qwi_employment: industry pinned to '6113' in this target; other values need a separate metric (the custom compiler allows an explicit filter)
- qwi_employment: ownership pinned to 'A00' in this target; other values need a separate metric (the custom compiler allows an explicit filter)
- qwi_hires: geography pinned to '17' in this target; other values need a separate metric (the custom compiler allows an explicit filter)
- qwi_hires: breakdown by sex is lost in this target (measure pinned to total row '0'); the custom compiler switches to member rows when grouped
- qwi_hires: breakdown by age_group is lost in this target (measure pinned to total row 'A00'); the custom compiler switches to member rows when grouped
- qwi_hires: industry pinned to '6113' in this target; other values need a separate metric (the custom compiler allows an explicit filter)
- qwi_hires: ownership pinned to 'A00' in this target; other values need a separate metric (the custom compiler allows an explicit filter)
- qwi_separations: geography pinned to '17' in this target; other values need a separate metric (the custom compiler allows an explicit filter)
- qwi_separations: breakdown by sex is lost in this target (measure pinned to total row '0'); the custom compiler switches to member rows when grouped
- qwi_separations: breakdown by age_group is lost in this target (measure pinned to total row 'A00'); the custom compiler switches to member rows when grouped
- qwi_separations: industry pinned to '6113' in this target; other values need a separate metric (the custom compiler allows an explicit filter)
- qwi_separations: ownership pinned to 'A00' in this target; other values need a separate metric (the custom compiler allows an explicit filter)
- qwi_avg_monthly_earnings: geography pinned to '17' in this target; other values need a separate metric (the custom compiler allows an explicit filter)
- qwi_avg_monthly_earnings: breakdown by sex is lost in this target (measure pinned to total row '0'); the custom compiler switches to member rows when grouped
- qwi_avg_monthly_earnings: breakdown by age_group is lost in this target (measure pinned to total row 'A00'); the custom compiler switches to member rows when grouped
- qwi_avg_monthly_earnings: industry pinned to '6113' in this target; other values need a separate metric (the custom compiler allows an explicit filter)
- qwi_avg_monthly_earnings: ownership pinned to 'A00' in this target; other values need a separate metric (the custom compiler allows an explicit filter)
- ai_task_usage_pct: rule 'release must be chosen' (Percentages are only comparable within one release; summing releases is meaningless.) cannot be enforced in a single aggregate; carried only as comment/instructions. Summing across it is possible here.

### Cortex Analyst YAML
- staff_headcount: category_total_row pinned to 'false' in this target; other values need a separate metric (the custom compiler allows an explicit filter)
- full_time_staff_headcount: category_total_row pinned to 'false' in this target; other values need a separate metric (the custom compiler allows an explicit filter)
- staff_fte: category_total_row pinned to 'false' in this target; other values need a separate metric (the custom compiler allows an explicit filter)
- avg_instructional_salary: contract_length pinned to '9-month' in this target; other values need a separate metric (the custom compiler allows an explicit filter)
- enrollment_12mo: breakdown by student_level is lost in this target (measure pinned to total row '1'); the custom compiler switches to member rows when grouped
- qcew_employment: rule 'area must be chosen' (National, state and county rows overlap; summing areas double counts.) cannot be enforced in a single aggregate; carried only as comment/instructions. Summing across it is possible here.
- qcew_employment: industry pinned to '611310' in this target; other values need a separate metric (the custom compiler allows an explicit filter)
- qcew_total_wages: rule 'area must be chosen' (National, state and county rows overlap; summing areas double counts.) cannot be enforced in a single aggregate; carried only as comment/instructions. Summing across it is possible here.
- qcew_total_wages: industry pinned to '611310' in this target; other values need a separate metric (the custom compiler allows an explicit filter)
- qwi_employment: geography pinned to '17' in this target; other values need a separate metric (the custom compiler allows an explicit filter)
- qwi_employment: breakdown by sex is lost in this target (measure pinned to total row '0'); the custom compiler switches to member rows when grouped
- qwi_employment: breakdown by age_group is lost in this target (measure pinned to total row 'A00'); the custom compiler switches to member rows when grouped
- qwi_employment: industry pinned to '6113' in this target; other values need a separate metric (the custom compiler allows an explicit filter)
- qwi_employment: ownership pinned to 'A00' in this target; other values need a separate metric (the custom compiler allows an explicit filter)
- qwi_hires: geography pinned to '17' in this target; other values need a separate metric (the custom compiler allows an explicit filter)
- qwi_hires: breakdown by sex is lost in this target (measure pinned to total row '0'); the custom compiler switches to member rows when grouped
- qwi_hires: breakdown by age_group is lost in this target (measure pinned to total row 'A00'); the custom compiler switches to member rows when grouped
- qwi_hires: industry pinned to '6113' in this target; other values need a separate metric (the custom compiler allows an explicit filter)
- qwi_hires: ownership pinned to 'A00' in this target; other values need a separate metric (the custom compiler allows an explicit filter)
- qwi_separations: geography pinned to '17' in this target; other values need a separate metric (the custom compiler allows an explicit filter)
- qwi_separations: breakdown by sex is lost in this target (measure pinned to total row '0'); the custom compiler switches to member rows when grouped
- qwi_separations: breakdown by age_group is lost in this target (measure pinned to total row 'A00'); the custom compiler switches to member rows when grouped
- qwi_separations: industry pinned to '6113' in this target; other values need a separate metric (the custom compiler allows an explicit filter)
- qwi_separations: ownership pinned to 'A00' in this target; other values need a separate metric (the custom compiler allows an explicit filter)
- qwi_avg_monthly_earnings: geography pinned to '17' in this target; other values need a separate metric (the custom compiler allows an explicit filter)
- qwi_avg_monthly_earnings: breakdown by sex is lost in this target (measure pinned to total row '0'); the custom compiler switches to member rows when grouped
- qwi_avg_monthly_earnings: breakdown by age_group is lost in this target (measure pinned to total row 'A00'); the custom compiler switches to member rows when grouped
- qwi_avg_monthly_earnings: industry pinned to '6113' in this target; other values need a separate metric (the custom compiler allows an explicit filter)
- qwi_avg_monthly_earnings: ownership pinned to 'A00' in this target; other values need a separate metric (the custom compiler allows an explicit filter)
- ai_task_usage_pct: rule 'release must be chosen' (Percentages are only comparable within one release; summing releases is meaningless.) cannot be enforced in a single aggregate; carried only as comment/instructions. Summing across it is possible here.
- staff_fte_per_100_students: cross-table derived metric not representable in legacy Cortex Analyst YAML; use the semantic view DDL or a verified query

### Databricks metric views
- staff_fte_per_100_students: derived across entities ['staff_eap', 'enrollment']; a UC metric view has a single source, so this metric is NOT emitted (compose two metric-view queries or materialise a joined aggregate)
- staff_headcount: category_total_row pinned to 'false' in this target; other values need a separate metric (the custom compiler allows an explicit filter)
- full_time_staff_headcount: category_total_row pinned to 'false' in this target; other values need a separate metric (the custom compiler allows an explicit filter)
- staff_fte: category_total_row pinned to 'false' in this target; other values need a separate metric (the custom compiler allows an explicit filter)
- avg_instructional_salary: contract_length pinned to '9-month' in this target; other values need a separate metric (the custom compiler allows an explicit filter)
- enrollment_12mo: breakdown by student_level is lost in this target (measure pinned to total row '1'); the custom compiler switches to member rows when grouped
- qcew_employment: rule 'area must be chosen' (National, state and county rows overlap; summing areas double counts.) cannot be enforced in a single aggregate; carried only as comment/instructions. Summing across it is possible here.
- qcew_employment: industry pinned to '611310' in this target; other values need a separate metric (the custom compiler allows an explicit filter)
- qcew_total_wages: rule 'area must be chosen' (National, state and county rows overlap; summing areas double counts.) cannot be enforced in a single aggregate; carried only as comment/instructions. Summing across it is possible here.
- qcew_total_wages: industry pinned to '611310' in this target; other values need a separate metric (the custom compiler allows an explicit filter)
- qwi_employment: geography pinned to '17' in this target; other values need a separate metric (the custom compiler allows an explicit filter)
- qwi_employment: breakdown by sex is lost in this target (measure pinned to total row '0'); the custom compiler switches to member rows when grouped
- qwi_employment: breakdown by age_group is lost in this target (measure pinned to total row 'A00'); the custom compiler switches to member rows when grouped
- qwi_employment: industry pinned to '6113' in this target; other values need a separate metric (the custom compiler allows an explicit filter)
- qwi_employment: ownership pinned to 'A00' in this target; other values need a separate metric (the custom compiler allows an explicit filter)
- qwi_hires: geography pinned to '17' in this target; other values need a separate metric (the custom compiler allows an explicit filter)
- qwi_hires: breakdown by sex is lost in this target (measure pinned to total row '0'); the custom compiler switches to member rows when grouped
- qwi_hires: breakdown by age_group is lost in this target (measure pinned to total row 'A00'); the custom compiler switches to member rows when grouped
- qwi_hires: industry pinned to '6113' in this target; other values need a separate metric (the custom compiler allows an explicit filter)
- qwi_hires: ownership pinned to 'A00' in this target; other values need a separate metric (the custom compiler allows an explicit filter)
- qwi_separations: geography pinned to '17' in this target; other values need a separate metric (the custom compiler allows an explicit filter)
- qwi_separations: breakdown by sex is lost in this target (measure pinned to total row '0'); the custom compiler switches to member rows when grouped
- qwi_separations: breakdown by age_group is lost in this target (measure pinned to total row 'A00'); the custom compiler switches to member rows when grouped
- qwi_separations: industry pinned to '6113' in this target; other values need a separate metric (the custom compiler allows an explicit filter)
- qwi_separations: ownership pinned to 'A00' in this target; other values need a separate metric (the custom compiler allows an explicit filter)
- qwi_avg_monthly_earnings: geography pinned to '17' in this target; other values need a separate metric (the custom compiler allows an explicit filter)
- qwi_avg_monthly_earnings: breakdown by sex is lost in this target (measure pinned to total row '0'); the custom compiler switches to member rows when grouped
- qwi_avg_monthly_earnings: breakdown by age_group is lost in this target (measure pinned to total row 'A00'); the custom compiler switches to member rows when grouped
- qwi_avg_monthly_earnings: industry pinned to '6113' in this target; other values need a separate metric (the custom compiler allows an explicit filter)
- qwi_avg_monthly_earnings: ownership pinned to 'A00' in this target; other values need a separate metric (the custom compiler allows an explicit filter)
- ai_task_usage_pct: rule 'release must be chosen' (Percentages are only comparable within one release; summing releases is meaningless.) cannot be enforced in a single aggregate; carried only as comment/instructions. Summing across it is possible here.
- entity qcew: logical SQL view must be created in Unity Catalog first (dialect not executed here)
- relationship aei_task_text (many_to_many) intentionally omitted: Task text is not unique across occupations (and AEI lower-cases it); joining would fan out usage percentages. Blocked.
- relationship sucss_onet_candidate (many_to_many) intentionally omitted: Mappings are unreviewed lexical suggestions (sucss_onet_candidate); not an approved join.
