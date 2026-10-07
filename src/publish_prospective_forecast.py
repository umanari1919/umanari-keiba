"""Publish verified historical assembly and bounded future forecast status."""
import re
import gzip
import json
from urllib.request import urlopen
import prospective_capture as p
import prospective_forecast as f
import build_prospective_history as h


def main():
    result = p.read(f.OUT / 'status.json')
    verification = p.read(h.OUT / 'verification.json')
    expected_history = verification['state_sha256']
    last_day = verification['last_result_day']
    refresh = p.ROOT / 'artifacts/prospective-history-refresh-v1/latest.json'
    if refresh.exists():
        receipt = p.read(refresh)
        expected_history = receipt['state_sha256']
        with gzip.open(p.ROOT / receipt['state_path'], 'rt', encoding='utf-8') as handle:
            last_day = json.load(handle)['last_result_day']
    if result['capture_sha256'] != p.verify()[-1]['sha256'] or result['history_sha256'] != expected_history:
        raise ValueError('Forecast status is stale')
    if not verification['history_roundtrip_verified'] or not verification['future_scoring_api_reproduced_2026']:
        raise ValueError('History/API verification required')
    if p.digest((p.ROOT / 'src/prospective_forecast.py').read_bytes()) != result['forecaster_sha256']:
        raise ValueError('Forecast implementation changed')
    states = {'awaiting_source_data': 'レース前データ待ち', 'awaiting_history_update': '履歴更新待ち',
              'research_predictions_saved': '研究予測保存済み', 'input_checks_blocked': '入力不足等で停止'}
    state = states[result['state']]
    note = f'''## 将来予測の履歴組立て・計算接続

履歴の組立てと将来レースの研究予測計算を実装しました。現在の状態は「{state}」で、実際の将来予測は{result['predicted_races']}レース・{result['predicted_runners']}記録です。

- 2011年から履歴を構築し、2016〜2025年のjockey-25勝率スコア479,100記録が完全一致。
- 2026年36,511記録の騎手基準・調教追加の1着／2着以内／3着以内確率が一致。将来用の計算関数でも全記録を照合。
- ウッド14日・終い1F・25%の過去3目標集計を再現。校正指数は固定2.3。
- 同日の結果は全レースの予測後に履歴へ入れる。1着同着は基準履歴には反映し、既定の採点・調教補正学習からは除外。
- 履歴をJSONで保存し、読戻し・イベント合計・1095日窓を確認。危険なオブジェクト復元形式は使わない。
- 履歴のDB確認範囲は{result['history_snapshot_through']}まで、最終の履歴結果日は{last_day}。確認日の前日まで履歴を取得していなければ将来予測は停止。
- 最新のレース前記録で入力条件を満たしたレースだけを計算。当日・過去のレースや不足・不整合の入力は計算しない。
- 実際に予測できた場合は、取得記録・モデル・履歴・計算コードのハッシュと予測を追記保存。履歴と計算コードの実体も内容別に保持。
- 手動起動：Build-History.cmd（履歴を再構築）、Forecast-PreRace.cmd（既存の履歴・保存データで計算）。Capture-PreRace.cmdは取得後に入力確認と研究予測を実行。
- 現在は実データが0件なので将来予測は0件。合成テストの結果を実際の予測として保存していない。
- 結果取得・出走馬の変更確認・記述的採点はCollect-Results.cmdの別工程。履歴更新はRefresh-History.cmd。将来検証の最終判定、収益性評価、定期実行は未実装・未実施。
- 公式出馬表の網羅性と過去の配信可能性は未証明。研究用・本番REJECTを維持。
- 元の研究入力・成果物は不変。DB接続なしで計算し、DB変更・サービス停止・フォルダー移動は行っていない。
'''
    (f.OUT / 'report.md').write_text(note, encoding='utf-8')
    handover = p.ROOT / 'HANDOVER.md'
    marker = note.splitlines()[0]
    text = handover.read_text(encoding='utf-8-sig')
    text = re.sub(re.escape(marker) + r'.*?(?=\n## |\Z)', note.rstrip(), text, flags=re.S) if marker in text else text + '\n\n' + note
    handover.write_text(text, encoding='utf-8')
    start, end = '<!-- PROSPECTIVE_FORECAST_START -->', '<!-- PROSPECTIVE_FORECAST_END -->'
    section = start + f'<section id="prospective-forecast" style="max-width:1100px;margin:24px auto;padding:20px;background:white;color:#17253a;border-radius:12px"><h2>将来レースの研究予測：{state}</h2><p>履歴組立てと計算を接続しました。過去479,100記録の騎手基準スコアと、2026年36,511記録の3目標確率を再現。保存した履歴の読戻しも確認済みです。</p><p>現在の将来予測：{result["predicted_races"]}レース・{result["predicted_runners"]}記録。履歴のDB確認範囲は{result["history_snapshot_through"]}まで。入力不足や古い履歴では計算を止めます。</p><p>研究用・本番REJECT。結果取得と履歴更新はそれぞれ別工程。将来検証の最終判定、収益性評価は未完了。定期実行は登録していません。</p></section>' + end
    page = p.ROOT / 'web/index.html'
    html = page.read_text(encoding='utf-8')
    html = re.sub(re.escape(start) + r'.*?' + re.escape(end), section, html, flags=re.S) if start in html else html.replace('</html>', section + '</html>')
    page.write_text(html, encoding='utf-8')
    with urlopen('http://127.0.0.1:8792/', timeout=10) as response:
        if section.encode('utf-8') not in response.read(): raise ValueError('Forecast page not delivered')
    checkpoint = p.ROOT / 'src/checkpoint.py'
    code = checkpoint.read_text(encoding='utf-8')
    if '"artifacts/prospective-history-v1"' not in code:
        code = code.replace('    selected = [', '    selected = [\n        "artifacts/prospective-history-v1",\n        "artifacts/prospective-forecast-v1",\n        "Build-History.cmd",\n        "Forecast-PreRace.cmd",', 1)
        checkpoint.write_text(code, encoding='utf-8')
    (f.OUT / 'completion.json').write_bytes(p.encoded({'completed': True, 'http_page_delivered': True,
        'visual_confirmation': False, 'historical_strengths_exact': 479100, 'reference_2026_rows_verified': 36511,
        'future_prediction_races': result['predicted_races'], 'db_modified': False, 'services_stopped': False, 'folders_moved': False}))
    print(f'History and forecast status published: {state}')


if __name__ == '__main__':
    main()
