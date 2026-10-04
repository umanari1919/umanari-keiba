from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
LAB=ROOT/'tools'/'research_dashboard'
if str(LAB) not in sys.path:sys.path.insert(0,str(LAB))

def load(name):
    spec=importlib.util.spec_from_file_location(name,LAB/f'{name}.py');assert spec and spec.loader
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);return mod

def temporal_plan():
    return {'status':'PASS','splits':{
        'TRAIN':{'start_date':'2020-01-01','end_date':'2023-12-31'},
        'VALIDATION':{'start_date':'2024-01-01','end_date':'2024-06-30'},
        'SELECTION':{'start_date':'2024-07-01','end_date':'2024-12-31'},
        'TEST':{'start_date':'2025-01-01','end_date':'2025-12-31'},
        'OOS':{'start_date':'2026-01-01','end_date':'2026-09-30'},
    }}

def test_brief_freezes_test_oos_as_report_only():
    b=load('research_brief_director')
    idea={'key':'field','title':'Field Strength研究','kind':'FIELD_STRENGTH','status':'READY','required_columns':['field_strength_v2'],'evidence':{},'worker':'feature_research_director','notes':'相手関係を研究'}
    out=b.build_brief(idea,temporal_plan())
    assert out['status']=='READY_FOR_EXECUTION'
    assert out['temporal_policy']['decision_splits']==['TRAIN','VALIDATION','SELECTION']
    assert out['temporal_policy']['report_only_splits']==['TEST','OOS']
    assert out['temporal_policy']['test_oos_feedback_prohibited'] is True
    assert 'selection_logloss' in out['evaluation_metrics']

def test_specialist_brief_has_contract_gate():
    b=load('research_brief_director')
    idea={'key':'obstacle','title':'障害戦研究','kind':'OBSTACLE_SPECIALIST','status':'READY','required_columns':['obstacle_flag'],'evidence':{},'worker':'domain_research_director'}
    out=b.build_brief(idea,temporal_plan())
    assert out['execution_worker']=='domain_research_director'
    assert 'Contract' in out['specialist_rule']

def test_small_ticket_brief_uses_bankroll_metrics():
    b=load('research_brief_director')
    idea={'key':'min123','title':'小点数比較','kind':'SMALL_TICKET','status':'READY','required_columns':[],'evidence':{},'worker':'decision_strategy_director'}
    out=b.build_brief(idea,temporal_plan())
    for metric in ['ROI','max_drawdown','ticket_efficiency','capital_efficiency']:
        assert metric in out['evaluation_metrics']

def test_research_brief_is_always_on_and_blocker_still_wins():
    p=load('mission_portfolio')
    assert 'research_brief_director' in p.ALWAYS_ON
    blocker={'department':'FOUNDATION','kind':'BLOCKER','impact':5,'urgency':5,'confidence':5,'cost':2,'risk':1}
    brief={'department':'RESEARCH','kind':'RESEARCH_BRIEF','impact':5,'urgency':4,'confidence':5,'cost':3,'risk':1}
    assert p.score(blocker)>p.score(brief)
