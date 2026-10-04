from __future__ import annotations
import hashlib,json,os,signal,subprocess,sys,time,urllib.request
from datetime import datetime
from pathlib import Path
ROOT=Path(os.environ.get('THE_JOCKEY_RESEARCH_ROOT',Path.home()/'Downloads'/'THE-JOCKEY-RESEARCH'));BASE='https://raw.githubusercontent.com/umanari1919/umanari-keiba/main/tools/research_dashboard';CHECK=ROOT/'checkpoints';STATE=CHECK/'lab_updater_state.json';LOG=ROOT/'logs'/'lab_updater.log';INTERVAL=int(os.environ.get('THE_JOCKEY_UPDATE_INTERVAL','300'))
FILES=['dashboard_server.py','research_director.py','source_adapter_director.py','source_adapter_runtime.py','chunked_source_staging_director.py','staging_canonical_bridge.py','research_material_engine.py','mission_portfolio.py','data_inventory_director.py','canonicalization_director.py','data_reconciliation_director.py','canonical_store.py','dependency_guard.py','modern_data_engine.py','modern_contracts.py','experiment_tracking.py','mlflow_mirror_director.py','foundation_selftest_director.py','temporal_sample_optimizer.py','universal_model_director.py','probability_director.py','race_simulation_director.py','decision_strategy_director.py','failure_analysis_director.py','meta_research_director.py','feature_research_director.py','experiment_director.py','hypothesis_generator.py','domain_research_director.py','ensemble_director.py','blind_evaluation_director.py','schema_contract_director.py','resource_manager_director.py','leakage_guard_director.py','backup_rollback_director.py','pipeline_orchestrator.py','chief_operating_director.py','autonomy_supervisor.py','start-dashboard.ps1','start-research-lab.ps1','install-dashboard.ps1','lab_updater.py']
STATES={'research_director.py':'research_director_state.json','source_adapter_director.py':'source_adapter_director_state.json','data_inventory_director.py':'data_inventory_director_state.json','canonicalization_director.py':'canonicalization_director_state.json','data_reconciliation_director.py':'data_reconciliation_director_state.json','dependency_guard.py':'dependency_guard_state.json','mlflow_mirror_director.py':'mlflow_mirror_director_state.json','foundation_selftest_director.py':'foundation_selftest_director_state.json','temporal_sample_optimizer.py':'temporal_sample_optimizer_state.json','universal_model_director.py':'universal_model_director_state.json','probability_director.py':'probability_director_state.json','race_simulation_director.py':'race_simulation_director_state.json','decision_strategy_director.py':'decision_strategy_director_state.json','failure_analysis_director.py':'failure_analysis_director_state.json','meta_research_director.py':'meta_research_director_state.json','feature_research_director.py':'feature_research_director_state.json','experiment_director.py':'experiment_director_state.json','hypothesis_generator.py':'hypothesis_generator_state.json','domain_research_director.py':'domain_research_director_state.json','ensemble_director.py':'ensemble_director_state.json','blind_evaluation_director.py':'blind_evaluation_director_state.json','chief_operating_director.py':'chief_operating_director_state.json','autonomy_supervisor.py':'autonomy_supervisor_state.json'}
for p in (CHECK,LOG.parent):p.mkdir(parents=True,exist_ok=True)
def now():return datetime.now().astimezone().isoformat()
def log(s):
 line=f'[{now()}] {s}';print(line,flush=True)
 with LOG.open('a',encoding='utf-8') as f:f.write(line+'\n')
def readj(p,d=None):
 try:return json.loads(p.read_text(encoding='utf-8-sig'))
 except:return d
def alive(pid):
 try:os.kill(int(pid),0);return True
 except:return False
def fetch(name):
 req=urllib.request.Request(f'{BASE}/{name}?t={time.time_ns()}',headers={'User-Agent':'THE-JOCKEY-Lab-Updater/4.3'})
 with urllib.request.urlopen(req,timeout=30) as r:return r.read()
def sha(b):return hashlib.sha256(b).hexdigest()
def replace(path,data):
 t=path.with_suffix(path.suffix+'.update');t.write_bytes(data);t.replace(path)
def stop(pid):
 if not alive(pid):return
 try:os.kill(int(pid),signal.SIGTERM);time.sleep(.5)
 except:pass
 if os.name=='nt' and alive(pid):subprocess.run(['taskkill','/PID',str(pid),'/T','/F'],capture_output=True)
def start(name):
 flags=(getattr(subprocess,'CREATE_NO_WINDOW',0)|getattr(subprocess,'DETACHED_PROCESS',0)) if os.name=='nt' else 0
 return subprocess.Popen([sys.executable,str(ROOT/name)],cwd=str(ROOT),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=flags,env={**os.environ,'THE_JOCKEY_RESEARCH_ROOT':str(ROOT)}).pid
def ensure(name,statefile,force=False):
 st=readj(CHECK/statefile,{}) or {};pid=int(st.get('pid') or 0)
 if force and pid:stop(pid);pid=0
 if not alive(pid):pid=start(name);log(f'START {name} pid={pid}')
 return pid
def run_once():
 updated=[];errors=[]
 for name in FILES:
  try:
   remote=fetch(name);path=ROOT/name;local=path.read_bytes() if path.exists() else b''
   if sha(remote)!=sha(local):replace(path,remote);updated.append(name);log(f'UPDATED {name}')
  except Exception as e:errors.append({'file':name,'error':repr(e)});log(f'ERROR {name}: {e!r}')
 workers={}
 for name,statefile in STATES.items():
  if (ROOT/name).exists():
   try:workers[name]=ensure(name,statefile,force=name in updated)
   except Exception as e:errors.append({'file':name,'error':f'start/restart {e!r}'})
 out={'updated_at':now(),'updated_files':updated,'workers':workers,'errors':errors,'status':'PASS' if not errors else 'PARTIAL','interval_seconds':INTERVAL};STATE.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8');return out
def main():
 log('LAB UPDATER START v4.3')
 while True:run_once();time.sleep(max(60,INTERVAL))
if __name__=='__main__':main()
