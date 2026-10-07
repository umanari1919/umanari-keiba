import sys, json, hashlib, ast, re
from pathlib import Path
from datetime import datetime
from collections import defaultdict, deque
from concurrent.futures import ProcessPoolExecutor, as_completed
import parallel_experiments as previous

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "artifacts/decade-2016-2025"
OUT = ROOT / "artifacts/personnel-experiments-v1"
BENCHMARK = None
BENCHMARK_REPORT = None

CONFIGS = [
    {"id":"control","mode":"control","cap":0.},
    {"id":"jockey-10","mode":"jockey","cap":.10},
    {"id":"jockey-25","mode":"jockey","cap":.25},
    {"id":"trainer-10","mode":"trainer","cap":.10},
    {"id":"trainer-25","mode":"trainer","cap":.25},
    {"id":"both-10","mode":"both","cap":.10},
    {"id":"both-25","mode":"both","cap":.25}
]
FROZEN_BASE={"id":"window-1095","kind":"window","days":1095}
CURRENT_PERSONNEL=CONFIGS[0]
RIDERS={}

FIXED = {
    "id":"class-s24-d800-w50", "strength":24,
    "width":800, "cap":.5, "context":"class"
}

def load(path):
    return json.loads(path.read_text(encoding="utf-8"))

def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True),
        encoding="utf-8"
    )
    temporary.replace(path)

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

class History:
    def __init__(self, config):
        self.config = config
        self.today = 0
        self.states = {}
        self.events = {}

    def set_day(self, day):
        self.today = datetime.strptime(day, "%Y%m%d").date().toordinal()

    def __getitem__(self, key):
        state = self.states.setdefault(key, [0., 0., self.today])
        kind = self.config["kind"]
        if kind == "decay":
            elapsed = self.today - state[2]
            factor = 2. ** (-elapsed / self.config["days"])
            state[0] *= factor
            state[1] *= factor
        elif kind == "window":
            queue = self.events.setdefault(key, deque())
            cutoff = self.today - self.config["days"]
            while queue and queue[0][0] < cutoff:
                _, win = queue.popleft()
                state[0] -= 1.
                state[1] -= win
        state[2] = self.today
        return state[:2]

    def add(self, key, win):
        self[key]
        state = self.states[key]
        state[0] += 1.
        state[1] += win
        if self.config["kind"] == "window":
            self.events[key].append((self.today, win))

def base_engine(config):
    config = FROZEN_BASE
    text = augment(previous.transformed(FIXED),CURRENT_PERSONNEL)
    if config["kind"] != "all":
        text = previous.replace_once(
            text,
            "general = defaultdict(lambda:[0,0])",
            "general = History(ACTIVE_CONFIG)"
        )
        text = previous.replace_once(
            text,
            "local = defaultdict(lambda:[0,0])",
            "local = History(ACTIVE_CONFIG)"
        )
        text = previous.replace_once(
            text,
            "for day,day_rows in sorted(days.items()):",
            "for day,day_rows in sorted(days.items()):\n"
            "            general.set_day(day)\n"
            "            local.set_day(day)"
        )
        old = (
            "                general[horse][0]+=1\n"
            "                general[horse][1]+=y\n"
            "                local[context_key][0]+=1\n"
            "                local[context_key][1]+=y"
        )
        new = (
            "                general.add(horse,y)\n"
            "                local.add(context_key,y)"
        )
        text = previous.replace_once(text, old, new)
    ast.parse(text)
    namespace = {
        "__file__":str(ROOT / "src/decade_evaluate.py"),
        "__name__":"recency_engine",
        "History":History, "ACTIVE_CONFIG":config,
        "RIDERS":RIDERS, "personnel_score":personnel_score,
        "MIX_CONFIG":dict(CURRENT_PERSONNEL)
    }
    exec(compile(text, "recency_engine", "exec"), namespace)
    namespace["snapshot"] = (
        lambda path: previous.CACHE[path.relative_to(BASE).as_posix()]
    )
    namespace["interval"] = lambda *args: None
    return namespace


