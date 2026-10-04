# THE JOCKEY Source Adapter 運用仕様

## 目的

JV2AI / MySQL、PostgreSQL `mykeibadb` など異なる保有データを、意味を推測せず安全にCanonicalへ接続する。

## 原則

1. Source Adapter Directorは常にREAD-ONLYで開始する。
2. `information_schema` / catalogから実在schema・table・columnを発見する。
3. テーブル名・列名からCanonicalの意味を勝手に推測しない。
4. Source Adapter Contractに明示された`column_map`だけを意味変換に使う。
5. `rights_status`が`APPROVED_INTERNAL`または`APPROVED`で、かつ`enabled=true`の場合だけ深いCoverage監査へ進む。
6. Production DBへの書込みは禁止する。
7. Source AdapterからActive Canonical Storeへ直接書き込まない。必ずStaging → Canonicalization → Reconciliation → Immutable Canonical Storeの順を通す。

## 自動生成する監査物

- `SOURCE_SCHEMA_inventory.json`
- `SOURCE_COVERAGE_by_year.csv`
- `SOURCE_OVERLAP_audit.json`
- `CANONICAL_RECONCILIATION_plan.json`
- `CANONICAL_RECONCILIATION_decision.json`
- `SOURCE_ADAPTER_summary.json`

## 状態

- `NEEDS_CONTRACT`: スキーマは見つかったが意味対応が未定義。
- `EXACT_CANONICAL_CANDIDATE`: 必須Canonical列名がそのまま存在する。ただし自動承認はしない。
- `CONTRACT_INCOMPLETE`: 契約はあるが必須列またはsource列が不足。
- `CONTRACT_READY`: 明示契約と実スキーマが一致。

`EXACT_CANONICAL_CANDIDATE`では無効・権利未確認のproposalだけを生成し、自動昇格しない。

## PostgreSQL

既定候補はローカル`127.0.0.1:5433` / `mykeibadb`。接続後に`default_transaction_read_only=on`とstatement timeoutを設定する。

## MySQL / JV2AI

DB名は推測しない。`THE_JOCKEY_MYSQL_DB`が未設定なら`MYSQL_NOT_CONFIGURED`として待機する。

## 研究所の正式データ経路

```text
JV2AI / mykeibadb
        ↓ READ ONLY
Source Adapter Director
        ↓ explicit contract only
Staging
        ↓
Canonicalization
        ↓
Reconciliation
        ↓
Immutable Canonical Store
        ↓
CORE-004 / Temporal / Model Research
```

## 禁止

- SELECT *による巨大抽出
- schema/table/column名の推測
- 未承認rights sourceの自動取り込み
- Raw DBのUPDATE/DELETE/INSERT/DDL
- Source AdapterからCurrent Canonicalへの直書き
