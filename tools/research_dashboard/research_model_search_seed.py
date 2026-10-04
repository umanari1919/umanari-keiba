from __future__ import annotations

import hashlib,json,os
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT=Path(os.environ.get('THE_JOCKEY_RESEARCH_ROOT',Path.home()/'Downloads'/'THE-JOCKEY-RESEARCH'));REPORTS=ROOT/'CORE'/'reports';BRIEFS=REPORTS/'research_briefs';QUEUE=REPORTS/'RESEARCH_BRIEF_queue.json'
def now():return datetime.now().astimezone().isoformat()
def writej(p,o):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);t=p.with_suffix(p.suffix+'.tmp');t.write_text(json.dumps(o,ensure_ascii=False,indent=2),encoding='utf-8');t.replace(p)
def augment(payload:dict[str,Any])->dict[str,Any]:
 out=dict(payload or {});sid=str(out.get('split_id') or '')
 if not sid:return out
 bid=hashlib.sha256(f'model-search|{sid}'.encode()).hexdigest()[:20]
 brief={'brief_id':bid,'created_at':now(),'idea_key':'model-search-closed-loop','title':'Universal Model探索を閉ループで改善','kind':'MODEL_SEARCH','status':'READY_FOR_EXECUTION','split_id':sid,'source_idea':'SYSTEM_CLOSED_LOOP_SEED','execution_worker':'experiment_director','objective':'Selection指標だけを使って現行Championより安定して改善するモデル候補を探索する。','population':'Canonicalの国内JRA/NAR安全母集団。既存Experiment Directorと同じTemporal Splitを使用。','required_columns':[],'evidence':{'source':'EXPERIMENT_ledger.csv / EXPERIMENT_registry.json'},'temporal_policy':{'decision_splits':['TRAIN','VALIDATION','SELECTION'],'report_only_splits':['TEST','OOS'],'test_oos_feedback_prohibited':True},'evaluation_metrics':['selection_logloss','selection_auc','validation_stability'],'baseline':'現行Championを同一split_idで比較。','success_gate':'SELECTION loglossが既存Championより改善し、同一epochでTEST/OOSを選抜に使わない。','stop_conditions':['Leakage検出','Temporal overlap','母集団不足','計算資源上限超過'],'blind_gate':'PROMOTE_CANDIDATEのみForward Blindへ送り、Blind結果は同一epochへ戻さない。','founder_approval_required':False}
 items=[b for b in out.get('briefs',[]) if isinstance(b,dict) and b.get('brief_id')!=bid];items.append({**brief,'path':str(BRIEFS/f'{bid}.json')});out['briefs']=items;out['count']=len(items);out['status']='PASS';writej(BRIEFS/f'{bid}.json',brief);writej(QUEUE,out);return out
