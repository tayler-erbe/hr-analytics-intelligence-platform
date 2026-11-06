"""Build the multi-year IPEDS peer benchmark (Fall 2015-2023) from raw downloads.

    python peer_benchmarks/acquire.py   # first
    python peer_benchmarks/build.py     # -> peer_benchmarks/artifacts/*.parquet + peer_trends.json

Reads only the zipped IPEDS CSVs and dictionaries in data/lake/raw/ipeds_history/
(revised "_rv" CSV preferred when a zip carries one) and the BLS CPI-U page saved there.
Nothing in lake/ or scripts/ is read or changed.

Grain rules (see METHODS.md):
  * Occupation facts use the 14 IPEDS occupation groups at the 3-digit OCCUPCAT level
    (210 instructional ... 390 production). Library (260) and student/academic affairs (270)
    are kept combined as 250 so staff, new-hire and salary files share one code list.
    Those 14 groups x {full-time, part-time} partition the published grand total exactly.
  * Graduate assistants are outside the IPEDS grand total and are reported separately.
  * Every value carries its IPEDS imputation flag; comparability flags live in
    comparability_flags.parquet and are joined, never silently applied.
"""
from __future__ import annotations

import html
import io
import json
import re
import statistics
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import openpyxl
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.csv as pacsv

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
RAW = ROOT / "data" / "lake" / "raw" / "ipeds_history"
ART = HERE / "artifacts"
MANIFESTS = HERE / "manifests"
YEARS = list(range(2015, 2024))
SOC2018_FIRST_YEAR = 2018  # 2018-19 HR collection (Fall 2018) adopted the 2018 SOC
BASE_AY = "2023-24"

# Panel = gold_institution_panel in lake/gold/gold_views.sql (U of I System + 15 Big Ten publics).
PANEL = {
    "145637": ("UIUC", "uofi_system"), "145600": ("UIC", "uofi_system"), "148654": ("UIS", "uofi_system"),
    "149587": ("System Offices", "uofi_system"),
    "170976": ("Michigan", "big_ten_peer"), "240444": ("Wisconsin", "big_ten_peer"),
    "204796": ("Ohio State", "big_ten_peer"), "243780": ("Purdue", "big_ten_peer"),
    "174066": ("Minnesota", "big_ten_peer"), "151351": ("Indiana", "big_ten_peer"),
    "153658": ("Iowa", "big_ten_peer"), "171100": ("Michigan State", "big_ten_peer"),
    "214777": ("Penn State", "big_ten_peer"), "186380": ("Rutgers NB", "big_ten_peer"),
    "163286": ("Maryland", "big_ten_peer"), "181464": ("Nebraska", "big_ten_peer"),
    "110662": ("UCLA", "big_ten_peer"), "209551": ("Oregon", "big_ten_peer"),
    "236948": ("Washington", "big_ten_peer"),
}
PEERS = [u for u, (_, r) in PANEL.items() if r == "big_ten_peer"]
UOFI = [u for u, (_, r) in PANEL.items() if r == "uofi_system"]

# 14 IPEDS occupation groups (3-digit OCCUPCAT) with the matching S_NH and SAL_NIS codes.
GROUPS = [  # code, label, NH SNHCAT, NIS index (None = instructional, not in SAL_NIS)
    ("210", "Instructional", "21000", None),
    ("220", "Research", "22000", "02"),
    ("230", "Public service", "23000", "03"),
    ("250", "Library, student & academic affairs, other education services", "25000", "04"),
    ("300", "Management", "30000", "05"),
    ("310", "Business & financial operations", "31000", "06"),
    ("320", "Computer, engineering & science", "32000", "07"),
    ("330", "Community/social service, legal, arts, design, media", "33000", "08"),
    ("340", "Healthcare practitioners & technical", "34000", "09"),
    ("350", "Service", "35000", "10"),
    ("360", "Sales & related", "36000", "11"),
    ("370", "Office & administrative support", "37000", "12"),
    ("380", "Natural resources, construction & maintenance", "38000", "13"),
    ("390", "Production, transportation & material moving", "39000", "14"),
]
GROUP_LABEL = {g[0]: g[1] for g in GROUPS}
RANKS = {"7": "All ranks", "1": "Professor", "2": "Associate professor", "3": "Assistant professor",
         "4": "Instructor", "5": "Lecturer", "6": "No academic rank"}
TENURE = {"20": "Tenured", "30": "On tenure track", "40": "Not on tenure track / no tenure system",
          "50": "Without faculty status"}
IMPUTED = {"J", "K", "L", "N", "P"}       # logical, ratio, group median, nearest neighbor, carry forward
ADJUSTED = {"C", "G", "H"}               # analyst corrected, generated from other values, not usable
# IPEDS fall FTE factors for part-time students at public 4-year institutions.
FALL_FTE_PT_UG, FALL_FTE_PT_GR = 0.403543, 0.361702


# ----------------------------------------------------------------------------- raw readers
TEXT_COLS = {"unitid", "staffcat", "occupcat", "ftpt", "siscat", "facstat", "arank", "snhcat", "efalevel", "effylev",
             "effyalev", "countycd", "fips", "cbsa", "instnm", "stabbr", "f1sysnam", "idx_hr"}


def is_text_col(name: str) -> bool:
    n = name.strip().lower()
    return n in TEXT_COLS or n.startswith("x")


def _member(z: zipfile.ZipFile) -> str:
    names = [n for n in z.namelist() if n.lower().endswith(".csv")]
    rv = [n for n in names if n.lower().endswith("_rv.csv")]
    return rv[0] if rv else names[0]


def read_ipeds(name: str) -> tuple[pa.Table, str]:
    """Return (table with lower-case columns, csv member used). Codes and IDs stay strings."""
    with zipfile.ZipFile(RAW / f"{name}.zip") as z:
        member = _member(z)
        data = z.read(member)
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    header = data.split(b"\n", 1)[0].decode("latin1").strip().split(",")
    string_cols = {c: pa.string() for c in header if is_text_col(c)}
    t = pacsv.read_csv(io.BytesIO(data), read_options=pacsv.ReadOptions(encoding="latin1"),
                       convert_options=pacsv.ConvertOptions(column_types=string_cols, strings_can_be_null=True))
    # A measure column read as text (stray blanks or '.') is converted to numbers; blanks become NULL.
    for i, field in enumerate(t.schema):
        if field.name in string_cols:  # IPEDS pads some codes with spaces (e.g. SISCAT '  1')
            t = t.set_column(i, field.name, pc.utf8_trim_whitespace(t.column(i)))
        elif pa.types.is_string(field.type):
            col = pc.utf8_trim_whitespace(t.column(i))
            col = pc.if_else(pc.is_in(col, pa.array(["", "."])), pa.scalar(None, pa.string()), col)
            try:
                t = t.set_column(i, field.name, pc.cast(col, pa.float64()))
            except pa.ArrowInvalid:
                pass  # genuinely textual (names, addresses): left as text
    return t.rename_columns([c.strip().lower() for c in t.column_names]), member


