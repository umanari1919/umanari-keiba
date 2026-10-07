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
            $conn.CommandTimeout=240
            $conn.Open("Provider=$provider;Data Source=$Path;Mode=Read;")
            return [pscustomobject]@{Connection=$conn;Provider=$provider}
        }catch{
            if($conn){
                try{$conn.Close()}catch{}
                try{[void][Runtime.InteropServices.Marshal]::ReleaseComObject($conn)}catch{}
            }
        }
    }
    return $null
}

function Invoke-Row {
    param([Parameter(Mandatory)]$Connection,[Parameter(Mandatory)][string]$Sql)
    $rs=$null
    try{
        $rs=$Connection.Execute($Sql)
        if($rs.EOF){return $null}
        $o=[ordered]@{}
        for($i=0;$i -lt $rs.Fields.Count;$i++){
            $name=[string]$rs.Fields.Item($i).Name
            $value=$rs.Fields.Item($i).Value
            if($value -is [DBNull]){$value=$null}
            $o[$name]=$value
        }
        return [pscustomobject]$o
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

function Get-ColumnNames {
    param([Parameter(Mandatory)]$Connection,[Parameter(Mandatory)][string]$Table)
    $schema=$null; $names=@()
    try{
        $schema=$Connection.OpenSchema(4)
        while(-not $schema.EOF){
            if([string]$schema.Fields.Item('TABLE_NAME').Value -eq $Table){
                $names += [string]$schema.Fields.Item('COLUMN_NAME').Value
            }
            $schema.MoveNext()
        }
        return @($names)
    }finally{
        if($schema){
            try{$schema.Close()}catch{}
            try{[void][Runtime.InteropServices.Marshal]::ReleaseComObject($schema)}catch{}
        }
    }
}

function Get-Fingerprint {
    param(
        [Parameter(Mandatory)]$Connection,
        [Parameter(Mandatory)][string]$Where,
        [Parameter(Mandatory)][string[]]$AvailableColumns
    )

    $parts=@(
        'Count(*) AS N',
        'Min([年月日]) AS MinDate',
        'Max([年月日]) AS MaxDate'
    )

    foreach($name in @('馬券評価順位','騎手評価','調教師評価','血統総合評価','予想タイム指数','デフォルト得点','得点')){
        if($AvailableColumns -contains $name){
            $alias=($name -replace '[^0-9A-Za-z一-龠ぁ-んァ-ヶー]','')
            $parts += "Sum(IIf([$name] Is Null,0,CDbl([$name]))) AS [SUM_$alias]"
            $parts += "Sum(IIf([$name] Is Null,0,CDbl([$name])*CDbl([$name]))) AS [SUMSQ_$alias]"
            $parts += "Count([$name]) AS [NN_$alias]"
        }
    }

    $sql="SELECT " + ($parts -join ", ") + " FROM [出走馬T] WHERE $Where"
    return Invoke-Row $Connection $sql
}

if(-not $BaoZPath){
    Write-Host 'BaoZ active DB root: auto-discovery...' -ForegroundColor DarkGray
    $BaoZPath=Find-BaoZRoot
}
$BaoZPath=(Resolve-Path -LiteralPath $BaoZPath).Path

$files=@(
    Get-ChildItem -LiteralPath $BaoZPath -Filter '*.mdb' -File -Recurse -Depth 6 -ErrorAction SilentlyContinue
) | Sort-Object FullName -Unique

$audit=@()
foreach($file in $files){
    $opened=Open-ReadOnlyConnection -Path $file.FullName
    if(-not $opened){continue}
    $conn=$opened.Connection

    try{
        $tables=Get-TableNames $conn
        if($tables -notcontains '出走馬T'){continue}

        $cols=Get-ColumnNames $conn '出走馬T'
        if($cols -notcontains '年月日'){continue}
        if($cols -notcontains '馬券評価順位'){continue}

        $periods=[ordered]@{
            '2012-2018'='[年月日] Between #2012-01-01# And #2018-12-31#'
            '2019-2023'='[年月日] Between #2019-01-01# And #2023-12-31#'
            '2024-2025'='[年月日] Between #2024-01-01# And #2025-12-31#'
        }

        $fps=[ordered]@{}
        foreach($p in $periods.Keys){
            try{
                $fps[$p]=Get-Fingerprint -Connection $conn -Where $periods[$p] -AvailableColumns $cols
            }catch{
                $fps[$p]=[ordered]@{error=$_.Exception.Message}
            }
        }

        $audit += [pscustomobject]@{
            path=$file.FullName
            file_name=$file.Name
            last_write=$file.LastWriteTime.ToString('yyyy-MM-ddTHH:mm:ss')
            size_mb=[math]::Round($file.Length/1MB,2)
            provider=$opened.Provider
            column_count=$cols.Count
            fingerprints=$fps
        }
    }finally{
        try{$conn.Close()}catch{}
        try{[void][Runtime.InteropServices.Marshal]::ReleaseComObject($conn)}catch{}
    }
}

$activePath=Join-Path $BaoZPath 'DB\BaoZ.mdb'
$active=$audit | Where-Object { $_.path -eq $activePath } | Select-Object -First 1
$comparisons=@()

if($active){
    foreach($candidate in $audit){
        if($candidate.path -eq $active.path){continue}

        foreach($period in @('2012-2018','2019-2023','2024-2025')){
            $a=$active.fingerprints[$period]
            $b=$candidate.fingerprints[$period]
            if(-not $a -or -not $b){continue}
            if($a.PSObject.Properties.Name -contains 'error' -or $b.PSObject.Properties.Name -contains 'error'){continue}

            $shared=@($a.PSObject.Properties.Name | Where-Object {
                $_ -notin @('MinDate','MaxDate') -and ($b.PSObject.Properties.Name -contains $_)
            })

            $equal=$true
            $diffs=@()
            foreach($name in $shared){
                $av=$a.$name
                $bv=$b.$name
                if("$av" -ne "$bv"){
                    $equal=$false
                    $diffs += $name
                }
            }

            $comparisons += [pscustomobject]@{
                candidate=$candidate.file_name
                candidate_path=$candidate.path
                candidate_last_write=$candidate.last_write
                period=$period
                exact_aggregate_match=$equal
                differing_metrics=($diffs -join ',')
                active_n=$a.N
                candidate_n=$b.N
            }
        }
    }
}

$result=[ordered]@{
    mission='BAOZ-BASELINE-001'
    probe='BAOZ-PROBE-018'
    created_at=(Get-Date).ToString('yyyy-MM-ddTHH:mm:sszzz')
    safety=[ordered]@{
        read_only=$true
        aggregate_only=$true
        horse_rows_output=$false
        baoz_modified=$false
    }
    active_db=$activePath
    comparable_runner_databases=$audit
    aggregate_comparisons=$comparisons
    interpretation_note='Exact aggregate matches across distinct database copies/version dates strongly support frozen historical materialization. Differences require follow-up and are not automatically leakage.'
}

if(-not $OutputPath){
    $outDir=Join-Path $env:TEMP 'JIZO\BAOZ-BASELINE-001'
    New-Item -ItemType Directory -Path $outDir -Force | Out-Null
    $OutputPath=Join-Path $outDir 'baoz_probe_018_cross_version_freeze.json'
}
$result | ConvertTo-Json -Depth 16 | Set-Content -LiteralPath $OutputPath -Encoding utf8

Write-Host ''
Write-Host '============================================================' -ForegroundColor Cyan
Write-Host ' BAOZ-PROBE-018 — CROSS-VERSION FREEZE' -ForegroundColor Cyan
Write-Host '============================================================' -ForegroundColor Cyan

Write-Host '--- COMPARABLE RUNNER DATABASES ---' -ForegroundColor Yellow
$audit |
    Select-Object file_name,last_write,size_mb,column_count,path |
    Format-Table -AutoSize |
    Out-String -Width 220 |
    Write-Host

Write-Host '--- ACTIVE vs OTHER COPIES ---' -ForegroundColor Yellow
$comparisons |
    Select-Object candidate,candidate_last_write,period,exact_aggregate_match,active_n,candidate_n,differing_metrics |
    Format-Table -AutoSize |
    Out-String -Width 240 |
    Write-Host

Write-Host ("Comparable DBs      : {0}" -f $audit.Count)
Write-Host ("Aggregate only      : {0}" -f $result.safety.aggregate_only)
Write-Host ("Horse rows output   : {0}" -f $result.safety.horse_rows_output)
Write-Host ("BaoZ modified       : {0}" -f $result.safety.baoz_modified)
Write-Host ("Output              : {0}" -f $OutputPath)
Write-Host '============================================================'
