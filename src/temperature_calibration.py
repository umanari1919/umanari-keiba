"""Common race-strength temperature selected using 2023 only.
2024 validates the fixed parameter; 2025 and examined 2026 are retrospective references.
Positive common exponent preserves ranking and coherent top1/top2/top3 marginals.
"""
import argparse, gzip, json, math, random
from collections import defaultdict
from datetime import datetime
from pathlib import Path
import training_three_targets as t
from diagnose_training_oos_2026 import bin_stats

ROOT=t.ROOT
OUT=ROOT/'artifacts/temperature-calibration-v1'
DIAG=ROOT/'artifacts/oos-2026-training-diagnostics-v1'
GRID=[round(.5+.1*i,2) for i in range(26)]


def recalibrate(win,alpha):
    if not math.isfinite(alpha) or alpha<=0:raise ValueError('Exponent must be positive and finite')
    if any(not math.isfinite(p) or p<=0 or p>=1 for p in win):raise ValueError('Invalid source probabilities')
    logs=[alpha*math.log(p) for p in win];largest=max(logs)
    return t.marginals([math.exp(v-largest) for v in logs])


def prior_predictions():
    history=t.History({'kind':'window','days':1095})
    result={}
    for year in (2023,2024,2025):
        races=t.read_year(year);stores={'wood':t.collect(year,'wood')[0]};days=defaultdict(list);yearly={};total=t.empty()
        for rid,rows in races.items():days[rid[:8]].append((rid,rows))
        for day,entries in days.items():
            history.set_day(day);updates=[]
            for rid,rows in entries:
                base=t.marginals([r[2] for r in rows]);bins=t.feature_bins(rid,rows,stores,14,'wood','1f');factors=[1.]*len(rows)
                for i,key in bins.items():
                    n,correct=history[key];expected=history[('expected',)+key][1]
                    ratio=max(.25,min(4.,(correct+10)/(expected+10)));weight=.25*n/(n+100)
                    factors[i]=1+weight*(ratio-1);updates.append((key,int(rows[i][1]==1),base[0][i]))
                probs=t.marginals([r[2]*m for r,m in zip(rows,factors)])
                yearly[rid]=(rows,probs);t.add(total,t.metrics(rows,probs))
            for key,y,p in updates:history.add(key,y);history.add(('expected',)+key,p)
        expected=t.load(t.OUT/'results/wood-14-1f-25.json')['years'][str(year)];actual=t.finalize(total)
        for k in ('1','2','3'):
            for m in ('logloss','brier','top_pick_observed_rate'):
                if abs(actual[k][m]-expected[k][m])>1e-12:raise ValueError(f'Historical candidate mismatch {year}/{k}/{m}')
        result[year]=yearly
        print(f'Reconstructed calibration input {year}: {len(yearly)} races',flush=True)
    return result


def aggregate_calibration(races,alpha,capture=False):
    totals={'uncalibrated':t.empty(),'calibrated':t.empty()}
    observations={str(k):{m:[] for m in totals} for k in (1,2,3)}
    day_map={};captured=[];ordering=0
    for rid,(rows,original) in races.items():
        adjusted=recalibrate(original[0],alpha)
        before=sorted(range(len(rows)),key=lambda i:(-original[0][i],rows[i][0]))
        after=sorted(range(len(rows)),key=lambda i:(-adjusted[0][i],rows[i][0]))
        if before!=after:raise ValueError('Temperature changed ranking')
        ordering+=len(rows)
        original_scores=t.metrics(rows,original);new_scores=t.metrics(rows,adjusted)
        t.add(totals['uncalibrated'],original_scores);t.add(totals['calibrated'],new_scores)
        day=day_map.setdefault(rid[:8],{'day':rid[:8],'rows':[0,0,0],'logloss':[0.,0.,0.],'brier':[0.,0.,0.]})
        for k,(a,b) in enumerate(zip(new_scores,original_scores)):
            if a is not None:
                day['rows'][k]+=a[0];day['logloss'][k]+=a[2]-b[2];day['brier'][k]+=a[3]-b[3]
                for method,values in (('uncalibrated',original),('calibrated',adjusted)):
                    observations[str(k+1)][method].extend((p,int(0<row[1]<=k+1)) for row,p in zip(rows,values[k]))
        if capture:
            for i,row in enumerate(rows):captured.append({'race_id':rid,'horse_id':row[0],'finish':row[1],'uncalibrated':[values[i] for values in original],'calibrated':[values[i] for values in adjusted]})
    metrics={name:t.finalize(value) for name,value in totals.items()}
    calibration={k:{name:{str(count):bin_stats(values,count) for count in (10,20)} for name,values in methods.items()} for k,methods in observations.items()}
    for k in ('1','2','3'):
        assert metrics['uncalibrated'][k]['top_pick_observed_rate']==metrics['calibrated'][k]['top_pick_observed_rate']
    return {'metrics':metrics,'calibration':calibration,'paired_days':list(day_map.values()),'ranking_preserved_runner_count':ordering},captured


