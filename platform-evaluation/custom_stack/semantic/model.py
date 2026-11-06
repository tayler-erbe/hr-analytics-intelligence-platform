"""Load and validate a portable semantic-layer spec (YAML).

The spec is the single source of truth. Compilers for DuckDB, Snowflake and
Databricks all read the objects defined here, so a definition can only differ
between targets where a compiler explicitly reports a portability warning.
"""
from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

SPEC_DIR = Path(__file__).resolve().parent / "specs"

AGGS = {"sum", "count", "count_distinct", "min", "max"}
METRIC_TYPES = {"simple", "ratio", "derived"}
ADDITIVITY = {"additive", "semi_additive", "non_additive"}
TIME_ROLLUPS = {"none", "avg", "last", "require_single"}
REL_TYPES = {"many_to_one", "one_to_one", "many_to_many", "one_to_many"}
DIM_TYPES = {"string", "integer", "number", "boolean", "date"}
UNCONSTRAINED_MODES = {"sum_members", "use_total", "default", "clarify"}
FILTER_OPS = {"eq", "ne", "in", "not_in", "gt", "gte", "lt", "lte", "between", "latest"}

_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class SpecError(ValueError):
    """The spec is internally inconsistent."""


@dataclass
class Dimension:
    name: str
    entity: str
    expr: str
    type: str = "string"
    description: str = ""
    synonyms: list[str] = field(default_factory=list)
    values: dict[str, list[str]] = field(default_factory=dict)
    is_time: bool = False
    value_pattern: str | None = None  # regex for open value sets (e.g. release labels)
    hierarchical: bool = False        # members nest/overlap: grouped rows must not be summed


@dataclass
class ConstrainedDimension:
    dimension: str
    when_unconstrained: str
    total_value: str | None = None
    default_value: str | None = None
    reason: str = ""
    satisfied_by: list[str] = field(default_factory=list)  # grouping/filtering these dims also satisfies the rule


@dataclass
class Entity:
    name: str
    table: str
    description: str
    grain: str
    primary_key: list[str]
    columns: dict[str, str]
    dimensions: dict[str, Dimension]
    sql: str | None = None
    physical_tables: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    time_dimensions: dict[str, str] = field(default_factory=dict)  # role -> dim name
    constrained: list[ConstrainedDimension] = field(default_factory=list)
    base_filter: str | None = None
    synonyms: list[str] = field(default_factory=list)  # source names ("qcew", "ipeds eap")

    @property
    def time_key(self) -> list[str]:
        order = ["year", "quarter", "month", "date"]
        return [self.time_dimensions[r] for r in order if r in self.time_dimensions]

    @property
    def sources(self) -> list[str]:
        """Physical tables that must exist for this entity."""
        return self.physical_tables if self.sql else [self.table]


@dataclass
class Relationship:
    name: str
    from_entity: str
    to_entity: str
    on: list[tuple[str, str]]
    type: str
    note: str = ""


@dataclass
class Metric:
    name: str
    label: str
    type: str
    description: str
    grain_rule: str
    unit: str
    additivity: str
    synonyms: list[str]
    entity: str | None = None
    agg: str | None = None
    expr: str | None = None
    numerator: dict | None = None
    denominator: dict | None = None
    formula: str | None = None
    components: list[str] = field(default_factory=list)
    filter: str | None = None
    time_rollup: str = "none"
    null_policy: str = "ignore"  # 'propagate': any NULL (e.g. suppressed cell) in a group makes the result NULL
    constrained: list = field(default_factory=list)  # metric-level ConstrainedDimension rules
    align_on: list = field(default_factory=list)     # derived: dims that define the common population (e.g. unitid)


@dataclass
class VerifiedQuery:
    name: str
    question: str
    plan: dict
    verified_by: str
    verified_at: str


@dataclass
class AbstainRule:
    id: str
    pattern: re.Pattern
    reason: str


