from __future__ import annotations

import hashlib,json,os,subprocess,sys,time,urllib.request
from datetime import datetime
from pathlib import Path
ROOT=Path(os.environ.get('THE_JOCKEY_RESEARCH_ROOT',Path.home()/'Downloads'/'THE-JOCKEY-RESEARCH'));CORE=ROOT/'CORE';DATA=CORE/'data';REPORTS=CORE/'reports';CHECK=ROOT/'checkpoints';LOGS=ROOT/'logs'
STATE=CHECK/'autonomy_supervisor_state.json';LOG=LOGS/'autonomy_supervisor.log';PROD=ROOT/'production';INTERVAL=int(os.environ.get('THE_JOCKEY_SUPERVISOR_INTERVAL','60'));MAX_RESTARTS=int(os.environ.get('THE_JOCKEY_MAX_RESTARTS','5'))
WORKERS={'research_director.py':'research_director_state.json','data_inventory_director.py':'data_inventory_director_state.json','data_reconciliation_director.py':'data_reconciliation_director_state.json','temporal_sample_optimizer.py':'temporal_sample_optimizer_state.json','universal_model_director.py':'universal_model_director_state.json','probability_director.py':'probability_director_state.json','meta_research_director.py':'meta_research_director_state.json','feature_research_director.py':'feature_research_director_state.json','experiment_director.py':'experiment_director_state.json','hypothesis_generator.py':'hypothesis_generator_state.json','domain_research_director.py':'domain_research_director_state.json','ensemble_director.py':'ensemble_director_state.json'}
BASE='https://raw.githubusercontent.com/umanari1919/umanari-keiba/main/tools/research_dashboard';PLAN=REPORTS/'TEMPORAL_SPLIT_plan.json'
for p in (CHECK,LOGS,PROD,REPORTS):p.mkdir(parents=True,exist_ok=True)
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
def alive(pid):
 try:os.kill(int(pid),0);return True
 except:return False
def start(script):
 flags=getattr(subprocess,'CREATE_NO_WINDOW',0)|getattr(subprocess,'DETACHED_PROCESS',0) if os.name=='nt' else 0
 return subprocess.Popen([sys.executable,str(ROOT/script)],cwd=str(ROOT),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=flags,env={**os.environ,'THE_JOCKEY_RESEARCH_ROOT':str(ROOT)}).pid
def bootstrap(script):
 path=ROOT/script
 if path.exists():return True
 try:
  req=urllib.request.Request(f'{BASE}/{script}?t={time.time_ns()}',headers={'User-Agent':'THE-JOCKEY-Autonomy-Supervisor/1.5'})
  with urllib.request.urlopen(req,timeout=30) as r:data=r.read()
  tmp=path.with_suffix(path.suffix+'.bootstrap');tmp.write_bytes(data);tmp.replace(path);log(f'BOOTSTRAP {script}');return True
 except Exception as e:log(f'BOOTSTRAP FAILED {script}: {e!r}');return False
def signature(path):
 if not path.exists():return None
 st=path.stat();return hashlib.sha256(f'{st.st_size}:{int(st.st_mtime)}'.encode()).hexdigest()
def quality_audit():
 src=DATA/'CORE-004_field_strength_v2.csv';out={'status':'WAITING','source':str(src)}
 if not src.exists():return out
 import pandas as pd
 cols=['race_id','race_horse_id','horse_id','race_date','race_scope_cd','label_win','label_top2','label_top3'];df=pd.read_csv(src,usecols=lambda c:c in cols,low_memory=False)
 dup=int(df['race_horse_id'].duplicated().sum()) if 'race_horse_id' in df else -1;mono=int(((df['label_win']>df['label_top2'])|(df['label_top2']>df['label_top3'])).fillna(False).sum()) if all(c in df for c in ['label_win','label_top2','label_top3']) else -1
 out={'status':'PASS' if dup==0 and mono==0 else 'BLOCKED','rows':len(df),'races':int(df.race_id.nunique()),'duplicate_race_horse_id':dup,'label_order_violations':mono,'signature':signature(src),'updated':now()};writej(REPORTS/'AUTONOMY_data_quality.json',out);return out
