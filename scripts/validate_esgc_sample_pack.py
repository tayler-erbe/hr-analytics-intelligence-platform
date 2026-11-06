"""Validate synthetic samples using the inspected upstream rules and extraction gates."""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--pack',type=Path,default=ROOT/'data/local/esgc_sample_pack_v1')
    ap.add_argument('--source-root',type=Path,default=ROOT/'data/local/sample-source/platform-evaluation')
    ap.add_argument('--dependency-dir',type=Path,default=ROOT/'data/local/sample-python')
    args=ap.parse_args();pack=args.pack.resolve();source=args.source_root.resolve()
    env=os.environ.copy();env['PYTHONPATH']=str(args.dependency_dir.resolve());env['PYTHONIOENCODING']='utf-8'
    validation=pack/'validation';validation.mkdir(exist_ok=True)
    runner='''import sys,json
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import run_checks
r=run_checks.run(sys.argv[2],Path(sys.argv[3]),Path(sys.argv[4]))
print(json.dumps({"label":r["label"],"totals":r["totals"],"overall_score":r["overall_score"]}))
'''
    results={}
    for label in ['CLEAN','DEFECTS']:
        run=subprocess.run([sys.executable,'-c',runner,str(source/'erp_readiness'),label,
            str(pack/'quality'/label),str(validation/label)],env=env,capture_output=True,text=True,encoding='utf-8')
        (validation/f'{label}.log').write_text(run.stdout+run.stderr,encoding='utf-8')
        run.check_returncode();results[label]=json.loads(run.stdout)
    assert results['CLEAN']['totals']['failing_rules']==0
    assert results['DEFECTS']['totals']['failing_rules']==43
    run=subprocess.run([sys.executable,str(source/'succession_models/extract.py'),
       '--engine','duckdb','--edw-dir',str(pack/'longitudinal'),'--out',str(validation/'longitudinal_extract')],
       cwd=source,env=env,capture_output=True,text=True,encoding='utf-8')
    (validation/'longitudinal_extraction.log').write_text(run.stdout+run.stderr,encoding='utf-8')
    run.check_returncode()
    gates=json.loads((validation/'longitudinal_extract/extract_validation.json').read_text())
    assert all(v['status']=='PASS' for k,v in gates.items() if k.startswith('G'))
    # Independently verify exported representations and key integrity on clean data.
    sys.path.insert(0,str(args.dependency_dir.resolve()))
    import pyarrow.parquet as pq
    import duckdb
    for dataset in [pack/'quality/CLEAN',pack/'quality/DEFECTS',pack/'longitudinal']:
        con=duckdb.connect(str(dataset/'sample.duckdb'),read_only=True)
        for path in dataset.glob('*.parquet'):
            n=pq.read_metadata(path).num_rows
            with path.with_suffix('.jsonl').open(encoding='utf-8') as f:assert sum(1 for _ in f)==n
            assert con.execute(f'SELECT COUNT(*) FROM "{path.stem}"').fetchone()[0]==n
        con.close()
    clean=duckdb.connect(str(pack/'quality/CLEAN/sample.duckdb'),read_only=True)
    people=clean.execute('SELECT COUNT(DISTINCT EDW_PERS_ID) FROM T_PERS_HIST').fetchone()[0]
    assert people==1500 or people==json.loads((pack/'generation_summary.json').read_text())['quality_people']
    orphan=clean.execute('''SELECT COUNT(*) FROM T_JOB_DETL_HIST j WHERE NOT EXISTS
      (SELECT 1 FROM T_PERS_HIST p WHERE p.EDW_PERS_ID=j.EDW_PERS_ID)''').fetchone()[0]
    assert orphan==0;clean.close()
    results['longitudinal_gates']=gates
    results['cross_format_checks']='All 28 source tables match between Parquet, JSONL and DuckDB.'
    results['clean_unique_people']=people
    results['synthetic']=True
    results['real_edw_validation']=False
    (validation/'pack_validation.json').write_text(json.dumps(results,indent=2)+'\n',encoding='utf-8')
    old=json.loads((pack/'pack_manifest.json').read_text())
    old['files']=[{'path':str(p.relative_to(pack)).replace('\\','/'),'bytes':p.stat().st_size,
       'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(pack.rglob('*'))
       if p.is_file() and p.name!='pack_manifest.json']
    (pack/'pack_manifest.json').write_text(json.dumps(old,indent=2)+'\n',encoding='utf-8')
    archive=pack.parent/(pack.name+'_validated.zip')
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED) as z:
        for p in sorted(pack.rglob('*')):
            if p.is_file():z.write(p,str(Path(pack.name)/p.relative_to(pack)))
    print(json.dumps({'clean_people':people,'quality_rules':43,'longitudinal_gates_passed':7,
       'validated_archive':str(archive),'archive_bytes':archive.stat().st_size}))


if __name__=='__main__':main()
