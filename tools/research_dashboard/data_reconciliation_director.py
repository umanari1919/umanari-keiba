from __future__ import annotations
import hashlib,json,os,time,traceback
from datetime import datetime
from pathlib import Path
import pandas as pd

ROOT=Path(os.environ.get('THE_JOCKEY_RESEARCH_ROOT',Path.home()/'Downloads'/'THE-JOCKEY-RESEARCH'))
CORE=ROOT/'CORE';DATA=CORE/'data';REPORTS=CORE/'reports';CHECK=ROOT/'checkpoints';LOG=ROOT/'logs'/'data_reconciliation_director.log'
STATE=CHECK/'data_reconciliation_director_state.json';SUMMARY=REPORTS/'DATA_RECONCILIATION_summary.json';LEDGER=REPORTS/'DATA_RECONCILIATION_ledger.csv';PLAN=REPORTS/'DATA_RECONCILIATION_plan.json'
BASE=DATA/'CORE-003B_historical_features.csv';INVENTORY=REPORTS/'DATA_INVENTORY_summary.json';INTERVAL=max(120,int(os.environ.get('THE_JOCKEY_RECONCILIATION_INTERVAL','600')))
DEFAULT_INBOX=[ROOT/'incoming',ROOT/'imports',CORE/'incoming',DATA/'incoming']
for p in (REPORTS,CHECK,LOG.parent):p.mkdir(parents=True,exist_ok=True)

def now():return datetime.now().astimezone().isoformat()
def writej(p,o):
    t=p.with_suffix(p.suffix+'.tmp');t.write_text(json.dumps(o,ensure_ascii=False,indent=2),encoding='utf-8');t.replace(p)
def readj(p,d=None):
    try:return json.loads(p.read_text(encoding='utf-8-sig'))
    except:return d
def log(s):
    line=f'[{now()}] {s}';print(line,flush=True)
    with LOG.open('a',encoding='utf-8') as f:f.write(line+'\n')
def state(status,detail='',extra=None):
    x={'pid':os.getpid(),'updated':now(),'status':status,'detail':detail}
    if extra:x.update(extra)
    writej(STATE,x)
def sig(p:Path):
    h=hashlib.sha256();
    with p.open('rb') as f:
        while True:
            b=f.read(1024*1024)
            if not b:break
            h.update(b)
    return h.hexdigest()
def inboxes():
    extra=[Path(x) for x in os.environ.get('THE_JOCKEY_RECONCILIATION_PATHS','').split(os.pathsep) if x.strip()]
    out=[]
    for p in DEFAULT_INBOX+extra:
        try:q=p.expanduser().resolve()
        except:q=p
        if q not in out:out.append(q)
    return out
def candidates():
    out=[]
    for d in inboxes():
        if not d.exists():continue
        for p in sorted(d.glob('*.csv')):
            if p.name.startswith('CORE-'):continue
            out.append(p)
    return out
def header(path:Path):
    return list(pd.read_csv(path,nrows=0).columns)
def compatible(path:Path,base_cols:list[str]):
    try:cols=header(path)
    except Exception as e:return False,{'reason':'HEADER_READ_FAILED','error':repr(e)}
    required={'race_id','race_horse_id','horse_id','race_date','race_scope_cd','label_win','label_top2','label_top3'}
    missing_req=sorted(required-set(cols));missing_base=sorted(set(base_cols)-set(cols));extra=sorted(set(cols)-set(base_cols))
    ratio=len(set(cols)&set(base_cols))/max(1,len(set(base_cols)))
    ok=not missing_req and not missing_base and ratio==1.0
    return ok,{'reason':'COMPATIBLE' if ok else 'SCHEMA_MISMATCH','column_match_ratio':ratio,'missing_required':missing_req,'missing_base_columns':missing_base[:40],'extra_columns':extra[:40]}
def normalize_scope(s):
    return pd.to_numeric(s,errors='coerce').isin([1,2])
def validate_rows(df:pd.DataFrame):
    issues=[]
    if 'race_horse_id' not in df or df['race_horse_id'].isna().any():issues.append('missing_race_horse_id')
    if 'race_horse_id' in df and df['race_horse_id'].astype(str).duplicated().any():issues.append('duplicate_race_horse_id_in_candidate')
    d=pd.to_datetime(df.get('race_date'),errors='coerce')
    if d.isna().any():issues.append('invalid_race_date')
    if 'race_scope_cd' not in df or not normalize_scope(df['race_scope_cd']).all():issues.append('non_domestic_or_invalid_scope')
    for c in ['label_win','label_top2','label_top3']:
        if c not in df:issues.append(f'missing_{c}')
        else:
            y=pd.to_numeric(df[c],errors='coerce')
            if y.isna().any():issues.append(f'unlabeled_{c}')
            if (~y.isin([0,1])).any():issues.append(f'invalid_binary_{c}')
    if all(c in df for c in ['label_win','label_top2','label_top3']):
        a=pd.to_numeric(df.label_win,errors='coerce');b=pd.to_numeric(df.label_top2,errors='coerce');c=pd.to_numeric(df.label_top3,errors='coerce')
        if ((a>b)|(b>c)).any():issues.append('label_monotonicity_violation')
    return issues