def drift_audit():
 src=REPORTS/'CORE-010_calibration_metrics.csv';out={'status':'WAITING'}
 if not src.exists():return out
 import pandas as pd
 m=pd.read_csv(src);alerts=[]
 if 'split' in m.columns:
  groups=m.groupby('target') if 'target' in m.columns else [('ALL',m)]
  for target,g in groups:
   a=g[g['split'].astype(str).str.upper().eq('TEST')];b=g[g['split'].astype(str).str.upper().eq('OOS')]
   if len(a) and len(b):
    if 'logloss' in m and b.logloss.mean()>a.logloss.mean()*1.08:alerts.append(f'{target}:logloss_drift')
    if 'brier' in m and b.brier.mean()>a.brier.mean()*1.08:alerts.append(f'{target}:brier_drift')
 out={'status':'ALERT' if alerts else 'PASS','alerts':alerts,'updated':now()};writej(REPORTS/'AUTONOMY_drift.json',out);return out
def production_gate(q,d):
 plan=readj(PLAN,{}) or {};current=split_id(plan) if plan.get('splits') else None;core=readj(REPORTS/'CORE-005_decision.json',{}) or {};cal=readj(REPORTS/'CORE-010_decision.json',{}) or {};exp=readj(REPORTS/'EXPERIMENT_registry.json',{}) or {};meta=readj(REPORTS/'model_registry.json',{}) or {}
 missing=[]
 if not plan.get('splits'):missing.append(str(PLAN))
 if core.get('status')!='PASS' or core.get('split_id')!=current:missing.append('CORE-005 current split')
 if cal.get('status')!='PASS' or cal.get('split_id')!=current:missing.append('CORE-010 current split')
 if exp.get('split_id')==current and exp.get('targets'):source='EXPERIMENT_REGISTRY';registry=exp
 elif meta and meta.get('split_id')==current:source='META_REGISTRY';registry=meta
 else:source='CORE-005_CHAMPION';registry=core.get('champion',{}) if core.get('split_id')==current else {}
 temporal_status=plan.get('status','WAITING');ok=not missing and bool(registry) and temporal_status in ('PASS','WARN') and q.get('status')=='PASS' and d.get('status')!='ALERT'
 manifest={'status':'READY' if ok else 'HOLD','split_id':current,'temporal_status':temporal_status,'missing':missing,'quality':q.get('status'),'drift':d.get('status'),'updated':now(),'auto_betting':False,'scope':'prediction-model-only','model_source':source,'registry':registry if ok else {}}
 writej(PROD/'production_manifest.json',manifest);return manifest
def worker_health(mem):
 out={}
 for script,state_name in WORKERS.items():
  if not bootstrap(script):out[script]={'status':'NOT_INSTALLED'};continue
  st=readj(CHECK/state_name,{}) or {};pid=int(st.get('pid') or 0);restarts=int(mem.get(script,{}).get('restarts',0));status='RUNNING' if alive(pid) else 'DEAD'
  if status=='DEAD' and restarts<MAX_RESTARTS:
   try:pid=start(script);restarts+=1;status='RESTARTED';log(f'RESTART {script} pid={pid}')
   except Exception as e:status='FAILED';log(f'FAILED {script}: {e!r}')
  out[script]={'status':status,'pid':pid,'restarts':restarts,'last_state_update':st.get('updated') or st.get('updated_at')}
 return out
def run_once():
 prev=readj(STATE,{}) or {};workers=worker_health(prev.get('workers',{}));q=quality_audit();d=drift_audit();prod=production_gate(q,d);plan=readj(PLAN,{}) or {};temporal=plan.get('status','WAITING');inventory=readj(REPORTS/'DATA_INVENTORY_summary.json',{}) or {};recon=readj(REPORTS/'DATA_RECONCILIATION_summary.json',{}) or {};bad_worker=any(v.get('status') in ('FAILED','DEAD') for v in workers.values());status='BLOCKED' if q.get('status')=='BLOCKED' or temporal=='BLOCKED' else ('DEGRADED' if bad_worker or d.get('status')=='ALERT' else 'PASS');state={'updated':now(),'status':status,'workers':workers,'inventory':inventory,'reconciliation':recon,'temporal_plan':{'status':temporal,'date_range':plan.get('date_range'),'population':plan.get('population'),'gates':plan.get('gates')},'data_quality':q,'drift':d,'production':prod};writej(STATE,state);return state
def main():
 log('AUTONOMY SUPERVISOR START v1.5')
 while True:
  try:run_once()
  except Exception as e:log(f'ERROR {e!r}')
  time.sleep(max(30,INTERVAL))
if __name__=='__main__':main()
