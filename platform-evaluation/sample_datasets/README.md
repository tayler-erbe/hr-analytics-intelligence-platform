# Synthetic workforce sample datasets

This folder contains an inspectable sample-data package for workforce analytics development. All employee records, histories, compensation, organizational assignments and demographic values are invented. Public SUCSS labels supply reference vocabulary. No EDW connection or real employee extract was used, and the package is not statistically calibrated to EDW.

Download [the complete ZIP](workforce_samples_v1.zip), or browse [the expanded files](v1/). The ZIP expands into `v1/`. Its SHA-256 is `191d4b9a30711f2db7304e28f06b7e434ec47169ebdc27bce90e2ebc8c639615`.

## Which set to use

| Set | Use | Scope |
|---|---|---|
| [quality/CLEAN](v1/quality/CLEAN/) | Join validation, reporting, extraction and quality checks | 1,500 distinct synthetic people, with employment, job, payroll, position and reference history |
| [quality/DEFECTS](v1/quality/DEFECTS/) | Check that known problems are detected | Same seeded starting world with explicit defect injections |
| [longitudinal](v1/longitudinal/) | Effective-dated history, transitions, separations and late-recorded corrections | 2,302 distinct synthetic people; 36,699 job-history rows |

The sets are separate worlds. Do not join people between them just because generated IDs match. A history table can contain more rows than people. The 1,500-person CLEAN set has 1,951 person-history rows; DEFECTS deliberately changes some counts.

There are 28 source tables across the three sets. Each is provided as typed Parquet and JSONL and loaded into a per-set `sample.duckdb`. The longitudinal database also defines a synthetic `V_EMPEE_HIST_1` current-effective employment view; active-employment interpretation still requires an explicit status filter and business definition.

## Start here

- [Inventory](v1/inventory.json): tables and row counts.
- [Scope and assumptions](v1/scope_and_assumptions.json): included concepts and unresolved definitions.
- [Generation summary](v1/generation_summary.json): seed, generator commit and planted events.
- [Schema assumptions](v1/longitudinal/schema_assumptions.json): synthetic field names/types; not a verified EDW dictionary.
- [Starter SQL](v1/sample_queries.sql): read-only DuckDB queries for the longitudinal database.
- [Validation report](v1/validation/pack_validation.json): results actually obtained.
- [File manifest](v1/pack_manifest.json): file-level hashes and publication changes.
- [Sample design and limitations](SAMPLE_DESIGN.md): interpretation and next calibration work.

## What passed

The existing upstream quality suite reported zero failing rules on CLEAN and all 43 rules failing on DEFECTS, as planted. Seven longitudinal extraction gates passed. All 28 source tables had matching row counts in Parquet, JSONL and DuckDB. Clean job records resolved to synthetic person records. Starter queries and ZIP integrity were checked.

These results establish the tested local sample pipeline's behavior. No promotion/readiness model was trained in this packaging task, no vendor benchmark grade was earned, and no real-data validity is claimed. The term `protected` in a generated extract identifies a synthetic audit fixture, not actual restricted records.

## Reproduce the samples

The generators live at pinned upstream commit `e8d541420594ef39d0b97d6b9aa0fb19e86e9420`. They are reused rather than copied into a second implementation. Use a separate checkout for those dependencies:

```powershell
git clone --branch claude/compassionate-thompson-ywgtcm https://github.com/tayler-erbe/hr-analytics-intelligence-platform.git generator-source
git -C generator-source checkout e8d541420594ef39d0b97d6b9aa0fb19e86e9420
```

Install `numpy`, `pandas`, `pyarrow`, `duckdb` and `pyyaml` into an isolated Python environment. From `platform-evaluation/` in the publication checkout:

```powershell
python scripts/build_esgc_sample_pack.py --source-root generator-source/platform-evaluation --out data/local/rebuilt_samples
python scripts/validate_esgc_sample_pack.py --source-root generator-source/platform-evaluation --pack data/local/rebuilt_samples
```

Adjust `--source-root` to where the separate checkout was actually created. The default seed is 20261106, quality population 1500, longitudinal scale 0.2. A first 250-person attempt lacked enough candidates for the complete defect suite; it is not included. Use a fresh output path to preserve prior runs. The source generators produce Parquet; wrappers add JSONL, DuckDB, provenance, validation and ZIP packaging.

The wrappers support `--dependency-dir` for isolated installed packages. Normal environments do not need it. Table contents are seeded, but file bytes can vary across library versions; file hashes identify this published build. Keep generated private/local files under `data/local/`. This explicit publication folder is the reviewed exception for synthetic assets, not permission to force-add ignored internal data.

## Publication boundaries

Included: generated synthetic rows, assumed schemas, synthetic reference tables, generator parameters, validation results, starter SQL and packaging source code. Two log/manifest paths were replaced with `WORKSPACE` for portability, and public-copy hashes were recalculated. Original source-table Parquet, JSONL and DuckDB files were preserved.

Excluded: original proposals, internal reference PDFs/Word files, org charts, notebook outputs, historical schema-evidence inventory and candidate mappings, authentication details and actual EDW profiles. Old reference documents revealed that some assumed field names differ; those source-derived bindings are not applied to this v1 package. It remains the original clearly labeled synthetic layout. An institution-approved document-aligned schema adapter can be developed separately.
