from __future__ import annotations

import hashlib,json,math,os,time,traceback
from collections import Counter
from datetime import datetime
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd

ROOT=Path(os.environ.get('THE_JOCKEY_RESEARCH_ROOT',Path.home()/'Downloads'/'THE-JOCKEY-RESEARCH'))
INBOX=ROOT/'simulation'/'inbox';OUTBOX=ROOT/'simulation'/'outbox';REPORTS=ROOT/'CORE'/'reports';CHECK=ROOT/'checkpoints';LOG=ROOT/'logs'/'race_simulation_director.log';STATE=CHECK/'race_simulation_director_state.json'
SIMS=max(2000,int(os.environ.get('THE_JOCKEY_RACE_SIMULATIONS','20000')));INTERVAL=max(15,int(os.environ.get('THE_JOCKEY_RACE_SIM_INTERVAL','30')))
FORBIDDEN={'finish_order','label_win','label_top2','label_top3','payout','result','odds_final','pay_win','pay_place'}
for p in (INBOX,OUTBOX,REPORTS,CHECK,LOG.parent):p.mkdir(parents=True,exist_ok=True)

def now():return datetime.now().astimezone().isoformat()
def writej(p,o):
 t=p.with_suffix(p.suffix+'.tmp');t.write_text(json.dumps(o,ensure_ascii=False,indent=2),encoding='utf-8');t.replace(p)
def log(s):
 line=f'[{now()}] {s}';print(line,flush=True)
 with LOG.open('a',encoding='utf-8') as f:f.write(line+'\n')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def state(status,detail='',extra=None):
 x={'pid':os.getpid(),'updated':now(),'status':status,'detail':detail,'simulations_per_race':SIMS}
 if extra:x.update(extra)
 writej(STATE,x)
def pick(df,names):
 for n in names:
  if n in df:return n
 return None

def validate(df):
 bad=sorted(set(df.columns)&FORBIDDEN)
 if bad:return False,f'FORBIDDEN_RESULT_COLUMNS:{bad}'
 required=['race_id','race_horse_id','horse_id','race_date']
 miss=[x for x in required if x not in df]
 if miss:return False,f'MISSING_REQUIRED:{miss}'
 p1=pick(df,['p_win_cal','p_win']);p2=pick(df,['p_top2_cal','p_top2']);p3=pick(df,['p_top3_cal','p_top3'])
 if not all([p1,p2,p3]):return False,'MISSING_PROBABILITY_COLUMNS'
 if df.race_horse_id.astype(str).duplicated().any():return False,'DUPLICATE_RACE_HORSE_ID'
 for c in [p1,p2,p3]:
  v=pd.to_numeric(df[c],errors='coerce')
  if v.isna().any() or ((v<0)|(v>1)).any():return False,f'INVALID_PROBABILITY:{c}'
 a=df[[p1,p2,p3]].to_numpy(float)
 if np.any(a[:,0]>a[:,1]+1e-12) or np.any(a[:,1]>a[:,2]+1e-12):return False,'PROBABILITY_MONOTONICITY_VIOLATION'
 if 'frame_no' in df:
  fr=pd.to_numeric(df['frame_no'],errors='coerce')
  if fr.notna().any() and ((fr.dropna()<1)|(fr.dropna()>8)).any():return False,'INVALID_FRAME_NO'
 return True,{'p1':p1,'p2':p2,'p3':p3,'frame_available':'frame_no' in df}

def latent_weights(g,p1,p2,p3):
 eps=1e-9
 a=np.clip(g[p1].to_numpy(float),eps,1)
 b=np.clip(g[p2].to_numpy(float)/2.0,eps,1)
 c=np.clip(g[p3].to_numpy(float)/3.0,eps,1)
 w=np.exp(.60*np.log(a)+.25*np.log(b)+.15*np.log(c));w=np.clip(w,eps,None)
 return w/w.sum()

