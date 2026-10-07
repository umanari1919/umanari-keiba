import json, math, hashlib, re, sys
from pathlib import Path
from collections import defaultdict, Counter
from datetime import datetime
from urllib.request import urlopen
from condition_audit import interval

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT/"artifacts/decade-2016-2025"
sys.stdout.reconfigure(encoding="utf-8",errors="replace")
METHODS = ("baseline","candidate","uniform")

def encoded(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True).encode("utf-8")

def load(path):
    return json.loads(path.read_text(encoding="utf-8"))

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def save(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp = path.with_name(path.name+".tmp")
    temp.write_bytes(encoded(value))
    temp.replace(path)

def snapshot(path):
    data = load(path)
    if hashlib.sha256(encoded(data["rows"])).hexdigest()!=data["rows_sha256"]:
        raise ValueError("スナップショットのハッシュ不一致："+str(path))
    return data["rows"]

def aggregate(entries):
    n = sum(r["rows"] for r in entries)
    if not n:
        return None
    return {
        "rows":n,"races":len(entries),
        "days":len({r["day"] for r in entries}),
        "metrics":{
            method:{
                "logloss":sum(r["loss"][method] for r in entries)/n,
                "brier":sum(r["brier"][method] for r in entries)/n
            } for method in METHODS
        },
        "delta_logloss":sum(r["delta_loss_sum"] for r in entries)/n,
        "delta_brier":sum(r["delta_brier_sum"] for r in entries)/n
    }

def compute(base,progress=None):
    general = defaultdict(lambda:[0,0])
    local = defaultdict(lambda:[0,0])
    fitted_rows = 0
    warmup_rows = 0
    years,warmup,all_pairs = [],[],[]

    for year in range(2011,2026):
        condition_rows = snapshot(base/"conditions"/f"{year}.json")
        counts = Counter(r["race_id"] for r in condition_rows)
        conditions = {r["race_id"]:r for r in condition_rows}
        raw = []
        for month in range(1,13):
            chunk = snapshot(base/"raw-cache"/f"{year}-{month:02}.json")
            if any(not r["race_id"].startswith(f"{year}{month:02}") for r in chunk):
                raise ValueError("対象月外の記録があります")
            raw.extend(chunk)

        days = defaultdict(list)
        for row in raw:
            days[row["race_id"][:8]].append(row)
        pairs,excluded = [],[]
        nonstarters = 0
        history_before = fitted_rows
        if year==2016 and fitted_rows==0:
            raise ValueError("初期履歴がなく2016年を評価できません")

        for day,day_rows in sorted(days.items()):
            races = defaultdict(list)
            for row in day_rows:
                races[row["race_id"]].append(row)
            updates = []
            for race_id,records in sorted(races.items()):
                c = conditions.get(race_id)
                reason = None
                if c is None:
                    reason = "条件情報なし"
                elif counts[race_id]!=1:
                    reason = "条件情報の重複"
                elif (not (c["distance"] or "").isdigit()
                      or int(c["distance"] or "0")<=0
                      or not (c["track"] or "").isdigit()
                      or len(c["track"] or "")!=2
                      or c["track"]=="00" or not c["race_class"]):
                    reason = "条件情報の不正"
                elif len({r["horse_id"] for r in records})!=len(records):
                    reason = "馬別記録の重複"
                elif any(not r["horse_id"] or r["abnormal"] not in tuple("01234567") for r in records):
                    reason = "未確認の馬ID・異常コード"

                active = [r for r in records if r["abnormal"] not in ("1","2","3")]
                nonstarters+=len(records)-len(active)
                if reason is None and (
                    not active or any(
                        not r["finish"].isdigit() or
                        (int(r["finish"])<1 and r["abnormal"]!="4")
                        for r in active
                    )
                ):
                    reason = "未確定結果・競走取りやめ等"
                winners = sum(int(r["finish"])==1 for r in active) if reason is None else 0
                if reason is None and winners==0:
                    reason = "勝馬未確定"
                if reason:
                    excluded.append({"race_id":race_id,"reason":reason})
                    continue

                def context(row):
                    return (
                        row["horse_id"],c["track"],int(c["distance"])//400,
                        c["grade"] or "0",c["race_class"]
                    )

                # 同日の結果はまだ反映せず、既存の履歴だけで予測
                if year>=2016 and winners==1:
                    scores = {m:[] for m in METHODS}
                    for row in active:
                        runs,wins = general[row["horse_id"]]
                        nr,nw = local[context(row)]
                        baseline = (wins+1)/(runs+12)
                        specific = (nw+1)/(nr+12)
                        weight = min(.5,nr/(nr+5))
                        scores["baseline"].append(baseline)
                        scores["candidate"].append((1-weight)*baseline+weight*specific)
                        scores["uniform"].append(1.)
                    loss,brier = {},{}
                    for method in METHODS:
                        total = sum(scores[method])
                        lm = bm = 0.
                        for row,score in zip(active,scores[method]):
                            p = max(1e-15,min(1-1e-15,score/total))
                            y = int(int(row["finish"])==1)
                            lm-=y*math.log(p)+(1-y)*math.log(1-p)
                            bm+=(p-y)**2
                        loss[method],brier[method] = lm,bm
                    pairs.append({
                        "race_id":race_id,"day":day,"month":day[4:6],
                        "venue":c["venue"],"rows":len(active),
                        "loss":loss,"brier":brier,
                        "delta_loss_sum":loss["candidate"]-loss["baseline"],
                        "delta_brier_sum":brier["candidate"]-brier["baseline"]
                    })
                elif year>=2016 and winners>1:
                    excluded.append({"race_id":race_id,"reason":"1着同着・現在の採点方式では対象外"})

                # 同着も実際の過去勝利として履歴へ入れるが、採点からは除外
                for row in active:
                    updates.append((row["horse_id"],context(row),int(int(row["finish"])==1)))
            for horse,context_key,y in updates:
                general[horse][0]+=1
                general[horse][1]+=y
                local[context_key][0]+=1
                local[context_key][1]+=y
                fitted_rows+=1

        if year<2016:
            warmup.append({
                "year":year,"raw_rows":len(raw),
                "usable_history_rows":fitted_rows-history_before,
                "excluded_races":excluded
            })
            warmup_rows = fitted_rows
        else:
            result = {
                "year":year,"raw_rows":len(raw),
                "history_rows_before_year":history_before,
                "overall":aggregate(pairs),
                "excluded_nonstarters":nonstarters,
                "excluded_races":excluded,
                "status":"evaluated" if pairs else "not_evaluated"
            }
            if pairs:
                result["day_interval"] = interval(pairs,"day",year)
                result["groups"] = {}
                for field in ("month","venue"):
                    grouped = defaultdict(list)
                    for entry in pairs:
                        grouped[entry[field]].append(entry)
                    result["groups"][field] = {
                        k:aggregate(v) for k,v in sorted(grouped.items())
                    }
            years.append(result)
            all_pairs.extend(pairs)
        if progress:
            progress(year,len(raw),len(pairs))

    overall = aggregate(all_pairs)
    report = {
        "requested_years":[2016,2025],
        "evaluated_years":sum(y["status"]=="evaluated" for y in years),
        "warmup_years":[2011,2015],"warmup_usable_rows":warmup_rows,
        "warmup":warmup,"years":years,"overall":overall,
        "day_interval":interval(all_pairs,"day",20162025) if all_pairs else None,
        "improved_years":sum(
            y["overall"] is not None and y["overall"]["delta_logloss"]<0 for y in years
        ),
        "production_approved":False,
        "limitations":[
            "candidate selected using 2024 results; retrospective comparison",
            "original pre-race availability and source revisions unverified",
            "official full-roster completeness and historical code mappings unverified",
            "2014 missing-condition race excluded from history",
            "bootstrap assumptions and temporal dependencies remain",
            "not directly comparable to fixed-at-2024 annual evaluation",
            "no calibrated probability or profitability claim"
        ]
    }
    return report,all_pairs

HTML = """
<!-- DECADE_START -->
<section id="decade-evaluation" style="max-width:1100px;margin:24px auto;padding:20px;background:white;color:#17253a;border-radius:12px">
<h2>2016〜2025年・10年間の年代順比較</h2>
<label>表示年 <select id="decade-year"></select></label>
<p id="decade-state"></p>
<div style="overflow-x:auto"><table>
<thead><tr><th>方法</th><th>Logloss</th><th>Brier</th></tr></thead>
<tbody id="decade-scores"></tbody></table></div>
<p id="decade-interval"></p>
<h3>年別の成績差</h3>
<div style="overflow-x:auto"><table>
<thead><tr><th>年</th><th>レース</th><th>記録</th><th>候補−基準のLogloss差</th></tr></thead>
<tbody id="decade-years"></tbody></table></div>
<details><summary>月別・競馬場別・対象外理由</summary><div id="decade-details"></div></details>
<p>2011〜2015年を初期履歴に使用。各日は過去日までの履歴で予測し、同日分の結果を翌日以降へ反映。
2014年の条件未接続1レースは履歴から除外。</p>
<p>候補は2024年の結果で選んだため、手法選択まで完全な未見検証ではありません。
過去時点の情報取得可能性、公式網羅性、歴史的なコードの意味の対応は未確認。
日単位の推定幅も仮定に依存します。本番未採用。</p>
<p>この評価は履歴を年代順に更新します。従来の2024年末固定の年間評価とは別条件です。</p>
</section>
<script>
(()=>{
const data=__DATA__;
const select=document.getElementById('decade-year');
const add=(v,t)=>{let o=document.createElement('option');o.value=v;o.textContent=t;select.append(o)};
add('all','10年間全体');data.years.forEach(y=>add(String(y.year),String(y.year)));
const names={baseline:'通常の過去勝率',candidate:'距離帯・トラック区分・競走条件を併用',uniform:'均等予想'};
const row=(target,values)=>{let tr=document.createElement('tr');values.forEach(v=>{let td=document.createElement('td');td.textContent=v;tr.append(td)});target.append(tr)};
const intervalText=ci=>ci?'日単位の95%推定幅（候補−基準のLogloss差）：['+ci.delta_logloss_95_interval.map(v=>v.toFixed(7)).join(', ')+']':'評価なし';
function render(){
 const selected=select.value==='all'?null:data.years.find(y=>String(y.year)===select.value);
 const result=selected?selected.overall:data.overall;
 document.getElementById('decade-state').textContent=selected?
 `${selected.year}年：${result?.races??0}レース・${result?.rows??0}記録`:
 `実評価 ${data.evaluated_years}/10年・${result?.races??0}レース・${result?.rows??0}記録。平均Logloss改善 ${data.improved_years}/10年`;
 const scores=document.getElementById('decade-scores');scores.replaceChildren();
 Object.entries(names).forEach(([k,n])=>row(scores,[n,result?.metrics[k]?.logloss.toFixed(6)??'—',result?.metrics[k]?.brier.toFixed(6)??'—']));
 document.getElementById('decade-interval').textContent=intervalText(selected?selected.day_interval:data.day_interval);
 const years=document.getElementById('decade-years');years.replaceChildren();
 data.years.forEach(y=>row(years,[y.year,y.overall?.races??0,y.overall?.rows??0,y.overall?.delta_logloss.toFixed(7)??'未評価']));
 const details=document.getElementById('decade-details');details.replaceChildren();
 const items=selected?[selected]:data.years;
 items.forEach(y=>{
  let heading=document.createElement('h4');heading.textContent=y.year+'年';details.append(heading);
  if(selected&&y.groups){
   ['month','venue'].forEach(field=>{
    let title=document.createElement('p');title.textContent=field==='month'?'月別':'競馬場コード別';details.append(title);
    let table=document.createElement('table');details.append(table);
    row(table,['区分','レース','Logloss差']);
    Object.entries(y.groups[field]).forEach(([k,v])=>row(table,[k,v.races,v.delta_logloss.toFixed(7)]));
   });
  }
  let p=document.createElement('p');p.textContent='採点対象外 '+y.excluded_races.length+'レース／取消・除外 '+y.excluded_nonstarters+'記録';details.append(p);
  let list=document.createElement('ul');details.append(list);
  y.excluded_races.forEach(r=>{let li=document.createElement('li');li.textContent=r.race_id+'：'+r.reason;list.append(li)});
 });
}
select.addEventListener('change',render);render();
})();
</script>
<!-- DECADE_END -->
"""

def main():
    collected = load(BASE/"collection-summary.json")
    if collected["completed_parts"]!=195 or collected["errors"]:
        raise ValueError("取得が未完了です。Run-Decade.cmdで再試行してください")
    prior = load(ROOT/"artifacts/condition-experiments-v1/report.json")
    if prior["selected_candidate"]!="distance_track_class":
        raise ValueError("固定候補が想定と異なります")
    inputs = sorted(list((BASE/"conditions").glob("*.json"))+
                    list((BASE/"raw-cache").glob("*.json")))
    if len(inputs)!=195:
        raise ValueError("スナップショット数が195と一致しません")
    policy = {
        "input_hashes":{p.relative_to(BASE).as_posix():sha(p) for p in inputs},
        "engine_sha256":sha(Path(__file__)),
        "uncertainty_engine_sha256":sha(ROOT/"src/condition_audit.py"),
        "history":"expanding from 2011; updates after each full day",
        "candidate":"fixed distance-track-class blend",
        "distance_band":400,"smoothing":[1,11],
        "context_weight":"min(0.5,n/(n+5))",
        "production_approved":False
    }
    protocol = BASE/"evaluation-protocol.json"
    if protocol.exists():
        if load(protocol)!=policy:
            raise ValueError("固定入力・計算条件が変わっています。混在を避けて停止します")
    else:
        save(protocol,policy)

    def progress(year,raw_count,race_count):
        role = "初期履歴" if year<2016 else "評価"
        print(f"{year}年：{role}・{raw_count:,}記録・採点{race_count:,}レース",flush=True)

    report,pairs = compute(BASE,progress)
    result_path = BASE/"report.json"
    if result_path.exists() and load(result_path)!=report:
        raise ValueError("保存済み長期評価と再現が一致しません")
    save(result_path,report)
    save(BASE/"paired-races.json",pairs)

    page_path = ROOT/"web/index.html"
    page = page_path.read_text(encoding="utf-8-sig")
    block = HTML.replace("__DATA__",json.dumps(report,ensure_ascii=False).replace("<","\\u003c"))
    start,end = "<!-- DECADE_START -->","<!-- DECADE_END -->"
    if start in page:
        if page.count(start)!=1 or page.count(end)!=1:
            raise ValueError("長期表示のマーカーが不正")
        page = re.sub(re.escape(start)+r".*?"+re.escape(end),lambda _:block.strip(),page,count=1,flags=re.S)
    else:
        if len(re.findall(r"</html\s*>",page,re.I))!=1:
            raise ValueError("HTML末尾が想定と異なります")
        backup = page_path.with_name("index.before-decade-"+datetime.now().strftime("%Y%m%d-%H%M%S-%f")+".html")
        backup.write_bytes(page_path.read_bytes())
        page = re.sub(r"</html\s*>",lambda m:block+m.group(0),page,count=1,flags=re.I)
    temporary = page_path.with_name("index.html.decade.tmp")
    temporary.write_text(page,encoding="utf-8")
    temporary.replace(page_path)

    from annual_pipeline import ensure_server
    ensure_server()
    with urlopen("http://127.0.0.1:8792/",timeout=5) as response:
        if 'id="decade-evaluation"' not in response.read().decode("utf-8"):
            raise ValueError("長期評価画面の配信が未確認")

    handover_path = ROOT/"HANDOVER.md"
    handover = handover_path.read_text(encoding="utf-8-sig")
    overall = report["overall"]
    note = f"""
<!-- DECADE_HANDOVER_START -->
## 10年間の長期評価
更新：{datetime.now().isoformat(timespec="seconds")}
入口：Run-Decade.cmd → decade_collect.py → decade_evaluate.py
結果：artifacts/decade-2016-2025/
初期履歴2011〜2015年、評価2016〜2025年。実評価{report['evaluated_years']}年。
{overall['races']}レース・{overall['rows']}記録。平均Logloss改善{report['improved_years']}年。
履歴は過去日のみ使用し、同日の全予測後に結果を反映。条件・候補は固定。
2014年の条件未接続レース2014061402010103は履歴から除外して記録。
同着は採点対象外だが、実際の勝利として後日の履歴には反映。
本番未採用。2024年選抜済み候補の遡及比較で、完全な未見検証ではない。
画面配信は確認済み、長期画面のユーザー確認は未確認。
従来の2024年末履歴固定の年間評価とは別条件として保存。
Save-Checkpoint.cmdに長期データと10年分の復元再計算を追加。
<!-- DECADE_HANDOVER_END -->
"""
    start,end = "<!-- DECADE_HANDOVER_START -->","<!-- DECADE_HANDOVER_END -->"
    if start in handover:
        handover = re.sub(re.escape(start)+r".*?"+re.escape(end),lambda _:note.strip(),handover,count=1,flags=re.S)
    else:
        backup = handover_path.with_name("HANDOVER.before-decade-"+datetime.now().strftime("%Y%m%d-%H%M%S-%f")+".md")
        backup.write_bytes(handover_path.read_bytes())
        handover+="\n"+note
    temporary = handover_path.with_name("HANDOVER.md.decade.tmp")
    temporary.write_text(handover,encoding="utf-8")
    temporary.replace(handover_path)

    save(ROOT/"artifacts/operations"/(
        "decade-"+datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    )/"operation.json",{
        "status":"completed","report_sha256":sha(result_path),
        "evaluated_years":report["evaluated_years"],
        "ui_delivery_verified":True,"user_visual_verified":False,
        "production_approved":False
    })
    print("【10年間の一括評価：完了】")
    for year in report["years"]:
        result = year["overall"]
        if not result:
            print(f"{year['year']}：未評価")
        else:
            print(f"{year['year']}：{result['races']}レース／"
                  f"基準 {result['metrics']['baseline']['logloss']:.6f}／"
                  f"候補 {result['metrics']['candidate']['logloss']:.6f}／"
                  f"差 {result['delta_logloss']:.7f}")
    print(f"全体：{report['evaluated_years']}年・{overall['races']:,}レース・{overall['rows']:,}記録")
    for method,name in (("baseline","通常の過去勝率"),("candidate","条件併用"),("uniform","均等予想")):
        values = overall["metrics"][method]
        print(f"{name}：Logloss {values['logloss']:.6f} / Brier {values['brier']:.6f}")
    print(f"平均Logloss改善：{report['improved_years']}/10年")
    print("日単位95%推定幅："+str(report["day_interval"]["delta_logloss_95_interval"]))
    print("保存・画面配信・引き継ぎ更新：完了。本番未採用。")

if __name__=="__main__":
    main()
