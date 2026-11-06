"""Canonical concept loader: the single switch point between physical layouts and the integration layer.

`edw_mapping.yaml` maps canonical concepts (person, employment, appointment, position, separation,
payroll line, job class, org, role family, employee class) to physical table.column names. This
module resolves that file against an actual data source and registers one canonical view per
concept (`c_<concept>`) in a DuckDB connection. Everything downstream reads only those views.

Environment variables
---------------------
HR_DATA_SOURCE      sample (default; alias: synthetic) | edw
HR_SAMPLE_PACK_PATH sample pack root (default: <platform-evaluation>/sample_datasets/v1)
HR_EDW_MAPPING      mapping file used when HR_DATA_SOURCE=edw (required for edw)
HR_EDW_DATA         duckdb file or parquet/jsonl directory holding the EDW-layout tables (edw only)

Canonical columns added by the loader
-------------------------------------
valid_from, valid_to   inclusive effective interval; open end normalized to 9999-12-31
known_from, known_to   recorded (transaction-time) interval, half-open [known_from, known_to);
                       0001-01-01 / 9999-12-31 when the source has no recorded-version columns
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
PE_ROOT = HERE.parent  # platform-evaluation/
DEFAULT_MAPPING = HERE / "edw_mapping.yaml"
OPEN_END = "9999-12-31"
MIN_DATE = "0001-01-01"
PROVENANCE_VALUES = {"assumed_synthetic_layout", "verified_dictionary"}
SQL_TYPES = {"varchar": "VARCHAR", "date": "DATE", "double": "DOUBLE", "integer": "INTEGER", "bigint": "BIGINT"}
TRANSFORMS = {"none", "percent_to_fraction", "trim", "yyyymmdd_to_date"}
# Concepts whose effective interval the loader normalizes (eff_date/exp_date -> valid_from/valid_to).
DATED = {"person", "employment", "appointment", "position"}


class MappingError(RuntimeError):
    pass


@dataclass
class Resolution:
    set_name: str
    location: str
    storage: str
    concepts: dict = field(default_factory=dict)   # concept -> report dict
    problems: list = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems

    def available(self, concept: str) -> bool:
        return self.concepts.get(concept, {}).get("status") == "resolved"

    def has_field(self, concept: str, fname: str) -> bool:
        f = self.concepts.get(concept, {}).get("fields", {}).get(fname)
        return bool(f and f.get("status") == "resolved")

    def to_dict(self) -> dict:
        return {"set": self.set_name, "storage": self.storage, "ok": self.ok,
                "problems": self.problems, "concepts": self.concepts}


# ----------------------------------------------------------------------------- loading
def data_source() -> str:
    src = os.environ.get("HR_DATA_SOURCE", "sample").strip().lower()
    if src == "synthetic":
        src = "sample"
    if src not in {"sample", "edw"}:
        raise MappingError(f"HR_DATA_SOURCE must be sample|edw, got {src!r}")
    return src


def mapping_path(path: str | Path | None = None) -> Path:
    if path:
        return Path(path)
    if data_source() == "edw":
        p = os.environ.get("HR_EDW_MAPPING")
        if not p:
            raise MappingError("HR_DATA_SOURCE=edw needs HR_EDW_MAPPING=<path to the verified edw_mapping.yaml>")
        return Path(p)
    return DEFAULT_MAPPING


def load_mapping(path: str | Path | None = None) -> dict:
    p = mapping_path(path)
    with open(p, encoding="utf-8") as fh:
        m = yaml.safe_load(fh)
    m["_path"] = str(p)
    _check_structure(m)
    return m


def _check_structure(m: dict) -> None:
    for key in ("concepts", "data", "conventions"):
        if key not in m:
            raise MappingError(f"mapping file lacks '{key}'")
    default_prov = m.get("default_provenance")
    for cname, c in m["concepts"].items():
        if "table" not in c or "fields" not in c:
            raise MappingError(f"concept {cname} needs table and fields")
        for fname, f in c["fields"].items():
            prov = f.get("provenance", default_prov)
            if prov not in PROVENANCE_VALUES:
                raise MappingError(f"{cname}.{fname}: provenance must be one of {sorted(PROVENANCE_VALUES)}")
            f["provenance"] = prov
            if f.get("type", "varchar") not in SQL_TYPES:
                raise MappingError(f"{cname}.{fname}: unknown type {f.get('type')}")
            if f.get("transform", "none") not in TRANSFORMS:
                raise MappingError(f"{cname}.{fname}: unknown transform {f.get('transform')}")
            if f.get("convention") not in (None, "inclusive", "exclusive"):
                raise MappingError(f"{cname}.{fname}: convention must be inclusive|exclusive")


def set_location(m: dict, set_name: str) -> tuple[Path, str]:
    """Return (location, storage) of one data set."""
    d = m["data"]
    storage = d.get("storage", "duckdb")
    if data_source() == "edw" and os.environ.get("HR_EDW_DATA"):
        loc = Path(os.environ["HR_EDW_DATA"])
        return loc, ("duckdb" if loc.suffix == ".duckdb" else storage)
    root = Path(os.environ.get("HR_SAMPLE_PACK_PATH", "") or d.get("pack_path", "."))
    if not root.is_absolute():
        root = PE_ROOT / root
    sets = d.get("sets") or {set_name: "."}
    if set_name not in sets:
        raise MappingError(f"unknown set {set_name!r}; mapping lists {sorted(sets)}")
    loc = root / sets[set_name]
    if storage == "duckdb":
        loc = loc / d.get("duckdb_file", "sample.duckdb")
    return loc, storage


def code_values(m: dict, key: str) -> list[str]:
    return [str(v) for v in m.get("code_values", {}).get(key, {}).get("values", [])]


def code_map(m: dict, key: str) -> dict:
    return {str(k): str(v) for k, v in m.get("code_values", {}).get(key, {}).get("map", {}).items()}


# ----------------------------------------------------------------------------- resolution
def _qi(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _ql(s: str) -> str:
    return "'" + str(s).replace("'", "''") + "'"


def _source_ref(con, loc: Path, storage: str, table: str) -> str | None:
    """SQL relation for a physical table, or None when it does not exist."""
    if storage == "duckdb":
        rows = con.execute(
            "SELECT 1 FROM information_schema.tables WHERE table_catalog = 'src' AND table_name = ?",
            [table]).fetchall()
        return f"src.main.{_qi(table)}" if rows else None
    if storage == "parquet":
        p = loc / f"{table}.parquet"
        return f"read_parquet({_ql(p.as_posix())})" if p.exists() else None
    if storage == "jsonl":
        p = loc / f"{table}.jsonl"
        if not p.exists():
            return None
        # every value as text, exactly as the pack stores it
        return f"read_json({_ql(p.as_posix())}, format='newline_delimited', auto_detect=true, all_varchar=true)" \
            if _supports_all_varchar(con) else \
            f"read_json({_ql(p.as_posix())}, format='newline_delimited', auto_detect=true)"
    raise MappingError(f"unknown storage {storage}")


def _supports_all_varchar(con) -> bool:
    try:
        con.execute("SELECT * FROM read_json('[]', format='array', all_varchar=true) LIMIT 0")
        return True
    except Exception:
        return False


def _columns(con, ref: str) -> dict[str, str]:
    rows = con.execute(f"DESCRIBE SELECT * FROM {ref}").fetchall()
    return {r[0]: r[1] for r in rows}


def _expr(col: str, f: dict) -> str:
    """Canonical SQL expression for one physical column."""
    t = SQL_TYPES[f.get("type", "varchar")]
    tr = f.get("transform", "none")
    src = _qi(col)
    if tr == "trim":
        src = f"trim(CAST({src} AS VARCHAR))"
    if tr == "yyyymmdd_to_date":
        return f"try_strptime(CAST({src} AS VARCHAR), '%Y%m%d')::DATE"
    if tr == "percent_to_fraction":
        return f"(TRY_CAST({src} AS DOUBLE) / 100.0)"
    if t == "VARCHAR":
        return f"CAST({src} AS VARCHAR)"
    return f"TRY_CAST({src} AS {t})"


def resolve(con, m: dict, set_name: str, strict: bool = True) -> Resolution:
    """Validate the mapping against the physical schema of one set and register canonical views.

    Creates DuckDB views `c_<concept>` for every resolved concept. Required concepts/fields that do
    not resolve are reported in `Resolution.problems`; with strict=True that raises MappingError.
    Restricted fields (role: restricted) are validated but never exposed in canonical views.
    """
    loc, storage = set_location(m, set_name)
    res = Resolution(set_name=set_name, location=str(loc), storage=storage)
    if storage == "duckdb":
        if not loc.exists():
            raise MappingError(f"data file not found: {loc}")
        attached = {r[0] for r in con.execute("SELECT database_name FROM duckdb_databases()").fetchall()}
        if "src" in attached:
            con.execute("DETACH src")
        con.execute(f"ATTACH {_ql(loc.as_posix())} AS src (READ_ONLY)")
    elif not loc.exists():
        raise MappingError(f"data folder not found: {loc}")

    conv = m["conventions"]
    for cname, c in m["concepts"].items():
        rep = {"table": c["table"], "optional": bool(c.get("optional")), "fields": {}}
        ref = _source_ref(con, loc, storage, c["table"])
        if ref is None:
            rep["status"] = "absent_optional" if c.get("optional") else "missing_required"
            if not c.get("optional"):
                res.problems.append(f"{cname}: table {c['table']} not found")
            res.concepts[cname] = rep
            continue
        cols = _columns(con, ref)
        select = []
        missing_required = []
        for fname, f in c["fields"].items():
            col = f["column"]
            fr = {"column": col, "provenance": f["provenance"], "type": f.get("type", "varchar")}
            if col in cols:
                fr["status"] = "resolved"
                fr["physical_type"] = cols[col]
                if f.get("role") != "restricted":
                    select.append((fname, _expr(col, f)))
            elif f.get("optional"):
                fr["status"] = "absent_optional"
                if f.get("role") != "restricted":
                    select.append((fname, f"CAST(NULL AS {SQL_TYPES[f.get('type', 'varchar')]})"))
            else:
                fr["status"] = "missing_required"
                missing_required.append(fname)
            rep["fields"][fname] = fr
        if missing_required:
            rep["status"] = "missing_required"
            res.problems.append(f"{cname}: columns not found for {missing_required} in {c['table']}")
            res.concepts[cname] = rep
            continue
        rep["status"] = "resolved"
        rep["physical_columns"] = len(cols)
        exprs = [f"{e} AS {_qi(n)}" for n, e in select]
        names = [n for n, _ in select]
        # normalized effective interval
        if cname in DATED and "eff_date" in names and "exp_date" in names:
            fx = c["fields"]["exp_date"]
            open_end = fx.get("open_end", conv.get("open_end", OPEN_END))
            exp_conv = fx.get("convention", conv.get("effective_end", "inclusive"))
            exp = dict(select)["exp_date"]
            norm = f"CASE WHEN {exp} IS NULL OR {exp} >= DATE {_ql(open_end)} THEN DATE '{OPEN_END}' "
            norm += (f"ELSE CAST({exp} - INTERVAL 1 DAY AS DATE) END" if exp_conv == "exclusive" else f"ELSE {exp} END")
            exprs.append(f"{dict(select)['eff_date']} AS valid_from")
            exprs.append(f"{norm} AS valid_to")
            rep["effective_end_convention"] = exp_conv
        if "recorded_start" in names:
            fs, fe = c["fields"].get("recorded_start", {}), c["fields"].get("recorded_end", {})
            has_rec = rep["fields"]["recorded_start"]["status"] == "resolved" and \
                rep["fields"].get("recorded_end", {}).get("status") == "resolved"
            rep["has_recorded_time"] = has_rec
            if has_rec:
                rs, re_ = dict(select)["recorded_start"], dict(select)["recorded_end"]
                rec_conv = fe.get("convention", conv.get("recorded_end", "exclusive"))
                open_end = fe.get("open_end", conv.get("open_end", OPEN_END))
                end = f"CASE WHEN {re_} IS NULL OR {re_} >= DATE {_ql(open_end)} THEN DATE '{OPEN_END}' "
                end += (f"ELSE CAST({re_} + INTERVAL 1 DAY AS DATE) END" if rec_conv == "inclusive" else f"ELSE {re_} END")
                exprs.append(f"COALESCE({rs}, DATE '{MIN_DATE}') AS known_from")
                exprs.append(f"{end} AS known_to")
            else:
                exprs.append(f"DATE '{MIN_DATE}' AS known_from")
                exprs.append(f"DATE '{OPEN_END}' AS known_to")
            _ = fs
        con.execute(f"CREATE OR REPLACE TEMP VIEW c_{cname} AS SELECT {', '.join(exprs)} FROM {ref}")
        res.concepts[cname] = rep
    if strict and res.problems:
        raise MappingError(f"mapping {m['_path']} does not resolve on {set_name}: {res.problems}")
    return res


def check_schema_assumptions(m: dict, set_name: str) -> dict:
    """Compare mapped columns with the set's published schema_assumptions.json (sample pack only).

    Returns {"checked": n, "mismatches": [...], "file": path}. A mismatch is a mapped, non-optional
    column that the published schema does not list for that table.
    """
    import json
    loc, storage = set_location(m, set_name)
    folder = loc.parent if storage == "duckdb" else loc
    f = folder / "schema_assumptions.json"
    if not f.exists():
        return {"checked": 0, "mismatches": [], "file": None}
    schema = json.loads(f.read_text(encoding="utf-8"))
    out = {"checked": 0, "mismatches": [], "file": str(f)}
    for cname, c in m["concepts"].items():
        cols = {x["name"] for x in schema.get(c["table"], [])}
        if not cols:
            if not c.get("optional"):
                out["mismatches"].append(f"{cname}: table {c['table']} not in schema_assumptions")
            continue
        for fname, fd in c["fields"].items():
            out["checked"] += 1
            if fd["column"] not in cols and not fd.get("optional"):
                out["mismatches"].append(f"{cname}.{fname}: {c['table']}.{fd['column']} not in schema_assumptions")
    return out


def validate_all(m: dict | None = None) -> dict:
    """Resolve the mapping against every listed set (fresh connection each) and return reports."""
    import duckdb
    m = m or load_mapping()
    out = {}
    for s in (m["data"].get("sets") or {}):
        con = duckdb.connect()
        try:
            out[s] = resolve(con, m, s, strict=False).to_dict()
        finally:
            con.close()
    return out


if __name__ == "__main__":  # pragma: no cover
    import json
    print(json.dumps(validate_all(), indent=1))
