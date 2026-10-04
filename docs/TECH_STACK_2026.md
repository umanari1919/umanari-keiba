# THE JOCKEY 技術スタック 2026

更新日: 2026-10-04

## 方針

THE JOCKEY は「最新」を目的にせず、**安定版・Windows対応・無料/OSS・再現性・監査性・速度**を満たすものだけを採用する。

採用階層:

- **CORE**: 日常運用で前提にしてよい安定基盤
- **RESEARCH**: 研究加速に使うが、無くても研究所は起動できる
- **MLOPS**: 実験・追跡・可視化を強化する任意層
- **PREVIEW**: RC/alphaは本番基盤へ入れない

## 2026-10-04 採用セット

### CORE

| ツール | 方針 | 役割 |
|---|---|---|
| uv 0.12系 | 採用 | Python/依存関係/仮想環境管理 |
| Ruff 0.16系 | 採用 | lint/format/静的品質ゲート |
| pytest 9.1 | 採用 | 自動テスト |
| pytest-xdist 3.8 | 採用 | 並列テスト |
| NumPy 2.5 / pandas 3.0 | 採用 | 既存コード互換の数値・表処理 |
| Pydantic 2.13 | 採用 | Director間JSON/state契約 |
| Pandera 0.33 | 採用 | DataFrame/Arrowデータ契約 |
| DuckDB 1.5 | 採用 | 大規模CSV/Parquet分析・JOIN・集計 |
| Polars 1.44 stable | 採用 | 高速LazyFrame処理 |
| Apache Arrow / PyArrow 25 | 採用 | Parquet/列指向データ交換 |

### RESEARCH

| ツール | 方針 | 役割 |
|---|---|---|
| scikit-learn 1.9 | 採用 | 評価・校正・基準モデル |
| Optuna 5 | 採用 | ハイパーパラメータ最適化。SELECTIONだけを最適化しTEST/OOSは使わない |
| CatBoost 1.2 | 分離採用 | 主力GBDT候補。model extraとしてCORE依存から分離 |
| LightGBM / XGBoost | 比較研究 | Champion Tournament候補 |

### MLOPS

| ツール | 方針 | 役割 |
|---|---|---|
| MLflow 3.16 | 任意採用 | 実験追跡・モデル履歴・比較UI。CSV台帳はSource of Truthのまま維持 |

MLflowは強力だが重量級なので、研究所の起動必須依存にはしない。

## 本番採用を保留するもの

- Polars 2.0 RC: プレリリースのため待機
- DuckDB 2.0: 2026-10-21予定。公開直後は上げず、互換性試験後に判断
- pandas 3.1 RCなどalpha/beta/RC版の主要基盤

## データ処理標準

新規処理は以下を優先する。

1. Parquet / Arrow
2. DuckDB SQLによる大規模JOIN・集約
3. Polars LazyFrameによる列変換
4. pandasは既存互換・小規模処理・移行期間用

CSVは交換形式として残すが、研究内部の大規模中間成果物は段階的にParquetへ移す。

## 実装済み接続

- Data Inventory: DuckDBがあれば高速集計、無ければpandasへ自動フォールバック
- Canonicalization: Pydantic + Panderaで契約を補強、無ければ既存手動ゲートへフォールバック
- Hypothesis Generator: Optuna 5 TPEを使用可能。最適化指標はSELECTION LogLossのみ
- MLflow: 明示有効時だけCSV実験台帳をミラー。研究所のSource of TruthはCSVのまま
- Dependency Guard: 安定版・古い版・preview混入・Python互換を監査。自動更新はしない
- GitHub Actions: Windows/Linux × Python 3.13/3.14で依存解決・構文・Ruff実害検査・pytestを実行

## 品質ゲート

```text
uv sync --extra core --extra research --extra dev
ruff check --select F,E9 tools/research_dashboard
pytest -q
Foundation Self-Test
Schema Contract
Leakage Guard
```

## 更新ポリシー

- major/minor更新は自動昇格しない
- patch更新はDependency Guardで検出
- 本番更新はSelf-Test + CI + regression testを通してから採用
- プレリリースは隔離
- `uv.lock` は実環境で依存解決に成功した時だけ生成する。手書き禁止
