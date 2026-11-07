"""Run extract.sql and the extract validation gates.

Synthetic (this repository): the "EDW" is a DuckDB schema of views over the synthetic Parquet.
Real (approved machine only): run the same statements through a DB-API driver, or paste them into
the approved SQL client and save each result as <NAME>.parquet; then run `--validate-only`.

    python succession_models/extract.py                                  # synthetic -> runs/extract
    python succession_models/extract.py --engine dbapi --dbapi-module oracledb --dsn "<dsn>" --schema EDW_OWNER \
        --out /secure/path/extract                                       # approved machine (UNTESTED here)
    python succession_models/extract.py --validate-only --out /secure/path/extract
    python succession_models/extract.py --layout v3_cookbook --edw-dir sample_datasets/v3_cookbook/longitudinal \
        --extract-date 2027-01-31 --out runs/extract_v3                 # Cookbook-shaped synthetic pack
"""
from __future__ import annotations

import argparse
import datetime as dt
import importlib
import json
import re
import sys
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from config import (DATA_DIR, EXTRACT_DATE, HISTORY_START, LAYOUTS, OPEN_END, RUNS_DIR, SOURCE_MAP,  # noqa: E402
                    resolve_layout, v3_sql_tokens, write_json)

SQL_PATH = HERE / "extract.sql"
DEFAULT_OUT = RUNS_DIR / "extract"
IDENTITY_COLS = re.compile(r"(NAME|NATL|SSN|UIN|EMAIL|ADDR|ZIP|POSTAL|PHONE)", re.I)


def statements(sql_text: str, schema: str, history_start: dt.date, extract_date: dt.date,
               tokens: dict | None = None) -> list[tuple[str, str]]:
    """Split the SQL file into (name, statement) pairs with the tokens rendered.

    `tokens` are extra {{NAME}} -> text substitutions (the v3 layout switches); v1 passes none."""
    out = []
    for block in re.split(r"^-- @extract ", sql_text, flags=re.M)[1:]:
        name, body = block.split("\n", 1)
        body = body.strip().rstrip(";")
        body = (body.replace("{{SCHEMA}}", schema)
                .replace("{{HISTORY_START}}", f"DATE '{history_start.isoformat()}'")
                .replace("{{EXTRACT_DATE}}", f"DATE '{extract_date.isoformat()}'"))
        for k, v in (tokens or {}).items():
            body = body.replace("{{" + k + "}}", v)
        if "{{" in body:
            raise ValueError(f"unrendered token in {name}")
        out.append((name.strip(), body))
    return out


def layout_sql(source_map: dict = SOURCE_MAP) -> tuple[Path, dict]:
    """(SQL file, extra tokens) for a source map: extract.sql for v1, extract_v3_cookbook.sql + switch tokens for v3."""
    if source_map.get("layout", "v1") == "v1":
        return SQL_PATH, {}
    return HERE / source_map["sql"], v3_sql_tokens(source_map["switches"])


def run_duckdb(edw_dir: Path, out_dir: Path, schema: str = "edw", history_start=HISTORY_START,
               extract_date=EXTRACT_DATE, prepare=None, source_map: dict = SOURCE_MAP) -> dict:
    """Execute the layout's extract SQL against Parquet files exposed as views in a DuckDB schema."""
    sql_path, tokens = layout_sql(source_map)
    out_dir.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute(f"CREATE SCHEMA {schema}")
    for f in sorted(Path(edw_dir).glob("*.parquet")):
        con.execute(f"CREATE VIEW {schema}.{f.stem} AS SELECT * FROM read_parquet('{f.as_posix()}')")
    if prepare:
        prepare(con, schema)
    counts = {}
    for name, sql in statements(sql_path.read_text(), schema, history_start, extract_date, tokens):
        tbl = con.sql(sql).to_arrow_table()
        if hasattr(tbl, "read_all"):
            tbl = tbl.read_all()
        pq.write_table(tbl, out_dir / f"{name}.parquet", compression="zstd")
        counts[name] = tbl.num_rows
    src_manifest = Path(edw_dir) / "manifest.json"
    meta = json.loads(src_manifest.read_text()) if src_manifest.exists() else {}
    manifest = dict(synthetic=meta.get("synthetic", False), source=str(edw_dir),
                    extract_date=extract_date, history_start=history_start, row_counts=counts)
    if source_map.get("layout", "v1") != "v1":
        manifest.update(layout=source_map["layout"], sql=sql_path.name, switches=source_map["switches"])
    write_json(out_dir / "manifest.json", manifest)
    return counts


