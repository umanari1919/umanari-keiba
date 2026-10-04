$ErrorActionPreference = 'Stop'
$Root = if ($env:THE_JOCKEY_RESEARCH_ROOT) { $env:THE_JOCKEY_RESEARCH_ROOT } else { Join-Path $HOME 'Downloads\THE-JOCKEY-RESEARCH' }
$env:THE_JOCKEY_RESEARCH_ROOT = $Root
$Workers = @(
    @{File='foundation_selftest_director.py'; Label='Foundation Self-Test'},
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
    @{File='hypothesis_generator.py'; Label='Hypothesis Generator'},
    @{File='domain_research_director.py'; Label='Domain Research Director'},
    @{File='ensemble_director.py'; Label='Ensemble Director'},
    @{File='blind_evaluation_director.py'; Label='Blind Evaluation Director'},
    @{File='chief_operating_director.py'; Label='Chief Operating Director'},
    @{File='autonomy_supervisor.py'; Label='Autonomy Supervisor'},
    @{File='lab_updater.py'; Label='Lab Updater'}
)
$RequiredModules = @('schema_contract_director.py','resource_manager_director.py','leakage_guard_director.py','backup_rollback_director.py','pipeline_orchestrator.py')
$Dashboard = Join-Path $Root 'dashboard_server.py'
foreach ($w in $Workers) { $w.Path = Join-Path $Root $w.File; if (-not (Test-Path $w.Path)) { throw "必要ファイルが見つかりません: $($w.Path)" } }
foreach ($m in $RequiredModules) { if (-not (Test-Path (Join-Path $Root $m))) { throw "統制モジュールが見つかりません: $m" } }
if (-not (Test-Path $Dashboard)) { throw "必要ファイルが見つかりません: $Dashboard" }
Write-Host ''
Write-Host '============================================================'
Write-Host ' THE JOCKEY 完全自律研究所 — FOUNDATION HARDENED MODE'
Write-Host '============================================================'
Write-Host "Research Root : $Root"
Write-Host 'Foundation Test : compile / worker coverage / writable dirs'
Write-Host 'Data Control     : inventory / canonicalization / reconciliation'
Write-Host 'Schema Contract  : enforced'
Write-Host 'Time Splits      : auto-optimized'
Write-Host 'Research         : autonomous / orchestrated'
Write-Host 'Experiments      : TURBO with resource governor'
Write-Host 'Simulation       : finish distribution / fair odds / FRAME'
Write-Host 'Strategy         : MIN-1 / MIN-2 / MIN-3; JRA/NAR separated'
Write-Host 'Failure Analysis : prediction / decision / pruning / variance'
Write-Host 'Blind Test       : FORWARD / SHA256 SEALED'
Write-Host 'Leakage Guard    : enforced'
Write-Host 'Backup           : daily governance snapshot'
Write-Host 'Chief Operating  : enabled'
Write-Host 'Recovery         : autonomous'
Write-Host 'Self Update      : enabled'
Write-Host 'Dashboard        : http://127.0.0.1:8791'
Write-Host ''
foreach ($w in $Workers) {
    $existing = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like "*$($w.File)*" -and $_.ProcessId -ne $PID }
    if (-not $existing) { Start-Process -FilePath 'py' -ArgumentList @($w.Path) -WorkingDirectory $Root -WindowStyle Hidden; Write-Host ("{0,-30}: STARTED" -f $w.Label) }
    else { Write-Host ("{0,-30}: ALREADY RUNNING" -f $w.Label) }
}
py $Dashboard
