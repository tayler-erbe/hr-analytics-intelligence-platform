# Multi-year IPEDS peer benchmark (Fall 2015–2023)

This extends the lake's Fall 2023 IPEDS HR evidence back to Fall 2015. The University of Illinois campuses (UIUC, UIC, UIS, System Offices) are compared with the 15 Big Ten public peers in `gold_institution_panel`. All data are public IPEDS institutional aggregates plus BLS CPI-U. The module reads nothing from `lake/` or `scripts/` at run time and changes neither.

**Methods and comparability:** [METHODS.md](METHODS.md). **Page:** `output/peer_benchmarks/peer_trends.html` (offline, one file).

## Run it

From `platform-evaluation/`:

```bash
python peer_benchmarks/acquire.py        # 199 files, ~233 MB -> data/lake/raw/ipeds_history/ (Git-ignored); about 1 minute
python peer_benchmarks/build.py          # raw -> peer_benchmarks/artifacts/*.parquet + peer_trends.json; about 20 seconds
python peer_benchmarks/render_html.py    # -> output/peer_benchmarks/peer_trends.html
python -m unittest discover -s peer_benchmarks/tests -v
```

Needs Python 3.13, duckdb, pyarrow and openpyxl. Every download is recorded in [`manifests/acquisition_manifest.json`](manifests/acquisition_manifest.json) with URL, HTTP status, bytes, SHA-256 and retrieval time. A re-run re-hashes cached files and reports `changed_on_disk` if a hash no longer matches. Parquet and JSON outputs are regenerable and Git-ignored. The manifests, `findings.json` and the code are tracked.

## Tables (`artifacts/`)

| Table | Grain | Contents |
|---|---|---|
| `dim_institution_year` | unitid × year | Name, state, county FIPS, hospital/medical codes, HR response and parent/child flags |
| `fact_staff_occupation` | unitid × year × occupation group × FT/PT | Headcount (total, men, women), IPEDS item flag, `soc_basis` |
| `fact_staff_totals` | unitid × year | Published grand / FT / PT totals and graduate assistants |
| `fact_faculty_tenure` | unitid × year × tenure status | FT instructional headcount |
| `fact_new_hires` | unitid × year × occupation group | FT new hires, FT staff on Nov 1, hires per 100 FT staff, `hire_window` |
| `fact_faculty_salary` | unitid × year × rank | 9-month-equated average (total, men, women), current and 2023-24 dollars, raw women/men ratio, small-cell flag, equating method |
| `fact_noninstructional_pay` | unitid × year × occupation group | FT count, outlays, average salary (current and real) |
| `fact_enrollment` | unitid × year | Fall headcount and computed fall FTE, 12-month FTE (EFIA), 12-month unduplicated headcount (EFFY) |
| `fact_institution_metrics` | unitid × year | Wide table: staff totals, FT share, management share, staff per 100 FTE (two denominators), tenure shares, new-hire rate |
| `comparability_flags` | unitid × year × domain × flag | Category changes, method changes, reporting changes, level shifts; severity `info` / `caution` / `exclude` |
| `soc_break_test`, `national_occupation_share` | group (× year) | National test for a 2018 SOC discontinuity |
| `salary_method_bridge_2016` | unitid × rank | 2015 equating method compared with the reported value in 2016 |
| `published_reconciliation`, `panel_total_reconciliation` | file × variable; unitid × year | Parsed sums against published IPEDS totals |
| `cpi_academic_year` | academic year | July–June CPI-U average and the factor to 2023-24 dollars |

Rules carried over from the lake contract: codes are strings (UNITID, FIPS, staff and rank codes), occupation groups partition the published total (filter nothing before summing), salary group tables exclude IPEDS all-groups rows, and suppressed or missing values stay NULL. Institution-years flagged `exclude` (Penn State 2019–2021) stay in the tables but are dropped from charts and peer bands.

## Findings (Fall 2015–2023; read METHODS.md caveats first)

1. **Staff per student.** UIUC had 21.7 staff per 100 FTE students in Fall 2023. The peer median was 39.6 (middle half 28.9–44.6), and UIUC was below the peer 25th percentile in all nine years on both FTE definitions. UIC (43.3) sits near the top of the peer range. Some of the gap may come from differences in whether hospital and clinical staff are on the reporting payroll.
2. **Management share vs management per student.** 10.6% of UIUC staff are coded Management, against a peer median of 5.3%, and UIS rose from 10.5% to 14.8%. Per 100 FTE students, though, UIUC has 2.30 management staff, at the peer median (2.31). Six peers recoded hundreds of staff into or out of Management between 2019 and 2022 with almost no change in total staff. Treat this share as a measure of classification practice as much as of administrative size.
3. **Tenure.** UIUC's tenured share of FT instructional staff fell from 57.5% to 51.1%, and the peer median fell from 49.3% to 42.5%. UIUC remains above the peer median. UIC fell from 43.2% to 39.3%.
4. **Faculty pay after inflation.** UIUC's all-ranks 9-month average rose 19.8% in current dollars from 2015-16 to 2023-24 but fell 7.8% in 2023-24 dollars. The peer median fell 8.2%. About 90% of UIUC's real decline came between 2020-21 and 2022-23. UIUC professor pay was above the peer median in every year.
5. **Raw women-to-men salary ratio (not a pay-equity finding).** UIUC's all-ranks ratio rose from 0.796 to 0.831 (peer median 0.823 in 2023). Within ranks in 2023 it was 0.900 for professors, 0.952 for associate professors and 0.921 for assistant professors. Much of the all-ranks gap reflects rank mix: 70% of UIUC professors are men. The ratios are unadjusted.
6. **Management pay.** UIUC's average full-time Management salary was $117,207 in 2023-24, against a peer median of $149,498. This fits broader management coding (finding 2), but IPEDS cannot confirm it.
7. **New hires.** On the 12-month definition (2016+), UIUC's all-occupation full-time new hires per 100 FT staff were below the peer median in every year. In 2023 the figure was 10.6 against 12.7.

## Not covered or limited

- Fall 2024 HR is not yet published by NCES. EAP files were downloaded but not used.
- No adjustment for medical-school or hospital scope. HD hospital/medical codes are in `dim_institution_year` for anyone who wants to segment.
- The peer group is a proposal, not an approved comparison group.
