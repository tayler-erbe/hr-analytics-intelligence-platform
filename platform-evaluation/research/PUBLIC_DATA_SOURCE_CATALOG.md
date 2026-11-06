# Public HR / Workforce Data Sources: University of Illinois System

> **Verification status (added 2026-11-06 after acquisition):** this catalog was compiled by web search while government hosts were blocked, so many direct file URLs below were marked unverified. The lake acquisition run then confirmed by download the O*NET 31.0 database and O*NET-SOC crosswalk, IPEDS 2023/2024 HR and directory files, QCEW annual slices, Census LEHD QWI Illinois files, Indeed Hiring Lab files and Anthropic Economic Index files. See `../lake/sources.json` and `../lake/manifests/acquisition_manifest.json` for exact URLs, HTTP status, bytes and SHA-256. Facts established then: O*NET 31.0 is published; IPEDS S/SAL/EAP 2024 files return 404, so 2023 is the latest HR collection on the server; QWI Illinois files carry only all-ownership code A00 at NAICS 4-digit; BLS www/download hosts return HTTP 403 without a contact User-Agent; the Census API now requires a key.


Research date: 2026-11-06. Scope: public, freely downloadable data for higher-ed HR and workforce benchmarking. Internal HR data is out of scope. Companion machine-readable file: `public_data_source_catalog.json`, which uses the requested fields plus one extra array, `unverified_urls`.

## How the URLs were checked

This session's network allowlist blocked direct fetches of most hosts. The blocked hosts include bls.gov, onetcenter.org, nces.ed.gov, census.gov, lehd and huggingface.co. GitHub was reachable.
- **`urls`**: the page appeared in live search results as an existing URL, or it was fetched directly. Direct fetches covered the GitHub repos and their raw file paths.
- **`unverified_urls`**: these were built from a documented pattern, such as the IPEDS `datacenter/data/{FILE}.zip` pattern (confirmed from downloader source code) or the QCEW `data.bls.gov/cew/data/api/{yr}/{qtr}/{slice}/{code}.csv` pattern (from BLS docs). Some were seen only on a third-party site, and a few are well-known file names. Each one needs a HEAD request before you rely on it.
- Before building ingestion, rerun the verification with a session that allows the hosts listed at the end.

## Institution identifiers (UNITID)

| Campus | UNITID | Status |
|---|---|---|
| University of Illinois Urbana-Champaign | 145637 | Not corroborated by search (no indexed page tied the ID). It matches prior knowledge; confirm in the IPEDS HD file |
| University of Illinois Chicago | 145600 | Corroborated (College Navigator-derived aggregator pages, DataUSA `profile/university/145600`) |
| University of Illinois Springfield | 148654 | Corroborated (`nces.ed.gov/collegenavigator/?id=148654` cited, DataUSA `profile/university/148654`) |

Confirm all three by filtering `HD{year}.csv` on `F1SYSCOD`/`F1SYSNAM` (the system identifier) during the first load.

## Canonical join spine

| Dimension | Canonical key | Bridges / notes |
|---|---|---|
| Occupation | **SOC 2018 6-digit** (`xx-xxxx`) | O*NET-SOC 2019 8-digit maps to SOC 2018 through the O*NET crosswalk (truncation is usually correct, but not always). Some OEWS/EP aggregate codes (e.g. `25-1000`, `xx-xxx0`) need a rollup table. IPEDS occupational categories map to SOC groups (IPEDS publishes this mapping). ESCO/ISCO-08 goes through the O*NET-ESCO crosswalk. Indeed sectors need a manual map. |
| Task / activity | O*NET `task_id`, `dwa_id`, `iwa_id`, `element_id` | Join Anthropic Economic Index (tasks) and Microsoft working-with-ai (IWAs) to occupations |
| Industry | **NAICS 2022** (`611310`/`6113` colleges & universities; `611300` OEWS industry; `61` sector) | QWI ownership A00/A05; QCEW `own_code` (2 = state govt); JOLTS uses its own industry codes (610000, 923000) |
| Geography | **FIPS** state `17` + county `17019` Champaign, `17031` Cook, `17167` Sangamon; **CBSA** `16580` Champaign-Urbana, `16980` Chicago-Naperville-Elgin, `44100` Springfield IL | IPEDS HD carries COUNTYCD and CBSA. OEWS uses CBSA codes for MSAs and its own codes for nonmetro areas. QWI uses county, metro and WIB. Indeed metro names need a CBSA lookup |
| Institution | **UNITID** | OPEID (PSEO, Title IV), NCSES inst_id plus HERD's IPEDS UNITID column, UEI (USAspending), NIH IPF/UEI. Keep a hand-curated `institution_xref` table |
| Time | `period_start`/`period_end` date plus a `period_type` (month/quarter/academic_year/fiscal_year/reference_date) | OEWS is a May reference. IPEDS HR counts staff as of Nov 1 of the collection year. The State of Illinois fiscal year ends Jun 30. NSF uses the institution's FY. CPI is monthly (deflate to a constant base). QWI and QCEW are calendar quarters |
| Vintage | `source_release` (e.g. `onet_30.3`, `oews_m2025`, `qwi_R2026Qx`) | Store with every row. Never overwrite a vintage; append new ones |

## Tiering

- **P0 (build first; core benchmarks):** O*NET database and crosswalks, OEWS (national/state/MSA/industry 611300), IPEDS HR (S, SAL, EAP) plus HD/EF/F, QCEW (NAICS 6113 for IL counties), QWI (higher-ed hires, separations and turnover for IL counties/metros), CPI.
- **P1 (enrichment and context):** BLS EP, JOLTS, BLS API v2, ACS, PSEO, NSF HERD, SURS reports, CUPA-HR public summaries, IBHE salary search, Anthropic Economic Index, Microsoft working-with-ai, Indeed postings tracker, FRED.
- **P2 (optional, restricted, or terms-limited):** USAspending, NIH RePORTER, IL Comptroller / Open Data salaries, U of I Gray Book, Lightcast Open Skills, ESCO, IL WARN, HigherEdJobs, Open Payrolls, ICCB salary report.

