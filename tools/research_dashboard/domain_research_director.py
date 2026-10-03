from __future__ import annotations
import hashlib,json,os,time,traceback
from datetime import datetime
from pathlib import Path
import numpy as np,pandas as pd
ROOT=Path(os.environ.get('THE_JOCKEY_RESEARCH_ROOT',Path.home()/'Downloads'/'THE-JOCKEY-RESEARCH'));CORE=ROOT/'CORE';DATA=CORE/'data';REPORTS=CORE/'reports';MODELS=CORE/'models'/'DOMAIN';CHECK=ROOT/'checkpoints';LOG=ROOT/'logs'/'domain_research_director.log';STATE=CHECK/'domain_research_director_state.json';PLAN=REPORTS/'TEMPORAL_SPLIT_plan.json'
THREADS=max(1,int(os.environ.get('THE_JOCKEY_MODEL_THREADS',str(os.cpu_count() or 4))))
for p in (REPORTS,MODELS,CHECK,LOG.parent):p.mkdir(parents=True,exist_ok=True)
def now():return datetime.now().astimezone().isoformat()
def writej(p,o):
 t=p.with_suffix(p.suffix+'.tmp');t.write_text(json.dumps(o,ensure_ascii=False,indent=2),encoding='utf-8');t.replace(p)
def readj(p,d=None):
 try:return json.loads(p.read_text(encoding='utf-8-sig'))
 except:return d
def log(s):
 with LOG.open('a',encoding='utf-8') as f:f.write(f'[{now()}] {s}\n')
def sid(plan):
 a=[]
 for n in ['TRAIN','VALIDATION','SELECTION','TEST','OOS']:
  s=(plan.get('splits') or {}).get(n,{});a += [n,str(s.get('start_date')),str(s.get('end_date'))]
 return hashlib.sha256('|'.join(a).encode()).hexdigest()[:16]
def mask(df,plan,name):
 s=plan['splits'][name];d=pd.to_datetime(df.race_date,errors='coerce').dt.normalize();return d.between(pd.Timestamp(s['start_date']),pd.Timestamp(s['end_date']),inclusive='both')
def auc(y,p):
 t=pd.DataFrame({'y':y,'p':p}).dropna();y=t.y.astype(int).to_numpy();p=t.p.to_numpy();n1=(y==1).sum();n0=(y==0).sum()
 if not n1 or not n0:return np.nan
 r=pd.Series(p).rank().to_numpy();return float((r[y==1].sum()-n1*(n1+1)/2)/(n1*n0))
def ll(y,p):
 y=np.asarray(y,float);p=np.clip(np.asarray(p,float),1e-9,1-1e-9);return float(-np.mean(y*np.log(p)+(1-y)*np.log(1-p)))
def run_once():
 src=DATA/'CORE-004_field_strength_v2.csv';plan=readj(PLAN,{}) or {}
 if not src.exists() or not plan.get('splits'):writej(STATE,{'pid':os.getpid(),'updated':now(),'status':'WAITING'});return
 if plan.get('status')=='BLOCKED':writej(STATE,{'pid':os.getpid(),'updated':now(),'status':'BLOCKED','detail':'Temporal/sample gate blocked'});return
 current=sid(plan);reg_path=REPORTS/'domain_model_registry.json';old=readj(reg_path,{}) or {}
 if old.get('split_id')==current and old.get('status')=='PASS':writej(STATE,{'pid':os.getpid(),'updated':now(),'status':'PASS','split_id':current,'models':old.get('model_count',0)});return
 try:from catboost import CatBoostClassifier
 except Exception as e:writej(STATE,{'pid':os.getpid(),'updated':now(),'status':'BLOCKED','detail':repr(e)});return
 df=pd.read_csv(src,low_memory=False);df['race_date']=pd.to_datetime(df.race_date,errors='coerce');scope_num=pd.to_numeric(df.race_scope_cd,errors='coerce');df=df[scope_num.isin([1,2])].copy()
 feats=[c for c in ['racecourse_cd','distance_m','track_cd','horse_age','sex_cd','carried_weight_kg','jockey_cd','trainer_cd','prior_start_count','days_since_last_run','prior_win_rate','prior_top2_rate','prior_top3_rate','recent5_time_diff_mean','recent5_finish_pct_mean','ability_vs_field','field_strength_v2','prior_avg_field_strength'] if c in df];cats=[c for c in feats if c in ['racecourse_cd','track_cd','sex_cd','jockey_cd','trainer_cd']]
 rows=[];registry={'status':'PASS','split_id':current,'updated':now(),'domains':{}}
 trainmask=mask(df,plan,'TRAIN');valmask=mask(df,plan,'VALIDATION');selmask=mask(df,plan,'SELECTION');testmask=mask(df,plan,'TEST');oosmask=mask(df,plan,'OOS')
 scope_num=pd.to_numeric(df.race_scope_cd,errors='coerce')
 for scope,name in [(1,'JRA'),(2,'NAR')]:
  dm=scope_num.eq(scope);registry['domains'][name]={}
  for target in ['label_win','label_top2','label_top3']:
   parts={'train':df[dm&trainmask&df[target].notna()].copy(),'val':df[dm&valmask&df[target].notna()].copy(),'sel':df[dm&selmask&df[target].notna()].copy(),'test':df[dm&testmask&df[target].notna()].copy(),'oos':df[dm&oosmask&df[target].notna()].copy()}
   if len(parts['train'])<1000 or min(len(parts['val']),len(parts['sel']),len(parts['test']),len(parts['oos']))<100:continue
   for c in cats:
    for p in parts.values():p[c]=p[c].fillna('MISSING').astype(str)
   m=CatBoostClassifier(iterations=600,depth=6,learning_rate=.04,l2_leaf_reg=6,loss_function='Logloss',eval_metric='Logloss',verbose=False,random_seed=20261004,allow_writing_files=False,thread_count=THREADS)
   m.fit(parts['train'][feats],parts['train'][target],cat_features=cats,eval_set=(parts['val'][feats],parts['val'][target]),early_stopping_rounds=60,use_best_model=True)
   d=MODELS/current;d.mkdir(parents=True,exist_ok=True);path=d/f'{name}_{target}.cbm';m.save_model(str(path));metrics={}
   for label,k in [('SELECTION','sel'),('TEST','test'),('OOS','oos')]:
    p=parts[k];pr=m.predict_proba(p[feats])[:,1];metrics[label]={'rows':len(p),'logloss':ll(p[target],pr),'auc':auc(p[target],pr)}
   rows.append({'split_id':current,'domain':name,'target':target,**{f'{s}_{k}':v for s,dct in metrics.items() for k,v in dct.items()}});registry['domains'][name][target]={'model':str(path),'metrics':metrics,'updated':now()}
 registry['model_count']=len(rows);pd.DataFrame(rows).to_csv(REPORTS/'DOMAIN_metrics.csv',index=False,encoding='utf-8-sig');writej(reg_path,registry);writej(STATE,{'pid':os.getpid(),'updated':now(),'status':'PASS','split_id':current,'models':len(rows)});log(f'DOMAIN PASS split={current} models={len(rows)}')
def main():
 log('DOMAIN DIRECTOR START')
 while True:
  try:run_once()
  except Exception:
   e=traceback.format_exc();log(e);writej(STATE,{'pid':os.getpid(),'updated':now(),'status':'BLOCKED','detail':e[-1600:]})
  time.sleep(300)
if __name__=='__main__':main()
