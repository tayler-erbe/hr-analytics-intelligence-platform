"""Build the national institution x year IPEDS panel (Fall 2015-2023) for the predictive models.

    python ipeds_models/acquire_finance.py   # finance files (research-expenditure proxy)
    python ipeds_models/build_panel.py       # -> ipeds_models/artifacts/panel.parquet, comparability_flags.parquet

Inputs (read-only):
  * data/lake/raw/ipeds_history/  HR, salary, enrollment, directory, FLAGS zips and the BLS CPI-U page,
    downloaded and hashed by peer_benchmarks/acquire.py. Parsed with peer_benchmarks/build.py's readers
    (imported, not modified), so revised "_rv" members, string codes and NULL handling are identical.
  * peer_benchmarks/artifacts/comparability_flags.parquet (if present): its 'exclude' flags are unioned in.
  * ipeds_models/data/raw_finance/  F{yy}{yy+1}_F1A / _F2 (research expenses).

Universe: every institution-year whose HD record that year is a degree-granting (DEGGRANT=1) 4-year
(ICLEVEL=1) public, private not-for-profit or for-profit institution (SECTOR 1-3) and that has a
published IPEDS staff grand total > 0 (S_OC staffcat 1100).

Partition rules follow lake/CONTRACT.md v1.1 and peer_benchmarks/METHODS.md:
  * 14 occupation groups (3-digit OCCUPCAT, 260+270 combined as 250) x FT/PT partition the grand total;
  * tenure status rows (S_IS arank 0, facstat 20/30/40/50) partition FT instructional staff;
  * new-hire groups (S_NH snhcat 21000..39000) partition all FT new hires; absent group rows = 0
    when the institution filed new hires that year;
  * salary tables exclude the all-groups / all-ranks rows when summing (we use them only as totals).
"""
from __future__ import annotations

import json
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import duckdb

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "peer_benchmarks"))
import build as pb  # noqa: E402  (peer_benchmarks/build.py: readers, GROUPS, CPI parser)

ART = HERE / "artifacts"
MAN = HERE / "manifests"
FIN_RAW = HERE / "data" / "raw_finance"
PB_FLAGS = ROOT / "peer_benchmarks" / "artifacts" / "comparability_flags.parquet"
YEARS = list(range(2015, 2024))
GROUPS = pb.GROUPS
UOFI = {"145637": "UIUC", "145600": "UIC", "148654": "UIS"}
BIG_TEN = [u for u, (_, r) in pb.PANEL.items() if r == "big_ten_peer"]

# Thresholds (documented in README)
SHIFT_CAUTION = 0.15      # yoy change in published total staff / FTE that gets a caution flag (as peer_benchmarks)
SHIFT_EXCLUDE = 0.35      # yoy change treated as a reporting-scope break -> excluded for that domain
MIN_FT_INSTR = 20         # tenure share defined only with >= 20 FT instructional staff
MIN_GROUP_FT = 20         # occupation new-hire rate defined only with >= 20 FT staff in the group
MIN_RANK_N = 10           # faculty rank pay defined only with >= 10 faculty in the rank
MIN_FTE = 200             # staff per 100 FTE defined only with >= 200 student FTE
PAY_MIN, PAY_MAX = 25_000, 450_000  # plausible 9-month average faculty pay, 2023-24 $


@contextmanager
def raw_dir(path: Path):
    old = pb.RAW
    pb.RAW = path
    try:
        yield
    finally:
        pb.RAW = old


