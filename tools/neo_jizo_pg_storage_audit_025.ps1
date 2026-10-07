[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# NEO-JIZO-DIRT-EDGE-025: filesystem-only recovery evidence.
# Never calls psql, pg_ctl, systemctl, net start/stop, or accesses SQL data.
$reportDir = Join-Path $env:TEMP 'JIZO\NEO-JIZO-DIRT-EDGE-025'
New-Item -Path $reportDir -ItemType Directory -Force | Out-Null
$reportFile = Join-Path $reportDir 'pg_storage_audit_025.txt'
$log = [System.Collections.Generic.List[string]]::new()

function LogLine {
    param([string]$Value)
    Write-Host $Value
    [void]$script:log.Add($Value)
}

LogLine '============================================================'
LogLine ' NEO JIZO 025 - WSL/POSTGRES FILESYSTEM AUDIT (READ ONLY)'
LogLine '============================================================'
LogLine 'No database connection, PostgreSQL start/stop or file modification.'
LogLine ''

$wsl = Get-Command wsl.exe -ErrorAction SilentlyContinue
if (-not $wsl) {
    LogLine 'WSL_COMMAND: MISSING'
    LogLine 'DECISION: BLOCKED_WSL_UNAVAILABLE'
    $log | Set-Content -LiteralPath $reportFile -Encoding utf8
    LogLine "Report: $reportFile"
    return
}

LogLine '--- WSL DISTROS ---'
$distroLines = @(& $wsl.Source --list --verbose 2>&1)
foreach ($line in $distroLines) { LogLine ([string]$line) }
LogLine ''

LogLine '--- UBUNTU USER, HOME, CLUSTER & SOCKETS ---'

# Run /bin/sh from an absolute path and pass the script via standard input.
# No bash login shell is involved; login-profile changes cannot hide HOME.
$probe = @'
set -u
printf 'WSL_KERNEL=%s\n' "$(uname -r 2>/dev/null || printf unknown)"
printf 'WSL_USER=%s\n' "$(id -un 2>/dev/null || printf unknown)"
printf 'WSL_UID=%s\n' "$(id -u 2>/dev/null || printf unknown)"
printf 'WSL_HOME=%s\n' "$HOME"
printf 'WSL_PWD=%s\n' "$(pwd)"
printf 'WSL_DISTRO_NAME=%s\n' "$(printenv WSL_DISTRO_NAME 2>/dev/null || printf UNSET)"
printf 'PATH_PSQL=%s\n' "$(command -v psql 2>/dev/null || printf MISSING)"
printf 'PATH_PG_CTL=%s\n' "$(command -v pg_ctl 2>/dev/null || printf MISSING)"

client_count=0
data_count=0
for base in "$HOME" /home/* /root; do
    [ -d "$base" ] || continue
    [ -d "$base/.keiba_ai" ] || continue
    printf 'KEIBA_ROOT=%s\n' "$base/.keiba_ai"
    if [ -x "$base/.keiba_ai/postgres18/bin/psql" ]; then
        printf 'PG_CLIENT=FOUND:%s\n' "$base/.keiba_ai/postgres18/bin/psql"
        client_count=$((client_count+1))
    else
        printf 'PG_CLIENT=NOT_EXECUTABLE_OR_MISSING:%s\n' "$base/.keiba_ai/postgres18/bin/psql"
    fi
    if [ -f "$base/.keiba_ai/pgdata18/PG_VERSION" ]; then
        printf 'PGDATA=FOUND:%s\n' "$base/.keiba_ai/pgdata18"
        printf 'PG_VERSION=%s\n' "$(cat "$base/.keiba_ai/pgdata18/PG_VERSION" 2>/dev/null || printf unreadable)"
        data_count=$((data_count+1))
        if [ -f "$base/.keiba_ai/pgdata18/postmaster.pid" ]; then
            printf 'POSTMASTER_PID_FILE=PRESENT_POSSIBLY_STALE\n'
        else
            printf 'POSTMASTER_PID_FILE=ABSENT\n'
        fi
    else
        printf 'PGDATA=NOT_FOUND_OR_UNREADABLE:%s\n' "$base/.keiba_ai/pgdata18"
    fi
done
printf 'CLIENT_LOCATIONS_FOUND=%s\n' "$client_count"
printf 'PGDATA_LOCATIONS_FOUND=%s\n' "$data_count"

socket_count=0
for dir in /tmp /var/run/postgresql /run/postgresql; do
    if [ -S "$dir/.s.PGSQL.5433" ]; then
        printf 'LIVE_SOCKET=FOUND:%s\n' "$dir/.s.PGSQL.5433"
        socket_count=$((socket_count+1))
    fi
done
if [ "$socket_count" -eq 0 ]; then
    printf 'LIVE_SOCKET=NONE_AT_PORT_5433\n'
fi

if command -v ps >/dev/null 2>&1; then
    printf 'POSTGRES_PROCESS_LIST_BEGIN\n'
    ps -eo comm= 2>/dev/null | grep -E '^(postgres|postmaster)$' | head -n 12 || true
    printf 'POSTGRES_PROCESS_LIST_END\n'
fi
printf 'AUDIT_COMPLETE=YES\n'
'@

$wslLines = @($probe | & $wsl.Source -d Ubuntu -- /bin/sh -s 2>&1)
$wslExit = $LASTEXITCODE
foreach ($line in $wslLines) { LogLine ([string]$line) }
LogLine "WSL_EXIT_CODE=$wslExit"
LogLine ''

LogLine '--- WINDOWS WSL STORAGE ENTRY ---'
$wslPath = 'D:\WSL\Ubuntu'
if (Test-Path -LiteralPath $wslPath -PathType Container) {
    LogLine "WSL_STORAGE_DIRECTORY=PRESENT:$wslPath"
    $vhdx = @(Get-ChildItem -LiteralPath $wslPath -File -Filter '*.vhdx' -ErrorAction SilentlyContinue)
    foreach ($item in $vhdx) {
        LogLine ("WSL_VHDX={0} SIZE_GB={1:N2}" -f $item.Name,($item.Length/1GB))
    }
} else {
    LogLine "WSL_STORAGE_DIRECTORY=NOT_FOUND:$wslPath"
}
LogLine ''

LogLine '--- EXISTING CORE PROBABILITIES (HEADER ONLY) ---'
$rootCandidates = @()
if ($env:THE_JOCKEY_RESEARCH_ROOT) {
    $rootCandidates += $env:THE_JOCKEY_RESEARCH_ROOT
}
$rootCandidates += (Join-Path $env:USERPROFILE 'Downloads\THE-JOCKEY-RESEARCH')
$rootCandidates += (Join-Path $env:USERPROFILE 'Documents\THE-JOCKEY-RESEARCH')
$rootCandidates = @($rootCandidates | Select-Object -Unique)
$found = $false
foreach ($root in $rootCandidates) {
    $candidate = Join-Path $root 'CORE\data\CORE-010_calibrated_probabilities.csv'
    if (Test-Path -LiteralPath $candidate -PathType Leaf) {
        $item = Get-Item -LiteralPath $candidate
        LogLine ("CORE_010=FOUND SIZE_MB={0:N2} LOCATION={1}" -f ($item.Length/1MB),$candidate)
        $header = Get-Content -LiteralPath $candidate -TotalCount 1 -ErrorAction Stop
        LogLine "CORE_010_HEADER=$header"
        $found = $true
        break
    }
}
if (-not $found) { LogLine 'CORE_010=NOT_FOUND_IN_KNOWN_LOCATIONS' }

LogLine ''
$joined = $log -join [Environment]::NewLine
if ($wslExit -ne 0) {
    LogLine 'DECISION=WSL_COMMAND_FAILED'
} elseif ($joined -match 'PGDATA_LOCATIONS_FOUND=0') {
    LogLine 'DECISION=PGDATA_NOT_VISIBLE_IN_EXISTING_HOME_LOCATIONS'
    LogLine 'NEXT=Check Ubuntu distro identity and VHDX mount; do not initialize database.'
} elseif ($joined -match 'LIVE_SOCKET=NONE_AT_PORT_5433') {
    LogLine 'DECISION=CLUSTER_FILES_PRESENT_BUT_NO_5433_SOCKET'
    LogLine 'NEXT=Review offline cluster state and startup configuration separately; do not start services now.'
} elseif ($joined -match 'CLIENT_LOCATIONS_FOUND=0') {
    LogLine 'DECISION=CLIENT_BINARY_UNAVAILABLE'
    LogLine 'NEXT=Find the existing PostgreSQL executable before any connection retry.'
} else {
    LogLine 'DECISION=WSL_FILES_AND_SOCKET_PRESENT'
    LogLine 'NEXT=Resolve connection permissions without modifying the cluster.'
}
LogLine "Report: $reportFile"
$log | Set-Content -LiteralPath $reportFile -Encoding utf8
