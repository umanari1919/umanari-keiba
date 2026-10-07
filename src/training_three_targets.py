"""48 chronological training experiments against frozen jockey-25, three targets.
Only workouts and source creation dates strictly before race day are admitted.
Place probabilities are Plackett-Luce marginals, not independently trained models.
"""
import argparse, bisect, gzip, hashlib, itertools, json, math, sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from capture_jockey_scores import ROOT, OUT, save
from sample_extract import query
from personnel_experiments import History

CONFIGS=[{'id':f'{s}-{w}-{f}-{int(c*100)}','source':s,'days':w,'feature':f,'cap':c}
         for s,w,f,c in itertools.product(('hanro','wood','both'),(7,14),('presence','count','4f','1f'),(.10,.25))]
TABLES={'hanro':'hanro_chokyo','wood':'woodchip_chokyo'}
CACHE=ROOT/'datasets/training-pre-race-v1'

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def load(path):return json.loads(path.read_text(encoding='utf-8-sig'))
def ordinal(day):return datetime.strptime(day,'%Y%m%d').date().toordinal()
def number(value):
    value=(value or '').strip()
    return int(value) if value.isdigit() and int(value)>0 else None

def marginals(scores):
    if not scores or any(not math.isfinite(s) or s<=0 for s in scores):raise ValueError('Invalid strength')
    total=sum(scores);p=[s/total for s in scores];n=len(p)
    second=p.copy();third=p.copy()
    for j,pj in enumerate(p):
        den=1-pj
        if den<=0:continue
        pool=sum(pk/max(1e-15,den-pk) for k,pk in enumerate(p) if k!=j)
        for i,pi in enumerate(p):
            if i==j:continue
            a=pi*pj/den
            second[i]+=a
            third[i]+=a+a*(pool-pi/max(1e-15,den-pi))
    arrays=[p,second,third]
    for k,values in enumerate(arrays,1):
        if abs(sum(values)-min(k,n))>1e-8:raise ValueError('Place probability mass mismatch')
        if any(v < -1e-9 or v>1+1e-9 for v in values):raise ValueError('Place probability outside range')
    return [[max(0.,min(1.,v)) for v in values] for values in arrays]

def metrics(rows,probs):
    result=[]
    rank=sorted(range(len(rows)),key=lambda i:(-probs[0][i],rows[i][0]))[0]
    for target,values in enumerate(probs,1):
        labels=[int(0<r[1]<=target) for r in rows]
        # Ties across the target boundary do not have exactly k positive labels.
        if sum(labels)!=min(target,len(rows)):
            result.append(None);continue
        loss=brier=0.
        for p,y in zip(values,labels):
            clipped=max(1e-15,min(1-1e-15,p))
            loss-=y*math.log(clipped)+(1-y)*math.log1p(-clipped)
            brier+=(p-y)**2
        result.append([len(rows),1,loss,brier,labels[rank]])
    return result

def empty():return [[0,0,0.,0.,0] for _ in range(3)]
def add(total,values):
    for dest,entry in zip(total,values):
        if entry is not None:
            for i,v in enumerate(entry):dest[i]+=v

def finalize(total):
    return {str(k):{'rows':v[0],'races':v[1],'logloss':v[2]/v[0] if v[0] else None,'brier':v[3]/v[0] if v[0] else None,'top_pick_observed_rate':v[4]/v[1] if v[1] else None} for k,v in enumerate(total,1)}

def read_year(year):
    races=defaultdict(list)
    with gzip.open(OUT/f'{year}-scores.jsonl.gz','rt',encoding='utf-8') as handle:
        for line in handle:
            rid,horse,finish,score=json.loads(line);races[rid].append([horse,finish,score])
    return dict(sorted(races.items()))

