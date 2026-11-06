# Higher-Ed HR Workforce Intelligence: The Tool Landscape Beyond Snowflake and Databricks

Research date: 2026-11-06. Method: web search of vendor newsrooms, product documentation, standards bodies, legal trackers and third-party pricing aggregators. No vendor was contacted and no product was trialled. Everything below is public information, and no institutional data was used.

## How to read the evidence labels

- **[V] Verified:** primary source (official documentation, standards body, court docket, government page) or several independent sources that agree.
- **[M] Vendor marketing:** the vendor's own claim (press release, solution page). The claim is accurately reported, but its outcomes have not been independently checked.
- **[S] Secondary or unverified:** aggregator, reseller, blog or single-source claim. Treat it as directional only.
- **[J] Judgement:** the author's assessment, not a sourced fact.

Pricing is almost never published for enterprise HR software. Where a number appears, its label says where it came from.

---

## 1. Summary

1. **No single product is "as good or better" across the whole job.** HR-native suites (Workday, Oracle, SAP) own the system of record and now ship skills ontologies and agents. People-analytics specialists (Visier, One Model) are better at longitudinal HR metrics. General data platforms (Fabric, BigQuery/Looker, AWS, MotherDuck/DuckDB, Postgres) are cheaper and more controllable. Each group is strong where the others are weak. [J]
2. **The best price-to-control option for a budget-limited public university with strict data rules** is an open, mostly local stack:
   - DuckDB or Postgres for storage, with dbt/MetricFlow for metric definitions
   - open taxonomies (O*NET, ESCO, NICE; Lightcast Open Skills only if licensing permits)
   - an open-weight model served on-prem with vLLM or llama.cpp
   - one institution-licensed BI tool for distribution (Power BI is the default if the campus is already on Microsoft 365)

   [J]
3. **Higher-ed adoption evidence is thin for most specialist tools.** Searches found no public university case study for Visier, One Model, Pigment, Gloat or Eightfold. Workday is the clear exception (650+ higher-ed institutions selected Workday [M]). Anaplan has a documented academic-workforce-planning customer (La Trobe) [M]. CUPA-HR remains the sector benchmark source [V].
4. **The engineering gaps are specific to higher ed.** Generic vendors do not model them:
   - crosswalks between position classes and SOC, IPEDS and CUPA-HR
   - faculty pipeline and tenure modeling
   - positions funded by grants
   - version-aware taxonomy mapping
   - small-cell suppression before publishing
   - deterministic evaluation of HR AI assistants
   - on-prem skills extraction

   Section 6 lists 14 of these gaps.

---

## 2. HR-native analytics, planning and talent-intelligence products

### 2.1 Workday (Prism, Data Cloud, Skills Cloud, Illuminate agents, Adaptive Planning)

- **Higher-ed footprint.** Workday reported more than 650 higher-ed institutions in 19 countries in October 2025. In April 2026 it said 200+ institutions had selected Workday Student and nearly 100 were live. [M] Sources: https://newsroom.workday.com/2025-10-15-Workdays-Higher-Education-Momentum-Accelerates-as-Over-650-Institutions-Worldwide-Turn-to-AI-to-Navigate-Uncertainty-and-Transform-the-Student-Experience ; https://newsroom.workday.com/2026-04-06-Workday-Named-a-Leader-in-2026-Gartner-R-Magic-Quadrant-TM-for-Higher-Education-Student-Information-Systems
- **Data Cloud.** It was announced in September 2025 as zero-copy sharing over Apache Iceberg, with Snowflake, Databricks and Salesforce as launch partners. It has three parts: Data Connect, Live Data Query (SQL) and Data Lake. As of the June 2026 AWS integration announcement, all three were available to early adopters, with GA "planned for later this year". I found no GA announcement as of this research date. [V for status, M for capability] Sources: https://newsroom.workday.com/2025-09-16-Workday-Introduces-Workday-Data-Cloud-to-Unlock-the-Power-of-People-and-Money-Data-and-Accelerate-AI-Powered-Innovation ; https://investor.workday.com/news-and-events/press-releases/news-details/2026/Workday-Announces-Workday-Data-Cloud-Integration-with-AWS-Giving-Developers-Direct-Access-to-Workdays-Governed-Data-Layer/default.aspx
- **Data Cloud and Google.** A November 2025 release added a Google BigQuery partnership. [M] https://s21.q4cdn.com/950027458/files/doc_news/Workday-Expands-Its-Open-Ecosystem-with-New-Global-Developer-Network-and-Google-BigQuery-Partnership-11-19-2025-2025.pdf
- **Prism versus Data Cloud.** Workday's own upgrade guide describes Prism as one-directional. Data Cloud Professional keeps existing Prism datasets, while a lighter Core tier leaves out Prism data preparation. [M] https://www.workday.com/en-us/topics/it/guide-prism-to-data-cloud.html
- **Illuminate agents.** Workday announced a Talent Mobility Agent, a Recruiter Agent, a Payroll Agent and others in September 2025, with availability through 2026. They are governed by the "Agent System of Record" and paid for with Flex Credits, a consumption currency. [M] https://newsroom.workday.com/2025-09-16-Workday-Illuminate-TM-Expands-with-New-AI-Agents-for-HR,-Finance,-and-Industry?es_id=58630df3ab
- **Assessment.** [J] Workday is the obvious source of truth for campuses that already run it. Skills Cloud is useful, but its ontology is proprietary and cannot easily be exported as a versioned taxonomy. The agents are tenant-cloud features, so whether they suit strict data rules is a contract and procurement question, not a technical one. Data Cloud lowers extraction cost for warehouses, but it is not yet GA.

