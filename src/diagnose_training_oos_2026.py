"""Diagnose frozen 2026 pick swaps and calibration; preserve locked experiment."""
import ast, csv, gzip, inspect, json, math, random
from collections import defaultdict
from datetime import datetime
from pathlib import Path
import training_three_targets as t
import evaluate_training_oos_2026 as oos
from sample_extract import query

OUT=t.ROOT/'artifacts/oos-2026-training-diagnostics-v1'
LOCKED=oos.OUT

def bin_stats(observations,count):
    bins=[{'count':0,'sum_probability':0.,'positives':0} for _ in range(count)]
    for p,y in observations:
        entry=bins[min(count-1,int(p*count))];entry['count']+=1;entry['sum_probability']+=p;entry['positives']+=y
    total=len(observations);ece=0.;result=[]
    for i,b in enumerate(bins):
        n=b['count'];pred=b['sum_probability']/n if n else None;actual=b['positives']/n if n else None
        if n:ece+=n/total*abs(pred-actual)
        result.append({'lower':i/count,'upper':(i+1)/count,'count':n,'predicted_mean':pred,'observed_rate':actual,'positives':b['positives']})
    return {'equal_width_bins':count,'rows':total,'ece':ece,'bins':result,'mean_probability':sum(p for p,y in observations)/total,'observed_rate':sum(y for p,y in observations)/total}

