from __future__ import annotations

import ast,json,os,time,traceback
from datetime import datetime
from pathlib import Path

ROOT=Path(os.environ.get('THE_JOCKEY_RESEARCH_ROOT',Path.home()/'Downloads'/'THE-JOCKEY-RESEARCH'))
REPORTS=ROOT/'CORE'/'reports';CHECK=ROOT/'checkpoints';LOG=ROOT/'logs'/'foundation_selftest_director.log';STATE=CHECK/'foundation_selftest_director_state.json';REPORT=REPORTS/'FOUNDATION_SELFTEST_report.json'
INTERVAL=max(120,int(os.environ.get('THE_JOCKEY_FOUNDATION_SELFTEST_INTERVAL','600')))
WORKERS=['research_director.py','data_inventory_director.py','canonicalization_director.py','data_reconciliation_director.py','temporal_sample_optimizer.py','universal_model_director.py','probability_director.py','race_simulation_director.py','decision_strategy_director.py','failure_analysis_director.py','meta_research_director.py','feature_research_director.py','experiment_director.py','hypothesis_generator.py','domain_research_director.py','ensemble_director.py','blind_evaluation_director.py','chief_operating_director.py','autonomy_supervisor.py','lab_updater.py']
REQUIRED_MODULES=['schema_contract_director.py','resource_manager_director.py','leakage_guard_director.py','backup_rollback_director.py','pipeline_orchestrator.py','dashboard_server.py','start-research-lab.ps1','install-dashboard.ps1']
for p in (REPORTS,CHECK,LOG.parent):p.mkdir(parents=True,exist_ok=True)

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
def parse_python(path):
 try:
  src=path.read_text(encoding='utf-8-sig');tree=ast.parse(src,filename=str(path));return {'status':'PASS','nodes':sum(1 for _ in ast.walk(tree))}
 except Exception as e:return {'status':'BLOCKED','error':repr(e)}
def check_worker_contract(name):
 p=ROOT/name
 if not p.exists():return {'file':name,'status':'MISSING'}
 x=parse_python(p)
 if x['status']!='PASS':return {'file':name,**x}
 text=p.read_text(encoding='utf-8-sig',errors='replace');issues=[]
 if name!='dashboard_server.py' and name.endswith('.py') and "if __name__=='__main__'" not in text and 'if __name__ == "__main__"' not in text:issues.append('missing_main_guard')
 if 'STATE=' not in text and name not in {'dashboard_server.py','pipeline_orchestrator.py'}:issues.append('missing_state_contract')
 return {'file':name,'status':'WARN' if issues else 'PASS','issues':issues,**{k:v for k,v in x.items() if k!='status'}}
def check_start_coverage():
 p=ROOT/'start-research-lab.ps1'
 if not p.exists():return {'status':'BLOCKED','missing':WORKERS}
 text=p.read_text(encoding='utf-8-sig',errors='replace');missing=[w for w in WORKERS if w not in text]
 return {'status':'BLOCKED' if missing else 'PASS','missing':missing}
def check_updater_coverage():
 p=ROOT/'lab_updater.py'
 if not p.exists():return {'status':'BLOCKED','missing':WORKERS}
 text=p.read_text(encoding='utf-8-sig',errors='replace');missing=[w for w in WORKERS if w not in text]
 return {'status':'BLOCKED' if missing else 'PASS','missing':missing}
def check_dirs():
 tests=[]
 for p in [ROOT/'CORE'/'data',ROOT/'CORE'/'reports',ROOT/'checkpoints',ROOT/'logs']:
  try:p.mkdir(parents=True,exist_ok=True);probe=p/'.foundation_write_probe';probe.write_text('ok',encoding='utf-8');probe.unlink();tests.append({'path':str(p),'status':'PASS'})
  except Exception as e:tests.append({'path':str(p),'status':'BLOCKED','error':repr(e)})
 return tests
def run_once():
 files=[]
 for n in WORKERS+REQUIRED_MODULES:
  p=ROOT/n
  if n.endswith('.py'):files.append(check_worker_contract(n))
  else:files.append({'file':n,'status':'PASS' if p.exists() else 'MISSING'})
 start=check_start_coverage();updater=check_updater_coverage();dirs=check_dirs()
 blockers=[x for x in files if x.get('status') in {'BLOCKED','MISSING'}]
 blockers += ([{'file':'start-research-lab.ps1','status':'BLOCKED','missing':start['missing']}] if start['status']=='BLOCKED' else [])
 blockers += ([{'file':'lab_updater.py','status':'BLOCKED','missing':updater['missing']}] if updater['status']=='BLOCKED' else [])
 blockers += [x for x in dirs if x.get('status')=='BLOCKED']
 warnings=[x for x in files if x.get('status')=='WARN']
 status='BLOCKED' if blockers else ('WARN' if warnings else 'PASS')
 out={'updated':now(),'status':status,'python_and_file_checks':files,'start_script_coverage':start,'updater_coverage':updater,'writable_directories':dirs,'blocker_count':len(blockers),'warning_count':len(warnings),'blockers':blockers[:50],'warnings':warnings[:50],'policy':'Foundation must compile, self-update, start, write state/reports, and expose missing workers before research is trusted.'}
 writej(REPORT,out);state(status,'foundation self-test complete',{'blocker_count':len(blockers),'warning_count':len(warnings)});log(f'FOUNDATION SELFTEST {status} blockers={len(blockers)} warnings={len(warnings)}');return out
def main():
 log('FOUNDATION SELFTEST DIRECTOR START')
 while True:
  try:run_once()
  except Exception:
   err=traceback.format_exc();log(err);state('BLOCKED',err[-1800:])
  time.sleep(INTERVAL)
if __name__=='__main__':main()
