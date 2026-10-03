from __future__ import annotations
import json, os, time
from datetime import datetime
from pathlib import Path
import numpy as np, pandas as pd
ROOT=Path(os.environ.get('THE_JOCKEY_RESEARCH_ROOT',Path.home()/'Downloads'/'THE-JOCKEY-RESEARCH')); CORE=ROOT/'CORE'; DATA=CORE/'data'; REPORTS=CORE/'reports'; MODELS=CORE/'models'/'DOMAIN'; CHECK=ROOT/'checkpoints'; LOG=ROOT/'logs'/'domain_research_director.log'; STATE=CHECK/'domain_research_director_state.json'
for p in (REPORTS,MODELS,CHECK,LOG.parent):p.mkdir(parents=True,exist_ok=True)
def now():return datetime.now().astimezone().isoformat()
def writej(p,o):p.write_text(json.dumps(o,ensure_ascii=False,indent=2),encoding='utf-8')
def readj(p,d=None):
 try:return json.loads(p.read_text(encoding='utf-8-sig'))
 except:return d
def log(s):
 with LOG.open('a',encoding='utf-8') as f:f.write(f'[{now()}] {s}\n')
def auc(y,p):
 t=pd.DataFrame({'y':y,'p':p}).dropna(); y=t.y.astype(int).to_numpy(); p=t.p.to_numpy(); n1=(y==1).sum(); n0=(y==0).sum()
 if not n1 or not n0:return np.nan
 r=pd.Series(p).rank().to_numpy();return float((r[y==1].sum()-n1*(n1+1)/2)/(n1*n0))
def ll(y,p):
 y=np.asarray(y,float);p=np.clip(np.asarray(p,float),1e-9,1-1e-9);return float(-np.mean(y*np.log(p)+(1-y)*np.log(1-p)))
def run_once():
 src=DATA/'CORE-004_field_strength_v2.csv'; dec=REPORTS/'CORE-005_decision.json'
 if not src.exists() or not dec.exists():writej(STATE,{'pid':os.getpid(),'updated':now(),'status':'WAITING'});return
 try:from catboost import CatBoostClassifier
 except Exception as e:writej(STATE,{'pid':os.getpid(),'updated':now(),'status':'BLOCKED','detail':repr(e)});return
 df=pd.read_csv(src,low_memory=False);df['race_date']=pd.to_datetime(df.race_date,errors='coerce');df['year']=df.race_date.dt.year
 feats=[c for c in ['racecourse_cd','distance_m','track_cd','horse_age','sex_cd','carried_weight_kg','jockey_cd','trainer_cd','prior_start_count','days_since_last_run','prior_win_rate','prior_top2_rate','prior_top3_rate','recent5_time_diff_mean','recent5_finish_pct_mean','ability_vs_field','field_strength_v2','prior_avg_field_strength'] if c in df]
 cats=[c for c in feats if c in ['racecourse_cd','track_cd','sex_cd','jockey_cd','trainer_cd']]
 rows=[];registry=readj(REPORTS/'domain_model_registry.json',{}) or {}
 for scope,name in [(1,'JRA'),(2,'NAR')]:
  dd=df[df.race_scope_cd==scope].copy()
  tr=dd[dd.year.between(2017,2022)];va=dd[dd.year==2023];te=dd[dd.year==2025];oo=dd[dd.year==2026]
  for c in cats:
   for p in (tr,va,te,oo):p[c]=p[c].fillna('MISSING').astype(str)
  for target in ['label_win','label_top2','label_top3']:
   a=tr[tr[target].notna()];b=va[va[target].notna()];
   if len(a)<1000 or len(b)<100:continue
   m=CatBoostClassifier(iterations=500,depth=6,learning_rate=.04,l2_leaf_reg=6,loss_function='Logloss',verbose=False,random_seed=20261004,allow_writing_files=False)
   m.fit(a[feats],a[target],cat_features=cats,eval_set=(b[feats],b[target]),early_stopping_rounds=60,use_best_model=True)
   path=MODELS/f'{name}_{target}.cbm';m.save_model(str(path));metrics={}
   for split,p in [('TEST_2025',te),('OOS_2026',oo)]:
    p=p[p[target].notna()];pr=m.predict_proba(p[feats])[:,1];metrics[split]={'rows':len(p),'logloss':ll(p[target],pr),'auc':auc(p[target],pr)}
   rows.append({'domain':name,'target':target,**{f'{s}_{k}':v for s,d in metrics.items() for k,v in d.items()}});registry.setdefault(name,{})[target]={'model':str(path),'metrics':metrics,'updated':now()}
 pd.DataFrame(rows).to_csv(REPORTS/'DOMAIN_metrics.csv',index=False,encoding='utf-8-sig');writej(REPORTS/'domain_model_registry.json',registry);writej(STATE,{'pid':os.getpid(),'updated':now(),'status':'PASS','models':len(rows)})
def main():
 log('DOMAIN DIRECTOR START')
 while True:
  try:run_once()
  except Exception as e:log(repr(e));writej(STATE,{'pid':os.getpid(),'updated':now(),'status':'BLOCKED','detail':repr(e)})
  time.sleep(900)
if __name__=='__main__':main()
