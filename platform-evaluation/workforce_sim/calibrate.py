"""Derive public calibration targets for the workforce scenario simulator.

Reads ONLY the public HR data lake (contract + silver Parquet). Writes
workforce_sim/calibration.json: aggregate targets with sources and caveats.
No person-level data is read or produced here.

Usage:  python workforce_sim/calibrate.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import duckdb

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent  # platform-evaluation/
LAKE = ROOT / "data" / "lake"
CONTRACT = LAKE / "contract"
SILVER = LAKE / "silver"
OUT = HERE / "calibration.json"

UIUC_UNITID = "145637"
# QWI calibration window: 8 fully published quarters. The contract notes the two
# most recent quarters (2025Q3, 2025Q4) are only partially published.
QWI_WINDOW = (2023, 3, 2025, 2)

AGE_LABELS = {
    "A01": "14-18", "A02": "19-21", "A03": "22-24", "A04": "25-34",
    "A05": "35-44", "A06": "45-54", "A07": "55-64", "A08": "65-99",
}
# Synthetic population excludes A01 (14-18): IPEDS staff counts exclude student
# workers and graduate assistants. A02/A03 are kept (small) for realism.
SIM_AGE_GROUPS = ["A02", "A03", "A04", "A05", "A06", "A07", "A08"]
AGE_BOUNDS = {  # inclusive lower, exclusive upper (years) used by the simulator
    "A02": (19, 22), "A03": (22, 25), "A04": (25, 35), "A05": (35, 45),
    "A06": (45, 55), "A07": (55, 65), "A08": (65, 75),
}

# Synthetic job families = IPEDS S2023_OC detail occupation categories (Public
# service, 1 person at UIUC, is folded into Research). Codes are our own.
FAMILIES = [
    # code, label, IPEDS staffcat suffix(es) (last 3 digits), new-hire snhcat, salary table key
    ("FAC", "Instructional (faculty)", ["210"], ["21000"], "instructional"),
    ("RES", "Research & public service", ["220", "230"], ["22000"], "02"),
    ("LIB", "Library & archives", ["260"], ["25000"], "04"),
    ("SAA", "Student & academic affairs", ["270"], ["25000"], "04"),
    ("MGT", "Management", ["300"], ["30000"], "05"),
    ("BFO", "Business & financial ops", ["310"], ["31000"], "06"),
    ("CES", "Computer, engineering & science", ["320"], ["32000"], "07"),
    ("CSL", "Community svc, legal, arts & media", ["330"], ["33000"], "08"),
    ("HLT", "Healthcare practitioners", ["340"], ["34000"], "09"),
    ("SVC", "Service occupations", ["350"], ["35000"], "10"),
    ("OAS", "Office & administrative support", ["370"], ["37000"], "12"),
    ("NRC", "Construction & maintenance", ["380"], ["38000"], "13"),
    ("PTM", "Production & transportation", ["390"], ["39000"], "14"),
]

RANKS = [  # (code, label, IPEDS S2023_IS tenure x rank partition rows)
    ("PROF", "Professor", ["201", "301", "411", "421"]),
    ("ASSOC", "Associate professor", ["202", "302", "412", "422"]),
    ("ASST", "Assistant professor", ["203", "303", "413", "423"]),
    ("INSTR", "Instructor", ["414", "424"]),
    ("LECT", "Lecturer", ["415", "425"]),
    ("NORANK", "No academic rank", ["426"]),
]


def q(con, sql):
    return con.sql(sql).fetchall()


def require_lake():
    needed = [CONTRACT / f"{t}.parquet" for t in (
        "qwi_higher_ed", "ipeds_staff_by_occupation", "ipeds_instructional_staff",
        "ipeds_new_hires", "ipeds_salary_instructional", "ipeds_salary_noninstructional",
        "ipeds_institution")] + [SILVER / "qwi_il_sa_gs_n4_oslp.parquet"]
    missing = [str(p) for p in needed if not p.exists()]
    if missing:
        sys.exit("Lake files missing (run scripts/lake_acquire.py, lake_build.py, lake_contract.py):\n  "
                 + "\n  ".join(missing))


def qwi_targets(con):
    y0, q0, y1, q1 = QWI_WINDOW
    win = f"(year*10+quarter) BETWEEN {y0*10+q0} AND {y1*10+q1}"
    silver = f"'{SILVER / 'qwi_il_sa_gs_n4_oslp.parquet'}'"
    contract = f"'{CONTRACT / 'qwi_higher_ed.parquet'}'"
    base = (f"FROM {silver} WHERE industry='6113' AND ownercode='A00' AND sex='0' "
            f"AND seasonadj='U' AND {win}")
    rows = q(con, f"""SELECT agegrp, count(*), sum(emp_s), sum(sep_s), sum(hir_as),
                             sum(emp), sum(sep), sum(sep_beg), min(s_sep_s), max(s_sep_s)
                      {base} GROUP BY agegrp ORDER BY agegrp""")
    by_age = {}
    for ag, n, emp_s, sep_s, hir_as, emp, sep, sep_beg, smin, smax in rows:
        by_age[ag] = {
            "label": AGE_LABELS.get(ag, "all ages"), "quarters": n,
            "mean_stable_emp": round(emp_s / n, 1),
            "stable_sep_rate_q": round(sep_s / emp_s, 5),
            "stable_hire_rate_q": round(hir_as / emp_s, 5),
            "all_sep_rate_q": round(sep / emp, 5),
            "beginning_of_quarter_sep_rate_q": round(sep_beg / emp, 5),
            "stable_hires_total": int(hir_as),
            "status_flag_range_sep_s": [smin, smax],
        }
    seas_rows = q(con, f"""SELECT quarter, sum(sep_s)/sum(emp_s) {base} AND agegrp='A00'
                           GROUP BY quarter ORDER BY quarter""")
    mean_rate = sum(r for _, r in seas_rows) / len(seas_rows)
    seasonality = {str(qq): round(r / mean_rate, 4) for qq, r in seas_rows}

    # Cross-check: contract qwi_higher_ed and silver agree on sep/emp in window.
    mism = q(con, f"""SELECT count(*) FROM {contract} c JOIN {silver} s
                      ON c.year=s.year AND c.quarter=s.quarter AND c.agegrp=s.agegrp AND c.sex=s.sex
                      AND s.industry='6113' AND s.ownercode='A00' AND s.seasonadj='U'
                      WHERE c.sex='0' AND {win.replace('year', 'c.year').replace('quarter', 'c.quarter')}
                      AND (c.sep IS DISTINCT FROM s.sep OR c.emp IS DISTINCT FROM s.emp)""")[0][0]
    n_contract = q(con, f"SELECT count(*) FROM {contract} WHERE sex='0' AND "
                        f"{win}")[0][0]

    sim_emp = sum(by_age[a]["mean_stable_emp"] for a in SIM_AGE_GROUPS)
    sim_hires = sum(by_age[a]["stable_hires_total"] for a in SIM_AGE_GROUPS)
    for a in SIM_AGE_GROUPS:
        by_age[a]["sim_population_share"] = round(by_age[a]["mean_stable_emp"] / sim_emp, 5)
        by_age[a]["sim_hire_age_share"] = round(by_age[a]["stable_hires_total"] / sim_hires, 5)
        by_age[a]["age_bounds"] = list(AGE_BOUNDS[a])
    return {
        "geography": "Illinois statewide", "industry": "NAICS 6113 Colleges, universities & professional schools",
        "ownership": "A00 all (public + private)", "window": f"{y0}Q{q0}-{y1}Q{q1}",
        "hazard_measure": "stable_sep_rate_q = SepS / EmpS (separations from jobs held a full quarter)",
        "by_age": by_age, "seasonality_multiplier_by_quarter": seasonality,
        "cross_check": {"contract_rows_in_window_sex0": n_contract,
                        "contract_vs_silver_sep_emp_mismatches": mism},
        "source": "contract qwi_higher_ed (totals) + silver qwi_il_sa_gs_n4_oslp (age rows, stable measures)",
    }


def ipeds_targets(con):
    staff = f"'{CONTRACT / 'ipeds_staff_by_occupation.parquet'}'"
    rows = q(con, f"""SELECT staffcat_code, occupation_category, ftpt_status, headcount
                      FROM {staff} WHERE unitid='{UIUC_UNITID}' AND sex='Total'
                      AND race_ethnicity='Total' AND NOT is_category_total
                      AND ftpt_status IN ('Full-time','Part-time')""")
    grand = q(con, f"""SELECT headcount FROM {staff} WHERE unitid='{UIUC_UNITID}' AND sex='Total'
                       AND race_ethnicity='Total' AND staffcat_code='1100'""")[0][0]
    ft_tot = q(con, f"""SELECT headcount FROM {staff} WHERE unitid='{UIUC_UNITID}' AND sex='Total'
                        AND race_ethnicity='Total' AND staffcat_code='2100'""")[0][0]
    snap = q(con, f"SELECT DISTINCT snapshot_date, source_vintage FROM {staff} WHERE unitid='{UIUC_UNITID}'")[0]
    name = q(con, f"SELECT name FROM '{CONTRACT / 'ipeds_institution.parquet'}' WHERE unitid='{UIUC_UNITID}'")[0][0]
    cells = {(code[1:], ftpt): hc for code, _, ftpt, hc in rows}

    nh = dict(q(con, f"""SELECT snhcat_code, headcount FROM '{CONTRACT / 'ipeds_new_hires.parquet'}'
                         WHERE unitid='{UIUC_UNITID}' AND sex='Total' AND race_ethnicity='Total'"""))
    nis = {r[0]: (r[1], r[2], r[3]) for r in q(con, f"""SELECT occupation_category_code, occupation_category,
                         staff_count, avg_salary FROM '{CONTRACT / 'ipeds_salary_noninstructional.parquet'}'
                         WHERE unitid='{UIUC_UNITID}'""")}
    sal_is = q(con, f"""SELECT academic_rank, sum(staff_count), sum(salary_outlays)
                        FROM '{CONTRACT / 'ipeds_salary_instructional.parquet'}'
                        WHERE unitid='{UIUC_UNITID}' GROUP BY academic_rank""")
    sal_rank = {r: (int(n), round(o / n) if n else None) for r, n, o in sal_is}

    fams = {}
    nh_used = {}
    for code, label, suffixes, nh_codes, sal_key in FAMILIES:
        ft = sum(cells.get((s, "Full-time"), 0) for s in suffixes)
        pt = sum(cells.get((s, "Part-time"), 0) for s in suffixes)
        fams[code] = {"label": label, "ipeds_staffcat_suffixes": suffixes,
                      "ft": ft, "pt": pt, "total": ft + pt, "new_hire_codes": nh_codes,
                      "salary_key": sal_key}
    # New hires: LIB and SAA share one IPEDS new-hire category -> split by FT share.
    for code, f in fams.items():
        nh_codes = f["new_hire_codes"]
        sharers = [c for c, g in fams.items() if g["new_hire_codes"] == nh_codes]
        pool = sum(nh.get(c, 0) for c in nh_codes)
        ft_pool = sum(fams[c]["ft"] for c in sharers)
        f["ft_new_hires"] = round(pool * f["ft"] / ft_pool, 2) if ft_pool else 0
        nh_used.update({c: nh.get(c, 0) for c in nh_codes})
    nh_total = nh.get("10000")
    overall = nh_total / ft_tot
    for code, f in fams.items():
        rate = f["ft_new_hires"] / f["ft"] if f["ft"] else overall
        f["ft_new_hire_rate"] = round(rate, 5)
        f["turnover_multiplier"] = round(min(2.0, max(0.5, rate / overall)), 4)
        if f["salary_key"] == "instructional":
            n = sum(v[0] for v in sal_rank.values())
            o = sum(v[0] * v[1] for v in sal_rank.values() if v[1])
            f["avg_salary_ft"] = round(o / n)
            f["salary_basis"] = "SAL2023_IS all ranks/contract lengths (outlays/count)"
        else:
            cnt, avg = nis[f["salary_key"]][1], nis[f["salary_key"]][2]
            f["avg_salary_ft"] = avg
            f["salary_basis"] = f"SAL2023_NIS group {f['salary_key']} ({nis[f['salary_key']][0]}), n={cnt}"

    is_tbl = f"'{CONTRACT / 'ipeds_instructional_staff.parquet'}'"
    is_rows = dict(q(con, f"""SELECT siscat_code, headcount FROM {is_tbl} WHERE unitid='{UIUC_UNITID}'
                              AND sex='Total' AND race_ethnicity='Total'"""))
    ranks = {}
    for code, label, cats in RANKS:
        ranks[code] = {"label": label, "ft_headcount": sum(is_rows.get(c, 0) for c in cats),
                       "ipeds_siscat_codes": cats,
                       "tenured": is_rows.get(cats[0], 0) if cats[0].startswith("2") else 0,
                       "avg_salary_ft": sal_rank.get({"PROF": "Professor", "ASSOC": "Associate professor",
                                                      "ASST": "Assistant professor", "INSTR": "Instructor",
                                                      "LECT": "Lecturer", "NORANK": "No academic rank"}[code],
                                                     (0, None))[1]}
    rank_sum = sum(r["ft_headcount"] for r in ranks.values())
    part_sum = sum(f["total"] for f in fams.values())
    return {
        "unitid": UIUC_UNITID, "institution": name, "snapshot_date": str(snap[0]), "vintage": snap[1],
        "grand_total_headcount": grand, "ft_total": ft_tot, "pt_total": grand - ft_tot,
        "families": fams, "faculty_ft_rank": ranks,
        "ft_new_hires_total": nh_total, "ft_new_hire_rate": round(overall, 5),
        "cross_check": {"family_partition_sum": part_sum, "equals_grand_total": part_sum == grand,
                        "rank_partition_sum": rank_sum,
                        "equals_ft_instructional": rank_sum == fams["FAC"]["ft"]},
        "source": "contract ipeds_staff_by_occupation (is_category_total=false, sex/race='Total'), "
                  "ipeds_instructional_staff, ipeds_new_hires, ipeds_salary_instructional, "
                  "ipeds_salary_noninstructional",
    }


def hazard_anchors(qwi, ipeds):
    """Two documented hazard levels with the same QWI age shape.

    qwi:   statewide stable-separation rates as published (level + shape).
    ipeds: QWI age shape rescaled so the expected annual separation rate of the
           UIUC-mirrored synthetic population equals UIUC's IPEDS FT new-hire
           rate (steady-state assumption: hires ~ separations).
    """
    shares = {a: qwi["by_age"][a]["sim_population_share"] for a in SIM_AGE_GROUPS}
    base = {a: qwi["by_age"][a]["stable_sep_rate_q"] for a in SIM_AGE_GROUPS}
    mean_q = sum(shares[a] * base[a] for a in SIM_AGE_GROUPS)
    annual_qwi = 1 - (1 - mean_q) ** 4
    target_annual = ipeds["ft_new_hire_rate"]
    target_q = 1 - (1 - target_annual) ** 0.25
    scale = target_q / mean_q
    return {
        "qwi": {"label": "QWI statewide level", "quarterly_rate_by_age": base,
                "implied_annual_rate_for_sim_age_mix": round(annual_qwi, 4)},
        "ipeds": {"label": "UIUC IPEDS new-hire anchored", "scale_vs_qwi": round(scale, 4),
                  "quarterly_rate_by_age": {a: round(base[a] * scale, 5) for a in SIM_AGE_GROUPS},
                  "implied_annual_rate_for_sim_age_mix": round(target_annual, 4)},
    }


CAVEATS = [
    "All targets are public aggregates. The simulator's population is synthetic; nothing here describes any real employee.",
    "QWI covers ALL Illinois NAICS 6113 employers (public and private), not UIUC. It includes stable jobs of any FTE; "
    "age group 14-18 is excluded from the synthetic population because IPEDS staff counts exclude student workers and graduate assistants.",
    "QWI does not distinguish retirements, voluntary quits or terminations. Retirement classification in the simulator is an illustrative eligibility rule, not SURS plan rules.",
    "The QWI statewide separation level is roughly twice the UIUC IPEDS full-time new-hire rate. Both anchors are kept; the difference is structural uncertainty and is shown in the planner.",
    "IPEDS new hires are Fall-2023 full-time permanent hires only; the IPEDS anchor assumes steady state (hires ~ separations) and ignores part-time churn.",
    "Family turnover multipliers come from UIUC FT new-hire rate by occupation relative to the overall rate, clipped to [0.5, 2.0]. "
    "Library and Student/Academic Affairs share one IPEDS new-hire category and are split by FT headcount.",
    "IPEDS salary averages are full-time only, Fall 2023 / AY2023-24; part-time pay is assumed pro-rata. No level-specific pay is published.",
    "Reporting levels, tenure, critical-role flags, promotion rates and time-to-fill have NO public UIUC source. They are labelled assumptions in synthesize.py/simulate.py.",
]


def main():
    require_lake()
    con = duckdb.connect()
    qwi = qwi_targets(con)
    ipeds = ipeds_targets(con)
    cal = {
        "calibration_version": "wfsim-cal-1.0",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "lake_contract": "1.0",
        "uiuc_ipeds": ipeds,
        "qwi_il_higher_ed": qwi,
        "hazard_anchors": hazard_anchors(qwi, ipeds),
        "caveats": CAVEATS,
    }
    assert ipeds["cross_check"]["equals_grand_total"], "IPEDS family partition does not sum to grand total"
    assert ipeds["cross_check"]["equals_ft_instructional"], "rank partition != FT instructional"
    assert qwi["cross_check"]["contract_vs_silver_sep_emp_mismatches"] == 0
    OUT.write_text(json.dumps(cal, indent=2))
    a = cal["hazard_anchors"]
    print(f"wrote {OUT.relative_to(ROOT)}")
    print(f"  UIUC Fall 2023 headcount {ipeds['grand_total_headcount']} (FT {ipeds['ft_total']}, PT {ipeds['pt_total']}); "
          f"FT new-hire rate {ipeds['ft_new_hire_rate']:.3f}")
    print(f"  QWI annual separation (sim age mix) {a['qwi']['implied_annual_rate_for_sim_age_mix']:.3f}; "
          f"IPEDS anchor scale {a['ipeds']['scale_vs_qwi']}")


if __name__ == "__main__":
    main()
