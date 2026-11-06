# SUCSS class → O*NET mapping from specification duties

This folder replaces the title-only lexical guess (`title_lexical_baseline_v1` in `sucss_onet_candidate`) with a matcher that reads each SUCSS class's published duties. On a provisional hand-labelled sample of 60 classes, top-1 accuracy goes from 25% to 65% and top-5 accuracy goes from 52% to 90%. Treat these as directional numbers. The labels were made by an agent and still need review by an HR analyst. The sample is small: the 95% intervals are roughly ±12 percentage points.

**Status: every candidate is unreviewed.** `evidence_index` is an ordinal score from 0 to 100. It is not a probability, a confidence level or an allocation weight. Contract rule 9 (`lake/CONTRACT.md`) still applies.

## Run

```bash
pip install -r sucss_mapping/requirements.txt          # Python 3.13
python sucss_mapping/acquire_specs.py                  # polite; cached; only fetches missing IDs
python sucss_mapping/build.py                          # parse + match + review queue + evaluation (~80 s)
python -m unittest sucss_mapping/tests/test_sucss_mapping.py
```

`sample_gold.py` re-draws the stratified sample frame. It is deterministic and does not use any matcher output.

## 1. How SUCSS publishes specifications (inspected 2026-11-06)

- The catalog page (`pages/classspec/Default.aspx`) gets its list from the `wsClassIndex.aspx/List_By_VariousMethods` JSON method. Each class links to `Detail.aspx?tblClassIndexID=<id>`. That page has only metadata (spec and exam effective dates, promotional line) and a **"View Series"** link.
- The specification text is published as **HTML per series**, not per class code, at `pages/classspec/ViewSeries.aspx?tblCS_SeriesID=<n>`. There are no PDFs. A series page lists every class in the series with its code, title, occupational area, probationary period, **Class Spec Effective Date**, exam effective date and last action. It then gives:
  - a Series Narrative;
  - DESCRIPTIONS OF LEVELS OF WORK: for each class, a level description and the list "A(n) <title> typically - …". This list is SUCSS's version of "Characteristic Duties and Responsibilities".
  - MINIMUM ACCEPTABLE QUALIFICATIONS: for each class, a credentials block and the KSAs.
- An invalid series ID returns HTTP 200 with the page title `Error Invalid Search`.
- **robots.txt** contains `Disallow: /pages/classpec/Detail.aspx`. The path is misspelled ("classpec"), and the file also disallows `/specs/detail.aspx` and the mobile `ClassIndexDetail.aspx`. We took this as the operator not wanting robots on per-class detail pages, so we did **not** crawl `Detail.aspx`. We fetched it once by hand to understand the site, before reading robots.txt. Instead we listed `ViewSeries.aspx` IDs one after another. That path is not disallowed.

### Acquisition

- Requests were sequential with a 1.5 s delay. The User-Agent was `generic-research-client/1.0`. Everything was cached, and the script stops on any HTTP or network error. The run stopped after 60 invalid IDs in a row.
- Totals: 727 requests between 2026-11-06 08:10 and 08:31 UTC, with no errors. 643 series IDs were valid. 203 of those are empty ("No Data To Display", probably retired series).
- Files are in `data/lake/raw/sucss_specs/`, which is gitignored: `series/<id>.html` holds the raw bytes, and `manifest.jsonl` holds the URL, HTTP status, sha256, byte count, retrieval time and user agent for each request. `_probe/` holds the hand-inspection fetches.
- Coverage: **862 of the 883 catalog records (97.6%) have parsed duties and a spec effective date.** 21 class codes appear on no series page. Examples are Comptroller, Pharmacist, Engineer, Architect II/III and Development Officer. These records are matched on title only, and the abstention rule for them is stricter.
- Class code 1164 has two catalog records. Only the "Police Telecommunicator" spec exists. The "Public Safety Telecommunicator" record reuses it and is flagged `code_only_title_differs`.

## 2. Parsing (`parse_specs.py`)

- The parser is regex/structure based and has no dependencies. It extracts:
  - from the class table: effective dates, converted to ISO;
  - the narrative;
  - the level description and duty items for each class;
  - the credentials block and KSA items for each class.
- Every text field has a **source span**: `[start, end)` character offsets into the page decoded as UTF-8, pinned by `page_sha256`. Running `clean(page[start:end])` reproduces the text, and the tests check this. Spans let anyone holding the cache recover the evidence without the repository storing SUCSS text.
- Known quirks:
  - Some duty lists split one duty into several `<li>` fragments, for example "administers special check requests…: / to replace lost checks / …".
  - IT-family classes write each duty as an "option" paragraph with a heading.
  - Boilerplate such as "performs other related duties as assigned" and "performs work related to the lower level…" is dropped at matching time. The parser keeps it.

