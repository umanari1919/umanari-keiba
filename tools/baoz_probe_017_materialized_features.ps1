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

function Count-Rows {
    param([Parameter(Mandatory)]$Connection,[Parameter(Mandatory)][string]$Sql)
    $rs=$null; $n=0
    try{
        $rs=$Connection.Execute($Sql)
        while(-not $rs.EOF){ $n++; $rs.MoveNext() }
        return $n
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
                $name=[string]$schema.Fields.Item('COLUMN_NAME').Value
                $ord=$schema.Fields.Item('ORDINAL_POSITION').Value
                $dt=$schema.Fields.Item('DATA_TYPE').Value
                $cols += [pscustomobject]@{
                    ordinal=if($ord -is [DBNull]){2147483647}else{[int]$ord}
                    name=$name
                    data_type=if($dt -is [DBNull]){$null}else{[int]$dt}
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

function Is-NumericType {
    param($DataType)
    return $DataType -in @(2,3,4,5,6,14,16,17,18,19,20,21,131)
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
    $cols=Get-Columns $conn '出走馬T'
    $allNames=@($cols | ForEach-Object {$_.name})

    $featureRegex='騎手|調教師|血統|父|母|コース|適性|評価|指数|得点|脚質|距離|馬場'
    $excludeRegex='順位|人気|オッズ|配当|着順|馬番|枠番|競走コード|馬名|年月日|作成|時刻|投票|確定|入線'
    $candidates=@($cols | Where-Object {
        $_.name -match $featureRegex -and $_.name -notmatch $excludeRegex
    })

    $periods=[ordered]@{
        '2012-2018'='[年月日] Between #2012-01-01# And #2018-12-31#'
        '2019-2023'='[年月日] Between #2019-01-01# And #2023-12-31#'
        '2024-2026'="[年月日] Between #2024-01-01# And #$cutoff#"
        'FUTURE'="[年月日] > #$cutoff#"
    }

    $coverage=[ordered]@{}
    foreach($col in $candidates){
        $name=$col.name
        $entry=[ordered]@{
            data_type=$col.data_type
            numeric=(Is-NumericType $col.data_type)
            periods=[ordered]@{}
        }

        foreach($p in $periods.Keys){
            $where=$periods[$p]
            $nonnull=[int64](Invoke-Scalar $conn "SELECT Count(*) FROM [出走馬T] WHERE $where AND [$name] Is Not Null")
            $pe=[ordered]@{nonnull=$nonnull}
            if($entry.numeric -and $nonnull -gt 0){
                try{
                    $pe.avg=Invoke-Scalar $conn "SELECT Avg([$name]) FROM [出走馬T] WHERE $where AND [$name] Is Not Null"
                    $pe.min=Invoke-Scalar $conn "SELECT Min([$name]) FROM [出走馬T] WHERE $where AND [$name] Is Not Null"
                    $pe.max=Invoke-Scalar $conn "SELECT Max([$name]) FROM [出走馬T] WHERE $where AND [$name] Is Not Null"
                }catch{
                    $pe.aggregate_error=$_.Exception.Message
                }
            }
            $entry.periods[$p]=$pe
        }
        $coverage[$name]=$entry
    }

    $domains=[ordered]@{
        jockey=[ordered]@{
            key_candidates=@('騎手コード')
            feature_pattern='騎手.*(評価|指数|得点|成績|適性|ランク)'
        }
        trainer=[ordered]@{
            key_candidates=@('調教師コード')
            feature_pattern='調教師.*(評価|指数|得点|成績|適性|ランク)'
        }
    }

    $variation=[ordered]@{}
    foreach($domain in $domains.Keys){
        $d=$domains[$domain]
        $key=$null
        foreach($kc in $d.key_candidates){
            if($allNames -contains $kc){$key=$kc;break}
        }

        $variation[$domain]=[ordered]@{
            key_column=$key
            features=[ordered]@{}
        }

        if(-not $key){continue}

        $features=@($candidates | Where-Object {
            $_.name -match $d.feature_pattern -and (Is-NumericType $_.data_type)
        })

        foreach($fc in $features){
            $name=$fc.name
            try{
                $sql=@"
SELECT [$key], Min([$name]) AS MinV, Max([$name]) AS MaxV, Count([$name]) AS N
FROM [出走馬T]
WHERE [年月日] Between #2012-01-01# And #$cutoff#
  AND [$key] Is Not Null
  AND [$name] Is Not Null
GROUP BY [$key]
HAVING Count([$name]) >= 2 AND Min([$name]) <> Max([$name])
"@
                $varying=Count-Rows $conn $sql
                $entitySql="SELECT [$key] FROM [出走馬T] WHERE [年月日] Between #2012-01-01# And #$cutoff# AND [$key] Is Not Null AND [$name] Is Not Null GROUP BY [$key]"
                $entities=Count-Rows $conn $entitySql
                $variation[$domain].features[$name]=[ordered]@{
                    entities_with_values=$entities
                    entities_with_historical_variation=$varying
                }
            }catch{
                $variation[$domain].features[$name]=[ordered]@{
                    error=$_.Exception.Message
                }
            }
        }
    }

    $result=[ordered]@{
        mission='BAOZ-BASELINE-001'
        probe='BAOZ-PROBE-017'
        created_at=(Get-Date).ToString('yyyy-MM-ddTHH:mm:sszzz')
        safety=[ordered]@{
            read_only=$true
            metadata_and_aggregate_only=$true
            horse_rows_output=$false
            baoz_modified=$false
        }
        runner_feature_candidates=@($candidates | ForEach-Object {
            [ordered]@{name=$_.name;data_type=$_.data_type;numeric=(Is-NumericType $_.data_type)}
        })
        feature_period_coverage=$coverage
        same_entity_historical_variation=$variation
        interpretation_note='Historical variation within materialized per-runner features supports frozen per-race values, but does not alone prove that every upstream input was temporally leakage-safe.'
    }

    if(-not $OutputPath){
        $outDir=Join-Path $env:TEMP 'JIZO\BAOZ-BASELINE-001'
        New-Item -ItemType Directory -Path $outDir -Force | Out-Null
        $OutputPath=Join-Path $outDir 'baoz_probe_017_materialized_features.json'
    }
    $result | ConvertTo-Json -Depth 16 | Set-Content -LiteralPath $OutputPath -Encoding utf8

    Write-Host ''
    Write-Host '============================================================' -ForegroundColor Cyan
    Write-Host ' BAOZ-PROBE-017 — MATERIALIZED HISTORICAL FEATURES' -ForegroundColor Cyan
    Write-Host '============================================================' -ForegroundColor Cyan

    Write-Host '--- CANDIDATE FEATURE COLUMNS ---' -ForegroundColor Yellow
    $result.runner_feature_candidates |
        Format-Table name,data_type,numeric -AutoSize |
        Out-String -Width 160 |
        Write-Host

    Write-Host '--- PERIOD COVERAGE / NUMERIC DISTRIBUTION ---' -ForegroundColor Yellow
    foreach($name in $coverage.Keys){
        $e=$coverage[$name]
        if(-not $e.numeric){continue}
        $a=$e.periods['2012-2018']; $b=$e.periods['2019-2023']; $d=$e.periods['2024-2026']; $f=$e.periods['FUTURE']
        Write-Host ("{0}: old n={1} avg={2} | mid n={3} avg={4} | recent n={5} avg={6} | future n={7} avg={8}" -f
            $name,$a.nonnull,$a.avg,$b.nonnull,$b.avg,$d.nonnull,$d.avg,$f.nonnull,$f.avg)
    }

    Write-Host ''
    Write-Host '--- SAME-ENTITY HISTORICAL VARIATION ---' -ForegroundColor Yellow
    foreach($domain in $variation.Keys){
        $d=$variation[$domain]
        Write-Host ("[{0}] key={1}" -f $domain,$d.key_column)
        foreach($name in $d.features.Keys){
            $m=$d.features[$name]
            if($m.Contains('error')){
                Write-Host ("  {0}: ERROR {1}" -f $name,$m.error)
            }else{
                Write-Host ("  {0}: entities={1}, varying={2}" -f $name,$m.entities_with_values,$m.entities_with_historical_variation)
            }
        }
    }

    Write-Host ''
    Write-Host ("Metadata/aggregate only : {0}" -f $result.safety.metadata_and_aggregate_only)
    Write-Host ("Horse rows output       : {0}" -f $result.safety.horse_rows_output)
    Write-Host ("BaoZ modified           : {0}" -f $result.safety.baoz_modified)
    Write-Host ("Output                  : {0}" -f $OutputPath)
    Write-Host '============================================================'
}
finally{
    try{$conn.Close()}catch{}
    try{[void][Runtime.InteropServices.Marshal]::ReleaseComObject($conn)}catch{}
}
