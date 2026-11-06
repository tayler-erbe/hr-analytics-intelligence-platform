# Sponsored-funding cliff (gap G3): positions funded by grants and soft money

This module addresses gap **G3** in [../research/TOOLS_BEYOND_SNOWFLAKE_DATABRICKS.md](../research/TOOLS_BEYOND_SNOWFLAKE_DATABRICKS.md): *positions funded by grants and soft money*. It builds the public half of that join from public federal award data for UIUC and UIC. It also specifies the internal half, which joins Banner labor distribution to grant end dates, but does not run it.

The output is an offline dashboard, `output/sponsored_funding/funding_cliff.html`. It contains aggregates only, by agency, NIH institute or center, NIH department category and activity code. No investigator names are shown anywhere, and none are stored, including in the raw cache.

Built 2026-11-06. **As-of date: 2026-11-06.** The window is the next 8 federal fiscal quarters, FY27 Q1 (Oct–Dec 2026, from the as-of date onward) through FY28 Q4 (Jul–Sep 2028).

## Run it

```bash
# from platform-evaluation/
python sponsored_funding/fetch_sponsored.py      # cached, paged, rate-limited pulls (~170 requests, ~4 min cold)
python sponsored_funding/build_cliff.py          # aggregates -> sponsored_funding/artifacts/
python sponsored_funding/render_dashboard.py     # -> output/sponsored_funding/funding_cliff.html
python -m unittest discover -s sponsored_funding/tests -v   # 20 tests
```

| Path | What | In Git? |
|---|---|---|
| `data/lake/raw/sponsored_funding/<source>/<hash>.json` | Raw API responses, byte-for-byte, named by a hash of (method, URL, body) | No (`data/lake/` is ignored) |
| `data/lake/raw/sponsored_funding/request_manifest.jsonl` | One line per request: source, URL, POST body, UTC timestamp, cache hit or miss, HTTP status, bytes, SHA-256 | No |
| `data/lake/raw/sponsored_funding/_derived/*.parquet` | Award-, application- and project-level tables with no PI fields | No |
| `sponsored_funding/artifacts/funding_cliff.json` | Every aggregate the dashboard shows | Yes |
| `sponsored_funding/artifacts/recipient_bridge.csv` | Institution identifiers (UEI, DUNS, IPF code) per source | Yes |
| `sponsored_funding/artifacts/build_manifest.json` | SHA-256 of every input file and output, row counts, exclusions | Yes |
| `sponsored_funding/hr_join_design.sql` | Design for the internal position-risk join (section 5) | Yes |

Live requests are spaced at least 1.1 s apart and retried with backoff on 429 and 5xx responses. NIH queries use `include_fields`, which excludes `PrincipalInvestigators`, `ContactPiName` and `ProgramOfficers`, so PI names never reach disk. A test enforces this.

## 1. Sources and reachability

| Source | Endpoint | Status from this session | Used for |
|---|---|---|---|
| NIH RePORTER v2 | `api.reporter.nih.gov/v2/projects/search` | OK: 5,375 records for FY2019–2027, 4,961 at U of I UEIs | Project and budget-period dates, annual total cost, activity code, IC, NIH department category |
| USAspending v2 | `api.usaspending.gov/api/v2/search/spending_by_award/`, `/recipient/` | OK: 6,336 rows, 5,667 unique awards | All federal agencies: period-of-performance end, obligations, agency, sub-agency, CFDA |
| NSF Award Search | `api.nsf.gov/services/v1/awards.json` | **Blocked**: the proxy refused the CONNECT tunnel with 403. The failure is logged in the manifest. `www.research.gov` is also blocked | Not used. NSF awards still come through USAspending |
| NCSES HERD FY2024 | `ncses.nsf.gov/pubs/nsf26304/...tables-excels.zip` | OK | Scale anchor: R&D expenditures by agency (Table 18), totals (Table 4), R&D personnel headcount and FTE (Table 27) |

### Recipient bridge (entity resolution)

