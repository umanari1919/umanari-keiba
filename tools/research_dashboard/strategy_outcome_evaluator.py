from __future__ import annotations

import json,os,time,traceback
from datetime import datetime
from pathlib import Path
import pandas as pd

ROOT=Path(os.environ.get('THE_JOCKEY_RESEARCH_ROOT',Path.home()/'Downloads'/'THE-JOCKEY-RESEARCH'))
REPORTS=ROOT/'CORE'/'reports';CHECK=ROOT/'checkpoints';BIND=REPORTS/'RESEARCH_EXECUTION_bindings.json';STRAT=ROOT/'strategy'/'outbox';RESULTS=ROOT/'strategy'/'inbox'/'results';OUT=REPORTS/'STRATEGY_EVALUATION_summary.csv';STATE=CHECK/'strategy_outcome_evaluator_state.json';INTERVAL=max(60,int(os.environ.get('THE_JOCKEY_STRATEGY_OUTCOME_INTERVAL','180')))
for p in (REPORTS,CHECK,RESULTS):p.mkdir(parents=True,exist_ok=True)

def now():return datetime.now().astimezone().isoformat()
def readj(p,d=None):
 try:return json.loads(Path(p).read_text(encoding='utf-8-sig'))
 except Exception:return d
def writej(p,o):
 p=Path(p);t=p.with_suffix(p.suffix+'.tmp');t.write_text(json.dumps(o,ensure_ascii=False,indent=2),encoding='utf-8');t.replace(p)
def active_binding():
 b=readj(BIND,{}) or {};return (b.get('bindings') or {}).get('decision_strategy_director') or {}
def max_drawdown(profits):
 equity=profits.cumsum();peak=equity.cummax().clip(lower=0);dd=peak-equity;return float(dd.max()) if len(dd) else 0.0
def losing_streak(hit):
 best=cur=0
 for v in hit.astype(bool).tolist():
  if v:cur=0
  else:cur+=1;best=max(best,cur)
 return int(best)
def run_once():
 binding=active_binding()
 if not binding:writej(STATE,{'pid':os.getpid(),'updated':now(),'status':'WAITING','reason':'NO_ACTIVE_STRATEGY_BINDING'});return
 frames=[];matched_files=0;rejected_files=[]
 for result_path in sorted(RESULTS.glob('*.csv')):
  stem=result_path.stem;profile=STRAT/stem/'strategy_profiles.csv'
  if not profile.exists():continue
  res=pd.read_csv(result_path,low_memory=False);req={'race_id','ticket_type','selection','payout_per_100'}
  if not req.issubset(res.columns):rejected_files.append({'file':result_path.name,'reason':'RESULT_SCHEMA'});continue
  prof=pd.read_csv(profile,low_memory=False);need={'race_id','strategy','ticket_type','selection'}
  if not need.issubset(prof.columns):rejected_files.append({'file':result_path.name,'reason':'PROFILE_SCHEMA'});continue
  x=prof.merge(res[list(req)],on=['race_id','ticket_type','selection'],how='left');x['payout_per_100']=pd.to_numeric(x.payout_per_100,errors='coerce')
  if x.payout_per_100.isna().any():rejected_files.append({'file':result_path.name,'reason':'INCOMPLETE_PAYOUT'});continue
  x['source_result_file']=result_path.name;frames.append(x);matched_files+=1
 if not frames:
  writej(STATE,{'pid':os.getpid(),'updated':now(),'status':'WAITING_OUTCOME','brief_id':binding.get('brief_id'),'matched_result_files':0,'rejected_files':rejected_files});return
 allx=pd.concat(frames,ignore_index=True);allx['stake']=100.0;allx['payout']=allx.payout_per_100;allx['profit']=allx.payout-allx.stake;allx['hit']=allx.payout.gt(0);rows=[]
 for strategy,g in allx.sort_values(['race_id','strategy']).groupby('strategy',sort=True):
  turnover=float(g.stake.sum());payout=float(g.payout.sum());profit=float(g.profit.sum());tickets=int(len(g));races=int(g.race_id.nunique())
  rows.append({'brief_id':binding.get('brief_id'),'split_id':binding.get('split_id'),'strategy':strategy,'ROI':(payout/turnover if turnover else None),'profit':profit,'turnover':turnover,'tickets':tickets,'races':races,'hit_rate':float(g.hit.mean()) if tickets else None,'max_drawdown':max_drawdown(g.profit),'losing_streak':losing_streak(g.hit),'ticket_efficiency':(profit/tickets if tickets else None),'capital_efficiency':(profit/turnover if turnover else None),'result_files':matched_files,'updated':now()})
 pd.DataFrame(rows).to_csv(OUT,index=False,encoding='utf-8-sig');writej(STATE,{'pid':os.getpid(),'updated':now(),'status':'PASS','brief_id':binding.get('brief_id'),'evaluations':len(rows),'matched_result_files':matched_files,'rejected_files':rejected_files,'artifact':str(OUT)});return

def main():
 while True:
  try:run_once()
  except Exception:writej(STATE,{'pid':os.getpid(),'updated':now(),'status':'BLOCKED','detail':traceback.format_exc()[-1800:]})
  time.sleep(INTERVAL)
if __name__=='__main__':main()
