# HANDOVER — AI開発引き継ぎ入口

更新日: 2026-10-07

このファイルは、NEO JIZO KEIBA / THE JOCKEY の作業を新しいAIセッションへ低コストで引き継ぐための入口です。
毎回リポジトリ全体を読み直さず、次の順序で必要最小限だけ確認してください。

## 読む順番

1. `CURRENT_STATE.md`
2. `NEXT_MISSION.md`
3. NEXT_MISSIONで明示された対象ファイルだけ

過去のMission、docs全体、tests全体、DB全表を最初から走査しないでください。
不足情報が発生したときだけ探索範囲を広げます。

## 運用原則

- GitHubをコード・仕様・履歴の正規保管場所とする。
- 通常ChatGPTは設計、研究、レビュー、GitHub操作を担当する。
- WorkはローカルPC、WSL、PostgreSQL、ローカル未同期ファイルが必要な作業だけに限定する。
- 原則 `1 Work = 1 Mission` とし、Missionの対象・完了条件を先に限定する。
- GitHub Actionsへ自動テストを寄せ、同じテストをWorkで何度も繰り返さない。
- Mission終了時に `CURRENT_STATE.md` と `NEXT_MISSION.md` を更新する。
- 機能開発より先に、GitHubとローカル最新版の同期状態を保証する。

## 安全規則

- 既存DBの削除、DDL、データ更新は禁止。明示承認がない限りREAD ONLY。
- サービス停止、既存フォルダー移動、既存データ削除は禁止。
- ローカル最新版がGitHubへ同期済みと確認できるまで、古いGitHubコードで最新機能を上書きしない。
- 大規模変更は専用ブランチ + PRで行う。

## 現在の入口

現在地は `CURRENT_STATE.md` を参照してください。
次に行う作業は `NEXT_MISSION.md` の1件だけです。
