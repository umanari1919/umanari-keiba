from __future__ import annotations
import json,os,time,traceback
from datetime import datetime
from pathlib import Path

ROOT=Path(os.environ.get('THE_JOCKEY_RESEARCH_ROOT',Path.home()/'Downloads'/'THE-JOCKEY-RESEARCH'))
CORE=ROOT/'CORE';REPORTS=CORE/'reports';CHECK=ROOT/'checkpoints';CONTRACTS=CORE/'contracts'/'source_adapters';QUAR=ROOT/'canonicalization'/'quarantine';CASES=REPORTS/'conflict_cases';STATE=CHECK/'conflict_resolution_director_state.json';SUMMARY=REPORTS/'CONFLICT_RESOLUTION_summary.json';INTERVAL=max(300,int(os.environ.get('THE_JOCKEY_CONFLICT_INTERVAL','1800')))
for p in (REPORTS,CHECK,CASES):p.mkdir(parents=True,exist_ok=True)

def now():return datetime.now().astimezone().isoformat()
def writej(p,o):
 t=p.with_suffix(p.suffix+'.tmp');t.write_text(json.dumps(o,ensure_ascii=False,indent=2),encoding='utf-8');t.replace(p)
def readj(p,d=None):
 try:return json.loads(Path(p).read_text(encoding='utf-8-sig'))
 except Exception:return d
def lit(v):return "'"+str(v).replace("'","''")+"'"
def source_id_from_name(path):
 name=Path(path).name
 return name.split('__conflicts__',1)[0] if '__conflicts__' in name else name.split('__',1)[0]
def contract_for(source_id):
 for p in CONTRACTS.glob('*.json'):
  x=readj(p,{}) or {}
  if str(x.get('source_id') or p.stem)==source_id:return p,x
 return None,{}
def case_policy(contract):
 policy=contract.get('conflict_policy') or {}
 explicit=bool(policy.get('allow_auto_replace_existing') is True)
 source_priority=policy.get('source_priority');incumbent_priority=policy.get('incumbent_priority')
 try:better=float(source_priority)>float(incumbent_priority)
 except Exception:better=False
 rights=contract.get('rights_status') in {'APPROVED','APPROVED_INTERNAL'}
 return {'auto_replace_requested':explicit,'source_priority':source_priority,'incumbent_priority':incumbent_priority,'source_priority_higher':better,'rights_approved':rights}
def evaluate(path):
 import duckdb
 source_id=source_id_from_name(path);cp,contract=contract_for(source_id);policy=case_policy(contract);con=duckdb.connect()
 try:rows=int(con.execute(f"SELECT count(*) FROM read_parquet({lit(path)})").fetchone()[0] or 0)
 finally:con.close()
 decision='FOUNDER_REVIEW';reason='NO_EXPLICIT_SAFE_AUTO_REPLACE_POLICY'
 if not contract:reason='SOURCE_CONTRACT_MISSING'
 elif not policy['rights_approved']:reason='RIGHTS_NOT_APPROVED'
 elif policy['auto_replace_requested'] and policy['source_priority_higher']:
  decision='POLICY_ELIGIBLE_BUT_HOLD';reason='ROW_LEVEL_ACTIVE_PROVENANCE_NOT_ESTABLISHED'
 case={'updated':now(),'source_id':source_id,'conflict_artifact':str(path),'rows':rows,'contract':str(cp) if cp else None,'decision':decision,'reason':reason,'policy_evidence':policy,'automatic_write_allowed':False,'founder_review_required':True,'rule':'Existing Canonical rows are never overwritten unless row-level provenance + explicit priority policy + rights are all proven.'}
 writej(CASES/f'{path.stem}.json',case)
 try:
  from data_lineage import append_event
  append_event('CONFLICT_CASE',source_id=source_id,source_artifact=str(path),policy=decision,details=case)
 except Exception:pass
 return case
def run_once():
 cases=[evaluate(p) for p in sorted(QUAR.glob('*__conflicts__*.parquet'))];founder=sum(bool(x.get('founder_review_required')) for x in cases);status='WARN' if founder else ('PASS' if cases else 'WAITING')
 out={'pid':os.getpid(),'updated':now(),'status':status,'cases':len(cases),'founder_review_cases':founder,'results':cases,'policy':'Evidence-driven triage only. No conflict artifact can overwrite Active Canonical automatically.'};writej(SUMMARY,out);writej(STATE,out);return out
def main():
 while True:
  try:run_once()
  except Exception:writej(STATE,{'pid':os.getpid(),'updated':now(),'status':'BLOCKED','detail':traceback.format_exc()[-1800:]})
  time.sleep(INTERVAL)
if __name__=='__main__':main()