@dataclass
class SemanticModel:
    name: str
    label: str
    description: str
    status: str
    path: Path
    sha256: str
    physical: dict
    targets: dict
    entities: dict[str, Entity]
    relationships: list[Relationship]
    metrics: dict[str, Metric]
    verified_queries: list[VerifiedQuery]
    abstain_rules: list[AbstainRule]
    ignorable_words: set[str]
    ambiguous_terms: dict[str, dict]

    # ------------------------------------------------------------------ paths
    def data_dir(self, override: str | os.PathLike | None = None) -> Path:
        if override:
            return Path(override)
        env = self.physical.get("data_dir_env")
        if env and os.environ.get(env):
            return Path(os.environ[env])
        return (self.path.parent / self.physical["default_data_dir"]).resolve()

    # ---------------------------------------------------------------- joins
    def reachable(self, entity: str) -> dict[str, list[Relationship]]:
        """Entities reachable WITHOUT fan-out (many_to_one / one_to_one only).

        Returns entity -> join path (list of relationships from `entity`).
        """
        paths: dict[str, list[Relationship]] = {entity: []}
        frontier = [entity]
        while frontier:
            nxt = []
            for e in frontier:
                for r in self.relationships:
                    if r.from_entity == e and r.type in ("many_to_one", "one_to_one") and r.to_entity not in paths:
                        paths[r.to_entity] = paths[e] + [r]
                        nxt.append(r.to_entity)
            frontier = nxt
        return paths

    def blocked_relationship(self, entity: str, dim_name: str) -> Relationship | None:
        """If `dim_name` lives on an entity only reachable through a fan-out
        relationship, return that relationship (used to explain refusals)."""
        for r in self.relationships:
            if r.type in ("many_to_many", "one_to_many") and entity in (r.from_entity, r.to_entity):
                other = r.to_entity if r.from_entity == entity else r.from_entity
                for e in [other, *self.reachable(other)]:
                    if dim_name in self.entities[e].dimensions:
                        return r
        return None

    def metric_entities(self, metric: str) -> list[str]:
        m = self.metrics[metric]
        if m.type == "derived":
            out: list[str] = []
            for c in m.components:
                for e in self.metric_entities(c):
                    if e not in out:
                        out.append(e)
            return out
        return [m.entity]

    def resolve_dimension(self, entity: str, dim_name: str) -> tuple[Dimension, list[Relationship]] | None:
        """Find dimension by name on `entity` or a non-fan-out joined entity.

        The metric's own entity wins; otherwise the nearest joined entity.
        Raises SpecError if two entities at the same distance both define it.
        """
        paths = self.reachable(entity)
        hits = [(len(p), e) for e, p in paths.items() if dim_name in self.entities[e].dimensions]
        if not hits:
            return None
        hits.sort()
        if len(hits) > 1 and hits[0][0] == hits[1][0]:
            raise SpecError(f"dimension {dim_name!r} is ambiguous from entity {entity!r}: {hits}")
        e = hits[0][1]
        return self.entities[e].dimensions[dim_name], paths[e]

    def available_dimensions(self, metric: str) -> dict[str, Dimension]:
        """Dimensions usable with `metric` (for derived: conformed across all components)."""
        sets = []
        for e in self.metric_entities(metric):
            dims = {}
            for re_, _path in self.reachable(e).items():
                for dn, d in self.entities[re_].dimensions.items():
                    dims.setdefault(dn, d)
            # the metric's own entity wins on name collisions
            dims.update(self.entities[e].dimensions)
            sets.append(dims)
        common = set(sets[0])
        for s in sets[1:]:
            common &= set(s)
        return {k: sets[0][k] for k in sorted(common)}

    def time_dimensions(self, metric: str) -> dict[str, str]:
        """role -> dimension name shared by every entity of the metric."""
        roles: dict[str, str] | None = None
        for e in self.metric_entities(metric):
            td = self.entities[e].time_dimensions
            roles = dict(td) if roles is None else {r: d for r, d in roles.items() if td.get(r) == d}
        return roles or {}

    def requires_single_time(self, metric: str) -> bool:
        m = self.metrics[metric]
        if m.type == "derived":
            return any(self.requires_single_time(c) for c in m.components)
        return m.time_rollup == "require_single"

    def constraints_for(self, metric: str, entity: str | None = None) -> list[ConstrainedDimension]:
        """Entity rules plus metric rules (metric rule wins for the same dimension)."""
        m = self.metrics[metric]
        if m.type == "derived":
            out = []
            for c in m.components:
                out += self.constraints_for(c)
            return out
        own = {c.dimension: c for c in m.constrained}
        return [c for c in self.entities[m.entity].constrained if c.dimension not in own] + list(own.values())

    def to_catalog(self) -> dict:
        """JSON-serialisable description for MCP clients and LLM backends."""
        return {
            "model": self.name,
            "label": self.label,
            "status": self.status,
            "spec_sha256": self.sha256,
            "metrics": [self.describe_metric(m) for m in self.metrics],
        }

    def describe_metric(self, name: str) -> dict:
        m = self.metrics[name]
        dims = self.available_dimensions(name)
        out = {
            "name": m.name,
            "label": m.label,
            "type": m.type,
            "unit": m.unit,
            "description": m.description,
            "grain_rule": m.grain_rule,
            "additivity": m.additivity,
            "time_rollup": m.time_rollup,
            "requires_single_time_period": self.requires_single_time(name),
            "synonyms": m.synonyms,
            "entities": [
                {"name": e, "source": self.entities[e].table, "grain": self.entities[e].grain}
                for e in self.metric_entities(name)
            ],
            "dimensions": [
                {"name": d.name, "type": d.type, "description": d.description,
                 "allowed_values": sorted(d.values) if d.values else None}
                for d in dims.values()
            ],
            "time_dimensions": self.time_dimensions(name),
            "constraints": [
                {"dimension": c.dimension, "when_unconstrained": c.when_unconstrained,
                 "total_value": c.total_value, "default_value": c.default_value, "reason": c.reason}
                for e in self.metric_entities(name) for c in self.constraints_for(name, e)
            ],
        }
        if m.type == "derived":
            out["formula"] = m.formula
            out["components"] = m.components
        if m.filter:
            out["metric_filter"] = m.filter
        return out


