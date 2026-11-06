"""Run the conversion-readiness rule catalog against one EDW-shaped extract.

    python erp_readiness/run_checks.py --label M1            # synthetic extract in data/synthetic/M1
    python erp_readiness/run_checks.py --data-dir <dir>      # any folder of Parquet files named like the EDW tables

Outputs (runs/<label>/): issue_register.csv (one row per rule), issues_detail.csv (one row per
failing entity), summary.json (register + domain readiness + examples). With several labels the
script also writes runs/trend.json across mock conversions.

On an approved machine the same rules run inside the warehouse: point source_map.yaml at the real
tables and execute the compiled SQL (compile_rules.py) - no data needs to leave the platform.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import duckdb

from common import (AS_OF, DATA_DIR, MOCK_CYCLES, RUNS_DIR, SOURCE_MAP_PATH, load_catalog, load_yaml,
                    params, render_sql, staging_sql, write_json)

EXAMPLES_PER_RULE = 5


def connect(data_dir: Path, source_map: dict | None = None) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    source_map = source_map or load_yaml(SOURCE_MAP_PATH)
    physical = {spec["table"] for spec in source_map["views"].values()}
    schema = source_map.get("physical_schema", "main")
    con.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
    for t in sorted(physical):
        f = data_dir / f"{t}.parquet"
        if not f.exists():
            raise FileNotFoundError(f"missing physical table {t} in {data_dir}")
        con.execute(f"CREATE OR REPLACE TABLE {schema}.{t} AS SELECT * FROM read_parquet('{f.as_posix()}')")
    for _, sql in staging_sql(source_map, "duckdb"):
        con.execute(sql)
    return con


def create_helpers(con, catalog: dict, as_of=AS_OF):
    for name, sql in catalog["helpers"].items():
        con.execute(f"CREATE OR REPLACE VIEW {name} AS {render_sql(sql, 'duckdb', as_of)}")


def scalar(con, sql: str):
    rows = con.execute(sql).fetchall()
    return rows[0][0] if rows else None


def run_rules(con, catalog: dict, as_of=AS_OF) -> list[dict]:
    pops = {k: int(scalar(con, render_sql(v, "duckdb", as_of)) or 0) for k, v in catalog["populations"].items()}
    sev = catalog["severity"]
    results = []
    for rule in catalog["rules"]:
        rows = con.execute(render_sql(rule["sql"], "duckdb", as_of)).fetchall()
        if rows and len(rows[0]) != 3:
            raise ValueError(f"{rule['id']}: rules must return (entity_type, entity_id, detail)")
        by_entity = {}
        for etype, eid, detail in rows:
            by_entity.setdefault(eid, (etype, detail))
        ids = sorted(by_entity)
        pop = pops[rule["population"]]
        fails = len(ids)
        rate = fails / pop if pop else 0.0
        tol = sev[rule["severity"]]["tolerance"]
        if fails == 0:
            rule_score = 1.0
        elif tol == 0:
            rule_score = 0.0
        else:
            rule_score = max(0.0, 1.0 - rate / tol)
        results.append(dict(
            rule_id=rule["id"], name=rule["name"], domain=rule["domain"], severity=rule["severity"],
            owner=rule["owner"], population=rule["population"], population_n=pop, failing=fails,
            failure_rate=round(rate, 6), rule_score=round(rule_score, 4),
            status="pass" if fails == 0 else ("fail" if rule_score == 0 else "warn"),
            examples=[dict(entity_type=by_entity[i][0], entity_id=i, detail=by_entity[i][1]) for i in ids[:EXAMPLES_PER_RULE]],
            entity_ids=ids,
        ))
    return results


def domain_scores(results: list[dict], catalog: dict) -> list[dict]:
    sev = catalog["severity"]
    out = []
    for dom, label in catalog["domains"].items():
        rs = [r for r in results if r["domain"] == dom]
        wsum = sum(sev[r["severity"]]["weight"] for r in rs)
        score = 100 * sum(sev[r["severity"]]["weight"] * r["rule_score"] for r in rs) / wsum if wsum else 100.0
        crit = sum(1 for r in rs if r["severity"] == "critical" and r["failing"])
        high = sum(1 for r in rs if r["severity"] == "high" and r["failing"])
        gate = "blocked" if crit else ("at_risk" if high else ("watch" if any(r["failing"] for r in rs) else "ready"))
        out.append(dict(domain=dom, label=label, score=round(score, 1), gate=gate, rules=len(rs),
                        failing_rules=sum(1 for r in rs if r["failing"]),
                        failing_entities=sum(r["failing"] for r in rs), critical_failing_rules=crit))
    return out


def run(label: str, data_dir: Path | None = None, out_dir: Path | None = None, as_of=AS_OF) -> dict:
    data_dir = data_dir or (DATA_DIR / label)
    out_dir = out_dir or (RUNS_DIR / label)
    catalog = load_catalog()
    con = connect(data_dir)
    create_helpers(con, catalog, as_of)
    results = run_rules(con, catalog, as_of)
    domains = domain_scores(results, catalog)
    manifest_path = data_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    summary = dict(
        label=label, as_of=as_of.isoformat(), params={k: v.isoformat() for k, v in params(as_of).items()},
        catalog_version=catalog["version"], data_dir=str(data_dir.name), synthetic=manifest.get("synthetic", False),
        overall_score=round(sum(d["score"] for d in domains) / len(domains), 1),
        totals=dict(rules=len(results), failing_rules=sum(1 for r in results if r["failing"]),
                    failing_entities=sum(r["failing"] for r in results),
                    by_severity={s: sum(r["failing"] for r in results if r["severity"] == s) for s in catalog["severity"]}),
        domains=domains,
        register=[{k: v for k, v in r.items() if k != "entity_ids"} for r in results],
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_dir / "summary.json", summary)
    with open(out_dir / "issue_register.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["rule_id", "name", "domain", "severity", "owner", "population", "population_n", "failing",
                    "failure_rate", "rule_score", "status", "example_ids"])
        for r in results:
            w.writerow([r["rule_id"], r["name"], r["domain"], r["severity"], r["owner"], r["population"], r["population_n"],
                        r["failing"], r["failure_rate"], r["rule_score"], r["status"],
                        "; ".join(e["entity_id"] for e in r["examples"])])
    with open(out_dir / "issues_detail.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["rule_id", "severity", "entity_type", "entity_id"])
        for r in results:
            for eid in r["entity_ids"]:
                w.writerow([r["rule_id"], r["severity"], r["examples"][0]["entity_type"] if r["examples"] else "", eid])
    con.close()
    summary["_entity_ids"] = {r["rule_id"]: r["entity_ids"] for r in results}
    return summary


def trend(labels: list[str], runs_dir: Path = RUNS_DIR) -> dict:
    series = []
    for lab in labels:
        s = json.loads((runs_dir / lab / "summary.json").read_text())
        series.append(dict(label=lab, overall_score=s["overall_score"], totals=s["totals"],
                           domains={d["domain"]: d["score"] for d in s["domains"]},
                           by_rule={r["rule_id"]: r["failing"] for r in s["register"]}))
    out = dict(labels=labels, series=series)
    write_json(runs_dir / "trend.json", out)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--label", action="append", help="extract label(s); default: all mock cycles")
    ap.add_argument("--data-dir", type=Path, help="override data folder (single label)")
    a = ap.parse_args(argv)
    labels = a.label or list(MOCK_CYCLES)
    for lab in labels:
        s = run(lab, a.data_dir if len(labels) == 1 else None)
        print(f"{lab}: overall {s['overall_score']}  failing rules {s['totals']['failing_rules']}/{s['totals']['rules']}"
              f"  entities {s['totals']['failing_entities']}")
    if len(labels) > 1:
        trend(labels)


if __name__ == "__main__":
    main()
