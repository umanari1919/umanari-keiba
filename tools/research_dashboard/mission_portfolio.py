from __future__ import annotations

import json,os
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT=Path(os.environ.get('THE_JOCKEY_RESEARCH_ROOT',Path.home()/'Downloads'/'THE-JOCKEY-RESEARCH'));REPORTS=ROOT/'CORE'/'reports';CHECK=ROOT/'checkpoints';PLAN=REPORTS/'MISSION_PORTFOLIO_plan.json';NEXT=REPORTS/'NEXT_MISSION.json';CONTROL=REPORTS/'OPERATION_control.json'
DEPT_ORDER={'FOUNDATION':0,'DATA':1,'RESEARCH':2,'PREDICTION':3,'STRATEGY':4,'AUDIT':5}
ALWAYS_ON={'foundation_selftest_director','dependency_guard','data_inventory_director','source_adapter_director','canonicalization_director','data_reconciliation_director','chief_operating_director','autonomy_supervisor'}
def now():return datetime.now().astimezone().isoformat()
def readj(p,d=None):
 try:return json.loads(p.read_text(encoding='utf-8-sig'))
 except Exception:return d
def score(m:dict[str,Any])->float:
 impact=float(m.get('impact',3));urgency=float(m.get('urgency',3));confidence=float(m.get('confidence',3));cost=max(1.0,float(m.get('cost',2)));risk=max(0.0,float(m.get('risk',1)));base=impact*2.2+urgency*1.8+confidence-cost*0.9-risk*1.1
 if m.get('kind') in {'BLOCKER','STAGING_RECOVERY'}:base+=8
 if m.get('department')=='DATA' and m.get('kind') in {'UNUSED_DATA','SOURCE_CONTRACT','SOURCE_STAGING'}:base+=3
 return round(base,3)
def run_once(materials:dict[str,Any]|None=None,resource:dict[str,Any]|None=None,foundation:dict[str,Any]|None=None)->dict[str,Any]:
 materials=materials or readj(REPORTS/'RESEARCH_MATERIAL_queue.json',{}) or {};resource=resource or {};foundation=foundation or {};ranked=[]
 for m in materials.get('materials',[]):x=dict(m);x['score']=score(x);ranked.append(x)
 ranked.sort(key=lambda x:(-x['score'],DEPT_ORDER.get(x.get('department'),99),x.get('key','')));active=ranked[:3];next_mission=active[0] if active else {'key':'maintenance:steady','title':'研究所を安定運転し新しい証拠を待つ','department':'FOUNDATION','kind':'STEADY_STATE','score':0,'worker':None};mode='NORMAL'
 if foundation.get('status')=='BLOCKED':mode='FOUNDATION_RECOVERY'
 elif resource.get('mode')=='PAUSE_EXPERIMENTS':mode='RESOURCE_CONSTRAINED'
 elif next_mission.get('department')=='DATA':mode='DATA_EXPANSION'
 elif next_mission.get('department')=='RESEARCH':mode='RESEARCH_EXPANSION'
 elif next_mission.get('department')=='AUDIT':mode='EVIDENCE_BUILDING'
 desired_workers=set(ALWAYS_ON)
 for m in active:
  if m.get('worker'):desired_workers.add(m['worker'])
 desired_workers.update({'research_director','temporal_sample_optimizer','universal_model_director','probability_director','race_simulation_director','blind_evaluation_director','failure_analysis_director'})
 if mode not in {'FOUNDATION_RECOVERY','RESOURCE_CONSTRAINED'}:
  if any(m.get('department')=='RESEARCH' for m in active):desired_workers.update({'feature_research_director','experiment_director','hypothesis_generator','domain_research_director','ensemble_director'})
  if any(m.get('department')=='STRATEGY' for m in active):desired_workers.add('decision_strategy_director')
 out={'updated':now(),'mode':mode,'next_mission':next_mission,'active_missions':active,'backlog':ranked[3:25],'desired_workers':sorted(desired_workers),'decision_rule':'score=impact*2.2+urgency*1.8+confidence-cost*0.9-risk*1.1 plus governance/data-pipeline boosts.'};REPORTS.mkdir(parents=True,exist_ok=True)
 for p,obj in ((PLAN,out),(NEXT,next_mission),(CONTROL,{'updated':now(),'mode':mode,'desired_workers':sorted(desired_workers),'active_mission_keys':[m['key'] for m in active]})):
  t=p.with_suffix(p.suffix+'.tmp');t.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8');t.replace(p)
 return out
