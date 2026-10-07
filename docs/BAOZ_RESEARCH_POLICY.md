# BAOZ RESEARCH POLICY

更新日: 2026-10-08

## 1. Standard first

標準状態を測り終えるまで設定を変更しない。

## 2. Prediction and betting are separate

「強い馬を選べるか」と「その価格で買う価値があるか」を別問題として評価する。

順番:

```text
能力順位
 -> 勝率 / 連対率 / 複勝率
 -> 人気
 -> オッズ / 払戻
 -> 券種
 -> 資金配分
```

## 3. One-variable experiments

カスタマイズ段階では一度に一要素だけ変更する。
複数係数を同時に動かして原因不明の改善を作らない。

## 4. Failure is data

特に保存する対象:

- ◎が4着以下
- ◎が人気を大きく裏切った
- ▲△が人気薄で3着以内
- 馬王高評価とNEO JIZO低評価の不一致
- 馬王低評価とNEO JIZO高評価の不一致

## 5. No retrospective tuning in baseline

BAOZ-BASELINE-001では過去結果を見て設定を変更しない。
Baselineの目的は勝つ設定を作ることではなく、標準状態の真の性能を測ること。

## 6. Founder gate

馬王Z設定変更、NEO JIZOへの統合、公開利用、実投票は別Missionとし、
自動昇格させない。