| Campus | UEI | Legacy DUNS | Evidence |
|---|---|---|---|
| System parent | V2PHZ2CSCH63 | — | USAspending parent. Not queried directly; its children are |
| UIUC | **Y8CWNJRCNN91** | 041544081 | USAspending child of the parent, Urbana address; also NIH RePORTER `primary_uei` for "UNIVERSITY OF ILLINOIS AT URBANA-CHAMPAIGN" |
| UIUC | C11MNATAJ3K5 | 801623620 | USAspending child, Urbana address (alternate names include "UNIV ILLINOIS URBANA"). 3 grant awards |
| UIC | **W8XEAJDKMXH3** | 098987217 | USAspending child of the parent; NIH RePORTER `primary_uei` for "UNIVERSITY OF ILLINOIS AT CHICAGO" |
| UIS | LMKAF2LNJGP6, M6X1K9AU6HM5 | 965932734, 958081929 | Springfield address. Pulled and included in "All U of I", but negligible (fewer than 20 awards) |

Entity-resolution caveats, found in this data:

- **USAspending's recipient name is useless as a key.** All the UEIs above report the name "UNIVERSITY OF ILLINOIS". The UIUC recipient profile lists about 60 alternate names, including "UNIVERSITY OF NEW ORLEANS", "UNIVERSITY OF NORTH CAROLINA", "ROCHESTER" and "STATE EMERGENCY MANAGEMENT AGENCY". These are data-entry noise and show why matching on names fails. The pipeline joins on **UEI only**.
- **`recipient_search_text` is a fuzzy text search, not a UEI filter.** A query for the UIUC UEI also returns UIC awards. 669 duplicate rows across the per-UEI queries were removed on `generated_internal_id`, keeping exact UEI matches only.
- **NIH RePORTER** uses `org_names` for substring search. The pipeline queries `ILLINOIS` within IL so that every Illinois-named organization is visible in the bridge file, then keeps records whose `primary_uei` or `org_ueis` is in the table above. 414 records from other Illinois institutions were dropped and are listed in `recipient_bridge.csv`.
- **NIH ↔ USAspending.** NIH `core_project_num` equals the USAspending FAIN (`Award ID`), for example `R01CA285576`.

## 2. Methods

**USAspending (all agencies).** Prime grants and cooperative agreements are included, with award types `02`–`05` **plus `F001` and `F002`**. FY2026 FABS records use the new assistance-type codes F001 and F002. The first pull used only 02–05 and returned *zero* FY2026 NIH grant awards nationwide, so it was discarded. Both pulls are logged in the manifest. The action-date window is 2018-10-01 to 2026-11-06.

An award is *active* if its end date is on or after the as-of date and its net obligation is above zero. Excluded from the cliff:
- 98 awards with zero or negative obligation.
- 27 student-aid and loan programs (CFDA 93.342, 93.364, 84.0xx). These carry placeholder end dates such as 2079-06-06 and are not position funding.
- Awards with an end date more than 15 years out are flagged as anomalous. None remained after the student-aid filter.
- 35 active awards (\$26.9M) have no end date. They are shown in their own bucket.

The dollar measure is an **annual run-rate estimate**: obligation ÷ max(1, period-of-performance years). USAspending does not show which awards are funded incrementally and which are funded up front, so any single number is an estimate (see section 4).

**NIH RePORTER.** Rows are deduplicated on `appl_id` and rolled up to core-project grain. The latest fiscal year wins. The annual amount is the sum of that year's parent-record total cost, including type-3 supplements. Project end is the latest `project_end_date` in that year. **Subprojects (418 rows) are excluded** because their dollars are already inside the parent award. NIH FY2027 returned 0 records as of the as-of date.

There are **two NIH cliffs**:
- **Project end.** The award stops unless it is competitively renewed.
- **Budget-period end before project end.** The project continues, but the next year's money is a non-competing continuation that depends on appropriations. FY2027 began under a continuing resolution.

**Departments.** Only NIH supplies a department, and it is NIH's standardized `dept_type` (for example "PHARMACOLOGY" or "ENGINEERING (ALL TYPES)"), not the University's own org unit. About 16% of NIH application records have a blank department. USAspending has no department at all. A real department view needs Banner Finance org codes (section 5).

**Small cells.** In every dimension × quarter table, cells with 1–2 awards are suppressed (k = 3). If a row has exactly one suppressed cell, the next-smallest cell is also suppressed. If no second cell can be suppressed, the row's window total and share are hidden too. Tests cover all three rules. Award amounts are public, but a department or quarter cell with one award points at one lab.

**Concentration.** The pipeline reports the share of the active run-rate by agency and the HHI (Σ share² × 10,000).

## 3. Results (as of 2026-11-06)

