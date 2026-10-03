from __future__ import annotations

import hashlib,json,os,sys,time
from datetime import datetime
from pathlib import Path
import numpy as np,pandas as pd
ROOT=Path(os.environ.get('THE_JOCKEY_RESEARCH_ROOT',Path.home()/'Downloads'/'THE-JOCKEY-RESEARCH'));CORE=ROOT/'CORE';DATA=CORE/'data';REPORTS=CORE/'reports';STATE=ROOT/'checkpoints'/'feature_research_director_state.json';LOG=ROOT/'logs'/'feature_research_director.log';SRC=DATA/'CORE-004_field_strength_v2.csv';OUT=DATA/'FEATURE-RESEARCH_candidates.csv';CATALOG=REPORTS/'feature_research_catalog.csv';DECISION=REPORTS/'feature_research_decision.json';PROMOTED=REPORTS/'promoted_feature_contract.json';PLAN=REPORTS/'TEMPORAL_SPLIT_plan.json'
for p in (DATA,REPORTS,STATE.parent,LOG.parent):p.mkdir(parents=True,exist_ok=True)
def now():return datetime.now().astimezone().isoformat()
def log(msg):
 line=f'[{now()}] {msg}';print(line,flush=True)
 with LOG.open('a',encoding='utf-8') as f:f.write(line+'\n')
def savej(p,o):
 t=p.with_suffix(p.suffix+'.tmp');t.write_text(json.dumps(o,ensure_ascii=False,indent=2),encoding='utf-8');t.replace(p)
def readj(p,d=None):
 try:return json.loads(p.read_text(encoding='utf-8-sig'))
 except:return d
def signature(path):
 st=path.stat();return hashlib.sha256(f'{st.st_size}:{st.st_mtime_ns}'.encode()).hexdigest()
def split_id(plan):
 a=[]
 for n in ['TRAIN','VALIDATION','SELECTION','TEST','OOS']:
  s=(plan.get('splits') or {}).get(n,{});a += [n,str(s.get('start_date')),str(s.get('end_date'))]
 return hashlib.sha256('|'.join(a).encode()).hexdigest()[:16]
def mask(df,plan,name):
 s=plan['splits'][name];d=pd.to_datetime(df.race_date,errors='coerce').dt.normalize();return d.between(pd.Timestamp(s['start_date']),pd.Timestamp(s['end_date']),inclusive='both')
def auc_rank(y,score):
 t=pd.DataFrame({'y':y,'s':score}).dropna()
 if t.empty:return float('nan')
 y=t.y.astype(int).to_numpy();s=t.s.astype(float).to_numpy();pos=int((y==1).sum());neg=int((y==0).sum())
 if not pos or not neg:return float('nan')
 r=pd.Series(s).rank(method='average').to_numpy();return float((r[y==1].sum()-pos*(pos+1)/2)/(pos*neg))
