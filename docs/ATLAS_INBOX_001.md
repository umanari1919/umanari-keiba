# ATLAS-INBOX-001：ファイルを置くだけの安全なデータ取り込み口

2026-10-08／状態：コード＋使い捨てDBでの合成検証。PC上の実JRA/NAR連携は**未接続**。

## 目的と約束

JRA-VAN、NAR等の許諾済み取得アダプターが出力した規定形式のファイルを、手でSQLやPowerShellを毎回書かずに検査し、新しい独立DBへ投入する。既存の `mykeibadb`、原本、馬王ZのDBは絶対に変更しない。

**重要：このPRの仕組みはJV-Link/UmaConnから直接データをダウンロードするアダプターではない。** JV-Linkのバイナリレコード、既製DBの任意CSV、馬王Z独自MDBはそのまま受け付けない。正式な項目対応と取得権利確認を行った「正規化済みJSONL」のみ受け付ける。

### 1回だけの初期設定（Windows）

1. PR #61（専用DB初期構造）を安全審査して取り込み、**新規空DB `neo_jizo_atlas` のみに**マイグレーションを適用する。既存DBには適用しない。
2. このPRのコードをローカルへ同期して `tools/ATLAS-INBOX-SETUP.cmd` をダブルクリックする。初期フォルダーは `ドキュメント/NEO-JIZO-ATLAS-DATA`。
3. `sources.local.json` のJRA/NARそれぞれについて、実際の利用許諾とアダプターを**人間が確認した後だけ** `enabled:true`, `rights_status:"APPROVED_INTERNAL"` などを設定し、8文字以上の根拠識別子を `authorization_reference` に記録する。**許諾済みでない間は変更しない**。
4. 新DBへの接続情報をOSのローカル環境変数 `ATLAS_PG_DSN` に安全に設定する（GitHubやチャットにパスワードを掲載しない）。`python tools/atlas_inbox.py --enroll` を**最初の登録時だけ**実行し、許諾承認済みの供給元を登録する。
5. 日常的には `tools/ATLAS-INBOX-START.cmd` を起動。既定は**検査専用**。確実に新DB・権利・アダプターを確認した運用だけ、ローカル環境変数 `ATLAS_INBOX_COMMIT=1` を設定し、ダブルクリックで`--watch --commit`となる。

まだ完全無人ではない。OSログイン時の自動起動・JRA/NAR取得アダプター・インストーラーは後続ミッションで実装し、ここでは誤接続・無断登録を優先的に防ぐ。

### 日常運用

```text
ドキュメント/NEO-JIZO-ATLAS-DATA/
  sources.local.json        ← 非公開・一度設定・初期は全ソース無効
  inbox/
    JRA/                    ← 承認済みアダプター出力だけ置く
    NAR/
  objects/<sha-prefix>/     ← 同一SHAごとに原本の固定コピーを1回保管
  receipts/latest.json      ← 日本語表示と機械可読な集計・隔離理由
```

アダプターが新しい正規化済みJSONLファイルを置いたら、監視が約60秒ごとにチェックする。作成/更新直後2秒以内のファイルは触れず、書き込み途中の読み込みを避ける。原本を移動・削除せず、新しいSHA-256のファイルだけを処理する。

- 合格：新DBの`atlas.import_object`, `atlas.raw_observation`, `atlas.ingest_decision`に**同一トランザクション**で登録。
- 再取得：出典とSHA-256の一致で**重複**と判定し、同じ原本を再登録しない。
- 異常：そのファイル全体を**保留**。 `receipts/latest.json`に件数・匿名のSHAと理由コードを出力し、ファイルは触らない。
- 一時停止後：同じ監視を開始すれば、未登録のファイルを再走査できる。
- 原本内容や機密パスワードをGitHub・端末ログ・AIサービスへ自動送信しない。
- **Canonical Parquetへの昇格・馬ID確定・レース内容の正当性判定は行わない**。それは別の品質ゲートで実施する。

### アダプター標準形式（合成サンプル）

UTF-8の1行1オブジェクト。公式JV-DataのRAWレコードそのものではなく、項目対応が完成したアダプターの中間形式。

```json
{"native_kind":"RACE","native_key":"FAKE-JRA-20261010-01","payload":{"synthetic":true,"race_date":"2026-10-10"},"provider_published_at":null,"event_time":"2026-10-10T10:00:00+09:00"}
{"native_kind":"RUNNER","native_key":"FAKE-JRA-20261010-01:FAKE-H-1","payload":{"synthetic":true,"horse_no":1},"provider_published_at":null,"event_time":"2026-10-10T10:00:00+09:00"}
```

実ファイルは最大50MiB・10万行・1行256KiB。大量調教データは安易に全件JSONB化しないで、将来の分割Parquet/参照ロケータ専用アダプターを使う。単一ファイルで上限を超えた場合は失敗を記録し、黙って一部だけ取り込まない。

### セキュリティ境界

- **既定は検査のみ。** `--commit`がない限りDBへ接続せず、原本コピーもしない。
- 接続先DB名が`neo_jizo_atlas`以外なら**必ず拒否**。 `mykeibadb`にはSQLを書かない。
- 供給元はローカル権利設定・DB登録・DB権利状態の**すべて**が有効でなければ取り込めない。
- 公式配信が未承認なら`sources.local.json`は既定の`UNVERIFIED`を維持する。承認ラベルは法的許諾の自動判定ではない。
- 取得ファイルとDBはローカルに保持。GitHub Actionsには合成レコードのみ。
- アプリ起動の二重実行防止、OS登録の自動起動、停電後の復旧検査、ファイル原本の長期保管規約・容量制御は今後の運用ゲート。
- ソースが完全に書き込み終わった保証には、上記2秒の時間差だけでは不十分。公式アダプター側で`.tmp`から`.jsonl`へアトミックにリネームして提供する契約が必要。

### 合格基準

1. Linux/Windows、Python 3.13/3.14で検査動作と拒否動作を合成検証。
2. GitHub Actionsの隔離PostgreSQL 18で実スキーマを作成し、**新規→同一ファイル再取り込み→権利取消後の新規ファイル拒否**を確認。
3. 入力ファイルが変更・欠損・二重・破損したら無条件に拒否。
4. `mykeibadb`や競馬の実データにアクセスするテストは禁止。

## 次の接続フェーズ

**INGEST-002:** JRA-VANの公式64bit JV-Link Ver5.0.0 SDK（JVInit→JVOpen→JVRead→JVClose）対応アダプターと取得時刻証拠。WindowsデスクトップのJV-Link上に閉じて動かす。Python 3.14例の動作は実機で確認。 <https://developer.jra-van.jp/t/topic/45>

**INGEST-003:** 地方競馬DATA / UmaConnの利用条件と公式API/提供形式を調査し、同じ契約へ接続。

**INGEST-004:** 大容量調教・血統・過去レースの初回バックフィル。既存`mykeibadb`はread-onlyの照合元とし、件数・時点証拠・権利・重複・欠損を別途検証。

**INGEST-005:** Windows自動起動、ヘルスチェック、リトライ/ロック、原本容量制御とダッシュボード、完全な取得→DB→Canonical→FORWARDの定期運用。