def personnel_score(base,jockey,trainer,ids,config):
    estimates=[]
    for mode,store,key in (
        ("jockey",jockey,ids[0]),("trainer",trainer,ids[1])
    ):
        if config["mode"] not in (mode,"both"):
            continue
        runs,wins=store[key]
        rate=(wins+10)/(runs+120)
        weight=config["cap"]*runs/(runs+100)
        estimates.append((1-weight)*base+weight*rate)
    return sum(estimates)/len(estimates) if estimates else base

def augment(text,config):
    if config["mode"]=="control":
        return text
    text=previous.replace_once(
        text,"    fitted_rows = 0",
        "    jockey = History(ACTIVE_CONFIG)\n"
        "    trainer = History(ACTIVE_CONFIG)\n"
        "    fitted_rows = 0"
    )
    text=previous.replace_once(
        text,"for day,day_rows in sorted(days.items()):",
        "for day,day_rows in sorted(days.items()):\n"
        "            jockey.set_day(day)\n"
        "            trainer.set_day(day)"
    )
    text=previous.replace_once(
        text,"            updates = []",
        "            updates = []\n            personnel_updates = []"
    )
    text=previous.replace_once(
        text,
        'scores["candidate"].append((1-weight)*baseline+weight*specific)',
        'scores["candidate"].append(personnel_score('
        '(1-weight)*baseline+weight*specific,jockey,trainer,'
        'RIDERS[(race_id,row["horse_id"])],MIX_CONFIG))'
    )
    text=previous.replace_once(
        text,
        'updates.append((row["horse_id"],context(row),int(int(row["finish"])==1)))',
        'updates.append((row["horse_id"],context(row),int(int(row["finish"])==1)))\n'
        '                    personnel_updates.append(('
        'RIDERS[(race_id,row["horse_id"])],int(int(row["finish"])==1)))'
    )
    text=previous.replace_once(
        text,"                fitted_rows+=1",
        "                fitted_rows+=1\n"
        "            for ids,win in personnel_updates:\n"
        "                jockey.add(ids[0],win)\n"
        "                trainer.add(ids[1],win)"
    )
    return text

def engine(config):
    global CURRENT_PERSONNEL
    CURRENT_PERSONNEL=config
    return base_engine(FROZEN_BASE)

def initialize(source,hashes):
    global BENCHMARK,BENCHMARK_REPORT,RIDERS
    previous.init_worker(source,hashes)
    metadata=load(OUT/"protocol.json")["personnel_hashes"]
    for filename,expected in metadata.items():
        path=ROOT/"datasets/rider-trainer-v1"/filename
        if digest(path)!=expected:
            raise ValueError("騎手・調教師の入力が変更されています")
        envelope=load(path)
        actual=hashlib.sha256(previous.encoded(envelope["rows"])).hexdigest()
        if actual!=envelope["rows_sha256"]:
            raise ValueError("騎手・調教師のハッシュ不一致")
        for row in envelope["rows"]:
            key=(row["race_id"],row["horse_id"])
            if key in RIDERS:
                raise ValueError("騎手・調教師の接続重複")
            RIDERS[key]=(row["jockey_id"],row["trainer_id"])
    expected_keys=set()
    for relative,rows in previous.CACHE.items():
        if relative.startswith("raw-cache/"):
            expected_keys.update((r["race_id"],r["horse_id"]) for r in rows)
    if set(RIDERS)!=expected_keys:
        raise ValueError("既存履歴との接続キーが一致しません")
    namespace=engine(CONFIGS[0])
    BENCHMARK_REPORT,pairs=namespace["compute"](BASE)
    BENCHMARK={r["race_id"]:r for r in pairs}
    expected=load(
        ROOT/"artifacts/recency-experiments-v1/results/window-1095.json"
    )["report"]["overall"]
    for metric in ("logloss","brier"):
        actual=BENCHMARK_REPORT["overall"]["metrics"]["candidate"][metric]
        if abs(actual-expected["metrics"]["candidate"][metric])>1e-12:
            raise ValueError("直近3年の比較基準が再現されません")