def collect(year,source):
    path=CACHE/f'{source}-{year}.json.gz'
    end=f'{year}1231';start=f'{year-1}1218'
    sql=f"""SELECT coalesce(json_agg(t),'[]'::json) FROM (
      SELECT trim(ketto_toroku_bango) AS horse, trim(chokyo_nengappi) AS day,
      trim(data_sakusei_nengappi) AS created,trim(tracen_kubun) AS center,
      trim(chokyo_jikoku) AS time,trim(time_gokei_4furlong) AS f4,
      trim({'lap_time_1furlong' if source=='hanro' else 'laptime_1furlong'}) AS f1
      FROM public.{TABLES[source]}
      WHERE chokyo_nengappi BETWEEN '{start}' AND '{end}'
      AND data_sakusei_nengappi BETWEEN '19000101' AND '{end}'
      ORDER BY ketto_toroku_bango,chokyo_nengappi,chokyo_jikoku,tracen_kubun
    ) t"""
    if path.exists():
        with gzip.open(path,'rt',encoding='utf-8') as handle:envelope=json.load(handle)
        if envelope['sql']!=sql:raise ValueError('Cache query changed')
        records=envelope['rows']
        if hashlib.sha256(json.dumps(records,sort_keys=True).encode()).hexdigest()!=envelope['rows_sha256']:raise ValueError('Workout cache hash mismatch')
    else:
        records=query(sql)
        CACHE.mkdir(parents=True,exist_ok=True)
        envelope={'sql':sql,'captured_at':datetime.now().astimezone().isoformat(),'rows':records,'rows_sha256':hashlib.sha256(json.dumps(records,sort_keys=True).encode()).hexdigest()}
        with gzip.open(path.with_name(path.name+'.tmp'),'wt',encoding='utf-8') as handle:json.dump(envelope,handle,separators=(',',':'))
        path.with_name(path.name+'.tmp').replace(path)
    by_horse=defaultdict(list); seen={}; invalid=duplicate=conflict=0
    for row in records:
        try:
            d=ordinal(row['day']);created=ordinal(row['created'])
            if not row['horse'] or not row['center']:raise ValueError('Missing identity')
        except (ValueError,TypeError):invalid+=1;continue
        key=(row['horse'],row['day'],row['time'],row['center'])
        if key in seen:
            duplicate+=1
            if seen[key]!=row:conflict+=1
            continue
        seen[key]=row
        by_horse[row['horse']].append((d,created,row['center'],number(row['f4']),number(row['f1']),row['time']))
    if conflict:raise ValueError(f'Conflicting workouts: {source}/{year}: {conflict}')
    for values in by_horse.values():values.sort(key=lambda e:(e[0],e[5],e[1],e[2]))
    print(f'Workout cache {year}/{source}: {len(records)} records, invalid {invalid}, duplicate {duplicate}',flush=True)
    return by_horse,{'year':year,'source':source,'records':len(records),'invalid':invalid,'duplicates':duplicate,'sha256':sha(path)}

