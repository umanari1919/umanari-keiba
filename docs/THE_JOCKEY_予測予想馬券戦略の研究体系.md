# THE JOCKEY 予測・予想・馬券戦略の研究体系

## 1. 予測と馬券を分離する
能力評価モデルは市場オッズを入力に使いません。市場は意思決定層でのみ利用します。

```text
能力評価
↓
P(Win) / P(Top2) / P(Top3)
↓
着順分布
↓
Race Simulation
↓
券種別成立確率
↓
Fair Odds
↓
市場オッズ
↓
Edge / EV
↓
小点数戦略
```

## 2. 券種研究
対象:
- 単勝
- 複勝系
- ワイド
- 馬連
- 馬単
- 枠連
- 三連複
- 三連単

枠連は馬連とは独立に評価し、同一枠の2頭が1・2着になるゾロ目も保持します。

## 3. 小点数原則
小点数そのものを目的にはしません。期待値の低い買い目を削り、資金効率を高めることが目的です。

研究戦略:
- MIN-1: 最大1点
- MIN-2: 最大2点
- MIN-3: 最大3点

比較指標:
- ROI
- 的中率
- 1点あたり期待利益
- 投資額あたり期待利益
- 最大ドローダウン
- 連敗数
- 券種別成績

## 4. JRA戦略
研究仮説:
- 午前の未勝利戦
- 新馬戦
- 障害戦

これらを資金形成フェーズ候補として検証します。ただし固定ルールにはせず、Blind Bettingで有効性を確認します。

将来的に専用化したい領域:
- Maiden Specialist
- Debut Specialist
- Obstacle Specialist

## 5. NAR戦略
NARは時間帯固定よりOpportunity Drivenを優先します。

重視項目:
- Edge
- 不確実性
- 頭数
- 競馬場特性
- 転入馬
- クラス間Field Strength
- 騎手×競馬場
- 短期ローテ

## 6. Fair Odds
Fair Oddsは市場価格ではなく、モデルが推定した成立確率の逆数です。

```text
Fair Odds = 1 / simulated probability
EV = simulated probability × market odds - 1
```

## 7. 最終評価
研究上良かった戦略でも、最終的にはForward Blind / Blind Bettingで評価します。

Blind結果を見てモデルや戦略を後から選び直すことは禁止します。
