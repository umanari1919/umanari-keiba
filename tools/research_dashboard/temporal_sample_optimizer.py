from __future__ import annotations

import hashlib, json, os, time, traceback
from datetime import datetime
from pathlib import Path
import numpy as np
import pandas as pd

ROOT=Path(os.environ.get('THE_JOCKEY_RESEARCH_ROOT',Path.home()/'Downloads'/'THE-JOCKEY-RESEARCH'))
CORE=ROOT/'CORE';DATA=CORE/'data';REPORTS=CORE/'reports';CHECK=ROOT/'checkpoints'
SRC=DATA/'CORE-004_field_strength_v2.csv';PLAN=REPORTS/'TEMPORAL_SPLIT_plan.json';PROFILE=REPORTS/'TEMPORAL_SPLIT_profile.csv'
STATE=CHECK/'temporal_sample_optimizer_state.json';LOG=ROOT/'logs'/'temporal_sample_optimizer.log'
INTERVAL=max(60,int(os.environ.get('THE_JOCKEY_TEMPORAL_OPTIMIZER_INTERVAL','300')))
TARGETS=('label_win','label_top2','label_top3'); NAMES=('TRAIN','VALIDATION','SELECTION','TEST','OOS')
PROFILES=[
 ('TRAIN_HEAVY',{'TRAIN':.65,'VALIDATION':.10,'SELECTION':.09,'TEST':.08,'OOS':.08}),
 ('BALANCED_62',{'TRAIN':.62,'VALIDATION':.10,'SELECTION':.10,'TEST':.09,'OOS':.09}),
 ('BALANCED_58',{'TRAIN':.58,'VALIDATION':.12,'SELECTION':.10,'TEST':.10,'OOS':.10}),
 ('EVAL_HEAVY',{'TRAIN':.55,'VALIDATION':.12,'SELECTION':.11,'TEST':.11,'OOS':.11}),
 ('ROBUST_EVAL',{'TRAIN':.50,'VALIDATION':.15,'SELECTION':.12,'TEST':.12,'OOS':.11}),
]
for p in (REPORTS,CHECK,LOG.parent):p.mkdir(parents=True,exist_ok=True)

def now():return datetime.now().astimezone().isoformat()
def log(s):
 line=f'[{now()}] {s}';print(line,flush=True)
 with LOG.open('a',encoding='utf-8') as f:f.write(line+'\n')
def readj(p,d=None):
 try:return json.loads(p.read_text(encoding='utf-8-sig'))
 except Exception:return d
def writej(p,o):
 t=p.with_suffix(p.suffix+'.tmp');t.write_text(json.dumps(o,ensure_ascii=False,indent=2),encoding='utf-8');t.replace(p)
def state(status,detail='',extra=None):
 x={'pid':os.getpid(),'updated':now(),'status':status,'detail':detail}
 if extra:x.update(extra)
 writej(STATE,x)
def sig(path):
 st=path.stat();return hashlib.sha256(f'{st.st_size}:{st.st_mtime_ns}'.encode()).hexdigest()
def prepare(df):
 d=df.copy();d['race_date']=pd.to_datetime(d.race_date,errors='coerce').dt.normalize();scope=pd.to_numeric(d.race_scope_cd,errors='coerce');d=d[d.race_date.notna()&scope.isin([1,2])].copy();return d
def race_dates(df):
 r=df[['race_id','race_date']].drop_duplicates('race_id').sort_values(['race_date','race_id']);daily=r.groupby('race_date').size().rename('n').to_frame();daily['cum']=daily.n.cumsum();return daily
def bounds_for(df,ratios):
 daily=race_dates(df);dates=list(daily.index);total=int(daily.n.sum());cuts=[];cum=0
 for name in NAMES[:-1]:
  cum+=ratios[name];target=total*cum;cut=pd.Timestamp((daily['cum']-target).abs().idxmin());
  if cuts and cut<=cuts[-1]:
   pos=min(len(dates)-1,dates.index(cuts[-1])+1);cut=pd.Timestamp(dates[pos])
  cuts.append(cut)
 starts=[pd.Timestamp(dates[0])]
 for cut in cuts:
  i=min(len(dates)-1,dates.index(cut)+1);starts.append(pd.Timestamp(dates[i]))
 ends=cuts+[pd.Timestamp(dates[-1])]
 return {n:(s,e) for n,s,e in zip(NAMES,starts,ends)}
