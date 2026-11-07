"""Run the 43-rule conversion-readiness catalog on the v3 Data-Cookbook-shaped synthetic EDW pack.

    python erp_readiness/v3/run_v3.py                         # both sets -> erp_readiness/v3/runs/<set>/
    python erp_readiness/v3/run_v3.py --set CLEAN --switch job_change_date=recorded
    python erp_readiness/v3/run_v3.py --write-results         # also rewrite v3/RESULTS.md (committed summary)

The catalog (rules/catalog.yaml), common.py and run_checks.py are reused unchanged. Only the source map
differs: rules/source_map_v3_cookbook.yaml binds the logical views to the Cookbook tables through a
`prepared` view layer and a set of documented switches (`${token}` substitution, --switch name=value).

Outputs per set: issue_register.csv, issues_detail.csv, summary.json, compiled_duckdb.sql (prepared +
staging + helpers + 43 rules + supplementary checks, as executed). Rules the pack cannot support are
reported as unbound / not_evaluable / vacuous and are excluded from domain scores, never counted as a pass.
"""
from __future__ import annotations

import argparse
import copy
import csv
import datetime as dt
import json
import re
import sys
from pathlib import Path

import duckdb

HERE = Path(__file__).resolve().parent            # erp_readiness/v3/
ERP = HERE.parent                                  # erp_readiness/
sys.path.insert(0, str(ERP))

import run_checks  # noqa: E402
from common import (PE_ROOT, RULES_DIR, load_catalog, load_yaml, params, render_sql,  # noqa: E402
                    staging_sql, write_json)

V3_SOURCE_MAP_PATH = RULES_DIR / "source_map_v3_cookbook.yaml"
SUPPLEMENTARY_PATH = HERE / "supplementary_rules.yaml"
V3_RUNS_DIR = HERE / "runs"                        # git-ignored by erp_readiness/.gitignore (runs/)
RESULTS_MD = HERE / "RESULTS.md"
SETS = ("longitudinal", "CLEAN")
TOKEN = re.compile(r"\$\{(\w+)\}")
NON_SCORED = ("unbound", "not_evaluable", "vacuous")


# ---------------------------------------------------------------- source map + switches
def resolve_switches(smap: dict, overrides: dict[str, str] | None = None) -> dict[str, str]:
    chosen = {}
    for name, spec in smap.get("switches", {}).items():
        val = (overrides or {}).get(name, spec["default"])
        if val not in spec["options"]:
            raise ValueError(f"switch {name}: unknown value {val!r}; options {sorted(spec['options'])}")
        chosen[name] = val
    unknown = set(overrides or {}) - set(chosen)
    if unknown:
        raise ValueError(f"unknown switch(es): {sorted(unknown)}")
    return chosen


def _substitute(text: str, smap: dict, chosen: dict[str, str]) -> str:
    for _ in range(10):                      # options may themselves contain tokens (nested)
        if not TOKEN.search(text):
            return text
        text = TOKEN.sub(lambda m: str(smap["switches"][m.group(1)]["options"][chosen[m.group(1)]]), text)
    raise ValueError("switch substitution did not converge")


def load_source_map(overrides: dict[str, str] | None = None, path: Path = V3_SOURCE_MAP_PATH) -> dict:
    """Load the v3 map with every `${switch}` token replaced by the chosen option's text."""
    raw = load_yaml(path)
    chosen = resolve_switches(raw, overrides)
    smap = copy.deepcopy(raw)

    def walk(node):
        if isinstance(node, str):
            return _substitute(node, raw, chosen)
        if isinstance(node, dict):
            return {k: walk(v) for k, v in node.items()}
        if isinstance(node, list):
            return [walk(v) for v in node]
        return node

    smap["prepared"] = walk(raw["prepared"])
    smap["views"] = walk(raw["views"])
    smap["_switches"] = chosen
    return smap


