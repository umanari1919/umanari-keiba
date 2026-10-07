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
            $conn.CommandTimeout=120
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
        $value=$rs.Fields.Item(0).Value
        if($value -is [DBNull]){return $null}
        return $value
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
    $avgPop=Invoke-Scalar $Connection "SELECT Avg([単勝人気]) FROM [出走馬T] WHERE $Where"

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
        avg_popularity=if($null -ne $avgPop){[math]::Round([double]$avgPop,3)}else{$null}
        win_index_pct=if($den){[math]::Round(([double]$winReturn/$den)*100,3)}else{$null}
        place_index_pct=if($den){[math]::Round(([double]$placeReturn/$den)*100,3)}else{$null}
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

    $bands=[ordered]@{
        'P1'='[単勝人気]=1'
        'P2-3'='[単勝人気] Between 2 And 3'
        'P4-6'='[単勝人気] Between 4 And 6'
        'P7+'='[単勝人気] >= 7'
        'P0/unknown'='([単勝人気] Is Null OR [単勝人気] <= 0)'
    }

    $cross=[ordered]@{}
    foreach($field in $rankFields){
        $rankWhere="$base AND [$field]=1"
        $entry=[ordered]@{
            overall=Get-Metrics -Connection $conn -Where $rankWhere
            by_popularity=[ordered]@{}
        }
        foreach($band in $bands.Keys){
            $entry.by_popularity[$band]=Get-Metrics -Connection $conn -Where "$rankWhere AND $($bands[$band])"
        }
        $entry.favorite_overlap_count=[int64](Invoke-Scalar $conn "SELECT Count(*) FROM [出走馬T] WHERE $rankWhere AND [単勝人気]=1")
        $entry.nonfavorite_count=[int64](Invoke-Scalar $conn "SELECT Count(*) FROM [出走馬T] WHERE $rankWhere AND [単勝人気] >= 2")
        $cross[$field]=$entry
    }

    $agreement=@()
    for($i=0;$i -lt $rankFields.Count;$i++){
        for($j=$i+1;$j -lt $rankFields.Count;$j++){
            $a=$rankFields[$i]
            $b=$rankFields[$j]
            $both=[int64](Invoke-Scalar $conn "SELECT Count(*) FROM [出走馬T] WHERE $base AND [$a] Is Not Null AND [$b] Is Not Null")
            $exact=[int64](Invoke-Scalar $conn "SELECT Count(*) FROM [出走馬T] WHERE $base AND [$a]=[$b]")
            $r1Both=[int64](Invoke-Scalar $conn "SELECT Count(*) FROM [出走馬T] WHERE $base AND [$a]=1 AND [$b]=1")
            $aR1=[int64](Invoke-Scalar $conn "SELECT Count(*) FROM [出走馬T] WHERE $base AND [$a]=1")
            $bR1=[int64](Invoke-Scalar $conn "SELECT Count(*) FROM [出走馬T] WHERE $base AND [$b]=1")
            $union=$aR1+$bR1-$r1Both

            $agreement += [ordered]@{
                rank_a=$a
                rank_b=$b
                both_nonnull=$both
                exact_rank_equal=$exact
                exact_rank_equal_pct=if($both){[math]::Round(($exact/$both)*100,3)}else{$null}
                rank1_overlap=$r1Both
                rank1_jaccard_pct=if($union){[math]::Round(($r1Both/$union)*100,3)}else{$null}
            }
        }
    }

    $payoutSanity=[ordered]@{
        winner_count=[int64](Invoke-Scalar $conn "SELECT Count(*) FROM [出走馬T] WHERE $base AND [確定着順]=1")
        winner_positive_win_payout_count=[int64](Invoke-Scalar $conn "SELECT Count(*) FROM [出走馬T] WHERE $base AND [確定着順]=1 AND [単勝配当] > 0")
        min_positive_win_payout=(Invoke-Scalar $conn "SELECT Min([単勝配当]) FROM [出走馬T] WHERE $base AND [単勝配当] > 0")
        max_win_payout=(Invoke-Scalar $conn "SELECT Max([単勝配当]) FROM [出走馬T] WHERE $base")
        top3_positive_place_payout_count=[int64](Invoke-Scalar $conn "SELECT Count(*) FROM [出走馬T] WHERE $base AND [確定着順] Between 1 And 3 AND [複勝配当] > 0")
        min_positive_place_payout=(Invoke-Scalar $conn "SELECT Min([複勝配当]) FROM [出走馬T] WHERE $base AND [複勝配当] > 0")
        max_place_payout=(Invoke-Scalar $conn "SELECT Max([複勝配当]) FROM [出走馬T] WHERE $base")
    }

    $result=[ordered]@{
        mission='BAOZ-BASELINE-001'
        probe='BAOZ-PROBE-006'
        created_at=(Get-Date).ToString('yyyy-MM-ddTHH:mm:sszzz')
        safety=[ordered]@{
            read_only=$true
            aggregate_only=$true
            horse_rows_output=$false
            baoz_modified=$false
        }
        assumptions=[ordered]@{
            cutoff_date=$cutoff
            valid_finish='1..28'
        }
        rank1_by_popularity=$cross
        rank_agreement=$agreement
        payout_sanity=$payoutSanity
    }

    if(-not $OutputPath){
        $outDir=Join-Path $env:TEMP 'JIZO\BAOZ-BASELINE-001'
        New-Item -ItemType Directory -Path $outDir -Force | Out-Null
        $OutputPath=Join-Path $outDir 'baoz_probe_006_popularity_cross.json'
    }
    $result | ConvertTo-Json -Depth 14 | Set-Content -LiteralPath $OutputPath -Encoding utf8

    Write-Host ''
    Write-Host '============================================================' -ForegroundColor Cyan
    Write-Host ' BAOZ-PROBE-006 — RANK x POPULARITY' -ForegroundColor Cyan
    Write-Host '============================================================' -ForegroundColor Cyan

    foreach($field in $rankFields){
        $e=$cross[$field]
        Write-Host ("--- {0} / rank=1 ---" -f $field) -ForegroundColor Yellow
        Write-Host ("overall n={0} avgPop={1} favOverlap={2} nonFav={3}" -f $e.overall.starts,$e.overall.avg_popularity,$e.favorite_overlap_count,$e.nonfavorite_count)
        foreach($band in $bands.Keys){
            $m=$e.by_popularity[$band]
            Write-Host (
                "{0,-10} n={1,7} win={2,7:P2} top2={3,7:P2} top3={4,7:P2} winIdx={5,7} placeIdx={6,7}" -f
                $band,$m.starts,$m.win_rate,$m.top2_rate,$m.top3_rate,$m.win_index_pct,$m.place_index_pct
            )
        }
        Write-Host ''
    }

    Write-Host '--- RANK AGREEMENT (top pairs) ---' -ForegroundColor Yellow
    $agreement |
        Sort-Object exact_rank_equal_pct -Descending |
        Select-Object -First 15 |
        Format-Table rank_a,rank_b,exact_rank_equal_pct,rank1_overlap,rank1_jaccard_pct -AutoSize |
        Out-String -Width 220 |
        Write-Host

    Write-Host '--- PAYOUT SANITY ---' -ForegroundColor Yellow
    foreach($key in $payoutSanity.Keys){
        Write-Host ("{0,-36} {1}" -f $key,$payoutSanity[$key])
    }

    Write-Host ''
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
