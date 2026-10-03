from __future__ import annotations

import hashlib,json,os,time
from datetime import datetime
from pathlib import Path
import pandas as pd

ROOT=Path(os.environ.get('THE_JOCKEY_RESEARCH_ROOT',Path.home()/'Downloads'/'THE-JOCKEY-RESEARCH'));CORE=ROOT/'CORE';REPORTS=CORE/'reports';CHECK=ROOT/'checkpoints';LOG=ROOT/'logs'/'meta_research_director.log';STATE=CHECK/'meta_research_director_state.json';PLAN=REPORTS/'TEMPORAL_SPLIT_plan.json';EXPREG=REPORTS/'EXPERIMENT_registry.json';LEDGER=REPORTS/'EXPERIMENT_ledger.csv';REGISTRY=REPORTS/'model_registry.json'
for p in (REPORTS,CHECK,LOG.parent):p.mkdir(parents=True,exist_ok=True)
def now():return datetime.now().astimezone().isoformat()
def readj(p,d=None):
 try:return json.loads(p.read_text(encoding='utf-8-sig'))
 except:return d
def writej(p,o):
 t=p.with_suffix(p.suffix+'.tmp');t.write_text(json.dumps(o,ensure_ascii=False,indent=2),encoding='utf-8');t.replace(p)
def log(s):
 line=f'[{now()}] {s}';print(line,flush=True)
 with LOG.open('a',encoding='utf-8') as f:f.write(line+'\n')
def split_id(plan):
 a=[]
 for n in ['TRAIN','VALIDATION','SELECTION','TEST','OOS']:
  s=(plan.get('splits') or {}).get(n,{});a += [n,str(s.get('start_date')),str(s.get('end_date'))]
 return hashlib.sha256('|'.join(a).encode()).hexdigest()[:16]
def run_once():
 plan=readj(PLAN,{}) or {}
 if not plan.get('splits') or plan.get('status')=='BLOCKED':writej(STATE,{'pid':os.getpid(),'updated':now(),'status':'WAITING','detail':'Temporal plan not ready'});return False
 sid=split_id(plan);exp=readj(EXPREG,{}) or {};targets=(exp.get('targets') or {}) if exp.get('split_id')==sid else {}
 completed=promotions=0
 if LEDGER.exists():
  try:
   d=pd.read_csv(LEDGER)
   if 'split_id' in d:d=d[d.split_id.astype(str)==sid]
   completed=len(d);promotions=int((d.status=='PROMOTE').sum()) if 'status' in d else 0
  except Exception:pass
 if targets:
  reg={'version':2,'split_id':sid,'updated':now(),'source':'ADAPTIVE_EXPERIMENT_LOOP','targets':targets};writej(REGISTRY,reg);status='PASS';detail='Adaptive experiment champions synchronized'
 else:status='WAITING';detail='Waiting for first adaptive experiment champion'
 writej(STATE,{'pid':os.getpid(),'updated':now(),'status':status,'detail':detail,'split_id':sid,'mode':'DELEGATED','completed_experiments':completed,'promotions':promotions,'champion_targets':len(targets)});return status=='PASS'
def main():
 log('META DIRECTOR START delegated-to-adaptive-loop')
 while True:
  try:run_once()
  except Exception as e:log(f'ERROR {e!r}');writej(STATE,{'pid':os.getpid(),'updated':now(),'status':'BLOCKED','detail':repr(e)})
  time.sleep(120)
if __name__=='__main__':main()
