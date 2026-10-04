from __future__ import annotations

import csv,json,os,time,traceback
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT=Path(os.environ.get('THE_JOCKEY_RESEARCH_ROOT',Path.home()/'Downloads'/'THE-JOCKEY-RESEARCH'))
CORE=ROOT/'CORE';DATA=CORE/'data';REPORTS=CORE/'reports';CHECK=ROOT/'checkpoints'
STATE=CHECK/'research_factory_director_state.json';SUMMARY=REPORTS/'RESEARCH_FACTORY_summary.json';IDEAS=REPORTS/'RESEARCH_FACTORY_ideas.json';BACKLOG=REPORTS/'RESEARCH_FACTORY_backlog.csv'
BASE=DATA/'CORE-004_field_strength_v2.csv';INTERVAL=max(300,int(os.environ.get('THE_JOCKEY_RESEARCH_FACTORY_INTERVAL','1800')))
for p in (REPORTS,CHECK):p.mkdir(parents=True,exist_ok=True)

def now():return datetime.now().astimezone().isoformat()
def readj(p,d=None):
 try:return json.loads(Path(p).read_text(encoding='utf-8-sig'))
 except Exception:return d
def writej(p,o):
 t=Path(p).with_suffix(Path(p).suffix+'.tmp');t.write_text(json.dumps(o,ensure_ascii=False,indent=2),encoding='utf-8');t.replace(p)
