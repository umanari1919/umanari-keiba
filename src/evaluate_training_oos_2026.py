"""Locked 2026 evaluation of one previously selected workout candidate."""
import ast, gzip, hashlib, json, math, random, sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
import training_three_targets as t
import personnel_experiments as personnel
import parallel_experiments as previous
from sample_extract import query

ROOT=t.ROOT
OUT=ROOT/'artifacts/oos-2026-training-v1'
DATA=ROOT/'datasets/oos-2026-training-v1'

def snapshot(name,sql):
    path=DATA/name
    if path.exists():
        envelope=t.load(path)
        if envelope['sql']!=sql:raise ValueError('Locked query changed')
        rows=envelope['rows']
        if hashlib.sha256(previous.encoded(rows)).hexdigest()!=envelope['rows_sha256']:raise ValueError('Snapshot hash mismatch')
    else:
        rows=query(sql)
        t.save(path,{'sql':sql,'rows':rows,'rows_sha256':hashlib.sha256(previous.encoded(rows)).hexdigest(),'captured_at':datetime.now().astimezone().isoformat()})
    return rows

def capture(protocol):
    end=protocol['evaluation_end'];venues="('01','02','03','04','05','06','07','08','09','10')"
    rows=snapshot('runners-2026.json',f"""SELECT coalesce(json_agg(t),'[]'::json) FROM (
      SELECT trim(race_code) AS race_id,trim(ketto_toroku_bango) AS horse_id,
        trim(kakutei_chakujun) AS finish,trim(ijo_kubun_code) AS abnormal,
        trim(kishu_code) AS jockey_id,trim(chokyoshi_code) AS trainer_id
      FROM public.umagoto_race_joho WHERE kaisai_nen='2026' AND kaisai_gappi<='{end[4:]}'
      AND keibajo_code IN {venues} ORDER BY race_code,ketto_toroku_bango) t""")
    conditions=snapshot('conditions-2026.json',f"""SELECT coalesce(json_agg(t),'[]'::json) FROM (
      SELECT trim(race_code) AS race_id,trim(keibajo_code) AS venue,
      trim(kyori) AS distance,trim(track_code) AS track,trim(grade_code) AS grade,
      trim(kyoso_joken_code_saijakunen) AS race_class
      FROM public.race_shosai WHERE kaisai_nen='2026' AND kaisai_gappi<='{end[4:]}'
      AND keibajo_code IN {venues} ORDER BY race_code) t""")
    keys={(r['race_id'],r['horse_id']) for r in rows}
    if len(keys)!=len(rows):raise ValueError('Duplicate 2026 runner keys')
    if any(not r['jockey_id'] or not r['trainer_id'] for r in rows):raise ValueError('Missing 2026 personnel identities')
    source=(ROOT/'src/decade_evaluate.py').read_text(encoding='utf-8-sig').split('\ndef main(',1)[0]
    metadata=t.load(t.OUT/'baseline-verification.json')
    personnel.initialize(source,metadata['input_hashes'])
    for row in rows:personnel.RIDERS[(row['race_id'],row['horse_id'])]=(row['jockey_id'],row['trainer_id'])
    previous.CACHE['conditions/2026.json']=conditions
    for month in range(1,13):
        previous.CACHE[f'raw-cache/2026-{month:02}.json']=[{k:r[k] for k in ('race_id','horse_id','finish','abnormal')} for r in rows if r['race_id'].startswith(f'2026{month:02}')]
    config={'id':'jockey-25','mode':'jockey','cap':.25}
    ns=personnel.engine(config)
    code=personnel.augment(previous.transformed(personnel.FIXED),config)
    for old,new in (
      ('general = defaultdict(lambda:[0,0])','general = History(ACTIVE_CONFIG)'),
      ('local = defaultdict(lambda:[0,0])','local = History(ACTIVE_CONFIG)'),
      ('for day,day_rows in sorted(days.items()):','for day,day_rows in sorted(days.items()):\n            general.set_day(day)\n            local.set_day(day)'),
      ('                general[horse][0]+=1\n                general[horse][1]+=y\n                local[context_key][0]+=1\n                local[context_key][1]+=y','                general.add(horse,y)\n                local.add(context_key,y)'),
      ('for year in range(2011,2026):','for year in range(2011,2027):')):
        code=previous.replace_once(code,old,new)
    anchor='                        scores["uniform"].append(1.)'
    code=previous.replace_once(code,anchor,anchor+'\n                        CAPTURE(race_id,row,scores["candidate"][-1])')
    handles={year:gzip.open(t.OUT/f'{year}-scores.jsonl.gz','rt',encoding='utf-8') for year in range(2016,2026)}
    new_races=defaultdict(list);verified=0
    def append(rid,row,score):
        nonlocal verified
        record=[rid,row['horse_id'],int(row['finish']),score]
        if rid.startswith('2026'):
            new_races[rid].append(record[1:])
        else:
            old=json.loads(next(handles[int(rid[:4])]))
            if old!=record:raise ValueError('Adding future data changed historical score: '+rid)
            verified+=1
    ns['CAPTURE']=append
    exec(compile(code,'locked-2026-jockey','exec'),ns)
    ns['snapshot']=lambda p:previous.CACHE[p.relative_to(personnel.BASE).as_posix()]
    ns['interval']=lambda *args:None
    try:
        report,pairs=ns['compute'](personnel.BASE,lambda year,n,r:print(f'Jockey replay {year}: {r} races',flush=True))
        if any(handle.readline() for handle in handles.values()):raise ValueError('Historical capture was truncated')
    finally:
        for handle in handles.values():handle.close()
    old_aggregate=ns['aggregate']([p for p in pairs if not p['day'].startswith('2026')])
    for metric in ('logloss','brier'):
        if abs(old_aggregate['metrics']['candidate'][metric]-metadata['overall']['metrics']['candidate'][metric])>1e-12:raise ValueError('Historical aggregate changed')
    current=[p for p in pairs if p['day'].startswith('2026')]
    if set(new_races)!={p['race_id'] for p in current}:raise ValueError('2026 score/pair population mismatch')
    if not current:raise ValueError('No usable 2026 races')
    t.save(OUT/'capture-verification.json',{'all_prior_scores_exactly_matched':True,'matched_rows':verified,'prior_metrics_matched':True,'raw_2026_rows':len(rows),'raw_2026_races':len({r['race_id'] for r in rows}),'2026_races':len(current),'2026_rows':sum(p['rows'] for p in current),'excluded_races':report['years'][-1]['excluded_races'],'excluded_nonstarters':report['years'][-1]['excluded_nonstarters'],'source_connection_read_only':True})
    t.save(OUT/'jockey-2026-pairs.json',current)
    return dict(sorted(new_races.items()))

