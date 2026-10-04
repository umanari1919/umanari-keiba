# THE JOCKEY — Decision Strategy Architecture

## 目的
研究・予測・馬券戦略を分離し、モデル研究と購入戦略が相互汚染しない構造にする。

## 4層
1. **Research** — 能力、特徴量、時系列、JRA/NAR専門モデル、Ensemble
2. **Prediction** — Win/Top2/Top3、着順分布、Race Simulation、全券種Fair Odds
3. **Decision Strategy** — 市場オッズ、Edge、小点数最適化、JRA/NAR別戦略
4. **Independent Audit** — Forward Blind、将来のBlind Betting Evaluation

## 券種
WIN / PLACE系指標 / WIDE / QUINELLA / EXACTA / FRAME / TRIO / TRIFECTA。
FRAMEは馬連と独立して扱い、同枠1-1等のゾロ目も保持する。

## 小点数原則
点数を固定目的にせず、低期待値の買い目を削り、1点あたり期待値と資金効率を最大化する。
研究プロファイルとして MIN-1 / MIN-2 / MIN-3 を常時比較する。

## JRA仮説
午前の未勝利・新馬・障害を「資金形成候補」として独立タグ付けする。
これは経験則に基づく研究仮説であり、固定ルールにはしない。Blind Bettingで検証する。

## NAR仮説
時間帯よりも競馬場・クラス・頭数・転入・Field Strength・不確実性を重視し、Opportunity Drivenで高品質レースを探索する。

## ガバナンス
- Predictionモデルは市場オッズを学習入力にしない。
- Decision Strategyだけが市場オッズを参照する。
- Blind/Blind Betting結果をChampion選定へ逆流させない。
- 自動投票・資金移動は行わない。
- 戦略は候補生成と研究評価までとする。
