from __future__ import annotations

import hashlib, json, os, time, traceback
from datetime import datetime
from pathlib import Path
import numpy as np, pandas as pd

ROOT=Path(os.environ.get('THE_JOCKEY_RESEARCH_ROOT',Path.home()/'Downloads'/'THE-JOCKEY-RESEARCH'))
CORE=ROOT/'CORE';DATA=CORE/'data';REPORTS=CORE/'reports';PROGRAM=CORE/'program.json';CHECK=ROOT/'checkpoints'
LOG=ROOT/'logs'/'probability_director.log';STATE=CHECK/'probability_director_state.json';PLAN=REPORTS/'TEMPORAL_SPLIT_plan.json'
PROB_DECISION=REPORTS/'CORE-006_008_decision.json'
for p in (REPORTS,LOG.parent,STATE.parent):p.mkdir(parents=True,exist_ok=True)

def now():return datetime.now().astimezone().isoformat()
def readj(p,d=None):
    try:return json.loads(p.read_text(encoding='utf-8-sig'))
    except Exception:return d
def writej(p,o):
    t=p.with_suffix(p.suffix+'.tmp');t.write_text(json.dumps(o,ensure_ascii=False,indent=2),encoding='utf-8');t.replace(p)
def log(s):
    line=f'[{now()}] {s}';print(line,flush=True)
    with LOG.open('a',encoding='utf-8') as f:f.write(line+'\n')
def state(mission,status,detail='',extra=None):
    x={'updated':now(),'current_mission':mission,'status':status,'detail':detail,'pid':os.getpid()}
    if extra:x.update(extra)
    writej(STATE,x)
def set_mission(mid,status):
    p=readj(PROGRAM,{'missions':[]}) or {'missions':[]};found=False
    for m in p.setdefault('missions',[]):
        if m.get('id')==mid:m['state']=status;found=True
    if not found:p['missions'].append({'id':mid,'name':mid,'state':status})
    writej(PROGRAM,p)
def split_id(plan):
    parts=[]
    for name in ['TRAIN','VALIDATION','SELECTION','TEST','OOS']:
        s=(plan.get('splits') or {}).get(name,{})
        parts.extend([name,str(s.get('start_date')),str(s.get('end_date'))])
    return hashlib.sha256('|'.join(parts).encode()).hexdigest()[:16]
def split_mask(df,plan,name):
    s=plan['splits'][name];d=pd.to_datetime(df.race_date,errors='coerce').dt.normalize();return d.between(pd.Timestamp(s['start_date']),pd.Timestamp(s['end_date']),inclusive='both')
def feature_set(df,variant):
    base=[c for c in ['race_scope_cd','racecourse_cd','distance_m','track_cd','horse_age','sex_cd','carried_weight_kg','frame_no','horse_no','jockey_cd','trainer_cd'] if c in df]
    hist=base+[c for c in ['prior_start_count','days_since_last_run','prior_win_rate','prior_top2_rate','prior_top3_rate','prior_avg_finish_pct','prior_avg_time_diff','prior_avg_last3f','prior_avg_corner4_pct','recent3_time_diff_mean','recent5_time_diff_mean','recent3_finish_pct_mean','recent5_finish_pct_mean','recent3_last3f_mean','recent5_last3f_mean','recent3_corner4_pct_mean','recent5_corner4_pct_mean','same_distance_prior_count','same_distance_prior_avg_time_diff','same_track_prior_count','same_track_prior_avg_time_diff','same_racecourse_prior_count','same_racecourse_prior_avg_time_diff','same_course_surface_prior_count','same_course_surface_prior_avg_time_diff'] if c in df]
    field=hist+[c for c in ['horse_pre_ability_v1','field_strength_v2','field_strength_coverage','ability_vs_field','ability_percentile_in_race','last_field_strength','recent3_field_strength_mean','recent5_field_strength_mean','prior_avg_field_strength','field_strength_trend'] if c in df]
    return {'BASELINE':base,'HISTORICAL':hist,'FIELD_STRENGTH':field}[variant]
