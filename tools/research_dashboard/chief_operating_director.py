from __future__ import annotations
import json,os,subprocess,sys,time,traceback
from datetime import datetime
from pathlib import Path
ROOT=Path(os.environ.get('THE_JOCKEY_RESEARCH_ROOT',Path.home()/'Downloads'/'THE-JOCKEY-RESEARCH'));CHECK=ROOT/'checkpoints';REPORTS=ROOT/'CORE'/'reports';PROD=ROOT/'production';LOG=ROOT/'logs'/'chief_operating_director.log';STATE=CHECK/'chief_operating_director_state.json';INTERVAL=max(30,int(os.environ.get('THE_JOCKEY_CHIEF_INTERVAL','60')))
for p in (CHECK,REPORTS,PROD,LOG.parent):p.mkdir(parents=True,exist_ok=True)
def now():return datetime.now().astimezone().isoformat()
def readj(p,d=None):
 try:return json.loads(p.read_text(encoding='utf-8-sig'))
 except Exception:return d
def writej(p,o):
 t=p.with_suffix(p.suffix+'.tmp');t.write_text(json.dumps(o,ensure_ascii=False,indent=2),encoding='utf-8');t.replace(p)
def log(s):
 line=f'[{now()}] {s}';print(line,flush=True)
 with LOG.open('a',encoding='utf-8') as f:f.write(line+'\n')
def alive(pid):
 try:os.kill(int(pid),0);return True
 except Exception:return False
def stop_worker(name):
 st=readj(CHECK/f'{name}_state.json',{}) or {};pid=int(st.get('pid') or 0)
 if not alive(pid):return False
 try:
  if os.name=='nt':subprocess.run(['taskkill','/PID',str(pid),'/T','/F'],capture_output=True)
  else:os.kill(pid,15)
  log(f'CHIEF STOP {name} pid={pid}');return True
 except Exception as e:log(f'CHIEF STOP FAILED {name}: {e!r}');return False
def start_worker(name):
 st=readj(CHECK/f'{name}_state.json',{}) or {};pid=int(st.get('pid') or 0)
 if alive(pid):return False
 script=ROOT/f'{name}.py'
 if not script.exists():return False
 flags=(getattr(subprocess,'CREATE_NO_WINDOW',0)|getattr(subprocess,'DETACHED_PROCESS',0)) if os.name=='nt' else 0
 try:
  p=subprocess.Popen([sys.executable,str(script)],cwd=str(ROOT),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=flags,env={**os.environ,'THE_JOCKEY_RESEARCH_ROOT':str(ROOT)});log(f'CHIEF START {name} pid={p.pid}');return True
 except Exception as e:log(f'CHIEF START FAILED {name}: {e!r}');return False
def enforce(o,r,portfolio):
 actions=[];hold={x['worker'] for x in o.get('steps',[]) if x.get('desired')=='HOLD'};desired=set(portfolio.get('desired_workers',[]))
 costly={'chunked_source_staging_director','feature_research_director','experiment_director','hypothesis_generator','domain_research_director','ensemble_director','decision_strategy_director'}
 for n in costly:
  if n in hold or n not in desired or r.get('mode')=='PAUSE_EXPERIMENTS':
   if stop_worker(n):actions.append(f'STOP:{n}')
  else:
   if start_worker(n):actions.append(f'START:{n}')
 return actions
def enforce_production_hold(status,blockers):
 path=PROD/'production_manifest.json';m=readj(path,{}) or {}
 if status=='BLOCKED':m.update({'status':'HOLD','governance_hold':True,'governance_blockers':blockers,'governance_updated':now(),'auto_betting':False});writej(path,m);return True
 if m.get('governance_hold'):m['governance_hold']=False;m['governance_blockers']=[];m['governance_updated']=now();writej(path,m)
 return False
def run_once():
 import foundation_selftest_director as foundation
 import schema_contract_director as schema
 import resource_manager_director as resource
 import leakage_guard_director as leakage
 import backup_rollback_director as backup
 import pipeline_orchestrator as orchestrator
 import research_material_engine as material_engine
 import mission_portfolio as portfolio_engine
 f=foundation.run_once();s=schema.run_once();r=resource.run_once();l=leakage.run_once();b=backup.run_once();materials=material_engine.run_once();portfolio=portfolio_engine.run_once(materials,r,f);o=orchestrator.run_once(s,l,r,f,portfolio);actions=enforce(o,r,portfolio);blockers=[]
 if f.get('status')=='BLOCKED':blockers.append('FOUNDATION')
 if s.get('status')=='BLOCKED':blockers.append('SCHEMA')
 if l.get('status')=='BLOCKED':blockers.append('LEAKAGE')
 status='BLOCKED' if blockers else ('DEGRADED' if f.get('status')=='WARN' or r.get('mode')!='TURBO' or o.get('status') not in {'PASS','FOCUSED'} else 'PASS');prod_hold=enforce_production_hold(status,blockers)
 out={'pid':os.getpid(),'updated':now(),'status':status,'blockers':blockers,'actions':actions,'production_hold':prod_hold,'next_mission':portfolio.get('next_mission'),'portfolio_mode':portfolio.get('mode'),'active_missions':portfolio.get('active_missions',[]),'research_material_count':materials.get('count',0),'foundation':{'status':f.get('status'),'blockers':f.get('blocker_count'),'warnings':f.get('warning_count')},'schema':s,'resources':r,'leakage':l,'backup':{'status':b.get('status'),'snapshot':b.get('snapshot'),'items':len(b.get('items',[]))},'orchestration':o}
 writej(STATE,out);writej(REPORTS/'CHIEF_OPERATING_report.json',out);log(f"CHIEF {status} next={portfolio.get('next_mission',{}).get('key')} mode={portfolio.get('mode')} resource={r.get('mode')} actions={actions}");return out
def main():
 log('CHIEF OPERATING DIRECTOR START v2 PORTFOLIO MODE')
 while True:
  try:run_once()
  except Exception:
   err=traceback.format_exc();log(err);writej(STATE,{'pid':os.getpid(),'updated':now(),'status':'BLOCKED','detail':err[-1800:]})
  time.sleep(INTERVAL)
if __name__=='__main__':main()
