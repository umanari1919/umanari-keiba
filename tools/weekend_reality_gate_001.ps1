#Requires -Version 7.2
[CmdletBinding()]
param(
    [string]$RepoPath = '',
    [switch]$SelfTest,
    [switch]$DiagnoseLatest
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ReplayCommit = 'e75691d2ebae2d67fe633e042010d3ed02755403'
$ReplayUrl = "https://raw.githubusercontent.com/umanari1919/umanari-keiba/$ReplayCommit/src/weekend_replay.py"

function Resolve-Workspace {
    param([string]$Requested)

    $candidates = [System.Collections.Generic.List[string]]::new()
    if ($Requested) { $candidates.Add($Requested) }
    if ($env:NEO_JIZO_KEIBA_ROOT) { $candidates.Add($env:NEO_JIZO_KEIBA_ROOT) }
    if ($env:USERPROFILE) {
        $candidates.Add((Join-Path $env:USERPROFILE 'Documents/Codex/2026-10-06/new-chat/neo-jizo-keiba'))
    }

    foreach ($candidate in ($candidates | Select-Object -Unique)) {
        if (-not $candidate) { continue }
        if (-not (Test-Path -LiteralPath $candidate -PathType Container)) { continue }
        $root = (Resolve-Path -LiteralPath $candidate).Path
        if (
            (Test-Path -LiteralPath (Join-Path $root 'src/weekend_source_status.py') -PathType Leaf) -and
            (Test-Path -LiteralPath (Join-Path $root 'src/weekend_personal_forecast.py') -PathType Leaf) -and
            (Test-Path -LiteralPath (Join-Path $root 'src/refresh_prospective_history.py') -PathType Leaf)
        ) {
            return $root
        }
    }
    throw 'NEO JIZO KEIBA workspace with weekend runtime files was not found.'
}

function Resolve-Python {
    param([string]$Root)

    $candidates = @(
        (Join-Path $Root '.venv/Scripts/python.exe'),
        (Join-Path $Root '.venv/bin/python'),
        'python'
    )
    foreach ($candidate in $candidates) {
        if ($candidate -eq 'python') {
            $cmd = Get-Command python -ErrorAction SilentlyContinue
            if ($cmd) { return $cmd.Source }
        }
        elseif (Test-Path -LiteralPath $candidate -PathType Leaf) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }
    throw 'Python runtime was not found (.venv or PATH).'
}

function Invoke-PythonStep {
    param(
        [string]$Name,
        [string]$Python,
        [string]$Script,
        [string]$WorkingDirectory
    )

    $started = Get-Date
    $output = @()
    $code = 1
    try {
        Push-Location $WorkingDirectory
        try {
            $output = @(& $Python -X utf8 -B $Script 2>&1 | ForEach-Object { "$_" })
            $code = $LASTEXITCODE
        }
        finally {
            Pop-Location
        }
    }
    catch {
        $output += "EXCEPTION: $($_.Exception.Message)"
        $code = 1
    }

    [pscustomobject]@{
        Name = $Name
        ExitCode = [int]$code
        StartedAt = $started
        FinishedAt = Get-Date
        Output = @($output)
    }
}

function Read-FreshJson {
    param(
        [string]$Path,
        [datetime]$NotBefore
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $null }
    $item = Get-Item -LiteralPath $Path
    if ($item.LastWriteTime -lt $NotBefore.AddSeconds(-3)) { return $null }
    try {
        return Get-Content -LiteralPath $Path -Raw -Encoding utf8 | ConvertFrom-Json
    }
    catch {
        return $null
    }
}

function To-CompactBlockers {
    param($Personal)
    if ($null -eq $Personal -or $null -eq $Personal.input_checks -or $null -eq $Personal.input_checks.blocker_counts) {
        return '(none reported)'
    }
    $pairs = @()
    foreach ($property in $Personal.input_checks.blocker_counts.PSObject.Properties) {
        $pairs += "$($property.Name)=$($property.Value)"
    }
    if ($pairs.Count) {
        return ($pairs -join ', ')
    }
    return '(none)'
}


function Get-FailureClass {
    param([string[]]$Lines)

    $text = ($Lines -join [Environment]::NewLine)
    if ($text -match '(?i)(connection refused|could not connect|server.*not running|No connection could be made)') { return 'DB_CONNECTION' }
    if ($text -match '(?i)(password authentication failed|no password supplied|fe_sendauth|authentication failed)') { return 'DB_AUTH' }
    if ($text -match '(?i)(psql.*not found|No such file or directory|WinError 2|cannot find the file)') { return 'PSQL_NOT_FOUND' }
    if ($text -match '(?i)(relation .* does not exist|undefined table)') { return 'TABLE_MISSING' }
    if ($text -match '(?i)(column .* does not exist|undefined column)') { return 'COLUMN_MISSING' }
    if ($text -match '(?i)(statement timeout|canceling statement due to statement timeout|TimeoutExpired)') { return 'DB_TIMEOUT' }
    if ($text -match '(?i)(JSONDecodeError|Expecting value)') { return 'DB_OUTPUT_NOT_JSON' }
    if ($text -match '(?i)(FileNotFoundError|ModuleNotFoundError|ImportError)') { return 'LOCAL_RUNTIME_DEPENDENCY' }
    return 'UNKNOWN'
}

function New-GateSummary {
    param(
        [string]$Root,
        [object[]]$Steps,
        $Source,
        $Replay,
        $History,
        $Personal
    )

    $sourceReadOnly = $false
    if ($null -ne $Source -and $null -ne $Source.read_only) {
        $values = @($Source.read_only.PSObject.Properties | ForEach-Object { "$($_.Value)" })
        $sourceReadOnly = ($values.Count -gt 0 -and @($values | Where-Object { $_ -ne 'on' }).Count -eq 0)
    }

    [pscustomobject]@{
        mission = 'WEEKEND-REALITY-GATE-001'
        observed_at = (Get-Date).ToString('o')
        repo_path = $Root
        steps = @($Steps | ForEach-Object {
            $tail = @($_.Output | Select-Object -Last 12)
            [pscustomobject]@{
                name = $_.Name
                exit_code = $_.ExitCode
                failure_class = if ($_.ExitCode -eq 0) { 'NONE' } else { Get-FailureClass -Lines $tail }
                output_tail = $tail
            }
        })
        db_read_only = $sourceReadOnly
        source_state = if ($Source) { "$($Source.state)" } else { 'UNAVAILABLE' }
        confirmed_runner_rows = if ($Source) { [int]$Source.confirmed_runner_rows } else { $null }
        special_registration_rows = if ($Source) { [int]$Source.special_registration_rows } else { $null }
        replay_state = if ($Replay) { "$($Replay.state)" } else { 'UNAVAILABLE' }
        replay_races = if ($Replay) { [int]$Replay.predicted_races } else { $null }
        replay_runners = if ($Replay) { [int]$Replay.predicted_runners } else { $null }
        replay_result_states = if ($Replay) { $Replay.result_states } else { $null }
        history_snapshot_through = if ($History) { "$($History.snapshot_through)" } else { $null }
        history_learned_rows = if ($History -and $null -ne $History.learned_rows) { [int]$History.learned_rows } else { $null }
        history_empty_source_interval = if ($History -and $null -ne $History.empty_source_interval) { [bool]$History.empty_source_interval } else { $null }
        personal_state = if ($Personal) { "$($Personal.state)" } else { 'UNAVAILABLE' }
        personal_predicted_races = if ($Personal) { [int]$Personal.predicted_races } else { $null }
        personal_predicted_runners = if ($Personal) { [int]$Personal.predicted_runners } else { $null }
        personal_blockers = To-CompactBlockers $Personal
        automatic_betting = $false
        production_promotion = $false
    }
}


function Show-LatestFailureDiagnostics {
    $tempRoot = Join-Path ([IO.Path]::GetTempPath()) 'neo-jizo-weekend-reality'
    $latest = Get-ChildItem -LiteralPath $tempRoot -Filter 'WEEKEND-REALITY-GATE-001-*.json' -File -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if (-not $latest) {
        throw 'No previous WEEKEND-REALITY-GATE-001 JSON report was found.'
    }

    $report = Get-Content -LiteralPath $latest.FullName -Raw -Encoding utf8 | ConvertFrom-Json
    Write-Host ''
    Write-Host '============================================================' -ForegroundColor Cyan
    Write-Host ' WEEKEND-REALITY-GATE-001 FAILURE DIAGNOSTICS' -ForegroundColor Cyan
    Write-Host '============================================================' -ForegroundColor Cyan
    Write-Host "Report : $($latest.FullName)"
    Write-Host ''
    $failed = @($report.steps | Where-Object { [int]$_.exit_code -ne 0 })
    if (-not $failed.Count) {
        Write-Host 'No failed steps in the latest report.' -ForegroundColor Green
        return
    }
    foreach ($step in $failed) {
        $tail = @($step.output_tail | ForEach-Object { "$_" })
        $class = Get-FailureClass -Lines $tail
        Write-Host ("{0}: [{1}]" -f $step.name, $class) -ForegroundColor Yellow
        foreach ($line in @($tail | Select-Object -Last 8)) {
            Write-Host ("  " + $line)
        }
        Write-Host ''
    }
}

function Invoke-SelfTest {
    $steps = @(
        [pscustomobject]@{ Name='source'; ExitCode=1; Output=@('psql: error: connection to server at "127.0.0.1", port 5433 failed: Connection refused') },
        [pscustomobject]@{ Name='replay'; ExitCode=0; Output=@('ok') }
    )
    $source = [pscustomobject]@{
        state='awaiting_confirmed_race_cards'
        confirmed_runner_rows=0
        special_registration_rows=92
        read_only=[pscustomobject]@{ transaction_read_only='on'; default_transaction_read_only='on' }
    }
    $replay = [pscustomobject]@{ state='replay_completed'; predicted_races=24; predicted_runners=360; result_states=[pscustomobject]@{scored=24} }
    $history = [pscustomobject]@{ snapshot_through='20261006'; learned_rows=0; empty_source_interval=$true }
    $personal = [pscustomobject]@{
        state='awaiting_confirmed_race_cards'
        predicted_races=0
        predicted_runners=0
        input_checks=[pscustomobject]@{blocker_counts=[pscustomobject]@{}}
    }
    $summary = New-GateSummary -Root 'X:\neo-jizo-keiba' -Steps $steps -Source $source -Replay $replay -History $history -Personal $personal
    if (-not $summary.db_read_only) { throw 'Expected read-only summary.' }
    if ($summary.replay_races -ne 24) { throw 'Expected replay race count.' }
    if ($summary.personal_predicted_races -ne 0) { throw 'Expected zero personal forecasts.' }
    if ($summary.source_state -ne 'awaiting_confirmed_race_cards') { throw 'Expected source waiting state.' }
    if ($summary.steps[0].failure_class -ne 'DB_CONNECTION') { throw 'Expected DB_CONNECTION classification.' }
    Write-Host 'WEEKEND-REALITY-GATE-001 self-test PASS'
}

if ($SelfTest) {
    Invoke-SelfTest
    exit 0
}

if ($DiagnoseLatest) {
    Show-LatestFailureDiagnostics
    exit 0
}

$root = Resolve-Workspace -Requested $RepoPath
$python = Resolve-Python -Root $root
$gateStarted = Get-Date

$tempRoot = Join-Path ([IO.Path]::GetTempPath()) 'neo-jizo-weekend-reality'
New-Item -ItemType Directory -Force -Path $tempRoot | Out-Null
$replayScript = Join-Path $tempRoot 'weekend_replay.py'
Invoke-WebRequest -Uri $ReplayUrl -OutFile $replayScript

$oldPythonPath = $env:PYTHONPATH
$env:PYTHONPATH = Join-Path $root 'src'
try {
    $steps = [System.Collections.Generic.List[object]]::new()
    $steps.Add((Invoke-PythonStep -Name 'weekend-source-status' -Python $python -Script (Join-Path $root 'src/weekend_source_status.py') -WorkingDirectory $root))
    $steps.Add((Invoke-PythonStep -Name 'historical-replay-20261003-04' -Python $python -Script $replayScript -WorkingDirectory $root))
    $steps.Add((Invoke-PythonStep -Name 'history-refresh' -Python $python -Script (Join-Path $root 'src/refresh_prospective_history.py') -WorkingDirectory $root))
    $steps.Add((Invoke-PythonStep -Name 'weekend-engine-check' -Python $python -Script (Join-Path $root 'src/weekend_engine_check.py') -WorkingDirectory $root))
    $steps.Add((Invoke-PythonStep -Name 'weekend-personal-forecast' -Python $python -Script (Join-Path $root 'src/weekend_personal_forecast.py') -WorkingDirectory $root))
}
finally {
    $env:PYTHONPATH = $oldPythonPath
}

$source = Read-FreshJson -Path (Join-Path $root 'artifacts/jwk-weekend-source-status-v1/latest.json') -NotBefore $gateStarted
$replay = Read-FreshJson -Path (Join-Path $root 'artifacts/jwk-weekend-replay-v1/latest.json') -NotBefore $gateStarted
$history = Read-FreshJson -Path (Join-Path $root 'artifacts/prospective-history-refresh-v1/latest.json') -NotBefore $gateStarted
$personal = Read-FreshJson -Path (Join-Path $root 'artifacts/jwk-weekend-personal-v1/latest.json') -NotBefore $gateStarted

$summary = New-GateSummary -Root $root -Steps @($steps) -Source $source -Replay $replay -History $history -Personal $personal

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$jsonPath = Join-Path $tempRoot "WEEKEND-REALITY-GATE-001-$stamp.json"
$mdPath = Join-Path $tempRoot "WEEKEND-REALITY-GATE-001-$stamp.md"
ConvertTo-Json -InputObject $summary -Depth 8 | Set-Content -LiteralPath $jsonPath -Encoding utf8

$md = @(
    '# WEEKEND-REALITY-GATE-001',
    '',
    "- Observed: $($summary.observed_at)",
    "- Repo: $($summary.repo_path)",
    "- DB read-only: $($summary.db_read_only)",
    "- Weekend source: $($summary.source_state)",
    "- Confirmed runner rows: $($summary.confirmed_runner_rows)",
    "- Special registrations: $($summary.special_registration_rows)",
    "- Replay: $($summary.replay_state) / $($summary.replay_races) races / $($summary.replay_runners) runners",
    "- History through: $($summary.history_snapshot_through)",
    "- Personal forecast: $($summary.personal_state) / $($summary.personal_predicted_races) races / $($summary.personal_predicted_runners) runners",
    "- Personal blockers: $($summary.personal_blockers)",
    '',
    '## Steps',
    ''
)
foreach ($step in $summary.steps) {
    $md += "- $($step.name): exit $($step.exit_code)"
}
$md -join [Environment]::NewLine | Set-Content -LiteralPath $mdPath -Encoding utf8

Write-Host ''
Write-Host '============================================================' -ForegroundColor Cyan
Write-Host ' WEEKEND-REALITY-GATE-001 COMPLETE' -ForegroundColor Cyan
Write-Host '============================================================' -ForegroundColor Cyan
Write-Host "Repo                 : $($summary.repo_path)"
Write-Host "DB read-only         : $($summary.db_read_only)"
Write-Host "Weekend source       : $($summary.source_state)"
Write-Host "Confirmed runners    : $($summary.confirmed_runner_rows)"
Write-Host "Special registrations: $($summary.special_registration_rows)"
Write-Host "10/3-4 replay        : $($summary.replay_state)"
Write-Host "Replay races/runners : $($summary.replay_races) / $($summary.replay_runners)"
Write-Host "History through      : $($summary.history_snapshot_through)"
Write-Host "Personal forecast    : $($summary.personal_state)"
Write-Host "Forecast races/runners: $($summary.personal_predicted_races) / $($summary.personal_predicted_runners)"
Write-Host "Blockers             : $($summary.personal_blockers)"
Write-Host ''
foreach ($step in $summary.steps) {
    Write-Host ("{0,-28}: exit {1} [{2}]" -f $step.name, $step.exit_code, $step.failure_class)
    if ($step.exit_code -ne 0) {
        foreach ($line in @($step.output_tail | Select-Object -Last 5)) {
            Write-Host ("    " + $line) -ForegroundColor Yellow
        }
    }
}
Write-Host ''
Write-Host "JSON report          : $jsonPath"
Write-Host "Markdown report      : $mdPath"
Write-Host ''
Write-Host 'No database write, service stop, source checkout/reset/clean, or automatic wagering was performed.' -ForegroundColor Green
