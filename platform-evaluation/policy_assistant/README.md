# Policy assistant: governed HR policy Q&A over public pages

This is the retrieval half of solution #10 in the [opportunity brief](../research/IHR_STRATEGIC_PROGRAMS_OPPORTUNITY_BRIEF.md). The [custom stack](../custom_stack/README.md) answers metric questions from governed definitions. This package answers **policy and process** questions by quoting public Illinois HR pages, with citations. It follows the same discipline as the custom stack:

- Every answer cites its source passages and records when each page was retrieved.
- It abstains instead of guessing.
- Refusals come from explicit rules, not model behaviour.
- The evaluation is deterministic. No LLM grades anything.

It runs fully locally. After the crawl, there are no network calls and no LLM by default.

It is a **prototype over public pages**. It is not an approved HR service and has not been reviewed by IHR, University Counsel or Labor & Employee Relations. Its answers are quotes, not determinations.

```
crawler.py     polite crawl -> data/lake/raw/hr_policy_pages/{pages/*.html, manifest.jsonl, crawl_log.jsonl, crawl_summary.json}
extract.py     HTML -> heading/text blocks (drops header/nav/footer/breadcrumbs/scripts), title, "last updated" text, links
chunker.py     heading-aware passages; each keeps URL, #anchor, heading path, page hash, retrieved_at, last-updated
build.py       chunks.jsonl + DuckDB (pages, chunks, build_info) under data/lake/raw/hr_policy_pages/build/
retrieval.py   BM25 (always) + Embedder interface (local LSA bundled, OFF by default), reciprocal-rank fusion
answerer.py    policy guard -> retrieval -> evidence gate -> cited passages + templated extractive summary
llm.py         OPTIONAL local OpenAI-compatible synthesis; loopback hosts only; OFF by default
demo.py        single-file offline HTML (index embedded) -> output/policy_assistant/index.html
demo_engine.js JS port of tokenizer/BM25/gate used by the demo; parity-tested against Python with node
eval/          questions.json (40), score.py, results_*.json|md
tests/         unittest (offline; fixtures + fake fetcher; node parity when node is present)
```

## Run

From `platform-evaluation/` (Python 3.13; standard library, plus `duckdb` for the build tables; `scikit-learn` only for the optional embedder):

```bash
python -m policy_assistant.cli crawl          # network: robots.txt obeyed, <= 1 req/s, <= 300 pages
python -m policy_assistant.cli build          # chunks + DuckDB
python -m policy_assistant.cli ask "What is the Employee Assistance Program?"
python -m policy_assistant.cli ask "Am I eligible for FMLA?"        # -> abstain (individual advice)
python -m policy_assistant.cli eval                     # BM25 only (default)
python -m policy_assistant.cli eval --embeddings lsa    # hybrid, for comparison
python -m policy_assistant.cli demo           # output/policy_assistant/index.html (open from disk; works offline)
python -m unittest discover -s policy_assistant/tests -t .
node policy_assistant/screenshot.js           # optional; needs the playwright npm package
```

The crawled pages and derived chunks are under `data/lake/`, which is gitignored. A fresh clone has to crawl and build before `ask`, `eval` or `demo` will run. The tests do not need the crawl. The two corpus-dependent tests skip when the corpus is absent.

## Results (crawl of 2026-11-06)

**Corpus.** 152 requests (142 page fetches), all ≤ 1 req/s, finished in about 5 minutes. 109 pages stored, giving 1,417 passages (median about 50 words). 19 boilerplate blocks were removed. The demo HTML is 1.1 MB and embeds the full index, so no subsetting was needed.

| Host | Pages | Status |
|---|---:|---|
| humanresources.illinois.edu | 87 | crawled (sitemap + 2 hops); 5 pages skipped as `noindex` (e.g. faculty phased retirement, service catalog) |
| www.sucss.illinois.gov | 13 | crawled; robots.txt paths obeyed (job, class-spec detail and search pages excluded) |
| ihr-hub.illinois.edu | 6 | no robots.txt (404); root 404; linked documents crawled (e.g. classifications that cannot work remotely) |
| news.illinois.edu | 2 | only HR-topic slugs linked from IHR pages |
| illinoishumanr.web.illinois.edu | 1 | tiny (FSAWS annual report stub) |
| **www.hr.uillinois.edu** (System HR) | 0 | **robots.txt is behind a Cloudflare bot challenge (HTTP 403)**. It is treated as disallow-all and was not circumvented. This is where most detailed leave and benefit policy text lives: IHR's Leaves page links 56 times to it |
| **answers.uillinois.edu / answers.illinois.edu** | 0 | **blocked by this environment's egress proxy** (CONNECT 403). The Answers knowledge base was not indexed |
| cam.illinois.edu (Campus Administrative Manual) | 0 | not on the allowed-host list; links to it are not followed |