Person-level public salary sources (Comptroller, IBHE, Gray Book, Open Payrolls, NIH PIs) are public records, but this repo's rules say to publish only aggregates. Land them in a restricted zone and expose only aggregates.

## Catalog

### P0
#### O*NET Database (full, incl. Tasks, Work Activities, Technology Skills, Alternate Titles)  
`id: onet_db` | Publisher: O*NET Resource Center / US DOL ETA | API key: no
- **Format:** ZIP of tab-delimited text (also Excel, MySQL, Oracle, SQL Server; JSON/CSV/RDF dictionary renderings exist for 30.3)
- **Grain:** O*NET-SOC 2019 occupation (8-digit, e.g. 15-1252.00) x element (task/activity/skill/technology/title)
- **Join keys:** onetsoc_code, soc_2018 (first 7 chars), element_id, task_id, dwa_id, iwa_id, commodity_code (UNSPSC, Technology Skills)
- **Vintage:** 30.3 is the current release listed on database.html; a 31.0 release-notes page exists (208 occupations updated) - confirm whether 31.0 is live. 30.3 dropped 'Tools Used' and 'Work Values' and reorganised the content model.
- **License:** CC BY 4.0 (attribution to O*NET/USDOL ETA required)
- **Hosts:** www.onetcenter.org, onetcenter.org
- **URLs (found):**
  - <https://www.onetcenter.org/database.html>
  - <https://www.onetcenter.org/dictionary/30.3/json/>
  - <https://www.onetcenter.org/dictionary/30.3/csv/>
  - <https://www.onetcenter.org/dictionary/31.0/nt/appendix_updates.html>
  - <https://onetcenter.org/db_releases.html>
- **URLs (unverified - pattern/guess):**
  - `https://www.onetcenter.org/dl_files/database/db_30_3_text.zip`
  - `https://www.onetcenter.org/dl_files/database/db_31_0_text.zip`
- **Notes:** Core files: Occupation Data, Task Statements, Task Ratings, Work Activities, Tasks to DWAs, DWA/IWA Reference, Technology Skills, Alternate Titles, Sample of Reported Titles. Bulk zip needs no key; O*NET Web Services API (services.onetcenter.org) needs free registration. Direct zip URLs not verified (host unreachable from this session).
#### O*NET-SOC 2019 taxonomy and crosswalks (O*NET-SOC 2019<->2018 SOC, 2010<->2019, ESCO, military, CIP)  
`id: onet_soc_crosswalks` | Publisher: O*NET Resource Center | API key: no
- **Format:** CSV / XLSX
- **Grain:** occupation code pair
- **Join keys:** onetsoc_code, soc_2018, soc_2010, cip_2020
- **Vintage:** O*NET-SOC 2019 taxonomy (current)
- **License:** CC BY 4.0
- **Hosts:** www.onetcenter.org
- **URLs (found):**
  - <https://www.onetcenter.org/database.html>
- **URLs (unverified - pattern/guess):**
  - `https://www.onetcenter.org/taxonomy/2019/soc.html`
  - `https://www.onetcenter.org/crosswalks.html`
  - `https://www.onetcenter.org/taxonomy/2019/soc/2019_to_SOC_Crosswalk.csv`
- **Notes:** Needed to roll 8-digit O*NET-SOC up to 6-digit SOC 2018 used by OEWS/EP. BLS also publishes an O*NET-SOC -> National Employment Matrix/OOH crosswalk on bls.gov/emp/data/occupational-data.htm.
#### BLS Occupational Employment and Wage Statistics (OEWS) - national, state, metro/nonmetro, industry-specific incl. NAICS 611300  
`id: bls_oews` | Publisher: US BLS | API key: no
- **Format:** ZIP of XLSX (per-geo/per-industry), plus flat tab-delimited time.series/oe
- **Grain:** year (May reference) x area (nat/state/MSA/nonmetro) x 6-digit SOC 2018 [x NAICS 2022 for industry files, x ownership for 611300_2/_3/_5 views]
- **Join keys:** occ_code (SOC 2018), area (FIPS state / CBSA / BLS nonmetro code), naics, own_code, year
- **Vintage:** May 2025 (released May 2026; MB3 model-based, 2022 NAICS, ~830 occupations). May 2026 expected spring 2027.
- **License:** US federal public domain
- **Hosts:** www.bls.gov, download.bls.gov
- **URLs (found):**
  - <https://www.bls.gov/oes/tables.htm>
  - <https://www.bls.gov/oes/2025/may/oes_tec.htm>
  - <https://download.bls.gov/pub/time.series/oe/>
  - <https://download.bls.gov/pub/time.series/oe/oe.txt>
  - <https://www.bls.gov/oes/2024/may/area_definitions_m2024.xlsx>
  - <https://www.bls.gov/oes/current/611300_5.htm>
  - <https://www.bls.gov/oes/2022/may/naics4_611300.htm>
- **URLs (unverified - pattern/guess):**
  - `https://www.bls.gov/oes/special-requests/oesm25nat.zip (seen only in a third-party lock file)`
  - `https://www.bls.gov/oes/special-requests/oesm25st.zip`
  - `https://www.bls.gov/oes/special-requests/oesm25ma.zip`
  - `https://www.bls.gov/oes/special-requests/oesm25in4.zip`
  - `https://www.bls.gov/oes/special-requests/oesm25all.zip`
  - `https://www.bls.gov/oes/current/naics4_611300.htm`
