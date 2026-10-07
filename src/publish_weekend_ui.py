"""Publish personal/replay jockey25 predictions in the existing local UI."""
import json,re,html
from datetime import datetime
import jwk
ROOT=jwk.ROOT

def render(personal,replay):
    data=json.dumps(dict(personal=personal,replay=replay),ensure_ascii=False).replace('</','<\/')
    return """<!-- PERSONAL_WEEKEND_START -->
<section id="personal-weekend" style="max-width:1100px;margin:24px auto;padding:24px;background:#fff;color:#17253a;border:2px solid #315b85;border-radius:16px">
<h2>JRA 個人用予想 · jockey-25</h2><p>10月10〜12日の予想と、10月3・4日の事前情報限定の再現予想。</p>
<div style="display:flex;gap:12px;flex-wrap:wrap"><label>表示 <select id="pw-mode"><option value="personal">週末の予想</option><option value="replay">10月3・4日 再現予想</option></select></label><label>日付 <select id="pw-day"></select></label><label>開催 <select id="pw-venue"></select></label><label>レース <select id="pw-race"></select></label><label><input type="checkbox" id="pw-result">再現結果を表示</label></div>
<p id="pw-status" role="status"></p><div id="pw-table" style="overflow-x:auto"></div><p style="font-size:13px">1着・2着以内・3着以内のモデル推定値です。再現予想は現在保存されている過去記録から計算し、当時の配信を証明するものではありません。自動購入は行いません。</p>
</section><script>
(()=>{const D=DATA;const $=id=>document.getElementById('pw-'+id);const venues={'01':'札幌','02':'函館','03':'福島','04':'新潟','05':'東京','06':'中山','07':'中京','08':'京都','09':'阪神','10':'小倉'};
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const all=()=>{const mode=$('mode').value,source=D[mode];return (source.predictions||[]).filter(r=>{if(mode==='replay')return true;const rid=r.race_id,t=r.start_time||'',captured=Date.parse(source.captured_at),now=Date.now();if(t.length!==4)return false;const start=Date.parse(rid.slice(0,4)+'-'+rid.slice(4,6)+'-'+rid.slice(6,8)+'T'+t.slice(0,2)+':'+t.slice(2)+':00+09:00');return Number.isFinite(start)&&Number.isFinite(captured)&&captured<=now&&now-captured<=86400000&&now<start;});};
function options(el,values,label){const prior=el.value;el.innerHTML=values.map(v=>'<option value="'+esc(v)+'">'+esc(label(v))+'</option>').join('');if(values.includes(prior))el.value=prior;}
function dates(){options($('day'),[...new Set(all().map(r=>r.race_id.slice(0,8)))],v=>v.slice(0,4)+'/'+v.slice(4,6)+'/'+v.slice(6));places();}
function places(){options($('venue'),[...new Set(all().filter(r=>r.race_id.startsWith($('day').value)).map(r=>r.race_id.slice(8,10)))],v=>venues[v]||v);races();}
function races(){options($('race'),all().filter(r=>r.race_id.startsWith($('day').value)&&r.race_id.slice(8,10)===$('venue').value).map(r=>r.race_id),v=>Number(v.slice(-2))+'R');draw();}
function draw(){const mode=$('mode').value,source=D[mode],race=all().find(r=>r.race_id===$('race').value);$('result').disabled=mode!=='replay';
$('status').textContent=(mode==='personal'?'週末予想':'再現予想')+'：'+all().length+'レース・'+all().reduce((n,r)=>n+r.runners.length,0)+'頭'+(race?' ／ '+(race.race_name||race.name||'')+' '+(race.start_time||''):(mode==='personal'?'。確定出馬表の到着待ち。':'。再現予想の準備中。'))+((source.updated_at||source.created_at)?' ／ 更新 '+(source.updated_at||source.created_at):'');
if(!race){$('table').innerHTML=(mode==='personal'?'<p>確定出走馬を取得後、この画面へ予想を反映します。</p>':'<p>過去開催の全出走馬と予想の照合後に表示します。</p>');return;}
const show=mode==='replay'&&$('result').checked;
$('table').innerHTML='<table style="width:100%;border-collapse:collapse"><thead><tr><th>予想順</th><th>馬番</th><th>馬名</th><th>1着</th><th>2着以内</th><th>3着以内</th>'+(show?'<th>確定着順</th>':'')+'</tr></thead><tbody>'+[...race.runners].sort((a,b)=>b.jockey_25[0]-a.jockey_25[0]||Number(a.horse_number)-Number(b.horse_number)).map((r,i)=>'<tr style="border-top:1px solid #ddd;background:'+(i===0?'#edf5fb':'white')+'"><td>'+(i+1)+'</td><td>'+esc(r.horse_number)+'</td><td>'+esc(r.horse_name||r.name||r.horse_id)+'</td>'+r.jockey_25.map(p=>'<td style="padding:12px;text-align:right">'+(p*100).toFixed(1)+'%</td>').join('')+(show?'<td>'+esc(r.finish_order??r.result?.finish_order??'—')+'</td>':'')+'</tr>').join('')+'</tbody></table>';}
$('mode').onchange=dates;$('day').onchange=places;$('venue').onchange=races;$('race').onchange=draw;$('result').onchange=draw;dates();setInterval(()=>{if($('mode').value==='personal')dates();},30000);
})();</script><!-- PERSONAL_WEEKEND_END -->""".replace('DATA',data)

def main():
    personal=jwk.read(ROOT/'artifacts/jwk-weekend-personal-v1/latest.json')
    replay=jwk.read(ROOT/'artifacts/jwk-weekend-replay-v1/latest.json')
    section=render(personal,replay)
    page=ROOT/'web/index.html';old=page.read_text(encoding='utf-8')
    if '<!-- PERSONAL_WEEKEND_START -->' in old:
        updated=re.sub(r'<!-- PERSONAL_WEEKEND_START -->.*?<!-- PERSONAL_WEEKEND_END -->',lambda m:section,old,flags=re.S)
    else:
        updated=old.replace('</header>','</header>'+section,1)
    if updated==old and section not in old:raise ValueError('Page insertion failed')
    if updated!=old:
        backup=ROOT/'artifacts/jwk-weekend-ui-v1/backups'/('index-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f')+'.html');backup.parent.mkdir(parents=True,exist_ok=True);backup.write_text(old,encoding='utf-8');page.write_text(updated,encoding='utf-8')
    jwk.save(ROOT/'artifacts/jwk-weekend-ui-v1/latest.json',dict(updated_at=datetime.now().astimezone().isoformat(),personal_races=len(personal.get('predictions',[])),replay_races=len(replay.get('predictions',[])),url='http://127.0.0.1:8792/#personal-weekend',existing_ui_preserved=True))
    print('Personal/replay panel published')
if __name__=='__main__':main()
