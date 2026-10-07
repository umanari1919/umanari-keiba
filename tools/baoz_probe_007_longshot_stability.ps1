[CmdletBinding()]
param(
    [string]$BaoZPath = '',
    [datetime]$CutoffDate = [datetime]'2026-10-08',
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
        } catch {}
    }
    throw 'BaoZ active DB root was not found.'
}

function Open-ReadOnlyConnection {
    param([Parameter(Mandatory)][string]$Path)

    foreach ($provider in @('Microsoft.ACE.OLEDB.16.0','Microsoft.ACE.OLEDB.12.0','Microsoft.Jet.OLEDB.4.0')) {
        $conn=$null
        try {
            $conn=New-Object -ComObject ADODB.Connection
            $conn.ConnectionTimeout=5
            $conn.CommandTimeout=180
            $conn.Open("Provider=$provider;Data Source=$Path;Mode=Read;")
            return [pscustomobject]@{Connection=$conn;Provider=$provider}
        } catch {
            if($conn){
                try{$conn.Close()}catch{}
                try{[void][Runtime.InteropServices.Marshal]::ReleaseComObject($conn)}catch{}
            }
        }
    }
    throw "Could not open MDB read-only: $Path"
}

function Invoke-Scalar {
    param(
        [Parameter(Mandatory)]$Connection,
        [Parameter(Mandatory)][string]$Sql
    )
    $rs=$null
    try {
        $rs=$Connection.Execute($Sql)
        if($rs.EOF){return $null}
        $v=$rs.Fields.Item(0).Value
        if($v -is [DBNull]){return $null}
        return $v
    }
    finally {
        if($rs){
            try{$rs.Close()}catch{}
            try{[void][Runtime.InteropServices.Marshal]::ReleaseComObject($rs)}catch{}
        }
    }
}

function Invoke-Rows {
    param(
        [Parameter(Mandatory)]$Connection,
        [Parameter(Mandatory)][string]$Sql
    )
    $rs=$null
    $rows=@()
    try {
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
    }
    finally {
        if($rs){
            try{$rs.Close()}catch{}
            try{[void][Runtime.InteropServices.Marshal]::ReleaseComObject($rs)}catch{}
        }
    }
}

function Get-Metrics {
    param(
        [Parameter(Mandatory)]$Connection,
        [Parameter(Mandatory)][string]$Where
    )

    $starts=[int64](Invoke-Scalar $Connection "SELECT Count(*) FROM [出走馬T] WHERE $Where")
    $wins=[int64](Invoke-Scalar $Connection "SELECT Count(*) FROM [出走馬T] WHERE $Where AND [確定着順]=1")
    $top2=[int64](Invoke-Scalar $Connection "SELECT Count(*) FROM [出走馬T] WHERE $Where AND [確定着順] Between 1 And 2")
    $top3=[int64](Invoke-Scalar $Connection "SELECT Count(*) FROM [出走馬T] WHERE $Where AND [確定着順] Between 1 And 3")
    $winReturn=Invoke-Scalar $Connection "SELECT Sum([単勝配当]) FROM [出走馬T] WHERE $Where"
    $placeReturn=Invoke-Scalar $Connection "SELECT Sum([複勝配当]) FROM [出走馬T] WHERE $Where"
    if($null -eq $winReturn){$winReturn=0}
    if($null -eq $placeReturn){$placeReturn=0}
    $den=[double]($starts*100)

    return [ordered]@{
        starts=$starts
        wins=$wins
        top2=$top2
        top3=$top3
        win_rate=if($starts){[math]::Round($wins/$starts,6)}else{$null}
        top2_rate=if($starts){[math]::Round($top2/$starts,6)}else{$null}
        top3_rate=if($starts){[math]::Round($top3/$starts,6)}else{$null}
        win_index_pct=if($den){[math]::Round(([double]$winReturn/$den)*100,3)}else{$null}
        place_index_pct=if($den){[math]::Round(([double]$placeReturn/$den)*100,3)}else{$null}
        win_return_yen=[int64]$winReturn
        place_return_yen=[int64]$placeReturn
    }
}

if(-not $BaoZPath){
    Write-Host 'BaoZ active DB root: auto-discovery...' -ForegroundColor DarkGray
    $BaoZPath=Find-BaoZRoot
}
$BaoZPath=(Resolve-Path -LiteralPath $BaoZPath).Path
$db=Join-Path $BaoZPath 'DB\BaoZ.ex.mdb'

$opened=Open-ReadOnlyConnection -Path $db
$conn=$opened.Connection

