"""Weekend personal-JRA orchestration, separate from research promotion."""
import subprocess,sys,json,re,html
from datetime import datetime
import jwk
OUT=jwk.ROOT/'artifacts/jwk-weekend-v1'
DEADLINE='2026-10-10'
def summarize(source,forecast):
    return dict(state='predictions_saved' if forecast.get('predicted_races',0)>0 else 'awaiting_entries',predicted_races=forecast.get('predicted_races',0),predicted_runners=forecast.get('predicted_runners',0),source_state=source.get('state','not_observed'),production_promotion=False)
def main():
    before=jwk.observe()
    if before['tracks']['Platform']['existing_active']:raise RuntimeError('Preserve active legacy worker; defer weekend job')
    steps=[]
    scripts=['weekend_source_status.py','weekend_engine_check.py','refresh_prospective_history.py','prospective_capture.py','prospective_readiness.py','prospective_forecast.py','publish_prospective_forecast.py','weekend_personal_forecast.py','publish_weekend_ui.py']
    for name in scripts:
        path=jwk.ROOT/'src'/name
        if not path.exists():raise ValueError('Required orchestration component absent: '+name)
        run=subprocess.run([sys.executable,'-X','utf8','-B',str(path)],cwd=jwk.ROOT,capture_output=True,text=True,encoding='utf-8',timeout=150)
        steps.append(dict(script=name,exit_code=run.returncode,stdout=run.stdout[-3000:],stderr=run.stderr[-1500:]))
        if run.returncode:break
    source=jwk.read(jwk.ROOT/'artifacts/jwk-weekend-source-status-v1/latest.json');forecast=jwk.read(jwk.ROOT/'artifacts/jwk-weekend-personal-v1/latest.json')
    result=dict(updated_at=datetime.now().astimezone().isoformat(),weekend_dates=['20261010','20261011','20261012'],venues=['東京','京都'],use='個人の馬券判断支援',deadline_first_day=DEADLINE,team=dict(input='出馬表の取得と欠損診断',engine='jockey-25の3目標予測',integration='一括実行・画面・再試行'),**summarize(source,forecast),steps=steps,run_success=all(s['exit_code']==0 for s in steps),research_missions_preserved=True,automatic_betting=False,existing_db_changed=False)
    folder=OUT/datetime.now().strftime('%Y%m%d-%H%M%S-%f');jwk.save(folder/'result.json',result);jwk.save(OUT/'latest.json',result)
    message=f"週末JRA（10月10〜12日・東京／京都）：{'予想保存済み' if result['predicted_races'] else '確定出馬表の到着待ち'}。{result['predicted_races']}レース・{result['predicted_runners']}頭。個人の判断支援用。"
    section='<!-- WEEKEND_STATUS_START --><section id="weekend-status" style="max-width:1100px;margin:20px auto;padding:20px;background:#fff;border:2px solid #315b85;border-radius:12px"><h2>週末JRAの準備</h2><p>'+message+'</p><p>取得・予測・表示を一括確認しています。特別登録は確定出馬表と区別します。</p></section><!-- WEEKEND_STATUS_END -->'
    race_sections=[]
    for race in forecast.get('predictions',[]):
        rid=race['race_id']
        if rid[:8] not in result['weekend_dates']:continue
        table='<table><thead><tr><th>馬番</th><th>1着</th><th>2着以内</th><th>3着以内</th></tr></thead><tbody>'
        for runner in sorted(race['runners'],key=lambda r: -r['jockey_25'][0]):
            probs=runner['jockey_25']
            table+='<tr><td>'+html.escape(str(runner['horse_number']))+'</td>'+''.join('<td>'+f'{v:.1%}'+'</td>' for v in probs)+'</tr>'
        table+='</tbody></table>'
        race_sections.append('<h3>'+html.escape(rid)+'</h3>'+table)
    if race_sections:section=section.replace('</section>', '<p>表示方式：jockey-25。未採用の調教候補は表示に混ぜていません。</p>'+''.join(race_sections)+'</section>')
    page=jwk.ROOT/'web/index.html';page_html=page.read_text(encoding='utf-8')
    if '<!-- WEEKEND_STATUS_START -->' in page_html:page_html=re.sub(r'<!-- WEEKEND_STATUS_START -->.*?<!-- WEEKEND_STATUS_END -->',section,page_html,flags=re.S)
    else:page_html=page_html.replace('<main>',section+'<main>',1)
    page.write_text(page_html,encoding='utf-8')
    (OUT/'report.md').write_text('# 週末JRA運用の統合\n\n'+message+'\n\n一括入口：jwk run weekend-run。入力診断→エンジン確認→入力保存→準備確認→予測→表示。予想保存と本番への研究昇格は別で、未検証候補は昇格しない。\n',encoding='utf-8')
    print(json.dumps({k:result[k] for k in ('state','predicted_races','predicted_runners','run_success')},ensure_ascii=False))
    if not result['run_success']:raise SystemExit(1)
if __name__=='__main__':main()
