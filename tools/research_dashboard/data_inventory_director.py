from __future__ import annotations
import csv, json, os, time, traceback
from datetime import datetime
from pathlib import Path
import pandas as pd
try:
    from modern_data_engine import inventory_scan, capabilities
except Exception:
    inventory_scan=lambda path: None
    capabilities=lambda: {'duckdb':False,'polars':False,'pyarrow':False}
try:
    from canonical_store import current_manifest, resolve_canonical_source
except Exception:
    current_manifest=lambda: None
    resolve_canonical_source=lambda p: p

ROOT=Path(os.environ.get('THE_JOCKEY_RESEARCH_ROOT',Path.home()/'Downloads'/'THE-JOCKEY-RESEARCH'))
CORE=ROOT/'CORE'; DATA=CORE/'data'; REPORTS=CORE/'reports'; CHECK=ROOT/'checkpoints'; LOG=ROOT/'logs'/'data_inventory_director.log'; STATE=CHECK/'data_inventory_director_state.json'
SUMMARY=REPORTS/'DATA_INVENTORY_summary.json'; SOURCES=REPORTS/'DATA_INVENTORY_sources.csv'; GAP=REPORTS/'DATA_INVENTORY_gap.csv'; PLAN=REPORTS/'TEMPORAL_SPLIT_plan.json'
INTERVAL=max(120,int(os.environ.get('THE_JOCKEY_DATA_INVENTORY_INTERVAL','600')))
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

def norm_scope(v):
    s=str(v).strip().upper()
    if s in {'1','1.0','JRA'}:return 'JRA'
    if s in {'2','2.0','NAR'}:return 'NAR'
    return None

def scan_file(path:Path, role:str):
    out=[]
    if not path.exists():return out
    source_type='PARQUET' if path.suffix.lower()=='.parquet' else 'CSV'
    fast=inventory_scan(path)
    if fast:
        for x in fast:
            out.append({'source_type':source_type,'source':path.name,'role':role,'domain':x['domain'],'rows':x['rows'],'races':x['races'],'horses':x['horses'],'labeled_rows':x['labeled_rows'],'start_date':x['start_date'],'end_date':x['end_date'],'path':str(path),'engine':'DUCKDB'})
        return out
    use=['race_id','race_horse_id','horse_id','race_date','race_scope_cd','label_win','finish_order']
    rows={'JRA':0,'NAR':0};races={'JRA':set(),'NAR':set()};horses={'JRA':set(),'NAR':set()};dates={'JRA':[],'NAR':[]};labeled={'JRA':0,'NAR':0}
    try:
        if source_type=='PARQUET':
            chunks=[pd.read_parquet(path,columns=None)]
        else:
            chunks=pd.read_csv(path,usecols=lambda c:c in use,chunksize=150000,low_memory=False)
        for ch in chunks:
            cols=[c for c in use if c in ch.columns]
            ch=ch[cols]
            if 'race_scope_cd' not in ch:continue
            scopes=ch['race_scope_cd'].map(norm_scope)
            for domain in ('JRA','NAR'):
                m=scopes.eq(domain)
                if not m.any():continue
                x=ch.loc[m]
                rows[domain]+=len(x)
                if 'race_id' in x:races[domain].update(x['race_id'].dropna().astype(str).tolist())
                if 'horse_id' in x:horses[domain].update(x['horse_id'].dropna().astype(str).tolist())
                if 'race_date' in x:
                    d=pd.to_datetime(x['race_date'],errors='coerce').dropna()
                    if len(d):dates[domain].extend([d.min(),d.max()])
                if 'label_win' in x:labeled[domain]+=int(x['label_win'].notna().sum())
                elif 'finish_order' in x:labeled[domain]+=int(x['finish_order'].notna().sum())
        for domain in ('JRA','NAR'):
            ds=dates[domain]
            out.append({'source_type':source_type,'source':path.name,'role':role,'domain':domain,'rows':rows[domain],'races':len(races[domain]),'horses':len(horses[domain]),'labeled_rows':labeled[domain],'start_date':min(ds).date().isoformat() if ds else '', 'end_date':max(ds).date().isoformat() if ds else '', 'path':str(path),'engine':'PANDAS_FALLBACK'})
    except Exception as e:
        out.append({'source_type':source_type,'source':path.name,'role':role,'domain':'ERROR','rows':0,'races':0,'horses':0,'labeled_rows':0,'start_date':'','end_date':'','path':str(path),'engine':'PANDAS_FALLBACK','error':repr(e)})
    return out

