"""Selection audit, Japanese report and existing-page integration; no service operations."""
import ast, html, json, math, random
from collections import defaultdict
from datetime import datetime
from urllib.request import urlopen
import training_three_targets as t

OUT=t.OUT

def audit(results):
    tests=[]
    for result in results:
        for target in range(3):
            blocks=defaultdict(float)
            for row in result['paired_days']:
                blocks[t.ordinal(row['day'])//28]+=row['delta_loss_sum'][target]
            values=[v for v in blocks.values() if v!=0]
            observed=sum(values)
            rng=random.Random(20261006)
            exceed=0
            if observed<0 and values:
                for _ in range(20000):
                    sampled=sum(v*(1 if rng.getrandbits(1) else -1) for v in values)
                    exceed+=sampled<=observed
                p=(exceed+1)/20001
            else:p=1.
            tests.append({'id':result['config']['id'],'target':target+1,'p_one_sided':p,'nonzero_28day_blocks':len(values),'delta_logloss':result['delta'][str(target+1)]['logloss']})
    ordered=sorted(tests,key=lambda x:x['p_one_sided']);previous=0.
    for i,item in enumerate(ordered):
        previous=max(previous,min(1.,(len(ordered)-i)*item['p_one_sided']))
        item['p_holm']=previous
    indexed={(r['id'],str(r['target'])):r for r in tests}
    decisions=[]
    for result in results:
        retained=all(result['delta'][str(k)]['logloss']<0 and result['delta'][str(k)]['brier']<0 and indexed[(result['config']['id'],str(k))]['p_holm']<.05 for k in (1,2,3))
        decisions.append({'id':result['config']['id'],'experiment_decision':'KEEP' if retained else 'REJECT','production_decision':'REJECT','production_approved':False})
    return {'tests':tests,'comparison_count':len(tests),'draws':20000,'block_calendar_days':28,'correction':'Holm across 48 candidates x 3 target Logloss tests','brier_selection_adjusted':False,'retention_rule':'All three target Logloss Holm p<.05 and both mean metrics improve for all three targets','decisions':decisions,'retained_research_candidates':[r['id'] for r in decisions if r['experiment_decision']=='KEEP'],'production_decision':'REJECT','limitations':['Brier significance and calibration are not established.','Previously examined retrospective data and benchmark-selection effects are not corrected.','Non-overlapping 28-calendar-day sign blocks require symmetry and adequate temporal independence.','Source creation dates do not prove actual pre-race delivery or revision history.']}

def backup(path,stamp):
    path.with_name(path.name+'.before-three-targets-'+stamp+'.bak').write_bytes(path.read_bytes())

def main():
    files=sorted((OUT/'results').glob('*.json'))
    results=[t.load(p) for p in files]
    if len(results)!=48 or {r['config']['id'] for r in results}!={c['id'] for c in t.CONFIGS}:raise ValueError('48 candidates not complete')
    baseline=t.load(OUT/'three-target-baseline.json');summary=t.load(OUT/'summary.json')
    if summary['completed']!=48:raise ValueError('Summary incomplete')
    selection=audit(results);t.save(OUT/'selection-check.json',selection)
    decisions={r['id']:r for r in selection['decisions']}
    for row in summary['ranking']:
        row['descriptive_screening_decision']=row['experiment_decision']
        row['experiment_decision']=decisions[row['config']['id']]['experiment_decision']
    for result in results:
        result.setdefault('descriptive_screening_decision',result['experiment_decision'])
        result['experiment_decision']=decisions[result['config']['id']]['experiment_decision']
        result['decision_scope']='Holm-adjusted three-target Logloss plus descriptive Brier gate; production rejected'
        t.save(OUT/'results'/(result['config']['id']+'.json'),result)
    summary['selection_adjusted']=True
    summary['selection_adjusted_metrics']=['logloss']
    summary['retained_research_candidates']=selection['retained_research_candidates']
    t.save(OUT/'summary.json',summary)
    coverage=t.load(OUT/'workout-coverage.json')
    report=['# NEO JIZO KEIBA：3目標と調教48候補','',f"更新：{datetime.now().astimezone().isoformat()}",'','基準：jockey-25。2016〜2025年の既存10年評価と勝率のLogloss・Brierが一致。','2着以内・3着以内は勝率スコアから順位モデルで推定した周辺確率。独立した目標別学習ではない。','','|目標|レース|頭数|Logloss|Brier|最上位馬の実測率|','|---|---:|---:|---:|---:|---:|']
    for k in ('1','2','3'):
        b=baseline['overall'][k]
        report.append(f"|{k}着以内|{b['races']}|{b['rows']}|{b['logloss']:.8f}|{b['brier']:.8f}|{b['top_pick_observed_rate']:.2%}|")
    report+=['','48/48候補完了。坂路／ウッド／併用 × 7／14日 × 有無／回数／4F／終い1F × 最大比重10／25%。','調教日とソース作成日がともにレース日より前の記録だけを使用。同日の結果は全レース予測後に履歴へ反映。','欠損は中立の補正。4F・1Fは同じ調教種別・トレセン内で時計コードの相対順位を使用し、秒単位と断定しない。','調教補正の履歴は2016年から開始、直近1095日。基準予測の2011〜2015年初期履歴とは区別。','','|候補|1着Logloss差|2着以内差|3着以内差|1着実測率|2着以内実測率|3着以内実測率|研究判断|','|---|---:|---:|---:|---:|---:|---:|---|']
    for r in summary['ranking']:
        report.append('|'+r['config']['id']+'|'+ '|'.join(f"{r['delta'][str(k)]['logloss']:+.8f}" for k in (1,2,3))+'|'+ '|'.join(f"{r['overall'][str(k)]['top_pick_observed_rate']:.2%}" for k in (1,2,3))+'|'+r['experiment_decision']+'|')
    report+=['','研究判断：'+(', '.join(selection['retained_research_candidates']) or '48候補ともREJECT。jockey-25を維持。'),'本番判断：REJECT。調教候補は本番未採用。','48候補×3目標のLoglossを28暦日ブロック・20000回の符号再標本化とHolm補正で確認。Brierの統計的優位性・確率校正・収益性は未検証。','既に調べた期間の研究比較。完全な未見OOSではない。作成日フィルターも当時の配信・訂正履歴を証明しない。','','## 調教接続率','', '|年|評価頭数|坂路14日・有無 接続頭数|ウッド14日・有無 接続頭数|','|---|---:|---:|---:|']
    for c in coverage:
        if 'evaluation_rows' in c:report.append(f"|{c['year']}|{c['evaluation_rows']}|{c['eligible_feature_rows'].get('hanro-14-presence',0)}|{c['eligible_feature_rows'].get('wood-14-presence',0)}|")
    t.save(OUT/'input-result-manifest.json',{'files':{p.relative_to(t.ROOT).as_posix():t.sha(p) for p in sorted(list(t.CACHE.glob('*.gz'))+list(OUT.glob('*-scores.jsonl.gz'))+files+[OUT/'protocol.json',OUT/'baseline-verification.json'])},'production_approved':False})
    (OUT/'report.md').write_text('\n'.join(report)+'\n',encoding='utf-8')
    stamp=datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    start,end='<!-- THREE_TARGET_TRAINING_START -->','<!-- THREE_TARGET_TRAINING_END -->'
    rows=[]
    for r in summary['ranking']:
        rows.append('<tr><td>'+html.escape(r['config']['id'])+'</td>'+''.join(f"<td>{r['delta'][str(k)]['logloss']:+.8f}</td>" for k in (1,2,3))+''.join(f"<td>{r['overall'][str(k)]['top_pick_observed_rate']:.2%}</td>" for k in (1,2,3))+'<td>'+r['experiment_decision']+'</td></tr>')
    base_rows=''.join(f"<tr><td>{k}着以内</td><td>{baseline['overall'][k]['races']:,}</td><td>{baseline['overall'][k]['logloss']:.8f}</td><td>{baseline['overall'][k]['brier']:.8f}</td><td>{baseline['overall'][k]['top_pick_observed_rate']:.2%}</td></tr>" for k in ('1','2','3'))
    section=start+'<section style="max-width:1100px;margin:24px auto;padding:20px;background:white;color:#17253a;border-radius:12px"><h2>3目標評価・調教48候補</h2><p>48/48候補完了。基準：jockey-25。研究用・本番未採用。</p><p>2着以内・3着以内は勝率スコアから順位モデルで推定。独立した目標別学習ではありません。同着は目標の境界ごとに採点対象を確認します。</p><table><thead><tr><th>基準の目標</th><th>レース</th><th>Logloss</th><th>Brier</th><th>最上位馬の実測率</th></tr></thead><tbody>'+base_rows+'</tbody></table><p>調教日・作成日ともレース前。欠損は中立。2016〜2022年にはこの条件を満たす調教記録がなく、この期間は調教追加の効果を測れていません。</p><p>研究候補：'+html.escape(', '.join(selection['retained_research_candidates']) or 'なし。jockey-25を維持')+'。144比較のLoglossを28暦日ブロック・Holm補正で確認。Brierの統計的優位性・校正・収益性は未検証。</p><details><summary>48候補と最上位馬の1着・2着以内・3着以内実測率</summary><div style="overflow:auto"><table><thead><tr><th>候補</th><th>1着Logloss差</th><th>2着以内差</th><th>3着以内差</th><th>1着実測率</th><th>2着以内実測率</th><th>3着以内実測率</th><th>研究判断</th></tr></thead><tbody>'+''.join(rows)+'</tbody></table></div></details><p>既に検討した2016〜2025年の遡及研究。ソース作成日も当時の配信・訂正履歴を証明しません。本番判断：REJECT。</p></section>'+end
    page=t.ROOT/'web/index.html';text=page.read_text(encoding='utf-8-sig')
    if start in text:
        if text.count(start)!=1 or text.count(end)!=1:raise ValueError('Duplicate UI section')
        updated=text[:text.index(start)]+section+text[text.index(end)+len(end):]
    else:
        closing='</body>' if '</body>' in text.lower() else '</html>'
        if text.lower().count(closing)!=1:raise ValueError('Expected one page closing tag')
        offset=text.lower().index(closing);updated=text[:offset]+section+text[offset:]
    backup(page,stamp);page.write_text(updated,encoding='utf-8')
    checkpoint=t.ROOT/'src/checkpoint.py';text=checkpoint.read_text(encoding='utf-8-sig')
    if '"artifacts/three-targets-training-v1"' not in text:
        anchor='    selected = ['
        if text.count(anchor)!=1:raise ValueError('Checkpoint anchor mismatch')
        updated=text.replace(anchor,anchor+'\n        "artifacts/three-targets-training-v1",\n        "datasets/training-pre-race-v1",\n        "Run-Training-Experiments.cmd",',1)
        ast.parse(updated);backup(checkpoint,stamp);checkpoint.write_text(updated,encoding='utf-8')
    handover=t.ROOT/'HANDOVER.md';text=handover.read_text(encoding='utf-8-sig');mark='## 3目標評価と調教48候補'
    note='\n\n'+mark+'\n- 更新：'+datetime.now().astimezone().isoformat()+'\n- PowerShellファイル書込・読戻し、DB接続のtransaction_read_only=onを実測確認。\n- 起動：Run-Training-Experiments.cmd。48/48候補完了。\n- 基準：jockey-25。10年の保存済み勝率評価に一致。\n- 3目標：1着・2着以内・3着以内。順位モデルの周辺確率で、独立した目標別学習ではない。\n- 調教48候補：坂路／ウッド／併用 × 7／14日 × 有無／回数／4F／終い1F × 10／25%。\n- 調教日と作成日がともにレース前。同日結果は全予測後に更新。欠損は中立。\n- 2016〜2022年の利用可能調教は0件。調教効果の確認は後年の接続対象に限定。\n- 調教補正履歴は2016年から、直近1095日。\n- 144件のLogloss比較に28暦日ブロックとHolm補正。Brierの統計的優位性は未検証。\n- 研究候補：'+(', '.join(selection['retained_research_candidates']) or 'なし。jockey-25を維持')+'。本番判断：REJECT。\n- 保存：artifacts/three-targets-training-v1/report.md、summary.json、selection-check.json、workout-coverage.json。\n- バックアップ対象追加済み。この48候補の復元再計算は未検証。\n- 既存DBの変更・サービス停止・フォルダー移動は実施していない。\n'
    if mark not in text:backup(handover,stamp);handover.write_text(text+note,encoding='utf-8')
    delivered=False
    try:
        with urlopen('http://127.0.0.1:8792/',timeout=10) as response:delivered=start.encode() in response.read()
    except OSError:pass
    t.save(OUT/'completion.json',{'completed_candidates':48,'targets':3,'frozen_jockey_metrics_matched':True,'regression_checks_passed':t.load(OUT/'regression-checks.json')['passed'],'http_page_delivered':delivered,'visual_user_confirmation':False,'selection_adjusted_logloss_comparisons':144,'production_decision':'REJECT','retained_research_candidates':selection['retained_research_candidates'],'db_write_performed':False,'service_stop_performed':False,'folder_move_performed':False})
    print(json.dumps({'baseline':baseline['overall'],'retained':selection['retained_research_candidates'],'http_page_delivered':delivered},ensure_ascii=False,indent=2))
def verify_inputs():
    path=OUT/'input-result-manifest.json'
    if not path.exists():
        print('First run: no frozen manifest yet');return
    for name,expected in t.load(path)['files'].items():
        if t.sha(t.ROOT/name)!=expected:raise ValueError('Frozen input or result changed: '+name)
    print('Frozen input/result manifest verified')

if __name__=='__main__':
    import sys
    if '--verify-inputs' in sys.argv:verify_inputs()
    else:main()
