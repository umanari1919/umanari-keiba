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

function Invoke-Rows {
    param([Parameter(Mandatory)]$Connection,[Parameter(Mandatory)][string]$Sql)
    $rs=$null; $rows=@()
    try{
        $rs=$Connection.Execute($Sql)
        while(-not $rs.EOF){
            $obj=[ordered]@{}
            for($i=0;$i -lt $rs.Fields.Count;$i++){
                $name=[string]$rs.Fields.Item($i).Name
                $value=$rs.Fields.Item($i).Value
                if($value -is [DBNull]){$value=$null}
                $obj[$name]=$value
            }
            $rows += [pscustomobject]$obj
            $rs.MoveNext()
        }
        return @($rows)
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

    $trackMap=Invoke-Rows $conn @"
SELECT R.[主催者コード] AS Organizer,
       R.[トラック種別コード] AS TrackType,
       R.[トラックコード] AS RawTrackCode,
       Count(*) AS N
FROM [レースT] AS R
WHERE R.[月日] Between #2012-01-01# And #$cutoff#
GROUP BY R.[主催者コード], R.[トラック種別コード], R.[トラックコード]
ORDER BY R.[主催者コード], R.[トラック種別コード], R.[トラックコード]
"@

    $yearOrg=Invoke-Rows $conn @"
SELECT Year(S.[年月日]) AS Y,
       R.[主催者コード] AS Organizer,
       Count(*) AS N,
       Sum(IIf(S.[確定着順]=1,1,0)) AS W,
       Sum(IIf(S.[確定着順] Between 1 And 2,1,0)) AS T2,
       Sum(IIf(S.[確定着順] Between 1 And 3,1,0)) AS T3
FROM [出走馬T] AS S INNER JOIN [レースT] AS R
  ON S.[競走コード]=R.[競走コード]
WHERE S.[年月日] Between #2012-01-01# And #$cutoff#
  AND S.[確定着順] Between 1 And 28
  AND S.[馬番] > 0
  AND S.[馬券評価順位]=1
  AND S.[単勝人気] Between 7 And 9
  AND R.[トラック種別コード]=1
GROUP BY Year(S.[年月日]), R.[主催者コード]
ORDER BY Year(S.[年月日]), R.[主催者コード]
"@

    $yearOrgMetrics=@()
    foreach($r in $yearOrg){
        $n=[int64]$r.N
        $yearOrgMetrics += [pscustomobject]@{
            year=[int]$r.Y
            organizer=[int]$r.Organizer
            n=$n
            win_rate=if($n){[math]::Round(([double]$r.W/$n),6)}else{$null}
            top2_rate=if($n){[math]::Round(([double]$r.T2/$n),6)}else{$null}
            top3_rate=if($n){[math]::Round(([double]$r.T3/$n),6)}else{$null}
        }
    }

    $venueRecent=Invoke-Rows $conn @"
SELECT R.[主催者コード] AS Organizer,
       R.[場コード] AS VenueCode,
       R.[場名] AS VenueName,
       Count(*) AS N,
       Sum(IIf(S.[確定着順]=1,1,0)) AS W,
       Sum(IIf(S.[確定着順] Between 1 And 3,1,0)) AS T3
FROM [出走馬T] AS S INNER JOIN [レースT] AS R
  ON S.[競走コード]=R.[競走コード]
WHERE S.[年月日] Between #2024-01-01# And #$cutoff#
  AND S.[確定着順] Between 1 And 28
  AND S.[馬番] > 0
  AND S.[馬券評価順位]=1
  AND S.[単勝人気] Between 7 And 9
  AND R.[トラック種別コード]=1
GROUP BY R.[主催者コード], R.[場コード], R.[場名]
ORDER BY Count(*) DESC
"@

    $venueRecentMetrics=@()
    foreach($r in $venueRecent){
        $n=[int64]$r.N
        $venueRecentMetrics += [pscustomobject]@{
            organizer=[int]$r.Organizer
            venue_code=[int]$r.VenueCode
            venue_name=[string]$r.VenueName
            n=$n
            win_rate=if($n){[math]::Round(([double]$r.W/$n),6)}else{$null}
            top3_rate=if($n){[math]::Round(([double]$r.T3/$n),6)}else{$null}
        }
    }

    $result=[ordered]@{
        mission='BAOZ-BASELINE-001'
        probe='BAOZ-PROBE-013'
        created_at=(Get-Date).ToString('yyyy-MM-ddTHH:mm:sszzz')
        safety=[ordered]@{
            read_only=$true
            aggregate_only=$true
            horse_rows_output=$false
            baoz_modified=$false
        }
        track_type_to_raw_track_code=$trackMap
        p7_9_track1_year_by_organizer=$yearOrgMetrics
        p7_9_track1_recent_venue=$venueRecentMetrics
    }

    if(-not $OutputPath){
        $outDir=Join-Path $env:TEMP 'JIZO\BAOZ-BASELINE-001'
        New-Item -ItemType Directory -Path $outDir -Force | Out-Null
        $OutputPath=Join-Path $outDir 'baoz_probe_013_track_semantics.json'
    }
    $result | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $OutputPath -Encoding utf8

    Write-Host ''
    Write-Host '============================================================' -ForegroundColor Cyan
    Write-Host ' BAOZ-PROBE-013 — TRACK SEMANTICS' -ForegroundColor Cyan
    Write-Host '============================================================' -ForegroundColor Cyan

    Write-Host '--- TRACK TYPE -> RAW TRACK CODE ---' -ForegroundColor Yellow
    $trackMap |
        Format-Table Organizer,TrackType,RawTrackCode,N -AutoSize |
        Out-String -Width 140 |
        Write-Host

    Write-Host '--- P7-9 x TRACK1 / YEAR x ORGANIZER ---' -ForegroundColor Yellow
    $yearOrgMetrics |
        Format-Table year,organizer,n,win_rate,top2_rate,top3_rate -AutoSize |
        Out-String -Width 150 |
        Write-Host

    Write-Host '--- P7-9 x TRACK1 / 2024-2026 VENUES ---' -ForegroundColor Yellow
    $venueRecentMetrics |
        Select-Object -First 30 |
        Format-Table organizer,venue_code,venue_name,n,win_rate,top3_rate -AutoSize |
        Out-String -Width 160 |
        Write-Host

    Write-Host ("Aggregate only      : {0}" -f $result.safety.aggregate_only)
    Write-Host ("Horse rows output   : {0}" -f $result.safety.horse_rows_output)
    Write-Host ("BaoZ modified       : {0}" -f $result.safety.baoz_modified)
    Write-Host ("Output              : {0}" -f $OutputPath)
    Write-Host '============================================================'
}
finally{
    try{$conn.Close()}catch{}
    try{[void][Runtime.InteropServices.Marshal]::ReleaseComObject($conn)}catch{}
}
