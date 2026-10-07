import json, math, random, hashlib, re, html, sys
from pathlib import Path
from collections import defaultdict
from datetime import datetime
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/"artifacts/condition-audit-v1"
sys.stdout.reconfigure(encoding="utf-8",errors="replace")

def load(path):
    return json.loads(path.read_text(encoding="utf-8"))

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def save(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp = path.with_name(path.name+".tmp")
    temp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding="utf-8")
    temp.replace(path)

def aggregate(rows):
    n = sum(r["rows"] for r in rows)
    if not n:
        raise ValueError("集計対象なし")
    return {
        "rows":n,"races":len(rows),
        "days":len({r["day"] for r in rows}),
        "delta_logloss":sum(r["delta_loss_sum"] for r in rows)/n,
        "delta_brier":sum(r["delta_brier_sum"] for r in rows)/n
    }

def interval(rows,unit,seed):
    if unit=="day":
        grouped = defaultdict(list)
        for row in rows:
            grouped[row["day"]].append(row)
        units = [
            (sum(r["rows"] for r in group),
             sum(r["delta_loss_sum"] for r in group),
             sum(r["delta_brier_sum"] for r in group))
            for _,group in sorted(grouped.items())
        ]
    else:
        units = [(r["rows"],r["delta_loss_sum"],r["delta_brier_sum"]) for r in rows]
    rng = random.Random(seed)
    losses, briers = [], []
    for _ in range(2000):
        n = loss = brier = 0
        for _ in units:
            size,dl,db = units[rng.randrange(len(units))]
            n+=size
            loss+=dl
            brier+=db
        losses.append(loss/n)
        briers.append(brier/n)
    def limits(values):
        values.sort()
        def percentile(p):
            position = (len(values)-1)*p
            low = int(position)
            high = min(low+1,len(values)-1)
            return values[low]+(values[high]-values[low])*(position-low)
        return [percentile(.025),percentile(.975)]
    return {
        "resampling_unit":unit,"units":len(units),
        "repetitions":2000,"seed":seed,
        "delta_logloss_95_interval":limits(losses),
        "delta_brier_95_interval":limits(briers)
    }

