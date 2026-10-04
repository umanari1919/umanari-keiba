from __future__ import annotations

import json,os
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT=Path(os.environ.get('THE_JOCKEY_RESEARCH_ROOT',Path.home()/'Downloads'/'THE-JOCKEY-RESEARCH'));REPORTS=ROOT/'CORE'/'reports';OUT=REPORTS/'RESEARCH_EXECUTION_bindings.json'
def now():return datetime.now().astimezone().isoformat()
def writej(p,o):
 p=Path(p);t=p.with_suffix(p.suffix+'.tmp');t.write_text(json.dumps(o,ensure_ascii=False,indent=2),encoding='utf-8');t.replace(p)
def build(portfolio:dict[str,Any],brief_queue:dict[str,Any])->dict[str,Any]:
 by_id={str(b.get('brief_id')):b for b in (brief_queue or {}).get('briefs',[]) if isinstance(b,dict) and b.get('brief_id')}
 bindings={}
 for mission in (portfolio or {}).get('active_missions',[]):
  if not isinstance(mission,dict):continue
  evidence=mission.get('evidence') or {};bid=str(evidence.get('brief_id') or '')
  if not bid or bid not in by_id:continue
  brief=by_id[bid];worker=str(brief.get('execution_worker') or '')
  if not worker:continue
  bindings[worker]={'brief_id':bid,'split_id':brief.get('split_id'),'idea_key':brief.get('idea_key'),'kind':brief.get('kind'),'bound_at':now(),'binding_source':'MISSION_PORTFOLIO_ACTIVE_MISSION','test_oos_feedback_prohibited':True}
 out={'updated':now(),'count':len(bindings),'bindings':bindings,'policy':'Research results may be attributed to a brief only through an explicit active binding or an equivalent explicit brief_id written by the executor.'};writej(OUT,out);return out
