from __future__ import annotations

import hashlib,json,os,time,traceback
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT=Path(os.environ.get('THE_JOCKEY_RESEARCH_ROOT',Path.home()/'Downloads'/'THE-JOCKEY-RESEARCH'))
CORE=ROOT/'CORE';DATA=CORE/'data';REPORTS=CORE/'reports';CHECK=ROOT/'checkpoints';STAGING=CORE/'source_staging';CONTRACTS=CORE/'contracts'/'source_adapters';OUT=ROOT/'canonicalization'/'outbox';QUAR=ROOT/'canonicalization'/'quarantine'
BASE=DATA/'CORE-003B_historical_features.csv';STATE=CHECK/'staging_canonical_bridge_state.json';SUMMARY=REPORTS/'STAGING_CANONICAL_BRIDGE_summary.json';INTERVAL=max(300,int(os.environ.get('THE_JOCKEY_STAGING_BRIDGE_INTERVAL','1800')))
for p in (REPORTS,CHECK,OUT,QUAR):p.mkdir(parents=True,exist_ok=True)

def now():return datetime.now().astimezone().isoformat()
def writej(p,o):
 t=p.with_suffix(p.suffix+'.tmp');t.write_text(json.dumps(o,ensure_ascii=False,indent=2),encoding='utf-8');t.replace(p)
def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()
def lit(v):return "'"+str(v).replace("'","''")+"'"
def q(n):return '"'+str(n).replace('"','""')+'"'
def load_json(p):
 try:return json.loads(Path(p).read_text(encoding='utf-8-sig'))
 except Exception:return None
def contract_for(source_id):
 for p in CONTRACTS.glob('*.json'):
  x=load_json(p)
  if x and str(x.get('source_id') or p.stem)==source_id:return p,x
 return None,None
def active_source():
 try:
  from canonical_store import resolve_canonical_source
  return resolve_canonical_source(BASE)
 except Exception:return BASE if BASE.exists() else None
def base_columns(path):
 import duckdb
 con=duckdb.connect()
 try:return [r[0] for r in con.execute(f'DESCRIBE SELECT * FROM read_parquet({lit(path)})' if Path(path).suffix.lower()=='.parquet' else f'DESCRIBE SELECT * FROM read_csv_auto({lit(path)},header=true,sample_size=-1)').fetchall()]
 finally:con.close()
def source_expr(path):
 return f'read_parquet({lit(path)})' if Path(path).suffix.lower()=='.parquet' else f'read_csv_auto({lit(path)},header=true,sample_size=-1)'
def staging_files(root):return sorted(Path(root).glob('year=*/domain=*/*.parquet'))
def verify_manifest(root,manifest):
 issues=[];files=staging_files(root);part_meta={x.get('file'):x for x in manifest.get('parts',[]) if isinstance(x,dict)}
 if not files:issues.append('NO_STAGING_FILES')
 for p in files:
  rel=str(p.relative_to(root)).replace('\\','/')
  meta=part_meta.get(rel)
  if meta is None:issues.append(f'UNMANIFESTED:{rel}');continue
  if meta.get('sha256')!=sha(p):issues.append(f'SHA_MISMATCH:{rel}')
 return issues,files
def sql_literal(v):
 if v is None:return 'NULL'
 if isinstance(v,bool):return 'TRUE' if v else 'FALSE'
 if isinstance(v,(int,float)):return str(v)
 return lit(v)
def canonical_projection_sql(stage_expr,stage_cols,base_cols,contract):
 defaults=contract.get('defaults') or {};select=[];missing=[]
 for c in base_cols:
  if c in stage_cols:select.append(f'{q(c)} AS {q(c)}')
  elif c in defaults:select.append(f'{sql_literal(defaults[c])} AS {q(c)}')
  else:missing.append(c)
 if missing:raise ValueError('BASE_COLUMNS_UNSATISFIED:'+','.join(missing[:50]))
 return f"SELECT {', '.join(select)} FROM {stage_expr}"
def row_signature(cols,prefix=''):
 pieces=[]
 for c in cols:
  ref=f'{prefix}{q(c)}'
  pieces.append(f"coalesce(cast({ref} as varchar),'∅')")
 return "md5(concat_ws('¦',"+','.join(pieces)+'))'
