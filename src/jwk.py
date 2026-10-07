"""Three-track portfolio observation and bounded reusable jobs; no legacy queue writes."""
import argparse
import hashlib
import json
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEGACY = Path.home()/'Downloads/THE-JOCKEY-RESEARCH'
OUT = ROOT/'artifacts/jwk-portfolio-v1'
THEMES = {'field_strength': ('field',), 'pedigree': ('pedigree','blood','血統'),
          'workouts': ('training','workout','調教'), 'volatility': ('volatility','chaos','荒れ'),
          'ability_error': ('ability','error','能力'), 'debut': ('debut','新馬'),
          'obstacle': ('obstacle','障害'), 'aptitude': ('aptitude','適性')}
JOBS = {'weekend-replay': ('weekend_replay.py','publish_weekend_ui.py'), 'weekend-personal': ('weekend_personal_forecast.py','publish_weekend_ui.py'), 'weekend-display': ('publish_weekend_ui.py',), 'weekend-run': ('weekend_run.py',), 'weekend-source': ('weekend_source_status.py',), 'portfolio-reconcile': (), 'production-readiness': ('prospective_readiness.py',),
        'research-inventory': ('research_inventory.py',),
        'research-pedigree-features': ('pedigree_features.py',),
        'research-pedigree-race-join': ('pedigree_race_join.py',),
        'research-pedigree-forward-capture': ('pedigree_forward_capture.py',),
        'research-volatility-concentration': ('volatility_concentration.py',),
        'research-ability-disagreement': ('ability_disagreement.py',),
        'research-obstacle-cohort': ('obstacle_cohort.py',),
        'research-obstacle-entrants': ('obstacle_entrants.py',),
        'research-obstacle-history': ('obstacle_history.py',),
        'research-obstacle-reference': ('obstacle_reference.py',),
        'research-obstacle-champion-contract': ('obstacle_champion_contract.py',),
        'research-obstacle-champion-comparison': ('obstacle_champion_comparison.py',),
        'research-volatility-target': ('volatility_target.py',),
        'research-volatility-temporal': ('volatility_temporal.py',),
        'research-ability-error-proxy': ('ability_error_proxy.py',),
        'research-forward-package': ('research_forward_package.py',),
        'research-reconcile': ('research_reconcile.py','research_inventory.py'),
        'research-aptitude-input-audit': ('aptitude_input_audit.py',),
        'research-aptitude-comparison-audit': ('aptitude_comparison_audit.py',),
        'research-paired-model-reference': ('paired_model_reference.py',),
        'research-paired-reference-diagnostics': ('paired_reference_diagnostics.py',),
        'research-aptitude-ablation': ('aptitude_ablation.py',),
        'research-aptitude-ablation-validate': ('aptitude_ablation_validate.py',),
        'research-aptitude-ablation-diagnostics': ('aptitude_ablation_diagnostics.py',),
        'research-aptitude-probability-order': ('aptitude_probability_order.py',),
        'research-aptitude-race-population': ('aptitude_race_population.py',),
        'research-aptitude-label-contract': ('aptitude_label_contract.py',),
        'research-aptitude-history-rebuild': ('aptitude_history_rebuild.py',),
        'research-aptitude-feature-cohort': ('aptitude_feature_cohort.py',),
        'research-aptitude-cohort-validate': ('aptitude_cohort_validate.py',),
        'research-aptitude-starter-comparison': ('aptitude_starter_comparison.py',),
        'research-aptitude-starter-validate': ('aptitude_starter_validate.py',),
        'research-aptitude-upstream-contract': ('aptitude_upstream_contract.py',),
        'research-aptitude-disposition': ('aptitude_disposition.py',),
        'research-debut-audit': ('debut_evidence_audit.py',),
        'research-debut-source-audit': ('debut_source_audit.py',),
        'research-debut-eligibility': ('debut_eligibility_audit.py',),
        'research-debut-training-timing': ('debut_training_timing.py',),
        'research-debut-training-sources': ('debut_training_sources.py',),
        'research-debut-clock-audit': ('debut_clock_audit.py',),
        'research-debut-missing-scope': ('debut_missing_scope.py',),
        'research-debut-missing-policy': ('debut_missing_policy.py',),
        'production-capture': ('prospective_capture.py','prospective_readiness.py','prospective_forecast.py'),
        'research-validation': ('check_selective_history.py','check_fast_history_restore.py','check_shared_workouts.py','check_prospective_results.py','prospective_validation.py')}


def read(path):
    if not path.exists(): return {'observation': 'missing', 'path': str(path)}
    try: return json.loads(path.read_text(encoding='utf-8-sig'))
    except (ValueError, OSError) as exc: return {'observation':'unreadable','path':str(path),'reason':str(exc)}


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')


