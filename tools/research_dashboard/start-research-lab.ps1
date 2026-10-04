$ErrorActionPreference = 'Stop'
$Root = if ($env:THE_JOCKEY_RESEARCH_ROOT) { $env:THE_JOCKEY_RESEARCH_ROOT } else { Join-Path $HOME 'Downloads\THE-JOCKEY-RESEARCH' }
$env:THE_JOCKEY_RESEARCH_ROOT = $Root
$Workers = @(
    @{File='foundation_selftest_director.py'; Label='Foundation Self-Test'},
    @{File='dependency_guard.py'; Label='Dependency Guard'},
    @{File='source_adapter_director.py'; Label='Source Adapter Director'},
    @{File='data_inventory_director.py'; Label='Data Inventory Director'},
    @{File='canonicalization_director.py'; Label='Canonicalization Director'},
    @{File='data_reconciliation_director.py'; Label='Data Reconciliation Director'},
    @{File='research_factory_director.py'; Label='Research Factory / 研究素材創出'},
    @{File='research_brief_director.py'; Label='Research Brief / 研究計画固定'},
    @{File='research_cycle_director.py'; Label='Research Cycle / 研究閉ループ'},
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
$RequiredModules = @('source_adapter_runtime.py','chunked_source_staging_director.py','staging_canonical_bridge.py','conflict_resolution_director.py','data_lineage.py','research_model_search_seed.py','research_cycle_material.py','research_execution_binding.py','research_material_engine.py','mission_portfolio.py','canonical_store.py','modern_data_engine.py','modern_contracts.py','experiment_tracking.py','schema_contract_director.py','resource_manager_director.py','leakage_guard_director.py','backup_rollback_director.py','pipeline_orchestrator.py')
$Dashboard = Join-Path $Root 'dashboard_server.py'
foreach ($w in $Workers) { $w.Path = Join-Path $Root $w.File; if (-not (Test-Path $w.Path)) { throw "必要ファイルが見つかりません: $($w.Path)" } }
foreach ($m in $RequiredModules) { if (-not (Test-Path (Join-Path $Root $m))) { throw "統制/高速化モジュールが見つかりません: $m" } }
if (-not (Test-Path $Dashboard)) { throw "必要ファイルが見つかりません: $Dashboard" }
Write-Host ''
Write-Host '============================================================'
Write-Host ' THE JOCKEY 完全自律研究所 — RESEARCH CLOSED LOOP MODE'
Write-Host '============================================================'
Write-Host "Research Root : $Root"
Write-Host 'Research Factory : evidence-gated idea generation / READY vs NEEDS_DATA'
Write-Host 'Research Brief   : freeze objective / population / metrics / stop / Blind gate before execution'
Write-Host 'Execution Binding: explicit brief_id -> worker result attribution'
Write-Host 'Research Cycle   : result decision -> next hypothesis / Blind, TEST-OOS feedback prohibited'
Write-Host 'Research Material: evidence-driven automatic discovery'
Write-Host 'Mission Portfolio: automatic priority / next mission / worker focus'
Write-Host 'Source Adapter   : PostgreSQL/MySQL READ-ONLY discovery / NO GUESSING'
Write-Host 'Source Staging   : ON-DEMAND / CHUNKED / RESUMABLE / SHA256'
Write-Host 'Canonical Bridge : ON-DEMAND / NEW-DUPLICATE-CONFLICT CLASSIFICATION'
Write-Host 'Conflict Resolver: ON-DEMAND / EVIDENCE-BASED / NO AUTO OVERWRITE'
Write-Host 'Data Lineage     : APPEND-ONLY / SHA256 / SOURCE→CANONICAL TRACE'
Write-Host 'Canonical Store  : immutable Parquet / manifest / rollback'
Write-Host 'Chief Operating  : portfolio executive mode'
Write-Host 'Dashboard        : http://127.0.0.1:8791'
Write-Host ''
foreach ($w in $Workers) {
    $existing = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like "*$($w.File)*" -and $_.ProcessId -ne $PID }
    if (-not $existing) { Start-Process -FilePath 'py' -ArgumentList @($w.Path) -WorkingDirectory $Root -WindowStyle Hidden; Write-Host ("{0,-38}: STARTED" -f $w.Label) }
    else { Write-Host ("{0,-38}: ALREADY RUNNING" -f $w.Label) }
}
py $Dashboard