| | All U of I | UIUC | UIC |
|---|---|---|---|
| Active federal grants and cooperative agreements (USAspending) | 1,657 | 1,004 | 651 |
| Estimated annual run-rate | \$597M | \$384M | \$213M |
| Share of run-rate whose award ends within 4 quarters (by FY27 Q4) | 52% | 51% | 54% |
| … within 8 quarters (by FY28 Q4) | 69% | 69% | 70% |
| Agency HHI (top agency) | 2,278 (HHS 38%) | 1,780 (NSF 27%) | **5,416 (HHS 72%)** |
| Active NIH core projects / latest-FY annual cost (RePORTER) | 595 / \$351M | 194 / \$114M | 401 / \$237M |
| NIH continuations due by FY27 Q4, project continuing (appropriations-dependent) | 310 / \$163M | 106 / \$56M | 204 / \$107M |
| NIH competing awards (types 1 and 2), FY2024 → FY2025 | | 44 → 32 | 102 → 76 |

How to read these:
- **UIC is highly concentrated in HHS/NIH.** On the agency HHI it falls in the "highly concentrated" range (above 2,500).
- **UIUC is diversified** across NSF, DOE, HHS, USDA and DOD.
- **The FY27 Q4 spike is mostly September 30 end dates.** Many awards with annual budget periods, especially DOE and NSF cooperative agreements, end at fiscal year end and are routinely extended. The 52% and 69% figures are *exposure* (decisions that must happen), not *loss*.

## 4. Reconciliation: obligations ≠ spending ≠ salaries

| Check | Result |
|---|---|
| Active NIH core projects that match a USAspending FAIN at the same campus UEI | 580 of 595 (97.5%) |
| End dates identical across the two sources | 564 of 580. 15 are earlier in USAspending by more than 31 days; none are later |
| Annual NIH dollars for the matched projects | RePORTER latest-FY cost \$338M; USAspending obligation ÷ years \$198M; USAspending obligated-to-date \$1.17B |
| HERD FY2024 federal R&D **expenditures** | UIUC \$511.6M (NSF \$125.7M, DOE \$121.8M, HHS \$97.5M); UIC \$300.0M (HHS \$226.9M) |
| HERD FY2024 R&D personnel paid from R&D funds (all sources) | UIUC 20,171 headcount / 8,337 FTE; UIC 6,862 / 2,215 FTE |

The USAspending run-rate is about 0.59× RePORTER for NIH, so treat it as a **lower bound**. These are three different quantities:
- **Obligations:** what the agency committed.
- **Expenditures:** what HERD reports was spent, including subawards received, which are not prime awards here.
- **Salaries:** what HR pays.

None of them is a count of positions. HERD's personnel table is the only public anchor for people, and it covers R&D funds from all sources, not only federal.

Not covered:
- Subawards received from other institutions.
- Non-federal sponsors.
- NSF Award Search (blocked).
- Grant terminations that have not yet been reflected in end dates.
- RePORTER FY2026 may still be filling in.

## 5. From award risk to position risk (designed, not populated)

`hr_join_design.sql` is portable DuckDB/ANSI SQL. It is tested only on a synthetic fixture.

1. **As-of labor distribution.** Banner HR `NBRJLBD`, or EDW `T_PAYR_ACCTG_DETL`, gives one row per position, suffix and FOAPAL split with its percent, filtered to the splits in force on the as-of date (`eff_dt ≤ as_of < exp_dt`).
2. **Fund → grant.** Banner Finance `FTVFUND.FTVFUND_GRNT_CODE`, effective-dated. State, tuition and indirect-cost-recovery funds have no grant.
3. **Grant end.** `FRBGRNT` project end and budget end, plus the sponsor award ID, which is the same FAIN or NIH core project number this module pulls. The query uses the **earlier** of the internal and public end dates, and counts positions where the two disagree as a data-quality signal.
4. **Position grain (internal only).** The share of each position's pay that ends in each fiscal quarter. A position is "at risk" if 50% or more of its pay is on grants ending in that quarter. The query also sums funded FTE and salary dollars ending.
5. **Publish only** campus × home department × employee class × quarter, suppressing cells with fewer than 5 positions. The k for people data is stricter than the k = 3 used for awards.

Column names for internal tables are **assumptions** to confirm with AITS and OBFS. Other caveats:
- **Cost share.** Positions charged to cost-share funds are invisible unless cost-share funds are linked to grants.
- **Effort.** Effort certification can differ from payroll distribution. Retroactive salary transfers move charges after the fact.
- **Bridge funding.** Departments often bridge salaries after a grant ends, so "at risk" means *a funding decision is needed*, not *a layoff*.
- **Legal review.** Any person-level list derived from this join is an employment-decision input under Illinois HB 3773 and needs review first. The design publishes aggregates only.