### 2.2 Oracle Fusion HCM (Dynamic Skills, AI agents)

- **Agents.** Dynamic Skills has shipped four AI agents since release 25A. [V] https://docs.oracle.com/en/cloud/saas/talent-management/24d/faidy/overview-of-dynamic-skills.html
- **Skill suggestions.** Release 26A added generative-AI skill suggestions. The older predictive model stops being supported in 26B, so migration is mandatory. [V] https://docs.oracle.com/en/cloud/saas/readiness/hcm/26a/dyns-26a/26A-dynamic-skills-wn-t74721.htm
- **Agentic talent applications.** Newer agentic applications cover job design, skills profiles, learning and workforce planning, and run under existing Fusion permissions. AI Agent Studio lets customers build their own agents. [M] https://uctoday.com/oracle-ai-agents-talent-management
- **Assessment.** [J] Oracle is relevant only to campuses already on Fusion HCM. Its higher-ed HR evidence is weaker than Workday's.

### 2.3 SAP SuccessFactors (Talent Intelligence Hub, Joule agents)

- **Talent Intelligence Hub.** The hub combines a skills ontology, an attributes library and a growth portfolio. The first-half 2026 release adds skills governance and consolidation of partner skills data from Beamery and Lightcast. [S] https://www.savictech.com/insights/sap-successfactors-ai-agents-skills-hr-2026/
- **Joule agents.** Four agents (Career & Talent Development, HR Service, People Intelligence, Payroll) were expected to be GA in May 2026. Joule Studio for custom agents is reported as GA. One Sapphire 2026 summary claims "42 specialized agents", which I could not verify. [S] https://sapinsider.org/articles/new-joule-agents-coming-to-bolster-ai-in-sap-successfactors/ ; https://www.pulse.bot/hrtech/news/sap-unveils-autonomous-hcm-roadmap-and-unified-business-ai-platform-at-sapphire-2026-eb7370fa-e505-4b63-9ed4-7420bb627aea/

### 2.4 Visier (People, Vee assistant)

- **Pricing and Vee.** Visier is the most mature specialist for packaged people metrics. Vee, its generative-AI assistant, went to all customers in 2024. Vee is reportedly bundled into the core per-employee subscription. Vendr reports a median spend of about $103k per year. [S] https://www.vendr.com/marketplace/visier ; https://workplacejournal.co.uk/2024/04/visier-launches-ai-driven-hr-assistant-vee-to-all-customers/
- **Higher-ed evidence.** I found no public university case study. The public-sector reference is the City of Edmonton. [S] https://www.casestudies.com/company/visier/case-study/the-city-of-edmonton-fueling-hr-modernization-with-workforce-intelligence

### 2.5 One Model

- **Positioning.** One Model is a people-analytics data platform with a more open data model than Visier. Its customers are mainly corporate and nonprofit (Colgate-Palmolive, Atlassian, Chan Zuckerberg Initiative). I found no university customer. [S] https://www.onemodel.co/results

### 2.6 Orgvue, ChartHop, Anaplan, Pigment (workforce and org planning)

- **Orgvue.** Positioned for large-enterprise transformation and scenario modeling. [M] https://www.orgvue.com/resources/articles/best-workforce-planning-software/
- **ChartHop.** An org-chart and headcount-planning tool for mid-size companies. A competitor's review site quotes "$8 PEPM". [S] https://resources.rework.com/tools/workforce-management/best-charthop-alternatives
- **Anaplan.** This is the strongest higher-ed evidence among the planning tools:
  - La Trobe University has used Anaplan Workforce Planning for academic workforce planning since 2020. [M] https://www.anaplan.com/news/la-trobe-university-uses-anaplan-for-academic-workforce-planning/
  - Deloitte sells an Anaplan "Higher Education Model" that includes position budgeting. [M] https://www.deloitte.com/content/dam/assets-zone3/us/en/docs/alliances/2026/deloitte-anaplan-higher-education-sales-sheet.pdf