def run_dbapi(module: str, dsn: str, schema: str, out_dir: Path, source_map: dict = SOURCE_MAP,
              extract_date=EXTRACT_DATE) -> dict:  # pragma: no cover - approved machine
    """Generic DB-API path for the approved machine. UNTESTED in this repository (no EDW here)."""
    sql_path, tokens = layout_sql(source_map)
    mod = importlib.import_module(module)
    conn = mod.connect(dsn)
    out_dir.mkdir(parents=True, exist_ok=True)
    counts = {}
    for name, sql in statements(sql_path.read_text(), schema, HISTORY_START, extract_date, tokens):
        cur = conn.cursor()
        cur.execute(sql)
        cols = [d[0].upper() for d in cur.description]
        rows = cur.fetchall()
        tbl = pa.Table.from_pylist([dict(zip(cols, r)) for r in rows])
        pq.write_table(tbl, out_dir / f"{name}.parquet", compression="zstd")
        counts[name] = len(rows)
    manifest = dict(synthetic=False, source=f"dbapi:{module}", row_counts=counts, extract_date=extract_date)
    if source_map.get("layout", "v1") != "v1":
        manifest.update(layout=source_map["layout"], sql=sql_path.name, switches=source_map["switches"])
    write_json(out_dir / "manifest.json", manifest)
    return counts


def rec_cols_for(source_map: dict, logical: str) -> dict:
    """Transaction-time columns of one table: the per-table override (v3 term rows) or the shared pair."""
    return source_map["tables"][logical].get("rec_cols", source_map["rec_cols"])


def status_value(spec: dict, code: str) -> str:
    """Physical value of a canonical status code ('A' / 'T') for a table spec (v3 carries descriptions)."""
    return spec.get("status_values", {}).get(code, code)


