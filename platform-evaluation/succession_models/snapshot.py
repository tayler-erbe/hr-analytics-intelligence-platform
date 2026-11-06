"""Bitemporal as-of snapshot builder (DuckDB) -- the leakage firewall of the pipeline.

FEATURES at snapshot date S use only row versions that were
    effective on or before S        (eff_dt <= S)                 -- valid time
AND recorded on or before S         (rec_start <= S < rec_end)    -- transaction time
so a termination keyed in March for a January exit, a back-dated hire, or a later correction is
invisible to a January snapshot, exactly as it was to HR at the time.

LABELS (spell exits) are computed separately by `spells(known_at=...)` and joined only on keys:
for a backtest with origin C, training labels use `known_at=C`; evaluation outcomes use the
latest data. Nothing in `incumbents_asof` reads a row that fails the predicates above (unit-tested
by truncating / scrambling all post-S rows in tests/test_succession.py).

In "effective_only" mode (no transaction time in the extract) rec_start := effective date and
rec_end := open; closures after S are still invisible because status is evaluated at S, but
retro-keyed rows cannot be detected (residual risk documented in data_contract.md).
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from config import OPEN_END, SOURCE_MAP, SURS_TIER2_START

OPEN = f"DATE '{OPEN_END.isoformat()}'"


def _lit(d: dt.date) -> str:
    return f"DATE '{d.isoformat()}'"


def open_source(extract_dir: Path, source_map: dict = SOURCE_MAP) -> duckdb.DuckDBPyConnection:
    """Register logical views v_<name> over the extract Parquet, renaming physical -> logical columns."""
    con = duckdb.connect()
    extract_dir = Path(extract_dir)
    bitemporal = source_map["bitemporal"]
    rc = source_map["rec_cols"]
    for logical, spec in source_map["tables"].items():
        f = extract_dir / f"{spec['file']}.parquet"
        if not f.exists():
            if spec.get("optional"):
                continue
            raise FileNotFoundError(f)
        cols = [f"{phys} AS {log}" for log, phys in spec["cols"].items()]
        if logical not in ("ref_class", "ref_org", "ref_role", "protected"):
            if "exp_dt" in spec["cols"]:
                cols = [c for c in cols if not c.endswith(" AS exp_dt")]
                cols.append(f"COALESCE({spec['cols']['exp_dt']}, {OPEN}) AS exp_dt")
            eff = spec["cols"].get("eff_dt") or spec["cols"].get("term_dt")
            if bitemporal:
                cols.append(f"{rc['rec_start']} AS rec_start")
                cols.append(f"COALESCE({rc['rec_end']}, {OPEN}) AS rec_end")
            else:
                cols.append(f"{eff} AS rec_start")
                cols.append(f"{OPEN} AS rec_end")
        con.execute(f"CREATE VIEW v_{logical} AS SELECT {', '.join(cols)} FROM read_parquet('{f.as_posix()}')")
    # org -> reporting unit (ancestor at depth unit_level)
    orgs = con.sql("SELECT org_cd, parent_org_cd, org_title FROM v_ref_org").fetchall()
    parent = {o: p for o, p, _ in orgs}
    title = {o: t for o, _, t in orgs}

    def chain(o):
        out = []
        while o is not None and o not in out:
            out.append(o)
            o = parent.get(o)
        return out[::-1]
    lvl = source_map.get("unit_level", 2)
    rows = []
    for o in parent:
        c = chain(o)
        u = c[min(lvl, len(c) - 1)]
        rows.append((o, u, title.get(u) or u))
    con.execute("CREATE TABLE org_unit (org_cd VARCHAR, unit_cd VARCHAR, unit_title VARCHAR)")
    if rows:
        con.executemany("INSERT INTO org_unit VALUES (?, ?, ?)", rows)
    con.execute("""CREATE VIEW v_role AS SELECT r.class_cd, r.role_family, CAST(r.role_level AS INTEGER) role_level,
                   r.critical_ind, MAX(CAST(r.role_level AS INTEGER)) OVER (PARTITION BY r.role_family) family_top
                   FROM v_ref_role r""")
    return con


def _snaps(con, dates) -> None:
    con.execute("CREATE OR REPLACE TEMP TABLE snaps (snap_dt DATE)")
    con.executemany("INSERT INTO snaps VALUES (?)", [(d,) for d in sorted(set(dates))])


KNOWN = "{a}.eff_dt <= s.snap_dt AND {a}.rec_start <= s.snap_dt AND s.snap_dt < {a}.rec_end"


def incumbents_asof(con, dates) -> pd.DataFrame:
    """One row per (snapshot, incumbent of a primary position) with RAW as-of features."""
    _snaps(con, dates)
    k = KNOWN.format(a="j")
    sql = f"""
    WITH jk AS (
        SELECT s.snap_dt, j.* FROM snaps s JOIN v_job j ON {k} WHERE j.contract_type = 'P'),
    cur AS (
        SELECT * FROM jk WHERE status_cd = 'A' AND exp_dt >= snap_dt
        QUALIFY ROW_NUMBER() OVER (PARTITION BY snap_dt, pers_id ORDER BY fte DESC, eff_dt DESC, posn_nbr) = 1),
    role AS (
        SELECT snap_dt, pers_id, posn_nbr, MIN(eff_dt) role_start FROM jk WHERE status_cd = 'A' GROUP BY ALL),
    prior AS (
        SELECT c.snap_dt, c.pers_id, MAX(CASE WHEN j.posn_nbr <> c.posn_nbr THEN 1 ELSE 0 END) prior_role
        FROM cur c JOIN jk j ON j.snap_dt = c.snap_dt AND j.pers_id = c.pers_id AND j.status_cd = 'A'
        GROUP BY ALL),
    emp AS (
        SELECT s.snap_dt, e.pers_id, e.first_hire_dt, e.cur_hire_dt FROM snaps s JOIN v_employee e ON {KNOWN.format(a="e")}
        QUALIFY ROW_NUMBER() OVER (PARTITION BY s.snap_dt, e.pers_id ORDER BY e.eff_dt DESC, e.rec_start DESC) = 1),
    per AS (
        SELECT s.snap_dt, p.pers_id, p.birth_dt FROM snaps s JOIN v_person p ON {KNOWN.format(a="p")}
        QUALIFY ROW_NUMBER() OVER (PARTITION BY s.snap_dt, p.pers_id ORDER BY p.eff_dt DESC, p.rec_start DESC) = 1),
    exits AS (   -- position exits known at S in the trailing 12 months, by unit
        SELECT j.snap_dt, u.unit_cd, COUNT(*) n_exit FROM jk j JOIN org_unit u ON u.org_cd = j.org_cd
        WHERE j.status_cd = 'T' AND j.eff_dt > j.snap_dt - INTERVAL 365 DAY GROUP BY ALL),
    hc AS (
        SELECT c.snap_dt, u.unit_cd, COUNT(*) n_hc FROM cur c JOIN org_unit u ON u.org_cd = c.org_cd GROUP BY ALL)
    SELECT c.snap_dt, c.pers_id, c.posn_nbr, c.class_cd, r.role_family, r.role_level, r.critical_ind,
           CASE WHEN r.role_level = r.family_top THEN 1 ELSE 0 END AS top_level,
           c.org_cd, u.unit_cd, u.unit_title, CAST(c.fte AS DOUBLE) fte,
           CAST(c.annual_sal AS DOUBLE) annual_sal, CAST(rc.min_amt AS DOUBLE) min_amt, CAST(rc.max_amt AS DOUBLE) max_amt,
           p.birth_dt, COALESCE(e.first_hire_dt, ro.role_start) first_hire_dt, COALESCE(e.cur_hire_dt, ro.role_start) cur_hire_dt,
           ro.role_start, COALESCE(pr.prior_role, 0) prior_role,
           COALESCE(x.n_exit, 0) * 1.0 / h.n_hc AS unit_churn
    FROM cur c
    LEFT JOIN v_role r ON r.class_cd = c.class_cd
    LEFT JOIN v_ref_class rc ON rc.class_cd = c.class_cd
    LEFT JOIN org_unit u ON u.org_cd = c.org_cd
    LEFT JOIN role ro ON ro.snap_dt = c.snap_dt AND ro.pers_id = c.pers_id AND ro.posn_nbr = c.posn_nbr
    LEFT JOIN prior pr ON pr.snap_dt = c.snap_dt AND pr.pers_id = c.pers_id
    LEFT JOIN emp e ON e.snap_dt = c.snap_dt AND e.pers_id = c.pers_id
    LEFT JOIN per p ON p.snap_dt = c.snap_dt AND p.pers_id = c.pers_id
    LEFT JOIN exits x ON x.snap_dt = c.snap_dt AND x.unit_cd = u.unit_cd
    LEFT JOIN hc h ON h.snap_dt = c.snap_dt AND h.unit_cd = u.unit_cd
    ORDER BY c.snap_dt, c.posn_nbr, c.pers_id
    """
    df = con.sql(sql).df()
    return _derive(df)


def _derive(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    snap = pd.to_datetime(df["snap_dt"])
    yrs = lambda c: (snap - pd.to_datetime(df[c])).dt.days / 365.25  # noqa: E731
    df["age_years"] = yrs("birth_dt")
    df["service_years"] = yrs("first_hire_dt")
    df["tenure_years"] = yrs("cur_hire_dt")
    df["role_years"] = yrs("role_start")
    df["days_since_role_change"] = (snap - pd.to_datetime(df["role_start"])).dt.days
    df["prior_role"] = df["prior_role"].astype(bool)
    df["surs_tier"] = np.where(pd.to_datetime(df["first_hire_dt"]) < pd.Timestamp(SURS_TIER2_START), 1, 2)
    rng = (df["max_amt"] - df["min_amt"]).where(lambda s: s > 0)
    rate = df["annual_sal"] / df["fte"].where(df["fte"] > 0)
    df["pay_pos"] = ((rate - df["min_amt"]) / rng).clip(0, 1).fillna(0.5)
    df["role_family"] = df["role_family"].fillna("Unmapped")
    df["role_level"] = df["role_level"].fillna(1).astype(int)
    df["critical_ind"] = df["critical_ind"].fillna("N")
    df["unit_churn"] = df["unit_churn"].fillna(0.0)
    df["age_years"] = df["age_years"].fillna(df["age_years"].median())
    return df


def spells(con, known_at: dt.date | None = None) -> pd.DataFrame:
    """Primary-position spells with exit date, cause (SEP / MOVE) and destination class.

    known_at=None -> latest row versions (final truth, used for evaluation outcomes and mobility on the
    full history). known_at=C -> as known at C (used for training labels and mobility in backtests);
    exits after C, or recorded after C, are censored at C.
    """
    if known_at is None:
        filt_j = f"j.rec_end = {OPEN}"
        filt_t = f"t.rec_end = {OPEN}"
        cens = None
    else:
        c = _lit(known_at)
        filt_j = f"j.eff_dt <= {c} AND j.rec_start <= {c} AND {c} < j.rec_end"
        filt_t = f"t.term_dt <= {c} AND t.rec_start <= {c} AND {c} < t.rec_end"
        cens = c
    sql = f"""
    WITH j AS (SELECT * FROM v_job j WHERE j.contract_type = 'P' AND {filt_j}),
    a AS (SELECT pers_id, posn_nbr, MIN(eff_dt) start_dt, MAX(exp_dt) max_exp,
                 ARG_MAX(class_cd, eff_dt) class_cd, ARG_MAX(org_cd, eff_dt) org_cd
          FROM j WHERE status_cd = 'A' GROUP BY ALL),
    t AS (SELECT pers_id, posn_nbr, MIN(eff_dt) t_dt FROM j WHERE status_cd = 'T' GROUP BY ALL),
    sp AS (
      SELECT a.*, COALESCE(t.t_dt, CASE WHEN a.max_exp < {OPEN} THEN CAST(a.max_exp + INTERVAL 1 DAY AS DATE) END) exit_dt
      FROM a LEFT JOIN t USING (pers_id, posn_nbr)),
    sp2 AS (SELECT * REPLACE (CASE WHEN {cens or 'NULL'} IS NOT NULL AND exit_dt > {cens or OPEN} THEN NULL ELSE exit_dt END AS exit_dt) FROM sp),
    term AS (SELECT DISTINCT pers_id, term_dt FROM v_term t WHERE {filt_t})
    SELECT s.pers_id, s.posn_nbr, s.class_cd, s.org_cd, u.unit_cd, s.start_dt, s.exit_dt,
           CASE WHEN s.exit_dt IS NULL THEN NULL
                WHEN tm.term_dt IS NOT NULL THEN 'SEP'
                WHEN nx.class_cd IS NOT NULL THEN 'MOVE' ELSE 'SEP' END AS cause,
           nx.class_cd AS dest_class_cd, nx.org_cd AS dest_org_cd
    FROM sp2 s
    LEFT JOIN org_unit u ON u.org_cd = s.org_cd
    LEFT JOIN term tm ON tm.pers_id = s.pers_id AND tm.term_dt = s.exit_dt
    LEFT JOIN sp2 nx ON nx.pers_id = s.pers_id AND nx.start_dt = s.exit_dt AND nx.posn_nbr <> s.posn_nbr
    QUALIFY ROW_NUMBER() OVER (PARTITION BY s.pers_id, s.posn_nbr ORDER BY nx.class_cd NULLS LAST) = 1
    ORDER BY s.pers_id, s.start_dt, s.posn_nbr
    """
    return con.sql(sql).df()


def vacant_asof(con, d: dt.date) -> pd.DataFrame:
    """Active positions with no known incumbent at d (needs the position-control table)."""
    _snaps(con, [d])
    sql = f"""
    WITH pk AS (SELECT s.snap_dt, p.* FROM snaps s JOIN v_position p ON {KNOWN.format(a="p")}
                WHERE p.exp_dt >= s.snap_dt AND p.status_cd = 'A'),
    jk AS (SELECT s.snap_dt, j.* FROM snaps s JOIN v_job j ON {KNOWN.format(a="j")}
           WHERE j.contract_type = 'P' AND j.status_cd = 'A' AND j.exp_dt >= s.snap_dt)
    SELECT pk.posn_nbr, pk.class_cd, r.role_family, r.role_level, r.critical_ind, u.unit_cd
    FROM pk LEFT JOIN v_role r ON r.class_cd = pk.class_cd LEFT JOIN org_unit u ON u.org_cd = pk.org_cd
    WHERE NOT EXISTS (SELECT 1 FROM jk WHERE jk.posn_nbr = pk.posn_nbr)
    """
    return con.sql(sql).df()


def protected_attrs(con) -> pd.DataFrame | None:
    """RESTRICTED: only the fairness audit may call this."""
    try:
        return con.sql("SELECT pers_id, sex_cd, race_eth_cd FROM v_protected").df()
    except duckdb.CatalogException:
        return None


def semiannual(start: dt.date, end: dt.date) -> list[dt.date]:
    out = []
    for y in range(start.year, end.year + 1):
        for m in (1, 7):
            d = dt.date(y, m, 1)
            if start <= d <= end:
                out.append(d)
    return out