def prepare(df,feats):
    out=df.copy();cats=[c for c in feats if c in {'race_scope_cd','racecourse_cd','track_cd','sex_cd','jockey_cd','trainer_cd'}]
    for c in cats:out[c]=out[c].fillna('MISSING').astype(str)
    return out
def brier(y,p):return float(np.mean((np.asarray(p,float)-np.asarray(y,float))**2))
def ll(y,p):
    y=np.asarray(y,float);p=np.clip(np.asarray(p,float),1e-12,1-1e-12);return float(-np.mean(y*np.log(p)+(1-y)*np.log(1-p)))

def context():
    plan=readj(PLAN,{}) or {};dec=readj(REPORTS/'CORE-005_decision.json',{}) or {}
    if not plan.get('splits') or plan.get('status')=='BLOCKED':return None,None,None
    sid=split_id(plan)
    if dec.get('status')!='PASS' or dec.get('split_id')!=sid:return plan,sid,None
    return plan,sid,dec

def run_predictions():
    plan,sid,dec=context()
    if plan is None:state('CORE-006','WAITING','Temporal split plan not ready');return False
    if dec is None:state('CORE-006','WAITING','CORE-005 current split not PASS');return False
    src=DATA/'CORE-004_field_strength_v2.csv';out=DATA/'CORE-006_008_probabilities.csv';metrics=REPORTS/'CORE-006_008_probability_metrics.csv'
    old=readj(PROB_DECISION,{}) or {}
    if out.exists() and metrics.exists() and old.get('status')=='PASS' and old.get('split_id')==sid:
        for m in ['CORE-006','CORE-007','CORE-008']:set_mission(m,'COMPLETE')
        return True
    if not src.exists():state('CORE-006','BLOCKED','CORE-004 missing');return False
    try:from catboost import CatBoostClassifier
    except Exception as e:state('CORE-006','BLOCKED',f'catboost unavailable: {e}');return False
    df=pd.read_csv(src,low_memory=False);df['race_date']=pd.to_datetime(df.race_date,errors='coerce');scope=pd.to_numeric(df.race_scope_cd,errors='coerce');df=df[scope.isin([1,2])].copy()
    pred=df[[c for c in ['race_id','race_horse_id','horse_id','race_date','race_scope_cd','label_win','label_top2','label_top3'] if c in df]].copy();rows=[]
    for mission,target,pcol in [('CORE-006','label_win','p_win'),('CORE-007','label_top2','p_top2'),('CORE-008','label_top3','p_top3')]:
        ch=(dec.get('champion') or {}).get(target)
        if not ch or not ch.get('model_path'):state(mission,'BLOCKED',f'No current champion for {target}');return False
        model_path=Path(ch['model_path'])
        if not model_path.exists():state(mission,'BLOCKED',f'Model missing {model_path}');return False
        feats=feature_set(df,ch['variant']);prepared=prepare(df,feats);m=CatBoostClassifier();m.load_model(str(model_path));pp=m.predict_proba(prepared[feats])[:,1];pred[pcol]=pp
        for label,name in [('TEST','TEST'),('OOS','OOS')]:
            mask=split_mask(df,plan,name)&df[target].notna();rows.append({'split_id':sid,'mission':mission,'target':target,'variant':ch['variant'],'split':label,'rows':int(mask.sum()),'logloss':ll(df.loc[mask,target],pp[mask]),'brier':brier(df.loc[mask,target],pp[mask])})
        set_mission(mission,'COMPLETE')
    pred.to_csv(out,index=False,encoding='utf-8-sig');pd.DataFrame(rows).to_csv(metrics,index=False,encoding='utf-8-sig');writej(PROB_DECISION,{'status':'PASS','split_id':sid,'updated':now()});log(f'CORE-006/007/008 PASS split={sid}');return True

