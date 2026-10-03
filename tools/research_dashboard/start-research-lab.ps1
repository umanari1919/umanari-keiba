$ErrorActionPreference = 'Stop'

$Root = if ($env:THE_JOCKEY_RESEARCH_ROOT) {
    $env:THE_JOCKEY_RESEARCH_ROOT
} else {
    Join-Path $HOME 'Downloads\THE-JOCKEY-RESEARCH'
}

$Director = Join-Path $Root 'research_director.py'
$ProbabilityDirector = Join-Path $Root 'probability_director.py'
$Dashboard = Join-Path $Root 'dashboard_server.py'
$Updater = Join-Path $Root 'lab_updater.py'

if (-not (Test-Path $Director)) { throw "research_director.py が見つかりません: $Director" }
if (-not (Test-Path $ProbabilityDirector)) { throw "probability_director.py が見つかりません: $ProbabilityDirector" }
if (-not (Test-Path $Dashboard)) { throw "dashboard_server.py が見つかりません: $Dashboard" }
if (-not (Test-Path $Updater)) { throw "lab_updater.py が見つかりません: $Updater" }

$env:THE_JOCKEY_RESEARCH_ROOT = $Root

Write-Host ''
Write-Host '============================================================'
Write-Host ' THE JOCKEY 自律研究所'
Write-Host '============================================================'
Write-Host "Research Root : $Root"
Write-Host 'Director      : autonomous'
Write-Host 'Probability   : autonomous'
Write-Host 'Self Update   : enabled'
Write-Host 'Dashboard     : http://127.0.0.1:8791'
Write-Host ''

function Start-WorkerIfMissing {
    param(
        [string]$Pattern,
        [string]$Script,
        [string]$Label
    )

    $Existing = Get-CimInstance Win32_Process | Where-Object {
        $_.CommandLine -like "*$Pattern*" -and $_.ProcessId -ne $PID
    }

    if (-not $Existing) {
        Start-Process -FilePath 'py' -ArgumentList @($Script) -WorkingDirectory $Root -WindowStyle Hidden
        Write-Host ("{0,-24}: STARTED" -f $Label)
    } else {
        Write-Host ("{0,-24}: ALREADY RUNNING" -f $Label)
    }
}

Start-WorkerIfMissing 'research_director.py' $Director 'Research Director'
Start-WorkerIfMissing 'probability_director.py' $ProbabilityDirector 'Probability Director'
Start-WorkerIfMissing 'lab_updater.py' $Updater 'Lab Updater'

py $Dashboard
