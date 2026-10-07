[CmdletBinding()]
param(
    [string]$BaoZPath = '',
    [string]$OutputPath = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Find-BaoZRoot {
    $roots = @(
        [Environment]::GetFolderPath('MyDocuments'),
        (Join-Path $env:USERPROFILE 'Documents'),
        $env:OneDrive,
        $env:OneDriveConsumer,
        'C:\BaoZ',
        'D:\BaoZ',
        'C:\',
        'D:\'
    ) | Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Container) } | Select-Object -Unique

    foreach ($root in $roots) {
        try {
            $hit = Get-ChildItem -LiteralPath $root -Filter 'BaoZ.mdb' -File -Recurse -Depth 5 -ErrorAction SilentlyContinue |
                Where-Object { $_.FullName -match '[\\/]DB[\\/]BaoZ\.mdb$' } |
                Select-Object -First 1
            if ($hit) {
                return (Split-Path -Parent (Split-Path -Parent $hit.FullName))
            }
        }
        catch {}
    }

    throw 'BaoZ active DB root was not found.'
}

function Open-ReadOnlyConnection {
    param([Parameter(Mandatory)][string]$Path)

    $providers = @(
        'Microsoft.ACE.OLEDB.16.0',
        'Microsoft.ACE.OLEDB.12.0',
        'Microsoft.Jet.OLEDB.4.0'
    )

    foreach ($provider in $providers) {
        $conn = $null
        try {
            $conn = New-Object -ComObject ADODB.Connection
            $conn.ConnectionTimeout = 5
            $conn.CommandTimeout = 10
            $conn.Open("Provider=$provider;Data Source=$Path;Mode=Read;")
            return [pscustomobject]@{
                Connection = $conn
                Provider = $provider
            }
        }
        catch {
            if ($conn) {
                try { $conn.Close() } catch {}
                try { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($conn) } catch {}
            }
        }
    }

    throw "Could not open MDB read-only: $Path"
}

function Get-TableColumns {
    param(
        [Parameter(Mandatory)][string]$Path,
        [string[]]$OnlyTables = @()
    )

    $opened = Open-ReadOnlyConnection -Path $Path
    $conn = $opened.Connection
    $rs = $null
    $columns = @()

    try {
        # 4 = adSchemaColumns. Metadata only; no user table rows are read.
        $rs = $conn.OpenSchema(4)

        while (-not $rs.EOF) {
            $tableName = [string]$rs.Fields.Item('TABLE_NAME').Value
            $columnName = [string]$rs.Fields.Item('COLUMN_NAME').Value
            $ordinal = 0
            $dataType = $null
            $charLength = $null
            $numericPrecision = $null
            $nullable = $null

            try { $ordinal = [int]$rs.Fields.Item('ORDINAL_POSITION').Value } catch {}
            try { $dataType = [int]$rs.Fields.Item('DATA_TYPE').Value } catch {}
            try { $charLength = $rs.Fields.Item('CHARACTER_MAXIMUM_LENGTH').Value } catch {}
            try { $numericPrecision = $rs.Fields.Item('NUMERIC_PRECISION').Value } catch {}
            try { $nullable = $rs.Fields.Item('IS_NULLABLE').Value } catch {}

            if (
                $tableName -and
                $tableName -notmatch '^MSys' -and
                ($OnlyTables.Count -eq 0 -or $OnlyTables -contains $tableName)
            ) {
                $columns += [pscustomobject]@{
                    table = $tableName
                    ordinal = $ordinal
                    column = $columnName
                    ado_type = $dataType
                    char_length = $charLength
                    numeric_precision = $numericPrecision
                    nullable = $nullable
                }
            }

            $rs.MoveNext()
        }
    }
    finally {
        if ($rs) {
            try { $rs.Close() } catch {}
            try { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($rs) } catch {}
        }
        try { $conn.Close() } catch {}
        try { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($conn) } catch {}
    }

    return [pscustomobject]@{
        provider = $opened.Provider
        columns = @($columns | Sort-Object table, ordinal, column)
    }
}

if (-not $BaoZPath) {
    Write-Host 'BaoZ active DB root: auto-discovery...' -ForegroundColor DarkGray
    $BaoZPath = Find-BaoZRoot
}
$BaoZPath = (Resolve-Path -LiteralPath $BaoZPath).Path

$targets = @(
    [pscustomobject]@{
        label = 'prediction'
        relative = 'DB\BaoZ.mdb'
        tables = @()
    },
    [pscustomobject]@{
        label = 'active_runner'
        relative = 'DB\BaoZ.ex.mdb'
        tables = @('出走馬T')
    },
    [pscustomobject]@{
        label = 'race_master'
        relative = 'DB\MasterDB\BaoZ-RA.mdb'
        tables = @('レースマスタ', '競走履歴T')
    },
    [pscustomobject]@{
        label = 'runner_master'
        relative = 'DB\MasterDB\BaoZ-SE.mdb'
        tables = @('出走馬マスタ')
    },
    [pscustomobject]@{
        label = 'training'
        relative = 'DB\MasterDB\BaoZ-HC.mdb'
        tables = @('ウッドチップ調教T', '坂路調教T', '出走履歴T', '調教分析T')
    }
)

