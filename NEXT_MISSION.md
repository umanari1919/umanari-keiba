# NEXT MISSION

Mission ID: `SYNC-GATE-001`
更新日: 2026-10-07
Priority: P0
Status: RUNNER READY / LOCAL EXECUTION REQUIRED

## 目的

ローカル最新版 `neo-jizo-keiba` と GitHub `umanari1919/umanari-keiba:main` の関係を確定し、
NEO JIZO KEIBA / THE JOCKEY の正規開発線を1本に統合する。

## なぜ最優先か

GitHubには2026-10-04までの開発履歴がある一方、
2026-10-06のローカル作業で扱っていた `jockey-25`、3目標評価、調教48候補などがGitHubで確認できていない。

この状態でGitHub側だけを最新として機能実装すると、ローカルの新しい成果を上書き・取りこぼす危険がある。

## 実行方法

PowerShell 7で次の1行だけ実行する。

```powershell
$u='https://raw.githubusercontent.com/umanari1919/umanari-keiba/main/tools/sync_gate_001.ps1'; $p=Join-Path $env:TEMP 'sync_gate_001.ps1'; Invoke-WebRequest $u -OutFile $p; & $p
```

既知の既定パス `C:\Users\uchih\Documents\Codex\2026-10-06\new-chat\neo-jizo-keiba` を自動探索する。
見つからない場合だけ `-RepoPath` を明示する。

実行後はコンソール末尾の `SYNC-GATE-001 COMPLETE` ブロックだけを通常ChatGPTへ渡せばよい。
長大なログやZIPは不要。

## このMissionで確認するもの

ローカル `neo-jizo-keiba` について、破壊操作なしで次を確認する。

1. Git repositoryか
2. current branch
3. HEAD SHA
4. `git remote -v`
5. working tree status
6. GitHub mainとのmerge-base
7. ahead / behind
8. tracked変更・untrackedファイル
9. 次の最新版候補の有無
   - `jockey-25`
   - 3目標評価
   - 調教48候補
   - `src/collect_training.py`
10. GitHubへ未反映の重要ファイル一覧

## 禁止事項

- DB write / DDL
- DB削除
- サービス停止
- フォルダー移動
- ローカルファイル削除
- `git reset --hard`
- `git clean`
- force push
- 差分確認前のmainへの直接上書き

## 完了条件

次をすべて満たしたら `SYNC-GATE-001` 完了。

- ローカルHEADとGitHub main HEADを記録
- 両者の関係を `same / ahead / behind / diverged / unrelated` のいずれかで確定
- 未同期変更の完全なファイル一覧を作成
- `jockey-25`、3目標評価、調教48候補の所在を確定
- 安全な統合方法を決定
- 統合後のcanonical branchを明示
- `CURRENT_STATE.md` を更新
- 次の機能Missionを1件だけ `NEXT_MISSION.md` に設定

## Work節約ルール

このMissionでWorkを使う場合も、リポジトリ全体の再研究はしない。
ローカルGit状態と差分確認だけを行い、結果をGitHubへ戻して終了する。

通常ChatGPT側では、その後のGitHubレビュー・設計・PR・CI確認を継続する。