**Evaluation.** The scorer is `eval/score.py`, and results are in `eval/results_*.{json,md}`. The 30 answerable questions have gold URLs (2 on SUCSS, 1 on ihr-hub, 27 on IHR). The other 10 are unanswerable: 5 out of scope or coverage, and 5 that policy requires the assistant to refuse.

| Run | ret hit@1 | hit@3 | hit@5 | MRR@5 | answer hit@3 | abst. precision | abst. recall | unsafe answers | over-abstentions |
|---|---|---|---|---|---|---|---|---|---|
| Dev set, BM25 (default) | 0.90 | 0.97 | 1.00 | 0.94 | 0.97 | 1.00 | 0.90 | 1 | 0 |
| Dev set, BM25 + local LSA (RRF) | 0.87 | 0.93 | 1.00 | 0.92 | 0.93 | 0.90 | 0.90 | 1 | 1 |
| 12 untuned paraphrases, BM25 | 0.78 | 0.78 | 0.89 | – | 0.33 | 0.375 | 1.00 | 0 | 5 (+1 answered from the wrong page) |
| 12 untuned paraphrases, BM25 + LSA | 0.67 | 0.78 | 0.78 | – | 0.33 | 0.33 | 1.00 | 0 | 6 |

How to read this:

- **The dev set is a visible development set.** I wrote the questions after reading the crawled pages, so they share the pages' vocabulary. The coverage threshold (0.6) and BM25 floor (6.0) were set before the first eval run and not changed afterwards. On the dev set, answerable questions had coverage ≥ 0.64 and out-of-scope questions ≤ 0.46, except one.
- **Dev-set tuning that did happen:**
  - One policy rule was broadened after a miss: "rank these *three* applicants" now matches.
  - The sentence picker was changed to prefer passage [1].
  - SUCSS extraction was fixed: ASP.NET wraps whole pages in `<form>`.
- **The one unsafe answer is U02**, "out-of-state undergraduate tuition". "out" is a stopword, so the query reduces to *state undergraduate tuition*. That matches the child tuition-waiver passage, so the assistant answers with a quote about tuition waivers. The answer is cited and on a related page, but it does not answer the question. This is the inherent weakness of a lexical gate.
- **The paraphrase set is the more honest number.** It was written after seeing the dev results and was not used for tuning.
  - The individual-advice guard over-refuses general questions phrased in the first person: "Do I get paid for unused floating holidays…", "Can I use sick leave to care for my child?", "What documents should I bring for the I-9?". That failure is safe, but it costs usefulness.
  - Vocabulary mismatch causes abstention: "e-cigarettes" vs "vaping"; "deadline to pick health insurance" vs "30 calendar days … choose coverage".
  - One question, "free therapy", was **answered from the wrong page**: the tobacco-cessation FAQ and a community-resource list instead of FSAWS counseling. The citations make that visible, but it is a miss.
- **Local LSA embeddings did not help** on either set, so they stay off. A real sentence-embedding model on an approved machine is the next thing to try, through the `Embedder` interface. The hit@k and abstention numbers above are the bar it has to beat.
- **The JS demo engine reproduces the Python answerer** (status, reason and cited URLs) on all 40 dev questions (`tests/test_demo_parity.py`, run with node). The demo works with the browser offline: the Playwright screenshots run in an `offline: true` context.

Screenshots: `output/policy_assistant/screenshot_desktop_light.png`, `screenshot_desktop_dark_abstain.png`, `screenshot_phone_dark.png` (390 px wide, no horizontal overflow).

## Design

**Crawl (provenance first).**
- Seeds come from the IHR WordPress sitemap and a short list of seed URLs. Links are followed up to 2 hops, within an allow-list of hosts and path rules (`config.in_scope`).
- `news.illinois.edu` pages are kept only when the URL slug names an HR topic.
- `robots.txt` is obeyed. When it cannot be read (HTTP 401/403, or a bot challenge), the host is treated as disallow-all.
- Pages with `<meta name="robots" content="noindex">` are not stored.
- Requests are spaced ≥ 1.1 s apart. The page budget is 300.
- Each stored page gets a manifest row with these fields:
  - `url`, `requested_url`
  - `retrieved_at`, `sha256` (raw bytes), `text_sha256` (extracted text, used for de-duplication)
  - `title`, `last_updated_shown` (only when the page itself displays a date) and `meta_modified` (the CMS `article:modified_time`, which the page does not show)
  - `depth`, `discovered_from`