- **Pigment.** It markets agent-built workforce models, and its blog banner announces a $250M Series E. I found no university customer. [M] https://www.pigment.com/webinars/autonomous-workforce-planning-with-ai-agents

### 2.7 Talent-intelligence and marketplace vendors (Eightfold, Gloat, Beamery)

- **Eightfold (legal risk).** *Kistler et al. v. Eightfold AI Inc.* was filed in January 2026 and removed to N.D. Cal. as No. 3:26-cv-1768. It alleges that Eightfold acts as an unregistered consumer reporting agency under the FCRA because it scores applicants using scraped data. Eightfold disputes the claim. I found no ruling. [V] https://www.akingump.com/en/insights/ai-law-and-regulation-tracker/ai-hiring-platform-faces-fcra-class-action-over-data-use-or-kistler-et-al-v-eightfold-ai-inc ; https://towardsjustice.org/2026/01/21/press_release_eightfold/
- **Gloat.** In March 2026 Gloat packaged its skills graph as an autonomous AI agent. [S] https://www.pulse.bot/human-resources/news/gloat-enters-the-crowded-war-for-ai-agents-in-hr-0f915ea7-c044-4ce4-9fbb-29ce5e740405
- **Beamery.** Beamery is now also a skills-data partner feeding SAP. [S]
- **Higher-ed evidence.** I found no vendor case study for these products in higher ed. The best-documented university internal job marketplace is home-built: NUS reported 249 jobs posted and 526 applications. [V] https://www.nus.edu.sg/inside-nus/stories/internal-job-marketplace-developing-talent-from-within

### 2.8 Labor-market data (Lightcast, Revelio Labs, LinkedIn Talent Insights)

- **Lightcast Open Skills.** The library has 33,000+ skills and 75,000+ titles. The free API tier is limited, at 50 skill-extraction calls per month on the free scope. The library is free for individual and not-for-profit use with attribution. [V] https://docs.lightcast.io/lightcast-api/docs/free-api-features ; https://lightcast.io/open-skills/faqs
  - One competitor blog says the free tier became nonprofit-only in April 2026. [S, unconfirmed]
- **Lightcast products for higher ed.** Analyst, Skillabi (program-to-occupation alignment scored 0–100) and Alumni Pathways are widely used in program review. [M] https://lightcast.io/resources/blog/skillabi-press-release-june-3-2025
- **Lightcast and HR.** Lightcast is strong on external labor demand. It is weak on internal HR data: it is not an HRIS analytics tool. [J]
- **Revelio Labs.** Public Labor Statistics (RPLS) is a free monthly macro dataset built from more than 100 million profiles, released the day before the BLS jobs report. Its methodology was updated in October 2026. The firm-level workforce data is a paid product. [V] https://www.reveliolabs.com/public-labor-statistics/
- **LinkedIn Talent Insights.** Still active, with figures now shown inside Recruiter. I found no 2026 discontinuation. [S] https://www.pin.com/blog/linkedin-talent-insights-guide/

### 2.9 Recruiting analytics (iCIMS, PageUp)

- **PageUp.** It targets higher ed explicitly and names the University of Melbourne and TCU as customers. [M] https://pageuppeople.com/solutions/higher-education
- **iCIMS.** Its Summer 2026 release added embedded analytics for high-volume hiring. [M] https://team.icims.com/Webinar-ICIMSSummer2026Release
- **Assessment.** Both are useful for funnel metrics but are not workforce-intelligence platforms. [J]

### 2.10 Sector benchmarks (not software, but essential)

- **CUPA-HR.** Its 2025-26 surveys covered 334,666 faculty at 795 institutions, plus Professionals and Staff surveys. The data is reached through DataOnDemand, a subscription service, and is protected by a published anonymity statement. [V] https://cupahr.org/research-data/about-our-surveys/faculty-survey/ ; https://cupahr.org/research-data/data-anonymity-statement/
- **IPEDS Human Resources component.** It is the mandatory federal reporting standard. The 2025-26 forms changed "gender" to "sex" and "men/women" to "male/female". [V] https://www.scu.edu/media/offices/institutional-research/ipeds/human-resources/Human-Resources-2025-2026.pdf

---

## 3. General data and AI platforms

