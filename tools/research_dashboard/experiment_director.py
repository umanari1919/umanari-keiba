from __future__ import annotations

import json, os, time, traceback
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(os.environ.get('THE_JOCKEY_RESEARCH_ROOT', Path.home()/'Downloads'/'THE-JOCKEY-RESEARCH'))
CORE = ROOT/'CORE'; DATA = CORE/'data'; REPORTS = CORE/'reports'; MODELS = CORE/'models'/'EXPERIMENTS'
CHECK = ROOT/'checkpoints'; LOG = ROOT/'logs'/'experiment_director.log'; STATE = CHECK/'experiment_director_state.json'
LEDGER = REPORTS/'EXPERIMENT_ledger.csv'; REGISTRY = REPORTS/'EXPERIMENT_registry.json'
INTERVAL = int(os.environ.get('THE_JOCKEY_EXPERIMENT_INTERVAL','300'))
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
    x={'pid':os.getpid(),'updated':now(),'status':status,'detail':detail}
    if extra:x.update(extra)
    writej(STATE,x)
def ll(y,p):
    y=np.asarray(y,float); p=np.clip(np.asarray(p,float),1e-9,1-1e-9)
    return float(-np.mean(y*np.log(p)+(1-y)*np.log(1-p)))
def auc(y,p):
    t=pd.DataFrame({'y':y,'p':p}).dropna()
    if t.empty:return np.nan
    yv=t.y.astype(int).to_numpy(); pv=t.p.astype(float).to_numpy(); pos=int((yv==1).sum()); neg=int((yv==0).sum())
    if pos==0 or neg==0:return np.nan
    r=pd.Series(pv).rank(method='average').to_numpy()
    return float((r[yv==1].sum()-pos*(pos+1)/2)/(pos*neg))

def feature_sets(df):
    base=[c for c in ['race_scope_cd','racecourse_cd','distance_m','track_cd','horse_age','sex_cd','carried_weight_kg','frame_no','horse_no','jockey_cd','trainer_cd'] if c in df]
    hist=base+[c for c in ['prior_start_count','days_since_last_run','prior_win_rate','prior_top2_rate','prior_top3_rate','prior_avg_finish_pct','prior_avg_time_diff','prior_avg_last3f','prior_avg_corner4_pct','recent3_time_diff_mean','recent5_time_diff_mean','recent3_finish_pct_mean','recent5_finish_pct_mean','recent3_last3f_mean','recent5_last3f_mean','recent3_corner4_pct_mean','recent5_corner4_pct_mean','same_distance_prior_count','same_distance_prior_avg_time_diff','same_track_prior_count','same_track_prior_avg_time_diff','same_racecourse_prior_count','same_racecourse_prior_avg_time_diff','same_course_surface_prior_count','same_course_surface_prior_avg_time_diff'] if c in df]
    field=hist+[c for c in ['horse_pre_ability_v1','field_strength_v2','field_strength_coverage','ability_vs_field','ability_percentile_in_race','last_field_strength','recent3_field_strength_mean','recent5_field_strength_mean','prior_avg_field_strength','field_strength_trend'] if c in df]
    compact=[c for c in field if c not in {'frame_no','horse_no'}]
    return {'BASE':base,'HIST':hist,'FIELD':field,'COMPACT':compact}

def candidate_space():
    cfgs=[('D4_LR06',4,.06,4,600),('D5_LR04',5,.04,5,800),('D6_LR03',6,.03,8,1000),('D7_LR025',7,.025,10,1100),('D8_LR02',8,.02,12,1200),('D6_REG15',6,.03,15,1000)]
    out=[]
    for target in ['label_win','label_top2','label_top3']:
        for fset in ['HIST','FIELD','COMPACT']:
            for name,depth,lr,l2,iters in cfgs:
                for seed in [20261004,20261041,20261103]:out.append({'target':target,'feature_set':fset,'config':name,'depth':depth,'lr':lr,'l2':l2,'iters':iters,'seed':seed})
    return out
def completed_keys():
    if not LEDGER.exists():return set()
    try:
        d=pd.read_csv(LEDGER);return set(d['experiment_key'].astype(str)) if 'experiment_key' in d else set()
    except Exception:return set()
