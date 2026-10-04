from __future__ import annotations

import hashlib,json,os,time,traceback
from datetime import datetime
from pathlib import Path
import pandas as pd
try:
 from modern_contracts import validate_adapter_contract,validate_core003b_frame
except Exception:
 validate_adapter_contract=lambda x:([],'MANUAL_FALLBACK')
 validate_core003b_frame=lambda x:([],'MANUAL_FALLBACK')

ROOT=Path(os.environ.get('THE_JOCKEY_RESEARCH_ROOT',Path.home()/'Downloads'/'THE-JOCKEY-RESEARCH'))
CORE=ROOT/'CORE';DATA=CORE/'data';REPORTS=CORE/'reports';CHECK=ROOT/'checkpoints';LOG=ROOT/'logs'/'canonicalization_director.log'
CONTRACTS=CORE/'contracts'/'source_adapters';INBOX=ROOT/'canonicalization'/'inbox';OUT=ROOT/'canonicalization'/'outbox';BASE=DATA/'CORE-003B_historical_features.csv'
STATE=CHECK/'canonicalization_director_state.json';SUMMARY=REPORTS/'CANONICALIZATION_summary.json';LEDGER=REPORTS/'CANONICALIZATION_ledger.csv'
INTERVAL=max(120,int(os.environ.get('THE_JOCKEY_CANONICALIZATION_INTERVAL','600')))
REQUIRED={'race_id','race_horse_id','horse_id','race_date','race_scope_cd','label_win','label_top2','label_top3'}
for p in (CONTRACTS,INBOX,OUT,REPORTS,CHECK,LOG.parent):p.mkdir(parents=True,exist_ok=True)

def now():return datetime.now().astimezone().isoformat()
def writej(p,o):
 t=p.with_suffix(p.suffix+'.tmp');t.write_text(json.dumps(o,ensure_ascii=False,indent=2),encoding='utf-8');t.replace(p)
def log(s):
 line=f'[{now()}] {s}';print(line,flush=True)
 with LOG.open('a',encoding='utf-8') as f:f.write(line+'\n')
def state(status,detail='',extra=None):
 x={'pid':os.getpid(),'updated':now(),'status':status,'detail':detail}
 if extra:x.update(extra)
 writej(STATE,x)
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()
def base_columns():
 if not BASE.exists():return []
 return list(pd.read_csv(BASE,nrows=0).columns)
def contracts():
 out={}
 for p in CONTRACTS.glob('*.json'):
  try:
   x=json.loads(p.read_text(encoding='utf-8-sig'));sid=str(x.get('source_id') or p.stem);out[sid]=(p,x)
  except Exception:continue
 return out
def validate_contract(x,base_cols):
 issues=[];typed_issues,contract_engine=validate_adapter_contract(x);issues.extend(typed_issues)
 if not x.get('source_id'):issues.append('missing_source_id')
 if x.get('enabled') is not True:issues.append('not_enabled')
 m=x.get('column_map') or {};defaults=x.get('defaults') or {}
 if not isinstance(m,dict):issues.append('column_map_not_object');m={}
 targets=set(m.values())|set(defaults)
 if not REQUIRED.issubset(targets):issues.append('required_canonical_fields_not_mapped')
 if base_cols and not set(base_cols).issubset(targets):issues.append('core003b_columns_not_fully_mapped_or_defaulted')
 if x.get('domain') not in {'JRA','NAR','MIXED'}:issues.append('invalid_domain')
 if not x.get('provenance'):issues.append('missing_provenance')
 if x.get('rights_status') not in {'APPROVED_INTERNAL','APPROVED'}:issues.append('rights_not_approved')
 return issues,contract_engine
