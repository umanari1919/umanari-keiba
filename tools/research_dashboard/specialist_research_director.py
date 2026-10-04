from __future__ import annotations

import hashlib,json,os,time,traceback
from datetime import datetime
from pathlib import Path
import numpy as np,pandas as pd

ROOT=Path(os.environ.get('THE_JOCKEY_RESEARCH_ROOT',Path.home()/'Downloads'/'THE-JOCKEY-RESEARCH'))
DATA=ROOT/'CORE'/'data';REPORTS=ROOT/'CORE'/'reports';CHECK=ROOT/'checkpoints';CONTRACT=ROOT/'CORE'/'contracts'/'specialist_segments.json';PROPOSAL=ROOT/'CORE'/'contracts'/'specialist_segments.proposal.json';SRC=DATA/'CORE-004_field_strength_v2.csv';PLAN=REPORTS/'TEMPORAL_SPLIT_plan.json';BIND=REPORTS/'RESEARCH_EXECUTION_bindings.json';OUT=REPORTS/'SPECIALIST_metrics.csv';STATE=CHECK/'specialist_research_director_state.json';INTERVAL=max(120,int(os.environ.get('THE_JOCKEY_SPECIALIST_INTERVAL','300')))
SPECIALIST_KINDS=['JRA_MORNING','DEBUT_SPECIALIST','OBSTACLE_SPECIALIST','NAR_TRANSFER_SPECIALIST']
for p in (REPORTS,CHECK,CONTRACT.parent):p.mkdir(parents=True,exist_ok=True)

def now():return datetime.now().astimezone().isoformat()
def readj(p,d=None):
 try:return json.loads(Path(p).read_text(encoding='utf-8-sig'))
 except Exception:return d
def writej(p,o):
 p=Path(p);t=p.with_suffix(p.suffix+'.tmp');t.write_text(json.dumps(o,ensure_ascii=False,indent=2),encoding='utf-8');t.replace(p)
def ensure_proposal():
 if PROPOSAL.exists():return
 writej(PROPOSAL,{'version':2,'enabled':False,'segments':{k:{'enabled':False,'filters':[],'race_scope_cd':1 if k.startswith('JRA_') or k in {'DEBUT_SPECIALIST','OBSTACLE_SPECIALIST'} else 2,'note':'filters=[{"column":"明示列","values":["明示値"]}] を契約確認後に設定。複数filtersはAND。推測禁止。'} for k in SPECIALIST_KINDS},'policy':'Disabled proposal only. Compound segment semantics must be explicit; no name-based inference.'})
def sid(plan):
 a=[]
 for n in ['TRAIN','VALIDATION','SELECTION','TEST','OOS']:
  s=(plan.get('splits') or {}).get(n,{});a += [n,str(s.get('start_date')),str(s.get('end_date'))]
 return hashlib.sha256('|'.join(a).encode()).hexdigest()[:16]
def ll(y,p):
 y=np.asarray(y,float);p=np.clip(np.asarray(p,float),1e-9,1-1e-9);return float(-np.mean(y*np.log(p)+(1-y)*np.log(1-p)))
def mask(df,plan,name):
 s=plan['splits'][name];d=pd.to_datetime(df.race_date,errors='coerce').dt.normalize();return d.between(pd.Timestamp(s['start_date']),pd.Timestamp(s['end_date']),inclusive='both')
def _rule_mask(df,rule):
 col=str(rule.get('column') or '');vals=rule.get('values') or []
 if not col or col not in df.columns or not isinstance(vals,list) or not vals:return None
 x=df[col].astype(str).str.strip().str.upper();allowed={str(v).strip().upper() for v in vals};return x.isin(allowed)
def segment_mask(df,spec):
 filters=spec.get('filters')
 if filters is None:
  filters=[{'column':spec.get('column'),'values':spec.get('values') or []}]
 if not isinstance(filters,list) or not filters:return None
 m=pd.Series(True,index=df.index)
 for rule in filters:
  if not isinstance(rule,dict):return None
  rm=_rule_mask(df,rule)
  if rm is None:return None
  m &= rm
 scope=spec.get('race_scope_cd')
 if scope is not None:m &= pd.to_numeric(df.race_scope_cd,errors='coerce').eq(int(scope))
 return m
def active_binding():
 b=readj(BIND,{}) or {};return (b.get('bindings') or {}).get('specialist_research_director') or {}
def train_model(parts,features,cats,target):
 from catboost import CatBoostClassifier
 for c in cats:
  for p in parts.values():p[c]=p[c].fillna('MISSING').astype(str)
 m=CatBoostClassifier(iterations=500,depth=6,learning_rate=.04,l2_leaf_reg=6,loss_function='Logloss',eval_metric='Logloss',verbose=False,random_seed=20261004,allow_writing_files=False,thread_count=max(1,os.cpu_count() or 4));m.fit(parts['TRAIN'][features],parts['TRAIN'][target],cat_features=cats,eval_set=(parts['VALIDATION'][features],parts['VALIDATION'][target]),early_stopping_rounds=60,use_best_model=True)
 out={}
 for n in ['VALIDATION','SELECTION','TEST','OOS']:
  if parts[n].empty:continue
  out[n]=ll(parts[n][target],m.predict_proba(parts[n][features])[:,1])
 return out
