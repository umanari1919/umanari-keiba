$ErrorActionPreference = 'Stop'

$Root = if ($env:THE_JOCKEY_RESEARCH_ROOT) {
    $env:THE_JOCKEY_RESEARCH_ROOT
} else {
    Join-Path $HOME 'Downloads\THE-JOCKEY-RESEARCH'
}

$Director = Join-Path $Root 'research_director.py'
$Dashboard = Join-Path $Root 'dashboard_server.py'

if (-not (Test-Path $Director)) { throw "research_director.py が見つかりません: $Director" }
if (-not (Test-Path $Dashboard)) { throw "dashboard_server.py が見つかりません: $Dashboard" }

$env:THE_JOCKEY_RESEARCH_ROOT = $Root

Write-Host ''
Write-Host '============================================================'
Write-Host ' THE JOCKEY 自律研究所'
Write-Host '============================================================'
Write-Host "Research Root : $Root"
Write-Host 'Director      : autonomous'
Write-Host 'Dashboard     : http://127.0.0.1:8791'
Write-Host ''

$Existing = Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -like '*research_director.py*' -and $_.ProcessId -ne $PID
}

if (-not $Existing) {
    Start-Process -FilePath 'py' -ArgumentList @($Director) -WorkingDirectory $Root -WindowStyle Hidden
    Write-Host 'Research Director : STARTED'
} else {
    Write-Host 'Research Director : ALREADY RUNNING'
}

py $Dashboard
