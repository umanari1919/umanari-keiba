from __future__ import annotations

import json,os,time,traceback
from datetime import datetime
from pathlib import Path
import pandas as pd
try:
 from canonical_store import bootstrap_from_legacy,build_merged_version,current_manifest,dataset_columns,dataset_stats,overlap_count,resolve_canonical_source,sha256_file,validate_dataset
except Exception as e:CANONICAL_IMPORT_ERROR=repr(e)
else:CANONICAL_IMPORT_ERROR=None
ROOT=Path(os.environ.get('THE_JOCKEY_RESEARCH_ROOT',Path.home()/'Downloads'/'THE-JOCKEY-RESEARCH'));CORE=ROOT/'CORE';DATA=CORE/'data';REPORTS=CORE/'reports';CHECK=ROOT/'checkpoints';LOG=ROOT/'logs'/'data_reconciliation_director.log';STATE=CHECK/'data_reconciliation_director_state.json';SUMMARY=REPORTS/'DATA_RECONCILIATION_summary.json';LEDGER=REPORTS/'DATA_RECONCILIATION_ledger.csv';PLAN=REPORTS/'DATA_RECONCILIATION_plan.json';BASE=DATA/'CORE-003B_historical_features.csv';INVENTORY=REPORTS/'DATA_INVENTORY_summary.json';INTERVAL=max(120,int(os.environ.get('THE_JOCKEY_RECONCILIATION_INTERVAL','600')));DEFAULT_INBOX=[ROOT/'canonicalization'/'outbox',ROOT/'incoming',ROOT/'imports',CORE/'incoming',DATA/'incoming']
for p in (REPORTS,CHECK,LOG.parent):p.mkdir(parents=True,exist_ok=True)
def now():return datetime.now().astimezone().isoformat()
def writej(path,obj):
 tmp=path.with_suffix(path.suffix+'.tmp');tmp.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8');tmp.replace(path)
def readj(path,default=None):
 try:return json.loads(path.read_text(encoding='utf-8-sig'))
 except Exception:return default
def log(msg):
 line=f'[{now()}] {msg}';print(line,flush=True)
 with LOG.open('a',encoding='utf-8') as f:f.write(line+'\n')
def state(status,detail='',extra=None):
 payload={'pid':os.getpid(),'updated':now(),'status':status,'detail':detail};payload.update(extra or {});writej(STATE,payload)
def lineage(event_type,source_artifact='',parent_artifact='',output_artifact='',canonical_version='',details=None):
 try:
  from data_lineage import append_event
  append_event(event_type,source_artifact=str(source_artifact or ''),parent_artifact=str(parent_artifact or ''),output_artifact=str(output_artifact or ''),canonical_version=str(canonical_version or ''),policy='IMMUTABLE_CANONICAL_RECONCILIATION',details=details or {})
 except Exception:pass
def inboxes():
 extra=[Path(x) for x in os.environ.get('THE_JOCKEY_RECONCILIATION_PATHS','').split(os.pathsep) if x.strip()];result=[]
 for p in DEFAULT_INBOX+extra:
  try:q=p.expanduser().resolve()
  except Exception:q=p
  if q not in result:result.append(q)
 return result
def candidates():
 result=[]
 for directory in inboxes():
  if not directory.exists():continue
  for pattern in ('*.csv','*.parquet'):
   for p in sorted(directory.glob(pattern)):
    if not p.name.startswith('CORE-'):result.append(p)
 return result
def append_ledger(rows):
 if rows:pd.DataFrame(rows).to_csv(LEDGER,mode='a',header=not LEDGER.exists(),index=False,encoding='utf-8-sig')
