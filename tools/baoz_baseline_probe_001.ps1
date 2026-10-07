[CmdletBinding()]
param(
    [string]$BaoZPath = '',
    [string]$OutputPath = '',
    [switch]$NoSchema
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-DefaultBaoZPath {
    $candidates = @(
        (Join-Path $env:USERPROFILE 'Documents\BaoZ'),
        (Join-Path $env:USERPROFILE 'OneDrive\Documents\BaoZ')
    ) | Select-Object -Unique

    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate -PathType Container) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }

    throw "BaoZ folder not found in standard Documents locations. Re-run with -BaoZPath '<path>'."
}

function Test-ComProgId {
    param([Parameter(Mandatory)][string]$ProgId)

    try {
        $type = [type]::GetTypeFromProgID($ProgId, $true)
        return [bool]$type
    }
    catch {
        return $false
    }
}

function Get-MdbSchema {
    param([Parameter(Mandatory)][string]$Path)

    $providers = @(
        'Microsoft.ACE.OLEDB.16.0',
        'Microsoft.ACE.OLEDB.12.0',
        'Microsoft.Jet.OLEDB.4.0'
    )

    $connection = $null
    $providerUsed = $null
    $lastError = $null

    foreach ($provider in $providers) {
        try {
            $connection = New-Object -ComObject ADODB.Connection
            $connection.ConnectionTimeout = 5
            $connection.CommandTimeout = 10
            $connection.Open("Provider=$provider;Data Source=$Path;Mode=Read;")
            $providerUsed = $provider
            break
        }
        catch {
            $lastError = $_.Exception.Message
            if ($connection) {
                try { $connection.Close() } catch {}
                try { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($connection) } catch {}
            }
            $connection = $null
        }
    }

    if (-not $connection) {
        return [ordered]@{
            provider = $null
            opened = $false
            error = $lastError
            tables = @()
        }
    }

    $tables = @()
    $recordset = $null

    try {
        # 20 = adSchemaTables. Schema only; no user rows are read.
        $recordset = $connection.OpenSchema(20)
        while (-not $recordset.EOF) {
            $tableName = [string]$recordset.Fields.Item('TABLE_NAME').Value
            $tableType = [string]$recordset.Fields.Item('TABLE_TYPE').Value
            if ($tableType -eq 'TABLE' -and $tableName -notmatch '^MSys') {
                $tables += [ordered]@{
                    name = $tableName
                    type = $tableType
                }
            }
            $recordset.MoveNext()
        }
    }
    finally {
        if ($recordset) {
            try { $recordset.Close() } catch {}
            try { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($recordset) } catch {}
        }
        try { $connection.Close() } catch {}
        try { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($connection) } catch {}
    }

    return [ordered]@{
        provider = $providerUsed
        opened = $true
        error = $null
        tables = @($tables | Sort-Object name)
    }
}

if (-not $BaoZPath) {
    $BaoZPath = Get-DefaultBaoZPath
}
$BaoZPath = (Resolve-Path -LiteralPath $BaoZPath).Path

if (-not $OutputPath) {
    $outDir = Join-Path $env:TEMP 'JIZO\BAOZ-BASELINE-001'
    New-Item -ItemType Directory -Path $outDir -Force | Out-Null
    $OutputPath = Join-Path $outDir 'baoz_probe_001.json'
}

$files = @(
    Get-ChildItem -LiteralPath $BaoZPath -File -Recurse -ErrorAction Stop |
        Where-Object {
            $_.Extension -in @('.MDB', '.mdb', '.bzi', '.BZI') -and
            $_.FullName.Length -lt 1000
        } |
        Sort-Object FullName
)

$mdbs = @($files | Where-Object { $_.Extension -ieq '.mdb' })

$relativeFiles = foreach ($file in $files) {
    $relative = [IO.Path]::GetRelativePath($BaoZPath, $file.FullName)
    [ordered]@{
        relative_path = $relative
        extension = $file.Extension
        size_bytes = $file.Length
        last_write_time = $file.LastWriteTime.ToString('yyyy-MM-ddTHH:mm:ss')
    }
}

$schemas = @()
if (-not $NoSchema) {
    foreach ($mdb in $mdbs) {
        $relative = [IO.Path]::GetRelativePath($BaoZPath, $mdb.FullName)
        $schema = Get-MdbSchema -Path $mdb.FullName
        $schemas += [ordered]@{
            relative_path = $relative
            provider = $schema.provider
            opened = $schema.opened
            error = $schema.error
            tables = $schema.tables
        }
    }
}

$result = [ordered]@{
    mission = 'BAOZ-BASELINE-001'
    probe = 'BAOZ-PROBE-001'
    created_at = (Get-Date).ToString('yyyy-MM-ddTHH:mm:sszzz')
    safety = [ordered]@{
        read_only = $true
        row_data_read = $false
        service_keys_read = $false
        baoz_files_modified = $false
    }
    environment = [ordered]@{
        os_64bit = [Environment]::Is64BitOperatingSystem
        process_64bit = [Environment]::Is64BitProcess
        powershell = $PSVersionTable.PSVersion.ToString()
        jvlink_com_registered = (Test-ComProgId 'JVDTLab.JVLink')
        nvlink_com_registered = (
            (Test-ComProgId 'NVDTLabLib.NVLink') -or
            (Test-ComProgId 'NVDTLab.NVLink')
        )
    }
    baoz = [ordered]@{
        path_redacted = '<BaoZ>'
        file_count = $relativeFiles.Count
        mdb_count = $mdbs.Count
        files = @($relativeFiles)
        schemas = @($schemas)
    }
}

$json = $result | ConvertTo-Json -Depth 12
$parent = Split-Path -Parent $OutputPath
if ($parent) {
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
}
Set-Content -LiteralPath $OutputPath -Value $json -Encoding utf8

Write-Host ''
Write-Host '============================================================' -ForegroundColor Cyan
Write-Host ' BAOZ-PROBE-001 COMPLETE' -ForegroundColor Cyan
Write-Host '============================================================' -ForegroundColor Cyan
Write-Host ("BaoZ files          : {0}" -f $relativeFiles.Count)
Write-Host ("MDB files           : {0}" -f $mdbs.Count)
Write-Host ("JV-Link COM         : {0}" -f $result.environment.jvlink_com_registered)
Write-Host ("UmaConn COM         : {0}" -f $result.environment.nvlink_com_registered)
Write-Host ("Row data read       : {0}" -f $result.safety.row_data_read)
Write-Host ("BaoZ files modified : {0}" -f $result.safety.baoz_files_modified)
Write-Host ("Output              : {0}" -f $OutputPath)
Write-Host '============================================================'