def mask(df,b):return df.race_date.between(b[0],b[1],inclusive='both')
def stats(df,name,b):
 p=df[mask(df,b)];domains={}
 for code,label in [(1,'JRA'),(2,'NAR')]:
  x=p[pd.to_numeric(p.race_scope_cd,errors='coerce').eq(code)];domains[label]={'rows':int(len(x)),'races':int(x.race_id.nunique())}
 targets={}
 for t in TARGETS:
  y=pd.to_numeric(p[t],errors='coerce') if t in p else pd.Series(dtype=float);targets[t]={'labeled_rows':int(y.notna().sum()),'positives':int(y.eq(1).sum()),'positive_rate':float(y.eq(1).mean()) if y.notna().any() else None}
 hist={}
 if 'prior_start_count' in p:
  h=pd.to_numeric(p.prior_start_count,errors='coerce');hist={'prior_1plus_rate':float(h.ge(1).mean()),'prior_3plus_rate':float(h.ge(3).mean()),'prior_6plus_rate':float(h.ge(6).mean())}
 return {'name':name,'start_date':b[0].date().isoformat(),'end_date':b[1].date().isoformat(),'days':int((b[1]-b[0]).days+1),'rows':int(len(p)),'races':int(p.race_id.nunique()),'horses':int(p.horse_id.nunique()) if 'horse_id' in p else None,'domains':domains,'targets':targets,'history':hist}
def gates(all_stats,total_races,span_days):
 warnings=[];blockers=[]
 if total_races<3000:blockers.append(f'total_races<3000:{total_races}')
 elif total_races<8000:warnings.append(f'limited_total_races:{total_races}')
 if span_days<365:warnings.append(f'short_span_days:{span_days}')
 for n in NAMES[1:]:
  s=all_stats[n]
  if s['races']<250:blockers.append(f'{n}_races<250:{s["races"]}')
  for t in TARGETS:
   pos=s['targets'].get(t,{}).get('positives',0)
   if pos<100:blockers.append(f'{n}_{t}_positives<100:{pos}')
  for dom in ('JRA','NAR'):
   r=s['domains'].get(dom,{}).get('races',0)
   if r<100:warnings.append(f'{n}_{dom}_races<100:{r}')
 tr=all_stats['TRAIN'];
 if tr['races']<1500:blockers.append(f'TRAIN_races<1500:{tr["races"]}')
 p3=tr.get('history',{}).get('prior_3plus_rate')
 if p3 is not None and p3<.35:warnings.append(f'low_train_prior3:{p3:.3f}')
 return warnings,blockers
def adequacy_score(st,warnings,blockers):
 # Population-only score. No model metric is used, so TEST/OOS remain statistically untouched.
 evals=[st[n] for n in NAMES[1:]]
 min_r=min(x['races'] for x in evals);min_pos=min(x['targets'][t]['positives'] for x in evals for t in TARGETS)
 min_dom=min(x['domains'][d]['races'] for x in evals for d in ('JRA','NAR'))
 train_r=st['TRAIN']['races'];p3=st['TRAIN'].get('history',{}).get('prior_3plus_rate',0) or 0
 return float(min_r*2 + min_pos*3 + min_dom + min(train_r,10000)*.15 + p3*500 - len(warnings)*25 - len(blockers)*100000)
def walk_folds(df,oos_start):
 pre=df[df.race_date<oos_start];daily=race_dates(pre)
 if len(daily)<10:return []
 total=int(daily.n.sum());dates=list(daily.index)
 def cut(fr):return pd.Timestamp((daily['cum']-total*fr).abs().idxmin())
 out=[]
 for i,(a,b) in enumerate(((.45,.55),(.55,.65),(.65,.75),(.75,.85)),1):
  te=cut(a);ve=cut(b);later=[d for d in dates if d>te and d<=ve]
  if later:out.append({'fold':i,'train_start':pd.Timestamp(dates[0]).date().isoformat(),'train_end':te.date().isoformat(),'validation_start':pd.Timestamp(later[0]).date().isoformat(),'validation_end':ve.date().isoformat()})
 return out
