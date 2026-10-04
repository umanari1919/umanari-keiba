from __future__ import annotations

import json, os, time, traceback
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(os.environ.get('THE_JOCKEY_RESEARCH_ROOT', Path.home()/'Downloads'/'THE-JOCKEY-RESEARCH'))
CORE = ROOT/'CORE'; DATA = CORE/'data'; REPORTS = CORE/'reports'; CHECK = ROOT/'checkpoints'
LOG = ROOT/'logs'/'research_director.log'; STATE = CHECK/'research_director_state.json'; PROGRAM = CORE/'program.json'
SRC = DATA/'CORE-003B_historical_features.csv'; OUT = DATA/'CORE-004_field_strength_v2.csv'
AUDIT = REPORTS/'CORE-004_field_strength_audit.json'; METRICS = REPORTS/'CORE-004_field_strength_metrics.csv'
INTERVAL = max(30, int(os.environ.get('THE_JOCKEY_RESEARCH_INTERVAL','60')))
for p in (DATA,REPORTS,CHECK,LOG.parent): p.mkdir(parents=True,exist_ok=True)

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
    x={'pid':os.getpid(),'updated':now(),'status':status,'current_mission':'CORE-004','detail':detail,'scope':'FIELD_STRENGTH_ONLY'}
    if extra:x.update(extra)
    writej(STATE,x)
def set_mission(status):
    p=readj(PROGRAM,{'missions':[]}) or {'missions':[]}; found=False
    for m in p.setdefault('missions',[]):
        if m.get('id')=='CORE-004': m['state']=status; found=True
    if not found:p['missions'].append({'id':'CORE-004','name':'Field Strength v2','state':status})
    writej(PROGRAM,p)
def inv_time(x):
    x=pd.to_numeric(x,errors='coerce').clip(-8,8); return 1/(1+np.exp(x))
def auc(y,s):
    t=pd.DataFrame({'y':y,'s':s}).dropna()
    if t.empty:return np.nan
    y=t.y.astype(int).to_numpy();s=t.s.astype(float).to_numpy();p=int((y==1).sum());n=int((y==0).sum())
    if not p or not n:return np.nan
    r=pd.Series(s).rank(method='average').to_numpy(); return float((r[y==1].sum()-p*(p+1)/2)/(p*n))
def source_sig():
    if not SRC.exists():return None
    st=SRC.stat();return f'{st.st_size}:{st.st_mtime_ns}'
