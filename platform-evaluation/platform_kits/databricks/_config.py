# Databricks notebook source
# MAGIC %md
# MAGIC # Shared configuration for the Databricks trial-run kit
# MAGIC
# MAGIC Every numbered notebook runs this file first with `%run ./_config`. Change values **here**, never inline,
# MAGIC so that a run can be traced back to one configuration.
# MAGIC
# MAGIC **Public data only.** This kit loads O*NET, IPEDS, QCEW, Census QWI and the SUCSS public class catalog,
# MAGIC plus the frozen *synthetic* benchmark fixtures (read-only). Do not upload institutional HR, payroll,
# MAGIC appointment, applicant or employee records to a Free Edition or trial workspace.
# MAGIC
# MAGIC **Protocol label.** Prompts, label sets, row caps and scoring rules below are frozen under `PROTOCOL`.
# MAGIC Do not edit them to improve a result. A change requires a new protocol label, and both runs must be kept.

# COMMAND ----------

import datetime as _dt
import uuid as _uuid

KIT_VERSION = "databricks_kit_v0.1"
PROTOCOL = "dbx-public-ai-protocol-v1"   # bump on ANY prompt / label / scoring / cap change

# ---- Unity Catalog locations -------------------------------------------------
# Free Edition: the default catalog is usually named `workspace` (verify in Catalog Explorer).
# A paid workspace can use a dedicated catalog such as `hr_eval`.
CATALOG = "workspace"
SCHEMA = "hr_public"                 # matches lake contract: catalog.hr_public
EVAL_SCHEMA = "hr_eval_results"      # results, scores and run logs
GOV_SCHEMA = "hr_gov_synthetic"      # synthetic governance tests (07)
PIPELINE_SCHEMA = "hr_public_pipeline"  # Lakeflow pipeline target (06), kept apart from 01 tables
VOLUME = "lake"                      # managed volume holding uploaded files

VOLUME_ROOT = f"/Volumes/{CATALOG}/{SCHEMA}/{VOLUME}"
SILVER_PATH = f"{VOLUME_ROOT}/silver"            # upload data/lake/contract/*.parquet here
BENCHMARK_PATH = f"{VOLUME_ROOT}/benchmark_v1"   # upload benchmark/fixtures/*.jsonl + manifest.json here
INJECT_PATH = f"{VOLUME_ROOT}/injected"          # deliberately bad rows for pipeline tests (06b)

FQ = lambda t: f"{CATALOG}.{SCHEMA}.{t}"
FQE = lambda t: f"{CATALOG}.{EVAL_SCHEMA}.{t}"
FQG = lambda t: f"{CATALOG}.{GOV_SCHEMA}.{t}"

# ---- Lake contract (lake/CONTRACT.md v1.0, reconciled 2026-11-06) --------------
# Table names are fixed by the contract. Non-key column names were NOT final when this kit was written;
# 01_load_lake prints a contract check. If it reports a mismatch, change the mapping below, not the notebooks.
LAKE_TABLES = [
    "onet_occupation", "onet_task_statement", "onet_task_rating", "onet_element_rating",
    "onet_technology_skill", "onet_alternate_title", "onet_job_zone",
    "sucss_class", "sucss_onet_candidate",
    "ipeds_institution", "ipeds_staff_by_occupation", "ipeds_instructional_staff", "ipeds_new_hires",
    "ipeds_salary_instructional", "ipeds_salary_noninstructional", "ipeds_employees_by_position",
    "ipeds_enrollment_12mo",
    "qcew_industry", "qcew_area", "qwi_higher_ed", "aei_task_usage",
    "aei_occupation_exposure", "onet_soc_crosswalk",
]
PENDING_TABLES = ["bls_oews", "bls_projections", "acs_county_labor"]   # not yet published (BLS needs a contact User-Agent; ACS needs a Census API key)