def feature_bins(rid,rows,stores,window,source,feature):
    day=ordinal(rid[:8]); candidates={}; groups=defaultdict(list)
    for i,row in enumerate(rows):
        entries=stores[source].get(row[0],[])
        stop=bisect.bisect_left(entries,(day,))
        eligible=[]
        for entry in reversed(entries[:stop]):
            if entry[0]<day-window:break
            if entry[1]<day:eligible.append(entry)
        if not eligible:continue
        if feature=='presence':candidates[i]=(source,'present')
        elif feature=='count':candidates[i]=(source,'count',min(3,len(eligible)))
        else:
            col=3 if feature=='4f' else 4
            measured=[e for e in eligible if e[col] is not None]
            if not measured:continue
            # Most recent center; rank raw clock codes only within source/center.
            center=measured[0][2]
            matching=[e for e in measured if e[2]==center]
            selected=min(matching,key=lambda e:e[col]) if feature=='4f' else matching[0]
            groups[center].append((selected[col],i))
    for center,items in groups.items():
        # Equal clocks receive equal bins; no assumed unit or cross-center clock comparison.
        values=sorted(v for v,i in items)
        for value,i in items:
            rank=bisect.bisect_left(values,value)
            bucket=min(3,4*rank//len(values))
            candidates[i]=(source,center,feature,bucket)
    return candidates

def prepare():
    verification=load(OUT/'baseline-verification.json')
    for name,expected in verification['score_hashes'].items():
        if sha(OUT/name)!=expected:raise ValueError('Captured baseline changed')
    all_data={}; totals=empty();years={}; coverage=[]
    for year in range(2016,2026):
        races=read_year(year); stores={}
        for source in TABLES:
            stores[source],audit=collect(year,source);coverage.append(audit)
        annual=empty();race_data={};connected=defaultdict(int)
        for rid,rows in races.items():
            probs=marginals([r[2] for r in rows]);base=metrics(rows,probs);add(annual,base)
            bins={}
            for source,window,feature in itertools.product(TABLES,(7,14),('presence','count','4f','1f')):
                bins[(source,window,feature)]=feature_bins(rid,rows,stores,window,source,feature)
                connected[f'{source}-{window}-{feature}']+=len(bins[(source,window,feature)])
            race_data[rid]=(rows,probs[0],base,bins)
        all_data[year]=race_data;years[str(year)]=finalize(annual);add(totals,annual)
        coverage.append({'year':year,'evaluation_rows':sum(len(x[0]) for x in race_data.values()),'eligible_feature_rows':dict(connected)})
        print(f'Prepared {year}: {len(races)} races',flush=True)
    baseline=finalize(totals)
    expected=verification['overall']['metrics']['candidate']
    for key in ('logloss','brier'):
        if abs(baseline['1'][key]-expected[key])>1e-12:raise ValueError('Win baseline metrics changed')
    save(OUT/'three-target-baseline.json',{'model':'jockey-25','method':'Plackett-Luce exact top-1/top-2/top-3 marginals from frozen win strengths','overall':baseline,'years':years,'target_boundary_ties':'excluded per target if positive labels differ from min(k, field_size)','production_approved':False})
    save(OUT/'workout-coverage.json',coverage)
    return all_data,baseline

def experiment(config,data,baseline):
    history=History({'kind':'window','days':1095}); overall=empty();years={};changed=eligible=0;days=[]
    for year,races in data.items():
        annual=empty();by_day=defaultdict(list)
        for rid,entry in races.items():by_day[rid[:8]].append((rid,entry))
        for day,entries in by_day.items():
            history.set_day(day);updates=[];delta=[0.,0.,0.];counts=[0,0,0]
            for rid,(rows,win_probs,base,bins) in entries:
                sources=TABLES if config['source']=='both' else (config['source'],)
                factors=[[] for _ in rows]
                for source in sources:
                    for i,key in bins[(source,config['days'],config['feature'])].items():
                        stats=history[key];n,correct=stats
                        expected=history[('expected',)+key][1]
                        ratio=max(.25,min(4.,(correct+10)/(expected+10)))
                        weight=config['cap']*n/(n+100)
                        factors[i].append(1+weight*(ratio-1))
                        updates.append((key,int(rows[i][1]==1),win_probs[i]))
                multipliers=[sum(fs)/len(fs) if fs else 1. for fs in factors]
                eligible+=sum(bool(fs) for fs in factors)
                if any(abs(m-1)>1e-15 for m in multipliers):
                    values=metrics(rows,marginals([row[2]*m for row,m in zip(rows,multipliers)]));changed+=1
                else:values=base
                add(annual,values)
                for i,(a,b) in enumerate(zip(values,base)):
                    if a is not None:
                        delta[i]+=a[2]-b[2];counts[i]+=a[0]
            # All outcomes and expected probabilities enter history only after the whole day.
            for key,y,p in updates:
                history.add(key,y);history.add(('expected',)+key,p)
            days.append({'day':day,'rows':counts,'delta_loss_sum':delta})
        add(overall,annual);years[str(year)]=finalize(annual)
        print(f"{config['id']} {year} complete",flush=True)
    metrics_out=finalize(overall)
    return {'config':config,'overall':metrics_out,'years':years,'eligible_rows':eligible,'changed_races':changed,'delta':{str(k):{m:metrics_out[str(k)][m]-baseline[str(k)][m] for m in ('logloss','brier','top_pick_observed_rate')} for k in (1,2,3)},'paired_days':days,'experiment_decision':'KEEP' if all(metrics_out[str(k)]['logloss']<baseline[str(k)]['logloss'] and metrics_out[str(k)]['brier']<baseline[str(k)]['brier'] for k in (1,2,3)) else 'REJECT','decision_scope':'descriptive screening only; selection-adjusted inference pending','production_decision':'REJECT','production_approved':False}

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--candidate');args=parser.parse_args()
    protocol={'version':1,'benchmark':'jockey-25','configs':CONFIGS,'evaluation_years':[2016,2025],'candidate_history_days':1095,'candidate_history_start':'20160101','probability_method':'exact Plackett-Luce top-1/top-2/top-3 marginals','cutoff':'training_day < race_day AND creation_day < race_day','missing_features':'neutral multiplier; no missing-as-zero clocks','feature_bins':'presence, count capped 3, fastest 4F or most recent 1F rank quartiles within race/source/most recent center','multipliers':'1 + cap*n/(n+100)*(clip((wins+10)/(expected_wins+10),.25,4)-1)','same_day_updates':False,'baseline_verification_sha256':sha(OUT/'baseline-verification.json'),'runner_sha256':sha(Path(__file__)),'production_approved':False,'limitations':['Source creation date does not prove historical delivery or revision availability.','Clock units are not inferred; only ordinal comparisons within source/center are used.','Top2/top3 are rank-model estimates, not independent target-trained models.','Period and benchmark were previously examined; not untouched OOS.','Candidate selection uncertainty is not yet adjusted.','Strict source creation filter may leave earlier years without eligible workouts.']}
    path=OUT/'protocol.json'
    if path.exists() and load(path)!=protocol:raise ValueError('Frozen protocol changed; use a new experiment version')
    save(path,protocol)
    data,baseline=prepare();results=[]
    for config in CONFIGS:
        if args.candidate and config['id']!=args.candidate:continue
        result_path=OUT/'results'/(config['id']+'.json')
        if result_path.exists():
            result=load(result_path)
            if result['config']!=config:raise ValueError('Stored config changed')
        else:
            result=experiment(config,data,baseline);save(result_path,result)
        results.append({k:v for k,v in result.items() if k!='paired_days'})
        save(OUT/'summary.json',{'requested':48,'completed':len(results),'baseline':baseline,'ranking':sorted(results,key=lambda r:r['overall']['1']['logloss']),'production_approved':False,'selection_adjusted':False})
        print(f"Completed {len(results)}/48: {config['id']} {result['experiment_decision']}",flush=True)
    if len(results)!=48 and not args.candidate:raise ValueError('Incomplete candidates')
    print('Three targets and training experiments completed',flush=True)
if __name__=='__main__':main()
