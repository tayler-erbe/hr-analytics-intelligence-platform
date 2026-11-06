# Public EDW reference: University of Illinois HR tables

This folder records what **public** University of Illinois documents say about the EDW HR tables, their
columns and their code values. Every row cites a URL and a confidence grade. Nothing here comes from the
Data Cookbook, EDW metadata, real rows or any login-protected page. The material was gathered on
2026-11-06.

| File | Contents |
|---|---|
| `sources.yaml` | Source registry and download manifest: URL, document date, retrieval time (UTC), HTTP status, bytes, SHA-256 |
| `field_inventory.csv` / `.parquet` | 123 evidence rows covering 83 physical fields in 23 tables/views (most table names beyond the core HR tables are inferred), plus code-domain rows |
| `code_domains.yaml` | E-Class, P-Class character rules, tenure/rank, salary tables, flex year, place of employment, chart codes, FTE rules, job type/suffix, termination and job-change codes, earn-code families, benefit categories, with drift notes |
| `inventory_summary.json` | Counts by source type, confidence and physical-name evidence (written by the build) |
| `build_reference.py` | Holds the curated evidence. Writes the inventory, validates it, and with `--text-cache` checks every document excerpt verbatim |

```bash
cd platform-evaluation
python integration/edw_public_reference/build_reference.py                    # rebuild + validate
python integration/edw_public_reference/build_reference.py --text-cache DIR   # + verbatim excerpt check
```

## Methods

1. **Full documents.** These public PDFs on `nessie.uihr.uillinois.edu` were downloaded with plain `curl`
   and a normal User-Agent, then fully extracted with `pypdf` under `python -I`:
   - HR Reporting Concepts (2009-11-17);
   - E-Class job aid (2015-05-05);
   - Termination Codes (2014-01-27);
   - Rank and Tenure Codes (2008-03-12);
   - Job Change Reason Codes (2016).

   They were found through `WebSearch`. Plain keyword searches surfaced the nessie URLs of the termination,
   tenure and job-change aids (a `site:` search returned none). The E-Class aid's filename came from a hit
   on `www.hr.uillinois.edu`, and the same filename was fetched from nessie.
2. **KB articles.** Articles 120569, 120570, 120378, 120385, 120574, 120563, 120369, 118751, 158288 and
   75281 were fetched from `answers.uillinois.edu` with `curl`. Their HTML tables were parsed cell by cell
   with Python's `html.parser`. Article 50367 returns only its title to anonymous users, so nothing is
   cited from it.
3. **Search snippets.** About 35 targeted web searches covered physical models, logical models, release
   notes, universe guides, cube definitions and column names. A snippet is recorded only with the URL of
   the document it summarises, and it is never graded `high`. Four snippets reported by the requester
   (`req_*`) could not be reproduced in this session and are graded `low`:
   - PRR physical model;
   - RA physical model;
   - DS release notes 2005-05;
   - UIS gitlist SQL.
4. **Verification.**
   - All 88 excerpts from full documents and KB articles were found verbatim in the extracted text, after
     whitespace and table separators were normalised (`--text-cache`).
   - The downloaded copies are not committed. Re-fetch from the URL and compare the SHA-256.
5. **Not done.**
   - `uillinois.datacookbook.com` was not contacted.
   - The 403 bot blocks on `www.aits.uillinois.edu`, `aits.content.uillinois.edu` and `www.hr.uillinois.edu`
     were not bypassed. No headless browser, spoofed headers, mirrors or caches were used.
   - `dmi.illinois.edu` was refused by the proxy.

### Confidence and name basis

The grades work as follows:
- **high**: the physical name or code value is printed in a fully read document or KB article.
- **medium**: either of these holds:
  - the business field ("Job Detail FTE field") is stated in a full document and the physical name is inferred;
  - a verbatim name comes from a snippet that an independent source corroborates.
- **low**: a single snippet, a requester-reported snippet, or the v1 assumed name.

