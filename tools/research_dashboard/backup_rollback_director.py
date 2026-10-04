from __future__ import annotations
import hashlib,json,os,shutil
from datetime import datetime
from pathlib import Path
ROOT=Path(os.environ.get('THE_JOCKEY_RESEARCH_ROOT',Path.home()/'Downloads'/'THE-JOCKEY-RESEARCH'));CORE=ROOT/'CORE';REPORTS=CORE/'reports';CHECK=ROOT/'checkpoints';PROD=ROOT/'production';BACK=ROOT/'backups'/'governance'
STATE=CHECK/'backup_rollback_director_state.json';REPORT=REPORTS/'BACKUP_ROLLBACK_report.json'
FILES=[CORE/'data'/'CORE-003B_historical_features.csv',REPORTS/'TEMPORAL_SPLIT_plan.json',REPORTS/'CORE-005_decision.json',REPORTS/'CORE-010_decision.json',REPORTS/'EXPERIMENT_registry.json',PROD/'production_manifest.json']
for p in (REPORTS,CHECK,BACK):p.mkdir(parents=True,exist_ok=True)
def now():return datetime.now().astimezone().isoformat()
def writej(p,o):
 t=p.with_suffix(p.suffix+'.tmp');t.write_text(json.dumps(o,ensure_ascii=False,indent=2),encoding='utf-8');t.replace(p)
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()
def run_once():
 stamp=datetime.now().strftime('%Y%m%d');dest=BACK/stamp;dest.mkdir(parents=True,exist_ok=True);items=[]
 for p in FILES:
  if not p.exists():continue
  s=sha(p);target=dest/p.name
  if not target.exists():shutil.copy2(p,target)
  items.append({'file':str(p),'backup':str(target),'sha256':s,'size':p.stat().st_size})
 manifests=sorted(BACK.glob('*/manifest.json'))
 if len(manifests)>14:
  for m in manifests[:-14]:
   try:shutil.rmtree(m.parent)
   except Exception:pass
 out={'updated':now(),'status':'PASS','snapshot':stamp,'items':items,'rollback_mode':'SAFE_MANUAL_OR_GOVERNED','automatic_destructive_restore':False};writej(dest/'manifest.json',out);writej(REPORT,out);writej(STATE,{'pid':os.getpid(),'updated':now(),'status':'PASS','snapshot':stamp,'items':len(items)});return out
