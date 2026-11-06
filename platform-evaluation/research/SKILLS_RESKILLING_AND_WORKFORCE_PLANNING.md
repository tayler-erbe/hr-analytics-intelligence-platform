# Skills, AI Reskilling, Workforce Planning, Mobility and Succession in Higher Ed and Public-Sector HR

**Research date:** 2026-11-06. **Method:** targeted web searches plus prior knowledge, cut off June 2026. Items marked *(verify)* rest on secondary or vendor sources, or on recall, and need a check against the primary source before anyone cites them.
**Audience:** a data/AI engineer supporting an Assistant Chancellor at UIUC who leads HR Data & Analytics, Strategic Workforce Planning (SWP), Talent Mobility, Succession Planning, and AI Professional Development & Reskilling.
**Data-handling note for this repository:** under AGENTS.md, real position descriptions (PDs), employee records, assessment responses and model outputs stay on approved work machines, and institutional text is processed with local or on-prem inference. Anything built in this lab should run on synthetic or public data (O*NET, Lightcast Open Skills, ESCO, published exposure scores) and publish only aggregates.

---

## 1. Executive summary

1. **"Skills-based" is now the default in the public sector and in professional bodies, but higher ed is behind on execution.** Over half of U.S. states have dropped degree requirements or adopted skills-based hiring for some classifications (Maryland, Pennsylvania and Colorado among them). OPM built a skills-based AI competency model with 43 general and 14 technical competencies. Higher ed HR still runs mostly on job-classification systems; in Illinois that means the SUCSS civil-service classifications for staff. Practical skills work therefore happens *as an overlay on the classification system*, not in place of it.
2. **AI adoption by employees runs ahead of governance.** The EDUCAUSE/CUPA-HR/NACUBO/AIR study *The Impact of AI on Work in Higher Education* (Jan 2026) reports 94% of respondents used AI tools for work in the past six months. Over 70% use them daily or weekly, many are unaware of institutional policy, and over half have used unsanctioned tools. This gap between adoption and governance is the main baseline to measure.
3. **Measuring AI exposure has moved from expert ratings to observed usage.** Eloundou et al. (*GPTs are GPTs*) rated O*NET tasks. Microsoft's "Working with AI" scores applicability from 200k Copilot conversations. The Anthropic Economic Index (AEI) maps millions of Claude conversations to O*NET tasks and separates automation from augmentation. The ILO's 2025 refined index uses four exposure gradients. All of them work at the **task** level, which is what makes them usable for redesigning roles and building reskilling pathways rather than headcount cuts.
4. **The legal regime moved in two directions at once.** Federally, the EEOC removed its AI guidance (Jan–Apr 2025). EO 14281 (April 2025) directs agencies to drop disparate-impact enforcement, and the EEOC closed pending disparate-impact charges by 30 Sep 2025. Private Title VII disparate-impact claims are still available. In Illinois, **HB 3773 (P.A. 103-0804) took effect 1 Jan 2026**. It makes discriminatory AI use in recruitment, hiring, promotion, training selection, discipline and discharge a civil-rights violation, requires notice, and bans zip code as a proxy. IDHR's notice rules were proposed and then withdrawn in 2026 *(verify current status)*. For UIUC, every AI-assisted skills inference that feeds promotion, training selection or succession falls in scope.
5. **Succession practice is moving from replacement charts to talent pools and readiness evidence.** The 9-box is widely criticized for subjectivity and gendered "potential" ratings, and is best kept as a calibration aid at most. For bench strength, use readiness against defined role challenges, pool depth, and diversity of pools.

---

## 2. Landscape by domain

### 2.1 Skills-based organizations (SBO)

