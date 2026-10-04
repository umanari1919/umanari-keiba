from __future__ import annotations

import json, os, time, traceback
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT=Path(os.environ.get('THE_JOCKEY_RESEARCH_ROOT',Path.home()/'Downloads'/'THE-JOCKEY-RESEARCH'))
BLIND=ROOT/'blind'/'scored';STRAT=ROOT/'strategy'/'outbox';RESULTS=ROOT/'blind'/'inbox'/'results';REPORTS=ROOT/'CORE'/'reports';CHECK=ROOT/'checkpoints';LOG=ROOT/'logs'/'failure_analysis_director.log';STATE=CHECK/'failure_analysis_director_state.json'
INTERVAL=max(30,int(os.environ.get('THE_JOCKEY_FAILURE_ANALYSIS_INTERVAL','60')))
for p in (REPORTS,CHECK,LOG.parent):p.mkdir(parents=True,exist_ok=True)

def now():return datetime.now().astimezone().isoformat()
def writej(p,o):
 t=p.with_suffix(p.suffix+'.tmp');t.write_text(json.dumps(o,ensure_ascii=False,indent=2),encoding='utf-8');t.replace(p)
def log(s):
 line=f'[{now()}] {s}';print(line,flush=True)
 with LOG.open('a',encoding='utf-8') as f:f.write(line+'\n')
def state(status,detail='',extra=None):
 x={'pid':os.getpid(),'updated':now(),'status':status,'detail':detail}
 if extra:x.update(extra)
 writej(STATE,x)
def classify_probability_miss(p,hit):
 p=float(p)
 if hit:return 'HIT'
 if p>=.50:return 'HIGH_CONFIDENCE_MISS'
 if p>=.25:return 'MEDIUM_CONFIDENCE_MISS'
 if p>=.10:return 'PLAUSIBLE_VARIANCE'
 return 'LOW_PROBABILITY_EXPECTED_MISS'
def analyze_scored(path):
 try:df=pd.read_csv(path,low_memory=False)
 except Exception:return []
 rows=[]
 # Accept either runner-level scored rows or aggregate metrics files.
 if {'race_id','race_horse_id'}.issubset(df.columns):
  for target,pcol,lcol in [('WIN','p_win','label_win'),('TOP2','p_top2','label_top2'),('TOP3','p_top3','label_top3')]:
   if pcol not in df or lcol not in df:continue
   for _,r in df[[c for c in ['race_id','race_horse_id',pcol,lcol] if c in df]].dropna().iterrows():
    hit=bool(int(r[lcol]));rows.append({'source':path.name,'race_id':str(r.race_id),'entity':str(r.race_horse_id),'layer':'PREDICTION','target':target,'classification':classify_probability_miss(r[pcol],hit),'probability':float(r[pcol]),'outcome':int(hit)})
 return rows
def analyze_strategy_dir(d):
 cand=d/'strategy_candidates.csv';prof=d/'strategy_profiles.csv'
 if not cand.exists() or not prof.exists():return []
 try:c=pd.read_csv(cand,low_memory=False);p=pd.read_csv(prof,low_memory=False)
 except Exception:return []
 rows=[]
 # Strategy diagnosis without pretending every loss is an error.
 for _,r in p.iterrows():
  cls='POSITIVE_EV_SELECTED' if float(r.get('ev',0))>0 else 'NONPOSITIVE_EV_SELECTED'
  rows.append({'source':d.name,'race_id':str(r.get('race_id')),'entity':str(r.get('selection')),'layer':'DECISION','target':str(r.get('ticket_type')),'classification':cls,'probability':float(r.get('probability',np.nan)) if pd.notna(r.get('probability',np.nan)) else None,'ev':float(r.get('ev',np.nan)) if pd.notna(r.get('ev',np.nan)) else None,'strategy':str(r.get('strategy',''))})
 # Detect potentially harmful pruning: high-EV tickets omitted by MIN profiles.
 if not c.empty and 'eligible' in c:
  elig=c[c.eligible.astype(str).str.lower().isin(['true','1'])].copy()
  chosen=set((str(r.race_id),str(r.ticket_type),str(r.selection)) for _,r in p.iterrows())
  for _,r in elig.iterrows():
   key=(str(r.race_id),str(r.ticket_type),str(r.selection))
   if key not in chosen and float(r.get('ev',0))>=.10:
    rows.append({'source':d.name,'race_id':key[0],'entity':key[2],'layer':'DECISION','target':key[1],'classification':'HIGH_EV_PRUNED_BY_POINT_LIMIT','probability':float(r.get('probability',np.nan)) if pd.notna(r.get('probability',np.nan)) else None,'ev':float(r.get('ev',np.nan)) if pd.notna(r.get('ev',np.nan)) else None})
 return rows
def summarize(rows):
 df=pd.DataFrame(rows)
 if df.empty:return {'updated':now(),'status':'WAITING','total_findings':0,'counts':{}}
 counts=df.classification.value_counts().to_dict();layers=df.layer.value_counts().to_dict()
 return {'updated':now(),'status':'PASS','total_findings':len(df),'counts':{str(k):int(v) for k,v in counts.items()},'layers':{str(k):int(v) for k,v in layers.items()},'principle':'A losing ticket is not automatically a model failure; separate prediction, decision, market and variance causes.'}
def run_once():
 rows=[]
 if BLIND.exists():
  for p in BLIND.rglob('*.csv'):rows+=analyze_scored(p)
 if STRAT.exists():
  for d in STRAT.iterdir():
   if d.is_dir():rows+=analyze_strategy_dir(d)
 df=pd.DataFrame(rows)
 if not df.empty:df.to_csv(REPORTS/'FAILURE_ANALYSIS_ledger.csv',index=False,encoding='utf-8-sig')
 summary=summarize(rows);writej(REPORTS/'FAILURE_ANALYSIS_summary.json',summary);state(summary['status'],'failure analysis scan complete',{'findings':summary.get('total_findings',0)});return summary
def main():
 log('FAILURE ANALYSIS DIRECTOR START')
 while True:
  try:run_once()
  except Exception:
   err=traceback.format_exc();log(err);state('BLOCKED',err[-1800:])
  time.sleep(INTERVAL)
if __name__=='__main__':main()
