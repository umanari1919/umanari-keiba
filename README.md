# NEO JIZO ATLAS

**競馬を知る。未来を読む。競馬を体験する。**

うまなり地蔵の競馬データ・能力研究と予測支援の開発基盤です。従来の研究名 **THE JOCKEY** は、研究基盤としては **NEO JIZO ATLAS（ネオ・ジゾウ・アトラス）** に移行します。

## 3つのプロジェクト

| 名称 | 役割 | 状態 |
|---|---|---|
| **NEO JIZO ATLAS** | JRA/NARデータ、能力・血統・調教、AI学習と研究評価 | 研究開発中 |
| **NEO JIZO FORWARD** | 出走表、レース前予測、予測凍結、結果照合、実戦評価 | 実装・検証中 |
| **THE JOCKEY** | 競馬ゲーム・物語・育成・体験 | 将来の開発構想 |

上位ブランドは **JIZO WORKS**。

詳しくは[プロジェクト構成](docs/PROJECT_PORTFOLIO.md)。

## 開発原則

- 勝率・連対率・複勝率を別々に評価する。
- 履歴から算出した成績と、発走前に凍結した予測の実戦成績を混同しない。
- 市場オッズ・人気を独立した能力モデルへ無断混入しない。
- JRA/NARの出走表の正当性・時間整合性・データの権利と品質を守る。
- PostgreSQLや馬王Zの既存データを勝手に削除・移動・初期化しない。
- 自動投票および未承認モデルの本番利用は行わない。

## 既存資産・進行状況

リポジトリ名 **umanari1919/umanari-keiba** と既存のプログラム識別子は互換性維持のため変更しません。

- 旧THE_JOCKEY仕様書やjockey-25の研究コードはATLAS側の過去資産として参照可能に残します。
- FORWARDの進行中研究： [Draft PR #54](https://github.com/umanari1919/umanari-keiba/pull/54)
- このリポジトリは研究・検証段階です。ライブ予測の完全自動化や商用本番承認はまだありません。

関連資料：

- [ATLAS / FORWARD / THE JOCKEY の役割](docs/PROJECT_PORTFOLIO.md)
- [安全な改称と移行](docs/NEO_JIZO_ATLAS_MIGRATION.md)
- [開発状態](CURRENT_STATE.md)
- [次の実装課題](NEXT_MISSION.md)

商標・類似名称は商用利用前に別途確認します。