def load(con, name: str, table: str, cols: list[str], year: int, sources: list, raw: Path | None = None):
    import pyarrow as pa
    with raw_dir(raw or pb.RAW):
        t, member = pb.read_ipeds(name)
    sources.append({"file": name, "member": member, "fall_year": year})
    present = [c for c in cols if c in t.column_names]
    sel = t.select(present)
    for c in cols:
        if c not in present:
            sel = sel.append_column(c, pa.nulls(len(sel), pa.string() if pb.is_text_col(c) else pa.float64()))
    sel = sel.select(cols).append_column("year", pa.array([year] * len(sel), pa.int32()))
    con.register("_tmp", sel)
    exists = con.execute(f"SELECT count(*) FROM information_schema.tables WHERE table_name = '{table}'").fetchall()[0][0]
    if exists:
        con.execute(f"INSERT INTO {table} BY NAME SELECT * FROM _tmp")
    else:
        con.execute(f"CREATE TABLE {table} AS SELECT * FROM _tmp")
    con.unregister("_tmp")


def main() -> int:
    ART.mkdir(parents=True, exist_ok=True)
    MAN.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    sources: list = []
    print("loading raw IPEDS files (national) ...")
    for y in YEARS:
        load(con, f"HD{y}", "hd", ["unitid", "instnm", "stabbr", "sector", "iclevel", "deggrant", "control",
                                   "c15basic", "c18basic", "c21basic", "instsize", "hospital", "medical", "landgrnt",
                                   "obereg", "hbcu", "locale"], y, sources)
        load(con, f"FLAGS{y}", "flags", ["unitid", "stat_hr", "prch_hr", "imp_hr", "stat_sa", "prch_f", "stat_f",
                                         "prch_ef", "prch_e12"], y, sources)
        load(con, f"S{y}_OC", "s_oc", ["unitid", "staffcat", "hrtotlt", "xhrtotlt"], y, sources)
        load(con, f"S{y}_IS", "s_is", ["unitid", "facstat", "arank", "hrtotlt", "xhrtotlt"], y, sources)
        load(con, f"S{y}_NH", "s_nh", ["unitid", "snhcat", "hrtotlt", "xhrtotlt"], y, sources)
        load(con, f"SAL{y}_IS", "sal_is", ["unitid", "arank", "satotlt", "saeq9at", "saavmnt", "xsaeq9at",
                                           "xsaavmnt"], y, sources)
        load(con, f"SAL{y}_NIS", "sal_nis", ["unitid", "sanin01", "sanit01", "xsanin01", "xsanit01"], y, sources)
        load(con, f"EF{y}A", "ef_a", ["unitid", "efalevel", "eftotlt", "xeftotlt"], y, sources)
        load(con, f"EFIA{y + 1}", "efia", ["unitid", "fteug", "ftegd", "ftedpp", "xfteug"], y, sources)
        fy = f"F{(y - 1) % 100:02d}{y % 100:02d}"
        load(con, f"{fy}_F1A", "f1a", ["unitid", "f1c021", "f1c191", "xf1c021"], y, sources, FIN_RAW)
        load(con, f"{fy}_F2", "f2", ["unitid", "f2e021", "f2e131", "xf2e021"], y, sources, FIN_RAW)

    # CPI-U academic-year deflator to 2023-24 dollars (same method as peer_benchmarks)
    cpi = pb.cpi_monthly()
    if not cpi:
        raise SystemExit("CPI-U page missing: run peer_benchmarks/acquire.py first")
    con.execute("CREATE TABLE cpi_month(year INTEGER, month INTEGER, cpi DOUBLE)")
    con.executemany("INSERT INTO cpi_month VALUES (?, ?, ?)", cpi)
    con.execute("CREATE TABLE years AS SELECT unnest(range(2015, 2024))::INTEGER AS year")
    con.execute("""CREATE TABLE cpi AS
        SELECT y.year, avg(c.cpi) AS cpi_ay, count(*) AS months FROM years y JOIN cpi_month c
          ON (c.year = y.year AND c.month >= 7) OR (c.year = y.year + 1 AND c.month <= 6)
        GROUP BY y.year HAVING count(*) = 12""")
    con.execute("CREATE OR REPLACE TABLE cpi AS SELECT year, cpi_ay, (SELECT cpi_ay FROM cpi WHERE year = 2023) / cpi_ay AS defl FROM cpi")
    assert con.execute("SELECT count(*) FROM cpi").fetchall()[0][0] == len(YEARS)

    con.execute("CREATE TABLE groups(group_code VARCHAR, label VARCHAR, snhcat VARCHAR, nis VARCHAR)")
    con.executemany("INSERT INTO groups VALUES (?, ?, ?, ?)", GROUPS)

    # ---------------------------------------------------------------- universe
    con.execute("""
      CREATE TABLE universe AS
      SELECT h.unitid, h.year FROM hd h
      JOIN (SELECT unitid, year, hrtotlt FROM s_oc WHERE staffcat = '1100') t USING (unitid, year)
      WHERE h.iclevel = 1 AND h.deggrant = 1 AND h.sector IN (1, 2, 3) AND t.hrtotlt > 0
    """)
    # Carnegie basic classification as published in that year's HD: the 2018 classification where the file
    # carries it (HD2018+), else the 2015 classification (same code list). No look-ahead to later HD files.
    con.execute("""
      CREATE TABLE carnegie AS
      SELECT unitid, year, coalesce(nullif(c18basic, -2), nullif(c15basic, -2)) AS carnegie_basic
      FROM hd WHERE (unitid, year) IN (SELECT unitid, year FROM universe)
    """)

    # ---------------------------------------------------------------- staff by occupation (partition)
    oc_cols = ",\n".join(
        f"sum(hrtotlt) FILTER (WHERE staffcat IN ('2{g}', '3{g}')) AS staff_{g},"
        f" sum(hrtotlt) FILTER (WHERE staffcat = '2{g}') AS staff_ft_{g}" for g, *_ in GROUPS)
    group_list = ",".join(f"'{g}'" for g, *_ in GROUPS)
    con.execute(f"""
      CREATE TABLE oc AS
      SELECT unitid, year,
             sum(hrtotlt) FILTER (WHERE left(staffcat, 1) IN ('2', '3') AND substr(staffcat, 2) IN ({group_list})) AS staff_total,
             sum(hrtotlt) FILTER (WHERE left(staffcat, 1) = '2' AND substr(staffcat, 2) IN ({group_list})) AS staff_ft,
             max(hrtotlt) FILTER (WHERE staffcat = '1100') AS published_grand_total,
             max(hrtotlt) FILTER (WHERE staffcat = '2100') AS published_ft_total,
             max(hrtotlt) FILTER (WHERE staffcat = '4400') AS graduate_assistants,
             count(*) FILTER (WHERE left(staffcat, 1) IN ('2', '3') AND xhrtotlt IN ('J','K','L','N','P')) AS n_imputed_cells,
             {oc_cols}
      FROM s_oc WHERE (unitid, year) IN (SELECT unitid, year FROM universe) GROUP BY unitid, year
    """)
    # ---------------------------------------------------------------- tenure
    con.execute("""
      CREATE TABLE ten AS
      SELECT unitid, year,
             max(hrtotlt) FILTER (WHERE facstat = '0') AS ft_instr_published,
             sum(hrtotlt) FILTER (WHERE facstat IN ('20','30','40','50')) AS ft_instr,
             sum(hrtotlt) FILTER (WHERE facstat = '20') AS tenured,
             sum(hrtotlt) FILTER (WHERE facstat = '30') AS tenure_track,
             sum(hrtotlt) FILTER (WHERE facstat = '40') AS non_tenure_track,
             sum(hrtotlt) FILTER (WHERE facstat = '50') AS no_faculty_status,
             count(*) FILTER (WHERE facstat IN ('20','30','40','50') AND xhrtotlt IN ('J','K','L','N','P')) AS n_imputed_cells
      FROM s_is WHERE arank = '0' AND (unitid, year) IN (SELECT unitid, year FROM universe) GROUP BY unitid, year
    """)
    # ---------------------------------------------------------------- new hires
    nh_cols = ",\n".join(f"coalesce(sum(hrtotlt) FILTER (WHERE snhcat = '{s}'), 0) AS nh_{g}" for g, _, s, _ in GROUPS)
    con.execute(f"""
      CREATE TABLE nh AS
      SELECT unitid, year, max(hrtotlt) FILTER (WHERE snhcat = '10000') AS nh_total_published,
             {nh_cols},
             count(*) FILTER (WHERE xhrtotlt IN ('J','K','L','N','P')) AS n_imputed_cells
      FROM s_nh WHERE (unitid, year) IN (SELECT unitid, year FROM universe)
      GROUP BY unitid, year HAVING max(hrtotlt) FILTER (WHERE snhcat = '10000') IS NOT NULL
    """)
    # ---------------------------------------------------------------- faculty pay by rank (real 2023-24 $)
    rank_cols = ",\n".join(
        f"max(n) FILTER (WHERE arank = '{r}') AS fac_n_{r}, "
        f"max(CASE WHEN n >= {MIN_RANK_N} THEN pay * c.defl END) FILTER (WHERE arank = '{r}') AS fac_pay_real_{r}"
        for r in ("7", "1", "2", "3"))
    con.execute(f"""
      CREATE TABLE pay AS
      WITH x AS (SELECT unitid, year, arank, satotlt AS n,
                        CASE WHEN year = 2015 THEN saavmnt * 9 ELSE saeq9at END AS pay,
                        CASE WHEN year = 2015 THEN xsaavmnt ELSE xsaeq9at END AS flag
                 FROM sal_is WHERE (unitid, year) IN (SELECT unitid, year FROM universe))
      SELECT x.unitid, x.year, {rank_cols},
             count(*) FILTER (WHERE flag IN ('J','K','L','N','P')) AS n_imputed_cells
      FROM x JOIN cpi c USING (year) GROUP BY x.unitid, x.year
    """)
    con.execute("""
      CREATE TABLE nis AS
      SELECT s.unitid, s.year, s.sanin01 AS nis_ft_n,
             CASE WHEN s.sanin01 >= 10 THEN s.sanit01 / s.sanin01 * c.defl END AS nis_pay_real,
             (coalesce(s.xsanit01, '') IN ('J','K','L','N','P')) AS nis_imputed
      FROM sal_nis s JOIN cpi c USING (year) WHERE (s.unitid, s.year) IN (SELECT unitid, year FROM universe)
    """)
    # ---------------------------------------------------------------- enrollment
    con.execute("""
      CREATE TABLE enr AS
      WITH ef AS (SELECT unitid, year,
                    max(eftotlt) FILTER (WHERE efalevel = '1') AS fall_headcount,
                    max(eftotlt) FILTER (WHERE efalevel = '21') AS fall_ft,
                    max(eftotlt) FILTER (WHERE efalevel = '42') AS fall_pt_ug,
                    max(eftotlt) FILTER (WHERE efalevel = '52') AS fall_pt_gr
                  FROM ef_a GROUP BY 1, 2)
      SELECT u.unitid, u.year, ef.fall_headcount,
             ef.fall_ft + 0.403543 * coalesce(ef.fall_pt_ug, 0) + 0.361702 * coalesce(ef.fall_pt_gr, 0) AS fall_fte,
             CASE WHEN ia.fteug IS NOT NULL OR ia.ftegd IS NOT NULL
                  THEN coalesce(ia.fteug, 0) + coalesce(ia.ftegd, 0) + coalesce(ia.ftedpp, 0) END AS fte12,
             coalesce(ia.ftegd, 0) + coalesce(ia.ftedpp, 0) AS fte12_grad,
             (ia.xfteug IN ('J','K','L','N','P')) AS fte_imputed
      FROM universe u LEFT JOIN ef USING (unitid, year) LEFT JOIN efia ia USING (unitid, year)
    """)
    # ---------------------------------------------------------------- finance (research-expense proxy)
    con.execute("""
      CREATE TABLE fin AS
      SELECT u.unitid, u.year, f.prch_f,
             CASE WHEN coalesce(f.prch_f, -2) IN (-2, 3, 5)
                  THEN coalesce(a.f1c021, b.f2e021) * c.defl END AS research_exp_real,
             CASE WHEN coalesce(f.prch_f, -2) IN (-2, 3, 5)
                  THEN coalesce(a.f1c191, b.f2e131) * c.defl END AS total_exp_real
      FROM universe u JOIN cpi c USING (year)
      LEFT JOIN flags f USING (unitid, year)
      LEFT JOIN f1a a USING (unitid, year) LEFT JOIN f2 b USING (unitid, year)
    """)

    # ---------------------------------------------------------------- wide panel
    sg = ", ".join(f"o.staff_{g}, o.staff_ft_{g}" for g, *_ in GROUPS)
    nhg = ", ".join(f"n.nh_{g}" for g, *_ in GROUPS)
    rate = ", ".join(
        f"CASE WHEN u.year >= 2016 AND o.staff_ft_{g} >= {MIN_GROUP_FT} AND n.unitid IS NOT NULL "
        f"THEN 100.0 * n.nh_{g} / o.staff_ft_{g} END AS nh_rate_{g}" for g, *_ in GROUPS)
    con.execute(f"""
      CREATE TABLE panel AS
      SELECT u.unitid, u.year, h.instnm AS name, h.stabbr AS state, h.sector::INTEGER AS sector,
             cg.carnegie_basic::INTEGER AS carnegie_basic,
             CASE WHEN cg.carnegie_basic = 15 THEN 'R1' WHEN cg.carnegie_basic = 16 THEN 'R2'
                  WHEN cg.carnegie_basic = 17 THEN 'D/PU' WHEN cg.carnegie_basic BETWEEN 18 AND 20 THEN 'Masters'
                  WHEN cg.carnegie_basic BETWEEN 21 AND 23 THEN 'Baccalaureate'
                  WHEN cg.carnegie_basic BETWEEN 24 AND 32 THEN 'Special focus' ELSE 'Other' END AS carnegie_group,
             h.instsize::INTEGER AS instsize, (h.hospital = 1)::INTEGER AS hospital, (h.medical = 1)::INTEGER AS medical,
             (h.landgrnt = 1)::INTEGER AS landgrant, (h.hbcu = 1)::INTEGER AS hbcu, h.obereg::INTEGER AS region,
             o.staff_total, o.staff_ft, o.published_grand_total, o.published_ft_total, o.graduate_assistants, {sg},
             t.ft_instr, t.ft_instr_published, t.tenured, t.tenure_track, t.non_tenure_track, t.no_faculty_status,
             CASE WHEN t.ft_instr >= {MIN_FT_INSTR} THEN 100.0 * t.tenured / t.ft_instr END AS tenured_share,
             CASE WHEN t.ft_instr >= {MIN_FT_INSTR} THEN 100.0 * t.tenure_track / t.ft_instr END AS tenure_track_share,
             (n.unitid IS NOT NULL) AS nh_filed, n.nh_total_published, {nhg},
             CASE WHEN u.year >= 2016 AND n.unitid IS NOT NULL AND o.staff_ft > 0
                  THEN 100.0 * n.nh_total_published / o.staff_ft END AS nh_rate_all, {rate},
             p.fac_n_7, p.fac_n_1, p.fac_n_2, p.fac_n_3,
             p.fac_pay_real_7, p.fac_pay_real_1, p.fac_pay_real_2, p.fac_pay_real_3,
             s.nis_ft_n, s.nis_pay_real,
             e.fte12, e.fall_fte, e.fall_headcount, e.fte12_grad,
             CASE WHEN e.fte12 > 0 THEN 100.0 * e.fte12_grad / e.fte12 END AS grad_fte_share,
             CASE WHEN e.fte12 >= {MIN_FTE} THEN 100.0 * o.staff_total / e.fte12 END AS staff_per_100_fte,
             f.research_exp_real, f.total_exp_real,
             CASE WHEN e.fte12 >= {MIN_FTE} THEN f.research_exp_real / e.fte12 END AS research_per_fte,
             fl.stat_hr, fl.prch_hr, fl.imp_hr, fl.prch_f,
             o.n_imputed_cells AS oc_imputed_cells, t.n_imputed_cells AS is_imputed_cells,
             n.n_imputed_cells AS nh_imputed_cells, p.n_imputed_cells AS sal_imputed_cells,
             s.nis_imputed, e.fte_imputed
      FROM universe u
      JOIN hd h USING (unitid, year) LEFT JOIN carnegie cg USING (unitid, year)
      LEFT JOIN oc o USING (unitid, year) LEFT JOIN ten t USING (unitid, year) LEFT JOIN nh n USING (unitid, year)
      LEFT JOIN pay p USING (unitid, year) LEFT JOIN nis s USING (unitid, year) LEFT JOIN enr e USING (unitid, year)
      LEFT JOIN fin f USING (unitid, year) LEFT JOIN flags fl USING (unitid, year)
    """)

    # ---------------------------------------------------------------- comparability flags (national, same codes)
    flags: list[tuple] = []

    def add(u, y, dom, code, sev, detail):
        flags.append((u, int(y), dom, code, sev, detail, "ipeds_models"))

    rows = con.execute("""SELECT unitid, year, prch_hr, stat_hr, imp_hr, oc_imputed_cells, is_imputed_cells,
                                 nh_imputed_cells, sal_imputed_cells, nis_imputed, fte_imputed,
                                 published_grand_total, staff_total, ft_instr, ft_instr_published,
                                 nh_filed, nh_total_published FROM panel""").fetchall()
    for (u, y, prch, stat, imp, oci, isi, nhi, sali, nisi, ftei, pgt, st, fti, ftip, nhf, nht) in rows:
        if prch in (1, 2):
            add(u, y, "all", "PARENT_INCLUDES_CHILD_CAMPUSES" if prch == 1 else "CHILD_REPORTED_WITH_PARENT", "exclude",
                f"FLAGS PRCH_HR = {prch}: reporting scope differs from a single-campus record.")
        if stat is not None and stat not in (1, -2):
            add(u, y, "all", "HR_RESPONSE_STATUS", "exclude", f"FLAGS STAT_HR = {stat} (not a full respondent).")
        if imp in (1, 2):
            add(u, y, "all", "HR_IMPUTED_BY_NCES", "exclude", f"FLAGS IMP_HR = {imp} (carry-forward / nearest neighbour).")
        if (oci or 0) > 0:
            add(u, y, "staff", "IMPUTED_VALUES", "exclude", f"{oci} imputed S_OC cell(s).")
        if (isi or 0) > 0:
            add(u, y, "tenure", "IMPUTED_VALUES", "exclude", f"{isi} imputed S_IS cell(s).")
        if (nhi or 0) > 0:
            add(u, y, "new_hires", "IMPUTED_VALUES", "exclude", f"{nhi} imputed S_NH cell(s).")
        if (sali or 0) > 0:
            add(u, y, "faculty_pay", "IMPUTED_VALUES", "exclude", f"{sali} imputed SAL_IS cell(s).")
        if ftei:
            add(u, y, "enrollment", "IMPUTED_VALUES", "exclude", "12-month FTE imputed.")
        if pgt is not None and st is not None and pgt != st:
            add(u, y, "staff", "PARTITION_MISMATCH", "exclude", f"Groups sum {st} vs published total {pgt}.")
        if fti is not None and ftip is not None and fti != ftip:
            add(u, y, "tenure", "PARTITION_MISMATCH", "exclude", f"Tenure statuses sum {fti} vs published {ftip}.")
        if y == 2015:
            add(u, y, "new_hires", "NEW_HIRE_WINDOW_2015", "exclude",
                "Fall 2015 new hires used a 4-month window; not comparable with 2016+ (12 months).")
            add(u, y, "faculty_pay", "EQ9_METHOD_2015", "caution", "2015 pay = 9 x average monthly salary.")
        if y == 2018:
            add(u, y, "staff", "SOC2018_CATEGORY_BASIS", "caution", "First year coded with the 2018 SOC.")
        if y in (2020, 2021):
            add(u, y, "all", "PANDEMIC_PERIOD", "info", "COVID-19 period.")
    # partition check for new hires
    nh_sum = " + ".join(f"nh_{g}" for g, *_ in GROUPS)
    for (u, y, s, p) in con.execute(f"SELECT unitid, year, {nh_sum}, nh_total_published FROM panel WHERE nh_filed "
                                    f"AND {nh_sum} <> nh_total_published").fetchall():
        add(u, y, "new_hires", "PARTITION_MISMATCH", "exclude", f"New-hire groups sum {s} vs published {p}.")
    # level shifts (yoy) -> caution >= 15 %, exclude >= 35 % (scope break)
    # compared with the previous year the institution is in the universe (gaps included)
    for col, dom, minprev in (("published_grand_total", "staff", 100), ("fte12", "enrollment", 200),
                              ("ft_instr", "tenure", 50), ("fac_pay_real_7", "faculty_pay", 25000)):
        for (u, y, prev, cur) in con.execute(f"""
            WITH t AS (SELECT unitid, year, {col} AS cur,
                              lag({col}) OVER (PARTITION BY unitid ORDER BY year) AS prev,
                              lag(year) OVER (PARTITION BY unitid ORDER BY year) AS py FROM panel)
            SELECT unitid, year, prev, cur FROM t WHERE prev >= {minprev}
              AND abs(cur::DOUBLE / prev - 1) >= {SHIFT_CAUTION}""").fetchall():
            pct = cur / prev - 1
            sev = "exclude" if abs(pct) >= SHIFT_EXCLUDE else "caution"
            add(u, y, dom, f"LEVEL_SHIFT_{col.upper()}", sev, f"{col} {prev:,.0f} -> {cur:,.0f} ({100 * pct:+.0f}%).")
    # implausible faculty pay (real 2023-24 $, 9-month equated) -> value nulled, institution-year flagged
    for r in ("7", "1", "2", "3"):
        for (u, y, v) in con.execute(f"SELECT unitid, year, fac_pay_real_{r} FROM panel WHERE fac_pay_real_{r} "
                                     f"NOT BETWEEN {PAY_MIN} AND {PAY_MAX}").fetchall():
            add(u, y, "faculty_pay", "IMPLAUSIBLE_PAY", "caution", f"Rank {r} average {v:,.0f} outside "
                f"[{PAY_MIN:,}, {PAY_MAX:,}] (2023-24 $); value set to NULL.")
        con.execute(f"UPDATE panel SET fac_pay_real_{r} = NULL WHERE fac_pay_real_{r} NOT BETWEEN {PAY_MIN} AND {PAY_MAX}")

    # union in peer_benchmarks 'exclude' flags (Big Ten / U of I panel)
    n_pb = 0
    if PB_FLAGS.exists():
        for (u, y, dom, code, sev, det) in con.execute(
                f"SELECT unitid, year, domain, flag_code, severity, detail FROM '{PB_FLAGS}' WHERE severity = 'exclude'").fetchall():
            flags.append((u, int(y), "all" if dom == "all" else dom, code, sev, det, "peer_benchmarks"))
            n_pb += 1

    con.execute("CREATE TABLE comparability_flags(unitid VARCHAR, year INTEGER, domain VARCHAR, flag_code VARCHAR, "
                "severity VARCHAR, detail VARCHAR, source VARCHAR)")
    con.executemany("INSERT INTO comparability_flags VALUES (?, ?, ?, ?, ?, ?, ?)", flags)
    # Per-domain exclusion columns on the panel
    for dom in ("staff", "tenure", "new_hires", "faculty_pay", "enrollment"):
        con.execute(f"""ALTER TABLE panel ADD COLUMN excl_{dom} BOOLEAN""")
        con.execute(f"""UPDATE panel SET excl_{dom} = (unitid, year) IN (
            SELECT unitid, year FROM comparability_flags WHERE severity = 'exclude' AND domain IN ('all', '{dom}'
            {", 'staff_occupation'" if dom == 'staff' else ''}{", 'faculty_tenure'" if dom == 'tenure' else ''}))""")
    con.execute("ALTER TABLE panel ADD COLUMN is_uofi BOOLEAN")
    con.execute(f"UPDATE panel SET is_uofi = unitid IN ({','.join(repr(u) for u in UOFI)})")
    con.execute("ALTER TABLE panel ADD COLUMN is_big_ten BOOLEAN")
    con.execute(f"UPDATE panel SET is_big_ten = unitid IN ({','.join(repr(u) for u in BIG_TEN)})")

    for name in ("panel", "comparability_flags"):
        con.execute(f"COPY (SELECT * FROM {name} ORDER BY ALL) TO '{ART / (name + '.parquet')}' (FORMAT parquet, COMPRESSION zstd)")

    # summary
    summ = {}
    summ["institution_years"] = con.execute("SELECT count(*) FROM panel").fetchall()[0][0]
    summ["institutions"] = con.execute("SELECT count(DISTINCT unitid) FROM panel").fetchall()[0][0]
    summ["by_year"] = dict(con.execute("SELECT year, count(*) FROM panel GROUP BY 1 ORDER BY 1").fetchall())
    summ["by_sector_2023"] = dict(con.execute("SELECT sector, count(*) FROM panel WHERE year = 2023 GROUP BY 1 ORDER BY 1").fetchall())
    summ["excluded_share"] = {d: round(con.execute(f"SELECT avg(excl_{d}::INT) FROM panel").fetchall()[0][0], 4)
                              for d in ("staff", "tenure", "new_hires", "faculty_pay", "enrollment")}
    summ["flags_by_code"] = {f"{c}|{s}": n for c, s, n in con.execute(
        "SELECT flag_code, severity, count(*) FROM comparability_flags GROUP BY 1, 2 ORDER BY 3 DESC").fetchall()}
    summ["peer_benchmarks_exclude_flags_unioned"] = n_pb
    summ["finance_research_nonnull"] = con.execute("SELECT count(research_exp_real) FROM panel").fetchall()[0][0]
    summ["uofi"] = con.execute("""SELECT unitid, year, staff_total, tenured_share, staff_per_100_fte, fac_pay_real_7,
        research_exp_real, excl_staff, excl_tenure FROM panel WHERE is_uofi ORDER BY 1, 2""").fetchall()
    summ["uofi"] = [list(r) for r in summ["uofi"]]
    (MAN / "panel_manifest.json").write_text(json.dumps({
        "built_at_utc": datetime.now(timezone.utc).isoformat(), "years": YEARS,
        "thresholds": {"shift_caution": SHIFT_CAUTION, "shift_exclude": SHIFT_EXCLUDE, "min_ft_instr": MIN_FT_INSTR,
                       "min_group_ft": MIN_GROUP_FT, "min_rank_n": MIN_RANK_N, "min_fte": MIN_FTE,
                       "pay_min": PAY_MIN, "pay_max": PAY_MAX},
        "summary": summ, "source_members": sources,
        "columns": [c[0] for c in con.execute("DESCRIBE panel").fetchall()]}, indent=1, default=str) + "\n")
    print(json.dumps({k: v for k, v in summ.items() if k != "uofi"}, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