- Every skipped or blocked attempt is in `crawl_log.jsonl`.

**Chunks keep their context.** Each passage carries its heading path (page title › section › subsection). It also carries the nearest heading `id` as a `#anchor`; when there is none, a `#:~:text=` fragment links to the exact text. Text blocks repeated on many pages, such as site banners and contact boxes, are dropped as boilerplate.

**Retrieval.** BM25 (k1 1.2, b 0.75) is computed over title, heading path and body, with at most 2 passages per page in the top k. `Embedder` is the interface for dense retrieval. The bundled `LsaEmbedder` (TF-IDF → SVD) is local and downloads nothing. A sentence-transformer, or an embedding endpoint on Illinois Chat, can implement the same two methods on an approved machine. Fusion is reciprocal-rank (k = 60). **Dense similarity never decides whether to answer.** The evidence gate uses lexical evidence only, so a nearest neighbour cannot turn an unsupported question into an answer.

**Answer or abstain (all deterministic, traced).**
1. *Policy guard.* Regex rules abstain on:
   - individual advice ("am I eligible", "should I", "my case")
   - legal determinations ("is it legal", "can I sue", "wrongful termination")
   - employment decisions about people ("should we fire", "rank these candidates", "who is likely to quit")
   - a named person's records
   - instruction injection

   These rules run before retrieval, and the response is a referral to unit HR or IHR. This is the HB 3773 posture from the brief: the assistant quotes policy and never makes or recommends decisions about people.
2. *Evidence gate.* The best passage must cover at least `MIN_COVERAGE` of the question's content terms, weighted by IDF. Terms never seen in the corpus get the maximum IDF, so an off-topic question cannot pass on one common word. Its BM25 score must also be at least `MIN_TOP_SCORE`. When the gate fails, the assistant abstains and lists the closest pages as "places to look, not an answer".
3. *Answer.* The answer is the supporting passages, each with a citation. A templated summary quotes the 1–2 best-matching sentences verbatim with `[n]` markers. It then adds a freshness line: the retrieval date, plus whatever update date the page shows, or "no update date shown".
4. *Optional synthesis.* `llm.py` is off unless `POLICY_ASSISTANT_LLM_ENDPOINT` and `POLICY_ASSISTANT_LLM_MODEL` are set.
   - It accepts loopback hosts only (localhost, 127.0.0.0/8, ::1), with no override, and uses a no-proxy opener.
   - It runs only after the deterministic layer has decided to answer, and sees only the cited passages.
   - It must cite `[n]` for passages it was given. Otherwise its text is discarded, and the extractive summary stands either way.
   - It cannot change the status.

## Why platform search services don't supply this

Snowflake Cortex Search, Databricks Vector Search (and Mosaic AI Agent Framework), Azure AI Search and Vertex AI Search are good *retrieval engines*. Any of them could replace `retrieval.py` at scale. What they do not supply is the governance around retrieval, and that is most of this package:

| Discipline | What the platform gives | What this package adds |
|---|---|---|
| **Evaluation** | Tooling to run evals: Agent Evaluation, Cortex/TruLens-style feedback functions. The default "correctness/groundedness" judges are LLMs | A fixed question set with **gold source URLs** written from the crawled pages, plus a scorer for hit@k, MRR and abstention precision/recall. No model grades a model, so results are reproducible and auditable, and two platforms can be scored on the same set |
| **Abstention** | A ranked list always comes back, with a relevance score that is not calibrated across queries. Refusal is left to the LLM prompt | An explicit, testable gate (coverage + score) and **policy refusals that run before retrieval**: individual advice, legal determinations, employment decisions. These are the HB 3773 and civil-service constraints. They are rules, with unit tests, not prompt instructions |
| **Freshness** | Incremental index refresh from a table or volume. Nothing knows whether the *source page* changed or how old it is | A manifest with retrieval time, content hash and the page's own "last updated" text. Every answer shows how old its evidence is. The refresh plan below re-crawls and diffs by hash |
| **Provenance** | Chunk IDs and a source column, if you model them | Heading path + anchor/text-fragment deep links + page hash for every passage, and an `ask --json` trace of query terms, unknown terms, thresholds and the gate result |
| **Scope** | Whatever is loaded | A crawl allow-list, robots/noindex compliance, and a crawl log listing what was *not* indexed. Unindexed sites lead to abstention, not guesses |
| **Portability** | Index locked to the platform | Plain JSONL + DuckDB + a 1-file offline demo. The same eval set scores Cortex Search or Vector Search if they are swapped in behind `Retriever.search` |

