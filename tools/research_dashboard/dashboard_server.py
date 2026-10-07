from __future__ import annotations
import csv,json,os,threading,time,webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT=Path(os.environ.get('THE_JOCKEY_RESEARCH_ROOT',Path.home()/'Downloads'/'THE-JOCKEY-RESEARCH'))
HOST='127.0.0.1';PORT=int(os.environ.get('THE_JOCKEY_DASHBOARD_PORT','8791'))

def rj(p,d=None):
 try:return json.loads(p.read_text(encoding='utf-8-sig'))
 except:return d

def rc(p):
 try:
  with p.open('r',encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
 except:return []

def tail(p,n=80):
 try:return p.read_text(encoding='utf-8',errors='replace').splitlines()[-n:]
 except:return []

def st(name):return rj(ROOT/'checkpoints'/f'{name}_state.json',{}) or {}

def build():
 core=ROOT/'CORE';reports=core/'reports';program=rj(core/'program.json',{}) or {};missions=program.get('missions',[])
 current=next((m for m in missions if str(m.get('state','')).upper() in {'READY','RUNNING'}),next((m for m in missions if str(m.get('state','')).upper()=='PENDING'),None))
 complete=sum(str(m.get('state','')).upper()=='COMPLETE' for m in missions)
 plan=rj(reports/'TEMPORAL_SPLIT_plan.json',{}) or {};inventory=rj(reports/'DATA_INVENTORY_summary.json',{}) or {};recon=rj(reports/'DATA_RECONCILIATION_summary.json',{}) or {};chief=rj(reports/'CHIEF_OPERATING_report.json',{}) or {}
 strategy=rj(reports/'DECISION_STRATEGY_summary.json',{}) or {};failure=rj(reports/'FAILURE_ANALYSIS_summary.json',{}) or {};blind=rj(reports/'BLIND_EVALUATION_summary.json',{}) or {};sim=rj(reports/'RACE_SIMULATION_summary.json',{}) or {}
 sup=st('autonomy_supervisor');exp=st('experiment_director')
 ledger=rc(reports/'EXPERIMENT_ledger.csv');sid=str(exp.get('split_id') or '');cur=[x for x in ledger if not sid or str(x.get('split_id',''))==sid];promotes=sum(1 for x in cur if x.get('status')=='PROMOTE');last=cur[-1] if cur else {}
 workers={
  'データ棚卸し':st('data_inventory_director'),'未利用データ統合':st('data_reconciliation_director'),'時系列最適化':st('temporal_sample_optimizer'),'能力・勝率モデル':st('universal_model_director'),'確率校正':st('probability_director'),'着順シミュレーション':st('race_simulation_director'),'馬券戦略':st('decision_strategy_director'),'外れ理由分析':st('failure_analysis_director'),'仮説生成':st('hypothesis_generator'),'継続実験':exp,'JRA/NAR専門':st('domain_research_director'),'アンサンブル':st('ensemble_director'),'ブラインド評価':st('blind_evaluation_director'),'研究所統括':st('chief_operating_director')}
 logs=[]
 for p in [ROOT/'logs'/x for x in ['chief_operating_director.log','decision_strategy_director.log','failure_analysis_director.log','race_simulation_director.log','blind_evaluation_director.log','experiment_director.log','autonomy_supervisor.log','lab_updater.log']]:
  for line in tail(p,16):logs.append({'source':p.name,'line':line})
 return {'updated':datetime.now().astimezone().isoformat(),'current':current,'missions':missions,'progress':{'complete':complete,'total':len(missions),'pct':round(complete/len(missions)*100,1) if missions else 0},'chief':chief,'supervisor':sup,'temporal':plan,'inventory':inventory,'reconciliation':recon,'simulation':sim,'strategy':strategy,'failure':failure,'blind':blind,'workers':workers,'experiments':{'split_id':sid,'completed':exp.get('completed',len(cur)),'total':exp.get('total',0),'remaining':exp.get('remaining',0),'promotions':promotes,'mode':exp.get('mode','NORMAL'),'threads':exp.get('threads','-'),'last_seconds':exp.get('last_seconds','-'),'last':last},'production':sup.get('production',{}),'quality':sup.get('data_quality',{}),'drift':sup.get('drift',{}),'logs':logs[-180:]}

HTML='''<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>NEO JIZO ATLAS｜競馬研究ダッシュボード</title><style>
:root{--bg:#071019;--panel:#101b26;--panel2:#142332;--line:#263b4c;--text:#edf5fb;--muted:#8fa7b8;--good:#5de197;--warn:#f1c75b;--bad:#ff7878;--accent:#7cc5ff}*{box-sizing:border-box}body{margin:0;background:linear-gradient(180deg,#061019,#0d1721 42%,#09121a);color:var(--text);font-family:"Yu Gothic UI",Meiryo,Segoe UI,sans-serif}header{position:sticky;top:0;z-index:5;background:#071019ee;backdrop-filter:blur(12px);border-bottom:1px solid var(--line);padding:14px 20px;display:flex;justify-content:space-between;gap:12px;align-items:center}header b{font-size:18px}.sub{font-size:11px;color:var(--muted)}nav{display:flex;gap:8px;overflow:auto;padding:10px 18px;border-bottom:1px solid #172938;background:#0a141d}nav a{color:#c7d8e5;text-decoration:none;white-space:nowrap;font-size:12px;padding:6px 9px;border:1px solid #294154;border-radius:999px}main{max-width:1580px;margin:auto;padding:16px}.grid{display:grid;grid-template-columns:repeat(12,1fr);gap:12px}.card{background:linear-gradient(180deg,var(--panel2),var(--panel));border:1px solid var(--line);border-radius:15px;padding:15px;box-shadow:0 8px 26px #0003}.s12{grid-column:span 12}.s8{grid-column:span 8}.s6{grid-column:span 6}.s4{grid-column:span 4}.s3{grid-column:span 3}.big{font-size:27px;font-weight:800}.title{font-weight:800;margin-bottom:9px}.muted{color:var(--muted);font-size:12px}.metric{display:flex;justify-content:space-between;gap:12px;border-bottom:1px dashed #284052;padding:7px 0}.g{color:var(--good)}.w{color:var(--warn)}.r{color:var(--bad)}.a{color:var(--accent)}.badge{display:inline-block;padding:3px 8px;border-radius:999px;border:1px solid currentColor;font-size:11px;margin:2px}.flow{font-size:13px;line-height:1.8;background:#09141d;border-radius:10px;padding:10px}.note{font-size:12px;color:#bed0dc;line-height:1.7}table{width:100%;border-collapse:collapse}td,th{padding:8px;border-bottom:1px solid #263b4c;text-align:left;font-size:12px;vertical-align:top}th{color:#aac0d0}.log{height:280px;overflow:auto;background:#050c12;padding:10px;border-radius:10px;font:11px Consolas,monospace}.section-label{grid-column:span 12;font-size:13px;font-weight:800;color:#a9cce5;padding:10px 2px 2px;border-bottom:1px solid #203543}.pillrow{display:flex;gap:6px;flex-wrap:wrap}.mini{font-size:11px}.hero{background:linear-gradient(120deg,#14283b,#112332 60%,#182638)}@media(max-width:1000px){.s8,.s6,.s4,.s3{grid-column:span 12}header{align-items:flex-start;flex-direction:column}}</style></head><body>
<header><div><b>NEO JIZO ATLAS｜競馬研究ダッシュボード</b><div class="sub">データ・能力・血統・調教の研究と、将来予測に向けた検証状況を表示</div></div><span id="updated" class="sub"></span></header>
<nav><a href="#overview">今日の状態</a><a href="#data">データ</a><a href="#prediction">予測</a><a href="#strategy">馬券戦略</a><a href="#failure">外れ理由</a><a href="#blind">ブラインド</a><a href="#research">研究</a><a href="#ops">運用</a></nav>
<main><div class="grid">
<div id="overview" class="section-label">今日の状態</div>
<section class="card s8 hero"><div class="muted">現在の研究テーマ</div><div id="mission" class="big">-</div><div id="progress" class="muted"></div><div class="flow">能力評価 → 勝率/連対率/複勝率 → 着順シミュレーション → 各券種の適正オッズ → 市場比較 → 小点数戦略 → ブラインド評価 → 外れ理由分析</div></section>
<section class="card s4"><div class="muted">研究所総合状態</div><div id="chief" class="big">-</div><div id="chiefDetail"></div></section>
<section class="card s3"><div class="title">本番ゲート</div><div id="production"></div></section><section class="card s3"><div class="title">資源状態</div><div id="resource"></div></section><section class="card s3"><div class="title">漏洩監査</div><div id="leakage"></div></section><section class="card s3"><div class="title">自律運転</div><div id="autonomy"></div></section>
<div id="data" class="section-label">データ基盤 ― 「持っている」と「研究に使えている」を分けて見る</div>
<section class="card s4"><div class="title">母集団</div><div id="population"></div></section><section class="card s4"><div class="title">データ棚卸し</div><div id="inventory"></div></section><section class="card s4"><div class="title">未利用データ統合</div><div id="recon"></div></section>
<section class="card s12"><div class="title">時系列分割</div><div class="note">TRAIN=学習、VALIDATION=調整、SELECTION=モデル選抜、TEST=最終確認、OOS=研究へ逆流させない外部評価用。</div><table><thead><tr><th>役割</th><th>期間</th><th>レース</th><th>行</th><th>JRA</th><th>NAR</th><th>過去3走以上</th></tr></thead><tbody id="splits"></tbody></table></section>
<div id="prediction" class="section-label">予測層 ― 馬の能力とレース結果の確率</div>
<section class="card s4"><div class="title">着順シミュレーション</div><div id="simulation"></div></section><section class="card s4"><div class="title">対象券種</div><div class="pillrow"><span class="badge">単勝</span><span class="badge">複勝系</span><span class="badge">ワイド</span><span class="badge">馬連</span><span class="badge">馬単</span><span class="badge">枠連</span><span class="badge">三連複</span><span class="badge">三連単</span></div><div class="note">枠連は同枠1着・2着のゾロ目も独立集計。市場オッズは予測モデルへ入れず、次の意思決定層だけで使います。</div></section><section class="card s4"><div class="title">最新実験</div><div id="lastExp"></div></section>
<div id="strategy" class="section-label">意思決定層 ― 当てるより「資金効率」を研究</div>
<section class="card s4"><div class="title">馬券戦略</div><div id="strategyState"></div><div class="pillrow"><span class="badge">MIN-1 最大1点</span><span class="badge">MIN-2 最大2点</span><span class="badge">MIN-3 最大3点</span></div></section>
<section class="card s4"><div class="title">JRA研究仮説</div><div class="note"><b>午前の未勝利・新馬・障害</b>を資金形成フェーズ候補として検証。固定ルールにはせず、最終的にブラインド成績で採否を決めます。</div></section>
<section class="card s4"><div class="title">NAR研究方針</div><div class="note">時間帯固定ではなく、<b>Edge・不確実性・頭数・競馬場特性</b>から勝負機会を探すOpportunity Driven型。転入馬・クラス間Field Strengthも重点研究対象。</div></section>
<div id="failure" class="section-label">外れ理由 ― 「外れたからモデルが悪い」を禁止する</div>
<section class="card s8"><div class="title">失敗原因の内訳</div><div id="failureState"></div></section><section class="card s4"><div class="title">改善原則</div><div class="note">1回の外れではルールを変えません。同じ失敗分類が蓄積 → 仮説化 → 再研究 → TEST/OOS → Forward Blind の順で検証します。</div></section>
<div id="blind" class="section-label">独立監査 ― 結果を知らない未来で試す</div>
<section class="card s6"><div class="title">Forward Blind</div><div id="blindState"></div></section><section class="card s6"><div class="title">監査原則</div><div class="note">レース前に予測をSHA256で封印し、結果公開後だけ採点。ブラインド結果を見てChampionを選び直すことは禁止。将来は買い目・金額も封印するBlind Bettingへ拡張します。</div></section>
<div id="research" class="section-label">研究活動</div>
<section class="card s4"><div class="title">研究速度</div><div id="experiments"></div></section><section class="card s8"><div class="title">AI研究員</div><div id="workers"></div></section>
<section class="card s12"><div class="title">研究ミッション</div><table><thead><tr><th>ID</th><th>状態</th><th>内容</th></tr></thead><tbody id="missions"></tbody></table></section>
<div id="ops" class="section-label">運用・監査ログ</div><section class="card s12"><div class="title">最新ログ</div><div id="logs" class="log"></div></section>
</div></main><script>
const metric=(k,v,c='')=>`<div class="metric"><span>${k}</span><b class="${c}">${v??'-'}</b></div>`;
const cls=s=>['PASS','READY','RUNNING','COMPLETE','PROMOTE','TURBO'].includes(String(s).toUpperCase())?'g':(['WAITING','WARN','HOLD','PENDING','ALERT','KEEP','DEGRADED','THROTTLED','PARTIAL'].includes(String(s).toUpperCase())?'w':'r');
const jp={PASS:'正常',READY:'準備完了',RUNNING:'実行中',COMPLETE:'完了',WAITING:'待機',BLOCKED:'停止',PARTIAL:'一部注意',DEGRADED:'制限運転',THROTTLED:'減速運転',TURBO:'高速研究',HOLD:'保留',UNKNOWN:'未確認'};const J=s=>jp[String(s||'UNKNOWN').toUpperCase()]||s||'未確認';const pct=x=>x===undefined||x===null?'-':(Number(x)*100).toFixed(1)+'%';const n=x=>x===undefined||x===null?'-':Number(x).toLocaleString('ja-JP');
async function go(){try{const s=await (await fetch('/api/state',{cache:'no-store'})).json();updated.textContent='更新 '+new Date(s.updated).toLocaleString('ja-JP');mission.textContent=s.current?(s.current.name||s.current.id):'研究キュー待機';progress.textContent=`完了 ${s.progress.complete}/${s.progress.total}（${s.progress.pct}%）`;
let c=s.chief||{},cs=c.status||s.supervisor?.status||'WAITING';chief.textContent=J(cs);chief.className='big '+cls(cs);chiefDetail.innerHTML=metric('阻害要因',(c.blockers||[]).join(', ')||'なし',(c.blockers||[]).length?'r':'g')+metric('自動措置',(c.actions||[]).length||0)+metric('統制',J(c.orchestration?.status||'-'),cls(c.orchestration?.status));production.innerHTML=metric('予測モデル',J(s.production?.status),cls(s.production?.status))+metric('時系列',J(s.production?.temporal_status||'-'),cls(s.production?.temporal_status))+metric('自動投票','無効','w');resource.innerHTML=metric('運転モード',c.resources?.mode||'-',cls(c.resources?.mode))+metric('ディスク空き',c.resources?.disk_free_gb!==undefined?c.resources.disk_free_gb+' GB':'-')+metric('メモリ使用',c.resources?.memory_percent!==undefined?c.resources.memory_percent+'%':'-');leakage.innerHTML=metric('状態',J(c.leakage?.status),cls(c.leakage?.status))+metric('検出数',(c.leakage?.violations||[]).length||0,(c.leakage?.violations||[]).length?'r':'g');autonomy.innerHTML=metric('状態',J(s.supervisor?.status),cls(s.supervisor?.status))+metric('ドリフト',J(s.drift?.status||'-'),cls(s.drift?.status));
let tp=s.temporal||{},p=tp.population||{};population.innerHTML=metric('総行数',n(p.rows))+metric('レース数',n(p.races),'g')+metric('馬数',n(p.horses))+metric('JRA',n(p.jra_races))+metric('NAR',n(p.nar_races));inventory.innerHTML=metric('状態',J(s.inventory?.status),cls(s.inventory?.status))+metric('警告',(s.inventory?.alerts||[]).length||0,(s.inventory?.alerts||[]).length?'w':'g')+metric('更新',s.inventory?.updated_at||s.inventory?.updated||'-');recon.innerHTML=metric('状態',J(s.reconciliation?.status),cls(s.reconciliation?.status))+metric('処理件数',(s.reconciliation?.processed||[]).length||0)+metric('自動統合','厳格ゲート','g');
let ss=tp.splits||{};splits.innerHTML=['TRAIN','VALIDATION','SELECTION','TEST','OOS'].map(k=>{let x=ss[k]||{},d=x.domains||{},h=x.history||{},name={TRAIN:'学習',VALIDATION:'調整',SELECTION:'選抜',TEST:'最終確認',OOS:'外部評価'}[k];return `<tr><td><b>${name}</b><div class="sub">${k}</div></td><td>${x.start_date||'-'} → ${x.end_date||'-'}</td><td>${n(x.races)}</td><td>${n(x.rows)}</td><td>${n(d.JRA?.races)}</td><td>${n(d.NAR?.races)}</td><td>${pct(h.prior_3plus_rate)}</td></tr>`}).join('');
simulation.innerHTML=metric('状態',J(s.simulation?.status),cls(s.simulation?.status))+metric('入力ファイル',s.simulation?.inbox_files??'-')+metric('方式','着順反復シミュレーション','a');let e=s.experiments||{},le=e.last||{};lastExp.innerHTML=metric('結果',J(le.status||'-'),cls(le.status))+metric('選抜LogLoss',le.selection_logloss||'-')+metric('TEST',le.test_logloss||'-')+metric('OOS',le.oos_logloss_report_only||'-');strategyState.innerHTML=metric('状態',J(s.strategy?.status),cls(s.strategy?.status))+metric('市場ファイル',s.strategy?.market_files??'-')+metric('自動購入','しない','w');let fc=s.failure?.counts||{};failureState.innerHTML=Object.keys(fc).length?Object.entries(fc).sort((a,b)=>b[1]-a[1]).map(([k,v])=>metric(k,v,k.includes('HIGH_CONFIDENCE')||k.includes('NONPOSITIVE')?'r':k.includes('PRUNED')?'w':'')).join(''):metric('状態',J(s.failure?.status||'WAITING'),cls(s.failure?.status));blindState.innerHTML=metric('状態',J(s.blind?.status),cls(s.blind?.status))+metric('封印予測',s.blind?.frozen??s.blind?.frozen_count??'-')+metric('採点済み',s.blind?.scored??s.blind?.scored_count??'-')+metric('評価','結果非参照','g');experiments.innerHTML=metric('実験',`${e.completed||0} / ${e.total||0}`,'g')+metric('残り',e.remaining??'-')+metric('Champion更新',e.promotions||0,'g')+metric('CPUスレッド',e.threads||'-')+metric('直近',`${e.last_seconds||'-'}秒`);workers.innerHTML=Object.entries(s.workers||{}).map(([k,v])=>metric(k,J(v.status||'WAITING'),cls(v.status))).join('');missions.innerHTML=(s.missions||[]).map(x=>`<tr><td>${x.id||'-'}</td><td class="${cls(x.state)}">${J(x.state)}</td><td>${x.name||''}</td></tr>`).join('');logs.innerHTML=(s.logs||[]).map(x=>`<div><span style="color:#607487">[${x.source}]</span> ${String(x.line).replaceAll('&','&amp;').replaceAll('<','&lt;')}</div>`).join('')}catch(e){chief.textContent='表示エラー';chief.className='big r'}}go();setInterval(go,3000)</script></body></html>'''

class H(BaseHTTPRequestHandler):
 def sendx(self,status,ct,b):self.send_response(status);self.send_header('Content-Type',ct);self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(b)));self.end_headers();self.wfile.write(b)
 def do_GET(self):
  p=urlparse(self.path).path
  if p=='/api/state':self.sendx(200,'application/json; charset=utf-8',json.dumps(build(),ensure_ascii=False).encode())
  elif p in ('/','/index.html'):self.sendx(200,'text/html; charset=utf-8',HTML.encode())
  elif p=='/health':self.sendx(200,'text/plain; charset=utf-8',b'ok')
  else:self.sendx(404,'text/plain',b'not found')
 def log_message(self,*a):return

def op():time.sleep(.7);webbrowser.open(f'http://{HOST}:{PORT}')
if __name__=='__main__':
 print('='*68);print(' NEO JIZO ATLAS 日本語・競馬研究ダッシュボード');print('='*68);print(f'Research root : {ROOT}');print(f'Dashboard     : http://{HOST}:{PORT}');threading.Thread(target=op,daemon=True).start();ThreadingHTTPServer((HOST,PORT),H).serve_forever()
