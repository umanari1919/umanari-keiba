# NEO JIZO FORWARD — BLIND-001

日付：2026-10-08  
状態：実装提案・Draft PR（現物レースの実証は未実施）

## 目的

既存jockey-25週末予測の時系列証拠を強化し、結果が揃わない場合には成績を偽造せず隔離する。研究側ATLASのCORE-010評価や調教候補の本番昇格と独立させる。

## 既存コードの再利用

現行の `src/weekend_personal_forecast.py` は生成時刻、入力読取専用証跡、発走前チェック、保存済みモデル/履歴/入力ハッシュ、内容アドレス型runを既に持つ。これらの**保存済みローカルファイル**を検証してから、`src/forward_blind.py` で別個のローカル凍結受領書を作る。

- `artifacts/jwk-weekend-personal-v1/runs/<SHA256>.json` を読み、ファイル名と内容のSHA256一致を確認。
- `assets/source-<SHA256>.json` の内容SHA256を照合し、予測前入力だけを許可。
- 馬ID・馬番・頭数・出走可否・レース発走時刻・3目標確率の順序と合計・読取専用フラグを再検査。
- 実際の予測作成時刻から短時間で、全対象レースの発走時刻より前でなければ凍結しない。過去の保存済みレースを後から「発走前」として登録することを拒否。
- 各runごとに `artifacts/neo-jizo-forward-blind-v1/receipts/<runSHA256>.json` を `xb`（新規作成のみ）で保存。同一の受領書は上書きしない。
- 保存済みrunの凍結に失敗した場合、新しい `latest.json` を公開しない。
- 予測が0件なら受領書は作らない。架空の未来予想を作らない。

## 得点照合（受領書と別工程）

`python src/forward_blind.py score --receipt <receipt.json> --results <local-results.json>`

結果入力は次の仕様。実データの取得プログラムは今回実装しない。

~~~json
{
  "observed_at": "2026-10-10T11:00:00+09:00",
  "read_only_connection": {"transaction_read_only": "on", "default_transaction_read_only": "on"},
  "source": "verified-readonly-result-extract",
  "rows": [
    {"race_id": "2026101005010101", "horse_id": "2020000001", "finish_position": 1, "result_status": "FINISHED"}
  ]
}
~~~

- 結果取得時刻は凍結より後、採点可能なレースは発走より後。
- 馬ID・レースID重複を拒否し、事前凍結出走馬と結果出走馬を厳密に照合。
- 未到着・欠損・不正ラベル・同着・不完全な上位3着を **QUARANTINED** 扱い。0着・ハズレに捏造しない。
- `DID_NOT_FINISH` は明示された場合だけ識別可能だが、上位着順の整合性が取れないレースは隔離。
- 採点可能レースは1着、2着以内、3着以内それぞれ Brier・平均予測・実測率・校正誤差・予測首位の的中率を集計。年とJRA/NARの区分も集計。
- 結果行そのものをスコアJSONに再保存しない。元データはローカル限定。
- 出力は `artifacts/neo-jizo-forward-blind-v1/scores` に結果ファイルSHA256別・書換禁止で保存。

## ステータス・信頼限界（重要）

**LOCAL_PRESTART_SEALED_UNATTESTED** は「ローカル時計で発走前・内容ハッシュ確認済み」を示すが、第三者に独立した時刻証明ではない。

**SCORED_LOCAL_ONLY** は「ローカル凍結に紐づき採点できた」を示すが、`PROSPECTIVE_VERIFIED` ではない。OS時計変更・凍結コード改変・ファイルを後から作成する行為に対する独立証明はなく、公式の確定出馬表網羅性や権利も未確認である。独立した事前時刻証明が別途導入されるまでは研究の本番昇格を認めない。

## 安全・非実施

- DBの起動・復旧・書込・DDLはしない。
- レース結果の自動取得、当日の公式出馬表完全性保証は未実装。
- 馬王Zの私的ソースと学習モデルは変更しない。
- このPRのsynthetic testとCI合格は、2026-10-10〜12の実予想・第三者時刻証明・利益の実証を意味しない。
- 対象は既存のJRA個人向けjockey-25。NARの実出馬表取得は別工程。
- 公開GitHubへ実競馬の馬単位データ、DBファイル、馬王Zデータは載せない。

関連：表示分離 PR #57、名称体系 PR #55、CORE-010／独立ベンチマーク PR #54。
