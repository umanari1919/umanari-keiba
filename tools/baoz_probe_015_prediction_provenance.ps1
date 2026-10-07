[CmdletBinding()]
param(
    [string]$BaoZPath = '',
    [datetime]$CutoffDate = [datetime]'2026-10-08',
    [string]$OutputPath = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Find-BaoZRoot {
    $roots=@(
        [Environment]::GetFolderPath('MyDocuments'),
        (Join-Path $env:USERPROFILE 'Documents'),
        $env:OneDrive,
        $env:OneDriveConsumer,
        'C:\BaoZ','D:\BaoZ','C:\','D:\'
    ) | Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Container) } | Select-Object -Unique

    foreach($root in $roots){
        try{
            $hit=Get-ChildItem -LiteralPath $root -Filter 'BaoZ.mdb' -File -Recurse -Depth 5 -ErrorAction SilentlyContinue |
                Where-Object { $_.FullName -match '[\\/]DB[\\/]BaoZ\.mdb$' } |
                Select-Object -First 1
            if($hit){ return (Split-Path -Parent (Split-Path -Parent $hit.FullName)) }
        }catch{}
    }
    throw 'BaoZ active DB root was not found.'
}

function Open-ReadOnlyConnection {
    param([Parameter(Mandatory)][string]$Path)
    foreach($provider in @('Microsoft.ACE.OLEDB.16.0','Microsoft.ACE.OLEDB.12.0','Microsoft.Jet.OLEDB.4.0')){
        $conn=$null
        try{
            $conn=New-Object -ComObject ADODB.Connection
            $conn.ConnectionTimeout=5
            $conn.CommandTimeout=180
            $conn.Open("Provider=$provider;Data Source=$Path;Mode=Read;")
            return [pscustomobject]@{Connection=$conn;Provider=$provider}
        }catch{
            if($conn){
                try{$conn.Close()}catch{}
                try{[void][Runtime.InteropServices.Marshal]::ReleaseComObject($conn)}catch{}
            }
        }
    }
    throw "Could not open MDB read-only: $Path"
}

function Invoke-Scalar {
    param([Parameter(Mandatory)]$Connection,[Parameter(Mandatory)][string]$Sql)
    $rs=$null
    try{
        $rs=$Connection.Execute($Sql)
        if($rs.EOF){return $null}
        $v=$rs.Fields.Item(0).Value
        if($v -is [DBNull]){return $null}
        return $v
    }finally{
        if($rs){
            try{$rs.Close()}catch{}
            try{[void][Runtime.InteropServices.Marshal]::ReleaseComObject($rs)}catch{}
        }
    }
}

function Get-FieldNames {
    param([Parameter(Mandatory)]$Connection,[Parameter(Mandatory)][string]$Table)

    # ACE/Jet through ADO does not reliably accept SELECT TOP 0.
    # First use an empty-result SELECT; if the provider rejects that,
    # fall back to the ADO columns schema.
    $rs=$null
    try{
        try{
            $rs=$Connection.Execute("SELECT * FROM [$Table] WHERE 1=0")
        }catch{
            $rs=$null
        }

        if($rs){
            $names=@()
            for($i=0;$i -lt $rs.Fields.Count;$i++){
                $names += [string]$rs.Fields.Item($i).Name
            }
            return @($names)
        }
    }finally{
        if($rs){
            try{$rs.Close()}catch{}
            try{[void][Runtime.InteropServices.Marshal]::ReleaseComObject($rs)}catch{}
        }
    }

    $schema=$null
    try{
        $schema=$Connection.OpenSchema(4) # adSchemaColumns
        $cols=@()
        while(-not $schema.EOF){
            $tableName=[string]$schema.Fields.Item('TABLE_NAME').Value
            if($tableName -eq $Table){
                $columnName=[string]$schema.Fields.Item('COLUMN_NAME').Value
                $ordinalValue=$schema.Fields.Item('ORDINAL_POSITION').Value
                $ordinal=if($ordinalValue -is [DBNull]){2147483647}else{[int]$ordinalValue}
                $cols += [pscustomobject]@{
                    ordinal=$ordinal
                    name=$columnName
                }
            }
            $schema.MoveNext()
        }
        return @($cols | Sort-Object ordinal | ForEach-Object { $_.name })
    }finally{
        if($schema){
            try{$schema.Close()}catch{}
            try{[void][Runtime.InteropServices.Marshal]::ReleaseComObject($schema)}catch{}
        }
    }
}

