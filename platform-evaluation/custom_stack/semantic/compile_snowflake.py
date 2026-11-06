"""Compile the portable spec to Snowflake artefacts.

1. `CREATE SEMANTIC VIEW` DDL (semantic views are what Cortex Analyst reads).
2. A legacy Cortex Analyst semantic-model YAML (stage-file format) with the same
   tables, relationships, metrics, synonyms and verified queries.

Neither artefact has been executed against a Snowflake account from this
repository. Syntax follows Snowflake documentation as understood on
2026-11-06; validate with `CREATE SEMANTIC VIEW` / Cortex Analyst before
recording any score. Every rule that could not be expressed is returned as a
warning and written to the portability report.
"""
from __future__ import annotations

import datetime as _dt
import re

import yaml

from .compile_duckdb import compile_plan
from .model import SemanticModel, qualify
from .portable import portable_measure

_SF_TYPES = {"string": "VARCHAR", "integer": "NUMBER", "number": "FLOAT", "boolean": "BOOLEAN", "date": "DATE"}


def _s(text: str) -> str:
    return "'" + " ".join(str(text).split()).replace("\\", "\\\\").replace("'", "''") + "'"


def _fq(model: SemanticModel, table: str) -> str:
    t = model.targets.get("snowflake", {})
    return f"{t.get('database', 'HR_ANALYTICS')}.{t.get('schema', 'HR_PUBLIC')}.{table.upper()}"


def _syn(words: list[str]) -> str:
    if not words:
        return ""
    return " WITH SYNONYMS = (" + ", ".join(_s(w) for w in dict.fromkeys(words)) + ")"


def semantic_view_ddl(model: SemanticModel) -> tuple[str, list[str]]:
    warnings: list[str] = []
    sf = model.targets.get("snowflake", {})
    db, schema = sf.get("database", "HR_ANALYTICS"), sf.get("schema", "HR_PUBLIC")
    view = sf.get("semantic_view", model.name.upper())
    out = [f"-- Generated from {model.path.name} (sha256 {model.sha256[:16]}) by custom_stack.semantic.compile_snowflake",
           "-- NOT executed against Snowflake from this repository; validate before use.",
           f"USE SCHEMA {db}.{schema};", ""]
    # logical entities defined by SQL become ordinary views first
    for e in model.entities.values():
        if e.sql:
            out.append(f"-- logical entity {e.name}: SQL emitted verbatim (DuckDB-tested); review dialect")
            out.append(f"CREATE OR REPLACE VIEW {_fq(model, e.table)} AS\n{e.sql.strip()};\n")
            warnings.append(f"entity {e.name}: logical SQL view emitted verbatim; Snowflake dialect not executed here")

    tables, rels, facts, dims, metrics = [], [], [], [], []
    for e in model.entities.values():
        comment = f"{e.description} Grain: {e.grain}."
        tables.append(f"    {e.name} AS {_fq(model, e.table)}\n      PRIMARY KEY ({', '.join(e.primary_key)}){_syn(e.synonyms)}\n      COMMENT = {_s(comment)}")
        for dn, d in e.dimensions.items():
            expr = qualify(d.expr, e.name, e.columns)
            extra = d.description
            if d.values:
                extra += " Values: " + "; ".join(f"{k} = {', '.join(v)}" for k, v in d.values.items())
            dims.append(f"    {e.name}.{dn} AS {expr}{_syn(d.synonyms)}\n      COMMENT = {_s(extra)}")
    for r in model.relationships:
        if r.type not in ("many_to_one", "one_to_one"):
            warnings.append(f"relationship {r.name} ({r.type}) intentionally omitted: {r.note}")
            continue
        rels.append(f"    {r.name} AS {r.from_entity} ({', '.join(a for a, _ in r.on)}) REFERENCES {r.to_entity} ({', '.join(b for _, b in r.on)})")

    for mn, m in model.metrics.items():
        if m.type == "derived":
            formula = m.formula
            for c in m.components:
                formula = formula.replace("{" + c + "}", f"{model.metrics[c].entity}.{c}")
            metrics.append(f"    {mn} AS {formula}{_syn(m.synonyms)}\n      COMMENT = {_s(m.description + ' Grain rule: ' + m.grain_rule)}")
            warnings.append(f"{mn}: emitted as a Snowflake derived (view-level) metric; cross-table aggregation "
                            "behaviour must be checked by result equality")
            if m.align_on:
                warnings.append(f"{mn}: population alignment on {', '.join(m.align_on)} is NOT expressible; the Snowflake "
                                "metric divides unaligned totals (can differ from the reference)")
            continue
        e = model.entities[m.entity]
        pm = portable_measure(model, mn, lambda x, e=e: qualify(x, e.name, e.columns))
        warnings += pm.warnings
        rules = ("; ".join(pm.folded_rules)) if pm.folded_rules else "none"
        comment = f"{m.description} Unit: {m.unit}. Grain rule: {m.grain_rule} Folded rules: {rules}."
        metrics.append(f"    {e.name}.{mn} AS {pm.expr}{_syn(m.synonyms)}\n      COMMENT = {_s(comment)}")

    out.append(f"CREATE OR REPLACE SEMANTIC VIEW {db}.{schema}.{view}")
    out.append("  TABLES (\n" + ",\n".join(tables) + "\n  )")
    if rels:
        out.append("  RELATIONSHIPS (\n" + ",\n".join(rels) + "\n  )")
    if facts:
        out.append("  FACTS (\n" + ",\n".join(facts) + "\n  )")
    out.append("  DIMENSIONS (\n" + ",\n".join(dims) + "\n  )")
    out.append("  METRICS (\n" + ",\n".join(metrics) + "\n  )")
    out.append(f"  COMMENT = {_s(model.description + ' Status: ' + model.status)};")
    return "\n".join(out) + "\n", list(dict.fromkeys(warnings))