| Platform | What it is in 2026 | Pricing signal | Fit for strict-data public university [J] |
|---|---|---|---|
| **Microsoft Fabric + Power BI Copilot** | Copilot runs on any paid capacity from F2 since April 2025; Pro or PPU alone is not enough. Fabric Data Agents are still associated with F64-class capacity. [V] https://blog.fabric.microsoft.com/en-US/blog/copilot-and-ai-capabilities-now-accessible-to-all-paid-skus-in-microsoft-fabric/ | F2 about $263/month pay-as-you-go [S] https://querio.ai/articles/power-bi-pricing-copilot-costs-nobody-mentions | High if the campus is already on M365 or Entra and its education agreement covers it. Copilot is a cloud LLM, so institutional text policies apply. |
| **Google BigQuery + Looker/Gemini** | Looker Conversational Analytics went GA in November 2025; Looker agents can publish into Gemini Enterprise. BigQuery conversational analytics was still listed as Preview in May 2026. [V/S] https://cloud.google.com/blog/products/business-intelligence/looker-conversational-analytics-now-ga | Usage-based plus Looker licensing | Good semantic layer (LookML). Cloud only. |
| **AWS (Redshift, SageMaker, Bedrock, Quick Suite)** | QuickSight now sits inside Quick Suite. Author Pro is $40 per user per month, and Quick Enterprise is promotionally available to Authors until 31 Dec 2026. Bedrock Knowledge Bases GraphRAG runs on Neptune Analytics. [V] https://aws.amazon.com/quicksuite/quicksight/pricing ; https://aws.amazon.com/about-aws/whats-new/2025/08/amazon-neptune-supports-byokg-rag-toolkit | Per user plus consumption; watch the mandatory "Amazon Q" fee after promotions end [S] | Strong if the campus has an AWS enterprise agreement, such as through Internet2 or a state contract. |
| **Palantir Foundry/AIP** | Strong ontology and agent tooling. I found no university HR deployment; public 2026 awards are federal (Army, NIH). [V] https://www.highergov.com/contract/47QTCA24D004L-75N99226F00002/ | Enterprise, high | Poor fit on cost and campus politics. Students have protested Palantir promotion. [S] |
| **MotherDuck / DuckDB** | DuckDB is free and embedded. MotherDuck Business costs about $250 per month plus usage after a 2025–26 price rise. [S] https://pricingsaas.com/companies/motherduck | Free locally; low cloud cost | Excellent for an on-prem analytics core of up to tens of millions of rows. |
| **ClickHouse** | Open-source columnar OLAP; fast. [J] | Free self-hosted | Overkill at HR data volumes. |
| **Postgres + pgvector** | Mature; can host relational HR marts and embeddings together. [J] | Free | Excellent default for the operational store and vector search on-prem. |
| **dbt + MetricFlow** | dbt Labs and Fivetran merged, closing June 2026. MetricFlow moved to Apache 2.0 in late 2025 (one source says BSL, so check the LICENSE file). Hosted semantic-layer endpoints remain commercial. [S] https://www.techtarget.com/data-technologies/news/366643590/Fivetran-DBT-Labs-complete-merger-to-form-data-layer-for-AI | Core free; Cloud paid | The best open way to pin HR metric definitions such as headcount, FTE and turnover. |
| **Cube** | Open-source semantic layer and API (not re-verified in this pass). [J] | OSS plus cloud | An alternative to MetricFlow for serving metrics to several BI front ends. |
| **Evidence.dev** | Open-source BI-as-code built from Markdown and SQL (not re-verified). [J] | OSS | Good for static, reviewed aggregate reports. Its outputs fit "publish only aggregates" rules. |
| **Hex** | Hosted notebooks and apps (not re-verified). [J] | Per seat | Cloud only, so a weaker fit for row-level HR data. |
| **Dagster** | Open-source orchestrator with asset lineage (not re-verified). [J] | OSS plus cloud | Good for reproducible, audited pipelines. |

---

## 4. Knowledge-graph and skills-graph technology

| Tool | 2026 status | Notes |
|---|---|---|
| **Neo4j (Aura, GraphRAG)** | Market leader. The `neo4j-graphrag` Python package (KG builder, retrievers) supports several LLM providers. Aura Professional costs about $65 per month according to aggregators. [V package; S price] https://neo4j.com/blog/news/graphrag-python-package/ | Community Edition is free self-hosted (GPLv3). [J] Best tooling ecosystem. |
| **TigerGraph** | Savanna cloud was announced January 2025; it is positioned for large-scale real-time analytics. [M] https://aiwire.net/2025/01/21/tigergraph-launches-savanna-cloud-platform-to-scale-graph-analytics-for-ai | Overkill at university scale. [J] |
| **Amazon Neptune** | Neptune Analytics backs Bedrock GraphRAG. Bring-your-own-KG (BYOKG) RAG is GA in the open-source GraphRAG toolkit. [V] | Only if the campus is AWS-first. |
| **Stardog** | Semantic and RDF knowledge graph with the Voicebox natural-language layer. A June 2026 release, v12.1, is claimed but not confirmed. [S] https://futureagi.com/blog/enterprise-knowledge-graph-platforms-2026/ | Strong fit for SKOS or RDF taxonomies such as ESCO, but commercial. |
| **LadybugDB (Kuzu fork)** | Kuzu was archived in 2025. LadybugDB is the MIT-licensed community fork, with 0.17.1 reported in June 2026. [S] https://dbdb.io/db/ladybugdb | Embedded "DuckDB for graphs". Small project, so there is single-maintainer risk. [J] |
| **DuckDB property graph (DuckPGQ)** | A CWI research community extension supporting SQL/PGQ, PageRank and shortest path. From DuckDB v2.0 it needs an explicit grammar opt-in. [V] https://duckdb.org/community_extensions/extensions/duckpgq | Zero-infrastructure graph queries over existing DuckDB marts. Research-grade. |
| **Microsoft GraphRAG** | Open source. Its indexing is expensive: one 2026 paper estimates about $0.10 per document with GPT-4o, or about $10k per 100k documents. [S] https://arxiv.org/pdf/2607.11683 | Poor fit for corpora that change often. |
| **LightRAG** | Open source, with cheaper incremental indexing. Claims of savings vary from 90% to 6,000×, and I found no reproducible head-to-head benchmark. [S] https://arxiv.org/pdf/2506.05690 | Better for local models. |

