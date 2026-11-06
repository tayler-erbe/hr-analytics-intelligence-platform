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

Recorded-time modes (concept key `recorded_time.mode`; default `interval`)
----------------------------------------------------------------------------
interval      recorded_start/recorded_end columns (v1/v2 ROW_REC_START_DT/ROW_REC_END_DT).
lineage_next  Data Cookbook pattern for history tables with a history-effective date in the key
              (T_JOB_DETL_HIST: JOB_DETL_HIST_EFF_DT). known_from = recorded_start; known_to = the next
              recorded_start in the same primary-key lineage (`lineage`: the key without the history
              date), or the open end. A row whose `deleted_field` holds a `deleted_values` code ('D') is
              known until its `deleted_end_field` (the post date: when EDW recorded the deletion).
post_date     Tables updated in place with only a post date (T_EMPEE_HIST, T_POSN_HIST, T_PERS_HIST):
              known_from = post_date (when the row now stored was written); deleted rows are known from
              their effective date until their post date. Earlier versions of an updated row are not
              recoverable from such a table.

Derived fields (field key `derive`, list tried in order; first non-NULL wins, then the column itself
when `fallback_to_column: true`)
  - {column: X, when_matches: '<regex>'}                      another column of the same row
  - {lookup: {table, key, value, when_matches?}}              value from a reference table, joined on
                                                              key = this field's column; the key must be
                                                              unique (checked) so rows never multiply
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
# Roles whose fields are validated but never exposed in canonical views.
RESTRICTED_ROLES = {"restricted", "restricted_fairness_only"}
RECORDED_MODES = {"interval", "lineage_next", "post_date"}
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
            for d in f.get("derive", []) or []:
                if not (("column" in d) ^ ("lookup" in d)):
                    raise MappingError(f"{cname}.{fname}: each derive entry needs exactly one of column|lookup")
                if "lookup" in d and not {"table", "key", "value"} <= set(d["lookup"]):
                    raise MappingError(f"{cname}.{fname}: lookup needs table, key and value")
        rt = c.get("recorded_time")
        if rt is not None:
            mode = rt.get("mode", "interval")
            if mode not in RECORDED_MODES:
                raise MappingError(f"{cname}: recorded_time.mode must be one of {sorted(RECORDED_MODES)}")
            need = {"lineage_next": ["recorded_start"], "post_date": ["post_date"]}.get(mode, [])
            for fn in need + list(rt.get("lineage", [])) + ([rt["deleted_field"]] if rt.get("deleted_field") else []):
                if fn not in c["fields"]:
                    raise MappingError(f"{cname}: recorded_time refers to unknown field {fn}")
            if mode == "lineage_next" and not rt.get("lineage"):
                raise MappingError(f"{cname}: lineage_next needs a lineage (key fields without the history date)")


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
    src = "s." + _qi(col)
    if tr == "trim":
        src = f"trim(CAST({src} AS VARCHAR))"
    if tr == "yyyymmdd_to_date":
        return f"try_strptime(CAST({src} AS VARCHAR), '%Y%m%d')::DATE"
    if tr == "percent_to_fraction":
        return f"(TRY_CAST({src} AS DOUBLE) / 100.0)"
    if t == "VARCHAR":
        return f"CAST({src} AS VARCHAR)"
    return f"TRY_CAST({src} AS {t})"


def _derive(con, loc: Path, storage: str, cols: dict, col: str, f: dict, fname: str, n_joins: int):
    """SQL for a derived field: COALESCE over same-row columns and reference-table lookups."""
    parts, joins, problems, rep = [], [], [], []
    for i, d in enumerate(f["derive"]):
        if "column" in d:
            other = d["column"]
            if other not in cols:
                rep.append({"column": other, "status": "absent"})
                continue
            e = f"CAST(s.{_qi(other)} AS VARCHAR)"
            if d.get("when_matches"):
                e = f"CASE WHEN regexp_full_match({e}, {_ql(d['when_matches'])}) THEN {e} END"
            parts.append(e)
            rep.append({"column": other, "status": "resolved", "when_matches": d.get("when_matches")})
            continue
        lk = d["lookup"]
        lref = _source_ref(con, loc, storage, lk["table"])
        if lref is None:
            rep.append({"lookup": lk["table"], "status": "absent"})
            continue
        lcols = _columns(con, lref)
        if lk["key"] not in lcols or lk["value"] not in lcols:
            problems.append(f"lookup {lk['table']} lacks {lk['key']} or {lk['value']}")
            continue
        k, v = _qi(lk["key"]), _qi(lk["value"])
        where = f"WHERE regexp_full_match(CAST({v} AS VARCHAR), {_ql(lk['when_matches'])})" if lk.get("when_matches") else \
            f"WHERE {v} IS NOT NULL"
        sub = (f"SELECT CAST({k} AS VARCHAR) AS k, min(CAST({v} AS VARCHAR)) AS v, count(DISTINCT {v}) AS n "
               f"FROM {lref} {where} GROUP BY 1")
        nmax = con.execute(f"SELECT coalesce(max(n), 0) FROM ({sub})").fetchone()[0]
        if nmax > 1:
            problems.append(f"lookup {lk['table']}.{lk['key']} -> {lk['value']} is not unique (max {nmax} values per key)")
        alias = f"lk{n_joins + len(joins)}"
        joins.append(f"LEFT JOIN ({sub}) AS {alias} ON {alias}.k = CAST(s.{_qi(col)} AS VARCHAR)")
        parts.append(f"{alias}.v")
        rep.append({"lookup": lk["table"], "key": lk["key"], "value": lk["value"], "status": "resolved",
                    "when_matches": lk.get("when_matches")})
    if f.get("fallback_to_column", True):
        parts.append(f"CAST(s.{_qi(col)} AS VARCHAR)")
    expr = f"coalesce({', '.join(parts)})" if parts else "CAST(NULL AS VARCHAR)"
    t = SQL_TYPES[f.get("type", "varchar")]
    if t != "VARCHAR":
        expr = f"TRY_CAST({expr} AS {t})"
    return expr, joins, problems, rep


