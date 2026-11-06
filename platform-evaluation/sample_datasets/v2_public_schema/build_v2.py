"""Build the v2 public-schema sample pack from the frozen v1 pack (deterministic, no randomness).

    cd platform-evaluation
    python sample_datasets/v2_public_schema/build_v2.py            # writes longitudinal/ and CLEAN/
    python sample_datasets/v2_public_schema/build_v2.py --check    # rebuild in a temp dir, compare content hashes

What it does, per set (v1 longitudinal and v1 quality/CLEAN; DEFECTS is not adapted):
  * renames tables/columns to the publicly documented EDW names in integration/edw_mapping_public.yaml
    (only where public evidence exists; unresolved columns keep their v1 name);
  * recodes code columns into public University of Illinois code domains
    (integration/edw_public_reference/code_domains.yaml) with a fixed one-to-one table (RECODES);
  * adds a few columns that public documents describe and that are derivable from v1 rows
    (current-record indicators, status descriptions, appointment percent, employee group, salary range);
  * adds _1 views and a public E-Class reference table.
Every v1 row is kept (same row counts), keys and synthetic identifiers are unchanged, and the v1 time
semantics hold: inclusive effective end dates, exclusive recorded end dates, 9999-12-31 open end.

Synthetic IDs (SYN*/SP*, Q/R/O position numbers) are deliberately NOT converted to the real University
formats (UIN, C/S/U/G + 5-digit position numbers) so they can never collide with real identifiers.
Nothing here comes from the Data Cookbook or from real EDW data.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

import duckdb
import yaml

HERE = Path(__file__).resolve().parent
PE_ROOT = HERE.parents[1]                               # platform-evaluation/
V1 = PE_ROOT / "sample_datasets" / "v1"
DOMAINS = PE_ROOT / "integration" / "edw_public_reference" / "code_domains.yaml"
SETS = {"longitudinal": "longitudinal", "CLEAN": "quality/CLEAN"}
OPEN_END = "9999-12-31"

# ----------------------------------------------------------------------------- one-to-one recodes
# (column family) -> {v1 value: v2 value}. Each map is injective, so the crosswalk inverts exactly.
ECLASS = {"C1": "CA", "A1": "BA", "F1": "AA", "G1": "GA"}
ECLASS_RULE = {
    "C1": "civil service salaried -> CA 'CS 75Hr/pay N/E Ben Elig' (non-exempt, 37.5 h/week)",
    "A1": "academic professional -> BA 'Acad/Pro 12mth Ben Elig'",
    "F1": "faculty -> AA 'Acad 9/12mth Ben Elig'",
    "G1": "graduate assistant -> GA 'Graduate Assistants'",
}
# v1 LOCAL classes -> five-character P-Classes built with the public structure (kb120569).
# Choices are illustrative but follow the character rules; NAAAA/LAAAA/AAAAA are verbatim KB examples.
PCLASS = {
    "AP01": ("RAJAA", "Coordinator - General Administration (synthetic)"),
    "AP02": ("SAMBA", "Specialist - IT Applications Analyst/Programmer (synthetic)"),
    "AP03": ("SACBA", "Specialist - Business and Finance Accounting (synthetic)"),
    "AP04": ("TAMTA", "Professional Title - IT Reporting/Data Management (synthetic)"),
    "AP05": ("RALGA", "Coordinator - HR Staffing/Recruitment (synthetic)"),
    "AP06": ("NFJAA", "Assistant Director - General Administration (synthetic)"),
    "AP07": ("NEPDA", "Associate Director - Research Administration (synthetic)"),
    "AP08": ("NAAAA", "Director (synthetic)"),
    "AP09": ("LEJAA", "Associate Dean - General Administration (synthetic)"),
    "AP10": ("LAAAA", "Dean (synthetic)"),
    "FA01": ("BAEAA", "OthAc 9-mo Lecturer (synthetic)"),
    "FA02": ("AACAA", "Tenur 9-mo Assistant Professor (synthetic)"),
    "FA03": ("AABAA", "Tenur 9-mo Associate Professor (synthetic)"),
    "FA04": ("AAAAA", "Tenur 9-mo Professors (synthetic)"),
    "FA05": ("AAAEA", "Tenur 9-mo Professors Endowed (synthetic)"),
    "GA01": ("CASAA", "Assistants 9-mo Grad Appt (synthetic)"),
    "OV01": ("BEEAA", "OthAc Non Service Lecturer - overload (synthetic)"),
}
TERM = {"RES": "TQ", "RET": "TR", "END": "TE"}
TERM_RULE = {"RES": "resignation -> TQ Employee Resigned", "RET": "retirement -> TR Retired (SURS annuitant)",
             "END": "end of appointment -> TE Terminated/Expired (public group: academic; no CS-specific end code exists)"}
PAYR_ID = {"MN": "MO"}          # kb120369: Pay ID Monthly (MO) or Biweekly (BW)
GROUP = {"CA": ("CS", "Civil Service"), "BA": ("AP", "Academic Professionals"),
         "AA": ("FA", "Faculty"), "GA": ("GA", "Grads and Pre Doc Fellows")}
JOB_STATUS_DESC = {"A": "Active", "T": "Terminated"}
POSN_STATUS_DESC = {"A": "Active", "I": "Inactive"}

# ----------------------------------------------------------------------------- renames (v1 -> v2)
TABLE_RENAME = {"REF_JOB_CLASS": "T_POSN_CLS_HIST"}
COL_RENAME = {
    "T_EMPEE_HIST": {"CAMPUS_CD": "HR_CAMPUS_CD"},
    "T_JOB_DETL_HIST": {"JOB_STATUS_CD": "JOB_DETL_STATUS_CD", "JOB_FTE": "JOB_DETL_FTE",
                        "JOB_ANNUAL_SAL_AMT": "JOB_DETL_ANNUAL_SAL", "JOB_CLS_CD": "POSN_CLS_CD",
                        "JOB_ECLS_CD": "JOB_DETL_EMPEE_CLS_CD"},
    "REF_JOB_CLASS": {"CLS_CD": "POSN_CLS_CD", "CLS_TITLE": "POSN_CLS_DESC"},
}
# column -> recode map applied to it (v1 table, v1 column)
VALUE_RECODES = {
    ("T_EMPEE_HIST", "EMPEE_CLS_CD"): ("ECLASS", ECLASS),
    ("T_JOB_DETL_HIST", "JOB_ECLS_CD"): ("ECLASS", ECLASS),
    ("REF_EMPEE_CLS", "ECLS_CD"): ("ECLASS", ECLASS),
    ("T_JOB_DETL_HIST", "JOB_CLS_CD"): ("PCLASS", {k: v[0] for k, v in PCLASS.items()}),
    ("T_POSN_HIST", "POSN_CLS_CD"): ("PCLASS", {k: v[0] for k, v in PCLASS.items()}),
    ("REF_JOB_CLASS", "CLS_CD"): ("PCLASS", {k: v[0] for k, v in PCLASS.items()}),
    ("REF_ROLE_FAMILY", "CLS_CD"): ("PCLASS", {k: v[0] for k, v in PCLASS.items()}),
    ("T_EMPEE_HIST_5", "TERM_REASON_CD"): ("TERM", TERM),
    ("T_PAYR_ACCTG_DETL", "PAYR_ID"): ("PAYR_ID", PAYR_ID),
}
COL_SOURCE = {   # public evidence for each v2 name / domain (source keys in edw_public_reference/sources.yaml)
    "EMPEE_CLS_CD": "kb120378", "JOB_DETL_EMPEE_CLS_CD": "rc2009", "ECLS_CD": "kb120378", "POSN_CLS_CD": "kb120569",
    "CLS_CD": "kb120569", "TERM_REASON_CD": "kb120385", "PAYR_ID": "kb120369", "POSN_CLS_DESC": "rc2009",
    "ECLS_DESC": "kb120378", "HR_CAMPUS_CD": "rc2009", "JOB_DETL_STATUS_CD": "rc2009", "JOB_DETL_FTE": "rc2009",
    "JOB_DETL_ANNUAL_SAL": "rc2009",
}


def q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def lit(v) -> str:
    return "NULL" if v is None else "'" + str(v).replace("'", "''") + "'"


def case_map(col: str, mapping: dict) -> str:
    """Recode known values; any other value passes through unchanged (keeps SUCSS codes)."""
    whens = " ".join(f"WHEN {q(col)} = {lit(k)} THEN {lit(v)}" for k, v in sorted(mapping.items()))
    return f"CASE {whens} ELSE {q(col)} END"


def public_eclass_rows() -> list[tuple]:
    dom = yaml.safe_load(DOMAINS.read_text(encoding="utf-8"))["e_class"]
    rows = []
    for group, codes in dom["groups"].items():
        for code, d in codes.items():
            rows.append((code, d["desc"], group, str(d["job_end_date"]), str(d["leave_category"]), "kb120378"))
    return rows


def public_eclass_desc() -> dict:
    return {r[0]: r[1] for r in public_eclass_rows()}


# ----------------------------------------------------------------------------- transforms
def transform_table(con, set_name: str, v1_table: str, cols: list[str], xw: list[dict]) -> tuple[str, str]:
    """Return (v2 table name, SELECT sql) for one v1 parquet registered as view v1_<table>."""
    v2_table = TABLE_RENAME.get(v1_table, v1_table)
    ren = COL_RENAME.get(v1_table, {})
    xw.append({"set": set_name, "change": "table_renamed" if v2_table != v1_table else "table_kept",
               "v1_table": v1_table, "v1_column": "", "v2_table": v2_table, "v2_column": "",
               "v1_value": "", "v2_value": "", "rule": "", "source_key": "rc2009" if v2_table == "T_POSN_CLS_HIST" else ""})
    sel = []
    desc = public_eclass_desc()
    for c in cols:
        new = ren.get(c, c)
        expr = q(c)
        rc = VALUE_RECODES.get((v1_table, c))
        if rc:
            fam, mp = rc
            expr = case_map(c, mp)
            present = {r[0] for r in con.execute(f"SELECT DISTINCT {q(c)} FROM v1_{v1_table}").fetchall()}
            for k, v in sorted(mp.items()):
                if k in present:
                    rule = (ECLASS_RULE.get(k) if fam == "ECLASS" else TERM_RULE.get(k) if fam == "TERM"
                            else PCLASS[k][1] if fam == "PCLASS" else "Pay ID Monthly")
                    xw.append({"set": set_name, "change": "value_recoded", "v1_table": v1_table, "v1_column": c,
                               "v2_table": v2_table, "v2_column": new, "v1_value": k, "v2_value": v,
                               "rule": rule, "source_key": COL_SOURCE.get(new, "")})
        # description columns recoded with their codes
        if (v1_table, c) == ("REF_JOB_CLASS", "CLS_TITLE"):
            expr = "CASE " + " ".join(f"WHEN CLS_CD = {lit(k)} THEN {lit(v[1])}" for k, v in sorted(PCLASS.items())) + f" ELSE {q(c)} END"
            titles = dict(con.execute("SELECT CLS_CD, CLS_TITLE FROM v1_REF_JOB_CLASS").fetchall())
            for k, v in sorted(PCLASS.items()):
                if k in titles:
                    xw.append({"set": set_name, "change": "value_recoded", "v1_table": v1_table, "v1_column": c,
                               "v2_table": v2_table, "v2_column": new, "v1_value": titles[k], "v2_value": v[1],
                               "rule": f"description of {k} -> {v[0]}", "source_key": "kb120569"})
        if (v1_table, c) == ("REF_EMPEE_CLS", "ECLS_DESC"):
            descs = dict(con.execute("SELECT ECLS_CD, ECLS_DESC FROM v1_REF_EMPEE_CLS").fetchall())
            expr = "CASE " + " ".join(f"WHEN ECLS_CD = {lit(k)} THEN {lit(desc[v])}" for k, v in sorted(ECLASS.items())) + f" ELSE {q(c)} END"
            for k, v in sorted(ECLASS.items()):
                if k in descs:
                    xw.append({"set": set_name, "change": "value_recoded", "v1_table": v1_table, "v1_column": c,
                               "v2_table": v2_table, "v2_column": c, "v1_value": descs[k], "v2_value": desc[v],
                               "rule": f"public description of {v}", "source_key": "kb120378"})
        if new != c:
            xw.append({"set": set_name, "change": "column_renamed", "v1_table": v1_table, "v1_column": c,
                       "v2_table": v2_table, "v2_column": new, "v1_value": "", "v2_value": "", "rule": "",
                       "source_key": COL_SOURCE.get(new, "")})
        sel.append(f"{expr} AS {q(new)}")

    def add(col: str, expr: str, rule: str, src: str):
        sel.append(f"{expr} AS {q(col)}")
        xw.append({"set": set_name, "change": "column_added", "v1_table": v1_table, "v1_column": "",
                   "v2_table": v2_table, "v2_column": col, "v1_value": "", "v2_value": "", "rule": rule, "source_key": src})

    rec = "ROW_REC_END_DT" in cols
    cur_filter = f"ROW_REC_END_DT >= DATE '{OPEN_END}'" if rec else "TRUE"
    if v1_table == "T_PERS_HIST":
        add("PERS_CUR_INFO_IND",
            f"CASE WHEN {cur_filter} AND row_number() OVER (PARTITION BY EDW_PERS_ID ORDER BY ({cur_filter}) DESC, "
            f"PERS_EFF_DT DESC, PERS_EXP_DT DESC, _rn DESC) = 1 THEN 'Y' ELSE 'N' END",
            "Y on the latest effective row among currently recorded rows of each person; N otherwise", "rc2009")
    if v1_table == "T_EMPEE_HIST":
        add("EMPEE_CUR_INFO_IND",
            f"CASE WHEN {cur_filter} AND row_number() OVER (PARTITION BY EDW_PERS_ID ORDER BY ({cur_filter}) DESC, "
            f"EMPEE_EFF_DT DESC, EMPEE_EXP_DT DESC, _rn DESC) = 1 THEN 'Y' ELSE 'N' END",
            "Y on the latest effective row among currently recorded rows of each person; N otherwise", "rc2009")
        add("ACTIVE_EMPEE_IND", "CASE WHEN EMPEE_STATUS_CD = 'T' THEN 'N' ELSE 'Y' END",
            "Y when Employee Status Code <> T (rc2009 active incl. leave)", "rc2009")
        add("COA_CD", "CASE CAMPUS_CD WHEN 'U1' THEN '1' WHEN 'U2' THEN '2' WHEN 'U3' THEN '4' WHEN 'U0' THEN '9' END",
            "home campus chart code from the synthetic campus (U1->1, U2->2, U3->4, U0->9; bridges.yaml synthetic assignment)", "kb118751")
    if v1_table == "T_JOB_DETL_HIST":
        add("JOB_DETL_STATUS_DESC", case_map("JOB_STATUS_CD", JOB_STATUS_DESC).replace("ELSE \"JOB_STATUS_CD\"", "ELSE NULL"),
            "A -> Active, T -> Terminated", "rc2009")
        add("JOB_DETL_APPT_PCT", "CAST(100 AS DECIMAL(6,2))", "100 (v1 has no appointment percent)", "rc2009")
        ec = case_map("JOB_ECLS_CD", ECLASS)
        add("EMPEE_GROUP_CD", "CASE " + " ".join(f"WHEN ({ec}) = {lit(k)} THEN {lit(v[0])}" for k, v in sorted(GROUP.items())) + " END",
            "from the job E-Class; values are the v1 group codes (real EMPEE_GROUP_CD values are not public)", "snip_rn_2010_09")
        add("EMPEE_GROUP_DESC", "CASE " + " ".join(f"WHEN ({ec}) = {lit(k)} THEN {lit(v[1])}" for k, v in sorted(GROUP.items())) + " END",
            "E-Class group heading in kb120378", "snip_rn_2010_09")
    if v1_table == "T_POSN_HIST":
        add("POSN_STATUS_DESC", case_map("POSN_STATUS_CD", POSN_STATUS_DESC).replace("ELSE \"POSN_STATUS_CD\"", "ELSE NULL"),
            "A -> Active, I -> Inactive", "rc2009")
        add("POSN_MIN_SAL", "(SELECT MIN_ANNUAL_AMT FROM v1_REF_JOB_CLASS r WHERE r.CLS_CD = t.POSN_CLS_CD)",
            "class range minimum of the position's class (synthetic ranges)", "rc2009")
        add("POSN_MAX_SAL", "(SELECT MAX_ANNUAL_AMT FROM v1_REF_JOB_CLASS r WHERE r.CLS_CD = t.POSN_CLS_CD)",
            "class range maximum of the position's class (synthetic ranges)", "rc2009")
    sql = f"SELECT {', '.join(sel)} FROM v1_{v1_table} t ORDER BY _rn"
    return v2_table, sql


def table_hash(con, table: str) -> str:
    h = hashlib.sha256()
    for row in con.execute(f"SELECT * FROM {q(table)} ORDER BY ALL").fetchall():
        h.update(repr(tuple(row)).encode())
    return h.hexdigest()


def build_set(set_name: str, out_root: Path, xw: list[dict]) -> dict:
    src = V1 / SETS[set_name]
    dst = out_root / set_name
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True)
    v1_tables = sorted(p.stem for p in src.glob("*.parquet"))
    db = dst / "sample.duckdb"
    con = duckdb.connect(str(db))
    for t in v1_tables:
        con.execute(f"CREATE TEMP VIEW v1_{t} AS SELECT *, file_row_number AS _rn "
                    f"FROM read_parquet({lit((src / (t + '.parquet')).as_posix())}, file_row_number = true)")
    manifest = {"set": set_name, "source": f"sample_datasets/v1/{SETS[set_name]}", "tables": {}, "views": {}}
    schema = {}
    for t in v1_tables:
        cols = [r[0] for r in con.execute(f"DESCRIBE SELECT * FROM v1_{t}").fetchall() if r[0] != "_rn"]
        v2, sql = transform_table(con, set_name, t, cols, xw)
        con.execute(f"CREATE TABLE {q(v2)} AS {sql}")
        n1 = con.execute(f"SELECT count(*) FROM v1_{t}").fetchone()[0]
        n2 = con.execute(f"SELECT count(*) FROM {q(v2)}").fetchone()[0]
        if n1 != n2:
            raise RuntimeError(f"{set_name}.{t}: row count changed {n1} -> {n2}")
        con.execute(f"COPY {q(v2)} TO {lit((dst / (v2 + '.parquet')).as_posix())} (FORMAT parquet)")
        manifest["tables"][v2] = {"v1_table": t, "rows": n2, "content_sha256": table_hash(con, v2)}
        schema[v2] = [{"name": r[0], "type": r[1]} for r in con.execute(f"DESCRIBE {q(v2)}").fetchall()]
    # public E-Class reference (all published codes)
    rows = public_eclass_rows()
    con.execute("CREATE TABLE REF_ECLS_PUBLIC (EMPEE_CLS_CD VARCHAR, EMPEE_CLS_DESC VARCHAR, EMPEE_CLS_GROUP VARCHAR, "
                "JOB_END_DATE_RULE VARCHAR, LEAVE_CATGRY_CD VARCHAR, SOURCE_KEY VARCHAR)")
    con.executemany("INSERT INTO REF_ECLS_PUBLIC VALUES (?, ?, ?, ?, ?, ?)", rows)
    con.execute(f"COPY (SELECT * FROM REF_ECLS_PUBLIC ORDER BY EMPEE_CLS_CD) TO {lit((dst / 'REF_ECLS_PUBLIC.parquet').as_posix())} (FORMAT parquet)")
    manifest["tables"]["REF_ECLS_PUBLIC"] = {"v1_table": None, "rows": len(rows), "content_sha256": table_hash(con, "REF_ECLS_PUBLIC")}
    schema["REF_ECLS_PUBLIC"] = [{"name": r[0], "type": r[1]} for r in con.execute("DESCRIBE REF_ECLS_PUBLIC").fetchall()]
    xw.append({"set": set_name, "change": "table_added", "v1_table": "", "v1_column": "", "v2_table": "REF_ECLS_PUBLIC",
               "v2_column": "", "v1_value": "", "v2_value": "", "rule": "all published E-Class codes", "source_key": "kb120378"})
    # _1 views (EDW reporting layer; the numeric suffix as a security tier is inferred, see README)
    views = {
        "V_EMPEE_HIST_1": "SELECT * FROM T_EMPEE_HIST",
        "V_JOB_DETL_HIST_1": "SELECT * FROM T_JOB_DETL_HIST",
        "V_EMPEE_PERS_HIST_1": "SELECT EDW_PERS_ID, PERS_EFF_DT, PERS_EXP_DT, PERS_CUR_INFO_IND FROM T_PERS_HIST",
    }
    for v, sql in views.items():
        con.execute(f"CREATE VIEW {v} AS {sql}")
        manifest["views"][v] = sql
        xw.append({"set": set_name, "change": "view_added" if not (v == "V_EMPEE_HIST_1" and set_name == "longitudinal") else "view_redefined",
                   "v1_table": "V_EMPEE_HIST_1" if (v == "V_EMPEE_HIST_1" and set_name == "longitudinal") else "",
                   "v1_column": "", "v2_table": v, "v2_column": "", "v1_value": "", "v2_value": "",
                   "rule": sql + ("; v1 view was a current-effective filter as of 2026-10-31, v2 is the full history "
                                  "(filter EMPEE_CUR_INFO_IND = 'Y')" if v == "V_EMPEE_HIST_1" and set_name == "longitudinal" else ""),
                   "source_key": "rc2009"})
    con.close()
    (dst / "schema.json").write_text(json.dumps(schema, indent=1) + "\n", encoding="utf-8")
    # same format as v1 schema_assumptions.json so mapping.check_schema_assumptions() can read it
    (dst / "schema_assumptions.json").write_text(json.dumps(schema, indent=1) + "\n", encoding="utf-8")
    (dst / "manifest.json").write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


XW_COLS = ["set", "change", "v1_table", "v1_column", "v2_table", "v2_column", "v1_value", "v2_value", "rule", "source_key"]


def build(out_root: Path = HERE) -> dict:
    xw: list[dict] = []
    out = {s: build_set(s, out_root, xw) for s in SETS}
    with open(out_root / "crosswalk_v1_to_v2.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=XW_COLS, lineterminator="\n")
        w.writeheader()
        w.writerows(xw)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="rebuild into a temp dir and compare content hashes")
    a = ap.parse_args(argv)
    if a.check:
        tmp = Path(tempfile.mkdtemp())
        try:
            new = build(tmp)
            bad = []
            for s, man in new.items():
                old = json.loads((HERE / s / "manifest.json").read_text(encoding="utf-8"))
                for t, v in man["tables"].items():
                    if old["tables"].get(t) != v:
                        bad.append(f"{s}.{t}")
            same_xw = (tmp / "crosswalk_v1_to_v2.csv").read_bytes() == (HERE / "crosswalk_v1_to_v2.csv").read_bytes()
            print("content identical" if not bad and same_xw else f"DIFFERENT: {bad} crosswalk_same={same_xw}")
            return 0 if not bad and same_xw else 1
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    out = build(HERE)
    for s, man in out.items():
        print(f"[{s}] " + ", ".join(f"{t}={v['rows']}" for t, v in man["tables"].items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
