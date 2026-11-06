# UIUC / U of I System HR Tool and AI Landscape, with a Workforce-Analytics Gap Analysis

**Research date:** 2026-11-06. **Method:** web search only. Direct page fetches to `*.illinois.edu`, `*.uillinois.edu` and `massmail.illinois.edu` were blocked in this research environment, so every claim below comes from search-engine snippets and summaries of the cited pages, not from reading the pages themselves. Treat everything as a lead to confirm. Nothing here uses or reflects internal or institutional documents.

**Confidence key:** **H** = an official Illinois page said this directly in the snippet. **M** = an official page implies it, or several secondary sources agree. **L** = a single, secondary or dated source. **UNVERIFIED** = asked about but not found; do not assert it.

---

## 1. Summary

- **System of record:** Banner HR/Payroll (Ellucian), in production since December 2003. HR transactions are entered through the custom **HR Front End (HRFE)**. AITS runs the reporting stack: the **EDW**, Business Objects/**EDDIE**, **Tableau Server** and **Denodo**.
- **ERP modernization:** In April 2026 President Killeen announced a System-wide **"ERP Business Transformation" / "Business Modernization and Transformation"** effort to move off Banner to a cloud ERP. HR and finance go first. As of the latest sources found (spring 2026), the program is in a **consultant-led readiness phase**. **No vendor selection was found.** The ERP site reportedly discusses Ellucian Cloud, Workday and Oracle Fusion as candidates.
- **Talent stack:** **JDXpert (JDX)** handles job descriptions and position reviews. **Cornerstone** handles recruiting; it replaced HireTouch in about 2022 and sits behind jobs.illinois.edu. **LinkedIn Learning** and **Coursera** provide content. **Qualtrics** is the survey tool. **TeamDynamix (TDX)** provides ticketing and knowledge bases.
- **AI tools:** Three AI tools are approved for Public, Internal and Sensitive data under conditions:
  - **Microsoft Copilot Chat** (enterprise data protection)
  - **Illinois ChatGPT EDU**
  - **Illinois Chat**, run by NCSA, Illinois Computes and the Office of the CIO, launched Fall 2025. Sensitive data is allowed only on its locally hosted models.

  **Microsoft 365 Copilot** is a paid per-user add-on bought through the WebStore. The last listing found expired 2026-06-30.
- **Legal:** **HB 3773** (an Illinois Human Rights Act amendment, in effect since 2026-01-01) requires employers to give notice when AI is used in employment decisions and prohibits discriminatory effect. The notice rules from the Illinois Department of Human Rights (IDHR) appear **not yet final**.
- **Main gap:** No tool joins position (JDX), person (Banner), learning, recruiting (Cornerstone) and external labor-market data into a **governed, skills-aware workforce model** that supports scenarios, succession and mobility. None of the approved AI assistants is **grounded in HR policy and HR data under role-based access**.

---

## 2. HR systems of record and ERP modernization

| Item | Current state | Conf. | Source(s) |
|---|---|---|---|
| Core HR/Payroll | Ellucian **Banner** HR/Payroll, implemented Dec 2003. Shared across the System and run by AITS. | H | https://hr.uillinois.edu/human_resource_systems/h_r_applications/hr_front_end/overview ; https://www.aits.uillinois.edu/services/systems_overview |
| Transaction layer | **HR Front End (HRFE)**, a custom web workflow over Banner covering hire through separation. Units initiate, colleges approve and central HR applies. Project ITPC-0175, started 2006, $4.7M. Some lookups still go directly to Banner forms. | H | same as above; https://hr.uic.edu/hr-staff-managers/hr-systems/hr-front-end/ ; https://answers.uillinois.edu/ihr/154705 |
| Other HR systems named in UIUC job postings | "HR Front End, Banner, Cornerstone, JDX, I-9 Tracker", and also Chrome River (expenses) | M | https://illinoisjoblink.illinois.gov/jobs/12064201 (posting; may expire) |
| IHR system list | Illinois HR maintains an "HR Systems" page and job-aid hub for HR professionals | M | https://humanresources.illinois.edu/hr-professionals/hr-systems.html ; https://humanresources.illinois.edu/services-and-information/resources/applications/ |
| **ERP modernization** | Program name: **"ERP Business Transformation"** / **"Business Modernization and Transformation."** Moves Banner to a cloud ERP. **HR and finance first, student later.** Announced about 2026-04-14 by President Killeen. Multi-year, in four phases: readiness, selection, deployment, post-deployment. A consultant is doing a readiness and roadmap assessment. | H (announcement), M (phases) | https://www.uillinois.edu/erp ; https://www.uillinois.edu/erp/our_path_forward ; https://massmail.illinois.edu/massmail/1486908145.html ; https://www.uis.edu/news/faculty-orbit-campus-announcement-staff/message-president-killeen-announcing-erp-business-transformation-university-illinois-system ; https://today.uic.edu/enterprise-resource-planning-modernization-what-this-means-for-us/ |
| Vendor candidates | The ERP page reportedly says only three platforms fit a system this size: **Ellucian Cloud (Banner SaaS), Workday, Oracle Fusion Cloud**. A sub-page reportedly mentions stakeholder demos. | M (snippet only) | https://www.uillinois.edu/erp ; https://www.uillinois.edu/erp/nextsteps |
| Vendor selected? | **UNVERIFIED / not found.** No announcement of a selection between Sept and Nov 2026 was found. The readiness phase was described as about two years. | UNVERIFIED | — |
| Consultant identity | **UNVERIFIED.** It was not named in the snippets. A 2026 Business & Finance Symposium session described the consultant-led assessment. | UNVERIFIED | https://conferences.uillinois.edu/business-and-finance-symposium-2026 |

**What this means for a workforce-planning lead:** for the next 2 to 4 years, HR data will live in Banner while the target model is chosen and built. Anything built now should sit on a **vendor-neutral semantic layer** so that it survives the cutover. It can also serve as reference work for the data conversion: definitions, history and quality rules.

---

## 3. Talent-lifecycle tools

| Domain | Tool(s) | Conf. | Source(s) / notes |
|---|---|---|---|
| Position descriptions / classification workflow | **JDXpert (JDX)**. Job description review routes initiator, then unit HR, hiring manager, college, IHR class analyst, IHR classification. Employees acknowledge their job description in JDX. The review cycle is "triennial" in the IHR job aid but "biennial" at UIS, so the two sources conflict. | H | https://www.humanresources.illinois.edu/jdxpert-cornerstone/index.html ; https://humanresources.illinois.edu/wp-content/uploads/2024/04/hrais-jdxjobdescriptionreviewsjobaid.pdf ; https://answers.uillinois.edu/118803 |
| Recruiting / ATS | **Cornerstone** (Cornerstone OnDemand recruiting) behind **jobs.illinois.edu**. Requisitions start from JDX workflows. Replaced **HireTouch** across the System in about 2022. **Not PageUp or iCIMS:** no evidence of either was found. | H (Cornerstone), L (2022 date) | https://www.humanresources.illinois.edu/jdxpert-cornerstone/index.html ; https://oae.illinois.edu/?p=2867 ; https://hr.uic.edu/hr-staff-managers/hr-systems/cornerstone/ |
| Civil service classification | Rules come from the **State Universities Civil Service System (SUCSS)**. Its stream of class-specification and exam revisions continued through 2026, for example Security Officer 4212 (effective 2026-07-01), Member Service Rep 1 4819, Deputy Director 1035 and the Institutional Compliance Examiner series. IHR points staff to the SUCSS notices. | H | https://answers.illinois.edu/ihr/158501 ; https://sucss.illinois.gov/documents/csn/3321.pdf (and adjacent CSN notices) |
| Civil service / AP reform | **Professional Employment Redesign (PER)** at IHR covers the revised SUCSS exemption criteria for Academic Professional positions. Older public hearings discussed statutory reform. **No 2026 UIUC "classification and compensation study" was found.** | M (PER), UNVERIFIED (comp study) | https://humanresources.illinois.edu/professional-empl-redesign-per/ ; https://news.illinois.edu/civil-service-recommendations-discussed-at-public-hearings/ |
| Learning content | **LinkedIn Learning**, free to faculty, staff and students via NetID. **Illinois on Coursera**, more than 170 non-credit courses. | H | https://humanresources.illinois.edu/employee-experience/current-employee/learning-development/ ; https://extension.illinois.edu/workforce/learning-development |
| Learning delivery / LMS | IHR **Employee Learning & Organizational Effectiveness (ELOE)** runs supervisor series and customized training. There is a System "Training and Development Resources" (Training Hub) KB. **No campus-wide employee LMS name was confirmed.** "Illinois Learning Center" was **not found**. Cornerstone's learning module is **not confirmed** in use. | M (ELOE), UNVERIFIED (LMS) | https://humanresources.illinois.edu/learning/ ; https://answers.uillinois.edu/118250 |
| Performance appraisal | The System Offices use an **online performance appraisal system**. UIUC civil service evaluations appear to be, at least in some units, **Word-form based** (for example, the F&S annual civil service evaluation form). **No campus-wide UIUC online appraisal tool was confirmed.** | H (System Offices), L (UIUC) | https://www.hr.uillinois.edu/system_office_employees/performanceappraisals ; https://docs.fs.illinois.edu/wp-content/uploads/2025/03/Annual-Civil-Service-Evaluation-Non-Supervisory.doc |
| Surveys | **Qualtrics** campus site license, administered by CITL with Technology Services Research Enablement. Free with NetID. Data is stored by Qualtrics. Add-ons such as SMS are sold through the WebStore. | H | https://webstore.illinois.edu/shop/product.aspx?zpid=1320 ; https://citl-data.github.io/qualtrics-guide/Illinois-Qualtrics-Guide.docx |
| Case / service management | **TeamDynamix ("TDX at Illinois")**: a single System instance with per-university portals at help.uillinois.edu. Technology Services moved to it in Feb 2021. The **answers.illinois.edu/ihr** KB exists. **Whether IHR uses TDX for HR cases is UNVERIFIED.** No ServiceNow use was found. | H (TDX), UNVERIFIED (IHR use) | https://help.uillinois.edu/TDClient/42/UIUC/Requests/ServiceDet?ID=504 ; https://answers.uillinois.edu/118503 |
| Collaboration | Microsoft 365 (Teams, Copilot Chat via NetID SSO). Box also appears (uofi.box.com). | H (M365), M (Box) | https://answers.illinois.edu/133037 ; https://www.techservices.illinois.edu/tag/microsoft-copilot |

---

## 4. HR reporting, BI and data platform

| Component | State | Conf. | Source(s) |
|---|---|---|---|
| **Enterprise Data Warehouse (EDW)** | AITS Decision Support. Combines finance, **HR** and student data. Access goes through Unit Security Contacts (USCs). | H | https://aits.uillinois.edu/access/data_warehouse_access ; https://www.aits.uillinois.edu/services/reports_and_data/enterprise_data/ |
| Business Objects / **EDDIE** | Canned and ad hoc reporting over the EDW. There are **"EDW – HR Front End" universes**. | H | https://www.aits.uillinois.edu/services/reports_and_data/about_data/metadata/metadata_for_business_objects_users/universe_information/edw_-_hr_front_end_universes |
| **Tableau Server** | AITS-hosted dashboard publishing. Tableau Desktop is bought through the WebStore. | H | https://www.aits.uillinois.edu/services/reports_and_data/tableau_server_service |
| **Denodo** | A data virtualization layer that joins external data with enterprise data. | H | https://www.aits.uillinois.edu/services/reports_and_data/enterprise_data/ |
| HR Reporting Portal / Data Cookbook | AITS lists an **HR Reporting Portal** linking HR report sources, and a **Data Cookbook** of EDW definitions. | M | https://www.aits.uillinois.edu/services/reports_and_data/help_and_training |
| Power BI / Fabric at UIUC | **UNVERIFIED.** No current Technology Services Power BI or Fabric service page was found. Tableau is the documented enterprise standard. | UNVERIFIED | — |
| Public IHR workforce dashboards | **None found.** One informal document mentions an "Employee Dashboard" with headcount by demographics and tenure, held by another office. Peer schools (UC Davis, Iowa) publish theirs. | L | https://uofi.box.com/shared/static/z84a50lawkdlpl9433zd4nu0q7g7b5p0.pdf ; https://www.hr.ucdavis.edu/data |
| AITS AI roles | AITS posted an **"AI Analyst – Hybrid/Remote"** role (about Jan 2026, $80K–$90K), a signal that enterprise AI capacity is being built at the System level. | L | https://www.career.com/job/university-of-illinois/ai-analyst-hybrid-remote/j202601092111446491074 |

---

## 5. Generative AI tools, governance and organization

### 5.1 Approved tools (UIUC GenAI site)

| Tool | Who | Approved data | Notes | Conf. | Source |
|---|---|---|---|---|---|
| **Microsoft Copilot Chat** | Faculty, staff, students | Public / Internal / **Sensitive** (within M365) | Enterprise data protection, so no training on prompts | H | https://genai.illinois.edu/ai-apps-copilot-chat/ |
| **Microsoft 365 Copilot** (in-app) | Faculty and staff, paid | Per M365 terms | The WebStore listed "M365 Copilot Edu Per User Urbana" at about $259.50 discounted, expiring 2026-06-30. FY27 terms are **UNVERIFIED**. A Copilot pilot program preceded it. UIC lists $402. | M | https://webstore.illinois.edu/shop/product.aspx?zpid=6050 ; https://it.uic.edu/news-stories/ms-copilot-available-to-uic-staff |
| **Illinois ChatGPT EDU** | Faculty and staff | Public / Internal / **Sensitive** in the Illinois workspace | Model training disabled. Extra usage credits purchasable. Personal ChatGPT accounts are not approved. | H | https://genai.illinois.edu/ai-apps-chatgpt-at-illinois-edu/ ; https://answers.uillinois.edu/156617 ; https://answers.uillinois.edu/159560 |
| **Illinois Chat** (illinois.chat, formerly UIUC.chat) | Everyone, free | Public / Internal; **Sensitive only on locally hosted models** | Build-your-own RAG chatbot. Data stays on university resources. Run by NCSA, Illinois Computes and the Office of the CIO. Launched Fall 2025. | H | https://genai.illinois.edu/ai-apps/ ; https://computes.illinois.edu/resources/illinois-chat/ ; https://www.ncsa.illinois.edu/research/project-highlights/illinois-chat/ |
| Google Gemini / NotebookLM | — | **UNVERIFIED** | No UIUC approval found | UNVERIFIED | — |

Library-licensed content may not be uploaded to AI tools. Questions about data types go to securitysupport@illinois.edu (H, from genai.illinois.edu/ai-apps).

### 5.2 Governance and organization

| Item | State | Conf. | Source |
|---|---|---|---|
| **GenAI Solutions Hub** (UIUC) | A cross-campus group that defines infrastructure, **procurement pathways** and usage practices, aligned with the System-wide GenAI risk-management strategy | H | https://genai.illinois.edu |
| System GenAI guidance | VPAA "Digital Risk Management – Generative AI" guidance and framework. Universities adapt it locally. Staff-specific guidance is "to be developed." | H | https://www.vpaa.uillinois.edu/digital_risk_management/generative_ai ; https://www.vpaa.uillinois.edu/digital_risk_management/generative_ai/guidance |
| AITS AI guidelines | "AI guidelines for safe use" (2026) at aits.uillinois.edu/ai/ai_guidelines. Cited by a System page, but the content was **not retrieved**. | M | https://www.studentmoney.uillinois.edu/aboutsmmc/a_i_use_disclosure |
| Senate oversight | Senate IT Committee 2025–26 annual report (2026-04-27) includes "shared governance and AI." Deputy CIO Kim Milford briefed the committee. | H | https://www.senate.illinois.edu/2025-2026/20260427senate/IT2604_FINAL_20260427.pdf |
| Office of the CIO | Recruited a **Deputy CIO, Campus Engagement** (posted 2026-03) | M | https://www.career.com/job/illinois/deputy-chief-information-officer-campus-engagement-office-of-the-chief-information-officer/j202603181908056624144 |
| **"Senior Enterprise AI Advisor, Office of the CIO"** | **UNVERIFIED.** No public posting or page was found. The search instead surfaced the **State of Illinois DoIT** Chief AI Officer build-out, which is a different employer. Treat the role's scope as unknown until its posting is in hand. | UNVERIFIED | (contrast) https://www.govtech.com/workforce/illinois-new-chief-ai-officer-has-federal-state-experience |
| NCSA **Center for AI Innovation (CAII)** | Founded 2019 and directed by Volodymyr Kindratenko. Research and applied-AI hub; Illinois Chat came out of its work. | H | https://ai.ncsa.illinois.edu/center-for-artificial-intelligence-innovation/ |
| Campus provost AI task force / CIO AI strategy doc | **Not found.** No 2025–26 UIUC provost AI task-force report or published CIO AI strategy was found. | UNVERIFIED | — |

---

## 6. Legal and procurement constraints

| Constraint | What it means for HR AI | Conf. | Source |
|---|---|---|---|
| **HB 3773** (Public Act 103-0804, Illinois Human Rights Act amendment), effective **2026-01-01** | It is a civil-rights violation to use AI that **has the effect** of discrimination in recruitment, hiring, promotion, training selection, discipline, discharge or terms of employment. Using **zip code as a proxy** for protected classes is prohibited. Employers must **give notice** when AI is used. **IDHR notice rules (draft "Subpart J")** are not final. One source says the May 2026 proposal was withdrawn; this is unconfirmed. | H (statute), L (rule status) | https://www.ebglaw.com/workforce-bulletin/illinois-prohibits-discriminatory-artificial-intelligence-in-employment-decisions ; https://natlawreview.com/article/illinois-proposed-notice-rules-complying-workplace-ai-anti-discrimination-law ; https://casrai.org/guides/illinois-hb-3773-ai-employment-discrimination |
| Artificial Intelligence Video Interview Act (820 ILCS 42) | Notice, consent and demographic-reporting duties if AI analyzes video interviews | H (well-established law; not re-checked today) | ilga.gov |
| BIPA (740 ILCS 14) | Biometric data in HR tools (timekeeping, identity verification) carries liability | H (well-established; not re-checked) | ilga.gov |
| **IITAA** (30 ILCS 587) and U of I EIT accessibility guidelines | Purchased or built software must meet IITAA. VPATs are required and should be verified. U of I prioritizes reviews of purchases of $100K or more and sends high-risk EIT to a review committee. Internally built tools must also be accessible. | H | https://doit.illinois.gov/initiatives/accessibility/iitaa/iitaa-procurement.html ; https://www.vpaa.uillinois.edu/userfiles/Servers/Server_420372/file/FINAL_Systemwide%20Digital%20(EIT)%20Accessibillity%20Implementation%20Guidelines_VPAA(1).pdf |
| Illinois Procurement Code (30 ILCS 500) / U of I purchasing | New SaaS (for example a skills-intelligence vendor) generally goes through competitive procurement or a sole-source justification, plus security, privacy and accessibility review. The GenAI Hub is defining "procurement pathways." **An AI-specific vendor review process at U of I is UNVERIFIED.** | M | https://genai.illinois.edu |
| Data classification | HR records are Sensitive or higher. They may go only to tools approved for that class: Copilot Chat, ChatGPT EDU, or locally hosted Illinois Chat models. | H | https://genai.illinois.edu/ai-apps/ |

---

## 7. Gap analysis: what the current stack does not do

Baseline: Banner/HRFE records the **person and the assignment**. JDX holds the **position and its duties**. Cornerstone holds **requisitions and applicants**. LinkedIn Learning and Coursera hold **content consumption**, which may not be centrally tracked. Qualtrics holds **sentiment**. The EDW and Tableau provide **historical reporting**. The GenAI tools provide **general-purpose chat**.

| Need | What exists | Gap | What a data/AI engineer could build | Notes / risk |
|---|---|---|---|---|
| **Integrated workforce record** | The EDW has Banner HR data. JDX and Cornerstone are separate SaaS products. Learning completions are scattered. | No position–person–requisition–learning join with consistent keys. Denodo could federate but has no curated HR model. | A **governed HR semantic layer** (dbt-style models on the EDW plus Denodo views) that links Banner position number, JDX job description ID, Cornerstone requisition and learning records. A data contract and Data Cookbook entries for each metric. Vendor-neutral, so it can be reused as the ERP conversion spec. | Owners: AITS Decision Support plus IHR. Respect USC access controls. |
| **Workforce planning / scenario modeling** | Static Tableau headcount views; spreadsheets | No forward projection of retirement eligibility, attrition, vacancy fill time or budget | **Projection and scenario engine**: cohort survival or attrition models by class, unit and SURS retirement eligibility; time-to-fill from Cornerstone; cost from Banner salary. "What-if" sliders for hiring freezes, reorganizations and ERP-driven role changes. | Publish aggregates only, with small-cell suppression. |
| **Skills inference** | JDX holds duties text. SUCSS class specifications are public. LinkedIn Learning has skill tags. | No skills taxonomy and no skills-to-position mapping | **Skills extraction from JDX descriptions and SUCSS specifications** (on-prem or approved models), mapped to **O*NET / Lightcast**-style taxonomies. A position-skills graph. Human review loop with classification analysts. | Infer skills for **positions**, not to score individuals. HB 3773 applies if outputs feed promotion or selection. |
| **Succession planning** | No tool found (the appraisal process is partly paper) | No critical-role register, readiness tracking or bench depth | **Critical-role risk index** (retirement eligibility × single-incumbent × skill scarcity × time-to-fill). Bench views from position-skills adjacency. | Keep it advisory with human decisions. Notice obligations under HB 3773 if applied to individuals. |
| **Talent mobility / internal career paths** | jobs.illinois.edu (Cornerstone) is posting-centric | No "roles like mine" or civil-service-to-AP pathway guidance. Civil service exam/register rules complicate moves. | **Career-path explorer**: position adjacency from skills overlap plus historical Banner transitions, annotated with SUCSS exam and register requirements and PER exemption rules. | Must encode civil service rules correctly. Validate with IHR and SUCSS. |
| **Reskilling / learning ROI** | LinkedIn Learning and Coursera licenses; ELOE programs | No link from skill gaps to recommended learning to outcomes; utilization probably not joined to HR data | **Gap-to-content recommender** (skills gap → LinkedIn Learning / Coursera / ELOE catalog). Aggregate learning-ROI analysis (completion → retention or mobility). Make AI-literacy uptake measurable for the CIO's AI adoption goals. | LinkedIn Learning reporting API access is UNVERIFIED. |
| **Classification analytics** | JDX workflow; SUCSS notices are PDFs | No impact analysis when SUCSS revises a class specification; no consistency check across job descriptions | **SUCSS notice tracker plus impact report**: parse class-specification notices, list affected positions and incumbents (aggregate), and flag JDX descriptions that drift from their class specification. | Advisory to IHR classification analysts; they decide. |
| **Governed HR AI assistant** | Copilot Chat, ChatGPT EDU and Illinois Chat are general-purpose; KB articles sit in answers.illinois.edu/ihr | No assistant grounded in IHR policy, SUCSS rules, the Campus Administrative Manual and HR job aids with citations; none over HR data with row-level security | (a) **Policy RAG** on **Illinois Chat (local models)** or Copilot Studio over public and internal HR policy, with citations, an evaluation set and refusal on individual cases. (b) Later, **NL-to-metric** over the semantic layer: aggregate-only, queries logged, role-scoped. | The Sensitive data class limits which tools can be used. IITAA accessibility review is required. Publish the evaluation method. No model grades another model. |
| **Engagement / sentiment linkage** | Qualtrics | Survey results not linked (aggregate) to turnover or unit structure | Pipeline that joins Qualtrics exports to unit hierarchies with k-anonymity thresholds, plus driver analysis | Qualtrics data is stored by the vendor; review consent language. |
| **External labor-market context** | None found | No benchmark for pay, demand or supply by occupation in the CU and Chicago markets | Ingest **BLS OES / QCEW, O*NET, IDES** data (free) and optionally Lightcast (procurement needed). Pay-competitiveness and hard-to-fill views by SUCSS class. | Public data first; vendor data requires procurement. |
| **AI-use compliance (HB 3773)** | No HR AI inventory found | No register of AI used in employment decisions, no notice tracking, no adverse-impact monitoring | **AI-in-employment register** plus a **disparate-impact monitoring job** (four-fifths rule and statistical tests on selection outcomes) for any AI-assisted step, and a notice template workflow | Coordinate with University Counsel and OAE. |
| **ERP transition readiness** | Consultant readiness assessment | No quantified data-quality baseline for HR | **HR data-quality scorecard** (completeness, position/job description mismatches, orphan records, history depth) that feeds the conversion and future-state design | Fits the readiness phase. |

### 7.1 Suggested sequencing (low regret)

1. **Months 0–3:** HR data-quality scorecard plus the semantic-layer core (person, position, job description, requisition) on the EDW/Denodo. Draft the AI-in-employment register.
2. **Months 3–6:** Retirement and attrition projection in Tableau (aggregate). SUCSS notice impact tracker. Policy RAG pilot on Illinois Chat (local models), using public policy text only, with a published evaluation.
3. **Months 6–12:** Skills extraction from position descriptions mapped to O*NET. Critical-role risk index. Career-path explorer prototype. External labor-market benchmarks.
4. **Continuously:** Map every artifact to the future ERP data model so the work carries over.

---

## 8. Open questions to verify (priority order)

1. ERP: vendor decision status, consultant name, and the HR go-live target. Check https://www.uillinois.edu/erp directly.
2. The actual posting and scope of the "Senior Enterprise AI Advisor, Office of the CIO" role.
3. Whether IHR has a workforce analytics team and internal dashboards (Tableau on the AITS server?), and what the HR Reporting Portal contains.
4. Which UIUC employee LMS records training completions (Cornerstone Learning? a unit-level system?), and whether LinkedIn Learning usage data is available.
5. UIUC online performance appraisal: is there a campus tool, or are forms unit-level?
6. FY27 Microsoft 365 Copilot licensing and price at Urbana. Whether Power BI or Copilot Studio is enabled in the UIUC tenant.
7. IDHR HB 3773 rule status, and any U of I counsel guidance on AI in hiring.
8. Contents of the AITS "AI guidelines for safe use" and the GenAI Solutions Hub procurement pathway for AI vendors.
