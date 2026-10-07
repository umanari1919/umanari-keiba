# CURRENT STATE — NEO JIZO KEIBA / THE JOCKEY

更新日: 2026-10-07

## GitHub正規リポジトリ

- Repository: `umanari1919/umanari-keiba`
- Default branch: `main`
- Visibility: public
- ChatGPT GitHub connector: 読み取り・書き込み確認済み
- この運用整備開始時に観測したmain HEAD: `369cf6516562fa09823f1ca365945649bbfcecbf`
- 上記HEADは PR #35 `THE JOCKEY Specialist Executors + Realized Strategy Outcome` のmerge

## GitHub側で確認済みの基盤

- `docs/`
- `tests/`
- `tools/`
- `pyproject.toml`
- `.github/workflows/modern-stack-quality.yml`

GitHub ActionsはUbuntu/Windows、Python 3.13/3.14でmodern-stackの品質ゲートを実行する構成を持つ。

## 重要: ローカル最新版との同期状態

状態: **UNVERIFIED / AUDIT RUNNER READY**

2026-10-06までローカル側では `neo-jizo-keiba` 作業が進んでいたが、その最新内容がこのGitHub mainへ完全同期済みとは確認できていない。

現在のGitHub検索では、最新ローカル作業で言及されている次の識別子・作業内容を確認できなかった。

- `jockey-25`
- 3目標評価
- 調教48候補
- 最新版 `collect_training.py` の存在・同期状態

したがって、GitHub mainを「2026-10-06時点の完全な最新版」とみなして機能開発を進めてはいけない。

## ローカル資産

通常ChatGPTからはローカルPC、WSL、PostgreSQL `mykeibadb` へ直接アクセスしない。
これらが必要なMissionだけWorkを利用する。

DB作業は原則READ ONLY。
既存DB削除、サービス停止、フォルダー移動は行わない。

## 現在の最優先課題

GitHubとローカル `neo-jizo-keiba` の差分を確定し、どちらが正規最新版かを安全に統合する。

詳細は `NEXT_MISSION.md` を参照。


## 2026-10-07 省トークン運用基盤

- PR #36: GitHub本社化の引き継ぎ基盤をmainへ統合
- PR #37: `tools/sync_gate_001.ps1` と専用CIをmainへ統合
- PR #37 merge commit: `ee45cdf218caba3cf72888d4729b39e3e581e878`
- `sync-gate-001` self-test: Windows / Linux PASS
- `modern-stack-quality`: Ubuntu/Windows × Python 3.13/3.14 PASS

ローカル最新版との関係そのものは、ローカル監査ランナーを1回実行するまで未確定。