# ---------------------------------------------------------------- loading
def _require(d: dict, key: str, ctx: str) -> Any:
    if key not in d:
        raise SpecError(f"{ctx}: missing {key!r}")
    return d[key]


def _parse_constraints(items, dims: dict, ctx: str) -> list[ConstrainedDimension]:
    out = []
    for c in items or []:
        mode = c["when_unconstrained"]
        if mode not in UNCONSTRAINED_MODES:
            raise SpecError(f"{ctx}: bad when_unconstrained {mode}")
        if c["dimension"] not in dims:
            raise SpecError(f"{ctx}: constrained dimension {c['dimension']} not declared")
        if mode == "use_total" and c.get("total_value") is None:
            raise SpecError(f"{ctx}: use_total needs total_value")
        if mode == "default" and c.get("default_value") is None:
            raise SpecError(f"{ctx}: default mode needs default_value")
        for sd in c.get("satisfied_by") or []:
            if sd not in dims:
                raise SpecError(f"{ctx}: satisfied_by dimension {sd} not declared")
        out.append(ConstrainedDimension(
            dimension=c["dimension"], when_unconstrained=mode,
            total_value=None if c.get("total_value") is None else str(c["total_value"]),
            default_value=None if c.get("default_value") is None else str(c["default_value"]),
            reason=c.get("reason", ""), satisfied_by=list(c.get("satisfied_by") or [])))
    return out


