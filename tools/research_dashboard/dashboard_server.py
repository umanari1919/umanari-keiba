from __future__ import annotations

import csv
import json
import os
import subprocess
import threading
import time
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(os.environ.get("THE_JOCKEY_RESEARCH_ROOT", Path.home() / "Downloads" / "THE-JOCKEY-RESEARCH"))
HOST = "127.0.0.1"
PORT = int(os.environ.get("THE_JOCKEY_DASHBOARD_PORT", "8791"))


def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def read_csv_rows(path: Path, limit: int = 200):
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
        return rows[:limit]
    except Exception:
        return []


def tail(path: Path, lines: int = 80):
    if not path.exists():
        return []
    try:
        data = path.read_text(encoding="utf-8", errors="replace").splitlines()
        return data[-lines:]
    except Exception:
        return []


def latest_mtime(paths):
    mtimes = [p.stat().st_mtime for p in paths if p.exists()]
    return max(mtimes) if mtimes else None


def mission_progress(missions):
    total = len(missions)
    complete = sum(1 for m in missions if str(m.get("state", "")).upper() == "COMPLETE")
    return {"complete": complete, "total": total, "pct": round((complete / total * 100), 1) if total else 0.0}


def normalize_missions(program):
    missions = program.get("missions", []) if isinstance(program, dict) else []
    out = []
    ready_found = False
    for m in missions:
        state = str(m.get("state", "PENDING")).upper()
        if state == "READY":
            ready_found = True
        out.append({
            "id": m.get("id", "-"),
            "name": m.get("name", ""),
            "state": state,
        })
    current = next((m for m in out if m["state"] == "READY"), None)
    if current is None:
        current = next((m for m in out if m["state"] == "PENDING"), None)
    return out, current


def build_state():
    core = ROOT / "CORE"
    reports = core / "reports"
    data = core / "data"
    program = read_json(core / "program.json", {}) or {}
    missions, current = normalize_missions(program)

    pop_rows = read_csv_rows(data / "CORE-001_domestic_population_audit.csv", 100)
    population = {"JRA": {}, "NAR": {}, "DOMESTIC_TOTAL": {}}
    for row in pop_rows:
        domain = row.get("domain")
        if domain in population and row.get("race_year") == "9999":
            population[domain] = row

    # CORE-001 exporter currently emits only DOMESTIC_TOTAL on 9999 in some versions.
    for domain in ("JRA", "NAR"):
        rows = [r for r in pop_rows if r.get("domain") == domain and r.get("race_year") != "9999"]
        if rows and not population[domain]:
            def total(key):
                return sum(int(float(r.get(key, 0) or 0)) for r in rows)
            population[domain] = {
                "race_count": str(total("race_count")),
                "runner_count": str(total("runner_count")),
                "safe_race_count": str(total("safe_race_count")),
                "safe_runner_count": str(total("safe_runner_count")),
            }

    leakage_rows = read_csv_rows(reports / "CORE-002_feature_contract_summary_v2.csv", 50)
    leakage = {}
    for row in leakage_rows:
        leakage[row.get("safety_class", "UNKNOWN")] = {
            "columns": int(float(row.get("columns", 0) or 0)),
            "tables": int(float(row.get("tables", 0) or 0)),
        }

    hist = read_json(reports / "CORE-003B_historical_feature_audit.json", {}) or {}
    base = read_json(reports / "CORE-003A_domestic_summary.json", {}) or {}
    fs = read_json(reports / "CORE-004_field_strength_audit.json", {}) or {}

    # Detect artifacts so status stays useful even if program.json lags behind.
    artifact_status = {
        "CORE-003A": (data / "CORE-003A_domestic_base_matrix.csv").exists(),
        "CORE-003B": (data / "CORE-003B_historical_features.csv").exists(),
        "CORE-004": (data / "CORE-004_field_strength_v2.csv").exists(),
        "CORE-005": any((core / "models").glob("*CORE-005*")) if (core / "models").exists() else False,
    }

    logs = []
    for p in [ROOT / "logs" / "orchestrator.log", ROOT / "logs" / "mission_runner.log"]:
        for line in tail(p, 50):
            logs.append({"source": p.name, "line": line})
    logs = logs[-80:]

    founder_action = "なし"
    blocked = [m for m in missions if m["state"] == "BLOCKED"]
    if blocked:
        founder_action = "BLOCKED Missionの確認が必要"
    elif current and current["state"] == "READY":
        founder_action = "なし（自動実行対象）"

    watched = [
        core / "program.json",
        reports / "CORE-003B_historical_feature_audit.json",
        reports / "CORE-004_field_strength_audit.json",
        ROOT / "logs" / "orchestrator.log",
    ]
    mt = latest_mtime(watched)

    return {
        "project": "THE JOCKEY 自律研究所",
        "root": str(ROOT),
        "updated": datetime.fromtimestamp(mt).astimezone().isoformat() if mt else datetime.now().astimezone().isoformat(),
        "current": current,
        "missions": missions,
        "progress": mission_progress(missions),
        "population": population,
        "leakage": leakage,
        "base": base,
        "historical": hist,
        "field_strength": fs,
        "artifact_status": artifact_status,
        "founder_action": founder_action,
        "logs": logs,
    }


