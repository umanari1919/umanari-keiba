$ErrorActionPreference = 'Stop'

$Root = if ($env:THE_JOCKEY_RESEARCH_ROOT) {
    $env:THE_JOCKEY_RESEARCH_ROOT
} else {
    Join-Path $HOME 'Downloads\THE-JOCKEY-RESEARCH'
}

$Server = Join-Path $Root 'dashboard_server.py'

if (-not (Test-Path $Server)) {
    throw "dashboard_server.py が見つかりません: $Server"
}

Write-Host ''
Write-Host '============================================================'
Write-Host ' THE JOCKEY 自律研究所 Dashboard'
Write-Host '============================================================'
Write-Host "Research Root : $Root"
Write-Host 'URL           : http://127.0.0.1:8791'
Write-Host ''

$env:THE_JOCKEY_RESEARCH_ROOT = $Root
py $Server