def paired_tests(days,protocol):
    tests=[];draws=protocol['inference']['draws']
    for target in range(3):
        for metric in ('logloss','brier'):
            blocks=defaultdict(lambda:[0.,0])
            for row in days:
                dest=blocks[t.ordinal(row['day'])//28]
                dest[0]+=row[metric][target];dest[1]+=row['rows'][target]
            values=[v[0] for v in blocks.values()];total_rows=sum(v[1] for v in blocks.values());observed=sum(values)
            rng=random.Random(protocol['inference']['seed']);exceed=0
            for _ in range(draws):exceed+=sum(v*(1 if rng.getrandbits(1) else -1) for v in values)<=observed
            p=(exceed+1)/(draws+1) if observed<0 else 1.
            rng=random.Random(protocol['inference']['seed']+target)
            samples=[];block_list=list(blocks.values())
            for _ in range(draws):
                chosen=[block_list[rng.randrange(len(block_list))] for _ in block_list]
                denominator=sum(v[1] for v in chosen)
                if denominator:samples.append(sum(v[0] for v in chosen)/denominator)
            samples.sort();lo=samples[int(.025*len(samples))];hi=samples[min(len(samples)-1,int(.975*len(samples)))]
            tests.append({'target':target+1,'metric':metric,'delta':observed/total_rows,'p_one_sided':p,'block_bootstrap_95_percent':[lo,hi],'blocks':len(blocks)})
    last=0.
    for i,item in enumerate(sorted(tests,key=lambda x:x['p_one_sided'])):
        last=max(last,min(1.,(len(tests)-i)*item['p_one_sided']));item['p_holm']=last
    return tests

def evaluate(protocol,races):
    # Reconstruct the chosen workout history from prior scores; no candidate reselection.
    old_cache=t.CACHE
    history=t.History({'kind':'window','days':1095})
    new_store,workout_audit=None,None
    baseline=t.empty();candidate=t.empty();days=[];eligible=changed=0;historical=t.empty()
    for year in range(2016,2027):
        yearly=t.read_year(year) if year<2026 else races
        if year<2026:
            stores={'wood':t.collect(year,'wood')[0]}
        else:
            t.CACHE=DATA/'workouts';new_store,workout_audit=t.collect(year,'wood');t.CACHE=old_cache
            stores={'wood':new_store}
        by_day=defaultdict(list)
        for rid,rows in yearly.items():by_day[rid[:8]].append((rid,rows))
        for day,entries in by_day.items():
            history.set_day(day);updates=[];day_delta={'day':day,'rows':[0,0,0],'logloss':[0.,0.,0.],'brier':[0.,0.,0.]}
            for rid,rows in entries:
                win=t.marginals([r[2] for r in rows]);base=t.metrics(rows,win)
                bins=t.feature_bins(rid,rows,stores,14,'wood','1f');multipliers=[1.]*len(rows)
                for i,key in bins.items():
                    n,correct=history[key];expected=history[('expected',)+key][1]
                    ratio=max(.25,min(4.,(correct+10)/(expected+10)))
                    weight=.25*n/(n+100);multipliers[i]=1+weight*(ratio-1)
                    updates.append((key,int(rows[i][1]==1),win[0][i]))
                adjusted=t.metrics(rows,t.marginals([r[2]*m for r,m in zip(rows,multipliers)])) if any(abs(m-1)>1e-15 for m in multipliers) else base
                if year<2026:t.add(historical,adjusted)
                else:
                    eligible+=len(bins);changed+=any(abs(m-1)>1e-15 for m in multipliers)
                    t.add(baseline,base);t.add(candidate,adjusted)
                    for k,(a,b) in enumerate(zip(adjusted,base)):
                        if a is not None:
                            day_delta['rows'][k]+=a[0];day_delta['logloss'][k]+=a[2]-b[2];day_delta['brier'][k]+=a[3]-b[3]
            for key,y,p in updates:history.add(key,y);history.add(('expected',)+key,p)
            if year==2026:days.append(day_delta)
        print(f'Locked workout replay {year}: {len(yearly)} races',flush=True)
    previous=t.load(t.OUT/'results/wood-14-1f-25.json')['overall']
    actual=t.finalize(historical)
    for k in ('1','2','3'):
        for metric in ('logloss','brier','top_pick_observed_rate'):
            if abs(actual[k][metric]-previous[k][metric])>1e-12:raise ValueError('Prior workout result failed replay')
    base=t.finalize(baseline);model=t.finalize(candidate)
    pairs=t.load(OUT/'jockey-2026-pairs.json')
    for metric,field in (('logloss','loss'),('brier','brier')):
        direct=sum(p[field]['candidate'] for p in pairs)/sum(p['rows'] for p in pairs)
        if abs(base['1'][metric]-direct)>1e-12:raise ValueError('2026 baseline scoring mismatch')
    tests=paired_tests(days,protocol)
    all_improved=all(model[k][m]<base[k][m] for k in ('1','2','3') for m in ('logloss','brier'))
    rates_safe=all(model[k]['top_pick_observed_rate']>=base[k]['top_pick_observed_rate'] for k in ('1','2','3'))
    promote=all_improved and rates_safe and all(test['p_holm']<.05 for test in tests)
    decision='PROMOTE' if promote else 'KEEP' if all_improved else 'REJECT'
    result={'protocol':protocol,'baseline':base,'candidate':model,'delta':{k:{m:model[k][m]-base[k][m] for m in ('logloss','brier','top_pick_observed_rate')} for k in ('1','2','3')},'paired_tests':tests,'paired_days':days,'eligible_training_rows':eligible,'changed_races':changed,'workout_audit':workout_audit,'previous_candidate_reproduced':True,'experiment_decision':decision,'production_decision':'REJECT','production_approved':False,'last_scored_day':max(p['day'] for p in pairs),'limitations':['Evaluation was first used after conditions were fixed, but current historical source availability and revisions are unverified.','Partial 2026 year; official complete-roster coverage unverified.','Rolling histories automatically include preceding-day 2026 outcomes under the locked algorithm.','Place probabilities are rank-model marginals; calibration unverified.','28-day sign/block-bootstrap inference relies on symmetry and temporal assumptions.']}
    t.save(OUT/'result.json',result)
    print(json.dumps({'baseline':base,'candidate':model,'experiment_decision':decision,'production_decision':'REJECT','eligible_training_rows':eligible,'changed_races':changed,'paired_tests':tests},ensure_ascii=False,indent=2),flush=True)


def main():
    protocol=t.load(OUT/'protocol.json')
    if protocol['candidate']!={'id':'wood-14-1f-25','source':'wood','days':14,'feature':'1f','cap':.25}:raise ValueError('Unexpected fixed candidate')
    if t.sha(t.OUT/'summary.json')!=protocol['selection_input_sha256']:raise ValueError('Selection input changed since lock')
    metadata=t.load(t.OUT/'baseline-verification.json')
    for name,expected in metadata['score_hashes'].items():
        if t.sha(t.OUT/name)!=expected:raise ValueError('Historical scores changed')
    implementation={'runner_sha256':t.sha(Path(__file__)),'helpers':{name:t.sha(ROOT/'src'/name) for name in ('training_three_targets.py','personnel_experiments.py','parallel_experiments.py','decade_evaluate.py','condition_audit.py')},'protocol_sha256':t.sha(OUT/'protocol.json')}
    path=OUT/'implementation.json'
    if path.exists() and t.load(path)!=implementation:raise ValueError('Locked implementation changed')
    t.save(path,implementation)
    evaluate(protocol,capture(protocol))
if __name__=='__main__':main()