function Get-TableNames {
    param([Parameter(Mandatory)]$Connection)
    $rs=$null
    $names=@()
    try{
        $rs=$Connection.OpenSchema(20)
        while(-not $rs.EOF){
            $type=[string]$rs.Fields.Item('TABLE_TYPE').Value
            $name=[string]$rs.Fields.Item('TABLE_NAME').Value
            if($type -eq 'TABLE' -and $name -notlike 'MSys*'){
                $names += $name
            }
            $rs.MoveNext()
        }
        return @($names | Sort-Object -Unique)
    }finally{
        if($rs){
            try{$rs.Close()}catch{}
            try{[void][Runtime.InteropServices.Marshal]::ReleaseComObject($rs)}catch{}
        }
    }
}

if(-not $BaoZPath){
    Write-Host 'BaoZ active DB root: auto-discovery...' -ForegroundColor DarkGray
    $BaoZPath=Find-BaoZRoot
}
$BaoZPath=(Resolve-Path -LiteralPath $BaoZPath).Path
$db=Join-Path $BaoZPath 'DB\BaoZ.mdb'
$opened=Open-ReadOnlyConnection -Path $db
$conn=$opened.Connection

try{
    $cutoff=$CutoffDate.ToString('yyyy-MM-dd')
    $allTables=Get-TableNames $conn
    $candidateTables=@($allTables | Where-Object {
        $_ -match '予想|設定|最新|成績|騎手|血統|調教師|得点|指数|集計|統計'
    })

    $columnRegex='予想|計算|作成|更新|月日|年月日|時刻|日時|設定|版|バージョン|得点|指数|履歴|世代'
    $columnScan=[ordered]@{}
    foreach($table in @('出走馬T','レースT','予想設定T')){
        if($allTables -contains $table){
            $cols=Get-FieldNames $conn $table
            $columnScan[$table]=@($cols | Where-Object { $_ -match $columnRegex })
        }
    }

    $periods=[ordered]@{
        '2012-2018'='[月日] Between #2012-01-01# And #2018-12-31#'
        '2019-2023'='[月日] Between #2019-01-01# And #2023-12-31#'
        '2024-2026'="[月日] Between #2024-01-01# And #$cutoff#"
        'FUTURE'="[月日] > #$cutoff#"
    }

    $raceCalc=[ordered]@{}
    foreach($p in $periods.Keys){
        $w=$periods[$p]
        $raceCalc[$p]=[ordered]@{
            races=[int64](Invoke-Scalar $conn "SELECT Count(*) FROM [レースT] WHERE $w")
            calc_nonnull=[int64](Invoke-Scalar $conn "SELECT Count(*) FROM [レースT] WHERE $w AND [予想計算済み] Is Not Null")
            calc_zero=[int64](Invoke-Scalar $conn "SELECT Count(*) FROM [レースT] WHERE $w AND ([予想計算済み]=0 OR [予想計算済み] Is Null)")
            calc_nonzero=[int64](Invoke-Scalar $conn "SELECT Count(*) FROM [レースT] WHERE $w AND [予想計算済み]<>0")
            win_index_nonnull=[int64](Invoke-Scalar $conn "SELECT Count(*) FROM [レースT] WHERE $w AND [予想勝ち指数] Is Not Null")
            turbulence_nonnull=[int64](Invoke-Scalar $conn "SELECT Count(*) FROM [レースT] WHERE $w AND [波乱度] Is Not Null")
        }
    }

    $settingsMeta=[ordered]@{
        table_exists=($allTables -contains '予想設定T')
        rows=0
        matching_key_names=@()
    }
    if($settingsMeta.table_exists){
        $settingsMeta.rows=[int64](Invoke-Scalar $conn "SELECT Count(*) FROM [予想設定T]")
        $rs=$null
        try{
            $rs=$conn.Execute("SELECT [セクション],[キー] FROM [予想設定T]")
            $pairs=@()
            while(-not $rs.EOF){
                $sec=$rs.Fields.Item(0).Value
                $key=$rs.Fields.Item(1).Value
                if($sec -is [DBNull]){$sec=''}
                if($key -is [DBNull]){$key=''}
                $label=("{0}/{1}" -f [string]$sec,[string]$key)
                if($label -match '版|バージョン|更新|計算|予想|得点|指数|履歴|世代|モデル'){
                    $pairs += $label
                }
                $rs.MoveNext()
            }
            $settingsMeta.matching_key_names=@($pairs | Sort-Object -Unique)
        }finally{
            if($rs){
                try{$rs.Close()}catch{}
                try{[void][Runtime.InteropServices.Marshal]::ReleaseComObject($rs)}catch{}
            }
        }
    }

    $result=[ordered]@{
        mission='BAOZ-BASELINE-001'
        probe='BAOZ-PROBE-015'
        created_at=(Get-Date).ToString('yyyy-MM-ddTHH:mm:sszzz')
        safety=[ordered]@{
            read_only=$true
            metadata_and_aggregate_only=$true
            setting_values_output=$false
            horse_rows_output=$false
            baoz_modified=$false
        }
        candidate_tables=$candidateTables
        provenance_columns=$columnScan
        race_prediction_computed=$raceCalc
        settings_metadata=$settingsMeta
        interpretation_note='This probe searches for provenance/version/timestamp evidence. It does not assume that 予想計算済み proves contemporaneous historical computation.'
    }

    if(-not $OutputPath){
        $outDir=Join-Path $env:TEMP 'JIZO\BAOZ-BASELINE-001'
        New-Item -ItemType Directory -Path $outDir -Force | Out-Null
        $OutputPath=Join-Path $outDir 'baoz_probe_015_prediction_provenance.json'
    }
    $result | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $OutputPath -Encoding utf8

    Write-Host ''
    Write-Host '============================================================' -ForegroundColor Cyan
    Write-Host ' BAOZ-PROBE-015 — PREDICTION PROVENANCE' -ForegroundColor Cyan
    Write-Host '============================================================' -ForegroundColor Cyan

    Write-Host '--- CANDIDATE TABLES ---' -ForegroundColor Yellow
    $candidateTables | ForEach-Object { Write-Host $_ }

    Write-Host ''
    Write-Host '--- PROVENANCE-RELATED COLUMNS ---' -ForegroundColor Yellow
    foreach($table in $columnScan.Keys){
        Write-Host ("[{0}]" -f $table) -ForegroundColor DarkYellow
        $columnScan[$table] | ForEach-Object { Write-Host ("  {0}" -f $_) }
    }

    Write-Host ''
    Write-Host '--- RACE PREDICTION COMPUTED FLAGS ---' -ForegroundColor Yellow
    foreach($p in $raceCalc.Keys){
        $m=$raceCalc[$p]
        Write-Host ("{0,-10} races={1,7} calcNonZero={2,7} calcZero={3,7} winIndex={4,7} turbulence={5,7}" -f $p,$m.races,$m.calc_nonzero,$m.calc_zero,$m.win_index_nonnull,$m.turbulence_nonnull)
    }

    Write-Host ''
    Write-Host '--- SETTINGS METADATA (NAMES ONLY) ---' -ForegroundColor Yellow
    Write-Host ("Rows: {0}" -f $settingsMeta.rows)
    $settingsMeta.matching_key_names | ForEach-Object { Write-Host $_ }

    Write-Host ''
    Write-Host ("Metadata/aggregate only : {0}" -f $result.safety.metadata_and_aggregate_only)
    Write-Host ("Setting values output   : {0}" -f $result.safety.setting_values_output)
    Write-Host ("Horse rows output       : {0}" -f $result.safety.horse_rows_output)
    Write-Host ("BaoZ modified           : {0}" -f $result.safety.baoz_modified)
    Write-Host ("Output                  : {0}" -f $OutputPath)
    Write-Host '============================================================'
}
finally{
    try{$conn.Close()}catch{}
    try{[void][Runtime.InteropServices.Marshal]::ReleaseComObject($conn)}catch{}
}
