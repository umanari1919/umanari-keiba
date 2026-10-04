from __future__ import annotations

import importlib.util,json,sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];LAB=ROOT/'tools'/'research_dashboard'
if str(LAB) not in sys.path:sys.path.insert(0,str(LAB))
def load(name):
 spec=importlib.util.spec_from_file_location(name,LAB/f'{name}.py');assert spec and spec.loader
 m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def test_feature_contract_uses_selection_only(tmp_path):
 a=load('research_result_adapter');a.FEATURE=tmp_path/'feature.csv'
 a.FEATURE.write_text('split_id,feature,decision,selection_mean_abs_auc,auc_label_win_test\nS1,f1,PROMOTE_CANDIDATE,0.53,0.99\n',encoding='utf-8')
 out=a._feature({'split_id':'S1'},{'kind':'FIELD_STRENGTH'})
 assert out['result_status']=='PROMOTE';assert out['decision_metrics']['best_selection_mean_abs_auc']==0.53
 assert out['report_only_metrics']['test_oos_present'] is True

def test_domain_gap_is_measured_but_not_auto_promoted(tmp_path):
 a=load('research_result_adapter');a.DOMAIN=tmp_path/'domain.csv'
 a.DOMAIN.write_text('split_id,domain,target,SELECTION_logloss,TEST_logloss,OOS_logloss\nS1,JRA,label_win,0.20,0.01,0.01\nS1,NAR,label_win,0.30,0.99,0.99\n',encoding='utf-8')
 out=a._domain({'split_id':'S1'},{'kind':'DOMAIN_GAP'})
 assert out['result_status']=='KEEP';assert abs(out['decision_metrics']['absolute_domain_gap']-0.1)<1e-9

def test_specialist_without_bound_artifact_waits_for_result(tmp_path):
 a=load('research_result_adapter');a.SPECIALIST=tmp_path/'missing.csv'
 out=a._specialist({'brief_id':'B1','split_id':'S1'},{'kind':'OBSTACLE_SPECIALIST'})
 assert out['result_status']=='WAITING_RESULT';assert 'SPECIALIST' in out['reason']

def test_strategy_never_invents_realized_roi(tmp_path):
 a=load('research_result_adapter');a.STRATEGY=tmp_path/'missing.csv'
 out=a._strategy({'brief_id':'B1','split_id':'S1'},{'kind':'SMALL_TICKET'})
 assert out['result_status']=='WAITING_OUTCOME';assert 'PAYOUT' in out['reason']

def test_cycle_maps_capability_gap_to_build_action():
 c=load('research_cycle_director');brief={'brief_id':'B1','idea_key':'i','kind':'DEBUT_SPECIALIST','split_id':'S1','execution_worker':'specialist_research_director'}
 out=c._decision(brief,[],{'result_status':'CAPABILITY_GAP','reason':'EXPLICIT_CAPABILITY_GAP','missing_capability':'SOME_FUTURE_SPECIALIST_COMPONENT'})
 assert out['status']=='CAPABILITY_GAP';assert out['action']=='BUILD_EXECUTOR_CAPABILITY';assert out['test_oos_used_for_decision'] is False

def test_capability_gap_becomes_foundation_mission():
 m=load('research_cycle_material');cycle={'decisions':[{'brief_id':'B1','status':'CAPABILITY_GAP','action':'BUILD_EXECUTOR_CAPABILITY','missing_capability':'FUTURE_COMPONENT','execution_worker':'specialist_research_director'}]}
 out=m.inject({'materials':[]},cycle);card=out['materials'][0]
 assert card['department']=='FOUNDATION';assert card['kind']=='RESEARCH_CAPABILITY_GAP';assert card['worker']=='specialist_research_director'
