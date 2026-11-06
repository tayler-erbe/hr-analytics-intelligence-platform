"""Compile the portable spec to Databricks Unity Catalog metric views (YAML v1.1).

A metric view has ONE source (fact) plus many-to-one joins, so the compiler
emits one metric view per entity that owns metrics. Dimensions of joined
entities are exposed through join names. Cross-entity derived metrics cannot
live in a single metric view and are reported as warnings.

Not executed against a Databricks workspace from this repository. Wrap each
YAML in `CREATE OR REPLACE VIEW <catalog>.<schema>.<name> WITH METRICS
LANGUAGE YAML AS $$ ... $$` (emitted alongside) and validate there.
"""
from __future__ import annotations

import re

import yaml

from .model import SemanticModel, qualify
from .portable import portable_measure


def _fq(model: SemanticModel, table: str) -> str:
    t = model.targets.get("databricks", {})
    return f"{t.get('catalog', 'hr_analytics')}.{t.get('schema', 'hr_public')}.{table}"


def _joins(model: SemanticModel, entity: str) -> list[dict]:
    """Nested join tree following only many_to_one / one_to_one relationships."""
    def children(name: str, alias_of_parent: str, seen: set[str]) -> list[dict]:
        out = []
        for r in model.relationships:
            if r.from_entity == name and r.type in ("many_to_one", "one_to_one") and r.to_entity not in seen:
                to = model.entities[r.to_entity]
                cond = " AND ".join(f"{alias_of_parent}.{a} = {to.name}.{b}" for a, b in r.on)
                j = {"name": to.name, "source": _fq(model, to.table), "on": cond}
                sub = children(to.name, to.name, seen | {to.name})
                if sub:
                    j["joins"] = sub
                out.append(j)
        return out
    return children(entity, "source", {entity})


def metric_views(model: SemanticModel) -> tuple[dict[str, str], list[str]]:
    """Return ({view_name: yaml_text}, warnings)."""
    warnings: list[str] = []
    views: dict[str, str] = {}
    owners: dict[str, list[str]] = {}
    for mn, m in model.metrics.items():
        if m.type == "derived":
            ents = model.metric_entities(mn)
            if len(ents) > 1:
                warnings.append(f"{mn}: derived across entities {ents}; a UC metric view has a single source, so this "
                                "metric is NOT emitted (compose two metric-view queries or materialise a joined aggregate)")
                continue
            owners.setdefault(ents[0], []).append(mn)
            continue
        owners.setdefault(m.entity, []).append(mn)

    for en, mnames in owners.items():
        e = model.entities[en]
        reach = model.reachable(en)
        dims = []
        seen = set()
        for target, path in sorted(reach.items(), key=lambda kv: len(kv[1])):
            te = model.entities[target]
            for dn, d in te.dimensions.items():
                if dn in seen:
                    continue
                seen.add(dn)
                expr = d.expr if target == en else qualify(d.expr, te.name, te.columns)
                dd = {"name": dn, "expr": expr, "comment": d.description}
                if d.synonyms:
                    dd["synonyms"] = list(dict.fromkeys(d.synonyms))[:10]
                dims.append(dd)
        measures = []
        for mn in mnames:
            m = model.metrics[mn]
            if m.type == "derived":
                expr = re.sub(r"\{([a-z0-9_]+)\}", lambda mm: f"MEASURE({mm.group(1)})", m.formula)
            else:
                pm = portable_measure(model, mn, lambda x: x)
                warnings += pm.warnings
                expr = pm.expr
            md = {"name": mn, "expr": expr, "comment": f"{m.description} Unit: {m.unit}. Grain rule: {m.grain_rule}"}
            if m.synonyms:
                md["synonyms"] = list(dict.fromkeys(m.synonyms))[:10]
            measures.append(md)
        doc: dict = {"version": "1.1",
                     "comment": f"{e.description} Grain: {e.grain}. Generated from {model.path.name} sha256 {model.sha256[:16]}; "
                                f"status {model.status}.",
                     "source": _fq(model, e.table)}
        if e.base_filter:
            doc["filter"] = e.base_filter
        j = _joins(model, en)
        if j:
            doc["joins"] = j
        doc["dimensions"] = dims
        doc["measures"] = measures
        views[f"{en}_metrics"] = yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=120)
    for e in model.entities.values():
        if e.sql:
            warnings.append(f"entity {e.name}: logical SQL view must be created in Unity Catalog first (dialect not executed here)")
    for r in model.relationships:
        if r.type not in ("many_to_one", "one_to_one"):
            warnings.append(f"relationship {r.name} ({r.type}) intentionally omitted: {r.note}")
    return views, list(dict.fromkeys(warnings))


def metric_view_ddl(model: SemanticModel, views: dict[str, str]) -> str:
    out = [f"-- Generated from {model.path.name} (sha256 {model.sha256[:16]}); NOT executed against Databricks here."]
    for e in model.entities.values():
        if e.sql:
            out.append(f"CREATE OR REPLACE VIEW {_fq(model, e.table)} AS\n{e.sql.strip()};\n")
    for name, text in views.items():
        out.append(f"CREATE OR REPLACE VIEW {_fq(model, name)}\nWITH METRICS\nLANGUAGE YAML\nAS $$\n{text}$$;\n")
    return "\n".join(out)
