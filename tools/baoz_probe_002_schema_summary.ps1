[CmdletBinding()]
param(
    [string]$InputPath = '',
    [string]$OutputPath = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if (-not $InputPath) {
    $InputPath = Join-Path $env:TEMP 'JIZO\BAOZ-BASELINE-001\baoz_probe_001.json'
}
if (-not (Test-Path -LiteralPath $InputPath -PathType Leaf)) {
    throw "BAOZ-PROBE-001 result not found: $InputPath"
}

$data = Get-Content -LiteralPath $InputPath -Raw -Encoding utf8 | ConvertFrom-Json -Depth 20

$rows = foreach ($schema in @($data.baoz.schemas)) {
    $tableNames = @($schema.tables | ForEach-Object { [string]$_.name })
    [pscustomobject]@{
        Database     = [string]$schema.relative_path
        Opened       = [bool]$schema.opened
        Provider     = [string]$schema.provider
        TableCount   = $tableNames.Count
        TablePreview = ($tableNames | Select-Object -First 12) -join ', '
        Error        = [string]$schema.error
    }
}

$candidateRegex = '(?i)(BaoZ|RA|SE|O[1-6]|HC|WC|Master|Index|Score|Point|Tokuten|Mark|印|得点|指数|予想)'
$candidates = @(
    $rows | Where-Object {
        $_.Database -match $candidateRegex -or
        $_.TablePreview -match $candidateRegex
    }
)

if (-not $OutputPath) {
    $OutputPath = Join-Path $env:TEMP 'JIZO\BAOZ-BASELINE-001\baoz_probe_002.json'
}

$result = [ordered]@{
    mission = 'BAOZ-BASELINE-001'
    probe = 'BAOZ-PROBE-002'
    source_probe = 'BAOZ-PROBE-001'
    created_at = (Get-Date).ToString('yyyy-MM-ddTHH:mm:sszzz')
    safety = [ordered]@{
        reads_probe_json_only = $true
        reads_mdb_rows = $false
        modifies_baoz = $false
    }
    summary = [ordered]@{
        database_count = @($rows).Count
        opened_count = @($rows | Where-Object Opened).Count
        failed_count = @($rows | Where-Object { -not $_.Opened }).Count
        candidate_count = $candidates.Count
    }
    databases = @($rows)
    candidates = @($candidates)
}

$result | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $OutputPath -Encoding utf8

Write-Host ''
Write-Host '============================================================' -ForegroundColor Cyan
Write-Host ' BAOZ-PROBE-002 — SCHEMA SUMMARY' -ForegroundColor Cyan
Write-Host '============================================================' -ForegroundColor Cyan
Write-Host ("Databases            : {0}" -f $result.summary.database_count)
Write-Host ("Schema opened        : {0}" -f $result.summary.opened_count)
Write-Host ("Schema failed        : {0}" -f $result.summary.failed_count)
Write-Host ("Research candidates  : {0}" -f $result.summary.candidate_count)
Write-Host ''

Write-Host '--- DATABASES ---' -ForegroundColor Yellow
$rows | Sort-Object Database | Format-Table Database, Opened, TableCount, Provider -AutoSize | Out-String | Write-Host

Write-Host '--- CANDIDATE TABLE PREVIEW ---' -ForegroundColor Yellow
foreach ($row in ($candidates | Sort-Object Database)) {
    Write-Host ("[{0}] opened={1} tables={2}" -f $row.Database, $row.Opened, $row.TableCount)
    if ($row.TablePreview) {
        Write-Host ("  {0}" -f $row.TablePreview)
    }
    if ($row.Error) {
        Write-Host ("  ERROR: {0}" -f $row.Error)
    }
}

Write-Host ''
Write-Host ("Output              : {0}" -f $OutputPath)
Write-Host '============================================================'
