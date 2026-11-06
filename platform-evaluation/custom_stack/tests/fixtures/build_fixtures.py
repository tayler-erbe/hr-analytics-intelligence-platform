"""Build tiny, deterministic, clearly SYNTHETIC Parquet fixtures with the same
table/column names and row structure as the real lake contract layer
(data/lake/contract, lake contract v1.0), including its traps: published total
and faculty-status rows, suppressed QCEW cells, duplicated county rows, nested
enrollment levels and unpublished QWI quarters.

No real institution, person or published statistic is represented: names are
"Fixture ..." and all numbers are invented so expected answers can be checked
by hand. Run:  python build_fixtures.py [out_dir]   (default: ./contract)
"""
from __future__ import annotations

import sys
from pathlib import Path

import duckdb

SRC = "synthetic_fixture"

INSTITUTIONS = [
    # unitid, name, state, sector_code, sector label, carnegie
    ("F001", "Fixture Flagship University", "IL", "1", "Public, 4-year or above", "Fixture R1"),
    ("F002", "Fixture Regional University", "IL", "1", "Public, 4-year or above", "Fixture M1"),
    ("F003", "Fixture Community College", "IL", "4", "Public, 2-year", "Fixture Assoc"),
    ("F004", "Fixture Neighbor University", "IN", "1", "Public, 4-year or above", "Fixture R1"),
]

# unitid -> {partition category: (ft, pt)} for survey_year 2023; 2022 has 5 fewer FT instructional
EAP_2023 = {
    "F001": {"Instructional staff, total": (100, 30), "Management": (20, 0)},
    "F002": {"Instructional staff, total": (50, 15), "Management": (10, 3)},
    "F003": {"Instructional staff, total": (20, 40), "Management": (5, 0)},
    "F004": {"Instructional staff, total": (80, 10), "Management": (15, 5)},
}
EAP_CODES = {"Instructional staff, total": "21000", "Management": "30000"}

# 9-month contracts (12-month extras added separately)
SAL_IS_2023 = {
    "F001": {("1", "Professor"): (40, 6_000_000), ("3", "Assistant professor"): (30, 3_000_000)},
    "F002": {("1", "Professor"): (20, 2_400_000), ("3", "Assistant professor"): (15, 1_350_000)},
    "F003": {("3", "Assistant professor"): (10, 700_000)},
    "F004": {("1", "Professor"): (30, 4_200_000), ("3", "Assistant professor"): (25, 2_250_000)},
}

SAL_NIS_2023 = {
    "F001": {("05", "Management"): (20, 2_000_000), ("07", "Computer, engineering and science"): (10, 900_000)},
    "F002": {("05", "Management"): (10, 900_000)},
}

ENROLLMENT_EFFY2024 = {"F001": 50_000, "F002": 20_000, "F003": 10_000, "F004": 40_000}  # EFFY2023 = minus 1000


def eap_rows():
    rows = []
    for year in (2022, 2023):
        vint = f"EAP{year} (Fall {year})"
        for uid, cats in EAP_2023.items():
            tot_ft = tot_pt = 0
            for cat, (ft, pt) in cats.items():
                if year == 2022 and cat.startswith("Instructional"):
                    ft -= 5
                rows.append((uid, year, EAP_CODES[cat], cat, "0", ft + pt, ft, pt, False, SRC, vint))
                tot_ft += ft
                tot_pt += pt
            # published total row and a cross-classified faculty-status row: both must never be added in
            rows.append((uid, year, "10000", "All staff", "0", tot_ft + tot_pt, tot_ft, tot_pt, True, SRC, vint))
            rows.append((uid, year, "10020", "All staff, Tenured", "20", 7, 7, 0, True, SRC, vint))
    return rows


def sal_is_rows():
    rows = []
    for uid, cats in SAL_IS_2023.items():
        for (code, rank), (cnt, outlay) in cats.items():
            rows.append((uid, 2023, code, rank, "9-month", cnt, outlay, SRC, "SAL2023_IS (2023-24)"))
    # 12-month contracts are excluded from the default average but counted in staff totals
    rows.append(("F001", 2023, "1", "Professor", "12-month", 5, 1_000_000, SRC, "SAL2023_IS (2023-24)"))
    rows.append(("F002", 2023, "3", "Assistant professor", "10-month", 0, 0, SRC, "SAL2023_IS (2023-24)"))
    return rows


def sal_nis_rows():
    return [(uid, 2023, code, cat, cnt, outlay, SRC, "SAL2023_NIS (2023-24)")
            for uid, cats in SAL_NIS_2023.items() for (code, cat), (cnt, outlay) in cats.items()]


def enrollment_rows():
    rows = []
    for effy in (2023, 2024):
        vint = f"EFFY{effy} ({effy - 1}-{str(effy)[2:]})"
        for uid, n in ENROLLMENT_EFFY2024.items():
            n = n - (1000 if effy == 2023 else 0)
            ug = int(n * 0.8)
            rows.append((uid, effy, "1", "All students total", n, SRC, vint))
            rows.append((uid, effy, "2", "Undergraduate total", ug, SRC, vint))
            rows.append((uid, effy, "12", "Graduate", n - ug, SRC, vint))
    return rows