def run_once():
 ensure_proposal();binding=active_binding();plan=readj(PLAN,{}) or {};contract=readj(CONTRACT,{}) or {}
 if not binding:writej(STATE,{'pid':os.getpid(),'updated':now(),'status':'WAITING','reason':'NO_ACTIVE_BINDING'});return
 if not SRC.exists() or not plan.get('splits') or plan.get('status')=='BLOCKED':writej(STATE,{'pid':os.getpid(),'updated':now(),'status':'WAITING','reason':'DATA_OR_TEMPORAL_NOT_READY'});return
 current=sid(plan)
 if str(binding.get('split_id') or '')!=current:writej(STATE,{'pid':os.getpid(),'updated':now(),'status':'WAITING','reason':'BINDING_SPLIT_MISMATCH'});return
 kind=str(binding.get('kind') or '');spec=(contract.get('segments') or {}).get(kind) or {}
 if kind not in SPECIALIST_KINDS or not spec.get('enabled'):writej(STATE,{'pid':os.getpid(),'updated':now(),'status':'NEEDS_CONTRACT','kind':kind,'reason':'SPECIALIST_SEGMENT_CONTRACT_MISSING','proposal':str(PROPOSAL)});return
 df=pd.read_csv(SRC,low_memory=False);df['race_date']=pd.to_datetime(df.race_date,errors='coerce');seg=segment_mask(df,spec)
 if seg is None:writej(STATE,{'pid':os.getpid(),'updated':now(),'status':'NEEDS_CONTRACT','kind':kind,'reason':'SEGMENT_FILTER_CONTRACT_INVALID'});return
 df=df[seg].copy();base_feats=[c for c in ['racecourse_cd','distance_m','track_cd','horse_age','sex_cd','carried_weight_kg'] if c in df];full_feats=base_feats+[c for c in ['jockey_cd','trainer_cd','prior_start_count','days_since_last_run','prior_win_rate','prior_top2_rate','prior_top3_rate','recent5_time_diff_mean','recent5_finish_pct_mean','ability_vs_field','field_strength_v2','prior_avg_field_strength'] if c in df and c not in base_feats]
 if len(df)<500 or len(base_feats)<3 or len(full_feats)<5:writej(STATE,{'pid':os.getpid(),'updated':now(),'status':'NEEDS_DATA','kind':kind,'rows':len(df),'base_features':len(base_feats),'full_features':len(full_feats),'reason':'SPECIALIST_SAMPLE_OR_FEATURES_INSUFFICIENT'});return
 try:from catboost import CatBoostClassifier
 except Exception as e:writej(STATE,{'pid':os.getpid(),'updated':now(),'status':'BLOCKED','reason':f'CATBOOST_UNAVAILABLE:{e!r}'});return
 rows=[];filter_desc=json.dumps(spec.get('filters') or [{'column':spec.get('column'),'values':spec.get('values') or []}],ensure_ascii=False,sort_keys=True)
 for target in ['label_win','label_top2','label_top3']:
  parts={n:df[mask(df,plan,n)&df[target].notna()].copy() for n in ['TRAIN','VALIDATION','SELECTION','TEST','OOS']}
  if len(parts['TRAIN'])<250 or min(len(parts['VALIDATION']),len(parts['SELECTION']))<50:continue
  base_cats=[c for c in base_feats if c in {'racecourse_cd','track_cd','sex_cd'}];full_cats=[c for c in full_feats if c in {'racecourse_cd','track_cd','sex_cd','jockey_cd','trainer_cd'}]
  bm=train_model({k:v.copy() for k,v in parts.items()},base_feats,base_cats,target);cm=train_model({k:v.copy() for k,v in parts.items()},full_feats,full_cats,target)
  improvement=(bm.get('SELECTION')-cm.get('SELECTION')) if bm.get('SELECTION') is not None and cm.get('SELECTION') is not None else None;val_improvement=(bm.get('VALIDATION')-cm.get('VALIDATION')) if bm.get('VALIDATION') is not None and cm.get('VALIDATION') is not None else None
  rows.append({'brief_id':binding.get('brief_id'),'split_id':current,'kind':kind,'target':target,'sample_rows':len(df),'validation_logloss':cm.get('VALIDATION'),'baseline_validation_logloss':bm.get('VALIDATION'),'validation_improvement':val_improvement,'selection_logloss':cm.get('SELECTION'),'baseline_selection_logloss':bm.get('SELECTION'),'selection_improvement':improvement,'test_logloss_report_only':cm.get('TEST'),'oos_logloss_report_only':cm.get('OOS'),'contract_filters':filter_desc,'updated':now()})
 pd.DataFrame(rows).to_csv(OUT,index=False,encoding='utf-8-sig');status='PASS' if rows else 'NEEDS_DATA';writej(STATE,{'pid':os.getpid(),'updated':now(),'status':status,'kind':kind,'brief_id':binding.get('brief_id'),'models':len(rows),'rows':len(df),'artifact':str(OUT)});return

def main():
 while True:
  try:run_once()
  except Exception:writej(STATE,{'pid':os.getpid(),'updated':now(),'status':'BLOCKED','detail':traceback.format_exc()[-1800:]})
  time.sleep(INTERVAL)
if __name__=='__main__':main()
