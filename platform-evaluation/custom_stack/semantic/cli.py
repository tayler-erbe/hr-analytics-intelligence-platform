"""Command line for the semantic layer.

  python -m custom_stack.semantic.cli compile [--out DIR]
  python -m custom_stack.semantic.cli check-contract [--model hr_public] [--data-dir DIR]
  python -m custom_stack.semantic.cli query --model hr_public --plan '{"metric": ...}' [--data-dir DIR]

Run from platform-evaluation/ (so that `custom_stack` is importable).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import duckdb
import yaml

from .compile_databricks import metric_view_ddl, metric_views
from .compile_duckdb import compile_plan, setup_statements
from .compile_snowflake import cortex_analyst_yaml, semantic_view_ddl
from .model import SemanticModel, load_all

GENERATED = Path(__file__).resolve().parent / "generated"

_TYPE_OK = {
    "string": ("VARCHAR",),
    "integer": ("TINYINT", "SMALLINT", "INTEGER", "BIGINT", "HUGEINT", "UTINYINT", "USMALLINT", "UINTEGER", "UBIGINT"),
    "number": ("DOUBLE", "FLOAT", "DECIMAL", "TINYINT", "SMALLINT", "INTEGER", "BIGINT", "HUGEINT", "REAL"),
    "boolean": ("BOOLEAN",),
    "date": ("DATE", "TIMESTAMP"),
}


def compile_all(models: dict[str, SemanticModel], out: Path) -> dict:
    summary = {}
    for name, model in models.items():
        d = out / name
        (d / "databricks").mkdir(parents=True, exist_ok=True)
        stmts, _ = setup_statements(model, Path("<DATA_DIR>"))
        (d / "duckdb_setup.sql").write_text(
            f"-- Generated from {model.path.name} sha256 {model.sha256[:16]}. Replace <DATA_DIR> with the contract-layer directory.\n"
            + ";\n\n".join(stmts) + ";\n")
        vq_sql = [f"-- Verified queries for {name} (compiled by compile_duckdb)"]
        for v in model.verified_queries:
            vq_sql.append(f"-- {v.name}: {v.question}\n-- verified_by: {v.verified_by} at {v.verified_at}\n{compile_plan(model, v.plan).sql};\n")
        (d / "duckdb_verified_queries.sql").write_text("\n".join(vq_sql))
        ddl, w_sv = semantic_view_ddl(model)
        (d / "snowflake_semantic_view.sql").write_text(ddl)
        ca, w_ca = cortex_analyst_yaml(model)
        (d / "cortex_analyst_semantic_model.yaml").write_text(ca)
        views, w_db = metric_views(model)
        for vn, text in views.items():
            (d / "databricks" / f"{vn}.yaml").write_text(text)
        (d / "databricks_metric_views.sql").write_text(metric_view_ddl(model, views))
        report = portability_report(model, w_sv, w_ca, w_db, views)
        (d / "PORTABILITY.md").write_text(report)
        summary[name] = {"snowflake_semantic_view_warnings": len(w_sv), "cortex_yaml_warnings": len(w_ca),
                         "databricks_warnings": len(w_db), "databricks_views": sorted(views)}
    return summary


def portability_report(model, w_sv, w_ca, w_db, views) -> str:
    lines = [f"# Portability report: {model.name}", "",
             f"Generated from `{model.path.name}` (sha256 `{model.sha256}`). Status: {model.status}.",
             "Vendor artefacts were generated, not executed against Snowflake or Databricks.", "",
             "| metric | type | DuckDB (reference) | Snowflake semantic view | Cortex YAML | Databricks metric view |",
             "|---|---|---|---|---|---|"]
    db_measures = set()
    for text in views.values():
        db_measures |= {m["name"] for m in yaml.safe_load(text).get("measures", [])}
    for mn, m in model.metrics.items():
        def status(ws, present=True):
            if not present:
                return "not emitted"
            hits = [w for w in ws if w.startswith(mn + ":")]
            return "emitted with caveat" if hits else "emitted"
        lines.append(f"| {mn} | {m.type} | exact | {status(w_sv)} | "
                     f"{status(w_ca, m.type != 'derived')} | {status(w_db, mn in db_measures)} |")
    lines += ["", "## Warnings", ""]
    for title, ws in (("Snowflake semantic view", w_sv), ("Cortex Analyst YAML", w_ca), ("Databricks metric views", w_db)):
        lines.append(f"### {title}")
        lines += [f"- {w}" for w in ws] or ["- none"]
        lines.append("")
    return "\n".join(lines)


def check_contract(model: SemanticModel, data_dir: Path) -> dict:
    con = duckdb.connect(":memory:")
    result = {"model": model.name, "data_dir": str(data_dir), "tables": {}, "ok": True}
    for e in model.entities.values():
        for t in e.sources:
            p = data_dir / f"{t}.parquet"
            entry = result["tables"].setdefault(t, {"exists": p.exists(), "missing_columns": [], "type_mismatches": [],
                                                    "extra_columns": []})
            if not p.exists():
                result["ok"] = False
                continue
            lit = str(p).replace("'", "''")
            schema = {r[0]: r[1] for r in con.execute(f"DESCRIBE SELECT * FROM read_parquet('{lit}')").fetchall()}
            for col, typ in e.columns.items():
                if col not in schema:
                    if col not in entry["missing_columns"]:
                        entry["missing_columns"].append(col)
                    result["ok"] = False
                elif not str(schema[col]).upper().startswith(_TYPE_OK[typ]):
                    entry["type_mismatches"].append({"column": col, "spec": typ, "actual": schema[col]})
                    result["ok"] = False
            entry["extra_columns"] = sorted(set(schema) - set(e.columns))
    con.close()
    return result


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="custom_stack.semantic.cli")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("compile")
    c.add_argument("--out", default=str(GENERATED))
    k = sub.add_parser("check-contract")
    k.add_argument("--model", default="hr_public")
    k.add_argument("--data-dir")
    q = sub.add_parser("query")
    q.add_argument("--model", default="hr_public")
    q.add_argument("--plan", required=True)
    q.add_argument("--data-dir")
    a = ap.parse_args(argv)
    models = load_all()
    if a.cmd == "compile":
        print(json.dumps(compile_all(models, Path(a.out)), indent=2))
        return 0
    model = models[a.model]
    if a.cmd == "check-contract":
        res = check_contract(model, model.data_dir(a.data_dir))
        print(json.dumps(res, indent=2))
        return 0 if res["ok"] else 1
    from .engine import Engine
    eng = Engine(model, a.data_dir)
    compiled, rows = eng.query(json.loads(a.plan))
    print(json.dumps({"compiled": compiled.to_dict(), "result": rows,
                      "source_vintages": eng.source_vintages(compiled)}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
