from __future__ import annotations
import json, os, time, traceback
from datetime import datetime
from pathlib import Path
import numpy as np, pandas as pd

ROOT=Path(os.environ.get('THE_JOCKEY_RESEARCH_ROOT',Path.home()/'Downloads'/'THE-JOCKEY-RESEARCH'))
CORE=ROOT/'CORE'; DATA=CORE/'data'; REPORTS=CORE/'reports'; MODELS=CORE/'models'/'EXPERIMENTS'; CHECK=ROOT/'checkpoints'
LOG=ROOT/'logs'/'experiment_director.log'; STATE=CHECK/'experiment_director_state.json'; LEDGER=REPORTS/'EXPERIMENT_ledger.csv'; REGISTRY=REPORTS/'EXPERIMENT_registry.json'; HYP=REPORTS/'HYPOTHESIS_queue.json'
THREADS=max(1,int(os.environ.get('THE_JOCKEY_EXPERIMENT_THREADS',str(os.cpu_count() or 4))))
ERROR_SLEEP=max(10,int(os.environ.get('THE_JOCKEY_EXPERIMENT_ERROR_SLEEP','20')))
for p in (MODELS,CHECK,LOG.parent,REPORTS):p.mkdir(parents=True,exist_ok=True)

def now():return datetime.now().astimezone().isoformat()
def readj(p,d=None):
    try:return json.loads(p.read_text(encoding='utf-8-sig'))
    except Exception:return d
def writej(p,o):
    t=p.with_suffix(p.suffix+'.tmp');t.write_text(json.dumps(o,ensure_ascii=False,indent=2),encoding='utf-8');t.replace(p)
def log(s):
    line=f'[{now()}] {s}';print(line,flush=True)
    with LOG.open('a',encoding='utf-8') as f:f.write(line+'\n')
def state(status,detail='',extra=None):
    x={'pid':os.getpid(),'updated':now(),'status':status,'detail':detail,'mode':'TURBO','threads':THREADS}
    if extra:x.update(extra)
    writej(STATE,x)
def ll(y,p):
    y=np.asarray(y,float);p=np.clip(np.asarray(p,float),1e-9,1-1e-9);return float(-np.mean(y*np.log(p)+(1-y)*np.log(1-p)))
def auc(y,p):
    t=pd.DataFrame({'y':y,'p':p}).dropna()
    if t.empty:return np.nan
    y=t.y.astype(int).to_numpy();p=t.p.astype(float).to_numpy();pos=int((y==1).sum());neg=int((y==0).sum())
    if pos==0 or neg==0:return np.nan
    r=pd.Series(p).rank(method='average').to_numpy();return float((r[y==1].sum()-pos*(pos+1)/2)/(pos*neg))
def feature_sets(df):
    base=[c for c in ['race_scope_cd','racecourse_cd','distance_m','track_cd','horse_age','sex_cd','carried_weight_kg','frame_no','horse_no','jockey_cd','trainer_cd'] if c in df]
    hist=base+[c for c in ['prior_start_count','days_since_last_run','prior_win_rate','prior_top2_rate','prior_top3_rate','prior_avg_finish_pct','prior_avg_time_diff','prior_avg_last3f','prior_avg_corner4_pct','recent3_time_diff_mean','recent5_time_diff_mean','recent3_finish_pct_mean','recent5_finish_pct_mean','recent3_last3f_mean','recent5_last3f_mean','recent3_corner4_pct_mean','recent5_corner4_pct_mean','same_distance_prior_count','same_distance_prior_avg_time_diff','same_track_prior_count','same_track_prior_avg_time_diff','same_racecourse_prior_count','same_racecourse_prior_avg_time_diff','same_course_surface_prior_count','same_course_surface_prior_avg_time_diff'] if c in df]
    field=hist+[c for c in ['horse_pre_ability_v1','field_strength_v2','field_strength_coverage','ability_vs_field','ability_percentile_in_race','last_field_strength','recent3_field_strength_mean','recent5_field_strength_mean','prior_avg_field_strength','field_strength_trend'] if c in df]
    return {'HIST':hist,'FIELD':field,'COMPACT':[c for c in field if c not in {'frame_no','horse_no'}]}
def base_space():
    cfg=[('D4_LR06',4,.06,4,600),('D5_LR04',5,.04,5,800),('D6_LR03',6,.03,8,1000),('D7_LR025',7,.025,10,1100),('D8_LR02',8,.02,12,1200),('D6_REG15',6,.03,15,1000)]
    out=[]
    for target in ['label_win','label_top2','label_top3']:
        for fset in ['HIST','FIELD','COMPACT']:
            for name,depth,lr,l2,iters in cfg:
                for seed in [20261004,20261041,20261103]:out.append({'source':'BASE','target':target,'feature_set':fset,'config':name,'depth':depth,'lr':lr,'l2':l2,'iters':iters,'seed':seed})
    return out
def adaptive_space():
    q=readj(HYP,{}) or {};out=[]
    for c in q.get('candidates',[]):
        if all(k in c for k in ['target','feature_set','config','depth','lr','l2','iters','seed']):out.append(c)
    return out
def candidate_space():
    base=base_space();adaptive=adaptive_space();seen=set();out=[]
    # Once adaptive hypotheses exist, interleave them ahead of remaining base candidates.
    for c in adaptive+base:
        k=key(c)
        if k in seen:continue
        seen.add(k);out.append(c)
    return out
def key(c):return f"{c['target']}|{c['feature_set']}|{c['config']}|{c['seed']}"
def done_keys():
    if not LEDGER.exists():return set()
    try:return set(pd.read_csv(LEDGER,usecols=['experiment_key']).experiment_key.astype(str))
    except Exception:return set()
