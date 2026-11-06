"""Generate fictional higher-ed IT history and an offline role evolution explorer.

No PDF/person data is read. The source chart inspired broad functions only.
All histories, tools, metrics, identities and recommendations are simulated.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'data' / 'synthetic'
YEARS = [2023, 2025, 2026]

# Each trajectory is invented. These labels are not assertions about AITS titles.
# team, old title, middle title, present scenario title, old tools, new tools,
# old duty, new duty, skills, intervention, proof-of-learning, recommendation test
TRACKS = [
('Infrastructure & Reliability','Server Administrator','Hybrid Infrastructure Engineer','Platform Reliability Engineer',
 'Manual runbooks; vSphere','Terraform; Azure; OpenTelemetry','Provision servers from tickets','Maintain reproducible environments and service reliability',
 ['Infrastructure as code','Observability','Incident learning'],'Azure Administrator Associate, if Azure is the selected stack',
 'Rebuild a test environment from code and demonstrate recovery','Measure deployment lead time and restore success, not certification count'),
('Infrastructure & Reliability','Backup Operator','Recovery Engineer','Resilience Engineer',
 'Backup console; spreadsheets','Immutable backups; recovery automation','Check scheduled backup jobs','Validate end-to-end recovery of critical university services',
 ['Recovery testing','Dependency mapping','Risk analysis'],'Recovery tabletop and hands-on restoration lab',
 'Restore a synthetic finance service against a defined recovery objective','Retain incident accountability; test recovery dependencies before changing staffing'),
('Infrastructure & Reliability','Network Support Analyst','Cloud Network Engineer','Cloud Network Engineer',
 'CLI; ticket queue','Network automation; policy as code','Resolve individual connectivity tickets','Test network policy changes across hybrid services',
 ['Network automation','Policy testing','Cloud networking'],'Cloud networking lab matched to the actual provider',
 'Build automated policy tests and a rollback plan','Same 2025/2026 title with changed duties: title-only monitoring must miss this'),
('Enterprise Applications','Application Support Analyst','Enterprise Application Analyst','Enterprise Application Product Specialist',
 'Email; vendor manuals','Service catalog; release testing; product backlog','Resolve ERP support requests','Own service outcomes and evaluate vendor feature changes',
 ['Product discovery','ERP domain knowledge','Release risk'],'Vendor learning plus a service ownership practicum',
 'Map a payroll release to affected workflows and regression tests','Do not infer tool expertise from a generic ERP title'),
('Enterprise Applications','Batch Scheduler','Production Operations Engineer','Production Operations Engineer',
 'Scheduler console; shell scripts','Workflow orchestration; lineage; alert routing','Restart failed scheduled jobs','Improve dependency-aware recovery and reliable data delivery',
 ['Orchestration','Dependency analysis','Operational SQL'],'Orchestration and incident simulation lab',
 'Recover a failed synthetic payroll feed without duplicate processing','A legacy platform can remain business-critical; do not label its operator obsolete'),
('Enterprise Applications','Access Request Processor','Identity Operations Analyst','Identity Governance Analyst',
 'Forms; manual approvals','Entra ID; access reviews; policy workflows','Process account-access requests','Review least-privilege access and automate standard provisioning',
 ['Identity lifecycle','Access governance','Audit evidence'],'Identity lifecycle and access-review lab',
 'Demonstrate joiner/mover/leaver controls with a synthetic identity','Automation suggestions must preserve segregation of duties'),
('Software & Experience','ColdFusion Developer','Legacy Application Engineer','Application Modernization Engineer',
 'ColdFusion; manual deployments','APIs; automated tests; CI/CD','Maintain departmental web forms','Modernize selected workflows while preserving legacy service continuity',
 ['API design','Automated testing','Migration planning'],'API and migration testing practicum',
 'Expose a tested API around one legacy process with a rollback path','Retain legacy expertise until the replacement passes acceptance tests'),
('Software & Experience','Quality Assurance Tester','Test Automation Engineer','Quality Engineering Specialist',
 'Manual test cases; spreadsheets','Playwright; CI pipelines; accessibility testing','Execute manual regression scripts','Design risk-based automated and human review coverage',
 ['Test design','Accessibility','AI output evaluation'],'Quality engineering and accessibility assessment',
 'Catch a seeded payroll rounding defect and an inaccessible interaction','AI-generated tests do not establish coverage; measure escaped defects'),
('Software & Experience','Web Designer','UX Designer','Service Experience Designer',
 'Page mockups; style guides','Journey mapping; usability testing; design systems','Design individual web pages','Improve end-to-end employee and student service journeys',
 ['User research','Service design','Accessible interaction'],'Accessible service-design workshop',
 'Validate a redesigned workflow with representative users','Keep usability findings distinct from traffic metrics'),
('Data Platforms & Integration','ETL Developer','Data Engineer','Data Product Engineer',
 'Nightly ETL; shared folders','SQL; contracts; lineage; lakehouse or warehouse','Move source extracts into reporting tables','Own tested data products with explicit service expectations',
 ['Data contracts','Incremental loading','Lineage'],'Databricks Data Engineer Associate only if Databricks is selected; otherwise stack-aligned labs',
 'Deliver a restartable pipeline that rejects schema drift','Do not recommend both vendor certifications simply because both appear in this demo'),
('Data Platforms & Integration','Integration Analyst','API Integration Analyst','Integration Reliability Specialist',
 'Flat files; email mappings','API contracts; contract tests; tracing','Document point-to-point field mappings','Manage cross-system contracts and prevent breaking changes',
 ['Contract testing','API lifecycle','Data semantics'],'Consumer-driven contract-testing lab',
 'Detect a simulated change to an HR status code before downstream failure','Measure mapping disputes and failed changes before consolidating team ownership'),
('Data Platforms & Integration','Database Administrator','Database Platform Engineer','Database Platform Engineer',
 'Manual SQL scripts; capacity spreadsheets','Automated maintenance; access policy; telemetry','Administer databases and troubleshoot queries','Provide governed database services with repeatable changes',
 ['Database reliability','Cost analysis','Access policy'],'Database performance and governance practicum',
 'Improve a workload with repeatable benchmarks and validated permissions','Do not replace critical tuning and recovery duties with generic AI training'),
('Analytics & Decision Support','Report Writer','BI Developer','Analytics Engineer',
 'Spreadsheet extracts; fixed reports','SQL models; semantic layer; Power BI','Deliver recurring static reports','Maintain tested metrics and reusable analytical models',
 ['Metric design','Dimensional modeling','Semantic governance'],'Power BI Data Analyst Associate if Power BI delivery is in scope',
 'Reconcile FTE and headcount definitions across two synthetic reports','A title update without new responsibilities is cosmetic; require artifacts'),
('Analytics & Decision Support','Decision Support Analyst','Decision Support Analyst','Decision Support Analyst',
 'Spreadsheet comparisons; descriptive charts','Causal diagrams; forecast backtests; decision logs','Summarize historical measures','Evaluate interventions and separate uncertainty from evidence',
 ['Experimental design','Forecast evaluation','Stakeholder framing'],'Applied evaluation and forecasting practicum',
 'Beat a seasonal baseline or explicitly report failure to improve it','Same title in every snapshot; changing work is detectable only through duty evidence'),
('Analytics & Decision Support','Data Scientist','Applied Data Scientist','Workforce Intelligence Scientist',
 'Ad hoc notebooks; one-time models','Versioned evidence; evaluation sets; model tracking','Build isolated predictive prototypes','Validate workforce hypotheses and maintain auditable evidence',
 ['Temporal validation','Entity resolution','Model monitoring'],'Workforce model validation and evidence-engineering lab',
 'Detect a future-data leak and reject a weak employee-risk inference','No employee replacement scores; recommendations target role/process improvements'),
('Process & Portfolio','Business Process Analyst','Process Improvement Analyst','Service Optimization Analyst',
 'Interviews; flowcharts','Event logs; process models; controlled experiments','Document handoffs and approval steps','Test bottleneck hypotheses against service event data',
 ['Process measurement','Queue analysis','Control design'],'Process analysis practicum with synthetic event logs',
 'Separate waiting time from handling time and recommend a measured pilot','Removing an approval can break a control; retain accountable owners'),
('Process & Portfolio','Project Coordinator','Project Manager','Technology Delivery Lead',
 'Status slides; task lists','Portfolio metrics; dependency board','Track task completion and project status','Manage delivery dependencies and measurable service outcomes',
 ['Portfolio prioritization','Dependency management','Benefits tracking'],'Delivery and benefits-realization workshop',
 'Demonstrate a decision that changes prioritization using documented capacity','Do not score productivity using messages or meeting counts'),
('Process & Portfolio','Records Clerk','Records Management Analyst','Information Lifecycle Specialist',
 'File shares; manual retention lists','Retention labels; classification workflow','File records and maintain retention lists','Design information lifecycle controls for digital and AI workflows',
 ['Records retention','Information classification','Evidence stewardship'],'Records and information-governance practicum',
 'Apply a retention rule without deleting records under hold','Policy interpretation still needs a qualified records owner'),
('Service Enablement','Help Desk Technician','Service Desk Analyst','Knowledge & Service Automation Analyst',
 'Ticket macros; static FAQ','Knowledge retrieval; service workflows; human escalation','Answer repetitive support questions','Maintain reliable knowledge and safely automate standard requests',
 ['Knowledge quality','Intent analysis','Escalation design'],'Knowledge engineering and support evaluation lab',
 'Reject an unsafe answer and route a novel access request to an owner','Measure resolution quality and reopened tickets, not deflection alone'),
('Service Enablement','Training Coordinator','Digital Adoption Specialist','Digital Adoption Specialist',
 'Course attendance sheets','Skills demonstrations; adoption analytics','Schedule tool training and track attendance','Validate job-specific adoption and retained capability',
 ['Learning assessment','Change management','Accessible training'],'Role-based adoption and assessment workshop',
 'Show a learner can complete an actual task after training','Completion and certification are not observed job competence'),
('Service Enablement','Technical Writer','Knowledge Designer','Knowledge Operations Specialist',
 'PDF manuals; shared documents','Versioned runbooks; evidence links; retrieval tests','Write manuals after implementation','Maintain change-linked operational knowledge and retrieval quality',
 ['Technical communication','Knowledge lifecycle','Retrieval evaluation'],'Documentation-as-code and retrieval testing lab',
 'Retire a stale answer and verify citations after a procedure update','A knowledge agent must not repeat superseded procedures'),
('IT Business Operations','Administrative Assistant','Business Operations Coordinator','IT Business Operations Analyst',
 'Email requests; spreadsheets','Intake workflow; purchasing controls','Coordinate schedules and routine requests','Improve purchasing intake and reconcile operational exceptions',
 ['Procurement controls','Exception handling','Process analysis'],'Purchasing-intake and reconciliation practicum',
 'Reduce incomplete requests without bypassing purchasing controls','Routine administrative work can transform without eliminating the role'),
('IT Business Operations','Budget Analyst','Technology Financial Analyst','Technology Financial Analyst',
 'Annual budget workbook','Service cost allocation; usage reporting','Prepare annual IT budget spreadsheets','Analyze service cost drivers and evaluate sourcing scenarios',
 ['Cost allocation','Scenario analysis','Vendor economics'],'Technology service costing workshop',
 'Compare costs including labor, migration and support rather than compute alone','Cloud savings are a hypothesis until total costs are measured'),
('IT Business Operations','HR Liaison','Workforce Development Partner','Workforce Capability Partner',
 'Title lists; annual training plans','Role evidence; skills rubric; development plans','Coordinate staffing paperwork and training requests','Translate service plans into role development investments',
 ['Role design','Skills validation','Workforce planning'],'Role-design and assessment calibration workshop',
 'Link a proposed training investment to a service need and validation task','Do not infer individual proficiency or protected traits from a title'),
]


def dump(name, rows):
    (OUT / name).write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows), encoding='utf-8')


def build():
    OUT.mkdir(parents=True, exist_ok=True)
    positions, states, people, observations, recommendations = [], [], [], [], []
    teams = list(dict.fromkeys(t[0] for t in TRACKS))
    # Fictional topology and sizes: not a renamed one-to-one copy of the source.
    positions.append({'position_id':'D000','team':'Strategy','reports_to':None,'kind':'executive'})
    for i, team in enumerate(teams, 1):
        positions.append({'position_id':f'D{i:02}L','team':team,'reports_to':'D000','kind':'team_lead'})
    for n, track in enumerate(TRACKS):
        team, old, middle, current, oldtools, newtools, oldduty, newduty, skills, training, proof, test = track
        for replica in range(2):
            pid = f'D{n:02}{replica+1}'
            positions.append({'position_id':pid,'team':team,'reports_to':f'D{teams.index(team)+1:02}L','kind':'specialist'})
            for year in YEARS:
                title = {2023:old,2025:middle,2026:current}[year]
                modern = year == 2026
                state = {'position_id':pid,'team':team,'year':year,'title':title,
                         'tools':newtools if modern else oldtools,
                         'duties':newduty if modern else oldduty,
                         'skills':skills if modern else ['Domain support','Documentation'],
                         'evidence_id':f'SYN-{pid}-{year}','evidence_type':'synthetic_scenario',
                         'training':training,'proof_of_learning':proof}
                states.append(state)
            recommendations.append({'recommendation_id':f'REC-{pid}','position_id':pid,'team':team,
                 'type':'role_development','status':'illustrative_proposal','suggestion':training,
                 'evidence_ids':[f'SYN-{pid}-2025',f'SYN-{pid}-2026'],
                 'validation_task':proof,'decision_test':test,
                 'missing_evidence':['Actual service workload','Verified tool inventory','Observed skill assessment','Manager review'],
                 'expected_benefit':'Hypothesis only; not quantified','owner':'Fictional team lead'})
    first_names = ['Avery','Rowan','Morgan','Quinn','Sage','Reese','Emery','Parker','Skyler',
                   'Hayden','Finley','River','Arden','Ellis','Remy','Blair','Lane','Shiloh','Drew']
    for person_index, p in enumerate(positions):
        person_key = 'SYN-PERSON-' + p['position_id']
        people.append({'person_key':person_key,'display_name':first_names[person_index % 19] + ' ' + ['DemoVale','DemoBrook','DemoHaven'][person_index // 19],
                       'synthetic':True,'position_id':p['position_id']})
        if p['kind'] != 'specialist':
            for year in YEARS:
                states.append({'position_id':p['position_id'],'team':p['team'],'year':year,
                 'title':'Chief Shared IT Officer' if p['kind']=='executive' else p['team']+' Lead',
                 'tools':'Service portfolio; decision log','duties':'Own service priorities and review changes',
                 'skills':['Service leadership'],'evidence_id':f"SYN-{p['position_id']}-{year}",
                 'evidence_type':'synthetic_scenario','training':'Service leadership workshop',
                 'proof_of_learning':'Validate a prioritized service improvement'})
    for s in states:
        p = next(p for p in positions if p['position_id']==s['position_id'])
        observations.append({'kind':'appointment','source_system':'synthetic_demo_v1',
          'source_record_id':s['evidence_id'],'observed_on':f"{s['year']}-10-01",
          'institution_id':'DEMO_UNIVERSITY_SHARED_IT','position_id':s['position_id'],
          'person_key':'SYN-PERSON-'+s['position_id'],'unit_id':s['team'],'title':s['title'],
          'duties':s['duties'],'reports_to_position_id':p['reports_to'],'fte':1.0,
          'effective_from':f"{s['year']}-10-01",'synthetic':True,
          'source_locator':s['evidence_id'],'tools':s['tools'],'skills':s['skills']})
    dump('positions.jsonl',positions);dump('people.jsonl',people);dump('role_versions.jsonl',states)
    dump('observations.jsonl',observations);dump('recommendations.jsonl',recommendations)
    latest = [r for r in states if r['year']==2026]
    previous = {r['position_id']:r for r in states if r['year']==2025}
    renamed=sum(r['title']!=previous[r['position_id']]['title'] for r in latest)
    silent=sum(r['title']==previous[r['position_id']]['title'] and r['duties']!=previous[r['position_id']]['duties'] for r in latest)
    summary={'synthetic':True,'organization':'Demo University Shared IT',
      'positions_per_snapshot':len(positions),'people':len(people),'role_versions':len(states),
      'recommendations':len(recommendations),'renamed_positions_2025_to_2026':renamed,
      'same_title_changed_duties_2025_to_2026':silent,
      'warning':'All people, tools, histories, staffing and recommendations are fictional. No inferred employee assessment or measured market trends.',
      'source_use':'Broad functional inspiration only. No source names, person mapping, original topology or FTE totals reproduced.',
      'agent_status':'Design contracts only; recommendation generator is deterministic, not an autonomous agent.'}
    (OUT/'manifest.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    assert len({p['position_id'] for p in positions})==len(positions)
    assert len({p['person_key'] for p in people})==len(people)
    ids={p['position_id'] for p in positions}
    assert all(p['reports_to'] is None or p['reports_to'] in ids for p in positions)
    assert len(states)==len(positions)*len(YEARS)
    assert renamed and silent
    print(json.dumps(summary,indent=2))
    return summary


if __name__=='__main__':
    build()
