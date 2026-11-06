# AI use-case registry and reuse library (prototype)

Solution #9 in the [SP&P opportunity brief](../research/IHR_STRATEGIC_PROGRAMS_OPPORTUNITY_BRIEF.md). It gives the Joint Innovation in AI Team (JIAT) one place to take a prototype from an AI Professional Development cohort, triage its risk, review it, pilot it against a timed baseline, and package it for other units. It also shows the time returned, as a range, without inflating it.

**Everything in `data/` and on the page is synthetic.** The 64 use cases, the units, the timings and the adoption events are invented. Unit names are generic and describe no real office. No university data was used. The rules are a design proposal, not university policy.

Open `../output/ai_usecases/registry.html`. It is one offline file: no network requests, light and dark themes, usable on a phone.

## Run

From `platform-evaluation/` (Python 3.13 standard library plus `duckdb`; Node is optional and only used by the parity test):

```bash
python ai_usecases/build_registry.py     # specs -> 64 entries -> triage -> checks -> ROI -> DuckDB rollups -> data/*.json
python ai_usecases/build_page.py         # -> output/ai_usecases/registry.html
python -m unittest discover -s ai_usecases/tests -v
```

`build_registry.py` exits non-zero if any entry fails the schema, the data contract, the stored-triage check or a lifecycle gate.

| File | Role |
|---|---|
| `schema/usecase.schema.json` | Intake schema (structure). JSON Schema 2020-12, restricted to a keyword subset both validators implement |
| `DATA_CONTRACT.md` | Grain, owners, quality rules, versioning, lifecycle and OMB inventory crosswalk |
| `triage_rules.yaml` | Policy: 17 triage rules, 8 review paths, tier labels, lifecycle transitions and 5 gates |
| `roi_assumptions.yaml` | Every ROI parameter, each a stated assumption |
| `registry_lib.py` | YAML-subset loader, schema validator, contract checks, triage, lifecycle, ROI (stdlib only) |
| `registry_core.js` | The same logic in JavaScript for the page; the tests check that both give identical results |
| `seed_catalog.py` | Hand-written fictional use cases across HR, finance, advising, IT and research administration |
| `build_registry.py` | Seeded generator (seed `20261106`) and DuckDB rollups (reuse matrix, unit links, ROI by domain) |
| `build_page.py`, `page_template.html` | Offline page builder and template |
| `tests/test_ai_usecases.py` | 68 unittest cases |

PyYAML is not needed. The rules file uses a small YAML subset that `registry_lib.load_yaml_subset` reads, and a test checks it parses identically under PyYAML when PyYAML is installed.

## Workflow

```text
 cohort prototype ──► intake (form / TDX request) ──► triage (rules, automatic)
                                                     │ tier 1–4, review paths, blocks
                                                     ▼
            rejected ◄── review paths sign off ──► approved_pilot ──► piloting (timed baseline vs pilot)
                                                                       │ evaluation + time-saved estimate
                                                                       ▼
                         retired ◄── paused ◄────────────────────── production ──► reusable_library
                                                                       │                │
                                                                       └── adoption events from other units ──► reuse map, reuse ROI
```

1. **Intake.** The schema asks for the problem in the unit's words, the single process step the AI touches, the approved tool, the highest data class it sees, the human-in-the-loop pattern, who is affected, whether the use touches an employment decision (Illinois HB 3773), and how time saved will be measured.
2. **Triage** is deterministic. Every matching rule fires: tier = highest tier fired, review paths = union, blocked = any blocking rule. Rule order does not matter, and a test shuffles the rules to prove it. Stored results are rechecked on every build, so a rule change cannot leave stale tiers.
3. **Review paths:**
   - self-certify
   - JIAT peer review
   - security and privacy
   - data steward
   - accessibility (IITAA)
   - student records (FERPA)
   - employment AI review (Counsel, OAE, Illinois HR)
   - tool procurement
4. **Gates:**
   - G1: no blocked entry may enter pilot or later.
   - G2: every required review must be complete.
   - G3: production needs a real evaluation and a time-saved estimate.
   - G4: Tier 3+ production needs 30+ test cases and logged human overrides.
   - G5: the reusable library needs evidence on file and a maintenance owner, and excludes Tier 4. Every unit that wants to reuse an employment-decision tool repeats the employment review.