[J] For a skills graph, the data volume is small: about 33k Lightcast skills, around 1,000 O*NET occupations, about 14k ESCO skills, and roughly 10^4 positions. Postgres or DuckDB with typed edge tables, plus optional DuckPGQ or LadybugDB, handles that without a dedicated graph server. Neo4j is justified only when graph-native exploration UIs matter to the analysts.

---

## 5. Open-weight local AI stack for on-prem HR data

**Serving**

- **vLLM** is the production server. It released frequently through 2026; v0.28.0 was reported in August 2026, so pin a version. [S] https://hermes-ai.net/news/vllm-v0-28-0-ships-sparse-attention-and-60-faster-speculative-decoding/
- **llama.cpp** and **Ollama** suit single-GPU or Mac workstations and prototyping. Ollama runs on llama.cpp. [J; not re-verified]

**Models (2026, for one 24–80 GB GPU)**

- The main candidates are Gemma 4 (31B), Qwen 3.6 (32–35B), gpt-oss-20b and 120b (Apache 2.0), Mistral Small 3.2 24B (Apache 2.0) and DeepSeek V4 Flash. Rankings conflict across sources; there is "no single best". [S] https://codingscape.com/blog/best-open-weight-llms-for-local-ai-in-2026
- Licences differ: Gemma has its own terms, while gpt-oss and Mistral Small use Apache 2.0. Legal should review them. [J]

**Embeddings**

- Qwen3-Embedding-0.6B (Apache 2.0, about 1.5 GB) and 8B lead MTEB-v2 among open models.
- BGE-M3 provides dense, sparse and ColBERT retrieval in one model, in 4 GB.
- nomic-embed-text and EmbeddingGemma are laptop-class options.
- Benchmark on your own data before choosing. [S] https://d-central.tech/local-embedding-models/

**Guardrails**

- Microsoft Presidio for PII detection and redaction. [V via NeMo docs]
- NVIDIA NeMo Guardrails, an open-source library at v0.23; it sends telemetry by default according to one source. [V/S] https://docs.nvidia.com/nemo/guardrails/about-nemo-guardrails-library/overview.md
- Llama Guard 4 (licence reports conflict: Apache 2.0 versus the Llama 4 Community License) and IBM Granite Guardian, which was not re-verified. [S]
- One October 2026 source reports that LLM Guard is archived and that Guardrails AI was acquired by Harvey. [S, unconfirmed] https://wz-it.com/en/knowledge/ki/ai-guardrails/

**Evaluation**

- Candidate tools: Inspect AI (UK AISI), promptfoo, lm-evaluation-harness and Ragas. None was re-verified in this pass. [J]
- [J] For an institution that forbids one model grading another, the correct design is deterministic scoring: exact-match on SQL results, set overlap against gold labels, and citation span checks. The usable parts of these tools are the harness and scorer interfaces, not their LLM-judge modes.

---

## 6. Open skills taxonomies and frameworks