- **Notes:** Industry files exist only nationally (no state x industry). 611300 = Colleges, Universities and Professional Schools, with ownership splits (private, state govt, local govt). Relevant MSAs: Champaign-Urbana (16580), Chicago-Naperville-Elgin (16980), Springfield IL (44100). BLS blocks default user agents: send a User-Agent with contact email for download.bls.gov.
#### BLS QCEW open data CSV slices (NAICS 6113, Illinois counties)  
`id: bls_qcew` | Publisher: US BLS | API key: no
- **Format:** CSV (one file per year/qtr/slice); older years as zipped bulk files
- **Grain:** year x qtr (or 'a' annual) x area_fips x own_code x industry_code x agglvl_code
- **Join keys:** area_fips (county FIPS 17019 Champaign, 17031 Cook, 17167 Sangamon, 17000 IL), industry_code (NAICS), own_code (2=state govt, 3=local, 5=private), year, qtr
- **Vintage:** open-data slices cover most recent 5 years; quarterly with ~5-6 month lag
- **License:** US federal public domain
- **Hosts:** data.bls.gov, www.bls.gov
- **URLs (found):**
  - <https://www.bls.gov/cew/additional-resources/open-data/csv-data-slices.htm>
  - <https://www.bls.gov/cew/additional-resources/open-data/home.htm>
  - <https://www.bls.gov/cew/additional-resources/open-data/sample-code.htm>
  - <https://www.bls.gov/cew/data.htm>
- **URLs (unverified - pattern/guess):**
  - `https://data.bls.gov/cew/data/api/2025/a/area/17019.csv`
  - `https://data.bls.gov/cew/data/api/2025/a/area/17031.csv`
  - `https://data.bls.gov/cew/data/api/2025/a/area/17167.csv`
  - `https://data.bls.gov/cew/data/api/2025/1/industry/6113.csv`
  - `https://data.bls.gov/cew/data/api/2025/a/industry/6113.csv`
- **Notes:** URL pattern from BLS docs: https://data.bls.gov/cew/data/api/{year}/{qtr}/{industry|area|size}/{code}.csv (data.bls.gov replaces older bls.gov path). University of Illinois campuses are state-government owned (own_code 2); county x 6113 x own 2 cells are often disclosure-suppressed - expect disclosure_code 'N'.
#### BLS Consumer Price Index (CPI-U national and Chicago area) for real-wage adjustment  
`id: bls_cpi` | Publisher: US BLS | API key: no
- **Format:** tab-delimited flat files
- **Grain:** month (and annual avg) x area x item
- **Join keys:** series_id (CUUR0000SA0 US city avg NSA), year, period
- **Vintage:** monthly
- **License:** US federal public domain
- **Hosts:** download.bls.gov, www.bls.gov
- **URLs (found):**
  - <https://download.bls.gov/pub/time.series/cu/cu.txt>
  - <https://www.bls.gov:443/cpi/factsheets/cpi-series-ids.htm>
- **URLs (unverified - pattern/guess):**
  - `https://download.bls.gov/pub/time.series/cu/cu.data.1.AllItems`
  - `https://download.bls.gov/pub/time.series/cu/cu.series`
- **Notes:** Chicago-Naperville-Elgin all-items series ID believed to be CUURS23ASA0 - unverified, confirm in cu.series. Champaign/Springfield have no local CPI; use Midwest size-class series (CUUR0200SA0 region) - unverified.
#### IPEDS Complete Data Files - Human Resources (S, SAL, EAP)  
`id: ipeds_hr` | Publisher: NCES / US Dept of Education | API key: no
- **Format:** ZIP of CSV (+ _Dict.zip XLSX dictionary; Access DB alternative)
- **Grain:** UNITID x collection year x staff category (occupation/faculty status/rank/gender/race) [x contract length for SAL]
- **Join keys:** UNITID, collection_year, occupational category (IPEDS SOC-based), ARANK
- **Vintage:** 2024-25 collection (Nov 1 2024 staff) final ~Sept 2026; 2025-26 (Nov 1 2025) provisional ~July 2026 - confirm on release schedule.
- **License:** US federal public domain
- **Hosts:** nces.ed.gov
- **URLs (found):**
  - <https://nces.ed.gov/ipeds/datacenter/>
  - <https://nces.ed.gov/IPEDS/help/complete-data-files>
  - <https://nces.ed.gov/ipeds/survey-components/data-release-schedule>
  - <https://nces.ed.gov/ipeds/use-the-data/download-access-database/>
- **URLs (unverified - pattern/guess):**
  - `https://nces.ed.gov/ipeds/datacenter/data/S2024_SIS.zip`
  - `https://nces.ed.gov/ipeds/datacenter/data/S2024_IS.zip`
  - `https://nces.ed.gov/ipeds/datacenter/data/S2024_NH.zip`
  - `https://nces.ed.gov/ipeds/datacenter/data/S2024_OC.zip`
  - `https://nces.ed.gov/ipeds/datacenter/data/SAL2024_IS.zip`
  - `https://nces.ed.gov/ipeds/datacenter/data/SAL2024_NIS.zip`
  - `https://nces.ed.gov/ipeds/datacenter/data/EAP2024.zip`
- **Notes:** URL pattern confirmed from btskinner/downloadipeds source: https://nces.ed.gov/ipeds/datacenter/data/{FILE}.zip and {FILE}_Dict.zip. File codes from memory, confirm in the Complete Data Files list. Provisional files carry an _RV suffix when revised. Peer set: UIUC 145637, UIC 145600, UIS 148654.
#### IPEDS Complete Data Files - HD directory, EF/EFFY enrollment, F finance  
`id: ipeds_core` | Publisher: NCES / US Dept of Education | API key: no
- **Format:** ZIP of CSV
- **Grain:** UNITID x year [x enrollment level/race/sex or finance line]
- **Join keys:** UNITID, OPEID, FIPS (state/county in HD), CBSA (in HD), year
- **Vintage:** HD 2025 provisional likely available; F FY2024 (F2324) - confirm.
- **License:** US federal public domain
- **Hosts:** nces.ed.gov
- **URLs (found):**
  - <https://nces.ed.gov/ipeds/datacenter/>
  - <https://nces.ed.gov/IPEDS/help/complete-data-files>
- **URLs (unverified - pattern/guess):**
  - `https://nces.ed.gov/ipeds/datacenter/data/HD2024.zip`
  - `https://nces.ed.gov/ipeds/datacenter/data/EF2024A.zip`
  - `https://nces.ed.gov/ipeds/datacenter/data/EFFY2024.zip`
  - `https://nces.ed.gov/ipeds/datacenter/data/F2324_F1A.zip`
