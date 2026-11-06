"""Shared paths, parameters and SQL rendering for the ERP conversion-readiness toolkit.

Everything here is platform-neutral: rules are written in a portable ANSI subset
against *logical* staging views (stg_*, ref_*). `source_map.yaml` binds those views
to physical EDW tables, and `render_sql` fills the few dialect-specific tokens.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
PE_ROOT = HERE.parent                                   # platform-evaluation/
RULES_DIR = HERE / "rules"
CATALOG_PATH = RULES_DIR / "catalog.yaml"
SOURCE_MAP_PATH = RULES_DIR / "source_map.yaml"
TOLERANCES_PATH = HERE / "reconciliation" / "tolerances.yaml"
DATA_DIR = HERE / "data" / "synthetic"                  # git-ignored, regenerable
RUNS_DIR = HERE / "runs"                                # git-ignored, regenerable
HTML_OUT = PE_ROOT / "output" / "erp_readiness" / "readiness_dashboard.html"
SUCSS_CLASSES = PE_ROOT / "data" / "prepared" / "classes.jsonl"   # public catalog, read-only

AS_OF = dt.date(2026, 10, 31)          # extract / business date of the synthetic EDW snapshot
OPEN_END = dt.date(9999, 12, 31)       # open-ended *_EXP_DT convention assumed for the EDW
DEFAULT_SEED = 20261106
MOCK_CYCLES = {                        # mock conversion -> share of baseline defects still present
    "M1": 1.0, "M2": 0.55, "M3": 0.25, "M4": 0.08,
}
CLEAN_LABEL = "CLEAN"

DIALECTS = ("duckdb", "snowflake", "databricks", "oracle")


def params(as_of: dt.date = AS_OF) -> dict[str, dt.date]:
    """Date parameters used by rules. Computed in Python so the SQL holds only literals."""
    return {
        "AS_OF": as_of,
        "FUTURE_HORIZON": as_of + dt.timedelta(days=180),     # pending actions beyond this look like keying errors
        "ORPHAN_LOOKBACK": as_of - dt.timedelta(days=730),     # 24 months without an incumbent
        "PAY_WINDOW_START": as_of - dt.timedelta(days=730),
    }


def date_literal(d: dt.date) -> str:
    # ANSI DATE literal: accepted by DuckDB, Snowflake, Databricks SQL and Oracle.
    return f"DATE '{d.isoformat()}'"


def add_one_day(expr: str, dialect: str) -> str:
    """Only dialect-specific date arithmetic in the toolkit; used by staging views."""
    return {
        "duckdb": f"CAST({expr} + INTERVAL 1 DAY AS DATE)",
        "snowflake": f"DATEADD(day, 1, {expr})",
        "databricks": f"date_add({expr}, 1)",
        "oracle": f"({expr} + 1)",
    }[dialect]


def render_sql(sql: str, dialect: str = "duckdb", as_of: dt.date = AS_OF) -> str:
    out = sql
    for k, v in params(as_of).items():
        out = out.replace("{{" + k + "}}", date_literal(v))
    # Oracle accepts recursive subquery factoring but not the RECURSIVE keyword.
    out = out.replace("{{WITH_RECURSIVE}}", "WITH" if dialect == "oracle" else "WITH RECURSIVE")
    if "{{" in out:
        raise ValueError(f"unrendered token in SQL: {out[out.index('{{'):][:40]}")
    return out


def load_yaml(path: Path) -> dict:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_catalog() -> dict:
    return load_yaml(CATALOG_PATH)


def staging_sql(source_map: dict, dialect: str = "duckdb") -> list[tuple[str, str]]:
    """Build CREATE VIEW statements for logical stg_/ref_ views from source_map.yaml."""
    stmts = []
    open_end = date_literal(OPEN_END)
    schema = source_map.get("physical_schema")
    qual = (lambda t: f"{schema}.{t}") if schema else (lambda t: t)
    for view, spec in source_map["views"].items():
        cols = []
        for logical, physical in spec["columns"].items():
            cols.append(f"{physical} AS {logical}")
        if spec.get("interval"):
            iv = spec["interval"]
            eff, exp = iv["eff"], iv["exp"]
            if iv.get("end", "inclusive") != "inclusive":
                # Rules assume inclusive *_EXP_DT. If the real EDW turns out to be end-exclusive,
                # normalise here (exp - 1 day) rather than touching any rule.
                raise NotImplementedError(f"{view}: only inclusive-end intervals are wired up; confirm EDW convention")
            exp_expr = f"COALESCE({exp}, {open_end})"
            cols.append(f"{exp_expr} AS exp_dt")
            cols.append(f"CASE WHEN {exp_expr} >= {open_end} THEN {open_end} ELSE {add_one_day(exp_expr, dialect)} END AS exp_next_dt")
        sql = f"CREATE OR REPLACE VIEW {view} AS SELECT {', '.join(cols)} FROM {qual(spec['table'])}"
        stmts.append((view, sql))
    return stmts


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=2, sort_keys=True, default=str)
        fh.write("\n")