def validate(out_dir: Path, source_map: dict = SOURCE_MAP) -> dict:
    """Validation gates (see run_real.md). Returns {gate: {status, detail}}; any FAIL blocks modelling."""
    out_dir = Path(out_dir)
    con = duckdb.connect()
    res: dict[str, dict] = {}

    def gate(name, ok, detail, warn=False):
        res[name] = {"status": "PASS" if ok else ("WARN" if warn else "FAIL"), "detail": detail}

    missing = []
    for logical, spec in source_map["tables"].items():
        f = out_dir / f"{spec['file']}.parquet"
        if not f.exists():
            if not spec.get("optional"):
                missing.append(spec["file"])
            continue
        have = set(pq.read_schema(f).names)
        need = set(spec["cols"].values())
        if source_map["bitemporal"] and logical not in ("ref_class", "ref_org", "ref_role", "protected"):
            need |= set(rec_cols_for(source_map, logical).values())
        if need - have:
            missing.append(f"{spec['file']}: {sorted(need - have)}")
    gate("G1_required_columns", not missing, missing or "all required files and columns present")

    leaked = []
    for f in out_dir.glob("*.parquet"):
        leaked += [f"{f.stem}.{c}" for c in pq.read_schema(f).names if IDENTITY_COLS.search(c)]
    gate("G2_no_identity_columns", not leaked, leaked or "no name / national-ID / address / ZIP columns extracted")
    if missing:
        return res

    t = source_map["tables"]
    job = (out_dir / f"{t['job']['file']}.parquet").as_posix()
    jc = t["job"]["cols"]
    active = status_value(t["job"], "A")
    open_lit = f"DATE '{OPEN_END.isoformat()}'"
    bad, n = con.execute(f"SELECT SUM(CASE WHEN {jc['eff_dt']} > COALESCE({jc['exp_dt']}, {open_lit}) THEN 1 ELSE 0 END), "
                         f"COUNT(*) FROM read_parquet('{job}')").fetchall()[0]
    gate("G3_interval_order", (bad or 0) <= 0.001 * n, f"{bad or 0} of {n} job rows have EFF_DT > EXP_DT (tolerance 0.1%)")

    if source_map["bitemporal"]:
        rs, re_ = rec_cols_for(source_map, "job")["rec_start"], rec_cols_for(source_map, "job")["rec_end"]
        inv, dup = con.execute(f"""
            WITH v AS (SELECT * FROM read_parquet('{job}'))
            SELECT (SELECT COUNT(*) FROM v WHERE {rs} >= COALESCE({re_}, {open_lit})),
                   (SELECT COUNT(*) FROM (SELECT {jc['pers_id']}, {jc['posn_nbr']}, {jc['eff_dt']}, {jc['status_cd']}, COUNT(*) c
                     FROM v WHERE COALESCE({re_}, {open_lit}) = {open_lit} GROUP BY 1,2,3,4 HAVING COUNT(*) > 1) d)""").fetchall()[0]
        gate("G4_row_versions", inv == 0 and dup == 0,
             f"{inv} versions with REC_START >= REC_END; {dup} keys with >1 current version")
        late, tot = con.execute(f"""
            SELECT SUM(CASE WHEN first_rec > eff + INTERVAL 30 DAY THEN 1 ELSE 0 END), COUNT(*) FROM (
              SELECT {jc['eff_dt']} eff, MIN({rs}) first_rec FROM read_parquet('{job}')
              GROUP BY {jc['pers_id']}, {jc['posn_nbr']}, {jc['eff_dt']}, {jc['status_cd']})""").fetchall()[0]
        res["I1_retro_keying_rate"] = {"status": "INFO", "detail": f"{late / max(tot, 1):.1%} of job rows were first recorded >30 days after their effective date"}
    else:
        gate("G4_row_versions", False, "no transaction-time columns: effective-only mode, residual leakage risk "
             "from retro-keyed corrections (see data_contract.md section 4)", warn=True)

    lo, hi = con.execute(f"SELECT MIN({jc['eff_dt']}), MAX({jc['eff_dt']}) FROM read_parquet('{job}')").fetchall()[0]
    years = (hi - lo).days / 365.25 if lo and hi else 0
    gate("G5_history_depth", years >= 8, f"{years:.1f} years of job history (need >= 8 for a 5-origin backtest)")

    role = (out_dir / f"{t['ref_role']['file']}.parquet").as_posix()
    rc = t["ref_role"]["cols"]
    cov, ncur = con.execute(f"""
        SELECT AVG(CASE WHEN r.{rc['class_cd']} IS NULL THEN 0 ELSE 1 END), COUNT(*)
        FROM read_parquet('{job}') j LEFT JOIN read_parquet('{role}') r ON j.{jc['class_cd']} = r.{rc['class_cd']}
        WHERE j.{jc['status_cd']} = '{active}' AND COALESCE(j.{jc['exp_dt']}, {open_lit}) = {open_lit}""").fetchall()[0]
    gate("G6_role_family_coverage", (cov or 0) >= 0.95, f"{(cov or 0):.1%} of open primary job rows map to a role family (need 95%)")

    multi = con.execute(f"""
        SELECT AVG(CASE WHEN c > 1 THEN 1 ELSE 0 END) FROM (
          SELECT {jc['pers_id']}, COUNT(DISTINCT {jc['posn_nbr']}) c FROM read_parquet('{job}')
          WHERE {jc['status_cd']} = '{active}' AND COALESCE({jc['exp_dt']}, {open_lit}) = {open_lit}
          {"AND COALESCE(" + rec_cols_for(source_map, 'job')['rec_end'] + ", " + open_lit + ") = " + open_lit if source_map['bitemporal'] else ""}
          GROUP BY 1)""").fetchall()[0][0]
    gate("G7_one_primary_job", (multi or 0) <= 0.01, f"{(multi or 0):.2%} of persons hold >1 open primary position (tolerance 1%)")
    write_json(out_dir / "extract_validation.json", res)
    return res


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--engine", choices=["duckdb", "dbapi"], default="duckdb")
    ap.add_argument("--edw-dir", type=Path, default=DATA_DIR)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--schema", default="edw")
    ap.add_argument("--dbapi-module")
    ap.add_argument("--dsn")
    ap.add_argument("--validate-only", action="store_true")
    ap.add_argument("--layout", choices=sorted(LAYOUTS), default=None,
                    help="source binding: v1 (default, also SUCC_LAYOUT) or v3_cookbook (Data Cookbook tables)")
    ap.add_argument("--extract-date", type=dt.date.fromisoformat, default=EXTRACT_DATE)
    a = ap.parse_args(argv)
    layout, smap, _ = resolve_layout(a.layout)
    if not a.validate_only:
        if a.engine == "duckdb":
            print("extract:", run_duckdb(a.edw_dir, a.out, a.schema, extract_date=a.extract_date, source_map=smap))
        else:
            print("extract:", run_dbapi(a.dbapi_module, a.dsn, a.schema, a.out, smap, a.extract_date))
    res = validate(a.out, smap)
    for k, v in res.items():
        print(f"  {v['status']:4s} {k}: {v['detail']}")
    if any(v["status"] == "FAIL" for v in res.values()):
        sys.exit(2)


if __name__ == "__main__":
    main()
