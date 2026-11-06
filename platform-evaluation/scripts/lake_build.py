"""Build the public HR data lake: raw downloads -> typed silver Parquet -> gold SQL views.

    python scripts/lake_acquire.py     # first
    python scripts/lake_build.py       # this script
    python scripts/lake_build.py --only onet ipeds

Outputs (all excluded from Git except the manifest and DDL):
  data/lake/silver/<table>.parquet          one file per table, snake_case columns
  data/lake/hr_public.duckdb                DuckDB catalog: silver views + gold views
  lake/manifests/silver_manifest.json       row counts, schemas, source file hashes
  lake/ddl/{snowflake,databricks}_tables.sql  CREATE TABLE statements from the same schemas

Rules: raw files are read, never modified. Identifier/code columns are strings so
leading zeros survive (FIPS, NAICS, UNITID, SOC, class codes). Suppression and
imputation flags are retained as published, not converted to zero.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "lake" / "raw"
WORK = ROOT / "data" / "lake" / "_extract"
SILVER = ROOT / "data" / "lake" / "silver"
DB = ROOT / "data" / "lake" / "hr_public.duckdb"
MANIFEST = ROOT / "lake" / "manifests" / "silver_manifest.json"
DDL = ROOT / "lake" / "ddl"
GOLD_SQL = ROOT / "lake" / "gold" / "gold_views.sql"
ACQ = ROOT / "lake" / "manifests" / "acquisition_manifest.json"

RENAMES = {"o_net_soc_code": "onetsoc_code", "o_net_soc_2019_code": "onetsoc_code",
           "o_net_soc_2019_title": "onetsoc_title", "2018_soc_code": "soc_2018_code",
           "2018_soc_title": "soc_2018_title"}


def snake(name: str) -> str:
    s = name.strip().lstrip("﻿")
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s) if not s.isupper() else s
    s = re.sub(r"[^0-9a-zA-Z]+", "_", s).strip("_").lower()
    s = re.sub(r"_+", "_", s)
    return RENAMES.get(s, s) or "col"


class Builder:
    def __init__(self, con: duckdb.DuckDBPyConnection):
        self.con = con
        self.tables: dict[str, dict] = {}

    def write(self, table: str, select_sql: str, sources: list[Path], domain: str, note: str = ""):
        """Materialize a SELECT as silver Parquet with snake_case columns."""
        rel = self.con.sql(select_sql)
        cols = rel.columns
        seen: dict[str, int] = {}
        exprs = []
        for c in cols:
            n = snake(c)
            if n in seen:
                seen[n] += 1
                n = f"{n}_{seen[n]}"
            else:
                seen[n] = 0
            exprs.append(f'"{c}" AS "{n}"')
        out = SILVER / f"{table}.parquet"
        self.con.sql(f"COPY (SELECT {', '.join(exprs)} FROM ({select_sql})) TO '{out}' "
                     "(FORMAT parquet, COMPRESSION zstd)")
        desc = self.con.sql(f"DESCRIBE SELECT * FROM '{out}'").fetchall()
        n = self.con.sql(f"SELECT count(*) FROM '{out}'").fetchall()[0][0]
        self.tables[table] = {
            "domain": domain, "rows": n, "bytes": out.stat().st_size, "note": note,
            "columns": [{"name": d[0], "type": d[1]} for d in desc],
            "sources": sorted({p.relative_to(ROOT).as_posix() for p in sources}),
        }
        print(f"  {table:<44} {n:>10,} rows")


def unzip(zip_path: Path, dest: Path) -> list[Path]:
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(dest)
        return [dest / m for m in z.namelist() if not m.endswith("/")]


def q(p: Path) -> str:
    return str(p).replace("'", "''")


def varchar_types(f: Path, wanted: list[str], delim: str = ",") -> str:
    """DuckDB types= literal forcing the wanted columns that exist in the file header to VARCHAR."""
    import csv
    with f.open(encoding="utf-8-sig", newline="") as fh:
        header = next(csv.reader(fh, delimiter=delim))
    return "{" + ",".join(f"'{c}':'VARCHAR'" for c in header if c in wanted) + "}"


# ----------------------------------------------------------------------------- O*NET
def build_onet(b: Builder):
    zp = RAW / "onet_db_31_0" / "db_31_0_text.zip"
    files = unzip(zp, WORK / "onet")
    element_tables = []
    for f in sorted(files):
        if f.suffix != ".txt" or f.stem == "Read Me":
            continue
        table = "onet_" + snake(f.stem)
        header = f.open(encoding="utf-8-sig").readline().rstrip("\r\n").split("\t")
        id_cols = [c for c in header if c.endswith(("Code", "ID")) or c in ("Category", "Date")]
        types = "{" + ",".join(f"'{c}':'VARCHAR'" for c in id_cols) + "}"
        b.write(table, f"SELECT * FROM read_csv('{q(f)}', delim='\t', header=true, types={types}, "
                       f"quote='', strict_mode=false, sample_size=-1)", [zp], "onet", "O*NET 31.0 " + f.stem)
        cols = [c.lower() for c in b.con.sql(f"SELECT * FROM '{SILVER / (table + '.parquet')}' LIMIT 0").columns]
        if {"onetsoc_code", "element_id", "scale_id", "data_value"} <= set(cols) and "category" not in cols:
            element_tables.append((f.stem, table, set(cols)))
    # One long table of occupation x element ratings across all rating domains.
    optional = ["n", "standard_error", "lower_ci_bound", "upper_ci_bound", "recommend_suppress",
                "not_relevant", "date", "domain_source"]

    def pick(c, cols, cast):
        return f"TRY_CAST({c} AS {cast}) AS {c}_v" if c in cols else f"CAST(NULL AS {cast}) AS {c}_v"

    union = " UNION ALL ".join(
        f"SELECT '{snake(stem)}' AS domain, onetsoc_code, element_id, element_name, scale_id, "
        f"TRY_CAST(data_value AS DOUBLE) AS data_value, "
        + ", ".join(pick(c, cols, "DOUBLE" if c in ("n", "standard_error", "lower_ci_bound", "upper_ci_bound")
                         else "VARCHAR") for c in optional)
        + f" FROM '{SILVER / (t + '.parquet')}'" for stem, t, cols in element_tables)
    union = f"SELECT * RENAME ({', '.join(f'{c}_v AS {c}' for c in optional)}) FROM ({union})"
    b.write("onet_element_rating", union, [zp], "onet",
            "Long union of O*NET rating files: " + ", ".join(s for s, _, _ in element_tables))

    cw = RAW / "onet_soc_crosswalk" / "2019_to_SOC_Crosswalk.csv"
    b.write("onet_soc_crosswalk", f"SELECT * FROM read_csv('{q(cw)}', all_varchar=true)", [cw], "onet",
            "Official O*NET-SOC 2019 to SOC 2018 crosswalk")


# ----------------------------------------------------------------------------- IPEDS
def build_ipeds(b: Builder):
    import openpyxl  # dictionaries ship as xlsx

    labels, variables = [], []
    for zp in sorted((RAW / "ipeds").glob("*.zip")):
        files = unzip(zp, WORK / "ipeds" / zp.stem)
        survey = zp.stem.replace("_Dict", "").upper()
        for f in files:
            if f.suffix.lower() == ".csv":
                b.write("ipeds_" + survey.lower(),
                        f"SELECT * REPLACE (CAST(UNITID AS VARCHAR) AS UNITID) FROM read_csv('{q(f)}', "
                        "header=true, sample_size=-1, strict_mode=false)",
                        [zp], "ipeds", f"IPEDS {survey} as published (wide); X* columns are imputation flags")
            elif f.suffix.lower() == ".xlsx":
                wb = openpyxl.load_workbook(f, read_only=True)
                names = {ws.title.lower(): ws for ws in wb.worksheets}
                if "frequencies" in names:
                    for i, r in enumerate(names["frequencies"].iter_rows(values_only=True)):
                        if i and r[1]:
                            labels.append((survey, str(r[1]).upper(), str(r[2]).strip(), r[3]))
                if "varlist" in names:
                    for i, r in enumerate(names["varlist"].iter_rows(values_only=True)):
                        if i and r[1]:
                            variables.append((survey, str(r[1]).upper(), r[2], r[4], r[5], r[6]))
    b.con.sql("CREATE OR REPLACE TEMP TABLE _lab(survey VARCHAR, varname VARCHAR, codevalue VARCHAR, valuelabel VARCHAR)")
    b.con.executemany("INSERT INTO _lab VALUES (?,?,?,?)", labels)
    b.con.sql("CREATE OR REPLACE TEMP TABLE _var(survey VARCHAR, varname VARCHAR, data_type VARCHAR, "
              "format VARCHAR, imputation_var VARCHAR, var_title VARCHAR)")
    b.con.executemany("INSERT INTO _var VALUES (?,?,?,?,?,?)", variables)
    dicts = sorted((RAW / "ipeds").glob("*_Dict.zip"))
    b.write("ipeds_value_label", "SELECT * FROM _lab", dicts, "ipeds", "Code labels from IPEDS dictionaries")
    b.write("ipeds_variable", "SELECT * FROM _var", dicts, "ipeds", "Variable list from IPEDS dictionaries")


# ----------------------------------------------------------------------------- BLS QCEW
QCEW_TYPES = "{'area_fips':'VARCHAR','own_code':'VARCHAR','industry_code':'VARCHAR','agglvl_code':'VARCHAR'," \
             "'size_code':'VARCHAR','qtr':'VARCHAR','disclosure_code':'VARCHAR','lq_disclosure_code':'VARCHAR'," \
             "'oty_disclosure_code':'VARCHAR'}"


def build_qcew(b: Builder):
    for src, table, note in [("qcew_colleges", "qcew_colleges_annual", "NAICS 611310, all areas/ownerships, annual"),
                             ("qcew_il_counties", "qcew_il_county_annual", "Champaign/Cook/Sangamon, all industries, annual"),
                             ("qcew_colleges_qtr", "qcew_colleges_quarterly", "NAICS 611310, all areas/ownerships, quarterly"),
                             ("qcew_il_counties_qtr", "qcew_il_county_quarterly", "Champaign/Cook/Sangamon, all industries, quarterly")]:
        if not (RAW / src).exists():
            continue
        files = sorted((RAW / src).glob("*.csv"))
        glob = q(RAW / src) + "/*.csv"
        b.write(table, f"SELECT * FROM read_csv('{glob}', header=true, types={QCEW_TYPES}, union_by_name=true)",
                files, "bls_qcew", note)


# ----------------------------------------------------------------------------- Census QWI
QWI_TYPES = "{" + ",".join(f"'{c}':'VARCHAR'" for c in
                           ["periodicity", "seasonadj", "geo_level", "geography", "ind_level", "industry",
                            "ownercode", "sex", "agegrp", "race", "ethnicity", "education", "firmage",
                            "firmsize", "agg_level"]) + "}"


def build_qwi(b: Builder):
    for f in sorted((RAW / "qwi_il").glob("*.csv.gz")):
        table = "qwi_" + f.name.replace("qwi_", "").replace(".csv.gz", "").replace("_f_", "_").replace("_u", "")
        b.write(table, f"SELECT * FROM read_csv('{q(f)}', header=true, types={QWI_TYPES}, sample_size=-1)",
                [f], "census_qwi", "LEHD QWI Illinois " + f.name + "; s* columns are status flags")


# ----------------------------------------------------------------------------- Indeed, AEI, SUCSS
def build_misc(b: Builder):
    for f in sorted((RAW / "indeed_postings").glob("*.csv")):
        b.write("indeed_" + snake(f.stem), f"SELECT * FROM read_csv('{q(f)}', header=true, sample_size=-1)",
                [f], "indeed", "Indeed Hiring Lab index; not raw vacancy counts")
    for f in sorted((RAW / "anthropic_economic_index").glob("*.csv")):
        b.write("aei_" + snake(f.stem.split("__")[-1]),
                f"SELECT * FROM read_csv('{q(f)}', header=true, sample_size=-1, types={varchar_types(f, ['O*NET-SOC Code', 'Task ID', 'occ_code'])})",
                [f], "anthropic_economic_index", f.stem.split("__")[0] + "; observed Claude usage, not displacement")
    prep = ROOT / "data" / "prepared"
    b.write("sucss_class", f"SELECT * FROM read_json_auto('{q(prep / 'classes.jsonl')}')",
            [prep / "classes.jsonl"], "sucss", "Illinois SUCSS class catalog (acquired 2026-10-29)")
    b.write("sucss_onet_candidate", f"SELECT * FROM read_json_auto('{q(prep / 'mapping_review_queue.jsonl')}')",
            [prep / "mapping_review_queue.jsonl"], "sucss", "Unreviewed lexical title suggestions; not mappings")


# ----------------------------------------------------------------------------- BLS
def xlsx_to_csv(xlsx: Path, out: Path, sheet: str | None = None, header_match: str | None = None,
                extra: dict | None = None) -> Path:
    """Stream an xlsx sheet to CSV (all values as text), starting at the header row."""
    import csv
    import openpyxl
    wb = openpyxl.load_workbook(xlsx, read_only=True, data_only=True)
    ws = wb[sheet] if sheet else wb.worksheets[0]
    out.parent.mkdir(parents=True, exist_ok=True)
    extra = extra or {}
    with out.open("w", newline="") as fh:
        w = csv.writer(fh)
        started = header_match is None
        for row in ws.iter_rows(values_only=True):
            if not started:
                if row and any(isinstance(v, str) and header_match in v for v in row):
                    started = True
                else:
                    continue
                w.writerow([str(v).strip() if v is not None else "" for v in row] + list(extra))
                continue
            if started is True and header_match is None:
                started = "done"
                w.writerow([str(v).strip() if v is not None else "" for v in row] + list(extra))
                continue
            if row is None or all(v is None for v in row):
                continue
            w.writerow(["" if v is None else str(v) for v in row] + [str(v) for v in extra.values()])
    wb.close()
    return out


def build_bls(b: Builder):
    oews = RAW / "bls_oews"
    if not oews.exists():
        print("  (skipped: BLS files not acquired; set BLS_USER_AGENT and run lake_acquire.py)")
        return
    csvs = []
    # Full detail (area x industry x occupation) for the two latest panels.
    for yy in ("24", "25"):
        zp = oews / f"oesm{yy}all.zip"
        if not zp.exists():
            continue
        (x,) = [p for p in unzip(zp, WORK / "bls" / zp.stem) if p.suffix == ".xlsx"]
        csvs.append(xlsx_to_csv(x, WORK / "bls" / f"oews_all_20{yy}.csv", extra={"survey_year": f"20{yy}"}))
    if csvs:
        glob = q(WORK / "bls") + "/oews_all_*.csv"
        b.write("bls_oews_all", f"SELECT * FROM read_csv('{glob}', header=true, all_varchar=true, union_by_name=true)",
                [oews / f"oesm{y}all.zip" for y in ("24", "25") if (oews / f"oesm{y}all.zip").exists()], "bls_oews",
                "OEWS May estimates, all areas/industries/occupations; values as published text "
                "(* = not available, # = top-coded, ** = suppressed)")
    # National history 2015-2025 (occupation x year).
    nat = []
    for y in range(15, 26):
        zp = oews / f"oesm{y:02d}nat.zip"
        if not zp.exists():
            continue
        xs = [p for p in unzip(zp, WORK / "bls" / zp.stem) if p.suffix == ".xlsx" and "field" not in p.name.lower()]
        if xs:
            nat.append(xlsx_to_csv(xs[0], WORK / "bls" / "nat" / f"oews_nat_20{y:02d}.csv",
                                   extra={"survey_year": f"20{y:02d}"}))
    if nat:
        glob = q(WORK / "bls" / "nat") + "/*.csv"
        b.write("bls_oews_national_history",
                f"SELECT * FROM read_csv('{glob}', header=true, all_varchar=true, union_by_name=true)",
                [oews / f"oesm{y:02d}nat.zip" for y in range(15, 26) if (oews / f"oesm{y:02d}nat.zip").exists()],
                "bls_oews", "OEWS national May estimates 2015-2025; column names vary by year (union by name)")
    proj = RAW / "bls_projections" / "occupation.xlsx"
    if proj.exists():
        for sheet, table, note in [("Table 1.2", "bls_projections_occupation", "Employment Projections 2025-35, Table 1.2"),
                                   ("Table 1.10", "bls_projections_separations", "Employment Projections 2025-35, Table 1.10")]:
            c = xlsx_to_csv(proj, WORK / "bls" / f"{table}.csv", sheet=sheet, header_match="National Employment Matrix code")
            b.write(table, f"SELECT * FROM read_csv('{q(c)}', header=true, all_varchar=true)", [proj], "bls_projections", note)
    jt = RAW / "bls_jolts"
    if (jt / "jt.data.1.AllItems").exists():
        def tsv(f):
            return f"read_csv('{q(jt / f)}', delim='\\t', header=true, all_varchar=true)"
        b.write("bls_jolts", f"""
            SELECT trim(d.series_id) AS series_id, CAST(d.year AS INTEGER) AS year, trim(d.period) AS period,
                   TRY_CAST(trim(d.value) AS DOUBLE) AS value, trim(d.footnote_codes) AS footnote_codes,
                   s.seasonal, s.industry_code, i.industry_text, s.state_code, st.state_text, s.sizeclass_code,
                   s.dataelement_code, e.dataelement_text, s.ratelevel_code
            FROM {tsv('jt.data.1.AllItems')} d
            JOIN {tsv('jt.series')} s ON trim(s.series_id) = trim(d.series_id)
            LEFT JOIN {tsv('jt.industry')} i ON i.industry_code = s.industry_code
            LEFT JOIN {tsv('jt.state')} st ON st.state_code = s.state_code
            LEFT JOIN {tsv('jt.dataelement')} e ON e.dataelement_code = s.dataelement_code""",
                [jt / f for f in ("jt.data.1.AllItems", "jt.series", "jt.industry", "jt.state", "jt.dataelement")],
                "bls_jolts", "JOLTS monthly series with dimension labels; ratelevel L = level (thousands), R = rate")


STEPS = {"onet": build_onet, "ipeds": build_ipeds, "qcew": build_qcew, "qwi": build_qwi, "misc": build_misc,
         "bls": build_bls}

SF_TYPES = {"VARCHAR": "VARCHAR", "BIGINT": "NUMBER(19,0)", "INTEGER": "NUMBER(10,0)", "DOUBLE": "FLOAT",
            "DATE": "DATE", "BOOLEAN": "BOOLEAN", "TIMESTAMP": "TIMESTAMP_NTZ", "SMALLINT": "NUMBER(5,0)",
            "TINYINT": "NUMBER(3,0)", "FLOAT": "FLOAT", "HUGEINT": "NUMBER(38,0)"}
DBX_TYPES = {"VARCHAR": "STRING", "BIGINT": "BIGINT", "INTEGER": "INT", "DOUBLE": "DOUBLE", "DATE": "DATE",
             "BOOLEAN": "BOOLEAN", "TIMESTAMP": "TIMESTAMP_NTZ", "SMALLINT": "SMALLINT", "TINYINT": "TINYINT",
             "FLOAT": "FLOAT", "HUGEINT": "DECIMAL(38,0)"}


def map_type(t: str, table: dict) -> str:
    base = t.split("(")[0]
    if base == "DECIMAL":
        return {"sf": t.replace("DECIMAL", "NUMBER"), "dbx": t}
    return {"sf": SF_TYPES.get(base, "VARIANT"), "dbx": DBX_TYPES.get(base, "STRING")}


def write_ddl(tables: dict):
    DDL.mkdir(parents=True, exist_ok=True)
    hdr = "-- Generated by scripts/lake_build.py from data/lake/silver schemas. Do not edit by hand.\n"
    sf, dbx = [hdr + "-- Snowflake: run in the HR_PUBLIC schema, then COPY INTO ... MATCH_BY_COLUMN_NAME.\n"], \
              [hdr + "-- Databricks: run in <catalog>.hr_public, or use CREATE TABLE AS SELECT FROM parquet.\n"]
    for name, t in sorted(tables.items()):
        sf_cols = ",\n  ".join(f'"{c["name"].upper()}" {map_type(c["type"], t)["sf"]}' for c in t["columns"])
        dbx_cols = ",\n  ".join(f'`{c["name"]}` {map_type(c["type"], t)["dbx"]}' for c in t["columns"])
        comment = (t["note"] or "").replace("'", "''")
        sf.append(f"CREATE TABLE IF NOT EXISTS {name.upper()} (\n  {sf_cols}\n) COMMENT = '{comment}';\n")
        dbx.append(f"CREATE TABLE IF NOT EXISTS {name} (\n  {dbx_cols}\n) COMMENT '{comment}';\n")
    (DDL / "snowflake_tables.sql").write_text("\n".join(sf))
    (DDL / "databricks_tables.sql").write_text("\n".join(dbx))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", choices=list(STEPS))
    args = ap.parse_args(argv)
    SILVER.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    b = Builder(con)
    previous = json.loads(MANIFEST.read_text())["tables"] if MANIFEST.exists() and args.only else {}
    for step in args.only or STEPS:
        print(f"[{step}]")
        STEPS[step](b)
    tables = previous | b.tables

    acq = {f["path"]: f.get("sha256") for f in json.loads(ACQ.read_text())["files"]} if ACQ.exists() else {}
    for t in tables.values():
        t["source_sha256"] = {s: acq.get(s) or (hashlib.sha256((ROOT / s).read_bytes()).hexdigest()
                                                 if (ROOT / s).exists() else None) for s in t["sources"]}
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps({"built_at_utc": datetime.now(timezone.utc).isoformat(),
                                    "duckdb_version": duckdb.__version__, "tables": dict(sorted(tables.items()))},
                                   indent=1) + "\n")
    write_ddl(tables)

    # DuckDB catalog with silver views and gold views for local exploration.
    con.close()
    DB.unlink(missing_ok=True)
    db = duckdb.connect(str(DB))
    for name in tables:
        db.sql(f"CREATE VIEW {name} AS SELECT * FROM '{q(SILVER / (name + '.parquet'))}'")
    if GOLD_SQL.exists():
        db.sql(GOLD_SQL.read_text())
        print("gold views:", [r[0] for r in db.sql(
            "SELECT view_name FROM duckdb_views() WHERE NOT internal AND view_name LIKE 'gold_%'").fetchall()])
    db.close()
    print(f"{len(tables)} silver tables, "
          f"{sum(t['rows'] for t in tables.values()):,} rows, "
          f"{sum(t['bytes'] for t in tables.values()) / 1e6:.1f} MB parquet")
    return 0


if __name__ == "__main__":
    sys.exit(main())
