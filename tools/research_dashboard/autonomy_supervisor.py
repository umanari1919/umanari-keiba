from __future__ import annotations

import hashlib, json, os, subprocess, sys, time
from datetime import datetime
from pathlib import Path

ROOT = Path(os.environ.get('THE_JOCKEY_RESEARCH_ROOT', Path.home()/'Downloads'/'THE-JOCKEY-RESEARCH'))
CORE = ROOT/'CORE'; DATA = CORE/'data'; REPORTS = CORE/'reports'; CHECK = ROOT/'checkpoints'; LOGS = ROOT/'logs'
STATE = CHECK/'autonomy_supervisor_state.json'; LOG = LOGS/'autonomy_supervisor.log'; PROD = ROOT/'production'
INTERVAL = int(os.environ.get('THE_JOCKEY_SUPERVISOR_INTERVAL','60'))
MAX_RESTARTS = int(os.environ.get('THE_JOCKEY_MAX_RESTARTS','5'))
STALE_SECONDS = int(os.environ.get('THE_JOCKEY_STALE_SECONDS','1800'))
WORKERS = {
 'research_director.py':'research_director_state.json',
 'probability_director.py':'probability_director_state.json',
 'meta_research_director.py':'meta_research_director_state.json',
 'feature_research_director.py':'feature_research_director_state.json',
 'domain_research_director.py':'domain_research_director_state.json',
 'ensemble_director.py':'ensemble_director_state.json',
}
for p in (CHECK,LOGS,PROD,REPORTS): p.mkdir(parents=True,exist_ok=True)

def now(): return datetime.now().astimezone().isoformat()
def readj(p,d=None):
 try:return json.loads(p.read_text(encoding='utf-8-sig'))
 except Exception:return d

def writej(p,o):
 t=p.with_suffix(p.suffix+'.tmp'); t.write_text(json.dumps(o,ensure_ascii=False,indent=2),encoding='utf-8'); t.replace(p)
def log(s):
 line=f'[{now()}] {s}'; print(line,flush=True)
 with LOG.open('a',encoding='utf-8') as f:f.write(line+'\n')
def alive(pid):
 try: os.kill(int(pid),0); return True
 except Exception:return False

def start(script):
 flags=getattr(subprocess,'CREATE_NO_WINDOW',0)|getattr(subprocess,'DETACHED_PROCESS',0) if os.name=='nt' else 0
 p=subprocess.Popen([sys.executable,str(ROOT/script)],cwd=str(ROOT),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=flags,env={**os.environ,'THE_JOCKEY_RESEARCH_ROOT':str(ROOT)})
 return p.pid

def signature(path):
 if not path.exists(): return None
 h=hashlib.sha256(); st=path.stat(); h.update(f'{st.st_size}:{int(st.st_mtime)}'.encode()); return h.hexdigest()

def quality_audit():
 src=DATA/'CORE-004_field_strength_v2.csv'; out={'status':'WAITING','source':str(src)}
 if not src.exists(): return out
 import pandas as pd
 cols=['race_id','race_horse_id','horse_id','race_date','race_scope_cd','label_win','label_top2','label_top3']
 df=pd.read_csv(src,usecols=lambda c:c in cols,low_memory=False)
 dup=int(df['race_horse_id'].duplicated().sum()) if 'race_horse_id' in df else -1
 monotonic=int(((df['label_win']>df['label_top2'])|(df['label_top2']>df['label_top3'])).fillna(False).sum()) if all(c in df for c in ['label_win','label_top2','label_top3']) else -1
 out={'status':'PASS' if dup==0 and monotonic==0 else 'BLOCKED','rows':len(df),'races':int(df.race_id.nunique()),'duplicate_race_horse_id':dup,'label_order_violations':monotonic,'signature':signature(src),'updated':now()}
 writej(REPORTS/'AUTONOMY_data_quality.json',out); return out

def drift_audit():
 src=REPORTS/'CORE-010_calibration_metrics.csv'; out={'status':'WAITING'}
 if not src.exists(): return out
 import pandas as pd
 m=pd.read_csv(src)
 numeric=[c for c in ['logloss','brier','auc'] if c in m.columns]
 alerts=[]
 if 'split' in m.columns:
  for target,g in m.groupby('target') if 'target' in m.columns else [('ALL',m)]:
   a=g[g['split'].astype(str).str.contains('2025')]; b=g[g['split'].astype(str).str.contains('2026')]
   if len(a) and len(b):
    if 'logloss' in numeric and b.logloss.mean()>a.logloss.mean()*1.08: alerts.append(f'{target}:logloss_drift')
    if 'brier' in numeric and b.brier.mean()>a.brier.mean()*1.08: alerts.append(f'{target}:brier_drift')
 out={'status':'ALERT' if alerts else 'PASS','alerts':alerts,'updated':now()}; writej(REPORTS/'AUTONOMY_drift.json',out); return out

def production_gate(quality,drift):
 req=[REPORTS/'CORE-005_decision.json',REPORTS/'CORE-010_calibration_metrics.csv',REPORTS/'model_registry.json']
 missing=[str(p) for p in req if not p.exists()]
 ok=not missing and quality.get('status')=='PASS' and drift.get('status')!='ALERT'
 manifest={'status':'READY' if ok else 'HOLD','missing':missing,'quality':quality.get('status'),'drift':drift.get('status'),'updated':now(),'auto_betting':False,'scope':'prediction-model-only'}
 if ok:
  manifest['registry']=readj(REPORTS/'model_registry.json',{})
 writej(PROD/'production_manifest.json',manifest); return manifest

def worker_health(mem):
 result={}
 for script,state_name in WORKERS.items():
  if not (ROOT/script).exists(): result[script]={'status':'NOT_INSTALLED'}; continue
  st=readj(CHECK/state_name,{}) or {}; pid=int(st.get('pid') or 0); restarts=int(mem.get(script,{}).get('restarts',0)); updated=st.get('updated') or st.get('updated_at')
  status='RUNNING' if alive(pid) else 'DEAD'
  if status=='DEAD' and restarts<MAX_RESTARTS:
   try:
    pid=start(script); restarts+=1; status='RESTARTED'; log(f'RESTART {script} pid={pid}')
   except Exception as e: status='FAILED'; log(f'FAILED {script}: {e!r}')
  result[script]={'status':status,'pid':pid,'restarts':restarts,'last_state_update':updated}
 return result

def run_once():
 prev=readj(STATE,{}) or {}; workers=worker_health(prev.get('workers',{})); q=quality_audit(); d=drift_audit(); prod=production_gate(q,d)
 state={'updated':now(),'status':'BLOCKED' if q.get('status')=='BLOCKED' else ('DEGRADED' if any(v['status'] in ('FAILED','DEAD') for v in workers.values()) or d.get('status')=='ALERT' else 'PASS'),'workers':workers,'data_quality':q,'drift':d,'production':prod}
 writej(STATE,state); return state

def main():
 log('AUTONOMY SUPERVISOR START')
 while True:
  try: run_once()
  except Exception as e: log(f'ERROR {e!r}')
  time.sleep(max(30,INTERVAL))
if __name__=='__main__': main()
