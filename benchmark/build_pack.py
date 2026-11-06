"""Build deterministic synthetic evaluation fixtures. Does not execute vendor tests."""
import hashlib
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent
FIX = HERE / 'fixtures'

CRITERIA = [
 ('I1','ERP ingestion','Source integration',5),('I2','ERP ingestion','Temporal/grain correctness',5),
 ('I3','ERP ingestion','Incremental recovery',5),('B1','Business definitions','Metric reconciliation',5),
 ('B2','Business definitions','Cross-domain joins',5),('B3','Business definitions','Traceability',5),
 ('A1','AI tools','Structured question accuracy',5),('A2','AI tools','Evidence and abstention',5),
 ('A3','AI tools','Controlled tools and context',5),('M1','Data science','Reproducible features',5),
 ('M2','Data science','Valid evaluation',5),('M3','Data science','Deployment/monitoring',5),
 ('D1','Dashboards','Initial authoring',5),('D2','Dashboards','Iterative change',5),
 ('D3','Dashboards','Faithful migration',5),('D4','Dashboards','Consumption/delivery',5),
 ('G1','Governance','Identity and row/column controls',5),('G2','Governance','Lineage/audit and AI boundaries',5),
 ('O1','Operations','Deployment/recovery',3),('O2','Operations','Independent handover',2),
 ('C1','Cost/exit','Measured operating cost',3),('C2','Cost/exit','Portability/recovery',2)]