def columns(path):
 if not Path(path).exists():return set()
 try:
  import duckdb
  rel=f"read_parquet('{str(path).replace("'","''")}')" if Path(path).suffix.lower()=='.parquet' else f"read_csv_auto('{str(path).replace("'","''")}',header=true,sample_size=-1)"
  con=duckdb.connect()
  try:return {r[0] for r in con.execute(f'DESCRIBE SELECT * FROM {rel}').fetchall()}
  finally:con.close()
 except Exception:
  import pandas as pd
  try:return set(pd.read_csv(path,nrows=0).columns)
  except Exception:return set()
def idea(key,title,kind,required,evidence,worker='feature_research_director',impact=3,confidence=3,notes=''):
 req=set(required);available=set(evidence.get('available_columns') or []);missing=sorted(req-available);status='READY' if not missing else 'NEEDS_DATA'
 return {'key':key,'title':title,'kind':kind,'status':status,'required_columns':sorted(req),'missing_columns':missing,'evidence':evidence,'worker':worker,'impact':impact,'confidence':confidence,'notes':notes}
def _catalog_signal():
 p=REPORTS/'feature_research_catalog.csv';out=[]
 if not p.exists():return out
 try:
  with p.open('r',encoding='utf-8-sig',newline='') as f:
   rows=list(csv.DictReader(f))
  for r in rows:
   if str(r.get('decision'))=='PROMOTE_CANDIDATE':out.append(str(r.get('feature') or ''))
 except Exception:pass
 return [x for x in out if x]
def build_ideas(cols:set[str])->list[dict[str,Any]]:
 avail=sorted(cols);base={'available_columns':avail,'source':str(BASE)};ideas=[]
 templates=[
  ('field-strength-step','Field Strengthの昇級・降級差を専門研究','FIELD_STRENGTH',['field_strength_v2','prior_avg_field_strength','race_scope_cd'],5,'相手関係の変化を独立研究テーマ化する。'),
  ('form-momentum','近3走と近5走のフォーム変化を研究','FORM_MOMENTUM',['recent3_time_diff_mean','recent5_time_diff_mean','recent3_finish_pct_mean','recent5_finish_pct_mean'],4,'短期フォームと中期フォームの乖離を検証する。'),
  ('first-start','初出走・低経験馬の専用評価を研究','FIRST_START',['prior_start_count','race_scope_cd'],4,'prior_start_count=0/少数の標本を別セグメントとして扱えるか検証する。'),
  ('distance-adaptation','距離経験と能力差の相互作用を研究','DISTANCE',['same_distance_prior_count','prior_start_count','prior_avg_time_diff','same_distance_prior_avg_time_diff'],4,'距離経験量とタイム差の組合せを検証する。'),
  ('track-adaptation','競馬場・コース経験の相互作用を研究','TRACK',['same_racecourse_prior_count','prior_start_count','same_racecourse_prior_avg_time_diff'],4,'競馬場経験を汎用能力と分離して検証する。'),
  ('jra-nar-domain-gap','JRA/NARで特徴量の効き方が違うか検証','DOMAIN_GAP',['race_scope_cd','label_win','label_top2','label_top3'],5,'同一特徴量のDomain別安定性を比較する。'),
 ]
 for k,t,kind,req,impact,note in templates:ideas.append(idea(k,t,kind,req,base,'domain_research_director' if kind=='DOMAIN_GAP' else 'feature_research_director',impact,4,note))
 # JRA morning / debut / obstacle are only researchable when the dataset exposes explicit segmentation columns.
 morning_candidates=[c for c in ('race_number','race_no','post_time','start_time') if c in cols]
 class_candidates=[c for c in ('race_class','race_name','race_type','condition_code') if c in cols]
 obstacle_candidates=[c for c in ('surface','track_type','obstacle_flag') if c in cols]
 evidence={**base,'detected_time_columns':morning_candidates,'detected_class_columns':class_candidates,'detected_obstacle_columns':obstacle_candidates}
 req=['race_scope_cd','label_win']
 if morning_candidates:req.append(morning_candidates[0])
 else:req.append('__JRA_MORNING_SEGMENT_COLUMN__')
 if class_candidates:req.append(class_candidates[0])
 else:req.append('__RACE_CLASS_COLUMN__')
 ideas.append(idea('jra-morning-capital','JRA午前の資金形成仮説をデータ検証','JRA_MORNING',req,evidence,'domain_research_director',5,4,'未勝利・新馬・障害を固定的に有利とみなさず、時間帯×レース種別の差を検証する。'))
 req=['race_scope_cd','label_win']
 if class_candidates:req.append(class_candidates[0])
 else:req.append('__RACE_CLASS_COLUMN__')
 ideas.append(idea('debut-specialist','新馬・初出走専用モデルの成立条件を研究','DEBUT_SPECIALIST',req+['prior_start_count'],evidence,'domain_research_director',4,3,'新馬判定列が無い場合は先にデータ契約を要求する。'))
 req=['race_scope_cd','label_win']
 if obstacle_candidates:req.append(obstacle_candidates[0])
 else:req.append('__OBSTACLE_SEGMENT_COLUMN__')
 ideas.append(idea('obstacle-specialist','障害戦専用モデルの成立条件を研究','OBSTACLE_SPECIALIST',req,evidence,'domain_research_director',4,3,'障害を明示識別できないデータでは実験しない。'))
 strategy=readj(REPORTS/'DECISION_STRATEGY_summary.json',{}) or {}
 if strategy:
  ev={**base,'strategy_report':'DECISION_STRATEGY_summary.json','strategy_status':strategy.get('status')}
  ideas.append(idea('small-ticket-efficiency','MIN-1 / MIN-2 / MIN-3の資金効率を比較','SMALL_TICKET',[],ev,'decision_strategy_director',5,5,'同じ予測snapshot上で点数差だけを比較する。'))
 failures=readj(REPORTS/'FAILURE_ANALYSIS_summary.json',{}) or {};counts=failures.get('reason_counts') or failures.get('counts') or {}
 if isinstance(counts,dict):
  for reason,count in sorted(counts.items(),key=lambda x:x[1] if isinstance(x[1],(int,float)) else 0,reverse=True)[:5]:
   try:n=int(count)
   except Exception:continue
   if n>=5:ideas.append({'key':f'failure-{reason}','title':f'反復失敗パターンを仮説化: {reason}','kind':'FAILURE_DERIVED','status':'READY','required_columns':[],'missing_columns':[],'evidence':{'source':'FAILURE_ANALYSIS_summary.json','reason':reason,'count':n},'worker':'hypothesis_generator','impact':4,'confidence':min(5,2+n//10),'notes':'単発の外れではなく反復パターンだけ研究素材へ昇格。'})
 promoted=_catalog_signal()
 if promoted:ideas.append({'key':'promoted-feature-interactions','title':'昇格特徴量どうしの相互作用を研究','kind':'FEATURE_INTERACTION','status':'READY','required_columns':promoted[:12],'missing_columns':[],'evidence':{'source':'feature_research_catalog.csv','promoted_features':promoted[:12]},'worker':'feature_research_director','impact':4,'confidence':4,'notes':'TEST/OOSは最適化に使わず後段評価のみ。'})
 return ideas
def run_once():
 cols=columns(BASE);items=build_ideas(cols);ready=[x for x in items if x['status']=='READY'];needs=[x for x in items if x['status']=='NEEDS_DATA']
 items.sort(key=lambda x:(x['status']!='READY',-int(x.get('impact',0)),-int(x.get('confidence',0)),x['key']))
 writej(IDEAS,{'updated':now(),'source':str(BASE),'available_column_count':len(cols),'ready_count':len(ready),'needs_data_count':len(needs),'ideas':items,'policy':'Ideas are evidence-gated. Unsupported segmentation becomes NEEDS_DATA, never an assumed horse-racing fact.'})
 if items:
  keys=['key','title','kind','status','impact','confidence','worker','missing_columns','notes']
  with BACKLOG.open('w',encoding='utf-8-sig',newline='') as f:
   w=csv.DictWriter(f,fieldnames=keys);w.writeheader()
   for x in items:w.writerow({k:('|'.join(x[k]) if isinstance(x.get(k),list) else x.get(k)) for k in keys})
 out={'pid':os.getpid(),'updated':now(),'status':'PASS' if cols else 'WAITING','ideas':len(items),'ready':len(ready),'needs_data':len(needs),'top_ready':ready[:5],'top_needs_data':needs[:5]};writej(SUMMARY,out);writej(STATE,out);return out
def main():
 while True:
  try:run_once()
  except Exception:writej(STATE,{'pid':os.getpid(),'updated':now(),'status':'BLOCKED','detail':traceback.format_exc()[-1800:]})
  time.sleep(INTERVAL)
if __name__=='__main__':main()