| Taxonomy | Current version (as found) | Licence | Higher-ed use |
|---|---|---|---|
| **O\*NET** | 30.1 (Dec 2025, revised Work Styles, AI-plus-expert method); 30.2 (Feb 2026, interests); 30.3 (Content Model modernised); 31.0 (Essential and Transferable Skills for 157 occupations). [V] https://www.onetcenter.org/dictionary/31.0/nt/appendix_updates.html | Public (CC BY 4.0) | Staff and professional roles map well. Faculty roles are coarse (one SOC per broad discipline). |
| **Lightcast Open Skills** | 33k+ skills; versioned. [V] | Free for individuals and not-for-profit with attribution; commercial use by contract. [V] | Public universities are generally not-for-profit, but confirm whether internal operational use qualifies. [J] |
| **ESCO** | v1.2.1 (Dec 2025, minor quality release). I found no v1.3. [V] https://esco.ec.europa.eu/ | Free (EU) | SKOS/RDF, multilingual. EU-oriented occupations. |
| **SFIA 9** | Current. [V] https://sfia-online.org/en/sfia-9/documentation | Free for most internal employer use; fees for large-scale or commercial use. [V] https://sfia-online.org/en/licensing-sfia | Central IT job families. |
| **NICE Framework (cyber)** | Components v2.0.0 (Mar 2025), v2.1.0 (Dec 2025) and v2.2.0 (Apr 2026, adds a C-SCRM role and a Cryptography competency area). [V] https://www.nist.gov/news-events/news/2026/04/nice-releases-nice-framework-components-v220 | Public domain | Campus security, research computing. |
| **EDUCAUSE** | 2024 AI Literacy in Teaching and Learning competencies for students, faculty and staff. I found no 2026 IT-workforce AI framework. [V] https://www.educause.edu/content/2024/ai-literacy-in-teaching-and-learning/executive-summary | Free | AI-literacy baseline. |
| **UNESCO** | AI Competency Frameworks for Teachers (15 competencies, 5 dimensions) and for Students (2024). There is no framework for higher-ed staff, a gap that sector commentary also notes. [V] https://www.iau-hesd.net/action/unesco-ai-competency-frameworks-students-and-teachers | Open | Faculty development only. |

---

## 7. Comparison matrix (capability × tool)

Key: **S** = strong or native, **P** = partial or needs a partner or custom build, **–** = absent or not found, **?** = not publicly evidenced. The ratings are [J] syntheses of the sources above.

| Capability | Workday | Oracle | SAP SF | Visier | One Model | Anaplan/Pigment | Orgvue/ChartHop | Eightfold/Gloat/Beamery | Lightcast | Fabric+PBI | BigQuery+Looker | AWS | DuckDB/Postgres+dbt (DIY) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| HR system of record | S | S | S | – | – | – | P | – | – | – | – | – | – |
| Longitudinal HR metrics (turnover, tenure cohorts) | P | P | P | S | S | P | P | P | – | P | P | P | P (build) |
| Scenario and headcount planning | S (Adaptive) | P | P | P | P | S | S | – | – | P | – | – | P (build) |
| Skills ontology | S (proprietary) | S (proprietary) | S (proprietary) | P | P | – | – | S (proprietary) | S (open/commercial) | – | – | – | P (open taxonomies) |
| Internal mobility and marketplace | P (agent) | P | S | – | – | – | – | S | – | – | – | – | P (build) |
| Succession | S | S | S | P | P | – | P | P | – | – | – | – | P (build) |
| External labor-market data | P | – | P (partners) | P | P | – | – | S | S | – | P | – | P (O*NET, RPLS) |
| Natural-language assistant over HR data | S (cloud) | S (cloud) | S (cloud) | S (Vee) | P | P | P | S | P | S (Copilot) | S | S | P (local LLM) |
| On-prem or local inference possible | – | – | – | – | – | – | – | – | P (data files) | – | – | – | S |
| Open, exportable, versioned definitions | – | – | – | P | P | – | – | – | P | P | S (LookML) | P | S |
| Higher-ed-specific models (faculty rank, tenure, IPEDS, CUPA-HR) | P | ? | ? | ? | ? | P (La Trobe, Deloitte model) | – | – | P (programs, not HR) | – | – | – | P (build) |
| Public higher-ed adoption evidence | S | P | P | – | – | P | – | – | S (programs) | P | P | P | n/a |
| Published accuracy evaluation of AI features | – | – | – | – | – | – | – | – | – | – | – | – | P (you build it) |
| Cost transparency | – | – | – | – (about $100k/yr median [S]) | – | – | P | – | P | S | S | S | S |

---

## 8. Best tool per job: public university HR analytics shop, limited budget, strict data rules

Assumptions [J]: the HRIS is already Workday or Oracle; there is a campus Microsoft or Google agreement; institutional content must stay on approved machines and use local inference; only aggregates are published.

