# Survey text intelligence (solution #8): local and governed

This folder builds solution #8 from the [SP&P opportunity brief](../research/IHR_STRATEGIC_PROGRAMS_OPPORTUNITY_BRIEF.md): theme extraction from Workplace Satisfaction and exit-survey comments, joined to eNPS and turnover at aggregated segment level. It is designed for approved on-prem machines. Inference is local, and nothing in the pipeline can call a remote model.

> **All data here is SYNTHETIC.** `generate_synthetic.py` invents every response, unit, name, e-mail (`example.edu`), phone number (`555-01xx`) and UIN from a seed. None of the numbers in the dashboard describe real people or units, and the dashboard states this in a banner.

Dashboard: [`../output/survey_text/survey_insights.html`](../output/survey_text/survey_insights.html). It is one offline file with vanilla JS and inline SVG, no network requests, light and dark themes, and a layout that works at phone width.

## Run

From `platform-evaluation/`:

```bash
pip install -r survey_text/requirements.txt         # Presidio + spaCy are optional
python -m spacy download en_core_web_sm             # optional; enables the Presidio layer
python survey_text/generate_synthetic.py            # seeded synthetic Qualtrics-style exports
python survey_text/pipeline.py                      # redact -> code -> evaluate -> aggregate -> HTML
python -m unittest discover -s survey_text/tests -v # 23 tests
python survey_text/quotes.py list                   # human quote review (see below)
```

The pipeline runs in about 25 s with Presidio and about 3 s without it (`--no-presidio`). The tests take about 11 s and run without Presidio, except for one Presidio test that is skipped if Presidio is not installed.

## Data flow on an approved machine

```text
Qualtrics export (CSV, 3-header layout)          Banner/EDW directory extract (names only)
  ws_export.csv / exit_export.csv                  roster_names.csv
          │  raw text is read here only, never copied        │
          ▼                                                  ▼
  redact.py  regex (e-mail, phone, UIN, SSN, URL) → cue names ("my supervisor X", "Dr. X", signatures)
             → roster names → optional Presidio NER (with a common-word guard)
          │  redacted text only from here on
          ▼
  coding.py  lexicon coder (codebook.yaml) ─┐        llm_coder.py  (OFF by default; loopback-only
             TF-IDF + NMF topic discovery   ├─ theme codes      OpenAI-compatible endpoint, e.g. vLLM /
                                            │                   llama.cpp / Ollama on this machine)
  scoring.py gold sample → P/R/F1 per theme, Cohen's kappa, inter-rater kappa (no LLM judge)
          ▼
  analytics.py eNPS + CI by segment · theme prevalence · drivers (RR, logistic OR) · exit-reason trends ·
               unit eNPS vs turnover   ── all with k ≥ 10 small-cell suppression
          ▼
  artifacts/survey_text.duckdb  (LOCAL ONLY: responses_redacted, theme_codes, quote_approval)
  artifacts/published/survey_insights.json  (aggregates only)  →  output/survey_text/survey_insights.html
```

- **Raw text** exists only in the export files. The DuckDB store holds redacted text, and only on the approved machine. Only `artifacts/published/` and the HTML are meant to leave it.
- **Small cells.** k comes from `codebook.yaml` (`min_cell_size: 10`). A cell with n < k is withheld, and so is its n. Counts of 1–9 are masked. When exactly one segment in a dimension is suppressed, the next-smallest segment is also suppressed (complementary suppression), so the hidden value cannot be worked out from the total. A relative-risk driver is published only when every cell of its 2×2 table is at least k. In the synthetic run, "Field Research Station" is suppressed (n < k) and "Human Resources Office" is suppressed as its complement.
- **No verbatim quotes by default.** The pipeline proposes candidate quotes and stores them in the local `quote_approval` table as `pending`. A named person approves or rejects each one with `quotes.py approve <id> --approver "Name"`. Only approved quotes that still pass redaction are published. A test confirms that no 6-word fragment of any comment appears in the published JSON or HTML. Reviewers must also check identifiability from context (a unit, a role and an unusual detail), which no automated check can guarantee.
- **No individual scoring.** No person-level score is computed or published. The unit-level eNPS-versus-turnover view is an association between aggregates (HB 3773, brief §7).

## What is here

| File | Purpose |
|---|---|
| `generate_synthetic.py` | Seeded generator. Writes 3,000 Workplace Satisfaction responses over 2 waves (eNPS 0–10 + comment) and 800 exit responses over 2024Q1–2026Q3 (primary reason, 0–10 recommend, comment), with unit, role family and tenure band. Comments are assembled from varied templates across the 10 themes. About 12% of theme sentences are "implicit" phrasings that avoid the lexicon words. 281 PII-like decoys are planted in 226 comments. Also writes synthetic headcount and separations, a synthetic roster, ground-truth themes and a simulated double-coded gold sample |
| `codebook.yaml` | 10 themes with definitions, include and exclude notes, lexicon and exclusions. Status: **draft, not reviewed** |
| `redact.py` | Layered PII redaction, described above |
| `coding.py` | Deterministic lexicon coder and TF-IDF + NMF topics (unigrams with min_df = k, seeded) |
| `llm_coder.py` | Pluggable local-LLM coder (see "Local-LLM coder" below) |
| `scoring.py` | Gold-sample scorer: per-theme precision, recall, F1 and Cohen's kappa, micro/macro F1, exact match, inter-rater kappa |
| `analytics.py` | eNPS with Wald 95% CI, prevalence, relative risk with Katz CI, numpy IRLS logistic regression with Wald CIs, share tables, suppression |
| `pipeline.py` | Orchestration, local DuckDB store, published JSON, run manifest with input hashes |
| `render_dashboard.py` | Offline HTML dashboard |
| `quotes.py` | Human approval workflow for verbatim quotes |
| `tests/test_survey_text.py` | 23 unittest tests |

