# NEXT MISSION

Mission ID: `RESCUE-MANIFEST-001`
更新日: 2026-10-07
Priority: P0
Status: READY

## 目的

ローカル `neo-jizo-keiba` の未追跡272ファイルを、内容を壊さず自動分類し、
GitHubへ救出すべきソース・テスト・設計・設定ファイルを確定する。

## 前提

SYNC-GATE-001で以下を確認済み。

- Relation: `unborn`
- Local HEAD: `(unborn)`
- Tracked changes: 0
- Untracked files: 272
- Keyword hits: 1
- `collect_training.py`: 0

## 分類

最低限、次に分類する。

- SOURCE
- TEST
- CONFIG
- DOC
- DATA
- GENERATED
- SECRET_RISK
- OTHER

## 禁止事項

- `git add .`
- commit
- checkout
- merge / rebase
- pullによるworking tree変更
- reset / clean
- ファイル削除・移動
- DBアクセス
- secret内容の表示・GitHub送信

## 完了条件

- 272件の分類数
- top-level directory件数
- 拡張子別件数
- SOURCE / TEST / CONFIG / DOC候補パス
- `jockey-25` / 3目標 / 調教48 の一致ファイル
- SECRET_RISKの件数だけ確認（内容は表示しない）
- GitHubへ救出する安全なファイル集合を確定

完了後、`RESCUE-IMPORT-001` へ進む。
