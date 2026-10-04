from __future__ import annotations
import json,os,time,traceback
from datetime import datetime
from pathlib import Path
ROOT=Path(os.environ.get('THE_JOCKEY_RESEARCH_ROOT',Path.home()/'Downloads'/'THE-JOCKEY-RESEARCH'));CHECK=ROOT/'checkpoints';REPORTS=ROOT/'CORE'/'reports';LOG=ROOT/'logs'/'chief_operating_director.log';STATE=CHECK/'chief_operating_director_state.json';INTERVAL=max(30,int(os.environ.get('THE_JOCKEY_CHIEF_INTERVAL','60')))
for p in (CHECK,REPORTS,LOG.parent):p.mkdir(parents=True,exist_ok=True)
def now():return datetime.now().astimezone().isoformat()
def writej(p,o):
 t=p.with_suffix(p.suffix+'.tmp');t.write_text(json.dumps(o,ensure_ascii=False,indent=2),encoding='utf-8');t.replace(p)
def log(s):
 line=f'[{now()}] {s}';print(line,flush=True)
 with LOG.open('a',encoding='utf-8') as f:f.write(line+'\n')
def run_once():
 import schema_contract_director as schema
 import resource_manager_director as resource
 import leakage_guard_director as leakage
 import backup_rollback_director as backup
 import pipeline_orchestrator as orchestrator
 s=schema.run_once();r=resource.run_once();l=leakage.run_once();b=backup.run_once();o=orchestrator.run_once(s,l,r)
 blockers=[]
 if s.get('status')=='BLOCKED':blockers.append('SCHEMA')
 if l.get('status')=='BLOCKED':blockers.append('LEAKAGE')
 status='BLOCKED' if blockers else ('DEGRADED' if r.get('mode')!='TURBO' or o.get('status')!='PASS' else 'PASS')
 out={'pid':os.getpid(),'updated':now(),'status':status,'blockers':blockers,'schema':s,'resources':r,'leakage':l,'backup':{'status':b.get('status'),'snapshot':b.get('snapshot'),'items':len(b.get('items',[]))},'orchestration':o}
 writej(STATE,out);writej(REPORTS/'CHIEF_OPERATING_report.json',out);log(f"CHIEF {status} blockers={blockers} resource={r.get('mode')} orchestration={o.get('status')}");return out
def main():
 log('CHIEF OPERATING DIRECTOR START')
 while True:
  try:run_once()
  except Exception:
   err=traceback.format_exc();log(err);writej(STATE,{'pid':os.getpid(),'updated':now(),'status':'BLOCKED','detail':err[-1800:]})
  time.sleep(INTERVAL)
if __name__=='__main__':main()
