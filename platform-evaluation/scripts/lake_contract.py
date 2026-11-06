"""Publish the lake contract layer: tidy, stable-named tables for the platform kits.

    python scripts/lake_build.py      # first (silver)
    python scripts/lake_contract.py   # -> data/lake/contract/<table>.parquet

Silver tables mirror each publisher's file layout (IPEDS is wide, O*NET file names vary).
The contract layer is what the Snowflake kit, the Databricks kit and the custom stack load:
the same table names, grains and column names everywhere, as specified in
lake/CONTRACT.md. Every table carries source_id and source_vintage.

Grain rules enforced here so platforms cannot double count by accident:
  * IPEDS staff/new-hire/instructional tables are long by sex x race_ethnicity; the
    published totals are rows with sex = 'Total' AND race_ethnicity = 'Total'.
    Category hierarchies are flagged: in ipeds_staff_by_occupation and
    ipeds_employees_by_position, rows with is_category_total = false form an exact
    partition of the institution total (verified against IPEDS totals for every
    institution), so SUM over those rows never double counts.
  * Salary tables exclude IPEDS total rows (all-ranks, all-occupations) so that
    SUM over categories reproduces the institution total.
  * QCEW and QWI keep publisher suppression: suppressed values are NULL.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
SILVER = ROOT / "data" / "lake" / "silver"
CONTRACT = ROOT / "data" / "lake" / "contract"
MANIFEST = ROOT / "lake" / "manifests" / "contract_manifest.json"
DDL = ROOT / "lake" / "ddl"

RACES = {"totl": "Total", "aian": "American Indian or Alaska Native", "asia": "Asian",
         "bkaa": "Black or African American", "hisp": "Hispanic or Latino",
         "nhpi": "Native Hawaiian or Other Pacific Islander", "whit": "White",
         "2mor": "Two or more races", "unkn": "Race/ethnicity unknown", "nral": "U.S. nonresident"}
SEXES = {"t": "Total", "m": "Men", "w": "Women"}


def s(t):  # silver parquet reference
    return f"read_parquet('{SILVER / (t + '.parquet')}')"


def label(survey, var, code_expr):
    return (f"(SELECT max(valuelabel) FROM {s('ipeds_value_label')} l WHERE l.survey = '{survey}' "
            f"AND l.varname = '{var}' AND l.codevalue = CAST({code_expr} AS VARCHAR))")


def long_race_sex(table, survey, keys: str, extra: str = ""):
    """Unpivot IPEDS HR race x sex columns (HR<race><T|M|W>) into long rows with imputation flags."""
    parts = []
    for rc, rname in RACES.items():
        for sc, sname in SEXES.items():
            col = f"hr{rc}{sc}"
            parts.append(f"SELECT {keys}, '{sname}' AS sex, '{rname}' AS race_ethnicity, "
                         f"CAST({col} AS BIGINT) AS headcount, CAST(x{col} AS VARCHAR) AS imputation_flag{extra} "
                         f"FROM {s(table)}")
    return " UNION ALL ".join(parts)


TABLES: dict[str, tuple[str, str, str]] = {}  # name -> (sql, source_id, vintage)


def t(name, source_id, vintage):
    def deco(fn):
        TABLES[name] = (fn, source_id, vintage)
        return fn
    return deco


# ------------------------------------------------------------------------------ O*NET
@t("onet_occupation", "onet_db_31_0", "O*NET 31.0")
def _():
    return f"SELECT onetsoc_code, title, description FROM {s('onet_occupation_data')}"


@t("onet_task_statement", "onet_db_31_0", "O*NET 31.0")
def _():
    return (f"SELECT onetsoc_code, task_id, task, task_type, incumbents_responding, date AS source_date, "
            f"domain_source FROM {s('onet_task_statements')}")


@t("onet_task_rating", "onet_db_31_0", "O*NET 31.0")
def _():
    return (f"SELECT onetsoc_code, task_id, scale_id, category, TRY_CAST(data_value AS DOUBLE) AS data_value, "
            f"TRY_CAST(n AS DOUBLE) AS n, recommend_suppress, date AS source_date FROM {s('onet_task_ratings')}")


@t("onet_element_rating", "onet_db_31_0", "O*NET 31.0")
def _():
    return f"SELECT * FROM {s('onet_element_rating')}"


@t("onet_technology_skill", "onet_db_31_0", "O*NET 31.0")
def _():
    # O*NET 31.0 ships technology examples as "Software Skills" with workplace_example + element ids.
    return (f"SELECT onetsoc_code, workplace_example AS example, element_id AS commodity_code, "
            f"element_name AS commodity_title, hot_technology, in_demand FROM {s('onet_software_skills')}")


@t("onet_alternate_title", "onet_db_31_0", "O*NET 31.0")
def _():
    return (f"SELECT DISTINCT onetsoc_code, job_title AS alternate_title, "
            f"NULLIF(short_title, 'n/a') AS short_title FROM {s('onet_job_titles')}")


@t("onet_job_zone", "onet_db_31_0", "O*NET 31.0")
def _():
    return f"SELECT onetsoc_code, job_zone FROM {s('onet_job_zones')}"


@t("onet_soc_crosswalk", "onet_soc_crosswalk", "O*NET-SOC 2019 to SOC 2018")
def _():
    return f"SELECT onetsoc_code, onetsoc_title, soc_2018_code, soc_2018_title FROM {s('onet_soc_crosswalk')}"


# ------------------------------------------------------------------------------ SUCSS
@t("sucss_class", "sucss_catalog", "acquired 2026-10-29")
def _():
    return f"SELECT source_record_id, class_code, class_title, occupational_line FROM {s('sucss_class')}"


@t("sucss_onet_candidate", "sucss_catalog", "title_lexical_baseline_v1")
def _():
    return (f"SELECT source_record_id, class_code, class_title, onet_code AS onetsoc_code, occupation_title, "
            f"candidate_rank, candidate_rank AS rank, title_similarity, title_similarity AS score, method, "
            f"review_status, warning FROM {s('sucss_onet_candidate')}")


# ------------------------------------------------------------------------------ IPEDS
@t("ipeds_institution", "ipeds", "HD2024")
def _():
    return (f"SELECT unitid, instnm AS name, instnm AS institution_name, stabbr AS state, stabbr AS state_abbr, "
            f"CAST(sector AS VARCHAR) AS sector_code, {label('HD2024', 'SECTOR', 'sector')} AS sector, "
            f"CAST(c21basic AS VARCHAR) AS carnegie_code, {label('HD2024', 'C21BASIC', 'c21basic')} AS carnegie, "
            f"{label('HD2024', 'C21BASIC', 'c21basic')} AS carnegie_class, "
            f"lpad(CAST(countycd AS VARCHAR), 5, '0') AS county_fips, CAST(cbsa AS VARCHAR) AS cbsa_code, "
            f"trim(f1sysnam) AS system_name, CAST(hospital AS VARCHAR) AS hospital, "
            f"CAST(landgrnt AS VARCHAR) AS land_grant, latitude, longitud AS longitude FROM {s('ipeds_hd2024')}")


@t("ipeds_staff_by_occupation", "ipeds", "S2023_OC (Fall 2023)")
def _():
    inner = long_race_sex("ipeds_s2023_oc", "S2023_OC",
                          "unitid, CAST(staffcat AS VARCHAR) AS staffcat_code, CAST(ftpt AS VARCHAR) AS ftpt_code, "
                          "CAST(occupcat AS VARCHAR) AS occupcat_code")
    return (f"SELECT unitid, 2023 AS survey_year, DATE '2023-11-01' AS snapshot_date, staffcat_code, "
            f"{label('S2023_OC', 'STAFFCAT', 'staffcat_code')} AS occupation_category, "
            f"{label('S2023_OC', 'FTPT', 'ftpt_code')} AS ftpt_status, occupcat_code, "
            f"CASE WHEN substr(staffcat_code, 2) = '100' THEN 'total' "
            f"WHEN staffcat_code LIKE '44%' THEN 'graduate_assistant' "
            f"WHEN substr(staffcat_code, 2) IN ('210','220','230','260','270','300','310','320','330','340','350','360','370','380','390') THEN 'detail' "
            f"WHEN substr(staffcat_code, 2) IN ('261','262','263','264') THEN 'subdetail' ELSE 'group' END AS category_level, "
            f"substr(staffcat_code, 2) NOT IN ('210','220','230','260','270','300','310','320','330','340','350','360','370','380','390') AS is_category_total, "
            f"sex, race_ethnicity, headcount, headcount AS staff_count, imputation_flag FROM ({inner})")


@t("ipeds_instructional_staff", "ipeds", "S2023_IS (Fall 2023)")
def _():
    inner = long_race_sex("ipeds_s2023_is", "S2023_IS",
                          "unitid, CAST(siscat AS VARCHAR) AS siscat_code, CAST(facstat AS VARCHAR) AS facstat_code, "
                          "CAST(arank AS VARCHAR) AS arank_code")
    return (f"SELECT unitid, 2023 AS survey_year, siscat_code, {label('S2023_IS', 'SISCAT', 'siscat_code')} AS category, "
            f"facstat_code, {label('S2023_IS', 'FACSTAT', 'facstat_code')} AS faculty_status, "
            f"arank_code, {label('S2023_IS', 'ARANK', 'arank_code')} AS academic_rank, "
            f"(arank_code = '0' OR facstat_code IN ('0','10','40')) AS is_category_total, "
            f"sex, race_ethnicity, headcount, imputation_flag FROM ({inner})")


@t("ipeds_new_hires", "ipeds", "S2023_NH (Fall 2023)")
def _():
    inner = long_race_sex("ipeds_s2023_nh", "S2023_NH",
                          "unitid, CAST(snhcat AS VARCHAR) AS snhcat_code, CAST(occupcat AS VARCHAR) AS occupcat_code, "
                          "CAST(facstat AS VARCHAR) AS facstat_code")
    return (f"SELECT unitid, 2023 AS survey_year, snhcat_code, {label('S2023_NH', 'SNHCAT', 'snhcat_code')} AS occupation_category, "
            f"occupcat_code, facstat_code, snhcat_code = '10000' AS is_category_total, "
            f"sex, race_ethnicity, headcount, imputation_flag FROM ({inner})")


@t("ipeds_salary_instructional", "ipeds", "SAL2023_IS (2023-24)")
def _():
    parts = []
    for cl, cnt, out in [("9", "sa09mc", "sa09mo"), ("10", "sa10mc", "sa10mo"), ("11", "sa11mc", "sa11mo"),
                         ("12", "sa12mc", "sa12mo")]:
        parts.append(f"SELECT unitid, CAST(arank AS VARCHAR) AS arank_code, '{cl}-month' AS contract_length, "
                     f"{cnt}t AS staff_count, {cnt}m AS staff_count_men, {cnt}w AS staff_count_women, "
                     f"{out}t AS salary_outlays, {out}m AS salary_outlays_men, {out}w AS salary_outlays_women "
                     f"FROM {s('ipeds_sal2023_is')}")
    return (f"SELECT unitid, 2023 AS survey_year, arank_code, {label('SAL2023_IS', 'ARANK', 'arank_code')} AS academic_rank, "
            f"contract_length, staff_count, staff_count_men, staff_count_women, salary_outlays, "
            f"salary_outlays AS total_salary_outlays, salary_outlays_men, salary_outlays_women, "
            f"CASE WHEN staff_count > 0 THEN round(CAST(salary_outlays AS DOUBLE) / staff_count, 0) END AS avg_salary "
            f"FROM ({' UNION ALL '.join(parts)}) "
            f"WHERE {label('SAL2023_IS', 'ARANK', 'arank_code')} NOT ILIKE 'All%'")


@t("ipeds_salary_noninstructional", "ipeds", "SAL2023_NIS (2023-24)")
def _():
    groups = ["Research", "Public service",
              "Library, curators, archivists, academic affairs and other education services", "Management",
              "Business and financial operations", "Computer, engineering and science",
              "Community/social service, legal, arts, design, media", "Healthcare practitioners and technical",
              "Service", "Sales and related", "Office and administrative support",
              "Natural resources, construction and maintenance", "Production, transportation and material moving"]
    parts = [f"SELECT unitid, '{i:02d}' AS occupation_category_code, '{g}' AS occupation_category, "
             f"sanin{i:02d} AS staff_count, sanit{i:02d} AS salary_outlays FROM {s('ipeds_sal2023_nis')}"
             for i, g in enumerate(groups, start=2)]
    return (f"SELECT unitid, 2023 AS survey_year, occupation_category_code, occupation_category, staff_count, "
            f"salary_outlays, salary_outlays AS total_salary_outlays, "
            f"CASE WHEN staff_count > 0 THEN round(CAST(salary_outlays AS DOUBLE) / staff_count, 0) END AS avg_salary "
            f"FROM ({' UNION ALL '.join(parts)})")


@t("ipeds_employees_by_position", "ipeds", "EAP2023 (Fall 2023)")
def _():
    return (f"SELECT unitid, 2023 AS survey_year, CAST(eapcat AS VARCHAR) AS eapcat_code, "
            f"{label('EAP2023', 'EAPCAT', 'eapcat')} AS position_category, CAST(occupcat AS VARCHAR) AS occupcat_code, "
            f"CAST(facstat AS VARCHAR) AS facstat_code, eaptot AS total_employees, eapft AS full_time, "
            f"eappt AS part_time, eapmed AS medical_school_employees, "
            f"right(CAST(eapcat AS VARCHAR), 3) = '000' AS is_all_faculty_status, "
            f"NOT (left(CAST(eapcat AS VARCHAR), 2) IN ('21','22','23','26','27','30','31','32','33','34','35','36','37','38','39') "
            f"AND right(CAST(eapcat AS VARCHAR), 3) = '000') AS is_category_total FROM {s('ipeds_eap2023')}")


@t("ipeds_enrollment_12mo", "ipeds", "EFFY2024 (2023-24)")
def _():
    return (f"SELECT unitid, 2024 AS survey_year, CAST(effyalev AS VARCHAR) AS level_code, "
            f"{label('EFFY2024', 'EFFYALEV', 'effyalev')} AS student_level, efytotlt AS enrollment_total, "
            f"efytotlm AS enrollment_men, efytotlw AS enrollment_women FROM {s('ipeds_effy2024')}")


# ------------------------------------------------------------------------------ QCEW
QCEW_Q = ("area_fips, own_code, industry_code, agglvl_code, size_code, year, CAST(qtr AS INTEGER) AS qtr, "
          "disclosure_code, "
          "CASE WHEN disclosure_code = 'N' THEN NULL ELSE qtrly_estabs END AS qtrly_estabs, "
          "CASE WHEN disclosure_code = 'N' THEN NULL ELSE month1_emplvl END AS month1_emplvl, "
          "CASE WHEN disclosure_code = 'N' THEN NULL ELSE month2_emplvl END AS month2_emplvl, "
          "CASE WHEN disclosure_code = 'N' THEN NULL ELSE month3_emplvl END AS month3_emplvl, "
          "CASE WHEN disclosure_code = 'N' THEN NULL ELSE total_qtrly_wages END AS total_qtrly_wages, "
          "CASE WHEN disclosure_code = 'N' THEN NULL ELSE avg_wkly_wage END AS avg_wkly_wage, "
          "make_date(CAST(year AS INTEGER), (CAST(qtr AS INTEGER) - 1) * 3 + 1, 1) AS quarter_start")
AREA_TITLE = ("CASE area_fips WHEN 'US000' THEN 'U.S. TOTAL' WHEN '17000' THEN 'Illinois -- Statewide' "
              "WHEN '17019' THEN 'Champaign County, Illinois' WHEN '17031' THEN 'Cook County, Illinois' "
              "WHEN '17167' THEN 'Sangamon County, Illinois' END AS area_title")


@t("qcew_industry", "qcew_colleges_qtr", "2019Q1 onward")
def _():
    return f"SELECT {QCEW_Q}, {AREA_TITLE} FROM {s('qcew_colleges_quarterly')}"


@t("qcew_area", "qcew_il_counties_qtr", "2019Q1 onward")
def _():
    # County files only; NAICS 611310 rows also appear in qcew_industry for the same counties.
    return f"SELECT {QCEW_Q}, {AREA_TITLE} FROM {s('qcew_il_county_quarterly')}"


# ------------------------------------------------------------------------------ QWI
@t("qwi_higher_ed", "qwi_il", "LEHD latest_release")
def _():
    return (f"SELECT geography, geo_level, '17' AS state_fips, CAST(NULL AS VARCHAR) AS county_fips, industry, "
            f"ownercode, sex, agegrp, CAST(year AS INTEGER) AS year, CAST(quarter AS INTEGER) AS quarter, "
            f"make_date(CAST(year AS INTEGER), (CAST(quarter AS INTEGER) - 1) * 3 + 1, 1) AS quarter_start, "
            f"emp, emp_s, hir_a AS hira, hir_n AS hirn, sep, turn_ovr_s AS turnovrs, earn_s AS earns, "
            f"s_emp, s_hir_a, s_sep, s_turn_ovr_s, s_earn_s "
            f"FROM {s('qwi_il_sa_gs_n4_oslp')} WHERE industry = '6113'")


# ------------------------------------------------------------------------------ AEI
@t("aei_task_usage", "anthropic_economic_index", "release_2025_03_27 + labor_market_impacts")
def _():
    return (f"SELECT p.task_name, 'release_2025_03_27' AS release, p.pct AS usage_pct, CAST(NULL AS DOUBLE) AS penetration, "
            f"a.directive, a.feedback_loop, a.task_iteration, a.validation, a.learning, a.filtered "
            f"FROM {s('aei_task_pct_v2')} p LEFT JOIN {s('aei_automation_vs_augmentation_by_task')} a USING (task_name) "
            f"UNION ALL "
            f"SELECT lower(task) AS task_name, 'labor_market_impacts' AS release, NULL, penetration, "
            f"NULL, NULL, NULL, NULL, NULL, NULL FROM {s('aei_task_penetration')}")


@t("aei_occupation_exposure", "anthropic_economic_index", "labor_market_impacts")
def _():
    return f"SELECT occ_code AS soc_2018_code, title, observed_exposure FROM {s('aei_job_exposure')}"


SF = {"VARCHAR": "VARCHAR", "BIGINT": "NUMBER(19,0)", "INTEGER": "NUMBER(10,0)", "DOUBLE": "FLOAT", "DATE": "DATE",
      "BOOLEAN": "BOOLEAN", "SMALLINT": "NUMBER(5,0)", "TINYINT": "NUMBER(3,0)", "FLOAT": "FLOAT", "HUGEINT": "NUMBER(38,0)"}
DBX = {"VARCHAR": "STRING", "BIGINT": "BIGINT", "INTEGER": "INT", "DOUBLE": "DOUBLE", "DATE": "DATE",
       "BOOLEAN": "BOOLEAN", "SMALLINT": "SMALLINT", "TINYINT": "TINYINT", "FLOAT": "FLOAT", "HUGEINT": "DECIMAL(38,0)"}


def main() -> int:
    CONTRACT.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    meta = {}
    for name, (fn, source_id, vintage) in TABLES.items():
        out = CONTRACT / f"{name}.parquet"
        sql = f"SELECT *, '{source_id}' AS source_id, '{vintage}' AS source_vintage FROM ({fn()})"
        con.sql(f"COPY ({sql}) TO '{out}' (FORMAT parquet, COMPRESSION zstd)")
        cols = con.sql(f"DESCRIBE SELECT * FROM '{out}'").fetchall()
        n = con.sql(f"SELECT count(*) FROM '{out}'").fetchall()[0][0]
        meta[name] = {"rows": n, "bytes": out.stat().st_size, "source_id": source_id, "source_vintage": vintage,
                      "columns": [{"name": c[0], "type": c[1]} for c in cols]}
        print(f"  {name:<34} {n:>10,} rows")
    MANIFEST.write_text(json.dumps({"contract_version": "1.0", "built_at_utc": datetime.now(timezone.utc).isoformat(),
                                    "tables": meta}, indent=1) + "\n")
    hdr = "-- Generated by scripts/lake_contract.py from data/lake/contract schemas (contract v1.0).\n"
    sf, dbx = [hdr], [hdr]
    for name, m in meta.items():
        sf.append(f"CREATE TABLE IF NOT EXISTS {name.upper()} (\n  " + ",\n  ".join(
            f'"{c["name"].upper()}" {SF.get(c["type"].split("(")[0], "VARCHAR")}' for c in m["columns"]) + "\n);\n")
        dbx.append(f"CREATE TABLE IF NOT EXISTS {name} (\n  " + ",\n  ".join(
            f'`{c["name"]}` {DBX.get(c["type"].split("(")[0], "STRING")}' for c in m["columns"]) + "\n);\n")
    (DDL / "snowflake_contract_tables.sql").write_text("\n".join(sf))
    (DDL / "databricks_contract_tables.sql").write_text("\n".join(dbx))
    print(f"{len(meta)} contract tables -> {CONTRACT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
