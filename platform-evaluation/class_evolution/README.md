# SUCSS class evolution: a real-data history of Illinois civil-service job classes

This folder builds a class × event history of the State Universities Civil Service System
(SUCSS) classification plan from two public SUCSS sources, then analyses how classes are
created, revised, retitled and abolished, how stale current specifications are, and how that
churn lines up with national task and technology change.

**Status: research prototype.** Everything is machine-parsed from PDFs (some scanned and OCRed)
and HTML. O*NET links are the **unreviewed** candidates from `sucss_mapping`. Treat counts as
lower bounds and check individual events against the linked source notice before acting.

## Results (build of 2026-11-06)

**Archive.** 2,662 CSN numbers probed (3,398 is the newest; the descending scan found nothing below
944, confirmed by a 1-in-25 probe of 25–775). 2,322 PDFs (884 MB), 0 network errors, 340 numbers
returning the site's error page. After de-duplication: **1,557 unique documents** (765 PDFs were
re-posts of the same notice), 906 memo notices and 590 spec attachments; 1,124 dated, spanning
**2003–2026** (2004–2026 with ≥9 documents a year). 1,006 documents name at least one class code.
Scanned PDFs: 178 OCRed with Tesseract (158 unique documents parsed from OCR text), 5 left without usable text.

**Events.** 3,087 class × notice events (1,721 at final stage) plus 948 series-page effective-date
events. 1,223 class codes in total: 873 active, 150 abolished by a final notice, 8 abolished but
still listed in the catalog, 18 proposed for deletion and not yet final, 174 named in notices but
neither in the catalog nor with a parsed deletion (older deletions the parser missed, OCR noise, or
codes the notices name only as successors).

**Cross-check against series pages.** Of the classes whose *current* spec took effect in
2016–2019, 95% (76/80) have a parsed notice naming them within 18 months before (or 3 after) that
date; 2020–2022: 97% (481/496); 2023–2026: 83% (24/29). For OCR events, 75% of codes are known
class codes; the rest are mostly deleted classes, but some will be OCR misreads.

**What changed.**
- Revision is wave-driven, not steady: final revisions ran at 10–70 classes a year in 2005–2021,
  then **528 classes in 2022** (the June/August 2022 plan-wide final notices) and 47 in 2023.
  Of the 860 active classes with a known spec date, the median spec is 4.4 years old because of
  that wave; 232 are older than 10 years, 125 older than 15, 11 older than 20.
- **IT consolidation.** In 2023 SUCSS designated legacy IT classes (Systems Programmer, Systems
  Administrator, Applications Analyst/Programmer, Microcomputer Support, LAN, Web, Network,
  IT Manager series and others) into three broad classes: 5031 IT Technical Associate (37 source
  classes), 5030 IT Manager/Administrative Coordinator (14) and 5032 IT Support Associate (6);
  the legacy classes were deleted in August 2024. IT is the family with the most abolished
  classes (43) and only 22 active ones.
- **Disappearing operations/clerical computing roles.** 33 deletions in 2015 include Digital
  Computer Operator, Operations Support Service Specialist and Technical Support classes.
- 2026: a run of deletions of unused classes (Cartographer, Meteorological Aide, Locker Room and
  Coin Machine Attendant, Broadcast Music Specialist, Valet Parking Attendant, Campus Planning …).
- **New classes** (133 dated: 103 from a "NEW"/new-class action in a notice, 30 inferred from a
  code's first appearance as the successor of deleted classes): clinical imaging and cardiovascular tracks (CT, Interventional
  Radiology, Invasive Cardiovascular, 2020), Peer Support series (2022), Live Captioner and
  Ophthalmic Photographer (2024), Public Health Response Specialist (2022), several
  communications "Associate" classes (2019). Few new IT/data/security classes: the IT change was
  consolidation, not creation.
- **Title changes** (final notices, 309 source→target or in-place records, 201 distinct
  source→successor pairs): 108 retitles with new words, 68 sharing words, 80 in-place retitles,
  9 level renumberings (I/II → 1/2), plus 28 flagged change-in-title rows with the same title.