def qcew_rows():
    ind, area = [], []
    vint = "2019Q1 onward (fixture)"
    champ_state = {1: (15000, 15100, 15200), 2: (15300, 15300, 15300), 3: (14000, 14500, 15000), 4: (15500, 15500, 15500)}
    for q in (1, 2, 3, 4):
        ind.append(("US000", "2", "611310", 2024, q, "", 1000, 1000, 1000, 9_000_000_000, SRC, vint))
        ind.append(("US000", "5", "611310", 2024, q, "", 2000, 2000, 2000, 15_000_000_000, SRC, vint))
        ind.append(("17000", "2", "611310", 2024, q, "", 100, 100, 100, 400_000_000, SRC, vint))
        ind.append(("17000", "5", "611310", 2024, q, "", 200, 200, 200, 600_000_000, SRC, vint))
        m1, m2, m3 = champ_state[q]
        ind.append(("17019", "2", "611310", 2024, q, "", m1, m2, m3, 300_000_000, SRC, vint))
        ind.append(("17019", "5", "611310", 2024, q, "", 500, 500, 500, 5_000_000, SRC, vint))
    # Cook County: private cell suppressed in Q2 (disclosure N -> NULL measures)
    ind.append(("17031", "2", "611310", 2024, 1, "", 3000, 3000, 3000, 50_000_000, SRC, vint))
    ind.append(("17031", "5", "611310", 2024, 1, "", 7000, 7000, 7000, 100_000_000, SRC, vint))
    ind.append(("17031", "2", "611310", 2024, 2, "", 3000, 3000, 3000, 50_000_000, SRC, vint))
    ind.append(("17031", "5", "611310", 2024, 2, "N", None, None, None, None, SRC, vint))
    # county all-industry file: industry 10 with an ownership total row, plus 611310 duplicates (junk values)
    for q in (1, 2):
        area.append(("17019", "0", "10", 2024, q, "", 90000, 90000, 90000, 1_000_000_000, SRC, vint))
        area.append(("17019", "2", "10", 2024, q, "", 30000, 30000, 30000, 400_000_000, SRC, vint))
        area.append(("17019", "5", "10", 2024, q, "", 60000, 60000, 60000, 600_000_000, SRC, vint))
        area.append(("17019", "2", "611310", 2024, q, "", 999, 999, 999, 1, SRC, vint))
    return ind, area


def qwi_rows():
    rows = []
    vint = "LEHD latest_release (fixture)"
    data = {
        # (year, quarter) -> (emp, hira, sep, emp_s, earns) for the all-sex row; sep NULL = not yet published
        (2024, 1): (200000, 9000, 8500, 190000, 5500),
        (2024, 2): (202000, 9500, 9000, 192000, 5600),
        (2025, 1): (204000, 9800, None, 195000, None),
    }
    for (y, q), (emp, hira, sep, emp_s, earn) in data.items():
        rows.append(("17", "6113", "A00", y, q, "0", "A00", emp, emp_s, hira, sep, earn, SRC, vint))
        m = (round(emp * 0.45), round(emp_s * 0.45), round(hira * 0.45), None if sep is None else round(sep * 0.45),
             None if earn is None else round(earn * 1.1))
        f = (emp - m[0], emp_s - m[1], hira - m[2], None if sep is None else sep - m[3],
             None if earn is None else round(earn * 0.9))
        rows.append(("17", "6113", "A00", y, q, "1", "A00", *m, SRC, vint))
        rows.append(("17", "6113", "A00", y, q, "2", "A00", *f, SRC, vint))
        rows.append(("17", "6113", "A00", y, q, "0", "A01", 1000, 900, 300, None if sep is None else 280, None, SRC, vint))
    return rows