$results = @()

foreach ($target in $targets) {
    $path = Join-Path $BaoZPath $target.relative
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        $results += [pscustomobject]@{
            label = $target.label
            relative_path = $target.relative
            opened = $false
            provider = $null
            error = 'FILE_NOT_FOUND'
            columns = @()
        }
        continue
    }

    try {
        $meta = Get-TableColumns -Path $path -OnlyTables $target.tables
        $results += [pscustomobject]@{
            label = $target.label
            relative_path = $target.relative
            opened = $true
            provider = $meta.provider
            error = $null
            columns = @($meta.columns)
        }
    }
    catch {
        $results += [pscustomobject]@{
            label = $target.label
            relative_path = $target.relative
            opened = $false
            provider = $null
            error = $_.Exception.Message
            columns = @()
        }
    }
}

$keywordRegex = '(?i)(印|得点|指数|予想|人気|オッズ|着順|順位|馬番|枠番|競走馬|血統登録|馬名|年月日|日付|場|開催|回次|日次|レース|距離|芝|ダート|騎手|調教師|タイム|単勝|複勝|score|point|mark|rank|odds|finish|horse|race)'

$hits = foreach ($db in $results) {
    foreach ($col in @($db.columns)) {
        if ($col.column -match $keywordRegex -or $col.table -match $keywordRegex) {
            [pscustomobject]@{
                database = $db.relative_path
                table = $col.table
                ordinal = $col.ordinal
                column = $col.column
                ado_type = $col.ado_type
            }
        }
    }
}

if (-not $OutputPath) {
    $outDir = Join-Path $env:TEMP 'JIZO\BAOZ-BASELINE-001'
    New-Item -ItemType Directory -Path $outDir -Force | Out-Null
    $OutputPath = Join-Path $outDir 'baoz_probe_003_columns.json'
}

$result = [ordered]@{
    mission = 'BAOZ-BASELINE-001'
    probe = 'BAOZ-PROBE-003'
    created_at = (Get-Date).ToString('yyyy-MM-ddTHH:mm:sszzz')
    safety = [ordered]@{
        metadata_only = $true
        reads_user_rows = $false
        modifies_baoz = $false
        reads_service_keys = $false
    }
    summary = [ordered]@{
        target_database_count = $targets.Count
        opened_database_count = @($results | Where-Object opened).Count
        failed_database_count = @($results | Where-Object { -not $_.opened }).Count
        column_count = @($results | ForEach-Object { $_.columns }).Count
        keyword_hit_count = @($hits).Count
    }
    databases = @($results)
    keyword_hits = @($hits)
}

$result | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $OutputPath -Encoding utf8

Write-Host ''
Write-Host '============================================================' -ForegroundColor Cyan
Write-Host ' BAOZ-PROBE-003 — COLUMN MAP' -ForegroundColor Cyan
Write-Host '============================================================' -ForegroundColor Cyan
Write-Host ("Target DBs          : {0}" -f $result.summary.target_database_count)
Write-Host ("Opened DBs          : {0}" -f $result.summary.opened_database_count)
Write-Host ("Failed DBs          : {0}" -f $result.summary.failed_database_count)
Write-Host ("Columns mapped      : {0}" -f $result.summary.column_count)
Write-Host ("Keyword hits        : {0}" -f $result.summary.keyword_hit_count)
Write-Host ''

foreach ($db in ($results | Sort-Object label)) {
    Write-Host ("--- {0} :: {1} ---" -f $db.label, $db.relative_path) -ForegroundColor Yellow
    if (-not $db.opened) {
        Write-Host ("ERROR: {0}" -f $db.error)
        continue
    }

    $tableGroups = @($db.columns | Group-Object table)
    foreach ($group in $tableGroups) {
        Write-Host ("[{0}] columns={1}" -f $group.Name, $group.Count)
        $names = @($group.Group | Sort-Object ordinal | ForEach-Object { $_.column })
        Write-Host ('  ' + ($names -join ', '))
    }
    Write-Host ''
}

Write-Host '--- KEYWORD HITS ---' -ForegroundColor Yellow
$hits | Sort-Object database, table, ordinal |
    Format-Table database, table, ordinal, column -AutoSize |
    Out-String -Width 240 |
    Write-Host

Write-Host ("Metadata only       : {0}" -f $result.safety.metadata_only)
Write-Host ("User rows read      : {0}" -f $result.safety.reads_user_rows)
Write-Host ("BaoZ modified       : {0}" -f $result.safety.modifies_baoz)
Write-Host ("Output              : {0}" -f $OutputPath)
Write-Host '============================================================'