def accuracy_interval(entries):
    blocks=defaultdict(lambda:[0,0])
    for day,diff in entries:
        block=blocks[t.ordinal(day)//28];block[0]+=diff;block[1]+=1
    values=list(blocks.values());rng=random.Random(20261006);samples=[]
    for _ in range(20000):
        chosen=[values[rng.randrange(len(values))] for _ in values]
        samples.append(sum(v[0] for v in chosen)/sum(v[1] for v in chosen))
    samples.sort()
    return {'blocks':len(values),'draws':20000,'delta_rate':sum(v[0] for v in values)/sum(v[1] for v in values),'block_bootstrap_95_percent':[samples[500],samples[19500]]}

def loss(rows,probs,k):
    result=[0.,0.]
    for row,p in zip(rows,probs):
        y=int(0<row[1]<=k);clipped=max(1e-15,min(1-1e-15,p))
        result[0]-=y*math.log(clipped)+(1-y)*math.log1p(-clipped);result[1]+=(p-y)**2
    return result

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    # Hash all prior artifacts; the final assertion proves the diagnosis did not overwrite them.
    manifest=t.load(LOCKED/'manifest.json')
    for name,expected in manifest['files'].items():
        if t.sha(t.ROOT/name)!=expected:raise ValueError('Locked OOS artifact changed')
    before={p.relative_to(t.ROOT).as_posix():t.sha(p) for p in LOCKED.glob('*') if p.is_file()}
    expected=t.load(LOCKED/'result.json');protocol=t.load(LOCKED/'protocol.json')
    impl=t.load(LOCKED/'implementation.json')
    if t.sha(t.ROOT/'src/evaluate_training_oos_2026.py')!=impl['runner_sha256']:raise ValueError('OOS implementation changed')
    for name,sha in impl['helpers'].items():
        if t.sha(t.ROOT/'src'/name)!=sha:raise ValueError('OOS helper changed')
    t.save(OUT/'protocol.json',{'kind':'post-evaluation diagnosis, not new OOS','parent_protocol_sha256':t.sha(LOCKED/'protocol.json'),'parent_result_sha256':t.sha(LOCKED/'result.json'),'runner_sha256':t.sha(Path(__file__)),'targets':[1,2,3],'calibration_bins':[10,20],'pick_interval':'28-calendar-day blocks, 20000 resamples','candidate_unchanged':True,'production_approved':False})
    captured={}
    def record(year,rid,rows,base,model,factors,bins):
        if rid in captured:raise ValueError('Duplicate captured race')
        captured[rid]={'rows':rows,'baseline':base,'candidate':model,'multipliers':factors,'eligible_indices':sorted(bins)}
    # Instrument an in-memory function; no edit to the locked source, and no result write.
    source=inspect.getsource(oos.evaluate)
    anchor='                if year<2026:t.add(historical,adjusted)'
    insertion='                if year==2026: AUDIT(year,rid,rows,win,t.marginals([r[2]*m for r,m in zip(rows,multipliers)]),multipliers,bins)\n'+anchor
    if source.count(anchor)!=1:raise ValueError('Diagnostic hook mismatch')
    source=source.replace(anchor,insertion)
    source=source.split('    tests=paired_tests(days,protocol)',1)[0]+'    return {"baseline":base,"candidate":model,"days":days}\n'
    ast.parse(source);namespace=dict(oos.__dict__);namespace['AUDIT']=record
    exec(compile(source,'frozen-oos-diagnostic','exec'),namespace)
    replay=namespace['evaluate'](protocol,oos.capture(protocol))
    for model in ('baseline','candidate'):
        for k in ('1','2','3'):
            for key in ('rows','races','logloss','brier','top_pick_observed_rate'):
                if abs(replay[model][k][key]-expected[model][k][key])>1e-12:raise ValueError('Frozen metric not reproduced')
    names_path=OUT/'names.json'
    if names_path.exists():names_envelope=t.load(names_path);names=names_envelope['rows']
    else:
        sql="""SELECT coalesce(json_agg(t),'[]'::json) FROM (
        SELECT trim(race_code) AS race_id,trim(ketto_toroku_bango) AS horse_id,
        trim(umaban) AS horse_number,trim(bamei) AS horse_name
        FROM public.umagoto_race_joho WHERE kaisai_nen='2026' AND kaisai_gappi<='1005'
        AND keibajo_code IN ('01','02','03','04','05','06','07','08','09','10')
        ORDER BY race_code,ketto_toroku_bango) t"""
        names=query(sql);t.save(names_path,{'sql':sql,'rows':names,'captured_at':datetime.now().astimezone().isoformat(),'use':'display only; current DB names not historical pre-race features'})
    identities={(r['race_id'],r['horse_id']):r for r in names}
    if len(identities)!=len(names):raise ValueError('Name join would duplicate rows')
    observations={k:{m:[] for m in ('baseline','candidate')} for k in (1,2,3)}
    pick_observations={k:{m:[] for m in ('baseline','candidate')} for k in (1,2,3)}
    stats={k:{'races':0,'swaps':0,'gains':0,'losses':0,'both_hit':0,'both_miss':0,'baseline_hits':0,'candidate_hits':0} for k in (1,2,3)}
    pick_days={k:[] for k in (1,2,3)}
    contributions={k:{bucket:{'races':0,'rows':0,'logloss_delta_sum':0.,'brier_delta_sum':0.} for bucket in ('same_pick','swapped_pick')} for k in (1,2,3)}
    swaps=[];probability_rows=[]
    for rid,entry in sorted(captured.items()):
        rows=entry['rows'];base=entry['baseline'];model=entry['candidate']
        ib=sorted(range(len(rows)),key=lambda i:(-base[0][i],rows[i][0]))[0]
        ic=sorted(range(len(rows)),key=lambda i:(-model[0][i],rows[i][0]))[0]
        switched=ib!=ic
        for k in (1,2,3):
            if sum(0<row[1]<=k for row in rows)!=min(k,len(rows)):continue
            s=stats[k];s['races']+=1;s['swaps']+=switched
            hitb=int(0<rows[ib][1]<=k);hitc=int(0<rows[ic][1]<=k)
            s['baseline_hits']+=hitb;s['candidate_hits']+=hitc
            s['gains']+=hitc>hitb;s['losses']+=hitc<hitb;s['both_hit']+=hitb==hitc==1;s['both_miss']+=hitb==hitc==0
            pick_days[k].append((rid[:8],hitc-hitb))
            for method,probabilities,index in (('baseline',base,ib),('candidate',model,ic)):
                observations[k][method].extend((p,int(0<r[1]<=k)) for r,p in zip(rows,probabilities[k-1]))
                pick_observations[k][method].append((probabilities[k-1][index],int(0<rows[index][1]<=k)))
            b_loss=loss(rows,base[k-1],k);c_loss=loss(rows,model[k-1],k)
            group=contributions[k]['swapped_pick' if switched else 'same_pick'];group['races']+=1;group['rows']+=len(rows);group['logloss_delta_sum']+=c_loss[0]-b_loss[0];group['brier_delta_sum']+=c_loss[1]-b_loss[1]
        for i,row in enumerate(rows):
            identity=identities.get((rid,row[0]))
            if identity is None:raise ValueError('Missing name connection')
            probability_rows.append({'race_id':rid,'horse_id':row[0],'finish':row[1],'baseline': [p[i] for p in base],'candidate':[p[i] for p in model],'workout_multiplier':entry['multipliers'][i],'eligible_workout':i in entry['eligible_indices']})
        if switched:
            b=identities[(rid,rows[ib][0])];c=identities[(rid,rows[ic][0])]
            swaps.append({'race_id':rid,'day':rid[:8],'venue':rid[8:10],'race_number':int(rid[-2:]),'baseline_horse_id':rows[ib][0],'baseline_number':b['horse_number'],'baseline_name':b['horse_name'],'baseline_finish':rows[ib][1],'candidate_horse_id':rows[ic][0],'candidate_number':c['horse_number'],'candidate_name':c['horse_name'],'candidate_finish':rows[ic][1],'baseline_win_probability':base[0][ib],'candidate_win_probability':model[0][ic],'baseline_horse_multiplier':entry['multipliers'][ib],'candidate_horse_multiplier':entry['multipliers'][ic]})
    calibration={};intervals={}
    for k in (1,2,3):
        s=stats[k];s['net_hits']=s['gains']-s['losses'];assert s['net_hits']==s['candidate_hits']-s['baseline_hits']
        assert s['races']==expected['baseline'][str(k)]['races']
        for method in ('baseline','candidate'):
            assert abs(s[method+'_hits']/s['races']-expected[method][str(k)]['top_pick_observed_rate'])<1e-12
        total=expected['baseline'][str(k)]['rows']
        for metric in ('logloss','brier'):
            assert abs(sum(g[metric+'_delta_sum'] for g in contributions[k].values())/total-expected['delta'][str(k)][metric])<1e-12
        calibration[str(k)]={method:{'all_runners_10':bin_stats(observations[k][method],10),'all_runners_20':bin_stats(observations[k][method],20),'top_pick_10':bin_stats(pick_observations[k][method],10)} for method in ('baseline','candidate')}
        intervals[str(k)]=accuracy_interval(pick_days[k])
    with (OUT/'top-pick-swaps.csv').open('w',encoding='utf-8-sig',newline='') as handle:
        writer=csv.DictWriter(handle,fieldnames=list(swaps[0]) if swaps else ['race_id']);writer.writeheader();writer.writerows(swaps)
    with gzip.open(OUT/'runner-probabilities.jsonl.gz','wt',encoding='utf-8') as handle:
        for row in probability_rows:handle.write(json.dumps(row,separators=(',',':'))+'\n')
    t.save(OUT/'diagnosis.json',{'targets':stats,'unique_swap_races':len(swaps),'contributions':contributions,'calibration':calibration,'pick_rate_intervals':intervals,'parent_metric_reproduced':True,'all_name_connections_matched':True,'experiment_decision':'KEEP','production_decision':'REJECT','limitations':['This is a diagnosis of an already examined 2026 period; not a new untouched OOS test.','Pick changes are an exact accounting explanation, not proof of causal workout effects.','ECE depends on bins and finite sample size; no recalibration was fitted.','All-runner mean probabilities match target prevalence by construction and do not prove calibration.','Place probabilities use the fixed rank model; official full-roster coverage and historical data availability remain unverified.']})
    after={p.relative_to(t.ROOT).as_posix():t.sha(p) for p in LOCKED.glob('*') if p.is_file()}
    if before!=after:raise ValueError('Diagnosis modified a locked artifact')
    t.save(OUT/'verification.json',{'parent_artifact_hashes_unchanged':True,'parent_metric_reproduced':True,'pick_hit_totals_reconciled':True,'additive_error_contributions_reconciled':True,'runner_count':len(probability_rows),'races':len(captured),'names_joined_one_to_one':True,'runner_sha256':t.sha(Path(__file__))})
    print(json.dumps({'unique_swaps':len(swaps),'pick_stats':stats,'intervals':intervals,'ece10':{k:{m:calibration[str(k)][m]['all_runners_10']['ece'] for m in ('baseline','candidate')} for k in (1,2,3)},'contributions':contributions},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
