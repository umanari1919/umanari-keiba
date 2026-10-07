# BAOZ DATA BOUNDARY

更新日: 2026-10-08

## Purpose

馬王Z、JV-Link、UmaConn、NEO JIZO KEIBAのデータ境界を固定する。

## Local only

次はローカルPCから外へ出さない。

- 馬王ZのMDB原本・バックアップ
- JV-Link / UmaConnのサービスキー
- 契約情報
- 認証情報
- PostgreSQL `mykeibadb` 本体
- ローカルキャッシュ
- 馬王Z内部の独自指数・予想値を公開用途へ転用した成果物

## GitHub allowed

GitHubへ保存してよいのは原則として次だけ。

- 研究コード
- テスト
- 入力スキーマ
- 集計ロジック
- 匿名化・最小化したテストfixture
- 集計済みの研究結果
- Mission記録
- エラー分類
- 再現手順

## Separation

```text
JV-Link / UmaConn
        |
        v
ローカル一次データ
        |
        +----> NEO JIZO独自研究・独自モデル
        |
        +----> 馬王Z
                 |
                 v
          PRIVATE BENCHMARK ONLY
```

馬王Zは非公開の比較研究・検算対象とする。
馬王Z由来の値をTHE JOCKEYの公開・販売予想へ直接流さない。

## Database safety

- 原本READ ONLYを優先。
- DELETE / UPDATE / DDL禁止。
- フォルダー移動禁止。
- サービス停止禁止。
- 研究用中間データは別ファイルへ出力する。
