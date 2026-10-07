[CmdletBinding()]
param(
    [string]$BaoZPath = '',
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

function Get-TableNames {
    param([Parameter(Mandatory)]$Connection)
    $rs=$null; $names=@()
    try{
        $rs=$Connection.OpenSchema(20)
        while(-not $rs.EOF){
            $type=[string]$rs.Fields.Item('TABLE_TYPE').Value
            $name=[string]$rs.Fields.Item('TABLE_NAME').Value
            if($type -eq 'TABLE' -and $name -notlike 'MSys*'){ $names += $name }
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

function Get-Columns {
    param([Parameter(Mandatory)]$Connection,[Parameter(Mandatory)][string]$Table)

    $schema=$null
    try{
        $schema=$Connection.OpenSchema(4)
        $cols=@()
        while(-not $schema.EOF){
            $tableName=[string]$schema.Fields.Item('TABLE_NAME').Value
            if($tableName -eq $Table){
                $columnName=[string]$schema.Fields.Item('COLUMN_NAME').Value
                $ordinalValue=$schema.Fields.Item('ORDINAL_POSITION').Value
                $dataTypeValue=$schema.Fields.Item('DATA_TYPE').Value
                $ordinal=if($ordinalValue -is [DBNull]){2147483647}else{[int]$ordinalValue}
                $dtype=if($dataTypeValue -is [DBNull]){$null}else{[int]$dataTypeValue}
                $cols += [pscustomobject]@{
                    ordinal=$ordinal
                    name=$columnName
                    data_type=$dtype
                }
            }
            $schema.MoveNext()
        }
        return @($cols | Sort-Object ordinal)
    }finally{
        if($schema){
            try{$schema.Close()}catch{}
            try{[void][Runtime.InteropServices.Marshal]::ReleaseComObject($schema)}catch{}
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
    $allTables=Get-TableNames $conn
    $targets=@(
        '最新コース成績T',
        '最新騎手成績T',
        '最新血統成績T',
        '最新調教師成績T',
        '最新票数T',
        '条件別着順タイム指数',
        '着順指数Ｔ',
        '設定T'
    )

    $audit=[ordered]@{}
    $dateRegex='日|月|年|時刻|日時|fromtime|更新|作成|期間|基準|集計'
    $versionRegex='版|バージョン|version|世代|モデル|更新|作成|計算'

    foreach($table in $targets){
        if($allTables -notcontains $table){
            $audit[$table]=[ordered]@{
                exists=$false
            }
            continue
        }

        $cols=Get-Columns $conn $table
        $dateCols=@($cols | Where-Object { $_.name -match $dateRegex })
        $versionCols=@($cols | Where-Object { $_.name -match $versionRegex })
        $dateRanges=[ordered]@{}

        foreach($col in $dateCols){
            $name=$col.name
            try{
                $min=Invoke-Scalar $conn "SELECT Min([$name]) FROM [$table]"
                $max=Invoke-Scalar $conn "SELECT Max([$name]) FROM [$table]"
                $nonnull=[int64](Invoke-Scalar $conn "SELECT Count(*) FROM [$table] WHERE [$name] Is Not Null")
                $dateRanges[$name]=[ordered]@{
                    nonnull=$nonnull
                    min=$min
                    max=$max
                }
            }catch{
                $dateRanges[$name]=[ordered]@{
                    error=$_.Exception.Message
                }
            }
        }

        $audit[$table]=[ordered]@{
            exists=$true
            rows=[int64](Invoke-Scalar $conn "SELECT Count(*) FROM [$table]")
            columns=@($cols | ForEach-Object { $_.name })
            date_like_columns=@($dateCols | ForEach-Object { $_.name })
            version_like_columns=@($versionCols | ForEach-Object { $_.name })
            date_ranges=$dateRanges
        }
    }

    $settingsNames=[ordered]@{
        exists=($allTables -contains '設定T')
        rows=0
        field_names=@()
        key_like_names=@()
    }

    if($settingsNames.exists){
        $cols=Get-Columns $conn '設定T'
        $settingsNames.field_names=@($cols | ForEach-Object { $_.name })
        $settingsNames.rows=[int64](Invoke-Scalar $conn "SELECT Count(*) FROM [設定T]")

        # Read only likely label/key columns; never output values.
        $candidateKeyCols=@($cols | Where-Object { $_.name -match 'キー|key|項目|名前|名称|セクション|section' })
        foreach($kc in $candidateKeyCols){
            try{
                $rs=$null
                $rs=$conn.Execute("SELECT DISTINCT [$($kc.name)] FROM [設定T]")
                while(-not $rs.EOF){
                    $v=$rs.Fields.Item(0).Value
                    if(-not ($v -is [DBNull])){
                        $s=[string]$v
                        if($s -match '版|バージョン|version|更新|計算|予想|得点|指数|モデル|世代|履歴'){
                            $settingsNames.key_like_names += ("{0}:{1}" -f $kc.name,$s)
                        }
                    }
                    $rs.MoveNext()
                }
            }catch{}
            finally{
                if($rs){
                    try{$rs.Close()}catch{}
                    try{[void][Runtime.InteropServices.Marshal]::ReleaseComObject($rs)}catch{}
                }
            }
        }
        $settingsNames.key_like_names=@($settingsNames.key_like_names | Sort-Object -Unique)
    }

    $result=[ordered]@{
        mission='BAOZ-BASELINE-001'
        probe='BAOZ-PROBE-016'
        created_at=(Get-Date).ToString('yyyy-MM-ddTHH:mm:sszzz')
        safety=[ordered]@{
            read_only=$true
            metadata_and_aggregate_only=$true
            setting_values_output=$false
            horse_rows_output=$false
            baoz_modified=$false
        }
        snapshot_table_audit=$audit
        settings_name_audit=$settingsNames
        interpretation_note='Date-like columns can support as-of/history structure; their absence suggests snapshot-like storage but does not by itself prove how historical predictions were computed.'
    }

    if(-not $OutputPath){
        $outDir=Join-Path $env:TEMP 'JIZO\BAOZ-BASELINE-001'
        New-Item -ItemType Directory -Path $outDir -Force | Out-Null
        $OutputPath=Join-Path $outDir 'baoz_probe_016_snapshot_audit.json'
    }
    $result | ConvertTo-Json -Depth 14 | Set-Content -LiteralPath $OutputPath -Encoding utf8

    Write-Host ''
    Write-Host '============================================================' -ForegroundColor Cyan
    Write-Host ' BAOZ-PROBE-016 — SNAPSHOT / AS-OF AUDIT' -ForegroundColor Cyan
    Write-Host '============================================================' -ForegroundColor Cyan

    foreach($table in $audit.Keys){
        $m=$audit[$table]
        Write-Host ("--- {0} ---" -f $table) -ForegroundColor Yellow
        if(-not $m.exists){
            Write-Host 'exists: False'
            continue
        }
        Write-Host ("rows              : {0}" -f $m.rows)
        Write-Host ("columns           : {0}" -f (($m.columns) -join ', '))
        Write-Host ("date-like columns : {0}" -f (($m.date_like_columns) -join ', '))
        Write-Host ("version-like      : {0}" -f (($m.version_like_columns) -join ', '))
        foreach($name in $m.date_ranges.Keys){
            $r=$m.date_ranges[$name]
            if($r.Contains('error')){
                Write-Host ("  {0}: ERROR {1}" -f $name,$r.error)
            }else{
                Write-Host ("  {0}: n={1} min={2} max={3}" -f $name,$r.nonnull,$r.min,$r.max)
            }
        }
        Write-Host ''
    }

    Write-Host '--- 設定T NAMES ONLY ---' -ForegroundColor Yellow
    Write-Host ("rows        : {0}" -f $settingsNames.rows)
    Write-Host ("fields      : {0}" -f (($settingsNames.field_names) -join ', '))
    $settingsNames.key_like_names | ForEach-Object { Write-Host $_ }

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
