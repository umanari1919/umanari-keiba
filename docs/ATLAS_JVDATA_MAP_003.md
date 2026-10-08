# ATLAS-JVDATA-MAP-003 — JRA固定長JV-Dataを独立DBのレース・馬・結果へ

状態：**GitHub実装・合成テスト**。Windows実機JV-Link、JRA/NARの本物の原本に対する検証は未実施。PR #61（DB）→ #63（INBOX）→ #64（JV-Link原本取得）から継承。

## 何ができるようになるか

`JVDATA`として保存されたJRA-VANの生レコードを、公式JV-Data Ver.4.9.0.1（2024/8/7）の**バイト位置**で切り出す。レコード種別RA（レース詳細、1272バイト）とSE（馬毎レース情報、555バイト）のうち、データ区分`2`（確定出馬表）・`7`（月曜成績）だけを変換する。他の速報状態`3〜6`は**確定結果として扱わない**。

出力先（新規専用DB`neo_jizo_atlas`の`atlas`スキーマのみ）：

| JV-Data | 原本から解釈する情報 | ATLAS |
|---|---|---|
| RA 2 | 年月日、競馬場、開催回/日、レース番号、距離、発走時刻（JST） | `race`・`race_identifier`・`race_observation(CONFIRMED_CARD)` |
| SE 2 | 同じレースキー、血統登録番号10桁、馬番、馬名 | `horse`・`horse_identifier`・`runner_observation(CONFIRMED)` |
| RA 7 | レース最終版の条件・発走時刻 | `race_observation(OFFICIAL_RESULT)` |
| SE 7 | 公式血統登録番号、確定着順、異常区分 | `runner_observation`・`result_observation(OFFICIAL)` |
| SE 7で異常 | 取消、競走除外、中止、失格、降着など | 異常区分に応じた`NON_STARTER`・`DID_NOT_FINISH`・`UNRESOLVED`。着順不明はNULLとし`quarantine_issue`へ |
| RA/SE A・B | JV-Linkに含まれる地方・海外の競走情報 | **JRAとして自動登録しない** |
| RA/SE 0・9 | 提供元削除・レース中止 | **その原本オブジェクト全体を保留**。過去情報を黙って残して「現行」と宣言しない |
| RA/SE 1・3〜6 | 木曜出走馬名表・速報 | この変換ミッションでは対象外（原本は保持） |

**同着の馬券解釈や複勝的中ルールを導く処理ではない。** 異常結果は不正な負例として扱わず、確定着順を観測情報として保管するだけ。馬場種別もトラックコード対応の検証前はNULLにする。イベント時刻と提供元作成日、実際の取得時刻を混同しない。

## 自動化の境界と運用

- `tools/atlas_jvdata_map.py`：デフォルト**読み取りプレビュー**。実DB登録は`--apply`明示指定のみ。接続は`ATLAS_PG_DSN`で、接続先データベース名が`neo_jizo_atlas`でない場合は既存のINBOX側が拒否する。
- 登録済みソースが`JRA`、`JV_LINK`、現時点と取り込み時点で**権利承認済み**、かつ元原本が`VALIDATED`でなければ変換しない。CLIでは`--source-code`または`--local-jra`を選択。後者は`ドキュメント/NEO-JIZO-ATLAS-DATA/sources.local.json`の許可済みJRA登録だけを使い、IDを毎回入力しなくてよい。
- 同一原本を複数回適用しないため`atlas/sql/002_canonical_map.sql`で`canonicalization_batch`を追加。マッピング結果と件数は追記専用。
- **RA→SE順**で同一ファイルの収録順序が乱れても関連付けできる。SEだけ来た場合はRAが先に届くまで保留し、二度目のスキャンで再試行できる。
- 完全な検証が終わるまでDB変更はしない。異常レコード一件でも発見されたら、そのオブジェクトは**全体をロールバック**する。
- 原本、個人契約データ、DBダンプ、APIキーをGitHubにアップロードしない。AIには原本と秘密情報を送信しない。
- 一つのファイル当たり20,000レコード超はこのマッピング処理の対象外。大量のウッド/坂路は既存Parquet構想へ。
- **予測凍結証拠は別途必要**。過去のJVData`データ作成日`やイベント日付から「実際に発走前に受信した」と推論しない。FORWARDは取得SHA・凍結Receiptを検査するまで本番利用禁止。

## 仕様上の裏付け

