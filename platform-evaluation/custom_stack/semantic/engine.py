"""Execute compiled plans on DuckDB over the lake contract-layer Parquet (or fixture) files."""
from __future__ import annotations

import datetime as _dt
import decimal
from pathlib import Path

import duckdb

from .compile_duckdb import CompiledQuery, compile_plan, setup_statements
from .model import SemanticModel


def _jsonable(v):
    if isinstance(v, decimal.Decimal):
        return float(v)
    if isinstance(v, (_dt.date, _dt.datetime)):
        return v.isoformat()
    return v


class DataUnavailable(Exception):
    pass


class Engine:
    """One in-memory DuckDB connection with views over a model's physical files."""

    def __init__(self, model: SemanticModel, data_dir: str | Path | None = None):
        self.model = model
        self.data_dir = model.data_dir(data_dir)
        self.con = duckdb.connect(":memory:")
        stmts, self.missing_tables = setup_statements(model, self.data_dir)
        for s in stmts:
            self.con.execute(s)

    def close(self):
        self.con.close()

    def available(self, compiled: CompiledQuery) -> list[str]:
        return [t for t in compiled.physical_tables if t in self.missing_tables]

    def run_sql(self, sql: str) -> dict:
        cur = self.con.execute(sql)
        cols = [d[0] for d in cur.description]
        rows = [[_jsonable(v) for v in r] for r in cur.fetchall()]
        return {"columns": cols, "rows": rows}

    def execute(self, compiled: CompiledQuery) -> dict:
        missing = self.available(compiled)
        if missing:
            raise DataUnavailable(f"physical tables not present in {self.data_dir}: {', '.join(missing)}")
        return self.run_sql(compiled.sql)

    def query(self, plan: dict) -> tuple[CompiledQuery, dict]:
        c = compile_plan(self.model, plan)
        return c, self.execute(c)

    def join_coverage(self, compiled: CompiledQuery) -> list[dict]:
        """For each many-to-one join used, count fact rows with no matching dimension row.

        Unmatched rows are kept (LEFT JOIN) and appear under a NULL group; this makes that visible.
        """
        out = []
        for r in self.model.relationships:
            if r.name not in compiled.joins:
                continue
            f, t = self.model.entities[r.from_entity], self.model.entities[r.to_entity]
            if any(x in self.missing_tables for x in (*f.sources, *t.sources)):
                continue
            cond = " AND ".join(f"f.{a} = t.{b}" for a, b in r.on)
            nulls = " AND ".join(f"t.{b} IS NULL" for _, b in r.on)
            total, unmatched, keys = self.con.execute(
                f"SELECT COUNT(*), COUNT(*) FILTER (WHERE {nulls}), COUNT(DISTINCT CASE WHEN {nulls} THEN "
                f"{'f.' + r.on[0][0]} END) FROM {f.table} f LEFT JOIN {t.table} t ON {cond}").fetchone()
            out.append({"relationship": r.name, "fact_rows": total, "unmatched_rows": unmatched,
                        "unmatched_keys": keys})
        return out

    def source_vintages(self, compiled: CompiledQuery) -> list[dict]:
        """Distinct (table, source_id, source_vintage) for physical tables that carry them."""
        out = []
        for t in compiled.physical_tables:
            if t in self.missing_tables:
                continue
            cols = {r[0] for r in self.con.execute(f"DESCRIBE {t}").fetchall()}
            if {"source_id", "source_vintage"} <= cols:
                for sid, vin in self.con.execute(
                        f"SELECT DISTINCT CAST(source_id AS VARCHAR), CAST(source_vintage AS VARCHAR) FROM {t} ORDER BY 1, 2 LIMIT 20").fetchall():
                    out.append({"table": t, "source_id": sid, "source_vintage": vin})
            else:
                out.append({"table": t, "source_id": None, "source_vintage": None,
                            "note": "table carries no source_id/source_vintage columns"})
        return out
