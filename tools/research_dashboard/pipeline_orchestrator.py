from __future__ import annotations
import json,os
from datetime import datetime
from pathlib import Path
ROOT=Path(os.environ.get('THE_JOCKEY_RESEARCH_ROOT',Path.home()/'Downloads'/'THE-JOCKEY-RESEARCH'));CHECK=ROOT/'checkpoints';REPORTS=ROOT/'CORE'/'reports'
STATE=CHECK/'pipeline_orchestrator_state.json';PLAN=REPORTS/'ORCHESTRATION_plan.json';CONTROL=REPORTS/'OPERATION_control.json'
ORDER=['foundation_selftest_director','source_adapter_director','chunked_source_staging_director','staging_canonical_bridge','data_inventory_director','canonicalization_director','data_reconciliation_director','research_director','temporal_sample_optimizer','universal_model_director','feature_research_director','experiment_director','hypothesis_generator','probability_director','domain_research_director','ensemble_director','race_simulation_director','decision_strategy_director','blind_evaluation_director','failure_analysis_director']
STATE_FILES={n:CHECK/f'{n}_state.json' for n in ORDER}
for p in (CHECK,REPORTS):p.mkdir(parents=True,exist_ok=True)
def now():return datetime.now().astimezone().isoformat()
def readj(p,d=None):
 try:return json.loads(p.read_text(encoding='utf-8-sig'))
 except Exception:return d
def writej(p,o):
 t=p.with_suffix(p.suffix+'.tmp');t.write_text(json.dumps(o,ensure_ascii=False,indent=2),encoding='utf-8');t.replace(p)
def run_once(schema=None,leak=None,resource=None,foundation=None,portfolio=None):
 schema=schema or {};leak=leak or {};resource=resource or {};foundation=foundation or readj(STATE_FILES['foundation_selftest_director'],{}) or {};portfolio=portfolio or readj(REPORTS/'MISSION_PORTFOLIO_plan.json',{}) or {};control=readj(CONTROL,{}) or {};steps=[];blocked=False
 if foundation.get('status')=='BLOCKED':blocked=True;reason='FOUNDATION_BLOCKED'
 elif schema.get('status')=='BLOCKED':blocked=True;reason='SCHEMA_BLOCKED'
 elif leak.get('status')=='BLOCKED':blocked=True;reason='LEAKAGE_BLOCKED'
 elif resource.get('mode')=='PAUSE_EXPERIMENTS':reason='RESOURCE_PAUSE'
 elif portfolio.get('mode') and portfolio.get('mode')!='NORMAL':reason=portfolio.get('mode')
 else:reason='NORMAL'
 downstream={'chunked_source_staging_director','staging_canonical_bridge','data_reconciliation_director','research_director','temporal_sample_optimizer','universal_model_director','feature_research_director','experiment_director','hypothesis_generator','probability_director','domain_research_director','ensemble_director','race_simulation_director','decision_strategy_director'}
 desired_portfolio=set(portfolio.get('desired_workers',[]));costly={'chunked_source_staging_director','staging_canonical_bridge','feature_research_director','experiment_director','hypothesis_generator','domain_research_director','ensemble_director','decision_strategy_director'}
 for n in ORDER:
  st=readj(STATE_FILES[n],{}) or {};desired='RUN';why='BASELINE'
  if blocked and n in downstream:desired='HOLD';why=reason
  elif resource.get('mode')=='PAUSE_EXPERIMENTS' and n in {'experiment_director','hypothesis_generator','race_simulation_director','decision_strategy_director'}:desired='HOLD';why='RESOURCE_PAUSE'
  elif n in costly and desired_portfolio and n not in desired_portfolio:desired='HOLD';why='PORTFOLIO_NOT_SELECTED'
  elif n in desired_portfolio:why='PORTFOLIO_SELECTED'
  steps.append({'worker':n,'desired':desired,'why':why,'current':st.get('status','UNKNOWN'),'updated':st.get('updated')})
 status='BLOCKED' if blocked else ('THROTTLED' if resource.get('mode')=='PAUSE_EXPERIMENTS' else ('FOCUSED' if desired_portfolio else 'PASS'))
 out={'updated':now(),'status':status,'reason':reason,'foundation_status':foundation.get('status','UNKNOWN'),'next_mission':portfolio.get('next_mission'),'portfolio_mode':portfolio.get('mode'),'steps':steps,'control':control};writej(PLAN,out);writej(STATE,{'pid':os.getpid(),'updated':now(),'status':out['status'],'reason':reason,'next_mission':portfolio.get('next_mission')});return out
