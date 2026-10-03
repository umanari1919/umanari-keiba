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
    @{ Name = 'start-dashboard.ps1'; Url = "$Base/start-dashboard.ps1" }
)

foreach ($f in $Files) {
    $Out = Join-Path $Root $f.Name
    Invoke-WebRequest -Uri $f.Url -OutFile $Out -UseBasicParsing
    Write-Host "Installed: $Out"
}

Write-Host ''
Write-Host 'Dashboard installed.'
Write-Host "Start with: $Root\start-dashboard.ps1"
Write-Host ''

Set-Location $Root
& .\start-dashboard.ps1