`notes` in each row carries `name_basis`:
- `verbatim`: the physical name is printed in the source.
- `inferred`: the name is built from EDW abbreviations seen verbatim elsewhere (`PERS`, `EMPEE`, `POSN`,
  `JOB_DETL`, `CLS`, `CD`, `DESC`, `IND`, `DT`, `NBR`, `PCT`, `SAL`, `CATGRY`).
- `v1_assumed`: there is no public name at all.
- `business_only`: a code domain with no column.

`first_seen_date` is the earliest document date among the sources that show the field. Undated snippets
use the retrieval date.

## What is confirmed, inferred, unknown

| Physical-name evidence (83 fields) | n | Examples |
|---|---:|---|
| Verbatim in a full document | 6 | `T_POSN_HIST.POSN_MIN_SAL`, `POSN_MAX_SAL`, `T_POSN_CLS_HIST.POSN_CLS_DESC`, `t_job_detl_hist.Job_detl_appt_pct`, `V_EMPEE_PERS_HIST_3.AGE`, `IPEDS_RACE_ETH_CATGRY_DESC` |
| Verbatim in snippets only | 12 | `EDW_PERS_ID`, `POSN_NBR`, `EMPEE_EFF_DT`, `EMPEE_EXP_DT`, `EMPEE_CUR_INFO_IND`, `ACTIVE_EMPEE_IND`, `PERS_CUR_INFO_IND`, `EMPEE_GROUP_CD/DESC`, `JOB_DETL_TIME_ENTRY_METHOD_CD`, `JOB_DETL_ENC_HOURS` (dropped 2008) |
| Inferred from a documented business name | 60 | `JOB_DETL_FTE`, `JOB_DETL_EFF_DT`, `JOB_DETL_SAL_TABLE_CD`, `POSN_BARGAIN_UNIT_CD`, `EMPEE_STATUS_CD`, `EMPEE_CLS_CD`, `COA_CD`, `HR_CAMPUS_CD`, `BENEFIT_CATGRY_CD` |
| No public name (v1 assumed kept) | 5 | `TERM_REASON_CD`, `SURS_RETIR_IND`, `FIRST_HIRE_DT`, `POSN_ORG_CD`, `JOB_CONTRACT_TYPE_CD` |

Of the 83 fields, 68 have at least one full-document or KB source and 15 rest on snippets alone.

**Confirmed (high).** These code domains are printed in full documents or KB articles:
- E-Class: 68 codes with groups and leave categories;
- the P-Class five-character structure for faculty/other academics, AP and students;
- tenure and rank codes;
- salary table codes by campus;
- civil-service flex-year codes (PFX08-11) and place-of-employment codes (LC/LS/LU/LCR/LUA);
- position descriptor codes;
- chart codes (1, 2, 4, 9);
- fund prefixes and earn-code families;
- termination and job-change reason codes;
- FTE rules: 37.5, 40 and 42 hours all equal 1 FTE, and actual FTE = FTE × appointment %;
- the primary/overload job type and the headcount exclusions.

**Confirmed table names.** `T_POSN_HIST` and `T_POSN_CLS_HIST` are verbatim in rc2009.
`V_JOB_DETL_HIST_1` is verbatim in a release-note snippet. Link rules from rc2009:
- position history ↔ job on position number + job suffix;
- payroll accounting detail (public) ↔ job on position number + job suffix.

**Inferred.** These are reasoned from patterns, not stated:
- Most physical column names (60).
- `_1` / `_3` / `_5` views as security tiers. This is inferred only from which fields appear in which
  variant: AGE and race are on `_3`, visa on `_5`.
- `T_EMPEE_HIST` as the base of `V_EMPEE_HIST_1`.
- `T_PAYR_ACCTG_DETL` as the payroll table name; rc2009 says "Payroll Accounting Detail Public Table".
- The termination analytic grouping.

**Unknown.**
- The effective-end convention (inclusive or exclusive), the open-end value, and whether
  recorded-version history exists.
