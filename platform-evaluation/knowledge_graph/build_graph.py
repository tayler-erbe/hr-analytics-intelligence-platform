"""Build the public workforce data network (knowledge graph) as two Parquet tables.

Reads the lake contract layer (data/lake/contract) and a few silver tables
(data/lake/silver) and writes:

    data/lake/graph/nodes.parquet
    data/lake/graph/edges.parquet
    knowledge_graph/build_manifest.json   (counts and timings only; no row data)

Run from platform-evaluation/:

    python knowledge_graph/build_graph.py

The ontology is documented in knowledge_graph/schema.md. Public data only: this
script never reads data/local/ and never creates the internal node types.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pyarrow as pa

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent  # platform-evaluation/
CONTRACT = ROOT / "data" / "lake" / "contract"
SILVER = ROOT / "data" / "lake" / "silver"
GRAPH_DIR = ROOT / "data" / "lake" / "graph"
MANIFEST = HERE / "build_manifest.json"

ONTOLOGY_VERSION = "0.1"
QCEW_YEARS = (2019, 2025)

# Published SOC 2018 major groups (BLS). Used only for labels of soc:NN-0000 nodes.
SOC_MAJOR_GROUPS = {
    "11": "Management Occupations",
    "13": "Business and Financial Operations Occupations",
    "15": "Computer and Mathematical Occupations",
    "17": "Architecture and Engineering Occupations",
    "19": "Life, Physical, and Social Science Occupations",
    "21": "Community and Social Service Occupations",
    "23": "Legal Occupations",
    "25": "Educational Instruction and Library Occupations",
    "27": "Arts, Design, Entertainment, Sports, and Media Occupations",
    "29": "Healthcare Practitioners and Technical Occupations",
    "31": "Healthcare Support Occupations",
    "33": "Protective Service Occupations",
    "35": "Food Preparation and Serving Related Occupations",
    "37": "Building and Grounds Cleaning and Maintenance Occupations",
    "39": "Personal Care and Service Occupations",
    "41": "Sales and Related Occupations",
    "43": "Office and Administrative Support Occupations",
    "45": "Farming, Fishing, and Forestry Occupations",
    "47": "Construction and Extraction Occupations",
    "49": "Installation, Maintenance, and Repair Occupations",
    "51": "Production Occupations",
    "53": "Transportation and Material Moving Occupations",
    "55": "Military Specific Occupations",
}

# IPEDS non-instructional occupation group -> SOC 2018 major groups. Curated from the
# IPEDS HR occupational category definitions (which are built from SOC codes).
# Groups 02 (Research) and 03 (Public service) are functions of postsecondary staff,
# not SOC groups, so they get no edge.
IPEDS_GROUP_TO_SOC = {
    "04": (["25"], "partial", "25-2000, 25-3000, 25-4000, 25-9000 (excludes 25-1000 postsecondary teachers)"),
    "05": (["11"], "full", "11-0000"),
    "06": (["13"], "full", "13-0000"),
    "07": (["15", "17", "19"], "full", "15-0000, 17-0000, 19-0000"),
    "08": (["21", "23", "27"], "full", "21-0000, 23-0000, 27-0000"),
    "09": (["29"], "full", "29-0000"),
    "10": (["31", "33", "35", "37", "39"], "full", "31-0000 to 39-0000"),
    "11": (["41"], "full", "41-0000"),
    "12": (["43"], "full", "43-0000"),
    "13": (["45", "47", "49"], "full", "45-0000 to 49-0000"),
    "14": (["51", "53"], "full", "51-0000, 53-0000"),
}

ELEMENT_DOMAINS = {
    # domain -> node type. work_activities are GWAs (one node, see schema.md).
    "abilities": "Ability",
    "knowledge": "Knowledge",
    "essential_skills": "Skill",
    "transferable_skills": "Skill",
    "work_activities": "GWA",
}

INTERNAL_NODE_TYPES = ("Person", "Appointment", "Position", "Department",
                       "LearningActivity", "Requisition", "Posting")


def c(table: str) -> str:
    return f"read_parquet('{(CONTRACT / (table + '.parquet')).as_posix()}')"


def s(table: str) -> str:
    return f"read_parquet('{(SILVER / (table + '.parquet')).as_posix()}')"


def tech_slugs(examples: list[str]) -> dict[str, str]:
    """Readable, stable technology IDs. A hash suffix is added only on slug collisions."""
    def slug(x: str) -> str:
        x = x.lower().replace("+", " plus ").replace("#", " sharp ").replace("&", " and ")
        return re.sub(r"[^a-z0-9]+", "-", x).strip("-") or "x"

    by_slug: dict[str, list[str]] = {}
    for e in examples:
        by_slug.setdefault(slug(e), []).append(e)
    out = {}
    for sl, items in by_slug.items():
        for e in items:
            out[e] = sl if len(items) == 1 else f"{sl}~{hashlib.md5(e.encode()).hexdigest()[:6]}"
    return out


NODE_COLS = "node_id, node_type, label, code, props, source_id, source_vintage"
EDGE_COLS = ("src_id, dst_id, edge_type, qualifier, weight, props, source_id, source_vintage, "
             "method, confidence, review_status, valid_from, valid_to")


def build(con: duckdb.DuckDBPyConnection, log=print) -> dict:
    timings: dict[str, float] = {}
    t0 = time.perf_counter()

    def step(name):
        timings[name] = round(time.perf_counter() - t0 - sum(timings.values()), 3)
        log(f"  {name}: {timings[name]:.2f}s")

    con.execute(f"CREATE TEMP TABLE nodes_raw ({NODE_COLS.replace(',', ' VARCHAR,')} VARCHAR)")
    con.execute("""CREATE TEMP TABLE edges_raw (src_id VARCHAR, dst_id VARCHAR, edge_type VARCHAR,
        qualifier VARCHAR, weight DOUBLE, props VARCHAR, source_id VARCHAR, source_vintage VARCHAR,
        method VARCHAR, confidence DOUBLE, review_status VARCHAR, valid_from DATE, valid_to DATE)""")

    def nodes(sql):
        con.execute(f"INSERT INTO nodes_raw ({NODE_COLS}) {sql}")

    def edges(sql):
        con.execute(f"INSERT INTO edges_raw ({EDGE_COLS}) {sql}")

    # ------------------------------------------------------------------ O*NET core
    nodes(f"""
        WITH alt AS (
            SELECT onetsoc_code, count(*) AS n,
                   list(alternate_title ORDER BY alternate_title)[1:8] AS sample
            FROM {c('onet_alternate_title')} GROUP BY 1)
        SELECT 'onet:' || o.onetsoc_code, 'Occupation', o.title, o.onetsoc_code,
               json_object('description', o.description, 'job_zone', jz.job_zone,
                           'alternate_title_count', coalesce(alt.n, 0),
                           'alternate_titles_sample', alt.sample)::VARCHAR,
               o.source_id, o.source_vintage
        FROM {c('onet_occupation')} o
        LEFT JOIN {c('onet_job_zone')} jz USING (onetsoc_code)
        LEFT JOIN alt USING (onetsoc_code)""")

    con.execute("CREATE TEMP TABLE soc_major (code VARCHAR, title VARCHAR)")
    con.executemany("INSERT INTO soc_major VALUES (?, ?)", list(SOC_MAJOR_GROUPS.items()))
    nodes(f"""
        SELECT DISTINCT 'soc:' || soc_2018_code, 'SOC2018', soc_2018_title, soc_2018_code,
               json_object('level', 'detailed')::VARCHAR, source_id, source_vintage
        FROM {c('onet_soc_crosswalk')}""")
    nodes("""
        SELECT 'soc:' || code || '-0000', 'SOC2018', title, code || '-0000',
               json_object('level', 'major')::VARCHAR, 'bls_soc_2018', 'SOC 2018 major groups'
        FROM soc_major""")
    edges(f"""
        SELECT 'onet:' || onetsoc_code, 'soc:' || soc_2018_code, 'MAPS_TO_SOC', NULL, NULL, NULL,
               source_id, source_vintage, 'onet_soc_crosswalk', 1.0, 'publisher_asserted', NULL, NULL
        FROM {c('onet_soc_crosswalk')}""")
    edges(f"""
        SELECT DISTINCT 'soc:' || soc_2018_code, 'soc:' || substr(soc_2018_code, 1, 2) || '-0000',
               'BROADER', NULL, NULL, NULL, 'bls_soc_2018', 'SOC 2018', 'soc_code_prefix', 1.0,
               'derived_rule', NULL, NULL
        FROM {c('onet_soc_crosswalk')}""")

    nodes(f"""
        SELECT 'jobzone:' || job_zone, 'JobZone', name, job_zone::VARCHAR,
               json_object('education', education, 'experience', experience,
                           'svp_range', svp_range)::VARCHAR,
               'onet_db_31_0', 'O*NET 31.0'
        FROM {s('onet_job_zone_reference')}""")
    edges(f"""
        SELECT 'onet:' || onetsoc_code, 'jobzone:' || job_zone, 'IN_JOB_ZONE', NULL, NULL, NULL,
               source_id, source_vintage, 'onet_job_zones', 1.0, 'publisher_asserted', NULL, NULL
        FROM {c('onet_job_zone')}""")
    step("onet_occupations_soc_jobzones")

    # Tasks, with importance (IM) and relevance (RT) from task ratings.
    nodes(f"""
        SELECT 'task:' || task_id, 'Task', task, task_id,
               json_object('onetsoc_code', onetsoc_code, 'task_type', task_type)::VARCHAR,
               source_id, source_vintage
        FROM {c('onet_task_statement')}""")
    edges(f"""
        WITH r AS (
            SELECT onetsoc_code, task_id,
                   max(data_value) FILTER (WHERE scale_id = 'IM') AS im,
                   max(data_value) FILTER (WHERE scale_id = 'RT') AS rt
            FROM {c('onet_task_rating')} GROUP BY 1, 2)
        SELECT 'onet:' || t.onetsoc_code, 'task:' || t.task_id, 'PERFORMS_TASK', NULL, r.im,
               json_object('task_type', t.task_type, 'relevance', r.rt,
                           'domain_source', t.domain_source)::VARCHAR,
               t.source_id, t.source_vintage,
               'onet_task_statement:' || coalesce(t.domain_source, 'unknown'),
               1.0, 'publisher_asserted', NULL, NULL
        FROM {c('onet_task_statement')} t LEFT JOIN r USING (onetsoc_code, task_id)""")

    # Work-activity hierarchy: GWA (rated elements) <- IWA <- DWA <- Task
    nodes(f"""
        SELECT DISTINCT 'iwa:' || iwa_element_id, 'IWA', iwa_element_name, iwa_element_id,
               json_object('gwa_element_id', gwa_element_id)::VARCHAR, 'onet_db_31_0', 'O*NET 31.0'
        FROM {s('onet_gwas_to_iwas')}""")
    nodes(f"""
        SELECT 'dwa:' || dwa_element_id, 'DWA', dwa_element_name, dwa_element_id,
               json_object('iwa_element_id', iwa_element_id)::VARCHAR, 'onet_db_31_0', 'O*NET 31.0'
        FROM {s('onet_gwas_to_iwas_to_dwas')}""")
    edges(f"""
        SELECT 'dwa:' || dwa_element_id, 'iwa:' || iwa_element_id, 'PART_OF', NULL, NULL, NULL,
               'onet_db_31_0', 'O*NET 31.0', 'onet_dwa_reference', 1.0, 'publisher_asserted', NULL, NULL
        FROM {s('onet_gwas_to_iwas_to_dwas')}""")
    edges(f"""
        SELECT DISTINCT 'iwa:' || iwa_element_id, 'gwa:' || gwa_element_id, 'PART_OF', NULL, NULL, NULL,
               'onet_db_31_0', 'O*NET 31.0', 'onet_iwa_reference', 1.0, 'publisher_asserted', NULL, NULL
        FROM {s('onet_gwas_to_iwas')}""")
    edges(f"""
        SELECT 'task:' || task_id, 'dwa:' || dwa_element_id, 'ALIGNS_TO_DWA', onetsoc_code, NULL,
               json_object('date', date)::VARCHAR, 'onet_db_31_0', 'O*NET 31.0',
               'onet_tasks_to_dwas:' || coalesce(domain_source, 'unknown'), 1.0, 'publisher_asserted',
               NULL, NULL
        FROM {s('onet_tasks_to_dwas')}""")
    step("onet_tasks_and_work_activities")

    # Rated elements (skills, knowledge, abilities, work activities = GWAs)
    con.execute("CREATE TEMP TABLE dom (domain VARCHAR, node_type VARCHAR, prefix VARCHAR)")
    con.executemany("INSERT INTO dom VALUES (?, ?, ?)",
                    [(d, t, "gwa:" if t == "GWA" else "element:") for d, t in ELEMENT_DOMAINS.items()])
    nodes(f"""
        SELECT DISTINCT d.prefix || e.element_id, d.node_type, e.element_name, e.element_id,
               json_object('domain', e.domain, 'description', cm.description)::VARCHAR,
               e.source_id, e.source_vintage
        FROM {c('onet_element_rating')} e JOIN dom d USING (domain)
        LEFT JOIN {s('onet_content_model_reference')} cm USING (element_id)""")
    edges(f"""
        WITH im AS (SELECT * FROM {c('onet_element_rating')} WHERE scale_id = 'IM'),
             lv AS (SELECT * FROM {c('onet_element_rating')} WHERE scale_id = 'LV')
        SELECT 'onet:' || im.onetsoc_code, d.prefix || im.element_id, 'HAS_ELEMENT_RATING', NULL,
               im.data_value,
               json_object('domain', im.domain, 'level', lv.data_value,
                           'level_suppress_flag', lv.recommend_suppress,
                           'importance_suppress_flag', im.recommend_suppress,
                           'n', im.n, 'date', im.date)::VARCHAR,
               im.source_id, im.source_vintage,
               'onet_published_rating:' || coalesce(im.domain_source, 'unknown'),
               1.0, 'publisher_asserted', NULL, NULL
        FROM im JOIN dom d USING (domain)
        LEFT JOIN lv ON lv.onetsoc_code = im.onetsoc_code AND lv.element_id = im.element_id
                    AND lv.domain = im.domain""")
    step("onet_element_ratings")

    # Technology examples
    examples = [r[0] for r in con.sql(
        f"SELECT DISTINCT example FROM {c('onet_technology_skill')} ORDER BY 1").fetchall()]
    slug_map = tech_slugs(examples)
    tech_tbl = pa.table({"example": list(slug_map), "tech_id": ["tech:" + v for v in slug_map.values()]})
    con.register("tech_tbl", tech_tbl)
    con.execute("CREATE TEMP TABLE tech_ids AS SELECT * FROM tech_tbl")
    nodes(f"""
        SELECT t.tech_id, 'Technology', t.example, NULL,
               json_object('commodity_code', any_value(ts.commodity_code),
                           'commodity_title', any_value(ts.commodity_title),
                           'occupation_count', count(DISTINCT ts.onetsoc_code))::VARCHAR,
               any_value(ts.source_id), any_value(ts.source_vintage)
        FROM {c('onet_technology_skill')} ts JOIN tech_ids t USING (example)
        GROUP BY t.tech_id, t.example""")
    edges(f"""
        SELECT 'onet:' || ts.onetsoc_code, t.tech_id, 'USES_TECHNOLOGY', NULL, NULL,
               json_object('hot_technology', ts.hot_technology = 'Y',
                           'in_demand', ts.in_demand = 'Y')::VARCHAR,
               ts.source_id, ts.source_vintage, 'onet_technology_skills', 1.0, 'publisher_asserted',
               NULL, NULL
        FROM {c('onet_technology_skill')} ts JOIN tech_ids t USING (example)""")

    edges(f"""
        SELECT 'onet:' || onetsoc_code, 'onet:' || related_o_net_soc_code, 'RELATED_TO', NULL, NULL,
               json_object('tier', relatedness_tier, 'index', "index")::VARCHAR,
               'onet_db_31_0', 'O*NET 31.0', 'onet_related_occupations', 1.0, 'publisher_asserted',
               NULL, NULL
        FROM {s('onet_related_occupations')}""")
    step("onet_technology_and_related")

    # ------------------------------------------------------------------ SUCSS
    nodes(f"""
        SELECT 'sucss:' || source_record_id, 'SUCSSClass', class_title, class_code,
               json_object('class_code', class_code, 'source_record_id', source_record_id,
                           'occupational_line', nullif(occupational_line, ''))::VARCHAR,
               source_id, source_vintage
        FROM {c('sucss_class')}""")
    edges(f"""
        SELECT 'sucss:' || source_record_id, 'onet:' || onetsoc_code, 'CANDIDATE_MATCH',
               candidate_rank::VARCHAR, score,
               json_object('rank', candidate_rank, 'title_similarity', title_similarity,
                           'warning', warning)::VARCHAR,
               source_id, source_vintage, method, NULL, review_status, NULL, NULL
        FROM {c('sucss_onet_candidate')}""")
    step("sucss")

    # ------------------------------------------------------------------ Geography
    nodes("SELECT 'geo:US000', 'Geography', 'United States', 'US000', "
          "json_object('level', 'nation')::VARCHAR, 'census_fips', 'FIPS'")
    # States: FIPS prefix of IPEDS counties, labelled with the IPEDS state abbreviation.
    nodes(f"""
        SELECT 'fips:' || st, 'Geography', mode(state_abbr), st,
               json_object('level', 'state', 'state_abbr', mode(state_abbr))::VARCHAR,
               'census_fips', 'FIPS (labels from IPEDS HD2024)'
        FROM (SELECT substr(county_fips, 1, 2) AS st, state_abbr FROM {c('ipeds_institution')}
              WHERE regexp_full_match(county_fips, '[0-9]{{5}}'))
        GROUP BY st""")
    con.execute(f"""
        CREATE TEMP TABLE county_src AS
        SELECT county_fips AS fips, NULL AS title FROM {c('ipeds_institution')}
        WHERE regexp_full_match(county_fips, '[0-9]{{5}}')
        UNION ALL
        SELECT area_fips, area_title FROM {c('qcew_area')}
        UNION ALL
        SELECT area_fips, area_title FROM {c('qcew_industry')}
        WHERE regexp_full_match(area_fips, '[0-9]{{5}}') AND area_fips NOT LIKE '%000'""")
    nodes("""
        SELECT 'fips:' || fips, 'Geography', coalesce(max(title), 'County ' || fips), fips,
               json_object('level', 'county')::VARCHAR, 'census_fips', 'FIPS'
        FROM county_src GROUP BY fips""")
    # States that appear only in QCEW (territories etc.)
    nodes(f"""
        SELECT DISTINCT 'fips:' || substr(f, 1, 2), 'Geography', 'State ' || substr(f, 1, 2),
               substr(f, 1, 2), json_object('level', 'state')::VARCHAR, 'census_fips', 'FIPS'
        FROM (SELECT fips AS f FROM county_src UNION SELECT area_fips FROM {c('qcew_industry')}
              WHERE regexp_full_match(area_fips, '[0-9]{{2}}000'))
        WHERE 'fips:' || substr(f, 1, 2) NOT IN (SELECT node_id FROM nodes_raw)""")
    edges("""
        SELECT DISTINCT 'fips:' || fips, 'fips:' || substr(fips, 1, 2), 'IN_STATE', NULL, NULL, NULL,
               'census_fips', 'FIPS', 'fips_prefix', 1.0, 'derived_rule', NULL, NULL
        FROM county_src""")
    con.execute(f"""
        CREATE TEMP TABLE cbsa_src AS
        SELECT cbsa_code AS cbsa, NULL AS title FROM {c('ipeds_institution')}
        WHERE regexp_full_match(cbsa_code, '[0-9]{{5}}')
        UNION ALL
        SELECT substr(area_fips, 2, 4) || '0', area_title FROM {c('qcew_industry')}
        WHERE area_fips LIKE 'C%'""")
    nodes("""
        SELECT 'cbsa:' || cbsa, 'Geography', coalesce(max(title), 'CBSA ' || cbsa), cbsa,
               json_object('level', 'cbsa')::VARCHAR, 'census_cbsa', 'CBSA (IPEDS HD2024 / QCEW)'
        FROM cbsa_src GROUP BY cbsa""")
    edges(f"""
        WITH pairs AS (
            SELECT DISTINCT county_fips, cbsa_code FROM {c('ipeds_institution')}
            WHERE regexp_full_match(county_fips, '[0-9]{{5}}') AND regexp_full_match(cbsa_code, '[0-9]{{5}}')),
        uniq AS (SELECT county_fips FROM pairs GROUP BY 1 HAVING count(*) = 1)
        SELECT 'fips:' || county_fips, 'cbsa:' || cbsa_code, 'IN_CBSA', NULL, NULL, NULL,
               'ipeds', 'HD2024', 'ipeds_hd_county_cbsa_cooccurrence', 1.0, 'derived_rule', NULL, NULL
        FROM pairs JOIN uniq USING (county_fips)""")
    step("geography")

    # ------------------------------------------------------------------ Institutions
    nodes(f"""
        SELECT 'ipeds:' || unitid, 'Institution', institution_name, unitid,
               json_object('in_hd2024', true, 'state_abbr', state_abbr, 'sector_code', sector_code, 'sector', sector,
                           'carnegie_code', carnegie_code, 'carnegie', carnegie,
                           'system_name', system_name, 'land_grant', land_grant = '1',
                           'hospital', hospital = '1', 'latitude', latitude,
                           'longitude', longitude)::VARCHAR,
               source_id, source_vintage
        FROM {c('ipeds_institution')}""")
    # IPEDS 2023 HR reporters missing from the HD2024 directory (closed or merged since):
    # keep their facts and add a flagged stub rather than dropping rows.
    nodes(f"""
        SELECT DISTINCT 'ipeds:' || unitid, 'Institution', 'UNITID ' || unitid || ' (not in HD2024)',
               unitid, json_object('in_hd2024', false)::VARCHAR, 'ipeds', 'S2023_OC / SAL2023_NIS only'
        FROM (SELECT unitid FROM {c('ipeds_salary_noninstructional')} WHERE staff_count > 0
              UNION SELECT unitid FROM {c('ipeds_staff_by_occupation')} WHERE staffcat_code = '1100')
        WHERE unitid NOT IN (SELECT unitid FROM {c('ipeds_institution')})""")
    edges(f"""
        SELECT 'ipeds:' || unitid, 'fips:' || county_fips, 'LOCATED_IN', NULL, NULL, NULL,
               source_id, source_vintage, 'ipeds_hd_countycd', 1.0, 'publisher_asserted', NULL, NULL
        FROM {c('ipeds_institution')} WHERE regexp_full_match(county_fips, '[0-9]{{5}}')""")
    edges(f"""
        SELECT 'ipeds:' || unitid, 'cbsa:' || cbsa_code, 'IN_CBSA', NULL, NULL, NULL,
               source_id, source_vintage, 'ipeds_hd_cbsa', 1.0, 'publisher_asserted', NULL, NULL
        FROM {c('ipeds_institution')} WHERE regexp_full_match(cbsa_code, '[0-9]{{5}}')""")
    step("institutions")

    # ------------------------------------------------------------------ Industry
    nodes("""
        SELECT * FROM (VALUES
          ('naics:611310', 'Industry', 'Colleges, universities, and professional schools', '611310',
           '{"is_naics": true}', 'census_naics', 'NAICS 2022'),
          ('naics:6113', 'Industry', 'Colleges, universities, and professional schools (4-digit)', '6113',
           '{"is_naics": true}', 'census_naics', 'NAICS 2022'),
          ('naics:10', 'Industry', 'Total, all industries (QCEW aggregate)', '10',
           '{"is_naics": false, "note": "QCEW aggregate industry code, not a NAICS code"}',
           'bls_qcew', 'QCEW industry codes'))""")
    edges("""SELECT 'naics:611310', 'naics:6113', 'BROADER', NULL, NULL, NULL, 'census_naics',
                    'NAICS 2022', 'naics_code_prefix', 1.0, 'derived_rule', NULL, NULL""")

    # ------------------------------------------------------------------ Labor-market facts
    def area_node(col):
        return (f"CASE WHEN {col} = 'US000' THEN 'geo:US000' "
                f"WHEN {col} LIKE 'C%' THEN 'cbsa:' || substr({col}, 2, 4) || '0' "
                f"WHEN {col} LIKE '%000' THEN 'fips:' || substr({col}, 1, 2) "
                f"ELSE 'fips:' || {col} END")

    con.execute(f"""
        CREATE TEMP TABLE qcew_q AS
        SELECT area_fips, own_code, industry_code, year, qtr, disclosure_code,
               month1_emplvl, month2_emplvl, month3_emplvl, total_qtrly_wages, qtrly_estabs,
               source_id, source_vintage
        FROM {c('qcew_industry')} WHERE size_code = '0'
        UNION ALL
        SELECT area_fips, own_code, industry_code, year, qtr, disclosure_code,
               month1_emplvl, month2_emplvl, month3_emplvl, total_qtrly_wages, qtrly_estabs,
               source_id, source_vintage
        FROM {c('qcew_area')} WHERE size_code = '0' AND industry_code = '10'""")
    con.execute(f"""
        CREATE TEMP TABLE qcew_y AS
        SELECT area_fips, own_code, industry_code, year,
               count(*) AS quarters,
               bool_or(disclosure_code = 'N') AS suppressed,
               CASE WHEN count(*) = 4 AND NOT bool_or(disclosure_code = 'N')
                    THEN (sum(month1_emplvl) + sum(month2_emplvl) + sum(month3_emplvl)) / 12.0 END AS avg_emp,
               CASE WHEN count(*) = 4 AND NOT bool_or(disclosure_code = 'N')
                    THEN sum(total_qtrly_wages) END AS total_wages,
               CASE WHEN count(*) = 4 AND NOT bool_or(disclosure_code = 'N')
                    THEN avg(qtrly_estabs) END AS avg_estabs,
               any_value(source_id) AS source_id, any_value(source_vintage) AS source_vintage
        FROM qcew_q WHERE year BETWEEN {QCEW_YEARS[0]} AND {QCEW_YEARS[1]}
        GROUP BY ALL""")
    own = "CASE own_code WHEN '0' THEN 'Total, all ownerships' WHEN '1' THEN 'Federal government' " \
          "WHEN '2' THEN 'State government' WHEN '3' THEN 'Local government' WHEN '5' THEN 'Private' " \
          "ELSE own_code END"
    nodes(f"""
        SELECT 'lmf:qcew:' || area_fips || ':' || own_code || ':' || industry_code || ':' || year,
               'LaborMarketFact',
               'QCEW ' || year || ' ' || area_fips || ' ' || {own} || ' ' || industry_code,
               area_fips,
               json_object('measure_family', 'qcew_annual', 'year', year, 'area_fips', area_fips,
                           'own_code', own_code, 'ownership', {own}, 'industry_code', industry_code,
                           'quarters', quarters, 'suppressed', suppressed,
                           'avg_employment', round(avg_emp, 1), 'total_wages', total_wages,
                           'avg_weekly_wage', CASE WHEN avg_emp > 0 THEN round(total_wages / avg_emp / 52, 0) END,
                           'avg_establishments', round(avg_estabs, 1))::VARCHAR,
               source_id, source_vintage
        FROM qcew_y""")
    edges(f"""
        SELECT 'lmf:qcew:' || area_fips || ':' || own_code || ':' || industry_code || ':' || year,
               {area_node('area_fips')}, 'ABOUT_GEOGRAPHY', NULL, NULL, NULL, source_id, source_vintage,
               'qcew_area_fips', 1.0, 'publisher_asserted', make_date(year::INT, 1, 1), make_date(year::INT + 1, 1, 1)
        FROM qcew_y""")
    edges("""
        SELECT 'lmf:qcew:' || area_fips || ':' || own_code || ':' || industry_code || ':' || year,
               'naics:' || industry_code, 'ABOUT_INDUSTRY', NULL, NULL, NULL, source_id, source_vintage,
               'qcew_industry_code', 1.0, 'publisher_asserted', make_date(year::INT, 1, 1), make_date(year::INT + 1, 1, 1)
        FROM qcew_y""")
    step("qcew_facts")

    nodes(f"""
        WITH q AS (
            SELECT *, row_number() OVER (ORDER BY year DESC, quarter DESC) AS recency
            FROM {c('qwi_higher_ed')} WHERE sex = '0' AND agegrp = 'A00')
        SELECT 'lmf:qwi:17:6113:' || year || 'q' || quarter, 'LaborMarketFact',
               'QWI Illinois NAICS 6113 ' || year || ' Q' || quarter, '17',
               json_object('measure_family', 'qwi_quarterly', 'year', year, 'quarter', quarter,
                           'quarter_start', quarter_start, 'ownercode', ownercode,
                           'employment', emp, 'stable_employment', emp_s, 'hires_all', hira,
                           'hires_new', hirn, 'separations', sep, 'turnover_rate_stable', turnovrs,
                           'avg_monthly_earnings_stable', earns, 's_emp', s_emp, 's_hir_a', s_hir_a,
                           's_sep', s_sep, 's_turn_ovr_s', s_turn_ovr_s, 's_earn_s', s_earn_s,
                           'provisional', recency <= 2)::VARCHAR,
               source_id, source_vintage
        FROM q""")
    edges(f"""
        SELECT 'lmf:qwi:17:6113:' || year || 'q' || quarter, 'fips:17', 'ABOUT_GEOGRAPHY', NULL, NULL,
               NULL, source_id, source_vintage, 'qwi_state_file', 1.0, 'publisher_asserted',
               quarter_start, quarter_start + INTERVAL 3 MONTH
        FROM {c('qwi_higher_ed')} WHERE sex = '0' AND agegrp = 'A00'""")
    edges(f"""
        SELECT 'lmf:qwi:17:6113:' || year || 'q' || quarter, 'naics:6113', 'ABOUT_INDUSTRY', NULL, NULL,
               NULL, source_id, source_vintage, 'qwi_state_file', 1.0, 'publisher_asserted',
               quarter_start, quarter_start + INTERVAL 3 MONTH
        FROM {c('qwi_higher_ed')} WHERE sex = '0' AND agegrp = 'A00'""")

    # IPEDS occupation groups and their SOC coverage.
    nodes(f"""
        SELECT DISTINCT 'ipedsocc:' || occupation_category_code, 'IPEDSOccupationGroup',
               occupation_category, occupation_category_code,
               json_object('survey', 'SAL_NIS')::VARCHAR, source_id, source_vintage
        FROM {c('ipeds_salary_noninstructional')}""")
    con.execute("CREATE TEMP TABLE ipeds_soc (grp VARCHAR, major VARCHAR, coverage VARCHAR, scope VARCHAR)")
    con.executemany("INSERT INTO ipeds_soc VALUES (?, ?, ?, ?)",
                    [(g, m, cov, sc) for g, (ms, cov, sc) in IPEDS_GROUP_TO_SOC.items() for m in ms])
    edges("""
        SELECT 'ipedsocc:' || grp, 'soc:' || major || '-0000', 'COVERS_SOC_GROUP', NULL, NULL,
               json_object('coverage', coverage, 'scope', scope)::VARCHAR,
               'ipeds', 'IPEDS HR occupational categories (SOC 2018 based)',
               'ipeds_occupation_category_definition', 1.0, 'curated_rule', NULL, NULL
        FROM ipeds_soc""")
    nodes(f"""
        SELECT 'lmf:ipeds_sal_nis:' || unitid || ':' || occupation_category_code, 'LaborMarketFact',
               'IPEDS ' || survey_year || ' ' || occupation_category || ' salaries, ' || unitid, unitid,
               json_object('measure_family', 'ipeds_salary_noninstructional',
                           'survey_year', survey_year, 'unitid', unitid,
                           'occupation_category_code', occupation_category_code,
                           'staff_count', staff_count, 'salary_outlays', salary_outlays,
                           'avg_salary', round(salary_outlays / staff_count, 0))::VARCHAR,
               source_id, source_vintage
        FROM {c('ipeds_salary_noninstructional')} WHERE staff_count > 0""")
    edges(f"""
        SELECT 'ipeds:' || unitid, 'lmf:ipeds_sal_nis:' || unitid || ':' || occupation_category_code,
               'HAS_FACT', NULL, NULL, NULL, source_id, source_vintage, 'ipeds_sal_nis', 1.0,
               'publisher_asserted', NULL, NULL
        FROM {c('ipeds_salary_noninstructional')} WHERE staff_count > 0""")
    edges(f"""
        SELECT 'lmf:ipeds_sal_nis:' || unitid || ':' || occupation_category_code,
               'ipedsocc:' || occupation_category_code, 'ABOUT_OCCUPATION_GROUP', NULL, NULL, NULL,
               source_id, source_vintage, 'ipeds_sal_nis', 1.0, 'publisher_asserted', NULL, NULL
        FROM {c('ipeds_salary_noninstructional')} WHERE staff_count > 0""")
    con.execute(f"""
        CREATE TEMP TABLE staff_tot AS
        SELECT unitid, any_value(survey_year) AS survey_year, any_value(snapshot_date) AS snapshot_date,
               max(staff_count) FILTER (WHERE staffcat_code = '1100') AS all_staff,
               max(staff_count) FILTER (WHERE staffcat_code = '2100') AS full_time,
               max(staff_count) FILTER (WHERE staffcat_code = '3100') AS part_time,
               any_value(source_id) AS source_id, any_value(source_vintage) AS source_vintage
        FROM {c('ipeds_staff_by_occupation')}
        WHERE staffcat_code IN ('1100', '2100', '3100') AND sex = 'Total' AND race_ethnicity = 'Total'
        GROUP BY unitid""")
    nodes("""
        SELECT 'lmf:ipeds_staff:' || unitid, 'LaborMarketFact', 'IPEDS Fall ' || survey_year ||
               ' staff total, ' || unitid, unitid,
               json_object('measure_family', 'ipeds_staff_total', 'survey_year', survey_year,
                           'snapshot_date', snapshot_date, 'all_staff', all_staff,
                           'full_time', full_time, 'part_time', part_time)::VARCHAR,
               source_id, source_vintage
        FROM staff_tot""")
    edges("""
        SELECT 'ipeds:' || unitid, 'lmf:ipeds_staff:' || unitid, 'HAS_FACT', NULL, NULL, NULL,
               source_id, source_vintage, 'ipeds_s_oc_grand_total', 1.0, 'publisher_asserted',
               snapshot_date, NULL
        FROM staff_tot""")
    step("qwi_and_ipeds_facts")

    # ------------------------------------------------------------------ AI usage evidence
    con.execute(f"""
        CREATE TEMP TABLE aei_t AS
        SELECT DISTINCT * FROM {c('aei_task_usage')}""")
    aei_rows = con.sql(f"SELECT count(*) FROM {c('aei_task_usage')}").fetchall()[0][0]
    aei_distinct = con.sql("SELECT count(*) FROM aei_t").fetchall()[0][0]
    con.execute(f"""
        CREATE TEMP TABLE aei_match AS
        SELECT a.*, 'aei:task:' || a.release || ':' || substr(md5(a.task_name), 1, 12) AS aei_id,
               t.task_id, count(*) OVER (PARTITION BY a.task_name, a.release) AS text_shared_by_tasks
        FROM aei_t a JOIN {c('onet_task_statement')} t ON lower(t.task) = a.task_name""")
    nodes("""
        SELECT DISTINCT aei_id, 'AIUsageEvidence', task_name, release,
               json_object('level', 'task', 'release', release, 'usage_pct', usage_pct,
                           'penetration', penetration, 'directive', directive,
                           'feedback_loop', feedback_loop, 'task_iteration', task_iteration,
                           'validation', validation, 'learning', learning, 'filtered', filtered,
                           'caveat', 'Observed Claude usage; not a forecast of job loss.')::VARCHAR,
               source_id, source_vintage
        FROM aei_match""")
    edges("""
        SELECT 'task:' || task_id, aei_id, 'HAS_AI_USAGE_EVIDENCE', release, NULL,
               json_object('text_shared_by_tasks', text_shared_by_tasks)::VARCHAR,
               source_id, source_vintage, 'exact_lowercase_task_text_match', 1.0, 'derived_rule',
               NULL, NULL
        FROM aei_match""")
    nodes(f"""
        SELECT 'aei:occ:' || soc_2018_code, 'AIUsageEvidence', title || ' (observed exposure)',
               soc_2018_code,
               json_object('level', 'occupation', 'observed_exposure', observed_exposure,
                           'caveat', 'Observed Claude usage; not a forecast of job loss.')::VARCHAR,
               source_id, source_vintage
        FROM {c('aei_occupation_exposure')}""")
    edges(f"""
        SELECT 'soc:' || soc_2018_code, 'aei:occ:' || soc_2018_code, 'HAS_AI_USAGE_EVIDENCE', NULL, NULL,
               NULL, source_id, source_vintage, 'aei_soc_2018_code', 1.0, 'publisher_asserted', NULL, NULL
        FROM {c('aei_occupation_exposure')}""")
    aei_unmatched = con.sql("""
        SELECT count(*) FROM aei_t a WHERE NOT EXISTS
            (SELECT 1 FROM aei_match m WHERE m.task_name = a.task_name AND m.release = a.release)""").fetchall()[0][0]
    step("ai_usage_evidence")

    # ------------------------------------------------------------------ finalize
    con.execute("""
        CREATE TEMP TABLE nodes AS
        SELECT node_id, node_type, label, code, props, source_id, source_vintage
        FROM nodes_raw ORDER BY node_type, node_id""")
    con.execute("""
        CREATE TEMP TABLE edges AS
        SELECT 'e:' || substr(md5(edge_type || '|' || src_id || '|' || dst_id || '|' || coalesce(qualifier, '')), 1, 20)
                   AS edge_id,
               src_id, dst_id, edge_type, weight, props, source_id, source_vintage, method,
               confidence, review_status, valid_from, valid_to
        FROM edges_raw ORDER BY edge_type, src_id, dst_id, qualifier""")
    step("finalize")

    GRAPH_DIR.mkdir(parents=True, exist_ok=True)
    for t in ("nodes", "edges"):
        con.execute(f"COPY {t} TO '{(GRAPH_DIR / (t + '.parquet')).as_posix()}' "
                    "(FORMAT parquet, COMPRESSION zstd)")
    step("write_parquet")

    q = lambda sql: con.sql(sql).fetchall()
    manifest = {
        "ontology_version": ONTOLOGY_VERSION,
        "built_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "duckdb_version": duckdb.__version__,
        "inputs": "data/lake/contract/*.parquet (contract v1.0) + data/lake/silver onet_* reference tables",
        "outputs": {t: {"path": f"data/lake/graph/{t}.parquet",
                        "bytes": (GRAPH_DIR / f"{t}.parquet").stat().st_size} for t in ("nodes", "edges")},
        "node_count": q("SELECT count(*) FROM nodes")[0][0],
        "edge_count": q("SELECT count(*) FROM edges")[0][0],
        "nodes_by_type": dict(q("SELECT node_type, count(*) FROM nodes GROUP BY 1 ORDER BY 1")),
        "edges_by_type": dict(q("SELECT edge_type, count(*) FROM edges GROUP BY 1 ORDER BY 1")),
        "edges_by_review_status": dict(q("SELECT review_status, count(*) FROM edges GROUP BY 1 ORDER BY 1")),
        "integrity": {
            "duplicate_node_ids": q("SELECT count(*) - count(DISTINCT node_id) FROM nodes")[0][0],
            "duplicate_edge_ids": q("SELECT count(*) - count(DISTINCT edge_id) FROM edges")[0][0],
            "dangling_edges": q("""SELECT count(*) FROM edges e WHERE e.src_id NOT IN (SELECT node_id FROM nodes)
                                   OR e.dst_id NOT IN (SELECT node_id FROM nodes)""")[0][0],
            "internal_node_types_present": q(
                "SELECT count(*) FROM nodes WHERE node_type IN " + str(INTERNAL_NODE_TYPES))[0][0],
        },
        "notes": {
            "aei_task_usage_rows": aei_rows,
            "aei_task_usage_exact_duplicate_rows_collapsed": aei_rows - aei_distinct,
            "aei_task_rows_without_onet_text_match": aei_unmatched,
            "technology_slug_collisions_hashed": sum(1 for v in slug_map.values() if "~" in v),
            "qcew_years": list(QCEW_YEARS),
        },
        "timings_seconds": timings,
    }
    manifest["timings_seconds"]["total"] = round(time.perf_counter() - t0, 3)
    return manifest


def main(argv=None) -> dict:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)
    log = (lambda *_: None) if args.quiet else print
    missing = [p for p in (CONTRACT, SILVER) if not p.exists()]
    if missing:
        sys.exit(f"Missing lake layer(s): {missing}. Run scripts/lake_build.py and scripts/lake_contract.py first.")
    log("Building workforce graph from", CONTRACT.relative_to(ROOT), "and", SILVER.relative_to(ROOT))
    con = duckdb.connect()
    manifest = build(con, log)
    MANIFEST.write_text(json.dumps(manifest, indent=2, default=str) + "\n")
    log(f"nodes={manifest['node_count']:,} edges={manifest['edge_count']:,} "
        f"total={manifest['timings_seconds']['total']}s -> {GRAPH_DIR.relative_to(ROOT)}")
    return manifest


if __name__ == "__main__":
    main()