def safe_div(a,b):return pd.to_numeric(a,errors='coerce')/pd.to_numeric(b,errors='coerce').replace(0,np.nan)
def generate(df):
 c={};has=lambda *x:all(i in df.columns for i in x)
 if has('recent3_time_diff_mean','recent5_time_diff_mean'):c['form_time_momentum_3v5']=pd.to_numeric(df.recent5_time_diff_mean,errors='coerce')-pd.to_numeric(df.recent3_time_diff_mean,errors='coerce')
 if has('recent3_finish_pct_mean','recent5_finish_pct_mean'):c['form_finish_momentum_3v5']=pd.to_numeric(df.recent5_finish_pct_mean,errors='coerce')-pd.to_numeric(df.recent3_finish_pct_mean,errors='coerce')
 if has('recent3_last3f_mean','recent5_last3f_mean'):c['last3f_momentum_3v5']=pd.to_numeric(df.recent5_last3f_mean,errors='coerce')-pd.to_numeric(df.recent3_last3f_mean,errors='coerce')
 if has('prior_start_count'):c['experience_log1p']=np.log1p(pd.to_numeric(df.prior_start_count,errors='coerce').clip(lower=0))
 if has('days_since_last_run'):
  x=pd.to_numeric(df.days_since_last_run,errors='coerce');c['rest_log1p']=np.log1p(x.clip(lower=0));c['rest_ideal_band']=((x>=14)&(x<=70)).astype(float)
 if has('prior_win_rate','prior_top3_rate'):c['conversion_win_given_top3_proxy']=safe_div(df.prior_win_rate,df.prior_top3_rate)
 if has('prior_top2_rate','prior_top3_rate'):c['conversion_top2_given_top3_proxy']=safe_div(df.prior_top2_rate,df.prior_top3_rate)
 if has('same_distance_prior_count','prior_start_count'):c['distance_experience_share']=safe_div(df.same_distance_prior_count,df.prior_start_count)
 if has('same_track_prior_count','prior_start_count'):c['track_experience_share']=safe_div(df.same_track_prior_count,df.prior_start_count)
 if has('same_racecourse_prior_count','prior_start_count'):c['racecourse_experience_share']=safe_div(df.same_racecourse_prior_count,df.prior_start_count)
 if has('same_course_surface_prior_count','prior_start_count'):c['course_surface_experience_share']=safe_div(df.same_course_surface_prior_count,df.prior_start_count)
 if has('prior_avg_time_diff','same_distance_prior_avg_time_diff'):c['distance_time_diff_edge']=pd.to_numeric(df.prior_avg_time_diff,errors='coerce')-pd.to_numeric(df.same_distance_prior_avg_time_diff,errors='coerce')
 if has('prior_avg_time_diff','same_track_prior_avg_time_diff'):c['track_time_diff_edge']=pd.to_numeric(df.prior_avg_time_diff,errors='coerce')-pd.to_numeric(df.same_track_prior_avg_time_diff,errors='coerce')
 if has('prior_avg_time_diff','same_racecourse_prior_avg_time_diff'):c['racecourse_time_diff_edge']=pd.to_numeric(df.prior_avg_time_diff,errors='coerce')-pd.to_numeric(df.same_racecourse_prior_avg_time_diff,errors='coerce')
 if has('horse_pre_ability_v1','field_strength_v2'):c['ability_field_ratio']=safe_div(df.horse_pre_ability_v1,df.field_strength_v2)
 if has('ability_vs_field','field_strength_coverage'):c['ability_edge_coverage_weighted']=pd.to_numeric(df.ability_vs_field,errors='coerce')*pd.to_numeric(df.field_strength_coverage,errors='coerce')
 if has('prior_avg_field_strength','field_strength_v2'):c['field_step_up']=pd.to_numeric(df.field_strength_v2,errors='coerce')-pd.to_numeric(df.prior_avg_field_strength,errors='coerce')
 if has('last_field_strength','recent5_field_strength_mean'):c['field_strength_short_term_shift']=pd.to_numeric(df.last_field_strength,errors='coerce')-pd.to_numeric(df.recent5_field_strength_mean,errors='coerce')
 return c
def redundancy(df,candidate,existing):
 vals=[];c=pd.to_numeric(candidate,errors='coerce')
 for col in existing:
  x=pd.to_numeric(df[col],errors='coerce');pair=pd.concat([c,x],axis=1).dropna()
  if len(pair)<500:continue
  v=pair.corr(method='spearman').iloc[0,1]
  if pd.notna(v):vals.append(abs(float(v)))
 return max(vals) if vals else 0.0
