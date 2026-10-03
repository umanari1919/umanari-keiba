$ErrorActionPreference = 'Stop'

$Root = if ($env:THE_JOCKEY_RESEARCH_ROOT) {
    $env:THE_JOCKEY_RESEARCH_ROOT
} else {
    Join-Path $HOME 'Downloads\THE-JOCKEY-RESEARCH'
}

New-Item -ItemType Directory -Force -Path $Root | Out-Null

$Base = 'https://raw.githubusercontent.com/umanari1919/umanari-keiba/main/tools/research_dashboard'

$Files = @(
    @{ Name = 'dashboard_server.py'; Url = "$Base/dashboard_server.py" },
    @{ Name = 'start-dashboard.ps1'; Url = "$Base/start-dashboard.ps1" },
    @{ Name = 'research_director.py'; Url = "$Base/research_director.py" },
    @{ Name = 'probability_director.py'; Url = "$Base/probability_director.py" },
    @{ Name = 'start-research-lab.ps1'; Url = "$Base/start-research-lab.ps1" },
    @{ Name = 'lab_updater.py'; Url = "$Base/lab_updater.py" }
)

foreach ($f in $Files) {
    $Out = Join-Path $Root $f.Name
    Invoke-WebRequest -Uri ($f.Url + "?nocache=" + [guid]::NewGuid()) -OutFile $Out -UseBasicParsing
    Write-Host "Installed: $Out"
}

Write-Host ''
Write-Host 'Autonomous Research Lab installed.'
Write-Host 'Self Update: ENABLED'
Write-Host 'Probability Pipeline: ENABLED'
Write-Host "Start with: $Root\start-research-lab.ps1"
Write-Host ''

Set-Location $Root
& .\start-research-lab.ps1
