from __future__ import annotations

import hashlib, json, os, time, traceback
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT=Path(os.environ.get('THE_JOCKEY_RESEARCH_ROOT',Path.home()/'Downloads'/'THE-JOCKEY-RESEARCH'))
REPORTS=ROOT/'CORE'/'reports';CHECK=ROOT/'checkpoints';BRIEFS=REPORTS/'research_briefs'
IDEAS=REPORTS/'RESEARCH_FACTORY_ideas.json';TEMPORAL=REPORTS/'TEMPORAL_SPLIT_plan.json'
STATE=CHECK/'research_brief_director_state.json';SUMMARY=REPORTS/'RESEARCH_BRIEF_summary.json';QUEUE=REPORTS/'RESEARCH_BRIEF_queue.json'
INTERVAL=max(300,int(os.environ.get('THE_JOCKEY_RESEARCH_BRIEF_INTERVAL','1800')))
SPECIALIST_KINDS={'JRA_MORNING','DEBUT_SPECIALIST','OBSTACLE_SPECIALIST','NAR_TRANSFER_SPECIALIST'}
for p in (REPORTS,CHECK,BRIEFS):p.mkdir(parents=True,exist_ok=True)

def now():return datetime.now().astimezone().isoformat()
def readj(p,d=None):
 try:return json.loads(Path(p).read_text(encoding='utf-8-sig'))
 except Exception:return d
def writej(p,o):
 p=Path(p);t=p.with_suffix(p.suffix+'.tmp');t.write_text(json.dumps(o,ensure_ascii=False,indent=2),encoding='utf-8');t.replace(p)
def split_id(plan):
 parts=[]
 for n in ['TRAIN','VALIDATION','SELECTION','TEST','OOS']:
  s=(plan.get('splits') or {}).get(n,{})
  parts.extend([n,str(s.get('start_date')),str(s.get('end_date'))])
 return hashlib.sha256('|'.join(parts).encode()).hexdigest()[:16]
def route(kind,worker):
 if kind in SPECIALIST_KINDS:return 'specialist_research_director'
 if worker:return worker
 if kind=='DOMAIN_GAP':return 'domain_research_director'
 if kind=='SMALL_TICKET':return 'decision_strategy_director'
 if kind=='FAILURE_DERIVED':return 'hypothesis_generator'
 return 'feature_research_director'
def metrics(kind):
 if kind=='SMALL_TICKET':return ['ROI','profit','max_drawdown','losing_streak','ticket_efficiency','capital_efficiency']
 if kind in SPECIALIST_KINDS:return ['validation_logloss','selection_logloss','baseline_selection_logloss','selection_improvement','sample_size']
 if kind=='DOMAIN_GAP':return ['selection_logloss','selection_brier','validation_stability','sample_size','domain_gap']
 return ['selection_logloss','selection_brier','coverage','stability','redundancy']
def population(kind):
 return {
  'JRA_MORNING':'JRAのみ。午前/レース種別を明示契約列で抽出。未勝利・新馬・障害は個別集計し一括優位を仮定しない。',
  'DEBUT_SPECIALIST':'新馬/初出走を明示契約で識別できる行のみ。prior_start_count=0は補助条件に留める。',
  'OBSTACLE_SPECIALIST':'障害戦を明示契約で識別できる行のみ。平地戦を混入させない。',
  'NAR_TRANSFER_SPECIALIST':'NAR転入を出自・前所属を明示契約で識別できる行のみ。名称やクラスから推測しない。',
  'DOMAIN_GAP':'JRA/NARを同一Split境界で比較し、競走体系差を別集計する。',
  'SMALL_TICKET':'同一prediction snapshot・同一市場snapshot上でMIN-1/2/3を比較し、実払戻で最終評価する。',
 }.get(kind,'Canonicalの国内JRA/NAR安全母集団。対象特徴量が観測可能な行のみ。')
def build_brief(idea:dict[str,Any],plan:dict[str,Any]):
 kind=str(idea.get('kind') or 'UNKNOWN');sid=split_id(plan);key=str(idea.get('key') or 'unnamed');route_worker=route(kind,idea.get('worker'));required=idea.get('required_columns') or []
 brief={'brief_id':hashlib.sha256(f'{key}|{sid}'.encode()).hexdigest()[:20],'created_at':now(),'idea_key':key,'title':idea.get('title'),'kind':kind,'status':'READY_FOR_EXECUTION','split_id':sid,'source_idea':str(IDEAS),'execution_worker':route_worker,'objective':idea.get('notes') or idea.get('title'),'population':population(kind),'required_columns':required,'evidence':idea.get('evidence') or {},'temporal_policy':{'decision_splits':['TRAIN','VALIDATION','SELECTION'],'report_only_splits':['TEST','OOS'],'test_oos_feedback_prohibited':True},'evaluation_metrics':metrics(kind),'baseline':'既存Champion/現行戦略/既存特徴量集合を同一Split・同一対象母集団で比較対象とする。','success_gate':'VALIDATIONとSELECTIONで一貫改善し、sample/coverage/stability gateを満たす。TEST/OOSは昇格後の報告・監査にのみ使用。','stop_conditions':['データ契約違反','Leakage検出','Temporal overlap','必要列欠落','母集団不足','計算資源上限超過'],'blind_gate':'研究昇格後にForward Blindで外部監査。Blind結果を同一epochの再最適化へ戻さない。','founder_approval_required':False}
 if kind in SPECIALIST_KINDS:brief['specialist_rule']='CORE/contracts/specialist_segments.json の明示列・値契約が無い場合は実行禁止。'
 return brief
def run_once():
 ideas=readj(IDEAS,{}) or {};plan=readj(TEMPORAL,{}) or {}
 if not (plan.get('splits') and plan.get('status')!='BLOCKED'):
  out={'pid':os.getpid(),'updated':now(),'status':'WAITING','reason':'TEMPORAL_PLAN_NOT_READY','briefs':0};writej(SUMMARY,out);writej(STATE,out);return out
 ready=[x for x in ideas.get('ideas',[]) if isinstance(x,dict) and x.get('status')=='READY'];queue=[]
 for idea in ready:
  brief=build_brief(idea,plan);path=BRIEFS/f"{brief['brief_id']}.json";writej(path,brief);queue.append({**brief,'path':str(path)})
 queue.sort(key=lambda x:(-int((x.get('evidence') or {}).get('count') or 0),x.get('idea_key','')))
 payload={'updated':now(),'status':'PASS' if queue else 'WAITING','split_id':split_id(plan),'count':len(queue),'briefs':queue,'policy':'Research criteria are frozen before execution. Specialist segmentation is contract-driven. TEST/OOS never select or tune the same research epoch.'}
 writej(QUEUE,payload);writej(SUMMARY,{'pid':os.getpid(),'updated':now(),'status':payload['status'],'split_id':payload['split_id'],'briefs':len(queue),'workers':sorted({x['execution_worker'] for x in queue})});writej(STATE,{'pid':os.getpid(),'updated':now(),'status':payload['status'],'briefs':len(queue)});return payload
def main():
 while True:
  try:run_once()
  except Exception:writej(STATE,{'pid':os.getpid(),'updated':now(),'status':'BLOCKED','detail':traceback.format_exc()[-1800:]})
  time.sleep(INTERVAL)
if __name__=='__main__':main()
