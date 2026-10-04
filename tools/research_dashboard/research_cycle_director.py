from __future__ import annotations

import csv,json,os,time,traceback
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT=Path(os.environ.get('THE_JOCKEY_RESEARCH_ROOT',Path.home()/'Downloads'/'THE-JOCKEY-RESEARCH'))
REPORTS=ROOT/'CORE'/'reports';CHECK=ROOT/'checkpoints';BRIEFS=REPORTS/'research_briefs'
QUEUE=REPORTS/'RESEARCH_BRIEF_queue.json';LEDGER=REPORTS/'EXPERIMENT_ledger.csv';RCON=REPORTS/'RESEARCH_RESULT_contracts.json';OUT=REPORTS/'RESEARCH_CYCLE_summary.json';DECISIONS=REPORTS/'RESEARCH_CYCLE_decisions.json';STATE=CHECK/'research_cycle_director_state.json'
INTERVAL=max(120,int(os.environ.get('THE_JOCKEY_RESEARCH_CYCLE_INTERVAL','600')))
for p in (REPORTS,CHECK,BRIEFS):p.mkdir(parents=True,exist_ok=True)

def now():return datetime.now().astimezone().isoformat()
def readj(p,d=None):
 try:return json.loads(Path(p).read_text(encoding='utf-8-sig'))
 except Exception:return d
def writej(p,o):
 p=Path(p);t=p.with_suffix(p.suffix+'.tmp');t.write_text(json.dumps(o,ensure_ascii=False,indent=2),encoding='utf-8');t.replace(p)