def canonicalize(path,contract,base_cols):
 issues,contract_engine=validate_contract(contract,base_cols)
 if issues:return None,issues,contract_engine,'NOT_RUN'
 src=pd.read_csv(path,low_memory=False);mapping=contract['column_map'];missing=[c for c in mapping if c not in src.columns]
 if missing:return None,[f'missing_source_columns:{missing[:20]}'],contract_engine,'NOT_RUN'
 df=src[list(mapping)].rename(columns=mapping).copy()
 for k,v in (contract.get('defaults') or {}).items():
  if k not in df:df[k]=v
 if base_cols:
  missing_base=[c for c in base_cols if c not in df]
  if missing_base:return None,[f'core003b_columns_missing_after_mapping:{missing_base[:30]}'],contract_engine,'NOT_RUN'
  df=df[base_cols].copy()
 if not REQUIRED.issubset(df.columns):return None,['canonical_required_missing'],contract_engine,'NOT_RUN'
 df['race_date']=pd.to_datetime(df.race_date,errors='coerce').dt.strftime('%Y-%m-%d')
 if df.race_date.isna().any():issues.append('invalid_race_date')
 scope=pd.to_numeric(df.race_scope_cd,errors='coerce')
 if (~scope.isin([1,2])).any():issues.append('invalid_race_scope_cd')
 if df.race_horse_id.isna().any() or df.race_horse_id.astype(str).duplicated().any():issues.append('invalid_or_duplicate_race_horse_id')
 for c in ['label_win','label_top2','label_top3']:
  y=pd.to_numeric(df[c],errors='coerce')
  if y.isna().any() or (~y.isin([0,1])).any():issues.append(f'invalid_{c}')
 if not issues:
  a=pd.to_numeric(df.label_win);b=pd.to_numeric(df.label_top2);c=pd.to_numeric(df.label_top3)
  if ((a>b)|(b>c)).any():issues.append('label_monotonicity_violation')
 data_issues,data_engine=validate_core003b_frame(df)
 issues.extend(data_issues)
 return (df if not issues else None),issues,contract_engine,data_engine
def append_ledger(rows):
 if rows:pd.DataFrame(rows).to_csv(LEDGER,mode='a',header=not LEDGER.exists(),index=False,encoding='utf-8-sig')
def run_once():
 base_cols=base_columns()
 if not base_cols:state('WAITING',f'CORE-003B schema unavailable: {BASE}');return {'status':'WAITING','updated':now(),'reason':'CORE003B_SCHEMA_UNAVAILABLE'}
 cs=contracts();rows=[]
 for p in sorted(INBOX.glob('*.csv')):
  side=p.with_suffix('.source.json')
  if not side.exists():rows.append({'updated':now(),'source':str(p),'status':'QUARANTINED','reason':'MISSING_SOURCE_DESCRIPTOR'});continue
  try:desc=json.loads(side.read_text(encoding='utf-8-sig'));sid=str(desc.get('source_id') or '')
  except Exception as e:rows.append({'updated':now(),'source':str(p),'status':'QUARANTINED','reason':f'BAD_SOURCE_DESCRIPTOR:{e!r}'});continue
  if sid not in cs:rows.append({'updated':now(),'source':str(p),'source_id':sid,'status':'QUARANTINED','reason':'UNREGISTERED_SOURCE'});continue
  cp,contract=cs[sid];df,issues,contract_engine,data_engine=canonicalize(p,contract,base_cols)
  if issues:rows.append({'updated':now(),'source':str(p),'source_id':sid,'status':'QUARANTINED','reason':'|'.join(map(str,issues)),'contract_engine':contract_engine,'data_contract_engine':data_engine});continue
  source_sig=sha(p);dest=OUT/f'{sid}__{source_sig[:12]}__canonical.csv';meta=dest.with_suffix('.json')
  if not dest.exists():
   tmp=dest.with_suffix('.tmp');df.to_csv(tmp,index=False,encoding='utf-8-sig');tmp.replace(dest)
   writej(meta,{'status':'CANONICAL_STAGED','created_at':now(),'source_id':sid,'source_file':str(p),'source_sha256':source_sig,'contract_file':str(cp),'contract_sha256':sha(cp),'core003b_schema_columns':len(base_cols),'rows':len(df),'races':int(df.race_id.nunique()),'contract_engine':contract_engine,'data_contract_engine':data_engine,'policy':'versioned staging only; exact CORE-003B column contract; reconciliation decides promotion'})
  rows.append({'updated':now(),'source':str(p),'source_id':sid,'status':'STAGED','rows':len(df),'races':int(df.race_id.nunique()),'output':str(dest),'contract_engine':contract_engine,'data_contract_engine':data_engine})
 append_ledger(rows);blocked=sum(r['status']=='QUARANTINED' for r in rows);staged=sum(r['status']=='STAGED' for r in rows)
 out={'updated':now(),'status':'WARN' if blocked else 'PASS','registered_contracts':len(cs),'core003b_schema_columns':len(base_cols),'staged':staged,'quarantined':blocked,'processed':rows,'policy':'Only registered + rights-approved + exact CORE-003B-compatible sources are staged. Pydantic/Pandera strengthen validation when installed; manual gates remain fallback.'}
 writej(SUMMARY,out);state(out['status'],'canonicalization scan complete',out);return out
def main():
 log('CANONICALIZATION DIRECTOR START')
 while True:
  try:run_once()
  except Exception:
   err=traceback.format_exc();log(err);state('BLOCKED',err[-1800:])
  time.sleep(INTERVAL)
if __name__=='__main__':main()
