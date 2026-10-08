# NEO JIZO ATLAS — TOOL-ADOPTION-001 / 自律研究所技術選定

2026-10-08 版。調査・GitHub合成検証の範囲と、PC実環境導入を区別する。

## 採用方針

「有名だから」ではなく、`目的 → 現行機能 → ギャップ → 既存実装との重複 → ソース/ライセンス → セキュリティ → 小さな実験 → 定量評価 → 採用`を原則とする。PCローカルへの自動インストール、DB変更、暗黙課金、非公開馬王Z/契約データのクラウド転送は禁止。

## ATLAS技術レジストリ

| 技術 | 用途 | GitHub現状 | 判断 |
|---|---|---|---|
| DuckDB / Polars / PyArrow | 大規模競馬データ・Parquet | 既存`modern_data_engine.py`/pyprojectに採用済み | 再利用・運用実測 |
| uv / pytest / Ruff | 環境・品質・速度 | pyprojectとCIに採用済み | ロック生成と再現性検証を進める |
| Pydantic / Pandera | スキーマ・明示契約 | `modern_contracts.py`あり | 既存検証を強化 |
| Optuna | 仮説・探索の自動実験 | `hypothesis_generator.py`に候補生成あり | 時系列と試行予算の統制 |
| MLflow | 実験・モデル・トレース | `experiment_tracking.py`は任意mirrorで既定OFF | 有効化前にアクセス権限・秘匿性を検証 |
| CatBoost | 表形式予測 | 任意model extra採用済み | jockey-25基準での比較 |
| River 0.26.1 / ADWIN | レース単位の予測誤差の変化検出 | **本PRで任意extra＋合成テストを導入** | シャドー研究専用 |
| Prefect 3.8.8 | 再実行・遅延・監視可能なPythonワークフロー | **未導入**・既存workerが多数ある | 旧監視の重複排除を証明できてから実験 |
| OpenAI Agents SDK 0.23.1 | 研究AIの委譲・査読・ツール保護 | **未導入**。現時点はAPI不要 | まず合成入出力・sandbox・コスト上限を確認 |
| OpenTelemetry Python | エラー/遅延の分散トレース | **未導入** | 機密データのマスキング方針後 |
| DSPy / GEPA | AI仮説/指示の改善実験 | **未導入** | ベンチマークを固定してから |
| AI Scientist-v2 | 自律仮説・実験の参考 | **コード未導入** | 独自ライセンス・生成コード実行リスクを先に評価 |
| Temporal / A2A / MCP | 分散ワーカー連携 | **未導入** | 一台PC運用から必要性が発生したときのみ |

### 初回採用：River

- 2026-08-21公開の0.26.1、BSD-3-Clause。Python 3.13/3.14 Windows/Linux配布を確認。
- `pyproject.toml`に**opt-in**の`drift` extraを追加したのみ。標準環境では新規インストールされない。
- `src/atlas_drift_monitor.py`: 全出走馬が揃ったレースの**確定後Brier損失**を、レース単位でADWINへ流す。勝率/連対率/複勝率を別検知。
- 非数値・結果未確定・タイムゾーン不明・未来情報混入・重複・出走馬不足はfail closed。
- 検出は「ドリフトの**兆候**」にすぎず、統計的真実・次回勝利・モデル昇格の根拠とはしない。
- 入力の発走前時刻は**宣言された情報**であり、この研究用モジュールだけでは本物の当時の証拠にはならない。FORWARDの凍結receipt/結果照合ゲートは別途必要。
- 返却は集計値とレース開始時刻のみ、馬ID・生データ・原本・トークンはレポートへ出さない。

### 次期実装順

1. **ORCHESTRA-001**: 既存`pipeline_orchestrator.py`, `autonomy_supervisor.py`を整理し、ジョブID・冪等性・権限・再開・失敗分類を一元化。自動生成コードの実行は隔離環境のみ。
2. **INGEST-001**: 承認ソースと権利契約ごとの取得を、新ATLAS DB/不変Parquetへ結ぶ。ソースごとの許可済み更新時刻を厳密に管理。
3. **DRIFT-002**: FORWARDで事前凍結を証明した予測＋確定結果だけをADWINに送る。欠損結果は学習対象から除外ではなく理由付き隔離。
4. **TECH-RADAR-002**: 新パッケージのリリース・脆弱性・ライセンス・性能と既存実装の重複を評価し、採否案をGitHub PRへ。依存更新は常にlock・CI・人間の許可を経る。

## 固定ルール

- Python API/外部サービスの費用上限・回数上限・利用許可を先に設定。
- Agents SDKのトレースは初期構成で機密入出力を含み得るので、利用するなら`RunConfig(trace_include_sensitive_data=False)`と明示した保護を前提にする。機密ソースをプロンプトやログへ流さない。
- Prefect等のサービス運用を開始しても古いworkerと二重起動しない。既存supervisorのネットワークbootstrapや自動実行の権限を見直してから。
- 著作権・独自契約・ソースの再配布条件を確認。既存`mykeibadb`と契約原本は保全。
- ビルド中のCIは合成データだけ。正常なCIはローカルDBやモデル品質の証明ではない。

## 公式参照（採用検討日2026-10-08）

- River: https://pypi.org/project/river/ （BSD-3-Clause）
- Prefect: https://pypi.org/project/prefect/ （Apache-2.0）
- Agents SDK: https://openai.github.io/openai-agents-python/
- Agents SDK sensitive tracing: https://openai.github.io/openai-agents-python/tracing/
- MLflow: https://www.mlflow.org/docs/latest/tracking/
- uv dependency management: https://docs.astral.sh/uv/concepts/dependencies/
- OpenTelemetry: https://opentelemetry.io/docs/languages/python/
- AI Scientist v2: https://github.com/SakanaAI/AI-Scientist-v2