# ---------------------------------------------------------------- physical layer
def load_physical(con: duckdb.DuckDBPyConnection, smap: dict, data_dir: Path) -> dict[str, bool]:
    """Load each raw table from Parquet (or an empty fallback). Returns {table: present}."""
    schema = smap["physical_schema"]
    con.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
    present = {}
    for t, spec in smap["physical_tables"].items():
        f = data_dir / f"{t}.parquet"
        if f.exists():
            con.execute(f"CREATE OR REPLACE TABLE {schema}.{t} AS SELECT * FROM read_parquet('{f.as_posix()}')")
            present[t] = True
        elif spec.get("optional"):
            cols = ", ".join(f"{c} {ty}" for c, ty in spec["fallback_columns"].items())
            con.execute(f"CREATE OR REPLACE TABLE {schema}.{t} ({cols})")
            present[t] = False
        else:
            raise FileNotFoundError(f"required Cookbook table {t} missing from {data_dir}")
    return present


def prepared_sql(smap: dict) -> list[tuple[str, str]]:
    schema = smap["physical_schema"]
    return [(p["name"], f"CREATE OR REPLACE VIEW {schema}.{p['name']} AS {p['sql'].strip()}") for p in smap["prepared"]]


def connect(data_dir: Path, smap: dict) -> tuple[duckdb.DuckDBPyConnection, dict[str, bool]]:
    con = duckdb.connect()
    present = load_physical(con, smap, data_dir)
    for _, sql in prepared_sql(smap):
        con.execute(sql)
    for _, sql in staging_sql(smap, "duckdb"):
        con.execute(sql)
    return con, present


def compiled_script(smap: dict, catalog: dict, supplementary: dict | None, as_of: dt.date) -> str:
    """Everything run_v3 executes after the raw tables exist, as one DuckDB script (for review and tests)."""
    out = [f"-- v3 Cookbook binding, switches {json.dumps(smap['_switches'])}, as_of {as_of}", "-- prepared views"]
    out += [s + ";" for _, s in prepared_sql(smap)]
    out.append("-- staging views")
    out += [s + ";" for _, s in staging_sql(smap, "duckdb")]
    out.append("-- helpers")
    out += [f"CREATE OR REPLACE VIEW {n} AS {render_sql(s, 'duckdb', as_of).strip()};" for n, s in catalog["helpers"].items()]
    out.append("-- rules")
    for r in catalog["rules"]:
        out.append(f"-- {r['id']} [{r['severity']}] {r['name']}\n{render_sql(r['sql'], 'duckdb', as_of).strip()};")
    if supplementary:
        out.append("-- supplementary v3 checks (not part of the catalog)")
        for r in supplementary["rules"]:
            out.append(f"-- {r['id']} [{r['severity']}] {r['name']}\n{render_sql(r['sql'], 'duckdb', as_of).strip()};")
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------- evaluability
def _words(sql: str) -> set[str]:
    return set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", sql))


def rule_dependencies(smap: dict, catalog: dict) -> dict[str, dict]:
    """For each rule: logical views it touches (through helpers/populations) and the raw tables behind them."""
    schema = smap["physical_schema"]
    views = smap["views"]
    helpers = catalog["helpers"]
    prepared = {p["name"]: p["sql"] for p in smap["prepared"]}
    raw_tables = set(smap["physical_tables"])

    def raw_behind(table: str, seen=None) -> set[str]:
        seen = seen or set()
        if table in raw_tables:
            return {table}
        out = set()
        for ref in re.findall(rf"\b{schema}\.(\w+)", prepared.get(table, "")):
            if ref not in seen:
                seen.add(ref)
                out |= raw_behind(ref, seen)
        return out

    def views_in(sql: str, depth=0) -> set[str]:
        w = _words(sql)
        found = {v for v in views if v in w}
        if depth < 4:
            for h in helpers:
                if h in w:
                    found |= views_in(helpers[h], depth + 1)
        return found

    deps = {}
    for r in catalog["rules"]:
        vs = views_in(r["sql"]) | views_in(catalog["populations"][r["population"]])
        tables = set()
        for v in vs:
            tables |= raw_behind(views[v]["table"])
        deps[r["id"]] = dict(views=sorted(vs), raw_tables=sorted(tables))
    return deps