# Key columns stated in the contract (these are checked strictly).
CONTRACT_KEYS = {
    "onet_occupation": ["onetsoc_code"],
    "onet_task_statement": ["onetsoc_code", "task_id"],
    "onet_task_rating": ["onetsoc_code", "task_id", "scale_id"],
    "onet_element_rating": ["onetsoc_code", "domain", "element_id", "scale_id"],
    "onet_technology_skill": ["onetsoc_code", "example", "commodity_code"],
    "onet_alternate_title": ["onetsoc_code", "alternate_title"],
    "onet_job_zone": ["onetsoc_code"],
    "sucss_class": ["source_record_id"],
    "sucss_onet_candidate": ["source_record_id", "onetsoc_code"],
    "ipeds_institution": ["unitid"],
    "ipeds_staff_by_occupation": ["unitid", "survey_year"],
    "qcew_industry": ["area_fips", "own_code", "industry_code", "year", "qtr"],
    "qcew_area": ["area_fips", "own_code", "industry_code", "year", "qtr"],
    "aei_task_usage": ["task_name", "release"],
}
COMMON_COLS = ["source_id", "source_vintage"]   # contract: every table has these

# Assumed non-key columns (ASSUMPTION -> verify against 01 contract check output).
COL = {
    # O*NET
    "occ_title": "title", "occ_desc": "description",
    "task_text": "task", "task_type": "task_type",
    "element_name": "element_name", "element_value": "data_value",
    "tech_hot": "hot_technology",
    # SUCSS
    "class_code": "class_code", "class_title": "class_title", "occ_line": "occupational_line",
    "cand_rank": "candidate_rank", "cand_score": "title_similarity",
    # IPEDS
    "inst_name": "institution_name", "inst_state": "state_abbr", "inst_sector": "sector",
    "staff_occ": "occupation_category", "staff_count": "staff_count",
    "sal_occ": "occupation_category", "sal_staff": "staff_count", "sal_outlays": "total_salary_outlays",
    # QCEW (BLS CSV names, already snake_case)
    "qcew_emp": "month3_emplvl", "qcew_wage": "avg_wkly_wage", "qcew_estabs": "qtrly_estabs",
    "qcew_wages_total": "total_qtrly_wages", "qcew_area_title": "area_title",
    # Census QWI (API variable names lower-cased)
    "qwi_geo": "geography", "qwi_industry": "industry", "qwi_year": "year", "qwi_quarter": "quarter",
    "qwi_emp": "emp", "qwi_hires": "hira", "qwi_seps": "sep", "qwi_turnover": "turnovrs", "qwi_earn": "earns",
    "qwi_sex": "sex", "qwi_agegrp": "agegrp",
}

# ---- Model endpoints (names change; confirm on the Serving page) --------------
CHAT_ENDPOINT = "databricks-meta-llama-3-3-70b-instruct"   # verify in workspace; any pay-per-token chat model
EMBED_ENDPOINT = "databricks-gte-large-en"                   # 1024-d; verify (SQL docs also show system.ai.gte-large-en)
AGENT_ENDPOINT = CHAT_ENDPOINT                               # must support tool calling
AI_SEARCH_ENDPOINT = "hr-public-ai-search"                   # Free Edition allows ONE AI Search (Vector Search) endpoint

# ---- Cost caps (rows sent to AI services per run). Raising them is a protocol change. ----
CAP_CLASSIFY = 200        # SUCSS classes sent to ai_classify
CAP_EXTRACT = 150         # O*NET task statements sent to ai_extract
CAP_QUERY = 100           # O*NET task statements sent to ai_query (chat)
CAP_EMBED_CLASSES = 200   # SUCSS classes embedded
CAP_EMBED_OCC = 1100      # O*NET occupations embedded (whole O*NET 31.0 occupation list is ~1,000)
CAP_GENIE_QUESTIONS = 15
CAP_AGENT_CASES = 12
SAMPLE_SEED = 20261106    # deterministic sampling (ORDER BY xxhash64(key, seed))