def write_json(path, value):
    path.write_text(json.dumps(value,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')


def fixtures():
    return {
 'positions': [dict(position_id=f'POS{i}',department_id='T1' if i<3 else 'T2') for i in range(1,6)],
 'appointments': [
 dict(appointment_id='AP1',person_id='PERSON1',position_id='POS1',department_id='T1',title='Analyst',fte=.6,effective_from='2026-01-01',effective_to=None,recorded_on='2026-01-01',revision=1),
 dict(appointment_id='AP2',person_id='PERSON1',position_id='POS2',department_id='T1',title='Interim Lead',fte=.4,effective_from='2026-01-01',effective_to=None,recorded_on='2026-01-01',revision=1),
 dict(appointment_id='AP3',person_id='PERSON2',position_id='POS3',department_id='T1',title='Engineer',fte=1.,effective_from='2026-01-01',effective_to='2026-10-15',recorded_on='2026-01-01',revision=1),
 dict(appointment_id='AP3',person_id='PERSON2',position_id='POS3',department_id='T2',title='Engineer',fte=1.,effective_from='2026-10-15',effective_to=None,recorded_on='2026-10-16',revision=1),
 dict(appointment_id='AP4',person_id='PERSON3',position_id='POS4',department_id='T2',title='Coordinator',fte=.75,effective_from='2026-10-01',effective_to=None,recorded_on='2026-10-02',revision=1),
 dict(appointment_id='AP4',person_id='PERSON3',position_id='POS4',department_id='T2',title='Coordinator',fte=.5,effective_from='2026-10-01',effective_to=None,recorded_on='2026-11-01',revision=2)],
 'proposals': [dict(proposal_id='PR1',submitted_on='2026-06-30',requested_cents=10000000),dict(proposal_id='PR2',submitted_on='2026-07-01',requested_cents=20000000),dict(proposal_id='PR3',submitted_on='2026-09-01',requested_cents=5000000)],
 'investigators': [dict(proposal_id='PR1',investigator_id='INV1'),dict(proposal_id='PR2',investigator_id='INV1'),dict(proposal_id='PR2',investigator_id='INV2'),dict(proposal_id='PR3',investigator_id='INV3')],
 'awards': [dict(award_id='AW1',proposal_id='PR2',awarded_on='2026-08-01',original_cents=15000000),dict(award_id='AW2',proposal_id='PR3',awarded_on='2026-10-01',original_cents=4000000)],
 'amendments': [dict(amendment_id='AM1',award_id='AW1',change_cents=2500000),dict(amendment_id='AM2',award_id='AW1',change_cents=-500000),dict(amendment_id='AM3',award_id='AW2',change_cents=1000000)],
 'award_transactions': [dict(transaction_id=f'TX{i+1}',award_id=a,transaction_type=t,amount_cents=v) for i,(a,t,v) in enumerate([
 ('AW1','obligation',12000000),('AW1','obligation',2000000),('AW1','obligation',-1000000),('AW2','obligation',3000000),('AW1','expenditure',5000000),('AW2','expenditure',1500000)])],
 'expected_runs': [dict(run_id=f'RUN{i}',scheduled_on='2026-11-01',job_id='JOB1' if i<3 else 'JOB2') for i in range(1,5)],
 'job_attempts': [dict(attempt_id=f'ATT{i+1}',run_id=r,attempt_number=n,status=s,completed_at_utc=ts) for i,(r,n,s,ts) in enumerate([
 ('RUN1',1,'success','2026-11-01T18:00:00Z'),('RUN2',1,'failed','2026-11-01T23:50:00Z'),('RUN2',2,'success','2026-11-02T00:30:00Z'),('RUN3',1,'failed','2026-11-01T22:00:00Z'),('RUN3',2,'failed','2026-11-01T22:30:00Z')])],
 'external_role_context': [dict(occupation_code='DEMO-ONLY-1',title='Synthetic IT analyst context',release_date='2026-10-01',reference_year=2025,evidence_status='synthetic',note='No employment growth or displacement measure is provided.')],
 'ml_features': [dict(entity_id='TRAIN1',prediction_on='2026-09-01',feature_name='prior_failures',value=2,available_on='2026-08-31'),dict(entity_id='TRAIN1',prediction_on='2026-09-01',feature_name='next_month_resolution',value=1,available_on='2026-10-01')]
    }


def create_db(data, path):
    # Build only our generated local database; original project/server stores are untouched.
    con=sqlite3.connect(path)
    with con:
        for name, rows in data.items():
            con.execute(f'DROP TABLE IF EXISTS "{name}"')
            fields=list(rows[0])
            defs=[]
            for key in fields:
                vals=[r[key] for r in rows if r[key] is not None]
                kind='INTEGER' if vals and all(type(v) is int for v in vals) else 'REAL' if vals and all(type(v) in (int,float) for v in vals) else 'TEXT'
                defs.append(f'"{key}" {kind}')
            con.execute(f'CREATE TABLE "{name}" ('+','.join(defs)+')')
            con.executemany(f'INSERT INTO "{name}" VALUES ('+','.join('?' for _ in fields)+')',[[r[k] for k in fields] for r in rows])
        for view in ['workforce_current','workforce_as_known','workforce_totals','workforce_department','vacant_positions','fiscal_proposals','award_ceiling','transaction_totals','run_status','observed_run_failure']:
            con.execute(f'DROP VIEW IF EXISTS {view}')
        con.executescript((HERE/'reference.sql').read_text())
    return con


def main():
    FIX.mkdir(parents=True,exist_ok=True)
    data=fixtures()
    for name,rows in data.items():
        (FIX/f'{name}.jsonl').write_text(''.join(json.dumps(r,sort_keys=True)+'\n' for r in rows),encoding='utf-8')
    expected={
      'synthetic':True,'domain_owner_approval':'pending; fixture definitions only',
      'workforce_current':{'headcount':3,'appointments':4,'filled_positions':4,'fte':2.5},
      'workforce_as_known_fte':2.75,
      'department_totals':[{'department_id':'T1','headcount':1,'appointments':2,'fte':1.0},{'department_id':'T2','headcount':2,'appointments':2,'fte':1.5}],
      'vacant_positions':['POS5'],'fiscal_proposals':{'proposal_count':2,'requested_cents':25000000},
      'award_ceiling':{'AW1':17000000,'AW2':5000000},'award_ceiling_total_cents':22000000,
      'obligation_cents':16000000,'expenditure_cents':6500000,
      'job_runs':{'failed_runs':1,'observed_runs':3,'unknown_runs':1},
      'attempt_failure':{'failed_attempts':3,'attempts':5},
      'ml_allowed_features':['prior_failures'],'ml_rejected_features':['next_month_resolution']}
    write_json(HERE/'answer_keys.json',expected)
    score_dir=HERE/'scorecards';score_dir.mkdir(exist_ok=True)
    assert sum(c[3] for c in CRITERIA)==100
    for platform in ['snowflake','databricks','custom']:
        for track in ['platform_native','common_implementation']:
            path=score_dir/f'{platform}_{track}.json'
            if not path.exists():
                write_json(path,{'rubric_version':'1.0','benchmark_version':'1.0','platform':platform,'track':track,
                 'status':'not_tested','environment':None,'reviewer':None,'gate_results':{},
                 'criteria':[dict(criterion_id=i,category=c,criterion=n,weight=w,rating=None,evidence=[],limitations=None) for i,c,n,w in CRITERIA]})
    local=ROOT/'data'/'local';local.mkdir(parents=True,exist_ok=True)
    con=create_db(data,local/'benchmark_v1.sqlite');con.close()
    paths=sorted(FIX.glob('*.jsonl'))+[HERE/'reference.sql',HERE/'answer_keys.json',HERE/'cases.json',HERE/'documents.md',HERE/'README.md',HERE/'build_pack.py',HERE/'test_reference.py',HERE/'score_report.py',ROOT/'PLATFORM_EVALUATION_RUBRIC.md']
    for p in paths:
        if not p.exists(): raise FileNotFoundError(p)
    write_json(HERE/'manifest.json',{'benchmark_version':'1.0','rubric_version':'1.0','synthetic':True,
      'build_date':'2026-11-02','row_counts':{k:len(v) for k,v in data.items()},
      'files':[dict(path=str(p.relative_to(ROOT)).replace('\\','/'),sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in paths],
      'limitations':['Tiny functional fixture; not a performance or forecasting benchmark.','Case questions are public development examples; no unseen holdout exists yet.','No vendor tests executed.']})
    print('Built synthetic fixtures, reference DB, answer keys, and six unscored scorecards.')


if __name__=='__main__': main()
