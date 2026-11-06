# Peer benchmark methods and comparability

This document covers how the Fall 2015–2023 IPEDS peer benchmark is built and where the series are or are not comparable over time and across institutions. Code: [`build.py`](build.py). Flags: `artifacts/comparability_flags.parquet`.

## Scope

- **Institutions.** U of I System: UIUC 145637, UIC 145600, UIS 148654, System Offices 149587. Peers: the 15 Big Ten publics in `gold_institution_panel` ([`lake/gold/gold_views.sql`](../lake/gold/gold_views.sql)). This is a proposed panel, not an approved HR peer group. UCLA, Oregon and Washington joined the Big Ten in 2024, but they are included in every year for a constant panel.
- **Peer statistics** (median, 25th and 75th percentiles, linear interpolation) use the 15 peers only. U of I campuses are never part of the band. A band is drawn only when at least 8 peers report a value. The number of peers behind each point is in the chart tooltip and table.
- **Years.** Fall 2015 to Fall 2023 HR snapshots (Nov 1). IPEDS 2024 HR files were not published on the NCES server when this was built.

## Sources and alignment

| Measure | IPEDS file (Fall Y) | Notes |
|---|---|---|
| Staff headcount by occupation × FT/PT | `S{Y}_OC` | Graduate assistants are outside the IPEDS grand total and are kept separately |
| FT instructional staff by tenure status | `S{Y}_IS` (all ranks rows) | Tenured, on track, not on track / no tenure system, without faculty status |
| FT new hires by occupation | `S{Y}_NH` | See the hire-window change below |
| Faculty salary by rank and sex | `SAL{Y}_IS` | Academic year Y-(Y+1) |
| Non-instructional FT salary by occupation | `SAL{Y}_NIS` | 13 occupation groups |
| Fall enrollment | `EF{Y}A` | Same term as the staff snapshot |
| 12-month FTE and headcount | `EFIA{Y+1}`, `EFFY{Y+1}` | Covers academic year Y-(Y+1), the year that contains the Fall Y snapshot |
| Directory and response flags | `HD{Y}`, `FLAGS{Y}` | Parent/child reporting, response status |
| CPI-U | BLS `CUUR0000SA0` (data.bls.gov table page) | Monthly, not seasonally adjusted |

When a zip contains a revised CSV (`*_rv.csv`), the revised file is used; the member used for each file is in `manifests/build_manifest.json`. `EAP{Y}` was downloaded and hashed but is not used.

