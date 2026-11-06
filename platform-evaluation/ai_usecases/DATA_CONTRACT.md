# Data contract: AI use-case registry entry v1.0

| | |
|---|---|
| **Producer** | Intake form (offline page or a TeamDynamix request), then the JIAT registry steward |
| **Consumers** | JIAT reviewers, unit owners, the AI Adoption Impact Scorecard (unit/cohort level), any OMB-style public inventory |
| **Grain** | One row per use case: one process step, one tool configuration, one owning unit. A use case that touches several steps is split |
| **Key** | `id` (`UC-0000`), assigned at intake and never reused. Adoption by another unit is an event on the same entry, not a new entry. A substantially changed fork becomes a new entry with a `forked_adapted` event on the original |
| **Structure** | [`schema/usecase.schema.json`](schema/usecase.schema.json) (JSON Schema 2020-12 keyword subset) |
| **Policy** | [`triage_rules.yaml`](triage_rules.yaml) (tier, review paths, blocks, lifecycle gates) and [`roi_assumptions.yaml`](roi_assumptions.yaml). Both are versioned separately from the schema |
| **Classification of the registry itself** | Internal. Entries describe processes, tools and aggregate timings. They must not contain the data the tool processes, people's names, or individual productivity |

## Field groups

| Group | Required content | Who writes it | Quality rule |
|---|---|---|---|
| `title`, `problem_statement`, `proposed_solution` | Problem in the unit's words; what the AI does and what the human still does | Submitter | 30–1,200 characters; problem describes work, not a tool |
| `domain`, `unit`, `owner_role` | Owning unit and an accountable **role** | Submitter | Role titles only, so entries survive staff changes |
| `process` | Process, frequency, the single step augmented | Submitter | One step per entry |
| `origin` | Program (`AI PD Intermediate cohort`, `AI PD leader track`, `JIAT sprint`, `Unit-initiated`) and cohort code | Submitter | Cohort pattern `YYYY-Term-Cn`; links to the AI Adoption Impact Scorecard at cohort level |
| `tool` | Approved tool, artifact type, configuration another unit could rebuild | Submitter | Tool from the approved list, or `Other (not on approved list)`, which blocks |
| `data` | Highest data class the tool sees (Public / Internal / Sensitive), PII flag, sources | Submitter, confirmed by the data steward when required | PII cannot be labelled Public (rule T04) |
| `human_in_the_loop` | Pattern, reviewer role, review point, whether overrides are logged, manual fallback | Submitter | Tier 3+ production requires `override_logged = true` (gate G4) |
| `affected_people` | Groups, scale band, output audience | Submitter | Campus- or public-facing output adds accessibility review |
| `employment_decision` | HB 3773 flag, decision types, notice plan, zip-code/proxy flag | Submitter; employment AI review confirms scope | If flagged: ≥1 decision type and a notice plan (schema `if/then`). Decision types without the flag are rejected |
| `consequential_decision` | Non-employment decisions with material effect on a person | Submitter | Description required when flagged |
| `risk` | Tier, review paths, blocked, reasons, rules version; `reviews_completed` | **Triage engine only**; reviewers append to `reviews_completed` | Re-computed on every build; a stale block fails the build |
| `evaluation` | Method, test cases, observed correction rate, failure modes, evidence location, date | Owner, checked by JIAT | `none_yet` cannot carry results. Evidence is a Box/SharePoint pointer, never the data |
| `time_saved` | Method; timed baseline and pilot (n ≥ 5, mean, SD; pilot includes human review) or a self-reported figure; annual volume range | Owner | Timed method requires both timings; only timed evidence counts in ROI totals |
| `maintenance` | Owner role, hours per month range, review cadence | Owner | Library entries need a maintenance owner with at least 0.5 h/month at the high end (gate G5) |
| `adoption_events` | Date, unit, domain, event (`pilot_started`, `adopted`, `forked_adapted`, `retired_by_unit`), volume range | Adopting unit, recorded by the steward | Volume required except for retirement; the origin unit cannot adopt its own entry; dates on or after submission |
| `status` | Current stage and the full history (stage, date, role) | Steward | Starts at `submitted` on `submitted_on`; dates non-decreasing; last history stage equals `stage`; every move allowed by `lifecycle.transitions` |

Range fields (`{low, high}`) require `low ≤ high`. Dates are ISO `YYYY-MM-DD`. These cross-field rules are in `contract_checks()` (Python) and `contractChecks()` (JS).

## Lifecycle and the federal inventory stages

| Registry stage | OMB inventory SDLC stage (2024 data dictionary, field `16_dev_stage`) |
|---|---|
| submitted, triaged, in_review | Initiated |
| approved_pilot | Acquisition and/or Development |
| piloting | Implementation and Assessment |
| production, reusable_library | Operation and Maintenance |
| retired | Retired |
| paused, rejected | No equivalent (paused keeps its last stage for reporting; rejected is not reported) |

## Crosswalk to the OMB AI use case inventory

The [2024 Federal AI Use Case Inventory data dictionary](https://github.com/ombegov/2024-Federal-AI-Use-Case-Inventory) is the most detailed public template for inventory fields. The registry covers its intent at campus scale:

| OMB field (2024) | Registry field |
|---|---|
| `2_use_case_name`, `4_bureau` | `title`, `unit` |
| `10_commercial_ai` | `tool.approved_tool` |
| `11_purpose_benefits` | `problem_statement`, `proposed_solution`, `time_saved` |
| `12_outputs` | `proposed_solution`, `affected_people.output_audience` |
| `16_dev_stage`, `18`–`21` dates | `status.stage`, `status.history` |
| `17_impact_type` (2025: high-impact determination) | `risk.tier`, `employment_decision`, `consequential_decision` |
| `29_contains_pii`, `30_saop_review` | `data.contains_pii`, `security_privacy_review` path |
| `33_agency_data`, `34_data_docs` | `data.sources`, `evaluation.evidence_location` |
| `49_existing_reuse` | `adoption_events`, reusable_library stage |
| `52_impact_assessment`, `53_real_world_testing`, `55_independent_eval` | review paths, `evaluation.method = pilot_with_baseline`, `jiat_peer_review` |
| `54_key_risks` | `evaluation.known_failure_modes`, `risk.reasons` |
| `56_monitor_postdeploy` | `human_in_the_loop.override_logged`, `maintenance.review_cadence` |
| `59_ai_notice` | `employment_decision.notice_plan` |
| `65_appeal_process` | `human_in_the_loop.fallback_process`; T08 control "ask for human reconsideration" |

Not carried over: contract PIIDs, ATO, compute provisioning and HISP fields, which do not apply to approved enterprise tools.

## Versioning

- **Schema** (`schema_version`): additive optional fields are a minor change; anything that makes a valid entry invalid is a major change with a migration script.
- **Triage rules** (`version` in `triage_rules.yaml`): any change bumps the version. The build re-triages every entry, and `check_record` reports `$.risk: stale` until it does. `reviews_completed` keeps only paths that are still required, so a newly required review shows as open.
- **ROI assumptions** (`version` in `roi_assumptions.yaml`): reported totals always name the assumption version.

## Retention and access

Entries are kept for the life of the solution plus the records schedule that applies to the unit's process. Rejected entries are kept, because they record why something was not done. Evidence files stay in the owning unit's Box or SharePoint folder under that folder's access controls; the registry holds only the path.