### Tiers and blocks

| Tier | Triggered by (any of) | Paths added |
|---|---|---|
| 1 Low | Default | Self-certify |
| 2 Moderate | Campus- or public-facing output; human samples outputs; 5,000+ people affected | JIAT peer review; accessibility when output is campus/public |
| 3 High | Sensitive data; student records; consequential non-employment decision; AI acts before a human sees output; applicants affected but not flagged | Security & privacy, data steward, student records, employment scope check |
| 4 Restricted | Employment decision under HB 3773 | Employment AI review, data steward, JIAT; controls: notice, adverse-impact monitoring plan, human decision logged |

**Blocked**, whatever the tier, until the input changes:
- an employment or consequential decision without human review of every output;
- a zip-code or other protected-class proxy;
- a tool not on the approved list;
- Sensitive data on a tool not approved for Sensitive data (for example, Illinois Chat hosted models; only its local models are approved);
- PII labelled Public.

## Governance mapping

| Practice (source) | Where it lives here |
|---|---|
| NIST AI RMF GOVERN 1.6: mechanisms to inventory AI systems | The registry itself; every entry is triaged (rule T00) |
| NIST AI RMF MAP: context, affected people, scale | `affected_people`, `process`, `consequential_decision`; rules T08, T14 |
| NIST AI RMF MEASURE: test and monitor | `evaluation`, override logging, gates G3/G4, review cadence |
| NIST AI RMF MANAGE: human oversight, fallback, deactivation | `human_in_the_loop.pattern` and `fallback_process`; rules T07, T09, T12 |
| OMB M-25-21 high-impact AI and minimum practices (pre-deployment testing, impact assessment, human oversight, monitoring, remedy) | Tier 3–4 paths, gate G4, T08 control (human reconsideration). The 2025 inventory classes (high-impact / presumed but determined not / not) correspond to Tier 4 + Tier 3 consequential / flagged-then-cleared by employment review / everything else |
| OMB 2024 inventory data dictionary (54 fields) | Crosswalk in `DATA_CONTRACT.md`; lifecycle mapped to `16_dev_stage` |
| California SIMM 5305-F (Low/Moderate/High; Part 2 only for Moderate/High) | Tier 1 self-certifies; Tier 2+ adds reviews |
| Maryland DoIT intake (default to the higher category when unsure) | HB 3773 flag guidance ("flag if unsure"); T15 escalates applicant-facing uses that were not flagged |
| Oregon EIS screen (public-facing, regulated data, rights-impacting) | T11, T01/T10, T05/T08 |
| WaTech (reuse existing security and privacy assessments) | `security_privacy_review` reuses the existing campus security review rather than inventing one |
| EDUCAUSE GenAI Readiness Assessment (stakeholders evaluate and approve use cases; decisions communicated) | Review paths name the deciding office; rejected entries are kept with reasons |
| Illinois HB 3773 (notice; discriminatory effect; zip-code proxy) | `employment_decision`; T05, T06, T07, T15; gate G5 |
| UIUC approved tools and data classes | `tool.approved_tool`, `data.classification`; T02, T03 |
| IITAA / U of I EIT accessibility | `accessibility_review` path (T11) |

## ROI model (and why the headline is a wide range)

