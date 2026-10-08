# ATLAS-DB-SETUP-001 — 独立DBを安全にワンクリック構築

状態（2026-10-08）：コード実装。実Windows環境・実JRA-VAN原本への適用は**未実施**。ユーザーの既存`mykeibadb`、馬王Z、JV-Linkのローカルデータはそのまま保全する。

## どんな操作に変わるか

**初回だけ**次の流れにする。PowerShellの長文貼り付けやZIPの受け渡しは不要。

1. PR #61・#63・#64・#65の内容を順番にレビュー・統合する。先にマージは自動実行しない。Python 3.13/3.14と`psycopg[binary]==3.3.2`を別のATLAS用環境に導入（現物PCへの導入は別途必要）。
2. Windowsの**環境変数**で`ATLAS_PG_ADMIN_DSN`と`ATLAS_PG_DSN`を**一度だけ**設定。adminの接続先DBは`postgres`、新DBの接続先は`neo_jizo_atlas`。同じユーザー名・同じローカルホスト・同じポートであることが必須。既存`mykeibadb`はどちらにも指定しない。
3. `tools/ATLAS-DB-CHECK.cmd`をダブルクリック。**DBを変更せず**、接続先の形式・新DBが未作成かを検査する。
4. `tools/ATLAS-DB-CREATE.cmd`をダブルクリックし、内容を確認してから一度だけ`CREATE`と入力。対象DBが**まだ存在しないときだけ**`CREATE DATABASE neo_jizo_atlas`とSQLマイグレーション`001_init.sql`・`002_canonical_map.sql`を適用する。
5. 終了後`tools/ATLAS-DOCTOR.cmd`でPython・JV-Link許諾・カーソル・専用テーブルを検査する。**JRA-VAN実取得は別の実機ゲート**で行う。

### DSN設定例（資格情報を含めない推奨例）

```text
ATLAS_PG_ADMIN_DSN = postgresql://atlas_user@localhost:5433/postgres
ATLAS_PG_DSN       = postgresql://atlas_user@localhost:5433/neo_jizo_atlas
```

既存PostgreSQLのクラスタのポートが5433の場合の例であり、自動的にユーザーPCの設定を確定したものではない。ユーザー名は利用環境に合わせる。パスワードはDSN・GitHub・会話へ書かず、libpqのローカル資格情報保存方法（`PGPASSFILE`等）またはOSの許可済み方法を使用する。新DBの初期作成時のみ、対象ロールには`CREATEDB`権限が必要。管理者の秘密情報を、作業成果やスクリーンショットへ掲載しないこと。

### 間違った環境を絶対に触らないためのルール

- **既定は読取専用**。実行時に`--apply`が指定されて初めて新DB作成を試みる。
- `postgres`は**管理用データベースとして読み取りと`CREATE DATABASE`操作だけ**に使う。既存テーブルや他のDB、サーバーサービスは操作しない。
- 接続先は`localhost / 127.0.0.1 / ::1`のみ許可、リモートDBへの作成は拒否する。同一ユーザー・ホスト・ポートしか受け付けない。
- `neo_jizo_atlas`が既に存在する場合は**上書きしない**。必須表がそろっていれば`ALREADY_READY_NO_CHANGES`、未知の構造なら`EXISTING_ATLAS_DB_NEEDS_MANUAL_REVIEW`で停止する。
- **CREATE DATABASE成功後に後続SQLが失敗しても、DB削除・サービス再起動・既存DB復元はしない**。実行を止めて原因を調査する。
- SQL自体にも`current_database() = 'neo_jizo_atlas'`チェックがあり、`mykeibadb`へ誤って送った場合はDDL前に拒否する。
- 自動バックフィル、JRA取得開始、NAR接続、ユーザーDBの読み取りや書き換えは、この初期化ツールでは行わない。

## 2026-10-08追加：GitHub Actions起動障害に依存しない実機前診断

GitHub PR #65は`startup_failure`/`BuildFailed`/`0 jobs`のため、最新コミットのWindows/Linux CIはまだ実行できていない。**「テスト合格」と表示することは禁止。** 過去の成功CIと区別する。これに備え、実機では次の二つを独立してチェックできるようにした。

- `tools/ATLAS-JRA-COM-CHECK.cmd`：**ローカルCOM登録だけ**をダブルクリックで調べる。JV-Linkの`JVDTLab.JVLink` COMオブジェクトを生成・解放するが、`JVInit/JVOpen/JVGets`は**一切呼ばない**。通信・契約・実データ取得を確認するものではない。`ATLAS-DOCTOR`の`JV_COM_LOCAL`欄に結果が出る。ほかのDB設定がBLOCKEDでも、この欄は独立に確認可能。
- `tools/ATLAS-OFFLINE-SELFTEST.cmd`：**合成レコードだけの7スイート**を同じPCのPythonで実行。子プロセスから`ATLAS_PG_DSN`・`ATLAS_PG_ADMIN_DSN`・PostgreSQL資格情報・JRA-VANのソフトID・実DBテストフラグを外す。旧DB、新DB、SDKの取得関数には接続しない。失敗があれば直ちにBLOCKEDとして終了する。

