"""Single-pass aggregate expressions that carry the grain rules into engines
whose semantic objects (Snowflake semantic views, Databricks metric views) only
accept one aggregate expression per metric.

The DuckDB compiler uses explicit SQL structure (two-stage rollups, WHERE
clauses). Here the same rules are folded into the measure itself:

* constrained dimension rules        -> CASE WHEN inside the aggregate
* metric filters                      -> CASE WHEN inside the aggregate
* time_rollup=avg (stock over time)   -> SUM(x) / COUNT(DISTINCT period)
                                         (identical to AVG of per-period sums)
* time_rollup=require_single          -> CASE WHEN COUNT(DISTINCT period) <= 1
                                         THEN agg END  (NULL, not a wrong sum)
* ratio                               -> SUM(num) / NULLIF(SUM(den), 0)

tests/test_portability.py executes these expressions on DuckDB and checks
they equal the reference compiler, so vendor artefacts inherit verified
semantics. Rules that cannot be folded (clarify) become warnings.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .compile_duckdb import render_literal
from .model import SemanticModel


@dataclass
class PortableMeasure:
    expr: str
    warnings: list[str] = field(default_factory=list)
    folded_rules: list[str] = field(default_factory=list)


def _period_key(entity, q: Callable[[str], str]) -> str | None:
    keys = [q(entity.dimensions[d].expr) for d in entity.time_key]
    if not keys:
        return None
    if len(keys) == 1:
        return keys[0]
    parts = ", '-', ".join(f"CAST({k} AS STRING)" for k in keys)
    return f"CONCAT({parts})"


def portable_measure(model: SemanticModel, metric_name: str, q: Callable[[str], str],
                     string_type: str = "STRING") -> PortableMeasure:
    """Return the aggregate SQL for a simple/ratio metric.

    `q(expr)` qualifies a row-level expression for the target engine.
    """
    m = model.metrics[metric_name]
    if m.type == "derived":
        raise ValueError("derived metrics are compiled per target")
    e = model.entities[m.entity]
    warnings, folded = [], []
    conds: list[str] = []
    if e.base_filter:
        conds.append(q(e.base_filter))
        folded.append("entity base filter")
    if m.filter:
        conds.append(q(m.filter))
        folded.append(f"metric filter {m.filter}")
    for c in model.constraints_for(metric_name):
        dim = e.dimensions[c.dimension]
        dexpr = q(dim.expr)
        if c.when_unconstrained == "sum_members" and c.total_value is not None:
            conds.append(f"{dexpr} <> {render_literal(dim, c.total_value)}")
            folded.append(f"{c.dimension}: total row {c.total_value!r} never counted")
        elif c.satisfied_by and c.when_unconstrained in ("use_total", "default"):
            warnings.append(f"{metric_name}: rule '{c.dimension}' (satisfied when {', '.join(c.satisfied_by)} is chosen) cannot "
                            "be expressed in a single aggregate; NOT folded. Consumers must filter it; summing hierarchical "
                            "members double counts in this target")
        elif c.when_unconstrained == "use_total":
            conds.append(f"{dexpr} = {render_literal(dim, c.total_value)}")
            folded.append(f"{c.dimension}: only published total row {c.total_value!r} counted")
            warnings.append(f"{metric_name}: breakdown by {c.dimension} is lost in this target (measure pinned to total row {c.total_value!r}); "
                            "the custom compiler switches to member rows when grouped")
        elif c.when_unconstrained == "default":
            conds.append(f"{dexpr} = {render_literal(dim, c.default_value)}")
            folded.append(f"{c.dimension}: pinned to {c.default_value!r}")
            warnings.append(f"{metric_name}: {c.dimension} pinned to {c.default_value!r} in this target; "
                            "other values need a separate metric (the custom compiler allows an explicit filter)")
        elif c.when_unconstrained == "clarify":
            warnings.append(f"{metric_name}: rule '{c.dimension} must be chosen' ({c.reason}) cannot be enforced in a single "
                            "aggregate; carried only as comment/instructions. Summing across it is possible here.")

    def agg(a: str, expr: str) -> str:
        cond = " AND ".join(f"({x})" for x in conds)
        if expr.strip() == "*":
            return f"COUNT(CASE WHEN {cond} THEN 1 END)" if cond else "COUNT(*)"
        inner = q(expr)
        if cond:
            inner = f"CASE WHEN {cond} THEN {inner} END"
        if a == "count_distinct":
            return f"COUNT(DISTINCT {inner})"
        return f"{a.upper()}({inner})"

    if m.type == "ratio":
        num = agg(m.numerator["agg"], str(m.numerator["expr"]))
        den = agg(m.denominator["agg"], str(m.denominator["expr"]))
        return PortableMeasure(f"CAST({num} AS DOUBLE) / NULLIF({den}, 0)", warnings, folded)

    base = agg(m.agg, m.expr)
    if m.null_policy == "propagate" and m.expr.strip() != "*":
        cond = " AND ".join(f"({x})" for x in conds) or "TRUE"
        base = (f"CASE WHEN COUNT(CASE WHEN {cond} THEN 1 END) = COUNT(CASE WHEN {cond} THEN {q(m.expr)} END) "
                f"THEN {base} END")
        folded.append("NULL (suppressed) inputs propagate to a NULL result")
    pk = _period_key(e, q)
    if m.additivity == "semi_additive" and pk:
        if m.time_rollup == "avg":
            if m.agg != "sum":
                raise ValueError(f"{metric_name}: avg rollup requires sum")
            base = f"CAST({base} AS DOUBLE) / NULLIF(COUNT(DISTINCT {pk}), 0)"
            folded.append("stock averaged across periods: SUM / COUNT(DISTINCT period)")
        elif m.time_rollup == "require_single":
            base = f"CASE WHEN COUNT(DISTINCT {pk}) <= 1 THEN {base} END"
            folded.append("returns NULL when more than one period is aggregated")
        elif m.time_rollup == "last":
            warnings.append(f"{metric_name}: 'last' rollup needs a target-specific construct")
    if string_type != "STRING":
        base = base.replace("AS STRING", f"AS {string_type}")
    return PortableMeasure(base, warnings, folded)