## 3. Matcher (`matcher.py`, method `sucss_duty_tfidf_v1`)

**Units.**
- SUCSS side: each duty item, plus the level description.
- O*NET 31.0 side: each of the 18,838 task statements, plus each occupation description, so that the 93 occupations without tasks still compete. Alternate titles (54,269) are used for the title component.

**Scoring.** The text model is word TF-IDF with unigrams and bigrams, light suffix stemming, English and HR-boilerplate stop words, and sublinear tf. It is fitted on the O*NET units. For each class × occupation pair:

| Component | Definition |
|---|---|
| `duty_coverage` | Mean over SUCSS units of the cosine with the best-matching O*NET unit of that occupation |
| `doc_similarity` | Cosine between the concatenated class text and the occupation's title, description and tasks |
| `title_similarity` | Maximum character 3–5-gram TF-IDF cosine between the class title (level numerals and "lead/senior/trainee" removed) and the O*NET title or any alternate title |

`evidence_index = 100·(0.35·title + 0.45·min(1, duty_coverage/0.35) + 0.20·min(1, doc/0.45))`. Bands: strong ≥ 55, moderate ≥ 40, weak below that. These bands only order candidates; they are not calibrated.

**Abstention.** No candidate is suggested when any of these holds (the top-5 candidates are still listed):
- the top-1 index is below 30;
- top-1 duty coverage is below 0.10 and title similarity is below 0.60;
- there is no spec text and title similarity is below 0.60.

**Evidence.** For each candidate, the three strongest SUCSS-unit → O*NET-task pairs are kept. Each pair records the duty reference (for example `D3`), its span, the O*NET task ID and text, and the cosine.

**Tuning.** The weights and thresholds were set before scoring the gold labels. The only things checked first were the Accountant series (excluded from the sample) and a look at about 40 non-gold top-1 results. Nothing was tuned on the gold set.

**Population results (883 records).**
- 30 records abstain (3.4%).
- Top-1 bands: 237 strong, 467 moderate, 179 weak.

## 4. Evaluation against the provisional gold set

**The gold set.** The file is `gold/provisional_gold_labels.csv`. Every row is marked `provisional_agent_label — requires HR analyst review`.

**Sampling.**
- 60 catalog records, stratified into eight job families by transparent title keyword rules: admin/business 10, finance 7, HR 6, IT 7, library/museum 5, student services 6, facilities 9, other 10.
- Within each family, records were chosen by seeded SHA-256 order (`sample_gold.py`).
- The Accountant series was excluded because it was looked at during development.

**Labelling.**
- Each label was made by reading the class's level description and duties and searching O*NET titles and alternate titles. This was done **blind to the new matcher's output**.
- Each row records a primary code, acceptable alternates (for example, a supervisor code versus the worked occupation), the duty/level references used as evidence, and a short rationale written in our own words.
- Three labels are flagged low-confidence: Anatomy Curator Coordinator, Molecular Beam Epitaxy Facility Coordinator and Senior Library Specialist.

"Acceptable" means the code is the primary or a listed alternate. "Strict" means the code is the primary.

| Metric (n = 60) | Old title-lexical | New duty matcher |
|---|---:|---:|
| Top-1 acceptable | **15 (25%)**, 95% CI 16–37% | **39 (65%)**, 95% CI 52–76% |
| Top-1 strict (primary code) | 11 (18%) | 29 (48%) |
| Top-3 acceptable | 27 (45%) | — |
| Top-5 acceptable | 31 (52%) | **54 (90%)** |
| Abstention | 0% (never abstains) | 3 / 60 (5%) |
| Top-1 acceptable when not abstaining | 15 / 60 | 38 / 57 (67%) |
| Top-5 acceptable when not abstaining | — | 53 / 57 (93%) |

**Paired comparison (top-1).**
- New right, old wrong: 25.
- Old right, new wrong: 1.
- Both right: 14.
- Both wrong: 20.

Even the baseline's "confident" rows, those with title similarity ≥ 0.35, are right only 7 of 19 times.

**By family (top-1 old → new).**

| Family | Old → new |
|---|---|
| Admin/business | 3 → 9 of 10 |
| Finance | 4 → 7 of 7 |
| HR | 2 → 4 of 6 |
| IT | 0 → 3 of 7 |
| Library | 4 → 5 of 5 |
| Student services | 0 → 2 of 6 |
| Facilities | 0 → 4 of 9 |
| Other | 2 → 5 of 10 |

**Example.** Human Resource Assistant now ranks 43-4161.00 Human Resources Assistants first. The old method ranked HR Managers first.

