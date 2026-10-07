"""Expose verified diagnostic results in existing UI and native answer sources."""
import ast, html, inspect, json
from datetime import datetime
from urllib.request import urlopen
import training_three_targets as t
import diagnose_training_oos_2026 as diagnostic
OUT=diagnostic.OUT

def main():
    d=t.load(OUT/'diagnosis.json');v=t.load(OUT/'verification.json');parent=t.load(diagnostic.LOCKED/'result.json')
    if not all(v[k] for k in ('parent_artifact_hashes_unchanged','parent_metric_reproduced','pick_hit_totals_reconciled','additive_error_contributions_reconciled')):raise ValueError('Diagnostic checks incomplete')
    pick_rows=[];calibration_rows=[];contribution_rows=[]
    for k in ('1','2','3'):
        s=d['targets'][k];ci=d['pick_rate_intervals'][k]['block_bootstrap_95_percent']
        pick_rows.append({'target':k+'着以内','races':s['races'],'swaps':s['swaps'],'new_hits':s['gains'],'lost_hits':s['losses'],'net_hits':s['net_hits'],'ci_low_pp':100*ci[0],'ci_high_pp':100*ci[1]})
        calibration_rows.append({'target':k+'着以内','baseline_ece10_pp':100*d['calibration'][k]['baseline']['all_runners_10']['ece'],'candidate_ece10_pp':100*d['calibration'][k]['candidate']['all_runners_10']['ece'],'baseline_ece20_pp':100*d['calibration'][k]['baseline']['all_runners_20']['ece'],'candidate_ece20_pp':100*d['calibration'][k]['candidate']['all_runners_20']['ece']})
        a=d['contributions'][k]['same_pick'];b=d['contributions'][k]['swapped_pick']
        share=a['logloss_delta_sum']/(a['logloss_delta_sum']+b['logloss_delta_sum'])
        contribution_rows.append({'target':k+'着以内','same_pick_races':a['races'],'changed_pick_races':b['races'],'same_pick_logloss_improvement_share_percent':100*share,'same_pick_logloss_delta_sum':a['logloss_delta_sum'],'changed_pick_logloss_delta_sum':b['logloss_delta_sum']})
    receipt={'schemaVersion':1,'items':[
        {'id':'pick-swaps','title':'首位の入替と的中件数の差','queries':[{'id':'pick-swap-accounting','source':{'label':'固定候補の2026年診断','files':[{'label':'diagnosis.json'},{'label':'top-pick-swaps.csv'},{'label':'verification.json'}],'metricDefinitions':[{'label':'的中件数の差','definition':'同じ対象レースで候補の予測首位が目標着順に入った件数から、jockey-25の予測首位の的中件数を引く。'},{'label':'首位入替','definition':'勝率の予測首位の馬IDが基準と候補で異なるレース。'}],'filters':['中央10場の保存済み2026年評価対象','1着同着を元の評価方針で除外','各目標で陽性頭数が規定値と一致しないレースを除外'],'caveats':['入替件数は的中率差の算術的な分解であり、調教の因果的効果を証明しない。','28暦日ブロックの的中率差推定幅は全3目標でゼロを含む。'],'evidenceFlow':[{'kind':'validation','title':'元の評価との照合','detail':'3目標の的中件数差と実測率を保存済み2026年評価に照合し、一致した。'},{'kind':'validation','title':'固定成果物','detail':'診断前後で固定評価の全成果物のハッシュが一致した。'}]},'reportingPeriod':'2026-01-04〜2026-10-04（途中年の収録評価）','rows':pick_rows,'columns':[{'field':'target','label':'目標'},{'field':'races','label':'レース数'},{'field':'swaps','label':'首位入替'},{'field':'new_hits','label':'新たな的中'},{'field':'lost_hits','label':'失った的中'},{'field':'net_hits','label':'差し引き'},{'field':'ci_low_pp','label':'的中率差95%幅 下限（ポイント）'},{'field':'ci_high_pp','label':'同 上限（ポイント）'}],'preview':{'kind':'aggregate','note':'全評価対象の目標別集計。個別の首位入替一覧は435レース。','totalRows':435},'methods':[{'language':'calculation','code':'1着: 56 - 64 = -8\n2着以内: 91 - 86 = +5\n3着以内: 105 - 107 = -2'}]}]},
        {'id':'calibration','title':'全出走馬の確率校正誤差','queries':[{'id':'calibration-bins','source':{'label':'固定候補の校正診断','files':[{'label':'diagnosis.json'},{'label':'runner-probabilities.jsonl.gz'}],'metricDefinitions':[{'label':'ECE','definition':'予測確率を等幅区間に分け、区間内の平均確率と実測陽性率の差の絶対値を頭数で加重平均した校正誤差。小さいほどよい。'}],'filters':['中央10場の保存済み評価対象の全出走馬','各目標で陽性頭数が規定値と一致しないレースを除外'],'caveats':['ECEは区間分けと標本数に依存する記述統計。差の統計的な有意性は未検証。','10区間・20区間とも全出走馬のECEは3目標で増加した。予測首位だけのECEは3目標とも低下した。','全出走馬の平均確率が陽性率と一致するのはレース内確率合計の構造による。校正がよい証明ではない。','この診断では確率校正の学習や調整を行っていない。']},'reportingPeriod':'2026-01-04〜2026-10-04（途中年の収録評価）','rows':calibration_rows,'columns':[{'field':'target','label':'目標'},{'field':'baseline_ece10_pp','label':'基準ECE・10区間（ポイント）'},{'field':'candidate_ece10_pp','label':'候補ECE・10区間（ポイント）'},{'field':'baseline_ece20_pp','label':'基準ECE・20区間（ポイント）'},{'field':'candidate_ece20_pp','label':'候補ECE・20区間（ポイント）'}],'methods':[{'language':'python','code':inspect.getsource(diagnostic.bin_stats)}]}]},
        {'id':'error-contribution','title':'Logloss改善と首位が同じレースの寄与','queries':[{'id':'error-accounting','source':{'label':'誤差改善の分解','files':[{'label':'diagnosis.json'},{'label':'runner-probabilities.jsonl.gz'}],'metricDefinitions':[{'label':'首位不変の寄与率','definition':'首位が同じレースでの候補と基準のLogloss合計差を、全評価対象での合計差で割った比率。'}],'filters':['中央10場の保存済み2026年評価対象','首位が同じレースと異なるレースの重複しない2群に分割'],'caveats':['首位不変群の寄与率は算術的な分解であり、改善の因果的な仕組みを証明しない。','順位の精度と全馬の確率配分の誤差は別の指標である。'],'evidenceFlow':[{'kind':'validation','title':'合計の一致','detail':'2群のLogloss・Brier合計差を合算し、全評価対象の保存済み差と一致した。'}]},'reportingPeriod':'2026-01-04〜2026-10-04（途中年の収録評価）','rows':contribution_rows,'columns':[{'field':'target','label':'目標'},{'field':'same_pick_races','label':'首位不変レース'},{'field':'changed_pick_races','label':'首位入替レース'},{'field':'same_pick_logloss_improvement_share_percent','label':'首位不変群のLogloss改善寄与（%）'}],'methods':[{'language':'python','code':inspect.getsource(diagnostic.loss)}]}]}
    ]}
    t.save(OUT/'answer-sources.json',receipt)
    section_rows=''.join(f"<tr><td>{r['target']}</td><td>{r['swaps']}</td><td>{r['new_hits']}</td><td>{r['lost_hits']}</td><td>{r['net_hits']:+d}</td></tr>" for r in pick_rows)
    ece_rows=''.join(f"<tr><td>{r['target']}</td><td>{r['baseline_ece10_pp']:.3f}</td><td>{r['candidate_ece10_pp']:.3f}</td></tr>" for r in calibration_rows)
    start,end='<!-- TRAINING_DIAGNOSTICS_2026_START -->','<!-- TRAINING_DIAGNOSTICS_2026_END -->'
    section=start+'<section style="max-width:1100px;margin:24px auto;padding:20px;background:white;color:#17253a;border-radius:12px"><h2>NEO JIZO ATLAS｜2026年診断：的中率と確率誤差の違い</h2><p>固定した調教候補の首位入替は435レース。勝ち馬を新たに選べた56件に対し、選べなくなった64件で差し引き8件減少。3着以内は2件減少。</p><table><thead><tr><th>目標</th><th>首位入替</th><th>新たな的中</th><th>失った的中</th><th>差し引き</th></tr></thead><tbody>'+section_rows+'</tbody></table><p>28暦日ブロックの的中率差95%推定幅は3目標ともゼロを含み、継続的な悪化とは断定できません。</p><h3>全出走馬の校正誤差（10区間・ポイント）</h3><table><thead><tr><th>目標</th><th>jockey-25</th><th>調教追加</th></tr></thead><tbody>'+ece_rows+'</tbody></table><p>20区間でも全出走馬の校正誤差は3目標とも増加。予測首位だけの校正誤差は低下しています。区間分けに依存する診断値で、統計的有意性や校正の完成を示しません。</p><p>1着Logloss改善の'+f"{contribution_rows[0]['same_pick_logloss_improvement_share_percent']:.1f}"+'%は首位が同じレースから来ています。確率配分の改善と的中率改善は分けて判断します。</p><p>既に評価した2026年の事後診断。候補の再選抜・校正学習は実施していません。研究KEEP・本番REJECT、jockey-25を維持。</p></section>'+end
    stamp=datetime.now().strftime('%Y%m%d-%H%M%S-%f');page=t.ROOT/'web/index.html';text=page.read_text(encoding='utf-8-sig')
    if start in text:
        if text.count(start)!=1 or text.count(end)!=1:raise ValueError('Diagnostic section duplicated')
        updated=text[:text.index(start)]+section+text[text.index(end)+len(end):]
    else:
        if text.lower().count('</html>')!=1:raise ValueError('Closing html mismatch')
        i=text.lower().index('</html>');updated=text[:i]+section+text[i:]
    if updated!=text:
        page.with_name(page.name+'.before-diagnostics-'+stamp+'.bak').write_bytes(page.read_bytes());page.write_text(updated,encoding='utf-8')
    checkpoint=t.ROOT/'src/checkpoint.py';text=checkpoint.read_text(encoding='utf-8-sig')
    if '"artifacts/oos-2026-training-diagnostics-v1"' not in text:
        anchor='    selected = ['
        if text.count(anchor)!=1:raise ValueError('Checkpoint anchor mismatch')
        updated=text.replace(anchor,anchor+'\n        "artifacts/oos-2026-training-diagnostics-v1",\n        "Run-Training-Diagnostics-2026.cmd",',1)
        ast.parse(updated);checkpoint.with_name(checkpoint.name+'.before-diagnostics-'+stamp+'.bak').write_bytes(checkpoint.read_bytes());checkpoint.write_text(updated,encoding='utf-8')
    delivered=False
    try:
        with urlopen('http://127.0.0.1:8792/',timeout=10) as response:delivered=start.encode() in response.read()
    except OSError:pass
    handover=t.ROOT/'HANDOVER.md';text=handover.read_text(encoding='utf-8-sig');mark='## 固定調教候補の2026年事後診断'
    note='\n\n'+mark+'\n- 更新：'+datetime.now().astimezone().isoformat()+'\n- 首位入替435レース。1着の新たな的中56・失った的中64、差し引き8件減少。\n- 2着以内は5件増加、3着以内は2件減少。的中率差の28日ブロック推定幅は全3目標でゼロを含む。\n- 全出走馬のECEは10・20区間とも3目標で増加。予測首位のみのECEは低下。\n- 1着Logloss改善の'+f"{contribution_rows[0]['same_pick_logloss_improvement_share_percent']:.1f}"+'%は首位不変レースから。算術的分解であり因果効果の証明ではない。\n- 元の評価値を再現し、診断前後で固定成果物のハッシュ一致。研究KEEP・本番REJECTを維持。\n- 保存：artifacts/oos-2026-training-diagnostics-v1/diagnosis.json、top-pick-swaps.csv、runner-probabilities.jsonl.gz。\n- 起動：Run-Training-Diagnostics-2026.cmd。既存データで固定候補を再計算して診断。\n- 画面HTTP配信確認：'+str(delivered)+'。目視確認は未実施。\n- バックアップ対象追加済み。診断の復元再計算は未検証。\n- 2026を見て候補の再選抜や確率調整を行っていない。次の改善を2026で比較する場合は事後探索として区別し、未使用の将来期間で別検証する。\n'
    if mark not in text:
        handover.with_name(handover.name+'.before-diagnostics-'+stamp+'.bak').write_bytes(handover.read_bytes());handover.write_text(text+note,encoding='utf-8')
    t.save(OUT/'completion.json',{'completed':True,'http_page_delivered':delivered,'visual_confirmation':False,'experiment_decision':'KEEP','production_decision':'REJECT','db_modified':False,'services_stopped':False,'folders_moved':False})
    print(json.dumps({'swaps':435,'pick_hit_differences':[-8,5,-2],'win_logloss_improvement_from_same_pick_percent':contribution_rows[0]['same_pick_logloss_improvement_share_percent'],'http_page_delivered':delivered},ensure_ascii=False))
if __name__=='__main__':main()