def null_columns(con, smap: dict) -> dict[str, list[str]]:
    """Logical columns that are NULL on every row of their staging view (or views that are empty)."""
    out = {}
    for view, spec in smap["views"].items():
        cols = list(spec["columns"])
        n = con.execute(f"SELECT COUNT(*) FROM {view}").fetchone()[0]
        if n == 0:
            out[view] = cols
            continue
        counts = con.execute("SELECT " + ", ".join(f"COUNT({c})" for c in cols) + f" FROM {view}").fetchone()
        out[view] = [c for c, k in zip(cols, counts) if k == 0]
    return out


def classify(results: list[dict], smap: dict, catalog: dict, present: dict[str, bool], nulls: dict[str, list[str]]) -> None:
    """Overwrite `status` with unbound / not_evaluable / vacuous where the pack cannot support a rule."""
    deps = rule_dependencies(smap, catalog)
    bindings = smap["rule_bindings"]
    for r in results:
        rid = r["rule_id"]
        b = bindings[rid]
        r["raw_tables"] = deps[rid]["raw_tables"]
        r["binding_note"] = ""
        if b.get("unbound"):
            r["status"], r["binding_note"] = "unbound", b["unbound"]
            continue
        absent = [t for t in deps[rid]["raw_tables"] if not present.get(t, False)]
        if absent:
            r["status"], r["binding_note"] = "not_evaluable", f"table(s) absent from this set: {', '.join(absent)}"
            continue
        null_deps = [c for c in b["columns"] if c.split(".")[1] in nulls.get(c.split(".")[0], [])]
        if null_deps and r["failing"] == 0:
            r["status"], r["binding_note"] = "vacuous", f"NULL on every row: {', '.join(null_deps)}"


# ---------------------------------------------------------------- supplementary checks
def run_supplementary(con, supp: dict, as_of: dt.date) -> list[dict]:
    out = []
    for rule in supp["rules"]:
        pop = int(con.execute(render_sql(rule["population_sql"], "duckdb", as_of)).fetchone()[0] or 0)
        rows = con.execute(render_sql(rule["sql"], "duckdb", as_of)).fetchall()
        by_entity = {}
        for etype, eid, detail in rows:
            by_entity.setdefault(eid, (etype, detail))
        ids = sorted(by_entity)
        out.append(dict(rule_id=rule["id"], name=rule["name"], domain="v3_supplementary", severity=rule["severity"],
                        owner=rule["owner"], population=rule["population"], population_n=pop, failing=len(ids),
                        failure_rate=round(len(ids) / pop, 6) if pop else 0.0, rule_score=None,
                        status="pass" if not ids else "fail", binding_note=rule.get("note", ""),
                        examples=[dict(entity_type=by_entity[i][0], entity_id=i, detail=by_entity[i][1]) for i in ids[:run_checks.EXAMPLES_PER_RULE]],
                        entity_ids=ids))
    return out