def observe(root=ROOT, legacy=LEGACY):
    runtime=read(legacy/'runtime/state.json'); plan=read(legacy/'CORE/reports/MISSION_PORTFOLIO_plan.json')
    pending=[]
    for item in runtime.get('queue',[]):
        if item.get('status') not in ('PASS','COMPLETE','COMPLETED'):
            pending.append({'source':'runtime','mission':item})
    for item in plan.get('active_missions',[])+plan.get('backlog',[]):
        pending.append({'source':'legacy_portfolio_unreconciled','mission':item})
    actual=runtime.get('active')
    stale=bool(runtime.get('updated') and plan.get('updated') and plan['updated']<runtime['updated'])
    previous_missing=[name for item in plan.get('active_missions',[]) for blocker in item.get('evidence',{}).get('blockers',[]) for name in blocker.get('missing',[])]
    missing_now=[name for name in previous_missing if not (legacy/name).is_file()]
    themes={key:{'state':'queued_for_evidence_inventory','executing':False,'evidence':[]} for key in THEMES}
    for item in runtime.get('queue',[]):
        text=json.dumps(item,ensure_ascii=False).lower()
        for theme, words in THEMES.items():
            if any(word in text for word in words):
                themes[theme]['evidence'].append({'mission_id':item.get('id'),'status':item.get('status'),'result':item.get('result')})
                themes[theme]['state']='existing_runtime_evidence'
                if actual and actual.get('mission_id')==item.get('id'): themes[theme].update(state='running',executing=True)
    themes['workouts']['evidence'].append({'source':str(root/'artifacts/temperature-calibration-v1/future-validation-protocol.json'),'status':'KEEP; prospective validation pending'})
    for path in (legacy/'CORE/reports').glob('*.json'):
        for theme, words in THEMES.items():
            if any(word in path.name.lower() for word in words):
                evidence=read(path)
                themes[theme]['evidence'].append({'source':str(path),'reported_status':evidence.get('status'),'reported_updated':evidence.get('updated'),'current_validity':'not_revalidated'})
    forecasts=read(root/'artifacts/prospective-forecast-v1/status.json')
    gate=read(root/'artifacts/prospective-validation-v1/status.json')
    registry=read(root/'artifacts/jwk-research-inventory-v1/registry.json')
    if 'missions' in registry:
        for record in registry['missions'].values():
            if record.get('theme') in themes:
                themes[record['theme']]['inventory_mission']=record
    next_job='portfolio-reconcile' if stale else 'production-readiness' if forecasts.get('predicted_races',0)==0 else 'research-validation'
    return {'observed_at':datetime.now().astimezone().isoformat(),
            'tracks':{'Platform':{'runtime_status':runtime.get('status','unknown'),'runtime_updated':runtime.get('updated'),'legacy_plan_updated':plan.get('updated'),'legacy_plan_stale':stale,'existing_active':actual,
                                 'legacy_dependency_recheck':{'previously_missing':len(previous_missing),'still_missing':missing_now,'interpretation':'File presence only; imports/behavior and full legacy pipeline are not certified'}},
                      'Production':{'forecast_state':forecasts.get('state','unknown'),'forecast_races':forecasts.get('predicted_races'),'production_decision':'REJECT','gate_state':gate.get('state','unknown'),'automatic_promotion':False},
                      'Research':{'themes':themes,'pending_missions_preserved':pending}},
            'next_job':next_job,'reason':'Legacy portfolio is older than runtime observation; refresh evidence before changing missions' if stale else 'Prioritize production input readiness while retaining every research track',
            'weekend_mission':dict(active=datetime.now().strftime('%Y%m%d') <= '20261012',deadline='20261010',status=read(root/'artifacts/jwk-weekend-v1/latest.json').get('state'),replay_state=read(root/'artifacts/jwk-weekend-replay-v1/latest.json').get('state')),
            'bounded_research_jobs':{job:{k:read(root/f'artifacts/{artifact}/latest.json').get(k) for k in ('state','completed_units','total_units')} for job,artifact in [('research-aptitude-ablation','jwk-aptitude-ablation-v1'),('research-aptitude-starter-comparison','jwk-aptitude-starter-comparison-v1')]},
            'external_queue_modified':False,'approval_scope':['deletion','DROP','irreversible_change','production_data_migration','rights_decision'],
            'limitations':['Existing runtime PASS is operational evidence, not scientific production approval.', 'Research themes without inventoried evidence are queued, not executing.', 'No external queue states are marked complete by this observer.']}