**Typical misses (new).** Detailed per-class results are in `outputs/evaluation_by_class.csv`.
- **Sibling occupations:** HR Manager → HR Specialists; Benefits Counselor → C&B Managers; Security Officer → Transportation Security Screeners; Plumber Sub-Foreman → plumber/pipefitter helpers.
- **"Postsecondary education administrator" pull:** university vocabulary in the duties pulls toward this code. This affects Admissions and Records Representative/Assistant, and IR Data Coordinator. Academic Contract Specialist went to an adult-education instructor code.
- **Alternate-title over-reach:** examples are Building Automation Technician → Energy Engineers and IT Technical Associate → Computer User Support Specialists. The same pattern appears in the non-gold rows: Roofer → Helpers--Roofers and Police Captain → Transit and Railroad Police.
- **No good O*NET home:** the two low-confidence classes abstained or missed.

## 5. Review queue for HR analysts

- `outputs/review_queue.csv` and `.parquet` have one row per class × candidate: 883 × 5 = 4,415 rows.
- The queue is sorted by priority:

  | Priority | Classes |
  |---|---:|
  | `1_abstained` | 30 |
  | `2_weak` | 149 |
  | `3_close_call` (top-1 margin < 3 points) | 196 |
  | `4_confirm` | 508 |

- Each row includes the series URL, the spec effective date, the evidence index and its components, the old baseline's top-1, three evidence pairs, and blank reviewer columns (`reviewer_decision`, `reviewer_onetsoc_code`, `reviewer`, `reviewed_on`, `reviewer_notes`).
- The committed queue shows SUCSS evidence only as duty references and character spans. `build.py` also writes `local/review_queue_with_sucss_text.csv` (gitignored), which adds the matched SUCSS duty sentence beside each O*NET task. Analysts who have the cache should work from that file.

Other outputs:
- `outputs/spec_coverage.parquet`: one row per catalog record, with series ID, URL, page hash, retrieval time, effective dates and section counts.
- `outputs/spec_spans.parquet`: spans and 16-hex text hashes only.
- `outputs/candidates.parquet`: the top-5 candidates with evidence as JSON references.
- `outputs/summary.json`: all the numbers above.

## 6. Licensing and terms

- **SUCSS.** The site's "Terms and Conditions" page covers "This website and the secure section". It says materials are SUCSS property and grants permission "to use, copy and distribute these materials as presented on the Secure Site, without alteration, for the furtherance of State Universities Civil Service System purposes only". It is unclear whether this covers the public class-spec pages, and whether derived research use counts as "furtherance of SUCSS purposes".
  - **We therefore committed no SUCSS specification text, not even short spans.** Git holds only IDs, URLs, hashes, offsets, counts, scores and O*NET text.
  - Raw pages are in the gitignored lake. Parsed text and the text-bearing queue are in `sucss_mapping/local/`, which is gitignored by `sucss_mapping/.gitignore`.
  - The test fixtures are synthetic pages that copy the markup with invented wording.
  - A test fails if any committed review-queue row contains a parsed duty sentence.
  - Get permission from SUCSS before publishing any spec text.
- **O*NET 31.0** is CC BY 4.0. Task statements appear in the queue. Attribution: O*NET 31.0 Database, U.S. Department of Labor, Employment and Training Administration (USDOL/ETA), used under CC BY 4.0. O*NET® is a trademark of USDOL/ETA. The mappings are ours and are not endorsed by USDOL/ETA.

## 7. Honest limits

- **One labeller, and an AI.** The gold labels were made by the same agent that built the matcher. That agent was blind to the matcher's ranks but knew the method. The acceptable-alternate sets are fairly generous, and choices such as supervisor versus worker codes are judgement calls. An HR analyst should re-label, ideally two analysts with an agreement check, before any of these numbers is quoted.
- **Small sample.** With n = 60, a family-level difference of one or two classes is noise.
- **Lexical method only.** There are no embeddings and no learned weights. University-specific vocabulary such as "student" and "campus" biases candidates toward education codes. Alternate-title matching sometimes beats the duty evidence. The abstention rule fires rarely (3.4%), so many wrong top-1 answers still come out as "suggested". Use the bands and the close-call priority, not the top-1 alone.
- **Level is ignored.** Levels within a series (I/II/III) often share an O*NET code. The matcher does not model job zone or seniority, so supervisor-versus-worker choices are weak.
- **What is not used yet.** MAQ credentials and KSAs are parsed but not used for matching. They could feed job-zone and education checks later.
- **Coverage and staleness.**
  - The 21 records without a series page are matched on title only.
  - 203 empty series pages were not investigated.
  - The pages describe the specs as of 2026-11-06. Effective dates range back many years, so some specs may be stale relative to actual jobs.
- **Not a workforce measure.** Catalog classes are not employees or vacancies. Nothing here weights or allocates headcount.