# ---------------------------------------------------------------- run one set
def run_set(set_name: str, data_dir: Path | None = None, out_dir: Path | None = None, switches: dict | None = None,
            as_of: dt.date | None = None, pack_dir: Path | None = None) -> dict:
    catalog = load_catalog()
    smap = load_source_map(switches)
    supp = load_yaml(SUPPLEMENTARY_PATH) if SUPPLEMENTARY_PATH.exists() else None
    pack_dir = pack_dir or (PE_ROOT / smap["pack_dir"])
    data_dir = data_dir or (pack_dir / set_name)
    out_dir = out_dir or (V3_RUNS_DIR / set_name)
    manifest_path = data_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    as_of = as_of or dt.date.fromisoformat(manifest.get("extract_date", run_checks.AS_OF.isoformat()))

    con, present = connect(data_dir, smap)
    run_checks.create_helpers(con, catalog, as_of)
    results = run_checks.run_rules(con, catalog, as_of)
    nulls = null_columns(con, smap)
    classify(results, smap, catalog, present, nulls)
    scored = [r for r in results if r["status"] not in NON_SCORED]
    domains = run_checks.domain_scores(scored, catalog)
    for d in domains:                                   # rules per domain incl. the excluded ones
        d["rules"] = sum(1 for r in results if r["domain"] == d["domain"])
        d["excluded_rules"] = sorted(r["rule_id"] for r in results if r["domain"] == d["domain"] and r["status"] in NON_SCORED)
    supplementary = run_supplementary(con, supp, as_of) if supp else []
    script = compiled_script(smap, catalog, supp, as_of)
    con.close()

    summary = dict(
        label=f"v3_{set_name}", set=set_name, as_of=as_of.isoformat(),
        params={k: v.isoformat() for k, v in params(as_of).items()},
        catalog_version=catalog["version"], source_map="rules/source_map_v3_cookbook.yaml",
        switches=smap["_switches"], data_dir=str(data_dir.relative_to(PE_ROOT)) if data_dir.is_relative_to(PE_ROOT) else str(data_dir),
        synthetic=manifest.get("synthetic", False), tables_present=present,
        null_logical_columns={v: c for v, c in nulls.items() if c},
        overall_score=round(sum(d["score"] for d in domains) / len(domains), 1),
        totals=dict(rules=len(results), scored_rules=len(scored),
                    failing_rules=sum(1 for r in scored if r["failing"]),
                    failing_entities=sum(r["failing"] for r in scored),
                    by_severity={s: sum(r["failing"] for r in scored if r["severity"] == s) for s in catalog["severity"]},
                    by_status={s: sum(1 for r in results if r["status"] == s)
                               for s in ("pass", "warn", "fail", "unbound", "not_evaluable", "vacuous")}),
        domains=domains,
        register=[{k: v for k, v in r.items() if k != "entity_ids"} for r in results],
        supplementary=[{k: v for k, v in r.items() if k != "entity_ids"} for r in supplementary],
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_dir / "summary.json", summary)
    (out_dir / "compiled_duckdb.sql").write_text(script, encoding="utf-8")
    with open(out_dir / "issue_register.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["rule_id", "name", "domain", "severity", "owner", "population", "population_n", "failing",
                    "failure_rate", "rule_score", "status", "binding_note", "example_ids"])
        for r in results + supplementary:
            w.writerow([r["rule_id"], r["name"], r["domain"], r["severity"], r["owner"], r["population"], r["population_n"],
                        r["failing"], r["failure_rate"], r["rule_score"], r["status"], r["binding_note"],
                        "; ".join(str(e["entity_id"]) for e in r["examples"])])
    with open(out_dir / "issues_detail.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["rule_id", "severity", "entity_type", "entity_id"])
        for r in results + supplementary:
            for eid in r["entity_ids"]:
                w.writerow([r["rule_id"], r["severity"], r["examples"][0]["entity_type"] if r["examples"] else "", eid])
    summary["_entity_ids"] = {r["rule_id"]: r["entity_ids"] for r in results + supplementary}
    return summary


# ---------------------------------------------------------------- committed summary
def _md(text) -> str:
    return str(text).replace("|", "\\|")


def write_results_md(summaries: dict[str, dict], path: Path = RESULTS_MD) -> None:
    L = ["# v3 Cookbook binding: run results (generated by run_v3.py --write-results)", "",
         "Synthetic data only. Rules with status unbound / not_evaluable / vacuous are excluded from the scores.", ""]
    L += ["| Set | as-of | Switches | Overall | Scored rules | Failing rules | Failing entities (crit/high/med) | Unbound / not evaluable / vacuous |", "|---|---|---|---:|---:|---:|---|---|"]
    for s in summaries.values():
        t, st = s["totals"], s["totals"]["by_status"]
        L.append(f"| {s['set']} | {s['as_of']} | {', '.join(f'{k}={v}' for k, v in s['switches'].items())} | {s['overall_score']} | {t['scored_rules']}/{t['rules']} | {t['failing_rules']} | "
                 f"{t['failing_entities']} ({t['by_severity']['critical']}/{t['by_severity']['high']}/{t['by_severity']['medium']}) | {st['unbound']} / {st['not_evaluable']} / {st['vacuous']} |")
    for s in summaries.values():
        L += ["", f"## {s['set']}", "", "### Domain readiness", "", "| Domain | Score | Gate | Rules (excluded) | Failing rules | Failing entities |", "|---|---:|---|---|---:|---:|"]
        for d in s["domains"]:
            exc = f" ({', '.join(d['excluded_rules'])})" if d["excluded_rules"] else ""
            L.append(f"| {d['label']} | {d['score']} | {d['gate']} | {d['rules']}{exc} | {d['failing_rules']} | {d['failing_entities']} |")
        L += ["", "### Rules with findings or a binding limitation", "", "| Rule | Sev | Status | Failing / population | Note or first example |", "|---|---|---|---:|---|"]
        for r in s["register"]:
            if r["status"] == "pass":
                continue
            ex = r["binding_note"] or (f"{r['examples'][0]['entity_id']}: {r['examples'][0]['detail']}" if r["examples"] else "")
            L.append(f"| {r['rule_id']} {r['name']} | {r['severity']} | {r['status']} | {r['failing']} / {r['population_n']} | {_md(ex)} |")
        if s["supplementary"]:
            L += ["", "### Supplementary v3 checks (outside the catalog, not scored)", "", "| Check | Sev | Failing / population | First example |", "|---|---|---:|---|"]
            for r in s["supplementary"]:
                ex = f"{r['examples'][0]['entity_id']}: {r['examples'][0]['detail']}" if r["examples"] else ""
                L.append(f"| {r['rule_id']} {r['name']} | {r['severity']} | {r['failing']} / {r['population_n']} | {_md(ex)} |")
    path.write_text("\n".join(L) + "\n", encoding="utf-8")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--set", action="append", choices=SETS, help="v3 set(s); default both")
    ap.add_argument("--pack-dir", type=Path, help="override sample_datasets/v3_cookbook")
    ap.add_argument("--data-dir", type=Path, help="override the data folder (single set)")
    ap.add_argument("--out-dir", type=Path, help="override the output folder (single set)")
    ap.add_argument("--as-of", type=dt.date.fromisoformat, help="override the manifest extract date")
    ap.add_argument("--switch", action="append", default=[], metavar="NAME=VALUE")
    ap.add_argument("--write-results", action="store_true", help="rewrite v3/RESULTS.md from this run")
    a = ap.parse_args(argv)
    switches = dict(s.split("=", 1) for s in a.switch)
    sets = a.set or list(SETS)
    single = len(sets) == 1
    summaries = {}
    for s in sets:
        summ = run_set(s, data_dir=a.data_dir if single else None, out_dir=a.out_dir if single else None,
                       switches=switches, as_of=a.as_of, pack_dir=a.pack_dir)
        summaries[s] = summ
        t = summ["totals"]
        print(f"{s}: overall {summ['overall_score']}  failing rules {t['failing_rules']}/{t['scored_rules']} scored "
              f"({t['rules']} total; status {t['by_status']})  entities {t['failing_entities']}")
    if a.write_results:
        write_results_md(summaries)
        print(f"wrote {RESULTS_MD}")


if __name__ == "__main__":
    main()