def simulate_race(g,pcols):
 n=len(g);rid=str(g.race_id.iloc[0]);seed=int(hashlib.sha256(rid.encode()).hexdigest()[:8],16)
 rng=np.random.default_rng(seed);w=latent_weights(g,pcols['p1'],pcols['p2'],pcols['p3']);scores=np.log(w)[None,:]+rng.gumbel(size=(SIMS,n));order=np.argsort(-scores,axis=1)
 ids=g.race_horse_id.astype(str).tolist();horses=g.horse_id.astype(str).tolist();slots=int(g['place_slots'].iloc[0]) if 'place_slots' in g and pd.notna(g['place_slots'].iloc[0]) else (3 if n>=8 else 2 if n>=4 else 1);slots=max(1,min(slots,n))
 frames=None
 if 'frame_no' in g:
  fr=pd.to_numeric(g['frame_no'],errors='coerce')
  if fr.notna().all():frames=[str(int(x)) for x in fr]
 finish=[]
 for i,rhid in enumerate(ids):
  pos=(order==i).argmax(axis=1)+1
  cnt=np.bincount(pos,minlength=n+1)[1:]/SIMS
  for k,p in enumerate(cnt,1):finish.append({'race_id':rid,'race_horse_id':rhid,'horse_id':horses[i],'finish_position':k,'probability':float(p)})
 tickets=[]
 def add(kind,key,count):
  p=count/SIMS
  if p>0:tickets.append({'race_id':rid,'ticket_type':kind,'selection':key,'probability':float(p),'fair_odds':float(1/p)})
 for i,rhid in enumerate(ids):
  add('WIN',rhid,int((order[:,0]==i).sum()));add('TOP2',rhid,int((order[:,:min(2,n)]==i).any(axis=1).sum()));add('TOP3',rhid,int((order[:,:min(3,n)]==i).any(axis=1).sum()))
 top2=order[:,:min(2,n)]
 if n>=2:
  q=Counter(tuple(ids[j] for j in row) for row in top2)
  for k,cnt in q.items():add('EXACTA','>'.join(k),cnt)
  q2=Counter(tuple(sorted(ids[j] for j in row)) for row in top2)
  for k,cnt in q2.items():add('QUINELLA','-'.join(k),cnt)
  if frames:
   fq=Counter(tuple(sorted((frames[row[0]],frames[row[1]]),key=int)) for row in top2)
   for k,cnt in fq.items():add('FRAME','-'.join(k),cnt)
 if slots>=2:
  wc=Counter()
  for row in order[:,:slots]:
   sel=sorted(ids[j] for j in row)
   for a,b in combinations(sel,2):wc[(a,b)]+=1
  kind='WIDE' if n>=4 else 'WIDE_PROXY'
  for k,cnt in wc.items():add(kind,'-'.join(k),cnt)
 if n>=3:
  t3=order[:,:3];tri=Counter(tuple(sorted(ids[j] for j in row)) for row in t3);tf=Counter(tuple(ids[j] for j in row) for row in t3)
  for k,cnt in tri.items():add('TRIO','-'.join(k),cnt)
  for k,cnt in tf.items():add('TRIFECTA','>'.join(k),cnt)
 winp=np.array([sum(1 for x in order[:,0] if x==i)/SIMS for i in range(n)],float);ent=-float(np.sum(winp*np.log(np.clip(winp,1e-12,1))))/max(math.log(max(n,2)),1e-9);top=np.sort(winp)[::-1]
 structure={'race_id':rid,'runners':n,'place_slots':slots,'frames_available':bool(frames),'simulations':SIMS,'favorite_win_probability':float(top[0]),'top2_concentration':float(top[:2].sum()),'normalized_entropy':ent,'uncertainty':'HIGH' if ent>.82 else ('MEDIUM' if ent>.65 else 'LOW'),'race_shape':'ONE_STRONG' if top[0]>=.35 else ('TWO_STRONG' if top[:2].sum()>=.55 else ('OPEN' if ent>=.80 else 'BALANCED'))}
 sim=pd.DataFrame(finish);diag=[]
 for label,col,k in [('WIN',pcols['p1'],1),('TOP2',pcols['p2'],2),('TOP3',pcols['p3'],3)]:
  pred=np.array([sim[(sim.race_horse_id==r)&(sim.finish_position<=k)].probability.sum() for r in ids]);src=g[col].to_numpy(float);diag.append({'race_id':rid,'target':label,'mae_vs_source':float(np.mean(np.abs(pred-src)))})
 return finish,tickets,structure,diag

