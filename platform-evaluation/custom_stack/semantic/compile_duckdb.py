"""Compile a structured metric query (a "plan") into DuckDB SQL.

A plan is the only interface between natural language (or an MCP client) and
the data. It names one governed metric, group-by dimensions and filters:

    {"metric": "staff_fte", "dimensions": ["sector"],
     "filters": [{"dimension": "survey_year", "op": "eq", "value": 2023}],
     "order_by": {"field": "staff_fte", "direction": "desc"}, "limit": 5}

Grain rules enforced here (not in the NL layer, so every client gets them):
* joins only follow many_to_one / one_to_one relationships (no fan-out);
* ratio metrics are ratios of sums at the requested grain;
* derived metrics aggregate each component separately, then join on the
  requested (conformed) dimensions;
* semi-additive metrics are summed within a period and averaged / last-valued
  / required-single across periods;
* constrained dimensions (published total rows, overlapping geographies,
  alternative knowledge bases) are filtered or trigger a clarification.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .model import FILTER_OPS, Dimension, Entity, Relationship, SemanticModel, SpecError, qualify


class PlanError(ValueError):
    """Plan is malformed or references unknown objects."""


class Unsupported(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class NeedsClarification(Exception):
    def __init__(self, kind: str, question: str, options: list | None = None, dimension: str | None = None):
        super().__init__(question)
        self.kind = kind
        self.question = question
        self.options = options or []
        self.dimension = dimension


@dataclass
class CompiledQuery:
    model: str
    metric: str
    sql: str
    plan: dict
    entities: list[str]
    physical_tables: list[str]
    joins: list[str]
    assumptions: list[str] = field(default_factory=list)
    columns: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "model": self.model, "metric": self.metric, "sql": self.sql, "plan": self.plan,
            "entities": self.entities, "physical_tables": self.physical_tables, "joins": self.joins,
            "assumptions": self.assumptions, "columns": self.columns,
        }


# ------------------------------------------------------------------ plans
def normalize_plan(model: SemanticModel, plan: dict) -> dict:
    """Validate and canonicalise a plan (sorted, typed) for comparison and compilation."""
    if not isinstance(plan, dict):
        raise PlanError("plan must be an object")
    metric = plan.get("metric")
    if metric not in model.metrics:
        raise PlanError(f"unknown metric {metric!r}")
    dims = plan.get("dimensions") or []
    if not isinstance(dims, list) or not all(isinstance(d, str) for d in dims):
        raise PlanError("dimensions must be a list of names")
    filters = []
    for f in plan.get("filters") or []:
        if not isinstance(f, dict) or "dimension" not in f:
            raise PlanError(f"bad filter {f!r}")
        op = f.get("op", "eq")
        if op not in FILTER_OPS:
            raise PlanError(f"bad filter op {op!r}")
        nf = {"dimension": f["dimension"], "op": op}
        if op in ("in", "not_in", "between"):
            vals = f.get("values", f.get("value"))
            if not isinstance(vals, list) or not vals:
                raise PlanError(f"filter {op} needs a list of values")
            if op == "between" and len(vals) != 2:
                raise PlanError("between needs exactly two values")
            nf["values"] = vals if op == "between" else sorted(vals, key=str)
        elif op != "latest":
            if "value" not in f:
                raise PlanError(f"filter {op} needs a value")
            nf["value"] = f["value"]
        filters.append(nf)
    filters.sort(key=lambda x: (x["dimension"], x["op"], str(x.get("value", x.get("values")))))
    out = {"model": model.name, "metric": metric, "dimensions": sorted(dict.fromkeys(dims)), "filters": filters}
    ob = plan.get("order_by")
    if ob:
        if ob.get("field") not in (metric, *dims):
            raise PlanError("order_by field must be the metric or a requested dimension")
        if ob.get("direction", "asc") not in ("asc", "desc"):
            raise PlanError("order_by direction must be asc or desc")
        out["order_by"] = {"field": ob["field"], "direction": ob.get("direction", "asc")}
    if plan.get("limit") is not None:
        lim = plan["limit"]
        if not isinstance(lim, int) or isinstance(lim, bool) or lim < 1 or lim > 10000:
            raise PlanError("limit must be an integer 1..10000")
        out["limit"] = lim
    return out


# --------------------------------------------------------------- literals
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def render_literal(dim: Dimension, value) -> str:
    t = dim.type
    if t == "integer":
        try:
            if isinstance(value, bool):
                raise ValueError
            iv = int(str(value))
        except ValueError:
            raise PlanError(f"{dim.name} expects an integer, got {value!r}") from None
        return str(iv)
    if t == "number":
        try:
            return repr(float(value))
        except (TypeError, ValueError):
            raise PlanError(f"{dim.name} expects a number, got {value!r}") from None
    if t == "boolean":
        s = str(value).strip().lower()
        if s not in ("true", "false", "1", "0"):
            raise PlanError(f"{dim.name} expects a boolean, got {value!r}")
        return "TRUE" if s in ("true", "1") else "FALSE"
    if t == "date":
        if not _DATE.match(str(value)):
            raise PlanError(f"{dim.name} expects YYYY-MM-DD, got {value!r}")
        return f"DATE '{value}'"
    return "'" + str(value).replace("'", "''") + "'"


# --------------------------------------------------------------- compiler
def _q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


class _Builder:
    def __init__(self, model: SemanticModel, entity: Entity):
        self.model = model
        self.entity = entity
        self.joins: dict[str, Relationship] = {}

    def dim(self, name: str) -> tuple[Dimension, str]:
        try:
            res = self.model.resolve_dimension(self.entity.name, name)
        except SpecError as e:
            raise Unsupported(str(e)) from None
        if res is None:
            rel = self.model.blocked_relationship(self.entity.name, name)
            if rel is not None:
                raise Unsupported(
                    f"dimension {name!r} is only reachable through relationship {rel.name!r} "
                    f"({rel.type}); joining would fan out the measure. {rel.note}".strip())
            raise Unsupported(f"dimension {name!r} is not available for entity {self.entity.name!r}")
        dim, path = res
        for r in path:
            self.joins.setdefault(r.name, r)
        ent = self.model.entities[dim.entity]
        return dim, qualify(dim.expr, ent.name, ent.columns)

    def from_clause(self) -> str:
        e = self.entity
        lines = [f"FROM {e.table} AS {e.name}"]
        done = {e.name}
        # emit joins in dependency order
        pending = list(self.joins.values())
        while pending:
            progressed = False
            for r in list(pending):
                if r.from_entity in done:
                    to = self.model.entities[r.to_entity]
                    cond = " AND ".join(f"{r.from_entity}.{a} = {to.name}.{b}" for a, b in r.on)
                    lines.append(f"LEFT JOIN {to.table} AS {to.name} ON {cond}")
                    done.add(to.name)
                    pending.remove(r)
                    progressed = True
            if not progressed:
                raise SpecError("join path could not be ordered")
        return "\n".join(lines)


def _measure_sql(model: SemanticModel, metric_name: str) -> str:
    m = model.metrics[metric_name]
    e = model.entities[m.entity]

    def agg(a: str, expr: str) -> str:
        if expr.strip() == "*":
            if a != "count":
                raise SpecError(f"{metric_name}: '*' only valid with count")
            return "COUNT(*)"
        qe = qualify(expr, e.name, e.columns)
        if a == "count_distinct":
            return f"COUNT(DISTINCT {qe})"
        return f"{a.upper()}({qe})"

    if m.type == "simple":
        out = agg(m.agg, m.expr)
        if m.null_policy == "propagate" and m.expr.strip() != "*":
            qe = qualify(m.expr, e.name, e.columns)
            out = f"CASE WHEN COUNT(*) = COUNT({qe}) THEN {out} END"
        return out
    if m.type == "ratio":
        if m.null_policy == "propagate":
            raise SpecError(f"{metric_name}: null_policy propagate is only supported for simple metrics")
        num = agg(m.numerator["agg"], str(m.numerator["expr"]))
        den = agg(m.denominator["agg"], str(m.denominator["expr"]))
        return f"CAST({num} AS DOUBLE) / NULLIF({den}, 0)"
    raise SpecError("derived metrics have no single measure")


def _filter_sql(dim: Dimension, expr: str, f: dict, b: _Builder) -> str:
    op = f["op"]
    if op == "latest":
        ent = b.model.entities[dim.entity]
        inner = qualify(dim.expr, "_latest", ent.columns)
        return f"{expr} = (SELECT MAX({inner}) FROM {ent.table} AS _latest)"
    if op in ("in", "not_in"):
        vals = ", ".join(render_literal(dim, v) for v in f["values"])
        return f"{expr} {'IN' if op == 'in' else 'NOT IN'} ({vals})"
    if op == "between":
        lo, hi = (render_literal(dim, v) for v in f["values"])
        return f"{expr} BETWEEN {lo} AND {hi}"
    sym = {"eq": "=", "ne": "<>", "gt": ">", "gte": ">=", "lt": "<", "lte": "<="}[op]
    return f"{expr} {sym} {render_literal(dim, f['value'])}"


def _time_check(model: SemanticModel, metric_name: str, entity: Entity, plan: dict) -> None:
    if model.metrics[metric_name].time_rollup != "require_single":
        return
    filters = {f["dimension"]: f for f in plan["filters"]}
    for tdim in entity.time_key:
        if tdim in plan["dimensions"]:
            continue
        f = filters.get(tdim)
        if f and f["op"] in ("eq", "latest"):
            continue
        m = model.metrics[metric_name]
        what = "a range of periods" if f else "no period"
        raise NeedsClarification(
            "time",
            f"{m.label} is a point-in-time stock ({m.grain_rule.split('.')[0]}). The question gives {what}; "
            f"which single {tdim.replace('_', ' ')} do you want, or should results be broken down by {tdim}?",
            options=["specify one " + tdim, "group by " + tdim, "latest available " + tdim],
            dimension=tdim,
        )


def _compile_single(model: SemanticModel, metric_name: str, plan: dict, assumptions: list[str],
                    for_component: bool = False) -> tuple[str, _Builder]:
    m = model.metrics[metric_name]
    entity = model.entities[m.entity]
    b = _Builder(model, entity)
    _time_check(model, metric_name, entity, plan)

    selects, group_exprs = [], []
    for dn in plan["dimensions"]:
        dim, expr = b.dim(dn)
        selects.append(f"{expr} AS {_q(dn)}")
        group_exprs.append(expr)

    where: list[str] = []
    if entity.base_filter:
        where.append(qualify(entity.base_filter, entity.name, entity.columns))
    if m.filter:
        where.append(qualify(m.filter, entity.name, entity.columns))
    filtered = set()
    for f in plan["filters"]:
        dim, expr = b.dim(f["dimension"])
        where.append(_filter_sql(dim, expr, f, b))
        filtered.add(f["dimension"])
        if f["op"] == "latest":
            assumptions.append(f"'latest' {f['dimension']} resolved in SQL as the maximum value present in {model.entities[dim.entity].table}")

    # constrained dimensions (entity rules + metric rules)
    for c in model.constraints_for(metric_name):
        dim = entity.dimensions[c.dimension]
        expr = qualify(dim.expr, entity.name, entity.columns)
        grouped = c.dimension in plan["dimensions"]
        if c.dimension in filtered:
            continue
        if any(sd in plan["dimensions"] or sd in filtered for sd in c.satisfied_by):
            assumptions.append(f"{c.dimension}: rule satisfied by {', '.join(c.satisfied_by)} in the request")
            continue
        if grouped:
            if c.total_value is not None and c.when_unconstrained in ("sum_members", "use_total"):
                where.append(f"{expr} <> {render_literal(dim, c.total_value)}")
                assumptions.append(f"{c.dimension}: total row {c.total_value!r} excluded when grouping ({c.reason})")
            continue
        mode = c.when_unconstrained
        if mode == "clarify":
            opts = sorted(dim.values) if dim.values else []
            raise NeedsClarification(
                "dimension", f"{m.label} needs a {c.dimension.replace('_', ' ')} ({c.reason}) Which one?",
                options=opts, dimension=c.dimension)
        if mode == "sum_members":
            if c.total_value is not None:
                where.append(f"{expr} <> {render_literal(dim, c.total_value)}")
                assumptions.append(f"{c.dimension}: summed members, excluded total row {c.total_value!r} ({c.reason})")
        elif mode == "use_total":
            where.append(f"{expr} = {render_literal(dim, c.total_value)}")
            assumptions.append(f"{c.dimension}: used published total row {c.total_value!r} ({c.reason})")
        elif mode == "default":
            where.append(f"{expr} = {render_literal(dim, c.default_value)}")
            assumptions.append(f"{c.dimension}: defaulted to {c.default_value!r} ({c.reason})")

    for dn in plan["dimensions"]:
        res = model.resolve_dimension(entity.name, dn)
        if res and res[0].hierarchical:
            assumptions.append(f"{dn} is hierarchical: grouped rows overlap and must not be added together")

    measure = _measure_sql(model, metric_name)
    from_sql = b.from_clause()
    where_sql = ("\nWHERE " + "\n  AND ".join(where)) if where else ""
    out_name = _q(metric_name)

    time_key = entity.time_key
    rollup = m.time_rollup if m.additivity == "semi_additive" else "none"
    needs_two_stage = rollup in ("avg", "last") and any(t not in plan["dimensions"] for t in time_key)
    if not needs_two_stage:
        sel = ",\n  ".join(selects + [f"{measure} AS {out_name}"])
        sql = f"SELECT\n  {sel}\n{from_sql}{where_sql}"
        if selects:
            sql += "\nGROUP BY " + ", ".join(str(i + 1) for i in range(len(selects)))
        return sql, b

    # two-stage: sum within period, then roll up across periods
    tk_sel, tk_names = [], []
    for t in time_key:
        if t in plan["dimensions"]:
            continue
        dim, expr = b.dim(t)
        tk_sel.append(f"{expr} AS {_q('__period_' + t)}")
        tk_names.append(_q("__period_" + t))
    inner_sel = ",\n    ".join(selects + tk_sel + [f"{measure} AS __v"])
    inner = f"SELECT\n    {inner_sel}\n  {from_sql.replace(chr(10), chr(10) + '  ')}{where_sql.replace(chr(10), chr(10) + '  ')}"
    inner += "\n  GROUP BY " + ", ".join(str(i + 1) for i in range(len(selects) + len(tk_sel)))
    dim_cols = [_q(d) for d in plan["dimensions"]]
    if rollup == "avg":
        avg = "CASE WHEN COUNT(*) = COUNT(__v) THEN AVG(__v) END" if m.null_policy == "propagate" else "AVG(__v)"
        outer_sel = ",\n  ".join(dim_cols + [f"{avg} AS {out_name}"])
        sql = f"WITH per_period AS (\n  {inner}\n)\nSELECT\n  {outer_sel}\nFROM per_period"
        if dim_cols:
            sql += "\nGROUP BY " + ", ".join(dim_cols)
        rolled = ", ".join(t for t in time_key if t not in plan["dimensions"])
        assumptions.append(f"{metric_name} is a stock: summed within each period, averaged across {rolled}")
    else:  # last
        part = ("PARTITION BY " + ", ".join(dim_cols) + " ") if dim_cols else ""
        outer_sel = ",\n  ".join(dim_cols + [f"__v AS {out_name}"])
        sql = (f"WITH per_period AS (\n  {inner}\n)\nSELECT\n  {outer_sel}\nFROM per_period\n"
               f"QUALIFY ROW_NUMBER() OVER ({part}ORDER BY {', '.join(n + ' DESC' for n in tk_names)}) = 1")
        assumptions.append(f"{metric_name} is a stock: last period value")
    return sql, b


def _order_limit(plan: dict) -> str:
    parts = []
    ob = plan.get("order_by")
    if ob:
        parts.append(f"ORDER BY {_q(ob['field'])} {ob['direction'].upper()} NULLS LAST"
                     + "".join(f", {_q(d)}" for d in plan["dimensions"] if d != ob["field"]))
    elif plan["dimensions"]:
        parts.append("ORDER BY " + ", ".join(_q(d) for d in plan["dimensions"]))
    if plan.get("limit"):
        parts.append(f"LIMIT {int(plan['limit'])}")
    return ("\n" + "\n".join(parts)) if parts else ""


def compile_plan(model: SemanticModel, plan: dict) -> CompiledQuery:
    """Compile a plan to DuckDB SQL. Raises PlanError, Unsupported or NeedsClarification."""
    plan = normalize_plan(model, plan)
    metric = model.metrics[plan["metric"]]
    available = model.available_dimensions(metric.name)
    for dn in [*plan["dimensions"], *(f["dimension"] for f in plan["filters"])]:
        if dn not in available:
            for e in model.metric_entities(metric.name):
                rel = model.blocked_relationship(e, dn)
                if rel is not None:
                    raise Unsupported(
                        f"{metric.name} cannot be broken down by {dn!r}: the only path is relationship "
                        f"{rel.name!r} ({rel.type}), which would fan out the measure. {rel.note}".strip())
            raise Unsupported(f"dimension {dn!r} is not available for metric {metric.name!r}"
                              + (" (not conformed across all components)" if metric.type == "derived" else ""))
    assumptions: list[str] = []
    entities, joins = [], []
    if metric.type != "derived":
        body, b = _compile_single(model, metric.name, plan, assumptions)
        entities = [metric.entity, *(r.to_entity for r in b.joins.values())]
        joins = list(b.joins)
        sql = body + _order_limit(plan)
    else:
        ctes, names = [], []
        align = [a for a in metric.align_on if a not in plan["dimensions"]]
        join_dims = plan["dimensions"] + align
        for c in metric.components:
            sub_plan = {**plan, "metric": c, "dimensions": join_dims, "order_by": None, "limit": None}
            body, b = _compile_single(model, c, sub_plan, assumptions, for_component=True)
            names.append(c)
            ctes.append(f"c_{c} AS (\n  " + body.replace("\n", "\n  ") + "\n)")
            for e in [model.metrics[c].entity, *(r.to_entity for r in b.joins.values())]:
                if e not in entities:
                    entities.append(e)
            joins += [j for j in b.joins if j not in joins]
        first = f"c_{names[0]}"
        from_sql = f"FROM {first}"
        for n in names[1:]:
            if join_dims:
                cond = " AND ".join(f"{first}.{_q(d)} IS NOT DISTINCT FROM c_{n}.{_q(d)}" for d in join_dims)
                from_sql += f"\nJOIN c_{n} ON {cond}"
            else:
                from_sql += f"\nCROSS JOIN c_{n}"
        if align:
            formula = re.sub(r"\{([a-z0-9_]+)\}", lambda mm: f"SUM(c_{mm.group(1)}.{_q(mm.group(1))})", metric.formula)
            assumptions.append(f"{metric.name}: population aligned on {', '.join(align)}; only units present in every "
                               f"component ({', '.join(names)}) are included, then components are summed")
        else:
            formula = re.sub(r"\{([a-z0-9_]+)\}", lambda mm: f"c_{mm.group(1)}.{_q(mm.group(1))}", metric.formula)
        sel = ",\n  ".join([f"{first}.{_q(d)}" for d in plan["dimensions"]] + [f"{formula} AS {_q(metric.name)}"])
        sql = "WITH " + ",\n".join(ctes) + f"\nSELECT\n  {sel}\n{from_sql}"
        if align and plan["dimensions"]:
            sql += "\nGROUP BY " + ", ".join(str(i + 1) for i in range(len(plan["dimensions"])))
        sql += _order_limit(plan)
        assumptions.append(f"{metric.name}: components {', '.join(names)} aggregated separately and joined on requested dimensions")
    physical = []
    for e in entities:
        for t in model.entities[e].sources:
            if t not in physical:
                physical.append(t)
        for dep in model.entities[e].depends_on:
            for t in model.entities[dep].sources:
                if t not in physical:
                    physical.append(t)
    return CompiledQuery(model=model.name, metric=metric.name, sql=sql, plan=plan, entities=entities,
                         physical_tables=physical, joins=joins, assumptions=list(dict.fromkeys(assumptions)),
                         columns=[*plan["dimensions"], metric.name])


# ------------------------------------------------------------------ setup
def setup_statements(model: SemanticModel, data_dir) -> tuple[list[str], list[str]]:
    """CREATE VIEW statements exposing physical files then logical entities.

    Returns (statements, missing_physical_tables).
    """
    from pathlib import Path

    data_dir = Path(data_dir)
    fmt = model.physical.get("format", "parquet")
    stmts, missing, created = [], [], set()
    physical = []
    for e in model.entities.values():
        for t in e.sources:
            if t not in physical:
                physical.append(t)
    for t in physical:
        ext = "parquet" if fmt == "parquet" else "jsonl"
        p = data_dir / f"{t}.{ext}"
        if not p.exists():
            missing.append(t)
            continue
        lit = "'" + str(p).replace("'", "''") + "'"
        reader = f"read_parquet({lit})" if fmt == "parquet" else f"read_json_auto({lit}, format='newline_delimited')"
        stmts.append(f"CREATE OR REPLACE VIEW {t} AS SELECT * FROM {reader}")
        created.add(t)
    ordered, seen = [], set()

    def visit(name: str):
        if name in seen:
            return
        seen.add(name)
        for d in model.entities[name].depends_on:
            visit(d)
        ordered.append(name)

    for n in model.entities:
        visit(n)
    for n in ordered:
        e = model.entities[n]
        if e.sql and all(t in created for t in e.physical_tables):
            stmts.append(f"CREATE OR REPLACE VIEW {e.table} AS\n{e.sql.strip()}")
            created.add(e.table)
    return stmts, missing
