"""Parse archived O*NET releases into long panel tables (native O*NET-SOC codes).

Inputs : data/lake/raw/onet_history/releases/db_*.zip, crosswalks/*.csv
Outputs: data/lake/raw/onet_history/derived/*.parquet (gitignored lake area)
         job_evolution/artifacts/release_inventory.json

Tables (one row per release x ...):
  occupations  release, code, title
  tasks        release, code, task_id, task, task_type, date, source
  ratings      release, domain (skills|gwa), code, element_id, element_name, scale, value, date, source
  tech         release, code, example, category, hot, in_demand   (technology/software only)
  job_zones    release, code, job_zone, date
  emerging     release, code, task, category, original_task_id, date, source
  crosswalk    from_tax, to_tax, from_code, to_code
"""
from __future__ import annotations

import csv
import io
import sys
import zipfile

import pyarrow as pa
import pyarrow.parquet as pq

from common import ART, DERIVED, RAW, RELEASES, dump_json, sha256_file

csv.field_size_limit(1 << 30)


def read_member(z: zipfile.ZipFile, name: str) -> list[dict] | None:
    hits = [n for n in z.namelist() if n.rsplit("/", 1)[-1] == name]
    if not hits:
        return None
    raw = z.read(hits[0])
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("cp1252")
    text = text.lstrip("﻿")
    rdr = csv.DictReader(io.StringIO(text), delimiter="\t", quoting=csv.QUOTE_NONE)
    return [{k.strip(): (v.strip() if isinstance(v, str) else v) for k, v in r.items() if k} for r in rdr]


def parse_release(version: str, path) -> dict[str, list[dict]]:
    z = zipfile.ZipFile(path)
    out = {k: [] for k in ("occupations", "tasks", "ratings", "tech", "job_zones", "emerging")}
    for r in read_member(z, "Occupation Data.txt"):
        out["occupations"].append({"release": version, "code": r["O*NET-SOC Code"], "title": r["Title"]})
    for r in read_member(z, "Task Statements.txt"):
        out["tasks"].append({"release": version, "code": r["O*NET-SOC Code"], "task_id": r["Task ID"],
                             "task": r["Task"], "task_type": r.get("Task Type") or None,
                             "date": r.get("Date") or None, "source": r.get("Domain Source") or None})
    skill_files = ["Skills.txt"] if read_member(z, "Skills.txt") is not None else \
        ["Essential Skills.txt", "Transferable Skills.txt"]
    for domain, files in (("skills", skill_files), ("gwa", ["Work Activities.txt"])):
        for f in files:
            for r in read_member(z, f) or []:
                if r["Scale ID"] not in ("IM", "LV"):
                    continue
                try:
                    val = float(r["Data Value"])
                except (TypeError, ValueError):
                    continue
                out["ratings"].append({"release": version, "domain": domain, "code": r["O*NET-SOC Code"],
                                       "element_id": r["Element ID"], "element_name": r["Element Name"],
                                       "scale": r["Scale ID"], "value": val, "date": r.get("Date") or None,
                                       "source": r.get("Domain Source") or None})
    # Technology examples: Technology Skills (24.0-30.x) > Software Skills (31.0) >
    # Tools and Technology with T2 Type = Technology (21.0-23.x).
    ts = read_member(z, "Technology Skills.txt")
    ss = read_member(z, "Software Skills.txt")
    tt = read_member(z, "Tools and Technology.txt")
    if ts is not None:
        rows = [(r["O*NET-SOC Code"], r["Example"], r["Commodity Title"], r.get("Hot Technology"),
                 r.get("In Demand")) for r in ts]
    elif ss is not None:
        rows = [(r["O*NET-SOC Code"], r["Workplace Example"], r["Element Name"], r.get("Hot Technology"),
                 r.get("In Demand")) for r in ss]
    elif tt is not None:
        rows = [(r["O*NET-SOC Code"], r["T2 Example"], r["Commodity Title"], r.get("Hot Technology"), None)
                for r in tt if r.get("T2 Type") == "Technology"]
    else:
        rows = []
    seen = set()
    for code, ex, cat, hot, dem in rows:
        if (code, ex) in seen:
            continue
        seen.add((code, ex))
        out["tech"].append({"release": version, "code": code, "example": ex, "category": cat,
                            "hot": None if hot in (None, "") else hot == "Y",
                            "in_demand": None if dem in (None, "") else dem == "Y"})
    for r in read_member(z, "Job Zones.txt") or []:
        out["job_zones"].append({"release": version, "code": r["O*NET-SOC Code"],
                                 "job_zone": int(r["Job Zone"]), "date": r.get("Date") or None})
    for r in read_member(z, "Emerging Tasks.txt") or []:
        out["emerging"].append({"release": version, "code": r["O*NET-SOC Code"], "task": r["Task"],
                                "category": r.get("Category"), "original_task_id": r.get("Original Task ID"),
                                "date": r.get("Date") or None, "source": r.get("Domain Source") or None})
    return out


def read_crosswalks() -> list[dict]:
    rows = []
    for a, b in (("2000", "2006"), ("2006", "2009"), ("2009", "2010"), ("2010", "2019")):
        p = RAW / "crosswalks" / f"{a}_to_{b}_Crosswalk.csv"
        with p.open(encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                fc, tc = r[f"O*NET-SOC {a} Code"].strip(), r[f"O*NET-SOC {b} Code"].strip()
                if fc and tc:
                    rows.append({"from_tax": a, "to_tax": b, "from_code": fc, "to_code": tc})
    return rows


def detect_taxonomy(codes: set[str], xw: list[dict]) -> dict[str, float]:
    """Share of a release's codes found in each taxonomy's code list."""
    sets = {}
    for r in xw:
        sets.setdefault(r["from_tax"], set()).add(r["from_code"])
        sets.setdefault(r["to_tax"], set()).add(r["to_code"])
    return {t: round(len(codes & s) / len(codes), 4) for t, s in sorted(sets.items())}


def main() -> int:
    DERIVED.mkdir(parents=True, exist_ok=True)
    xw = read_crosswalks()
    tables = {k: [] for k in ("occupations", "tasks", "ratings", "tech", "job_zones", "emerging")}
    inventory = []
    for version, month, tax in RELEASES:
        path = RAW / "releases" / f"db_{version.replace('.', '_')}.zip"
        part = parse_release(version, path)
        codes = {r["code"] for r in part["occupations"]}
        overlap = detect_taxonomy(codes, xw)
        best = max(overlap, key=lambda t: (overlap[t], t))
        if overlap[tax] < 0.95:
            print(f"WARNING {version}: declared taxonomy {tax} overlap {overlap[tax]} (best {best})", file=sys.stderr)
        inventory.append({"release": version, "release_month": month, "taxonomy": tax,
                          "taxonomy_code_overlap": overlap, "sha256": sha256_file(path),
                          **{f"n_{k}": len(v) for k, v in part.items()},
                          "n_occupations_with_tasks": len({r["code"] for r in part["tasks"]}),
                          "n_occupations_with_tech": len({r["code"] for r in part["tech"]}),
                          "hot_flag_present": any(r["hot"] is not None for r in part["tech"])})
        for k, v in part.items():
            tables[k].extend(v)
        print(f"{version}: {len(part['tasks'])} tasks, {len(part['ratings'])} ratings, {len(part['tech'])} tech")
    tables["crosswalk"] = xw
    for k, rows in tables.items():
        pq.write_table(pa.Table.from_pylist(rows), DERIVED / f"{k}.parquet", compression="zstd")
    dump_json({"releases": inventory}, ART / "release_inventory.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