# ---- Frozen prompts / label sets ---------------------------------------------
# SOC 2018 major groups: allows a deterministic comparison with the first two digits of O*NET-SOC codes.
SOC_MAJOR_GROUPS = {
    "11 Management": "Executives, managers and directors who plan and direct organizations or units",
    "13 Business and Financial Operations": "Accountants, auditors, HR specialists, buyers, analysts, compliance",
    "15 Computer and Mathematical": "Software, IT support, network, database, data science, statistics",
    "17 Architecture and Engineering": "Engineers, architects, drafters, engineering technicians",
    "19 Life, Physical, and Social Science": "Scientists, research technicians, laboratory science",
    "21 Community and Social Service": "Counselors, social workers, community health, clergy",
    "23 Legal": "Lawyers, paralegals, legal support",
    "25 Educational Instruction and Library": "Teachers, faculty, librarians, archivists, instructional coordinators",
    "27 Arts, Design, Entertainment, Sports, and Media": "Designers, writers, broadcast, photographers, public relations specialists",
    "29 Healthcare Practitioners and Technical": "Physicians, nurses, pharmacists, therapists, clinical technologists",
    "31 Healthcare Support": "Nursing assistants, medical assistants, therapy aides",
    "33 Protective Service": "Police, security guards, firefighters, correctional officers",
    "35 Food Preparation and Serving Related": "Cooks, food service workers, food service supervisors",
    "37 Building and Grounds Cleaning and Maintenance": "Custodians, housekeepers, groundskeepers, pest control",
    "39 Personal Care and Service": "Childcare, recreation workers, personal care aides",
    "41 Sales and Related": "Sales representatives, cashiers, retail",
    "43 Office and Administrative Support": "Clerks, secretaries, administrative assistants, office supervisors",
    "45 Farming, Fishing, and Forestry": "Agricultural workers, animal caretakers on farms, forestry",
    "47 Construction and Extraction": "Carpenters, electricians, plumbers, construction laborers",
    "49 Installation, Maintenance, and Repair": "Mechanics, maintenance workers, HVAC, repairers",
    "51 Production": "Machinists, printing, plant and system operators, water treatment",
    "53 Transportation and Material Moving": "Drivers, material movers, aircraft and vehicle operators",
    "55 Military Specific": "Military occupations",
}
CLASSIFY_INSTRUCTIONS = (
    "Classify an Illinois state civil service class title into the single best SOC 2018 major group. "
    "Use only the title text. If the title is too ambiguous, still choose the best group."
)
EXTRACT_SCHEMA_JSON = """{
  "tools_or_software": {"type": "array", "items": {"type": "string"}, "description": "Named tools, equipment or software explicitly mentioned in the task"},
  "primary_action": {"type": "string", "description": "Main verb of the task, lower case"},
  "work_object": {"type": "string", "description": "What the action is performed on"},
  "requires_physical_presence": {"type": "boolean", "description": "True only if the task text implies on-site physical work"}
}"""
QUERY_PROMPT_PREFIX = (
    "List up to 5 skills required to perform the following O*NET task. "
    "Use short skill names (1-4 words). Do not invent tools not mentioned. Return JSON {\"skills\": [..]}. Task: "
)

# ---- Run identity -------------------------------------------------------------
RUN_ID = f"{_dt.datetime.utcnow():%Y%m%dT%H%M%SZ}-{_uuid.uuid4().hex[:6]}"
print(f"KIT={KIT_VERSION} PROTOCOL={PROTOCOL} RUN_ID={RUN_ID}")
print(f"CATALOG.SCHEMA={CATALOG}.{SCHEMA}  VOLUME_ROOT={VOLUME_ROOT}")

# COMMAND ----------

def log_run(step: str, status: str, detail: str = "", rows_sent_to_ai: int = 0):
    """Append one row to the run log. Never overwrite; failures are evidence too."""
    import json as _json
    spark.sql(f"CREATE TABLE IF NOT EXISTS {FQE('run_log')} ("
              "run_id STRING, kit_version STRING, protocol STRING, step STRING, status STRING, detail STRING, "
              "rows_sent_to_ai INT, executed_by STRING, executed_at TIMESTAMP)")
    spark.createDataFrame(
        [(RUN_ID, KIT_VERSION, PROTOCOL, step, status, detail[:4000], int(rows_sent_to_ai))],
        "run_id STRING, kit_version STRING, protocol STRING, step STRING, status STRING, detail STRING, rows_sent_to_ai INT",
    ).selectExpr("*", "current_user() AS executed_by", "current_timestamp() AS executed_at") \
     .write.mode("append").saveAsTable(FQE("run_log"))

def sample_order(key_expr: str) -> str:
    """Deterministic pseudo-random order for capped samples (same rows every run)."""
    return f"xxhash64(CAST({key_expr} AS STRING), {SAMPLE_SEED})"