def read_ledger():
 if not LEDGER.exists():return []
 try:
  with LEDGER.open('r',encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
 except Exception:return []
def _float(v):
 try:return float(v)
 except Exception:return None
def _experiment_results(brief:dict[str,Any],rows:list[dict[str,str]]):
 sid=str(brief.get('split_id') or '');bid=str(brief.get('brief_id') or '')
 if not bid:return []
 scoped=[r for r in rows if str(r.get('split_id') or '')==sid and str(r.get('brief_id') or '')==bid]
 vals=[]
 for r in scoped:
  s=_float(r.get('selection_logloss'))
  if s is not None:vals.append((s,r))
 vals.sort(key=lambda x:x[0]);return [r for _,r in vals[:20]]

def _brief_results(brief:dict[str,Any],rows:list[dict[str,str]]):
 return _experiment_results(brief,rows)

def _contract(brief):
 x=readj(RCON,{}) or {};bid=str(brief.get('brief_id') or '');sid=str(brief.get('split_id') or '')
 return next((c for c in x.get('contracts',[]) if str(c.get('brief_id') or '')==bid and str(c.get('split_id') or '')==sid),None)
def _decision(brief,results,contract=None):
 kind=str(brief.get('kind') or '');base={'brief_id':brief.get('brief_id'),'idea_key':brief.get('idea_key'),'kind':kind,'split_id':brief.get('split_id'),'execution_worker':brief.get('execution_worker'),'updated':now(),'test_oos_used_for_decision':False}
 if contract:
  rs=str(contract.get('result_status') or '')
  if rs in {'WAITING_RESULT','WAITING_OUTCOME'}:return {**base,'status':rs,'action':'KEEP_RUNNING','reason':contract.get('reason'),'result_contract':contract}
  if rs=='CAPABILITY_GAP':return {**base,'status':'CAPABILITY_GAP','action':'BUILD_EXECUTOR_CAPABILITY','reason':contract.get('reason'),'missing_capability':contract.get('missing_capability'),'result_contract':contract}
  if rs=='PROMOTE':return {**base,'status':'PROMOTE_CANDIDATE','action':'PREPARE_FORWARD_BLIND','reason':contract.get('reason'),'decision_metrics':contract.get('decision_metrics'),'same_epoch_test_oos_feedback_prohibited':True}
  if rs=='KEEP':return {**base,'status':'KEEP','action':'GENERATE_NEXT_HYPOTHESIS','reason':contract.get('reason'),'decision_metrics':contract.get('decision_metrics'),'same_epoch_test_oos_feedback_prohibited':True}
  if rs=='REJECT':return {**base,'status':'REJECT','action':'GENERATE_NEXT_HYPOTHESIS','reason':contract.get('reason'),'decision_metrics':contract.get('decision_metrics'),'same_epoch_test_oos_feedback_prohibited':True}
 if not results:return {**base,'status':'WAITING_BINDING','action':'KEEP_RUNNING','reason':'NO_EXPLICIT_BRIEF_BOUND_RESULT'}
 promoted=[r for r in results if str(r.get('status','')).upper()=='PROMOTE'];kept=[r for r in results if str(r.get('status','')).upper()=='KEEP']
 if promoted:
  best=min(promoted,key=lambda r:_float(r.get('selection_logloss')) if _float(r.get('selection_logloss')) is not None else 999)
  return {**base,'status':'PROMOTE_CANDIDATE','action':'PREPARE_FORWARD_BLIND','reason':'SELECTION_PROMOTION','best_experiment_key':best.get('experiment_key'),'selection_logloss':_float(best.get('selection_logloss')),'next_epoch_feedback':['VALIDATION','SELECTION'],'same_epoch_test_oos_feedback_prohibited':True}
 if kept:
  best=min(kept,key=lambda r:_float(r.get('selection_logloss')) if _float(r.get('selection_logloss')) is not None else 999)
  return {**base,'status':'KEEP','action':'GENERATE_NEXT_HYPOTHESIS','reason':'NO_PROMOTION_YET','best_experiment_key':best.get('experiment_key'),'selection_logloss':_float(best.get('selection_logloss')),'next_epoch_feedback':['VALIDATION','SELECTION'],'same_epoch_test_oos_feedback_prohibited':True}
 return {**base,'status':'REJECT','action':'GENERATE_NEXT_HYPOTHESIS','reason':'NO_VALID_DECISION_SPLIT_IMPROVEMENT','next_epoch_feedback':['VALIDATION','SELECTION'],'same_epoch_test_oos_feedback_prohibited':True}
def run_once():
 q=readj(QUEUE,{}) or {};rows=read_ledger();decisions=[]
 for brief in q.get('briefs',[]):
  if not isinstance(brief,dict) or brief.get('status')!='READY_FOR_EXECUTION':continue
  decisions.append(_decision(brief,_experiment_results(brief,rows),_contract(brief)))
 payload={'updated':now(),'status':'PASS' if decisions else 'WAITING','count':len(decisions),'decisions':decisions,'policy':{'explicit_brief_binding_required':True,'decision_feedback':['TRAIN','VALIDATION','SELECTION'],'test_oos_report_only':True,'same_epoch_test_oos_feedback_prohibited':True,'blind_feedback_same_epoch_prohibited':True}}
 writej(DECISIONS,payload);summary={'pid':os.getpid(),'updated':now(),'status':payload['status'],'decisions':len(decisions),'promote_candidates':sum(d.get('status')=='PROMOTE_CANDIDATE' for d in decisions),'next_hypothesis':sum(d.get('action')=='GENERATE_NEXT_HYPOTHESIS' for d in decisions),'blind_ready':sum(d.get('action')=='PREPARE_FORWARD_BLIND' for d in decisions),'capability_gaps':sum(d.get('status')=='CAPABILITY_GAP' for d in decisions),'waiting_binding':sum(d.get('status')=='WAITING_BINDING' for d in decisions)};writej(OUT,summary);writej(STATE,summary);return payload
def main():
 while True:
  try:run_once()
  except Exception:writej(STATE,{'pid':os.getpid(),'updated':now(),'status':'BLOCKED','detail':traceback.format_exc()[-1800:]})
  time.sleep(INTERVAL)
if __name__=='__main__':main()
