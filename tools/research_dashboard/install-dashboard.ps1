$ErrorActionPreference = 'Stop'
$Root = if ($env:THE_JOCKEY_RESEARCH_ROOT) { $env:THE_JOCKEY_RESEARCH_ROOT } else { Join-Path $HOME 'Downloads\THE-JOCKEY-RESEARCH' }
New-Item -ItemType Directory -Force -Path $Root | Out-Null
$Base = 'https://raw.githubusercontent.com/umanari1919/umanari-keiba/main/tools/research_dashboard'
$Names = @('dashboard_server.py','start-dashboard.ps1','research_director.py','temporal_sample_optimizer.py','universal_model_director.py','probability_director.py','meta_research_director.py','feature_research_director.py','experiment_director.py','hypothesis_generator.py','domain_research_director.py','ensemble_director.py','autonomy_supervisor.py','start-research-lab.ps1','lab_updater.py')
foreach ($Name in $Names) {
    $Out = Join-Path $Root $Name
    $Uri = "${Base}/${Name}?nocache=$([guid]::NewGuid())"
    Invoke-WebRequest -Uri $Uri -OutFile $Out -UseBasicParsing
    Write-Host "Installed: $Out"
}
Write-Host ''
Write-Host 'THE JOCKEY Complete Autonomous Research Lab installed.'
Write-Host 'Self Update           : ENABLED'
Write-Host 'Auto Recovery         : ENABLED'
Write-Host 'Population Audit      : ENABLED'
Write-Host 'Temporal Optimization : ENABLED'
Write-Host 'Walk Forward Plan     : ENABLED'
Write-Host 'Continuous Experiments: TURBO'
Write-Host 'Hypothesis Generation : ENABLED'
Write-Host 'Data Quality          : ENABLED'
Write-Host 'Drift Detection       : ENABLED'
Write-Host 'Feature Research      : ENABLED'
Write-Host 'Universal Model       : ADAPTIVE SPLITS'
Write-Host 'JRA/NAR Specialists   : ADAPTIVE SPLITS'
Write-Host 'Ensemble Research     : ADAPTIVE SPLITS'
Write-Host 'Production Gate       : ENABLED (prediction models only)'
Write-Host "Start with: $Root\start-research-lab.ps1"
Set-Location $Root
& .\start-research-lab.ps1
