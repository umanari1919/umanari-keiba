# THE JOCKEY 基盤強化方針

## 目的

THE JOCKEYは機能数を増やすことより、研究結果を長期間信頼できることを優先する。

研究所の土台は次の順序で成立する。

1. Foundation Self-Test
2. Data Inventory
3. Canonicalization
4. Reconciliation
5. Schema / Leakage Gate
6. Feature / Temporal / Model Research
7. Prediction / Simulation
8. Decision Strategy
9. Forward Blind / Failure Analysis

上流が壊れている状態で下流の成績が良くても、その結果は本番判断に使用しない。

## Foundation Self-Test

常駐Workerについて以下を監査する。

- Python構文が成立している
- state contractがある
- main guardがある
- start-research-lab.ps1から起動対象になっている
- lab_updater.pyの自己更新対象になっている
- installerへ含まれている
- CORE/data、CORE/reports、checkpoints、logs、canonicalization領域へ書き込み可能

BLOCKED時はChief Operating DirectorがProductionをHOLDする。

## Canonicalization

JV2AI、PostgreSQL、JVD、その他CSVは直接CORE-003Bへ混ぜない。

必ずSource Adapter Contractを登録し、次を満たす場合だけversioned stagingへ変換する。

- source_idが明示されている
- provenanceが明示されている
- rights_statusがAPPROVED_INTERNALまたはAPPROVED
- 元列→Canonical列の対応が明示されている
- CORE-003Bの全列をmappingまたはdefaultで構成できる
- race_id / race_horse_id / horse_id / race_date / race_scope_cdが有効
- WIN/TOP2/TOP3ラベルが有効
- race_horse_idが一意

列名・テーブル名・意味を推測して自動変換してはいけない。

## Reconciliation

Canonicalizationで作成されたstaging artifactを含め、CORE-003Bと完全互換の候補だけを昇格対象とする。

Raw sourceは上書きしない。

昇格時にはsource signatureを変更し、下流のCORE-004、Temporal、Model研究を再評価させる。

## 研究所の原則

- 便利な仮設より、検証可能な契約を優先する
- 一時的な高成績より、再現性を優先する
- データソースは複数あってよいがCanonical Truthは一つにする
- Source Rights / Provenanceが不明なデータは自動昇格しない
- Blind結果はモデル選抜へ逆流させない
- 自動投票・資金移動は研究所基盤とは分離する

## 今後の強化順

1. JV2AI実スキーマ用Adapter Contract
2. PostgreSQL mykeibadb用Adapter Contract
3. Source Coverage by Year / Domain
4. Source Overlap / Duplicate audit
5. 72時間無人運転試験
6. Recovery Drill
7. Blind Betting Tournament
