"""Publish the locked 2026 comparison without starting or stopping services."""
import ast, html, json
from datetime import datetime
from urllib.request import urlopen
import training_three_targets as t
OUT=t.ROOT/'artifacts/oos-2026-training-v1'

def backup(path,stamp):path.with_name(path.name+'.before-oos-2026-'+stamp+'.bak').write_bytes(path.read_bytes())

def main():
    result=t.load(OUT/'result.json');verification=t.load(OUT/'capture-verification.json')
    assert verification['all_prior_scores_exactly_matched'] and result['previous_candidate_reproduced']
    assert result['last_scored_day']<=result['protocol']['evaluation_end']
    report=['# NEO JIZO KEIBA：固定候補の2026年評価','',f"更新：{datetime.now().astimezone().isoformat()}",'',f"評価対象：2026年1月1日〜10月5日。実際の最終評価日：{result['last_scored_day']}。途中年。",'候補：wood-14-1f-25（ウッド・14日・終い1F・最大比重25%）。2026年の結果取得前に候補・評価条件・採否基準を固定。','比較基準：jockey-25。2026年を使った48候補の選び直しはしていない。','予測は固定した時系列アルゴリズム。2026年も前日までの結果を履歴へ反映し、同日結果はその日の全レース予測後に更新。固定学習済みパラメータを年末まで据え置く評価とは異なる。','',f"生データ：{verification['raw_2026_races']:,}レース・{verification['raw_2026_rows']:,}記録。1着評価：{verification['2026_races']:,}レース・{verification['2026_rows']:,}頭。取消・除外：{verification['excluded_nonstarters']:,}記録。",f"調教特徴量が接続できた評価頭数：{result['eligible_training_rows']:,}。補正により予測が変わったレース：{result['changed_races']:,}。",'', '|目標|評価レース|評価頭数|基準Logloss|候補Logloss|基準Brier|候補Brier|基準の実測率|候補の実測率|','|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for k in ('1','2','3'):
        b=result['baseline'][k];c=result['candidate'][k]
        report.append(f"|{k}着以内|{b['races']}|{b['rows']}|{b['logloss']:.8f}|{c['logloss']:.8f}|{b['brier']:.8f}|{c['brier']:.8f}|{b['top_pick_observed_rate']:.2%}|{c['top_pick_observed_rate']:.2%}|")
    report+=['','実測率は各レースの予測最上位馬が目標に入った割合。全出走馬の陽性率とは異なる。','1着同着は元の方式どおり除外。2着・3着の同着は対象目標の陽性頭数が一致しない場合、その目標だけを除外。','', '|目標|指標|候補−基準|28日ブロック95%推定幅|Holm補正p|','|---|---|---:|---|---:|']
    for test in result['paired_tests']:
        lo,hi=test['block_bootstrap_95_percent']
        report.append(f"|{test['target']}着以内|{test['metric']}|{test['delta']:+.8f}|[{lo:+.8f}, {hi:+.8f}]|{test['p_holm']:.6f}|")
    report+=['',f"研究判断：**{result['experiment_decision']}**。本番判断：**REJECT**。jockey-25を維持し、調教方式を本番には採用しない。",'PROMOTE条件：3目標ともLogloss・Brierが改善し、最上位馬の実測率がすべて非悪化、6指標のHolm補正pがすべて0.05未満。3目標の両指標の平均のみ改善した場合はKEEP、それ以外はREJECT。','6指標の符号検定と推定幅は28暦日ブロック・20,000回。推定幅自体は多重比較補正していない。','', '## 検証と限界','',f"過去2016〜2025年の全{verification['matched_rows']:,}頭のjockey-25スコアが保存済みと完全一致。調教候補の過去3目標の集計も再現。",'DBは読取専用。既存DBの削除・変更、サービス停止、フォルダー移動は実施していない。','過去データによる2026年の初回評価であり、予測を実際に事前配信していた証明ではない。ソース作成日・調教日がレース前でも、取得可能性と訂正履歴は未検証。','公式全出走表との網羅性、確率校正、収益性は未検証。順位モデルで算出した2着・3着以内の確率で、独立した目標別学習モデルではない。','2026年の結果を見て他の19候補へ乗り換えると、この期間の未使用評価としての扱いを失う。','','## 対象外レース','']
    report += [f"- {row['race_id']}：{row['reason']}" for row in verification['excluded_races']]
    (OUT/'report.md').write_text('\n'.join(report)+'\n',encoding='utf-8')
    start,end='<!-- TRAINING_OOS_2026_START -->','<!-- TRAINING_OOS_2026_END -->'
    rows=[]
    for k in ('1','2','3'):
        b=result['baseline'][k];c=result['candidate'][k]
        rows.append(f"<tr><td>{k}着以内</td><td>{b['races']:,}</td><td>{b['logloss']:.8f}</td><td>{c['logloss']:.8f}</td><td>{b['brier']:.8f}</td><td>{c['brier']:.8f}</td><td>{b['top_pick_observed_rate']:.2%}</td><td>{c['top_pick_observed_rate']:.2%}</td></tr>")
    section=start+'<section style="max-width:1100px;margin:24px auto;padding:20px;background:white;color:#17253a;border-radius:12px"><h2>2026年・固定調教候補の評価</h2><p>候補：ウッド・14日・終い1F・25%。比較基準：jockey-25。候補と採否条件を結果取得前に固定。</p><p>2026年1月1日〜10月5日を対象。最終評価日：'+result['last_scored_day']+'。途中年の過去データ評価。前日までの結果を固定アルゴリズムで履歴更新します。</p><div style="overflow:auto"><table><thead><tr><th>目標</th><th>レース</th><th>基準Logloss</th><th>候補Logloss</th><th>基準Brier</th><th>候補Brier</th><th>基準の実測率</th><th>候補の実測率</th></tr></thead><tbody>'+''.join(rows)+'</tbody></table></div><p>実測率＝予測最上位馬の1着・2着以内・3着以内率。研究判断：'+result['experiment_decision']+'。本番判断：REJECT。jockey-25を維持。</p><p>6指標の比較に28暦日ブロックとHolm補正。独立した目標別学習・確率校正・収益性・公式網羅性・過去の配信と訂正履歴は未検証。</p></section>'+end
    stamp=datetime.now().strftime('%Y%m%d-%H%M%S-%f');page=t.ROOT/'web/index.html';text=page.read_text(encoding='utf-8-sig')
    if start in text:
        if text.count(start)!=1 or text.count(end)!=1:raise ValueError('Duplicated OOS section')
        updated=text[:text.index(start)]+section+text[text.index(end)+len(end):]
    else:
        if text.lower().count('</html>')!=1:raise ValueError('Closing html mismatch')
        offset=text.lower().index('</html>');updated=text[:offset]+section+text[offset:]
    if text!=updated:backup(page,stamp);page.write_text(updated,encoding='utf-8')
    checkpoint=t.ROOT/'src/checkpoint.py';text=checkpoint.read_text(encoding='utf-8-sig')
    if '"artifacts/oos-2026-training-v1"' not in text:
        anchor='    selected = ['
        if text.count(anchor)!=1:raise ValueError('Checkpoint anchor mismatch')
        updated=text.replace(anchor,anchor+'\n        "artifacts/oos-2026-training-v1",\n        "datasets/oos-2026-training-v1",\n        "Run-Training-OOS-2026.cmd",',1)
        ast.parse(updated);backup(checkpoint,stamp);checkpoint.write_text(updated,encoding='utf-8')
    delivered=False
    try:
        with urlopen('http://127.0.0.1:8792/',timeout=10) as response:delivered=start.encode() in response.read()
    except OSError:pass
    handover=t.ROOT/'HANDOVER.md';text=handover.read_text(encoding='utf-8-sig');mark='## 固定調教候補の2026年評価'
    note='\n\n'+mark+'\n- 更新：'+datetime.now().astimezone().isoformat()+'\n- 固定候補：wood-14-1f-25、基準jockey-25。2026結果取得前に条件固定。\n- 対象2026年1月1日〜10月5日、実際の最終評価日'+result['last_scored_day']+'。\n- 1着評価：'+str(verification['2026_races'])+'レース・'+str(verification['2026_rows'])+'頭。\n- 過去479100頭のjockey-25スコア完全一致、調教候補の過去3目標の集計を再現。\n- 2026年も前日までの結果で履歴更新する固定アルゴリズム。\n- 3目標のLogloss・Brier・最上位馬の実測率を比較、6指標に28暦日ブロックとHolm補正。\n- 研究判断：'+result['experiment_decision']+'。本番判断：REJECT。jockey-25を維持。\n- 保存：artifacts/oos-2026-training-v1/report.md、result.json、protocol.json。\n- 起動：Run-Training-OOS-2026.cmd。保存済みDB取得を再利用し、再計算する。\n- 画面HTTP配信確認：'+str(delivered)+'、目視確認は未実施。\n- バックアップ対象追加済み。この評価の復元再計算は未検証。\n- 公式網羅性、当時の配信・訂正履歴、校正、収益性は未検証。本番未採用。\n'
    if mark not in text:backup(handover,stamp);handover.write_text(text+note,encoding='utf-8')
    files=list((t.ROOT/'datasets/oos-2026-training-v1').rglob('*'))+list(OUT.glob('*.json'))
    t.save(OUT/'manifest.json',{'files':{p.relative_to(t.ROOT).as_posix():t.sha(p) for p in sorted(files) if p.is_file() and p.name not in ('manifest.json','completion.json')},'report_sha256':t.sha(OUT/'report.md')})
    t.save(OUT/'completion.json',{'completed':True,'experiment_decision':result['experiment_decision'],'production_decision':'REJECT','http_page_delivered':delivered,'visual_confirmation':False,'protocol_frozen_before_extraction':True,'prior_scores_matched':True,'prior_workout_metrics_matched':True,'db_modified':False,'services_stopped':False,'folders_moved':False})
    print(json.dumps({'experiment_decision':result['experiment_decision'],'production_decision':'REJECT','http_page_delivered':delivered,'last_scored_day':result['last_scored_day']},ensure_ascii=False))
if __name__=='__main__':main()