| Source | What it says / provides | URL |
|---|---|---|
| OPM AI competency model and skills-based hiring guidance (Apr 2024) | 43 general + 14 technical competencies for AI work, from a government-wide job-analysis survey; usable for hiring, workforce planning, training and performance. 2210 IT series moving to skills-based assessment. | https://www.opm.gov/chcoc/transmittals/2024/Skills-Based%20Hiring%20Guidance%20and%20Competency%20Model%20for%20Artificial%20Intelligence%20Work.pdf |
| State skills-first hiring | More than half of states have adopted skills-based hiring in the past three years *(verify; GovLoop)*. New Jersey Civil Service Commission and Northeastern Burnes Center are using AI to review more than 3,000 job descriptions for degree barriers. | https://burnes.northeastern.edu/skills-first-workforce-hiring-creating-more-equitable-and-inclusive-state-employment-opportunities-using-ai/ ; https://www.govloop.com/community/blog/upskilling-the-public-workforce-for-the-ai-era |
| SHRM | Skills-first hiring resources and "AI+HI" (human intelligence) positioning; SHRM higher-ed upskilling guidance. | https://www.shrm.org/mena/enterprise-solutions/insights/8-ways-to-upskill-faculty-future-of-higher-ed |
| CUPA-HR | Data on workforce composition, pay and retention, and AI adoption in HR; 2026 programming on "human skills as AI strategy". | https://www.cupahr.org/resource/ai-adoption-and-attitudes-in-higher-ed-hr/ |

**Best practice pattern.** Build a skills ontology (canonical taxonomy plus local extensions). Attach skills to jobs and classifications first, then to people using several kinds of evidence. Apply skills to mobility, learning and planning before selection, where legal risk is highest. Under merit systems, skills overlays inform classification and exam rules but do not override them.

### 2.2 AI literacy and competency frameworks

| Framework | Structure | Use at UIUC | URL |
|---|---|---|---|
| EDUCAUSE *AI Literacy in Teaching and Learning: A Durable Framework* (2024) | Domains of technical understanding, evaluative, practical and ethical literacy, defined per stakeholder group (faculty, staff, students, leaders). | Base layer for a staff/faculty AI literacy profile. | https://www.educause.edu/content/2024/ai-literacy-in-teaching-and-learning/introduction |
| SFIA 9 (Oct 2024) | Seven levels of responsibility (Follow → Set strategy) with generic attributes (autonomy, influence, complexity, knowledge, business skills). AI skills cover AI & data literacy, building AI/ML models, developing and operationalising AI/ML, MLOps, and impact on jobs. | Proficiency scaffold for IT/analytics roles; strong level descriptors. | https://sfia-online.org/en/sfia-9/sfia-9-release-notes/sfia-a-framework-for-ai-skills |
| OPM AI competency model | General vs technical competencies, each with a definition. | Government-grade template for technical AI roles. | (see 2.1) |
| Ohio State AI Fluency | Endorsement for instructors and instructional staff; $300 PD incentive (Dec 2025–Aug 2027); BuckeyeLearn courses for staff; faculty advisory council. | Big Ten peer benchmark for incentives and credentialing. | https://oaa.osu.edu/ai-fluency |
| UNESCO AI Competency Frameworks (students, teachers, 2024) | Four dimensions (human-centred mindset, ethics, AI techniques/applications, AI system design) × three progression levels (Acquire, Deepen, Create). | Clean progression-level model. *(verify; recall)* | https://www.unesco.org/en/articles/ai-competency-framework-teachers |
| UIUC's own baseline | OCIO + Illinois HR AI Professional Development Series: about 1,380 faculty/staff in Fall 2025; Spring 2026 staff and leadership tracks. | Existing programme whose participation data seeds analytics. | https://boldlyit.illinois.edu/illinois-ai-professional-development-series-1300-sign-ups-and-counting/ |

**Recommended structure for a competency framework** (consistent across SFIA, OPM, and classic HR competency modelling):

