from __future__ import annotations
import json,os
from datetime import datetime
from pathlib import Path
import pandas as pd
ROOT=Path(os.environ.get('THE_JOCKEY_RESEARCH_ROOT',Path.home()/'Downloads'/'THE-JOCKEY-RESEARCH'));CORE=ROOT/'CORE';DATA=CORE/'data';REPORTS=CORE/'reports';CHECK=ROOT/'checkpoints'
STATE=CHECK/'leakage_guard_director_state.json';REPORT=REPORTS/'LEAKAGE_GUARD_report.json';PLAN=REPORTS/'TEMPORAL_SPLIT_plan.json'
for p in (CHECK,REPORTS):p.mkdir(parents=True,exist_ok=True)
def now():return datetime.now().astimezone().isoformat()
def readj(p,d=None):
 try:return json.loads(p.read_text(encoding='utf-8-sig'))
 except Exception:return d
def writej(p,o):
 t=p.with_suffix(p.suffix+'.tmp');t.write_text(json.dumps(o,ensure_ascii=False,indent=2),encoding='utf-8');t.replace(p)
def run_once():
 src=DATA/'CORE-004_field_strength_v2.csv';issues=[];stats={}
 if not src.exists():
  out={'updated':now(),'status':'WAITING','issues':['CORE-004 missing']};writej(REPORT,out);writej(STATE,{'pid':os.getpid(),'updated':now(),'status':'WAITING'});return out
 cols=['race_id','race_horse_id','horse_id','race_date','prior_start_count','label_win','label_top2','label_top3','last_field_strength','recent3_field_strength_mean','recent5_field_strength_mean','prior_avg_field_strength']
 df=pd.read_csv(src,usecols=lambda c:c in cols,low_memory=False);df['race_date']=pd.to_datetime(df.race_date,errors='coerce')
 dup=int(df.race_horse_id.duplicated().sum()) if 'race_horse_id' in df else -1;stats['duplicate_race_horse_id']=dup
 if dup>0:issues.append(f'duplicate_race_horse_id:{dup}')
 if all(c in df for c in ['label_win','label_top2','label_top3']):
  mono=int(((df.label_win>df.label_top2)|(df.label_top2>df.label_top3)).fillna(False).sum());stats['label_order_violations']=mono
  if mono:issues.append(f'label_order_violations:{mono}')
 if 'prior_start_count' in df:
  first=pd.to_numeric(df.prior_start_count,errors='coerce').fillna(0).eq(0);leak_cols=[c for c in ['last_field_strength','recent3_field_strength_mean','recent5_field_strength_mean','prior_avg_field_strength'] if c in df]
  leaks={c:int(df.loc[first,c].notna().sum()) for c in leak_cols};stats['first_start_history_leaks']=leaks
  if sum(leaks.values()):issues.append(f'first_start_history_leaks:{sum(leaks.values())}')
 plan=readj(PLAN,{}) or {};splits=plan.get('splits') or {}
 order=[]
 for n in ['TRAIN','VALIDATION','SELECTION','TEST','OOS']:
  s=splits.get(n) or {}
  if s.get('start_date') and s.get('end_date'):order.append((n,pd.Timestamp(s['start_date']),pd.Timestamp(s['end_date'])))
 for i in range(1,len(order)):
  if order[i][1] <= order[i-1][2]:issues.append(f'split_overlap:{order[i-1][0]}->{order[i][0]}')
 out={'updated':now(),'status':'BLOCKED' if issues else 'PASS','issues':issues,'stats':stats,'oos_policy':'OOS report-only; no feature/champion selection'};writej(REPORT,out);writej(STATE,{'pid':os.getpid(),'updated':now(),'status':out['status'],'detail':issues});return out