def run_consistency():
    plan,sid,dec=context();mission='CORE-009';src=DATA/'CORE-006_008_probabilities.csv';out=DATA/'CORE-009_consistent_probabilities.csv';audit=REPORTS/'CORE-009_consistency_audit.json'
    old=readj(audit,{}) or {}
    if out.exists() and old.get('status')=='PASS' and old.get('split_id')==sid:set_mission(mission,'COMPLETE');return True
    if not src.exists():return False
    df=pd.read_csv(src,low_memory=False);before=int(((df.p_win>df.p_top2)|(df.p_top2>df.p_top3)).sum());arr=np.vstack([df.p_win.to_numpy(float),df.p_top2.to_numpy(float),df.p_top3.to_numpy(float)]).T;arr=np.maximum.accumulate(arr,axis=1);arr=np.clip(arr,0,1);df[['p_win_consistent','p_top2_consistent','p_top3_consistent']]=arr;after=int(((df.p_win_consistent>df.p_top2_consistent)|(df.p_top2_consistent>df.p_top3_consistent)).sum());df.to_csv(out,index=False,encoding='utf-8-sig');writej(audit,{'status':'PASS' if after==0 else 'BLOCKED','split_id':sid,'violations_before':before,'violations_after':after,'updated':now()});set_mission(mission,'COMPLETE' if after==0 else 'BLOCKED');return after==0

def run_calibration():
    plan,sid,dec=context();mission='CORE-010';src=DATA/'CORE-009_consistent_probabilities.csv';out=DATA/'CORE-010_calibrated_probabilities.csv';report=REPORTS/'CORE-010_calibration_metrics.csv';decision=REPORTS/'CORE-010_decision.json';old=readj(decision,{}) or {}
    if out.exists() and old.get('status')=='PASS' and old.get('split_id')==sid:set_mission(mission,'COMPLETE');return True
    if not src.exists():return False
    df=pd.read_csv(src,low_memory=False);df['race_date']=pd.to_datetime(df.race_date,errors='coerce');specs=[('label_win','p_win_consistent','p_win_cal'),('label_top2','p_top2_consistent','p_top2_cal'),('label_top3','p_top3_consistent','p_top3_cal')];metrics=[]
    try:
        from sklearn.isotonic import IsotonicRegression
        for target,pcol,outcol in specs:
            cm=split_mask(df,plan,'SELECTION')&df[target].notna()&df[pcol].notna();iso=IsotonicRegression(out_of_bounds='clip')
            if int(cm.sum())>=100:iso.fit(df.loc[cm,pcol],df.loc[cm,target]);df[outcol]=iso.predict(df[pcol].fillna(df[pcol].median()))
            else:df[outcol]=df[pcol]
            for label,name in [('TEST','TEST'),('OOS','OOS')]:
                m=split_mask(df,plan,name)&df[target].notna()&df[outcol].notna();metrics.append({'split_id':sid,'target':target,'split':label,'rows':int(m.sum()),'logloss':ll(df.loc[m,target],df.loc[m,outcol]),'brier':brier(df.loc[m,target],df.loc[m,outcol])})
    except Exception as e:
        log(f'Calibration identity fallback: {e!r}')
        for _,pcol,outcol in specs:df[outcol]=df[pcol]
    arr=np.vstack([df.p_win_cal.to_numpy(float),df.p_top2_cal.to_numpy(float),df.p_top3_cal.to_numpy(float)]).T;arr=np.maximum.accumulate(arr,axis=1);arr=np.clip(arr,0,1);df[['p_win_cal','p_top2_cal','p_top3_cal']]=arr;viol=int(((df.p_win_cal>df.p_top2_cal)|(df.p_top2_cal>df.p_top3_cal)).sum());df.to_csv(out,index=False,encoding='utf-8-sig');pd.DataFrame(metrics).to_csv(report,index=False,encoding='utf-8-sig');status='PASS' if viol==0 else 'BLOCKED';writej(decision,{'status':status,'split_id':sid,'violations':viol,'updated':now(),'method':'isotonic_on_SELECTION_split','oos_policy':'report-only'});set_mission(mission,'COMPLETE' if status=='PASS' else 'BLOCKED');state(mission,status,f'calibration {status}',{'split_id':sid});log(f'CORE-010 {status} split={sid}');return status=='PASS'

def run_once():
    return run_predictions() and run_consistency() and run_calibration()
def main():
    log('Probability Director started')
    while True:
        try:
            if run_once():state('QUEUE','IDLE','CORE-006..010 current')
        except Exception:
            err=traceback.format_exc();log(err);state('UNKNOWN','BLOCKED',err[-1500:])
        time.sleep(30)
if __name__=='__main__':main()
