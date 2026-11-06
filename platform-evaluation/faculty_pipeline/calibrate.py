"""Derive public calibration inputs for the faculty pipeline model (gap G2).

Reads ONLY public data:
  * the lake contract (data/lake/contract/*.parquet): IPEDS Fall 2023 instructional staff by
    tenure status x rank, full-time new hires by faculty status, 2023-24 instructional salary
    by rank, 12-month enrollment (EFFY2024), institution directory;
  * IPEDS Completions C2023_A (awards by 6-digit CIP x award level), downloaded once from
    nces.ed.gov into faculty_pipeline/data/raw/ (not in the lake contract yet).

Writes faculty_pipeline/calibration.json: start states, hire flows, salaries, enrollment,
discipline-group shares, Big Ten peer ratios, literature parameters with citations, and
SURS eligibility rules. No person-level data is read or written.

Usage:  python faculty_pipeline/calibrate.py            (downloads C2023_A if absent)
        python faculty_pipeline/calibrate.py --offline  (fails if C2023_A is absent)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import duckdb

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent  # platform-evaluation/
CONTRACT = ROOT / "data" / "lake" / "contract"
RAW = HERE / "data" / "raw"
OUT = HERE / "calibration.json"

COMPLETIONS_URL = "https://nces.ed.gov/ipeds/datacenter/data/C2023_A.zip"
COMPLETIONS_CSV = "C2023_a_RV.csv"  # revised release inside the zip

INSTITUTIONS = {"145637": "UIUC", "145600": "UIC", "148654": "UIS"}
# Big Ten Conference members (2024-25, 18 institutions; main campuses as IPEDS reports them).
BIG_TEN = ["145637", "151351", "153658", "163286", "170976", "171100", "174066", "181464", "147767",
           "204796", "214777", "243780", "186380", "240444", "110662", "123961", "209551", "236948"]

# Model states and their IPEDS S2023_IS leaf rows (siscat codes). The leaf partition is
# tenured (20r) + on tenure track (30r) + NTT multi-year/indefinite (41r) + NTT annual (42r)
# + NTT less-than-annual (43r), r = rank digit 1-6. 44x ("multi-year contract") is a subset of 41x
# ("multi-year and indefinite") - identical at UIUC - and is excluded. Tenured or on-track instructors/lecturers (20/30, r>=4)
# are rare and are folded into ASC/PRE.
STATES = {
    "PRE": {"label": "Pre-tenure (on track)", "siscat": [f"30{r}" for r in range(1, 7)]},
    "ASC": {"label": "Associate, tenured", "siscat": [f"20{r}" for r in range(2, 7)]},
    "FUL": {"label": "Full professor, tenured", "siscat": ["201"]},
    "NTP": {"label": "NTT professorial (clinical/teaching/research)",
            "siscat": [f"4{c}{r}" for c in "123" for r in (1, 2, 3)]},
    "NTL": {"label": "NTT lecturer/instructor/no rank",
            "siscat": [f"4{c}{r}" for c in "123" for r in (4, 5, 6)]},
}
LEAF = [c for s in STATES.values() for c in s["siscat"]]

# Discipline groups by 2-digit CIP (2020 CIP families).
GROUPS = {
    "ENG": ("Engineering & computing", ["11", "14", "15"]),
    "SCI": ("Natural sciences & math", ["26", "27", "40", "41"]),
    "BUS": ("Business", ["52"]),
    "SOC": ("Social & behavioral sciences", ["42", "45", "44", "43"]),
    "HUM": ("Arts, humanities & communication", ["05", "09", "10", "16", "23", "24", "38", "39", "50", "54"]),
    "PRO": ("Health, agriculture, education & other professional", None),  # everything else
}
# Enrollment-years weight per award (proxy for how many enrolled student-years each award
# represents). AWLEVEL codes: 5 bachelor, 7 master, 17 research doctorate, 18 professional
# doctorate, 19 other doctorate; others are certificates.
AWARD_YEARS = {"5": 4.0, "7": 1.5, "17": 5.0, "18": 4.0, "19": 3.0}
CERT_YEARS = 0.5

LITERATURE = {
    "tenure_success": {
        "default": 0.62, "range": [0.50, 0.72],
        "what": "Share of an entering assistant-professor cohort that earns tenure at the hiring institution",
        "evidence": [
            {"cite": "Kaminski & Geisler (2012), Science 335:864, 2,966 S&E assistant professors at 14 US universities: 64% promoted to associate at the same institution; median time to departure 10.9 years",
             "url": "https://www.sciencedaily.com/releases/2012/02/120216144240.htm"},
            {"cite": "Virginia Tech hires 1998-2005: about 64% of assistant professors achieved tenure",
             "url": "https://faculty.vt.edu/content/dam/faculty_vt_edu/files/studies-reports/An%20Examination%20of%20Departure%20Trends%20among%20Pre-Tenure%20Faculty%20at%20Virginia%20Tech%20-%202003-2013%20(2020).pdf"},
            {"cite": "University of Michigan ADVANCE (2026): tenure rates of 72-73% for the AY2008-2012 hiring cohort",
             "url": "https://advance.umich.edu/wp-content/uploads/2026/01/TenureOutcomesByGenderAndRace_ADV-report_2026.pdf"},
            {"cite": "University of Missouri system, 1980s cohorts: 39% tenured within 6 years, 44% had left (AIR 1995 forum paper, ERIC ED386998)",
             "url": "https://bvbvf1.bib-bvb.de/vufind/PrimoRecord/cdi_eric_primary_ED386998"},
        ]},
    "tenure_clock": {
        "review_year": 6,
        "what": "Mandatory promotion-and-tenure dossier in the sixth probationary year; early review allowed; extensions exist",
        "evidence": [{"cite": "UIUC Provost Communication #9, Promotion and Tenure (AY2025-26)",
                      "url": "https://provost.illinois.edu/policies/provosts-communications/communication-9-promotion-and-tenure/"}]},
    "assoc_to_full_years": {
        "default": 7.0, "range": [6.5, 8.2],
        "what": "Mean years as associate professor before promotion to full, among those promoted",
        "evidence": [
            {"cite": "MLA 'Standing Still' survey (2009): 6.6 years (men) and 8.2 years (women) as associate before promotion",
             "url": "https://www.bu.edu/win/data/fig6.html"},
            {"cite": "American Historical Association field report (2012): 7.6 years from associate to full",
             "url": "https://www.historians.org/perspectives-article/what-makes-a-successful-academic-career-in-history-a-field-report-from-the-higher-ranks-december-2012/"},
        ]},
    "faculty_age": {
        "share_55_plus": 0.37, "share_65_plus": 0.13,
        "what": "Age profile of US tenure-track faculty (CUPA-HR 2018 data); used to shape the synthetic starting age distribution of tenure-system faculty",
        "evidence": [{"cite": "McChesney & Bichsel, 'The Aging of Tenure-Track Faculty in Higher Ed' (CUPA-HR, Jan 2020): 37% of faculty are 55+, 13% are 65+",
                      "url": "https://archive.cupahr.org/surveys/research-briefs/2020-aging-of-tenure-track-faculty-in-higher-ed-implications-for-succession-diversity/"}]},
    "retirement_behaviour": {
        "what": "Faculty retire late and the 70+ hazard fell after mandatory retirement ended (1994)",
        "evidence": [
            {"cite": "Ashenfelter & Card (2002), 'Did the Elimination of Mandatory Retirement Affect Faculty Retirement?', AER 92(4), NBER w8378: retirement rates at 70-71 fell from about 75%/60% to under 30%",
             "url": "https://www.nber.org/papers/w8378.pdf"},
            {"cite": "Yakoboski, 'Understanding the Faculty Retirement (Non)Decision' (TIAA Institute 2015): about two-thirds of tenured faculty 50+ expect to work past normal retirement age",
             "url": "https://www.tiaa.org/public/institute/publication/2015/understanding-faculty-retirement-non-decision"},
            {"cite": "National Research Council (1991), 'Ending Mandatory Retirement for Tenured Faculty', ch. 5 Retirement Incentive Programs",
             "url": "https://nap.nationalacademies.org/read/1795/chapter/8"},
        ]},
    "enrollment_demography": {
        "what": "US high-school graduates peak in 2025, then fall about 13% by 2041; Illinois about -32% (2023-2041)",
        "evidence": [{"cite": "WICHE, Knocking at the College Door (11th ed., Dec 2024)",
                      "url": "https://www.wiche.edu/knocking/"}]},
}

SURS = {
    "what": "State Universities Retirement System of Illinois: retirement eligibility, Traditional/Portable plans",
    "tier1": {"applies_to": "First SURS-covered employment before 2011-01-01",
              "rules": ["Age 62 with 5+ years of service", "Age 55 with 8+ years (age reduction may apply)",
                        "Any age with 30+ years of service"]},
    "tier2": {"applies_to": "First SURS-covered employment on or after 2011-01-01",
              "rules": ["Age 67 with 10+ years of service (no reduction)",
                        "Age 62 with 10+ years, reduced 0.5% per month under 67"]},
    "evidence": [
        {"cite": "SURS, Retirement Eligibility", "url": "https://surs.org/retirement-eligibility/"},
        {"cite": "SURS FAQ, When am I eligible to retire in the Traditional or Portable Plans?",
         "url": "https://surs.org/faqs/when-am-i-eligible-to-retire/"},
        {"cite": "SURS, Traditional Plan", "url": "https://surs.org/retirement-plans/traditional/"},
    ],
    "verification_note": "surs.org could not be fetched from the build sandbox (host not allowed); the rules were read from SURS page text returned by web search on 2026-11-06. Re-check before use.",
    "model_simplification": "Eligibility uses age and tier only: Tier 1 eligible from 55 (service assumed >= 8), Tier 2 from 62 (service assumed >= 10). The 30-years-any-age rule and reciprocal service are not modelled.",
}


def rows(con, sql, params=None):
    return con.execute(sql, params or []).fetchall()


def ensure_completions(offline: bool) -> Path:
    csv = RAW / COMPLETIONS_CSV
    if csv.exists():
        return csv
    if offline:
        sys.exit(f"missing {csv}; rerun without --offline to download {COMPLETIONS_URL}")
    RAW.mkdir(parents=True, exist_ok=True)
    zpath = RAW / "C2023_A.zip"
    print(f"downloading {COMPLETIONS_URL}")
    urllib.request.urlretrieve(COMPLETIONS_URL, zpath)
    with zipfile.ZipFile(zpath) as z:
        z.extract(COMPLETIONS_CSV, RAW)
    return csv


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def instructional(con, unitid):
    t = str(CONTRACT / "ipeds_instructional_staff.parquet")
    got = dict(rows(con, f"""select siscat_code, headcount from '{t}'
        where unitid = ? and sex = 'Total' and race_ethnicity = 'Total'""", [unitid]))
    # Model scope = full-time instructional staff WITH faculty status (siscat 100). Staff without
    # faculty status (500) are outside the rank/tenure structure and are reported separately.
    total = got.get("100", 0)
    assert total + got.get("500", 0) == got.get("1", 0), (unitid, got.get("1"))
    leaf_sum = sum(got.get(c, 0) for c in LEAF)
    assert leaf_sum == total, (unitid, leaf_sum, total)
    # 44x is nested in 41x (equal when no indefinite contracts): is_category_total = false is NOT
    # a partition in this table.
    dup = all(got.get("44" + r, 0) == got.get("41" + r, 0) for r in "0123456")
    states = {k: sum(got.get(c, 0) for c in v["siscat"]) for k, v in STATES.items()}
    tenured = got.get("200", 0)
    assert states["ASC"] + states["FUL"] == tenured, (unitid, states, tenured)
    return {"total": total, "all_ft_instructional": got.get("1", 0), "without_faculty_status": got.get("500", 0),
            "states": states, "leaf": {c: got.get(c, 0) for c in LEAF},
            "tenured": tenured, "on_track": got.get("300", 0), "ntt": got.get("400", 0),
            "rank_totals": {"prof": got.get("101", 0), "assoc": got.get("102", 0), "asst": got.get("103", 0),
                            "instr": got.get("104", 0), "lect": got.get("105", 0), "norank": got.get("106", 0)},
            "x44_equals_x41": dup}


def new_hires(con, unitid):
    t = str(CONTRACT / "ipeds_new_hires.parquet")
    got = dict(rows(con, f"""select snhcat_code, headcount from '{t}'
        where unitid = ? and sex = 'Total' and race_ethnicity = 'Total'""", [unitid]))
    ten, tt, ntt = got.get("21020", 0), got.get("21030", 0), got.get("21040", 0)
    assert ten + tt + ntt == got.get("21010", 0), (unitid, got)
    assert got.get("21041", 0) + got.get("21042", 0) + got.get("21043", 0) == ntt, (unitid, got)
    return {"tenured": ten, "tenure_track": tt, "ntt": ntt, "total_faculty_status": ten + tt + ntt,
            "all_ft_new_hires": got.get("10000", 0)}


def salaries(con, unitid):
    t = str(CONTRACT / "ipeds_salary_instructional.parquet")
    out = {}
    for code, label, n, outlays in rows(con, f"""select arank_code, any_value(academic_rank),
            sum(staff_count), sum(salary_outlays) from '{t}' where unitid = ? group by 1 order by 1""", [unitid]):
        out[code] = {"rank": label, "n": int(n), "avg": round(outlays / n) if n else None}
    return out


def enrollment(con, unitid):
    t = str(CONTRACT / "ipeds_enrollment_12mo.parquet")
    got = {k: v for k, v in rows(con, f"select level_code, enrollment_total from '{t}' where unitid = ?", [unitid])}
    ft, pt = got.get("21", 0), got.get("41", 0)
    return {"all": got.get("1", 0), "full_time": ft, "part_time": pt, "fte_proxy": round(ft + pt / 3.0)}


def group_of(cip2):
    for k, (_, fams) in GROUPS.items():
        if fams and cip2 in fams:
            return k
    return "PRO"


def completions(con, csv: Path, unitid):
    data = rows(con, f"""select substr(CIPCODE, 1, 2) cip2, AWLEVEL, sum(try_cast(CTOTALT as integer))
        from read_csv('{csv}', all_varchar = true)
        where UNITID = ? and MAJORNUM = '1' and length(CIPCODE) = 7 group by 1, 2""", [unitid])
    g = {k: {"awards": 0, "weighted": 0.0} for k in GROUPS}
    for cip2, aw, n in data:
        k = group_of(cip2)
        g[k]["awards"] += int(n or 0)
        g[k]["weighted"] += (n or 0) * AWARD_YEARS.get(aw, CERT_YEARS)
    tot = sum(v["weighted"] for v in g.values())
    for v in g.values():
        v["share"] = round(v["weighted"] / tot, 4) if tot else 0
        v["weighted"] = round(v["weighted"], 1)
    return g


def peers(con):
    t = str(CONTRACT / "ipeds_instructional_staff.parquet")
    h = str(CONTRACT / "ipeds_new_hires.parquet")
    names = dict(rows(con, f"select unitid, name from '{CONTRACT / 'ipeds_institution.parquet'}'"))
    out = []
    for u in BIG_TEN:
        s = instructional(con, u)
        nh = new_hires(con, u)
        tot = s["total"]
        st = s["states"]
        out.append({
            "unitid": u, "name": names.get(u, u), "ft_instructional": tot,
            "tenure_density": round(st["ASC"] / tot + st["FUL"] / tot, 4),
            "tenure_system_share": round((st["PRE"] + st["ASC"] + st["FUL"]) / tot, 4),
            "ntt_share": round((st["NTP"] + st["NTL"]) / tot, 4),
            "full_share": round(st["FUL"] / tot, 4),
            "pre_per_tenured": round(st["PRE"] / max(1, st["ASC"] + st["FUL"]), 4),
            "new_hire_rate": round(nh["total_faculty_status"] / tot, 4),
            "ntt_share_of_hires": round(nh["ntt"] / max(1, nh["total_faculty_status"]), 4),
            "tt_hires_per_pre": round(nh["tenure_track"] / max(1, st["PRE"]), 4),
            "x44_equals_x41": s["x44_equals_x41"],
        })
    keys = ["tenure_density", "tenure_system_share", "ntt_share", "full_share", "new_hire_rate",
            "ntt_share_of_hires", "tt_hires_per_pre"]

    def pct(vals, p):
        v = sorted(vals)
        i = (len(v) - 1) * p
        lo, hi = int(i), min(int(i) + 1, len(v) - 1)
        return round(v[lo] + (v[hi] - v[lo]) * (i - lo), 4)
    summary = {k: {"p25": pct([r[k] for r in out], .25), "median": pct([r[k] for r in out], .5),
                   "p75": pct([r[k] for r in out], .75)} for k in keys}
    return {"members": out, "summary": summary}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true")
    args = ap.parse_args()
    for t in ("ipeds_instructional_staff", "ipeds_new_hires", "ipeds_salary_instructional",
              "ipeds_enrollment_12mo", "ipeds_institution"):
        if not (CONTRACT / f"{t}.parquet").exists():
            sys.exit(f"lake contract table {t} missing: build the lake first (scripts/lake_contract.py)")
    csv = ensure_completions(args.offline)
    con = duckdb.connect()
    vint = dict(rows(con, f"""select 'is', any_value(source_vintage) from '{CONTRACT / 'ipeds_instructional_staff.parquet'}'
        union all select 'nh', any_value(source_vintage) from '{CONTRACT / 'ipeds_new_hires.parquet'}'
        union all select 'sal', any_value(source_vintage) from '{CONTRACT / 'ipeds_salary_instructional.parquet'}'
        union all select 'effy', any_value(source_vintage) from '{CONTRACT / 'ipeds_enrollment_12mo.parquet'}'"""))
    inst = {}
    for u, short in INSTITUTIONS.items():
        name = rows(con, f"select name from '{CONTRACT / 'ipeds_institution.parquet'}' where unitid = ?", [u])[0][0]
        inst[short] = {"unitid": u, "name": name, "instructional": instructional(con, u),
                       "new_hires": new_hires(con, u), "salary": salaries(con, u),
                       "enrollment": enrollment(con, u), "discipline_groups": completions(con, csv, u)}
    cal = {
        "calibration_version": "faculty_pipeline_cal_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "snapshot": "Fall 2023 (IPEDS HR survey, 2023-11-01 reference date)",
        "sources": {
            "ipeds_instructional_staff": {"contract_table": "ipeds_instructional_staff", "vintage": vint["is"],
                                          "filter": "sex='Total' AND race_ethnicity='Total'; scope = with faculty status (siscat 100); leaf rows 20r, 30r, 41r, 42r, 43r (44x is nested in 41x and is excluded)"},
            "ipeds_new_hires": {"contract_table": "ipeds_new_hires", "vintage": vint["nh"],
                                "filter": "sex='Total' AND race_ethnicity='Total'; 21020 tenured, 21030 on track, 21040 NTT (21041+21042+21043; 21044 is nested in 21041)"},
            "ipeds_salary_instructional": {"contract_table": "ipeds_salary_instructional", "vintage": vint["sal"],
                                           "use": "average salary by rank = sum(outlays)/sum(count) across contract lengths"},
            "ipeds_enrollment_12mo": {"contract_table": "ipeds_enrollment_12mo", "vintage": vint["effy"],
                                      "use": "FTE proxy = full-time + part-time/3 (12-month unduplicated headcount)"},
            "ipeds_completions": {"url": COMPLETIONS_URL, "file": COMPLETIONS_CSV, "sha256": sha256(csv),
                                  "vintage": "C2023_A (awards 2022-23, revised)",
                                  "use": "first-major awards by 2-digit CIP, weighted by enrollment-years per award, as the discipline-group mix (proxy for both enrollment and faculty allocation)"},
        },
        "states": {k: v["label"] for k, v in STATES.items()},
        "state_ipeds_rows": {k: v["siscat"] for k, v in STATES.items()},
        "discipline_groups": {k: {"label": v[0], "cip2": v[1] or "all other 2-digit CIP families"} for k, v in GROUPS.items()},
        "award_enrollment_years": {**AWARD_YEARS, "certificates": CERT_YEARS},
        "institutions": inst,
        "big_ten_peers": peers(con),
        "literature": LITERATURE,
        "surs": SURS,
        "caveats": [
        "Scope is full-time instructional staff with faculty status (IPEDS siscat 100). Instructional staff without faculty status (siscat 500) have no rank or tenure status and are excluded (0 at UIUC, UIC and UIS).",
            "IPEDS counts full-time instructional staff only; part-time faculty, research-only and medical-school clinical staff outside instruction are not in the start state.",
            "is_category_total = false is not a partition in ipeds_instructional_staff: the 44x rows (multi-year) are nested in 41x (multi-year and indefinite) and equal them at UIUC. The leaf set used here is 20r + 30r + 41r + 42r + 43r and is asserted to equal the published total.",
            "IPEDS gives one snapshot. Transition rates are not estimable from it; they come from published literature and from steady-state flow balance, and are labelled as such.",
            "No public source gives faculty by discipline. Faculty are allocated to discipline groups in proportion to the completions-weighted mix, so every group starts at the institutional ratio.",
        ],
    }
    OUT.write_text(json.dumps(cal, indent=1))
    for s, v in inst.items():
        print(s, v["instructional"]["total"], v["instructional"]["states"], v["new_hires"])
    print("wrote", OUT)


if __name__ == "__main__":
    main()