**Local churn vs national change.** Families were placed on a national-change index (mean
percentile of O*NET 31.0 hot-technology share, emerging-task rate, AEI observed exposure and
job_evolution task churn 2016–2026) and on local churn (share of classes with any notice,
revision or deletion in the last 5 years). Library/museum, management/administration,
finance/procurement and health score high nationally but low locally; clerical, IT, transportation,
food and skilled trades churned locally more than national signals suggest (IT's churn is the
consolidation, clerical's the 2022 wave). At class level the relationship is weak: Spearman ρ
between national signals and years since last revision ranges from −0.07 (hot-tech share) to
+0.16 (AEI task coverage), n ≈ 780–820. SUCSS revision timing does **not** track national task or
technology change in any useful way.

**Revision outlook.** Temporal backtest over 14 annual cutoffs (2010–2023, 3-year windows, each
trained only on earlier closed windows, features point-in-time): mean AUC logistic model 0.53,
spec-age only 0.54, family base rate 0.48, descriptive index 0.55. Performance swings with the
waves (index AUC 0.80–0.81 before the 2022 wave, 0.17 for the 2023 cutoff). Because the model does
not beat simple age, `revision_risk` is published as a **descriptive risk index** (55% spec-age
percentile, 25% national-change percentile, 20% recent notice activity in the class or its series),
not as a probability. 16 of its top 50 classes had a proposal rescinded in 2026 (the nursing
series), which the explorer flags.

**Linkage.** 852 classes carry an unreviewed top-1 O*NET candidate from `sucss_mapping`;
30 abstained; 341 codes (mostly abolished or notice-only codes) have none.

### Known limitations
- Codes are only as good as the parser: older notices name classes by title only (resolved
  against current series/class titles, so classes renamed since are missed); OCR tables lose
  column alignment, so per-row actions and successor codes are not recovered for scanned notices.
- Series pages show only the latest revision; the notice archive fills the history, but is sparse
  before 2007 and absent before CSN 944 (~2003).
- Families are keyword rules; "Other" absorbs abolished codes whose titles were not recovered.
- National signals are 2025–26 snapshots except the job_evolution panel, which is point-in-time.


## Run

```bash
pip install -r class_evolution/requirements.txt         # Python 3.13; plus poppler-utils, tesseract-ocr (system)
python class_evolution/acquire_notices.py --start 3381 --end 3600 --stop-after-missing 25   # newest numbers
python class_evolution/acquire_notices.py --start 3397 --end 1 --stop-after-missing 150     # back to CSN 1
python class_evolution/ocr_notices.py --workers 3      # OCR scanned PDFs (cached)
python class_evolution/build.py                        # parse + timeline + analytics + model + HTML
python -m unittest class_evolution/tests/test_class_evolution.py
```

`build.py` needs the cached series pages from `sucss_mapping/acquire_specs.py`, the lake
contract tables, and (optionally) `job_evolution/artifacts/` from the job_evolution workstream.

## Sources and acquisition

| Source | What it gives | How it was read |
|---|---|---|
| Civil Service Notices, `https://www.sucss.illinois.gov/documents/csn/<n>.pdf` | Proposal, preliminary and final status notices; deletion (abolishment) notices; rescissions; meeting notices; draft and adopted spec attachments. Dated memos with SUCSS action tables (REVISE / NEW / DELETE / CIT, revised/new class code, effective date). | Enumerated by number (see below). |
| Series pages, `pages/classspec/ViewSeries.aspx` (cached by `sucss_mapping`) | Each current class's spec and exam effective dates and last action. | Re-parsed with `sucss_mapping/parse_specs.py`; no new requests. |

**robots.txt.** The live file (sha256 recorded in `data/lake/raw/sucss_notices/robots_manifest.json`)
disallows the notice index pages `/csn.aspx`, `/csn_detail.aspx` and `/csnDeleted.aspx`. The site
now lists notices at `/pages/csn/default.aspx`, which is not literally disallowed, but, following
the precedent in `sucss_mapping` (an operator's disallow on an old or misspelled path is read as
intent), **no index page was crawled**. The PDFs live under `/documents/csn/`, which robots.txt
does not disallow; they were enumerated by integer.

**Politeness.** One request at a time, at least 1.5 s apart, User-Agent
`Mozilla/5.0 (compatible; generic-research-client/1.0; public classification research)`,
cached (re-runs skip numbers already in the manifest), and the run stops on any network error or
any HTTP status other than 200/404. A number that returns the site's HTML error page with
HTTP 200 is recorded as `200_not_pdf` (treated as missing). The descending scan stops after 150
consecutive missing numbers. Every request is logged in `manifest.jsonl` with URL, status,
content type, sha256, bytes, retrieval time and User-Agent.

**Duplicates.** SUCSS often posts the same notice under many CSN numbers (one per affected class
or employer). Documents are de-duplicated by PDF sha256 and by normalized-text sha256; each is
counted once, under its lowest number (`duplicate_of` in `notice_documents`).

**OCR.** Many 2020–2022 and older notices are scanned images. `ocr_notices.py` rasterises the
first 6 pages at 200 dpi and runs Tesseract 5 (psm 6). OCR destroys table alignment, so for
scanned notices a 4-digit token in the action table is kept only if it is a known class code
(catalog, series pages, or a code seen in a text-layer notice) or is followed by an action word
on the same line. Events carry `extractor` so OCR-derived events can be filtered out.

## Parsing (`parse_notices.py`)

- Text from poppler `pdftotext -layout` (pypdf fallback).
- Memo header: DATE (skipping digital-signature timestamps), SUBJECT/RE.
- Stage from the subject: proposal, preliminary, final, rescission, meeting; attachments are
  `draft` or `spec_document`.
- Class codes from explicit contexts ("Classification Code Number 4212", "(Class Code 0082)",
  "Spec. Code:", "Level I: … 3086") and from SUCSS **action tables**. Table rows are rebuilt in
  layout text by matching each left-column code to the nearest action cell (orientation-aware:
  some tables put the code under the title, some above). Codes in the "Revised/New Class Title"
  column become `target_codes`, e.g. `2421 Information Technology Assistant Manager DELETE → 5030`.
  A DELETE row whose target is its own code (e.g. `1236 Driver → 1236 Heavy Driver`) is a
  retitle, not an abolishment.
- Codes cited as "not affected by this notice" / "currently under review" are kept with
  `role = context`, not as events.
- Action per class: table action, else the subject (deletion → `abolish`, new class, title
  change, exam change, revision); secondary flags for exam, pay-range and qualification notes.

## Outputs (`outputs/`, committed: IDs, dates, codes, titles, labels, counts only)

| File | Grain |
|---|---|
| `notice_documents` | one row per CSN number requested: URL, status, hashes, kind, stage, date, primary action, duplicate_of, extractor |
| `class_events` | one row per class × notice (CSN events) plus series-page spec/exam effective dates |
| `class_timeline` | one row per class code ever seen: status, created/abolished/last-revision dates, spec age, open process, O*NET candidate and national signals |
| `revision_activity_by_family_year`, `revision_activity_by_occ_line_year` | distinct classes changed per family/line and year, by measure |
| `created_abolished`, `title_changes` | creations, abolishments with successor codes, retitle/consolidation patterns |
| `stale_specs` | active classes, ranked watchlist of old specs weighted by national change |
| `onet_linkage` | unreviewed top-1 O*NET candidate per class |
| `family_alignment` | local churn vs national change per family |
| `revision_risk` | 3-year revision outlook per active class |
| `summary.json` | all headline numbers, validation, backtest |

Explorer: `output/class_evolution/class_evolution_explorer.html` (single offline file,
vanilla JS + SVG, light/dark, phone width).

## Licensing and what is (not) in Git

SUCSS documents are public records but are not openly licensed. As in `sucss_mapping`:
- PDFs, extracted text and OCR text stay in `data/lake/raw/sucss_notices/` (gitignored).
- Committed outputs hold only CSN numbers, URLs, sha256 hashes, dates, class codes, class titles
  (public identifiers of the classification plan), categorical labels, counts and derived
  features. No notice prose, duty statements or exam content is stored or shown; the explorer
  links each event to the source PDF instead.
- O*NET 31.0 (CC BY 4.0, U.S. DOL/ETA) and the Anthropic Economic Index (CC BY) are used for
  derived numeric features only.
