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

def test_material_cards_are_evidence_based():
    m=load('research_material_engine')
    card=m._card('x','title','RESEARCH','TEST',{'source':'unit-test'},3,3,3,2,1,'experiment_director')
    assert card['evidence']['source']=='unit-test'
    assert 'result' not in card