To score a platform retriever, export its top-5 URLs per question and compute the same metrics with `eval/score.py` logic: retrieval hit@k against `gold_urls`. The abstention decision is still made by `answerer.py` unless the platform's own refusal behaviour is being evaluated. In that case, a human labels each response answer/abstain from the transcript, as in `custom_stack/eval`.

## Running on Illinois Chat local models

The brief notes that Illinois Chat's locally hosted models are the approved option for Sensitive data. For *public* policy pages, no LLM is needed at all; the extractive mode is the default. If IHR wants fluent summaries:

1. Run the package on an approved University machine. Expose the Illinois Chat local model, or an Ollama/vLLM server hosting an approved open-weights model, as an OpenAI-compatible endpoint **on loopback** (directly, or through an SSH tunnel that terminates on 127.0.0.1).
2. Set `POLICY_ASSISTANT_LLM_ENDPOINT=http://127.0.0.1:<port>/v1` and `POLICY_ASSISTANT_LLM_MODEL=<model>`. Remote hostnames are refused by design. If an approved Illinois Chat API is reachable only on a University hostname, add that single host to an allow-list in `llm.assert_local` after a security review. Do not loosen it to "any host".
3. Keep the eval unchanged. Synthesis can't change answer/abstain, so citation hit@k and abstention metrics stay valid. Add a human-rated sample of synthesized summaries (faithful / unfaithful to the cited passages) before turning synthesis on for users.
4. Embeddings: implement `Embedder.fit/encode` against the local embedding model, then run `eval --embeddings <name>`. Keep it only if it improves hit@k without hurting abstention.
5. The same `answer()` function can be exposed as an MCP tool next to `custom_stack/mcp_server` (`search_policy`, returning the cited JSON). Illinois Chat or Copilot agents then get cited policy passages and governed metrics from one place.

## Refresh plan

| Cadence | Action |
|---|---|
| Weekly (scheduled job on an approved machine) | `crawl` → compare each page's `text_sha256` with the previous manifest → `build` → `eval` → `demo`. Publish only if the eval shows no new unsafe answers and no hit@k drop beyond 1 question. Keep the previous manifest for diffing |
| On change | Pages whose text hash changed are listed in a diff report to the IHR content owner. Any eval question whose gold page changed is re-checked by a person. Questions whose gold page disappeared become "expected abstain" until rewritten |
| Before benefits Open Enrollment, July 1 policy changes and the January HB 3773-related updates | Force a full re-crawl, and have a human reviewer re-read the gold passages for the affected questions |
| Every answer | Shows the retrieval date and any page-shown update date. Passages older than a configurable age (e.g. 120 days since retrieval) should be flagged as stale. Not implemented yet; it is a small change in `answerer.freshness_note` |
| Coverage | Re-try blocked hosts each cycle (see the limits below). If IHR provides an approved export of the System HR policy site or the Answers knowledge base, add it as a source instead of scraping around a bot challenge |

## Limitations (honest list)

- **Coverage gap: System HR policy pages and the Answers knowledge base are missing.** They hold most detailed leave, benefits and FMLA rules. As a result, many real employee questions abstain, or are answered from IHR summary pages or the SUCSS Merit Board benefits policy instead. Do not deploy before a sanctioned source exists for those pages: an export, or permission and an allow-listed crawler identity.
- PDFs, DOCX and RTF files (policy fact sheets, FMLA templates) are not indexed. Only HTML is.
- Pages marked `noindex` were respected. A few public IHR pages, such as Faculty Phased Retirement, are therefore absent.
- The policy guard uses regular expressions. It catches the phrasings it was written for, and it over-refuses first-person questions about general policy (see the paraphrase results). A small rule-plus-classifier approach on local models, evaluated on a labelled set of a few hundred questions, would be the next step. Its errors should still fall toward refusal.
- The evidence gate is lexical, and IDF-weighted coverage is not semantic entailment. A passage can contain all the query words and still not answer the question (U02, P03). Citations make that visible to the reader, but do not prevent it.
- The summary is extractive and templated. It quotes sentences verbatim but can join two quotes that are each true yet read oddly together. The passages are the answer; the summary is a pointer.
- The eval is small: 40 dev questions + 12 paraphrases, all written by one person (an AI assistant) and not reviewed by IHR. Before any claim of fitness, IHR staff should write a held-out set from real Service Center questions (de-identified), and a second rater should label it.
- The local-LLM synthesis path is tested only with a fake transport. No real model was run here, and its faithfulness has not been evaluated.
- The crawler identifies itself in its User-Agent but provides no contact address. Add one before any scheduled use.
- `output/policy_assistant/` is not gitignored (only `data/lake/` is). `index.html` embeds about 1.1 MB of public page text. Decide whether to commit it or regenerate it.
