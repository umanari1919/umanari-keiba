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
    throw "Could not open MDB read-only: $Path"
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

function Invoke-Scalar {
    param([Parameter(Mandatory)]$Connection,[Parameter(Mandatory)][string]$Sql)
    $row=Invoke-Row $Connection $Sql
    if(-not $row){return $null}
    return $row.PSObject.Properties[0].Value
}

function Get-ColumnMeta {
    param([Parameter(Mandatory)]$Connection,[Parameter(Mandatory)][string]$Table,[Parameter(Mandatory)][string]$Column)
    $schema=$null
    try{
        $schema=$Connection.OpenSchema(4)
        while(-not $schema.EOF){
            $tn=[string]$schema.Fields.Item('TABLE_NAME').Value
            $cn=[string]$schema.Fields.Item('COLUMN_NAME').Value
            if($tn -eq $Table -and $cn -eq $Column){
                $dt=$schema.Fields.Item('DATA_TYPE').Value
                return [pscustomobject]@{
                    table=$tn
                    column=$cn
                    data_type=if($dt -is [DBNull]){$null}else{[int]$dt}
                }
            }
            $schema.MoveNext()
        }
        return $null
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
    $meta=Get-ColumnMeta $conn 'レースT' 'レコード作成fromtime'

    $periods=[ordered]@{
        '2012-2018'='[月日] Between #2012-01-01# And #2018-12-31#'
        '2019-2023'='[月日] Between #2019-01-01# And #2023-12-31#'
        '2024-2025'='[月日] Between #2024-01-01# And #2025-12-31#'
        '2026'='[月日] Between #2026-01-01# And #2026-12-31#'
        'FUTURE'='[月日] > #2026-10-08#'
    }

    $periodAudit=[ordered]@{}
    foreach($p in $periods.Keys){
        $w=$periods[$p]
        $periodAudit[$p]=Invoke-Row $conn @"
SELECT Count(*) AS N,
       Count([レコード作成fromtime]) AS NonNull,
       Min([レコード作成fromtime]) AS MinFromTime,
       Max([レコード作成fromtime]) AS MaxFromTime,
       Min([月日]) AS MinRaceDate,
       Max([月日]) AS MaxRaceDate
FROM [レースT]
WHERE $w
"@
    }

    $dateRelation=$null
    if($meta -and $meta.data_type -in @(7,133,134,135)){
        try{
            $dateRelation=Invoke-Row $conn @"
SELECT
  Sum(IIf([レコード作成fromtime] < [月日],1,0)) AS BeforeRace,
  Sum(IIf(DateValue([レコード作成fromtime]) = DateValue([月日]),1,0)) AS SameDay,
  Sum(IIf(DateValue([レコード作成fromtime]) > DateValue([月日]),1,0)) AS AfterRace,
  Count([レコード作成fromtime]) AS NonNull
FROM [レースT]
WHERE [月日] Between #2012-01-01# And #2026-10-08#
"@
        }catch{
            $dateRelation=[pscustomobject]@{error=$_.Exception.Message}
        }
    }

    $flagAudit=Invoke-Row $conn @"
SELECT Count(*) AS N,
       Sum(IIf([予想計算状況フラグ] Is Null,1,0)) AS FlagNull,
       Sum(IIf([予想計算状況フラグ]=0,1,0)) AS FlagZero,
       Sum(IIf([予想計算状況フラグ]<>0,1,0)) AS FlagNonZero
FROM [レースT]
WHERE [月日] Between #2012-01-01# And #2026-10-08#
"@

    $backupRoot=Join-Path $BaoZPath 'Backup'
    $backupArtifacts=@()
    if(Test-Path -LiteralPath $backupRoot){
        $backupArtifacts=@(
            Get-ChildItem -LiteralPath $backupRoot -File -Recurse -Depth 8 -ErrorAction SilentlyContinue |
            Where-Object {
                $_.Extension -match '^\.(mdb|accdb|zip|7z|rar|bak|cab|gz|tar)$'
            } |
            ForEach-Object {
                [pscustomobject]@{
                    name=$_.Name
                    extension=$_.Extension
                    last_write=$_.LastWriteTime.ToString('yyyy-MM-ddTHH:mm:ss')
                    size_mb=[math]::Round($_.Length/1MB,2)
                    path=$_.FullName
                }
            } |
            Sort-Object last_write,path
        )
    }

    $distinctBackupDays=@($backupArtifacts | ForEach-Object {
        try{([datetime]$_.last_write).ToString('yyyy-MM-dd')}catch{$null}
    } | Where-Object {$_} | Sort-Object -Unique)

    $result=[ordered]@{
        mission='BAOZ-BASELINE-001'
        probe='BAOZ-PROBE-019'
        created_at=(Get-Date).ToString('yyyy-MM-ddTHH:mm:sszzz')
        safety=[ordered]@{
            read_only=$true
            aggregate_and_metadata_only=$true
            horse_rows_output=$false
            baoz_modified=$false
        }
        record_creation_fromtime_meta=$meta
        record_creation_by_period=$periodAudit
        record_creation_vs_race=$dateRelation
        prediction_status_flag=$flagAudit
        backup_artifacts=$backupArtifacts
        distinct_backup_days=$distinctBackupDays
        interpretation_note='レコード作成fromtime provenance meaning is inferred only from distributions; backup artifact dates identify whether a genuine longitudinal cross-version freeze test is possible.'
    }

    if(-not $OutputPath){
        $outDir=Join-Path $env:TEMP 'JIZO\BAOZ-BASELINE-001'
        New-Item -ItemType Directory -Path $outDir -Force | Out-Null
        $OutputPath=Join-Path $outDir 'baoz_probe_019_creation_and_backup_history.json'
    }
    $result | ConvertTo-Json -Depth 16 | Set-Content -LiteralPath $OutputPath -Encoding utf8

    Write-Host ''
    Write-Host '============================================================' -ForegroundColor Cyan
    Write-Host ' BAOZ-PROBE-019 — CREATION TIME / BACKUP HISTORY' -ForegroundColor Cyan
    Write-Host '============================================================' -ForegroundColor Cyan

    Write-Host '--- レコード作成fromtime META ---' -ForegroundColor Yellow
    if($meta){
        $meta | Format-List | Out-String -Width 140 | Write-Host
    }else{
        Write-Host 'Column metadata not found.'
    }

    Write-Host '--- PERIOD DISTRIBUTION ---' -ForegroundColor Yellow
    foreach($p in $periodAudit.Keys){
        $m=$periodAudit[$p]
        Write-Host ("{0,-10} N={1,7} nonnull={2,7} race={3}..{4} from={5}..{6}" -f
            $p,$m.N,$m.NonNull,$m.MinRaceDate,$m.MaxRaceDate,$m.MinFromTime,$m.MaxFromTime)
    }

    Write-Host ''
    Write-Host '--- FROMTIME vs RACE DATE ---' -ForegroundColor Yellow
    if($dateRelation){
        $dateRelation | Format-List | Out-String -Width 140 | Write-Host
    }else{
        Write-Host 'Date relation not attempted because column is not a recognized date/time provider type.'
    }

    Write-Host '--- 予想計算状況フラグ ---' -ForegroundColor Yellow
    $flagAudit | Format-List | Out-String -Width 140 | Write-Host

    Write-Host '--- BACKUP ARTIFACTS ---' -ForegroundColor Yellow
    if($backupArtifacts.Count -gt 0){
        $backupArtifacts |
            Select-Object name,last_write,size_mb,path |
            Format-Table -AutoSize |
            Out-String -Width 220 |
            Write-Host
    }else{
        Write-Host 'No MDB/archive-like backup artifacts found.'
    }

    Write-Host ("Distinct backup days : {0}" -f ($distinctBackupDays -join ', '))
    Write-Host ("Artifact count       : {0}" -f $backupArtifacts.Count)
    Write-Host ("Aggregate only       : {0}" -f $result.safety.aggregate_and_metadata_only)
    Write-Host ("Horse rows output    : {0}" -f $result.safety.horse_rows_output)
    Write-Host ("BaoZ modified        : {0}" -f $result.safety.baoz_modified)
    Write-Host ("Output               : {0}" -f $OutputPath)
    Write-Host '============================================================'
}
finally{
    try{$conn.Close()}catch{}
    try{[void][Runtime.InteropServices.Marshal]::ReleaseComObject($conn)}catch{}
}