def select(snapshot, completed, last_job=None):
    if datetime.now().strftime('%Y%m%d') <= '20261012' and 'weekend-run' not in completed:
        return 'weekend-run'
    for job in ('research-aptitude-ablation','research-aptitude-starter-comparison'):
        pending=snapshot.get('bounded_research_jobs',{}).get(job,{})
        if pending.get('state')=='in_progress' and last_job==job:return 'production-readiness'
        if pending.get('state')=='in_progress':return job
    if snapshot.get('weekend_mission',{}).get('active') and 'weekend-run' in completed:
        if 'replay_state' in snapshot['weekend_mission'] and 'weekend-replay' not in completed:
            return 'weekend-replay'
        return 'weekend-source' if last_job!='weekend-source' else 'weekend-run'
    order=['research-inventory','research-debut-audit','research-debut-source-audit','research-debut-eligibility','research-debut-training-timing','research-debut-training-sources','research-debut-clock-audit','research-debut-missing-scope','research-debut-missing-policy','research-reconcile','research-aptitude-input-audit','research-aptitude-comparison-audit','research-paired-model-reference','research-paired-reference-diagnostics','research-aptitude-ablation','research-aptitude-ablation-validate','research-aptitude-ablation-diagnostics','research-aptitude-probability-order','research-aptitude-race-population','research-aptitude-label-contract','research-aptitude-history-rebuild','research-aptitude-feature-cohort','research-aptitude-cohort-validate','research-aptitude-starter-comparison','research-aptitude-starter-validate','research-aptitude-upstream-contract','research-aptitude-disposition','research-pedigree-features','research-pedigree-race-join','research-pedigree-forward-capture','research-volatility-concentration','research-ability-disagreement','research-obstacle-cohort','research-obstacle-entrants','research-obstacle-history','research-obstacle-reference','research-obstacle-champion-contract','research-obstacle-champion-comparison','research-volatility-target','research-volatility-temporal','research-ability-error-proxy','research-forward-package',snapshot['next_job'],'production-readiness','research-validation','production-capture','portfolio-reconcile']
    remaining=next((job for job in dict.fromkeys(order) if job not in completed),None)
    pending=snapshot.get('bounded_research_jobs',{}).get('research-aptitude-ablation',{})
    if remaining=='research-aptitude-ablation-validate' and pending.get('state')=='in_progress':
        return 'production-readiness' if last_job=='research-aptitude-ablation' else 'research-aptitude-ablation'
    if remaining:return remaining
    pending=snapshot.get('bounded_research_jobs',{}).get('research-aptitude-ablation',{})
    if pending.get('state')=='in_progress' and last_job in ('production-readiness','production-capture'):
        return 'research-aptitude-ablation'
    if pending.get('state')=='in_progress' and last_job=='research-aptitude-ablation':
        return 'production-readiness'
    # Reusable checks recur across tracks rather than remaining on Platform forever.
    cycle=('portfolio-reconcile','production-readiness','research-validation','production-capture')
    return cycle[(cycle.index(last_job)+1)%len(cycle)] if last_job in cycle else 'portfolio-reconcile'


def main():
    parser=argparse.ArgumentParser();parser.add_argument('command',choices=('status','doctor','next','run'));parser.add_argument('job',nargs='?',default='next')
    args=parser.parse_args()
    snapshot=observe();save(OUT/'latest.json',snapshot)
    previous=read(OUT/'completed.json');completed=previous.get('jobs',[])
    chosen=select(snapshot,completed,previous.get('last_job'))
    if args.command in ('status','doctor'):
        print(json.dumps(snapshot,ensure_ascii=False,indent=2));return
    if args.command=='next':
        print(json.dumps({'job':chosen,'reason':('Reconcile all research plans and explicit result bindings without changing legacy queues' if chosen=='research-reconcile' else 'Run the selected research validity audit; preserve all tracks' if chosen.startswith('research-debut-') or chosen.startswith('research-aptitude-') or chosen=='research-paired-model-reference' else 'Refresh production inputs and readiness' if chosen.startswith('production-') else snapshot['reason']),'tracks_preserved':list(snapshot['tracks'])},ensure_ascii=False));return
    job=chosen if args.job=='next' else args.job
    if job not in JOBS: raise ValueError('Job not allowlisted')
    if job!='portfolio-reconcile' and snapshot['tracks']['Platform']['existing_active']:
        raise RuntimeError('Existing runtime worker active; defer this job without interrupting it')
    OUT.mkdir(parents=True,exist_ok=True)
    lock=OUT/'job.lock'
    with lock.open('x',encoding='utf-8') as handle:handle.write(job)
    folder=OUT/'jobs'/(datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8]);folder.mkdir(parents=True)
    results=[]
    try:
        save(folder/'before.json',snapshot)
        for script in JOBS[job]:
            path=ROOT/'src'/script
            command=[r'C:\Python314\python.exe','-X','utf8','-B',str(path),'--worker'] if job in ('research-aptitude-ablation','research-aptitude-starter-comparison') else [sys.executable,'-X','utf8','-B',str(path)]
            result=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,encoding='utf-8',timeout=900 if job in ('weekend-run','research-aptitude-ablation','research-aptitude-starter-comparison') else 180)
            results.append({'script':script,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'exit_code':result.returncode,'stdout':result.stdout,'stderr':result.stderr})
            if result.returncode:break
        after=observe();save(folder/'after.json',after);save(OUT/'latest.json',after)
        success=all(item['exit_code']==0 for item in results)
        save(folder/'result.json',{'job':job,'success':success,'steps':results,'tracks_reevaluated_before_and_after':True,'existing_missions_preserved':True,'external_queue_modified':False})
        if success:save(OUT/'completed.json',{'jobs':list(dict.fromkeys(completed+[job])),'last_job':job,'scope':'Local reusable-job completion only; external missions remain unchanged'})
        print(json.dumps({'job':job,'success':success,'report':str(folder),'next_job':select(after,completed+[job] if success else completed,job if success else previous.get('last_job'))},ensure_ascii=False))
        if not success:raise SystemExit(1)
    finally:lock.unlink()


if __name__=='__main__':main()