def _custom_instructions(model: SemanticModel) -> str:
    lines = ["Answer only with the governed metrics in this model. Never sum a metric across its non-additive dimensions."]
    for e in model.entities.values():
        for c in e.constrained:
            if c.when_unconstrained == "clarify":
                lines.append(f"Ask the user to choose {c.dimension} for {e.name} metrics; never aggregate across it ({c.reason}).")
    for m in model.metrics.values():
        if m.time_rollup == "require_single":
            lines.append(f"{m.name} is a point-in-time stock: ask for a single period or group by period; never sum across periods.")
    for r in model.abstain_rules:
        lines.append(f"Decline ({r.id}): {r.reason}")
    return "\n".join(lines)


def _cortex_sql(model: SemanticModel, sql: str) -> str:
    """Rewrite compiled SQL to Cortex Analyst logical-table references (__name)."""
    for e in model.entities.values():
        sql = re.sub(rf"\b(FROM|JOIN) {re.escape(e.table)} AS {e.name}\b", rf"\1 __{e.name} AS {e.name}", sql)
    return sql


def cortex_analyst_yaml(model: SemanticModel) -> tuple[str, list[str]]:
    warnings: list[str] = []
    sf = model.targets.get("snowflake", {})
    tables = []
    for e in model.entities.values():
        t: dict = {
            "name": e.name,
            "description": f"{e.description} Grain: {e.grain}.",
            "base_table": {"database": sf.get("database", "HR_ANALYTICS"), "schema": sf.get("schema", "HR_PUBLIC"),
                           "table": e.table.upper()},
            "primary_key": {"columns": e.primary_key},
            **({"synonyms": e.synonyms} if e.synonyms else {}),
            "dimensions": [],
            "facts": [],
            "metrics": [],
            "filters": [],
        }
        for dn, d in e.dimensions.items():
            dd = {"name": dn, "expr": d.expr, "data_type": _SF_TYPES[d.type], "description": d.description}
            if d.synonyms:
                dd["synonyms"] = list(dict.fromkeys(d.synonyms))
            if d.values:
                dd["sample_values"] = list(d.values)
                dd["is_enum"] = False
            t["dimensions"].append(dd)
        for c in e.constrained:
            dim = e.dimensions[c.dimension]
            if c.total_value is not None:
                lit = "'" + c.total_value.replace("'", "''") + "'"
                t["filters"].append({"name": f"exclude_{c.dimension}_total", "expr": f"{dim.expr} <> {lit}",
                                     "description": c.reason})
        for mn, m in model.metrics.items():
            if m.type == "derived" or m.entity != e.name:
                continue
            pm = portable_measure(model, mn, lambda x: x)
            warnings += pm.warnings
            md = {"name": mn, "expr": pm.expr, "description": f"{m.description} Grain rule: {m.grain_rule}"}
            if m.synonyms:
                md["synonyms"] = list(dict.fromkeys(m.synonyms))
            t["metrics"].append(md)
        for k in ("facts", "metrics", "filters"):
            if not t[k]:
                del t[k]
        tables.append(t)
    rels = []
    for r in model.relationships:
        if r.type not in ("many_to_one", "one_to_one"):
            continue
        rels.append({"name": r.name, "left_table": r.from_entity, "right_table": r.to_entity,
                     "relationship_columns": [{"left_column": a, "right_column": b} for a, b in r.on],
                     "join_type": "left_outer", "relationship_type": r.type})
    for m in model.metrics.values():
        if m.type == "derived":
            warnings.append(f"{m.name}: cross-table derived metric not representable in legacy Cortex Analyst YAML; "
                            "use the semantic view DDL or a verified query")
    vqs = []
    for v in model.verified_queries:
        try:
            sql = _cortex_sql(model, compile_plan(model, v.plan).sql)
        except Exception as exc:  # pragma: no cover - surfaced as warning
            warnings.append(f"verified query {v.name} failed to compile: {exc}")
            continue
        ts = int(_dt.datetime.fromisoformat(v.verified_at).replace(tzinfo=_dt.timezone.utc).timestamp()) if v.verified_at else 0
        vqs.append({"name": v.name, "question": v.question, "sql": sql, "verified_at": ts,
                    "verified_by": v.verified_by, "use_as_onboarding_question": False})
    doc = {"name": model.name, "description": f"{model.description} Status: {model.status}. Generated from {model.path.name} "
                                             f"sha256 {model.sha256[:16]}.",
           "tables": tables, "relationships": rels, "verified_queries": vqs,
           "custom_instructions": _custom_instructions(model)}
    return yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=120), list(dict.fromkeys(warnings))