def fit(races):
    results=[]
    for alpha in GRID:
        total=t.empty()
        for rows,probs in races.values():t.add(total,t.metrics(rows,recalibrate(probs[0],alpha)))
        metrics=t.finalize(total);objective=sum(metrics[str(k)]['logloss'] for k in (1,2,3))/3
        results.append({'alpha':alpha,'temperature':1/alpha,'objective':objective,'metrics':metrics})
        print(f'2023-only exponent {alpha:.2f}: loss {objective:.8f}',flush=True)
    chosen=min(results,key=lambda r:(r['objective'],abs(r['alpha']-1),r['alpha']))
    model={'version':1,'base_model':'wood-14-1f-25','alpha':chosen['alpha'],'temperature':chosen['temperature'],'fitted_period':'2023 only','objective':'equal average of three binary Logloss means','selection':'fixed grid .5 to 3.0 step .1; objective then distance from identity then alpha','fit_races':len(races),'production_approved':False,'created_at':datetime.now().astimezone().isoformat()}
    path=OUT/'model.json'
    if path.exists():
        previous=t.load(path)
        comparable=dict(model);comparable['created_at']=previous['created_at']
        if comparable!=previous:raise ValueError('Frozen calibration parameter failed reproduction')
        model=previous
    t.save(path,model);t.save(OUT/'fit-grid.json',results)
    return model


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--verify-inputs',action='store_true');args=parser.parse_args()
    if args.verify_inputs:
        manifest=OUT/'manifest.json'
        if manifest.exists():
            for name,expected in t.load(manifest)['files'].items():
                if t.sha(ROOT/name)!=expected:raise ValueError('Locked calibration input/output changed: '+name)
        print('Calibration manifest verified');return
    OUT.mkdir(parents=True,exist_ok=True)
    original_files=[ROOT/'artifacts/oos-2026-training-v1/result.json',DIAG/'diagnosis.json',DIAG/'runner-probabilities.jsonl.gz',t.OUT/'results/wood-14-1f-25.json']
    parent_hashes={p.relative_to(ROOT).as_posix():t.sha(p) for p in original_files}
    input_files=list(original_files)+[ROOT/'src'/name for name in ('training_three_targets.py','diagnose_training_oos_2026.py')]+[t.OUT/f'{y}-scores.jsonl.gz' for y in (2023,2024,2025)]+[t.CACHE/f'wood-{y}.json.gz' for y in (2023,2024,2025)]
    protocol={'version':1,'grid':GRID,'fit_period':[2023,2023],'validation_period':[2024,2024],'reference_periods':[2025,2026],'base_candidate':'wood-14-1f-25','validation_gate':'all three Logloss/Brier means improve and ECE10 and ECE20 do not increase','fit_2026_outcomes':False,'future_period':['20261007','20270430'],'first_future_descriptive_review':'20261231','future_gate':'at least eight nonempty 28-calendar-day blocks; 3-target Logloss/Brier means improve, 6 Holm p<.05, and all three ECE10/ECE20 do not worsen','production_decision':'REJECT pending fresh future validation and historical availability/population audit','input_hashes':{p.relative_to(ROOT).as_posix():t.sha(p) for p in input_files},'runner_sha256':t.sha(Path(__file__)),'limitations':['Base candidate was selected using earlier examined 2016-2025 results; 2024/2025 are retrospective checks, not pristine holdouts.','2026 was examined before this calibration idea; comparison is post-hoc exploration, not a new untouched OOS.','A common positive exponent preserves ranking; it cannot repair top-pick hit rates.','Future protocol is saved only; no scheduling or source-service change is performed.']}
    path=OUT/'protocol.json'
    if path.exists() and t.load(path)!=protocol:raise ValueError('Calibration protocol changed')
    t.save(path,protocol)
    prior=prior_predictions();model=fit(prior[2023]);alpha=model['alpha'];periods={}
    for year in (2023,2024,2025):
        periods[str(year)],_=aggregate_calibration(prior[year],alpha)
        print(f'Calibration {year} evaluated',flush=True)
    # The exponent and validation were already saved before opening the 2026 runner results.
    validation=periods['2024'];passed=all(validation['metrics']['calibrated'][k][m]<validation['metrics']['uncalibrated'][k][m] for k in ('1','2','3') for m in ('logloss','brier')) and all(validation['calibration'][k]['calibrated'][b]['ece']<=validation['calibration'][k]['uncalibrated'][b]['ece'] for k in ('1','2','3') for b in ('10','20'))
    t.save(OUT/'pre-2026-selection.json',{'model_sha256':t.sha(OUT/'model.json'),'alpha':alpha,'validation_2024_passed':passed,'decision_before_2026':'KEEP' if passed else 'REJECT','fit_2026_labels':False})
    current=defaultdict(list)
    with gzip.open(DIAG/'runner-probabilities.jsonl.gz','rt',encoding='utf-8') as handle:
        for line in handle:
            row=json.loads(line);current[row['race_id']].append(row)
    races={rid:([[r['horse_id'],r['finish'],r['candidate'][0]] for r in entries],[[r['candidate'][k] for r in entries] for k in range(3)]) for rid,entries in sorted(current.items())}
    periods['2026'],captured=aggregate_calibration(races,alpha,True)
    expected=t.load(ROOT/'artifacts/oos-2026-training-v1/result.json')['candidate']
    for k in ('1','2','3'):
        for m in ('logloss','brier','top_pick_observed_rate'):
            if abs(periods['2026']['metrics']['uncalibrated'][k][m]-expected[k][m])>1e-12:raise ValueError('2026 reference input differs from locked evaluation')
    with gzip.open(OUT/'reference-2026-probabilities.jsonl.gz','wt',encoding='utf-8') as handle:
        for row in captured:handle.write(json.dumps(row,separators=(',',':'))+'\n')
    future={'candidate':model,'baseline':'wood-14-1f-25 without calibration','evaluation_start':'20261007','evaluation_end':'20270430','early_descriptive_review':'20261231','minimum_nonempty_28day_blocks':8,'parameters_fixed':True,'calibration_fit_years':[2023],'gate':protocol['future_gate'],'state':'awaiting_future_data','production_approved':False,'locked_at':model['created_at']}
    t.save(OUT/'future-validation-protocol.json',future)
    result={'model':model,'periods':periods,'validation_2024_passed':passed,'experiment_decision':'KEEP' if passed else 'REJECT','production_decision':'REJECT','production_approved':False,'2026_interpretation':'already-examined post-hoc reference only','2026_label_used_for_selection':False,'all_rankings_preserved':True,'future_validation_state':'awaiting_future_data'}
    t.save(OUT/'result.json',result)
    if parent_hashes!={p.relative_to(ROOT).as_posix():t.sha(p) for p in original_files}:raise ValueError('Original research outputs changed')
    t.save(OUT/'verification.json',{'parent_hashes_unchanged':True,'historical_model_metrics_reproduced':True,'reference_2026_metrics_reproduced':True,'all_rankings_and_hit_rates_preserved':True,'selection_before_reading_2026_labels':True,'future_period_not_evaluated':True})
    t.save(OUT/'manifest.json',{'files':{p.relative_to(ROOT).as_posix():t.sha(p) for p in input_files+[OUT/'protocol.json',OUT/'model.json',OUT/'pre-2026-selection.json',OUT/'future-validation-protocol.json',OUT/'result.json']}})
    print(json.dumps({'alpha':alpha,'temperature':1/alpha,'validation_2024_passed':passed,'experiment_decision':result['experiment_decision'],'2026_metrics':periods['2026']['metrics'],'ece10_2026':{k:{m:periods['2026']['calibration'][k][m]['10']['ece'] for m in ('uncalibrated','calibrated')} for k in ('1','2','3')}},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