def read_dict(name: str) -> dict:
    """Published statistics (sum per variable) and value labels from the IPEDS dictionary workbook."""
    with zipfile.ZipFile(RAW / f"{name}_Dict.zip") as z:
        wb = openpyxl.load_workbook(io.BytesIO(z.read(z.namelist()[0])), read_only=True)
    sheets = {s.lower(): s for s in wb.sheetnames}
    out = {"stats": {}, "stats_rv": {}, "labels": {}}
    for key, sheet in (("stats", "statistics"), ("stats_rv", "statisticsrv")):
        if sheet in sheets:
            for r in list(wb[sheets[sheet]].iter_rows(values_only=True))[1:]:
                if r and r[1]:
                    out[key][str(r[1]).lower()] = {"n": r[2], "sum": r[3]}
    fs = sheets.get("frequenciesrv") or sheets.get("frequencies")
    if fs:
        for r in list(wb[fs].iter_rows(values_only=True))[1:]:
            if r and r[1]:
                out["labels"].setdefault(str(r[1]).lower(), {})[str(r[2])] = r[3]
    return out


def cpi_monthly() -> list[tuple[int, int, float]]:
    """Parse CPI-U (CUUR0000SA0) monthly values from the saved data.bls.gov table page."""
    p = RAW / "bls_cpi_u_CUUR0000SA0.html"
    if not p.exists():
        return []
    text = p.read_text(errors="replace")
    if "CUUR0000SA0" not in text:
        return []
    m = re.search(r'<TABLE id="table0".*?</TABLE>', text, re.S | re.I)
    if not m:
        return []
    rows = []
    for tr in re.findall(r"<TR[^>]*>(.*?)</TR>", m.group(0), re.S | re.I):
        yr = re.search(r'<TH scope="row">\s*(\d{4})\s*</TH>', tr)
        if not yr:
            continue
        cells = [html.unescape(re.sub(r"<[^>]+>", "", c)).strip() for c in re.findall(r"<TD[^>]*>(.*?)</TD>", tr, re.S | re.I)]
        for month, val in enumerate(cells[:12], start=1):
            v = re.sub(r"[^\d.]", "", val)
            if v:
                rows.append((int(yr.group(1)), month, float(v)))
    return rows


