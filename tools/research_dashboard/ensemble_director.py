from __future__ import annotations
import json, os, time
from datetime import datetime
from pathlib import Path
import numpy as np, pandas as pd
ROOT=Path(os.environ.get('THE_JOCKEY_RESEARCH_ROOT',Path.home()/'Downloads'/'THE-JOCKEY-RESEARCH')); CORE=ROOT/'CORE'; DATA=CORE/'data'; REPORTS=CORE/'reports'; CHECK=ROOT/'checkpoints'; STATE=CHECK/'ensemble_director_state.json'; LOG=ROOT/'logs'/'ensemble_director.log'
for p in (REPORTS,CHECK,LOG.parent):p.mkdir(parents=True,exist_ok=True)
def now():return datetime.now().astimezone().isoformat()
def readj(p,d=None):
 try:return json.loads(p.read_text(encoding='utf-8-sig'))
 except:return d
def writej(p,o):p.write_text(json.dumps(o,ensure_ascii=False,indent=2),encoding='utf-8')
def log(s):
 with LOG.open('a',encoding='utf-8') as f:f.write(f'[{now()}] {s}\n')
def ll(y,p):
 y=np.asarray(y,float);p=np.clip(np.asarray(p,float),1e-9,1-1e-9);return float(-np.mean(y*np.log(p)+(1-y)*np.log(1-p)))
def run_once():
 src=DATA/'CORE-004_field_strength_v2.csv'; coredec=REPORTS/'CORE-005_decision.json'; domreg=REPORTS/'domain_model_registry.json'
 if not (src.exists() and coredec.exists() and domreg.exists()):writej(STATE,{'pid':os.getpid(),'updated':now(),'status':'WAITING'});return
 try:from catboost import CatBoostClassifier
 except Exception as e:writej(STATE,{'pid':os.getpid(),'updated':now(),'status':'BLOCKED','detail':repr(e)});return
 df=pd.read_csv(src,low_memory=False);df['race_date']=pd.to_datetime(df.race_date,errors='coerce');df['year']=df.race_date.dt.year
 core=readj(coredec,{}) or {}; dom=readj(domreg,{}) or {}; rows=[]; ensreg={}
 common_feats=[c for c in ['race_scope_cd','racecourse_cd','distance_m','track_cd','horse_age','sex_cd','carried_weight_kg','frame_no','horse_no','jockey_cd','trainer_cd','prior_start_count','days_since_last_run','prior_win_rate','prior_top2_rate','prior_top3_rate','prior_avg_finish_pct','prior_avg_time_diff','recent5_time_diff_mean','recent5_finish_pct_mean','horse_pre_ability_v1','field_strength_v2','field_strength_coverage','ability_vs_field','ability_percentile_in_race','last_field_strength','recent3_field_strength_mean','recent5_field_strength_mean','prior_avg_field_strength','field_strength_trend'] if c in df]
 cats=[c for c in common_feats if c in ['race_scope_cd','racecourse_cd','track_cd','sex_cd','jockey_cd','trainer_cd']]
 for c in cats:df[c]=df[c].fillna('MISSING').astype(str)
 for target in ['label_win','label_top2','label_top3']:
  ch=(core.get('champion') or {}).get(target); 
  if not ch:continue
  common_path=CORE/'models'/'CORE-005'/f"{target}_{ch['variant']}.cbm"
  if not common_path.exists():continue
  cm=CatBoostClassifier();cm.load_model(str(common_path))
  for scope,dname in [(1,'JRA'),(2,'NAR')]:
   info=(dom.get(dname) or {}).get(target); 
   if not info or not Path(info['model']).exists():continue
   dm=CatBoostClassifier();dm.load_model(info['model']); part=df[(df.race_scope_cd==scope)&(df.year.isin([2024,2025,2026]))&df[target].notna()].copy()
   if part.empty:continue
   cp=cm.predict_proba(part[common_feats])[:,1]
   dfeats=dm.feature_names_; dp=dm.predict_proba(part[dfeats])[:,1]
   best={'w_domain':0.0,'val_logloss':1e9}
   val=part.year==2024
   if val.sum()<100:continue
   for w in np.linspace(0,1,11):
    p=w*dp+(1-w)*cp; score=ll(part.loc[val,target],p[val])
    if score<best['val_logloss']:best={'w_domain':float(w),'val_logloss':score}
   p=best['w_domain']*dp+(1-best['w_domain'])*cp; mets={}
   for yr,label in [(2025,'TEST_2025'),(2026,'OOS_2026')]:
    m=part.year==yr
    if m.sum():mets[label]={'rows':int(m.sum()),'logloss':ll(part.loc[m,target],p[m]),'common_logloss':ll(part.loc[m,target],cp[m]),'domain_logloss':ll(part.loc[m,target],dp[m])}
   ensreg.setdefault(dname,{})[target]={'weight_domain':best['w_domain'],'weight_common':1-best['w_domain'],'validation_logloss':best['val_logloss'],'metrics':mets,'updated':now()};rows.append({'domain':dname,'target':target,'w_domain':best['w_domain'],'val_logloss':best['val_logloss'],**{f'{s}_{k}':v for s,d in mets.items() for k,v in d.items()}})
 pd.DataFrame(rows).to_csv(REPORTS/'ENSEMBLE_metrics.csv',index=False,encoding='utf-8-sig');writej(REPORTS/'ensemble_registry.json',ensreg);writej(STATE,{'pid':os.getpid(),'updated':now(),'status':'PASS','ensembles':len(rows)})
def main():
 log('ENSEMBLE DIRECTOR START')
 while True:
  try:run_once()
  except Exception as e:log(repr(e));writej(STATE,{'pid':os.getpid(),'updated':now(),'status':'BLOCKED','detail':repr(e)})
  time.sleep(900)
if __name__=='__main__':main()
