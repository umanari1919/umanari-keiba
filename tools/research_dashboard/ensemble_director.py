from __future__ import annotations
import hashlib,json,os,time,traceback
from datetime import datetime
from pathlib import Path
import numpy as np,pandas as pd
ROOT=Path(os.environ.get('THE_JOCKEY_RESEARCH_ROOT',Path.home()/'Downloads'/'THE-JOCKEY-RESEARCH'));CORE=ROOT/'CORE';DATA=CORE/'data';REPORTS=CORE/'reports';CHECK=ROOT/'checkpoints';STATE=CHECK/'ensemble_director_state.json';LOG=ROOT/'logs'/'ensemble_director.log';PLAN=REPORTS/'TEMPORAL_SPLIT_plan.json'
for p in (REPORTS,CHECK,LOG.parent):p.mkdir(parents=True,exist_ok=True)
def now():return datetime.now().astimezone().isoformat()
def readj(p,d=None):
 try:return json.loads(p.read_text(encoding='utf-8-sig'))
 except:return d
def writej(p,o):
 t=p.with_suffix(p.suffix+'.tmp');t.write_text(json.dumps(o,ensure_ascii=False,indent=2),encoding='utf-8');t.replace(p)
def log(s):
 with LOG.open('a',encoding='utf-8') as f:f.write(f'[{now()}] {s}\n')
def sid(plan):
 a=[]
 for n in ['TRAIN','VALIDATION','SELECTION','TEST','OOS']:
  s=(plan.get('splits') or {}).get(n,{});a += [n,str(s.get('start_date')),str(s.get('end_date'))]
 return hashlib.sha256('|'.join(a).encode()).hexdigest()[:16]
def mask(df,plan,name):
 s=plan['splits'][name];d=pd.to_datetime(df.race_date,errors='coerce').dt.normalize();return d.between(pd.Timestamp(s['start_date']),pd.Timestamp(s['end_date']),inclusive='both')
def ll(y,p):
 y=np.asarray(y,float);p=np.clip(np.asarray(p,float),1e-9,1-1e-9);return float(-np.mean(y*np.log(p)+(1-y)*np.log(1-p)))
def cast_cats(part,feats):
 cats=[c for c in feats if c in ['race_scope_cd','racecourse_cd','track_cd','sex_cd','jockey_cd','trainer_cd']]
 for c in cats:
  if c in part:part[c]=part[c].fillna('MISSING').astype(str)
def run_once():
 src=DATA/'CORE-004_field_strength_v2.csv';coredec=REPORTS/'CORE-005_decision.json';domreg=REPORTS/'domain_model_registry.json';plan=readj(PLAN,{}) or {}
 if not (src.exists() and coredec.exists() and domreg.exists() and plan.get('splits')):writej(STATE,{'pid':os.getpid(),'updated':now(),'status':'WAITING'});return
 if plan.get('status')=='BLOCKED':writej(STATE,{'pid':os.getpid(),'updated':now(),'status':'BLOCKED','detail':'Temporal/sample gate blocked'});return
 current=sid(plan);core=readj(coredec,{}) or {};dom=readj(domreg,{}) or {};old=readj(REPORTS/'ensemble_registry.json',{}) or {}
 if core.get('status')!='PASS' or core.get('split_id')!=current or dom.get('split_id')!=current:writej(STATE,{'pid':os.getpid(),'updated':now(),'status':'WAITING','detail':'Current split models not ready','split_id':current});return
 if old.get('split_id')==current and old.get('status')=='PASS':writej(STATE,{'pid':os.getpid(),'updated':now(),'status':'PASS','split_id':current,'ensembles':old.get('ensemble_count',0)});return
 try:from catboost import CatBoostClassifier
 except Exception as e:writej(STATE,{'pid':os.getpid(),'updated':now(),'status':'BLOCKED','detail':repr(e)});return
 df=pd.read_csv(src,low_memory=False);df['race_date']=pd.to_datetime(df.race_date,errors='coerce');scope_num=pd.to_numeric(df.race_scope_cd,errors='coerce');df=df[scope_num.isin([1,2])].copy();rows=[];ensreg={'status':'PASS','split_id':current,'updated':now(),'domains':{}}
 selection=mask(df,plan,'SELECTION');test=mask(df,plan,'TEST');oos=mask(df,plan,'OOS');scope_num=pd.to_numeric(df.race_scope_cd,errors='coerce')
 for target in ['label_win','label_top2','label_top3']:
  ch=(core.get('champion') or {}).get(target)
  if not ch or not ch.get('model_path'):continue
  common_path=Path(ch['model_path'])
  if not common_path.exists():continue
  cm=CatBoostClassifier();cm.load_model(str(common_path));cfeats=list(cm.feature_names_)
  if any(c not in df.columns for c in cfeats):continue
  for scope,dname in [(1,'JRA'),(2,'NAR')]:
   info=((dom.get('domains') or {}).get(dname) or {}).get(target)
   if not info or not Path(info['model']).exists():continue
   dm=CatBoostClassifier();dm.load_model(info['model']);dfeats=list(dm.feature_names_)
   if any(c not in df.columns for c in dfeats):continue
   base=scope_num.eq(scope)&df[target].notna();part=df[base&(selection|test|oos)].copy()
   if part.empty:continue
   cast_cats(part,cfeats);cast_cats(part,dfeats);cp=cm.predict_proba(part[cfeats])[:,1];dp=dm.predict_proba(part[dfeats])[:,1]
   sel=selection.loc[part.index]
   if int(sel.sum())<100:continue
   best={'w_domain':0.0,'selection_logloss':1e9}
   for w in np.linspace(0,1,21):
    p=w*dp+(1-w)*cp;score=ll(part.loc[sel,target],p[sel.to_numpy()])
    if score<best['selection_logloss']:best={'w_domain':float(w),'selection_logloss':score}
   p=best['w_domain']*dp+(1-best['w_domain'])*cp;mets={}
   for label,global_mask in [('TEST',test),('OOS',oos)]:
    m=global_mask.loc[part.index]
    if int(m.sum()):mets[label]={'rows':int(m.sum()),'logloss':ll(part.loc[m,target],p[m.to_numpy()]),'common_logloss':ll(part.loc[m,target],cp[m.to_numpy()]),'domain_logloss':ll(part.loc[m,target],dp[m.to_numpy()])}
   ensreg['domains'].setdefault(dname,{})[target]={'weight_domain':best['w_domain'],'weight_common':1-best['w_domain'],'selection_logloss':best['selection_logloss'],'metrics':mets,'updated':now()};rows.append({'split_id':current,'domain':dname,'target':target,'w_domain':best['w_domain'],'selection_logloss':best['selection_logloss'],**{f'{s}_{k}':v for s,dct in mets.items() for k,v in dct.items()}})
 ensreg['ensemble_count']=len(rows);pd.DataFrame(rows).to_csv(REPORTS/'ENSEMBLE_metrics.csv',index=False,encoding='utf-8-sig');writej(REPORTS/'ensemble_registry.json',ensreg);writej(STATE,{'pid':os.getpid(),'updated':now(),'status':'PASS','split_id':current,'ensembles':len(rows)});log(f'ENSEMBLE PASS split={current} count={len(rows)}')
def main():
 log('ENSEMBLE DIRECTOR START')
 while True:
  try:run_once()
  except Exception:
   e=traceback.format_exc();log(e);writej(STATE,{'pid':os.getpid(),'updated':now(),'status':'BLOCKED','detail':e[-1600:]})
  time.sleep(300)
if __name__=='__main__':main()