- **Notes:** HD carries COUNTYCD, CBSA, CARNEGIE, F1SYSCOD (system id) - this is the bridge from UNITID to FIPS/CBSA. Public institutions use F*_F1A (GASB). Historical 1980-2023 mirror on DataLumos (www.datalumos.org) if NCES availability changes.
#### Census LEHD Quarterly Workforce Indicators (hires, separations, turnover, earnings)  
`id: census_qwi` | Publisher: US Census Bureau (LEHD) | API key: no
- **Format:** gzip CSV; JSON API
- **Grain:** quarter x geography (state/county/metro/WIB) x NAICS (sector/3/4-digit; 5/6-digit added Jan 2026) x ownership x demographic (sex*age, sex*education, race/ethnicity) [x firm age/size]
- **Join keys:** geography (FIPS county / CBSA), industry (NAICS), ownercode (A00 = state+local govt+private, A05 = private only; confirm in label_ownercode.csv), year, quarter, sex, agegrp, education
- **Vintage:** quarterly releases; R2025Q2 directory observed; NAICS 5/6 expansion Jan-Feb 2026; data lag ~3 quarters
- **License:** US federal public domain
- **Hosts:** lehd.ces.census.gov, ledextract.ces.census.gov, api.census.gov
- **URLs (found):**
  - <https://lehd.ces.census.gov/data/qwi/R2025Q2/ri/?C=S&O=D>
  - <https://lehd.ces.census.gov/data/qwi_national_beta.html>
  - <https://lehd.ces.census.gov/data/schema/V4.11.1/lehd_csv_naming.html>
  - <https://api.census.gov/data/timeseries/qwi/se>
  - <https://census.gov/data/developers/data-sets/qwi.html>
  - <https://ledextract.ces.census.gov/>
  - <https://lehd.ces.census.gov/announcements.html>
- **URLs (unverified - pattern/guess):**
  - `https://lehd.ces.census.gov/data/qwi/latest_release/il/`
  - `https://lehd.ces.census.gov/data/qwi/latest_release/il/qwi_il_sa_f_gc_n4_oslp_u.csv.gz`
  - `https://lehd.ces.census.gov/data/qwi/latest_release/il/qwi_il_se_f_gm_n4_oslp_u.csv.gz`
  - `https://api.census.gov/data/timeseries/qwi/sa`
- **Notes:** Best public source for higher-ed attrition benchmarks: HirA, Sep, TurnOvrS, EarnHirNS for NAICS 6113 in Champaign/Cook/Sangamon counties, using ownercat 'oslp' (A00, all ownership incl. state/local govt) vs 'op' (A05, private); public-sector rows are only derivable as A00 minus A05 and may be noisy. File naming: qwi_[geo]_[demo]_[fas]_[geocat]_[indcat]_[ownercat]_[sa].csv.gz. API key optional (recommended for volume). Also consider J2J job-to-job flows under /data/j2j/.

### P1
#### BLS Employment Projections - occupation tables & National Employment Matrix  
`id: bls_ep` | Publisher: US BLS | API key: no
- **Format:** XLSX (tables also HTML)
- **Grain:** projection decade x National Employment Matrix occupation (SOC-based) [x NEM industry]
- **Join keys:** soc_code / NEM occupation code, nem_industry_code (NAICS-based), base_year, projection_year
- **Vintage:** 2024-34 confirmed (832 detailed occupations). 2025-35 normally released ~September 2026 - check.
- **License:** US federal public domain
- **Hosts:** www.bls.gov
- **URLs (found):**
  - <https://www.bls.gov/emp/data/occupational-data.htm>
  - <https://www.bls.gov/emp/data.htm>
  - <https://www.bls.gov/emp/tables/emp-by-detailed-occupation.htm>
  - <https://www.bls.gov/emp/tables/occupational-separations-and-openings.htm>
  - <https://www.bls.gov/emp/tables/industry-occupation-matrix-industry.htm>
  - <https://www.bls.gov/emp/tables/educational-attainment.htm>
  - <https://www.bls.gov/emp/tables/top-skills-by-detailed-occupation.htm>
- **URLs (unverified - pattern/guess):**
  - `https://www.bls.gov/emp/ind-occ-matrix/occupation.xlsx`
  - `https://www.bls.gov/emp/ind-occ-matrix/matrix.xlsx`
- **Notes:** Separations/openings table gives labor-force-exit and occupational-transfer rates useful as attrition priors. National only.
#### BLS Job Openings and Labor Turnover Survey (national industry incl. education; state estimates)  
`id: bls_jolts` | Publisher: US BLS | API key: no
- **Format:** tab-delimited flat files; API series
- **Grain:** month x industry (national) or month x state (total nonfarm) x data element (JO/HI/QU/LD/TS) x level|rate
- **Join keys:** series_id, industry_code (JOLTS NAICS-based, e.g. 610000 educational services, 923000 state&local govt education), state_code (FIPS), year, period
- **Vintage:** monthly; state release July 2026 seen (archives/jltst_07222026)
- **License:** US federal public domain
- **Hosts:** download.bls.gov, www.bls.gov
- **URLs (found):**
  - <https://www.bls.gov/news.release/archives/jltst_07222026.htm>
- **URLs (unverified - pattern/guess):**
  - `https://download.bls.gov/pub/time.series/jt/`
  - `https://download.bls.gov/pub/time.series/jt/jt.series`
  - `https://www.bls.gov/jlt/jlt_statedata.htm (cited in a state slide deck)`
- **Notes:** State JOLTS are model-based and essentially total-nonfarm/supersector; there is no Illinois x higher-ed series - use QWI for that. National 'state and local government education' is the closest public-university benchmark.
#### BLS Public Data API v2  
`id: bls_api_v2` | Publisher: US BLS | API key: **yes**
- **Format:** JSON (POST/GET)
- **Grain:** series_id x period
- **Join keys:** series_id
- **Vintage:** live
- **License:** US federal public domain
- **Hosts:** api.bls.gov, data.bls.gov
- **URLs (found):**
  - <https://www.bls.gov/developers/api_faqs.htm>
  - <https://www.bls.gov/bls/api_features.htm>