### Gold sample format

`data/<source>/gold/gold_sample.csv` has one row per response per coder:

```csv
ResponseId,coder_id,themes,coded_on,codebook_version
R_abc,coder_A,pay;workload,2026-12-01,0.1
R_abc,coder_B,pay,2026-12-01,0.1
R_abc,ADJUDICATED,pay;workload,2026-12-03,0.1
```

Two people code independently. Rows marked `ADJUDICATED` are the reference where they exist; otherwise the first coder in sorted order is used. Inter-rater kappa between the first two coders is reported as the practical ceiling for any automated coder. **In this synthetic build the gold is simulated:** coder A is the generator's truth and coder B is that truth with 4% random label flips. It is labelled `*_SIMULATED` everywhere.

### Local-LLM coder (`llm_coder.py`)

- **Off unless enabled.** It runs only when `SURVEY_TEXT_LLM_ENABLED=1`. The endpoint is `SURVEY_TEXT_LLM_ENDPOINT` (default `http://127.0.0.1:8000/v1`) and the model is `SURVEY_TEXT_LLM_MODEL`. By default it codes the gold sample only (`SURVEY_TEXT_LLM_SCOPE=gold`), so it can be scored against the lexicon before anyone relies on it. `SURVEY_TEXT_THEME_SOURCE=llm` makes the analytics use its codes.
- **Loopback only.** Any endpoint that is not `localhost`, `127.0.0.0/8` or `::1` is refused before a socket opens. That includes LAN IPs, public hosts, `localhost.evil…`, userinfo tricks, `0.0.0.0` and IPv4-mapped public addresses. A GPU box elsewhere on an approved network is reached through an SSH tunnel to localhost, so the network path is an explicit operator decision.
- **No proxies or redirects.** Requests ignore `HTTP(S)_PROXY`, because a proxy would carry the text off the machine, and redirects are refused.
- **Redacted input only.** Text is redacted again just before sending. If the regex layer still finds PII, the call aborts.
- **Constrained output.** Temperature is 0. Output must be `{"themes": [...]}` using codebook ids only; anything else is dropped and counted.
- **Coding only.** The LLM codes themes. It never grades anything, scores people, or judges another model.

## Results on the synthetic data (honest reading)

| Check | Result |
|---|---|
| Redaction recall, 281 planted decoys | regex alone 31.7% (100% of e-mails, phones and UINs; 0% of names) · + cue 90.0% · + roster **100%** · + Presidio (en_core_web_sm) 100%. Presidio added no extra catches here |
| Redaction false positives on clean synthetic comments | 0 with regex + cue + roster. Presidio without the common-word guard tagged sentence-initial "Morale" as a PERSON 44 times; with the guard it found 0 |
| Lexicon coder vs simulated gold (400 responses) | micro P 0.90 / R 0.88 / **F1 0.89**, macro F1 0.88, exact match 68%. Weakest themes: recognition (P 0.59, from "thanks" and "credit" in other contexts), manager support (R 0.77) and remote/hybrid (R 0.80) |
| Simulated inter-rater kappa | 0.72–0.91 by theme. By construction this is noise injected by the generator; it is not a measured human agreement |
| eNPS | 2025: −14.5 (95% CI −18.7 to −10.3); 2026: −16.1 (−20.3 to −12.0) |
| Drivers (adjusted OR for a detractor score) | workload 4.1, career growth 2.1, pay 2.0, culture 1.9, bureaucracy 1.7, … These were planted by the generator, so recovering them only shows that the pipeline works |

**These scores are not accuracy estimates for real comments.** The same author wrote the generator's templates and the lexicon, so the synthetic F1 is an optimistic pipeline check. Real comments will contain misspellings, sarcasm, mixed topics, references specific to campus life, and names that are not in the roster and have no cue in front of them. Expect lower recall in both redaction and coding.

Other known limits:
- The themes record presence, not sentiment. Positive and negative mentions of manager support or hybrid work pull in opposite directions, so their pooled driver estimates are blurred. Adding valence coding is the next step.
- The drivers are associations between coded comment content and scores. They do not show causes. Comment writers are a self-selected subset of respondents, and coder error attenuates the estimates.
- Exit-survey respondents are a subset of all separations. The turnover rate comes from separations ÷ headcount, not from survey counts.
- The last exit-trend period (2026H2) contains only one quarter.

## Why not Snowflake/Databricks AI functions or Qualtrics Text iQ for this

