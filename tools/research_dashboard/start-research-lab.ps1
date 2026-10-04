$ErrorActionPreference = 'Stop'
$Root = if ($env:THE_JOCKEY_RESEARCH_ROOT) { $env:THE_JOCKEY_RESEARCH_ROOT } else { Join-Path $HOME 'Downloads\THE-JOCKEY-RESEARCH' }
$env:THE_JOCKEY_RESEARCH_ROOT = $Root
$Workers = @(
    @{File='foundation_selftest_director.py'; Label='Foundation Self-Test'},
    @{File='dependency_guard.py'; Label='Dependency Guard'},
    @{File='source_adapter_director.py'; Label='Source Adapter Director'},
    @{File='source_staging_director.py'; Label='Source Staging Director (Portfolio Managed)'},
    @{File='data_inventory_director.py'; Label='Data Inventory Director'},
    @{File='canonicalization_director.py'; Label='Canonicalization Director'},
    @{File='data_reconciliation_director.py'; Label='Data Reconciliation Director'},
    @{File='research_director.py'; Label='Research Director'},
    @{File='temporal_sample_optimizer.py'; Label='Temporal Optimizer'},
    @{File='universal_model_director.py'; Label='Universal Model Director'},
    @{File='probability_director.py'; Label='Probability Director'},
    @{File='race_simulation_director.py'; Label='Race Simulation / Fair Odds'},
    @{File='decision_strategy_director.py'; Label='Decision Strategy Director'},
    @{File='failure_analysis_director.py'; Label='Failure Analysis Director'},
    @{File='meta_research_director.py'; Label='Meta Research Director'},
    @{File='feature_research_director.py'; Label='Feature Research Director'},
    @{File='experiment_director.py'; Label='Experiment Director'},
    @{File='hypothesis_generator.py'; Label='Hypothesis Generator / Optuna Advisor'},
    @{File='mlflow_mirror_director.py'; Label='MLflow Mirror (Optional)'},
    @{File='domain_research_director.py'; Label='Domain Research Director'},
    @{File='ensemble_director.py'; Label='Ensemble Director'},
    @{File='blind_evaluation_director.py'; Label='Blind Evaluation Director'},
    @{File='chief_operating_director.py'; Label='Chief Operating Director'},
    @{File='autonomy_supervisor.py'; Label='Autonomy Supervisor'},
    @{File='lab_updater.py'; Label='Lab Updater'}
)
$RequiredModules = @('source_adapter_runtime.py','source_staging_runtime.py','research_material_engine.py','mission_portfolio.py','canonical_store.py','modern_data_engine.py','modern_contracts.py','experiment_tracking.py','schema_contract_director.py','resource_manager_director.py','leakage_guard_director.py','backup_rollback_director.py','pipeline_orchestrator.py')
$Dashboard = Join-Path $Root 'dashboard_server.py'
foreach ($w in $Workers) { $w.Path = Join-Path $Root $w.File; if (-not (Test-Path $w.Path)) { throw "必要ファイルが見つかりません: $($w.Path)" } }
foreach ($m in $RequiredModules) { if (-not (Test-Path (Join-Path $Root $m))) { throw "統制/高速化モジュールが見つかりません: $m" } }
if (-not (Test-Path $Dashboard)) { throw "必要ファイルが見つかりません: $Dashboard" }
Write-Host ''
Write-Host '============================================================'
Write-Host ' THE JOCKEY 完全自律研究所 — PORTFOLIO GOVERNANCE MODE'
Write-Host '============================================================'
Write-Host "Research Root : $Root"
Write-Host ('uv               : ' + $(if (Get-Command uv -ErrorAction SilentlyContinue) { 'AVAILABLE' } else { 'NOT INSTALLED / FALLBACK' }))
Write-Host 'Foundation Test  : compile / worker coverage / writable dirs'
Write-Host 'Research Material: evidence-driven automatic discovery'
Write-Host 'Mission Portfolio: automatic priority / next mission / worker focus'
Write-Host 'Dependency Guard : stable versions / no auto-upgrade'
Write-Host 'Source Adapter   : PostgreSQL/MySQL READ-ONLY discovery / NO GUESSING'
Write-Host 'Source Staging   : chunked / resumable / checksum / Parquet / Chief-controlled'
Write-Host 'Data Engine      : DuckDB / Polars / Arrow optional acceleration'
Write-Host 'Canonical Store  : immutable Parquet / manifest / rollback'
Write-Host 'Data Contracts   : Pydantic / Pandera optional strengthening'
Write-Host 'Optuna Advisor   : selection-only TPE / manual fallback'
Write-Host 'MLflow Mirror    : optional / CSV ledger remains source of truth'
Write-Host 'Data Control     : discovery / staging / inventory / canonicalization / reconciliation'
Write-Host 'Schema Contract  : enforced'
Write-Host 'Time Splits      : auto-optimized'
Write-Host 'Research         : portfolio-driven / autonomous / orchestrated'
Write-Host 'Experiments      : focused TURBO with resource governor'
Write-Host 'Simulation       : finish distribution / fair odds / FRAME'
Write-Host 'Strategy         : MIN-1 / MIN-2 / MIN-3; JRA/NAR separated'
Write-Host 'Failure Analysis : prediction / decision / pruning / variance'
Write-Host 'Blind Test       : FORWARD / SHA256 SEALED'
Write-Host 'Leakage Guard    : enforced'
Write-Host 'Backup           : daily governance snapshot'
Write-Host 'Chief Operating  : portfolio executive mode'
Write-Host 'Recovery         : autonomous'
Write-Host 'Self Update      : enabled'
Write-Host 'Dashboard        : http://127.0.0.1:8791'
Write-Host ''
foreach ($w in $Workers) {
    $existing = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like "*$($w.File)*" -and $_.ProcessId -ne $PID }
    if (-not $existing) { Start-Process -FilePath 'py' -ArgumentList @($w.Path) -WorkingDirectory $Root -WindowStyle Hidden; Write-Host ("{0,-34}: STARTED" -f $w.Label) }
    else { Write-Host ("{0,-34}: ALREADY RUNNING" -f $w.Label) }
}
py $Dashboard
