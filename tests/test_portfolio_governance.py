from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
LAB=ROOT/'tools'/'research_dashboard'
if str(LAB) not in sys.path:sys.path.insert(0,str(LAB))

def load(name):
    spec=importlib.util.spec_from_file_location(name,LAB/f'{name}.py');assert spec and spec.loader
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);return mod

def test_foundation_blocker_outranks_research_idea():
    p=load('mission_portfolio')
    blocker={'department':'FOUNDATION','kind':'BLOCKER','impact':5,'urgency':5,'confidence':5,'cost':2,'risk':1}
    idea={'department':'RESEARCH','kind':'FEATURE_IDEA','impact':5,'urgency':3,'confidence':3,'cost':2,'risk':1}
    assert p.score(blocker)>p.score(idea)

def test_unused_data_gets_strong_priority():
    p=load('mission_portfolio')
    data={'department':'DATA','kind':'UNUSED_DATA','impact':5,'urgency':5,'confidence':4,'cost':3,'risk':2}
    routine={'department':'AUDIT','kind':'SAMPLE_GROWTH','impact':3,'urgency':2,'confidence':5,'cost':1,'risk':1}
    assert p.score(data)>p.score(routine)

def test_source_staging_is_prioritized_and_on_demand():
    p=load('mission_portfolio')
    staging={'department':'DATA','kind':'SOURCE_STAGING','impact':5,'urgency':5,'confidence':5,'cost':3,'risk':2,'worker':'chunked_source_staging_director'}
    routine={'department':'AUDIT','kind':'SAMPLE_GROWTH','impact':4,'urgency':3,'confidence':5,'cost':1,'risk':1}
    assert p.score(staging)>p.score(routine)
    out=p.run_once({'materials':[staging]}, {'mode':'TURBO'}, {'status':'PASS'})
    assert 'chunked_source_staging_director' in out['desired_workers']
    assert 'chunked_source_staging_director' not in p.ALWAYS_ON

def test_staging_requires_explicit_approved_export_contract():
    s=load('chunked_source_staging_director')
    base={'source_id':'T','enabled':True,'export_enabled':True,'rights_status':'APPROVED_INTERNAL','source':{'engine':'POSTGRES','schema':'public','table':'runners'},'column_map':{'a':'race_id'}}
    assert s.eligible(base)==(True,'READY')
    disabled={**base,'export_enabled':False};assert s.eligible(disabled)[0] is False
    unapproved={**base,'rights_status':'UNVERIFIED'};assert s.eligible(unapproved)[0] is False

def test_staging_query_is_explicit_and_resumable():
    s=load('chunked_source_staging_director')
    c={'source':{'engine':'POSTGRES','schema':'public','table':'runners'},'column_map':{'r':'race_id','rh':'race_horse_id','h':'horse_id','d':'race_date','sc':'race_scope_cd','w':'label_win','t2':'label_top2','t3':'label_top3'}}
    q,params=s.build_query(c,'POSTGRES','R0009')
    assert 'SELECT *' not in q.upper()
    assert 'ORDER BY "rh"' in q
    assert 'WHERE "rh" > %s' in q
    assert params==['R0009']

def test_material_cards_are_evidence_based():
    m=load('research_material_engine')
    card=m._card('x','title','RESEARCH','TEST',{'source':'unit-test'},3,3,3,2,1,'experiment_director')
    assert card['evidence']['source']=='unit-test'
    assert 'result' not in card