def main():
    candidate_path = ROOT/"artifacts/condition-experiments-v1/report.json"
    candidate = load(candidate_path)
    if candidate["selected_candidate"]!="distance_track_class" or candidate["annual_reference"] is None:
        raise ValueError("検証対象の候補が想定と異なります")

    conditions_path = ROOT/"datasets/race-conditions-v1/races.json"
    history_path = ROOT/"artifacts/baseline-v3/history.json"
    conditions = {r["race_id"]:r for r in load(conditions_path)}
    history = load(history_path)
    prior_policy = load(ROOT/"artifacts/condition-experiments-v1/protocol.json")
    if sha(conditions_path)!=prior_policy["conditions_sha256"] or sha(history_path)!=prior_policy["history_sha256"]:
        raise ValueError("固定入力のハッシュが一致しません")

    raw_paths = [ROOT/f"artifacts/annual-2025/{m:02}/raw.json" for m in range(1,13)]
    for path in raw_paths:
        if sha(path)!=prior_policy["annual_raw_sha256"][path.parent.name]:
            raise ValueError("年間固定データのハッシュが不一致")

    policy = {
        "candidate_report_sha256":sha(candidate_path),
        "engine_sha256":sha(Path(__file__)),
        "primary_resampling_unit":"day",
        "secondary_resampling_unit":"race",
        "repetitions":2000,
        "grouping":["month","venue"],
        "difference":"candidate minus baseline; negative means improvement",
        "model_or_parameter_changes":False,
        "production_approved":False
    }
    protocol = OUT/"protocol.json"
    if protocol.exists():
        if load(protocol)!=policy:
            raise ValueError("保存済み監査条件と異なります")
    else:
        save(protocol,policy)

    def key(row):
        c = conditions[row["race_id"]]
        return (
            row["horse_id"],c["track"],int(c["distance"])//400,
            c["grade"] or "0",c["race_class"]
        )

    def fit(cutoff):
        general = defaultdict(lambda:[0,0])
        local = defaultdict(lambda:[0,0])
        for row in history:
            if row["race_id"][:8]>=cutoff:
                continue
            y = int(int(row["finish"])==1)
            for target in (general[row["horse_id"]],local[key(row)]):
                target[0]+=1
                target[1]+=y
        return general,local

    def paired(raw,counts):
        general,local = counts
        grouped = defaultdict(list)
        for row in raw:
            grouped[row["race_id"]].append(row)
        output = []
        loss_base = loss_model = brier_base = brier_model = 0.
        for race_id,raw_rows in sorted(grouped.items()):
            rows = [r for r in raw_rows if r["abnormal"] not in ("1","2","3")]
            if not rows or any(
                not r["finish"].isdigit() or
                (int(r["finish"])<1 and r["abnormal"]!="4")
                for r in rows
            ):
                continue
            if sum(int(r["finish"])==1 for r in rows)!=1:
                continue
            baseline,model_values = [],[]
            for row in rows:
                runs,wins = general[row["horse_id"]]
                nr,nw = local[key(row)]
                base = (wins+1)/(runs+12)
                specific = (nw+1)/(nr+12)
                weight = min(.5,nr/(nr+5))
                baseline.append(base)
                model_values.append((1-weight)*base+weight*specific)
            bt,mt = sum(baseline),sum(model_values)
            dl = db = 0.
            for row,b,m in zip(rows,baseline,model_values):
                y = int(int(row["finish"])==1)
                p = max(1e-15,min(1-1e-15,b/bt))
                q = max(1e-15,min(1-1e-15,m/mt))
                lb = -(y*math.log(p)+(1-y)*math.log(1-p))
                lm = -(y*math.log(q)+(1-y)*math.log(1-q))
                bb,bm = (p-y)**2,(q-y)**2
                dl+=lm-lb
                db+=bm-bb
                loss_base+=lb
                loss_model+=lm
                brier_base+=bb
                brier_model+=bm
            output.append({
                "race_id":race_id,"day":race_id[:8],
                "month":race_id[4:6],"venue":conditions[race_id]["venue"],
                "rows":len(rows),"delta_loss_sum":dl,"delta_brier_sum":db
            })
        n = sum(r["rows"] for r in output)
        metrics = {
            "baseline":{"rows":n,"logloss":loss_base/n,"brier":brier_base/n},
            "distance_track_class":{"rows":n,"logloss":loss_model/n,"brier":brier_model/n}
        }
        return output,metrics

    validation_raw = [r for r in history if r["race_id"][:8]>="20241001"]
    annual_raw = []
    for path in raw_paths:
        annual_raw.extend(load(path))

    reports,paired_data = {},{}
    for label,raw,cutoff,expected,seed in (
        ("validation_2024",validation_raw,"20241001",candidate["validation"],20241001),
        ("reference_2025",annual_raw,"20250101",candidate["annual_reference"],20250101)
    ):
        print("検証中："+label,flush=True)
        rows,metrics = paired(raw,fit(cutoff))
        if len(rows)!=expected["races"]:
            raise ValueError("既存候補の対象レースと不一致")
        for method in metrics:
            if metrics[method]["rows"]!=expected["metrics"][method]["rows"]:
                raise ValueError("既存候補の対象記録と不一致")
            if any(abs(metrics[method][k]-expected["metrics"][method][k])>1e-10 for k in ("logloss","brier")):
                raise ValueError("既存候補の数値を再現できません")
        groups = {}
        for field in ("month","venue"):
            grouped = defaultdict(list)
            for row in rows:
                grouped[row[field]].append(row)
            groups[field] = {k:aggregate(v) for k,v in sorted(grouped.items())}
        day_ci = interval(rows,"day",seed)
        race_ci = interval(rows,"race",seed+1)
        reports[label] = {
            "overall":aggregate(rows),"metrics":metrics,
            "day_interval":day_ci,"race_interval":race_ci,"groups":groups,
            "nominal_day_intervals_below_zero":all(
                day_ci[k][1]<0 for k in ("delta_logloss_95_interval","delta_brier_95_interval")
            )
        }
        paired_data[label] = rows

    decision = (
        "両期間・両指標の日単位の推定幅が0未満。平均改善の安定性を示す参考情報。"
        if all(r["nominal_day_intervals_below_zero"] for r in reports.values())
        else "平均値は改善していても、不確実性を考慮した改善の確定条件は満たさない。"
    )
    report = {
        "periods":reports,"decision":decision,
        "production_approved":False,
        "limitations":[
            "bootstrap intervals are descriptive and depend on resampling assumptions",
            "days can remain dependent across seasons; no proof of independence",
            "2024 validation selected the candidate; selection effects not corrected",
            "2025 already examined; not an untouched confirmatory test",
            "group analysis must not be used to cherry-pick profitable subsets",
            "no calibration or profitability claim"
        ]
    }
    result_path = OUT/"report.json"
    if result_path.exists() and load(result_path)!=report:
        raise ValueError("保存済み監査結果と再現が一致しません")
    save(result_path,report)
    save(OUT/"paired-races.json",paired_data)

    def ci_text(ci,key):
        low,high = ci[key]
        return f"[{low:.7f}, {high:.7f}]"

    blocks = []
    venue_names = {
        "01":"札幌","02":"函館","03":"福島","04":"新潟","05":"東京",
        "06":"中山","07":"中京","08":"京都","09":"阪神","10":"小倉"
    }
    for label,title in (("validation_2024","2024年・選抜に使った検証期間"),("reference_2025","2025年・参考評価")):
        r = reports[label]
        blocks.append(
            f"<h3>{title}</h3><p>候補−基準の差：Logloss {r['overall']['delta_logloss']:.7f}、"
            f"Brier {r['overall']['delta_brier']:.7f}。マイナスが改善です。</p>"
            f"<p>日単位の95%推定幅：Logloss {ci_text(r['day_interval'],'delta_logloss_95_interval')}、"
            f"Brier {ci_text(r['day_interval'],'delta_brier_95_interval')}</p>"
            f"<p>レース単位の参考幅：Logloss {ci_text(r['race_interval'],'delta_logloss_95_interval')}</p>"
        )
        for field,heading in (("month","月別"),("venue","競馬場別")):
            entries = "".join(
                f"<tr><td>{html.escape(venue_names.get(k,k) if field=='venue' else k+'月')}</td>"
                f"<td>{v['races']}</td><td>{v['delta_logloss']:.7f}</td>"
                f"<td>{v['delta_brier']:.7f}</td></tr>"
                for k,v in r["groups"][field].items()
            )
            blocks.append(
                f"<details><summary>{heading}の差</summary><div style='overflow-x:auto'><table>"
                "<thead><tr><th>区分</th><th>レース</th><th>Logloss差</th><th>Brier差</th></tr></thead>"
                f"<tbody>{entries}</tbody></table></div></details>"
            )
    block = """
<!-- CONDITION_AUDIT_START -->
<section id="condition-audit" style="max-width:1100px;margin:24px auto;padding:20px;background:white;color:#17253a;border-radius:12px">
<h2>改善幅の検証：月別・競馬場別・不確実性</h2>
""" + "<p><strong>"+html.escape(decision)+" 本番未採用。</strong></p>" + "".join(blocks) + """
<p>同じ日のレースをまとめて再標本化した幅を主に確認します。
推定幅は仮定に依存し、統計的優位性の証明ではありません。
選抜による影響の補正、季節間の依存、未使用データでの確認は未完了。
都合のよい月・競馬場だけを選ぶための表ではありません。</p>
</section>
<!-- CONDITION_AUDIT_END -->
"""
    page_path = ROOT/"web/index.html"
    page = page_path.read_text(encoding="utf-8-sig")
    start,end = "<!-- CONDITION_AUDIT_START -->","<!-- CONDITION_AUDIT_END -->"
    if start in page:
        if page.count(start)!=1 or page.count(end)!=1:
            raise ValueError("表示マーカーが不正")
        page = re.sub(re.escape(start)+r".*?"+re.escape(end),lambda _:block.strip(),page,count=1,flags=re.S)
    else:
        if len(re.findall(r"</html\s*>",page,re.I))!=1:
            raise ValueError("HTML末尾が想定と異なります")
        backup = page_path.with_name("index.before-audit-"+datetime.now().strftime("%Y%m%d-%H%M%S-%f")+".html")
        backup.write_bytes(page_path.read_bytes())
        page = re.sub(r"</html\s*>",lambda m:block+m.group(0),page,count=1,flags=re.I)
    temporary = page_path.with_name("index.html.audit.tmp")
    temporary.write_text(page,encoding="utf-8")
    temporary.replace(page_path)

    from annual_pipeline import ensure_server
    ensure_server()
    with urlopen("http://127.0.0.1:8792/",timeout=5) as response:
        if 'id="condition-audit"' not in response.read().decode("utf-8"):
            raise ValueError("監査結果の画面配信が未確認")

    handover_path = ROOT/"HANDOVER.md"
    handover = handover_path.read_text(encoding="utf-8-sig").replace(
        "条件別実験のユーザー表示確認は未確認",
        "条件別実験の再実行・画面表示はユーザー確認済み"
    )
    note = f"""
<!-- CONDITION_AUDIT_HANDOVER_START -->
## 条件別候補の改善幅検証
更新：{datetime.now().isoformat(timespec="seconds")}
入口：Run-Experiments.cmdの最後にsrc/condition_audit.pyを実行。
結果：artifacts/condition-audit-v1/（条件、監査結果、レースごとの差）。
既存候補の2024検証・2025参考評価の数値を再現してから検証。
月別・競馬場別集計、日単位を主とする2000回の再標本化、レース単位の参考幅。
判断：{decision}
本番未採用。モデル・設定・年間評価結果は変更していない。
画面配信は確認済み、監査画面のユーザー確認は未確認。
統計的優位性の証明ではなく、選抜効果や依存関係の限界がある。
Save-Checkpoint.cmdの保存対象へ監査結果を追加。
<!-- CONDITION_AUDIT_HANDOVER_END -->
"""
    start,end = "<!-- CONDITION_AUDIT_HANDOVER_START -->","<!-- CONDITION_AUDIT_HANDOVER_END -->"
    if start in handover:
        handover = re.sub(re.escape(start)+r".*?"+re.escape(end),lambda _:note.strip(),handover,count=1,flags=re.S)
    else:
        backup = handover_path.with_name("HANDOVER.before-audit-"+datetime.now().strftime("%Y%m%d-%H%M%S-%f")+".md")
        backup.write_bytes(handover_path.read_bytes())
        handover+="\n"+note
    temporary = handover_path.with_name("HANDOVER.md.audit.tmp")
    temporary.write_text(handover,encoding="utf-8")
    temporary.replace(handover_path)

    save(ROOT/"artifacts/operations"/(
        "condition-audit-"+datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    )/"operation.json",{
        "status":"completed","report_sha256":sha(result_path),
        "ui_delivery_verified":True,"user_visual_verified":False,
        "production_approved":False
    })
    print("【改善幅の検証：完了】")
    for label,r in reports.items():
        print(label+"：差 "+f"{r['overall']['delta_logloss']:.7f}")
        print("  日単位95%推定幅："+ci_text(r["day_interval"],"delta_logloss_95_interval"))
        improved = sum(v["delta_logloss"]<0 for v in r["groups"]["month"].values())
        print(f"  平均Loglossが改善した月：{improved}/{len(r['groups']['month'])}")
    print("判断："+decision)
    print("保存・配信・引き継ぎ更新：完了。本番未採用。")

if __name__=="__main__":
    main()