**これは新しいPCやサービスへ勝手に展開したものではない**。GitHubのブランチに実装された診断コードを、実機導入レビュー後に使用する。ローカルのコードが最新になっていなければ起動ファイルは存在しない。

### コード位置

- `tools/atlas_db_setup.py`：読み取り専用チェックと明示的な初期化処理。
- `tools/ATLAS-DB-CHECK.cmd`：ワンクリックの安全確認。
- `tools/ATLAS-DB-CREATE.cmd`：人間が`CREATE`を明示入力する初回だけのDB構築。
- `tests/test_atlas_db_setup.py`：旧DB誤指定、異なるPostgreSQL、遠隔接続、マイグレーションガード、既存DBでの無変更再実行。
- `.github/workflows/atlas-jvdata-map-003.yml`：隔離PostgreSQLで新DB作成・再実行のテストを追加（CIが正常起動した場合に検証）。

## 大容量の過去データを毎回読み直さない対策

`tools/atlas_inbox.py` に**受信済みJV-Link原本の高速重複照合**を追加。初めて取り込む原本は、従来通り全チャンクのバイト列とSHA-256を検証し、専用DBへ**一括トランザクション**で記録する。成功後だけ、`receipts/jra_jvlink_done/`へ更新日時・サイズ・元マニフェストのハッシュを持つ**処理済み索引**を保存する。

次の取り込みでは、**今回の受信マニフェストに列挙されたSHA-256だけ**を新DB`neo_jizo_atlas`へ問い合わせる（1回のSQLで最大512件、必要に応じて分割）。DB全履歴のSHAをメモリーに読み込まず、さらに索引と現物ファイルの更新情報が完全一致するものだけを高速な`DUPLICATE`扱いにする。受信原本全体の再ハッシュやRAW JSONLの再解析は行わない。以下の異常は必ず通常の厳格な検証に戻る。

- DBを空の状態に復元した、登録済みSHAがDBから消えた
- 取得ファイルのサイズ・更新/作成時刻が変わった
- マニフェストの内容が変わった
- 最新のDB品質判定が`REJECTED`になった
- 供給元の権利状態が`DENIED`になった
- 受信完了マニフェストが欠損・破損した

**最も重要：** この高速索引は便利な最適化であり、**DBの登録事実に代わる証拠ではない**。索引の書き込みに失敗してもDBの原本登録は保全され、次回は通常処理で再照合する。

この改善は**過去原本を再読込するI/Oを削減する設計**であり、15年分全体の容量削減を達成したという意味ではない。マニフェストの列挙、ファイルのメタデータ確認、DBの一括照合は残る。実測速度とディスク使用量は利用者PCでの承認済み実データ試験後に測定する。

**テスト状況：** GitHubのPR #65はジョブ開始前の`startup_failure`が続いている。高速照合の新しい合成・PostgreSQL検証コードは追加したが、最新コミットで**実行済みPASSは未確認**。実機導入・本番投入はその合格後。

## 歴史データの供給元：RACEだけでは完結しない

JRA-VAN公式FAQでは、`RACE`が今週のレース詳細・出走馬情報、`RCOV`が競走馬マスタと過去走のレース詳細・馬毎レース情報を提供すると説明している。**現在のATLAS JV-Link取得コードは`RACE`の通常差分だけ**で、`RCOV`やセットアップモードの一括取得は実装していない。

JRAの長期研究DBで全期間の競走馬ID、過去走、結果を揃えるには、公式権利確認後に`RCOV`専用の取得契約・年次バックフィル・増分の証拠時刻を別工程として組み込む。NAR、坂路、ウッド、血統の歴史全量は、実DBで件数一致を確認するまで**「カバー済み」表示禁止**。

ソース: JRA-VAN公式競馬ソフト開発FAQ https://jra-van.jp/dlb/sdv/faq.html

## 依存PRを本番運用へ進める基準

DB初期化後、JRA実機との**最初の1件**を検証。受信完了マニフェストで保護された正規のJRAファイルは、ファイル更新から2秒を待たずにSHA-256で確認してDBへ取り込める。手で置かれた通常JSONLファイルには従来の「変更直後2秒は拒否」の保護を維持。

未確定結果・速報・取消・中止は正式な着順学習データにしない。フォルダー・DB・SDKの状態が不確かなら停止する。

**完了条件は「個人PC上で実際のJRAレース1件が原本の証拠付きでATLAS専用DBに入り、再起動・同一ファイル再処理で重複しないこと」。** GitHubの模擬成功とは区別する。
