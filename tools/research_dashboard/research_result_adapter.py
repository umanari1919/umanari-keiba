from __future__ import annotations

import csv,json,os
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT=Path(os.environ.get('THE_JOCKEY_RESEARCH_ROOT',Path.home()/'Downloads'/'THE-JOCKEY-RESEARCH'))
REPORTS=ROOT/'CORE'/'reports';BINDINGS=REPORTS/'RESEARCH_EXECUTION_bindings.json';QUEUE=REPORTS/'RESEARCH_BRIEF_queue.json';OUT=REPORTS/'RESEARCH_RESULT_contracts.json'
FEATURE=REPORTS/'feature_research_catalog.csv';DOMAIN=REPORTS/'DOMAIN_metrics.csv';SPECIALIST=REPORTS/'SPECIALIST_metrics.csv';STRATEGY=REPORTS/'STRATEGY_EVALUATION_summary.csv'
SPECIALIST_MIN_IMPROVEMENT=float(os.environ.get('THE_JOCKEY_SPECIALIST_MIN_IMPROVEMENT','0.0005'));STRATEGY_MIN_RACES=max(1,int(os.environ.get('THE_JOCKEY_STRATEGY_MIN_REALIZED_RACES','30')))

def now():return datetime.now().astimezone().isoformat()
def readj(p,d=None):
 try:return json.loads(Path(p).read_text(encoding='utf-8-sig'))
 except Exception:return d