| Job | Recommended | Why | Avoid or defer |
|---|---|---|---|
| HR system of record, transactional skills capture | **The existing HCM** (Workday Skills Cloud, Oracle Dynamic Skills) | Already paid for; employees maintain profiles there | Buying a second ontology vendor |
| Extraction | Workday Data Cloud Live Data Query once GA, with RaaS or Prism exports until then; Oracle BICC or HCM Extracts | Avoids hand-built extracts | Committing to Data Cloud before GA |
| Analytical store | **DuckDB** (single-analyst or small team) or **Postgres** (multi-user, row-level security) on approved servers | Free and local; fits HR volumes | Paid cloud warehouses for under 50M rows |
| Metric definitions | **dbt Core + MetricFlow** (Apache 2.0), with definitions aligned to IPEDS HR and CUPA-HR position codes | Versioned, reviewable, portable | Metrics defined separately in each BI tool |
| Orchestration and lineage | **Dagster** OSS (or cron plus dbt for a tiny shop) | Lineage for audit | — |
| Dashboards for HR leaders | **Power BI** on the existing campus tenant (F2 only if Copilot is needed); publish suppressed aggregates | Already licensed on most campuses | Turning on Copilot over row-level data without a policy review |
| Public or static reports | **Evidence.dev** (BI-as-code) | Reports are reviewed artifacts | — |
| Skills taxonomy backbone | **O\*NET 31.0** (public), **NICE v2.2** (cyber), **SFIA 9** (IT, within the free-licence scope), **Lightcast Open Skills** if not-for-profit terms are confirmed in writing | Free and auditable | Proprietary-only ontologies as the master |
| Skills graph | Typed edge tables in Postgres or DuckDB, plus **DuckPGQ** or **Neo4j Community** for exploration | Small graph; no extra infrastructure | TigerGraph, Stardog, Palantir |
| Local LLM serving | **vLLM** (server GPU) or **llama.cpp/Ollama** (workstation) | On-prem | Cloud LLM APIs for institutional text |
| Local models | One 20–35B open model with a clear licence (gpt-oss-20b or Mistral Small for Apache 2.0; Qwen or Gemma after a licence review) plus **Qwen3-Embedding-0.6B** or **BGE-M3** | Fits one GPU | Model choice without a local evaluation |
| Guardrails | **Presidio** (PII) plus rule-based output filters; NeMo Guardrails optional with telemetry disabled | Deterministic, auditable | LLM-judge moderation as the only control |
| Retrieval over policies and job descriptions | **LightRAG** or plain hybrid retrieval with pgvector; Microsoft GraphRAG only for static corpora | Indexing cost | — |
| External demand benchmarks | **CUPA-HR DataOnDemand** (already a member benefit for many campuses), **IPEDS**, **BLS OEWS**, **Revelio RPLS** (free); Lightcast Analyst if academic affairs already licenses it | Low cost | LinkedIn Talent Insights unless recruiting volume justifies it |
| Workforce planning scenarios | Workday Adaptive (if owned); otherwise a DuckDB plus Python scenario model with the outputs reviewed in Power BI | Avoids a $100k+ tool | Anaplan or Pigment unless finance already owns them |
| Internal mobility | HCM-native job board plus a skills-match prototype (see gap G10) | Vendors are expensive and unproven in higher ed; legal risk (Eightfold suit) | Black-box ranking of employees |

**Are other tools "just as good or better"?** [J]

- **Visier and One Model** beat a do-it-yourself stack on time to first insight for standard metrics. Their price (a median of about $100k per year [S]) and cloud-only processing are the obstacles, and neither showed public higher-ed references.
- **Fabric/Power BI and Looker** are as good as Snowflake or Databricks for this data volume, often at lower marginal cost, when the campus already holds the licence.
- **DuckDB/Postgres plus dbt** is *better* than any of them on data control and cost. It is worse on self-service for non-technical users.

---

## 9. Gaps no product fills well: work a custom engineer could build

Each gap lists what is missing, the evidence that it is missing, and what a build would look like.

**G1. A higher-ed job-architecture crosswalk.** This maps local position classes and job codes to SOC/O\*NET, the IPEDS HR occupational categories and CUPA-HR position codes in one versioned table.
- *Evidence:* CUPA-HR runs its own Position Matching Tool and survey codes [V]. IPEDS uses SOC-derived categories [V]. HCM ontologies are proprietary [V/M]. I found no product that ships this crosswalk.
- *Build:* a reviewed mapping table with confidence scores and human sign-off, plus a candidate-suggestion step that uses local embeddings.

**G2. Faculty pipeline modeling.** This covers rank progression, tenure clock, retirement eligibility, sabbatical cycles and discipline (CIP) coupled to teaching load and enrollment.
- *Evidence:* the only public academic-workforce-planning examples are consultant-built Anaplan models (La Trobe; the Deloitte HE model) [M]. Generic WFP tools model headcount and cost, not tenure states.
- *Build:* a Markov or cohort-component model in Python with transition rates estimated from internal history and benchmarked against CUPA-HR.

**G3. Positions funded by grants and soft money.** This means modeling position end dates, funding cliffs and effort percentages across HR and sponsored-research systems.
- *Evidence:* none of the WFP or people-analytics products reviewed expose funding-source-aware position risk [J; absence across the vendor material reviewed].
- *Build:* a join of HR positions to sponsored-project end dates, with risk horizons.

**G4. Version-aware taxonomy mapping with provenance.**
- *Evidence:* O\*NET shipped 30.1, 30.2, 30.3 and 31.0 within about a year. NICE went from v2.0 to v2.2 in 13 months. ESCO is at v1.2.1, and API results differ by version [V].
- *Build:* store every taxonomy release, compute diffs, re-map affected skills, and keep lineage from each skill tag to its taxonomy version and evidence span.

