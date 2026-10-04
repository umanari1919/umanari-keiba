from __future__ import annotations

import hashlib, json, os, time, traceback
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT=Path(os.environ.get('THE_JOCKEY_RESEARCH_ROOT',Path.home()/'Downloads'/'THE-JOCKEY-RESEARCH'))
SIM=ROOT/'simulation'/'outbox';MARKET=ROOT/'strategy'/'inbox'/'market_odds';OUT=ROOT/'strategy'/'outbox';REPORTS=ROOT/'CORE'/'reports';CHECK=ROOT/'checkpoints';LOG=ROOT/'logs'/'decision_strategy_director.log';STATE=CHECK/'decision_strategy_director_state.json'
INTERVAL=max(15,int(os.environ.get('THE_JOCKEY_STRATEGY_INTERVAL','30')));MIN_EV=float(os.environ.get('THE_JOCKEY_STRATEGY_MIN_EV','0.02'))
for p in (MARKET,OUT,REPORTS,CHECK,LOG.parent):p.mkdir(parents=True,exist_ok=True)

def now():return datetime.now().astimezone().isoformat()
def writej(p,o):
 t=p.with_suffix(p.suffix+'.tmp');t.write_text(json.dumps(o,ensure_ascii=False,indent=2),encoding='utf-8');t.replace(p)
def log(s):
 line=f'[{now()}] {s}';print(line,flush=True)
 with LOG.open('a',encoding='utf-8') as f:f.write(line+'\n')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def state(status,detail='',extra=None):
 x={'pid':os.getpid(),'updated':now(),'status':status,'detail':detail,'min_ev':MIN_EV}
 if extra:x.update(extra)
 writej(STATE,x)
def norm_scope(v):
 s=str(v).strip().upper()
 if s in {'1','1.0','JRA'}:return 'JRA'
 if s in {'2','2.0','NAR'}:return 'NAR'
 return 'UNKNOWN'
def validate_market(df):
 req=['race_id','ticket_type','selection','market_odds'];miss=[c for c in req if c not in df]
 if miss:return False,f'MISSING_REQUIRED:{miss}'
 o=pd.to_numeric(df.market_odds,errors='coerce')
 if o.isna().any() or (o<=1).any():return False,'INVALID_MARKET_ODDS'
 if df[req[:3]].astype(str).duplicated().any():return False,'DUPLICATE_MARKET_SELECTION'
 return True,''
def race_meta(market):
 cols=[c for c in ['race_id','race_scope_cd','race_no','race_type','venue','session_phase'] if c in market]
 if not cols:return pd.DataFrame(columns=['race_id'])
 return market[cols].drop_duplicates('race_id')
def jra_hypothesis(row):
 if row.get('domain')!='JRA':return False
 phase=str(row.get('session_phase','')).upper();rtype=str(row.get('race_type','')).upper()
 return phase=='MORNING' and rtype in {'MAIDEN','DEBUT','NEWCOMER','OBSTACLE'}
def opportunity_score(row):
 ev=max(float(row.get('ev') or 0),-1);p=float(row.get('probability') or 0);runners=float(row.get('runners') or 12);unc=str(row.get('uncertainty','MEDIUM')).upper()
 conf={'LOW':1.0,'MEDIUM':.7,'HIGH':.4}.get(unc,.6);small=1.0 if runners<=8 else (.7 if runners<=12 else .5)
 return float(max(0,min(100,100*(.50*min(max(ev,0),.5)/.5 + .30*conf + .20*small))))