def writej(p,o):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);t=p.with_suffix(p.suffix+'.tmp');t.write_text(json.dumps(o,ensure_ascii=False,indent=2),encoding='utf-8');t.replace(p)
def readcsv(p):
 if not Path(p).exists():return []
 try:
  with Path(p).open('r',encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
 except Exception:return []
def f(v):
 try:return float(v)
 except Exception:return None
def _feature(binding,brief):
 rows=[r for r in readcsv(FEATURE) if str(r.get('split_id') or '')==str(binding.get('split_id') or '')]
 if not rows:return {'result_status':'WAITING_RESULT','reason':'FEATURE_RESULT_NOT_READY'}
 promoted=[r for r in rows if str(r.get('decision'))=='PROMOTE_CANDIDATE'];valid=[r for r in rows if f(r.get('selection_mean_abs_auc')) is not None];best=max(valid,key=lambda r:f(r.get('selection_mean_abs_auc')) or -1) if valid else None
 return {'result_status':'PROMOTE' if promoted else 'REJECT','reason':'FEATURE_SELECTION_TRIAGE','decision_metrics':{'best_selection_mean_abs_auc':f(best.get('selection_mean_abs_auc')) if best else None,'promoted_feature_count':len(promoted),'candidate_count':len(rows)},'report_only_metrics':{'test_oos_present':any(any(k.startswith('auc_') and ('_test' in k or '_oos' in k) for k in r) for r in rows)},'artifact':str(FEATURE)}
def _domain(binding,brief):
 rows=[r for r in readcsv(DOMAIN) if str(r.get('split_id') or '')==str(binding.get('split_id') or '')]
 if not rows:return {'result_status':'WAITING_RESULT','reason':'DOMAIN_RESULT_NOT_READY'}
 if str(brief.get('kind') or '')!='DOMAIN_GAP':return {'result_status':'CAPABILITY_GAP','reason':'DOMAIN_RESULT_CONTRACT_UNSUPPORTED_KIND','missing_capability':brief.get('kind')}
 by={}
 for r in rows:
  x=f(r.get('SELECTION_logloss'))
  if x is not None:by.setdefault(str(r.get('domain')),[]).append(x)
 if not all(by.get(x) for x in ('JRA','NAR')):return {'result_status':'WAITING_RESULT','reason':'DOMAIN_BOTH_SIDES_NOT_READY'}
 j=sum(by['JRA'])/len(by['JRA']);n=sum(by['NAR'])/len(by['NAR'])
 return {'result_status':'KEEP','reason':'DOMAIN_GAP_MEASURED','decision_metrics':{'jra_selection_logloss_mean':j,'nar_selection_logloss_mean':n,'absolute_domain_gap':abs(j-n),'models':len(rows)},'report_only_metrics':{'test_oos_columns_present':True},'artifact':str(DOMAIN)}
def _specialist(binding,brief):
 rows=[r for r in readcsv(SPECIALIST) if str(r.get('brief_id') or '')==str(binding.get('brief_id') or '') and str(r.get('split_id') or '')==str(binding.get('split_id') or '')]
 if not rows:return {'result_status':'WAITING_RESULT','reason':'SPECIALIST_RESULT_NOT_READY','required_artifact':str(SPECIALIST)}
 valid=[r for r in rows if f(r.get('selection_improvement')) is not None and f(r.get('validation_improvement')) is not None]
 if not valid:return {'result_status':'WAITING_RESULT','reason':'SPECIALIST_COMPARISON_INCOMPLETE'}
 sel=[f(r.get('selection_improvement')) for r in valid];val=[f(r.get('validation_improvement')) for r in valid];passing=sum((s or 0)>=SPECIALIST_MIN_IMPROVEMENT and (v or 0)>0 for s,v in zip(sel,val));mean_sel=sum(sel)/len(sel);mean_val=sum(val)/len(val)
 status='PROMOTE' if passing>=min(2,len(valid)) and mean_sel>=SPECIALIST_MIN_IMPROVEMENT and mean_val>0 else 'REJECT'
 return {'result_status':status,'reason':'SPECIALIST_SAME_POPULATION_BASELINE_COMPARISON','decision_metrics':{'targets':len(valid),'passing_targets':passing,'mean_selection_improvement':mean_sel,'mean_validation_improvement':mean_val,'minimum_selection_improvement':SPECIALIST_MIN_IMPROVEMENT,'sample_rows':max(int(float(r.get('sample_rows') or 0)) for r in valid)},'report_only_metrics':{'test_oos_present':True},'artifact':str(SPECIALIST)}
def _strategy(binding,brief):
 rows=[r for r in readcsv(STRATEGY) if str(r.get('brief_id') or '')==str(binding.get('brief_id') or '') and str(r.get('split_id') or '')==str(binding.get('split_id') or '')]
 if not rows:return {'result_status':'WAITING_OUTCOME','reason':'REALIZED_PAYOUT_STRATEGY_EVALUATION_NOT_READY','required_artifact':str(STRATEGY)}
 valid=[r for r in rows if f(r.get('ROI')) is not None]
 if not valid:return {'result_status':'WAITING_OUTCOME','reason':'ROI_NOT_AVAILABLE'}
 best=max(valid,key=lambda r:f(r.get('ROI')) or -999);roi=f(best.get('ROI'));dd=f(best.get('max_drawdown'));te=f(best.get('ticket_efficiency'));ce=f(best.get('capital_efficiency'));races=int(float(best.get('races') or 0))
 if races<STRATEGY_MIN_RACES:return {'result_status':'KEEP','reason':'REALIZED_SAMPLE_BELOW_PROMOTION_GATE','decision_metrics':{'strategy':best.get('strategy'),'ROI':roi,'races':races,'required_races':STRATEGY_MIN_RACES,'max_drawdown':dd,'ticket_efficiency':te,'capital_efficiency':ce},'artifact':str(STRATEGY)}
 status='PROMOTE' if roi is not None and roi>1.0 else 'KEEP'
 return {'result_status':status,'reason':'REALIZED_SMALL_TICKET_EVALUATION','decision_metrics':{'strategy':best.get('strategy'),'ROI':roi,'races':races,'profit':f(best.get('profit')),'turnover':f(best.get('turnover')),'max_drawdown':dd,'losing_streak':f(best.get('losing_streak')),'ticket_efficiency':te,'capital_efficiency':ce},'artifact':str(STRATEGY)}
def build(bindings:dict[str,Any]|None=None,queue:dict[str,Any]|None=None):
 bindings=bindings or readj(BINDINGS,{}) or {};queue=queue or readj(QUEUE,{}) or {};by={str(b.get('brief_id')):b for b in queue.get('briefs',[]) if isinstance(b,dict) and b.get('brief_id')};contracts=[]
 for worker,binding in (bindings.get('bindings') or {}).items():
  bid=str(binding.get('brief_id') or '');brief=by.get(bid)
  if not brief:continue
  if worker=='feature_research_director':res=_feature(binding,brief)
  elif worker=='domain_research_director':res=_domain(binding,brief)
  elif worker=='specialist_research_director':res=_specialist(binding,brief)
  elif worker=='decision_strategy_director':res=_strategy(binding,brief)
  else:continue
  contracts.append({'brief_id':bid,'split_id':binding.get('split_id'),'idea_key':binding.get('idea_key'),'kind':binding.get('kind'),'execution_worker':worker,'bound_at':binding.get('bound_at'),'adapted_at':now(),'test_oos_used_for_decision':False,**res})
 out={'updated':now(),'count':len(contracts),'contracts':contracts,'policy':'Only explicitly bound artifacts become research results. Specialist promotion requires same-population baseline improvement. Strategy promotion requires realized payouts and a minimum race sample. TEST/OOS remain report-only.'};writej(OUT,out);return out
