from __future__ import annotations
import hashlib,json,os,time,traceback
from datetime import datetime
from pathlib import Path
import numpy as np
import pandas as pd

ROOT=Path(os.environ.get('THE_JOCKEY_RESEARCH_ROOT',Path.home()/'Downloads'/'THE-JOCKEY-RESEARCH'))
BLIND=ROOT/'blind'; PRE=BLIND/'inbox'/'pre_race'; RES=BLIND/'inbox'/'results'; FROZEN=BLIND/'frozen'; REPORTS=ROOT/'CORE'/'reports'; CHECK=ROOT/'checkpoints'; LOG=ROOT/'logs'/'blind_evaluation_director.log'; STATE=CHECK/'blind_evaluation_director_state.json'; LEDGER=REPORTS/'BLIND_EVALUATION_ledger.csv'; SUMMARY=REPORTS/'BLIND_EVALUATION_summary.json'
INTERVAL=max(30,int(os.environ.get('THE_JOCKEY_BLIND_INTERVAL','60')))
FORBIDDEN={'finish_order','label_win','label_top2','label_top3','payout','payoff','odds_final','result'}
REQ_PRE={'race_id','race_horse_id','horse_id','race_date','p_win','p_top2','p_top3'}
REQ_RES={'race_id','race_horse_id','finish_order'}
for p in (PRE,RES,FROZEN,REPORTS,CHECK,LOG.parent):p.mkdir(parents=True,exist_ok=True)

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
def sha256(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()
def ll(y,p):
 y=np.asarray(y,float);p=np.clip(np.asarray(p,float),1e-12,1-1e-12);return float(-np.mean(y*np.log(p)+(1-y)*np.log(1-p)))
def brier(y,p):return float(np.mean((np.asarray(p,float)-np.asarray(y,float))**2))
def freeze_one(path:Path):
 try:df=pd.read_csv(path,low_memory=False)
 except Exception as e:return {'file':path.name,'status':'REJECTED','reason':f'read_error:{e!r}'}
 cols={str(c).strip() for c in df.columns};bad=sorted(c for c in FORBIDDEN if c in cols);missing=sorted(REQ_PRE-cols)
 if bad:return {'file':path.name,'status':'REJECTED','reason':'forbidden_result_columns:'+','.join(bad)}
 if missing:return {'file':path.name,'status':'REJECTED','reason':'missing:'+','.join(missing)}
 if df['race_horse_id'].duplicated().any():return {'file':path.name,'status':'REJECTED','reason':'duplicate_race_horse_id'}
 for c in ['p_win','p_top2','p_top3']:
  x=pd.to_numeric(df[c],errors='coerce')
  if x.isna().any() or ((x<0)|(x>1)).any():return {'file':path.name,'status':'REJECTED','reason':f'invalid_{c}'}
 if ((df.p_win>df.p_top2)|(df.p_top2>df.p_top3)).any():return {'file':path.name,'status':'REJECTED','reason':'probability_order_violation'}
 sig=sha256(path);dest=FROZEN/f'{path.stem}__{sig[:12]}.csv';manifest=dest.with_suffix('.json')
 if not dest.exists():
  tmp=dest.with_suffix('.tmp');tmp.write_bytes(path.read_bytes());tmp.replace(dest)
  meta_cols=[c for c in ['model_id','split_id','model_source','generated_at'] if c in df.columns]
  meta={c:str(df[c].iloc[0]) if len(df) else None for c in meta_cols}
  writej(manifest,{'status':'FROZEN','frozen_at':now(),'source_file':path.name,'sha256':sig,'rows':int(len(df)),'races':int(df.race_id.nunique()),'metadata':meta,'policy':'results unavailable at freeze; immutable prediction snapshot'})
 return {'file':path.name,'status':'FROZEN','frozen':dest.name,'sha256':sig,'rows':int(len(df)),'races':int(df.race_id.nunique())}
def result_files():return {p.stem:p for p in RES.glob('*.csv') if p.is_file()}
def score_frozen(path:Path,results_map):
 try:p=pd.read_csv(path,low_memory=False)
 except Exception:return None
 keys=[]
 for stem,rp in results_map.items():
  try:r=pd.read_csv(rp,usecols=lambda c:c in REQ_RES,low_memory=False)
  except Exception:continue
  if not REQ_RES.issubset(r.columns):continue
  q=p.merge(r[['race_id','race_horse_id','finish_order']],on=['race_id','race_horse_id'],how='inner')
  if q.empty:continue
  q['finish_order']=pd.to_numeric(q.finish_order,errors='coerce');q=q[q.finish_order.notna()].copy()
  if q.empty:continue
  q['label_win']=(q.finish_order==1).astype(int);q['label_top2']=(q.finish_order<=2).astype(int);q['label_top3']=(q.finish_order<=3).astype(int)
  row={'snapshot':path.name,'prediction_sha256':sha256(path),'result_file':rp.name,'scored_at':now(),'rows':int(len(q)),'races':int(q.race_id.nunique())}
  for target,pc in [('win','p_win'),('top2','p_top2'),('top3','p_top3')]:
   row[f'{target}_logloss']=ll(q[f'label_{target}'],q[pc]);row[f'{target}_brier']=brier(q[f'label_{target}'],q[pc])
  row['status']='SCORED';keys.append(row)
 return keys[-1] if keys else None
def run_once():
 frozen=[];rejected=[]
 for p in sorted(PRE.glob('*.csv')):
  x=freeze_one(p);(frozen if x['status']=='FROZEN' else rejected).append(x)
 existing=set()
 if LEDGER.exists():
  try:existing=set(pd.read_csv(LEDGER,usecols=['prediction_sha256']).prediction_sha256.astype(str))
  except Exception:existing=set()
 scored=[];rmap=result_files()
 for p in sorted(FROZEN.glob('*.csv')):
  sig=sha256(p)
  if sig in existing:continue
  row=score_frozen(p,rmap)
  if row:
   pd.DataFrame([row]).to_csv(LEDGER,mode='a',header=not LEDGER.exists(),index=False,encoding='utf-8-sig');scored.append(row);existing.add(sig)
 total=0;races=0
 if LEDGER.exists():
  try:d=pd.read_csv(LEDGER);total=len(d);races=int(pd.to_numeric(d.get('races',0),errors='coerce').fillna(0).sum())
  except Exception:pass
 status='PASS' if not rejected else 'WARN'
 summary={'status':status,'updated':now(),'mode':'FORWARD_BLIND','frozen_snapshots':len(list(FROZEN.glob('*.csv'))),'scored_snapshots':total,'scored_races':races,'newly_frozen':frozen,'newly_scored':scored,'rejected':rejected,'rules':{'results_forbidden_before_freeze':True,'immutable_sha256':True,'results_join_only_after_freeze':True,'no_model_selection_from_blind_results':True}}
 writej(SUMMARY,summary);state(status,'blind evaluation cycle complete',summary);log(f"BLIND {status} frozen={len(frozen)} scored={len(scored)} rejected={len(rejected)}")
 return summary

def main():
 log('BLIND EVALUATION DIRECTOR START')
 while True:
  try:run_once()
  except Exception:
   err=traceback.format_exc();log(err);state('BLOCKED',err[-1800:])
  time.sleep(INTERVAL)
if __name__=='__main__':main()