def execute(config):
    namespace = engine(config)
    report, pairs = namespace["compute"](BASE)
    if {r["race_id"] for r in pairs} != set(BENCHMARK):
        raise ValueError("候補間で評価レースが一致しません")
    for row in pairs:
        reference = BENCHMARK[row["race_id"]]
        if row["rows"] != reference["rows"]:
            raise ValueError("評価頭数が一致しません")
        # 比較基準を前工程の最上位候補に置き換える
        row["loss"]["baseline"] = reference["loss"]["candidate"]
        row["brier"]["baseline"] = reference["brier"]["candidate"]
        row["delta_loss_sum"] = (
            row["loss"]["candidate"] - row["loss"]["baseline"]
        )
        row["delta_brier_sum"] = (
            row["brier"]["candidate"] - row["brier"]["baseline"]
        )

    aggregate = namespace["aggregate"]
    report["overall"] = aggregate(pairs)
    from condition_audit import interval
    report["day_interval"] = interval(pairs, "day", 20162025)
    by_year = defaultdict(list)
    daily = {}
    for row in pairs:
        by_year[int(row["day"][:4])].append(row)
        day = daily.setdefault(row["day"], {
            "day":row["day"], "rows":0, "races":0,
            "delta_loss_sum":0., "delta_brier_sum":0.
        })
        day["rows"] += row["rows"]
        day["races"] += 1
        day["delta_loss_sum"] += row["delta_loss_sum"]
        day["delta_brier_sum"] += row["delta_brier_sum"]
    for year in report["years"]:
        entries = by_year[year["year"]]
        year["overall"] = aggregate(entries)
        year["groups"] = {}
        for field in ("month", "venue"):
            grouped = defaultdict(list)
            for row in entries:
                grouped[row[field]].append(row)
            year["groups"][field] = {
                key:aggregate(rows) for key,rows in sorted(grouped.items())
            }
    report["improved_years"] = sum(
        y["overall"]["delta_logloss"] < 0 for y in report["years"]
    )
    report["benchmark"] = FIXED
    report["limitations"] = [
        "Comparison is against window-1095; personnel results use earlier days only.",
        "2016-2025 is a previously examined research period.",
        "Same-day results enter history only after the complete day.",
        "Windows are fixed calendar-day lengths, not calendar-year boundaries.",
        "Decay weights apply to both starts and wins.",
        "Intervals are unadjusted for candidate selection.",
        "Historical availability, code meanings and profitability unverified."
    ]
    if config["id"] == "control":
        if any(
            abs(report["overall"][key]) > 1e-12
            for key in ("delta_logloss", "delta_brier")
        ):
            raise ValueError("対照実験がゼロ差を再現しません")
    return {
        "config":config, "report":report,
        "paired_days":[daily[key] for key in sorted(daily)],
        "production_approved":False
    }