**Staff per 100 FTE students.** The main ratio divides Fall Y staff headcount by 12-month FTE (reported undergraduate + graduate + doctor's-professional-practice FTE from `EFIA{Y+1}`). It does not use `EFFY{Y}`, which covers the previous academic year. As a check, a fall-FTE version uses `EF{Y}A`: full-time students plus part-time undergraduates × 0.403543 and part-time graduate students × 0.361702 (the IPEDS factors for public four-year institutions). On both versions UIUC is below the peer 25th percentile in every year. UIC is near the peer 75th percentile on the 12-month version and just above it on the fall version. Staff counts are headcounts, not FTE.

**Real dollars.** Salaries are for an academic year, so each year is deflated by the July–June average of monthly CPI-U and expressed in 2023-24 dollars (factor in `cpi_academic_year.parquet`; 2015-16 = 1.299). The BLS bulk file server (download.bls.gov) refused requests without a contact User-Agent, so the CPI table comes from the data.bls.gov series page. That page was saved and hashed like every other download.

## Comparability changes and how they are handled

| Change | Years | Effect | Handling |
|---|---|---|---|
| **2018 SOC occupation coding** | Fall 2018 onward | IPEDS started assigning jobs to its occupation groups with the 2018 Standard Occupational Classification. Group codes and labels did not change. | Every occupation-based row carries `soc_basis`, and every institution-year from 2018 gets `SOC2018_CATEGORY_BASIS`. Charts mark the change with a dashed line. A national break test is described below. |
| **New-hire window** | Fall 2015 vs 2016+ | Before 2016, new hires were full-time permanent hires from July 1 to October 31 (4 months). From Fall 2016 the window is November 1 to October 31 (12 months). Nationally, new hires per 100 FT staff went from 5.9 (2015) to 9.9 (2016). | 2015 is kept in `fact_new_hires` with `hire_window` and flag `NEW_HIRE_WINDOW_2015`. It is not charted or compared. |
| **9-month-equated salary** | 2015-16 | `SAL2015_IS` has no 9-month-equated average. | 2015 uses 9 × average weighted monthly salary (`equating_method` column, flag `EQ9_METHOD_2015`). In 2016-17, when both exist, the derived value differs from the reported one by a median of 0.34% at the professor, associate and assistant ranks (90th percentile 1.1%). For UIUC the differences are -0.2% (professor), 0.0% (associate) and -0.4% (assistant). Table: `salary_method_bridge_2016.parquet`. |
| **Non-tenure-track contract detail** | 2016+ | Multi-year contracts were split into multi-year and indefinite. | Only the non-tenure-track total is used, and it is unaffected (flag `NTT_CONTRACT_DETAIL_2016`, info). |
| **Pandemic years** | Fall 2020–2021 | Hiring freezes and enrollment shifts are real events, not reporting artifacts. | Info flag only. |

### 2018 SOC break test

For each occupation group, `soc_break_test.parquet` compares the 2017-to-2018 change in the group's **national** share of all staff (every IPEDS reporter) with the median absolute yearly change in other years. A break is declared when the 2018 change is at least 3 times the typical change and at least 0.15 points. **No group shows a national break.** The largest 2018 moves were Office & administrative support (-0.26 pts against a typical 0.31) and Business & financial operations (+0.16 against 0.15). This means the recoding did not visibly shift national totals. It does not rule out recoding at individual institutions, and the institution-level shifts below did happen in 2018–2022.

## Institutions with reporting changes

These are detected from FLAGS files and from year-over-year shifts in published totals (total staff ±15%; any occupation group with at least 100 staff ±30%). The full list is in `comparability_flags.parquet` and in the page's flag panel.

- **Penn State (214777).** Fall 2019 HR was reported by a parent record that includes the Commonwealth campuses (`PRCH_HR = 1`; total staff 15,462 → 23,932). Fall 2020 has status "not active" and Fall 2021 has no FLAGS or HR record. These three years are **excluded** from charts and peer bands, so peer medians use 14 peers in 2019–2021. Fall 2022–2023 are flagged `POST_GAP_SCOPE_UNVERIFIED`: total staff (17,695 in 2022) is 14% above Fall 2018 and instructional headcount is 35% higher (3,615 → 4,890), so the reporting scope may still differ from 2015–2018.
- **Management recoding at peers.** Management headcount moved sharply at Purdue 2019 (210 → 920), Maryland 2019 (413 → 131), Iowa 2019 (+51%), Indiana 2021 (1,117 → 238), Michigan State 2021 (+58%, with Business & financial operations -55%) and Rutgers–New Brunswick 2022 (294 → 956). In each case total staff changed by less than 3%, and other groups moved the opposite way, which points to recoding rather than hiring or layoffs. The peer band for management share is therefore driven partly by coding practice.
- **Other group reshuffles** (flag `LEVEL_SHIFT_GROUP`): UCLA 2017 and 2022, Washington 2016 and 2022, Ohio State 2018 and 2023, Maryland 2019, Oregon 2019 and 2023, Wisconsin 2022, Minnesota 2022. Most involve the Library/student & academic affairs and Community/legal/arts/media groups.
- **U of I System Offices (149587).** Total staff 1,141 (2015) → 846 (2017) → 1,112 (2022), flagged `LEVEL_SHIFT_TOTAL_STAFF`. System Offices enrol no students, so they have no per-student ratio. They are hidden by default in the page.
- **UIUC, UIC and UIS** have no FLAGS issues and no level shifts that cross the thresholds. UIS management share rose steadily from 10.5% to 14.8% without a single-year jump.

**Imputation.** No value used for the panel was imputed by NCES: all HR and salary item flags are `R` (reported) or `Z` (implied zero). 12-month FTE carries `G` ("generated from other data values"), which is how IPEDS derives FTE from credit hours. Flags are kept on every row (`imputation_flag`, `imputation_class`). `S_NH` leaves out zero rows, so an occupation group with full-time staff but no new-hire row counts as 0 hires when the institution filed new hires that year (`absent_row_implied_zero`).

## Grain and reconciliation (tested)

- The 14 occupation groups at the 3-digit OCCUPCAT level × {full-time, part-time} partition the IPEDS grand total exactly. Library (260) and student/academic affairs (270) are kept combined as 250 so the staff, new-hire and salary files share one code list.
- For every file and every year, parsed column sums equal the published sums in the IPEDS dictionary's Statistics sheet for HRTOTLT, SATOTLT/SAOUTLT, SANIN01/SANIT01, EFTOTLT, FTEUG/FTEGD/FTEDPP and EFYTOTLT (126 checks, `published_reconciliation.parquet`).
- For every panel institution and year, the groups sum to the published grand, full-time and part-time totals. Tenure statuses sum to FT instructional staff. New-hire groups sum to all FT new hires. Non-instructional groups sum to SANIN01/SANIT01 (`panel_total_reconciliation.parquet`).
- Codes are strings: UNITID has 6 characters, county FIPS keeps its leading zero (UCLA `06037`), and staff/rank codes are text.

## How to read the results (caveats)

- These are **institution-level aggregates** that institutions self-report to IPEDS. They are not payroll records. Differences often reflect job classification and which units (hospitals, clinics, branch campuses, foundations) are on the reporting payroll.
- **Women-to-men ratios** are ratios of average salaries by rank. They do not control for discipline, time in rank, appointment type or anything else, and they are **not a pay-equity finding**.
- The all-ranks faculty average moves with the rank mix as well as with pay.
- Non-instructional average salary = outlays ÷ full-time count. It is shown only where a group has at least 10 full-time staff. New-hire rates by group are shown only where the group has at least 20 full-time staff. Sex ratios are not charted where a rank has fewer than 10 men or 10 women.
- Medians can move when panel composition changes (for example, Penn State's return in 2022). Check the peer count before reading a step in the median as a trend.
