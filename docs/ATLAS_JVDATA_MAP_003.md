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
- `--source-code`必須。登録済みソースが`JRA`、`JV_LINK`、現時点と取り込み時点で**権利承認済み**、かつ元原本が`VALIDATED`でなければ変換しない。
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

## 最初の試験

GitHub Actionsは合成レコードしか扱わず、Windows/Linux 3.13/3.14で固定長・CP932・馬ID・着順・情報漏洩・異常を試す。Ephemeral PostgreSQL 18では、①RAW投入、②プレビューはDB更新なし、③公式RA/SEを新DBへ登録、④再処理ゼロ、⑤RA未着のSEを保留、⑥不正ファイルなら全ロールバックを試験する。

## 次の最優先課題

1. **公式SDK Pythonサンプルと同じ原本**でRA/SE位置・JV-Link COM戻り値のクロス検証（PC実機、許可されたローカル原本のみ）。
2. RA 1や削除・訂正（0/9）、速報(3〜6)、異常区分の全状態管理。現時点の変換だけで全レースの完全な出走表を保証しない。
3. 公式トラックコード → 芝/ダート/障害、発走時刻変更、競馬場整合性、競走馬マスタ（UM）、HC/WC調教を順次追加。
4. **NAR/UmaConn**の仕様・許諾・自動取得アダプター、別ソースの公式馬ID照合。
5. 既存Draft PR #61,#63,#64 と順に統合し、実データ・DB接続を検証してから自動運転へ移行。