**G5. On-prem skills extraction from job descriptions and position documents, with a frozen evaluation set.**
- *Evidence:* the Lightcast free extraction tier allows 50 calls per month [V]. Oracle's skill suggestions are now generative and cloud-hosted [V]. Workday and SAP extraction runs in the vendor cloud [M].
- *Build:* a local model plus an open taxonomy, span-level evidence and deterministic precision and recall against a human-labelled sample.

**G6. Small-cell suppression and disclosure control before publishing.**
- *Evidence:* CUPA-HR publishes its own anonymity rules [V]. The BI copilots reviewed (Power BI Copilot, Looker Conversational Analytics, Quick Suite) document no minimum-cell-size enforcement in their natural-language answers [J; not found in the docs reviewed]. Small departments make re-identification easy.
- *Build:* a semantic-layer policy that refuses or rounds cells below k, with complementary suppression, applied to every export and to assistant answers.

**G7. Deterministic evaluation of HR AI assistants.**
- *Evidence:* Vee, Joule People Intelligence, Workday agents and Fabric Copilot publish no accuracy benchmarks on HR questions. SAP sources say agent output "will only ever be as accurate as the skills data input" [S].
- *Build:* a gold set of HR questions with SQL-computed answers; score exact match and tolerance, with no LLM grading; run it on every model or prompt change under a labelled protocol.

**G8. Audit-ready documentation for any ranking or matching of people.**
- *Evidence:* the Eightfold FCRA class action [V]. The Colorado AI Act's employment provisions were delayed to 30 June 2026 [V]; their status after that date was not confirmed in this research.
- *Build:* model cards, feature lineage, adverse-impact tests and appeal logs for internal-mobility or succession recommendations.

**G9. Benchmark fusion.** This joins internal aggregates to CUPA-HR, IPEDS HR, BLS OEWS and Revelio RPLS at matched occupation and geography.
- *Evidence:* each source is separate. CUPA-HR DataOnDemand does not ingest your HRIS, and no vendor reviewed integrates CUPA-HR [J].
- *Build:* a licence-aware benchmark mart that uses the G1 crosswalk.

**G10. Low-cost internal mobility for university staff.**
- *Evidence:* only 26% of higher-ed leaders are satisfied with internal-mobility processes; limited visibility of roles is the top obstacle [S, Cornerstone/University Business survey]. Only 29% of employees agree they have advancement opportunities [S, EAB]. NUS built its own marketplace [V]. I found no vendor case study in higher ed.
- *Build:* skills-overlap path suggestions between job families, shown as transparent explanations and not as ranked people.

**G11. An AI-exposure and reskilling map for university job families.**
- *Evidence:* UNESCO frameworks cover teachers and students only, and commentary notes that a higher-ed staff framework is missing. EDUCAUSE's competencies date from 2024 [V].
- *Build:* map O\*NET tasks for each job family to AI-assistable categories (human-reviewed), then link to learning offerings.

**G12. An open higher-ed HR metric pack.**
- *Evidence:* MetricFlow became Apache 2.0 in late 2025 [S], but I found no public metric package with IPEDS and CUPA-HR definitions (FTE, headcount by IPEDS category, faculty turnover).
- *Build:* a dbt package with tests, shareable across institutions as aggregates-only code.

**G13. Effective-dated organisation and position history reconstruction.**
- *Evidence:* Workday Data Cloud is early-adopter only [V]. Prism is one-directional [M]. Re-orgs break longitudinal series in every tool [J].
- *Build:* slowly-changing-dimension models of supervisory organisations and positions, with mapping across re-orgs.

**G14. A combined IT and cyber workforce view (NICE v2.2 plus SFIA 9) for central and distributed IT.**
- *Evidence:* both frameworks change on their own release cycles. SFIA licensing differs by use [V]. No HCM ontology reviewed exposes NICE work roles natively [J].
- *Build:* a dual-framework mapping of IT positions with proficiency levels.

---

## 10. Caveats and items to verify before decisions

- Enterprise pricing figures are second-hand (Vendr, aggregators). Request written quotes.
- Confirm these before relying on them:
  - Workday Data Cloud GA status
  - Lightcast's 2026 terms for non-profits
  - the Colorado AI Act's post-June-2026 status
  - the MetricFlow licence file
  - the Llama Guard 4 licence
- The absence of higher-ed case studies (Visier, One Model, Pigment, Eightfold, Gloat) reflects public search only; customers may exist privately. Ask vendors for public-university references.
- Open-model rankings change monthly. Choose by local evaluation under a fixed protocol, not by leaderboard.
- Nothing in this document tests any product's accuracy on real institutional documents. Source-traceability or marketing claims are not evidence of real-document accuracy.