def pg_inventory():
    rows=[]
    host=os.environ.get('THE_JOCKEY_PG_HOST','127.0.0.1');port=int(os.environ.get('THE_JOCKEY_PG_PORT','5433'));db=os.environ.get('THE_JOCKEY_PG_DB','mykeibadb')
    user=os.environ.get('THE_JOCKEY_PG_USER') or os.environ.get('PGUSER');password=os.environ.get('THE_JOCKEY_PG_PASSWORD') or os.environ.get('PGPASSWORD')
    try:
        try:import psycopg
        except Exception:psycopg=None
        if psycopg:
            kw={'host':host,'port':port,'dbname':db,'connect_timeout':3};
            if user:kw['user']=user
            if password:kw['password']=password
            con=psycopg.connect(**kw);cur=con.cursor();cur.execute("SET statement_timeout='15s'")
        else:
            import psycopg2
            kw={'host':host,'port':port,'dbname':db,'connect_timeout':3}
            if user:kw['user']=user
            if password:kw['password']=password
            con=psycopg2.connect(**kw);cur=con.cursor();cur.execute("SET statement_timeout='15s'")
        cur.execute("SELECT schemaname,relname,n_live_tup FROM pg_stat_user_tables ORDER BY n_live_tup DESC")
        for schema,table,n in cur.fetchall():
            name=str(table).lower()
            if not any(k in name for k in ('nar','race','horse','runner','entry','result')):continue
            rows.append({'source_type':'POSTGRES','source':f'{schema}.{table}','role':'HOLDING_CANDIDATE','domain':'NAR' if 'nar' in name else 'UNKNOWN','rows':int(n or 0),'races':'','horses':'','labeled_rows':'','start_date':'','end_date':'','path':f'{host}:{port}/{db}'})
        cur.close();con.close()
    except Exception as e:
        rows.append({'source_type':'POSTGRES','source':'connection','role':'UNAVAILABLE','domain':'UNKNOWN','rows':0,'races':'','horses':'','labeled_rows':'','start_date':'','end_date':'','path':f'{host}:{port}/{db}','error':repr(e)})
    return rows

def split_usage():
    p=readj(PLAN,{}) or {};out=[]
    for name,s in (p.get('splits') or {}).items():
        for domain in ('JRA','NAR'):
            d=(s.get('domains') or {}).get(domain,{})
            out.append({'stage':name,'domain':domain,'races':int(d.get('races') or 0),'rows':int(d.get('rows') or 0),'start_date':s.get('start_date',''),'end_date':s.get('end_date','')})
    return out

def run_once():
    state('RUNNING','Scanning holdings and research usage')
    source_rows=[]
    legacy=DATA/'CORE-003B_historical_features.csv'
    active=resolve_canonical_source(legacy)
    candidates=[
        (DATA/'CORE-001_domestic_population_audit.csv','POPULATION_AUDIT'),
        (active,'CANONICAL_ACTIVE'),
        (DATA/'CORE-004_field_strength_v2.csv','RESEARCH_INPUT'),
        (DATA/'CORE-010_calibrated_probabilities.csv','RESEARCH_OUTPUT'),
    ]
    if active != legacy:candidates.append((legacy,'LEGACY_CANONICAL_SNAPSHOT'))
    seen=set()
    for p,role in candidates:
        key=(str(p),role)
        if key in seen:continue
        seen.add(key);source_rows.extend(scan_file(p,role))
    source_rows.extend(pg_inventory())
    pd.DataFrame(source_rows).to_csv(SOURCES,index=False,encoding='utf-8-sig')
    usage=split_usage();gap=[]
    for domain in ('JRA','NAR'):
        file_dom=[r for r in source_rows if r.get('domain')==domain and r.get('source_type') in {'CSV','PARQUET'}]
        holding=max([int(r.get('races') or 0) for r in file_dom if r.get('role') in ('POPULATION_AUDIT','CANONICAL_ACTIVE')] or [0])
        research=max([int(r.get('races') or 0) for r in file_dom if r.get('role')=='RESEARCH_INPUT'] or [0])
        split_total=sum(int(r.get('races') or 0) for r in usage if r['domain']==domain)
        gap.append({'domain':domain,'holding_races_best_known':holding,'research_input_races':research,'split_assigned_races':split_total,'research_utilization_rate':(research/holding if holding else None),'unutilized_races':max(0,holding-research)})
    pd.DataFrame(gap).to_csv(GAP,index=False,encoding='utf-8-sig')
    nar=next(x for x in gap if x['domain']=='NAR');jra=next(x for x in gap if x['domain']=='JRA')
    pg_nar=sum(int(r.get('rows') or 0) for r in source_rows if r.get('source_type')=='POSTGRES' and r.get('domain')=='NAR')
    caps=capabilities();manifest=current_manifest() or {}
    summary={'status':'PASS','updated':now(),'sources':len(source_rows),'data_engine':caps,'canonical_store':{'active':bool(manifest),'version_id':manifest.get('version_id'),'path':str(active),'format':active.suffix.lower()},'postgres_nar_candidate_rows':pg_nar,'domains':{'JRA':jra,'NAR':nar},'split_usage':usage,'alerts':[]}
    for x in (jra,nar):
        rate=x.get('research_utilization_rate')
        if rate is not None and rate<0.90:summary['alerts'].append(f"{x['domain']}_research_utilization_below_90pct:{rate:.3f}")
    if nar.get('unutilized_races',0)>0:summary['alerts'].append(f"NAR_unutilized_races:{nar['unutilized_races']}")
    if any(r.get('role')=='UNAVAILABLE' for r in source_rows if r.get('source_type')=='POSTGRES'):summary['alerts'].append('PostgreSQL_inventory_unavailable')
    writej(SUMMARY,summary);state('PASS','Inventory refreshed',{'nar':nar,'jra':jra,'alerts':summary['alerts'],'data_engine':caps,'canonical_store':summary['canonical_store']});log(f"INVENTORY PASS engine={'DUCKDB' if caps.get('duckdb') else 'PANDAS'} canonical={manifest.get('version_id','LEGACY')} NAR holding={nar['holding_races_best_known']} research={nar['research_input_races']} gap={nar['unutilized_races']}")

def main():
    log('DATA INVENTORY DIRECTOR START')
    while True:
        try:run_once()
        except Exception:
            err=traceback.format_exc();log(err);state('BLOCKED',err[-1800:])
        time.sleep(INTERVAL)
if __name__=='__main__':main()
