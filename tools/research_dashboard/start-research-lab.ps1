$ErrorActionPreference = 'Stop'
$Root = if ($env:THE_JOCKEY_RESEARCH_ROOT) { $env:THE_JOCKEY_RESEARCH_ROOT } else { Join-Path $HOME 'Downloads\THE-JOCKEY-RESEARCH' }
$env:THE_JOCKEY_RESEARCH_ROOT = $Root
$Workers = @(
    @{File='research_director.py'; Label='Research Director'},
    @{File='data_inventory_director.py'; Label='Data Inventory Director'},
    @{File='data_reconciliation_director.py'; Label='Data Reconciliation Director'},
    @{File='temporal_sample_optimizer.py'; Label='Temporal Optimizer'},
    @{File='universal_model_director.py'; Label='Universal Model Director'},
    @{File='probability_director.py'; Label='Probability Director'},
    @{File='meta_research_director.py'; Label='Meta Research Director'},
    @{File='feature_research_director.py'; Label='Feature Research Director'},
    @{File='experiment_director.py'; Label='Experiment Director'},
    @{File='hypothesis_generator.py'; Label='Hypothesis Generator'},
    @{File='domain_research_director.py'; Label='Domain Research Director'},
    @{File='ensemble_director.py'; Label='Ensemble Director'},
    @{File='autonomy_supervisor.py'; Label='Autonomy Supervisor'},
    @{File='lab_updater.py'; Label='Lab Updater'}
)
$Dashboard = Join-Path $Root 'dashboard_server.py'
foreach ($w in $Workers) { $w.Path = Join-Path $Root $w.File; if (-not (Test-Path $w.Path)) { throw "必要ファイルが見つかりません: $($w.Path)" } }
if (-not (Test-Path $Dashboard)) { throw "必要ファイルが見つかりません: $Dashboard" }
Write-Host ''
Write-Host '============================================================'
Write-Host ' THE JOCKEY 完全自律研究所'
Write-Host '============================================================'
Write-Host "Research Root : $Root"
Write-Host 'Population     : auto-audited'
Write-Host 'Reconciliation : autonomous / gated'
Write-Host 'Time Splits    : auto-optimized'
Write-Host 'Research       : autonomous'
Write-Host 'Experiments    : TURBO continuous'
Write-Host 'Hypotheses     : self-generating'
Write-Host 'Probability    : autonomous'
Write-Host 'JRA/NAR        : autonomous'
Write-Host 'Ensemble       : autonomous'
Write-Host 'Quality/Drift  : autonomous'
Write-Host 'Recovery       : autonomous'
Write-Host 'Self Update    : enabled'
Write-Host 'Dashboard      : http://127.0.0.1:8791'
Write-Host ''
foreach ($w in $Workers) {
    $existing = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like "*$($w.File)*" -and $_.ProcessId -ne $PID }
    if (-not $existing) { Start-Process -FilePath 'py' -ArgumentList @($w.Path) -WorkingDirectory $Root -WindowStyle Hidden; Write-Host ("{0,-30}: STARTED" -f $w.Label) }
    else { Write-Host ("{0,-30}: ALREADY RUNNING" -f $w.Label) }
}
py $Dashboard
