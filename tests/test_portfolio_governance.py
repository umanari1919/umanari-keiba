from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
LAB=ROOT/'tools'/'research_dashboard'
if str(LAB) not in sys.path:sys.path.insert(0,str(LAB))

def load(name):
    spec=importlib.util.spec_from_file_location(name,LAB/f'{name}.py');assert spec and spec.loader
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);return mod

def test_foundation_blocker_outranks_research_idea():
    p=load('mission_portfolio');blocker={'department':'FOUNDATION','kind':'BLOCKER','impact':5,'urgency':5,'confidence':5,'cost':2,'risk':1};idea={'department':'RESEARCH','kind':'FEATURE_IDEA','impact':5,'urgency':3,'confidence':3,'cost':2,'risk':1};assert p.score(blocker)>p.score(idea)

def test_unused_data_gets_strong_priority():
    p=load('mission_portfolio');data={'department':'DATA','kind':'UNUSED_DATA','impact':5,'urgency':5,'confidence':4,'cost':3,'risk':2};routine={'department':'AUDIT','kind':'SAMPLE_GROWTH','impact':3,'urgency':2,'confidence':5,'cost':1,'risk':1};assert p.score(data)>p.score(routine)

def test_source_staging_is_prioritized_and_on_demand():
    p=load('mission_portfolio');staging={'key':'staging','department':'DATA','kind':'SOURCE_STAGING','impact':5,'urgency':5,'confidence':5,'cost':3,'risk':2,'worker':'chunked_source_staging_director'};routine={'department':'AUDIT','kind':'SAMPLE_GROWTH','impact':4,'urgency':3,'confidence':5,'cost':1,'risk':1};assert p.score(staging)>p.score(routine);out=p.run_once({'materials':[staging]},{'mode':'TURBO'},{'status':'PASS'});assert 'chunked_source_staging_director' in out['desired_workers'];assert 'chunked_source_staging_director' not in p.ALWAYS_ON

def test_canonical_bridge_is_prioritized_and_on_demand():
    p=load('mission_portfolio');bridge={'key':'bridge','department':'DATA','kind':'CANONICAL_BRIDGE','impact':5,'urgency':5,'confidence':5,'cost':2,'risk':1,'worker':'staging_canonical_bridge'};routine={'department':'AUDIT','kind':'SAMPLE_GROWTH','impact':4,'urgency':3,'confidence':5,'cost':1,'risk':1};assert p.score(bridge)>p.score(routine);out=p.run_once({'materials':[bridge]},{'mode':'TURBO'},{'status':'PASS'});assert 'staging_canonical_bridge' in out['desired_workers'];assert 'staging_canonical_bridge' not in p.ALWAYS_ON

def test_staging_requires_explicit_approved_export_contract():
    s=load('chunked_source_staging_director');base={'source_id':'T','enabled':True,'export_enabled':True,'rights_status':'APPROVED_INTERNAL','source':{'engine':'POSTGRES','schema':'public','table':'runners'},'column_map':{'a':'race_id'}};assert s.eligible(base)==(True,'READY');assert s.eligible({**base,'export_enabled':False})[0] is False;assert s.eligible({**base,'rights_status':'UNVERIFIED'})[0] is False

def test_staging_query_is_explicit_and_resumable():
    s=load('chunked_source_staging_director');c={'source':{'engine':'POSTGRES','schema':'public','table':'runners'},'column_map':{'r':'race_id','rh':'race_horse_id','h':'horse_id','d':'race_date','sc':'race_scope_cd','w':'label_win','t2':'label_top2','t3':'label_top3'}};q,params=s.build_query(c,'POSTGRES','R0009');assert 'SELECT *' not in q.upper();assert 'ORDER BY "rh"' in q;assert 'WHERE "rh" > %s' in q;assert params==['R0009']

def test_staging_partition_descriptor():
    s=load('chunked_source_staging_director');assert s.partition_descriptor({'race_date':'2026-10-04','race_scope_cd':1})==('2026','JRA');assert s.partition_descriptor({'race_date':'20240701','race_scope_cd':'2'})==('2024','NAR');assert s.partition_descriptor({'race_date':None,'race_scope_cd':99})==('UNKNOWN','UNKNOWN')

def test_bridge_classifies_new_duplicate_and_conflict(tmp_path):
    b=load('staging_canonical_bridge')
    active=tmp_path/'active.parquet';stage_root=tmp_path/'staging'/'TEST';part_dir=stage_root/'year=2026'/'domain=NAR';part_dir.mkdir(parents=True)
    cols=['race_id','race_horse_id','horse_id','race_date','race_scope_cd','label_win','label_top2','label_top3']
    pd.DataFrame([
        ['R1','RH1','H1','2026-01-01',2,1,1,1],
        ['R1','RH2','H2','2026-01-01',2,0,1,1],
    ],columns=cols).to_parquet(active,index=False)
    part=part_dir/'part-000001.parquet'
    pd.DataFrame([
        ['R1','RH1','H1','2026-01-01',2,1,1,1],
        ['R1','RH2','H2','2026-01-01',2,1,1,1],
        ['R2','RH3','H3','2026-01-02',2,1,1,1],
    ],columns=cols).to_parquet(part,index=False)
    contract_dir=tmp_path/'contracts';contract_dir.mkdir();out=tmp_path/'out';out.mkdir();quar=tmp_path/'quar';quar.mkdir()
    contract={'source_id':'TEST','enabled':True,'rights_status':'APPROVED_INTERNAL','column_map':{c:c for c in cols},'defaults':{}}
    (contract_dir/'test.json').write_text(json.dumps(contract),encoding='utf-8')
    rel=str(part.relative_to(stage_root)).replace('\\','/')
    (stage_root/'manifest.json').write_text(json.dumps({'source_id':'TEST','status':'READY','updated':'x','parts':[{'file':rel,'sha256':b.sha(part)}]}),encoding='utf-8')
    b.CONTRACTS=contract_dir;b.OUT=out;b.QUAR=quar;b.active_source=lambda:active
    result=b.process_source(stage_root)
    assert result['new_rows']==1
    assert result['exact_duplicates']==1
    assert result['conflicts']==1
    assert Path(result['candidate']).exists()
    assert Path(result['conflict_artifact']).exists()

def test_bridge_projection_refuses_missing_base_columns():
    b=load('staging_canonical_bridge')
    try:b.canonical_projection_sql('stage',['race_id'],['race_id','horse_id'],{'defaults':{}})
    except ValueError as exc:assert 'BASE_COLUMNS_UNSATISFIED' in str(exc)
    else:raise AssertionError('bridge must reject incomplete canonical schema')

def test_material_cards_are_evidence_based():
    m=load('research_material_engine');card=m._card('x','title','RESEARCH','TEST',{'source':'unit-test'},3,3,3,2,1,'experiment_director');assert card['evidence']['source']=='unit-test';assert 'result' not in card
