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

function Convert-Metrics {
    param($Rows)
    $out=@()
    foreach($r in $Rows){
        $n=[int64]$r.N
        $out += [pscustomobject]@{
            key=[string]$r.K
            n=$n
            wins=[int64]$r.W
            win_rate=if($n){[math]::Round(([double]$r.W/$n),6)}else{$null}
            top2_rate=if($n){[math]::Round(([double]$r.T2/$n),6)}else{$null}
            top3_rate=if($n){[math]::Round(([double]$r.T3/$n),6)}else{$null}
            avg_popularity=if($null -ne $r.AP){[math]::Round([double]$r.AP,3)}else{$null}
        }
    }
    return @($out)
}

function Query-Segment {
    param(
        [Parameter(Mandatory)]$Connection,
        [Parameter(Mandatory)][string]$Expr,
        [Parameter(Mandatory)][string]$ExtraWhere
    )
    $sql=@"
SELECT $Expr AS K,
       Count(*) AS N,
       Sum(IIf(S.[確定着順]=1,1,0)) AS W,
       Sum(IIf(S.[確定着順] Between 1 And 2,1,0)) AS T2,
       Sum(IIf(S.[確定着順] Between 1 And 3,1,0)) AS T3,
       Avg(S.[単勝人気]) AS AP
FROM [出走馬T] AS S INNER JOIN [レースT] AS R
  ON S.[競走コード]=R.[競走コード]
WHERE S.[年月日] >= #2012-01-01#
  AND S.[年月日] <= #2026-10-08#
  AND S.[確定着順] Between 1 And 28
  AND S.[馬番] > 0
  AND S.[馬券評価順位]=1
  AND $ExtraWhere
GROUP BY $Expr
"@
    return Convert-Metrics (Invoke-Rows $Connection $sql)
}

function Compare-Periods {
    param($Before,$After)
    $keys=@($Before.key + $After.key | Sort-Object -Unique)
    $out=@()
    foreach($key in $keys){
        $a=$Before | Where-Object {$_.key -eq $key} | Select-Object -First 1
        $b=$After | Where-Object {$_.key -eq $key} | Select-Object -First 1
        if((-not $a -or $a.n -lt 25) -and (-not $b -or $b.n -lt 25)){continue}
        $expected=$null
        $deficit=$null
        if($a -and $b){
            $expected=[double]$a.win_rate*[double]$b.n
            $deficit=[double]$b.wins-$expected
        }
        $out += [pscustomobject]@{
            key=$key
            before_n=if($a){$a.n}else{0}
            before_win=if($a){$a.win_rate}else{$null}
            before_top3=if($a){$a.top3_rate}else{$null}
            after_n=if($b){$b.n}else{0}
            after_win=if($b){$b.win_rate}else{$null}
            after_top3=if($b){$b.top3_rate}else{$null}
            expected_after_wins=if($null -ne $expected){[math]::Round($expected,2)}else{$null}
            observed_after_wins=if($b){$b.wins}else{$null}
            win_deficit=if($null -ne $deficit){[math]::Round($deficit,2)}else{$null}
        }
    }
    return @($out | Sort-Object win_deficit)
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
    $before='S.[年月日] Between #2019-01-01# And #2023-12-31#'
    $after='S.[年月日] Between #2024-01-01# And #2026-10-08#'
    $focus='S.[単勝人気] Between 7 And 9 AND R.[トラック種別コード]=1'

    $cross=Invoke-Rows $conn @"
SELECT CStr(R.[主催者コード]) & "|" & CStr(R.[トラック種別コード]) AS K,
       Count(*) AS N
FROM [出走馬T] AS S INNER JOIN [レースT] AS R ON S.[競走コード]=R.[競走コード]
WHERE S.[年月日] Between #2012-01-01# And #2026-10-08#
  AND S.[確定着順] Between 1 And 28
  AND S.[馬番] > 0
  AND S.[馬券評価順位]=1
GROUP BY R.[主催者コード], R.[トラック種別コード]
ORDER BY R.[主催者コード], R.[トラック種別コード]
"@

    $beforeOrg=Query-Segment $conn 'CStr(R.[主催者コード])' "$before AND $focus"
    $afterOrg=Query-Segment $conn 'CStr(R.[主催者コード])' "$after AND $focus"

    $beforeVenue=Query-Segment $conn 'CStr(R.[場コード]) & ":" & IIf(IsNull(R.[場名]),"",R.[場名])' "$before AND $focus"
    $afterVenue=Query-Segment $conn 'CStr(R.[場コード]) & ":" & IIf(IsNull(R.[場名]),"",R.[場名])' "$after AND $focus"

    $yearly=Query-Segment $conn 'CStr(Year(S.[年月日]))' "$focus"

    $result=[ordered]@{
        mission='BAOZ-BASELINE-001'
        probe='BAOZ-PROBE-012'
        created_at=(Get-Date).ToString('yyyy-MM-ddTHH:mm:sszzz')
        safety=[ordered]@{
            read_only=$true
            aggregate_only=$true
            horse_rows_output=$false
            baoz_modified=$false
        }
        target='P7-9 x track_type=1 prediction drift'
        organizer_track_cross=$cross
        organizer_comparison=(Compare-Periods $beforeOrg $afterOrg)
        venue_comparison=(Compare-Periods $beforeVenue $afterVenue)
        yearly=$yearly
    }

    if(-not $OutputPath){
        $outDir=Join-Path $env:TEMP 'JIZO\BAOZ-BASELINE-001'
        New-Item -ItemType Directory -Path $outDir -Force | Out-Null
        $OutputPath=Join-Path $outDir 'baoz_probe_012_p7_9_track1.json'
    }
    $result | ConvertTo-Json -Depth 14 | Set-Content -LiteralPath $OutputPath -Encoding utf8

    Write-Host ''
    Write-Host '============================================================' -ForegroundColor Cyan
    Write-Host ' BAOZ-PROBE-012 — P7-9 x TRACK TYPE 1' -ForegroundColor Cyan
    Write-Host '============================================================' -ForegroundColor Cyan

    Write-Host '--- ORGANIZER x TRACK TYPE STRUCTURE ---' -ForegroundColor Yellow
    $cross | Format-Table K,N -AutoSize | Out-String -Width 120 | Write-Host

    Write-Host '--- ORGANIZER: 2019-2023 vs 2024-2026 ---' -ForegroundColor Yellow
    $result.organizer_comparison |
        Format-Table key,before_n,before_win,before_top3,after_n,after_win,after_top3,expected_after_wins,observed_after_wins,win_deficit -AutoSize |
        Out-String -Width 180 |
        Write-Host

    Write-Host '--- VENUE: 2019-2023 vs 2024-2026 ---' -ForegroundColor Yellow
    $result.venue_comparison |
        Select-Object -First 30 |
        Format-Table key,before_n,before_win,before_top3,after_n,after_win,after_top3,expected_after_wins,observed_after_wins,win_deficit -AutoSize |
        Out-String -Width 190 |
        Write-Host

    Write-Host '--- YEARLY ---' -ForegroundColor Yellow
    $yearly |
        Sort-Object {[int]$_.key} |
        Format-Table key,n,win_rate,top2_rate,top3_rate,avg_popularity -AutoSize |
        Out-String -Width 150 |
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
