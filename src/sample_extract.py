import json, subprocess, os, hashlib, re
from pathlib import Path
from datetime import datetime, timezone
ROOT=Path(__file__).resolve().parents[1]
PSQL=r'C:\Program Files\PostgreSQL\18\bin\psql.exe'
QUERIES={
 'JRA': "SELECT coalesce(json_agg(t),'[]'::json) FROM (SELECT trim(race_code) AS race_id, trim(umaban) AS horse_number,trim(ketto_toroku_bango) AS horse_source_id,trim(bamei) AS horse_name,trim(kakutei_chakujun) AS finish_position,trim(ijo_kubun_code) AS abnormal_code FROM public.umagoto_race_joho WHERE kaisai_nen='2025' AND kaisai_gappi='0105' AND keibajo_code IN ('06','07') ORDER BY race_code,umaban LIMIT 1000) t",
 'NAR': "SELECT coalesce(json_agg(t),'[]'::json) FROM (SELECT id AS source_row_id,row_data FROM public.nar_official_horselist_raw WHERE row_data->>'競走年月日'='20230920' AND row_data->>'競馬場'='浦和' AND row_data->>'レース番号'='11' ORDER BY id LIMIT 1000) t"
}
def query(sql):
 sql=re.sub(r"'([^']*[^\x00-\x7f][^']*)'", lambda m:'('+'||'.join('chr('+str(ord(c))+')' for c in m[1])+')',sql)
 env=os.environ.copy();env.update(PGCONNECT_TIMEOUT='3',PGCLIENTENCODING='UTF8',PGOPTIONS='-c default_transaction_read_only=on -c statement_timeout=15000')
 r=subprocess.run([PSQL,'-X','-w','-h','127.0.0.1','-p','5433','-U','postgres','-d','mykeibadb','-At','-c',sql],capture_output=True,encoding='utf-8',env=env,timeout=25)
 if r.returncode:raise RuntimeError(r.stderr)
 return json.loads(r.stdout)
def main():
 folder=ROOT/'datasets'/'sample-v1';folder.mkdir(parents=True,exist_ok=True)
 report={'stage':'02_sample_quality','captured_at':datetime.now(timezone.utc).isoformat(),'read_only':True,'feature_use':'not approved; result and post-race fields excluded from future feature inputs','domains':{},'issues':['race_unified JRA has only 2 rows; unsuitable as unified training source','NAR horse identity and pre-race availability not verified','sample dates differ; not a model evaluation comparison','sample checks do not certify source completeness']}
 for domain,sql in QUERIES.items():
  raw=query(sql);rows=[]
  for r in raw:
   if domain=='NAR':
    d=r['row_data'];r={'source_row_id':r['source_row_id'],'race_id':'NAR|'+d.get('競走年月日','')+'|'+d.get('競馬場','')+'|'+d.get('レース番号',''),'horse_number':d.get('馬番'),'horse_name':d.get('馬名'),'finish_position':d.get('着順'),'horse_source_id':None}
   r['organizer']=domain
   position=str(r.get('finish_position',''))
   numeric=position.isdigit() and int(position)>0
   stopped=domain=='JRA' and r.get('abnormal_code')=='4'
   r['result_status']='DID_NOT_FINISH' if stopped else ('FINISHED' if numeric else 'UNRESOLVED')
   r['label_win']=0 if stopped else (int(int(position)==1) if numeric else None)
   r['identity_status']='SOURCE_ID' if r.get('horse_source_id') else 'UNRESOLVED'
   if domain=='NAR':
    r['provisional_identity']=hashlib.sha256((d.get('馬名','')+'|'+d.get('生年月日','')).encode()).hexdigest()
    r['identity_status']='PROVISIONAL_NAME_BIRTH; NOT_OFFICIAL_ID'
   rows.append(r)
  keys=[(r['race_id'],r['horse_number']) for r in rows]
  invalid=sum(not str(r.get('finish_position','')).isdigit() or int(r['finish_position'])<1 for r in rows)
  path=folder/(domain.lower()+'.json');path.write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
  report['domains'][domain]={'rows':len(rows),'races':len(set(r['race_id'] for r in rows)),'duplicate_runner_keys':len(keys)-len(set(keys)),'non_numeric_or_zero_finish':invalid,'did_not_finish':sum(r['result_status']=='DID_NOT_FINISH' for r in rows),'unresolved_labels':sum(r['label_win'] is None for r in rows),'missing_official_horse_identity':sum(not r.get('horse_source_id') for r in rows),'history_join_approved':False,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'source_table':'umagoto_race_joho' if domain=='JRA' else 'nar_official_horselist_raw','query':sql}
 report['status']='sample_extracted' if all(x['rows'] for x in report['domains'].values()) else 'blocked'
 (folder/'quality.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
 state=json.loads((ROOT/'runtime/status.json').read_text(encoding='utf-8'));state.update(stage='02_sample_quality',status=report['status'],database_read=True,next='抽出品質の問題を処理し、学習に必要な履歴・時点情報を定義する',quality_report=str(folder/'quality.json'))
 (ROOT/'runtime/status.json').write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