def append(row):pd.DataFrame([row]).to_csv(LEDGER,mode='a',header=not LEDGER.exists(),index=False,encoding='utf-8-sig')

class Engine:
    def __init__(self):self.src=None;self.mtime=None;self.df=None;self.sets=None;self.splits={}
    def ensure_data(self):
        src=DATA/'CORE-004_field_strength_v2.csv'
        if not src.exists():state('WAITING','CORE-004 missing');return False
        mt=src.stat().st_mtime
        if self.df is not None and self.mtime==mt:return True
        log('TURBO DATA LOAD START')
        df=pd.read_csv(src,low_memory=False);df['race_date']=pd.to_datetime(df.race_date,errors='coerce');df['year']=df.race_date.dt.year;df=df[df.race_scope_cd.isin([1,2])].copy()
        for c in ['race_scope_cd','racecourse_cd','track_cd','sex_cd','jockey_cd','trainer_cd']:
            if c in df:df[c]=df[c].fillna('MISSING').astype(str)
        self.src=src;self.mtime=mt;self.df=df;self.sets=feature_sets(df)
        self.splits={'train':df.year.between(2017,2022),'val':df.year.eq(2023),'sel':df.year.eq(2024),'test':df.year.eq(2025),'oos':df.year.eq(2026)}
        log(f'TURBO DATA READY rows={len(df):,} threads={THREADS}')
        return True
    def run(self,c):
        from catboost import CatBoostClassifier
        target=c['target'];feats=self.sets[c['feature_set']];cats=[x for x in feats if x in {'race_scope_cd','racecourse_cd','track_cd','sex_cd','jockey_cd','trainer_cd'}]
        parts={n:self.df[m & self.df[target].notna()] for n,m in self.splits.items()}
        if min(map(len,parts.values()))==0:
            row={'experiment_key':key(c),'status':'REJECT_EMPTY_SPLIT','updated':now(),**c};append(row);return row
        m=CatBoostClassifier(loss_function='Logloss',eval_metric='Logloss',iterations=int(c['iters']),depth=int(c['depth']),learning_rate=float(c['lr']),l2_leaf_reg=float(c['l2']),random_seed=int(c['seed']),verbose=False,allow_writing_files=False,thread_count=THREADS)
        m.fit(parts['train'][feats],parts['train'][target],cat_features=cats,eval_set=(parts['val'][feats],parts['val'][target]),early_stopping_rounds=80,use_best_model=True)
        met={}
        for label,n in [('SELECT_2024','sel'),('TEST_2025','test'),('OOS_2026','oos')]:
            p=m.predict_proba(parts[n][feats])[:,1];met[label]={'logloss':ll(parts[n][target],p),'auc':auc(parts[n][target],p),'rows':len(parts[n])}
        reg=readj(REGISTRY,{'targets':{}}) or {'targets':{}};entry=reg.setdefault('targets',{}).setdefault(target,{});champ=entry.get('champion');promote=champ is None or met['SELECT_2024']['logloss']<champ['select_2024_logloss']-0.0005;path=''
        if promote:
            d=MODELS/target;d.mkdir(parents=True,exist_ok=True);path=str(d/(key(c).replace('|','_')+'.cbm'));m.save_model(path);entry['champion']={'experiment_key':key(c),'model_path':path,'feature_set':c['feature_set'],'features':feats,'select_2024_logloss':met['SELECT_2024']['logloss'],'test_2025':met['TEST_2025'],'oos_2026_report_only':met['OOS_2026'],'updated':now()};writej(REGISTRY,reg)
        row={'experiment_key':key(c),'status':'PROMOTE' if promote else 'KEEP','updated':now(),**c,'trees':int(m.tree_count_),'features':len(feats),'select_2024_logloss':met['SELECT_2024']['logloss'],'select_2024_auc':met['SELECT_2024']['auc'],'test_2025_logloss':met['TEST_2025']['logloss'],'test_2025_auc':met['TEST_2025']['auc'],'oos_2026_logloss_report_only':met['OOS_2026']['logloss'],'oos_2026_auc_report_only':met['OOS_2026']['auc'],'model_path':path}
        append(row);return row

def main():
    log(f'EXPERIMENT DIRECTOR TURBO START threads={THREADS}');eng=Engine()
    while True:
        try:
            if not eng.ensure_data():time.sleep(30);continue
            try:from catboost import CatBoostClassifier
            except Exception as e:state('BLOCKED',f'catboost unavailable: {e}');time.sleep(60);continue
            space=candidate_space();done=done_keys();cand=next((c for c in space if key(c) not in done),None)
            if cand is None:
                state('WAITING','All known hypotheses exhausted; waiting for generator',{'completed':len(done),'total':len(space),'remaining':0});time.sleep(15);continue
            adaptive=sum(1 for c in space if c.get('source')=='HYPOTHESIS_GEN')
            state('RUNNING',key(cand),{'completed':len(done),'total':len(space),'remaining':max(0,len(space)-len(done)),'adaptive_candidates':adaptive})
            started=time.time();row=eng.run(cand);elapsed=round(time.time()-started,1);done.add(key(cand));log(f"TURBO {row['status']} {row['experiment_key']} src={row.get('source','BASE')} sec={elapsed} select2024={row.get('select_2024_logloss','-')}")
            state('RUNNING','next immediately',{'completed':len(done),'total':len(space),'remaining':max(0,len(space)-len(done)),'adaptive_candidates':adaptive,'last':row['experiment_key'],'last_result':row['status'],'last_seconds':elapsed})
        except Exception:
            err=traceback.format_exc();log(err);state('BLOCKED',err[-1800:]);time.sleep(ERROR_SLEEP)
if __name__=='__main__':main()
