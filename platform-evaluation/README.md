# Illinois Higher Education Workforce Analytics — practice-run starter

Start with [the research and pilot plan](RESEARCH_AND_PILOT_PLAN.md). It covers sources, joins, higher education context, job posting methods, AI task transformation and a common Databricks/Snowflake/custom evaluation.

The approved evaluation direction is now captured in [rubric v1.0](PLATFORM_EVALUATION_RUBRIC.md). Use [benchmark v1.0](benchmark/README.md) for synthetic ERP edge cases, reference SQL/answer keys, AI evaluation cases and six blank implementation scorecards. Reference validation is separate from platform grading.

For the first-unit engineering workflow, see [org-chart and roster intake](DATA_INTAKE.md). Run `python scripts/workforce_store.py` to initialize the local evidence store using real public reference data. Org charts, directory records, appointments, descriptions and postings are stored as separate dated observations; missing identities and conflicting titles remain visible.

For the fictional higher education IT showcase, see [the synthetic demo and agent design](SYNTHETIC_DEMO_AND_AGENT_DESIGN.md). Generate it with `python scripts/build_synthetic_demo.py`, then `python scripts/build_demo_explorer.py`. Open `output/demo/role-evolution.html` for an offline explorer. Its histories and recommendations are invented test cases, not real workforce findings or live AI-agent responses.

## Run locally

```powershell
python scripts/prepare_pilot.py
```

Python 3.12 was used; no third-party dependencies are required. The script reads the already acquired files in `data/raw`, preserves raw inputs, and regenerates `data/prepared`. It does not fetch fresh data. The title similarity calculation may take a minute.

Outputs: `occupations.jsonl`, `classes.jsonl`, `mapping_review_queue.jsonl`, and `manifest.json`. All suggestions are unreviewed; the numeric score is a lexical similarity, not mapping confidence or an AI risk score.

The SUCSS class code 1164 has two source records with different titles. Both remain separate pending status/effective-date review. Do not count catalog records as employees or vacancies.

## Practice in Databricks

1. Open a Databricks workspace with serverless notebook access. Free Edition is sufficient to attempt this small reference-data exercise, subject to its current account limits.
2. In Catalog Explorer, choose an existing catalog/schema where you have permission and create or use a Volume. Upload the three prepared `.jsonl` files to a folder named `prepared` inside it.
3. Import `notebooks/01_databricks_reference_pilot.py` as a Python notebook.
4. Replace `VOLUME_PATH` with `/Volumes/<catalog>/<schema>/<volume>/prepared`.
5. Run the cells. Compare counts with `data/prepared/manifest.json`. Review title candidates alongside occupation descriptions and inspect ambiguous matches.
6. Collect individual SUCSS duties and approve mappings before joining BLS facts. The final commented cell illustrates optional Delta persistence in a dedicated pilot schema.

This exercise shows ingestion, SQL joins and a review queue. No Databricks account was accessed or created here. The notebook was syntax-checked locally but not executed on Spark. Snowflake replay and the full descriptive dashboard are subsequent work in the plan, not implemented components.

## Data attribution and provenance

O*NET 31.0 Database, U.S. Department of Labor, Employment and Training Administration: [source](https://www.onetcenter.org/database.html), [license and exceptions](https://www.onetcenter.org/license_db.html), [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). O*NET is a trademark of USDOL/ETA. Raw occupation data is unmodified; prepared JSONL reformats it and the review queue adds our candidate mappings, which are not endorsed or tested by USDOL/ETA.

SUCSS: [public classification catalog](https://www.sucss.illinois.gov/pages/classspec/Default.aspx). The JSON response was obtained from the same read-only ShowAll request used by that page. Source record IDs are preserved. Review source terms before republishing raw material.

Acquired October 29, 2026. The manifest records URLs, request body, hashes, counts and limitations. BLS direct download returned HTTP 403; BLS data, individual SUCSS specs, IPEDS and HigherEdJobs postings remain pending. Read the plan for source-specific paths and access dependencies.


## Downloadable synthetic workforce samples

The [sample datasets](sample_datasets/README.md) provide complete clean, deliberately defective and longitudinal synthetic histories, with a ZIP download, typed files, DuckDB databases, validation reports and reproducibility instructions. Read the [sample design](sample_datasets/SAMPLE_DESIGN.md) before interpreting results. No EDW calibration is claimed.
