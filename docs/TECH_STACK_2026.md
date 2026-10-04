# THE JOCKEY 技術スタック 2026

更新日: 2026-10-04

## 方針

THE JOCKEY は「最新」を目的にせず、**安定版・Windows対応・無料/OSS・再現性・監査性・速度**を満たすものだけを採用する。

採用階層:

- **CORE**: 日常運用で前提にしてよい安定基盤
- **RESEARCH**: 研究加速に使うが、無くても研究所は起動できる
- **MLOPS**: 実験・追跡・可視化を強化する任意層
- **PREVIEW**: RC/alphaは本番基盤へ入れない

## 2026-10-04 採用候補

### CORE

| ツール | 採用方針 | 役割 |
|---|---|---|
| uv | 採用 | Python/依存関係/仮想環境管理 |
| Ruff | 採用 | lint/format/静的品質ゲート |
| pytest | 採用 | 自動テスト |
| pytest-xdist | 採用 | 並列テスト |
| Pydantic 2 | 採用 | Director間JSON/state契約 |
| Pandera | 採用 | DataFrame/Arrowデータ契約 |
| DuckDB | 採用 | 大規模CSV/Parquet分析・結合・集計 |
| Polars stable | 採用 | 高速LazyFrame処理 |
| Apache Arrow / PyArrow | 採用 | Parquet/列指向データ交換 |

### RESEARCH

| ツール | 採用方針 | 役割 |
|---|---|---|
| scikit-learn | 採用 | 評価・校正・基準モデル |
| Optuna 5 | 採用 | ハイパーパラメータ最適化 |
| CatBoost | 継続 | 主力GBDT候補 |
| LightGBM/XGBoost | 比較研究 | Champion Tournament候補 |

### MLOPS

| ツール | 採用方針 | 役割 |
|---|---|---|
| MLflow 3 | 任意採用 | 実験追跡・モデル履歴・比較UI |

MLflowは強力だが重量級なので、THE JOCKEYの起動必須依存にはしない。

## 現時点で本番採用しないもの

- Polars 2.0 RC: プレリリースのため待機
- DuckDB 2.0: 2026-10-21予定。公開後すぐには上げず、互換性試験後に判断
- alpha/beta/RC版の主要基盤

## データ処理標準

新規処理は以下を優先する。

1. Parquet / Arrow
2. DuckDB SQLによる大規模JOIN・集約
3. Polars LazyFrameによる列変換
4. pandasは既存互換・小規模処理・移行期間用

CSVは交換形式として残すが、研究内部の大規模中間成果物は段階的にParquetへ移す。

## 品質ゲート

すべての新しいDirector/研究コードは将来的に以下を通す。

```text
uv sync
ruff check
ruff format --check
pytest -q
Foundation Self-Test
Schema Contract
Leakage Guard
```

## 更新ポリシー

- major/minor更新は自動昇格しない
- patch更新はDependency Guardで検出
- 本番更新はSelf-Test + regression testを通してから採用
- プレリリースは隔離
- lockfile生成は実際にuvで解決した環境のみで行う。手書きuv.lockは禁止
