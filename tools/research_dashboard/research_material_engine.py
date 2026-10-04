from __future__ import annotations

import csv,json,os
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT=Path(os.environ.get('THE_JOCKEY_RESEARCH_ROOT',Path.home()/'Downloads'/'THE-JOCKEY-RESEARCH'));REPORTS=ROOT/'CORE'/'reports';CHECK=ROOT/'checkpoints';OUT=REPORTS/'RESEARCH_MATERIAL_queue.json'
def now():return datetime.now().astimezone().isoformat()
def readj(path,default=None):
 try:return json.loads(path.read_text(encoding='utf-8-sig'))
 except Exception:return default
def _card(key,title,department,kind,evidence,impact=3,urgency=3,confidence=3,cost=2,risk=1,worker=None):return {'key':key,'title':title,'department':department,'kind':kind,'evidence':evidence,'impact':impact,'urgency':urgency,'confidence':confidence,'cost':cost,'risk':risk,'worker':worker}
def _failure(cards):
 s=readj(REPORTS/'FAILURE_ANALYSIS_summary.json',{}) or {};counts=s.get('reason_counts') or s.get('counts') or {}
 if isinstance(counts,dict):
  for reason,count in sorted(counts.items(),key=lambda x:x[1] if isinstance(x[1],(int,float)) else 0,reverse=True)[:5]:
   try:n=int(count)
   except Exception:continue
   if n>=5:cards.append(_card(f'failure:{reason}',f'反復する外れ理由を研究: {reason}','RESEARCH','FAILURE_PATTERN',{'source':'FAILURE_ANALYSIS_summary.json','count':n},4,3,min(5,2+n//10),2,1,'hypothesis_generator'))
def _inventory(cards):
 s=readj(REPORTS/'DATA_INVENTORY_summary.json',{}) or {};domains=s.get('domains') or s.get('by_domain') or {}
 if isinstance(domains,dict):
  for d,v in domains.items():
   if not isinstance(v,dict):continue
   try:unused=int(v.get('unutilized_races') or 0)
   except Exception:unused=0
   if unused>0:cards.append(_card(f'data-gap:{d}',f'{d} 未利用データをCanonicalへ供給','DATA','UNUSED_DATA',{'source':'DATA_INVENTORY_summary.json','unutilized_races':unused,'utilization_rate':v.get('research_utilization_rate')},5,5,4,3,2,'source_adapter_director'))
def _source(cards):
 s=readj(REPORTS/'SOURCE_ADAPTER_summary.json',{}) or {}
 for key in ('sources','databases','connections'):
  vals=s.get(key)
  if not isinstance(vals,list):continue
  for v in vals:
   if not isinstance(v,dict):continue
   status=str(v.get('status','')).upper();name=str(v.get('name') or v.get('source') or v.get('engine') or 'source')
   if status in {'NEEDS_CONTRACT','UNVERIFIED','READY_FOR_CONTRACT'}:cards.append(_card(f'adapter:{name}',f'{name} Source Adapter契約を完成','DATA','SOURCE_CONTRACT',{'source':'SOURCE_ADAPTER_summary.json','status':status},5,5,4,2,2,'source_adapter_director'))
def _staging(cards):
 adapter=readj(REPORTS/'SOURCE_ADAPTER_summary.json',{}) or {}; staging=readj(REPORTS/'SOURCE_STAGING_summary.json',{}) or {}
 ready=int(adapter.get('contract_ready_tables') or adapter.get('ready_contracts') or 0); staged=int(staging.get('ready_sources') or 0); blocked=int(staging.get('blocked_sources') or 0)
 if ready>staged:cards.append(_card('staging:pending','契約済みSourceを分割Parquetへ搬送','DATA','SOURCE_STAGING',{'source':'SOURCE_ADAPTER_summary.json + SOURCE_STAGING_summary.json','contract_ready':ready,'staged':staged},5,5,5,3,2,'chunked_source_staging_director'))
 if blocked>0:cards.append(_card('staging:blocked','Source Staging失敗chunkを復旧','FOUNDATION','STAGING_RECOVERY',{'source':'SOURCE_STAGING_summary.json','blocked_sources':blocked},5,5,5,2,1,'chunked_source_staging_director'))
def _bridge(cards):
 staging=readj(REPORTS/'SOURCE_STAGING_summary.json',{}) or {};bridge=readj(REPORTS/'STAGING_CANONICAL_BRIDGE_summary.json',{}) or {};resolution=readj(REPORTS/'CONFLICT_RESOLUTION_summary.json',{}) or {}
 staged=int(staging.get('ready_sources') or 0);bridged=int(bridge.get('sources') or 0);conflicts=int(bridge.get('conflicts') or 0);blocked=int(bridge.get('blocked_sources') or 0);cases=int(resolution.get('cases') or 0)
 if staged>bridged:cards.append(_card('bridge:pending','StagingをCanonical候補へ分類','DATA','CANONICAL_BRIDGE',{'source':'SOURCE_STAGING_summary.json + STAGING_CANONICAL_BRIDGE_summary.json','staged_sources':staged,'bridged_sources':bridged},5,5,5,2,1,'staging_canonical_bridge'))
 if blocked>0:cards.append(_card('bridge:blocked','Staging→Canonical BridgeのBLOCKを復旧','FOUNDATION','BRIDGE_RECOVERY',{'source':'STAGING_CANONICAL_BRIDGE_summary.json','blocked_sources':blocked},5,5,5,2,1,'staging_canonical_bridge'))
 if conflicts>cases:cards.append(_card('bridge:conflicts','Canonical競合を証拠ベースで判定','DATA','CANONICAL_CONFLICT',{'source':'STAGING_CANONICAL_BRIDGE_summary.json + CONFLICT_RESOLUTION_summary.json','conflicts':conflicts,'cases':cases},5,5,5,2,3,'conflict_resolution_director'))
def _lineage(cards):
 recon=readj(REPORTS/'DATA_RECONCILIATION_summary.json',{}) or {};bridge=readj(REPORTS/'STAGING_CANONICAL_BRIDGE_summary.json',{}) or {};ledger=REPORTS/'DATA_LINEAGE_ledger.csv'
 evidence_exists=bool(recon.get('changed') or int(bridge.get('new_rows') or 0)>0 or int(bridge.get('conflicts') or 0)>0)
 if evidence_exists and not ledger.exists():cards.append(_card('lineage:missing','データ系譜台帳を復旧','FOUNDATION','LINEAGE_GAP',{'source':'reconciliation/bridge reports','ledger_exists':False},5,5,5,1,1,'conflict_resolution_director'))
def _foundation(cards):
 f=readj(REPORTS/'FOUNDATION_SELFTEST_report.json',{}) or {}
 if f.get('status')=='BLOCKED':cards.append(_card('foundation:blockers','基盤BLOCKERを最優先で解消','FOUNDATION','BLOCKER',{'blockers':f.get('blockers',[])[:10]},5,5,5,2,1,'foundation_selftest_director'))
 elif f.get('status')=='WARN':cards.append(_card('foundation:warnings','基盤警告を解消','FOUNDATION','WARNING',{'warnings':f.get('warnings',[])[:10]},4,4,5,2,1,'foundation_selftest_director'))
def _blind(cards):
 s=readj(REPORTS/'BLIND_EVALUATION_summary.json',{}) or {};sealed=int(s.get('sealed_count') or s.get('frozen') or 0);scored=int(s.get('scored_count') or s.get('scored') or 0)
 if sealed<50 or scored<30:cards.append(_card('blind:sample','Forward Blindの標本を蓄積','AUDIT','SAMPLE_GROWTH',{'sealed':sealed,'scored':scored},4,3,5,1,1,'blind_evaluation_director'))
def _experiment(cards):
 p=REPORTS/'EXPERIMENT_ledger.csv'
 if not p.exists():return
 try:rows=list(csv.DictReader(p.open('r',encoding='utf-8-sig',newline='')))
 except Exception:return
 if len(rows)<25:cards.append(_card('experiments:depth','比較実験の母数を増やす','RESEARCH','EXPERIMENT_DEPTH',{'experiments':len(rows)},3,2,4,2,1,'experiment_director'))
 recent=rows[-30:];keep=sum(str(r.get('status','')).upper()=='KEEP' for r in recent)
 if len(recent)>=20 and keep<=1:cards.append(_card('experiments:stagnation','探索停滞から新しい特徴量仮説を生成','RESEARCH','STAGNATION',{'recent_trials':len(recent),'keep':keep},4,3,4,3,1,'hypothesis_generator'))
def run_once()->dict[str,Any]:
 cards=[];_foundation(cards);_inventory(cards);_source(cards);_staging(cards);_bridge(cards);_lineage(cards);_failure(cards);_blind(cards);_experiment(cards);uniq={}
 for c in cards:
  old=uniq.get(c['key'])
  if old is None or (c['impact']+c['urgency'])>(old['impact']+old['urgency']):uniq[c['key']]=c
 out={'updated':now(),'count':len(uniq),'materials':list(uniq.values()),'policy':'Research materials are generated only from observed reports/states. No horse-racing fact, schema meaning, or result is invented.'};REPORTS.mkdir(parents=True,exist_ok=True);tmp=OUT.with_suffix('.tmp');tmp.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8');tmp.replace(OUT);return out