- Code letters for job and position status; only descriptions are public.
- `EMPEE_GROUP_CD` values, real `HR_CAMPUS_CD` values, and the regular-pay earn code.
- Where termination reason and SURS fields live (`T_EMPEE_HIST_5` is asserted only by this repository's handoff).
- The org hierarchy table.
- How 5-digit civil-service P-Classes (e.g. 00581, 32881) relate to 4-digit SUCSS class codes.

### Document dates and drift

`rc2009` is from **2009**. It says some fields "are in the process of being added to the EDW", and
it still points to Banner Report Copy tables for budgeted FTE, step increases and descriptors. Later
public sources show the schema changing:
- `JOB_DETL_ENC_HOURS` was dropped in 2008.
- `EMPEE_GROUP_CD/DESC` were added to `V_JOB_DETL_HIST_1` in 2010.
- Person-history restricted views changed in 2016.

E-Class `CL/CM/DR/DS` were "Exempt C" in the 2015 job aid and are "INA N/E" with leave category 51 in the
2026 KB. Tenure codes L/M/T/X are in 2008 but not in 2026. Termination code TW appears after 2014. Treat
every inferred name as a hypothesis to test against current metadata.

## Gaps only the Data Cookbook or EDW metadata can fill (the Codex task)

Resolve these on the approved machine. Use `ALL_TAB_COLUMNS`, `ALL_COL_COMMENTS` and `ALL_CONSTRAINTS`,
or the Data Cookbook; see `CODEX_HANDOFF_EDW_PROFILING.md`.

1. **Exact physical names** for the 60 inferred columns and 5 unresolved ones. These matter most:
   - `JOB_DETL_EFF_DT/EXP_DT`;
   - `POSN_EFF_DT` vs `POSN_HIST_EFF_DT`;
   - `JOB_DETL_STATUS_CD`;
   - the job P-Class column on the job detail table;
   - the job-type / primary-job column and its table (`T_JOB_HIST`?);
   - `JOB_DETL_ANNUAL_SAL` and `JOB_DETL_FTE`;
   - `EMPEE_STATUS_CD`, `EMPEE_CLS_CD` and `HR_CAMPUS_CD`.
2. **Schema owner and base tables** behind `V_EMPEE_HIST_1`, `V_JOB_DETL_HIST_1` and `V_EMPEE_PERS_HIST_1`.
   Also what each numeric view suffix exposes, and whether row-level security applies.
3. **Effective-dating convention.** Is `*_EXP_DT` inclusive or exclusive, and what is the open-end value?
   How do `*_CUR_INFO_IND` values (Y/N/D?) relate to the dates? Is there any recorded-time / row-version
   history?
4. **Termination and retirement.** Which table/column holds the employee-level termination code (TD..TZ)
   and termination date. Whether a SURS retirement indicator, tier or service credit exists.
   What `T_EMPEE_HIST_5` actually contains.
5. **Code letters** for job status, position status (A/I/F/C?) and employee leave statuses, and
   `EMPEE_GROUP_CD` values.
6. **Position control.** Budgeted FTE and salary in the EDW (not Banner Report Copy), position org,
   position labor distribution table names, and the position class attribute table.
7. **Organization hierarchy** table and columns, and the link from HR org codes to C-FOAPAL org levels 1-8.
8. **Payroll accounting detail.** The physical table (`T_PAYR_ACCTG_DETL` or a `_PUBLIC` view), and the
   names for amount, earn code, pay period, payroll ID/number/sequence and hours.
9. **Class codes.** How civil-service 5-digit P-Classes map to SUCSS 4-digit class codes. Where class
   salary ranges live besides `POSN_MIN_SAL/POSN_MAX_SAL`.
10. **FTE storage scale.** Is it a fraction or a percent, and is `JOB_DETL_APPT_PCT` 0-100?

`integration/edw_mapping_public.yaml` marks each of these entries `unresolved_needs_cookbook` or
`inferred_from_public_pattern`. Once a name is confirmed, set `provenance: verified_dictionary` in a copy
kept where the steward-approved metadata rule allows.
