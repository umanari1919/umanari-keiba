from __future__ import annotations

import hashlib
import json
import os
import time
import traceback
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(os.environ.get('THE_JOCKEY_RESEARCH_ROOT', Path.home()/'Downloads'/'THE-JOCKEY-RESEARCH'))
CORE = ROOT/'CORE'; DATA = CORE/'data'; REPORTS = CORE/'reports'; MODELS = CORE/'models'/'CORE-005'; CHECK = ROOT/'checkpoints'
PLAN = REPORTS/'TEMPORAL_SPLIT_plan.json'; DECISION = REPORTS/'CORE-005_decision.json'; METRICS = REPORTS/'CORE-005_universal_ability_metrics.csv'
STATE = CHECK/'universal_model_director_state.json'; LOG = ROOT/'logs'/'universal_model_director.log'
THREADS = max(1, int(os.environ.get('THE_JOCKEY_MODEL_THREADS', str(os.cpu_count() or 4))))
INTERVAL = max(60, int(os.environ.get('THE_JOCKEY_UNIVERSAL_INTERVAL','300')))
for p in (MODELS,CHECK,LOG.parent,REPORTS): p.mkdir(parents=True,exist_ok=True)

def now(): return datetime.now().astimezone().isoformat()
def readj(p,d=None):
    try:return json.loads(p.read_text(encoding='utf-8-sig'))
    except Exception:return d
def writej(p,o):
    t=p.with_suffix(p.suffix+'.tmp'); t.write_text(json.dumps(o,ensure_ascii=False,indent=2),encoding='utf-8'); t.replace(p)
def log(s):
    line=f'[{now()}] {s}'; print(line,flush=True)
    with LOG.open('a',encoding='utf-8') as f:f.write(line+'\n')
def state(status,detail='',extra=None):
    x={'pid':os.getpid(),'updated':now(),'status':status,'detail':detail,'threads':THREADS}
    if extra:x.update(extra)
    writej(STATE,x)
def split_id(plan):
    parts=[]
    for name in ['TRAIN','VALIDATION','SELECTION','TEST','OOS']:
        s=(plan.get('splits') or {}).get(name,{})
        parts.extend([name,str(s.get('start_date')),str(s.get('end_date'))])
    return hashlib.sha256('|'.join(parts).encode()).hexdigest()[:16]
def masks(df,plan):
    dates=pd.to_datetime(df.race_date,errors='coerce').dt.normalize();out={}
    for short,name in [('train','TRAIN'),('val','VALIDATION'),('sel','SELECTION'),('test','TEST'),('oos','OOS')]:
        s=plan['splits'][name];out[short]=dates.between(pd.Timestamp(s['start_date']),pd.Timestamp(s['end_date']),inclusive='both')
    return out
def auc(y,p):
    t=pd.DataFrame({'y':y,'p':p}).dropna()
    if t.empty:return np.nan
    y=t.y.astype(int).to_numpy();p=t.p.astype(float).to_numpy();pos=int((y==1).sum());neg=int((y==0).sum())
    if not pos or not neg:return np.nan
    r=pd.Series(p).rank(method='average').to_numpy();return float((r[y==1].sum()-pos*(pos+1)/2)/(pos*neg))
def ll(y,p):
    y=np.asarray(y,float);p=np.clip(np.asarray(p,float),1e-9,1-1e-9);return float(-np.mean(y*np.log(p)+(1-y)*np.log(1-p)))
def feature_sets(df):
    base=[c for c in ['race_scope_cd','racecourse_cd','distance_m','track_cd','horse_age','sex_cd','carried_weight_kg','frame_no','horse_no','jockey_cd','trainer_cd'] if c in df]
    hist=base+[c for c in ['prior_start_count','days_since_last_run','prior_win_rate','prior_top2_rate','prior_top3_rate','prior_avg_finish_pct','prior_avg_time_diff','prior_avg_last3f','prior_avg_corner4_pct','recent3_time_diff_mean','recent5_time_diff_mean','recent3_finish_pct_mean','recent5_finish_pct_mean','recent3_last3f_mean','recent5_last3f_mean','recent3_corner4_pct_mean','recent5_corner4_pct_mean','same_distance_prior_count','same_distance_prior_avg_time_diff','same_track_prior_count','same_track_prior_avg_time_diff','same_racecourse_prior_count','same_racecourse_prior_avg_time_diff','same_course_surface_prior_count','same_course_surface_prior_avg_time_diff'] if c in df]
    field=hist+[c for c in ['horse_pre_ability_v1','field_strength_v2','field_strength_coverage','ability_vs_field','ability_percentile_in_race','last_field_strength','recent3_field_strength_mean','recent5_field_strength_mean','prior_avg_field_strength','field_strength_trend'] if c in df]
    return {'BASELINE':base,'HISTORICAL':hist,'FIELD_STRENGTH':field}