# ----------------------------------------------------------------------------- build
def main() -> int:
    ART.mkdir(parents=True, exist_ok=True)
    MANIFESTS.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    recon = []      # parsed vs published dictionary sums
    sources = []    # file -> member used

    def load_family(prefix_fmt: str, year_offset: int, cols: list[str], stat_vars: list[str], table: str,
                    years=YEARS):
        parts = []
        for y in years:
            name = prefix_fmt.format(y=y + year_offset)
            t, member = read_ipeds(name)
            sources.append({"file": name, "member": member, "fall_year": y})
            d = read_dict(name)
            stats = d["stats_rv"] if member.lower().endswith("_rv.csv") and d["stats_rv"] else d["stats"]
            for v in stat_vars:
                if v in t.column_names and v in stats:
                    col = t.column(v)
                    parsed = pc.sum(col).as_py() or 0
                    recon.append({"file": name, "member": member, "fall_year": y, "variable": v,
                                  "published_sum": float(stats[v]["sum"]), "parsed_sum": float(parsed),
                                  "published_n": int(stats[v]["n"]), "parsed_n": int(len(col) - col.null_count)})
            present = [c for c in cols if c in t.column_names]
            sel = t.select(present)
            for c in cols:
                if c not in present:
                    sel = sel.append_column(c, pa.nulls(len(sel), pa.string() if is_text_col(c) else pa.float64()))
            sel = sel.append_column("year", pa.array([y] * len(sel), pa.int32()))
            parts.append(sel.select(cols + ["year"]))
        merged = pa.concat_tables(parts, promote_options="permissive")
        con.register(f"_{table}", merged)
        con.sql(f"CREATE OR REPLACE TABLE {table} AS SELECT * FROM _{table}")
        con.unregister(f"_{table}")

    print("loading raw IPEDS files ...")
    load_family("S{y}_OC", 0, ["unitid", "staffcat", "ftpt", "occupcat", "hrtotlt", "hrtotlm", "hrtotlw", "xhrtotlt"],
                ["hrtotlt", "hrtotlm", "hrtotlw"], "s_oc")
    load_family("S{y}_IS", 0, ["unitid", "siscat", "facstat", "arank", "hrtotlt", "xhrtotlt"], ["hrtotlt"], "s_is")
    load_family("S{y}_NH", 0, ["unitid", "snhcat", "hrtotlt", "xhrtotlt"], ["hrtotlt"], "s_nh")
    sal_cols = ["unitid", "arank", "satotlt", "satotlm", "satotlw", "xsatotlt", "sainstt", "saoutlt",
                "saeq9at", "saeq9am", "saeq9aw", "xsaeq9at", "xsaeq9am", "xsaeq9aw",
                "saavmnt", "saavmnm", "saavmnw", "xsaavmnt"]
    load_family("SAL{y}_IS", 0, sal_cols, ["satotlt", "saoutlt"], "sal_is")
    nis_cols = ["unitid"] + [f"{p}{i:02d}" for i in range(1, 15) for p in ("sanin", "sanit", "xsanin", "xsanit")]
    load_family("SAL{y}_NIS", 0, nis_cols, ["sanin01", "sanit01"], "sal_nis")
    load_family("EF{y}A", 0, ["unitid", "efalevel", "eftotlt", "xeftotlt"], ["eftotlt"], "ef_a")
    load_family("EFIA{y}", 1, ["unitid", "fteug", "ftegd", "ftedpp", "efteug", "eftegd", "xfteug", "xftegd"],
                ["fteug", "ftegd", "ftedpp"], "efia")
    load_family("EFFY{y}", 1, ["unitid", "effylev", "effyalev", "efytotlt", "xeytotlt"], ["efytotlt"], "effy")
    load_family("HD{y}", 0, ["unitid", "instnm", "stabbr", "countycd", "hospital", "medical", "f1sysnam"], [], "hd")
    load_family("FLAGS{y}", 0, ["unitid", "stat_hr", "prch_hr", "idx_hr", "imp_hr", "stat_sa", "stat_ef",
                                "prch_ef", "prch_e12", "rev_hr"], [], "flags")

    panel_rows = [(u, s, r) for u, (s, r) in PANEL.items()]
    con.sql("CREATE TABLE panel(unitid VARCHAR, short_name VARCHAR, panel_role VARCHAR)")
    con.executemany("INSERT INTO panel VALUES (?, ?, ?)", panel_rows)
    con.sql("CREATE TABLE groups(group_code VARCHAR, occupation_group VARCHAR, snhcat VARCHAR, nis VARCHAR)")
    con.executemany("INSERT INTO groups VALUES (?, ?, ?, ?)", GROUPS)
    con.sql("CREATE TABLE years AS SELECT unnest(range(2015, 2024))::INTEGER AS year")
    imputed_list = ",".join(f"'{c}'" for c in sorted(IMPUTED))
    adjusted_list = ",".join(f"'{c}'" for c in sorted(ADJUSTED))

    def flag_class(col):
        return (f"CASE WHEN {col} IN ({imputed_list}) THEN 'imputed' WHEN {col} IN ({adjusted_list}) THEN 'adjusted' "
                f"WHEN {col} IS NULL THEN NULL ELSE 'reported' END")

    def soc_basis():
        return f"CASE WHEN year >= {SOC2018_FIRST_YEAR} THEN 'SOC 2018' ELSE 'SOC 2010' END"

    # ------------------------------------------------------------- dimension
    con.sql("""
      CREATE TABLE dim_institution_year AS
      SELECT p.unitid, y.year, p.short_name, p.panel_role,
             h.instnm AS institution_name, h.stabbr AS state,
             lpad(h.countycd, 5, '0') AS county_fips, h.hospital::INTEGER AS hospital_code,
             h.medical::INTEGER AS medical_school_code, trim(h.f1sysnam) AS system_name,
             f.stat_hr::INTEGER AS hr_response_status, f.prch_hr::INTEGER AS hr_parent_child,
             CASE WHEN f.idx_hr IN ('-2', '') THEN NULL ELSE f.idx_hr END AS hr_reported_with_unitid,
             f.imp_hr::INTEGER AS hr_imputation_method, f.stat_sa::INTEGER AS salary_response_status,
             f.prch_ef::INTEGER AS fall_enrollment_parent_child, f.prch_e12::INTEGER AS enrollment_12mo_parent_child,
             (h.unitid IS NOT NULL) AS in_directory
      FROM panel p CROSS JOIN years y
      LEFT JOIN hd h ON h.unitid = p.unitid AND h.year = y.year
      LEFT JOIN flags f ON f.unitid = p.unitid AND f.year = y.year
    """)

    # ------------------------------------------------------------- staff by occupation (partition)
    con.sql(f"""
      CREATE TABLE fact_staff_occupation AS
      SELECT s.unitid, s.year, g.group_code, g.occupation_group,
             CASE left(s.staffcat, 1) WHEN '2' THEN 'full_time' ELSE 'part_time' END AS ftpt,
             s.staffcat AS staffcat_code, s.hrtotlt::BIGINT AS headcount,
             s.hrtotlm::BIGINT AS headcount_men, s.hrtotlw::BIGINT AS headcount_women,
             s.xhrtotlt AS imputation_flag, {flag_class('s.xhrtotlt')} AS imputation_class,
             {soc_basis()} AS soc_basis
      FROM s_oc s
      JOIN groups g ON g.group_code = substr(s.staffcat, 2)
      WHERE s.unitid IN (SELECT unitid FROM panel) AND left(s.staffcat, 1) IN ('2', '3')
    """)
    con.sql(f"""
      CREATE TABLE fact_staff_totals AS
      SELECT unitid, year,
             max(CASE WHEN staffcat = '1100' THEN hrtotlt END)::BIGINT AS published_grand_total,
             max(CASE WHEN staffcat = '2100' THEN hrtotlt END)::BIGINT AS published_full_time,
             max(CASE WHEN staffcat = '3100' THEN hrtotlt END)::BIGINT AS published_part_time,
             max(CASE WHEN staffcat = '4400' THEN hrtotlt END)::BIGINT AS graduate_assistants,
             max(CASE WHEN staffcat = '1100' THEN xhrtotlt END) AS grand_total_imputation_flag,
             {soc_basis()} AS soc_basis
      FROM s_oc WHERE unitid IN (SELECT unitid FROM panel) GROUP BY unitid, year
    """)

    # ------------------------------------------------------------- faculty tenure status (FT instructional)
    con.sql(f"""
      CREATE TABLE fact_faculty_tenure AS
      SELECT unitid, year, facstat AS tenure_status_code,
             CASE facstat {' '.join(f"WHEN '{k}' THEN '{v}'" for k, v in TENURE.items())} END AS tenure_status,
             hrtotlt::BIGINT AS fulltime_instructional_headcount, xhrtotlt AS imputation_flag,
             {flag_class('xhrtotlt')} AS imputation_class
      FROM s_is WHERE unitid IN (SELECT unitid FROM panel) AND arank = '0' AND facstat IN ('20','30','40','50')
    """)
    con.sql("""
      CREATE TABLE _is_total AS SELECT unitid, year, hrtotlt::BIGINT AS published_fulltime_instructional
      FROM s_is WHERE unitid IN (SELECT unitid FROM panel) AND arank = '0' AND facstat = '0'
    """)

    # ------------------------------------------------------------- new hires vs FT staff
    con.sql(f"""
      CREATE TABLE fact_new_hires AS
      WITH nh AS (SELECT unitid, year, snhcat, hrtotlt, xhrtotlt FROM s_nh WHERE unitid IN (SELECT unitid FROM panel)),
           ft AS (SELECT unitid, year, group_code, headcount FROM fact_staff_occupation WHERE ftpt = 'full_time')
      SELECT p.unitid, y.year, g.group_code, g.occupation_group,
             -- S_NH omits zero rows: when the institution filed new hires that year, an absent group row is 0.
             CASE WHEN nh.hrtotlt IS NOT NULL THEN nh.hrtotlt::BIGINT WHEN tot.unitid IS NOT NULL THEN 0 END
               AS fulltime_new_hires,
             ft.headcount AS fulltime_staff_nov1,
             CASE WHEN ft.headcount > 0 AND tot.unitid IS NOT NULL
                  THEN round(100.0 * coalesce(nh.hrtotlt, 0) / ft.headcount, 2) END AS new_hires_per_100_fulltime,
             CASE WHEN nh.hrtotlt IS NULL AND tot.unitid IS NOT NULL THEN 'absent_row_implied_zero'
                  ELSE nh.xhrtotlt END AS imputation_flag, {flag_class('nh.xhrtotlt')} AS imputation_class,
             {soc_basis().replace('year', 'y.year')} AS soc_basis,
             CASE WHEN y.year <= 2015 THEN 'Jul 1-Oct 31 (4 months)' ELSE 'Nov 1-Oct 31 (12 months)' END AS hire_window
      FROM panel p CROSS JOIN years y CROSS JOIN groups g
      LEFT JOIN ft ON ft.unitid = p.unitid AND ft.year = y.year AND ft.group_code = g.group_code
      LEFT JOIN nh ON nh.unitid = p.unitid AND nh.year = y.year AND nh.snhcat = g.snhcat
      LEFT JOIN (SELECT DISTINCT unitid, year FROM nh WHERE snhcat = '10000') tot
        ON tot.unitid = p.unitid AND tot.year = y.year
      WHERE ft.headcount IS NOT NULL OR nh.hrtotlt IS NOT NULL
    """)
    con.sql("""
      CREATE TABLE _nh_total AS SELECT unitid, year, hrtotlt::BIGINT AS published_fulltime_new_hires
      FROM s_nh WHERE unitid IN (SELECT unitid FROM panel) AND snhcat = '10000'
    """)

    # ------------------------------------------------------------- CPI-U, academic-year deflator
    cpi = cpi_monthly()
    cpi_ok = False
    if cpi:
        con.sql("CREATE TABLE cpi_month(year INTEGER, month INTEGER, cpi_u DOUBLE)")
        con.executemany("INSERT INTO cpi_month VALUES (?, ?, ?)", cpi)
        con.sql("""
          CREATE TABLE cpi_academic_year AS
          SELECT y.year AS fall_year, cast(y.year AS VARCHAR) || '-' || right(cast(y.year + 1 AS VARCHAR), 2) AS academic_year,
                 avg(c.cpi_u) AS cpi_u_jul_jun, count(*) AS months
          FROM years y JOIN cpi_month c
            ON (c.year = y.year AND c.month >= 7) OR (c.year = y.year + 1 AND c.month <= 6)
          GROUP BY y.year HAVING count(*) = 12
        """)
        base = con.sql("SELECT cpi_u_jul_jun FROM cpi_academic_year WHERE fall_year = 2023").fetchall()
        n_ay = con.sql("SELECT count(*) FROM cpi_academic_year").fetchall()[0][0]
        cpi_ok = bool(base) and n_ay == len(YEARS)
    if cpi_ok:
        con.sql(f"""CREATE OR REPLACE TABLE cpi_academic_year AS SELECT *,
                    round((SELECT cpi_u_jul_jun FROM cpi_academic_year WHERE fall_year = 2023) / cpi_u_jul_jun, 6)
                    AS to_{BASE_AY.replace('-', '_')}_dollars FROM cpi_academic_year""")
        defl = f"d.to_{BASE_AY.replace('-', '_')}_dollars"
        join_cpi = "LEFT JOIN cpi_academic_year d ON d.fall_year = x.year"
    else:
        con.sql("CREATE OR REPLACE TABLE cpi_academic_year(fall_year INTEGER, academic_year VARCHAR, cpi_u_jul_jun DOUBLE, months BIGINT)")
        defl, join_cpi = "NULL", ""

    # ------------------------------------------------------------- faculty pay by rank (9-month equated)
    con.sql(f"""
      CREATE TABLE fact_faculty_salary AS
      WITH x AS (
        SELECT unitid, year, arank,
               satotlt::BIGINT AS n_total, satotlm::BIGINT AS n_men, satotlw::BIGINT AS n_women,
               CASE WHEN year = 2015 THEN round(saavmnt * 9) ELSE saeq9at END AS avg_9mo_total,
               CASE WHEN year = 2015 THEN round(saavmnm * 9) ELSE saeq9am END AS avg_9mo_men,
               CASE WHEN year = 2015 THEN round(saavmnw * 9) ELSE saeq9aw END AS avg_9mo_women,
               CASE WHEN year = 2015 THEN 'derived: 9 x average weighted monthly salary (SAAVMN*)'
                    ELSE 'reported: average salary equated to 9 months (SAEQ9A*)' END AS equating_method,
               CASE WHEN year = 2015 THEN xsaavmnt ELSE xsaeq9at END AS imputation_flag
        FROM sal_is WHERE unitid IN (SELECT unitid FROM panel)
      )
      SELECT x.unitid, x.year, cast(x.year AS VARCHAR) || '-' || right(cast(x.year + 1 AS VARCHAR), 2) AS academic_year,
             x.arank AS arank_code,
             CASE x.arank {' '.join(f"WHEN '{k}' THEN '{v}'" for k, v in RANKS.items())} END AS academic_rank,
             x.n_total, x.n_men, x.n_women, x.avg_9mo_total, x.avg_9mo_men, x.avg_9mo_women,
             CASE WHEN x.avg_9mo_men > 0 AND x.avg_9mo_women > 0
                  THEN round(x.avg_9mo_women / x.avg_9mo_men, 4) END AS women_to_men_raw_ratio,
             (least(coalesce(x.n_men, 0), coalesce(x.n_women, 0)) < 10) AS small_cell,
             round(x.avg_9mo_total * {defl}) AS avg_9mo_total_real,
             round(x.avg_9mo_men * {defl}) AS avg_9mo_men_real,
             round(x.avg_9mo_women * {defl}) AS avg_9mo_women_real,
             '{BASE_AY}' AS real_dollar_base, x.equating_method,
             x.imputation_flag, {flag_class('x.imputation_flag')} AS imputation_class
      FROM x {join_cpi}
    """)

    # ------------------------------------------------------------- non-instructional pay by group
    nis_union = " UNION ALL ".join(
        f"SELECT unitid, year, '{g}' AS group_code, sanin{n}::BIGINT AS fulltime_staff, sanit{n}::DOUBLE AS salary_outlays, "
        f"coalesce(xsanit{n}, xsanin{n}) AS imputation_flag FROM sal_nis WHERE unitid IN (SELECT unitid FROM panel)"
        for g, _, _, n in GROUPS if n)
    con.sql(f"""
      CREATE TABLE fact_noninstructional_pay AS
      WITH x AS ({nis_union})
      SELECT x.unitid, x.year, cast(x.year AS VARCHAR) || '-' || right(cast(x.year + 1 AS VARCHAR), 2) AS academic_year,
             x.group_code, g.occupation_group, x.fulltime_staff, x.salary_outlays,
             CASE WHEN x.fulltime_staff > 0 THEN round(x.salary_outlays / x.fulltime_staff) END AS avg_salary,
             CASE WHEN x.fulltime_staff > 0 THEN round(x.salary_outlays / x.fulltime_staff * {defl}) END AS avg_salary_real,
             '{BASE_AY}' AS real_dollar_base, x.imputation_flag, {flag_class('x.imputation_flag')} AS imputation_class,
             {soc_basis().replace('year', 'x.year')} AS soc_basis
      FROM x JOIN groups g USING (group_code) {join_cpi}
    """)
    con.sql("""CREATE TABLE _nis_total AS SELECT unitid, year, sanin01::BIGINT AS published_n, sanit01::DOUBLE AS published_outlays
               FROM sal_nis WHERE unitid IN (SELECT unitid FROM panel)""")

    # ------------------------------------------------------------- enrollment denominators
    con.sql(f"""
      CREATE TABLE fact_enrollment AS
      WITH ef AS (
        SELECT unitid, year,
               max(CASE WHEN efalevel = '1' THEN eftotlt END) AS fall_headcount,
               max(CASE WHEN efalevel = '21' THEN eftotlt END) AS fall_fulltime,
               max(CASE WHEN efalevel = '42' THEN eftotlt END) AS fall_parttime_undergrad,
               max(CASE WHEN efalevel = '52' THEN eftotlt END) AS fall_parttime_graduate,
               max(CASE WHEN efalevel = '1' THEN xeftotlt END) AS fall_imputation_flag
        FROM ef_a WHERE unitid IN (SELECT unitid FROM panel) GROUP BY unitid, year),
      ia AS (SELECT unitid, year, fteug, ftegd, ftedpp, efteug, eftegd, xfteug FROM efia WHERE unitid IN (SELECT unitid FROM panel)),
      fy AS (SELECT unitid, year, efytotlt, xeytotlt FROM effy
             WHERE unitid IN (SELECT unitid FROM panel) AND coalesce(effyalev, effylev) = '1')
      SELECT p.unitid, y.year,
             cast(y.year AS VARCHAR) || '-' || right(cast(y.year + 1 AS VARCHAR), 2) AS academic_year,
             ef.fall_headcount::BIGINT AS fall_headcount, ef.fall_fulltime::BIGINT AS fall_fulltime,
             ef.fall_parttime_undergrad::BIGINT AS fall_parttime_undergrad,
             ef.fall_parttime_graduate::BIGINT AS fall_parttime_graduate,
             round(ef.fall_fulltime + {FALL_FTE_PT_UG} * coalesce(ef.fall_parttime_undergrad, 0)
                   + {FALL_FTE_PT_GR} * coalesce(ef.fall_parttime_graduate, 0), 1) AS fall_fte_computed,
             ia.fteug AS fte12_undergrad, ia.ftegd AS fte12_graduate, ia.ftedpp AS fte12_doctor_professional,
             CASE WHEN ia.fteug IS NOT NULL OR ia.ftegd IS NOT NULL
                  THEN coalesce(ia.fteug, 0) + coalesce(ia.ftegd, 0) + coalesce(ia.ftedpp, 0) END AS fte12_total,
             fy.efytotlt::BIGINT AS unduplicated_12mo_headcount,
             ef.fall_imputation_flag, ia.xfteug AS fte12_imputation_flag, fy.xeytotlt AS effy_imputation_flag,
             'EF' || y.year || 'A' AS fall_source, 'EFIA' || (y.year + 1) AS fte12_source, 'EFFY' || (y.year + 1) AS effy_source
      FROM panel p CROSS JOIN years y
      LEFT JOIN ef ON ef.unitid = p.unitid AND ef.year = y.year
      LEFT JOIN ia ON ia.unitid = p.unitid AND ia.year = y.year
      LEFT JOIN fy ON fy.unitid = p.unitid AND fy.year = y.year
    """)

    # ------------------------------------------------------------- institution-year metrics (wide)
    con.sql("""
      CREATE TABLE fact_institution_metrics AS
      WITH o AS (
        SELECT unitid, year, sum(headcount) AS staff_total,
               sum(headcount) FILTER (WHERE ftpt = 'full_time') AS staff_fulltime,
               sum(headcount) FILTER (WHERE ftpt = 'part_time') AS staff_parttime,
               sum(headcount) FILTER (WHERE group_code = '300') AS management_headcount,
               sum(headcount) FILTER (WHERE group_code = '300' AND ftpt = 'full_time') AS management_fulltime,
               sum(headcount) FILTER (WHERE group_code = '210') AS instructional_headcount,
               sum(headcount) FILTER (WHERE group_code = '210' AND ftpt = 'full_time') AS instructional_fulltime,
               count(*) FILTER (WHERE imputation_class = 'imputed') AS n_imputed_staff_cells
        FROM fact_staff_occupation GROUP BY unitid, year),
      t AS (SELECT unitid, year,
               sum(fulltime_instructional_headcount) AS ft_instr,
               sum(fulltime_instructional_headcount) FILTER (WHERE tenure_status_code = '20') AS tenured,
               sum(fulltime_instructional_headcount) FILTER (WHERE tenure_status_code = '30') AS tenure_track,
               sum(fulltime_instructional_headcount) FILTER (WHERE tenure_status_code = '40') AS non_tenure_track,
               sum(fulltime_instructional_headcount) FILTER (WHERE tenure_status_code = '50') AS no_faculty_status
            FROM fact_faculty_tenure GROUP BY unitid, year),
      n AS (SELECT unitid, year, sum(fulltime_new_hires) AS ft_new_hires FROM fact_new_hires GROUP BY unitid, year)
      SELECT d.unitid, d.year, d.short_name, d.panel_role,
             o.staff_total, o.staff_fulltime, o.staff_parttime, tot.graduate_assistants,
             o.management_headcount, o.management_fulltime, o.instructional_headcount, o.instructional_fulltime,
             round(100.0 * o.staff_fulltime / nullif(o.staff_total, 0), 2) AS fulltime_share_pct,
             round(100.0 * o.management_headcount / nullif(o.staff_total, 0), 2) AS management_share_pct,
             round(100.0 * o.management_fulltime / nullif(o.staff_fulltime, 0), 2) AS management_share_fulltime_pct,
             e.fte12_total, e.fall_fte_computed, e.fall_headcount,
             round(100.0 * o.staff_total / nullif(e.fte12_total, 0), 2) AS staff_per_100_fte12,
             round(100.0 * o.staff_fulltime / nullif(e.fte12_total, 0), 2) AS fulltime_staff_per_100_fte12,
             round(100.0 * o.staff_total / nullif(e.fall_fte_computed, 0), 2) AS staff_per_100_fall_fte,
             round(100.0 * o.instructional_fulltime / nullif(e.fte12_total, 0), 2) AS ft_instructional_per_100_fte12,
             round(100.0 * o.management_headcount / nullif(e.fte12_total, 0), 3) AS management_per_100_fte12,
             t.ft_instr AS fulltime_instructional, t.tenured, t.tenure_track, t.non_tenure_track, t.no_faculty_status,
             round(100.0 * t.tenured / nullif(t.ft_instr, 0), 2) AS tenured_share_pct,
             round(100.0 * t.tenure_track / nullif(t.ft_instr, 0), 2) AS tenure_track_share_pct,
             round(100.0 * (coalesce(t.non_tenure_track, 0) + coalesce(t.no_faculty_status, 0)) / nullif(t.ft_instr, 0), 2) AS non_tenure_share_pct,
             n.ft_new_hires, round(100.0 * n.ft_new_hires / nullif(o.staff_fulltime, 0), 2) AS new_hires_per_100_fulltime,
             o.n_imputed_staff_cells, tot.published_grand_total
      FROM dim_institution_year d
      LEFT JOIN o USING (unitid, year) LEFT JOIN t USING (unitid, year) LEFT JOIN n USING (unitid, year)
      LEFT JOIN fact_enrollment e USING (unitid, year) LEFT JOIN fact_staff_totals tot USING (unitid, year)
    """)

    # ------------------------------------------------------------- national SOC-2018 break diagnostic
    con.sql("""
      CREATE TABLE national_occupation_share AS
      WITH x AS (
        SELECT year, substr(staffcat, 2) AS group_code, sum(hrtotlt) AS headcount
        FROM s_oc WHERE left(staffcat, 1) IN ('2', '3') AND substr(staffcat, 2) IN (SELECT group_code FROM groups)
        GROUP BY 1, 2)
      SELECT x.year, x.group_code, g.occupation_group, x.headcount::BIGINT AS headcount,
             round(100.0 * x.headcount / sum(x.headcount) OVER (PARTITION BY x.year), 3) AS share_pct
      FROM x JOIN groups g USING (group_code)
    """)
    con.sql("""
      CREATE TABLE soc_break_test AS
      WITH c AS (
        SELECT group_code, occupation_group, year,
               share_pct - lag(share_pct) OVER (PARTITION BY group_code ORDER BY year) AS d_share,
               100.0 * (headcount::DOUBLE / lag(headcount) OVER (PARTITION BY group_code ORDER BY year) - 1) AS d_pct
        FROM national_occupation_share)
      SELECT group_code, occupation_group,
             round(max(d_share) FILTER (WHERE year = 2018), 3) AS share_change_2017_to_2018_pp,
             round(median(abs(d_share)) FILTER (WHERE year <> 2018 AND year > 2015), 3) AS median_abs_share_change_other_years_pp,
             round(max(d_pct) FILTER (WHERE year = 2018), 2) AS headcount_change_2017_to_2018_pct,
             round(median(abs(d_pct)) FILTER (WHERE year <> 2018 AND year > 2015), 2) AS median_abs_headcount_change_other_years_pct
      FROM c GROUP BY group_code, occupation_group
    """)
    con.sql("""
      CREATE OR REPLACE TABLE soc_break_test AS SELECT *,
        CASE WHEN abs(share_change_2017_to_2018_pp) >= greatest(0.15, 3 * median_abs_share_change_other_years_pp)
             THEN 'break_detected' ELSE 'no_material_break' END AS national_break_assessment
      FROM soc_break_test ORDER BY group_code
    """)

    # ------------------------------------------------------------- 2016 bridge for the 2015 equating method
    con.sql("""
      CREATE TABLE salary_method_bridge_2016 AS
      SELECT s.unitid, p.short_name, s.arank AS arank_code, s.saeq9at AS reported_eq9_2016,
             round(s.saavmnt * 9) AS derived_9x_monthly_2016,
             round(100.0 * (s.saavmnt * 9 / s.saeq9at - 1), 2) AS derived_minus_reported_pct
      FROM sal_is s JOIN panel p USING (unitid)
      WHERE s.year = 2016 AND s.saeq9at > 0 AND s.saavmnt > 0
    """)

    # ------------------------------------------------------------- comparability flags
    flags = []

    def add(unitid, year, domain, code, detail, severity="info"):
        flags.append((unitid, year, domain, code, severity, detail))

    for u in PANEL:
        for y in YEARS:
            if y >= SOC2018_FIRST_YEAR:
                for dom in ("staff_occupation", "new_hires", "noninstructional_pay"):
                    add(u, y, dom, "SOC2018_CATEGORY_BASIS",
                        "Occupation groups assigned with the 2018 SOC (2018-19 HR onward); earlier years use SOC 2010. "
                        "Group codes are unchanged; see soc_break_test for groups with a national discontinuity.",
                        "caution" if y == SOC2018_FIRST_YEAR else "info")
        add(u, 2015, "faculty_pay", "EQ9_METHOD_2015",
            "SAL2015_IS has no 9-month-equated average; value is 9 x average weighted monthly salary. "
            "See salary_method_bridge_2016 for the size of the method difference.", "caution")
        add(u, 2015, "faculty_tenure", "NTT_CONTRACT_DETAIL_2016",
            "Not-on-tenure-track contract detail was split (multi-year vs indefinite) from 2016; the aggregate "
            "non-tenure-track total used here is unaffected.", "info")
        add(u, 2015, "new_hires", "NEW_HIRE_WINDOW_2015",
            "Fall 2015 new hires cover Jul 1-Oct 31 (4 months); from Fall 2016 IPEDS counts Nov 1-Oct 31 (12 months). "
            "2015 rates are kept in the tables but not charted or compared.", "caution")
        add(u, 2020, "all", "PANDEMIC_PERIOD",
            "Fall 2020 / 2021 snapshots fall in the COVID-19 period (hiring freezes, furloughs, enrollment shifts).", "info")

    for (u, y, prch, idx, stat_hr, in_dir) in con.sql(
            "SELECT unitid, year, hr_parent_child, hr_reported_with_unitid, hr_response_status, in_directory "
            "FROM dim_institution_year").fetchall():
        if prch == 1:
            add(u, y, "all", "PARENT_INCLUDES_CHILD_CAMPUSES",
                "FLAGS: HR parent record includes data from child campuses (PRCH_HR = 1); scope is not comparable "
                "with single-campus years, so the institution-year is left out of charts and peer bands.", "exclude")
        if prch == 2:
            add(u, y, "all", "CHILD_REPORTED_WITH_PARENT", f"FLAGS: HR reported with parent UNITID {idx}.", "exclude")
        if stat_hr is not None and stat_hr != 1:
            add(u, y, "all", "HR_RESPONSE_STATUS", f"FLAGS: HR response status code {stat_hr} (1 = respondent).",
                "caution")
        if stat_hr is None:
            add(u, y, "all", "NOT_IN_FLAGS_FILE", "Institution absent from FLAGS file for this year.", "caution")

    # Missing HR files for an institution-year
    for (u, y) in con.sql("""SELECT d.unitid, d.year FROM dim_institution_year d LEFT JOIN fact_staff_totals t USING (unitid, year)
                             WHERE t.published_grand_total IS NULL""").fetchall():
        add(u, y, "all", "MISSING_HR_YEAR", "No staff (S_OC) rows for this institution-year.", "exclude")

    # Imputed or adjusted values, summarised per domain
    for dom, tbl in (("staff_occupation", "fact_staff_occupation"), ("faculty_tenure", "fact_faculty_tenure"),
                     ("new_hires", "fact_new_hires"), ("faculty_pay", "fact_faculty_salary"),
                     ("noninstructional_pay", "fact_noninstructional_pay")):
        for (u, y, cls, k, codes) in con.sql(
                f"SELECT unitid, year, imputation_class, count(*), string_agg(DISTINCT imputation_flag, ',') FROM {tbl} "
                f"WHERE imputation_class IN ('imputed', 'adjusted') GROUP BY 1, 2, 3").fetchall():
            add(u, y, dom, "IMPUTED_VALUES" if cls == "imputed" else "ADJUSTED_VALUES",
                f"{k} cell(s) with IPEDS flag {codes}.", "caution")

    # Level shifts in published totals (reporting changes show up here)
    for (u, y, prev, cur, pct) in con.sql("""
        WITH t AS (SELECT unitid, year, published_grand_total AS cur,
                          lag(published_grand_total) OVER (PARTITION BY unitid ORDER BY year) AS prev
                   FROM fact_staff_totals)
        SELECT unitid, year, prev, cur, round(100.0 * (cur::DOUBLE / prev - 1), 1) FROM t
        WHERE prev > 0 AND abs(cur::DOUBLE / prev - 1) >= 0.15""").fetchall():
        add(u, y, "staff_occupation", "LEVEL_SHIFT_TOTAL_STAFF",
            f"Published grand total moved {pct:+.1f}% ({prev:,} -> {cur:,}) from the prior fall; check for a "
            "reporting-scope change before reading it as real growth.", "caution")
    for (u, y, g, prev, cur) in con.sql("""
        WITH t AS (SELECT unitid, year, group_code, sum(headcount) AS cur FROM fact_staff_occupation GROUP BY 1,2,3),
             l AS (SELECT *, lag(cur) OVER (PARTITION BY unitid, group_code ORDER BY year) AS prev FROM t)
        SELECT unitid, year, group_code, prev, cur FROM l
        WHERE prev >= 100 AND abs(cur::DOUBLE / prev - 1) >= 0.30""").fetchall():
        add(u, y, "staff_occupation", "LEVEL_SHIFT_GROUP",
            f"{GROUP_LABEL[g]} headcount {prev:,} -> {cur:,} ({100 * (cur / prev - 1):+.0f}%).", "caution")
    for (u, y, prev, cur) in con.sql("""
        WITH t AS (SELECT unitid, year, fte12_total AS cur, lag(fte12_total) OVER (PARTITION BY unitid ORDER BY year) AS prev
                   FROM fact_enrollment)
        SELECT unitid, year, prev, cur FROM t WHERE prev > 0 AND abs(cur / prev - 1) >= 0.15""").fetchall():
        add(u, y, "enrollment", "LEVEL_SHIFT_FTE", f"12-month FTE moved {prev:,.0f} -> {cur:,.0f}.", "caution")
    for (u, y) in con.sql("SELECT unitid, year FROM fact_enrollment WHERE fte12_total IS NULL").fetchall():
        add(u, y, "enrollment", "NO_STUDENT_FTE", "No 12-month FTE reported (e.g., System Offices enrol no students); "
            "per-student ratios are NULL.", "info")
    for (u, y, r) in con.sql("SELECT unitid, year, academic_rank FROM fact_faculty_salary WHERE small_cell "
                             "AND avg_9mo_total IS NOT NULL").fetchall():
        add(u, y, "faculty_pay", "SMALL_CELL_SEX_RATIO",
            f"{r}: fewer than 10 men or women; raw women/men ratio not charted.", "info")
    if not cpi_ok:
        for u in PANEL:
            add(u, 2015, "all", "REAL_DOLLARS_UNAVAILABLE", "CPI-U could not be downloaded; real-dollar series skipped.",
                "info")

    # Years after an excluded / missing year: scope not verified against the earlier series.
    excluded = {(u, y) for (u, y, _, code, sev, _) in flags if sev == "exclude"}
    for u in PANEL:
        gap_years = sorted(y for (uu, y) in excluded if uu == u)
        if gap_years:
            for y in YEARS:
                if y > gap_years[-1]:
                    add(u, y, "all", "POST_GAP_SCOPE_UNVERIFIED",
                        f"First years after excluded/missing years {gap_years}; compare with the pre-gap series with care.",
                        "caution")

    con.sql("CREATE TABLE comparability_flags(unitid VARCHAR, year INTEGER, domain VARCHAR, flag_code VARCHAR, "
            "severity VARCHAR, detail VARCHAR)")
    con.executemany("INSERT INTO comparability_flags VALUES (?, ?, ?, ?, ?, ?)", flags)

    # ------------------------------------------------------------- reconciliation tables
    con.sql("CREATE TABLE published_reconciliation(file VARCHAR, member VARCHAR, fall_year INTEGER, variable VARCHAR, "
            "published_sum DOUBLE, parsed_sum DOUBLE, published_n BIGINT, parsed_n BIGINT)")
    con.executemany("INSERT INTO published_reconciliation VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    [tuple(r.values()) for r in recon])
    con.sql("""
      CREATE TABLE panel_total_reconciliation AS
      WITH o AS (SELECT unitid, year, sum(headcount) AS s_all,
                        sum(headcount) FILTER (WHERE ftpt = 'full_time') AS s_ft,
                        sum(headcount) FILTER (WHERE ftpt = 'part_time') AS s_pt FROM fact_staff_occupation GROUP BY 1, 2),
           t AS (SELECT unitid, year, sum(fulltime_instructional_headcount) AS s_is FROM fact_faculty_tenure GROUP BY 1, 2),
           n AS (SELECT unitid, year, sum(fulltime_new_hires) AS s_nh FROM fact_new_hires GROUP BY 1, 2),
           p AS (SELECT unitid, year, sum(fulltime_staff) AS s_nis_n, sum(salary_outlays) AS s_nis_out
                 FROM fact_noninstructional_pay GROUP BY 1, 2)
      SELECT tot.unitid, tot.year,
             tot.published_grand_total, o.s_all AS sum_groups_all,
             tot.published_full_time, o.s_ft AS sum_groups_full_time,
             tot.published_part_time, o.s_pt AS sum_groups_part_time,
             it.published_fulltime_instructional, t.s_is AS sum_tenure_status,
             nt.published_fulltime_new_hires, n.s_nh AS sum_new_hire_groups,
             nis.published_n AS published_noninstructional_n, p.s_nis_n AS sum_noninstructional_n,
             nis.published_outlays AS published_noninstructional_outlays, p.s_nis_out AS sum_noninstructional_outlays
      FROM fact_staff_totals tot
      LEFT JOIN o USING (unitid, year) LEFT JOIN t USING (unitid, year) LEFT JOIN _is_total it USING (unitid, year)
      LEFT JOIN n USING (unitid, year) LEFT JOIN _nh_total nt USING (unitid, year)
      LEFT JOIN p USING (unitid, year) LEFT JOIN _nis_total nis USING (unitid, year)
    """)

    # ------------------------------------------------------------- write parquet
    outputs = ["dim_institution_year", "fact_staff_occupation", "fact_staff_totals", "fact_faculty_tenure",
               "fact_new_hires", "fact_faculty_salary", "fact_noninstructional_pay", "fact_enrollment",
               "fact_institution_metrics", "cpi_academic_year", "national_occupation_share", "soc_break_test",
               "salary_method_bridge_2016", "comparability_flags", "published_reconciliation",
               "panel_total_reconciliation"]
    meta = {}
    for name in outputs:
        out = ART / f"{name}.parquet"
        con.sql(f"COPY (SELECT * FROM {name}) TO '{out}' (FORMAT parquet, COMPRESSION zstd)")
        n = con.sql(f"SELECT count(*) FROM {name}").fetchall()[0][0]
        cols = [c[0] for c in con.sql(f"DESCRIBE {name}").fetchall()]
        meta[name] = {"rows": n, "columns": cols}
        print(f"  {name:<32} {n:>7,} rows")

    payload = build_chart_payload(con, cpi_ok)
    (ART / "peer_trends.json").write_text(json.dumps(payload, separators=(",", ":")))
    (MANIFESTS / "build_manifest.json").write_text(json.dumps({
        "built_at_utc": datetime.now(timezone.utc).isoformat(), "years": YEARS, "real_dollars": cpi_ok,
        "real_dollar_base": BASE_AY if cpi_ok else None, "source_members": sources, "tables": meta}, indent=1) + "\n")
    return 0


# ----------------------------------------------------------------------------- chart payload
def quantile(vals: list[float], q: float) -> float:
    vals = sorted(vals)
    if len(vals) == 1:
        return vals[0]
    pos = (len(vals) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(vals) - 1)
    return vals[lo] + (vals[hi] - vals[lo]) * (pos - lo)


def build_chart_payload(con, cpi_ok: bool) -> dict:
    """Series per metric (x group) with U of I values and the Big Ten peer median / IQR band."""
    metrics = []
    excluded = set(con.sql("SELECT DISTINCT unitid, year FROM comparability_flags WHERE severity = 'exclude'").fetchall())

    def series(metric_id, label, unit, sql, group=None, group_label=None, family=None, note="", soc=False,
               real=False, min_peers=8):
        rows = con.sql(sql).fetchall()  # unitid, year, value
        by_unit: dict[str, dict[int, float]] = {}
        for u, y, v in rows:
            if v is not None and (u, y) not in excluded:
                by_unit.setdefault(u, {})[y] = float(v)
        band = []
        for y in YEARS:
            vals = [by_unit[u][y] for u in PEERS if u in by_unit and y in by_unit[u]]
            if len(vals) >= min_peers:
                band.append({"year": y, "n": len(vals), "p25": round(quantile(vals, .25), 3),
                             "median": round(statistics.median(vals), 3), "p75": round(quantile(vals, .75), 3)})
            else:
                band.append({"year": y, "n": len(vals), "p25": None, "median": None, "p75": None})
        values = {u: [by_unit.get(u, {}).get(y) for y in YEARS] for u in PANEL}
        metrics.append({"id": metric_id, "label": label, "unit": unit, "group": group, "group_label": group_label,
                        "family": family or metric_id, "note": note, "soc_break": soc, "real": real,
                        "values": values, "band": band})

    m = "fact_institution_metrics"
    series("staff_total", "Total staff headcount (excl. graduate assistants)", "count",
           f"SELECT unitid, year, staff_total FROM {m}", soc=False)
    series("fulltime_share", "Full-time share of staff", "pct", f"SELECT unitid, year, fulltime_share_pct FROM {m}")
    series("management_share", "Management share of staff headcount", "pct",
           f"SELECT unitid, year, management_share_pct FROM {m}", soc=True,
           note="IPEDS 'Management' occupation group (FT+PT) / all staff. Classification follows each institution's SOC coding.")
    series("staff_per_100_fte", "Staff per 100 FTE students (12-month FTE)", "ratio",
           f"SELECT unitid, year, staff_per_100_fte12 FROM {m}",
           note="Fall staff headcount / 12-month FTE for the same academic year (EFIA year+1).")
    series("staff_per_100_fall_fte", "Staff per 100 FTE students (fall FTE)", "ratio",
           f"SELECT unitid, year, staff_per_100_fall_fte FROM {m}",
           note="Fall staff headcount / fall FTE (EF fall headcount, IPEDS part-time factors). Sensitivity check.")
    series("mgmt_per_100_fte", "Management staff per 100 FTE students", "ratio",
           f"SELECT unitid, year, management_per_100_fte12 FROM {m}", soc=True)
    series("tenured_share", "Tenured share of full-time instructional staff", "pct",
           f"SELECT unitid, year, tenured_share_pct FROM {m}")
    series("tenure_track_share", "On-tenure-track share of full-time instructional staff", "pct",
           f"SELECT unitid, year, tenure_track_share_pct FROM {m}")
    series("non_tenure_share", "Non-tenure-track share (incl. no faculty status) of FT instructional staff", "pct",
           f"SELECT unitid, year, non_tenure_share_pct FROM {m}")
    series("new_hire_rate_all", "Full-time new hires per 100 full-time staff (all occupations)", "ratio",
           f"SELECT unitid, year, new_hires_per_100_fulltime FROM {m} WHERE year >= 2016",
           note="Full-time permanent hires Nov 1-Oct 31 per 100 full-time staff on Nov 1. Fall 2015 used a 4-month "
                "window and is not shown.")
    for g, lbl, _, nis in GROUPS:
        series(f"share_{g}", "Share of staff headcount by occupation group", "pct",
               f"""WITH x AS (SELECT unitid, year, sum(headcount) FILTER (WHERE group_code = '{g}') AS a, sum(headcount) AS b
                   FROM fact_staff_occupation GROUP BY 1, 2) SELECT unitid, year, round(100.0 * a / nullif(b, 0), 2) FROM x""",
               group=g, group_label=lbl, family="occupation_share", soc=True)
        series(f"nh_{g}", "Full-time new hires per 100 full-time staff, by occupation group", "ratio",
               f"SELECT unitid, year, new_hires_per_100_fulltime FROM fact_new_hires WHERE group_code = '{g}' "
               f"AND fulltime_staff_nov1 >= 20 AND year >= 2016", group=g, group_label=lbl, family="new_hire_rate",
               soc=True, note="12-month hire window (Fall 2016 onward). Shown only where the group has at least 20 "
                              "full-time staff.")
        if nis:
            for real in ((False, True) if cpi_ok else (False,)):
                col = "avg_salary_real" if real else "avg_salary"
                series(f"nis_{g}{'_real' if real else ''}", "Average salary, full-time non-instructional staff", "usd",
                       f"SELECT unitid, year, {col} FROM fact_noninstructional_pay WHERE group_code = '{g}' "
                       f"AND fulltime_staff >= 10", group=g, group_label=lbl, family="noninstructional_pay",
                       soc=True, real=real, note="Shown where the group has at least 10 full-time staff.")
    for code, lbl in RANKS.items():
        for real in ((False, True) if cpi_ok else (False,)):
            col = "avg_9mo_total_real" if real else "avg_9mo_total"
            series(f"fac_{code}{'_real' if real else ''}", "Faculty average salary, 9-month equated", "usd",
                   f"SELECT unitid, year, {col} FROM fact_faculty_salary WHERE arank_code = '{code}' AND n_total >= 10",
                   group=code, group_label=lbl, family="faculty_pay", real=real,
                   note="Full-time instructional staff. 2015 uses 9 x average monthly salary (method bridge in METHODS.md).")
        series(f"ratio_{code}", "Women-to-men raw ratio of average 9-month salary", "ratio_x",
               f"SELECT unitid, year, women_to_men_raw_ratio FROM fact_faculty_salary WHERE arank_code = '{code}' "
               f"AND NOT small_cell", group=code, group_label=lbl, family="pay_ratio",
               note="Unadjusted ratio of group averages (no controls for field, rank tenure, or experience). "
                    "Not a pay-equity finding.")

    flags = con.sql("""SELECT unitid, year, domain, flag_code, severity, detail FROM comparability_flags
                       WHERE flag_code NOT IN ('SOC2018_CATEGORY_BASIS', 'EQ9_METHOD_2015', 'NTT_CONTRACT_DETAIL_2016',
                                               'NEW_HIRE_WINDOW_2015',
                                               'PANDEMIC_PERIOD', 'SMALL_CELL_SEX_RATIO', 'NO_STUDENT_FTE')
                       ORDER BY unitid, year""").fetchall()
    soc = con.sql("SELECT * FROM soc_break_test").fetchall()
    soc_cols = [c[0] for c in con.sql("DESCRIBE soc_break_test").fetchall()]
    return {
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "years": YEARS, "soc_break_year": SOC2018_FIRST_YEAR, "real_base": BASE_AY if cpi_ok else None,
        "institutions": {u: {"name": s, "role": r} for u, (s, r) in PANEL.items()},
        "peers": PEERS, "uofi": UOFI, "metrics": metrics,
        "flags": [dict(zip(["unitid", "year", "domain", "code", "severity", "detail"], f)) for f in flags],
        "soc_break_test": [dict(zip(soc_cols, r)) for r in soc],
    }


if __name__ == "__main__":
    sys.exit(main())