- **URLs (unverified - pattern/guess):**
  - `https://api.bls.gov/publicAPI/v2/timeseries/data/`
  - `https://data.bls.gov/registrationEngine/`
- **Notes:** Free registration key (renew yearly). v2: 500 queries/day, 50 series/query, 20 years/query; unregistered 25/day. HTTP 429 on overage. Prefer flat files on download.bls.gov for bulk loads.
#### Census American Community Survey (API) - labor market context  
`id: census_acs` | Publisher: US Census Bureau | API key: **yes**
- **Format:** JSON (API)
- **Grain:** geography (county/CBSA/place/tract) x vintage x table variable
- **Join keys:** state FIPS 17, county FIPS, CBSA (16580/16980/44100), year, variable (e.g. S2401 occupation, B24010, B20017)
- **Vintage:** 2020-2024 5-year (released Dec 2025); 2025 1-year typically Sept 2026 - confirm.
- **License:** US federal public domain
- **Hosts:** api.census.gov, www.census.gov
- **URLs (found):**
  - <https://www.census.gov/data/developers/data-sets/acs-5year.2011.html>
  - <https://api.census.gov/data/key_signup.html>
- **URLs (unverified - pattern/guess):**
  - `https://api.census.gov/data/2024/acs/acs5`
  - `https://api.census.gov/data/2024/acs/acs5/subject`
  - `https://api.census.gov/data/2025/acs/acs1`
- **Notes:** Key requirement per Census guidance seen in search; key is free. 50 variables/call limit.
#### Census Post-Secondary Employment Outcomes (PSEO) earnings & flows  
`id: census_pseo` | Publisher: US Census Bureau (LEHD) | API key: no
- **Format:** CSV (gz) + label files
- **Grain:** institution x CIP program x degree level x grad cohort [x NAICS sector / geography for flows]
- **Join keys:** institution (OPEID-based; map to UNITID via IPEDS HD), cipcode, degree_level, grad_cohort, industry (NAICS sector), geography
- **Vintage:** annual; Aug 2026 partner expansion announced
- **License:** US federal public domain
- **Hosts:** lehd.ces.census.gov, www.census.gov
- **URLs (found):**
  - <https://www.census.gov/data/experimental-data-products/post-secondary-employment-outcomes.html>
  - <https://lehd.ces.census.gov/data/pseo_experimental.html>
  - <https://lehd.ces.census.gov/doc/PSEOTechnicalDocumentation.pdf>
  - <https://www.pb.uillinois.edu/what-we-do/other-system-services/pseo.cfm>
  - <https://www.census.gov/newsroom/press-releases/2026/pseo-partners.html>
- **URLs (unverified - pattern/guess):**
  - `https://lehd.ces.census.gov/data/pseo/latest_release/all/`
  - `https://lehd.ces.census.gov/data/pseo/latest_release/il/`
  - `https://lehd.ces.census.gov/data/pseo_explorer.html`
- **Notes:** UI System campuses participate via IBHE. Graduate earnings/destination industry - context for talent pipeline, not staff HR.
#### NSF NCSES Higher Education Research and Development (HERD) Survey  
`id: nsf_herd` | Publisher: NSF NCSES | API key: no
- **Format:** public-use files (CSV/zip, confirm) + data tables XLSX
- **Grain:** institution x fiscal year x R&D source/field/expense type (incl. R&D personnel headcounts)
- **Join keys:** inst_id (NCSES), ipeds_unitid (column in public file - confirm), fiscal_year
- **Vintage:** FY2024 released 2025-12-23; FY2025 scheduled 2026-11-24
- **License:** US federal public domain
- **Hosts:** ncses.nsf.gov
- **URLs (found):**
  - <https://ncses.nsf.gov/explore-data/microdata/higher-education-research-development>
  - <https://ncses.nsf.gov/surveys/higher-education-research-development/2024>
  - <https://ncses.nsf.gov/pubs/ncses26003>
  - <https://ncses.nsf.gov/schedule-of-release-dates>
- **Notes:** R&D personnel (researchers, postdocs) counts per institution - useful for research-workforce benchmarks across UIUC/UIC.
#### IBHE public university salary search (PA 96-266) and IBHE data/Data Book  
`id: ibhe_salary` | Publisher: Illinois Board of Higher Education | API key: no
- **Format:** web search UI (export unconfirmed); PDF/XLSX reports
- **Grain:** employee x institution x year (base salary + benefits)
- **Join keys:** institution (map to UNITID), position title, year
- **Vintage:** annual
- **License:** Illinois public records
- **Hosts:** salarysearch.ibhe.org, www.ibhe.org
- **URLs (found):**
  - <https://salarysearch.ibhe.org>
  - <https://www.pb.uillinois.edu/what-we-do/institutional-research-and-analytical-studies/students/ibhe-reporting.cfm>
- **URLs (unverified - pattern/guess):**
  - `https://www.ibhe.org/`
- **Notes:** Covers all IL public universities - enables peer comparisons (ISU, NIU, SIU etc.). Person-level; aggregate before publishing; check terms before bulk scraping.
#### Illinois State Universities Retirement System (SURS) ACFR, actuarial valuation, experience study  
`id: surs` | Publisher: SURS | API key: no
- **Format:** PDF (tables need extraction)
- **Grain:** system x fiscal year (membership counts, retirements, withdrawal/termination rates by age/service)
- **Join keys:** fiscal_year, employer (statistical section lists UI campuses)
- **Vintage:** FY2025 (valuation dated 2025-10-24); experience study 2020-2023
- **License:** Public report
- **Hosts:** surs.org, publicplansdata.org
- **URLs (found):**
  - <https://surs.org/news-publications/publications/annual-financial-report/>
  - <https://surs.org/wp-content/uploads/SURS-Actuarial-Valuation-Report-2025.pdf>
  - <https://surs.org/wp-content/uploads/Annual-Report-2025-Summary.pdf>
  - <https://surs.org/wp-content/uploads/experience_study_2024.pdf>
  - <https://publicplansdata.org/reports/IL_IL-SURS_CAFR_2017_35.pdf>