| Element | Definition | Example (AI literacy, staff) |
|---|---|---|
| Domain | Cluster of competencies | "Responsible use" |
| Competency | Named capability + definition | "Data protection when using AI" |
| Proficiency levels | Typically 4–5 (Awareness, Working, Practitioner, Advanced, Expert/Leader), mapped to SFIA levels where relevant | L2 "Applies institutional data classification before entering content into an AI tool" |
| Behavioral indicators | 2–4 observable, assessable statements per level | "Chooses the approved enterprise tool for Category II data; can explain why" |
| Role profile | Target level per competency for a job family / classification | Admin Aide: Responsible use L2, Prompting L2, Workflow automation L1 |
| Evidence types | Assessment item, work sample, course completion, manager attestation | Scenario-based quiz plus a work artifact |
| Version + provenance | Who approved, when, mapping to sources (EDUCAUSE/SFIA/OPM) | v1.2, approved by HR/OCIO council |

### 2.3 Skills inference from PDs/JDs with taxonomies

| Taxonomy | Size / structure | License | Notes | URL |
|---|---|---|---|---|
| O*NET 30.x | ~900+ occupations; Tasks, DWAs (~2,000), IWAs, GWAs, Skills/Knowledge/Abilities with importance & level, Technology Skills, Hot Tech | Public domain (CC BY 4.0 attribution) | Backbone of every AI-exposure study; SOC crosswalk. | https://www.onetcenter.org/database.html |
| Lightcast Open Skills | 33k–35k+ skills, categories/subcategories, skill types (specialized, common, certification); 75k titles | Free for individual/nonprofit with attribution; free API ~50 extraction calls/period, not for production; commercial license otherwise | Good granularity for IT/business skills; frequent releases. | https://skills.lightcast.io/ ; https://docs.lightcast.io/lightcast-api/docs/free-api-features |
| ESCO v1.2 | ~3,000 occupations, ~13,900 skills/competences, essential vs optional relations, multilingual, ISCO-linked | Open (EU) | Strong ontology (SKOS/RDF); transversal skills. | https://esco.ec.europa.eu |
| SFIA 9 | ~147 professional skills × 7 levels | Free for internal use with registration; commercial terms for products | Best level descriptors for digital roles. | https://sfia-online.org |

**State-of-the-art pipeline** (2024–2026 practice and literature; consistent with ESCOXLM-R, skill-extraction benchmarks such as SkillSpan, and LLM "extract-then-link" approaches):

1. **Segment** the PD into duties, % time, required/preferred qualifications, and supervision. Illinois PDs and SUCSS class specs have semi-structured duty lists with % time, which lets you weight tasks.
2. **Extract** candidate skill spans with an LLM, run locally for institutional PDs, constrained by a JSON schema and with the source span quoted verbatim. Keep the span, so every inferred skill can be traced back to its text.
3. **Link** to the taxonomy by embedding retrieval (bi-encoder over O*NET DWAs, Lightcast skills, ESCO), then an LLM or cross-encoder reranks the top-k. Output canonical IDs with scores.
4. **Map duties to O*NET tasks/DWAs.** This is the join key to the AI-exposure datasets (Section 2.4).
5. **Assign level**, using SFIA-style responsibility cues ("leads", "under general supervision") plus the classification level.
6. **Human validation**: a compensation/classification analyst accepts, rejects or edits each mapping, and those decisions become gold labels.