try {
    $cutoff=$CutoffDate.ToString('yyyy-MM-dd')
    $base="([年月日] >= #1986-01-01# AND [年月日] <= #$cutoff# AND [確定着順] Between 1 And 28 AND [馬番] > 0)"

    $rankFields=@(
        '予想タイム指数順位',
        '馬券評価順位',
        '得点V1順位',
        '得点V2順位',
        'デフォルト得点順位',
        '得点V3順位'
    )

    # Exact agreement, emitted as PSCustomObject so Format-Table renders correctly.
    $agreement=@()
    for($i=0;$i -lt $rankFields.Count;$i++){
        for($j=$i+1;$j -lt $rankFields.Count;$j++){
            $a=$rankFields[$i]; $b=$rankFields[$j]
            $both=[int64](Invoke-Scalar $conn "SELECT Count(*) FROM [出走馬T] WHERE $base AND [$a] Is Not Null AND [$b] Is Not Null")
            $equal=[int64](Invoke-Scalar $conn "SELECT Count(*) FROM [出走馬T] WHERE $base AND [$a]=[$b]")
            $a1=[int64](Invoke-Scalar $conn "SELECT Count(*) FROM [出走馬T] WHERE $base AND [$a]=1")
            $b1=[int64](Invoke-Scalar $conn "SELECT Count(*) FROM [出走馬T] WHERE $base AND [$b]=1")
            $overlap=[int64](Invoke-Scalar $conn "SELECT Count(*) FROM [出走馬T] WHERE $base AND [$a]=1 AND [$b]=1")
            $union=$a1+$b1-$overlap
            $agreement += [pscustomobject]@{
                rank_a=$a
                rank_b=$b
                exact_rank_equal_pct=if($both){[math]::Round(($equal/$both)*100,3)}else{$null}
                rank1_overlap=$overlap
                rank1_jaccard_pct=if($union){[math]::Round(($overlap/$union)*100,3)}else{$null}
            }
        }
    }

    $focus=@('馬券評価順位','得点V2順位','得点V3順位','予想タイム指数順位')
    $popBands=[ordered]@{
        'P7-9'='[単勝人気] Between 7 And 9'
        'P10-12'='[単勝人気] Between 10 And 12'
        'P13+'='[単勝人気] >= 13'
    }

    $eraBands=[ordered]@{
        '1999-2004'='[年月日] Between #1999-01-01# And #2004-12-31#'
        '2005-2009'='[年月日] Between #2005-01-01# And #2009-12-31#'
        '2010-2014'='[年月日] Between #2010-01-01# And #2014-12-31#'
        '2015-2019'='[年月日] Between #2015-01-01# And #2019-12-31#'
        '2020-2024'='[年月日] Between #2020-01-01# And #2024-12-31#'
        '2025-2026'='[年月日] Between #2025-01-01# And #2026-10-08#'
    }

    $focusResults=[ordered]@{}
    foreach($field in $focus){
        $where="$base AND [$field]=1 AND [単勝人気] >= 7"
        $entry=[ordered]@{
            overall=Get-Metrics $conn $where
            popularity_subbands=[ordered]@{}
            eras=[ordered]@{}
            years=@()
            tail=[ordered]@{}
        }

        foreach($band in $popBands.Keys){
            $entry.popularity_subbands[$band]=Get-Metrics $conn "$base AND [$field]=1 AND $($popBands[$band])"
        }
        foreach($era in $eraBands.Keys){
            $entry.eras[$era]=Get-Metrics $conn "$base AND [$field]=1 AND [単勝人気] >= 7 AND $($eraBands[$era])"
        }

        $yearSql=@"
SELECT Year([年月日]) AS Y,
       Count(*) AS N,
       Sum(IIf([確定着順]=1,1,0)) AS W,
       Sum(IIf([確定着順] Between 1 And 2,1,0)) AS T2,
       Sum(IIf([確定着順] Between 1 And 3,1,0)) AS T3,
       Sum([単勝配当]) AS WR,
       Sum([複勝配当]) AS PR
FROM [出走馬T]
WHERE $where
GROUP BY Year([年月日])
ORDER BY Year([年月日])
"@
        $yearRows=Invoke-Rows $conn $yearSql
        foreach($r in $yearRows){
            $n=[int64]$r.N
            $entry.years += [pscustomobject]@{
                year=[int]$r.Y
                n=$n
                wins=[int64]$r.W
                win_rate=if($n){[math]::Round(([double]$r.W/$n),6)}else{$null}
                top3_rate=if($n){[math]::Round(([double]$r.T3/$n),6)}else{$null}
                win_index_pct=if($n){[math]::Round(([double]$r.WR/($n*100))*100,3)}else{$null}
                place_index_pct=if($n){[math]::Round(([double]$r.PR/($n*100))*100,3)}else{$null}
            }
        }

        $totalReturn=[double]$entry.overall.win_return_yen
        foreach($threshold in @(5000,10000,20000,50000)){
            $cnt=[int64](Invoke-Scalar $conn "SELECT Count(*) FROM [出走馬T] WHERE $where AND [単勝配当] >= $threshold")
            $sum=Invoke-Scalar $conn "SELECT Sum([単勝配当]) FROM [出走馬T] WHERE $where AND [単勝配当] >= $threshold"
            if($null -eq $sum){$sum=0}
            $entry.tail["payout_ge_$threshold"]=[ordered]@{
                winning_rows=$cnt
                return_yen=[int64]$sum
                share_of_total_return_pct=if($totalReturn){[math]::Round(([double]$sum/$totalReturn)*100,3)}else{$null}
            }
        }
        $focusResults[$field]=$entry
    }

    $result=[ordered]@{
        mission='BAOZ-BASELINE-001'
        probe='BAOZ-PROBE-007'
        created_at=(Get-Date).ToString('yyyy-MM-ddTHH:mm:sszzz')
        safety=[ordered]@{
            read_only=$true
            aggregate_only=$true
            horse_rows_output=$false
            baoz_modified=$false
        }
        rank_agreement=$agreement
        p7plus_stability=$focusResults
    }

    if(-not $OutputPath){
        $outDir=Join-Path $env:TEMP 'JIZO\BAOZ-BASELINE-001'
        New-Item -ItemType Directory -Path $outDir -Force | Out-Null
        $OutputPath=Join-Path $outDir 'baoz_probe_007_longshot_stability.json'
    }
    $result | ConvertTo-Json -Depth 16 | Set-Content -LiteralPath $OutputPath -Encoding utf8

    Write-Host ''
    Write-Host '============================================================' -ForegroundColor Cyan
    Write-Host ' BAOZ-PROBE-007 — LONGSHOT STABILITY' -ForegroundColor Cyan
    Write-Host '============================================================' -ForegroundColor Cyan

    Write-Host '--- RANK AGREEMENT ---' -ForegroundColor Yellow
    $agreement |
        Sort-Object exact_rank_equal_pct -Descending |
        Format-Table rank_a,rank_b,exact_rank_equal_pct,rank1_overlap,rank1_jaccard_pct -AutoSize |
        Out-String -Width 220 |
        Write-Host

    foreach($field in $focus){
        $e=$focusResults[$field]
        Write-Host ("--- {0}=1 x P7+ ---" -f $field) -ForegroundColor Yellow
        $m=$e.overall
        Write-Host ("Overall n={0} win={1:P2} top3={2:P2} winIdx={3} placeIdx={4}" -f $m.starts,$m.win_rate,$m.top3_rate,$m.win_index_pct,$m.place_index_pct)

        Write-Host 'Popularity sub-bands:'
        foreach($band in $popBands.Keys){
            $x=$e.popularity_subbands[$band]
            Write-Host ("  {0,-7} n={1,6} win={2,7:P2} top3={3,7:P2} winIdx={4,8} placeIdx={5,8}" -f $band,$x.starts,$x.win_rate,$x.top3_rate,$x.win_index_pct,$x.place_index_pct)
        }

        Write-Host 'Era stability:'
        foreach($era in $eraBands.Keys){
            $x=$e.eras[$era]
            Write-Host ("  {0,-10} n={1,6} winIdx={2,8} placeIdx={3,8}" -f $era,$x.starts,$x.win_index_pct,$x.place_index_pct)
        }

        Write-Host 'Recent years:'
        $e.years | Where-Object {$_.year -ge 2019} |
            Format-Table year,n,win_rate,top3_rate,win_index_pct,place_index_pct -AutoSize |
            Out-String -Width 160 |
            Write-Host

        Write-Host 'Tail contribution:'
        foreach($key in $e.tail.Keys){
            $x=$e.tail[$key]
            Write-Host ("  {0,-18} wins={1,5} returnShare={2,8}%" -f $key,$x.winning_rows,$x.share_of_total_return_pct)
        }
        Write-Host ''
    }

    Write-Host ("Aggregate only      : {0}" -f $result.safety.aggregate_only)
    Write-Host ("Horse rows output   : {0}" -f $result.safety.horse_rows_output)
    Write-Host ("BaoZ modified       : {0}" -f $result.safety.baoz_modified)
    Write-Host ("Output              : {0}" -f $OutputPath)
    Write-Host '============================================================'
}
finally {
    try{$conn.Close()}catch{}
    try{[void][Runtime.InteropServices.Marshal]::ReleaseComObject($conn)}catch{}
}