def append_ledger(rows):
    if rows:pd.DataFrame(rows).to_csv(LEDGER,mode='a',header=not LEDGER.exists(),index=False,encoding='utf-8-sig')
def trigger_downstream(before_sig,after_sig):
    payload={'updated':now(),'before_source_signature':before_sig,'after_source_signature':after_sig,'action':'REBUILD_FROM_CORE003B'}
    writej(REPORTS/'DATA_RECONCILIATION_trigger.json',payload)
def run_once():
    if not BASE.exists():state('WAITING',f'missing {BASE}');return
    state('RUNNING','Scanning compatible incoming datasets')
    base_cols=header(BASE);base_ids=set(pd.read_csv(BASE,usecols=['race_horse_id'],low_memory=False)['race_horse_id'].astype(str));before=sig(BASE)
    actions=[];accepted_frames=[];seen_new=set()
    for p in candidates():
        ok,detail=compatible(p,base_cols);row={'updated':now(),'candidate':str(p),'candidate_sha256':sig(p),'status':'QUARANTINED',**detail}
        if not ok:actions.append(row);continue
        try:df=pd.read_csv(p,usecols=base_cols,low_memory=False)
        except Exception as e:row.update(status='QUARANTINED',reason='READ_FAILED',error=repr(e));actions.append(row);continue
        issues=validate_rows(df)
        if issues:row.update(status='QUARANTINED',reason='ROW_VALIDATION_FAILED',issues='|'.join(issues));actions.append(row);continue
        ids=df['race_horse_id'].astype(str);newmask=~ids.isin(base_ids|seen_new);new=df.loc[newmask].copy();dup=int((~newmask).sum())
        if new.empty:row.update(status='NOOP',reason='NO_NEW_ROWS',rows=len(df),duplicate_or_existing_rows=dup,new_rows=0);actions.append(row);continue
        seen_new.update(new['race_horse_id'].astype(str));accepted_frames.append(new);row.update(status='ACCEPTED',reason='EXACT_CORE003B_SCHEMA_AND_ROW_GATES',rows=len(df),duplicate_or_existing_rows=dup,new_rows=len(new),new_races=int(new['race_id'].nunique()),new_nar_rows=int((pd.to_numeric(new['race_scope_cd'],errors='coerce')==2).sum()),new_jra_rows=int((pd.to_numeric(new['race_scope_cd'],errors='coerce')==1).sum()));actions.append(row)
    promoted=sum(int(x.get('new_rows') or 0) for x in actions if x.get('status')=='ACCEPTED')
    if accepted_frames:
        tmp=BASE.with_suffix('.reconcile.tmp.csv')
        with BASE.open('rb') as src,tmp.open('wb') as dst:
            while True:
                b=src.read(1024*1024)
                if not b:break
                dst.write(b)
        for frame in accepted_frames:
            frame.to_csv(tmp,mode='a',header=False,index=False,encoding='utf-8')
        # final integrity guard before atomic replacement
        check=pd.read_csv(tmp,usecols=['race_horse_id','race_id','race_date','race_scope_cd','label_win','label_top2','label_top3'],low_memory=False)
        if check['race_horse_id'].astype(str).duplicated().any():
            tmp.unlink(missing_ok=True);raise RuntimeError('reconciled file would contain duplicate race_horse_id')
        if not normalize_scope(check['race_scope_cd']).all():
            tmp.unlink(missing_ok=True);raise RuntimeError('reconciled file would contain invalid scope')
        tmp.replace(BASE)
    after=sig(BASE)
    if after!=before:trigger_downstream(before,after)
    append_ledger(actions)
    inv=readj(INVENTORY,{}) or {};pg_gap=((inv.get('domains') or {}).get('NAR') or {}).get('unutilized_races',0)
    quarantined=sum(1 for x in actions if x.get('status')=='QUARANTINED')
    summary={'status':'PASS','updated':now(),'source_signature_before':before,'source_signature_after':after,'changed':after!=before,'promoted_rows':promoted,'accepted_files':sum(1 for x in actions if x.get('status')=='ACCEPTED'),'quarantined_files':quarantined,'noop_files':sum(1 for x in actions if x.get('status')=='NOOP'),'inventory_nar_unutilized_races':pg_gap,'policy':'auto-merge only exact CORE-003B schema + domestic + labeled + unique race_horse_id; everything else quarantined','downstream_rebuild_required':after!=before}
    writej(SUMMARY,summary);writej(PLAN,{'updated':now(),'candidates':actions,'summary':summary});state('PASS','Reconciliation complete',summary);log(f"RECONCILIATION PASS promoted_rows={promoted} quarantined={quarantined} changed={after!=before}")

def main():
    log('DATA RECONCILIATION DIRECTOR START')
    while True:
        try:run_once()
        except Exception:
            err=traceback.format_exc();log(err);state('BLOCKED',err[-1800:])
        time.sleep(INTERVAL)
if __name__=='__main__':main()
