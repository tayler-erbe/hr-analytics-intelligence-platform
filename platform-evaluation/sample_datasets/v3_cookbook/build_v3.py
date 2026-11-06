"""Build the v3 Cookbook-shaped synthetic sample pack from the frozen v2 pack (deterministic).

    cd platform-evaluation
    python sample_datasets/v3_cookbook/build_v3.py            # writes longitudinal/ and CLEAN/
    python sample_datasets/v3_cookbook/build_v3.py --check    # rebuild in a temp dir, compare content hashes

Every row is SYNTHETIC. Nothing here comes from EDW rows. The five tables transcribed from the University
of Illinois Data Cookbook (integration/edw_cookbook_reference/*.tsv) are reproduced column for column, in
Cookbook order, with Oracle types mapped to DuckDB types:

    T_JOB_DETL_HIST (79)  T_EMPEE_HIST (71)  T_EMPEE_HIST_5 (27)  T_POSN_HIST (52)
    T_PERS_HIST (62)      T_PAYR_ACCTG_DETL (47)

Other tables (T_POSN_CLS_HIST, REF_ORG, REF_ROLE_FAMILY, REF_EMPEE_CLS, REF_HIERARCHY_ROOT, REF_ECLS_PUBLIC)
keep their v2 names and values, with keys moved to the v3 identifiers, plus REF_PCLS_SUCSS_XWALK (synthetic
P-Class -> SUCSS crosswalk, fallback bridge). See README.md for every rule and every synthetic value list.

"Random" choices use a stable MD5-based fraction of a text key (h01), so rebuilds are byte-identical.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

import duckdb
import yaml

HERE = Path(__file__).resolve().parent
PE_ROOT = HERE.parents[1]
V2 = PE_ROOT / "sample_datasets" / "v2_public_schema"
COOKBOOK = PE_ROOT / "integration" / "edw_cookbook_reference"
DOMAINS = PE_ROOT / "integration" / "edw_public_reference" / "code_domains.yaml"
SETS = ["longitudinal", "CLEAN"]
OPEN_END = "9999-12-31"
VERIFIED_TABLES = ["T_JOB_DETL_HIST", "T_EMPEE_HIST", "T_EMPEE_HIST_5", "T_POSN_HIST", "T_PERS_HIST", "T_PAYR_ACCTG_DETL"]

# Extract ("today") date per set. longitudinal postings run to 2027-01-24, so its extract is after them;
# CLEAN keeps v1's 2026-10-31 so its December 2026 rows are future-dated.
EXTRACT = {"longitudinal": "2027-01-31", "CLEAN": "2026-10-31"}
# Synthetic EDW_PERS_ID: 9 digits beginning 99 (NUMBER(9)); 991xxxxxx longitudinal, 992xxxxxx CLEAN.
PERS_BASE = {"longitudinal": 991_000_000, "CLEAN": 992_000_000}
PERS_PREFIX = {"longitudinal": "SYN", "CLEAN": "SP"}

# Planted shares (documented in README.md)
SHARE_JOB_DELETED = 0.006       # job lineages that get a keyed-in-error row later deleted (D)
SHARE_EMPEE_DELETED = 0.005     # employee rows duplicated with a wrong effective date, then deleted (D)
SHARE_LEAVE = 0.03              # people given one leave of absence (status B or F)
SHARE_GRANT_AP = 0.35           # academic-professional positions paid from a grant
SHARE_GRANT_GA = 0.25           # graduate-assistant positions paid from a grant
SHARE_PAYROLL_VOID = 0.003      # earnings rows voided and reissued (V + I)
SHARE_PAYROLL_ADJ = 0.003       # earnings rows keyed high and corrected by a J row
SHARE_PAYROLL_ENC = 0.003       # encumbrance + liquidation pairs

# ----------------------------------------------------------------------------- code lists
# Each list says whether its values are Cookbook-listed (verified), public (code_domains.yaml) or synthetic.
JOB_STATUS_DESC = {"A": "Active", "T": "Terminated"}                       # public: rc2009 'Terminated'
EMPEE_STATUS = {"A": "Active", "B": "Leave w/o Pay with Benefits",          # Cookbook examples A/B/F
                "F": "Leave with Pay with Benefits", "T": "Terminated"}     # T: synthetic, unconfirmed
POSN_STATUS = {"A": "Active", "C": "Cancelled", "F": "Frozen", "I": "Inactive"}   # Cookbook-listed
TIME_ENTRY = {"P": "Payroll", "W": "Web", "D": "Departmental", "T": "Third Party"}  # Cookbook-listed
LEAVE_RPT = {"P": "None", "W": "Leave Report on the Web", "D": "Departmental Leave Report",
             "T": "Third Party Leave Report"}                                    # Cookbook-listed
WORK_LOCN = {"1": "No Remote", "2": "All Remote In State", "3": "All Remote Out of State",
             "4": "Hybrid in State", "5": "Hybrid Out of State"}   # 1/3/4 Cookbook examples; 2/5 synthetic
EEO_SKILL = {"12": "Execute/Admin and Managerial", "22": "Faculty", "23": "Other Academics",  # Cookbook
             "30": "Other Professional (synth)", "40": "Tech/Paraprofessional (synth)"}
GROUP_1 = {"A": "Faculty", "B": "Academic Professional", "C": "Civil Service",              # Cookbook
           "G": "Grads and Pre Doc Fellows"}                                                 # G desc public kb heading
EMPEE_GROUP_4 = {"CA": ("CS", "Civil Service"), "BA": ("AP", "Academic Professionals"),       # synthetic
                 "AA": ("FA", "Faculty"), "GA": ("GA", "Graduate Assistants")}
PAYR = {"BW": ("Biweekly", 26), "MO": ("Monthly", 12)}                                       # public kb120369
CHG = {  # job change reasons (public kb120563 unless marked synthetic)
    "HR001": "New Hire", "HR002": "Rehire", "EJ001": "End Job", "EJ002": "Employee Resignation",
    "SP003": "Retired", "OT010": "Promotion (CS)", "FA002": "Faculty Promotion",
    "RC001": "Reclassification (CS)", "RC003": "Reassignment (CS)", "OT009": "Campus Transfer",
    "OT012": "Lateral Transfer (CS)", "OT013": "Department Org Change", "FT001": "FTE Change",
    "SA001": "Pay Change (synthetic code)", "JB001": "Add Job (synthetic code)",
    "PR001": "AP Promotion (synthetic code)", "RA001": "Reactivation (synthetic code)",
}
CHG_SYNTHETIC = {"SA001", "JB001", "PR001", "RA001"}
TERM_TO_CHG = {"TQ": "EJ002", "TR": "SP003", "TE": "EJ001"}
TERM_DESC = {"TQ": "Employee Resigned", "TR": "Retired", "TE": "Terminated/Expired", "TF": "Federal Retired"}
LOA_REASON = {"FM": "Family/Medical Leave (synth)", "PL": "Personal Leave (synthetic)",
              "ML": "Military Leave (synthetic)", "SB": "Sabbatical (synthetic)"}       # synthetic codes
BNFT = {"CA": ("B1", "Ben eligible biweekly (synth)"), "BA": ("M1", "Ben eligible monthly (synth)"),
        "AA": ("M1", "Ben eligible monthly (synth)"), "GA": ("M4", "Not ben eligible (synth)")}
CHART = {"U0": ("9", "System Offices"), "U1": ("1", "Urbana/Champaign"), "U2": ("2", "Chicago"),
         "U3": ("4", "Springfield")}                                 # COA codes public (kb118751); tree synthetic
OPEN_RANGE = {"1": "EA", "2": "CA", "4": "DA", "9": "EA"}            # public open-range tables by campus
SEX = {"F": "Female", "M": "Male"}
GENDER = {"F": ("W", "Woman (synthetic code)"), "M": ("M", "Man (synthetic code)"), "N": ("NB", "Nonbinary (synthetic code)")}
RACE_RPT = {"U": "Unknown", "9": "International", "H": "Hispanic or Latino", "M": "Two or More Races",
            "1": "American Indian or Alaska Native", "2": "Asian", "3": "Black or African American",
            "4": "Native Hawaiian or Other Pacific Islander", "5": "White"}          # Cookbook codes
RACE_IPEDS_DESC = {k: {"1": "American Indian/Alaska Native", "4": "Native Hawaiian/Pac Islander",
                       "3": "Black/African American"}.get(k, v)[:30] for k, v in RACE_RPT.items()}   # VARCHAR2(30)
RACE_IND = {"1": "AIAN_RACE_IND", "2": "ASIAN_RACE_IND", "3": "BLACK_RACE_IND", "4": "NHPI_RACE_IND", "5": "WHITE_RACE_IND"}
V2_RACE = {"G1": "5", "G2": "3", "G3": "H", "G4": "2"}               # synthetic: v1 group -> reporting code
CITZN = {"CZ": ("US Citizen (synthetic code)", "Domestic"), "PR": ("Permanent Resident (synthetic)", "Domestic"),
         "NR": ("Nonresident Alien", "International"), "RA": ("Resident Alien", "International"),
         "AS": ("Asylee", "International"), "UC": ("Unknown Citizenship", "Not Reported")}  # NR/RA/AS/UC Cookbook
VETERAN = {"N": "Not a Veteran (synthetic code)", "P": "Protected Veteran (synthetic code)",
           "O": "Other Veteran (synthetic code)"}
FUNDING = {"STATE": ("State Appropriations", "1"), "LOCAL": ("Local Funds", "2"), "GRANT": ("Grant", "4")}
PAYR_EVENT = {"C": "Original", "V": "Void", "M": "Manual", "I": "Reissued", "J": "Adjusted", "R": "Redistribute"}

# Local (non-SUCSS) P-Class career ladders: (progression group, level). v2 local P-Classes.
LOCAL_LADDER = {
    "RAJAA": ("AP", 1), "SAMBA": ("AP", 1), "SACBA": ("AP", 1), "TAMTA": ("AP", 1), "RALGA": ("AP", 1),
    "NFJAA": ("AP", 2), "NEPDA": ("AP", 3), "NAAAA": ("AP", 4), "LEJAA": ("AP", 5), "LAAAA": ("AP", 6),
    "BAEAA": ("FAC", 1), "BEEAA": ("FAC", 1), "AACAA": ("FAC", 2), "AABAA": ("FAC", 3), "AAAAA": ("FAC", 4),
    "AAAEA": ("FAC", 5), "CASAA": ("GA", 1),
}
ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8}


def h01(key: str) -> float:
    return int(hashlib.md5(key.encode()).hexdigest()[:8], 16) / 2 ** 32


def q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def lit(v) -> str:
    return "NULL" if v is None else "'" + str(v).replace("'", "''") + "'"


def case(expr: str, mapping: dict, default: str = "NULL") -> str:
    if not mapping:
        return default
    return "CASE " + " ".join(f"WHEN {expr} = {lit(k)} THEN {lit(v)}" for k, v in mapping.items()) + f" ELSE {default} END"


# ----------------------------------------------------------------------------- Cookbook specs
def oracle_to_duckdb(dt: str) -> tuple[str, int | None]:
    """Oracle datatype -> (DuckDB type, VARCHAR max length).

    NUMBER(p,0) -> INTEGER (p<=9) | BIGINT (p<=18) | DECIMAL(p,0); NUMBER(p,s) -> DECIMAL(p,s);
    bare NUMBER -> DOUBLE; VARCHAR2(n) -> VARCHAR (length n enforced by tests); DATE -> DATE.
    """
    m = re.fullmatch(r"(NUMBER|VARCHAR2|DATE)(?:\((\d+)(?:,(\d+))?\))?", dt.strip())
    if not m:
        raise ValueError(f"unknown Oracle type {dt}")
    kind, p, s = m.group(1), m.group(2), m.group(3)
    if kind == "DATE":
        return "DATE", None
    if kind == "VARCHAR2":
        return "VARCHAR", int(p)
    if p is None:
        return "DOUBLE", None
    p, s = int(p), int(s or 0)
    if s == 0:
        return ("INTEGER" if p <= 9 else "BIGINT" if p <= 18 else f"DECIMAL({p},0)"), None
    return f"DECIMAL({p},{s})", None


def cookbook_spec(table: str) -> list[dict]:
    with open(COOKBOOK / f"{table}.tsv", encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh, delimiter="\t"))
    out = []
    for r in rows:
        t, n = oracle_to_duckdb(r["datatype"])
        out.append({"ordinal": int(r["ordinal"]), "name": r["column"], "oracle_type": r["datatype"],
                    "type": t, "max_length": n, "pk": r["pk"] == "Y"})
    return out


def eclass_domain() -> dict:
    dom = yaml.safe_load(DOMAINS.read_text(encoding="utf-8"))["e_class"]
    out = {}
    for group, codes in dom["groups"].items():
        for code, d in codes.items():
            out[code] = {"desc": d["desc"], "leave": str(d["leave_category"]), "group": group,
                         "job_end": str(d["job_end_date"])}
    return out


def p_function_titles() -> dict:
    dom = yaml.safe_load(DOMAINS.read_text(encoding="utf-8"))["p_class"]
    return dom["academic_professional"]["positions"]["3"]["values"]


# ----------------------------------------------------------------------------- helpers
def stem_level(title: str) -> tuple[str, int]:
    """SUCSS series stem and level from a class title ('Accountant II' -> ('Accountant', 2))."""
    t = re.sub(r"\s*\(.*?\)\s*$", "", title.strip())
    m = re.match(r"^(.*?)[\s,]+(I{1,3}|IV|V|VI{0,3}|\d)$", t)
    if m:
        lv = ROMAN.get(m.group(2)) or (int(m.group(2)) if m.group(2).isdigit() else 1)
        return m.group(1).strip(), lv
    return t, 1


def materialize(con, stage: str, table: str, spec: list[dict]) -> None:
    """Create `table` with exactly the Cookbook columns, in order and type, from staging relation `stage`."""
    have = {r[0] for r in con.execute(f"DESCRIBE SELECT * FROM {stage}").fetchall()}
    want = [c["name"] for c in spec]
    extra = sorted(c for c in have if c not in want and not c.startswith("_"))
    if extra:
        raise RuntimeError(f"{table}: staging has columns not in the Cookbook: {extra}")
    sel = []
    for c in spec:
        src = q(c["name"]) if c["name"] in have else "NULL"
        sel.append(f"CAST({src} AS {c['type']}) AS {q(c['name'])}")
    pk = [q(c["name"]) for c in spec if c["pk"]]
    con.execute(f"CREATE OR REPLACE TABLE {q(table)} AS SELECT {', '.join(sel)} FROM {stage} ORDER BY {', '.join(pk)}")
    for c in spec:
        if c["max_length"]:
            mx = con.execute(f"SELECT coalesce(max(length({q(c['name'])})), 0) FROM {q(table)}").fetchone()[0]
            if mx > c["max_length"]:
                raise RuntimeError(f"{table}.{c['name']}: value length {mx} exceeds VARCHAR2({c['max_length']})")


# ----------------------------------------------------------------------------- build one set
class SetBuilder:
    def __init__(self, set_name: str, out_dir: Path, xw: list[dict]):
        self.s = set_name
        self.out = out_dir
        self.xw = xw
        self.X = EXTRACT[set_name]
        self.rec = set_name == "longitudinal"       # v2 longitudinal has recorded-version columns
        self.ecls = eclass_domain()
        self.notes: dict = {}

    def x(self, change, **kw):
        row = {"set": self.s, "change": change, "v2_table": "", "v2_column": "", "v3_table": "", "v3_column": "",
               "v2_value": "", "v3_value": "", "rule": "", "status": ""}
        row.update({k: ("" if v is None else str(v)) for k, v in kw.items()})
        self.xw.append(row)

    # ------------------------------------------------------------------ setup
    def setup(self):
        self.out.mkdir(parents=True, exist_ok=True)
        self.db = self.out / "sample.duckdb"
        if self.db.exists():
            self.db.unlink()
        con = duckdb.connect(str(self.db))
        con.create_function("h01", h01, ["VARCHAR"], "DOUBLE")
        src = V2 / self.s
        self.v2_tables = sorted(p.stem for p in src.glob("*.parquet"))
        for t in self.v2_tables:
            con.execute(f"CREATE TEMP VIEW v2_{t} AS SELECT * EXCLUDE (file_row_number) FROM read_parquet({lit((src / (t + '.parquet')).as_posix())})"
                        if "file_row_number" in [r[0] for r in con.execute(f"DESCRIBE SELECT * FROM read_parquet({lit((src / (t + '.parquet')).as_posix())})").fetchall()]
                        else f"CREATE TEMP VIEW v2_{t} AS SELECT * FROM read_parquet({lit((src / (t + '.parquet')).as_posix())})")
        self.con = con
        X = self.X
        cur = "ROW_REC_END_DT >= DATE '9999-12-31'" if self.rec else "TRUE"
        self.cur = cur
        # ID maps
        pre, base = PERS_PREFIX[self.s], PERS_BASE[self.s]
        con.execute(f"""CREATE TEMP TABLE pmap AS
            SELECT DISTINCT v2_id, {base} + CAST(regexp_extract(v2_id, '([0-9]+)$', 1) AS INTEGER) AS pid FROM (
                SELECT EDW_PERS_ID AS v2_id FROM v2_T_PERS_HIST UNION SELECT EDW_PERS_ID FROM v2_T_JOB_DETL_HIST
                UNION SELECT SUPERVISOR_PERS_ID FROM v2_T_JOB_DETL_HIST WHERE SUPERVISOR_PERS_ID IS NOT NULL
                UNION SELECT EDW_PERS_ID FROM v2_T_EMPEE_HIST UNION SELECT EDW_PERS_ID FROM v2_T_EMPEE_HIST_5)""")
        bad = con.execute(f"SELECT count(*) FROM pmap WHERE NOT starts_with(v2_id, '{pre}') OR pid >= {base + 1_000_000}").fetchone()[0]
        if bad or con.execute("SELECT count(*) - count(DISTINCT pid) FROM pmap").fetchone()[0]:
            raise RuntimeError("person id map is not injective / in range")
        con.execute("""CREATE TEMP TABLE posmap AS
            SELECT DISTINCT v2_posn, CASE left(v2_posn, 1) WHEN 'S' THEN 'V' ELSE left(v2_posn, 1) END || lpad(CAST(CAST(substr(v2_posn, 2) AS INTEGER) AS VARCHAR), 5, '0') AS posn FROM (
                SELECT POSN_NBR AS v2_posn FROM v2_T_POSN_HIST UNION SELECT POSN_NBR FROM v2_T_JOB_DETL_HIST)""")
        if con.execute("SELECT count(*) - count(DISTINCT posn), max(length(posn)), max(CAST(substr(v2_posn, 2) AS INTEGER)) FROM posmap").fetchone() != (0, 6, con.execute("SELECT max(CAST(substr(v2_posn, 2) AS INTEGER)) FROM posmap").fetchone()[0]):
            raise RuntimeError("position map is not injective")
        for v2_id, pid in con.execute("SELECT v2_id, pid FROM pmap ORDER BY pid").fetchall():
            self.x("id_mapped", v2_column="EDW_PERS_ID", v3_column="EDW_PERS_ID", v2_value=v2_id, v3_value=pid,
                   rule=f"{base} + numeric part of the v2 id (9 digits, begins 99; synthetic range)", status="synthetic")
        for a, b in con.execute("SELECT v2_posn, posn FROM posmap ORDER BY posn").fetchall():
            self.x("id_mapped", v2_column="POSN_NBR", v3_column="POSN_NBR", v2_value=a, v3_value=b,
                   rule="letter + 5 digits (VARCHAR2(6)); v2 letters Q/R/O kept, S -> V, so no id uses a real campus letter C/S/U/G",
                   status="synthetic")

    # ------------------------------------------------------------------ reference: classes, orgs
    def build_reference(self):
        con = self.con
        # classes: v2 key, P-Class, progression
        rows = con.execute("SELECT POSN_CLS_CD, CLS_SOURCE, POSN_CLS_DESC, MIN_ANNUAL_AMT, MAX_ANNUAL_AMT FROM v2_T_POSN_CLS_HIST ORDER BY 1").fetchall()
        rf = {}
        if "REF_ROLE_FAMILY" in self.v2_tables:
            rf = {r[0]: (r[1], r[2]) for r in con.execute("SELECT CLS_CD, ROLE_FAMILY, ROLE_LEVEL FROM v2_REF_ROLE_FAMILY").fetchall()}
        ap_local = sorted(k for k, src, *_ in rows if src != "SUCSS" and LOCAL_LADDER.get(k, ("", 0))[0] == "AP")
        pape = {k: f"499{i + 1:02d}" for i, k in enumerate(ap_local)}
        if len(pape) > 20:
            raise RuntimeError("more AP classes than PAPE codes 49901-49920")
        recs, groups = [], {}
        for key, src, title, mn, mx in rows:
            pcls = ("Y" + key) if src == "SUCSS" else key
            if key in rf:
                grp, lvl = rf[key][0], int(rf[key][1])
                grp_src = "REF_ROLE_FAMILY role family and level"
            elif src != "SUCSS":
                grp, lvl = LOCAL_LADDER[key]
                grp = {"AP": "AP administration ladder", "FAC": "Faculty rank ladder", "GA": "Graduate assistant"}[grp]
                grp_src = "fixed local ladder (README)"
            else:
                grp, lvl = stem_level(title)
                grp_src = "SUCSS title series stem + roman level"
            groups.setdefault(grp, None)
            ladder = LOCAL_LADDER.get(key, ("CS", 0))[0] if src != "SUCSS" else "CS"
            recs.append((key, src, title, mn, mx, pcls, grp, lvl, grp_src, ladder, pape.get(key)))
        gnames = sorted(groups)
        if len(gnames) > 999:
            raise RuntimeError("too many progression groups for JPnnn")
        gcode = {g: f"JP{i + 1:03d}" for i, g in enumerate(gnames)}
        con.execute("""CREATE TEMP TABLE cls (cls_key VARCHAR, cls_source VARCHAR, cls_title VARCHAR, min_amt DECIMAL(12,2),
                       max_amt DECIMAL(12,2), pcls VARCHAR, prgs_group VARCHAR, prgs_level INTEGER, prgs_source VARCHAR,
                       ladder VARCHAR, pape VARCHAR, prgs_cd VARCHAR)""")
        con.executemany("INSERT INTO cls VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", [r + (gcode[r[6]],) for r in recs])
        for r in recs:
            if r[1] == "SUCSS":
                self.x("value_mapped", v2_table="T_POSN_CLS_HIST", v2_column="POSN_CLS_CD", v3_table="REF_PCLS_SUCSS_XWALK",
                       v3_column="JOB_DETL_POSN_CLS_CD", v2_value=r[0], v3_value=r[5],
                       rule="synthetic P-Class 'Y' + SUCSS code (Y = reserved-for-growth first character; cannot collide with a real P-Class)",
                       status="synthetic_unresolved")
        self.notes["progression_groups"] = len(gnames)
        # REF_ORG with Cookbook-style levels: insert synthetic admin-level-2 units between campus and college.
        org = con.execute("SELECT ORG_CD, PARENT_ORG_CD, ORG_STATUS_CD, ORG_TITLE FROM v2_REF_ORG ORDER BY 1").fetchall()
        new = []
        admin_titles = {"A": "Provost (synthetic)", "B": "VC Admin (synthetic)"}
        for code, parent, st, title in org:
            if parent and parent != "U00" and len(code) == 3 and code != "U00":        # college under a campus
                adm = parent[:2] + ("A" if int(code[2]) % 2 == 1 else "B")
                new.append((code, adm, st, title, 3))
            elif code == "U00":
                new.append((code, None, st, title, 1))
            elif parent == "U00":
                new.append((code, parent, st, title, 1))
            else:
                new.append((code, parent, st, title, 5))
        for camp in sorted({c for c, p, *_ in org if p == "U00"}):
            for k, t in admin_titles.items():
                new.append((camp[:2] + k, camp, "A", f"Campus {camp[1]} {t}", 2))
                self.x("row_added", v3_table="REF_ORG", v3_column="ORG_CD", v3_value=camp[:2] + k,
                       rule=f"synthetic administrative level-2 unit under {camp} (Cookbook org levels: 1 campus, 2 admin, 3 college, 5 department)",
                       status="synthetic")
        con.execute("CREATE TEMP TABLE org (ORG_CD VARCHAR, PARENT_ORG_CD VARCHAR, ORG_STATUS_CD VARCHAR, ORG_TITLE VARCHAR, lvl INTEGER)")
        con.executemany("INSERT INTO org VALUES (?,?,?,?,?)", new)
        # ancestor-or-self path per org (levels 1..8; synthetic tree uses 1,2,3,5)
        con.execute("""CREATE TEMP TABLE orgpath AS
            WITH RECURSIVE w(org, cur, parent, lvl) AS (
                SELECT ORG_CD, ORG_CD, PARENT_ORG_CD, lvl FROM org
                UNION ALL SELECT w.org, o.ORG_CD, o.PARENT_ORG_CD, o.lvl FROM w JOIN org o ON o.ORG_CD = w.parent
                WHERE NOT (w.lvl = 1))
            SELECT org AS ORG_CD,
                   max(cur) FILTER (WHERE lvl = 1) AS L1, max(cur) FILTER (WHERE lvl = 2) AS L2,
                   max(cur) FILTER (WHERE lvl = 3) AS L3, max(cur) FILTER (WHERE lvl = 4) AS L4,
                   max(cur) FILTER (WHERE lvl = 5) AS L5, max(cur) FILTER (WHERE lvl = 6) AS L6,
                   max(cur) FILTER (WHERE lvl = 7) AS L7, max(cur) FILTER (WHERE lvl = 8) AS L8
            FROM w GROUP BY 1""")
        chart_case = case("left(o.ORG_CD, 2)", {k: v[0] for k, v in CHART.items()})
        con.execute(f"""CREATE TEMP TABLE orginfo AS
            SELECT o.ORG_CD, o.ORG_TITLE, o.lvl, p.*  EXCLUDE (ORG_CD), {chart_case} AS coa,
                   t1.ORG_TITLE AS L1_name, t2.ORG_TITLE AS L2_name, t3.ORG_TITLE AS L3_name, t5.ORG_TITLE AS L5_name,
                   'U' || substr(o.ORG_CD, 2, 1) AS hr_campus
            FROM org o JOIN orgpath p USING (ORG_CD)
            LEFT JOIN org t1 ON t1.ORG_CD = p.L1 LEFT JOIN org t2 ON t2.ORG_CD = p.L2
            LEFT JOIN org t3 ON t3.ORG_CD = p.L3 LEFT JOIN org t5 ON t5.ORG_CD = p.L5""")
        # campus names follow the integration layer's synthetic campus assignment (bridges.yaml)
        bridges = yaml.safe_load((PE_ROOT / "integration" / "bridges.yaml").read_text(encoding="utf-8"))
        assign = {b["id"]: b for b in bridges["bridges"]}["org_to_campus"]["params"]["assignment"]
        self.campus_name = {}
        for code, v in assign.items():
            nm = v["label"].replace(" (synthetic assignment)", "")
            self.campus_name[code] = (nm[:24] + " (synthetic)")[:35]
        con.execute("CREATE TEMP TABLE campus_name (L1 VARCHAR, name VARCHAR)")
        con.executemany("INSERT INTO campus_name VALUES (?, ?)", sorted(self.campus_name.items()))
        con.execute("""CREATE OR REPLACE TEMP TABLE orginfo AS SELECT oi.*, cn.name AS campus_name
                       FROM orginfo oi LEFT JOIN campus_name cn USING (L1)""")

    # ------------------------------------------------------------------ jobs
    def build_jobs(self):
        con, X = self.con, self.X
        rec_start = "j.ROW_REC_START_DT" if self.rec else f"least(j.JOB_DETL_EFF_DT, DATE '{X}')"
        con.execute(f"""CREATE TEMP TABLE jb AS
            SELECT pm.pid, ps.posn, j.JOB_SUFFIX AS suf, j.JOB_DETL_EFF_DT AS eff, {rec_start} AS hist_eff,
                   j.JOB_DETL_EXP_DT AS exp, j.JOB_CONTRACT_TYPE_CD AS ctype, j.JOB_DETL_STATUS_CD AS st,
                   j.JOB_DETL_FTE AS fte, j.JOB_DETL_ANNUAL_SAL AS sal, j.POSN_CLS_CD AS cls_key,
                   j.JOB_DETL_EMPEE_CLS_CD AS ecls, j.JOB_ORG_CD AS org, sm.pid AS sup_pid, FALSE AS deleted
            FROM v2_T_JOB_DETL_HIST j JOIN pmap pm ON pm.v2_id = j.EDW_PERS_ID JOIN posmap ps ON ps.v2_posn = j.POSN_NBR
            LEFT JOIN pmap sm ON sm.v2_id = j.SUPERVISOR_PERS_ID""")
        # lineage = PK without JOB_DETL_HIST_EFF_DT
        con.execute("""CREATE OR REPLACE TEMP TABLE jb AS SELECT *,
            lead(hist_eff) OVER (PARTITION BY pid, posn, suf, eff ORDER BY hist_eff) AS next_hist FROM jb""")
        # plant keyed-in-error rows that were deleted 1-3 days later (never spanning a June 30 snapshot date)
        cand = con.execute(f"""SELECT pid, posn, suf, eff, hist_eff, exp FROM jb
            WHERE next_hist IS NULL AND eff BETWEEN DATE '2005-01-01' AND DATE '2025-12-31'
              AND h01('jobdel|{self.s}|' || pid || posn || suf || eff) < {SHARE_JOB_DELETED}
            ORDER BY pid, posn, suf, eff""").fetchall()
        keys = {(r[0], r[1], r[2], r[3], r[4]) for r in con.execute("SELECT pid, posn, suf, eff, hist_eff FROM jb").fetchall()}
        import datetime as _dt
        planted = []
        for pid, posn, suf, eff, hist, exp in cand:
            k = 1 + int(h01(f"jobdelk|{pid}{posn}{eff}") * 5)
            weff = eff + _dt.timedelta(days=k)
            if exp != _dt.date(9999, 12, 31) and weff > exp:
                continue
            post = hist + _dt.timedelta(days=1 + int(h01(f"jobdelp|{pid}{posn}{eff}") * 3))
            if any(_dt.date(y, 6, 30) >= hist and _dt.date(y, 6, 30) < post for y in (hist.year, post.year)):
                continue
            if (pid, posn, suf, weff, hist) in keys:
                continue
            planted.append((pid, posn, suf, eff, weff, hist, post))
        con.execute("CREATE TEMP TABLE jdel (pid INTEGER, posn VARCHAR, suf VARCHAR, base_eff DATE, eff DATE, hist_eff DATE, post DATE)")
        con.executemany("INSERT INTO jdel VALUES (?,?,?,?,?,?,?)", planted)
        self.notes["job_rows_deleted_planted"] = len(planted)
        # current knowledge (latest version of each lineage, not deleted)
        con.execute("CREATE TEMP TABLE jc AS SELECT * EXCLUDE (next_hist, deleted) FROM jb WHERE next_hist IS NULL")
        # change reasons on the current-knowledge chain
        sep = con.execute("SELECT 1").fetchall()
        con.execute("""CREATE TEMP TABLE sep AS SELECT pm.pid, t.TERM_DT AS term_dt, t.TERM_REASON_CD AS term_cd,
                       t.SURS_RETIR_IND AS surs FROM v2_T_EMPEE_HIST_5 t JOIN pmap pm ON pm.v2_id = t.EDW_PERS_ID""" +
                    (f" WHERE t.ROW_REC_END_DT >= DATE '{OPEN_END}'" if self.rec else ""))
        del sep
        con.execute(f"""CREATE TEMP TABLE jcx AS
            WITH a AS (
                SELECT j.*, c.prgs_group, c.prgs_level, c.ladder, o.L1 AS campus,
                       lag(j.st) OVER w AS p_st, lag(j.cls_key) OVER w AS p_cls, lag(j.org) OVER w AS p_org,
                       lag(j.fte) OVER w AS p_fte, lag(j.sal) OVER w AS p_sal, lag(j.eff) OVER w AS p_eff,
                       row_number() OVER (PARTITION BY j.pid ORDER BY j.eff, j.posn, j.suf) AS person_rn
                FROM jc j JOIN cls c ON c.cls_key = j.cls_key JOIN orginfo o ON o.ORG_CD = j.org
                WINDOW w AS (PARTITION BY j.pid, j.posn, j.suf ORDER BY j.eff)),
            spans AS (SELECT pid, posn, suf, min(eff) AS j_start, max(exp) FILTER (WHERE st = 'A') AS j_end_active,
                             max(fte) AS j_fte FROM jc GROUP BY ALL),
            starts AS (
                SELECT a.pid, a.posn, a.suf, a.eff,
                       (SELECT max(s.j_end_active) FROM spans s WHERE s.pid = a.pid AND (s.posn, s.suf) <> (a.posn, a.suf)
                          AND s.j_start < a.eff) AS prior_end,
                       (SELECT count(*) FROM sep WHERE sep.pid = a.pid AND sep.term_dt < a.eff) AS prior_seps
                FROM a WHERE a.p_eff IS NULL),
            mv AS (   -- the job the person left the day before (internal move source)
                SELECT a.pid, a.posn, a.suf, a.eff, p.prgs_group AS f_group, p.prgs_level AS f_level, p.campus AS f_campus,
                       p.cls_key AS f_cls, p.org AS f_org,
                       row_number() OVER (PARTITION BY a.pid, a.posn, a.suf, a.eff ORDER BY p.fte DESC, p.posn, p.suf) AS rn
                FROM a JOIN a p ON p.pid = a.pid AND (p.posn, p.suf) <> (a.posn, a.suf) AND p.st = 'A'
                 AND p.exp = a.eff - INTERVAL 1 DAY
                WHERE a.p_eff IS NULL)
            SELECT a.*, s.prior_end, s.prior_seps, mv.f_group, mv.f_level, mv.f_campus,
                   (SELECT min(t.term_cd) FROM sep t WHERE t.pid = a.pid AND abs(datediff('day', t.term_dt, a.eff)) <= 1) AS term_cd
            FROM a LEFT JOIN starts s USING (pid, posn, suf, eff)
            LEFT JOIN (SELECT * FROM mv WHERE rn = 1) mv USING (pid, posn, suf, eff)""")
        promo = "CASE WHEN ladder = 'FAC' THEN 'FA002' WHEN ladder = 'CS' THEN '{cs}' ELSE 'PR001' END"
        con.execute(f"""CREATE TEMP TABLE jreason AS SELECT pid, posn, suf, eff,
            CASE
              WHEN p_eff IS NULL AND person_rn = 1 AND coalesce(prior_seps, 0) = 0 THEN 'HR001'
              WHEN p_eff IS NULL AND f_group IS NOT NULL THEN
                   CASE WHEN f_group = prgs_group AND prgs_level > f_level THEN {promo.format(cs='OT010')}
                        WHEN f_campus IS DISTINCT FROM campus THEN 'OT009' ELSE 'OT012' END
              WHEN p_eff IS NULL AND (coalesce(prior_seps, 0) > 0 OR prior_end < eff - INTERVAL 1 DAY) THEN 'HR002'
              WHEN p_eff IS NULL THEN 'JB001'
              WHEN p_st = 'A' AND st = 'T' THEN coalesce({case('term_cd', TERM_TO_CHG)}, 'EJ001')
              WHEN p_st = 'T' AND st = 'A' THEN 'RA001'
              WHEN cls_key <> p_cls THEN CASE WHEN prgs_group IS NOT DISTINCT FROM (SELECT c.prgs_group FROM cls c WHERE c.cls_key = p_cls)
                                              AND prgs_level > (SELECT c.prgs_level FROM cls c WHERE c.cls_key = p_cls)
                                              THEN {promo.format(cs='RC001')} ELSE 'RC003' END
              WHEN org <> p_org THEN 'OT013'
              WHEN fte <> p_fte THEN 'FT001'
              WHEN sal <> p_sal THEN 'SA001'
            END AS chg FROM jcx""")
        # supervisor job: supervisor's primary active job on the row's effective date, else latest before, else first
        con.execute("""CREATE TEMP TABLE jsup AS
            WITH need AS (SELECT DISTINCT sup_pid, eff FROM jc WHERE sup_pid IS NOT NULL),
            c AS (SELECT n.sup_pid, n.eff, s.posn, s.suf,
                         row_number() OVER (PARTITION BY n.sup_pid, n.eff ORDER BY
                             CASE WHEN s.st = 'A' AND s.eff <= n.eff AND s.exp >= n.eff THEN 0
                                  WHEN s.eff <= n.eff THEN 1 ELSE 2 END,
                             CASE WHEN s.eff <= n.eff THEN s.fte ELSE 0 END DESC,
                             CASE WHEN s.eff <= n.eff THEN -epoch(s.eff) ELSE epoch(s.eff) END, s.posn, s.suf) AS rn
                  FROM need n JOIN jc s ON s.pid = n.sup_pid)
            SELECT sup_pid, eff, posn AS sup_posn, suf AS sup_suf FROM c WHERE rn = 1""")
        # data expiration date: day before the next effective row of the job (current knowledge), capped at EXP
        con.execute("""CREATE TEMP TABLE jded AS SELECT pid, posn, suf, eff,
                       least(exp, coalesce(CAST(lead(eff) OVER (PARTITION BY pid, posn, suf ORDER BY eff) - INTERVAL 1 DAY AS DATE), DATE '9999-12-31')) AS ded
                       FROM jc""")
        # all rows (versions + planted deletions) with derived status
        X = self.X
        con.execute(f"""CREATE TEMP TABLE jall AS
            SELECT b.pid, b.posn, b.suf, b.eff, b.hist_eff, b.exp, b.ctype, b.st, b.fte, b.sal, b.cls_key, b.ecls, b.org, b.sup_pid,
                   CASE WHEN b.next_hist IS NOT NULL THEN b.next_hist ELSE b.hist_eff END AS post,
                   CASE WHEN b.next_hist IS NOT NULL THEN 'N' WHEN b.eff > DATE '{X}' THEN 'N' WHEN d.ded < DATE '{X}' THEN 'N' ELSE 'Y' END AS cur_ind,
                   CASE WHEN b.next_hist IS NOT NULL THEN 'Expired' WHEN b.eff > DATE '{X}' THEN 'Future'
                        WHEN d.ded < DATE '{X}' THEN 'Expired' ELSE 'Current' END AS dsd,
                   b.next_hist IS NULL AS is_current_version, b.eff AS reason_eff
            FROM jb b LEFT JOIN jded d ON d.pid = b.pid AND d.posn = b.posn AND d.suf = b.suf AND d.eff = b.eff AND b.next_hist IS NULL
            UNION ALL
            SELECT b.pid, b.posn, b.suf, d.eff, d.hist_eff, b.exp, b.ctype, b.st, b.fte, b.sal, b.cls_key, b.ecls, b.org, b.sup_pid,
                   d.post, 'D', 'Deleted', FALSE, b.eff
            FROM jdel d JOIN jc b ON b.pid = d.pid AND b.posn = d.posn AND b.suf = d.suf AND b.eff = d.base_eff""")
        n = con.execute("SELECT count(*) FROM jall").fetchone()[0]
        self.notes["job_rows"] = n

    def stage_jobs(self):
        con = self.con
        ec = self.ecls
        ftitles = p_function_titles()
        ecls_desc = case("j.ecls", {k: v["desc"] for k, v in ec.items()})
        leave_cd = case("j.ecls", {k: v["leave"] for k, v in ec.items()})
        cs = "starts_with(j.ecls, 'C') OR starts_with(j.ecls, 'D')"
        payr = f"CASE WHEN {cs} THEN 'BW' ELSE 'MO' END"
        cnt = f"CASE WHEN {cs} THEN 26 ELSE 12 END"
        fy = "year(j.eff) + CASE WHEN month(j.eff) >= 7 THEN 1 ELSE 0 END"
        eeo_job_group = "CASE WHEN c.cls_source <> 'SUCSS' AND substr(c.pcls, 1, 1) BETWEEN 'E' AND 'U' THEN " + \
            case("substr(c.pcls, 3, 1)", {k: v for k, v in ftitles.items() if len(k) == 1}) + " END"
        eeo = """CASE WHEN starts_with(j.ecls, 'A') THEN '22' WHEN starts_with(j.ecls, 'G') THEN '23'
                      WHEN c.cls_source <> 'SUCSS' AND substr(c.pcls, 1, 1) IN ('E','F','G','H','J','K','L','M','N','P','U') THEN '12'
                      WHEN starts_with(j.ecls, 'B') OR c.cls_source <> 'SUCSS' THEN '30' ELSE '40' END"""
        con.execute(f"""CREATE TEMP TABLE stage_job AS
            SELECT j.pid AS EDW_PERS_ID, j.posn AS POSN_NBR, j.suf AS JOB_SUFFIX, j.eff AS JOB_DETL_EFF_DT,
                   j.hist_eff AS JOB_DETL_HIST_EFF_DT, j.exp AS JOB_DETL_EXP_DT,
                   CASE WHEN j.cur_ind = 'Y' THEN 'Y' ELSE 'N' END AS JOB_DETL_PAYR_CALC_IND,
                   j.cur_ind AS JOB_DETL_CUR_INFO_IND, {case('j.st', JOB_STATUS_DESC)} AS JOB_DETL_STATUS_DESC,
                   c.cls_title AS JOB_DETL_TITLE, j.ecls AS JOB_DETL_EMPEE_CLS_CD, {ecls_desc} AS JOB_DETL_EMPEE_CLS_LONG_DESC,
                   {payr} AS JOB_DETL_PAYR_ID, CASE WHEN {cs} THEN 'Biweekly' ELSE 'Monthly' END AS JOB_DETL_PAYR_ID_DESC,
                   o.coa AS COA_CD, j.org AS ORG_CD, o.coa AS JOB_DETL_CAMPUS_CD, o.campus_name AS JOB_DETL_CAMPUS_NAME,
                   o.L3 AS JOB_DETL_COLL_CD, o.L3_name AS JOB_DETL_COLL_NAME, o.L5 AS JOB_DETL_DEPT_CD, o.L5_name AS JOB_DETL_DEPT_NAME,
                   CASE WHEN {cs} THEN {case('o.coa', OPEN_RANGE)} END AS JOB_DETL_SAL_TBL_CD,
                   CASE WHEN c.cls_source = 'SUCSS' THEN c.cls_key END AS JOB_DETL_SAL_GRADE_CD,
                   CAST(NULL AS INTEGER) AS JOB_DETL_SAL_STEP_NBR,
                   j.fte AS JOB_DETL_FTE,
                   round(j.fte * CASE WHEN {cs} THEN 7.5 ELSE 8 END, 2) AS JOB_DETL_DAY_HOURS,
                   round(j.fte * CASE WHEN {cs} THEN 75 ELSE 173.33 END, 2) AS JOB_DETL_PAY_HOURS,
                   CASE WHEN j.fte > 0 THEN round(round(j.sal / {cnt}, 2) / round(j.fte * CASE WHEN {cs} THEN 75 ELSE 173.33 END, 2), 6) END AS JOB_DETL_REGULAR_RT,
                   round(j.sal / {cnt}, 2) AS JOB_DETL_PAY_PERD_SAL, {cnt} AS JOB_DETL_ANNL_PAY_COUNT, j.sal AS JOB_DETL_ANNL_SAL,
                   r.chg AS JOB_DETL_CHG_REASON_CD, {case('r.chg', CHG)} AS JOB_DETL_CHG_REASON_DESC,
                   'FY' || CAST({fy} AS VARCHAR) AS JOB_DETL_SAL_GROUP_CD, 'Fiscal Year ' || CAST({fy} AS VARCHAR) || ' (synthetic)' AS JOB_DETL_SAL_GROUP_DESC,
                   j.eff AS JOB_DETL_PRSNL_EFF_DT,
                   CASE WHEN {cs} THEN 'TimeSheet' WHEN starts_with(j.ecls, 'B') THEN 'Exception Time Only' ELSE 'None' END AS JOB_DETL_TIME_ENTRY_TYPE_DESC,
                   'N' AS JOB_DETL_ONE_TIME_PMT_IND, j.post AS JOB_DETL_HIST_POST_DT, 'Y' AS JOB_DETL_UNIV_AFFL_IND,
                   CAST(100 AS DECIMAL(5,2)) AS JOB_DETL_APPT_PCT, j.dsd AS JOB_DETL_DATA_STATUS_DESC,
                   CASE WHEN j.cur_ind = 'D' OR NOT j.is_current_version THEN j.exp ELSE d.ded END AS JOB_DETL_DATA_EXP_DT,
                   CASE WHEN {cs} THEN 'Open Range' END AS JOB_DETL_SAL_RT_TYPE_DESC,
                   CASE WHEN r.chg = 'SA001' AND strftime(j.eff, '%m-%d') IN ('07-01', '08-16') THEN 'Y' ELSE 'N' END AS JOB_DETL_ANNL_BUDG_IND,
                   {leave_cd} AS JOB_DETL_LEAVE_CATGRY_CD, 'Leave category ' || {leave_cd} || ' (synthetic)' AS JOB_DETL_LEAVE_CATGRY_DESC,
                   o.ORG_TITLE AS JOB_DETL_ORG_TITLE, {eeo} AS JOB_DETL_EEO_SKILL_CD, {case(eeo, EEO_SKILL)} AS JOB_DETL_EEO_SKILL_DESC,
                   {eeo_job_group} AS JOB_DETL_EEO_JOB_GROUP_TITLE,
                   CASE WHEN {cs} THEN 'W' ELSE 'P' END AS TIME_ENTRY_METHOD_CD,
                   CASE WHEN {cs} THEN 'Web' ELSE 'Payroll' END AS TIME_ENTRY_METHOD_DESC, {cnt} AS JOB_DETL_PAYS_YR,
                   o.L6 AS JOB_DETL_SUB_DEPT_LEVEL_6_CD, CAST(NULL AS VARCHAR) AS JOB_DETL_SUB_DEPT_LEVEL_6_NAME,
                   o.L7 AS JOB_DETL_SUB_DEPT_LEVEL_7_CD, CAST(NULL AS VARCHAR) AS JOB_DETL_SUB_DEPT_LEVEL_7_NAME,
                   c.pcls AS JOB_DETL_POSN_CLS_CD, c.cls_title AS JOB_DETL_POSN_CLS_DESC,
                   CASE WHEN {cs} THEN 'Y' ELSE 'N' END AS JOB_DETL_CIV_SVC_IND,
                   j.sup_pid AS SUPV_EDW_PERS_ID, s.sup_posn AS SUPV_POSN_NBR, s.sup_suf AS SUPV_JOB_SUFFIX,
                   o.L2 AS JOB_DETL_ADMIN_LEVEL_2_CD, o.L2_name AS JOB_DETL_ADMIN_LEVEL_2_NAME,
                   left(j.ecls, 1) AS JOB_DETL_EMPEE_GROUP_CD, {case('left(j.ecls, 1)', GROUP_1)} AS JOB_DETL_EMPEE_GROUP_DESC,
                   CASE WHEN j.eff < DATE '2021-07-01' THEN NULL
                        WHEN h01('wl|' || j.pid) < 0.70 THEN '1' WHEN h01('wl|' || j.pid) < 0.92 THEN '4'
                        WHEN h01('wl|' || j.pid) < 0.96 THEN '2' WHEN h01('wl|' || j.pid) < 0.99 THEN '3' ELSE '5' END AS JOB_DETL_WORK_LOCN_CD,
                   CASE WHEN {cs} THEN 'W' WHEN starts_with(j.ecls, 'B') THEN 'D' ELSE 'P' END AS JOB_DETL_LEAVE_RPT_METHOD_CD
            FROM jall j JOIN cls c ON c.cls_key = j.cls_key JOIN orginfo o ON o.ORG_CD = j.org
            LEFT JOIN jreason r ON r.pid = j.pid AND r.posn = j.posn AND r.suf = j.suf AND r.eff = j.reason_eff
            LEFT JOIN jded d ON d.pid = j.pid AND d.posn = j.posn AND d.suf = j.suf AND d.eff = j.eff
            LEFT JOIN jsup s ON s.sup_pid = j.sup_pid AND s.eff = j.reason_eff""")
        con.execute(f"""CREATE OR REPLACE TEMP TABLE stage_job AS SELECT *,
            {case('JOB_DETL_WORK_LOCN_CD', WORK_LOCN)} AS JOB_DETL_WORK_LOCN_DESC,
            {case('JOB_DETL_LEAVE_RPT_METHOD_CD', LEAVE_RPT)} AS JOB_DETL_LEAVE_RPT_METHOD_DESC FROM stage_job""")
        materialize(con, "stage_job", "T_JOB_DETL_HIST", cookbook_spec("T_JOB_DETL_HIST"))
        # job type P/O/S is not on T_JOB_DETL_HIST: kept in a documented side table (not Cookbook-verified)
        con.execute("""CREATE TABLE X_JOB_CONTRACT_TYPE AS
            SELECT DISTINCT pid AS EDW_PERS_ID, posn AS POSN_NBR, suf AS JOB_SUFFIX, ctype AS JOB_CONTRACT_TYPE_CD
            FROM jc ORDER BY ALL""")
        self.x("column_moved", v2_table="T_JOB_DETL_HIST", v2_column="JOB_CONTRACT_TYPE_CD", v3_table="X_JOB_CONTRACT_TYPE",
               v3_column="JOB_CONTRACT_TYPE_CD", rule="job type (P/O/S) is not among the 79 Cookbook columns; kept per job in a side table",
               status="assumed_pending_cookbook")

    # ------------------------------------------------------------------ employee
    def build_employee(self):
        con, X = self.con, self.X
        post = "e.ROW_REC_START_DT" if self.rec else f"least(e.EMPEE_EFF_DT, DATE '{X}')"
        con.execute(f"""CREATE TEMP TABLE eb AS
            SELECT pm.pid, e.EMPEE_EFF_DT AS eff, e.EMPEE_EXP_DT AS exp, e.EMPEE_STATUS_CD AS st, e.EMPEE_CLS_CD AS ecls,
                   e.FIRST_HIRE_DT AS v2_first_hire, e.CUR_HIRE_DT AS v2_cur_hire, e.HOME_ORG_CD AS home_org,
                   e.HR_CAMPUS_CD AS hr_campus, {post} AS post
            FROM v2_T_EMPEE_HIST e JOIN pmap pm ON pm.v2_id = e.EDW_PERS_ID WHERE {self.cur}""")
        n_dropped = con.execute(f"SELECT count(*) FROM v2_T_EMPEE_HIST WHERE NOT ({self.cur})").fetchone()[0]
        self.notes["empee_superseded_versions_dropped"] = n_dropped
        if n_dropped:
            self.x("rows_dropped", v2_table="T_EMPEE_HIST", v3_table="T_EMPEE_HIST", v2_value=n_dropped,
                   rule="superseded recorded versions: T_EMPEE_HIST's key (EDW_PERS_ID, EMPEE_EFF_DT) has no history date, "
                        "so only the version now stored survives; EMPEE_POST_DT records when it was written", status="verified_dictionary")
        # leave of absence: split one long Active row of a few people into A / B|F / A
        import datetime as _dt
        rows = con.execute(f"""SELECT pid, eff, exp FROM eb WHERE st = 'A' AND exp < DATE '9999-12-31' AND exp - eff > 900
                               AND h01('loa|{self.s}|' || pid) < {SHARE_LEAVE}
                               QUALIFY row_number() OVER (PARTITION BY pid ORDER BY eff) = 1 ORDER BY pid""").fetchall()
        rows += con.execute(f"""SELECT pid, eff, DATE '{X}' FROM eb WHERE st = 'A' AND exp >= DATE '9999-12-31'
                               AND DATE '{X}' - eff > 900 AND h01('loa|{self.s}|' || pid) < {SHARE_LEAVE}
                               AND pid NOT IN (SELECT pid FROM eb WHERE st = 'A' AND exp < DATE '9999-12-31' AND exp - eff > 900)
                               ORDER BY pid""").fetchall()
        loa = []
        for pid, eff, end in rows:
            span = (end - eff).days
            start = eff + _dt.timedelta(days=200 + int(h01(f"loas|{pid}") * (span - 600)))
            start = start.replace(day=1)
            length = 60 + int(h01(f"loal|{pid}") * 120)
            stop = start + _dt.timedelta(days=length)
            kind = "F" if h01(f"loak|{pid}") < 0.4 else "B"
            loa.append((pid, eff, start, stop, kind))
        con.execute("CREATE TEMP TABLE loa (pid INTEGER, row_eff DATE, l_from DATE, l_to DATE, kind VARCHAR)")
        con.executemany("INSERT INTO loa VALUES (?,?,?,?,?)", loa)
        self.notes["leave_of_absence_people"] = len(loa)
        con.execute("""CREATE TEMP TABLE e2 AS
            SELECT e.*, NULL::VARCHAR AS loa_kind, NULL::DATE AS l_from, NULL::DATE AS l_to FROM eb e
            WHERE NOT EXISTS (SELECT 1 FROM loa l WHERE l.pid = e.pid AND l.row_eff = e.eff)
            UNION ALL SELECT e.pid, e.eff, CAST(l.l_from - INTERVAL 1 DAY AS DATE), 'A', e.ecls, e.v2_first_hire, e.v2_cur_hire, e.home_org, e.hr_campus, e.post, NULL, NULL, NULL
                FROM eb e JOIN loa l ON l.pid = e.pid AND l.row_eff = e.eff
            UNION ALL SELECT e.pid, l.l_from, l.l_to, l.kind, e.ecls, e.v2_first_hire, e.v2_cur_hire, e.home_org, e.hr_campus, l.l_from, l.kind, l.l_from, l.l_to
                FROM eb e JOIN loa l ON l.pid = e.pid AND l.row_eff = e.eff
            UNION ALL SELECT e.pid, CAST(l.l_to + INTERVAL 1 DAY AS DATE), e.exp, 'A', e.ecls, e.v2_first_hire, e.v2_cur_hire, e.home_org, e.hr_campus,
                             CAST(least(l.l_to + INTERVAL 1 DAY, DATE '""" + X + """') AS DATE), NULL, NULL, NULL
                FROM eb e JOIN loa l ON l.pid = e.pid AND l.row_eff = e.eff""")
        # deleted (D) rows: duplicates of an Active row keyed with a wrong effective date, deleted 1-3 days later
        con.execute(f"""CREATE TEMP TABLE edel AS
            SELECT e.*, e.eff + CAST(1 + floor(h01('edk|' || e.pid || e.eff) * 5) AS INTEGER) AS weff,
                   e.post + CAST(1 + floor(h01('edp|' || e.pid || e.eff) * 3) AS INTEGER) AS dpost
            FROM e2 e WHERE e.st = 'A' AND e.loa_kind IS NULL AND h01('edel|{self.s}|' || e.pid || e.eff) < {SHARE_EMPEE_DELETED}
              AND datediff('day', e.eff, e.exp) > 10""")
        con.execute("DELETE FROM edel WHERE (pid, weff) IN (SELECT pid, eff FROM e2)")
        self.notes["empee_rows_deleted_planted"] = con.execute("SELECT count(*) FROM edel").fetchone()[0]
        # job facts per person
        con.execute("""CREATE TEMP TABLE jact AS SELECT * FROM jc WHERE st = 'A'""")
        con.execute("""CREATE TEMP TABLE pspell AS
            WITH a AS (SELECT pid, eff, exp, max(exp) OVER (PARTITION BY pid ORDER BY eff, exp ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS pmax FROM jact),
            b AS (SELECT *, CASE WHEN pmax IS NULL OR eff > pmax + INTERVAL 1 DAY THEN 1 ELSE 0 END AS new_spell FROM a)
            SELECT pid, eff AS spell_start FROM b WHERE new_spell = 1""")
        con.execute("""CREATE TEMP TABLE pfirst AS SELECT pid, min(eff) AS first_work,
                       min(eff) FILTER (WHERE starts_with(ecls, 'C') OR starts_with(ecls, 'D')) AS first_cs FROM jc GROUP BY 1""")
        X = self.X
        con.execute(f"""CREATE TEMP TABLE eall AS
            SELECT pid, eff, exp, st, ecls, v2_first_hire, v2_cur_hire, home_org, hr_campus, post, loa_kind, l_from, l_to, 'R' AS kind FROM e2
            UNION ALL SELECT pid, weff, exp, st, ecls, v2_first_hire, v2_cur_hire, home_org, hr_campus, dpost, NULL, NULL, NULL, 'D' FROM edel""")
        con.execute(f"""CREATE TEMP TABLE eref AS SELECT *,
            CASE WHEN eff > DATE '{X}' THEN eff ELSE least(exp, DATE '{X}') END AS rdt FROM eall""")
        con.execute("""CREATE TEMP TABLE eroll AS
            SELECT e.pid, e.eff, e.kind, sum(j.fte) FILTER (WHERE j.suf <> 'CE') AS fte,
                   sum(j.sal * 100 / 100.0) FILTER (WHERE j.suf <> 'CE') AS sal
            FROM eref e LEFT JOIN jact j ON j.pid = e.pid AND j.eff <= e.rdt AND j.exp >= e.rdt GROUP BY ALL""")
        con.execute("""CREATE TEMP TABLE eprim AS
            SELECT e.pid, e.eff, e.kind, j.org FROM eref e JOIN jc j ON j.pid = e.pid
            QUALIFY row_number() OVER (PARTITION BY e.pid, e.eff, e.kind ORDER BY
                CASE WHEN j.st = 'A' AND j.eff <= e.rdt AND j.exp >= e.rdt THEN 0 WHEN j.eff <= e.rdt THEN 1 ELSE 2 END,
                CASE WHEN j.eff <= e.rdt AND j.exp >= e.rdt THEN j.fte ELSE 0 END DESC,
                CASE WHEN j.eff <= e.rdt THEN -epoch(j.eff) ELSE epoch(j.eff) END, j.posn, j.suf) = 1""")
        con.execute("""CREATE TEMP TABLE eterm AS SELECT e.pid, e.eff, s.term_dt, s.term_cd FROM eall e JOIN sep s
                       ON s.pid = e.pid AND s.term_dt = e.eff WHERE e.st = 'T' AND e.kind = 'R'""")
        nterm = con.execute("SELECT count(*), (SELECT count(*) FROM sep) FROM eterm").fetchone()
        if nterm[0] != nterm[1]:
            raise RuntimeError(f"terminations not all placed on a T row: {nterm}")
        con.execute("""CREATE TEMP TABLE elast AS SELECT t.pid, t.eff, max(least(j.exp, t.term_dt)) AS last_work
                       FROM eterm t JOIN jact j ON j.pid = t.pid AND j.eff <= t.term_dt GROUP BY ALL""")
        con.execute("CREATE TEMP TABLE pmaxsal AS SELECT pid, max(sal) AS max_sal FROM jc GROUP BY 1")

    def stage_employee(self):
        con, X = self.con, self.X
        ec = self.ecls
        cs = "(starts_with(e.ecls, 'C') OR starts_with(e.ecls, 'D'))"
        con.execute(f"""CREATE TEMP TABLE stage_empee AS
            WITH sp AS (SELECT e.pid, e.eff, e.kind, max(s.spell_start) AS cur_spell, min(s.spell_start) AS first_spell
                        FROM eref e LEFT JOIN pspell s ON s.pid = e.pid AND s.spell_start <= e.rdt GROUP BY ALL)
            SELECT e.pid AS EDW_PERS_ID, e.eff AS EMPEE_EFF_DT, e.exp AS EMPEE_EXP_DT,
                   CASE WHEN e.kind = 'D' THEN 'D' WHEN e.eff <= DATE '{X}' AND e.exp >= DATE '{X}' THEN 'Y' ELSE 'N' END AS EMPEE_CUR_INFO_IND,
                   CASE WHEN e.st = 'T' THEN 'N' ELSE 'Y' END AS ACTIVE_EMPEE_IND,
                   least(e.v2_first_hire, pf.first_work) AS FIRST_HIRE_DT,
                   CASE WHEN sp.cur_spell IS NULL OR sp.cur_spell = sp.first_spell THEN least(e.v2_first_hire, pf.first_work)
                        ELSE sp.cur_spell END AS CUR_HIRE_DT,
                   CASE WHEN sp.cur_spell IS NULL OR sp.cur_spell = sp.first_spell THEN least(e.v2_first_hire, pf.first_work)
                        ELSE sp.cur_spell END AS ADJ_SVC_DT,
                   pf.first_work AS FIRST_WORK_DT, CASE WHEN e.st = 'T' THEN el.last_work END AS LAST_WORK_DT,
                   pf.first_cs AS ORIG_STATUS_HIRE_DT,
                   e.st AS EMPEE_STATUS_CD, {case('e.st', EMPEE_STATUS)} AS EMPEE_STATUS_DESC,
                   e.ecls AS EMPEE_CLS_CD, {case('e.ecls', {k: v['desc'] for k, v in ec.items()})} AS EMPEE_CLS_LONG_DESC,
                   {case('e.ecls', {k: v[0] for k, v in EMPEE_GROUP_4.items()})} AS EMPEE_GROUP_CD,
                   {case('e.ecls', {k: v[1] for k, v in EMPEE_GROUP_4.items()})} AS EMPEE_GROUP_DESC,
                   t.term_cd AS TERMN_REASON_CD, {case('t.term_cd', TERM_DESC)} AS TERMN_REASON_DESC, t.term_dt AS EMPEE_TERMN_DT,
                   {case('e.ecls', {k: v['leave'] for k, v in ec.items()})} AS EMPEE_LEAVE_CATGRY_CD,
                   'Leave category ' || {case('e.ecls', {k: v['leave'] for k, v in ec.items()})} || ' (synthetic)' AS EMPEE_LEAVE_CATGRY_DESC,
                   {case('e.ecls', {k: v[0] for k, v in BNFT.items()})} AS BNFT_CATGRY_CD,
                   {case('e.ecls', {k: v[1] for k, v in BNFT.items()})} AS BNFT_CATGRY_DESC,
                   CASE WHEN e.ecls = 'GA' THEN 'N' ELSE 'Y' END AS BNFT_ELIG_IND,
                   coalesce(e.hr_campus, ho.hr_campus) AS HR_CAMPUS_CD,
                   'HR campus ' || coalesce(e.hr_campus, ho.hr_campus) || ' (synthetic)' AS HR_CAMPUS_NAME,
                   CASE WHEN {cs} THEN 'C' ELSE 'N' END AS FLSA_IND,
                   ho.coa AS COA_CD, ho.ORG_CD AS ORG_CD,
                   po.coa AS EMPEE_CAMPUS_CD, po.campus_name AS EMPEE_CAMPUS_NAME, po.L3 AS EMPEE_COLL_CD, po.L3_name AS EMPEE_COLL_NAME,
                   po.L5 AS EMPEE_DEPT_CD, po.L5_name AS EMPEE_DEPT_NAME,
                   e.post AS EMPEE_POST_DT,
                   CASE WHEN e.kind = 'D' THEN 'Deleted' WHEN e.eff > DATE '{X}' THEN 'Future' WHEN e.exp < DATE '{X}' THEN 'Expired' ELSE 'Current' END AS EMPEE_DATA_STATUS_DESC,
                   e.exp AS EMPEE_DATA_EXP_DT,
                   CASE WHEN t.term_cd IN ('TR', 'TF') OR e.ecls = 'TR' THEN 'Y' ELSE 'N' END AS EMPEE_RET_IND,
                   po.ORG_TITLE AS EMPEE_ORG_TITLE, least(e.v2_first_hire, pf.first_work) AS UNIV_SNRTY_DT,
                   po.L6 AS EMPEE_SUB_DEPT_LEVEL_6_CD, po.L7 AS EMPEE_SUB_DEPT_LEVEL_7_CD,
                   CASE WHEN e.kind <> 'D' AND e.eff <= DATE '{X}' AND e.exp >= DATE '{X}' THEN
                        CASE WHEN e.st = 'T' THEN last_day(el.last_work) ELSE last_day(DATE '{X}' - INTERVAL 1 MONTH) END END AS EMPEE_LAST_PD_DT,
                   coalesce(r.fte, 0) AS EMPEE_FTE, coalesce(round(r.sal, 2), 0) AS EMPEE_ANNL_SAL,
                   po.L2 AS EMPEE_ADMIN_LEVEL_2_CD, po.L2_name AS EMPEE_ADMIN_LEVEL_2_NAME,
                   CASE WHEN t.term_cd = 'TR' THEN mx.max_sal END AS SURS_MAX_ANNL_EARNS_AMT,
                   CASE WHEN t.term_cd = 'TR' THEN round(mx.max_sal * 0.4, 2) END AS SURS_FORTY_PCT_THRSHLD_AMT,
                   CASE e.loa_kind WHEN 'F' THEN CASE WHEN e.ecls = 'AA' THEN 'SB' ELSE 'FM' END
                        WHEN 'B' THEN CASE WHEN h01('loar|' || e.pid) < 0.5 THEN 'FM' WHEN h01('loar|' || e.pid) < 0.85 THEN 'PL' ELSE 'ML' END END AS EMPEE_LEAVE_REASON_CD,
                   e.l_from AS EMPEE_LOA_FROM_DT, e.l_to AS EMPEE_LOA_TO_DT
            FROM eref e
            LEFT JOIN eterm t ON t.pid = e.pid AND t.eff = e.eff AND e.kind = 'R'
            LEFT JOIN elast el ON el.pid = e.pid AND el.eff = e.eff AND e.kind = 'R'
            LEFT JOIN pfirst pf ON pf.pid = e.pid
            LEFT JOIN sp ON sp.pid = e.pid AND sp.eff = e.eff AND sp.kind = e.kind
            LEFT JOIN eroll r ON r.pid = e.pid AND r.eff = e.eff AND r.kind = e.kind
            LEFT JOIN eprim p ON p.pid = e.pid AND p.eff = e.eff AND p.kind = e.kind
            LEFT JOIN orginfo po ON po.ORG_CD = p.org
            LEFT JOIN orginfo ho ON ho.ORG_CD = coalesce(e.home_org, p.org)
            LEFT JOIN pmaxsal mx ON mx.pid = e.pid""")
        con.execute(f"""CREATE OR REPLACE TEMP TABLE stage_empee AS SELECT *,
            {case('EMPEE_LEAVE_REASON_CD', LOA_REASON)} AS EMPEE_LEAVE_REASON_DESC FROM stage_empee""")
        materialize(con, "stage_empee", "T_EMPEE_HIST", cookbook_spec("T_EMPEE_HIST"))
        # T_EMPEE_HIST_5: secured termination table, one row per terminated employee record (same key and values)
        con.execute("""CREATE TEMP TABLE stage_empee5 AS
            SELECT e.EDW_PERS_ID, e.EMPEE_EFF_DT, e.EMPEE_EXP_DT, e.EMPEE_CUR_INFO_IND, e.TERMN_REASON_CD, e.TERMN_REASON_DESC,
                   e.EMPEE_TERMN_DT, e.COA_CD, o.L1 AS CAMPUS_LEVEL_1_CD, o.L2 AS ADMIN_LEVEL_2_CD, o.L3 AS COLL_LEVEL_3_CD,
                   o.L4 AS SCHOOL_SUB_COLL_LEVEL_4_CD, o.L5 AS DEPT_LEVEL_5_CD, o.L6 AS DEPT_SUB_ORG_LEVEL_6_CD,
                   o.L7 AS DEPT_SUB_ORG_LEVEL_7_CD, o.L8 AS DEPT_SUB_ORG_LEVEL_8_CD, e.EMPEE_POST_DT AS EMPEE_5_POST_DT,
                   e.EMPEE_DATA_STATUS_DESC, e.EMPEE_DATA_EXP_DT, e.SURS_ANNUITANT_AFFECT_DT, e.SURS_LAST_HR_REVW_DT,
                   e.SURS_MAX_ANNL_EARNS_AMT, e.SURS_FORTY_PCT_THRSHLD_AMT
            FROM T_EMPEE_HIST e LEFT JOIN orginfo o ON o.ORG_CD = e.ORG_CD WHERE e.TERMN_REASON_CD IS NOT NULL""")
        materialize(con, "stage_empee5", "T_EMPEE_HIST_5", cookbook_spec("T_EMPEE_HIST_5"))

    # ------------------------------------------------------------------ positions
    def stage_positions(self):
        con, X = self.con, self.X
        post = "p.ROW_REC_START_DT" if self.rec else f"least(p.POSN_EFF_DT, DATE '{X}')"
        con.execute(f"""CREATE TEMP TABLE pb AS
            SELECT ps.posn, p.POSN_EFF_DT AS eff, p.POSN_EXP_DT AS exp, p.POSN_STATUS_CD AS st, p.POSN_CLS_CD AS cls_key,
                   p.POSN_ORG_CD AS v2_org, p.POSN_BUDGET_FTE AS bfte, p.POSN_TITLE AS title, {post} AS post,
                   CASE WHEN p.POSN_EFF_DT > DATE '{X}' THEN p.POSN_EFF_DT ELSE least(p.POSN_EXP_DT, DATE '{X}') END AS rdt
            FROM v2_T_POSN_HIST p JOIN posmap ps ON ps.v2_posn = p.POSN_NBR WHERE {self.cur}""")
        con.execute("""CREATE TEMP TABLE pfill AS SELECT b.posn, b.eff, count(j.pid) AS n_filled
                       FROM pb b LEFT JOIN jact j ON j.posn = b.posn AND j.eff <= b.rdt AND j.exp >= b.rdt GROUP BY ALL""")
        con.execute("""CREATE TEMP TABLE pstat AS SELECT b.posn, b.eff,
            CASE WHEN b.st = 'I' AND f.n_filled = 0 AND h01('pst|' || b.posn) < 0.50 THEN 'C'
                 WHEN b.st = 'I' AND f.n_filled = 0 AND h01('pst|' || b.posn) < 0.75 THEN 'F' ELSE b.st END AS st3
            FROM pb b JOIN pfill f USING (posn, eff)""")
        con.execute("""CREATE TEMP TABLE pjobs AS SELECT posn, min(eff) AS first_job, max(exp) AS last_job_end,
                       mode(ecls ORDER BY ecls) AS ecls_mode FROM jc GROUP BY 1""")
        con.execute("""CREATE TEMP TABLE ppool AS SELECT DISTINCT a.posn FROM jact a JOIN jact b
                       ON a.posn = b.posn AND a.pid <> b.pid AND a.eff <= b.exp AND b.eff <= a.exp""")
        con.execute("""CREATE TEMP TABLE psup AS SELECT b.posn, b.eff, j.SUPV_POSN_NBR AS sup_posn
            FROM pb b JOIN T_JOB_DETL_HIST j ON j.POSN_NBR = b.posn AND j.JOB_DETL_CUR_INFO_IND <> 'D'
             AND j.JOB_DETL_EFF_DT <= b.rdt AND j.JOB_DETL_HIST_EFF_DT = (SELECT max(k.JOB_DETL_HIST_EFF_DT) FROM T_JOB_DETL_HIST k
                 WHERE k.EDW_PERS_ID = j.EDW_PERS_ID AND k.POSN_NBR = j.POSN_NBR AND k.JOB_SUFFIX = j.JOB_SUFFIX
                   AND k.JOB_DETL_EFF_DT = j.JOB_DETL_EFF_DT AND k.JOB_DETL_CUR_INFO_IND <> 'D')
            QUALIFY row_number() OVER (PARTITION BY b.posn, b.eff ORDER BY
                CASE WHEN j.JOB_DETL_STATUS_DESC = 'Active' AND j.JOB_DETL_EXP_DT >= b.rdt THEN 0 ELSE 1 END,
                j.JOB_DETL_EFF_DT DESC, j.JOB_DETL_FTE DESC, j.EDW_PERS_ID, j.JOB_SUFFIX) = 1""")
        ec = self.ecls
        ecls = "coalesce(pj.ecls_mode, CASE WHEN c.cls_source = 'SUCSS' THEN 'CA' WHEN c.ladder = 'FAC' THEN 'AA' WHEN c.ladder = 'GA' THEN 'GA' ELSE 'BA' END)"
        cs = f"starts_with({ecls}, 'C')"
        term = "(starts_with(b.posn, 'O') OR c.ladder = 'GA')"
        con.execute(f"""CREATE TEMP TABLE stage_posn AS
            SELECT b.posn AS POSN_NBR, b.eff AS POSN_HIST_EFF_DT, b.exp AS POSN_HIST_EXP_DT,
                   CASE WHEN b.eff <= DATE '{X}' AND b.exp >= DATE '{X}' THEN 'Y' ELSE 'N' END AS POSN_HIST_CUR_INFO_IND,
                   c.pcls AS POSN_CLS_CD, {case('s.st3', POSN_STATUS)} AS POSN_STATUS_DESC, b.title AS POSN_TITLE,
                   min(b.eff) OVER (PARTITION BY b.posn) AS POSN_BGN_DT,
                   CASE WHEN {term} THEN CASE WHEN pj.last_job_end < DATE '9999-12-31' THEN pj.last_job_end
                                              ELSE DATE '{int(X[:4]) + (1 if X[5:] > '05-15' else 0)}-05-15' END END AS POSN_END_DT,
                   CASE WHEN pp.posn IS NOT NULL THEN 'Pooled' ELSE 'Single' END AS POSN_TYPE_DESC,
                   {ecls} AS POSN_EMPEE_CLS_CD, {case(ecls, {k: v['desc'] for k, v in ec.items()})} AS POSN_EMPEE_CLS_LONG_DESC,
                   CASE WHEN {cs} THEN {case('o.coa', OPEN_RANGE)} END AS POSN_SAL_TBL_CD,
                   o.coa AS COA_CD,
                   'FY' || CAST(year(b.eff) + CASE WHEN month(b.eff) >= 7 THEN 1 ELSE 0 END AS VARCHAR) AS POSN_SAL_GROUP_CD,
                   'Fiscal Year ' || CAST(year(b.eff) + CASE WHEN month(b.eff) >= 7 THEN 1 ELSE 0 END AS VARCHAR) || ' (synthetic)' AS POSN_SAL_GROUP_DESC,
                   {case(ecls, {k: v[0] for k, v in EMPEE_GROUP_4.items()})} AS POSN_GROUP_CD,
                   {case(ecls, {k: v[1] for k, v in EMPEE_GROUP_4.items()})} AS POSN_GROUP_DESC,
                   CASE WHEN c.cls_source = 'SUCSS' THEN c.cls_key ELSE c.pape END AS PAPE_CIV_SVC_ID,
                   CASE WHEN c.cls_source = 'SUCSS' THEN c.cls_title WHEN c.pape IS NOT NULL THEN 'PAPE standard title ' || c.pape || ' (synthetic)' END AS PAPE_CIV_SVC_ID_DESC,
                   CASE WHEN {cs} THEN 'N' ELSE 'Y' END AS POSN_EXEMPT_IND,
                   CASE WHEN {cs} THEN 'Y' ELSE 'N' END AS POSN_ACCRUE_SNRTY_IND,
                   c.prgs_cd AS POSN_JOB_PRGS_CD, left(c.prgs_group, 30) AS POSN_JOB_PRGS_DESC,
                   CASE WHEN f.n_filled = 0 THEN 'Y' ELSE 'N' END AS OPEN_POSN_IND, 'N' AS POSN_ONE_TIME_PMT_IND,
                   b.post AS POSN_HIST_POST_DT, c.min_amt AS POSN_MIN_SAL, round((c.min_amt + c.max_amt) / 2, 4) AS POSN_MIDPT_SAL,
                   c.max_amt AS POSN_MAX_SAL, 'Annual' AS POSN_SAL_RANGE_TYPE_DESC,
                   CASE WHEN b.eff > DATE '{X}' THEN 'Future' WHEN b.exp < DATE '{X}' THEN 'Expired' ELSE 'Current' END AS POSN_DATA_STATUS_DESC,
                   b.exp AS POSN_DATA_EXP_DT, CASE WHEN {cs} THEN 'Open Range' END AS POSN_SAL_RT_TYPE_DESC,
                   s.st3 AS POSN_STATUS_CD, CASE WHEN c.cls_source = 'SUCSS' THEN c.cls_key END AS POSN_SAL_GRADE_CD,
                   CAST(b.bfte AS DECIMAL(5,4)) AS POSN_APPT_PCT,
                   least(b.exp, greatest(min(b.eff) OVER (PARTITION BY b.posn),
                         DATE '{X}' - CAST(floor(h01('pdu|' || b.posn) * 3650) AS INTEGER))) AS POSN_DESC_UPDATE_DT,
                   sp.sup_posn AS SUPV_POSN_NBR
            FROM pb b JOIN cls c ON c.cls_key = b.cls_key JOIN pstat s USING (posn, eff) JOIN pfill f USING (posn, eff)
            LEFT JOIN orginfo o ON o.ORG_CD = b.v2_org LEFT JOIN pjobs pj ON pj.posn = b.posn
            LEFT JOIN ppool pp ON pp.posn = b.posn LEFT JOIN psup sp ON sp.posn = b.posn AND sp.eff = b.eff""")
        materialize(con, "stage_posn", "T_POSN_HIST", cookbook_spec("T_POSN_HIST"))
        self.x("column_dropped", v2_table="T_POSN_HIST", v2_column="POSN_ORG_CD",
               rule="T_POSN_HIST has no organization column (Cookbook); the integration layer derives a position's org from its jobs",
               status="verified_dictionary")

    # ------------------------------------------------------------------ persons
    def stage_persons(self):
        con, X = self.con, self.X
        post = "p.ROW_REC_START_DT" if self.rec else f"least(p.PERS_EFF_DT, DATE '{X}')"
        has_demo = self.rec
        sex = "p.SEX_CD" if has_demo else "CASE WHEN h01('sex|' || pm.pid) < 0.52 THEN 'F' ELSE 'M' END"
        base_race = case("p.RACE_ETH_CD", V2_RACE) if has_demo else \
            "CASE WHEN h01('race|' || pm.pid) < 0.62 THEN '5' WHEN h01('race|' || pm.pid) < 0.74 THEN '3' WHEN h01('race|' || pm.pid) < 0.86 THEN 'H' ELSE '2' END"
        con.execute(f"""CREATE TEMP TABLE pr0 AS
            SELECT pm.pid, p.PERS_EFF_DT AS eff, p.PERS_EXP_DT AS exp, p.BIRTH_DT AS bdt, {post} AS post, {sex} AS sex,
                   {base_race} AS base_race, h01('demo|' || pm.pid) AS u, h01('demo2|' || pm.pid) AS u2
            FROM v2_T_PERS_HIST p JOIN pmap pm ON pm.v2_id = p.EDW_PERS_ID WHERE {self.cur}""")
        # citizenship and overrides (documented shares): 3% international, 2% unknown, 3% multi-race,
        # 1% AIAN, 1% NHPI; Hispanic people also carry one race indicator.
        con.execute("""CREATE TEMP TABLE pr1 AS SELECT *,
            CASE WHEN u < 0.01 THEN 'NR' WHEN u < 0.02 THEN 'RA' WHEN u < 0.03 THEN 'AS' WHEN u < 0.05 THEN 'UC'
                 WHEN u < 0.12 THEN 'PR' ELSE 'CZ' END AS citzn,
            CASE WHEN u BETWEEN 0.05 AND 0.08 THEN 'M' WHEN u BETWEEN 0.08 AND 0.09 THEN '1'
                 WHEN u BETWEEN 0.09 AND 0.10 THEN '4' ELSE base_race END AS race_pick FROM pr0""")
        ind = {k: f"CASE WHEN race_pick = '{k}' OR (race_pick = 'M' AND '{k}' IN (CASE WHEN u2 < 0.5 THEN '5' ELSE '3' END, '2')) " \
                  f"OR (race_pick = 'H' AND '{k}' = '5') THEN 'Y' ELSE 'N' END" for k in RACE_IND}
        con.execute(f"""CREATE TEMP TABLE pr2 AS SELECT *,
            CASE WHEN race_pick = 'H' THEN 'Y' ELSE 'N' END AS HISPANIC_ETH_IND,
            {', '.join(f'{v} AS {RACE_IND[k]}' for k, v in ind.items())} FROM pr1""")
        n_races = " + ".join(f"CASE WHEN {c} = 'Y' THEN 1 ELSE 0 END" for c in RACE_IND.values())
        single = " ".join(f"WHEN {c} = 'Y' THEN '{k}'" for k, c in RACE_IND.items())
        rpt = f"""CASE WHEN citzn IN ('AS', 'NR', 'RA') THEN '9' WHEN citzn = 'UC' THEN 'U' WHEN HISPANIC_ETH_IND = 'Y' THEN 'H'
                       WHEN ({n_races}) > 1 THEN 'M' {single} ELSE 'U' END"""
        con.execute(f"""CREATE TEMP TABLE stage_pers AS SELECT
            pid AS EDW_PERS_ID, eff AS PERS_HIST_EFF_DT, exp AS PERS_EXP_DT,
            CASE WHEN eff <= DATE '{X}' AND exp >= DATE '{X}' THEN 'Y' ELSE 'N' END AS PERS_CUR_INFO_IND,
            bdt AS BIRTH_DT, sex AS SEX_CD, {case('sex', SEX)} AS SEX_DESC,
            citzn AS PERS_CITZN_TYPE_CD, {case('citzn', {k: v[0] for k, v in CITZN.items()})} AS PERS_CITZN_TYPE_DESC,
            CASE WHEN u2 < 0.90 THEN 'N' WHEN u2 < 0.95 THEN 'P' ELSE 'O' END AS VETERAN_CLS_CD,
            post AS PERS_HIST_POST_DT,
            CASE WHEN h01('conf|' || pid) < 0.01 THEN 'Y' ELSE 'N' END AS PERS_CONFIDENTIALITY_IND,
            {case('citzn', {k: v[1] for k, v in CITZN.items()})} AS PERS_CITZN_TYPE_GROUP,
            CASE WHEN eff <= DATE '{X}' AND exp >= DATE '{X}' THEN date_diff('year', bdt, DATE '{X}')
                 - CASE WHEN strftime(DATE '{X}', '%m-%d') < strftime(bdt, '%m-%d') THEN 1 ELSE 0 END END AS AGE,
            CASE WHEN eff > DATE '{X}' THEN 'Future' WHEN exp < DATE '{X}' THEN 'Expired' ELSE 'Current' END AS PERS_DSD,
            HISPANIC_ETH_IND, {', '.join(RACE_IND.values())},
            CASE WHEN ({n_races}) > 1 THEN 'Y' ELSE 'N' END AS MULT_RACE_IND,
            {rpt} AS RACE_ETH_RPT_CD,
            CASE WHEN sex = 'F' AND h01('gen|' || pid) < 0.99 THEN 'W' WHEN sex = 'M' AND h01('gen|' || pid) < 0.99 THEN 'M' ELSE 'NB' END AS GENDER_CD
            FROM pr2""")
        con.execute(f"""CREATE OR REPLACE TEMP TABLE stage_pers AS SELECT *,
            {case('VETERAN_CLS_CD', VETERAN)} AS VETERAN_CLS_DESC,
            {case('RACE_ETH_RPT_CD', RACE_RPT)} AS RACE_ETH_RPT_DESC,
            RACE_ETH_RPT_CD AS IPEDS_RACE_ETH_CATGRY, {case('RACE_ETH_RPT_CD', RACE_IPEDS_DESC)} AS IPEDS_RACE_ETH_CATGRY_DESC,
            {case('GENDER_CD', {v[0]: v[1] for v in GENDER.values()})} AS GENDER_DESC FROM stage_pers""")
        materialize(con, "stage_pers", "T_PERS_HIST", cookbook_spec("T_PERS_HIST"))

    # ------------------------------------------------------------------ payroll (CLEAN only, as in v2)
    def stage_payroll(self):
        con = self.con
        if "T_PAYR_ACCTG_DETL" not in self.v2_tables:
            return
        lo, hi = con.execute("SELECT min(PAY_PERIOD_END_DT), max(PAY_PERIOD_END_DT) FROM v2_T_PAYR_ACCTG_DETL").fetchone()
        import datetime as _dt
        periods = []
        for y in range(lo.year, hi.year + 1):
            for mth in range(1, 13):
                end = (_dt.date(y + (mth == 12), mth % 12 + 1, 1) - _dt.timedelta(days=1))
                if lo <= end <= hi:
                    periods.append(("MO", y, mth, end))
            for k in range(1, 27):
                end = _dt.date(y, 12, 31) if k == 26 else _dt.date(y, 1, 1) + _dt.timedelta(days=14 * k - 1)
                if lo <= end <= hi:
                    periods.append(("BW", y, k, end))
        con.execute("CREATE TEMP TABLE pper (payr_id VARCHAR, yr INTEGER, nbr INTEGER, pend DATE)")
        con.executemany("INSERT INTO pper VALUES (?,?,?,?)", periods)
        # job version in force at period end (current knowledge, Active, with pay)
        con.execute("""CREATE TEMP TABLE pay0 AS
            SELECT j.EDW_PERS_ID AS pid, j.POSN_NBR AS posn, j.JOB_SUFFIX AS suf, p.payr_id, p.yr, p.nbr, p.pend,
                   j.JOB_DETL_PAY_PERD_SAL AS amt, j.JOB_DETL_PAY_HOURS AS hrs, j.ORG_CD AS org, j.COA_CD AS coa,
                   j.JOB_DETL_EMPEE_CLS_CD AS ecls, j.JOB_DETL_EMPEE_CLS_LONG_DESC AS ecls_desc
            FROM pper p JOIN T_JOB_DETL_HIST j ON j.JOB_DETL_PAYR_ID = p.payr_id AND j.JOB_DETL_EFF_DT <= p.pend
             AND j.JOB_DETL_EXP_DT >= p.pend AND j.JOB_DETL_STATUS_DESC = 'Active' AND j.JOB_DETL_CUR_INFO_IND <> 'D'
             AND j.JOB_DETL_HIST_EFF_DT = (SELECT max(k.JOB_DETL_HIST_EFF_DT) FROM T_JOB_DETL_HIST k WHERE k.EDW_PERS_ID = j.EDW_PERS_ID
                  AND k.POSN_NBR = j.POSN_NBR AND k.JOB_SUFFIX = j.JOB_SUFFIX AND k.JOB_DETL_EFF_DT = j.JOB_DETL_EFF_DT
                  AND k.JOB_DETL_CUR_INFO_IND <> 'D')
            WHERE j.JOB_DETL_PAY_PERD_SAL > 0""")
        # funding per position (documented shares)
        con.execute(f"""CREATE TEMP TABLE pfund AS SELECT DISTINCT posn, ecls,
            CASE WHEN ecls = 'BA' AND h01('fund|' || posn) < {SHARE_GRANT_AP} THEN 'GRANT'
                 WHEN ecls = 'GA' AND h01('fund|' || posn) < {SHARE_GRANT_GA} THEN 'GRANT'
                 WHEN h01('fund2|' || posn) < 0.6 THEN 'STATE' ELSE 'LOCAL' END AS src,
            'SYNG' || lpad(CAST(1 + CAST(floor(h01('grant|' || posn) * 60) AS INTEGER) AS VARCHAR), 5, '0') AS grant_cd
            FROM pay0""")
        con.execute("CREATE OR REPLACE TEMP TABLE pfund AS SELECT * FROM pfund QUALIFY row_number() OVER (PARTITION BY posn ORDER BY ecls) = 1")
        # events: originals, voids+reissues, keyed-high + J correction, encumbrance + liquidation
        con.execute(f"""CREATE TEMP TABLE pay1 AS
            WITH b AS (SELECT p.*, h01('pv|' || pid || posn || pend) AS u FROM pay0 p)
            SELECT *, 1 AS seq, 'C' AS ev, 'E' AS cat, CASE WHEN u >= {1 - SHARE_PAYROLL_ADJ} THEN amt + 50 ELSE amt END AS a FROM b
            UNION ALL SELECT *, 2, 'V', 'E', -amt FROM b WHERE u < {SHARE_PAYROLL_VOID}
            UNION ALL SELECT *, 3, 'I', 'E', amt FROM b WHERE u < {SHARE_PAYROLL_VOID}
            UNION ALL SELECT *, 2, 'J', 'E', -50 FROM b WHERE u >= {1 - SHARE_PAYROLL_ADJ}
            UNION ALL SELECT *, 4, 'C', 'C', amt FROM b WHERE u BETWEEN 0.5 AND {0.5 + SHARE_PAYROLL_ENC}
            UNION ALL SELECT *, 5, 'C', 'C', -amt FROM b WHERE u BETWEEN 0.5 AND {0.5 + SHARE_PAYROLL_ENC}""")
        con.execute(f"""CREATE TEMP TABLE stage_pay AS SELECT
            CAST(row_number() OVER (ORDER BY pend, pid, posn, suf, seq) AS BIGINT) AS PAYR_ACCTG_TRAN_NBR,
            pid AS EDW_PERS_ID, posn AS POSN_NBR, suf AS JOB_SUFFIX, CAST(yr AS VARCHAR) AS PAYR_YR, payr_id AS PAYR_ID,
            CASE payr_id WHEN 'BW' THEN 'Biweekly' ELSE 'Monthly' END AS PAYR_ACCTG_PAYR_ID_DESC, nbr AS PAYR_NBR, seq AS PAYR_SEQ_NBR,
            CASE WHEN cat = 'E' THEN 'REG' END AS PAYR_ACCTG_EARNS_CD, CASE WHEN cat = 'E' THEN 'Regular Pay (unconfirmed)' END AS PAYR_ACCTG_EARNS_LONG_DESC,
            {case('ev', PAYR_EVENT)} AS PAYR_ACCTG_EVENT_DESC, CASE WHEN cat = 'E' THEN 'REG' ELSE posn END AS PAYR_ACCTG_TRAN_SRC_DESC,
            cat AS PAYR_ACCTG_CATGRY_CD, CASE cat WHEN 'E' THEN 'Earnings' ELSE 'Encumbrance' END AS PAYR_ACCTG_CATGRY_DESC,
            CAST(year(pend) + CASE WHEN month(pend) >= 7 THEN 1 ELSE 0 END AS VARCHAR) AS FY_CD,
            coa AS COA_CD, {case('f.src', {k: v[1] for k, v in FUNDING.items()})} || CASE WHEN f.src = 'GRANT' THEN substr(f.grant_cd, 5, 5) ELSE '99990' END AS FIN_FUND_CD,
            org AS ORG_CD, CASE WHEN starts_with(p.ecls, 'C') THEN '999200' ELSE '999100' END AS FIN_ACCT_CD, '999000' AS FIN_PGM_CD,
            CASE WHEN f.src = 'GRANT' THEN f.grant_cd END AS GRANT_CD,
            {case('f.src', {k: v[0] for k, v in FUNDING.items()})} AS PAYR_ACCTG_FUNDING_SRC_DESC,
            CASE WHEN a < 0 THEN '-' ELSE '+' END AS PAYR_ACCTG_TRAN_SIGN_CD, pend AS PAYR_ACCTG_TRAN_DT, a AS PAYR_ACCTG_AMT,
            CASE WHEN cat = 'E' AND ev IN ('C', 'I') THEN hrs WHEN cat = 'E' AND ev = 'V' THEN -hrs END AS PAYR_ACCTG_HOURS,
            p.ecls AS PAYR_ACCTG_EMPEE_CLS_CD, ecls_desc AS PAYR_ACCTG_EMPEE_CLS_LONG_DESC,
            pend AS PAYR_ACCTG_EFF_DT, pend + INTERVAL 2 DAY AS PAYR_ACCTG_POST_DT, ev AS PAYR_EVENT_TYPE_CD,
            {case('ev', PAYR_EVENT)} AS PAYR_EVENT_TYPE_DESC,
            CASE WHEN cat = 'E' THEN a END AS PAYR_ACCTG_EXPS_AMT, CASE WHEN cat = 'C' THEN a END AS PAYR_ACCTG_ENC_AMT,
            1 AS EDW_VPD_NBR, CAST(900000000 + dense_rank() OVER (ORDER BY pend, payr_id) AS INTEGER) AS EDW_FIN_DOC_ID
            FROM pay1 p JOIN pfund f USING (posn)""")
        materialize(con, "stage_pay", "T_PAYR_ACCTG_DETL", cookbook_spec("T_PAYR_ACCTG_DETL"))
        self.notes["payroll_periods"] = len(periods)

    # ------------------------------------------------------------------ other (v2) tables
    def stage_other(self):
        con = self.con
        con.execute("CREATE TABLE T_POSN_CLS_HIST AS SELECT * FROM v2_T_POSN_CLS_HIST ORDER BY POSN_CLS_CD")
        con.execute("""CREATE TABLE REF_ORG AS SELECT o.ORG_CD, o.PARENT_ORG_CD, o.ORG_STATUS_CD, o.ORG_TITLE,
                       o.lvl AS ORG_HIER_LEVEL_NBR, i.coa AS COA_CD FROM org o JOIN orginfo i USING (ORG_CD) ORDER BY 1""")
        self.x("column_added", v3_table="REF_ORG", v3_column="ORG_HIER_LEVEL_NBR",
               rule="Cookbook org levels (1 campus, 2 admin, 3 college, 4 school, 5 department, 6-8 sub-org); synthetic tree uses 1/2/3/5",
               status="synthetic")
        self.x("column_added", v3_table="REF_ORG", v3_column="COA_CD", rule="chart of the org's campus (U1->1, U2->2, U3->4, U0->9)",
               status="synthetic")
        if "REF_ROLE_FAMILY" in self.v2_tables:
            con.execute("CREATE TABLE REF_ROLE_FAMILY AS SELECT * FROM v2_REF_ROLE_FAMILY ORDER BY CLS_CD")
        if "REF_EMPEE_CLS" in self.v2_tables:
            con.execute("CREATE TABLE REF_EMPEE_CLS AS SELECT * FROM v2_REF_EMPEE_CLS ORDER BY ECLS_CD")
        if "REF_HIERARCHY_ROOT" in self.v2_tables:
            con.execute("""CREATE TABLE REF_HIERARCHY_ROOT AS SELECT ps.posn AS POSN_NBR FROM v2_REF_HIERARCHY_ROOT r
                           JOIN posmap ps ON ps.v2_posn = r.POSN_NBR""")
        con.execute("CREATE TABLE REF_ECLS_PUBLIC AS SELECT * FROM v2_REF_ECLS_PUBLIC ORDER BY EMPEE_CLS_CD")
        con.execute("""CREATE TABLE REF_PCLS_SUCSS_XWALK AS
            SELECT pcls AS JOB_DETL_POSN_CLS_CD, cls_key AS POSN_CLS_CD,
                   CASE WHEN cls_source = 'SUCSS' THEN cls_key END AS SUCSS_CLS_CD, cls_source AS CLS_SOURCE,
                   CASE WHEN cls_source = 'SUCSS' THEN 'synthetic_unresolved' ELSE 'identity_local_class' END AS XWALK_STATUS,
                   prgs_cd AS POSN_JOB_PRGS_CD, prgs_level AS JOB_PRGS_LEVEL_NBR
            FROM cls ORDER BY 1""")
        # legacy-named views (pass-through) for the reporting layer
        con.execute("CREATE VIEW V_JOB_DETL_HIST_1 AS SELECT * FROM T_JOB_DETL_HIST")
        con.execute("CREATE VIEW V_EMPEE_HIST_1 AS SELECT * FROM T_EMPEE_HIST")
        con.execute("CREATE VIEW V_EMPEE_PERS_HIST_1 AS SELECT EDW_PERS_ID, PERS_HIST_EFF_DT, PERS_EXP_DT, PERS_CUR_INFO_IND FROM T_PERS_HIST")

    # ------------------------------------------------------------------ write
    def write(self) -> dict:
        con = self.con
        tables = [r[0] for r in con.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main' AND table_type = 'BASE TABLE' ORDER BY 1").fetchall()]
        manifest = {"set": self.s, "synthetic": True, "source": f"sample_datasets/v2_public_schema/{self.s}",
                    "extract_date": self.X, "tables": {}, "views": ["V_EMPEE_HIST_1", "V_EMPEE_PERS_HIST_1", "V_JOB_DETL_HIST_1"],
                    "notes": self.notes}
        schema = {}
        for t in tables:
            con.execute(f"COPY (SELECT * FROM {q(t)}) TO {lit((self.out / (t + '.parquet')).as_posix())} (FORMAT parquet)")
            n = con.execute(f"SELECT count(*) FROM {q(t)}").fetchone()[0]
            v2n = con.execute(f"SELECT count(*) FROM v2_{t}").fetchone()[0] if t in self.v2_tables else None
            manifest["tables"][t] = {"rows": n, "v2_rows": v2n, "content_sha256": table_hash(con, t),
                                     "cookbook_verified": t in VERIFIED_TABLES}
            schema[t] = column_schema(con, t)
        con.close()
        (self.out / "schema.json").write_text(json.dumps(schema, indent=1) + "\n", encoding="utf-8")
        (self.out / "schema_assumptions.json").write_text(json.dumps(schema, indent=1) + "\n", encoding="utf-8")
        (self.out / "manifest.json").write_text(json.dumps(manifest, indent=1, sort_keys=True, default=str) + "\n", encoding="utf-8")
        return manifest

    def build(self) -> dict:
        self.setup()
        self.build_reference()
        self.build_jobs()
        self.stage_jobs()
        self.build_employee()
        self.stage_employee()
        self.stage_positions()
        self.stage_persons()
        self.stage_payroll()
        self.stage_other()
        return self.write()


def table_hash(con, table: str) -> str:
    h = hashlib.sha256()
    for row in con.execute(f"SELECT * FROM {q(table)} ORDER BY ALL").fetchall():
        h.update(repr(tuple(row)).encode())
    return h.hexdigest()


# ----------------------------------------------------------------------------- schema.json annotations
# value_status per column: cookbook_listed | public_code_domain | synthetic | null_not_synthesized | null_prohibited
# | derived | identifier_synthetic | free_value. Anything not listed below is 'free_value' (dates, amounts, titles).
PROHIBITED_NULL = {
    "T_PERS_HIST": ["UIN", "SSN", "PERS_FNAME", "PERS_MNAME", "PERS_LNAME", "PERS_NAME_SUFFIX", "PERS_MARITAL_STATUS_CD",
                    "PERS_MARITAL_STATUS_DESC", "SEARCH_FNAME", "SEARCH_MNAME", "SEARCH_LNAME", "NON_UIN_UNIQUE_ID",
                    "PERS_PREFERRED_FNAME", "PERS_NAME_PREFIX", "LEGACY_CD", "LEGACY_DESC", "BIRTH_CITY", "BIRTH_STATE_CD",
                    "BIRTH_STATE_NAME", "RACE_VERF_IND", "RACE_VERF_DT", "VISUAL_VERF_IND", "VERIFIER_EDW_PERS_ID",
                    "VISUAL_VERF_DT", "VERIFY_ETH_CHG_IND", "VERIFY_RACE_CHG_IND"],
    "T_EMPEE_HIST": ["E_VERIFY_CASE_NBR", "CASE_NBR_ENTRY_USER_ID", "CASE_NBR_ENTRY_DT", "HIRETOUCH_ID", "E_VERIFY_EFF_DT",
                     "SURS_LAST_UPDATE_CHG_ID", "SURS_ENTR_EDW_PERS_ID", "SURS_ENTR_FULL_NAME", "SURS_UPDATE_NOTE_TXT", "EMPEE_USER_ID"],
    "T_EMPEE_HIST_5": ["SURS_LAST_UPDATE_CHG_ID", "SURS_ENTR_EDW_PERS_ID", "SURS_ENTR_FULL_NAME", "SURS_UPDATE_NOTE_TXT"],
    "T_PAYR_ACCTG_DETL": ["PAYR_ACCTG_BNFT_DED_CD", "PAYR_ACCTG_BNFT_DED_LONG_DESC", "PAYR_ACCTG_DED_TYPE_DESC"],
    "T_JOB_DETL_HIST": ["JOB_DETL_USER_ID", "JOB_DETL_HRFE_TRAN_ID", "JOB_DETL_HRFE_COMPNT_ID"],
}
VALUE_STATUS = {
    "T_JOB_DETL_HIST": {
        "EDW_PERS_ID": "identifier_synthetic", "POSN_NBR": "identifier_synthetic", "SUPV_EDW_PERS_ID": "identifier_synthetic",
        "SUPV_POSN_NBR": "identifier_synthetic", "JOB_SUFFIX": "free_value",
        "JOB_DETL_CUR_INFO_IND": "cookbook_listed", "JOB_DETL_PAYR_CALC_IND": "cookbook_listed",
        "JOB_DETL_DATA_STATUS_DESC": "cookbook_listed", "TIME_ENTRY_METHOD_CD": "cookbook_listed",
        "TIME_ENTRY_METHOD_DESC": "cookbook_listed", "JOB_DETL_LEAVE_RPT_METHOD_CD": "cookbook_listed",
        "JOB_DETL_LEAVE_RPT_METHOD_DESC": "cookbook_listed", "JOB_DETL_TIME_ENTRY_TYPE_DESC": "cookbook_listed",
        "JOB_DETL_WORK_LOCN_CD": "cookbook_listed", "JOB_DETL_WORK_LOCN_DESC": "cookbook_listed_partly_synthetic(2,5)",
        "JOB_DETL_EEO_SKILL_CD": "cookbook_listed_partly_synthetic(30,40)", "JOB_DETL_EEO_SKILL_DESC": "cookbook_listed_partly_synthetic(30,40)",
        "JOB_DETL_EEO_JOB_GROUP_TITLE": "public_code_domain", "JOB_DETL_EMPEE_GROUP_CD": "derived",
        "JOB_DETL_EMPEE_GROUP_DESC": "cookbook_listed_partly_public(G)", "JOB_DETL_CIV_SVC_IND": "derived",
        "JOB_DETL_EMPEE_CLS_CD": "public_code_domain", "JOB_DETL_EMPEE_CLS_LONG_DESC": "public_code_domain",
        "JOB_DETL_PAYR_ID": "public_code_domain", "JOB_DETL_PAYR_ID_DESC": "public_code_domain",
        "COA_CD": "public_code_domain", "JOB_DETL_CAMPUS_CD": "synthetic", "JOB_DETL_CAMPUS_NAME": "synthetic",
        "ORG_CD": "synthetic", "JOB_DETL_COLL_CD": "synthetic", "JOB_DETL_COLL_NAME": "synthetic", "JOB_DETL_DEPT_CD": "synthetic",
        "JOB_DETL_DEPT_NAME": "synthetic", "JOB_DETL_ORG_TITLE": "synthetic", "JOB_DETL_ADMIN_LEVEL_2_CD": "synthetic",
        "JOB_DETL_ADMIN_LEVEL_2_NAME": "synthetic", "JOB_DETL_SAL_TBL_CD": "public_code_domain",
        "JOB_DETL_SAL_GRADE_CD": "synthetic", "JOB_DETL_SAL_GROUP_CD": "synthetic", "JOB_DETL_SAL_GROUP_DESC": "synthetic",
        "JOB_DETL_SAL_RT_TYPE_DESC": "cookbook_listed", "JOB_DETL_CHG_REASON_CD": "public_code_domain_partly_synthetic(SA001,JB001,PR001,RA001)",
        "JOB_DETL_CHG_REASON_DESC": "public_code_domain_partly_synthetic", "JOB_DETL_POSN_CLS_CD": "synthetic_for_sucss_classes;public_rules_for_local",
        "JOB_DETL_POSN_CLS_DESC": "synthetic", "JOB_DETL_TITLE": "public_sucss_title_or_synthetic", "JOB_DETL_STATUS_DESC": "public_code_domain",
        "JOB_DETL_LEAVE_CATGRY_CD": "public_code_domain", "JOB_DETL_LEAVE_CATGRY_DESC": "synthetic",
        "JOB_DETL_ANNL_BUDG_IND": "derived", "JOB_DETL_UNIV_AFFL_IND": "synthetic", "JOB_DETL_ONE_TIME_PMT_IND": "synthetic",
        "JOB_DETL_ANNL_PAY_COUNT": "public_code_domain", "JOB_DETL_PAYS_YR": "public_code_domain",
        "JOB_DETL_FTE": "free_value(fraction 1.000; fraction vs percent UNCONFIRMED)", "JOB_DETL_APPT_PCT": "synthetic(100 on every row)",
        "JOB_DETL_SUB_DEPT_LEVEL_6_CD": "null_not_synthesized", "JOB_DETL_SUB_DEPT_LEVEL_6_NAME": "null_not_synthesized",
        "JOB_DETL_SUB_DEPT_LEVEL_7_CD": "null_not_synthesized", "JOB_DETL_SUB_DEPT_LEVEL_7_NAME": "null_not_synthesized",
        "JOB_DETL_SAL_STEP_NBR": "null_not_synthesized", "JOB_DETL_CNTRCT_NBR": "null_not_synthesized",
        "JOB_DETL_PREM_PAY_CATGRY_CD": "null_not_synthesized", "JOB_DETL_PREM_PAY_CATGRY_DESC": "null_not_synthesized",
    },
    "T_EMPEE_HIST": {
        "EDW_PERS_ID": "identifier_synthetic", "EMPEE_CUR_INFO_IND": "cookbook_listed", "EMPEE_DATA_STATUS_DESC": "cookbook_listed",
        "EMPEE_STATUS_CD": "cookbook_listed(A,B,F);T_synthetic_unconfirmed", "EMPEE_STATUS_DESC": "cookbook_listed;T_synthetic",
        "EMPEE_CLS_CD": "public_code_domain", "EMPEE_CLS_LONG_DESC": "public_code_domain", "EMPEE_GROUP_CD": "synthetic",
        "EMPEE_GROUP_DESC": "synthetic", "TERMN_REASON_CD": "public_code_domain", "TERMN_REASON_DESC": "public_code_domain",
        "EMPEE_RET_IND": "derived(cookbook rule)", "EMPEE_LEAVE_CATGRY_CD": "public_code_domain", "EMPEE_LEAVE_CATGRY_DESC": "synthetic",
        "BNFT_CATGRY_CD": "synthetic", "BNFT_CATGRY_DESC": "synthetic", "BNFT_ELIG_IND": "derived",
        "HR_CAMPUS_CD": "synthetic", "HR_CAMPUS_NAME": "synthetic", "FLSA_IND": "cookbook_listed", "COA_CD": "public_code_domain",
        "ORG_CD": "synthetic", "EMPEE_CAMPUS_CD": "synthetic", "EMPEE_CAMPUS_NAME": "synthetic", "EMPEE_COLL_CD": "synthetic",
        "EMPEE_COLL_NAME": "synthetic", "EMPEE_DEPT_CD": "synthetic", "EMPEE_DEPT_NAME": "synthetic", "EMPEE_ORG_TITLE": "synthetic",
        "EMPEE_ADMIN_LEVEL_2_CD": "synthetic", "EMPEE_ADMIN_LEVEL_2_NAME": "synthetic", "EMPEE_FTE": "derived(sum of active job FTE)",
        "EMPEE_ANNL_SAL": "derived(sum of active job salary x appt pct)", "EMPEE_LEAVE_REASON_CD": "synthetic",
        "EMPEE_LEAVE_REASON_DESC": "synthetic", "WORK_PERD_CD": "null_not_synthesized", "WORK_PERD_DESC": "null_not_synthesized",
        "EMPEE_SUB_DEPT_LEVEL_6_NAME": "null_not_synthesized", "EMPEE_SUB_DEPT_LEVEL_7_NAME": "null_not_synthesized",
        "SURS_ANNUITANT_AFFECT_DT": "null_not_synthesized", "SURS_LAST_HR_REVW_DT": "null_not_synthesized",
        "SURS_MAX_ANNL_EARNS_AMT": "synthetic(TR rows: max job salary)", "SURS_FORTY_PCT_THRSHLD_AMT": "derived(40%)",
    },
    "T_EMPEE_HIST_5": {"EDW_PERS_ID": "identifier_synthetic", "TERMN_REASON_CD": "public_code_domain",
                       "CAMPUS_LEVEL_1_CD": "synthetic", "ADMIN_LEVEL_2_CD": "synthetic", "COLL_LEVEL_3_CD": "synthetic",
                       "SCHOOL_SUB_COLL_LEVEL_4_CD": "null_not_synthesized(no level 4 in the synthetic tree)",
                       "DEPT_LEVEL_5_CD": "synthetic", "DEPT_SUB_ORG_LEVEL_6_CD": "null_not_synthesized",
                       "DEPT_SUB_ORG_LEVEL_7_CD": "null_not_synthesized", "DEPT_SUB_ORG_LEVEL_8_CD": "null_not_synthesized"},
    "T_POSN_HIST": {
        "POSN_NBR": "identifier_synthetic", "SUPV_POSN_NBR": "identifier_synthetic", "POSN_STATUS_CD": "cookbook_listed",
        "POSN_STATUS_DESC": "cookbook_listed", "POSN_HIST_CUR_INFO_IND": "cookbook_listed", "POSN_TYPE_DESC": "cookbook_listed",
        "POSN_CLS_CD": "synthetic_for_sucss_classes;public_rules_for_local", "PAPE_CIV_SVC_ID": "synthetic(SUCSS code for CS; 49901-49920 public PAPE list for AP) VALUE FORMAT TO CONFIRM",
        "PAPE_CIV_SVC_ID_DESC": "public_sucss_title_or_synthetic", "POSN_JOB_PRGS_CD": "synthetic", "POSN_JOB_PRGS_DESC": "synthetic",
        "OPEN_POSN_IND": "derived(job history)", "POSN_EMPEE_CLS_CD": "public_code_domain", "POSN_SAL_TBL_CD": "public_code_domain",
        "POSN_SAL_RT_TYPE_DESC": "cookbook_listed", "POSN_SAL_RANGE_TYPE_DESC": "cookbook_listed", "POSN_GROUP_CD": "synthetic",
        "POSN_APPT_PCT": "free_value(fraction)", "POSN_DESC_UPDATE_DT": "synthetic", "POSN_END_DT": "derived(term positions)",
        "CIPC_CD": "null_not_synthesized", "CIPC_DESC": "null_not_synthesized", "WORK_SCHED_CD": "null_not_synthesized",
        "OCCUP_TITLE_CD": "null_not_synthesized", "POSN_BRGN_UNIT_CD": "null_not_synthesized",
        "POSN_BUDG_PRFL_CD": "null_not_synthesized", "POSN_ROLL_CD": "null_not_synthesized", "POSN_SAL_STEP_NBR": "null_not_synthesized",
    },
    "T_PERS_HIST": {
        "EDW_PERS_ID": "identifier_synthetic", "SEX_CD": "synthetic(restricted_fairness_only)", "GENDER_CD": "synthetic(restricted_fairness_only)",
        "RACE_ETH_RPT_CD": "cookbook_listed(restricted_fairness_only)", "IPEDS_RACE_ETH_CATGRY": "synthetic(restricted_fairness_only)",
        "PERS_CITZN_TYPE_CD": "cookbook_listed(AS,NR,RA,UC);CZ,PR synthetic", "PERS_CITZN_TYPE_GROUP": "cookbook_listed",
        "VETERAN_CLS_CD": "synthetic", "PERS_CONFIDENTIALITY_IND": "synthetic(1% Y)", "AGE": "derived(current rows only)",
        "PERS_DSD": "cookbook_listed", "PERS_CITZN_IND": "null_not_synthesized", "AGE_AT_DEATH": "null_not_synthesized",
        "SPECIAL_DISABLED_VETERAN_IND": "null_not_synthesized", "ARMED_FORCES_SVC_MEDAL_IND": "null_not_synthesized",
        "VETERAN_ACTIVE_DUTY_SEPRTN_DT": "null_not_synthesized", "PERS_PRONOUN_CD": "null_not_synthesized",
        "PERS_PRONOUN_DESC": "null_not_synthesized",
    },
    "T_PAYR_ACCTG_DETL": {
        "PAYR_EVENT_TYPE_CD": "cookbook_listed", "PAYR_ACCTG_CATGRY_CD": "synthetic(E earnings, C encumbrance; letters unconfirmed)",
        "GRANT_CD": "synthetic(SYNGnnnnn)", "PAYR_ACCTG_FUNDING_SRC_DESC": "cookbook_listed", "FIN_FUND_CD": "public_prefix_rule;synthetic",
        "FIN_ACCT_CD": "synthetic", "FIN_PGM_CD": "synthetic", "PAYR_ACCTG_EARNS_CD": "synthetic(REG unconfirmed)",
        "PAYR_ACCTG_EFF_DT": "synthetic(pay-period end; meaning UNCONFIRMED)", "EDW_VPD_NBR": "synthetic(constant 1)",
        "EDW_FIN_DOC_ID": "synthetic", "FIN_ACTV_CD": "null_not_synthesized", "LOCN_CD": "null_not_synthesized",
        "PAYR_ACCTG_RULE_CLS_CD": "null_not_synthesized", "PAYR_ACCTG_RULE_CLS_DESC": "null_not_synthesized",
        "ENC_EDW_FIN_DOC_ID": "null_not_synthesized", "ENC_LINE_ITEM": "null_not_synthesized", "ENC_SEQ_NBR": "null_not_synthesized",
    },
}
FTE_NOTE = "JOB_DETL_FTE stored as a fraction (1.000 = full time). The Cookbook calls it a percentage; fraction vs percent is UNCONFIRMED."


def column_schema(con, table: str) -> list[dict]:
    desc = con.execute(f"DESCRIBE {q(table)}").fetchall()
    if table in VERIFIED_TABLES:
        spec = {c["name"]: c for c in cookbook_spec(table)}
        out = []
        for name, typ, *_ in desc:
            c = spec[name]
            st = "null_prohibited" if name in PROHIBITED_NULL.get(table, []) else VALUE_STATUS.get(table, {}).get(name, "free_value")
            item = {"name": name, "type": typ, "oracle_type": c["oracle_type"], "max_length": c["max_length"], "pk": c["pk"],
                    "provenance": "verified_dictionary", "value_status": st}
            if name == "JOB_DETL_FTE":
                item["note"] = FTE_NOTE
            if table == "T_EMPEE_HIST_5":
                item["note"] = "secured table; columns verified 2026-11-06; rows derived from T_EMPEE_HIST termination fields"
            out.append(item)
        return out
    return [{"name": name, "type": typ, "provenance": "assumed_synthetic_layout", "value_status": "v2_values"} for name, typ, *_ in desc]


XW_COLS = ["set", "change", "v2_table", "v2_column", "v3_table", "v3_column", "v2_value", "v3_value", "rule", "status"]


def build(out_root: Path = HERE) -> dict:
    xw: list[dict] = []
    out = {}
    for s in SETS:
        b = SetBuilder(s, out_root / s, xw)
        out[s] = b.build()
    for s in SETS:
        for t in VERIFIED_TABLES:
            if t in out[s]["tables"]:
                xw.append({"set": s, "change": "table_cookbook_shaped", "v2_table": t if t != "T_EMPEE_HIST_5" else "T_EMPEE_HIST_5",
                           "v2_column": "", "v3_table": t, "v3_column": "", "v2_value": out[s]["tables"][t]["v2_rows"],
                           "v3_value": out[s]["tables"][t]["rows"],
                           "rule": f"exact Data Cookbook column list ({len(cookbook_spec(t))} columns); v2/v3 row counts in v2_value/v3_value",
                           "status": "verified_dictionary"})
    with open(out_root / "crosswalk_v2_to_v3.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=XW_COLS, lineterminator="\n")
        w.writeheader()
        w.writerows(xw)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="rebuild into a temp dir and compare content hashes")
    a = ap.parse_args(argv)
    if a.check:
        tmp = Path(tempfile.mkdtemp())
        try:
            new = build(tmp)
            bad = []
            for s, man in new.items():
                old = json.loads((HERE / s / "manifest.json").read_text(encoding="utf-8"))
                for t, v in man["tables"].items():
                    if old["tables"].get(t) != v:
                        bad.append(f"{s}.{t}")
                if old.get("notes") != json.loads(json.dumps(man["notes"], default=str)):
                    bad.append(f"{s}.notes")
            same_xw = (tmp / "crosswalk_v2_to_v3.csv").read_bytes() == (HERE / "crosswalk_v2_to_v3.csv").read_bytes()
            print("content identical" if not bad and same_xw else f"DIFFERENT: {bad} crosswalk_same={same_xw}")
            return 0 if not bad and same_xw else 1
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    out = build(HERE)
    for s, man in out.items():
        print(f"[{s}] " + ", ".join(f"{t}={v['rows']}" for t, v in man["tables"].items()))
        print(f"[{s}] notes: {man['notes']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
