from __future__ import annotations

import csv,json,os
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT=Path(os.environ.get('THE_JOCKEY_RESEARCH_ROOT',Path.home()/'Downloads'/'THE-JOCKEY-RESEARCH'))
REPORTS=ROOT/'CORE'/'reports';CHECK=ROOT/'checkpoints'
OUT=REPORTS/'RESEARCH_MATERIAL_queue.json'


def now(): return datetime.now().astimezone().isoformat()
def readj(path:Path,default=None):
    try:return json.loads(path.read_text(encoding='utf-8-sig'))
    except Exception:return default

def _card(key,title,department,kind,evidence,impact=3,urgency=3,confidence=3,cost=2,risk=1,worker=None):
    return {'key':key,'title':title,'department':department,'kind':kind,'evidence':evidence,
            'impact':impact,'urgency':urgency,'confidence':confidence,'cost':cost,'risk':risk,'worker':worker}

def _failure_material(cards):
    s=readj(REPORTS/'FAILURE_ANALYSIS_summary.json',{}) or {}
    counts=s.get('reason_counts') or s.get('counts') or {}
    if isinstance(counts,dict):
        for reason,count in sorted(counts.items(),key=lambda x:x[1] if isinstance(x[1],(int,float)) else 0,reverse=True)[:5]:
            try:n=int(count)
            except Exception:continue
            if n>=5:
                cards.append(_card(f'failure:{reason}',f'反復する外れ理由を研究: {reason}','RESEARCH','FAILURE_PATTERN',
                    {'source':'FAILURE_ANALYSIS_summary.json','count':n},4,3,min(5,2+n//10),2,1,'hypothesis_generator'))

def _inventory_material(cards):
    s=readj(REPORTS/'DATA_INVENTORY_summary.json',{}) or {}
    domains=s.get('domains') or s.get('by_domain') or {}
    if isinstance(domains,dict):
        for d,v in domains.items():
            if not isinstance(v,dict):continue
            unused=v.get('unutilized_races') or 0
            rate=v.get('research_utilization_rate')
            try:unused=int(unused)
            except Exception:unused=0
            if unused>0:
                cards.append(_card(f'data-gap:{d}',f'{d} 未利用データをCanonicalへ供給','DATA','UNUSED_DATA',
                    {'source':'DATA_INVENTORY_summary.json','unutilized_races':unused,'utilization_rate':rate},5,5,4,3,2,'source_adapter_director'))

def _source_material(cards):
    s=readj(REPORTS/'SOURCE_ADAPTER_summary.json',{}) or {}
    for key in ('sources','databases','connections'):
        vals=s.get(key)
        if not isinstance(vals,list):continue
        for v in vals:
            if not isinstance(v,dict):continue
            status=str(v.get('status','')).upper(); name=str(v.get('name') or v.get('source') or v.get('engine') or 'source')
            if status in {'NEEDS_CONTRACT','UNVERIFIED','READY_FOR_CONTRACT'}:
                cards.append(_card(f'adapter:{name}',f'{name} Source Adapter契約を完成','DATA','SOURCE_CONTRACT',
                    {'source':'SOURCE_ADAPTER_summary.json','status':status},5,5,4,2,2,'source_adapter_director'))

def _foundation_material(cards):
    f=readj(REPORTS/'FOUNDATION_SELFTEST_report.json',{}) or {}
    if f.get('status')=='BLOCKED':
        cards.append(_card('foundation:blockers','基盤BLOCKERを最優先で解消','FOUNDATION','BLOCKER',
            {'blockers':f.get('blockers',[])[:10]},5,5,5,2,1,'foundation_selftest_director'))
    elif f.get('status')=='WARN':
        cards.append(_card('foundation:warnings','基盤警告を解消','FOUNDATION','WARNING',
            {'warnings':f.get('warnings',[])[:10]},4,4,5,2,1,'foundation_selftest_director'))

def _blind_material(cards):
    s=readj(REPORTS/'BLIND_EVALUATION_summary.json',{}) or {}
    sealed=int(s.get('sealed_count') or s.get('frozen') or 0); scored=int(s.get('scored_count') or s.get('scored') or 0)
    if sealed<50 or scored<30:
        cards.append(_card('blind:sample','Forward Blindの標本を蓄積','AUDIT','SAMPLE_GROWTH',
            {'sealed':sealed,'scored':scored},4,3,5,1,1,'blind_evaluation_director'))

def _experiment_material(cards):
    p=REPORTS/'EXPERIMENT_ledger.csv'
    if not p.exists():return
    try:
        rows=list(csv.DictReader(p.open('r',encoding='utf-8-sig',newline='')))
    except Exception:return
    if len(rows)<25:
        cards.append(_card('experiments:depth','比較実験の母数を増やす','RESEARCH','EXPERIMENT_DEPTH',
            {'experiments':len(rows)},3,2,4,2,1,'experiment_director'))
    recent=rows[-30:]
    keep=sum(str(r.get('status','')).upper()=='KEEP' for r in recent)
    if len(recent)>=20 and keep<=1:
        cards.append(_card('experiments:stagnation','探索停滞から新しい特徴量仮説を生成','RESEARCH','STAGNATION',
            {'recent_trials':len(recent),'keep':keep},4,3,4,3,1,'hypothesis_generator'))

def run_once()->dict[str,Any]:
    cards=[]
    _foundation_material(cards);_inventory_material(cards);_source_material(cards);_failure_material(cards);_blind_material(cards);_experiment_material(cards)
    # Deduplicate by stable key; strongest evidence wins.
    uniq={}
    for c in cards:
        old=uniq.get(c['key'])
        if old is None or (c['impact']+c['urgency'])>(old['impact']+old['urgency']):uniq[c['key']]=c
    out={'updated':now(),'count':len(uniq),'materials':list(uniq.values()),
         'policy':'Research materials are generated only from observed reports/states. No horse-racing fact, schema meaning, or result is invented.'}
    REPORTS.mkdir(parents=True,exist_ok=True);tmp=OUT.with_suffix('.tmp');tmp.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8');tmp.replace(OUT)
    return out
