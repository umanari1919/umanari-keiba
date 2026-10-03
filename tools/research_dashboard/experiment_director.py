from __future__ import annotations
import hashlib, json, os, time, traceback
from datetime import datetime
from pathlib import Path
import numpy as np, pandas as pd

ROOT=Path(os.environ.get('THE_JOCKEY_RESEARCH_ROOT',Path.home()/'Downloads'/'THE-JOCKEY-RESEARCH'))
CORE=ROOT/'CORE'; DATA=CORE/'data'; REPORTS=CORE/'reports'; MODELS=CORE/'models'/'EXPERIMENTS'; CHECK=ROOT/'checkpoints'
LOG=ROOT/'logs'/'experiment_director.log'; STATE=CHECK/'experiment_director_state.json'; LEDGER=REPORTS/'EXPERIMENT_ledger.csv'; REGISTRY=REPORTS/'EXPERIMENT_registry.json'; HYP=REPORTS/'HYPOTHESIS_queue.json'; PLAN=REPORTS/'TEMPORAL_SPLIT_plan.json'
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
def source_signature(path):
    st=path.stat();return hashlib.sha256(f'{st.st_size}:{st.st_mtime_ns}'.encode()).hexdigest()
def split_id(plan):
    parts=[]
    for name in ['TRAIN','VALIDATION','SELECTION','TEST','OOS']:
        s=(plan.get('splits') or {}).get(name,{})
        parts.extend([name,str(s.get('start_date')),str(s.get('end_date'))])
    return hashlib.sha256('|'.join(parts).encode()).hexdigest()[:16]
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
def adaptive_space(current_split):
    q=readj(HYP,{}) or {};out=[]
    if q.get('split_id') not in (None,current_split):return out
    for c in q.get('candidates',[]):
        if all(k in c for k in ['target','feature_set','config','depth','lr','l2','iters','seed']):out.append(c)
    return out
def candidate_space(current_split):
    base=base_space();adaptive=adaptive_space(current_split);seen=set();out=[]
    for c in adaptive+base:
        k=key(c)
        if k in seen:continue
        seen.add(k);out.append(c)
    return out
def key(c):return f"{c['target']}|{c['feature_set']}|{c['config']}|{c['seed']}"
def done_keys(current_split):
    if not LEDGER.exists():return set()
    try:
        d=pd.read_csv(LEDGER,usecols=lambda c:c in ['experiment_key','split_id'])
        if 'split_id' not in d.columns:return set()
        d=d[d.split_id.astype(str)==str(current_split)]
        return set(d.experiment_key.astype(str))
    except Exception:return set()
def append(row):pd.DataFrame([row]).to_csv(LEDGER,mode='a',header=not LEDGER.exists(),index=False,encoding='utf-8-sig')