### Why no HR or data platform provides this join

- **HR and workforce-planning products** (Workday, Oracle, SAP SuccessFactors, Visier, and the others reviewed in the research doc) model positions and costs. They do not model a funding source's *end date* from sponsored-projects systems. Funding-source-aware position risk was absent from all the vendor material reviewed (G3 evidence).
- **Snowflake and Databricks** provide storage and compute, not the domain semantics. They do not provide:
  - Banner FOAPAL-to-grant logic.
  - Effective-dated labor distribution.
  - Entity resolution between a sponsor's award ID and public award registries.
  - The NIH budget-period-versus-project-end distinction.
  - The USAspending F001/F002 coding change.
  - Small-cell rules for people data.
- **Research-administration systems** (Kuali, Huron, InfoEd, Cayuse) know grant end dates but not position-level payroll distribution.
- **The data is split across three systems** (HR, Finance, sponsored projects) and two public registries that disagree. The value is in the join and its caveats, and that work is portable to any platform.

## 6. Federal policy context, 2025–2026

This was gathered by web search on 2026-11-06. Several items rest on secondary sources. `grants.nih.gov` and `uillinois.content.uillinois.edu` could not be opened from this session, so the claims attributed to them are unverified. The dashboard shows the same list with links.

- **NIH 15% indirect-cost cap (Feb 2025).** Permanently enjoined. The First Circuit affirmed on 2026-01-05, and no Supreme Court petition was filed by the April 2026 deadline. The FY2027 budget request reportedly proposes the cap again. Sources: [Holland & Knight](https://www.hklaw.com/en/insights/publications/2026/01/the-nih-proposed-15-percent-indirect-cost-rate-cap-is-out-for-now), [JD Supra](https://www.jdsupra.com/legalnews/first-circuit-affirms-a-lower-court-4163925/).
- **NSF 15% indirect-cost policy (NSF 25-034).** Reported as not implemented after the court rulings. The FY2026 appropriations act reportedly bars a 15% cap at NSF, NASA and NIST and keeps NSF near \$8.75B. Source: [Biophysical Society](https://www.biophysics.org/blog/bps-in-the-beltway-january-16-2026).
- **Grant terminations in 2025.** A University of Illinois System document (Oct 2025) reportedly lists remaining balances above \$21M on terminated UIUC awards and about \$9.3M at UIC. Sources: [U of I System PDF](https://uillinois.content.uillinois.edu/userfiles/servers/server_1240/file/erc/federal-relations/impact20u20of20i20executive20actions20oct202025.pdf) (not opened), [CU-CitizenAccess](https://cu-citizenaccess.org/2025/03/university-of-illinois-research-already-suffering-from-federal-funding-cuts-and-doge/). End dates in public data may lag terminations.
- **NIH multiyear (up-front) funding.** NIH is funding more competing awards up front, so similar dollars go to fewer awards. The FY2026 law caps multiyear obligations at the FY2025 level. Sources: [CRS IF13131](https://www.everycrsreport.com/reports/IF13131.html), [The Scientist](https://www.the-scientist.com/federal-research-grant-awards-fall-to-a-six-year-low-75078). This is consistent with the FY2025 drop in competing NIH awards at both campuses in RePORTER. The data does not establish the cause.
- **FY2027 continuing resolution.** FY2027 is operating under a CR; NIH notice [NOT-OD-26-131](https://grants.nih.gov/grants/guide/notice-files/NOT-OD-26-131.html) cites P.L. 119-103 (not opened). Non-competing continuations, the 310 projects in the budget-period cliff, are issued under CR rules.

## 7. Tests

`tests/test_sponsored.py` has 20 tests:
- **Date logic:** fiscal-quarter edges, quarter bounds, end buckets including the as-of day, placeholder dates and missing dates.
- **Deduplication:** USAspending duplicate rows and the exact-UEI filter; NIH `appl_id` deduplication; subproject exclusion and supplement roll-up.
- **Sum reconciliation:** quarter buckets plus the other buckets equal active totals; agency and department rows sum to the scope total; the campus views partition the "All" view.
- **Suppression:** the k rules, including complementary suppression.
- **Concentration:** HHI.
- **HR join SQL:** runs on synthetic rows; no person columns; uses the earlier end date; applies as-of filtering and k = 5.
- **Privacy:** no PI fields in artifacts, HTML or the raw NIH cache.
