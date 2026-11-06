"""Build the public-documentation EDW field inventory (CSV + Parquet) and validate the reference.

    python integration/edw_public_reference/build_reference.py                 # write + validate
    python integration/edw_public_reference/build_reference.py --text-cache DIR  # also check excerpts verbatim

The curated evidence lives in ROWS below: one row per (table/view, column, source). Each row cites a
source key from sources.yaml. Nothing here comes from the Data Cookbook.

Column naming (`column`):
  name_basis=verbatim   the physical name is printed in the source
  name_basis=inferred   the source gives a business name ("Job Detail FTE field"); the physical name is
                        derived from EDW abbreviations seen verbatim elsewhere (PERS, EMPEE, POSN, JOB_DETL,
                        CLS, CD, DESC, IND, DT, NBR, PCT, SAL, CATGRY) and must be confirmed
  name_basis=v1_assumed no public name at all; the v1 sample-pack name is listed so the gap is visible
Confidence:
  high    physical name or value printed in a fully read document / KB article
  medium  business field stated in a full document or KB (physical name inferred), or a verbatim name
          from a search snippet that a second independent source corroborates
  low     a single search snippet, a requester-reported snippet, or a v1_assumed name

--text-cache DIR: a folder of text extracted from the downloads (reportingconcepts.txt, kb_120569.txt ...).
Every full_document/kb_article excerpt must then appear verbatim (whitespace and table separators
normalised); otherwise the build fails.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
COLUMNS = ["table_or_view", "column", "business_meaning", "example_values_or_domain", "source_url", "source_type",
           "evidence_excerpt", "confidence", "first_seen_date", "notes"]
CONFIDENCE = {"high", "medium", "low"}
SOURCE_TYPES = {"full_document", "kb_article", "search_snippet"}
BASES = {"verbatim", "inferred", "v1_assumed", "business_only"}
TEXT_FILES = {"rc2009": "reportingconcepts.txt", "eclass2015": "nessie_JobAid_EClass.txt",
              "term2014": "nessie_JA_Termination_Codes.txt", "tenure2008": "nessie_JobAid_Tenurecode.txt",
              "jobchg2016": "nessie_JobAid_JobChangeCodes.txt", "kb120378": "kb_eclass.txt"}

# (table_or_view, column, business_meaning, example_values_or_domain, source_key, evidence_excerpt,
#  confidence, name_basis, notes)
ROWS: list[tuple] = [
    # ------------------------------------------------------------------ person
    ("T_PERS_HIST", "*", "Person history table (biographic/demographic history)", "",
     "snip_data_models_page", 'using real table names such as "T_PERS_HIST" rather than "Person History"',
     "medium", "verbatim", "Data-models page explains physical vs logical names using this table; corroborated by req_ra_edw_physical."),
    ("T_PERS_HIST", "*", "Person history table listed in the RA physical model", "",
     "req_ra_edw_physical", "RA_EDW_Physical_Model.pdf lists T_PERS_HIST / EDW_PERS_ID",
     "low", "verbatim", "Requester-reported snippet; not reproduced in this session."),
    ("T_PERS_HIST", "EDW_PERS_ID", "EDW person identifier (warehouse surrogate key for a person)", "synthetic in samples",
     "req_ra_edw_physical", "RA_EDW_Physical_Model.pdf lists T_PERS_HIST / EDW_PERS_ID",
     "low", "verbatim", "Requester-reported snippet."),
    ("T_PERS_HIST", "EDW_PERS_ID", "EDW person identifier", "",
     "snip_ra_edw_logical", "Person History entity keyed by an EDW person ID foreign key, with a current-information indicator",
     "low", "inferred", "Search summary of the RA logical model (business name EDW Person ID)."),
    ("T_PERS_HIST", "PERS_EFF_DT", "Person history effective date", "date",
     "snip_hr_edw_logical", 'naming pattern with "Current Info Ind" fields alongside "Hist Effective Date" and "Hist Expiration Date"',
     "low", "inferred", "Physical name by analogy with EMPEE_EFF_DT (req_uis_gitlist)."),
    ("T_PERS_HIST", "PERS_EXP_DT", "Person history expiration date", "date; inclusive vs exclusive unknown",
     "snip_hr_edw_logical", 'naming pattern with "Current Info Ind" fields alongside "Hist Effective Date" and "Hist Expiration Date"',
     "low", "inferred", "End-date convention not documented publicly."),
    ("V_EMPEE_PERS_HIST_1", "PERS_CUR_INFO_IND", "Person current-information indicator", "Y = current row",
     "rc2009", "Employee Person History 1 Table, Current Info Indicator field = Y",
     "medium", "inferred", "Business name in full document; physical name from req_uis_gitlist."),
    ("V_EMPEE_PERS_HIST_1", "PERS_CUR_INFO_IND", "Person current-information indicator", "Y",
     "req_uis_gitlist", "edw.V_EMPEE_PERS_HIST_1 ... PERS_CUR_INFO_IND",
     "low", "verbatim", "Requester-reported snippet of UIS SQL."),
    ("V_EMPEE_PERS_HIST_3", "AGE", "Employee age", "integer years",
     "rc2009", "Age EDW: V_EMPEE_PERS_HIST_3.AGE.", "high", "verbatim", "Restricted demographic; age band only."),
    ("V_EMPEE_PERS_HIST_3", "IPEDS_RACE_ETH_CATGRY_DESC", "IPEDS race/ethnicity category description", "IPEDS categories",
     "rc2009", "Race/Ethnicity EDW: V_EMPEE_PERS_HIST_3.IPEDS_RACE_ETH_CATGRY_DESC", "high", "verbatim", "Restricted demographic."),
    ("V_EMPEE_PERS_HIST_3", "PERS_CITZN_IND_CD", "Person citizenship indicator code", "US = U.S. citizen",
     "rc2009", 'Employee Person History 3 Table, Person Citizenship Indicator Code field = "US"', "medium", "inferred", ""),
    ("V_EMPEE_VISA_HIST_5", "CUR_VISA_TYPE_CD", "Current visa type code; also Visa Issue Nation Code", "",
     "rc2009", "Employee Visa History 5 Table, Current Visa Type Code field, and Visa Issue Nation Code", "medium", "inferred", ""),
    ("V_PERS_HIST_RTA_LTD_RSTR", "*", "Restricted person-history view variant (also V_PERS_HIST_RTA_FULL)", "",
     "snip_sce_201609", "V_PERS_HIST_RTA_LTD_RSTR and V_PERS_HIST_RTA_FULL views", "low", "verbatim",
     "Shows that person history is exposed through several restricted views."),
    # ------------------------------------------------------------------ employee
    ("V_EMPEE_HIST_1", "*", "Employee History 1 (employee-level history view used for reporting)", "",
     "rc2009", "Employee History 1 Table", "medium", "inferred",
     "View name V_EMPEE_HIST_1 from req_uis_gitlist; T_EMPEE_HIST base table from repo handoff only."),
    ("V_EMPEE_HIST_1", "EMPEE_EFF_DT", "Employee history effective date", "date",
     "req_uis_gitlist", "edw.V_EMPEE_HIST_1 ... EMPEE_EFF_DT, EMPEE_EXP_DT", "low", "verbatim", "Requester-reported."),
    ("V_EMPEE_HIST_1", "EMPEE_EFF_DT", "Employee effective date", "date",
     "snip_hr_edw_logical", "Employee History, EDW Person ID (FK), Employee Effective Date, Employee Expiration Date",
     "low", "inferred", "Logical model business names; corroborates the gitlist name."),
    ("V_EMPEE_HIST_1", "EMPEE_EXP_DT", "Employee history expiration date", "date; convention unknown",
     "req_uis_gitlist", "edw.V_EMPEE_HIST_1 ... EMPEE_EFF_DT, EMPEE_EXP_DT", "low", "verbatim", "Requester-reported."),
    ("V_EMPEE_HIST_1", "EMPEE_STATUS_CD", "Employee status code", "A = active, T = terminated; leave statuses exist",
     "rc2009", "Employee History 1 Table, Employee Status Code field does not equal T", "medium", "inferred",
     "Values A and T printed; leave letters not listed."),
    ("V_EMPEE_HIST_1", "EMPEE_CUR_INFO_IND", "Employee current-information indicator", "Y = current row",
     "rc2009", "Employee History 1 Table, Employee Current Info Indicator field = Y", "medium", "inferred",
     "Physical name from req_uis_gitlist."),
    ("V_EMPEE_HIST_1", "EMPEE_CUR_INFO_IND", "Employee current-information indicator", "Y",
     "req_uis_gitlist", "EMPEE_CUR_INFO_IND", "low", "verbatim", "Requester-reported."),
    ("V_EMPEE_HIST_1", "ACTIVE_EMPEE_IND", "Active employee indicator", "Y = active",
     "rc2009", "Employee History 1 Table, Active Employee Indicator field = Y", "medium", "inferred",
     "Physical name from req_uis_gitlist."),
    ("V_EMPEE_HIST_1", "ACTIVE_EMPEE_IND", "Active employee indicator", "Y",
     "req_uis_gitlist", "ACTIVE_EMPEE_IND", "low", "verbatim", "Requester-reported."),
    ("V_EMPEE_HIST_1", "EMPEE_CLS_CD", "Person-level E-Class (drives benefit and leave eligibility)", "see code_domains.e_class",
     "rc2009", "When reporting on the Person E-Class, select the E-Class code field from the EDW Table: Employee History 1.",
     "medium", "inferred", ""),
    ("V_EMPEE_HIST_1", "BENEFIT_CATGRY_CD", "Benefit category code", "M1, M2, M3, M4, B1, B2, B3, B4",
     "rc2009", "Employee History 1 Table, Benefit Category Code field = M1, M2, B1, B2", "medium", "inferred",
     "SURS eligible = M1,M2,M3,B1,B2,B3."),
    ("V_EMPEE_HIST_1", "BENEFIT_ELIG_IND", "Derived benefit-eligible indicator", "",
     "rc2009", "there is also a derived benefit eligible field: Benefit Eligible Indicator.", "medium", "inferred", ""),
    ("V_EMPEE_HIST_1", "ADJ_SERVICE_DT", "Adjusted service date (years-of-service calculation)", "date",
     "rc2009", "Employee History 1 Table, calculation using Adjusted Service Date", "medium", "inferred", ""),
    ("V_EMPEE_HIST_1", "HR_CAMPUS_CD", "HR campus (physical location) code", "values not published",
     "rc2009", "Employee History 1 Table, HR Campus Code field", "medium", "inferred", ""),
    ("V_EMPEE_HIST_1", "COA_CD", "Home campus = chart of accounts code", "1 Urbana/Champaign, 2 Chicago, 4 Springfield, 9 System Offices",
     "rc2009", "Home Campus Code EDW: Employee History 1 Table, Chart of Accounts Code field", "medium", "inferred",
     "Values from kb118751."),
    ("(C-FOAPAL)", "COA_CD", "Chart code", "1 = Urbana/Champaign; 2 = Chicago; 4 = Springfield; 9 = System Offices",
     "kb118751", "1 = Urbana/Champaign 2 = Chicago 4 = Springfield 9 = System Offices", "high", "business_only", ""),
    ("(C-FOAPAL)", "ORG_CD", "Organization (8-level hierarchy)", "levels 1 University ... 8 Sub-Org User Defined",
     "kb118751", "Level 1: University Level 2: Administrative Rollup Level 3: College", "high", "business_only", ""),
    ("T_EMPEE_HIST", "FIRST_HIRE_DT", "First hire date", "date",
     "rc2009", "Years of Service Calculation EDW: Employee History 1 Table, calculation using Adjusted Service Date",
     "low", "v1_assumed", "No public source names hire-date fields; v1 names FIRST_HIRE_DT/CUR_HIRE_DT unresolved."),
    ("T_EMPEE_HIST_5", "*", "Employee history variant 5 (repo handoff: termination and SURS retirement details)", "",
     "kb120385", "This article provides a list of employee-level termination codes.", "low", "v1_assumed",
     "No public source ties termination fields to T_EMPEE_HIST_5; only the code domain is public."),
    ("T_EMPEE_HIST_5", "TERM_REASON_CD", "Employee-level termination code", "TD..TZ (see code_domains.termination_code)",
     "kb120385", "TQ | Employee Resigned | Employee has resigned from the university. | All", "low", "v1_assumed",
     "Domain high confidence; column/table name unresolved."),
    ("T_EMPEE_HIST_5", "TERM_REASON_CD", "Employee-level termination code", "TD..TZ",
     "term2014", "TR Retired Employee has retired from the university and is a SURS annuitant", "low", "v1_assumed",
     "2014 list (no TW)."),
    ("T_EMPEE_HIST_5", "SURS_RETIR_IND", "SURS retirement indicator", "no public indicator; TR = retired SURS annuitant",
     "rc2009", "SURS Eligible EDW: Employee History 1 Table, Benefit Category Code field = M1, M2, M3, B1, B2, B3",
     "low", "v1_assumed", "Public docs give SURS eligibility via benefit category, not a retirement indicator."),
    # ------------------------------------------------------------------ job detail
    ("T_JOB_DETL_HIST", "*", "Job detail history (appointment rows by person, position, suffix, effective date)", "",
     "req_prr_edw_physical", "PRR_EDW_Physical_Model_Multi-page.pdf lists T_JOB_DETL_HIST, EDW_PERS_ID, POSN_NBR",
     "low", "verbatim", "Requester-reported."),
    ("T_JOB_DETL_HIST", "*", "Job detail history table and its _1 view", "",
     "snip_rn_2008_06", "removal of the JOB_DETL_ENC_HOURS column from that table and its view", "medium", "verbatim",
     "Search summary of the 2008-06 release notes naming T_JOB_DETL_HIST; corroborates req_prr_edw_physical."),
    ("T_JOB_DETL_HIST", "JOB_DETL_APPT_PCT", "Appointment percent", "percent",
     "rc2009", "EDW: t_job_detl_hist.Job_detl_appt_pct", "high", "verbatim", "Actual FTE worked = Job FTE * Appointment Percent."),
    ("T_JOB_DETL_HIST", "JOB_DETL_ENC_HOURS", "Encumbrance hours (removed 2008)", "always null or zero",
     "snip_rn_2008_06", "JOB_DETL_ENC_HOURS column from that table and its view", "low", "verbatim", "Dropped column."),
    ("V_JOB_DETL_HIST_1", "*", "Job Detail History 1 (reporting view over T_JOB_DETL_HIST)", "",
     "snip_rn_2010_09", "added two columns, EMPEE_GROUP_CD and EMPEE_GROUP_DESC, to the Job Detail History table and to its view V_JOB_DETL_HIST_1",
     "medium", "verbatim", "Search summary of 2010-09 release notes; corroborated by req_rn_2005_05 and rc2009 business name."),
    ("V_JOB_DETL_HIST_1", "EMPEE_GROUP_CD", "Employee group code of the job", "values not published",
     "snip_rn_2010_09", "added two columns, EMPEE_GROUP_CD and EMPEE_GROUP_DESC, to the Job Detail History table and to its view V_JOB_DETL_HIST_1",
     "low", "verbatim", "Part 2 of a 3-part effort to add employee group to warehouse tables."),
    ("V_JOB_DETL_HIST_1", "EMPEE_GROUP_DESC", "Employee group description", "",
     "snip_rn_2010_09", "EMPEE_GROUP_CD and EMPEE_GROUP_DESC", "low", "verbatim", ""),
    ("V_JOB_DETL_HIST_1", "JOB_DETL_TIME_ENTRY_METHOD_CD", "Time entry method code", "",
     "req_rn_2005_05", "V_JOB_DETL_HIST_1 ... JOB_DETL_TIME_ENTRY_METHOD_CD", "low", "verbatim", "Requester-reported."),
    ("V_JOB_DETL_HIST_1", "EDW_PERS_ID", "Person key of the job", "",
     "snip_hr_edw_logical", "Job Detail, EDW Person ID (FK), Position Number (FK), Job Suffix (FK), Job Detail Effective Date",
     "medium", "verbatim", "EDW_PERS_ID also in req_prr_edw_physical."),
    ("V_JOB_DETL_HIST_1", "POSN_NBR", "Position number of the job", "C/S/U/G + 5 digits (snippet)",
     "req_prr_edw_physical", "T_JOB_DETL_HIST, EDW_PERS_ID, POSN_NBR", "low", "verbatim", "Requester-reported."),
    ("V_JOB_DETL_HIST_1", "POSN_NBR", "Position number", "letter for campus (C, S, U, or G) + five digits",
     "snip_hr_nbajobs", "begin with a letter indicating the campus (C, S, U, or G), followed by five numeric digits",
     "low", "inferred", "Format only."),
    ("V_JOB_DETL_HIST_1", "JOB_SUFFIX", "Job suffix (distinguishes jobs on one position)", "00, 01, ...; T* = overload",
     "snip_hr_edw_logical", "Job Detail, EDW Person ID (FK), Position Number (FK), Job Suffix (FK), Job Detail Effective Date",
     "medium", "inferred", "Corroborated by rc2009 and snip_hr_nbajobs."),
    ("V_JOB_DETL_HIST_1", "JOB_SUFFIX", "Job suffix", "first job 00, second 01",
     "snip_hr_nbajobs", "the first job associated with a position has a suffix of '00', the second job would be a suffix of '01",
     "low", "inferred", ""),
    ("V_JOB_DETL_HIST_1", "JOB_DETL_EFF_DT", "Job detail effective date", "date",
     "rc2009", "Job Detail History 1 Table, Job Detail History Effective Date field", "medium", "inferred", ""),
    ("V_JOB_DETL_HIST_1", "JOB_DETL_EXP_DT", "Job detail expiration date", "date; convention unknown",
     "rc2009", "Job Detail History Expiration Date field", "medium", "inferred", ""),
    ("V_JOB_DETL_HIST_1", "JOB_DETL_STATUS_DESC", "Job detail status description", "Terminated, ...",
     "rc2009", 'Active Job EDW: Job Detail History 1 Table, Job Detail Status Description does not equal "Terminated"',
     "medium", "inferred", "Status code letters not public; v2 adds JOB_DETL_STATUS_CD (inferred)."),
    ("V_JOB_DETL_HIST_1", "JOB_DETL_FTE", "Job FTE", "fraction (1.0 = full time)",
     "rc2009", "Job FTE EDW: Job Detail History 1, Job Detail FTE field", "medium", "inferred",
     "Stored scale (fraction vs percent) not stated; snip_fte_cube_2023 calls it a percentage."),
    ("V_JOB_DETL_HIST_1", "JOB_DETL_FTE", "Job FTE", "",
     "snip_fte_cube_2023", "The Job Detail FTE field is the full time equivalency percentage assigned to this job.",
     "low", "inferred", ""),
    ("V_JOB_DETL_HIST_1", "JOB_DETL_DAY_HRS", "Job day hours", "", "rc2009",
     "Job Day Hours EDW: Job Detail History 1 Table, Job Detail Day Hours field", "medium", "inferred", ""),
    ("V_JOB_DETL_HIST_1", "JOB_DETL_PAY_HRS", "Job pay hours (sum = total hours normally worked)", "", "rc2009",
     "Job Pay Hours EDW: Job Detail History 1 Table, Job Detail Pay Hours field", "medium", "inferred", ""),
    ("V_JOB_DETL_HIST_1", "JOB_DETL_REG_RATE", "Hourly rate", "", "rc2009",
     "Hourly Rate EDW: Job Detail History 1 Table, Job Detail Regular Rate field", "medium", "inferred", ""),
    ("V_JOB_DETL_HIST_1", "JOB_DETL_PAY_PERIOD_SAL", "Monthly rate for monthly paid", "", "rc2009",
     "Monthly Rate EDW: Job Detail History 1 Table, Job Detail Pay Period Salary field", "medium", "inferred", ""),
    ("V_JOB_DETL_HIST_1", "JOB_DETL_ANNUAL_SAL", "Annual salary rate", "currency", "rc2009",
     "Annual Rate EDW: Job Detail History 1 Table, Job Detail Annual Salary field", "medium", "inferred",
     "Suffix _SAL follows verbatim POSN_MIN_SAL."),
    ("V_JOB_DETL_HIST_1", "JOB_DETL_ANNUAL_PAY_CNT", "Pay factor (pays per year)", "CS 26; 12/12 = 12; 9/9 = 9", "rc2009",
     "Job Detail History 1 Table, Job Detail Annual Pay Count field.", "medium", "inferred", ""),
    ("V_JOB_DETL_HIST_1", "JOB_DETL_EMPEE_CLS_CD", "Job-level E-Class", "WT one-time, MM summer, LP lump sum; full list kb120378",
     "rc2009", "One Time Payments EDW: Job Detail History 1 Table, Job Detail Employee Class Code = WT", "medium", "inferred", ""),
    ("V_JOB_DETL_HIST_1", "JOB_DETL_SAL_TABLE_CD", "Job salary table code", "CA/DA/EA open range; T* established; Q/R/S prevailing; G/K/M negotiated",
     "rc2009", "Job: Job Detail History 1 Table, Job Detail Salary Table Code field.", "medium", "inferred", ""),
    ("V_JOB_DETL_HIST_1", "JOB_DETL_SAL_GRADE_CD", "Job salary grade code", "", "rc2009",
     "Job level: Job Detail History 1 Table, Job Detail Salary Grade Code field.", "medium", "inferred", ""),
    ("V_JOB_DETL_HIST_1", "POSN_CLS_CD", "Job P-Class (may differ from position for academic jobs)", "5 characters; see code_domains.p_class",
     "rc2009", "When reporting on the Job P-Class, select the P-Class code from the EDW Table: Job Detail History 1.",
     "medium", "inferred", "FK naming as for EDW_PERS_ID/POSN_NBR; could be JOB_DETL_POSN_CLS_CD."),
    ("V_JOB_DETL_HIST_1", "JOB_DETL_CHANGE_REASON_CD", "Job change reason code", "HR001, EJ002, OT010 ... (kb120563)",
     "rc2009", "Job Change Reason code values can be found in General Banner Information - Change Reason Code Job Aid",
     "medium", "inferred", "Not in v1."),
    ("V_JOB_DETL_HIST_1", "JOB_CONTRACT_TYPE_CD", "Job type", "P primary, O overload (S secondary in v1 only)",
     "rc2009", "Primary Job Job Type = P Overload Job Job Type = O", "medium", "v1_assumed",
     "Value domain public; column name and table (job vs job detail) unresolved."),
    ("T_JOB_HIST", "CONTRACT_PRIMARY_JOB_IND", "Primary job indicator", "Y primary, N secondary/overload",
     "snip_fte_cube_2023", "Indicates whether the job is Primary (Y) or Secondary/Overload (N).", "low", "inferred",
     "Cube object 'Contract Primary Job Ind'."),
    ("T_JOB_HIST", "JOB_PROBATION_END_DT", "Job probation end date", "date",
     "rc2009", "In Probationary Period EDW: Job History Table, if Job Probation End Date > today's date", "medium", "inferred", ""),
    ("(BusinessObjects HR universes)", "(predefined conditions)", "Current-record filters", "Current Position, Current Job, Current Job Detail, Current Active Job Detail, Current Employee",
     "snip_pjh_quickref", "Current Position, Current Job, Current Job Detail and Current Active Job Detail, and Current Employee",
     "low", "business_only", "Universe-level filters; underlying columns are the *_CUR_INFO_IND style flags (inferred)."),
    ("(BusinessObjects HR universes)", "(Employee Administration)", "Universe content", "position number, title, job suffix, job detail campus/college",
     "snip_empadmin_quickref", "position number, position title, job suffix, and job detail campus and college codes",
     "low", "business_only", ""),
    # ------------------------------------------------------------------ position
    ("T_POSN_HIST", "POSN_MIN_SAL", "Salary range minimum", "currency", "rc2009",
     "Salary Range Minimum EDW: T_POSN_HIST.POSN_MIN_SAL", "high", "verbatim", ""),
    ("T_POSN_HIST", "POSN_MAX_SAL", "Salary range maximum", "currency", "rc2009",
     "Salary Range Maximum EDW: T_POSN_HIST.POSN_MAX_SAL", "high", "verbatim", ""),
    ("T_POSN_HIST", "POSN_NBR", "Position number", "", "rc2009",
     "the Position History Table and the Job Table need to be linked by position number and job suffix.", "medium", "inferred",
     "POSN_NBR verbatim in req_prr_edw_physical."),
    ("T_POSN_HIST", "POSN_EFF_DT", "Position history effective date", "date", "rc2009",
     "EDW: Position History Table, Position History Effective Date field", "medium", "inferred",
     "Could also be POSN_HIST_EFF_DT; v1 name kept."),
    ("T_POSN_HIST", "POSN_EXP_DT", "Position history expiration date", "date", "rc2009",
     "Position History Expiration Date field", "medium", "inferred", "Could also be POSN_HIST_EXP_DT."),
    ("T_POSN_HIST", "POSN_STATUS_DESC", "Position status description", "Active, Inactive, Frozen, Cancelled", "rc2009",
     'Position History Table, Position Status Description field = "Active"', "medium", "inferred",
     "Vacant: Active or Inactive. Code letters not public."),
    ("T_POSN_HIST", "POSN_TYPE_DESC", "Position type", "Single, Pooled", "rc2009",
     "Position History Table, Position Type Description field = Single or Pooled", "medium", "inferred", ""),
    ("T_POSN_HIST", "POSN_SAL_TABLE_CD", "Position salary table code", "see code_domains.salary_table_code", "rc2009",
     "EDW: Position: Position History Table, Position Salary Table Code.", "medium", "inferred", ""),
    ("T_POSN_HIST", "POSN_SAL_GRADE_CD", "Position salary grade code", "", "rc2009",
     "Position level: Position History Table, Position Salary Grade Code field.", "medium", "inferred", ""),
    ("T_POSN_HIST", "POSN_BARGAIN_UNIT_CD", "Position bargaining unit code", "values not published", "rc2009",
     "EDW: Position History Table, Position Bargaining Unit Code field", "medium", "inferred", ""),
    ("T_POSN_HIST", "POSN_PAPE_CS_IDENT", "PAPE civil service identifier (standard PAPE title code)", "49901-49920", "rc2009",
     "EDW: Position History Table, PAPE Civil Service Identifier field", "medium", "inferred", ""),
    ("T_POSN_HIST", "POSN_EMPEE_CLS_CD", "Position-level E-Class (defaults from position class)", "see e_class", "rc2009",
     "When reporting on the Position level E-Class, select the E-Class code field from the EDW Table: Position History.",
     "medium", "inferred", ""),
    ("T_POSN_HIST", "POSN_CLS_CD", "Position P-Class", "5 characters", "rc2009",
     "The Position P-Class Code may indicate that the position is established as a visiting position.",
     "medium", "inferred", ""),
    ("T_POSN_HIST", "POSN_FTE", "Position FTE", "", "rc2009",
     "Position FTE will indicate the FTE for the Position", "medium", "inferred", "Budgeted FTE was Banner Report Copy NBRPTOT_FTE in 2009."),
    ("T_POSN_HIST", "POSN_ORG_CD", "Position organization", "",
     "rc2009", "The Organization Code of the C-FOAPAL indicates the organization providing the funding.", "low", "v1_assumed",
     "Position org column not public; funding org is on labor distribution / payroll."),
    ("T_POSN_CLS_HIST", "POSN_CLS_DESC", "Position class description", "contains 10001-90001 for apprentice/learner/trainee",
     "rc2009", "EDW: T_POSN_CLS_HIST.POSN_CLS_DESC contains 10001-90001 in the description.", "high", "verbatim", ""),
    ("T_POSN_CLS_HIST", "POSN_CLS_CD", "Position class code (P-Class)", "see p_class", "rc2009",
     "When reporting on the Position Class P-Class, select the P-Class code from the EDW Table: Position Class History.",
     "medium", "inferred", ""),
    ("T_POSN_CLS_ATTR", "POSN_CLS_ATTR_CD", "Position class attribute (descriptor) code", "ABDRS, ASLT, ASMT, PDIPC, PSENS, PCONF, PCERT, ARAMP, PFX08-11, L*",
     "rc2009", "the report must use the EDW Table Position Class Attribute, Position Class Attribute Code field.", "medium", "inferred",
     "Linked by Position Class Code."),
    ("T_POSN_CLS_ATTR", "POSN_CLS_ATTR_CD", "Position descriptor codes", "full list", "kb120570",
     "ASLT - Supervises less than 20 employees", "high", "business_only", "Values; table name inferred."),
    ("T_POSN_LABOR_DISTR", "FUND_CD", "Position labor distribution C-FOAPAL (chart, fund, org, account, program, activity, location, grant)", "",
     "rc2009", "EDW: Position Labor Distribution Table, select the following fields that contain CFOAPAL information", "medium", "inferred",
     "Plus Position Labor Distr Funding Desc, Pct, Amt, Effective Date."),
    ("T_JOB_LABOR_DISTR", "FUND_CD", "Job labor distribution C-FOAPAL", "",
     "rc2009", "EDW: Job Labor Distribution Table, select the following fields: Chart of Account Code, Financial Fund Code",
     "medium", "inferred", "Plus Job Labor Distribution Percent, Sal Enc Amt, Eff Dt."),
    # ------------------------------------------------------------------ payroll
    ("T_PAYR_ACCTG_DETL", "*", "Payroll Accounting Detail Public table", "",
     "rc2009", "EDW: Payroll Accounting Detail Public Table, Payroll Acctg Hours field.", "medium", "inferred",
     "Physical name T_PAYR_ACCTG_DETL is from the repo handoff only; a 'Public' variant exists by name."),
    ("T_PAYR_ACCTG_DETL", "POSN_NBR", "Position number link to the job", "", "rc2009",
     "The Payroll Accounting Detail Public Table is linked by the Position Number and", "medium", "inferred", ""),
    ("T_PAYR_ACCTG_DETL", "JOB_SUFFIX", "Job suffix link to the job", "", "rc2009",
     "Job Suffix in order for reported hours worked to be matched to the", "medium", "inferred", ""),
    ("T_PAYR_ACCTG_DETL", "PAYR_ACCTG_HRS", "Reported hours worked", "", "rc2009",
     "Payroll Accounting Detail Public Table, Payroll Acctg Hours field.", "medium", "inferred", ""),
    ("T_PAYR_ACCTG_DETL", "ORG_CD", "Funding organization (C-FOAPAL org)", "", "rc2009",
     "EDW: Payroll Accounting Detail Public Table, Organization Code field", "medium", "inferred", ""),
    ("T_PAYR_ACCTG_DETL", "FUND_CD", "Financial fund code", "1 state, 2 institutional, 3 self-supporting, 4 grants and contracts",
     "rc2009", "Payroll Accounting Detail Public, Financial Fund Code field begins with 4", "medium", "inferred", ""),
    ("T_PAYR_ACCTG_DETL", "PAYR_ID", "Payroll year / payroll ID / payroll number / earnings code / expense amount", "",
     "snip_hr_edw_logical", "payroll year, payroll ID, payroll number, earnings and benefit codes, chart-of-accounts fields, transaction date, and expense and encumbrance amounts",
     "low", "inferred", "Search summary of the logical model's Payroll Accounting Detail entity."),
    ("T_PAYR_ACCTG_DETL", "EARN_CD", "Earn code", "SF*, P01-P14, O*, ASI/ATS, ASV/ATV, CME..CSU, T*; REG not public",
     "rc2009", "Premium Pay Earn Codes: P01 through P14", "medium", "inferred", ""),
    ("T_PAYR_ACCTG_DETL", "ACCTG_DETL_EXPNS_AMT", "Accounting detail expense amount (main dollar figure)", "currency",
     "snip_payroll_quickref", "Accounting Detail Expense Amount is the main dollar figure you will want to use", "low", "inferred",
     "v1 uses PAY_AMT (unresolved)."),
    ("(PYR data mart)", "(entities)", "Payroll reconciliation data mart entities", "HR Payroll Expense Detail, Fund, Period, Program",
     "snip_pyr_dm_logical", "HR Payroll Expense Detail, HR Payroll Fund, HR Payroll Period, and HR Payroll Program", "low", "business_only", ""),
    # ------------------------------------------------------------------ academic / contract / benefits
    ("T_CONTRACT_PARM_HIST", "CONTRACT_TYPE_CD", "Contract type (terminal appointment notices)", "NONR, EXTN, TWNF, TWOF (+ENPR, RESC, ENER)",
     "rc2009", "EDW: Contract Parameter History Table, Contract Type Code.", "medium", "inferred", ""),
    ("T_CONTRACT_HIST", "CONTRACT_ANNIV_DT", "Contract anniversary date", "date", "rc2009",
     "Anniversary Date EDW: Contract History Table, Contract Anniversary Date field", "medium", "inferred", ""),
    ("T_FAC_TENURE_HIST", "FAC_TENURE_TERMINAL_JOB_IND", "Faculty terminal job indicator", "", "rc2009",
     "EDW: Faculty Tenure History Table, Faculty Tenure Terminal Job Ind field.", "medium", "inferred", ""),
    ("T_FAC_TENURE_HIST", "TENURE_CD", "Tenure code", "A, L, M, N, P, Q, T, X", "tenure2008",
     "A Indefinite Tenure", "medium", "inferred", "Values high; column name inferred."),
    ("T_FAC_TENURE_HIST", "TENURE_CD", "Tenure code (current KB subset)", "A, N, P, Q", "kb120574",
     "P | Probationary/On Tenure Track", "medium", "inferred", ""),
    ("V_FAC_RANK_HIST_PRR", "INST_RANK_CD", "Institutional rank code", "1 Professor ... 6, 9 Unreported, A Administrative", "tenure2008",
     "4 Research Professor", "medium", "inferred", "View name V_FAC_RANK_HIST_PRR seen in snip_rn_2010_05."),
    ("V_FAC_RANK_HIST_PRR", "*", "Faculty rank history view", "", "snip_rn_2010_05",
     "T_TEST_RESULT_HIST and V_FAC_RANK_HIST_PRR", "low", "verbatim", "Release notes 2010-05 search summary."),
    ("T_RETIRE_DED_HIST", "RETIRE_DED_CD", "Retirement deduction code", "T* = 403(b)", "rc2009",
     "EDW: Retirement Deduction History Table, Retirement Deduction Code begins with T", "medium", "inferred", ""),
    ("T_MEDICAL_DED_HIST", "MEDICAL_DED_CD", "Medical deduction code", "H* health plans; HQ* Quality Care", "rc2009",
     "EDW: Medical Deduction History Table, Medical Ded Code begins with H for health plans", "medium", "inferred", ""),
    # ------------------------------------------------------------------ code domains as fields
    ("(code domain)", "E-Class", "Employee class", "AA..WT (kb120378)", "kb120378",
     "CA | CS 75Hr/pay N/E Ben Elig | No End Date Required | 13", "high", "business_only", "Full list in code_domains.yaml."),
    ("(code domain)", "E-Class", "Employee class (2015)", "AA..WT", "eclass2015",
     "BA Acad/Pro 12mth Ben Elig Standard* Y3", "high", "business_only", "CL/CM/DR/DS differ from 2026 KB."),
    ("(code domain)", "E-Class groups", "E-Class reporting groups", "exempt/non-exempt lists", "rc2009",
     "Non-exempt Civil Service E-Class = CA, CB, DA, DB, CG, CH, DK, DL", "high", "business_only", ""),
    ("(code domain)", "P-Class", "Faculty/other academic P-Class structure", "5 positions", "kb120569",
     "Value | Employee Class | Value | Service Reference | Value | Rank | Value | Rank modifier | Value | Status Modifier",
     "high", "business_only", ""),
    ("(code domain)", "P-Class", "P-Class examples", "AAAAA, LAAAA, 00581 ...", "kb120369",
     "AAAAA Tenur 9-mo Professors", "high", "business_only", ""),
    ("(code domain)", "Salary table", "Open range salary tables", "CA Chicago, DA Springfield, EA Urbana", "rc2009",
     "Open Range Salary Table: CA (Chicago), DA (Springfield), EA (Urbana).", "high", "business_only", ""),
    ("(code domain)", "Flex year", "Civil service flex year descriptors", "PFX08-PFX11", "kb120570",
     "PFX09 - 9-Month Flex Year", "high", "business_only", ""),
    ("(code domain)", "Place of employment", "Civil service place-of-employment descriptors", "LC, LS, LU, LCR, LUA", "rc2009",
     "LC = Chicago, LS = Springfield, LU = Urbana-Champaign", "high", "business_only", ""),
    ("(code domain)", "FTE rule", "Civil service hours to FTE", "37.5/40/42 hours = 1 FTE", "rc2009",
     "Civil Service employees working 37.5, 40, or 42 hours per week are all considered 1 FTE.", "high", "business_only", ""),
    ("(code domain)", "Job change reason", "Job change reason codes", "116 codes", "kb120563",
     "New Hire | HR001 | New employees hired to the University | All", "high", "business_only", ""),
    ("(code domain)", "Job change reason", "Job change reason codes (2016)", "116 codes", "jobchg2016",
     "JOB CHANGE REASON CODES", "high", "business_only", ""),
    ("(code domain)", "Current info indicator", "Current-info indicator values", "D = Delete, Y = Current", "snip_usage_prr_stuattr",
     "current info indicators of D = Delete or Y = Current", "low", "business_only", "Student attribute table; HR use assumed."),
    ("(code domain)", "Banner identifiers", "UIN / PIDM", "9-character UIN; PIDM never displayed", "kb120369",
     "9-character University Identification Number that uniquely identifies an employee.", "high", "business_only",
     "EDW_PERS_ID is the warehouse key; UIN/PIDM must never enter synthetic data."),
    ("(code domain)", "E-Class", "E-Class is a two-character code at employee, position or job level", "", "snip_hr_peaempl",
     "Employment Class is a two-character code", "low", "business_only", ""),
]


def norm(s: str) -> str:
    s = s.replace("|", " ").replace("–", "-").replace("’", "'")
    return re.sub(r"\s+", " ", s).strip()


def load_sources() -> dict:
    return yaml.safe_load((HERE / "sources.yaml").read_text(encoding="utf-8"))["sources"]


def build_rows(sources: dict) -> list[dict]:
    out = []
    for r in ROWS:
        table, col, meaning, dom, key, excerpt, conf, basis, notes = r
        s = sources[key]
        out.append({
            "table_or_view": table, "column": col, "business_meaning": meaning, "example_values_or_domain": dom,
            "source_url": s["url"], "source_type": s["source_type"], "evidence_excerpt": excerpt,
            "confidence": conf, "first_seen_date": str(s.get("document_date") or s["retrieved_at"])[:10],
            "notes": f"source_key={key}; name_basis={basis}" + (f"; {notes}" if notes else ""),
        })
    # first_seen_date = earliest dated source showing that (table, column)
    first: dict = {}
    for row in out:
        k = (row["table_or_view"], row["column"])
        first[k] = min(first.get(k, "9999"), row["first_seen_date"])
    for row in out:
        row["first_seen_date"] = first[(row["table_or_view"], row["column"])]
    return out


def validate(rows: list[dict], sources: dict, text_cache: Path | None) -> dict:
    problems, verified, skipped = [], 0, 0
    for i, r in enumerate(rows):
        tag = f"row {i} {r['table_or_view']}.{r['column']}"
        for c in COLUMNS:
            if c not in r:
                problems.append(f"{tag}: missing {c}")
        if not r["source_url"]:
            problems.append(f"{tag}: no source_url")
        if r["confidence"] not in CONFIDENCE:
            problems.append(f"{tag}: bad confidence")
        if r["source_type"] not in SOURCE_TYPES:
            problems.append(f"{tag}: bad source_type")
        if len(r["evidence_excerpt"]) > 200:
            problems.append(f"{tag}: excerpt > 200 chars")
        basis = re.search(r"name_basis=(\w+)", r["notes"]).group(1)
        if basis not in BASES:
            problems.append(f"{tag}: bad name_basis {basis}")
        if r["source_type"] == "search_snippet" and r["confidence"] == "high":
            problems.append(f"{tag}: snippet evidence cannot be high confidence")
        key = re.search(r"source_key=(\w+)", r["notes"]).group(1)
        if text_cache and r["source_type"] in ("full_document", "kb_article"):
            fname = TEXT_FILES.get(key) or f"kb_{key[2:]}.txt"
            p = text_cache / fname
            if not p.exists():
                skipped += 1
                continue
            if norm(r["evidence_excerpt"]) in norm(p.read_text(encoding="utf-8", errors="replace")):
                verified += 1
            else:
                problems.append(f"{tag}: excerpt not found verbatim in {fname}")
    for key, s in sources.items():
        for f in ("url", "source_type", "retrieved_at"):
            if not s.get(f):
                problems.append(f"source {key}: missing {f}")
        if s["source_type"] != "search_snippet" and not s.get("sha256"):
            problems.append(f"source {key}: downloaded source without sha256")
    return {"problems": problems, "excerpts_verified": verified, "excerpts_unchecked": skipped}


def check_code_domains(sources: dict) -> list[str]:
    """Every `source`/`also_in`/`physical_names_source` key in code_domains.yaml must exist in sources.yaml."""
    dom = yaml.safe_load((HERE / "code_domains.yaml").read_text(encoding="utf-8"))
    bad = []

    def walk(node, path):
        if isinstance(node, dict):
            for k, v in node.items():
                if k in ("source", "physical_names_source") and isinstance(v, str) and v not in sources:
                    bad.append(f"{path}.{k}: unknown source {v}")
                if k == "also_in":
                    bad.extend(f"{path}.also_in: unknown source {x}" for x in v if x not in sources)
                walk(v, f"{path}.{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]")
    walk(dom, "code_domains")
    return bad


def summary(rows: list[dict]) -> dict:
    fields = {}
    for r in rows:
        if r["table_or_view"].startswith("(") or r["column"] == "*":
            continue
        k = (r["table_or_view"], r["column"])
        best = fields.setdefault(k, {"types": set(), "conf": set()})
        best["types"].add(r["source_type"])
        best["conf"].add(r["confidence"])
    by = {"full_document_or_kb": 0, "snippet_only": 0}
    for v in fields.values():
        by["full_document_or_kb" if v["types"] & {"full_document", "kb_article"} else "snippet_only"] += 1
    # strongest evidence for the PHYSICAL NAME of each field
    rank = {}
    for r in rows:
        if r["table_or_view"].startswith("(") or r["column"] == "*":
            continue
        k = (r["table_or_view"], r["column"])
        basis = re.search(r"name_basis=(\w+)", r["notes"]).group(1)
        doc = r["source_type"] in ("full_document", "kb_article")
        level = ("1_verbatim_in_full_document_or_kb" if basis == "verbatim" and doc else
                 "2_verbatim_in_snippet_only" if basis == "verbatim" else
                 "3_inferred_from_business_name" if basis == "inferred" else "4_v1_assumed_unresolved")
        rank[k] = min(rank.get(k, "9"), level)
    name_basis = {lvl: sorted(f"{t}.{c}" for (t, c), v in rank.items() if v == lvl) for lvl in sorted(set(rank.values()))}
    conf_rows = {c: sum(1 for r in rows if r["confidence"] == c) for c in sorted(CONFIDENCE)}
    type_rows = {t: sum(1 for r in rows if r["source_type"] == t) for t in sorted(SOURCE_TYPES)}
    return {"rows": len(rows), "physical_fields": len(fields), "fields_by_best_source": by,
            "physical_name_evidence": {k: {"n": len(v), "fields": v} for k, v in name_basis.items()},
            "rows_by_confidence": conf_rows, "rows_by_source_type": type_rows}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--text-cache", default=None, help="folder of extracted source text for verbatim checks")
    a = ap.parse_args(argv)
    sources = load_sources()
    rows = build_rows(sources)
    res = validate(rows, sources, Path(a.text_cache) if a.text_cache else None)
    res["problems"] += check_code_domains(sources)
    if res["problems"]:
        print("\n".join(res["problems"]), file=sys.stderr)
        return 1
    with open(HERE / "field_inventory.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    import pyarrow as pa
    import pyarrow.parquet as pq
    pq.write_table(pa.Table.from_pylist(rows), HERE / "field_inventory.parquet")
    s = summary(rows)
    s["excerpts_verified_against_text_cache"] = res["excerpts_verified"] if a.text_cache else "not run (no --text-cache)"
    (HERE / "inventory_summary.json").write_text(json.dumps(s, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(s, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
