"""Validate a Phase 2 outputs folder against delivery/star_schema.yaml.

    python wap_prototype/delivery/validate_star_schema.py <outputs_dir> [--schema star_schema.yaml] [--json report.json]

Checks, per table: the file exists (csv or parquet), required columns are present (extra columns are
warnings), values match the declared type and nullability, the primary key is unique (grain), foreign
keys resolve when the referenced dimension is present, no forbidden identifier / protected-attribute
column appears, and suppression holds: under mode k_anonymity every row with n < k_min is flagged and
every flagged row has null measures; small-count columns with 0 < value < k_min are also flagged; under
mode public the flag column is present and always false. Exit status 1 when any error is found.

Complementary suppression (succession_models governance.suppress) is applied by the producer and is
not re-derived here; the validator only checks that no published cell is below k_min.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd
import yaml

HERE = Path(__file__).resolve().parent
DEFAULT_SCHEMA = HERE / "star_schema.yaml"

TRUE_SET = {"true", "1", "t", "yes"}
FALSE_SET = {"false", "0", "f", "no"}


def load_schema(path: Path = DEFAULT_SCHEMA) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def read_table(outputs: Path, name: str) -> pd.DataFrame | None:
    for ext in (".parquet", ".csv"):
        p = outputs / f"{name}{ext}"
        if p.exists():
            if ext == ".parquet":
                return pd.read_parquet(p)
            return pd.read_csv(p, dtype=str, keep_default_na=False,
                               na_values=["", "NA", "NaN", "nan", "NULL", "null", "None"])
    return None


def _is_null(s: pd.Series) -> pd.Series:
    return s.isna()


def _key_str(df: pd.DataFrame, cols: list[str]) -> pd.Series:
    """Join key columns into one string per row, writing integral numbers without a decimal part so
    that an int key read from CSV ("1") matches the same key written through a float column ("1.0")."""
    parts = []
    for c in cols:
        num = pd.to_numeric(df[c], errors="coerce")
        if num.notna().equals(df[c].notna()) and num.notna().any() and (num.dropna() == num.dropna().round()).all():
            parts.append(num.map(lambda v: "" if pd.isna(v) else str(int(v))))
        else:
            parts.append(df[c].map(lambda v: "" if pd.isna(v) else str(v)))
    return pd.concat(parts, axis=1).agg("|".join, axis=1)


def _coerce_bool(s: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Returns (bool series with NA, mask of unparseable non-null values)."""
    out = pd.Series(pd.NA, index=s.index, dtype="object")
    bad = pd.Series(False, index=s.index)
    for i, v in s.items():
        if pd.isna(v):
            continue
        if isinstance(v, (bool,)) or (hasattr(v, "dtype") and str(v.dtype) == "bool"):
            out[i] = bool(v)
            continue
        sv = str(v).strip().lower()
        if sv in TRUE_SET:
            out[i] = True
        elif sv in FALSE_SET:
            out[i] = False
        else:
            bad[i] = True
    return out, bad


def check_type(s: pd.Series, typ: str) -> tuple[pd.Series, pd.Series]:
    """Returns (coerced series, mask of non-null values that violate the type)."""
    nn = ~_is_null(s)
    if typ == "int":
        num = pd.to_numeric(s, errors="coerce")
        bad = nn & (num.isna() | (num != num.round()))
        return num, bad
    if typ == "float":
        num = pd.to_numeric(s, errors="coerce")
        return num, nn & num.isna()
    if typ == "date":
        dt = pd.to_datetime(s.where(nn, None), format="%Y-%m-%d", errors="coerce")
        return dt, nn & dt.isna()
    if typ == "bool":
        b, bad = _coerce_bool(s)
        return b, bad
    if typ == "string":
        return s.astype("object"), pd.Series(False, index=s.index)
    raise ValueError(f"unknown type {typ!r} in schema")


class Report:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.tables: dict[str, dict] = {}

    def err(self, table: str, msg: str) -> None:
        self.errors.append(f"{table}: {msg}")

    def warn(self, table: str, msg: str) -> None:
        self.warnings.append(f"{table}: {msg}")

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict:
        return {"ok": self.ok, "errors": self.errors, "warnings": self.warnings, "tables": self.tables}


