from __future__ import annotations

from typing import Any

def inject(materials:dict[str,Any],cycle:dict[str,Any])->dict[str,Any]:
 out=dict(materials or {});cards=list(out.get('materials') or [])
 for d in (cycle or {}).get('decisions',[]):
  if not isinstance(d,dict):continue
  bid=str(d.get('brief_id') or 'unknown');status=str(d.get('status') or '');action=str(d.get('action') or '')
  evidence={'source':'RESEARCH_CYCLE_decisions.json','brief_id':bid,'idea_key':d.get('idea_key'),'split_id':d.get('split_id'),'cycle_status':status,'reason':d.get('reason'),'missing_capability':d.get('missing_capability'),'test_oos_used_for_decision':False}
  if action=='PREPARE_FORWARD_BLIND':
   cards.append({'key':f'cycle-blind:{bid}','title':'昇格候補をForward Blindへ送る','department':'AUDIT','kind':'RESEARCH_CYCLE_BLIND','evidence':evidence,'impact':5,'urgency':4,'confidence':5,'cost':2,'risk':1,'worker':'blind_evaluation_director'})
  elif action=='GENERATE_NEXT_HYPOTHESIS':
   cards.append({'key':f'cycle-hypothesis:{bid}','title':'研究結果から次仮説を生成','department':'RESEARCH','kind':'RESEARCH_CYCLE_NEXT_HYPOTHESIS','evidence':evidence,'impact':4,'urgency':3,'confidence':4,'cost':2,'risk':1,'worker':'hypothesis_generator'})
  elif action=='BUILD_EXECUTOR_CAPABILITY':
   worker=d.get('execution_worker') or 'research_factory_director'
   cards.append({'key':f'cycle-capability:{bid}','title':f"研究実行能力を補強: {d.get('missing_capability') or d.get('kind')}",'department':'FOUNDATION','kind':'RESEARCH_CAPABILITY_GAP','evidence':evidence,'impact':5,'urgency':4,'confidence':5,'cost':3,'risk':1,'worker':worker})
  elif action=='KEEP_RUNNING':
   cards.append({'key':f'cycle-running:{bid}','title':'Research Briefの実験を継続','department':'RESEARCH','kind':'RESEARCH_CYCLE_RUNNING','evidence':evidence,'impact':3,'urgency':2,'confidence':5,'cost':2,'risk':1,'worker':d.get('execution_worker') or 'experiment_director'})
 uniq={}
 for c in cards:
  key=str(c.get('key') or f'UNKEYED:{len(uniq)}');old=uniq.get(key)
  if old is None or int(c.get('impact',0))+int(c.get('urgency',0))>int(old.get('impact',0))+int(old.get('urgency',0)):uniq[key]=c
 out['materials']=list(uniq.values());out['count']=len(uniq);out['cycle_injected']=True
 return out
