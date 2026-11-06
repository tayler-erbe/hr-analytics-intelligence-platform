# HR Workforce Analytics Intelligence Platform

**University of Illinois System · AITS Decision Support**
Developed by [Tayler Erbe](https://terbe2022.github.io/tayler-portfolio/) in partnership with [Luanne Mayorga](https://www.linkedin.com/in/luannemayorga/), Assistant Chancellor for Illinois HR

> POC workstreams complete. Full production build currently under review.

---

## Overview

The HR Workforce Analytics Intelligence Platform is a predictive analytics initiative designed to transform raw HR and payroll data from the university's Enterprise Data Warehouse (EDW) into forward-looking strategic workforce intelligence.

Rather than producing another retrospective HR report, the platform is built to surface what the university does not yet know: which departments are quietly trending toward capacity gaps, which critical roles have no internal succession pipeline, and which employees are positioned to step into leadership before vacancies occur. It shifts workforce planning from reactive to proactive.

All data required for this platform exists within the university's existing HR and payroll infrastructure. No new data collection is required.

**Project case study:** [terbe2022.github.io/tayler-portfolio/hr-workforce-analytics.html](https://terbe2022.github.io/tayler-portfolio/hr-workforce-analytics.html)

---

## The Problem

Workforce planning at most universities is largely reactive. Leadership becomes aware of staffing challenges only after they have already materialized: key roles go vacant with no successors ready, departments lose institutional knowledge through unexpected attrition, and hiring decisions are made without visibility into internal mobility patterns or future demand.

Several fundamental workforce questions remain difficult to answer in real time:

- Which departments will face capacity or skills gaps in the next 12 months?
- Which critical roles have no viable internal succession pipeline right now?
- Where is turnover signaling structural instability versus normal movement?
- Which employees are positioned to step into leadership or specialist roles?
- Which job families face elevated risk from external labor market competition?

Without predictive intelligence, these questions only surface after the damage has been done.

---

## Three Core Analytics Capabilities

### 1. Internal Mobility Modeling and Career Path Analysis

Analyzes historical job transition data to map how employees actually move through the organization. Identifies career ladders, bottlenecks, fast-track pathways, and structural dead-end roles that stall progression and drive attrition.

Core technical components:

- **Career transition matrix** built from each employee's historical job title sequences
- **Markov chain simulation** engine (`simulate_career_path()`, `simulate_many_paths()`) that projects career journeys forward across N moves
- **Graph analytics** (NetworkX + `greedy_modularity_communities`) applied to the transition network to detect natural career communities and PageRank-style hub roles
- Classification of fast-track roles, dead-end roles, feeder roles, and diversity index per starting position

### 2. Succession Readiness Prediction

Identifies which internal employees are most ready to step into leadership or specialist roles before those positions become vacant, and flags roles with no viable internal pipeline.

Core technical components:

- **Departure risk model** (XGBoost / Logistic Regression): estimates probability a role becomes vacant in the next 6-12 months using tenure slope, SURS retirement indicator, department churn rate, role-level attrition history, and pay band ceiling proximity. Output: `p_vacancy`
- **Candidate readiness model** (Gradient Boosting / LambdaMART Learning-to-Rank): predicts fit between an internal candidate and a target role based on skill similarity, grade progression, and mobility history. Output: `p_success`
- **Succession Readiness Index (SRI)** composite score per candidate-role pair:

```
SRI = w1 * p_success + w2 * SkillSim + w3 * TenureFit + w4 * ExperienceFit
```

- **LLM-assisted skill enrichment**: GPT/LLaMA extracts skills from job titles and descriptions, mapped to O*NET canonical standards. Sentence Transformers (InstructorXL) generate semantic embeddings. Cosine similarity measures fit between candidate and target role skill profiles.
- Equity audit view: recommendation parity review across demographic groups before operational use

### 3. Workforce Growth Forecasting and Attrition Intelligence

Projects headcount, hiring demand, and turnover patterns by department and job family over a 1-3 year horizon.

Core technical components:

- Time series decomposition and trend analysis on historical EDW hiring, termination, and headcount records
- Department clustering by workforce behavior pattern (stable, growing, at-risk)
- Integration of O*NET occupation codes and BLS external growth outlook (Low / Moderate / High / Very High) to benchmark internal roles against labor market competition
- Attrition risk scoring at the unit and job family level

---

## Models and Algorithms

| Model | Type | Key Inputs | Output |
|---|---|---|---|
| Promotion Prediction | Supervised Classification (Random Forest, `class_weight="balanced"`) | Age, tenure, time in role, move rate, pay grade, job family, growth outlook, title embeddings | Promotion likelihood score per employee |
| Career Path Simulation | Generative (Markov Chain) | Career transition matrix from historical job title sequences | Probability distributions of career destinations across N moves |
| Career Community Detection | Graph Analytics (NetworkX, greedy modularity) | Weighted directed graph of role-to-role transitions | Natural career clusters, hub roles, dead-end and feeder role classification |
| Departure Risk | Supervised (XGBoost / Logistic Regression) | Tenure slope, SURS indicator, department churn, pay band ceiling proximity | `p_vacancy` per role |
| Candidate Readiness | Learning-to-Rank (LambdaMART) | Skill similarity, tenure, grade progression, mobility history | `p_success` per candidate-role pair |
| Workforce Growth Forecasting | Time Series / Trend Analysis | Historical hiring, turnover, and headcount by department and job family | Headcount forecasts and attrition risk scores |

---

## Feature Engineering

Derived features computed from raw EDW data that feed into all models:

- **Tenure buckets**: 0-3, 3-7, 7-15, 15+ years (total and current role separately)
- **Move rate per year**: `n_internal_moves / tenure_years`
- **Transition probability matrix**: from/to role probabilities derived from historical job title sequences
- **Job title embeddings**: SentenceTransformer vector representations (InstructorXL) enabling semantic similarity between roles
- **Career path structure metrics**: fast-track roles, dead-end roles, feeder roles, pathway diversity index
- **Departure risk signals**: SURS retirement eligibility, pay band ceiling proximity, department-level churn rate (trailing 12 months), tenure slope
- **Mobility cluster labels**: Early-career ladder, Fast-track leader, Stable long-tenure, Cross-department mobile
- **O*NET growth outlook**: external labor market classification (Low / Moderate / High / Very High) joined to internal job families
- **Skill similarity score**: cosine similarity between O*NET skill vectors of candidate and target role after LLM-assisted extraction and canonical mapping

---

## Data Sources

All data required for this platform exists within the university's existing HR and payroll infrastructure.

### EDW Tables

| Table | Contents | Used For |
|---|---|---|
| `T_PERS_HIST` | Biographical and demographic data | Person-level joins, demographic features for equity audit |
| `V_EMPEE_HIST_1` | Current employment view | Active employee filter, point-in-time snapshots |
| `T_EMPEE_HIST` | Employment lifecycle: hire date, FTE, job class | Tenure, FTE features, employment continuity |
| `T_EMPEE_HIST_5` | Termination and SURS retirement details | Departure risk modeling, SURS retirement indicator |
| `T_JOB_DETL_HIST` | Job history: title, pay rate, department, supervisor | Career transition sequences, role similarity, pay grade features |
| `T_PAYR_ACCTG_DETL` | Payroll accounting history | Pay band ceiling proximity, earnings trend |

### External Sources

- **O*NET Skill Taxonomies**: standardized occupational skill and knowledge attributes for canonical role mapping and semantic embeddings
- **BLS Workforce Trends**: occupational growth outlook classifications joined to internal job families via O*NET crosswalk

Effective-date logic (`*_EFF_DT` / `*_EXP_DT`) across EDW tables enables as-of snapshots at any point in time, essential for backtesting models and computing rolling features like tenure slope and department churn rate.

**Canonical joins:**

```sql
T_PERS_HIST.EDW_PERS_ID     = T_EMPEE_HIST.EDW_PERS_ID
T_EMPEE_HIST.EDW_PERS_ID    = T_JOB_DETL_HIST.EDW_PERS_ID
T_JOB_DETL_HIST.POSN_NBR   = T_PAYR_ACCTG_DETL.POSN_NBR
```

---

## Proof-of-Concept Work Completed

Three POC workstreams were completed before seeking production build approval. Each was built on a synthetic dataset mirroring EDW HR table structure.

### Internal Mobility and Career Path Forecasting
*Ruchita Alate, Data Science Analyst*

- Synthetic 500-employee dataset (`internal_mobility_dummy_500.csv`) mirroring EDW structure
- Full feature engineering pipeline: tenure buckets, move rate, title embeddings, transition matrix
- Random Forest promotion prediction model with balanced class weighting
- Markov chain simulation engine (`simulate_career_path`, `simulate_many_paths`)
- Career community detection via NetworkX and greedy modularity
- Fast-track, dead-end, and feeder role classification
- Dashboard prototype suite: Sankey flows, transition waterfalls, network density charts
- Produced artifacts: `career_transition_matrix.csv`, `internal_mobility_features_for_dashboard.csv`, `transitions.csv`

### Succession Readiness Prediction
*Tejasri Joshi, Data Science Analyst*

- EDW schema mapping for succession use case (T_PERS_HIST, T_JOB_DETL_HIST, T_EMPEE_HIST_5)
- Departure risk model design: XGBoost / Logistic Regression on SURS and churn features
- Candidate readiness model: Gradient Boosting and LambdaMART Learning-to-Rank
- O*NET skill enrichment pipeline with FAISS embedding index
- SRI composite formula and weighting framework
- Succession dashboard prototype: vacancy heatmap, skill gap views, equity audit view
- Three scenario walkthroughs: retirement succession, training gap, cross-unit mobility

### Workforce Growth Forecasting
*Tanvi, Data Science Analyst*

- Headcount forecasting by department and job family
- Hiring demand prediction models
- Turnover trend analysis and seasonality decomposition
- Department growth and stability clustering
- BLS / O*NET external growth outlook integration
- Attrition risk scoring at the unit level
- Dashboard visualization prototypes for Power BI / Tableau

---

## Production Build Roadmap

The platform build is structured across four phases with a team of one lead data scientist and three intern analysts (~2,460 total hours over approximately six months). The build is currently under review.

| Phase | Name | Duration | Focus |
|---|---|---|---|
| Phase 1 | Data Preparation and Quality Analysis | Weeks 1-6, ~500 hrs | EDW extraction, data cleaning, transition dataset construction, feature engineering, O*NET/BLS join |
| Phase 2 | Workforce Analytics Model Development | Weeks 6-14, ~800 hrs | Promotion model, transition matrix and Markov simulation, graph analytics, succession models, growth forecasting |
| Phase 3 | Model Validation and Output Generation | Weeks 14-18, ~400 hrs | Validation against historical trends, fairness review across demographic groups, structured output generation |
| Phase 4 | Workforce Intelligence Platform Development | Weeks 18-26, ~760 hrs | Platform architecture, Power BI / Tableau dashboards, career pathway maps, mobility network views, HR reporting tools |

---

## Long-Term Vision

This platform is not a standalone project. The standardized HR data, semantic role mappings, and model infrastructure built here support a broader institutional AI and analytics strategy:

- **ERP Modernization Readiness**: standardized workforce data and job taxonomy normalization reduce migration risk for future ERP upgrades
- **AI-Driven Talent Acquisition**: semantic role embeddings and mobility models enable intelligent internal candidate identification
- **Skill Gap Analysis**: O*NET mapping enables workforce capability gap modeling against future demand
- **LLM-Powered HR Assistant**: clean structured metadata and embeddings provide the grounding layer for conversational AI tools
- **University-Wide Analytics Platform**: the semantic data layer can extend to finance, research operations, and enrollment analytics

---

## Repository Contents

```
hr-analytics-intelligence-platform/
README.md
```

POC notebooks and analytical artifacts are maintained in a separate internal Box repository pending data governance review for production deployment.

---

## Contact

**Tayler Erbe** · Senior Data Scientist · AITS, University of Illinois System
[Portfolio](https://terbe2022.github.io/tayler-portfolio/) · [LinkedIn](https://www.linkedin.com/in/tayler-erbe/)

HR Stakeholder: [Luanne Mayorga](https://www.linkedin.com/in/luannemayorga/), Assistant Chancellor for Illinois HR


## Platform evaluation and synthetic practice run

The [platform-evaluation workspace](platform-evaluation/README.md) contains the Snowflake/Databricks/custom evaluation rubric, synthetic benchmark fixtures and reference SQL, blank scorecards, public O*NET and SUCSS reference data, and an offline role-evolution demo.

Start with the [evaluation rubric](platform-evaluation/PLATFORM_EVALUATION_RUBRIC.md) and [benchmark guide](platform-evaluation/benchmark/README.md). All platform scorecards remain ungraded. Internal org charts, employee exports, and local databases are excluded.