This is about the governance profile: sensitive HR free text, Illinois HB 3773, a "local models for Sensitive data" rule, and a requirement to suppress small cells and keep human approval. It is not a judgement on the tools' general quality. Evidence comes from this repository's research files.

- **Snowflake Cortex AI functions** (`AI_CLASSIFY`, `AI_SENTIMENT`, `AI_AGG`, `AI_REDACT`, `AI_COMPLETE`):
  - **Hosted models.** These send prompts to models that Snowflake hosts, and model choice is curated by region.
  - **Cross-region inference.** If a model is missing in-region, prompts are processed in another region, possibly on another cloud. Snowflake docs say organizations created after 2026-03-09 default to `ANY_REGION` (`CORTEX_ENABLED_CROSS_REGION`). An administrator has to find and restrict this setting; nothing protects HR text by default. See [SNOWFLAKE_AI_CAPABILITIES.md](../research/SNOWFLAKE_AI_CAPABILITIES.md).
  - **Redaction is best-effort.** Snowflake describes `AI_REDACT` as best-effort and asks users to review its output.
  - **Missing pieces.** None of these functions provides gold-sample evaluation, kappa, small-cell suppression or a quote-approval workflow.
- **Databricks AI Functions** (`ai_query`, `ai_classify`, `ai_extract`):
  - **Hosted models.** These call Databricks-hosted or external serving endpoints. Pay-per-token models "may be hosted cross-region or by partners; check per model", and whether a function runs in-geo has to be confirmed function by function. See [DATABRICKS_AI_CAPABILITIES.md](../research/DATABRICKS_AI_CAPABILITIES.md).
  - **Logging risk.** AI Gateway payload logging creates a new store of sensitive text.
  - **No quality metrics.** `ai_classify` returns no calibrated confidence and has no built-in metrics. You would still have to build the gold set, scorer and suppression shown here.
  - **Possible mitigation.** Provisioned endpoints with open-weight models inside a governed workspace could narrow the gap. That still puts survey text on a cloud platform, which needs a data-use decision of its own.
- **Qualtrics text analytics (Text iQ):**
  - **Stays inside Qualtrics.** Analysis runs inside Qualtrics, and campus guidance notes that "data is stored by Qualtrics" ([UIUC_HR_AND_AI_TOOL_LANDSCAPE.md](../research/UIUC_HR_AND_AI_TOOL_LANDSCAPE.md)). Its topics and sentiment cannot be joined, inside Qualtrics, to Banner unit hierarchies, separations or headcount under our suppression rules.
  - **Not reproducible or auditable.** It does not produce a reproducible, versioned codebook with deterministic scores against a human gold set, and its models and their changes are the vendor's.
  - **Licensing.** Whether the campus license includes Text iQ was not verified.
  - **Still the right collection point.** The pipeline here consumes standard Qualtrics CSV exports.
- **The approach here:**
  - **Open formats.** The codebook is YAML, the scorer is deterministic and the store is DuckDB.
  - **Local inference.** Inference is local and loopback-only.
  - **Swappable coder.** The same code runs with only the lexicon, or with any open-weight model served by vLLM, llama.cpp or Ollama (candidates in [TOOLS_BEYOND_SNOWFLAKE_DATABRICKS.md §5](../research/TOOLS_BEYOND_SNOWFLAKE_DATABRICKS.md)).
  - **Portable outputs.** The published aggregates can be delivered anywhere (Power BI, Tableau, this HTML file).

## Evaluation plan (before any real use)

1. **Data-use approval.** Agree with SP&P, HR and the privacy office on the data-use note, the k value (10 is proposed), the consent language in the survey invitations, and who may approve quotes.
2. **Codebook review.** HR analysts review and revise `codebook.yaml` on about 100 real comments, then freeze version 1.0.
3. **Gold set.** Draw a stratified random sample of 400–600 redacted comments covering both surveys, all waves and all major units. Two trained coders label it independently, then adjudicate. Target kappa ≥ 0.6 per theme before using that theme; themes below the target get their definitions revised.
4. **Split the gold set.** Hold out half of it. Tune the lexicon on the development half only, and report held-out P/R/F1 and kappa per theme with bootstrap CIs.
5. **Local-LLM candidates.** Run two or three open-weight models (for example gpt-oss-20b or Mistral Small 3.2, both Apache 2.0, plus one more) on the same held-out set at temperature 0, scored by `scoring.py` only. Adopt an LLM coder only if it beats the lexicon by a pre-registered margin, such as +0.05 macro-F1, with no theme dropping below 0.6 kappa. Pin the model, server version and prompt hash in the run manifest.
6. **Redaction audit.** A human reads all 600 gold comments after redaction and counts residual identifiers by type. The pass criterion is zero direct identifiers; any miss becomes a new test case. Load the real roster from the directory extract on the approved machine only.
7. **Stability.** Re-run on the prior year's data and compare theme prevalence and driver rankings. Check sensitivity to k (10 vs 15) and to the theme source (lexicon vs LLM).
8. **Pre-publication review.** Before anything leaves the machine, a second analyst checks every published table for suppression and confirms that only approved quotes appear.
