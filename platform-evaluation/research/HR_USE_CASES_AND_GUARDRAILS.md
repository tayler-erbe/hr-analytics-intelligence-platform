# HR Analytics and AI Use Cases: University of Illinois System HR

**Research date:** 2026-11-06. Sources are web search results from that date. Items marked **[UNVERIFIED]** were not confirmed against a primary source, or the sources conflict. No institutional data was used.

## 0. Context and corrections

- **Who's who.** Public org charts list Luanne Mayorga as *Assistant Chancellor for Strategic Programs & Partnerships* within Illinois Human Resources (IHR). Her unit covers HR programs and services. She reports to Shari Mickey-Boggs, Senior Associate Chancellor for Human Resources. The search did not confirm the title "Assistant Chancellor for Illinois HR", so check it before using it in any material. ([IHR org chart](https://ihr-hub.illinois.edu/documents/org-charts/ihr-organzational-chart-accessible.html), [theorg.com profile, third-party](https://theorg.com/org/university-of-illinois-at-urbana-champaign/org-chart/luanne-mayorga), [Mickey-Boggs appointment](https://news.illinois.edu/mickey-boggs-selected-as-senior-associate-chancellor-for-human-resources/))
- **Data platform.** AITS Decision Support runs the Enterprise Data Warehouse (EDW). The EDW combines data from Banner (HR, finance, student) and other systems. Access goes through EDDIE, Web Intelligence and OLAP cubes, and Unit Security Contacts request it. AITS has an HR reports area. A current HR data mart was **not confirmed**. ([AITS reports & data](https://www.aits.uillinois.edu/services/reports_and_data_v2), [Decision Support](https://answers.uillinois.edu/41531), [EDW access](https://aits.uillinois.edu/access/data_warehouse_access), [AITS HR reports](https://www.aits.uillinois.edu/services/reports_and_data/reports/human_resources__hr_/))
- **ERP.** The System is planning to replace Banner with a cloud ERP. The options under review are Ellucian Cloud (hosted Banner), Workday and Oracle Cloud, and the System held Workday and Oracle demonstrations. A draft timeline dated Oct 27, 2025 gives the readiness phase 3–4 years. No vendor selection or go-live date was found as of this date. **[UNVERIFIED: current status]** ([uillinois.edu/erp](https://www.uillinois.edu/erp), [next steps](https://www.uillinois.edu/erp/nextsteps), [UIC Today](https://live.today.uic.edu/enterprise-resource-planning-modernization-what-this-means-for-us/), [UIS presidential message](https://www.uis.edu/news/faculty-orbit-campus-announcement-staff/message-president-killeen-announcing-erp-business-transformation-university-illinois-system))
- **Civil service (SUCSS).** SUCSS is still revising classification series; proposal notices were issued in June 2026. The University has long pushed for statutory reform, for example of the presumption that every position is civil service unless exempted, and of the Academic Professional exemption criteria (cf. IHR's Professional Employment Redesign). No enacted 2026 statutory reform was found. **[UNVERIFIED]** ([SUCSS CSN 3325](https://www.sucss.illinois.gov/documents/csn/3325.pdf), [SUCSS CSN 3326](https://sucss.illinois.gov/documents/csn/3326.pdf), [IHR classification revisions](https://answers.illinois.edu/ihr/158501), [PER](https://humanresources.illinois.edu/professional-empl-redesign-per/), [Senate PER deck 2018](https://senate.illinois.edu/2018-2019/20181112senate/20181112_IHR-PER.pdf))
- **SURS Tier 2.** The Tier II pensionable salary cap ($127,283.01) is below the Social Security wage base ($176,100). As a result, Tier 2 may fail the federal Safe Harbor test. As of Fall 2025 no legislative fix had been enacted, and SURS tests annually as a courtesy to employers. ([SURS Fall 2025 newsletter](https://surs.org/wp-content/uploads/SURS-Fall-2025-Newsletter.pdf), [UI SURS page](https://hr.uillinois.edu/benefits/retirement/surs))
- **State budget.** The FY27 budget was signed June 16, 2026. It holds MAP at $721.6M and continues increases for higher education. A University of Illinois line item was not confirmed. ([IBHE FY27 release](https://www.ibhe.org/PressReleases/2026/Press_Release_FY27_Gov_s_Higher_Education_Budget.pdf), [ISAC](https://isac.org/newsroom/isac-press-releases/2026-Press-Releases/fy27-gov-higher-education-budget), [UIS budget note](https://www.uis.edu/news/faculty-orbit-campus-announcement-staff/new-state-budget-provides-continued-support-higher-education))
- **Bargaining units.** Contracts are managed by IHR Labor & Employee Relations. Units include GEO Local 6300, AFSCME Locals 698 and 3700, the FOP Labor Council, and non-tenure-track (NTT) faculty and tenure-track faculty units. Presumptive unit rules are in 80 Ill. Adm. Code 1135. **[UNVERIFIED: complete current roster]** ([80 IAC 1135](https://my.ilga.gov/ftp/JCAR/AdminCode/080/080011350000200R.html), [AAUP on NTT union](https://www.aaup.org/article/new-faculty-union-university-illinois-urbana-champaign), [GEO](https://uiucgeo.org/ra-faq))
- **Peer and CUPA-HR signals.**
  - **Turnover:** CUPA-HR's September 2026 turnover report says turnover has eased from its post-pandemic peak, but non-exempt staff turnover is still above 2019. Part-time exempt staff have the highest voluntary turnover rate (~23.9%, from a search excerpt).
  - **Intent to leave:** In the 2025 Retention Survey, one in four employees say they are likely to job-search. Confidence in leadership ethics is now the second-largest predictor of retention.
  - **Aging workforce:** About one third of staff are 55 or older, concentrated in facilities, trades and clerical roles (2019 brief). ([CUPA-HR turnover 2026](https://www.cupahr.org/resource/turnover-in-the-higher-education-workforce/), [Retention 2025](https://www.cupahr.org/resource/higher-ed-employee-retention-survey-findings-september-2025/), [Aging workforce](https://www.cupahr.org/wp-content/uploads/The-Challenges-of-an-Aging-Higher-Ed-Workforce.pdf), [Pay equity 2024](https://www.cupahr.org/resource/representation-and-pay-equity-in-higher-ed-professionals-trends-july-2024/))
  - **Peer dashboards:** UC Berkeley's Cal Answers includes "Campus Workforce Planning" with a Staff Retirement Metrics dashboard. At launch it showed about 1 in 10 staff with a high likelihood of retirement. The UW System Workforce Dashboard, UC Systemwide HR analytics and Michigan HR Data & Analytics are also published. ([Cal Answers CWP](https://calanswers.berkeley.edu/training/dashboards-and-reports/campus-workforce-planning), [UW dashboard spec](https://search.data.wisc.edu/specifications/29717), [UC Davis HR data](https://www.hr.ucdavis.edu/data), [Michigan HR D&A](https://hr.umich.edu/node/106807))

## 1. Prioritized use cases (18)

Each use case lists the stakeholder (**S**), the decision it supports (**D**), the data needed (**Data**), the analytic method (**M**), risk and governance notes (**Risk**), and the horizon (**H**). Unless noted, "EDW" means Banner-sourced HR, payroll and position data in the AITS warehouse. Priority reflects value, feasibility on current data, and legal exposure.

1. **Turnover and retention baseline by employee class**
   - **S:** IHR leadership, college HR officers.
   - **D:** Where to target retention spend; which classes are bleeding.
   - **Data:** EDW job and separation history with reason codes, class (civil service, AP, faculty, GA), and unit. Public benchmark: CUPA-HR turnover.
   - **M:** Cohort survival curves and annualized voluntary-turnover rates, benchmarked against CUPA-HR's non-exempt and part-time exempt findings.
   - **Risk:** Descriptive only. Suppress small cells (n<10).
   - **H:** Quick win.

2. **Time-to-fill and hiring funnel**
   - **S:** Talent acquisition, hiring units.
   - **D:** Where civil service exam/register steps or approvals add delay.
   - **Data:** Applicant tracking system (PeopleAdmin/Jobs@Illinois **[UNVERIFIED]**), EDW hire dates, SUCSS exam data.
   - **M:** Stage-duration process mining, bottleneck ranking.
   - **Risk:** Funnel conversion by demographic group touches applicant data. Restrict access, and use for adverse-impact checks, not for decisions on individuals.
   - **H:** Quick win.

3. **Pay-equity audit (internal, privileged)**
   - **S:** IHR Compensation, Office of Access & Equity, University Counsel.
   - **D:** Remediation budget; which individuals or job families to review.
   - **Data:** EDW pay, job code, class, grade, hire date, time in title, and protected traits.
   - **M:** Multiple regression within comparable job groups; Oaxaca-Blinder decomposition; flag outliers for human review.
   - **Risk:** Run under attorney–client privilege. Results feed human compensation review, not automatic adjustments.
   - **H:** Medium term.

4. **Pay-transparency posting compliance**
   - **S:** Talent acquisition, Compensation.
   - **D:** Whether postings carry good-faith ranges and benefits as required by HB 3129 (Equal Pay Act amendment, effective Jan 1, 2025), and whether the five-year records exist.
   - **Data:** Posting text, salary-structure tables, and the budgeted rate from position records.
   - **M:** Rule-based extraction from postings. Check that each posted range brackets the actual offer, and flag "up to $X" style ranges.
   - **Risk:** Whether and how the Act applies to public employers is **[UNVERIFIED]**; confirm with Counsel. No individual data needs to leave HR.
   - **H:** Quick win.
   - Sources: [Littler](https://www.littler.com/news-analysis/asap/pay-transparency-bill-headed-illinois-governor), [Perkins Coie](https://perkinscoie.com/insights/update/illinois-pay-transparency-requirements-arrive), [Amundsen Davis on IDOL guidance](https://www.amundsendavislaw.com/labor-employment-law-update/illinois-department-of-labor-gives-long-awaited-guidance-on-january-1-2025-pay-transparency-requirements)

5. **Retirement-eligibility and succession exposure map** (Berkeley-style)
   - **S:** Deans, vice chancellors, Facilities & Services.
   - **D:** Where to fund overlap hires and knowledge transfer.
   - **Data:** EDW age and service, SURS tier (from the benefits feed), and position criticality ratings from units.
   - **M:** Eligibility projection by year using Tier 1 and Tier 2 rules; heat map by unit and job family.
   - **Risk:** Age is a protected class. Report only at aggregate level and never use it to target individuals for exit.
   - **H:** Quick win.

6. **SURS Tier 2 Safe Harbor exposure model**
   - **S:** System HR Benefits, CFO, Government Relations.
   - **D:** Size the FICA or make-up liability if Tier 2 fails Safe Harbor, to inform the advocacy position.
   - **Data:** EDW Tier 2 earnings distribution against the cap and wage base; public SURS figures.
   - **M:** Scenario model across cap-indexing options, e.g. the 90.5%-of-wage-base threshold cited by SURS.
   - **Risk:** Aggregate only. Coordinate with SURS.
   - **H:** Quick win analysis; the policy question is long term.

7. **Civil service classification "fit" and reclassification backlog**
   - **S:** IHR Classification, SUCSS liaison.
   - **D:** Which titles are overloaded or obsolete, and where to propose series revisions or AP exemptions.
   - **Data:** EDW class codes and incumbents; SUCSS class specifications (public); position descriptions.
   - **M:** Title-proliferation statistics. Use NLP similarity between position descriptions and class specs as a reviewer-assist ranking only.
   - **Risk:** Under HB 3773, using AI to influence classification, which sets pay and status, could count as AI-assisted employment decisions. Keep a human decision, record notice, and run bias testing.
   - **H:** Medium term.

8. **Compression and market-position analysis**
   - **S:** Compensation, college HR officers.
   - **D:** Equity-adjustment pools; mapping market ranges onto job families.
   - **Data:** EDW salaries; CUPA-HR survey data (licensed); BLS OEWS (public).
   - **M:** Compa-ratios; new-hire versus incumbent pay gaps by job family.
   - **Risk:** CUPA-HR licensing terms. Results interact with collective bargaining agreements, so coordinate with Labor Relations.
   - **H:** Quick win.

9. **Collective bargaining costing**
   - **S:** Labor & Employee Relations, Budget.
   - **D:** Cost of wage proposals and step changes during negotiations.
   - **Data:** EDW roster by bargaining unit, scheduled hours, step and grade.
   - **M:** Deterministic costing model with sensitivity bands.
   - **Risk:** Bargaining-strategy confidentiality; restrict access tightly.
   - **H:** Quick win, given the frequent negotiation cycles.

10. **Position control and vacancy hygiene**
    - **S:** Budget offices, HR operations.
    - **D:** Which vacant or funded positions to reclaim or repost.
    - **Data:** EDW positions, budgets, incumbents and requisitions.
    - **M:** Join vacant positions to open requisitions; age-of-vacancy report. Ohio State Wexner publishes a similar "vacant positions without requisitions" report.
    - **Risk:** Low.
    - **H:** Quick win, and it doubles as ERP preparation (see §2).
    - Source: [OSU Workday notes](https://hr.osu.edu/news/2017/02/20/hr-service-delivery-transitions-to-workday-enterprise-project/)

11. **Retention risk early-warning (aggregate first)**
    - **S:** IHR Strategic Programs, unit leaders.
    - **D:** Where to deploy stay interviews and manager development.
    - **Data:** EDW tenure, pay movement, manager changes and promotions; engagement survey (CUPA-HR retention-survey style).
    - **M:** Survival or gradient-boosted model reported only at unit level. Calibration and subgroup error audits are mandatory.
    - **Risk:** **High.** Individual "flight-risk" scores that affect assignments, raises or discipline are covered by HB 3773. Proxies such as ZIP code, commute distance, age-correlated tenure and leave usage must be excluded or tested. Prefer interventions at unit level.
    - **H:** Long term.

12. **Workforce cost forecasting for the state budget cycle**
    - **S:** System Budget, University Office of Governmental Relations.
    - **D:** Personnel cost requests and the impact of MAP and appropriation scenarios.
    - **Data:** EDW payroll by fund source; IBHE and state budget documents.
    - **M:** Time series plus scenario modelling of salary programmes and fringe benefits by fund.
    - **Risk:** Low.
    - **H:** Medium term.

13. **Remote/hybrid work arrangement inventory and outcomes**
    - **S:** IHR policy, Facilities, Tax/Payroll.
    - **D:** Policy renewal, space planning, and multi-state tax exposure.
    - **Data:** Remote-work agreements (often outside Banner), work-state on payroll, retention outcomes.
    - **M:** Descriptive and matched comparison of retention for hybrid versus onsite employees.
    - **Risk:** Remote arrangements correlate with disability accommodation and caregiving status; avoid inferring these.
    - **H:** Medium term.

14. **Onboarding and early-tenure attrition (first 12 months)**
    - **S:** Talent acquisition, units.
    - **D:** Fix onboarding where 0–12 month turnover spikes.
    - **Data:** EDW hire and separation records; onboarding survey.
    - **M:** First-year survival by job family and hiring channel.
    - **Risk:** Low with aggregation.
    - **H:** Quick win.

15. **Graduate assistant appointment and tuition-waiver accuracy**
    - **S:** Graduate College, GEO contract administration, Payroll.
    - **D:** Prevent waiver and FTE errors that trigger grievances.
    - **Data:** EDW assistantship appointments (FTE %), waiver records, contract thresholds.
    - **M:** Rule-based exception reports.
    - **Risk:** Contract interpretation questions go to Labor Relations. Wisconsin's 2025 Workday rollout drew union complaints about missing tuition waivers.
    - **H:** Quick win.
    - Source: [UAW 4121](https://uaw4121.org/workday-issues-wages-benefits-more/)

16. **HR service-desk and policy Q&A assistant (generative AI, internal)**
    - **S:** IHR service centre, employees.
    - **D:** Not an employment decision; it deflects routine questions on policy, benefits and SURS basics.
    - **Data:** Public policy pages, the Answers knowledge base, benefits guides. No personnel records.
    - **M:** Retrieval-augmented answers with citations; human escalation; logged evaluation set.
    - **Risk:** Must not answer eligibility, pay or discipline questions for a specific person. Use approved/on-prem inference for any internal content.
    - **H:** Medium term.

17. **Job-description drafting and bias-language check (assistive)**
    - **S:** Hiring managers, Classification.
    - **D:** Clearer, more inclusive postings that are consistent with class specifications.
    - **Data:** Class specifications, posting templates.
    - **M:** LLM drafting with a fixed checklist; Compensation verifies the pay range.
    - **Risk:** Moderate. Postings shape the applicant pool, which brings it near HB 3773's "recruitment" scope. Keep human authorship, log AI use, and run periodic adverse-impact review of applicant flow.
    - **H:** Quick win, with guardrails.

18. **AI-in-hiring inventory and adverse-impact monitoring programme**
    - **S:** IHR leadership, Counsel, Office of Access & Equity, CIO/Privacy.
    - **D:** Which vendor tools (ATS ranking, video interviews, assessments) are in use, whether notice is required, and whether they cause disparate impact.
    - **Data:** Vendor contracts and configuration; applicant flow by stage and group.
    - **M:** Tool registry; four-fifths ratio and statistical-significance tests per stage; vendor bias-audit attestations.
    - **Risk:** This is the compliance backbone for HB 3773 and the AI Video Interview Act.
    - **H:** Quick win to stand up; ongoing thereafter.

**Top five to start:** #18, #1, #10, #4 and #5. They are low-risk, run on existing EDW data, deliver legal or ERP-preparation value, and produce the foundations the riskier models (#3, #11) need.

## 2. ERP conversion data-quality work an engineer can do now

Peer lessons:
- **Penn:** Data conversion was "a huge issue"; the deeper problem was data that hadn't been kept up to date and needed cleanup. ([Penn ISC](https://isc.upenn.edu/node/122))
- **Richmond:** Converted Banner data into Workday four times during implementation. ([Richmond history](https://workday.richmond.edu/about/history/index.html))
- **UChicago:** Underestimated testing effort. ([Stanford HCM symposium deck](https://uit.stanford.edu/sites/default/files/2022/09/02/Human%20Capital%20Management%20Symposium%20Full%20Slide%20Deck.pdf))
- **University of Washington:** Program review warned that a big-bang cutover raises risk. ([UW TSB](https://ocio.wa.gov/sites/default/files/2022-12/UW_TSB%25202.11.16%2520FINAL%2520nn.pdf))
- **Ohio State:** Had to clean up positions retroactively after switching between position management and job management. HR and payroll went live Jan 3, 2021. ([OSU timeline](https://busfin.osu.edu/news/2020/05/12/revised-enterprise-project-timeline))
- **Wisconsin:** Went live with HR and payroll in mid-2025 (UW–Madison's cutover schedule shows July 2025 payroll dates). Unions reported pay, benefits and waiver errors afterwards. **[UNVERIFIED: union claims, no official error counts]** ([UW–Madison cutover](https://hr.wisc.edu/hr-guides/for-hr-professionals/transition-period-actions-for-payroll/))

Because Illinois is still 3+ years from deployment, this cleanup is the highest-leverage engineering work. It does not depend on which vendor is chosen.

1. **Job and position inventory and cleanup**
   - Profile every active and inactive position: orphaned positions with no incumbent and no budget, positions with multiple incumbents, mismatched FTE, and expired positions with active assignments.
   - Produce a "retire / merge / keep" worklist for unit owners.
   - Decide whether the target model is position management or job management **before** conversion. Ohio State's retroactive cleanup shows the cost of deciding late.

2. **Classification crosswalks**
   - Build versioned mapping tables:
     - Banner employee class (eclass) to target worker type
     - SUCSS class code to target job profile, with series, level and exam/register attributes kept as custom fields
     - AP and faculty titles to job families
     - Bargaining unit to union membership object
   - Every legacy code must map to exactly one target code or to an explicit "retire" decision. Unmapped codes fail the build.
   - Track SUCSS proposal notices as a change feed, since the class plan keeps moving.

3. **Effective-dated history validation**
   - Write tests on job, salary, labor-distribution and status records:
     - no overlapping effective ranges per person and position
     - no gaps for continuously employed people
     - end dates not before start dates
     - salary changes carry reason codes
     - leave and return pairs balance
     - terminations aren't followed by pay without a rehire
   - Decide and document the history-conversion horizon, for example full history versus N years plus summarized history. Pension and service-credit calculations (SURS) may need long service history.

4. **Reconciliation test harness**
   - Build automated, repeatable comparisons between legacy and target data for each mock conversion:
     - headcount by class, unit and bargaining unit
     - gross-to-net payroll parallel per employee, with a tolerance and an exceptions list (UChicago reported >99% pay accuracy, so set targets explicitly)
     - year-to-date earnings and deductions
     - benefit enrollments and SURS tier
     - leave balances
     - FTE and labor-distribution totals by grant or fund
   - Plan for at least four mock conversions (Richmond's experience). Trend defect counts across mocks.

5. **Master-data hygiene**
   - Find duplicate persons (same SSN or UIN under multiple IDs), invalid addresses, and work-state anomalies (remote employees outside Illinois).
   - Find missing supervisor links. These break approval routing in any cloud HCM.

6. **Report and extract inventory**
   - Catalogue the EDW and Banner HR reports and their consumers (Decision Support's EDDIE and WebI universes) so reporting continuity and downstream feeds are designed in from the start, not discovered at cutover.
   - Use the rationalisation to retire duplicate reports.

7. **Data ownership**
   - Assign a business data steward for each conversion object, and record their sign-off on every mock-conversion reconciliation.

## 3. Legal and ethical guardrails

1. **Illinois HB 3773** (Public Act 103-0804, amends the Illinois Human Rights Act; effective Jan 1, 2026)
   - It is a civil rights violation to use AI that has a discriminatory effect in recruitment, hiring, promotion, discharge, discipline, tenure or terms of employment.
   - Using ZIP code as a proxy for a protected class is explicitly barred. Commentators read the law to cover other proxies as well.
   - Notice to employees is required.
   - IDHR proposed notice rules on May 15, 2026 and withdrew them 18 days later. They had not been refiled as of late September 2026. **[UNVERIFIED: check the Illinois Register]**
   - Practical stance: give notice anyway, keep an AI tool registry, and test for disparate impact.
   - Sources: [DLA Piper](https://knowledge.dlapiper.com/dlapiperknowledge/globalemploymentlatestdevelopments/2024/Illinois-becomes-second-state-to-enact-AI-law-for-employers), [Morgan Lewis](https://morganlewis.com/pubs/2024/09/illinois-passes-new-law-to-address-ai-in-the-workplace), [Hunton](https://www.hunton.com/hunton-employment-labor-perspectives/illinois-enacts-new-law-regulating-employer-use-of-artificial-intelligence), [rulemaking status, practitioner blog](https://beancount.io/blog/2026/09/19/illinois-ai-hiring-law-hb3773-notice-discrimination-testing-guide)

2. **AI Video Interview Act** (820 ILCS 42)
   - Requires notice, an explanation of the AI and consent before AI analysis of a video interview.
   - Videos must be deleted within 30 days of a request.
   - Employers that rely *solely* on AI to select applicants for in-person interviews must report applicant demographics to DCEO annually.
   - Sources: [statute](https://law.justia.com/codes/illinois/chapter-820/act-820-ilcs-42/), [DCEO 2024 report](https://dceo.illinois.gov/content/dam/soi/en/web/dceo/aboutdceo/reportsrequiredbystatute/2024-ai-video-report.pdf)

3. **Biometric Information Privacy Act** (740 ILCS 14)
   - Covers timeclocks, face or voice analytics and identity verification. Requires written consent, a retention schedule and a destruction policy.
   - **[UNVERIFIED: not re-checked in this search; from background knowledge]**

4. **Illinois Equal Pay Act (pay transparency)**
   - Posted ranges must be good-faith, and benefits must be listed.
   - Pay scale, benefits and posting records must be kept for five years.
   - Penalties are reported as up to $10K per violation.
   - Public-employer applicability and the Equal Pay Registration Certificate (EPRC, private employers with 100+ staff) do **not** clearly apply to the University. **[UNVERIFIED: confirm with Counsel]**
   - Note: the "SB 3646" in the brief was not found; the posting law is **HB 3129**.

5. **Federal law**
   - Title VII disparate-impact doctrine and the Uniform Guidelines (four-fifths rule) apply to any selection tool, AI or not.
   - The ADA, ADEA and Equal Pay Act also apply.
   - FERPA applies to student employees and graduate assistant data.

6. **Collective bargaining**
   - New monitoring, scoring or AI tools that affect terms and conditions of employment may be mandatory subjects of bargaining under IELRA (Illinois Educational Labor Relations Act). Engage Labor Relations before deploying.
   - **[UNVERIFIED: legal judgment needed]**

7. **Civil service law (110 ILCS 70 / SUCSS rules)**
   - Analytics cannot change merit-based exam, register or classification outcomes. AI may only assist reviewers.

8. **Operating principles**
   - **Data handling:** Institutional HR data stays on approved university systems with local or on-prem inference. Only suppressed aggregates are published (n<10 suppression). No personnel data goes to public or consumer AI services.
   - **Human decisions:** Humans decide all employment actions. Model outputs are advisory and logged with the model version.
   - **Bias testing:** Test for adverse impact before and after deployment, by protected class and intersection. Document excluded proxies: ZIP code, commute distance, name, graduation year, leave patterns.
   - **Protocols:** Pre-register each analytic protocol with fixed metrics, thresholds and inclusion rules. Changes require a new labelled version. Keep all errors and edge cases; never drop them.
   - **Separation of duties:** No model grades another model's employment-related output without human review.
   - **Privilege:** Pay-equity and AI-impact studies run under counsel direction where appropriate.
   - **Transparency:** Publish an employee-facing AI-use notice and an inventory of tools that affect employment.
