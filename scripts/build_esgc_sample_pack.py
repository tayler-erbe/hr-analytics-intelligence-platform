"""Package existing synthetic generators into sample datasets for the ESGC scope.

Requires an inspected checkout of the newer workforce repository and its generator
dependencies. Never connects to EDW, loads credentials or reads real employee rows.
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def write_json(path, obj):
    path.write_text(json.dumps(obj, indent=2, default=str)+'\n', encoding='utf-8')


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--source-root',type=Path,default=ROOT/'data/local/sample-source/platform-evaluation')
    ap.add_argument('--out',type=Path,default=ROOT/'data/local/esgc_sample_pack')
    ap.add_argument('--dependency-dir',type=Path,default=ROOT/'data/local/sample-python')
    ap.add_argument('--seed',type=int,default=20261106)
    ap.add_argument('--quality-people',type=int,default=1500)
    ap.add_argument('--history-scale',type=float,default=.2)
    args=ap.parse_args()
    if args.quality_people<1500 or not 0<args.history_scale<=2:
        raise ValueError('The full defect suite needs at least 1500 quality-test people; use a history scale in (0,2].')
    source=args.source_root.resolve();out=args.out.resolve()
    if (out/'pack_manifest.json').exists():
        raise FileExistsError('Preserve the existing pack; choose another --out directory for a new build.')
    for relative in ['succession_models/synth_edw.py','erp_readiness/generate_synthetic.py']:
        if not (source/relative).is_file():raise FileNotFoundError(source/relative)
    if args.dependency_dir.exists():sys.path.insert(0,str(args.dependency_dir.resolve()))
    import pyarrow.parquet as pq
    import duckdb
    env=os.environ.copy()
    env['PYTHONPATH']=os.pathsep.join([str(args.dependency_dir.resolve()),env.get('PYTHONPATH','')])
    env['PYTHONIOENCODING']='utf-8'
    out.mkdir(parents=True,exist_ok=True)
    def run(command):
        result=subprocess.run(command,cwd=source,env=env,text=True,encoding='utf-8',capture_output=True)
        with (out/'generation.log').open('a',encoding='utf-8') as log:
            log.write(result.stdout+result.stderr)
        if result.returncode:
            print(result.stderr)
            raise subprocess.CalledProcessError(result.returncode,command)
        print(result.stdout.strip(),flush=True)
    for label,defects in [('CLEAN',0),('DEFECTS',1)]:
        run([sys.executable,str(source/'erp_readiness/generate_synthetic.py'),
           '--label',label,'--defect-scale',str(defects),'--n-persons',str(args.quality_people),
           '--seed',str(args.seed),'--out-root',str(out/'quality')])
    run([sys.executable,str(source/'succession_models/synth_edw.py'),
       '--scale',str(args.history_scale),'--seed',str(args.seed),'--out',str(out/'longitudinal')])
    # Preserve exact generator outputs. Export JSONL copies for simple inspection.
    inventories=[]
    for dataset in [out/'quality/CLEAN',out/'quality/DEFECTS',out/'longitudinal']:
        schema={};con=duckdb.connect(str(dataset/'sample.duckdb'))
        for path in sorted(dataset.glob('*.parquet')):
            table=pq.read_table(path);name=path.stem
            schema[name]=[{'name':f.name,'type':str(f.type),'status':'synthetic layout assumption; not EDW-verified'} for f in table.schema]
            dest=dataset/f'{name}.jsonl'
            with dest.open('w',encoding='utf-8') as stream:
                for batch in table.to_batches(max_chunksize=5000):
                    for row in batch.to_pylist():stream.write(json.dumps(row,default=str,sort_keys=True)+'\n')
            con.register('source_table',table)
            con.execute(f'CREATE TABLE "{name}" AS SELECT * FROM source_table')
            inventories.append({'dataset':str(dataset.relative_to(out)).replace('\\','/'),'table':name,'rows':table.num_rows})
        # Current employee view is derived locally, not a discovered real EDW view.
        if dataset.name=='longitudinal':
            con.execute('''CREATE VIEW V_EMPEE_HIST_1 AS SELECT * FROM T_EMPEE_HIST
                WHERE EMPEE_EFF_DT <= DATE '2026-10-31'
                  AND EMPEE_EXP_DT >= DATE '2026-10-31'
                  AND ROW_REC_START_DT <= DATE '2026-10-31'
                  AND ROW_REC_END_DT > DATE '2026-10-31' ''')
        con.close();write_json(dataset/'schema_assumptions.json',schema)
    # Pin upstream code rather than silently claim compatibility with every branch.
    commit=subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'],text=True).strip()
    truth=json.loads((out/'longitudinal/truth.json').read_text())
    requirements={
      'synthetic':True,'edw_calibrated':False,'proposal_scope_hours':236,
      'sources_used':'Proposal requirements and existing synthetic generator contracts; no real EDW profiles.',
      'supported_sample_needs':['Effective-dated employment and appointment history','Role/class transitions',
       'Separations and retirement-coded events','Org and position relationships','FTE and pay ranges',
       'Late-recorded row versions','Clean-versus-defective quality examples','Role-family reference mapping'],
      'excluded_or_unverified':['Actual university field names and code domains','Real employment or demographic distributions',
       'Verified SURS participation or service credits','Employee skills/proficiency','JDX job descriptions','Learning records',
       'Real promotion labels','Causal retention effects','Power BI dashboards or model outputs'],
      'conventions':{'effective_end':'inclusive, generator assumption','recorded_end':'exclusive',
                     'open_end':'9999-12-31','current_view':'synthetic derived view only'},
      'interpretation':'Synthetic model results test implementation, not real employee behavior or real-data model accuracy.'}
    write_json(out/'scope_and_assumptions.json',requirements)
    write_json(out/'inventory.json',inventories)
    write_json(out/'generation_summary.json',{'synthetic':True,'source_commit':commit,
       'seed':args.seed,'quality_people':args.quality_people,'history_scale':args.history_scale,
       'longitudinal_events':truth['stats']})
    (out/'README.md').write_text('''# Synthetic workforce sample datasets

All people, identifiers, histories, compensation, organizations and demographic
attributes are invented. Public SUCSS codes/titles are reference labels only.
These data have NOT been calibrated against EDW. Physical layouts and code meanings
remain assumptions. The proposal documents and any internal links are not included.

## Three sets

- quality/CLEAN: coherent small workforce for joins, validation and reporting.
- quality/DEFECTS: same seeded source world plus deliberately planted defects.
  Its manifest lists injected cases; do not interpret them as real defect rates.
- longitudinal: multi-year bitemporal history for mobility, separation, vacancy,
  temporal validation and leakage tests. truth.json records the planted assumptions.

Each set has typed Parquet, JSONL copies, a DuckDB database and schema_assumptions.json.
The longitudinal database also defines a synthetic V_EMPEE_HIST_1 view at 2026-10-31.
Do not join the CLEAN, DEFECTS and longitudinal populations to one another: they are
separate worlds, and matching synthetic IDs do not establish a cross-world identity.

Start with inventory.json, scope_and_assumptions.json and generation_summary.json.
Use role/unit aggregate outputs for demonstrations; no individual employee scoring
is enabled by generating these files. Synthetic demographic columns belong in an
audit experiment, not automatically in predictive features.

This is structural and scenario ground truth only. Matching synthetic and actual
model conclusions is not guaranteed. A future approved metadata/profile exercise
must verify fields, temporal conventions, distributions and appropriate use.
''',encoding='utf-8')
    hashes=[]
    for p in sorted(out.rglob('*')):
        if p.is_file():hashes.append({'path':str(p.relative_to(out)).replace('\\','/'),
           'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
    write_json(out/'pack_manifest.json',{'synthetic':True,'version':'1.0','source_commit':commit,'files':hashes})
    archive=out.parent/(out.name+'.zip')
    if archive.exists():raise FileExistsError(archive)
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED) as z:
        for p in sorted(out.rglob('*')):
            if p.is_file():z.write(p,str(Path(out.name)/p.relative_to(out)))
    print(json.dumps({'folder':str(out),'archive':str(archive),'tables':len(inventories)}))


if __name__=='__main__':main()