- JRA-VAN公式[JV-Data仕様書 Ver.4.9.0.1](https://jra-van.jp/dlb/sdv/sdk/JV-Data4901.pdf)（PDFページ10: RA, 11: SE）。**文字列ではなくバイトオフセット**で解釈する。
- [SDK最新版](https://developer.jra-van.jp/t/topic/45) 5.0.0（2026/8/4）のJV-Data構造体/Python 3.14版と実機でクロス検証するまでは、解析器の正式性を確定しない。
- [公式レッスン：JV-Data内容の読み出し](https://developer.jra-van.jp/t/topic/605)：独自の文字分割ではなくSDKの構造体との照合を推奨する。構造体はSDKからユーザーのWindows端末上でのみ取得し、GitHubへ転載しない。

## 実機導入の前には「ATLAS-DOCTOR」を先に実行

**`tools/ATLAS-DOCTOR.cmd`をダブルクリック**。読み取り専用でWindows/Python 64bit・pywin32・PostgreSQLドライバー・新DBの対象名と必須テーブル・JRA許可設定・空き容量・取得カーソルをチェックし、日本語で`PASS/BLOCKED/ACTION_REQUIRED`を表示する。既存DB/原本を変更せず、SDKのJVInit/JVOpenも呼ばない。

公式開発者コミュニティには、JV-Link公式検証ツールでは成功しても**Python 3.14/3.13から`JVOpen`または`JVRTOpen`で`-413`となる事例**が2026年9～10月に報告されている。これは全環境での再現ではなく、単一原因が確定したものでもない。**CIの模擬成功から実通信の成功を保証しない**こと。公式の開発者コミュニティ・SDKログで検証し、サービスキーをチャットやGitHubへ載せないこと。
参考: https://developer.jra-van.jp/t/topic/1081

### 多分割のトランザクション境界

JV-Link `RACE`が複数のJSONLファイルへ分割された場合、**全チャンクのサイズ・SHA256・レコード構造の検証と原本保全を先に完了**し、その一連を**1つのPostgreSQLトランザクション**で記録する。途中の一件が失敗すれば、DBの全チャンク登録をロールバックし、次回の再処理に残す。単に受信済みマニフェストがあるだけでは不十分なため、独立CIで「2個目のDB書込失敗→1個目も残らない」を検証する。

## 日常の簡単な操作（PC実機SDK検証・事前設定後）

- **一括更新**：初回JRA取得が完了した後、`tools/ATLAS-JRA-UPDATE.cmd` のダブルクリック1回で「JV-Link差分受信 → JRA専用INBOX投入 → RA/SEを新DBへ登録」を順序通り実施。取り込み前に、新DBへの接続と許諾を検査する。
- **有人セッション中の自動更新**：`tools/ATLAS-JRA-UPDATE-WATCH.cmd`を実行し、60分ごとに同じ処理を繰り返す。**タスク/サービスの登録は行わない**。ほかの`ATLAS-JRA-WATCH.cmd`と同時に起動しないこと。
- どちらも新DB接続の`ATLAS_PG_DSN`、`sources.local.json`承認、JRA-VAN SDK/pywin32導入、初回受信カーソル、正規化DDL適用が前提。まだWindowsでの実データ動作保証はない。
- `tools/ATLAS-JRA-MAP-PREVIEW.cmd` をダブルクリック：**読取専用**で未処理原本の変換可能件数・理由を確認。
- `tools/ATLAS-JRA-MAP-APPLY.cmd` をダブルクリック：`ATLAS_PG_DSN`が**新DB**を指し、JRA権利登録とINBOX検証が済んだ場合だけ、最大10バッチを型付きテーブルへ追加。
- 多量の過去原本がある場合は10バッチずつ継続処理。将来は監督プロセスがキューを繰り返し走査する方式にする。
- JRA取得・RAW投入が未完了なら変換はできない。ファイルを手で改造して例外を通すことは禁止。

## 最初の試験

GitHub Actionsは合成レコードしか扱わず、Windows/Linux 3.13/3.14で固定長・CP932・馬ID・着順・情報漏洩・異常を試す。Ephemeral PostgreSQL 18では、①RAW投入、②プレビューはDB更新なし、③公式RA/SEを新DBへ登録、④再処理ゼロ、⑤RA未着のSEを保留、⑥不正ファイルなら全ロールバックを試験する。

## 2026-10-08：実機導入前の統合監査

- **JVInit：** 個人開発時はJRA-VAN公式の`UNKNOWN`へ統一。正式登録IDはローカルの`ATLAS_JVLINK_SID`で渡す。誤ったSIDはCOM起動前に拒否し、JRA-VANの`-413`等は理由コードだけ記録する。
- **DB：** `atlas/sql/001_init.sql`と`002_canonical_map.sql`の冒頭にSQLレベルの`current_database() = 'neo_jizo_atlas'`ガードを追加。**旧`mykeibadb`へ直接実行してもDDLに進まない**。CIでは無関係のDBへ同じSQLを適用して拒否されることを確認する。
- **PRの段階管理：** #61 → #63 → #64 → #65。今はDraftでマージしていない。#65は親#64を**履歴を破壊しないマージコミット**で取り込み、コードの重複を検証して競合を解消した。GitHubのテスト成功は、実機のJV-Link COM・権利・設定・OS自動運用の成功を意味しない。
- **実機接続時の順番：** まず読取専用`ATLAS-DOCTOR.cmd` → 新DBの接続先確認 → 公式SDKの単発受信 → RA/SE原本のハッシュ照合 → 新DBプレビュー → 許諾済み小規模データだけ登録。長期履歴の一括移行や常駐化はこの合格後。
- **停止条件：** スキーマ不一致・権利不明・COM `-413`・時刻不明・原本相違・DB接続先相違があれば、誤った成功報告をせず「BLOCKED」とする。自動でDB削除、サービス停止、キー再登録はしない。

## 次の最優先課題

1. **公式SDK Pythonサンプルと同じ原本**でRA/SE位置・JV-Link COM戻り値のクロス検証（PC実機、許可されたローカル原本のみ）。
2. RA 1や削除・訂正（0/9）、速報(3〜6)、異常区分の全状態管理。現時点の変換だけで全レースの完全な出走表を保証しない。
3. 公式トラックコード → 芝/ダート/障害、発走時刻変更、競馬場整合性、競走馬マスタ（UM）、HC/WC調教を順次追加。
4. **NAR/UmaConn**の仕様・許諾・自動取得アダプター、別ソースの公式馬ID照合。
5. 既存Draft PR #61,#63,#64 と順に統合し、実データ・DB接続を検証してから自動運転へ移行。