def process(market_path):
 market=pd.read_csv(market_path,low_memory=False);ok,reason=validate_market(market)
 if not ok:return {'file':market_path.name,'status':'REJECTED','reason':reason}
 stem=market_path.stem;sim_dir=SIM/stem;fair_path=sim_dir/'ticket_fair_odds.csv';structure_path=sim_dir/'race_structure.csv'
 if not fair_path.exists():return {'file':market_path.name,'status':'WAITING','reason':f'MISSING_SIMULATION:{fair_path}'}
 fair=pd.read_csv(fair_path,low_memory=False)
 need=['race_id','ticket_type','selection','probability','fair_odds'];miss=[c for c in need if c not in fair]
 if miss:return {'file':market_path.name,'status':'REJECTED','reason':f'BAD_SIMULATION_SCHEMA:{miss}'}
 x=fair.merge(market,on=['race_id','ticket_type','selection'],how='inner',suffixes=('','_market'))
 if x.empty:return {'file':market_path.name,'status':'REJECTED','reason':'NO_MATCHED_TICKETS'}
 x['market_odds']=pd.to_numeric(x.market_odds,errors='coerce');x['probability']=pd.to_numeric(x.probability,errors='coerce');x['fair_odds']=pd.to_numeric(x.fair_odds,errors='coerce')
 x['ev']=x.probability*x.market_odds-1.0;x['edge_ratio']=x.market_odds/x.fair_odds-1.0;x['expected_profit_per_100']=100*x.ev
 meta=race_meta(market);x=x.merge(meta,on='race_id',how='left',suffixes=('','_meta')) if len(meta) else x
 if 'race_scope_cd' in x:x['domain']=x.race_scope_cd.map(norm_scope)
 else:x['domain']='UNKNOWN'
 if structure_path.exists():
  st=pd.read_csv(structure_path,low_memory=False);keep=[c for c in ['race_id','runners','uncertainty','race_shape','favorite_win_probability','top2_concentration','normalized_entropy'] if c in st];x=x.merge(st[keep],on='race_id',how='left')
 x['jra_morning_capital_hypothesis']=x.apply(jra_hypothesis,axis=1)
 x['nar_opportunity_score']=x.apply(lambda r:opportunity_score(r) if r.domain=='NAR' else np.nan,axis=1)
 x['eligible']=x.ev>=MIN_EV
 x['ticket_efficiency']=x.expected_profit_per_100
 x['capital_efficiency']=x.ev
 eligible=x[x.eligible].sort_values(['race_id','ev','probability'],ascending=[True,False,False]).copy()
 prof=[]
 for rid,g in eligible.groupby('race_id',sort=False):
  for name,cap in [('MIN-1',1),('MIN-2',2),('MIN-3',3)]:
   z=g.head(cap)
   for rank,(_,r) in enumerate(z.iterrows(),1):
    prof.append({'race_id':rid,'strategy':name,'rank':rank,'ticket_type':r.ticket_type,'selection':r.selection,'probability':float(r.probability),'fair_odds':float(r.fair_odds),'market_odds':float(r.market_odds),'ev':float(r.ev),'expected_profit_per_100':float(r.expected_profit_per_100),'domain':r.domain,'jra_morning_capital_hypothesis':bool(r.jra_morning_capital_hypothesis),'nar_opportunity_score':None if pd.isna(r.nar_opportunity_score) else float(r.nar_opportunity_score)})
 dest=OUT/stem;dest.mkdir(parents=True,exist_ok=True);x.to_csv(dest/'strategy_candidates.csv',index=False,encoding='utf-8-sig');pd.DataFrame(prof).to_csv(dest/'strategy_profiles.csv',index=False,encoding='utf-8-sig')
 manifest={'status':'PASS','updated':now(),'market_source':str(market_path),'market_sha256':sha(market_path),'simulation_source':str(fair_path),'simulation_sha256':sha(fair_path),'races':int(x.race_id.nunique()),'matched_tickets':len(x),'eligible_tickets':int(x.eligible.sum()),'strategies':['MIN-1','MIN-2','MIN-3'],'principle':'small-ticket/high-efficiency research candidates only','jra_policy':'morning maiden/debut/obstacle is a research hypothesis, not a fixed betting rule','nar_policy':'opportunity-driven by edge, uncertainty and field size','market_used_only_in_decision_layer':True,'automatic_betting':False,'money_movement':False}
 writej(dest/'manifest.json',manifest);return {'file':market_path.name,'status':'PASS','races':manifest['races'],'eligible':manifest['eligible_tickets'],'output':str(dest)}
def run_once():
 rows=[]
 for p in sorted(MARKET.glob('*.csv')):
  m=OUT/p.stem/'manifest.json'
  if m.exists():
   try:
    old=json.loads(m.read_text(encoding='utf-8-sig'))
    if old.get('market_sha256')==sha(p):continue
   except Exception:pass
  try:rows.append(process(p))
  except Exception as e:rows.append({'file':p.name,'status':'BLOCKED','reason':repr(e)})
 summary={'updated':now(),'status':'PASS' if not any(r['status']=='BLOCKED' for r in rows) else 'PARTIAL','processed':rows,'market_files':len(list(MARKET.glob('*.csv'))),'automatic_betting':False};writej(REPORTS/'DECISION_STRATEGY_summary.json',summary);state(summary['status'],'strategy scan complete',{'processed':rows});return summary
def main():
 log('DECISION STRATEGY DIRECTOR START')
 while True:
  try:run_once()
  except Exception:
   err=traceback.format_exc();log(err);state('BLOCKED',err[-1800:])
  time.sleep(INTERVAL)
if __name__=='__main__':main()
