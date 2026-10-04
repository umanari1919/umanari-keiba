$ErrorActionPreference = 'Stop'
$Root = if ($env:THE_JOCKEY_RESEARCH_ROOT) { $env:THE_JOCKEY_RESEARCH_ROOT } else { Join-Path $HOME 'Downloads\THE-JOCKEY-RESEARCH' }
New-Item -ItemType Directory -Force -Path $Root | Out-Null
$Base = 'https://raw.githubusercontent.com/umanari1919/umanari-keiba/main/tools/research_dashboard'
$Names = @('dashboard_server.py','start-dashboard.ps1','foundation_selftest_director.py','dependency_guard.py','source_adapter_director.py','source_adapter_runtime.py','chunked_source_staging_director.py','staging_canonical_bridge.py','conflict_resolution_director.py','data_lineage.py','research_material_engine.py','mission_portfolio.py','canonical_store.py','modern_data_engine.py','modern_contracts.py','experiment_tracking.py','mlflow_mirror_director.py','research_director.py','data_inventory_director.py','canonicalization_director.py','data_reconciliation_director.py','temporal_sample_optimizer.py','universal_model_director.py','probability_director.py','race_simulation_director.py','decision_strategy_director.py','failure_analysis_director.py','meta_research_director.py','feature_research_director.py','experiment_director.py','hypothesis_generator.py','domain_research_director.py','ensemble_director.py','blind_evaluation_director.py','schema_contract_director.py','resource_manager_director.py','leakage_guard_director.py','backup_rollback_director.py','pipeline_orchestrator.py','chief_operating_director.py','autonomy_supervisor.py','start-research-lab.ps1','lab_updater.py')
foreach ($Name in $Names) {
    $Out = Join-Path $Root $Name
    $Uri = "${Base}/${Name}?nocache=$([guid]::NewGuid())"
    Invoke-WebRequest -Uri $Uri -OutFile $Out -UseBasicParsing
    Write-Host "Installed: $Out"
}
Write-Host ''
Write-Host 'THE JOCKEY Portfolio-Governed Autonomous Research Lab installed.'
Write-Host 'Research Material     : AUTO DISCOVERY FROM EVIDENCE'
Write-Host 'Mission Portfolio     : AUTO PRIORITY / NEXT MISSION / WORKER FOCUS'
Write-Host 'Source Adapter        : POSTGRES/MYSQL READ-ONLY DISCOVERY / NO GUESSING'
Write-Host 'Source Staging        : ON-DEMAND / CHUNKED / RESUMABLE / SHA256'
Write-Host 'Canonical Bridge      : ON-DEMAND / NEW-DUPLICATE-CONFLICT CLASSIFICATION'
Write-Host 'Conflict Resolver     : ON-DEMAND / EVIDENCE-BASED / NO AUTO OVERWRITE'
Write-Host 'Data Lineage          : APPEND-ONLY / SHA256 / SOURCE→CANONICAL TRACE'
Write-Host 'Immutable Canonical   : PARQUET / MANIFEST / ATOMIC POINTER / ROLLBACK'
Write-Host 'Pipeline Orchestrator : PORTFOLIO-DRIVEN'
Write-Host 'Chief Operating       : EXECUTIVE PORTFOLIO MODE'
Write-Host 'Production Gate       : ENABLED (prediction models only)'
Write-Host "Start with: $Root\start-research-lab.ps1"
Set-Location $Root
& .\start-research-lab.ps1
