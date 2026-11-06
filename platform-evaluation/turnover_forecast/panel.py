"""Build the state x quarter x age-group panel from the QWI n4 files.

Rows: 14 states x {6113 colleges & universities, 6111 K-12, 6221 hospitals, 00 all industries}
x age groups A00..A08 x quarter, sex = 0 (all), ownership A00 (all ownerships).
Measures: Emp, EmpEnd, HirA, HirN, Sep, SepBeg, TurnOvrS, EarnS with their status flags.

A measure is *usable* when its flag is in USABLE_FLAGS (1 OK, 6/10 derived without distortion,
9/12 distorted-but-released). Flags -2, -1, 5 and 11 mean missing or suppressed; those values are
NULL in the published file and stay NULL here (never coalesced to zero).

Output: turnover_forecast/data/panel.parquet and panel_manifest.json (row counts, SHA-256).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
IL_SILVER = ROOT / "data" / "lake" / "silver" / "qwi_il_sa_gs_n4_oslp.parquet"
INDUSTRIES = ("6113", "6111", "6221", "00")
USABLE_FLAGS = (1, 6, 9, 10, 12)
MEASURES = {  # panel name: (CSV column, silver column)
    "emp": ("Emp", "emp"), "emp_end": ("EmpEnd", "emp_end"), "hir_a": ("HirA", "hir_a"),
    "hir_n": ("HirN", "hir_n"), "sep": ("Sep", "sep"), "sep_beg": ("SepBeg", "sep_beg"),
    "turn_ovr_s": ("TurnOvrS", "turn_ovr_s"), "earn_s": ("EarnS", "earn_s"),
}


def _csv_flag(c: str) -> str:
    return "s" + c


def build(con: duckdb.DuckDBPyConnection | None = None) -> Path:
    con = con or duckdb.connect()
    man = json.loads((DATA / "acquisition_manifest.json").read_text())
    ind = ", ".join(f"'{i}'" for i in INDUSTRIES)
    parts = []
    for rec in man["files"]:
        st = rec["state"]
        if st == "IL":
            cols = ", ".join(f"CAST({s} AS DOUBLE) AS {k}, CAST(s_{s} AS INTEGER) AS s_{k}"
                             for k, (_, s) in MEASURES.items())
            parts.append(f"""SELECT 'IL' AS state, geography, industry, agegrp, CAST(year AS INTEGER) AS "year",
                CAST(quarter AS INTEGER) AS "quarter", {cols}, '{rec['sha256']}' AS source_sha256
                FROM read_parquet('{IL_SILVER.as_posix()}')
                WHERE industry IN ({ind}) AND sex = '0' AND ownercode = 'A00'""")
        else:
            path = (ROOT / rec["path"]).as_posix()
            cols = ", ".join(f"CAST({c} AS DOUBLE) AS {k}, CAST({_csv_flag(c)} AS INTEGER) AS s_{k}"
                             for k, (c, _) in MEASURES.items())
            parts.append(f"""SELECT '{st}' AS state, geography, industry, agegrp, CAST(year AS INTEGER) AS "year",
                CAST(quarter AS INTEGER) AS "quarter", {cols}, '{rec['sha256']}' AS source_sha256
                FROM read_csv('{path}', all_varchar=true, header=true)
                WHERE industry IN ({ind}) AND sex = '0' AND ownercode = 'A00'""")
    sql = " UNION ALL ".join(parts)
    DATA.mkdir(parents=True, exist_ok=True)
    out = DATA / "panel.parquet"
    con.execute(f"COPY ({sql} ORDER BY state, industry, agegrp, year, quarter) TO '{out.as_posix()}' (FORMAT parquet)")
    rows = con.execute(f"""SELECT state, count(*), min(year*10+quarter), max(year*10+quarter),
        max(CASE WHEN industry='6113' AND agegrp='A00' AND s_sep IN {USABLE_FLAGS} THEN year*10+quarter END)
        FROM read_parquet('{out.as_posix()}') GROUP BY 1 ORDER BY 1""").fetchall()
    dup = con.execute(f"""SELECT count(*) FROM (SELECT state, industry, agegrp, year, quarter, count(*) n
        FROM read_parquet('{out.as_posix()}') GROUP BY ALL HAVING n > 1)""").fetchall()[0][0]
    assert dup == 0, "duplicate panel keys"
    sha = hashlib.sha256(out.read_bytes()).hexdigest()
    pm = {"panel": out.relative_to(ROOT).as_posix(), "sha256": sha, "usable_flags": list(USABLE_FLAGS),
          "industries": list(INDUSTRIES), "by_state": [
              {"state": s, "rows": n, "first_yq": a, "last_yq": b, "last_6113_sep_yq": c} for s, n, a, b, c in rows]}
    (DATA / "panel_manifest.json").write_text(json.dumps(pm, indent=1))
    for r in pm["by_state"]:
        print(r)
    print("panel sha256", sha)
    return out


if __name__ == "__main__":
    build()
