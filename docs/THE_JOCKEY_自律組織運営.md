# THE JOCKEY 自律組織運営

## 目的
Founderが毎回「次に何を動かすか」を決めなくても、研究所自身が現在の証拠から次のMissionを決定する。

## 組織

### FOUNDATION
研究所そのものの健全性を担当する。Foundation / Schema / Leakage / Resource / Backup を含む。

### DATA
Source Adapter / Inventory / Canonicalization / Reconciliation / Immutable Canonical Store を担当する。

### RESEARCH
Field Strength、特徴量、Experiment、Hypothesis、JRA/NAR専門モデル、Ensembleを担当する。

### PREDICTION
Universal Model、確率校正、着順分布、Race Simulation、Fair Oddsを担当する。

### STRATEGY
市場価格との比較、MIN-1/MIN-2/MIN-3、JRA/NAR別意思決定研究を担当する。

### AUDIT
Forward Blind、Failure Analysis、将来のBlind Bettingを担当する。

## 経営サイクル

1. Research Material Engineが既存の監査・実験・外れ理由・データ棚卸しから研究素材を生成する。
2. Mission PortfolioがImpact / Urgency / Confidence / Cost / Riskで採点する。
3. BLOCKERは通常研究より優先する。
4. 未利用データ・Source Contractなどデータ供給上の大きな欠損には追加優先度を与える。
5. 上位3件をActive Missionとする。
6. 最上位1件をNEXT MISSIONとして公開する。
7. Pipeline OrchestratorはMissionに必要なWorkerを優先し、高コストWorkerを不要時に止める。
8. Chief Operating Directorが毎周期この判断を再評価する。

## 優先度

基本式:

`impact*2.2 + urgency*1.8 + confidence - cost*0.9 - risk*1.1`

さらに:
- Foundation BLOCKER: 強制加点
- DATAのUNUSED_DATA / SOURCE_CONTRACT: 加点

単一のモデルスコアや直近1レースの結果だけでMissionを変更しない。

## 研究素材の生成元

現在は次を自動監視する。

- Foundation Self-TestのBLOCK/WARN
- Data Inventoryの未利用レース
- Source AdapterのNEEDS_CONTRACT / UNVERIFIED
- Failure Analysisで反復する失敗理由
- Forward Blindの標本不足
- Experiment数不足
- 最近のExperiment停滞

研究素材は既存のreport/stateからのみ生成する。未知のDB列意味、競馬事実、レース結果を推測して素材化しない。

## 出力

- `RESEARCH_MATERIAL_queue.json`: 新しい研究素材
- `MISSION_PORTFOLIO_plan.json`: 優先順位付きMission全体
- `NEXT_MISSION.json`: 現在の最優先Mission
- `OPERATION_control.json`: 動かすべきWorkerと運転モード
- `CHIEF_OPERATING_report.json`: 経営層の最終判断

## Founder介入

Founder承認は次に限定する。

- 権利・契約の承認
- 不可逆なデータ破壊
- 本番公開・資金移動
- 大きなコスト発生
- Source Adapterで列意味を人間が確定する必要がある場合

通常の研究順序、再試行、優先順位変更、Worker停止/再開は研究所自身が判断する。

## 禁止

- 1回の外れで研究方針を反転する
- OOS / Blind結果を学習・選抜へ逆流させる
- 未知schemaを自動推測してCanonicalへ投入する
- 基盤BLOCK中に高コスト研究だけを走らせる
- 「全Directorを常に全力稼働」させる

## 目標

研究所は単なるスクリプト集合ではなく、

`観測 → 課題発見 → 優先順位 → Mission → 実行 → 評価 → 新素材生成`

を自律的に循環する組織として運用する。