def validate_table(name: str, spec: dict, df: pd.DataFrame, schema: dict, tables: dict[str, pd.DataFrame],
                   rep: Report) -> pd.DataFrame:
    k_min = int(schema.get("k_min", 10))
    forbidden = [f.lower() for f in schema.get("forbidden_columns", [])]
    cols = {c["name"]: c for c in spec["columns"]}

    # forbidden columns
    for c in df.columns:
        hit = [f for f in forbidden if f in c.lower()]
        if hit:
            rep.err(name, f"forbidden column {c!r} (matches {hit[0]!r}); identifiers and protected attributes may not be published")

    # presence
    missing = [c for c in cols if c not in df.columns]
    for c in missing:
        rep.err(name, f"missing column {c!r}")
    extra = [c for c in df.columns if c not in cols]
    for c in extra:
        rep.warn(name, f"extra column {c!r} not in contract")

    # types and nullability
    coerced = pd.DataFrame(index=df.index)
    for c, cs in cols.items():
        if c not in df.columns:
            continue
        s, bad = check_type(df[c], cs["type"])
        if bad.any():
            rep.err(name, f"column {c!r}: {int(bad.sum())} value(s) are not {cs['type']} (first bad row {int(bad.idxmax())})")
        if not cs.get("nullable", False):
            nulls = _is_null(df[c])
            if nulls.any():
                rep.err(name, f"column {c!r}: {int(nulls.sum())} null(s) in a non-nullable column")
        coerced[c] = s

    # primary key / grain
    pk = spec.get("primary_key", [])
    if pk and all(c in df.columns for c in pk):
        dup = df.duplicated(subset=pk, keep=False)
        if dup.any():
            rep.err(name, f"grain violated: {int(dup.sum())} row(s) share a primary key {pk}")
        nullkey = df[pk].isna().any(axis=1)
        if nullkey.any():
            rep.err(name, f"{int(nullkey.sum())} row(s) have a null primary-key value")

    # foreign keys
    for fk in spec.get("foreign_keys", []) or []:
        ref = fk["references"]
        if ref not in tables:
            rep.warn(name, f"foreign key {fk['columns']} -> {ref} not checked: {ref} not present")
            continue
        if not all(c in df.columns for c in fk["columns"]):
            continue
        ref_df = tables[ref]
        ref_cols = fk["ref_columns"]
        if not all(c in ref_df.columns for c in ref_cols):
            continue
        left = _key_str(df, fk["columns"])
        right = set(_key_str(ref_df, ref_cols))
        present = ~df[fk["columns"]].isna().any(axis=1)
        orphan = present & ~left.isin(right)
        if orphan.any():
            rep.err(name, f"{int(orphan.sum())} row(s) reference {ref}{ref_cols} values that do not exist "
                          f"(e.g. {left[orphan].iloc[0]!r})")

    # suppression
    sup = spec.get("suppression")
    if spec.get("kind") == "fact":
        if not sup:
            rep.err(name, "fact table without a suppression block in the contract")
        else:
            flag = sup.get("flag_column", "suppressed")
            if flag not in df.columns:
                rep.err(name, f"suppression flag column {flag!r} missing")
            else:
                fl, bad = _coerce_bool(df[flag])
                flb = fl.map(lambda v: v is True)
                if sup["mode"] == "public":
                    if flb.any():
                        rep.err(name, f"public fact has {int(flb.sum())} row(s) flagged suppressed")
                elif sup["mode"] == "k_anonymity":
                    ncol = sup["n_column"]
                    if ncol in df.columns:
                        n = pd.to_numeric(df[ncol], errors="coerce")
                        small = n.isna() | (n < k_min)
                        for sc in sup.get("small_count_columns", []) or []:
                            if sc in df.columns:
                                v = pd.to_numeric(df[sc], errors="coerce")
                                small = small | ((v > 0) & (v < k_min))
                        leak = small & ~flb
                        if leak.any():
                            rep.err(name, f"{int(leak.sum())} row(s) with {ncol} < {k_min} (or a small count) are not flagged suppressed")
                        measures = [m for m in sup.get("measure_columns", []) if m in df.columns]
                        if measures:
                            notnull = df.loc[flb, measures].notna().any(axis=1)
                            if notnull.any():
                                rep.err(name, f"{int(notnull.sum())} suppressed row(s) still carry measure values in {measures}")
                    else:
                        rep.err(name, f"suppression count column {ncol!r} missing")
                else:
                    rep.err(name, f"unknown suppression mode {sup['mode']!r}")

    rep.tables[name] = {"rows": int(len(df)), "columns": list(df.columns)}
    return coerced


def validate_outputs(outputs: Path, schema: dict) -> Report:
    rep = Report()
    outputs = Path(outputs)
    tables: dict[str, pd.DataFrame] = {}
    for name in schema["tables"]:
        df = read_table(outputs, name)
        if df is not None:
            tables[name] = df
    for name, spec in schema["tables"].items():
        if name not in tables:
            if spec.get("required", True):
                rep.err(name, "required table file not found (<name>.csv or <name>.parquet)")
            else:
                rep.warn(name, "optional table not present")
            continue
        validate_table(name, spec, tables[name], schema, tables, rep)
    # cross-table: every fact model_version exists in dim_model_version is covered by FK checks;
    # additionally the default published version must be unique
    if "dim_model_version" in tables and "is_published_default" in tables["dim_model_version"].columns:
        b, _ = _coerce_bool(tables["dim_model_version"]["is_published_default"])
        per_model = tables["dim_model_version"].assign(_d=b.map(lambda v: v is True)).groupby("model_id")["_d"].sum() \
            if "model_id" in tables["dim_model_version"].columns else None
        if per_model is not None and (per_model > 1).any():
            rep.err("dim_model_version", f"more than one is_published_default version for model_id(s) {list(per_model[per_model > 1].index)}")
    return rep


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("outputs", help="folder holding <table>.csv or <table>.parquet files")
    ap.add_argument("--schema", default=str(DEFAULT_SCHEMA))
    ap.add_argument("--json", default=None, help="write the report to this path")
    args = ap.parse_args(argv)
    schema = load_schema(Path(args.schema))
    rep = validate_outputs(Path(args.outputs), schema)
    for w in rep.warnings:
        print(f"WARN  {w}")
    for e in rep.errors:
        print(f"ERROR {e}")
    print(f"{'OK' if rep.ok else 'FAIL'}: {len(rep.tables)} table(s) read, {len(rep.errors)} error(s), {len(rep.warnings)} warning(s)")
    if args.json:
        Path(args.json).write_text(json.dumps(rep.to_dict(), indent=2) + "\n")
    return 0 if rep.ok else 1


if __name__ == "__main__":
    sys.exit(main())
