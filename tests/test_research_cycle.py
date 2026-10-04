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

def brief():
    return {'brief_id':'B1','idea_key':'model-search','kind':'MODEL_SEARCH','split_id':'S1','status':'READY_FOR_EXECUTION','execution_worker':'experiment_director','title':'model'}

def test_cycle_rejects_unbound_results():
    c=load('research_cycle_director');rows=[{'split_id':'S1','status':'PROMOTE','selection_logloss':'0.2','test_logloss':'0.01','oos_logloss_report_only':'0.01'}]
    assert c._brief_results(brief(),rows)==[]
    d=c._decision(brief(),[]);assert d['status']=='WAITING_BINDING';assert d['reason']=='NO_EXPLICIT_BRIEF_BOUND_RESULT'

def test_cycle_bound_promote_routes_to_blind_and_ignores_test_oos():
    c=load('research_cycle_director');rows=[{'brief_id':'B1','split_id':'S1','status':'PROMOTE','experiment_key':'E1','selection_logloss':'0.42','test_logloss':'9.9','oos_logloss_report_only':'9.9'}]
    res=c._brief_results(brief(),rows);assert len(res)==1
    d=c._decision(brief(),res);assert d['status']=='PROMOTE_CANDIDATE';assert d['action']=='PREPARE_FORWARD_BLIND';assert d['selection_logloss']==0.42;assert d['test_oos_used_for_decision'] is False;assert d['same_epoch_test_oos_feedback_prohibited'] is True

def test_cycle_bound_keep_generates_next_hypothesis():
    c=load('research_cycle_director');rows=[{'brief_id':'B1','split_id':'S1','status':'KEEP','experiment_key':'E2','selection_logloss':'0.44','test_logloss':'0.01','oos_logloss_report_only':'0.01'}]
    d=c._decision(brief(),c._brief_results(brief(),rows));assert d['status']=='KEEP';assert d['action']=='GENERATE_NEXT_HYPOTHESIS';assert d['next_epoch_feedback']==['VALIDATION','SELECTION']

def test_cycle_material_routes_actions():
    m=load('research_cycle_material');base={'materials':[]}
    cycle={'decisions':[{'brief_id':'B1','idea_key':'x','split_id':'S1','status':'PROMOTE_CANDIDATE','action':'PREPARE_FORWARD_BLIND','reason':'SELECTION_PROMOTION','execution_worker':'experiment_director'},{'brief_id':'B2','idea_key':'y','split_id':'S1','status':'KEEP','action':'GENERATE_NEXT_HYPOTHESIS','reason':'NO_PROMOTION_YET','execution_worker':'experiment_director'}]}
    out=m.inject(base,cycle);k={x['kind'] for x in out['materials']};assert 'RESEARCH_CYCLE_BLIND' in k;assert 'RESEARCH_CYCLE_NEXT_HYPOTHESIS' in k

def test_execution_binding_only_uses_active_brief_missions(tmp_path):
    b=load('research_execution_binding');b.OUT=tmp_path/'bindings.json'
    q={'briefs':[{'brief_id':'B1','split_id':'S1','idea_key':'model-search','kind':'MODEL_SEARCH','execution_worker':'experiment_director'}]}
    p={'active_missions':[{'key':'brief:B1','evidence':{'brief_id':'B1'}}]};out=b.build(p,q);x=out['bindings']['experiment_director'];assert x['brief_id']=='B1';assert x['split_id']=='S1';assert x['test_oos_feedback_prohibited'] is True

def test_model_search_seed_creates_experiment_brief(tmp_path):
    s=load('research_model_search_seed');s.REPORTS=tmp_path;s.BRIEFS=tmp_path/'research_briefs';s.QUEUE=tmp_path/'queue.json'
    out=s.augment({'status':'PASS','split_id':'S1','briefs':[]});assert out['count']==1;b=out['briefs'][0];assert b['kind']=='MODEL_SEARCH';assert b['execution_worker']=='experiment_director';assert b['temporal_policy']['test_oos_feedback_prohibited'] is True
