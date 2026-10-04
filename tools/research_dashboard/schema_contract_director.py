from __future__ import annotations
import hashlib,json,os
from datetime import datetime
from pathlib import Path
import pandas as pd
ROOT=Path(os.environ.get('THE_JOCKEY_RESEARCH_ROOT',Path.home()/'Downloads'/'THE-JOCKEY-RESEARCH'));CORE=ROOT/'CORE';DATA=CORE/'data';REPORTS=CORE/'reports';CHECK=ROOT/'checkpoints'
STATE=CHECK/'schema_contract_director_state.json';REPORT=REPORTS/'SCHEMA_CONTRACT_report.json'
FILES=[DATA/'CORE-003B_historical_features.csv',DATA/'CORE-004_field_strength_v2.csv',DATA/'CORE-010_calibrated_probabilities.csv']
REQUIRED={'CORE-003B_historical_features.csv':{'race_id','race_horse_id','horse_id','race_date','race_scope_cd','label_win','label_top2','label_top3'},'CORE-004_field_strength_v2.csv':{'race_id','race_horse_id','horse_id','race_date','race_scope_cd','field_strength_v2','ability_vs_field','label_win','label_top2','label_top3'}}
for p in (REPORTS,CHECK):p.mkdir(parents=True,exist_ok=True)
def now():return datetime.now().astimezone().isoformat()
def writej(p,o):
 t=p.with_suffix(p.suffix+'.tmp');t.write_text(json.dumps(o,ensure_ascii=False,indent=2),encoding='utf-8');t.replace(p)
def run_once():
 checks=[];blocked=False
 for path in FILES:
  if not path.exists():checks.append({'file':path.name,'status':'MISSING'});continue
  cols=list(pd.read_csv(path,nrows=0).columns);req=REQUIRED.get(path.name,set());missing=sorted(req-set(cols));dup=[c for c in cols if cols.count(c)>1];sig=hashlib.sha256('|'.join(cols).encode()).hexdigest()[:16]
  status='BLOCKED' if missing or dup else 'PASS';blocked|=status=='BLOCKED';checks.append({'file':path.name,'status':status,'columns':len(cols),'schema_hash':sig,'missing_required':missing,'duplicate_columns':sorted(set(dup))})
 out={'updated':now(),'status':'BLOCKED' if blocked else 'PASS','checks':checks};writej(REPORT,out);writej(STATE,{'pid':os.getpid(),'updated':now(),'status':out['status'],'detail':'schema contract audit','report':str(REPORT)});return out