- **Notes:** Experience study gives actuarial turnover/retirement rates - strong attrition priors for IL university staff. Public Plans Data has historic CAFRs.
#### CUPA-HR public survey summaries (workforce pay increases etc.)  
`id: cupahr_public` | Publisher: CUPA-HR | API key: no
- **Format:** HTML/PDF summaries (manually transcribed)
- **Grain:** national x employee group x academic year (median pay increase %)
- **Join keys:** academic_year, employee_group (admin/professional/faculty/staff)
- **Vintage:** 2025-26
- **License:** Copyrighted; public summaries only - cite, do not redistribute raw; DataOnDemand is paid
- **Hosts:** www.cupahr.org, cupahr.org
- **URLs (found):**
  - <https://www.cupahr.org/resource/workforce-pay-increases/>
  - <https://cupahr.org/research-data/about-our-surveys/faculty-survey/>
  - <https://cupahr.org/research-data/about-our-surveys/staff-methodology/>
- **Notes:** 2025-26: tenure-track faculty lowest raise (1.8%); all groups below 2019-20 real pay. Microdata out of scope.
#### Anthropic Economic Index  
`id: anthropic_econ_index` | Publisher: Anthropic | API key: no
- **Format:** CSV/JSON files per dated release folder (git LFS)
- **Grain:** O*NET task / SOC occupation x release (usage share, automation vs augmentation); some geo cuts
- **Join keys:** onet_task_text / task_id, soc_code, release_date, country/state (geo releases)
- **Vintage:** releases incl. 2026-01-15 and 2026-03-24 seen via mirror README; later releases possible
- **License:** CC BY 4.0
- **Hosts:** huggingface.co, cdn-lfs.huggingface.co (LFS, unverified), cas-bridge.xethub.hf.co (Xet storage, unverified)
- **URLs (found):**
  - <https://huggingface.co/datasets/Anthropic/EconomicIndex>
  - <https://cran.r-project.org/web/packages/aieconindex/index.html>
- **Notes:** huggingface.co was unreachable from this session; facts taken from mirror README and CRAN aieconindex docs.
#### Microsoft Research 'Working with AI' occupational AI applicability  
`id: ms_working_with_ai` | Publisher: Microsoft Research | API key: no
- **Format:** CSV
- **Grain:** SOC 2018 detailed occupation (785) and O*NET IWA
- **Join keys:** SOC Code, IWA (O*NET IWA id)
- **Vintage:** paper v6 (2025-2026); data from 2024 Bing Copilot conversations
- **License:** CC BY 4.0
- **Hosts:** github.com, raw.githubusercontent.com
- **URLs (found):**
  - <https://github.com/microsoft/working-with-ai>
  - <https://raw.githubusercontent.com/microsoft/working-with-ai/main/ai_applicability_scores.csv>
  - <https://raw.githubusercontent.com/microsoft/working-with-ai/main/soc_metrics.csv>
  - <https://raw.githubusercontent.com/microsoft/working-with-ai/main/iwa_metrics.csv>
  - <https://raw.githubusercontent.com/microsoft/working-with-ai/main/soc_iwa_weights.csv>
  - <https://raw.githubusercontent.com/microsoft/working-with-ai/main/soc_to_iwas.csv>
  - <https://arxiv.org/abs/2507.07935>
- **Notes:** Raw file URLs derived from repo listing (branch main); repo page fetched directly.
#### Indeed Hiring Lab job_postings_tracker  
`id: indeed_postings` | Publisher: Indeed Hiring Lab | API key: no
- **Format:** CSV
- **Grain:** day x geo (US/state/metro >=500k) [x Indeed occupational sector]
- **Join keys:** date, state (name/abbrev -> FIPS), metro (CBSA name/code - confirm), display_name (Indeed sector)
- **Vintage:** daily series, refreshed weekly
- **License:** CC BY 4.0 (cite Indeed Hiring Lab)
- **Hosts:** github.com, raw.githubusercontent.com
- **URLs (found):**
  - <https://github.com/hiring-lab/job_postings_tracker>
  - <https://raw.githubusercontent.com/hiring-lab/job_postings_tracker/master/US/aggregate_job_postings_US.csv>
  - <https://raw.githubusercontent.com/hiring-lab/job_postings_tracker/master/US/job_postings_by_sector_US.csv>
  - <https://raw.githubusercontent.com/hiring-lab/job_postings_tracker/master/US/state_job_postings_us.csv>
  - <https://raw.githubusercontent.com/hiring-lab/job_postings_tracker/master/US/metro_job_postings_us.csv>
- **Notes:** Index (Feb 2020=100), not counts. Sector taxonomy is Indeed's own; map to SOC manually (sector-job-title-examples.csv helps). Champaign/Springfield metros below 500k threshold - only Chicago metro available.
#### FRED API (St. Louis Fed)  
`id: fred` | Publisher: Federal Reserve Bank of St. Louis | API key: **yes**
- **Format:** JSON/XML API
- **Grain:** series x observation date
- **Join keys:** series_id, date
- **Vintage:** live
- **License:** FRED terms of use; some series third-party copyrighted
- **Hosts:** api.stlouisfed.org, fred.stlouisfed.org
- **URLs (found):**
  - <https://fred.stlouisfed.org/docs/api/fred/>
  - <https://fred.stlouisfed.org/docs/api/fred/v2/>
  - <https://fred.stlouisfed.org/docs/api/api_key.html>
- **URLs (unverified - pattern/guess):**
  - `https://api.stlouisfed.org/fred/series/observations`
- **Notes:** 32-char key. Convenient for CPI, IL/MSA unemployment (LAUS), CES state education employment. v2 API offers bulk retrieval.

### P2
#### USAspending.gov API v2 and award bulk downloads  
`id: usaspending` | Publisher: US Treasury (Bureau of the Fiscal Service) | API key: no
- **Format:** JSON API; zipped CSV bulk
- **Grain:** award / transaction x recipient x fiscal year
- **Join keys:** recipient_uei, duns (pre-2022), awarding_agency, cfda/assistance listing, fiscal_year, recipient county FIPS
- **Vintage:** live (daily)
- **License:** US federal public domain
- **Hosts:** api.usaspending.gov, files.usaspending.gov
- **URLs (found):**
  - <https://api.usaspending.gov/docs/endpoints>