def run_once():
    src=DATA/'CORE-004_field_strength_v2.csv';plan=readj(PLAN,{}) or {}
    if not src.exists():state('WAITING','CORE-004 missing');return False
    if not plan.get('splits'):state('WAITING','Temporal split plan not ready');return False
    if plan.get('status')=='BLOCKED':state('BLOCKED','Temporal/sample gate blocked',{'blockers':(plan.get('gates') or {}).get('blockers',[])});return False
    sid=split_id(plan);old=readj(DECISION,{}) or {}
    if old.get('status')=='PASS' and old.get('split_id')==sid:
        state('PASS','Universal model current',{'split_id':sid,'champion':old.get('champion')});return True
    try:from catboost import CatBoostClassifier
    except Exception as e:state('BLOCKED',f'catboost unavailable: {e}');return False
    state('RUNNING','Universal model tournament',{'split_id':sid})
    df=pd.read_csv(src,low_memory=False);df['race_date']=pd.to_datetime(df.race_date,errors='coerce');scope=pd.to_numeric(df.race_scope_cd,errors='coerce');df=df[scope.isin([1,2])].copy();sp=masks(df,plan)
    sets=feature_sets(df);cats_all={'race_scope_cd','racecourse_cd','track_cd','sex_cd','jockey_cd','trainer_cd'}
    rows=[];champions={}
    for target in ['label_win','label_top2','label_top3']:
        best=None
        for variant,feats in sets.items():
            parts={n:df[m & df[target].notna()].copy() for n,m in sp.items()}
            if min(map(len,parts.values()))==0:continue
            cats=[c for c in feats if c in cats_all]
            for c in cats:
                for p in parts.values():p[c]=p[c].fillna('MISSING').astype(str)
            model=CatBoostClassifier(loss_function='Logloss',eval_metric='Logloss',iterations=800,depth=6,learning_rate=.04,l2_leaf_reg=6,random_seed=20261004,verbose=False,allow_writing_files=False,thread_count=THREADS)
            model.fit(parts['train'][feats],parts['train'][target],cat_features=cats,eval_set=(parts['val'][feats],parts['val'][target]),early_stopping_rounds=80,use_best_model=True)
            d=MODELS/sid;d.mkdir(parents=True,exist_ok=True);path=d/f'{target}_{variant}.cbm';model.save_model(str(path))
            mets={}
            for label,n in [('VALIDATION','val'),('SELECTION','sel'),('TEST','test'),('OOS','oos')]:
                pred=model.predict_proba(parts[n][feats])[:,1];mets[label]={'rows':len(parts[n]),'logloss':ll(parts[n][target],pred),'auc':auc(parts[n][target],pred)}
                rows.append({'split_id':sid,'target':target,'variant':variant,'split':label,'rows':len(parts[n]),'logloss':mets[label]['logloss'],'auc':mets[label]['auc'],'features':len(feats),'trees':int(model.tree_count_)})
            score=mets['SELECTION']['logloss']
            if best is None or score<best['selection_logloss']:
                best={'variant':variant,'model_path':str(path),'features':len(feats),'selection_logloss':score,'validation':mets['VALIDATION'],'test':mets['TEST'],'oos_report_only':mets['OOS']}
        champions[target]=best
    pd.DataFrame(rows).to_csv(METRICS,index=False,encoding='utf-8-sig')
    ok=all(champions.get(t) for t in ['label_win','label_top2','label_top3'])
    decision={'status':'PASS' if ok else 'BLOCKED','updated':now(),'split_id':sid,'temporal_plan':str(PLAN),'selection_policy':'SELECTION split only; OOS report-only','champion':champions}
    writej(DECISION,decision)
    state('PASS' if ok else 'BLOCKED','Universal model tournament complete',{'split_id':sid,'champion':champions})
    log(f'UNIVERSAL MODEL {decision["status"]} split={sid} champions={champions}')
    return ok

def main():
    log('UNIVERSAL MODEL DIRECTOR START')
    while True:
        try:run_once()
        except Exception:
            err=traceback.format_exc();log(err);state('BLOCKED',err[-1800:])
        time.sleep(INTERVAL)
if __name__=='__main__':main()