**Evaluation:** precision, recall and F1 of linked skill IDs against an analyst-labelled gold set (stratified by job family and classification), span-grounding rate (inferred skill has a verbatim supporting span), inter-annotator agreement (Cohen's κ) among analysts, top-k accuracy of DWA linking, and *coverage parity* (whether extraction recall differs systematically across job families with different demographic composition). This mirrors the repo's discipline: frozen gold set, no model grading another model, preserve all failures.

### 2.4 Task-based AI exposure frameworks

| Framework | Unit & method | Key output | Caveats | URL |
|---|---|---|---|---|
| Eloundou, Manning, Mishkin, Rock, *GPTs are GPTs* (OpenAI/Penn; *Science* 2024) | O*NET tasks rated by humans + GPT-4 on rubric E0 (no exposure), E1 (direct LLM halves time), E2 (with complementary software) | ~80% of workers have ≥10% of tasks exposed; ~19% have ≥50% *(verify exact figures)* | Potential, not realized; rubric uses LLM ratings. | https://arxiv.org/abs/2303.10130 |
| Microsoft Research, *Working with AI* (Tomlinson et al., 2025; arXiv 2507.07935) | ~200k anonymized Bing Copilot conversations mapped to O*NET IWAs; applicability score = coverage × completion × scope; separates user goal vs AI action | Highest: sales, computer/math, office & admin support, interpreters/translators; low: healthcare support, cleaning. r=0.73 vs. prior predictions. Code/data on GitHub, v1.1 adds physical-task classification. | Usage-based; one product's user base. | https://arxiv.org/abs/2507.07935 ; https://github.com/microsoft/working-with-ai |
| Anthropic Economic Index (Feb 2025 →, reports through Mar 2026) | Privacy-preserving analysis (Clio) of Claude conversations mapped to O*NET tasks; automation (directive, feedback-loop) vs augmentation (validation, task iteration, learning); since Jan 2026 adds task complexity, skill level, purpose, autonomy, task success | Claude.ai ~52–53% augmentation; enterprise API much more automation-heavy (~75%+); computer/math tasks dominate. Datasets released on Hugging Face. | One platform; task shares ≠ jobs. Figures *(verify)* against primary reports. | https://www.anthropic.com/economic-index ; https://huggingface.co/datasets/Anthropic/EconomicIndex |
| ILO Working Paper 140 (May 2025), refined global index | ~30k ISCO-08 tasks scored with worker survey + expert + AI scoring; four exposure gradients | ~25% of global employment exposed; 3.3% in highest gradient (women 4.7% vs men 2.4%); clerical most exposed | Potential exposure, explicitly not job-loss forecasts; ISCO→SOC crosswalk needed. | https://www.ilo.org/publications/generative-ai-and-jobs-refined-global-index-occupational-exposure |

**From exposure to reskilling, not layoffs.** The method that works is to:
- Score exposure at the **task** level, weighted by the PD's % time.
- Classify each task as *automate* (AEI directive pattern / E1 high), *augment* (AEI iteration/validation, Microsoft "AI assists user goal"), or *human-core* (low exposure, interpersonal, physical, judgment).
- Compute **freed capacity** (hours/FTE) and **new task demand** (AI oversight, verification, data stewardship, higher-value student/faculty service).
- Redesign the role, then derive the **skill delta** (skills gained, retained, declining) and route the person into pathways.

ILO and AEI both stress the same lesson: exposure isn't displacement. Institutions such as Pennsylvania's GenAI pilot (175 employees, 14 agencies; average 95 min saved *on days used*) framed savings as capacity to redeploy. Any "time saved" metric should keep that "on days used" qualifier. https://www.pa.gov/agencies/oa/newsroom/icymi--shapiro-administration-s-generative-ai-pilot-for-state-wo

### 2.5 Measuring AI readiness and reskilling ROI

| Level | Metric | Data | Notes |
|---|---|---|---|
| Organizational readiness | Policy awareness %, sanctioned-tool access %, unsanctioned-use %, leadership/manager sponsorship, data-governance maturity | EDUCAUSE/CUPA-HR survey items (reuse for comparability), tool licensing logs | The EDUCAUSE 2026 study is the national comparator. https://library.educause.edu/resources/2026/1/the-impact-of-ai-on-work-in-higher-education |
| Individual readiness | Proficiency distribution per competency vs. role-profile target ("readiness gap") | Scenario-based assessment, work samples | Self-report alone overstates; GovLoop cites only 28% of government staff feel proficient *(verify)*. |
| Reach | Enrollment, completion, by unit/classification/demographics | LMS, PD series registrations | Completion parity across groups is an equity metric. |
| Learning (Kirkpatrick L2) | Pre/post assessment gains | Assessment platform | Use parallel forms; item analysis. |
| Behaviour (L3) | Enterprise AI tool active use, workflow adoption, manager-observed behaviors at 60/90 days | Tool telemetry (aggregate), pulse surveys | Aggregate only; avoid individual surveillance. |
| Results (L4) | Hours redeployed, cycle-time changes in specific processes, internal fills of reskilled roles, retention of participants | Process data, ATS/HRIS | Use difference-in-differences or staggered rollout vs. waitlist; avoid naive pre/post. |
| ROI (Phillips L5) | (Monetized benefits − program cost) / cost, with isolation factor and confidence adjustment | Above + finance | Report ranges and isolation assumptions; Phillips method conservative rules. |
| Build-vs-buy ROI | Cost to reskill internal vs. cost-to-hire + time-to-productivity + vacancy cost | Recruiting costs, time-to-fill | Often the most persuasive higher-ed ROI. |

### 2.6 Strategic workforce planning (SWP)

| Method | Description | Higher-ed specifics |
|---|---|---|
| Segmentation and critical-role identification | Score roles on strategic impact × scarcity/time-to-fill × single-incumbent risk × regulatory criticality | Include research-administration, IT security, facilities trades, clinical/vet, finance/compliance; separate faculty vs. staff planning. |
| Supply modeling | Stock-and-flow (Markov) models: hires, promotions, transfers, exits by segment; retirement probabilities by age/service | SURS retirement eligibility (Tier 1 vs Tier 2 rules) is a large driver for Illinois public universities; retirement hazard rises sharply at eligibility thresholds. |
| Demand modeling | Drivers: enrollment, research expenditure, new buildings, strategic plan initiatives, AI productivity | Tie to the campus strategic plan and budget model. |
| Gap analysis | Demand − projected supply by role family × skill × year | Express gaps in both FTE and skills. |
| Scenario planning | 3–4 scenarios (e.g., AI capacity shift low/high × enrollment/budget up/down) with Monte Carlo ranges | Avoid point forecasts; show bands. |
| Retirement-wave modeling | Survival/hazard models (Cox or discrete-time logistic) on age, service, pension tier eligibility, role | CUPA-HR workforce data supports benchmarking; use aggregates. |
| Bench strength | Ready-now / ready 1–2y / ready 3–5y successors per critical role; pool coverage ratio | See 2.8. |

### 2.7 Talent mobility and internal marketplaces

Patterns: skill-based matching of employees to openings, projects/gigs, stretch assignments and mentors. Typical vendors are Eightfold, Gloat, Workday Talent Marketplace and Phenom. Public-sector constraints (civil-service exams, bargaining units, posting rules) mean marketplaces in state/higher-ed settings lean on **projects, details, and development opportunities** rather than direct job placement. New York State and other states have used AI-based talent platforms *(verify; vendor material)* https://eightfold.ai/learn/how-new-york-state-uses-ai-to-rebuild-the-public-sector-talent-pipeline/ .

**Metrics:** internal fill rate, internal mobility rate by segment, time-to-fill internal vs. external, post-move retention and performance, **mobility equity** (move rates by gender, race and ethnicity, age, and unit, adjusted for eligibility).

### 2.8 Succession planning

| Practice | State of the art | Critique / risk |
|---|---|---|
| Replacement planning (1:1 named successor) | Legacy; still common for top roles | Brittle; favors similarity; low diversity; public-sector posting rules may conflict with pre-selection. |
| Talent pools / acceleration pools | Develop pools for role *families* (e.g., "associate director, business operations") | Needs clear criteria; better fit for merit systems. |
| 9-box (performance × potential) | Use, if at all, as a calibration discussion aid | Subjective "potential"; reported gender gap in potential ratings (study of ~30k employees, women rated lower potential despite higher performance) *(verify primary source)*; Gallup recommends readiness for specific future challenges. https://cultureamp.com/blog/9-box-grid-for-succession-planning |
| Readiness assessment | Readiness against defined role challenges using evidence (experiences, competencies, assessment center, 360) | More defensible; aligns with HB 3773 documentation needs. |
| Knowledge transfer | Critical-knowledge capture for retirement-eligible incumbents (phased retirement, return-to-work rules) | SURS return-to-work limits affect options *(verify)*. |

**Bench metrics:** coverage ratio (critical roles with ≥1 ready-now or 1–2y successor), bench depth (successors per critical role), pool diversity vs. feeder population, successor overlap (same person on many slates), succession "hit rate" (vacancies filled from slate), and time-to-readiness.

### 2.9 Validation, bias and legal

| Instrument | Status | Implication | URL |
|---|---|---|---|
| Illinois HB 3773 (P.A. 103-0804), amends IHRA | Effective 1 Jan 2026. Covers AI use in recruitment, hiring, promotion, renewal, **selection for training or apprenticeship**, discharge, discipline, tenure, terms. Notice required; zip code as a proxy banned. IDHR notice rules proposed, then withdrawn in 2026 *(verify)*. | Skills inference that feeds promotion, training selection or succession slates is in scope. Need notice, documentation, and adverse-impact monitoring even though no audit is mandated. | https://www.seyfarth.com/news-insights/illinois-department-of-human-rights-temporarily-withdraws-proposed-rules-on-use-of-artificial-intelligence-in-employment.html |
| Illinois AI Video Interview Act (2020) | In force | Relevant only if video assessment is used. | — |
| EEOC / federal | AI technical assistance removed (Jan–Apr 2025); EO 14281 directs agencies to deprioritize disparate impact; EEOC closed disparate-impact charges by 30 Sep 2025 | Private Title VII disparate-impact claims and the statute remain. UGESP (29 CFR 1607) four-fifths rule remains the practical heuristic *(verify whether UGESP has been amended)*. | https://natlawreview.com/article/federal-government-quietly-removed-its-ai-hiring-guidance-four-states-are-writing ; https://thedailyrecord.com/2025/10/01/eeoc-disparate-impact-ai-discrimination/ |
| Colorado AI Act (SB 24-205), NYC LL 144 | Colorado effective date delayed to 30 Jun 2026 *(verify)*; NYC requires bias audits | Useful templates for impact assessments and audits. | — |
| NIST AI RMF 1.0 + GenAI Profile (AI 600-1) | Voluntary | Governance structure (Govern/Map/Measure/Manage). | https://www.nist.gov/itl/ai-risk-management-framework |

**Validation practice:** content validity (skills traced to job analysis), criterion validity where outcomes exist, adverse-impact ratios (four-fifths plus statistical significance; Fisher's exact test for small n), measurement invariance of assessments across groups (DIF on items), and calibration of any readiness score by group. Keep a human decision-maker, and log what the AI suggested vs. the final decision.

---

## 3. Artifacts to build

Each artifact below gives its purpose, data, methods, risks and evaluation. All should start on synthetic and public data in this lab. Production versions use institutional data only on approved machines with local inference.

### A1. AI Competency Framework Builder + Assessment Analytics
- **Purpose:** author and version a UIUC AI literacy/fluency framework (domains → competencies → levels → behavioral indicators → role profiles), then analyze assessment results.
- **Data:** EDUCAUSE, SFIA 9, OPM, UNESCO source texts (public); role list by job family/classification; assessment item responses; PD-series participation.
- **Methods:** schema-first framework store (YAML/JSON with provenance to source framework clauses); LLM-assisted drafting of behavioral indicators with **mandatory human approval**; item response theory (Rasch/2PL) for item quality; DIF (Mantel-Haenszel) by group; readiness gap = target level − measured level, by unit.
- **Risks:** self-report inflation; using assessments for selection, which triggers HB 3773 and requires validation; surveillance perception.
- **Evaluation:** SME content-validity ratings (Lawshe CVR), item reliability (α/IRT information), DIF flags, test-retest; dashboard shows only aggregates with minimum cell size (n≥10).

### A2. Skills Inventory from Position Descriptions
- **Purpose:** canonical skill and task profile for every PD/classification, which is the foundation for A3–A6.
- **Data:** PDs and class specs (on approved machines only); O*NET 30.x tasks/DWAs/tech skills; Lightcast Open Skills (licensed tier for production); ESCO for transversal skills.
- **Methods:** segment → local-LLM span extraction with schema + verbatim span → embedding retrieval + rerank to taxonomy IDs → level inference → analyst review queue. Duty % time weights task importance.
- **Risks:** hallucinated skills (mitigate with span grounding); taxonomy gaps for academic and research roles; stale PDs; licensing limits (the Lightcast free API is not for production).
- **Evaluation:** frozen gold set of analyst-labelled PDs; precision/recall/F1 at the skill-ID level; grounding rate; κ among analysts; error analysis stratified by job family. All failed and truncated cases are kept, as in this repo's protocol.

### A3. AI Exposure & Role Redesign Explorer
- **Purpose:** show for each role which tasks are automatable, which augmentable, and which human-core, plus the freed capacity.
- **Data:** A2 task profiles joined to O*NET-SOC; AEI task-level data (Hugging Face), Microsoft Working-with-AI IWA applicability (GitHub), Eloundou E-ratings, ILO WP140 (ISCO→SOC crosswalk).
- **Methods:** weighted task exposure = Σ(%time × exposure); show the *range across frameworks* rather than one number; separate automation vs augmentation share (AEI); output role-redesign worksheets for managers.
- **Risks:** treating exposure as a layoff list. Mitigate with framing, governance, a "no-RIF use" policy statement, and aggregate display (job family, not individual). Framework disagreement; crosswalk error.
- **Evaluation:** rank correlation across frameworks; manager validation workshops (agreement with task classification); later, observed time savings in pilots vs. predicted.

### A4. Reskilling Pathway Engine
- **Purpose:** for each person or role in an exposed job family, recommend adjacent target roles and learning pathways.
- **Data:** skill profiles (A2), role profiles (A1), learning catalog mapped to skills (LinkedIn Learning/BuckeyeLearn-equivalent, UIUC PD series, Coursera for Campus), historical internal transitions, vacancy/demand forecast (A5).
- **Methods:** skill-gap distance (weighted Jaccard / embedding similarity with importance weights); transition graph from observed internal moves (a Markov transition matrix gives empirical feasibility); learning-path optimization (minimum hours to close the gap, subject to prerequisites); rank target roles by demand × feasibility × pay maintenance.
- **Risks:** steering by demographics (historic transitions encode bias, so audit recommendations for parity); classification and union rules; recommending roles with no openings.
- **Evaluation:** offline: hit-rate of recommended targets against actual later moves (time-split). Online: pathway enrollment → completion → placement conversion, with parity by group. Phillips ROI on placements vs. external hire cost.

### A5. Workforce Scenario Planner (supply/demand + retirement wave)
- **Purpose:** 3–5-year projections by job family/skill under scenarios.
- **Data:** HRIS snapshots (headcount, age band, service, SURS tier/eligibility flags, FTE, unit), historical flows, budget/enrollment drivers, AI capacity assumptions from A3.
- **Methods:** discrete-time hazard models for retirement/exit; Markov stock-flow for internal flows; driver-based demand; Monte Carlo over assumptions; scenario toggles (AI adoption low/high, budget flat/cut, enrollment growth).
- **Risks:** small cells; age-based modeling must not become age-based decisions (ADEA); overconfidence in point estimates.
- **Evaluation:** backtesting (fit on years t−5…t−2, predict t−1…t; MAPE by segment); calibration of hazard models (Brier, calibration curves); prediction-interval coverage.

### A6. Critical Role & Bench-Strength Dashboard
- **Purpose:** identify critical roles and quantify succession risk.
- **Data:** role criticality inputs (strategic impact rating, time-to-fill, market scarcity from Lightcast postings, single-incumbent flag, regulatory flag), retirement probability (A5), succession slates/pools, readiness evidence.
- **Methods:** transparent weighted criticality score with sensitivity analysis; risk = criticality × P(vacancy in 24 months) × (1 − bench coverage); pool metrics (depth, overlap, diversity vs. feeder pool, time-to-ready).
- **Risks:** 9-box ratings as inputs import bias, so prefer readiness evidence; named-successor data is highly sensitive; public-sector posting rules.
- **Evaluation:** retrospective: did high-risk roles actually experience disruptive vacancies? Track slate hit rate and post-promotion success; adverse-impact ratios on pool inclusion.

### A7. Talent Mobility / Opportunity Marketplace Analytics
- **Purpose:** measure and fairly match internal moves, projects and stretch assignments.
- **Data:** postings, applications, internal transfers, project gigs, skill profiles.
- **Methods:** skill-match scoring with explanation (matched/missing skills); mobility funnel; equity analysis (logistic regression on move probability, controlling for eligibility).
- **Risks:** HB 3773 applies if match scores affect who gets considered; manager hoarding; dataset shift.
- **Evaluation:** internal fill rate, time-to-fill, post-move retention at 12 months, four-fifths ratios at each funnel stage, plus user acceptance of recommendations.

### A8. AI Readiness & Reskilling ROI Scorecard
- **Purpose:** executive view combining readiness (org and individual), reach, behavior and results.
- **Data:** EDUCAUSE-comparable survey items, A1 assessments, LMS, tool telemetry (aggregate), A4 placements, finance costs.
- **Methods:** Kirkpatrick/Phillips chain; quasi-experimental impact estimates (staggered rollout DiD, waitlist controls); confidence-adjusted ROI ranges.
- **Risks:** vanity metrics (enrollment), attribution claims, surveillance via telemetry.
- **Evaluation:** pre-registered metric definitions (a "labelled protocol", in the spirit of this repo's AGENTS.md rules); reproducible pipelines; benchmarks against EDUCAUSE/CUPA-HR national figures.

### A9. AI-in-Employment Compliance Ledger (cross-cutting)
- An HB 3773-ready registry of every AI touchpoint in covered decisions: tool, decision point, notice issued, adverse-impact tests, human overrides, NIST AI RMF mapping. **Evaluate** by completeness (every covered point has notice + monitoring) and by time-to-remediate flagged disparities.

---

## 4. Cross-cutting guardrails

1. **No RIF use.** Exposure analytics feed role redesign and reskilling only. Display results at job-family level.
2. **HB 3773.** Covered decisions include training selection and promotion, so give notice, keep a human decision-maker, monitor outcomes, and never use zip code or its proxies.
3. **Disparate impact.** Private claims and state law still apply despite the federal pullback. Run four-fifths + significance tests and DIF.
4. **Grounding.** Every inferred skill needs a verbatim span and analyst sign-off.
5. **Succession.** Use readiness evidence instead of 9-box "potential".
6. **Privacy.** Aggregate telemetry only, minimum cell sizes, local inference for institutional text.
7. **Protocol discipline.** Pre-register metrics. A change to scoring or thresholds requires a new protocol version.

---

## 5. Suggested sequencing (12 months)

| Quarter | Deliverables |
|---|---|
| Q1 | A9 registry + legal review; A1 framework v1 (EDUCAUSE + SFIA mapping); A2 pilot on 1–2 job families with gold set |
| Q2 | A2 scale-out; A3 explorer for admin/business/IT families; A8 baseline readiness survey (EDUCAUSE-comparable) |
| Q3 | A5 scenario planner (retirement wave + AI scenarios); A6 critical-role scoring with leadership calibration |
| Q4 | A4 pathway engine pilot with waitlist control; A7 mobility analytics; first ROI estimate with ranges |

---

## 6. Sources

Source URLs are inline in each table above. The primary sources to re-check before external citation are the Anthropic Economic Index reports, the EDUCAUSE 2026 report full text, IDHR rulemaking status for HB 3773, and the ~30k-employee 9-box gender study.