- **URLs (unverified - pattern/guess):**
  - `https://api.usaspending.gov/api/v2/bulk_download/awards/`
  - `https://files.usaspending.gov/award_data_archive/`
- **Notes:** Federal grants funding positions (sponsored-research workforce proxy). Map UEI to UNITID manually for the three campuses.
#### NIH RePORTER API v2 / ExPORTER  
`id: nih_reporter` | Publisher: NIH | API key: no
- **Format:** JSON (POST); ExPORTER CSV zips
- **Grain:** project x fiscal year (PIs, org, award amount)
- **Join keys:** org_ipf_code / org_uei, fiscal_year, appl_id
- **Vintage:** live (weekly)
- **License:** US federal public domain
- **Hosts:** api.reporter.nih.gov, reporter.nih.gov
- **URLs (found):**
  - <https://api.reporter.nih.gov/>
  - https://api.reporter.nih.gov/documents/Sample RePORTER API Request Matching ExPORTER Project Files.pdf
- **URLs (unverified - pattern/guess):**
  - `https://api.reporter.nih.gov/v2/projects/search`
  - `https://reporter.nih.gov/exporter`
- **Notes:** No auth; max ~15k records per search (paginate by FY/org). Contains named PIs - aggregate before publishing.
#### Illinois Comptroller state employee salary database / Illinois Open Data state employee data  
`id: il_comptroller_salary` | Publisher: Illinois Office of the Comptroller; Illinois ITAP | API key: no
- **Format:** web search UI; datasets on state Open Data Portal (CSV/Socrata-style API - confirm)
- **Grain:** employee x agency x year (person-level)
- **Join keys:** agency, position title, year
- **Vintage:** current + prior years
- **License:** Illinois public records; terms on portal (confirm)
- **Hosts:** illinoiscomptroller.gov, itap.illinois.gov, data.illinois.gov
- **URLs (found):**
  - <https://illinoiscomptroller.gov/financial-reports-data/data-sets-portals/salary-database>
  - <https://itap.illinois.gov/state-employee-data>
- **URLs (unverified - pattern/guess):**
  - `https://data.illinois.gov/`
- **Notes:** Person-level public records. University employees may not be covered (universities run own payrolls) - confirm. Ingest only aggregates into shared lake.
#### University of Illinois Board of Trustees Gray Book (academic & administrative appointments)  
`id: uillinois_graybook` | Publisher: University of Illinois System BOT | API key: no
- **Format:** HTML pages per unit (+ DOCX)
- **Grain:** appointment (named employee) x unit x year (present vs proposed salary, FTE, tenure)
- **Join keys:** unit code, job title, year
- **Vintage:** 2025-26 (dated 2025-08-18); 2026-27 likely published Aug/Sep 2026 - check
- **License:** Public record
- **Hosts:** www.bot.uillinois.edu, www.trustees.uillinois.edu
- **URLs (found):**
  - <https://www.bot.uillinois.edu/gray-book>
  - <https://www.trustees.uillinois.edu/trustees/resources/25-26-Graybook/HD.html>
  - <https://www.trustees.uillinois.edu/trustees/resources/25-26-Graybook/SF.html>
  - <https://www.trustees.uillinois.edu/trustees/resources/25-26-Graybook/ZZ.html>
  - <https://www.trustees.uillinois.edu/trustees/resources/25-26-Gray-Book-System-Offices.docx>
  - <https://www.trustees.uillinois.edu/trustees/resources/24-25-Graybook/AM.html>
- **Notes:** Public but person-level and institution-specific; treat as restricted under project rules (aggregate only, keep off public presentation assets).
#### Lightcast Open Skills taxonomy  
`id: lightcast_open_skills` | Publisher: Lightcast | API key: **yes**
- **Format:** JSON API (OAuth client credentials)
- **Grain:** skill (id, name, type, category/subcategory)
- **Join keys:** skill_id, (Lightcast skill <-> O*NET/SOC mappings are paid)
- **Vintage:** taxonomy versioned (check /versions/latest)
- **License:** Open Skills license with attribution; free tier subject to approval (nonprofit/public-good)
- **Hosts:** lightcast.io, docs.lightcast.io, auth.emsicloud.com, emsiservices.com (unverified)
- **URLs (found):**
  - <https://lightcast.io/open-skills/access>
  - <https://docs.lightcast.io/lightcast-api/docs/api-access>
  - <https://docs.lightcast.io/lightcast-api/reference/overview-skills>
  - <https://docs.lightcast.io/lightcast-api/reference/overview-classification>
- **URLs (unverified - pattern/guess):**
  - `https://auth.emsicloud.com/connect/token`
  - `https://emsiservices.com/skills/versions/latest/skills`
- **Notes:** Conflicting reports: official docs describe free 'lightcast_open_free' scope (approval needed, 50 extraction calls/month, 5 req/s); third-party blog says API access is now contract-only. Verify before planning.
#### ESCO (European Skills, Competences, Qualifications and Occupations)  
`id: esco` | Publisher: European Commission | API key: no
- **Format:** CSV / ODS / SKOS-RDF (TTL) - download link emailed after form
- **Grain:** occupation (ISCO-08 based) x skill relations
- **Join keys:** esco_occupation_uri, isco_08, esco_skill_uri, (ESCO<->O*NET crosswalk: check O*NET crosswalks page)
- **Vintage:** v1.2.x (v1.2.1 referenced)
- **License:** EU reuse policy (free with attribution)
- **Hosts:** esco.ec.europa.eu, ec.europa.eu
- **URLs (found):**
  - <https://esco.ec.europa.eu/en/use-esco/download>
  - <https://esco.ec.europa.eu/en/structure-esco-downloadable-datasets>
  - <https://esco.ec.europa.eu/system/files/2024-05/V1.2%20Launch%20-%20ESCO%20SEC%20combined%20-%20final%20clean.pdf>