TABLES = {
    "ipeds_institution": ("unitid VARCHAR, institution_name VARCHAR, state_abbr VARCHAR, sector_code VARCHAR, sector VARCHAR, "
                          "carnegie VARCHAR, source_id VARCHAR, source_vintage VARCHAR",
                          lambda: [(*r, SRC, "HD2024") for r in INSTITUTIONS]),
    "ipeds_employees_by_position": ("unitid VARCHAR, survey_year INTEGER, eapcat_code VARCHAR, position_category VARCHAR, "
                                    "facstat_code VARCHAR, total_employees BIGINT, full_time BIGINT, part_time BIGINT, "
                                    "is_category_total BOOLEAN, source_id VARCHAR, source_vintage VARCHAR", eap_rows),
    "ipeds_salary_instructional": ("unitid VARCHAR, survey_year INTEGER, arank_code VARCHAR, academic_rank VARCHAR, "
                                   "contract_length VARCHAR, staff_count BIGINT, salary_outlays BIGINT, source_id VARCHAR, "
                                   "source_vintage VARCHAR", sal_is_rows),
    "ipeds_salary_noninstructional": ("unitid VARCHAR, survey_year INTEGER, occupation_category_code VARCHAR, "
                                      "occupation_category VARCHAR, staff_count BIGINT, salary_outlays BIGINT, "
                                      "source_id VARCHAR, source_vintage VARCHAR", sal_nis_rows),
    "ipeds_enrollment_12mo": ("unitid VARCHAR, survey_year INTEGER, level_code VARCHAR, student_level VARCHAR, "
                              "enrollment_total BIGINT, source_id VARCHAR, source_vintage VARCHAR", enrollment_rows),
    "qcew_industry": ("area_fips VARCHAR, own_code VARCHAR, industry_code VARCHAR, year BIGINT, qtr INTEGER, disclosure_code VARCHAR, "
                      "month1_emplvl BIGINT, month2_emplvl BIGINT, month3_emplvl BIGINT, total_qtrly_wages BIGINT, "
                      "source_id VARCHAR, source_vintage VARCHAR", lambda: qcew_rows()[0]),
    "qcew_area": ("area_fips VARCHAR, own_code VARCHAR, industry_code VARCHAR, year BIGINT, qtr INTEGER, disclosure_code VARCHAR, "
                  "month1_emplvl BIGINT, month2_emplvl BIGINT, month3_emplvl BIGINT, total_qtrly_wages BIGINT, "
                  "source_id VARCHAR, source_vintage VARCHAR", lambda: qcew_rows()[1]),
    "qwi_higher_ed": ("geography VARCHAR, industry VARCHAR, ownercode VARCHAR, year INTEGER, quarter INTEGER, sex VARCHAR, "
                      "agegrp VARCHAR, emp BIGINT, emp_s BIGINT, hira BIGINT, sep BIGINT, earns BIGINT, source_id VARCHAR, "
                      "source_vintage VARCHAR", qwi_rows),
    "onet_occupation": ("onetsoc_code VARCHAR, title VARCHAR, source_id VARCHAR, source_vintage VARCHAR",
                        lambda: [("15-1242.00", "Database Administrators", SRC, "O*NET 31.0"),
                                 ("25-1199.00", "Postsecondary Teachers, All Other", SRC, "O*NET 31.0"),
                                 ("11-3021.00", "Computer and Information Systems Managers", SRC, "O*NET 31.0")]),
    "onet_task_statement": ("onetsoc_code VARCHAR, task_id VARCHAR, task VARCHAR, task_type VARCHAR, source_id VARCHAR, source_vintage VARCHAR",
                            lambda: [(o, t, txt, ty, SRC, "O*NET 31.0") for o, t, txt, ty in [
                                ("15-1242.00", "T1", "Back up databases.", "Core"),
                                ("15-1242.00", "T2", "Plan and coordinate security measures.", "Core"),
                                ("15-1242.00", "T3", "Write and maintain documentation.", "Supplemental"),
                                ("25-1199.00", "T4", "Prepare course materials.", "Core"),
                                ("25-1199.00", "T5", "Write and maintain documentation.", "Core"),
                                ("11-3021.00", "T6", "Plan and coordinate security measures.", "Core")]]),
    "aei_task_usage": ("task_name VARCHAR, release VARCHAR, usage_pct DOUBLE, source_id VARCHAR, source_vintage VARCHAR",
                       lambda: [(t, r, s, SRC, "release_2025_03_27 + labor_market_impacts (fixture)") for t, r, s in [
                           ("back up databases.", "release_2025_03_27", 1.0),
                           ("plan and coordinate security measures.", "release_2025_03_27", 2.0),
                           ("write and maintain documentation.", "release_2025_03_27", 3.0),
                           ("back up databases.", "labor_market_impacts", None),
                           ("write and maintain documentation.", "labor_market_impacts", None)]]),
    "sucss_class": ("source_record_id BIGINT, class_code VARCHAR, class_title VARCHAR, source_id VARCHAR, source_vintage VARCHAR",
                    lambda: [(1, "1164", "Fixture Class Title A", SRC, "acquired 2026-10-29 (fixture)"),
                             (2, "1164", "Fixture Class Title A (variant)", SRC, "acquired 2026-10-29 (fixture)"),
                             (3, "0471", "Fixture Class Title B", SRC, "acquired 2026-10-29 (fixture)"),
                             (4, "2290", "Fixture Class Title C", SRC, "acquired 2026-10-29 (fixture)")]),
}


def build(out_dir: str | Path) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(":memory:")
    for name, (ddl, rows_fn) in TABLES.items():
        con.execute(f"CREATE TABLE {name} ({ddl})")
        rows = rows_fn()
        con.executemany(f"INSERT INTO {name} VALUES ({', '.join('?' * len(rows[0]))})", rows)
        target = str(out / f"{name}.parquet").replace("'", "''")
        con.execute(f"COPY (SELECT * FROM {name} ORDER BY ALL) TO '{target}' (FORMAT parquet)")
    con.close()
    return out


if __name__ == "__main__":
    print(build(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parent / "contract"))