- **Per instance.** Minutes saved = baseline mean − pilot mean, with a 90% Welch interval. The pilot time includes the human review. The low end may be negative: in the synthetic data, four timed use cases have a slowdown inside their range, and the retired spreadsheet helper was slower on average.
- **Self-reports are upper bounds.** Range is 0 to the reported figure, middle = half of it. They never enter a total. In a 2025 randomized trial, developers believed AI made them 20% faster while measured time rose 19% ([METR, arXiv 2507.09089](https://arxiv.org/abs/2507.09089)).
- **Origin unit.** 50% of annual volume while piloting, 100% in production or the library. Earlier stages count nothing; they are shown separately as "potential".
- **Adoption-weighted reuse.** Each adopting unit's latest event is weighted: pilot 0.25, adapted 0.75, adopted 1.0. A 0.5–1.0 transfer discount applies because savings were not re-measured in the adopting unit. Units that retired a solution stop counting.
- **Costs** (first year), subtracted from gross:
  - review hours by tier
  - build hours by artifact type
  - 12 months of maintenance
  - onboarding hours per adopting unit
- **Portfolio.** The headline sums every entry's low ends and high ends. That assumes all estimates err in the same direction at once, so the range is deliberately wide. A root-sum-square "independent errors" range is shown second and labelled as an approximation.
- **Hours, not cash.** Hours are capacity returned to the work. They are not a budget cut and say nothing about positions. A dollar figure is shown only at a placeholder loaded rate.

Synthetic result (seed 20261106): 40 of 43 timed use cases are realized (piloting or later).

| Measure | Low | Middle | High |
|---|---:|---:|---:|
| Measured net hours/year, conservative | −746 | 4,862 | 13,204 |
| Same, assuming independent errors | 3,590 | 4,862 | 6,872 |

The middle estimate splits into origin units 4,425 h/yr and reuse in other units 2,448 h/yr, less costs of 2,010 h. The self-reported pipeline is 0 to 2,848 h/yr and is not counted.

The numbers are fictional. What carries over to real data is the arithmetic and the discipline: no total without a timed baseline, every number a range, costs subtracted.

## Synthetic registry at a glance

**Entries:** 64 across five domains:

| Domain | Entries |
|---|---:|
| HR | 15 |
| Finance | 13 |
| Advising | 12 |
| IT | 12 |
| Research administration | 12 |

**Tiers:**

| Tier | Entries | Blocked |
|---|---:|---:|
| 1 | 22 | 0 |
| 2 | 20 | 0 |
| 3 | 16 | 5 |
| 4 | 6 | 1 |

**Lifecycle stages:**

| Stage | Entries |
|---|---:|
| Submitted | 4 |
| Triaged | 4 |
| In review | 6 |
| Approved for pilot | 4 |
| Piloting | 10 |
| Production | 20 |
| Reusable library | 10 |
| Paused | 2 |
| Retired | 1 |
| Rejected | 3 |

**Adoptions:** 64 active adoptions by other units, 23 of them across domains.

Deliberate negative examples:
- applicant ranking with after-the-fact audit (blocked, rejected);
- scholarship essay pre-screen with sampling (blocked, rejected);
- advising notes on Illinois Chat hosted models (blocked: Sensitive data);
- a third-party meeting plug-in (blocked: tool not approved);
- payee bank details pasted into a public AI site and labelled Public (blocked twice);
- export-control "cleared" determinations audited afterwards (blocked).

## Integration on campus

The registry is a data model plus rules, so it can sit on tools the campus already runs. The integration below is a design; none of it was tested against the real systems.

- **TeamDynamix (TDX).** Intake as a TDX service request form whose fields map to the schema. TDX holds the conversation and the review tasks. One task is created per review path that triage returns, and the "review complete" status writes to `risk.reviews_completed`. A nightly job (TDX Web API → JSON) runs `check_record` and the triage engine and posts the tier and paths back to the ticket. TDX has no field for a Welch interval, an adoption-weighted reuse value or a rules version, and that is the part this module adds.
- **Box.** Evaluation evidence (test sets, timing sheets, the configuration that would be reused) sits in a per-entry folder such as `JIAT Registry/UC-0000/evaluation/`. Box keeps that folder's access controls, and the registry stores only the path (`evaluation.evidence_location`). Sensitive test material stays in folders approved for it.
- **SharePoint / Microsoft 365.** The reusable library can be published as a SharePoint list or page per Tier 1–3 entry (configuration, prompt, failure modes, owner). Copilot Chat users can then find and reuse it inside the tenant where most of these tools run. Adoption is recorded when a unit clones the template, as a form submission that appends an `adoption_events` row.
- **Reporting.** `data/registry.json` and the DuckDB rollups are small. They load directly into Tableau or Power BI, or into the AI Adoption Impact Scorecard (solution #1) at unit and cohort level, joined on `origin.cohort`.
- **Public inventory.** If the System publishes an AI inventory, the OMB crosswalk in `DATA_CONTRACT.md` produces it. Internal-only fields such as evidence paths are dropped.

## Why the platforms do not provide this

- **Snowflake and Databricks** store and compute. Neither has a use-case intake, a risk-triage policy, a lifecycle with gates, or an ROI model with baselines and uncertainty. Their AI governance features (model registries, lineage, access policies) govern models and data, not a staff member's Copilot prompt template that never touches the platform.
- **ChatGPT EDU, Copilot Chat and Illinois Chat** run the tools but do not record:
  - which process step a prompt serves;
  - who reviewed it;
  - whether it is allowed for an employment decision;
  - how much time it saved, measured against a baseline.
- **TeamDynamix** routes tickets and tasks but has no rules engine for AI risk tiers and no ROI arithmetic.
- **Commercial AI governance products** (model inventories, risk registers) are built for organizations that train and deploy models. They do not model a cohort-to-library pipeline across units, the UIUC approved-tool and data-class matrix, or HB 3773 routing. Where one is procured later, this schema and these rules are the requirements to configure it against.

## Limitations

- **Synthetic data.** The data is synthetic and the rules are untested with real reviewers.
- **Tier and review boundaries.** These are judgement calls to calibrate with Counsel, OAE, the security office and the GenAI Solutions Hub.
- **HB 3773 scope.** The flag is self-reported and conservative. The IDHR notice rules were not final as of this research, so the notice controls are placeholders.
- **The validator is not full JSON Schema.** It covers only the keywords this schema uses: no `oneOf`, `anyOf`, remote `$ref` or format other than `date`. Both validators raise on unknown references and agree on every fixture tested.
- **Source quality.** Sources were read through search results. The one exception is the OMB 2024 data dictionary, which was downloaded and read. The M-25-21 details come from an agency compliance plan and commentary, not the memo text. Confirm all of them on the live pages.
- **Adopter savings are not re-measured.** The transfer discount stands in for that until adopting units time their own pilots.

## Sources

- NIST AI Risk Management Framework 1.0, GOVERN 1.6 (inventory) and the MAP, MEASURE and MANAGE functions: https://www.nist.gov/itl/ai-risk-management-framework
- OMB 2024 Federal AI Use Case Inventory and its data dictionary (`validation/data_dictionary.yaml`): https://github.com/ombegov/2024-Federal-AI-Use-Case-Inventory
- OMB M-25-21, as described in the OPM AI compliance plan: https://www.opm.gov/ai/references/opm-ai-compliance-plan.pdf. Commentary on the minimum practices: https://natlawreview.com/article/omb-issues-revised-policies-ai-use-and-procurement-federal-agencies
- California CDT SIMM 5305-F GenAI Risk Assessment: https://cdt.ca.gov/wp-content/uploads/2025/08/SIMM-5305-F-Generative-Artificial-Intelligence-Risk-Assessment-20250822FINAL.pdf
- Maryland DoIT, request software or technology (risk-based AI intake): https://ai.maryland.gov/state-employee-guidance/request-software-or-technology
- Oregon EIS AI Risk Management Framework: https://www.oregon.gov/eis/Documents/Attachment-B-AI-Risk-Management-Framework.pdf
- WaTech, Navigating AI risk: https://watech.wa.gov/sites/default/files/2025-07/Navigating%20AI%20risk%20p2.pdf
- NCDIT AI assessments: https://it.nc.gov/resources/artificial-intelligence/ai-assessments
- Georgia Innovation Lab use-case intake form: https://ai.georgia.gov/document/document/innovation-lab-use-case-intake-form/download
- EDUCAUSE Higher Education Generative AI Readiness Assessment (fill-in copy): https://ctli.vermontstate.edu/wp-content/uploads/2024/08/HigherEdGenAIReadinessFillIn.pdf
- EDUCAUSE Library, generative AI topic (2025 AI Landscape Study, Horizon Action Plan): https://library.educause.edu/topics/infrastructure-and-research-technologies/generative-ai
- Illinois HB 3773 summary: https://www.ebglaw.com/workforce-bulletin/illinois-prohibits-discriminatory-artificial-intelligence-in-employment-decisions
- UIUC GenAI approved tools: https://genai.illinois.edu/ai-apps/ (see also `../research/UIUC_HR_AND_AI_TOOL_LANDSCAPE.md`)
- METR (2025), randomized trial of AI tools and developer time: https://arxiv.org/abs/2507.09089
