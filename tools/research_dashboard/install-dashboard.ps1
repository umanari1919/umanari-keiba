$ErrorActionPreference = 'Stop'
$Root = if ($env:THE_JOCKEY_RESEARCH_ROOT) { $env:THE_JOCKEY_RESEARCH_ROOT } else { Join-Path $HOME 'Downloads\THE-JOCKEY-RESEARCH' }
New-Item -ItemType Directory -Force -Path $Root | Out-Null
$Base = 'https://raw.githubusercontent.com/umanari1919/umanari-keiba/main/tools/research_dashboard'
$Names = @('dashboard_server.py','start-dashboard.ps1','foundation_selftest_director.py','research_director.py','data_inventory_director.py','canonicalization_director.py','data_reconciliation_director.py','temporal_sample_optimizer.py','universal_model_director.py','probability_director.py','race_simulation_director.py','decision_strategy_director.py','failure_analysis_director.py','meta_research_director.py','feature_research_director.py','experiment_director.py','hypothesis_generator.py','domain_research_director.py','ensemble_director.py','blind_evaluation_director.py','schema_contract_director.py','resource_manager_director.py','leakage_guard_director.py','backup_rollback_director.py','pipeline_orchestrator.py','chief_operating_director.py','autonomy_supervisor.py','start-research-lab.ps1','lab_updater.py')
foreach ($Name in $Names) {
    $Out = Join-Path $Root $Name
    $Uri = "${Base}/${Name}?nocache=$([guid]::NewGuid())"
    Invoke-WebRequest -Uri $Uri -OutFile $Out -UseBasicParsing
    Write-Host "Installed: $Out"
}
Write-Host ''
Write-Host 'THE JOCKEY Foundation-Hardened Autonomous Research Lab installed.'
Write-Host 'Foundation Self-Test  : ENABLED'
Write-Host 'Canonicalization      : ENABLED / CONTRACT-GATED'
Write-Host 'Self Update           : ENABLED'
Write-Host 'Auto Recovery         : ENABLED'
Write-Host 'Schema Contract       : ENFORCED'
Write-Host 'Leakage Guard         : ENFORCED'
Write-Host 'Resource Governor     : ENABLED'
Write-Host 'Pipeline Orchestrator : ENABLED'
Write-Host 'Backup Snapshot       : ENABLED'
Write-Host 'Chief Operating       : ENABLED'
Write-Host 'Population Audit      : ENABLED'
Write-Host 'Data Reconciliation   : ENABLED (gated)'
Write-Host 'Temporal Optimization : ENABLED'
Write-Host 'Continuous Experiments: GOVERNED TURBO'
Write-Host 'Race Simulation       : ENABLED / FRAME INCLUDED'
Write-Host 'Decision Strategy     : ENABLED / MIN-1 MIN-2 MIN-3'
Write-Host 'Failure Analysis      : ENABLED / WHY-IT-LOST'
Write-Host 'Forward Blind Test    : ENABLED / SHA256 SEALED'
Write-Host 'Production Gate       : ENABLED (prediction models only)'
Write-Host "Start with: $Root\start-research-lab.ps1"
Set-Location $Root
& .\start-research-lab.ps1
