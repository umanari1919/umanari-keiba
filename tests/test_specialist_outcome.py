from __future__ import annotations

import importlib.util,json,sys
from pathlib import Path
import pandas as pd

ROOT=Path(__file__).resolve().parents[1];LAB=ROOT/'tools'/'research_dashboard'
if str(LAB) not in sys.path:sys.path.insert(0,str(LAB))
def load(name):
 spec=importlib.util.spec_from_file_location(name,LAB/f'{name}.py');assert spec and spec.loader
 m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def test_specialist_segment_requires_explicit_column_and_values():
 s=load('specialist_research_director');df=pd.DataFrame({'race_scope_cd':[1,1,2],'race_type':['DEBUT','MAIDEN','DEBUT']})
 assert s.segment_mask(df,{'column':None,'values':['DEBUT']}) is None
 m=s.segment_mask(df,{'column':'race_type','values':['DEBUT'],'race_scope_cd':1})
 assert m.tolist()==[True,False,False]

def test_jra_morning_contract_supports_compound_and_filters():
 s=load('specialist_research_director');df=pd.DataFrame({'race_scope_cd':[1,1,1,2],'session_phase':['MORNING','MORNING','AFTERNOON','MORNING'],'race_type':['MAIDEN','OPEN','MAIDEN','MAIDEN']})
 spec={'race_scope_cd':1,'filters':[{'column':'session_phase','values':['MORNING']},{'column':'race_type','values':['MAIDEN','DEBUT','OBSTACLE']}]}
 assert s.segment_mask(df,spec).tolist()==[True,False,False,False]

def test_specialist_adapter_promotes_only_same_population_improvement(tmp_path):
 a=load('research_result_adapter');a.SPECIALIST=tmp_path/'specialist.csv';a.SPECIALIST_MIN_IMPROVEMENT=.0005
 a.SPECIALIST.write_text('brief_id,split_id,target,sample_rows,validation_improvement,selection_improvement\nB1,S1,label_win,1000,0.002,0.003\nB1,S1,label_top2,1000,0.001,0.002\nB1,S1,label_top3,1000,-0.001,0.004\n',encoding='utf-8')
 out=a._specialist({'brief_id':'B1','split_id':'S1'},{'kind':'DEBUT_SPECIALIST'})
 assert out['result_status']=='PROMOTE';assert out['decision_metrics']['passing_targets']==2
 a.SPECIALIST.write_text('brief_id,split_id,target,sample_rows,validation_improvement,selection_improvement\nB1,S1,label_win,1000,-0.002,0.003\nB1,S1,label_top2,1000,-0.001,0.002\n',encoding='utf-8')
 assert a._specialist({'brief_id':'B1','split_id':'S1'},{'kind':'DEBUT_SPECIALIST'})['result_status']=='REJECT'

def test_strategy_promotion_requires_realized_sample_gate(tmp_path):
 a=load('research_result_adapter');a.STRATEGY=tmp_path/'strategy.csv';a.STRATEGY_MIN_RACES=30
 a.STRATEGY.write_text('brief_id,split_id,strategy,ROI,profit,turnover,races,max_drawdown,losing_streak,ticket_efficiency,capital_efficiency\nB1,S1,MIN-1,1.20,400,2000,20,500,6,20,0.20\n',encoding='utf-8')
 out=a._strategy({'brief_id':'B1','split_id':'S1'},{'kind':'SMALL_TICKET'});assert out['result_status']=='KEEP';assert out['reason']=='REALIZED_SAMPLE_BELOW_PROMOTION_GATE'
 a.STRATEGY.write_text('brief_id,split_id,strategy,ROI,profit,turnover,races,max_drawdown,losing_streak,ticket_efficiency,capital_efficiency\nB1,S1,MIN-1,1.20,800,4000,40,500,6,20,0.20\n',encoding='utf-8')
 assert a._strategy({'brief_id':'B1','split_id':'S1'},{'kind':'SMALL_TICKET'})['result_status']=='PROMOTE'

def test_strategy_outcome_aggregates_all_result_files(tmp_path):
 e=load('strategy_outcome_evaluator');e.REPORTS=tmp_path/'reports';e.CHECK=tmp_path/'check';e.BIND=e.REPORTS/'RESEARCH_EXECUTION_bindings.json';e.STRAT=tmp_path/'strategy'/'outbox';e.RESULTS=tmp_path/'strategy'/'inbox'/'results';e.OUT=e.REPORTS/'STRATEGY_EVALUATION_summary.csv';e.STATE=e.CHECK/'strategy_outcome_evaluator_state.json'
 for p in (e.REPORTS,e.CHECK,e.RESULTS):p.mkdir(parents=True,exist_ok=True)
 e.BIND.write_text(json.dumps({'bindings':{'decision_strategy_director':{'brief_id':'B1','split_id':'S1'}}}),encoding='utf-8')
 for stem,race,payout in [('day1','R1',200),('day2','R2',0)]:
  d=e.STRAT/stem;d.mkdir(parents=True,exist_ok=True);pd.DataFrame([{'race_id':race,'strategy':'MIN-1','ticket_type':'WIDE','selection':'1-2'}]).to_csv(d/'strategy_profiles.csv',index=False)
  pd.DataFrame([{'race_id':race,'ticket_type':'WIDE','selection':'1-2','payout_per_100':payout}]).to_csv(e.RESULTS/f'{stem}.csv',index=False)
 e.run_once();out=pd.read_csv(e.OUT);r=out.iloc[0]
 assert int(r['races'])==2;assert int(r['tickets'])==2;assert abs(float(r['ROI'])-1.0)<1e-9;assert int(r['result_files'])==2

def test_lab_updater_does_not_start_idle_on_demand_worker(monkeypatch):
 u=load('lab_updater');assert 'specialist_research_director.py' in u.ON_DEMAND;called=[]
 monkeypatch.setattr(u,'current_pid',lambda _s:0);monkeypatch.setattr(u,'alive',lambda _p:False);monkeypatch.setattr(u,'start',lambda n:called.append(n) or 999)
 assert u.maintain_on_demand('specialist_research_director.py','x.json',False) is None;assert called==[]