- **URLs (unverified - pattern/guess):**
  - `https://ec.europa.eu/esco/api`
- **Notes:** Download is email-gated, so automated pipeline needs a one-time manual fetch then mirror to object storage.
#### Illinois WARN notices  
`id: il_warn` | Publisher: Illinois Dept of Commerce & Economic Opportunity (DCEO) / IDES | API key: no
- **Format:** monthly XLSX/PDF reports (official, unconfirmed); aggregator CSV
- **Grain:** notice (employer x location x date x workers affected)
- **Join keys:** employer name, city/county -> FIPS, notice_date
- **Vintage:** monthly
- **License:** Public record (official); aggregator terms vary
- **Hosts:** dceo.illinois.gov (unverified), approjects-warn-act-notices.static.hf.space
- **URLs (found):**
  - <https://approjects-warn-act-notices.static.hf.space/states/illinois.html>
- **URLs (unverified - pattern/guess):**
  - `https://dceo.illinois.gov/workforcedevelopment/warn.html`
- **Notes:** Official state file location not confirmed - only third-party aggregators surfaced. Low relevance for university workforce (public employers rarely file).
#### HigherEdJobs (terms + historical quarterly employment report)  
`id: higheredjobs` | Publisher: HigherEdJobs Inc. | API key: no
- **Format:** HTML/PDF reports
- **Grain:** national x quarter (posting trends + BLS employment)
- **Join keys:** quarter
- **Vintage:** quarterly reports seen 2015-2019; no current series found
- **License:** Proprietary; terms not verified - do not scrape
- **Hosts:** www.higheredjobs.com
- **URLs (found):**
  - <https://prnewswire.com/news-releases/higher-education-employment-suffers-large-decline-in-q3-2015-300184541.html>
- **URLs (unverified - pattern/guess):**
  - `https://www.higheredjobs.com/`
  - `https://www.higheredjobs.com/about/terms.cfm`
- **Notes:** Recommend exclusion from automated lake; reference only. Third-party scrapers exist but terms compliance is the user's responsibility.
#### Open Payrolls (Illinois)  
`id: openpayrolls` | Publisher: OpenPayrolls / OpenTheBooks-style aggregator | API key: no
- **Format:** HTML
- **Grain:** employee x employer x year
- **Join keys:** employer, year
- **Vintage:** through ~2024 (varies)
- **License:** Third-party; terms not verified - do not scrape
- **Hosts:** openpayrolls.com
- **URLs (found):**
  - <https://openpayrolls.com/state/illinois/page-500>
- **Notes:** Duplicates official sources (Comptroller/IBHE). Prefer primary sources.
#### ICCB community college salary report (peer context)  
`id: iccb_salary` | Publisher: Illinois Community College Board | API key: no
- **Format:** PDF
- **Grain:** community college x employee group x year
- **Join keys:** institution -> UNITID, year
- **Vintage:** FY2026 report (June 2026)
- **License:** Public report
- **Hosts:** www.iccb.org
- **URLs (found):**
  - <https://www.iccb.org/wp-content/uploads/2026/06/salaryrpt26.pdf>
  - <https://www.iccb.org/divisions/research-and-analytics/2024-data-book/section-ii-faculty-and-staff-data>
- **Notes:** Optional, not in original brief; Illinois public 2-year comparator.

## Network allowlist: distinct hostnames

- `api.bls.gov`
- `api.census.gov`
- `api.reporter.nih.gov`
- `api.stlouisfed.org`
- `api.usaspending.gov`
- `approjects-warn-act-notices.static.hf.space`
- `auth.emsicloud.com`
- `cas-bridge.xethub.hf.co`
- `cdn-lfs.huggingface.co`
- `cupahr.org`
- `data.bls.gov`
- `data.illinois.gov`
- `dceo.illinois.gov`
- `docs.lightcast.io`
- `download.bls.gov`
- `ec.europa.eu`
- `emsiservices.com`
- `esco.ec.europa.eu`
- `files.usaspending.gov`
- `fred.stlouisfed.org`
- `github.com`
- `huggingface.co`
- `illinoiscomptroller.gov`
- `itap.illinois.gov`
- `ledextract.ces.census.gov`
- `lehd.ces.census.gov`
- `lightcast.io`
- `nces.ed.gov`
- `ncses.nsf.gov`
- `onetcenter.org`
- `openpayrolls.com`
- `publicplansdata.org`
- `raw.githubusercontent.com`
- `reporter.nih.gov`
- `salarysearch.ibhe.org`
- `surs.org`
- `www.bls.gov`
- `www.bot.uillinois.edu`
- `www.census.gov`
- `www.cupahr.org`
- `www.higheredjobs.com`
- `www.ibhe.org`
- `www.iccb.org`
- `www.onetcenter.org`
- `www.trustees.uillinois.edu`

Also consider `services.onetcenter.org` (O*NET Web Services API, needs a key), `www2.census.gov` (ACS/LEHD bulk FTP-style mirror), `www.datalumos.org` (IPEDS historical mirror) and `arxiv.org` (paper). None of these four was verified as a data host.

## Gaps and cautions
- No public series covers Illinois higher-ed **JOLTS**. Use QWI (NAICS 6113, counties) for hires and separations, and SURS experience-study rates for actuarial turnover.
- QWI has no separate state-government ownership code. You can only derive public-sector figures as A00 minus A05, and the result may be noisy. QCEW county x 6113 x state-gov cells are often suppressed.
- OEWS industry tables are **national only**. They have no IL x 611300 cut.
- The release state of O*NET 31.0 is unconfirmed. A 31.0 release-notes page exists, but database.html still listed 30.3 in the search index.
- The Lightcast free tier may now be contract-only (sources conflict).
- HigherEdJobs and Open Payrolls: terms were not verified. Do not scrape them. Treat them as reference only.
- The official Illinois WARN file location was not found. Only aggregators surfaced.
- `download.bls.gov` rejects requests without a descriptive User-Agent (one that includes a contact email). Plan for this in the loader.