def run_once():
 if not SRC.exists():savej(STATE,{'updated':now(),'status':'WAITING','reason':'CORE-004 missing','pid':os.getpid()});return False
 plan=readj(PLAN,{}) or {}
 if not plan.get('splits') or plan.get('status')=='BLOCKED':savej(STATE,{'updated':now(),'status':'WAITING','reason':'Temporal plan not ready','pid':os.getpid()});return False
 sid=split_id(plan);sig=signature(SRC);old=readj(DECISION,{}) or {}
 if old.get('data_signature')==sig and old.get('split_id')==sid and old.get('status')=='PASS':savej(STATE,{'updated':now(),'status':'IDLE','detail':'current split already researched','split_id':sid,'pid':os.getpid()});return True
 savej(STATE,{'updated':now(),'status':'RUNNING','split_id':sid,'pid':os.getpid()});df=pd.read_csv(SRC,low_memory=False);df['race_date']=pd.to_datetime(df.race_date,errors='coerce');scope=pd.to_numeric(df.race_scope_cd,errors='coerce');labeled=df.finish_order.notna() if 'finish_order' in df.columns else df.label_win.notna();winner=pd.to_numeric(df.label_win,errors='coerce').fillna(0);safe=labeled.groupby(df.race_id).transform('all')&winner.groupby(df.race_id).transform('sum').eq(1)&scope.isin([1,2]);work=df.loc[safe].copy();candidates=generate(work)
 if not candidates:savej(STATE,{'updated':now(),'status':'BLOCKED','detail':'no formulas','pid':os.getpid()});return False
 existing=[c for c in ['prior_win_rate','prior_top2_rate','prior_top3_rate','prior_avg_finish_pct','prior_avg_time_diff','recent3_time_diff_mean','recent5_time_diff_mean','recent3_finish_pct_mean','recent5_finish_pct_mean','horse_pre_ability_v1','field_strength_v2','ability_vs_field','ability_percentile_in_race','prior_avg_field_strength','field_strength_trend'] if c in work]
 eval_masks={n:mask(work,plan,n) for n in ['VALIDATION','SELECTION','TEST','OOS']};rows=[];promoted=[]
 for name,series in candidates.items():
  s=pd.to_numeric(series,errors='coerce').replace([np.inf,-np.inf],np.nan);coverage=float(s.notna().mean());unique=int(s.nunique(dropna=True));red=redundancy(work,s,existing);decision_metrics=[];reported={}
  for split,m in eval_masks.items():
   for target in ['label_win','label_top2','label_top3']:
    if target not in work:continue
    a=auc_rank(work.loc[m,target],s.loc[m])
    if pd.notna(a):
     a=max(float(a),1-float(a));reported[f'auc_{target}_{split.lower()}']=a
     if split in ('VALIDATION','SELECTION'):decision_metrics.append(a)
  mean_auc=float(np.mean(decision_metrics)) if decision_metrics else float('nan');min_auc=float(np.min(decision_metrics)) if decision_metrics else float('nan');reason=[]
  if coverage<.55:reason.append('LOW_COVERAGE')
  if unique<5:reason.append('LOW_VARIANCE')
  if red>=.98:reason.append('REDUNDANT')
  if not decision_metrics or mean_auc<.515:reason.append('WEAK_SIGNAL')
  if decision_metrics and min_auc<.505:reason.append('UNSTABLE')
  dec='PROMOTE_CANDIDATE' if not reason else 'REJECT'
  if dec=='PROMOTE_CANDIDATE':promoted.append(name)
  rows.append({'split_id':sid,'feature':name,'coverage':coverage,'unique':unique,'max_abs_spearman_existing':red,'selection_mean_abs_auc':mean_auc,'selection_min_abs_auc':min_auc,'decision':dec,'reason':'|'.join(reason) if reason else 'PASS_TRIAGE',**reported});work[name]=s
 pd.DataFrame(rows).sort_values(['decision','selection_mean_abs_auc'],ascending=[True,False]).to_csv(CATALOG,index=False,encoding='utf-8-sig');keep=[c for c in ['race_id','race_horse_id','horse_id','race_date','race_scope_cd','label_win','label_top2','label_top3'] if c in work]+promoted;work[keep].to_csv(OUT,index=False,encoding='utf-8-sig')
 contract={'updated':now(),'status':'PASS','split_id':sid,'data_signature':sig,'source':str(SRC),'safe_rows':int(len(work)),'safe_races':int(work.race_id.nunique()),'candidate_count':len(rows),'promoted_candidate_count':len(promoted),'promoted_candidates':promoted,'policy':{'decision_splits':['VALIDATION','SELECTION'],'report_only_splits':['TEST','OOS'],'targets':['WIN','TOP2','TOP3'],'note':'PROMOTE_CANDIDATE requires later model challenge'}};savej(PROMOTED,contract);savej(DECISION,contract);savej(STATE,{'updated':now(),'status':'IDLE','split_id':sid,'pid':os.getpid(),'promoted_candidate_count':len(promoted)});log(f'FEATURE RESEARCH PASS split={sid} candidates={len(rows)} promoted={len(promoted)}');return True
def main():
 continuous='--once' not in sys.argv;log('Feature Research Director started')
 while True:
  try:run_once()
  except KeyboardInterrupt:return
  except Exception as e:log(f'ERROR {e!r}');savej(STATE,{'updated':now(),'status':'BLOCKED','detail':repr(e),'pid':os.getpid()})
  if not continuous:return
  time.sleep(300)
if __name__=='__main__':main()