def run_once():
 if not SRC.exists():state('WAITING','CORE-004 missing');return False
 source=sig(SRC);old=readj(PLAN,{}) or {}
 if old.get('source_signature')==source and old.get('status') in ('PASS','WARN'):
  state(old['status'],'Temporal plan current',{'profile':old.get('profile_name'),'split_id':old.get('split_id')});return True
 state('RUNNING','Optimizing population and temporal split')
 df=prepare(pd.read_csv(SRC,low_memory=False))
 if df.empty:state('BLOCKED','No domestic dated rows');return False
 total_r=int(df.race_id.nunique());date_min=df.race_date.min();date_max=df.race_date.max();span=int((date_max-date_min).days+1)
 candidates=[]
 for profile,ratios in PROFILES:
  b=bounds_for(df,ratios);st={n:stats(df,n,b[n]) for n in NAMES};warn,block=gates(st,total_r,span);score=adequacy_score(st,warn,block)
  candidates.append({'profile_name':profile,'ratios':ratios,'bounds':b,'splits':st,'warnings':warn,'blockers':block,'score':score})
 valid=[x for x in candidates if not x['blockers']];chosen=max(valid or candidates,key=lambda x:x['score'])
 sid_raw='|'.join(f'{n}:{chosen["splits"][n]["start_date"]}:{chosen["splits"][n]["end_date"]}' for n in NAMES);sid=hashlib.sha256(sid_raw.encode()).hexdigest()[:16]
 status='BLOCKED' if chosen['blockers'] else ('WARN' if chosen['warnings'] else 'PASS')
 plan={'version':2,'status':status,'updated':now(),'source_signature':source,'split_id':sid,'strategy':'sample_adequacy_optimized_chronological','selection_uses_model_metrics':False,'profile_name':chosen['profile_name'],'ratios':chosen['ratios'],'date_range':{'start':date_min.date().isoformat(),'end':date_max.date().isoformat(),'span_days':span},'population':{'rows':int(len(df)),'races':total_r,'horses':int(df.horse_id.nunique()) if 'horse_id' in df else None,'JRA_races':int(df[pd.to_numeric(df.race_scope_cd,errors='coerce').eq(1)].race_id.nunique()),'NAR_races':int(df[pd.to_numeric(df.race_scope_cd,errors='coerce').eq(2)].race_id.nunique())},'splits':chosen['splits'],'gates':{'warnings':chosen['warnings'],'blockers':chosen['blockers']},'walk_forward_folds':walk_folds(df,pd.Timestamp(chosen['splits']['OOS']['start_date'])),'candidate_profiles':[{'name':x['profile_name'],'ratios':x['ratios'],'score':x['score'],'warnings':len(x['warnings']),'blockers':len(x['blockers']),'min_eval_races':min(x['splits'][n]['races'] for n in NAMES[1:])} for x in candidates],'contract':{'TRAIN':'model fitting','VALIDATION':'early stopping/tuning','SELECTION':'champion selection and calibration','TEST':'untouched evaluation','OOS':'final report-only'}}
 writej(PLAN,plan)
 rows=[]
 for n in NAMES:
  s=chosen['splits'][n];rows.append({'split_id':sid,'profile':chosen['profile_name'],'split':n,'start_date':s['start_date'],'end_date':s['end_date'],'days':s['days'],'races':s['races'],'rows':s['rows'],'horses':s['horses'],'JRA_races':s['domains']['JRA']['races'],'NAR_races':s['domains']['NAR']['races'],'win_pos':s['targets']['label_win']['positives'],'top2_pos':s['targets']['label_top2']['positives'],'top3_pos':s['targets']['label_top3']['positives'],'prior3_rate':s.get('history',{}).get('prior_3plus_rate')})
 pd.DataFrame(rows).to_csv(PROFILE,index=False,encoding='utf-8-sig')
 state(status,'Temporal/sample optimization complete',{'split_id':sid,'profile':chosen['profile_name'],'population':plan['population'],'warnings':chosen['warnings'],'blockers':chosen['blockers']});log(f'TEMPORAL OPTIMIZER {status} profile={chosen["profile_name"]} split={sid} races={total_r}')
 return status!='BLOCKED'
def main():
 log('TEMPORAL SAMPLE OPTIMIZER START v2')
 while True:
  try:run_once()
  except Exception:
   err=traceback.format_exc();log(err);state('BLOCKED',err[-1800:])
  time.sleep(INTERVAL)
if __name__=='__main__':main()