def _recorded_exprs(sel: dict, c: dict, rt: dict, mode: str, rep: dict) -> list[str]:
    """known_from / known_to for the lineage_next and post_date modes (see module docstring)."""
    deleted = "FALSE"
    if rt.get("deleted_field") and rt["deleted_field"] in sel:
        vals = ", ".join(_ql(v) for v in rt.get("deleted_values", ["D"]))
        deleted = f"coalesce({sel[rt['deleted_field']]} IN ({vals}), FALSE)"
    end_field = rt.get("deleted_end_field", "post_date")
    del_end = sel.get(end_field, f"DATE '{OPEN_END}'")
    if mode == "lineage_next":
        start = sel["recorded_start"]
        part = ", ".join(sel[k] for k in rt["lineage"])
        nxt = f"lead({start}) OVER (PARTITION BY {part} ORDER BY {start})"
        rep["has_recorded_time"] = True
        rep["recorded_lineage"] = list(rt["lineage"])
        return [f"COALESCE({start}, DATE '{MIN_DATE}') AS known_from",
                f"CASE WHEN {deleted} THEN {del_end} ELSE COALESCE({nxt}, DATE '{OPEN_END}') END AS known_to"]
    post = sel["post_date"]
    eff = sel.get("eff_date", f"DATE '{MIN_DATE}'")
    rep["has_recorded_time"] = True
    return [f"CASE WHEN {deleted} THEN COALESCE({eff}, DATE '{MIN_DATE}') ELSE COALESCE({post}, DATE '{MIN_DATE}') END AS known_from",
            f"CASE WHEN {deleted} THEN {del_end} ELSE DATE '{OPEN_END}' END AS known_to"]


def resolve(con, m: dict, set_name: str, strict: bool = True) -> Resolution:
    """Validate the mapping against the physical schema of one set and register canonical views.

    Creates DuckDB views `c_<concept>` for every resolved concept. Required concepts/fields that do
    not resolve are reported in `Resolution.problems`; with strict=True that raises MappingError.
    Restricted fields (role: restricted | restricted_fairness_only) are validated but never exposed in
    canonical views.
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
        joins: list[str] = []
        missing_required = []
        for fname, f in c["fields"].items():
            col = f["column"]
            fr = {"column": col, "provenance": f["provenance"], "type": f.get("type", "varchar")}
            if col in cols:
                fr["status"] = "resolved"
                fr["physical_type"] = cols[col]
                if f.get("derive"):
                    dexpr, djoins, dprob, drep = _derive(con, loc, storage, cols, col, f, fname, len(joins))
                    joins += djoins
                    fr["derive"] = drep
                    if dprob:
                        res.problems += [f"{cname}.{fname}: {p}" for p in dprob]
                    if f.get("role") not in RESTRICTED_ROLES:
                        select.append((fname, dexpr))
                elif f.get("role") not in RESTRICTED_ROLES:
                    select.append((fname, _expr(col, f)))
            elif f.get("optional"):
                fr["status"] = "absent_optional"
                if f.get("role") not in RESTRICTED_ROLES:
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
        rt = c.get("recorded_time") or {}
        mode = rt.get("mode", "interval")
        if mode != "interval":
            rep["recorded_time_mode"] = mode
            ex = _recorded_exprs(dict(select), c, rt, mode, rep)
            exprs += ex
        elif "recorded_start" in names:
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
        con.execute(f"CREATE OR REPLACE TEMP VIEW c_{cname} AS SELECT {', '.join(exprs)} FROM {ref} AS s {' '.join(joins)}")
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