def run_once():
    if not SRC.exists(): state('WAITING',f'missing {SRC}'); set_mission('BLOCKED'); return False
    sig=source_sig(); old=readj(AUDIT,{}) or {}
    if OUT.exists() and old.get('source_signature')==sig and old.get('first_start_field_strength_leaks')==0:
        state('PASS','Field Strength current',{'rows':old.get('rows'),'races':old.get('races')}); set_mission('COMPLETE'); return True
    state('RUNNING','Building Field Strength v2'); set_mission('RUNNING'); log('CORE-004 START')
    df=pd.read_csv(SRC,low_memory=False); df['race_date']=pd.to_datetime(df.race_date,errors='raise')
    comps=pd.DataFrame(index=df.index)
    for c in ['prior_win_rate','prior_top2_rate','prior_top3_rate','prior_avg_finish_pct','prior_avg_corner4_pct']:
        if c in df: comps[c]=pd.to_numeric(df[c],errors='coerce').clip(0,1)
    if 'prior_avg_time_diff' in df: comps['time_diff_score']=inv_time(df['prior_avg_time_diff'])
    if 'recent5_time_diff_mean' in df: comps['recent_time_score']=inv_time(df['recent5_time_diff_mean'])
    if 'recent5_finish_pct_mean' in df: comps['recent_finish_score']=pd.to_numeric(df['recent5_finish_pct_mean'],errors='coerce').clip(0,1)
    df['ability_component_count']=comps.notna().sum(axis=1); df['horse_pre_ability_v1']=comps.mean(axis=1,skipna=True)
    df.loc[df['ability_component_count'].eq(0),'horse_pre_ability_v1']=np.nan
    valid=df['horse_pre_ability_v1'].notna().astype(int); value=df['horse_pre_ability_v1'].fillna(0.0)
    race_sum=value.groupby(df['race_id']).transform('sum'); race_count=valid.groupby(df['race_id']).transform('sum')
    opp_sum=race_sum-value; opp_count=race_count-valid; runners=df.groupby('race_id')['race_horse_id'].transform('count')
    df['field_strength_v2']=opp_sum/opp_count.replace(0,np.nan); df['field_strength_known_opponents']=opp_count
    df['field_strength_coverage']=opp_count/(runners-1).replace(0,np.nan); df['ability_vs_field']=df['horse_pre_ability_v1']-df['field_strength_v2']
    df['ability_rank_in_race']=df.groupby('race_id')['horse_pre_ability_v1'].rank(method='average',ascending=False)
    df['ability_percentile_in_race']=df.groupby('race_id')['horse_pre_ability_v1'].rank(method='average',pct=True,ascending=True)
    df=df.sort_values(['horse_id','race_date','race_id','race_horse_id']).reset_index(drop=True); g=df.groupby('horse_id',sort=False)
    df['last_field_strength']=g['field_strength_v2'].shift(1); shifted=g['field_strength_v2'].shift(1); tmp=pd.DataFrame({'horse_id':df.horse_id,'v':shifted})
    for w in (3,5):df[f'recent{w}_field_strength_mean']=tmp.groupby('horse_id',sort=False)['v'].transform(lambda x:x.rolling(w,min_periods=1).mean())
    v=df['field_strength_v2'].notna().astype(int); x=df['field_strength_v2'].fillna(0.0); cnt=v.groupby(df.horse_id).cumsum()-v; sm=x.groupby(df.horse_id).cumsum()-x
    df['prior_avg_field_strength']=sm/cnt.replace(0,np.nan); df['field_strength_trend']=df['last_field_strength']-df['recent5_field_strength_mean']
    first=pd.to_numeric(df.get('prior_start_count'),errors='coerce').fillna(0).eq(0); hist=['last_field_strength','recent3_field_strength_mean','recent5_field_strength_mean','prior_avg_field_strength','field_strength_trend']
    leaks={c:int(df.loc[first,c].notna().sum()) for c in hist}; leak_count=sum(leaks.values())
    rows=[]
    for signal in ['horse_pre_ability_v1','ability_vs_field','field_strength_v2','prior_avg_field_strength']:
        score=-df[signal] if signal=='field_strength_v2' else df[signal]
        for target in ['label_win','label_top2','label_top3']:
            if target in df: rows.append({'signal':signal,'target':target,'auc_all_available':auc(df[target],score)})
    pd.DataFrame(rows).to_csv(METRICS,index=False,encoding='utf-8-sig'); df.to_csv(OUT,index=False,encoding='utf-8-sig')
    audit={'source_signature':sig,'rows':int(len(df)),'races':int(df.race_id.nunique()),'horses':int(df.horse_id.nunique()),'generated_features':13,'first_start_field_strength_leaks':int(leak_count),'first_start_leak_detail':leaks,'coverage':{'horse_pre_ability':float(df.horse_pre_ability_v1.notna().mean()),'field_strength':float(df.field_strength_v2.notna().mean()),'ability_vs_field':float(df.ability_vs_field.notna().mean()),'historical_field_strength':float(df.prior_avg_field_strength.notna().mean())},'note':'CORE-005 model selection is exclusively owned by universal_model_director.py'}
    writej(AUDIT,audit)
    if leak_count: state('BLOCKED',f'leakage={leak_count}',audit); set_mission('BLOCKED'); log(f'CORE-004 BLOCKED leakage={leak_count}'); return False
    state('PASS','Field Strength v2 ready',audit); set_mission('COMPLETE'); log('CORE-004 PASS'); return True

def main():
    log('RESEARCH DIRECTOR START — FIELD STRENGTH ONLY')
    while True:
        try:run_once()
        except Exception:
            err=traceback.format_exc();log(err);state('BLOCKED',err[-1800:])
        time.sleep(INTERVAL)
if __name__=='__main__':main()