def key(c):return f"{c['target']}|{c['feature_set']}|{c['config']}|{c['seed']}"
def append_ledger(row):pd.DataFrame([row]).to_csv(LEDGER,mode='a',header=not LEDGER.exists(),index=False,encoding='utf-8-sig')
def run_one():
    src=DATA/'CORE-004_field_strength_v2.csv'
    if not src.exists():state('WAITING','CORE-004 missing');return False
    try:from catboost import CatBoostClassifier
    except Exception as e:state('BLOCKED',f'catboost unavailable: {e}');return False
    done=completed_keys();space=candidate_space();cand=next((c for c in space if key(c) not in done),None)
    if cand is None:state('COMPLETE','Experiment queue exhausted',{'completed':len(done),'total':len(space)});return True
    state('RUNNING',key(cand),{'completed':len(done),'total':len(space)})
    df=pd.read_csv(src,low_memory=False);df['race_date']=pd.to_datetime(df.race_date,errors='coerce');df['year']=df.race_date.dt.year;df=df[df.race_scope_cd.isin([1,2])].copy();sets=feature_sets(df);feats=sets[cand['feature_set']];target=cand['target'];cats=[c for c in feats if c in {'race_scope_cd','racecourse_cd','track_cd','sex_cd','jockey_cd','trainer_cd'}]
    train=df[df.year.between(2017,2022)&df[target].notna()].copy();val=df[(df.year==2023)&df[target].notna()].copy();sel=df[(df.year==2024)&df[target].notna()].copy();test=df[(df.year==2025)&df[target].notna()].copy();oos=df[(df.year==2026)&df[target].notna()].copy()
    if min(len(train),len(val),len(sel),len(test),len(oos))==0:append_ledger({'experiment_key':key(cand),'status':'REJECT_EMPTY_SPLIT','updated':now(),**cand});return False
    for c in cats:
        for part in (train,val,sel,test,oos):part[c]=part[c].fillna('MISSING').astype(str)
    m=CatBoostClassifier(loss_function='Logloss',eval_metric='Logloss',iterations=cand['iters'],depth=cand['depth'],learning_rate=cand['lr'],l2_leaf_reg=cand['l2'],random_seed=cand['seed'],verbose=False,allow_writing_files=False)
    m.fit(train[feats],train[target],cat_features=cats,eval_set=(val[feats],val[target]),early_stopping_rounds=100,use_best_model=True)
    metrics={}
    for label,part in [('SELECT_2024',sel),('TEST_2025',test),('OOS_2026',oos)]:
        p=m.predict_proba(part[feats])[:,1];metrics[label]={'rows':len(part),'logloss':ll(part[target],p),'auc':auc(part[target],p)}
    registry=readj(REGISTRY,{'targets':{}}) or {'targets':{}};t=registry.setdefault('targets',{}).setdefault(target,{});champion=t.get('champion');promote=champion is None or metrics['SELECT_2024']['logloss']<champion['select_2024_logloss']-0.0005;model_path=''
    if promote:
        outdir=MODELS/target;outdir.mkdir(parents=True,exist_ok=True);model_path=str(outdir/(key(cand).replace('|','_')+'.cbm'));m.save_model(model_path);t['champion']={'experiment_key':key(cand),'model_path':model_path,'feature_set':cand['feature_set'],'features':feats,'select_2024_logloss':metrics['SELECT_2024']['logloss'],'test_2025':metrics['TEST_2025'],'oos_2026_report_only':metrics['OOS_2026'],'updated':now()};writej(REGISTRY,registry)
    row={'experiment_key':key(cand),'status':'PROMOTE' if promote else 'KEEP','updated':now(),**cand,'trees':int(m.tree_count_),'features':len(feats),'select_2024_logloss':metrics['SELECT_2024']['logloss'],'select_2024_auc':metrics['SELECT_2024']['auc'],'test_2025_logloss':metrics['TEST_2025']['logloss'],'test_2025_auc':metrics['TEST_2025']['auc'],'oos_2026_logloss_report_only':metrics['OOS_2026']['logloss'],'oos_2026_auc_report_only':metrics['OOS_2026']['auc'],'model_path':model_path}
    append_ledger(row);log(f"EXPERIMENT {row['status']} {row['experiment_key']} select2024={row['select_2024_logloss']:.6f}");done.add(key(cand));state('RUNNING','Next experiment queued',{'completed':len(done),'total':len(space),'last':row['experiment_key'],'last_result':row['status']});return False
def main():
    log('EXPERIMENT DIRECTOR START')
    while True:
        try:run_one()
        except Exception:
            err=traceback.format_exc();log(err);state('BLOCKED',err[-1500:])
        time.sleep(max(60,INTERVAL))
if __name__=='__main__':main()
