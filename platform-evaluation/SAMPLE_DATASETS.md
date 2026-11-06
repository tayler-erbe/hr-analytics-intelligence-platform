# Workforce sample datasets

The ESGC proposal requirements and the existing generator contracts were used to assemble three synthetic sample sets. No EDW connection or real employee extract was used. The source documents remain in the ignored local review folder and are not included in the sample archive.

## Open the samples

Validated archive: `data/local/esgc_sample_pack_v1_validated.zip`.

Expanded folder: `data/local/esgc_sample_pack_v1`.

| Set | Purpose | Contents |
|---|---|---|
| quality/CLEAN | Validate joins, reporting and conversion checks on coherent records | 1,500 fictional people; employment, appointment, position, payroll and reference tables |
| quality/DEFECTS | Test detection of known quality failures | Same seeded starting world with deliberate defects and an injection manifest |
| longitudinal | Develop and test transitions, vacancy and temporal extraction | 2,302 fictional people in the person table, 36,699 job-history rows, employment/separation/position history and role-family references |

Across the three sets there are 28 typed source tables. Each is available as Parquet and JSONL and loaded into a per-set `sample.duckdb`. The longitudinal database also contains a synthetic current-employment view named `V_EMPEE_HIST_1`. This is a local derived view, not a verified definition of the real EDW view. Keep populations separate; matching synthetic IDs across the three worlds do not establish a join.

Each set includes a schema with explicitly assumed physical field names. Begin with `inventory.json`, `scope_and_assumptions.json` and `generation_summary.json` at the pack root. `truth.json` describes the longitudinal generator's planted parameters. `validation/pack_validation.json` records the checks actually run.

## Validation performed

- CLEAN: zero failing rules across 43 quality checks.
- DEFECTS: all 43 rules fail as planted; failures are expected test results, not errors to hide.
- Longitudinal extract: seven extraction gates pass; a separate informational measure records late-keyed rows.
- All 28 source tables have matching row counts in Parquet, JSONL and DuckDB.
- Clean job records resolve to fictional person records; all 1,500 clean people are accounted for.

No promotion, attrition or readiness model was trained as part of packaging these samples. Passing these checks validates the synthetic package's compatibility with the tested local pipeline, not model accuracy on university data or a vendor benchmark score.

## Assumptions still to replace with verified metadata

The table/column layouts follow the current repository's synthetic EDW contracts. Code domains, pay ranges, organizational relationships, retirement assumptions and behavior probabilities are invented. Effective-end dates are inclusive in these generators; recorded-version end dates are exclusive. These conventions must be confirmed rather than silently imposed on actual EDW sources.

The samples include demographic attributes only because the existing generators have a synthetic fairness-audit fixture. They are not evidence about the real workforce and are not an instruction to use them in individual predictions. Skills, learning records, JDX descriptions and actual promotion decisions are not observed in these samples. A role transition is not automatically an HR-confirmed promotion.

Do not require synthetic and real models to reach the same conclusions. Future calibration should separately measure fidelity, downstream utility, temporal validity and disclosure risk on an approved environment. The current package supplies scenario and structural ground truth only.

## Reproduce

The source checkout is the inspected branch `claude/compassionate-thompson-ywgtcm` of `tayler-erbe/hr-analytics-intelligence-platform`; the pack records the exact source commit. The wrapper reuses its `erp_readiness` and `succession_models` generators without modifying them. It does not acquire credentials, query EDW or include private proposal documents.

Using Python with numpy, pandas, pyarrow, duckdb and pyyaml available:

```powershell
python scripts/build_esgc_sample_pack.py --source-root <checkout>/platform-evaluation --out data/local/my_sample_pack --dependency-dir <optional-local-packages>
python scripts/validate_esgc_sample_pack.py --source-root <checkout>/platform-evaluation --pack data/local/my_sample_pack --dependency-dir <optional-local-packages>
```

Choose a new output directory for a new build. Full defect injection requires the documented 1,500-person baseline; an initial 250-person attempt failed because too few examples existed for one injected defect. That partial attempt is retained locally as incomplete and is not the delivered validated archive.

For this machine, the bundled Python runtime and isolated dependencies under `data/local/sample-python` were used. Original generated samples and dependency files remain excluded from Git. The reviewed publication copy is organized under `platform-evaluation/sample_datasets/v1` in the GitHub repository, with a ZIP download and supporting documentation. Internal source documents and detailed historical schema findings remain local.