def process_source(root):
 import duckdb
 manifest=load_json(root/'manifest.json') or {};source_id=str(manifest.get('source_id') or root.name)
 if manifest.get('status')!='READY':return {'source_id':source_id,'status':'SKIP','reason':'STAGING_NOT_READY'}
 issues,files=verify_manifest(root,manifest)
 if issues:return {'source_id':source_id,'status':'BLOCKED','reason':'|'.join(issues[:20])}
 cp,contract=contract_for(source_id)
 if not contract:return {'source_id':source_id,'status':'BLOCKED','reason':'CONTRACT_MISSING'}
 if contract.get('enabled') is not True or contract.get('rights_status') not in {'APPROVED','APPROVED_INTERNAL'}:return {'source_id':source_id,'status':'BLOCKED','reason':'CONTRACT_NOT_APPROVED'}
 active=active_source()
 if active is None or not Path(active).exists():return {'source_id':source_id,'status':'WAITING','reason':'ACTIVE_CANONICAL_MISSING'}
 base_cols=base_columns(active)
 glob=str((root/'year=*'/'domain=*'/'*.parquet')).replace('\\','/')
 stage=f'read_parquet({lit(glob)}, union_by_name=true)'
 con=duckdb.connect()
 try:
  stage_cols=[r[0] for r in con.execute(f'DESCRIBE SELECT * FROM {stage}').fetchall()]
  projected=canonical_projection_sql(stage,stage_cols,base_cols,contract)
  active_expr=source_expr(active);sig=row_signature(base_cols,'c.');bsig=row_signature(base_cols,'b.')
  con.execute(f'CREATE TEMP VIEW candidate AS {projected}')
  counts=con.execute(f'''SELECT
    count(*) FILTER (WHERE b.race_horse_id IS NULL) AS new_rows,
    count(*) FILTER (WHERE b.race_horse_id IS NOT NULL AND {sig}={bsig}) AS exact_duplicates,
    count(*) FILTER (WHERE b.race_horse_id IS NOT NULL AND {sig}<>{bsig}) AS conflicts,
    count(*) AS total_rows
    FROM candidate c LEFT JOIN {active_expr} b ON cast(b.race_horse_id as varchar)=cast(c.race_horse_id as varchar)''').fetchone()
  new_rows,dups,conflicts,total=[int(x or 0) for x in counts]
  token=hashlib.sha256((source_id+'|'+str(manifest.get('updated'))+'|'+str(total)).encode()).hexdigest()[:12]
  candidate_path=OUT/f'{source_id}__bridge__{token}.parquet';meta_path=candidate_path.with_suffix('.json');conflict_path=QUAR/f'{source_id}__conflicts__{token}.parquet'
  if new_rows and not candidate_path.exists():
   con.execute(f'''COPY (SELECT c.* FROM candidate c LEFT JOIN {active_expr} b ON cast(b.race_horse_id as varchar)=cast(c.race_horse_id as varchar) WHERE b.race_horse_id IS NULL) TO {lit(candidate_path)} (FORMAT PARQUET,COMPRESSION ZSTD)''')
  if conflicts and not conflict_path.exists():
   con.execute(f'''COPY (SELECT c.* FROM candidate c JOIN {active_expr} b ON cast(b.race_horse_id as varchar)=cast(c.race_horse_id as varchar) WHERE {sig}<>{bsig}) TO {lit(conflict_path)} (FORMAT PARQUET,COMPRESSION ZSTD)''')
  result={'source_id':source_id,'status':'READY' if new_rows else ('CONFLICT' if conflicts else 'NOOP'),'staged_rows':total,'new_rows':new_rows,'exact_duplicates':dups,'conflicts':conflicts,'candidate':str(candidate_path) if new_rows else None,'candidate_sha256':sha(candidate_path) if new_rows else None,'conflict_artifact':str(conflict_path) if conflicts else None,'contract':str(cp),'active_canonical':str(active),'policy':'new-only candidate; exact duplicates ignored; conflicting existing IDs quarantined; no overwrite'}
  if new_rows:writej(meta_path,{**result,'created_at':now()})
  return result
 finally:con.close()
def run_once():
 results=[]
 for root in sorted(STAGING.iterdir()) if STAGING.exists() else []:
  if root.is_dir():results.append(process_source(root))
 blocked=sum(x.get('status')=='BLOCKED' for x in results);conflicts=sum(int(x.get('conflicts') or 0) for x in results);new=sum(int(x.get('new_rows') or 0) for x in results)
 status='BLOCKED' if blocked else ('WARN' if conflicts else ('PASS' if results else 'WAITING'))
 out={'pid':os.getpid(),'updated':now(),'status':status,'sources':len(results),'new_rows':new,'conflicts':conflicts,'blocked_sources':blocked,'results':results,'policy':'classify staged rows before reconciliation; only novel IDs become canonical candidates; existing conflicting IDs never auto-overwrite'}
 writej(SUMMARY,out);writej(STATE,out);return out
def main():
 while True:
  try:run_once()
  except Exception:
   writej(STATE,{'pid':os.getpid(),'updated':now(),'status':'BLOCKED','detail':traceback.format_exc()[-1800:]})
  time.sleep(INTERVAL)
if __name__=='__main__':main()
