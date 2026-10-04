from __future__ import annotations
import csv,hashlib,json,os
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT=Path(os.environ.get('THE_JOCKEY_RESEARCH_ROOT',Path.home()/'Downloads'/'THE-JOCKEY-RESEARCH'))
CORE=ROOT/'CORE';REPORTS=CORE/'reports';LEDGER=REPORTS/'DATA_LINEAGE_ledger.csv';GRAPH=REPORTS/'DATA_LINEAGE_graph.json'
FIELDS=['event_id','recorded_at','event_type','source_id','source_artifact','source_sha256','parent_artifact','parent_sha256','output_artifact','output_sha256','canonical_version','policy','details_json']

def now():return datetime.now().astimezone().isoformat()
def file_sha(path):
 p=Path(path)
 if not p.exists() or not p.is_file():return ''
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()
def _event_id(payload:dict[str,Any])->str:
 stable=json.dumps(payload,ensure_ascii=False,sort_keys=True,default=str).encode()
 return hashlib.sha256(stable).hexdigest()[:24]
def append_event(event_type:str,source_id:str='',source_artifact:str='',parent_artifact:str='',output_artifact:str='',canonical_version:str='',policy:str='',details:dict[str,Any]|None=None)->dict[str,Any]:
 REPORTS.mkdir(parents=True,exist_ok=True)
 base={'event_type':event_type,'source_id':source_id,'source_artifact':source_artifact,'source_sha256':file_sha(source_artifact) if source_artifact else '', 'parent_artifact':parent_artifact,'parent_sha256':file_sha(parent_artifact) if parent_artifact else '', 'output_artifact':output_artifact,'output_sha256':file_sha(output_artifact) if output_artifact else '', 'canonical_version':canonical_version,'policy':policy,'details_json':json.dumps(details or {},ensure_ascii=False,sort_keys=True,default=str)}
 eid=_event_id(base);row={'event_id':eid,'recorded_at':now(),**base}
 existing=set()
 if LEDGER.exists():
  try:
   with LEDGER.open('r',encoding='utf-8-sig',newline='') as f:existing={r.get('event_id','') for r in csv.DictReader(f)}
  except Exception:existing=set()
 if eid not in existing:
  with LEDGER.open('a',encoding='utf-8-sig',newline='') as f:
   w=csv.DictWriter(f,fieldnames=FIELDS); 
   if f.tell()==0:w.writeheader()
   w.writerow(row)
 rebuild_graph()
 return row

def rebuild_graph()->dict[str,Any]:
 nodes={};edges=[]
 if LEDGER.exists():
  with LEDGER.open('r',encoding='utf-8-sig',newline='') as f:
   for r in csv.DictReader(f):
    for key in ('source_artifact','parent_artifact','output_artifact'):
     p=r.get(key) or ''
     if p:nodes[p]={'id':p,'sha256':r.get(key.replace('artifact','sha256')) or ''}
    if r.get('source_artifact') and r.get('output_artifact'):edges.append({'from':r['source_artifact'],'to':r['output_artifact'],'type':r.get('event_type'),'event_id':r.get('event_id')})
    if r.get('parent_artifact') and r.get('output_artifact'):edges.append({'from':r['parent_artifact'],'to':r['output_artifact'],'type':r.get('event_type'),'event_id':r.get('event_id')})
 out={'updated':now(),'nodes':list(nodes.values()),'edges':edges,'policy':'append-only provenance; artifacts are addressed by path + SHA256; no lineage event mutates source data'}
 tmp=GRAPH.with_suffix('.tmp');tmp.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8');tmp.replace(GRAPH);return out