def process(path):
 df=pd.read_csv(path,low_memory=False);ok,info=validate(df)
 if not ok:return {'file':path.name,'status':'REJECTED','reason':info}
 all_finish=[];all_tickets=[];structures=[];diags=[]
 for _,g in df.groupby('race_id',sort=False):
  f,t,s,d=simulate_race(g.copy(),info);all_finish+=f;all_tickets+=t;structures.append(s);diags+=d
 stem=path.stem;dest=OUTBOX/stem;dest.mkdir(parents=True,exist_ok=True)
 pd.DataFrame(all_finish).to_csv(dest/'finish_distribution.csv',index=False,encoding='utf-8-sig')
 pd.DataFrame(all_tickets).sort_values(['race_id','ticket_type','probability'],ascending=[True,True,False]).to_csv(dest/'ticket_fair_odds.csv',index=False,encoding='utf-8-sig')
 pd.DataFrame(structures).to_csv(dest/'race_structure.csv',index=False,encoding='utf-8-sig')
 pd.DataFrame(diags).to_csv(dest/'simulation_diagnostics.csv',index=False,encoding='utf-8-sig')
 manifest={'status':'PASS','created_at':now(),'source':str(path),'source_sha256':sha(path),'races':int(df.race_id.nunique()),'rows':len(df),'simulations_per_race':SIMS,'method':'Gumbel rank simulation / Plackett-Luce-equivalent latent utility','probability_columns':info,'ticket_types':['WIN','TOP2','TOP3','WIDE','QUINELLA','EXACTA','FRAME','TRIO','TRIFECTA'],'frame_policy':'FRAME is derived from top-2 horse finish frames; same-frame combinations are preserved when two horses from one frame finish 1st/2nd','outputs':['finish_distribution.csv','ticket_fair_odds.csv','race_structure.csv','simulation_diagnostics.csv'],'fair_odds_policy':'raw no-takeout fair decimal odds = 1/probability','market_odds_used':False,'result_columns_used':False}
 writej(dest/'manifest.json',manifest);return {'file':path.name,'status':'PASS','races':manifest['races'],'sha256':manifest['source_sha256'],'output':str(dest)}

def run_once():
 rows=[]
 for p in sorted(INBOX.glob('*.csv')):
  dest=OUTBOX/p.stem/'manifest.json'
  if dest.exists():
   try:
    old=json.loads(dest.read_text(encoding='utf-8-sig'))
    if old.get('source_sha256')==sha(p):continue
   except Exception:pass
  try:rows.append(process(p))
  except Exception as e:rows.append({'file':p.name,'status':'BLOCKED','reason':repr(e)})
 summary={'updated':now(),'status':'PASS' if not any(x['status']=='BLOCKED' for x in rows) else 'PARTIAL','processed':rows,'inbox_files':len(list(INBOX.glob('*.csv'))),'method':'result-blind race simulation','frame_research':'enabled'};writej(REPORTS/'RACE_SIMULATION_summary.json',summary);state(summary['status'],'simulation scan complete',{'processed':rows});return summary

def main():
 log('RACE SIMULATION / FAIR ODDS DIRECTOR START — FRAME ENABLED')
 while True:
  try:run_once()
  except Exception:
   err=traceback.format_exc();log(err);state('BLOCKED',err[-1800:])
  time.sleep(INTERVAL)
if __name__=='__main__':main()