def load_model(path: str | os.PathLike) -> SemanticModel:
    path = Path(path)
    raw_bytes = path.read_bytes()
    raw = yaml.safe_load(raw_bytes)
    ctx = str(path.name)
    if raw.get("spec_version") != 1:
        raise SpecError(f"{ctx}: unsupported spec_version {raw.get('spec_version')!r}")

    entities: dict[str, Entity] = {}
    for en, e in (raw.get("entities") or {}).items():
        ectx = f"{ctx} entity {en}"
        columns = {str(k): str(v) for k, v in (_require(e, "columns", ectx) or {}).items()}
        dims: dict[str, Dimension] = {}
        tdims = {str(k): str(v) for k, v in (e.get("time_dimensions") or {}).items()}
        for dn, d in (e.get("dimensions") or {}).items():
            dtype = d.get("type", "string")
            if dtype not in DIM_TYPES:
                raise SpecError(f"{ectx} dim {dn}: bad type {dtype}")
            values = {str(k): [str(x).lower() for x in (v or [])] for k, v in (d.get("values") or {}).items()}
            dims[dn] = Dimension(
                name=dn, entity=en, expr=str(_require(d, "expr", f"{ectx} dim {dn}")), type=dtype,
                description=d.get("description", ""), synonyms=[s.lower() for s in d.get("synonyms", [])],
                values=values, is_time=dn in tdims.values(), value_pattern=d.get("value_pattern"),
                hierarchical=bool(d.get("hierarchical", False)),
            )
            if dims[dn].value_pattern:
                re.compile(dims[dn].value_pattern)
        for role, dn in tdims.items():
            if dn not in dims:
                raise SpecError(f"{ectx}: time dimension {role}->{dn} not declared")
        constrained = _parse_constraints(e.get("constrained_dimensions"), dims, ectx)
        pk = list(_require(e, "primary_key", ectx))
        for k in pk:
            if k not in columns:
                raise SpecError(f"{ectx}: primary key column {k} not in columns")
        entities[en] = Entity(
            name=en, table=str(_require(e, "table", ectx)), description=e.get("description", "").strip(),
            grain=str(_require(e, "grain", ectx)), primary_key=pk, columns=columns, dimensions=dims,
            sql=e.get("sql"), physical_tables=list(e.get("physical_tables") or []),
            depends_on=list(e.get("depends_on") or []), time_dimensions=tdims,
            constrained=constrained, base_filter=e.get("base_filter"),
            synonyms=[str(x).lower() for x in e.get("synonyms", [])],
        )
        if entities[en].sql and not entities[en].physical_tables:
            raise SpecError(f"{ectx}: sql entity must list physical_tables")

    rels = []
    for r in raw.get("relationships") or []:
        if r["type"] not in REL_TYPES:
            raise SpecError(f"{ctx} relationship {r['name']}: bad type")
        for side in ("from", "to"):
            if r[side] not in entities:
                raise SpecError(f"{ctx} relationship {r['name']}: unknown entity {r[side]}")
        on = [(str(a), str(b)) for a, b in r["keys"]]
        for a, b in on:
            if a not in entities[r["from"]].columns or b not in entities[r["to"]].columns:
                raise SpecError(f"{ctx} relationship {r['name']}: join columns not declared")
        if r["type"] == "many_to_one":
            if sorted(b for _, b in on) != sorted(entities[r["to"]].primary_key):
                raise SpecError(f"{ctx} relationship {r['name']}: many_to_one must join to the full primary key of {r['to']}")
        rels.append(Relationship(r["name"], r["from"], r["to"], on, r["type"], r.get("note", "")))

    metrics: dict[str, Metric] = {}
    for mn, m in (raw.get("metrics") or {}).items():
        mctx = f"{ctx} metric {mn}"
        mtype = _require(m, "type", mctx)
        if mtype not in METRIC_TYPES:
            raise SpecError(f"{mctx}: bad type {mtype}")
        additivity = m.get("additivity", "additive")
        if additivity not in ADDITIVITY:
            raise SpecError(f"{mctx}: bad additivity")
        rollup = m.get("time_rollup", "none")
        if rollup not in TIME_ROLLUPS:
            raise SpecError(f"{mctx}: bad time_rollup")
        if additivity == "semi_additive" and rollup == "none":
            raise SpecError(f"{mctx}: semi_additive metrics must declare time_rollup")
        metric = Metric(
            name=mn, label=m.get("label", mn), type=mtype, description=m.get("description", ""),
            grain_rule=_require(m, "grain_rule", mctx), unit=m.get("unit", ""), additivity=additivity,
            synonyms=[s.lower() for s in m.get("synonyms", [])], entity=m.get("entity"),
            agg=m.get("agg"), expr=None if m.get("expr") is None else str(m.get("expr")),
            numerator=m.get("numerator"), denominator=m.get("denominator"),
            formula=m.get("formula"), filter=m.get("filter"), time_rollup=rollup,
            null_policy=m.get("null_policy", "ignore"),
        )
        if metric.null_policy not in ("ignore", "propagate"):
            raise SpecError(f"{mctx}: null_policy must be ignore or propagate")
        if m.get("constrained_dimensions"):
            if mtype == "derived":
                raise SpecError(f"{mctx}: put constraints on component metrics")
            metric.constrained = _parse_constraints(m["constrained_dimensions"], entities[metric.entity].dimensions
                                                    if metric.entity in entities else {}, mctx)
        if mtype in ("simple", "ratio"):
            if metric.entity not in entities:
                raise SpecError(f"{mctx}: unknown entity {metric.entity}")
        if mtype == "simple":
            if metric.agg not in AGGS:
                raise SpecError(f"{mctx}: agg must be one of {sorted(AGGS)} (use a ratio metric for averages)")
            if metric.expr is None:
                raise SpecError(f"{mctx}: missing expr")
        if mtype == "ratio":
            for part in ("numerator", "denominator"):
                p = getattr(metric, part)
                if not p or p.get("agg") not in AGGS or "expr" not in p:
                    raise SpecError(f"{mctx}: bad {part}")
            if rollup != "none":
                raise SpecError(f"{mctx}: ratio metrics are re-aggregated from sums; time_rollup not allowed")
        if mtype == "derived":
            if not metric.formula:
                raise SpecError(f"{mctx}: derived metric needs formula")
            metric.components = list(dict.fromkeys(re.findall(r"\{([a-z0-9_]+)\}", metric.formula)))
            metric.align_on = list(m.get("align_on") or [])
        metrics[mn] = metric
    for metric in metrics.values():
        for c in metric.components:
            if c not in metrics or metrics[c].type == "derived":
                raise SpecError(f"{ctx} metric {metric.name}: component {c} must be a non-derived metric")

    vqs = [VerifiedQuery(v["name"], v["question"], v["plan"], v.get("verified_by", ""), str(v.get("verified_at", "")))
           for v in raw.get("verified_queries") or []]
    rules = [AbstainRule(r["id"], re.compile(r["pattern"], re.I), r["reason"]) for r in raw.get("abstain_rules") or []]
    amb = {}
    for term, a in (raw.get("ambiguous_terms") or {}).items():
        for o in a["options"]:
            if o not in metrics:
                raise SpecError(f"{ctx}: ambiguous term {term} option {o} unknown")
        amb[term.lower()] = a

    model = SemanticModel(
        name=raw["model"], label=raw.get("label", raw["model"]), description=str(raw.get("description", "")).strip(),
        status=raw.get("status", "development"), path=path.resolve(), sha256=hashlib.sha256(raw_bytes).hexdigest(),
        physical=raw["physical"], targets=raw.get("targets", {}), entities=entities, relationships=rels,
        metrics=metrics, verified_queries=vqs, abstain_rules=rules,
        ignorable_words={str(w).lower() for w in raw.get("ignorable_words", [])}, ambiguous_terms=amb,
    )
    # derived metrics must have at least one conformed dimension set (may be empty) - check resolvable
    for metric in metrics.values():
        avail = model.available_dimensions(metric.name)
        for a in metric.align_on:
            if a not in avail:
                raise SpecError(f"{ctx} metric {metric.name}: align_on dimension {a} is not conformed across components")
            for c in metric.components:
                if metrics[c].additivity == "non_additive":
                    raise SpecError(f"{ctx} metric {metric.name}: align_on needs additive components ({c} is not)")
    return model