def publish(results, errors):
    ranked = sorted(
        results,
        key=lambda r:(
            r["report"]["overall"]["metrics"]["candidate"]["logloss"],
            r["config"]["id"]
        )
    )
    summary = {
        "completed":len(results), "requested":7,
        "failed":errors, "benchmark":{"condition":FIXED,"history_days":1095},
        "ranking":[{
            "config":r["config"], "overall":r["report"]["overall"],
            "improved_years":r["report"]["improved_years"],
            "day_interval":r["report"]["day_interval"]
        } for r in ranked],
        "production_approved":False
    }
    save(OUT / "summary.json", summary)
    rows = []
    for item in summary["ranking"]:
        overall = item["overall"]
        rows.append(
            f"<tr><td>{item['config']['id']}</td>"
            f"<td>{overall['metrics']['candidate']['logloss']:.8f}</td>"
            f"<td>{overall['delta_logloss']:+.8f}</td>"
            f"<td>{overall['delta_brier']:+.8f}</td>"
            f"<td>{item['improved_years']}/10</td></tr>"
        )
    start, end = "<!-- PERSONNEL_START -->", "<!-- PERSONNEL_END -->"
    section = (
        start +
        '<section style="max-width:1100px;margin:24px auto;padding:20px;'
        'background:white;color:#17253a;border-radius:12px">'
        '<h2>騎手・調教師を追加する一括実験</h2>'
        f'<p>完了 {len(results)}/7候補・失敗 {len(errors)}件。'
        '再読込で更新。</p>'
        '<p>比較基準：前工程の最上位候補'
        '（直近1,095日・平滑化24・800m帯・条件比重50%）。</p>'
        '<div style="overflow:auto"><table><thead><tr>'
        '<th>候補</th><th>Logloss</th><th>基準との差</th>'
        '<th>Brier差</th><th>改善年</th></tr></thead><tbody>'
        + "".join(rows) +
        '</tbody></table></div>'
        '<p>control＝直近3年方式の再現。jockey＝騎手、'
        'trainer＝調教師、both＝両方。10・25＝最大比重（%）。</p>'
        '<p>確認済み期間での研究用比較。'
        '順位・推定幅だけで採用しません。本番未採用。</p>'
        '</section>' + end
    )
    page = ROOT / "web/index.html"
    text = page.read_text(encoding="utf-8-sig")
    if start in text:
        if text.count(start)!=1 or text.count(end)!=1:
            raise ValueError("画面の追加欄が重複しています")
        a,b = text.index(start),text.index(end)+len(end)
        updated = text[:a]+section+text[b:]
    else:
        if len(re.findall(r"</html\s*>",text,re.I))!=1:
            raise ValueError("画面終了位置が一致しません")
        page.with_name(
            page.name+".before-recency-"+
            datetime.now().strftime("%Y%m%d-%H%M%S-%f")+".bak"
        ).write_bytes(page.read_bytes())
        updated = re.sub(
            r"</html\s*>",lambda m:section+m.group(),text,flags=re.I
        )
    temporary = page.with_name(page.name+".recency.tmp")
    temporary.write_text(updated,encoding="utf-8")
    temporary.replace(page)

