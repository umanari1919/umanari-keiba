from __future__ import annotations

import json, os, time, traceback
from datetime import datetime
from pathlib import Path
import pandas as pd

from experiment_tracking import mirror_experiment, mlflow_enabled

ROOT=Path(os.environ.get('THE_JOCKEY_RESEARCH_ROOT',Path.home()/'Downloads'/'THE-JOCKEY-RESEARCH'))
REPORTS=ROOT/'CORE'/'reports';CHECK=ROOT/'checkpoints';LOG=ROOT/'logs'/'mlflow_mirror_director.log';STATE=CHECK/'mlflow_mirror_director_state.json';LEDGER=REPORTS/'EXPERIMENT_ledger.csv';MIRROR=REPORTS/'MLFLOW_MIRROR_ledger.csv'
INTERVAL=max(30,int(os.environ.get('THE_JOCKEY_MLFLOW_MIRROR_INTERVAL','60')))
for p in (REPORTS,CHECK,LOG.parent):p.mkdir(parents=True,exist_ok=True)

def now():return datetime.now().astimezone().isoformat()
def writej(p,o):
 t=p.with_suffix(p.suffix+'.tmp');t.write_text(json.dumps(o,ensure_ascii=False,indent=2),encoding='utf-8');t.replace(p)
def log(s):
 line=f'[{now()}] {s}';print(line,flush=True)
 with LOG.open('a',encoding='utf-8') as f:f.write(line+'\n')
def key(r):return f"{r.get('split_id','')}|{r.get('experiment_key','')}"
def run_once():
 if not mlflow_enabled():
  writej(STATE,{'pid':os.getpid(),'updated':now(),'status':'WAITING','detail':'MLflow mirror disabled; set THE_JOCKEY_MLFLOW_ENABLE=1 to enable'});return
 try:import mlflow  # noqa: F401
 except Exception as e:
  writej(STATE,{'pid':os.getpid(),'updated':now(),'status':'WAITING','detail':f'MLflow not installed: {e!r}'});return
 if not LEDGER.exists():
  writej(STATE,{'pid':os.getpid(),'updated':now(),'status':'WAITING','detail':'Experiment ledger missing'});return
 src=pd.read_csv(LEDGER,low_memory=False);done=set()
 if MIRROR.exists():
  try:done=set(pd.read_csv(MIRROR,usecols=['mirror_key']).mirror_key.astype(str))
  except Exception:done=set()
 rows=[]
 for _,r in src.iterrows():
  d=r.to_dict();k=key(d)
  if k in done:continue
  result=mirror_experiment(d,ROOT);rows.append({'updated':now(),'mirror_key':k,'split_id':d.get('split_id'),'experiment_key':d.get('experiment_key'),'status':result.get('status'),'tracking_uri':result.get('tracking_uri'),'error':result.get('error')})
  if result.get('status')=='MIRRORED':done.add(k)
 if rows:pd.DataFrame(rows).to_csv(MIRROR,mode='a',header=not MIRROR.exists(),index=False,encoding='utf-8-sig')
 status='PASS' if not any(x['status']=='ERROR' for x in rows) else 'WARN';writej(STATE,{'pid':os.getpid(),'updated':now(),'status':status,'mirrored_now':sum(x['status']=='MIRRORED' for x in rows),'errors_now':sum(x['status']=='ERROR' for x in rows)});log(f"MLFLOW MIRROR {status} mirrored={sum(x['status']=='MIRRORED' for x in rows)} errors={sum(x['status']=='ERROR' for x in rows)}")

def main():
 log('MLFLOW MIRROR DIRECTOR START')
 while True:
  try:run_once()
  except Exception:
   err=traceback.format_exc();log(err);writej(STATE,{'pid':os.getpid(),'updated':now(),'status':'WARN','detail':err[-1800:]})
  time.sleep(INTERVAL)
if __name__=='__main__':main()
