# BAOZ-BASELINE-001 — 馬王Z 標準状態ベースライン

更新日: 2026-10-08
Status: IMPLEMENTATION READY / LOCAL EVIDENCE PENDING

## Goal

馬王Zを一切カスタマイズしない初期セットアップ直後の状態を対照群として固定し、
印そのものの予測性能と、馬券としての収益性能を分離して測定する。

馬王Zの設定改善はこのMissionの対象外とする。

## Non-goals

- 馬王Zの得点式・印・推奨買い目設定を変更しない。
- 馬王ZのDBを更新・加工・削除しない。
- 馬王Zの指数や予想を公開・販売用途へ転用しない。
- 過去結果を見ながらパラメータを調整しない。
- NEO JIZOの本番モデルへ馬王Z値を投入しない。
- 自動投票を行わない。

## Baseline principle

初期状態を Control Group とする。

順序は必ず次の通り。

1. 標準印の性能を測る。
2. 人気との関係を測る。
3. 単勝・複勝の回収率を測る。
4. 条件別に分解する。
5. その後にのみ推奨買い目を評価する。
6. カスタマイズ研究は別Missionで一変数ずつ行う。

## Minimum input contract

ローカル側で馬王Zと結果データを結合し、研究用CSVを作る。
GitHubには馬王ZのMDB原本を置かない。

必須列:

| column | meaning |
|---|---|
| race_id | レースを一意に識別するキー |
| runner_id | 出走馬を一意に識別するキー |
| mark | ◎ / ○ / ▲ / △ / その他。空欄は無印 |
| finish_position | 確定着順 |

任意列:

| column | meaning |
|---|---|
| popularity | 最終人気 |
| win_return_yen | その馬へ100円単勝を買った場合の確定払戻。外れは0、取得不能は空欄 |
| place_return_yen | その馬へ100円複勝を買った場合の確定払戻。外れは0、取得不能は空欄 |
| surface | 芝 / ダート / 障害など |
| distance_m | 距離 |
| class_name | クラス |
| track | 競馬場 |
| field_size | 頭数 |

注意: ROIを測る場合、外れ馬の払戻列を空欄にせず 0 とする。
空欄は「払戻データを取得できなかった」と解釈する。

## Required metrics

印ごとに最低限:

- starts
- wins
- top2
- top3
- win_rate
- top2_rate
- top3_rate
- win_roi_pct
- place_roi_pct

人気帯:

- 1番人気
- 2〜3番人気
- 4〜6番人気
- 7番人気以下
- 不明

## Later slices

ローカル実データが揃った後に追加する。

- 芝 / ダート
- 距離帯
- クラス
- 競馬場
- 頭数
- 堅い / 荒れる
- 馬王◎が飛んだレース
- ▲△の人気薄激走

## Leakage guard

評価期間の結果を使って馬王Z設定を変更してはならない。
Baseline取得後のカスタマイズ研究は、学習・検証・未来検証期間を分離する。

## Completion gate

次を満たしたとき PASS。

- 初期設定を変更していない証拠を記録。
- 対象期間を固定。
- race count / runner count を記録。
- ◎○▲△について勝率・連対率・複勝率を算出。
- 人気帯別成績を算出。
- 単勝・複勝のROIを算出、または払戻データ不足を明示。
- 使用した研究用CSVの列契約と生成手順を記録。
- 馬王Z原本DB・契約キー・秘密情報がGitHubへ入っていないことを確認。

## Status format

Mission終了時は以下だけを要約する。

```text
Status       : PASS / PARTIAL / BLOCKED
Period       :
Race count   :
Runner count :
Baseline     : FROZEN / NOT FROZEN
Marks        : READY / INCOMPLETE
Win/Top2/Top3: READY / INCOMPLETE
ROI          : READY / INCOMPLETE
Leakage      : NONE / FOUND
Blockers     :
Next         :
```