class Engine:
    def __init__(self):self.src=None;self.mtime=None;self.df=None;self.sets=None;self.splits={};self.plan=None;self.split_id=None
    def ensure_data(self):
        src=DATA/'CORE-004_field_strength_v2.csv'
        if not src.exists():state('WAITING','CORE-004 missing');return False
        plan=readj(PLAN,{}) or {}
        if not plan or not plan.get('splits'):
            state('WAITING','Temporal split plan not ready');return False
        if plan.get('status')=='BLOCKED':
            state('BLOCKED','Temporal/sample gate blocked',{'blockers':(plan.get('gates') or {}).get('blockers',[])});return False
        sig=source_signature(src)
        if plan.get('source_signature')!=sig:
            state('WAITING','Temporal split plan is stale; optimizer will refresh');return False
        sid=split_id(plan);mt=src.stat().st_mtime_ns
        if self.df is not None and self.mtime==mt and self.split_id==sid:return True
        log(f'TURBO DATA LOAD START split={sid}')
        df=pd.read_csv(src,low_memory=False);df['race_date']=pd.to_datetime(df.race_date,errors='coerce')
        scope=pd.to_numeric(df.race_scope_cd,errors='coerce');df=df[scope.isin([1,2])].copy();dates=df.race_date.dt.normalize()
        for c in ['race_scope_cd','racecourse_cd','track_cd','sex_cd','jockey_cd','trainer_cd']:
            if c in df:df[c]=df[c].fillna('MISSING').astype(str)
        masks={}
        mapping={'train':'TRAIN','val':'VALIDATION','sel':'SELECTION','test':'TEST','oos':'OOS'}
        for short,name in mapping.items():
            s=plan['splits'][name];start=pd.Timestamp(s['start_date']);end=pd.Timestamp(s['end_date']);masks[short]=dates.between(start,end,inclusive='both')
        self.src=src;self.mtime=mt;self.df=df;self.sets=feature_sets(df);self.splits=masks;self.plan=plan;self.split_id=sid
        sizes={k:int(v.sum()) for k,v in masks.items()};log(f'TURBO DATA READY rows={len(df):,} split={sid} sizes={sizes} threads={THREADS}')
        return True
    def run(self,c):
        from catboost import CatBoostClassifier
        target=c['target'];feats=self.sets[c['feature_set']];cats=[x for x in feats if x in {'race_scope_cd','racecourse_cd','track_cd','sex_cd','jockey_cd','trainer_cd'}]
        parts={n:self.df[m & self.df[target].notna()] for n,m in self.splits.items()}
        if min(map(len,parts.values()))==0:
            row={'experiment_key':key(c),'split_id':self.split_id,'status':'REJECT_EMPTY_SPLIT','updated':now(),**c};append(row);return row
        m=CatBoostClassifier(loss_function='Logloss',eval_metric='Logloss',iterations=int(c['iters']),depth=int(c['depth']),learning_rate=float(c['lr']),l2_leaf_reg=float(c['l2']),random_seed=int(c['seed']),verbose=False,allow_writing_files=False,thread_count=THREADS)
        m.fit(parts['train'][feats],parts['train'][target],cat_features=cats,eval_set=(parts['val'][feats],parts['val'][target]),early_stopping_rounds=80,use_best_model=True)
        met={}
        for label,n in [('SELECTION','sel'),('TEST','test'),('OOS','oos')]:
            p=m.predict_proba(parts[n][feats])[:,1];met[label]={'logloss':ll(parts[n][target],p),'auc':auc(parts[n][target],p),'rows':len(parts[n])}
        reg=readj(REGISTRY,{}) or {}
        if reg.get('split_id')!=self.split_id:reg={'version':2,'split_id':self.split_id,'targets':{}}
        entry=reg.setdefault('targets',{}).setdefault(target,{});champ=entry.get('champion');promote=champ is None or met['SELECTION']['logloss']<champ['selection_logloss']-0.0005;path=''
        if promote:
            d=MODELS/self.split_id/target;d.mkdir(parents=True,exist_ok=True);path=str(d/(key(c).replace('|','_')+'.cbm'));m.save_model(path);entry['champion']={'experiment_key':key(c),'model_path':path,'feature_set':c['feature_set'],'features':feats,'selection_logloss':met['SELECTION']['logloss'],'test':met['TEST'],'oos_report_only':met['OOS'],'split_id':self.split_id,'updated':now()};writej(REGISTRY,reg)
        row={'experiment_key':key(c),'split_id':self.split_id,'status':'PROMOTE' if promote else 'KEEP','updated':now(),**c,'trees':int(m.tree_count_),'features':len(feats),'selection_logloss':met['SELECTION']['logloss'],'selection_auc':met['SELECTION']['auc'],'test_logloss':met['TEST']['logloss'],'test_auc':met['TEST']['auc'],'oos_logloss_report_only':met['OOS']['logloss'],'oos_auc_report_only':met['OOS']['auc'],'model_path':path}
        append(row);return row

def main():
    log(f'EXPERIMENT DIRECTOR TURBO START threads={THREADS}');eng=Engine()
    while True:
        try:
            if not eng.ensure_data():time.sleep(15);continue
            try:from catboost import CatBoostClassifier
            except Exception as e:state('BLOCKED',f'catboost unavailable: {e}');time.sleep(60);continue
            space=candidate_space(eng.split_id);done=done_keys(eng.split_id);cand=next((c for c in space if key(c) not in done),None)
            if cand is None:
                state('WAITING','All known hypotheses exhausted; waiting for generator',{'split_id':eng.split_id,'completed':len(done),'total':len(space),'remaining':0});time.sleep(15);continue
            adaptive=sum(1 for c in space if c.get('source')=='HYPOTHESIS_GEN')
            state('RUNNING',key(cand),{'split_id':eng.split_id,'completed':len(done),'total':len(space),'remaining':max(0,len(space)-len(done)),'adaptive_candidates':adaptive,'date_range':eng.plan.get('date_range')})
            started=time.time();row=eng.run(cand);elapsed=round(time.time()-started,1);done.add(key(cand));log(f"TURBO {row['status']} {row['experiment_key']} split={eng.split_id} src={row.get('source','BASE')} sec={elapsed} selection={row.get('selection_logloss','-')}")
            state('RUNNING','next immediately',{'split_id':eng.split_id,'completed':len(done),'total':len(space),'remaining':max(0,len(space)-len(done)),'adaptive_candidates':adaptive,'last':row['experiment_key'],'last_result':row['status'],'last_seconds':elapsed})
        except Exception:
            err=traceback.format_exc();log(err);state('BLOCKED',err[-1800:]);time.sleep(ERROR_SLEEP)
if __name__=='__main__':main()