HTML = r'''<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>THE JOCKEY 自律研究所</title>
<style>
:root{--bg:#0b0f14;--panel:#111820;--panel2:#17212b;--line:#263544;--txt:#e8f0f7;--muted:#91a2b1;--good:#55d187;--warn:#f4c95d;--bad:#ff6b6b;--info:#62a8ff}
*{box-sizing:border-box} body{margin:0;background:linear-gradient(180deg,#080b10,#101722);color:var(--txt);font-family:Segoe UI,"Yu Gothic UI",sans-serif}
header{position:sticky;top:0;z-index:5;background:#0a0f15eF;border-bottom:1px solid var(--line);backdrop-filter:blur(8px);padding:16px 22px;display:flex;align-items:center;justify-content:space-between}
h1{font-size:20px;margin:0;letter-spacing:.04em}.status{font-size:12px;color:var(--good)}
main{padding:18px;max-width:1500px;margin:auto}.grid{display:grid;grid-template-columns:repeat(12,1fr);gap:14px}.card{background:linear-gradient(180deg,var(--panel),#0e151d);border:1px solid var(--line);border-radius:14px;padding:16px;box-shadow:0 10px 28px #0005}.span12{grid-column:span 12}.span8{grid-column:span 8}.span6{grid-column:span 6}.span4{grid-column:span 4}.span3{grid-column:span 3}
.kicker{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.12em}.big{font-size:30px;font-weight:700;margin-top:6px}.sub{font-size:13px;color:var(--muted);margin-top:4px}.bar{height:9px;background:#071018;border-radius:20px;overflow:hidden;margin-top:12px}.bar>i{display:block;height:100%;background:linear-gradient(90deg,var(--info),var(--good));border-radius:20px}
.badge{display:inline-flex;padding:4px 8px;border-radius:20px;font-size:11px;font-weight:700;border:1px solid var(--line)}.COMPLETE{color:var(--good)}.READY{color:var(--info)}.PENDING{color:var(--muted)}.BLOCKED{color:var(--bad)}
table{width:100%;border-collapse:collapse;font-size:13px}th,td{text-align:left;padding:8px;border-bottom:1px solid #22303c}th{color:var(--muted);font-weight:600}.mono{font-family:Consolas,monospace;font-size:12px}.log{height:260px;overflow:auto;background:#080d12;border-radius:10px;padding:12px}.log div{padding:3px 0;color:#b9c5cf}.section-title{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px}.section-title h2{font-size:15px;margin:0}.pill{padding:5px 9px;border-radius:999px;background:#0a1219;border:1px solid var(--line);color:var(--muted);font-size:11px}
.metric{display:flex;justify-content:space-between;padding:7px 0;border-bottom:1px dashed #22303c}.metric:last-child{border-bottom:0}.metric b{font-size:16px}.good{color:var(--good)}.warn{color:var(--warn)}.bad{color:var(--bad)}
@media(max-width:900px){.span8,.span6,.span4,.span3{grid-column:span 12}header{padding:12px}.grid{gap:10px}main{padding:10px}}
</style>
</head>
<body>
<header><h1>THE JOCKEY｜自律研究所</h1><div><span class="status">● LIVE</span> <span id="updated" class="sub"></span></div></header>
<main><div class="grid">
<section class="card span8"><div class="kicker">CURRENT MISSION</div><div id="mission" class="big">読み込み中...</div><div id="missionName" class="sub"></div><div class="bar"><i id="progressBar" style="width:0%"></i></div><div id="progressText" class="sub"></div></section>
<section class="card span4"><div class="kicker">FOUNDER ACTION</div><div id="founder" class="big" style="font-size:22px"></div><div class="sub">重大・不可逆・高リスク以外は研究所が継続</div></section>
<section class="card span4"><div class="section-title"><h2>JRA</h2><span class="pill">中央</span></div><div id="jra"></div></section>
<section class="card span4"><div class="section-title"><h2>NAR</h2><span class="pill">地方</span></div><div id="nar"></div></section>
<section class="card span4"><div class="section-title"><h2>Feature Factory</h2><span class="pill">研究資産</span></div><div id="features"></div></section>
<section class="card span6"><div class="section-title"><h2>Leakage Guard</h2><span class="pill">CORE-002</span></div><div id="leakage"></div></section>
<section class="card span6"><div class="section-title"><h2>Artifact Status</h2><span class="pill">自動検出</span></div><div id="artifacts"></div></section>
<section class="card span12"><div class="section-title"><h2>Mission DAG</h2><span class="pill">CORE</span></div><table><thead><tr><th>Mission</th><th>状態</th><th>内容</th></tr></thead><tbody id="missions"></tbody></table></section>
<section class="card span12"><div class="section-title"><h2>Latest Logs</h2><span class="pill">5秒更新</span></div><div id="logs" class="log mono"></div></section>
</div></main>
<script>
const n=v=>Number(v||0).toLocaleString('ja-JP');
const metric=(k,v,cls='')=>`<div class="metric"><span>${k}</span><b class="${cls}">${v}</b></div>`;
function population(x){ if(!x||!Object.keys(x).length)return '<div class="sub">データ待ち</div>'; return metric('レース',n(x.race_count))+metric('出走頭数',n(x.runner_count))+metric('安全レース',n(x.safe_race_count),'good')+metric('安全出走頭数',n(x.safe_runner_count),'good'); }
async function refresh(){
  try{
    const s=await (await fetch('/api/state',{cache:'no-store'})).json();
    document.getElementById('updated').textContent=new Date(s.updated).toLocaleString('ja-JP');
    document.getElementById('mission').textContent=s.current?s.current.id:'QUEUE COMPLETE';
    document.getElementById('missionName').textContent=s.current?s.current.name:'現在READYのMissionはありません';
    document.getElementById('progressBar').style.width=s.progress.pct+'%';
    document.getElementById('progressText').textContent=`${s.progress.complete}/${s.progress.total} COMPLETE (${s.progress.pct}%)`;
    document.getElementById('founder').textContent=s.founder_action;
    document.getElementById('jra').innerHTML=population(s.population.JRA);
    document.getElementById('nar').innerHTML=population(s.population.NAR);
    const h=s.historical||{}, b=s.base||{}, f=s.field_strength||{};
    document.getElementById('features').innerHTML=metric('Base rows',n(b.rows))+metric('Historical features',n(h.generated_features||0),'good')+metric('History leakage',n(h.first_start_history_leaks||0),(h.first_start_history_leaks||0)?'bad':'good')+metric('Field Strength',f.generated_features?`${n(f.generated_features)} features`:'未生成',f.generated_features?'good':'warn');
    const order=['PRE_RACE_SAFE','HISTORICAL_ONLY','CONDITIONAL_SAFE','POST_RACE_ONLY','UNKNOWN'];
    document.getElementById('leakage').innerHTML=order.map(k=>{const v=(s.leakage||{})[k]||{}; const c=k==='UNKNOWN'?'warn':(k==='POST_RACE_ONLY'?'bad':''); return metric(k,n(v.columns||0),c)}).join('');
    document.getElementById('artifacts').innerHTML=Object.entries(s.artifact_status||{}).map(([k,v])=>metric(k,v?'PASS':'PENDING',v?'good':'warn')).join('');
    document.getElementById('missions').innerHTML=(s.missions||[]).map(m=>`<tr><td class="mono">${m.id}</td><td><span class="badge ${m.state}">${m.state}</span></td><td>${m.name}</td></tr>`).join('');
    document.getElementById('logs').innerHTML=(s.logs||[]).map(x=>`<div><span style="color:#607487">[${x.source}]</span> ${String(x.line).replaceAll('&','&amp;').replaceAll('<','&lt;')}</div>`).join('');
  }catch(e){ document.getElementById('mission').textContent='接続エラー'; document.getElementById('missionName').textContent=String(e); }
}
refresh(); setInterval(refresh,5000);
</script>
</body></html>'''


class Handler(BaseHTTPRequestHandler):
    def _send(self, status, content_type, body: bytes):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/state":
            body = json.dumps(build_state(), ensure_ascii=False).encode("utf-8")
            self._send(200, "application/json; charset=utf-8", body)
            return
        if path in ("/", "/index.html"):
            self._send(200, "text/html; charset=utf-8", HTML.encode("utf-8"))
            return
        if path == "/health":
            self._send(200, "text/plain; charset=utf-8", b"ok")
            return
        self._send(404, "text/plain; charset=utf-8", b"not found")

    def log_message(self, fmt, *args):
        return


def open_browser():
    time.sleep(0.8)
    webbrowser.open(f"http://{HOST}:{PORT}")


if __name__ == "__main__":
    if not ROOT.exists():
        raise SystemExit(f"Research root not found: {ROOT}")
    print("=" * 68)
    print(" THE JOCKEY 自律研究所 Dashboard")
    print("=" * 68)
    print(f"Research root : {ROOT}")
    print(f"Dashboard     : http://{HOST}:{PORT}")
    print("Ctrl+Cで停止")
    threading.Thread(target=open_browser, daemon=True).start()
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
