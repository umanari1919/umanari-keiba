"""Replay frozen jockey-25 and capture research scores without altering production."""
import ast, hashlib, json, gzip
from pathlib import Path
import personnel_experiments as personnel
import parallel_experiments as previous
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'artifacts/three-targets-training-v1'

def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp=path.with_name(path.name+'.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True), encoding='utf-8')
    temp.replace(path)

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    source=(ROOT/'src/decade_evaluate.py').read_text(encoding='utf-8-sig').split('\ndef main(',1)[0]
    files=sorted(list((personnel.BASE/'conditions').glob('*.json'))+list((personnel.BASE/'raw-cache').glob('*.json')))
    if len(files)!=195: raise ValueError('Expected 195 source snapshots')
    hashes={p.relative_to(personnel.BASE).as_posix():personnel.digest(p) for p in files}
    personnel.initialize(source,hashes)
    config={'id':'jockey-25','mode':'jockey','cap':.25}
    ns=personnel.engine(config)
    code=personnel.augment(previous.transformed(personnel.FIXED),config)
    code=previous.replace_once(code,'general = defaultdict(lambda:[0,0])','general = History(ACTIVE_CONFIG)')
    code=previous.replace_once(code,'local = defaultdict(lambda:[0,0])','local = History(ACTIVE_CONFIG)')
    code=previous.replace_once(code,'for day,day_rows in sorted(days.items()):','for day,day_rows in sorted(days.items()):\n            general.set_day(day)\n            local.set_day(day)')
    code=previous.replace_once(code,'                general[horse][0]+=1\n                general[horse][1]+=y\n                local[context_key][0]+=1\n                local[context_key][1]+=y','                general.add(horse,y)\n                local.add(context_key,y)')
    anchor='                        scores["uniform"].append(1.)'
    code=previous.replace_once(code,anchor,anchor+'\n                        CAPTURE(race_id, row, scores["candidate"][-1])')
    handles={}
    def capture(rid,row,score):
        year=rid[:4]
        if year not in handles:
            handles[year]=gzip.open(OUT/(year+'-scores.jsonl.gz.tmp'),'wt',encoding='utf-8')
        handles[year].write(json.dumps([rid,row['horse_id'],int(row['finish']),score],separators=(',',':'))+'\n')
    ns['CAPTURE']=capture
    ast.parse(code)
    exec(compile(code,'frozen-jockey-capture','exec'),ns)
    ns['snapshot']=lambda path:previous.CACHE[path.relative_to(personnel.BASE).as_posix()]
    ns['interval']=lambda *args:None
    try:
        report,pairs=ns['compute'](personnel.BASE,lambda y,n,r:print(f'Capture {y}: {n} records, {r} races',flush=True))
    finally:
        for handle in handles.values():handle.close()
    saved=personnel.load(ROOT/'artifacts/personnel-experiments-v1/results/jockey-25.json')
    for metric in ('logloss','brier'):
        if abs(report['overall']['metrics']['candidate'][metric]-saved['report']['overall']['metrics']['candidate'][metric])>1e-12:
            raise ValueError('Frozen jockey-25 does not match saved metrics')
    for year in handles:
        (OUT/(year+'-scores.jsonl.gz.tmp')).replace(OUT/(year+'-scores.jsonl.gz'))
    save(OUT/'baseline-verification.json',{'matched':True,'overall':report['overall'],'input_hashes':hashes,'personnel_hashes':personnel.load(personnel.OUT/'protocol.json')['personnel_hashes'],'capture_sha256':personnel.digest(Path(__file__)),'score_hashes':{p.name:personnel.digest(p) for p in OUT.glob('*-scores.jsonl.gz')},'production_approved':False})
    print('Frozen jockey-25 metrics matched; score capture complete',flush=True)
if __name__=='__main__':main()