def main():
    source = (ROOT/"src/decade_evaluate.py").read_text(encoding="utf-8-sig")
    source = source.split("\ndef main(",1)[0]
    previous.SOURCE = source
    for config in CONFIGS:
        engine(config)
    files = sorted(
        list((BASE/"conditions").glob("*.json"))+
        list((BASE/"raw-cache").glob("*.json"))
    )
    if len(files)!=195:
        raise ValueError("入力195ファイルがそろっていません")
    hashes = {p.relative_to(BASE).as_posix():digest(p) for p in files}
    personnel_files = sorted((ROOT/"datasets/rider-trainer-v1").glob("*.json"))
    if len(personnel_files)!=15:
        raise ValueError("騎手・調教師の15年分がそろっていません")
    personnel_hashes = {p.name:digest(p) for p in personnel_files}
    protocol = {
        "version":1, "configs":CONFIGS, "benchmark":{"condition":FIXED,"history_days":1095},
        "input_hashes":hashes, "runner_sha256":digest(Path(__file__)),
        "engine_sha256":hashlib.sha256(source.encode("utf-8")).hexdigest(),
        "previous_runner_sha256":digest(ROOT/"src/parallel_experiments.py"),
        "interval_sha256":digest(ROOT/"src/condition_audit.py"),
        "workers":2, "production_approved":False,
        "personnel_hashes":personnel_hashes,
        "history_days":1095,
        "personnel_smoothing":[10,110],
        "personnel_weight":"cap * runs / (runs + 100)"
    }
    path = OUT/"protocol.json"
    if path.exists() and load(path)!=protocol:
        raise ValueError("固定した実験条件が変わっています")
    save(path,protocol)
    results,pending,errors = [],[],[]
    for config in CONFIGS:
        path = OUT/"results"/(config["id"]+".json")
        if path.exists():
            result = load(path)
            if result["config"]!=config:
                raise ValueError("保存済み設定が一致しません")
            results.append(result)
            print("再利用："+config["id"],flush=True)
        else:
            pending.append(config)
    publish(results,errors)
    if pending:
        print("7候補を最大2プロセスで実験します。",flush=True)
        with ProcessPoolExecutor(
            max_workers=2,initializer=initialize,initargs=(source,hashes)
        ) as executor:
            futures = {executor.submit(execute,c):c for c in pending}
            for future in as_completed(futures):
                config = futures[future]
                try:
                    result = future.result()
                    save(OUT/"results"/(config["id"]+".json"),result)
                    results.append(result)
                    print(
                        f"完了 {len(results)}/7：{config['id']} / "
                        f"差 {result['report']['overall']['delta_logloss']:+.8f}",
                        flush=True
                    )
                except Exception as error:
                    errors.append({"id":config["id"],"error":str(error)})
                    print("失敗："+config["id"]+" / "+str(error),flush=True)
                publish(results,errors)
    if errors:
        raise RuntimeError("未完了候補があります。再実行で再試行できます")
    from annual_pipeline import ensure_server
    ensure_server()
    from urllib.request import urlopen
    with urlopen("http://127.0.0.1:8792/",timeout=10) as response:
        if b"PERSONNEL_START" not in response.read():
            raise ValueError("画面の配信を確認できません")
    summary = load(OUT/"summary.json")
    print("【騎手・調教師の一括実験：完了】")
    for item in summary["ranking"]:
        overall = item["overall"]
        print(
            f"{item['config']['id']} / "
            f"Logloss {overall['metrics']['candidate']['logloss']:.8f} / "
            f"差 {overall['delta_logloss']:+.8f} / "
            f"Brier差 {overall['delta_brier']:+.8f} / "
            f"改善 {item['improved_years']}/10年"
        )
    # 新しい結果を既存チェックポイントの保存対象へ追加
    checkpoint = ROOT/"src/checkpoint.py"
    text = checkpoint.read_text(encoding="utf-8-sig")
    if '"artifacts/personnel-experiments-v1"' not in text:
        anchor = "    selected = ["
        if text.count(anchor)!=1:
            raise ValueError("バックアップ対象の接続箇所が一致しません")
        updated = text.replace(
            anchor,anchor+
            '\n        "artifacts/personnel-experiments-v1",'
            '\n        "Run-Personnel-Experiments.cmd",',1
        )
        ast.parse(updated)
        checkpoint.with_name(
            checkpoint.name+".before-recency-"+
            datetime.now().strftime("%Y%m%d-%H%M%S-%f")+".bak"
        ).write_bytes(checkpoint.read_bytes())
        checkpoint.write_text(updated,encoding="utf-8")
    handover = ROOT/"HANDOVER.md"
    text = handover.read_text(encoding="utf-8-sig")
    if "## 騎手・調教師の一括実験" not in text:
        handover.write_text(
            text+"\n\n## 騎手・調教師の一括実験\n"
            "- 起動：Run-Personnel-Experiments.cmd\n"
            "- 7候補、比較基準は前工程の最上位候補。\n"
            "- 保存：artifacts/personnel-experiments-v1\n"
            "- 馬・騎手・調教師とも直近1,095日。過去日の結果だけを使用。\n"
            "- 研究用。本番未採用、候補選抜補正は未実施。\n"
            "- 結果のバックアップ対象追加済み。"
            "7候補の復元再計算は未実装。\n",
            encoding="utf-8"
        )
    print("保存・画面配信・引き継ぎ更新：完了。本番未採用。")

if __name__=="__main__":
    import msvcrt
    OUT.mkdir(parents=True,exist_ok=True)
    with (OUT/"execution.lock").open("a+b") as lock:
        lock.seek(0)
        if not lock.read(1):
            lock.write(b"0")
            lock.flush()
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        except OSError:
            raise SystemExit("騎手・調教師の実験は既に実行中です")
        main()