def load_all(spec_dir: str | os.PathLike = SPEC_DIR) -> dict[str, SemanticModel]:
    models = {}
    for p in sorted(Path(spec_dir).glob("*.yaml")):
        m = load_model(p)
        models[m.name] = m
    return models


# ------------------------------------------------------------ expressions
_STRING_LIT = re.compile(r"'(?:[^']|'')*'")


def qualify(expr: str, alias: str, columns: dict[str, str] | set[str]) -> str:
    """Prefix bare column identifiers in `expr` with `alias.` (string literals untouched)."""
    cols = set(columns)
    out, pos = [], 0
    for lit in _STRING_LIT.finditer(expr):
        out.append(_qualify_segment(expr[pos:lit.start()], alias, cols))
        out.append(lit.group(0))
        pos = lit.end()
    out.append(_qualify_segment(expr[pos:], alias, cols))
    return "".join(out)


def _qualify_segment(seg: str, alias: str, cols: set[str]) -> str:
    def rep(m: re.Match) -> str:
        start = m.start()
        if start > 0 and seg[start - 1] == ".":
            return m.group(0)
        return f"{alias}.{m.group(0)}" if m.group(0) in cols else m.group(0)
    return _IDENT.sub(rep, seg)


def referenced_columns(expr: str, columns: dict[str, str] | set[str]) -> set[str]:
    stripped = _STRING_LIT.sub("''", expr)
    return {t for t in _IDENT.findall(stripped) if t in set(columns)}
