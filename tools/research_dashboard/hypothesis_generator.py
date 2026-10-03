from __future__ import annotations

import hashlib, json, os, time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(os.environ.get('THE_JOCKEY_RESEARCH_ROOT', Path.home()/'Downloads'/'THE-JOCKEY-RESEARCH'))
REPORTS = ROOT/'CORE'/'reports'
CHECK = ROOT/'checkpoints'
LOG = ROOT/'logs'/'hypothesis_generator.log'
LEDGER = REPORTS/'EXPERIMENT_ledger.csv'
QUEUE = REPORTS/'HYPOTHESIS_queue.json'
PLAN = REPORTS/'TEMPORAL_SPLIT_plan.json'
STATE = CHECK/'hypothesis_generator_state.json'
INTERVAL = int(os.environ.get('THE_JOCKEY_HYPOTHESIS_INTERVAL','60'))
MIN_RESULTS = int(os.environ.get('THE_JOCKEY_HYPOTHESIS_MIN_RESULTS','12'))
MAX_QUEUE = int(os.environ.get('THE_JOCKEY_HYPOTHESIS_QUEUE','72'))
for p in (REPORTS,CHECK,LOG.parent): p.mkdir(parents=True,exist_ok=True)

def now(): return datetime.now().astimezone().isoformat()
def readj(path,default=None):
    try:return json.loads(path.read_text(encoding='utf-8-sig'))
    except Exception:return default
def writej(path,obj):
    t=path.with_suffix(path.suffix+'.tmp'); t.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8'); t.replace(path)
def log(msg):
    line=f'[{now()}] {msg}'; print(line,flush=True)
    with LOG.open('a',encoding='utf-8') as f:f.write(line+'\n')
def write_state(status,detail='',extra=None):
    x={'pid':os.getpid(),'updated':now(),'status':status,'detail':detail}
    if extra:x.update(extra)
    writej(STATE,x)
def split_id(plan):
    parts=[]
    for name in ['TRAIN','VALIDATION','SELECTION','TEST','OOS']:
        s=(plan.get('splits') or {}).get(name,{})
        parts.extend([name,str(s.get('start_date')),str(s.get('end_date'))])
    return hashlib.sha256('|'.join(parts).encode()).hexdigest()[:16]

def build_candidates(df:pd.DataFrame):
    if df.empty:return []
    good=df[df.status.isin(['PROMOTE','KEEP'])].copy()
    if len(good)<MIN_RESULTS:return []
    metric='selection_logloss' if 'selection_logloss' in good.columns else 'select_2024_logloss'
    if metric not in good.columns:return []
    good[metric]=pd.to_numeric(good[metric],errors='coerce')
    good=good.dropna(subset=[metric])
    if good.empty:return []
    out=[]
    for target,g in good.groupby('target'):
        elite=g.nsmallest(min(8,len(g)),metric)
        fsets=elite['feature_set'].value_counts().index.tolist()[:2] or ['FIELD']
        depths=sorted(set(pd.to_numeric(elite['depth'],errors='coerce').dropna().astype(int).tolist()))
        lrs=sorted(set(pd.to_numeric(elite['lr'],errors='coerce').dropna().astype(float).tolist()))
        l2s=sorted(set(pd.to_numeric(elite['l2'],errors='coerce').dropna().astype(float).tolist()))
        iters=sorted(set(pd.to_numeric(elite['iters'],errors='coerce').dropna().astype(int).tolist()))
        center_depth=int(round(np.median(depths))) if depths else 6
        center_lr=float(np.median(lrs)) if lrs else .03
        center_l2=float(np.median(l2s)) if l2s else 8.0
        center_iters=int(round(np.median(iters))) if iters else 900
        depth_opts=sorted(set(max(3,min(10,x)) for x in [center_depth-1,center_depth,center_depth+1]))
        lr_opts=sorted(set(max(.008,min(.12,x)) for x in [center_lr*.75,center_lr,center_lr*1.25]))
        l2_opts=sorted(set(max(1.0,min(30.0,x)) for x in [center_l2*.7,center_l2,center_l2*1.4]))
        iter_opts=sorted(set(max(300,min(1800,int(x))) for x in [center_iters*.8,center_iters,center_iters*1.2]))
        seeds=[20261201,20261217,20270103]
        rank=0
        for fset in fsets:
            for d in depth_opts:
                for lr in lr_opts:
                    for l2 in l2_opts:
                        it=iter_opts[min(rank % len(iter_opts),len(iter_opts)-1)]
                        seed=seeds[rank % len(seeds)]
                        out.append({'source':'HYPOTHESIS_GEN','generation':1,'target':target,'feature_set':str(fset),'config':f'G1_D{d}_LR{lr:.4f}_L2{l2:.2f}','depth':int(d),'lr':float(round(lr,6)),'l2':float(round(l2,4)),'iters':int(it),'seed':int(seed),'priority':rank})
                        rank+=1
    seen=set();uniq=[]
    for c in out:
        k=f"{c['target']}|{c['feature_set']}|{c['config']}|{c['seed']}"
        if k in seen:continue
        seen.add(k);uniq.append(c)
    return uniq[:MAX_QUEUE]

def run_once():
    plan=readj(PLAN,{}) or {}
    if not plan.get('splits') or plan.get('status')=='BLOCKED':
        write_state('WAITING','Temporal split plan not ready'); return
    sid=split_id(plan)
    if not LEDGER.exists():
        write_state('WAITING','Experiment ledger not available',{'split_id':sid}); return
    try:df=pd.read_csv(LEDGER)
    except Exception as e:
        write_state('BLOCKED',repr(e)); return
    if 'split_id' not in df.columns:
        write_state('WAITING','No experiments for current temporal split',{'split_id':sid}); return
    df=df[df['split_id'].astype(str)==sid].copy()
    if len(df)<MIN_RESULTS:
        write_state('WAITING',f'Need {MIN_RESULTS} completed experiments for current split',{'split_id':sid,'completed':int(len(df))}); return
    queue=build_candidates(df)
    payload={'updated':now(),'generation':1,'split_id':sid,'source_rows':int(len(df)),'count':len(queue),'candidates':queue}
    writej(QUEUE,payload)
    write_state('PASS','Adaptive hypothesis queue refreshed',{'split_id':sid,'source_rows':int(len(df)),'queue':len(queue)})
    log(f'HYPOTHESIS QUEUE refreshed split={sid} source_rows={len(df)} queue={len(queue)}')

def main():
    log('HYPOTHESIS GENERATOR START')
    while True:
        try:run_once()
        except Exception as e:write_state('BLOCKED',repr(e)); log(f'ERROR {e!r}')
        time.sleep(max(30,INTERVAL))

if __name__=='__main__':main()
