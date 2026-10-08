# ATLAS-JVLINK-002 — JRAの差分取得を、原本のまま安全にATLASへ

2026-10-08。**GitHubでの合成COM試験と、隔離PostgreSQL 18での統合試験が対象**。実ユーザーPCのJV-Link/Data Lab.契約に対する実取得は未実施。

## 実際に組み込むもの

- Windows用JV-Link 5.0.0を`pywin32`経由で利用。実際の公式エントリポイントは`JVDTLab.JVLink`。
- 標準的な通常差分 `JVInit → JVOpen("RACE", fromtime, 1, ...) → JVGets → JVClose` を実装する。
- JVOpenの最終ファイル時刻`lastfiletimestamp`を**読み取り成功後だけ**ローカルの`receipts/jra_jvlink_cursor.json`へ保存し、次回はその時刻から取得。
- JVGetsのバイト列を**完全一致するbase64**として各行の`payload.raw_base64`に格納。取得時点でCP932を不完全にデコードしたり、レース日時・馬ID・着順を推測したりしない。
- 全件の読み取りとJVCloseが成功してから、`work/.part`をローカル`inbox/JRA/*.jsonl`へ**原子的に公開**。全分割公開後には`receipts/jra_jvlink_batches/`へ**完全受信マニフェスト**を書き込み、ATLAS-INBOX側では全分割が揃わない限りどの分割も登録しない。中断・失敗ではカーソルを進めない。
- 同時二重起動は`.jra_jvlink_capture.lock`で拒否。異常終了でロックが残る場合は、停止を確認してから手動検査する（自動解除で重複実行しない）。
- 新規ファイルは前ミッションATLAS-INBOX-001へ渡せる。**この段階のDB登録はJVDATA原本観測であり、正規化されたレース・出走馬・結果テーブルへの昇格ではない。**

## 安全装置

- デフォルトでオンライン取得を**実行しない**。`--capture`か、それを含む明示的なWindows起動ファイルが必要。
- `sources.local.json`の`JRA`で`enabled:true`、承認済みのrights status、根拠識別子、`adapter_type:"JV_LINK"`が必要。**単なる自己申告ラベルは利用許諾の証明ではない。**
- 原本やライセンスキーはGitHubや外部AIサービスに送信しない。
- 読み取り・原本受信にはPostgreSQL権限不要。コミットは別個のATLAS-INBOXが`neo_jizo_atlas` DBに限定する。
- `mykeibadb`、馬王Z、JRA-VANの公式ローカル保存先は変更しない。
- `JVOpen`の`-1`は「今回新規なし」。異常終了は明示的にBLOCKED。なおCOM依存の画面表示・権限エラー等は現物テストが必要。
- ファイル名に原本名や出走馬名を含めず、取得内容のハッシュ・取得開始時刻・分割番号で識別。
- 一度公開済みのファイルを上書きしない。原本・カーソルの削除操作は用意しない。

## Windowsの操作を最小限にする

1. **一度だけ**JV-Link 5.0.0 / 対応64bit Python / `pywin32==312`を確認。SDK内の公式検証ツールでRACE取得が可能か検査。Python 3.14用サンプルは公式提供されている。
2. 新ATLAS DBはPR #61、INBOXの前提設定はPR #63を参照。許諾が確認できるまで`sources.local.json`は無効のまま。JRAの承認設定を入れる際は`adapter_type:"JV_LINK"`を保持。
3. **一度だけ**`tools/ATLAS-JRA-CAPTURE.cmd`をダブルクリック。初回はJV-Linkの14桁`fromtime`を指定。これが通常差分の取得起点となる。過去全期間が取得できるという意味ではない。
4. 次回以降は`tools/ATLAS-JRA-CAPTURE.cmd`をダブルクリックするだけ。初回のカーソルは保存されるため、日時の再入力は不要。
5. 常駐させる場合は`tools/ATLAS-JRA-WATCH.cmd`を起動しておく。標準60分ごとに確認する。**Windowsにサービスやタスクを無断登録しない。** ログアウト・シャットダウン中は実行されない。OS起動時の安全なタスク登録は次段階。
6. 受信済み`inbox/JRA/*.jsonl`はPR #63のINBOX検査/承認済み書込処理へ。双方とも完了した後、次期の公式JV-Data構造体アダプターでRA/SE/血統/調教等の項目をマッピングする。

> 「簡単に取り込める」とは**一度設定すれば取り込み手順を繰り返さなくてよい**こと。このPRでJRA差分**原本受信の自動監視コード**が完成しても、公式SDK実機検証、NAR、JV-Data正規化、Windows自動起動、全履歴バックフィルはまだ完了していない。

### 現状と次の品質ゲート

| ゲート | 状態 |
|---|---|
| 公式COMインターフェースと通常差分取得の実装 | 本PR |
| Windows/Linuxの合成COMケース | CI |
| 受信バイナリのSHA・byte-for-byte確認 | CI |
| 異常・通信停止後の再試行・カーソル進行拒否 | CI |
| PostgreSQL 18の隔離DBへのJVDATA原本行取り込み | CI |
| 利用者PC上の**実際のJV-Link 5.0.0**動作 | **未検証** |
| RA/SE/調教/血統/結果等の正規項目への変換 | **未実装** |
| NAR UmaConn公式取得 | **未実装** |
| 15年分歴史全量バックフィル | **未実装** |
| OSサービス化・ログアウト中も動作 | **未実装** |

## 注意：データ取得モード

本PRは`option=1`通常差分だけを明示実装し、古い全履歴取得（`option=3/4`セットアップ）は未実装。通常差分の開始時刻を昔にしても15年分を遡れる保証はない。データ提供時刻・契約・ローカル蓄積状況に依存する。

公式仕様確認先：
- JRA-VAN SDK 5.0.0: https://developer.jra-van.jp/t/topic/45
- Python 3.14 COM/JVGets: https://developer.jra-van.jp/t/topic/949
- JVOpenセットアップとの区別: https://developer.jra-van.jp/t/topic/604
- pywin32 312: https://pypi.org/project/pywin32/312/

## 次にやること

**ATLAS-JVDATA-MAP-003**：SDK構造体の実フィールド位置・コード変換表に従い、原本JVDATA → RA/SE/馬・レース・結果・調教の検証済み構造へ変換。未来情報混入防止、出典、同一馬キーを同時に確定する。

**ATLAS-NAR-CONNECT-003**：UmaConnの公式提供手段・利用権利・エンコード・構造を調査し、同じ原本受信と品質契約へ接続。

**ATLAS-UNATTENDED-004**：実機テスト後にWindowsタスク登録とINBOX自動処理を1クリックでセットアップ。ジョブ重複・停電再開・容量上限・サービスヘルスを検証する。