def trigger_downstream(before_version,after_version):writej(REPORTS/'DATA_RECONCILIATION_trigger.json',{'updated':now(),'before_version_id':before_version,'after_version_id':after_version,'action':'REBUILD_FROM_ACTIVE_CANONICAL'})
def run_once():
 if CANONICAL_IMPORT_ERROR:state('WAITING','Immutable Canonical Store unavailable',{'error':CANONICAL_IMPORT_ERROR});return
 if not BASE.exists() and current_manifest() is None:state('WAITING',f'missing legacy bootstrap source: {BASE}');return
 state('RUNNING','Bootstrapping/verifying immutable Canonical Store');before_manifest=current_manifest()
 if before_manifest is None:
  before_manifest=bootstrap_from_legacy(BASE);active_boot=resolve_canonical_source(BASE);lineage('CANONICAL_BOOTSTRAP',source_artifact=BASE,output_artifact=active_boot,canonical_version=(before_manifest or {}).get('version_id'),details={'mode':'BOOTSTRAP_LEGACY'});log(f"CANONICAL BOOTSTRAP version={(before_manifest or {}).get('version_id','-')}")
 active=resolve_canonical_source(BASE);base_cols=dataset_columns(active);base_audit=validate_dataset(active,base_cols)
 if base_audit.get('status')!='PASS':raise RuntimeError(f"active canonical invalid: {base_audit.get('issues')}")
 actions=[];accepted=[]
 for path in candidates():
  row={'updated':now(),'candidate':str(path),'candidate_sha256':sha256_file(path),'status':'QUARANTINED'}
  try:audit=validate_dataset(path,base_cols)
  except Exception as e:row.update(reason='READ_OR_SCHEMA_FAILED',error=repr(e));actions.append(row);continue
  if audit.get('status')!='PASS':row.update(reason='VALIDATION_FAILED',issues='|'.join(audit.get('issues') or []));actions.append(row);continue
  stats=audit.get('stats') or dataset_stats(path);overlap=overlap_count(active,path);rows=int(stats.get('rows') or 0);estimated_new=max(0,rows-overlap)
  if estimated_new==0:row.update(status='NOOP',reason='NO_NEW_RACE_HORSE_IDS',rows=rows,duplicate_or_existing_rows=overlap,estimated_new_rows=0,races=int(stats.get('races') or 0));actions.append(row);continue
  row.update(status='ACCEPTED',reason='EXACT_SCHEMA_AND_CANONICAL_GATES',rows=rows,duplicate_or_existing_rows=overlap,estimated_new_rows=estimated_new,races=int(stats.get('races') or 0),jra_rows=int(stats.get('jra_rows') or 0),nar_rows=int(stats.get('nar_rows') or 0));accepted.append(path);actions.append(row)
 before_version=(current_manifest() or {}).get('version_id');after_manifest=current_manifest()
 if accepted:after_manifest=build_merged_version(active,accepted)
 after_version=(after_manifest or {}).get('version_id');changed=bool(after_version and after_version!=before_version)
 if changed:
  new_active=resolve_canonical_source(BASE);trigger_downstream(before_version,after_version)
  for p in accepted:lineage('CANONICAL_PROMOTION',source_artifact=p,parent_artifact=active,output_artifact=new_active,canonical_version=after_version,details={'before_version':before_version,'after_version':after_version,'added_rows':(after_manifest or {}).get('added_rows')})
 append_ledger(actions);inv=readj(INVENTORY,{}) or {};pg_gap=(((inv.get('domains') or {}).get('NAR') or {}).get('unutilized_races',0));quarantined=sum(1 for x in actions if x.get('status')=='QUARANTINED');promoted_rows=int((after_manifest or {}).get('added_rows') or 0) if changed else 0
 summary={'status':'PASS','updated':now(),'immutable_store':True,'legacy_source_mutated':False,'active_data_path':str(resolve_canonical_source(BASE)),'version_before':before_version,'version_after':after_version,'changed':changed,'promoted_rows':promoted_rows,'accepted_files':sum(1 for x in actions if x.get('status')=='ACCEPTED'),'quarantined_files':quarantined,'noop_files':sum(1 for x in actions if x.get('status')=='NOOP'),'inventory_nar_unutilized_races':pg_gap,'active_audit':(after_manifest or {}).get('audit'),'policy':'immutable Parquet versions; exact schema; domestic/labeled/unique IDs; base precedence on duplicates; atomic current pointer; no in-place CORE-003B mutation','downstream_rebuild_required':changed};writej(SUMMARY,summary);writej(PLAN,{'updated':now(),'candidates':actions,'summary':summary});state('PASS','Immutable reconciliation complete',summary);log(f'RECONCILIATION PASS version={after_version} promoted_rows={promoted_rows} quarantined={quarantined} changed={changed}')
def main():
 log('DATA RECONCILIATION DIRECTOR START — IMMUTABLE CANONICAL STORE')
 while True:
  try:run_once()
  except Exception:
   err=traceback.format_exc();log(err);state('BLOCKED',err[-1800:])
  time.sleep(INTERVAL)
if __name__=='__main__':main()
