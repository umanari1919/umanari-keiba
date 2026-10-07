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
        }
        catch {}
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
        }
        catch {
            if($conn) {
                try {$conn.Close()} catch {}
                try {[void][Runtime.InteropServices.Marshal]::ReleaseComObject($conn)} catch {}
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

function Get-MetricSet {
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
        win_return_yen=[int64]$winReturn
        place_return_yen=[int64]$placeReturn
        win_return_index_pct=if($den){[math]::Round(([double]$winReturn/$den)*100,3)}else{$null}
        place_return_index_pct=if($den){[math]::Round(([double]$placeReturn/$den)*100,3)}else{$null}
    }
}

if(-not $BaoZPath){
    Write-Host 'BaoZ active DB root: auto-discovery...' -ForegroundColor DarkGray
    $BaoZPath=Find-BaoZRoot
}
$BaoZPath=(Resolve-Path -LiteralPath $BaoZPath).Path

$db=Join-Path $BaoZPath 'DB\BaoZ.ex.mdb'
if(-not (Test-Path -LiteralPath $db -PathType Leaf)){
    throw "Active runner DB not found: $db"
}

$opened=Open-ReadOnlyConnection -Path $db
$conn=$opened.Connection

try {
    $cutoffLiteral=$CutoffDate.ToString('yyyy-MM-dd')
    $base="([年月日] >= #1986-01-01# AND [年月日] <= #$cutoffLiteral# AND [確定着順] Between 1 And 28 AND [馬番] > 0)"

    $population=[ordered]@{
        cutoff_date=$cutoffLiteral
        valid_runner_rows=[int64](Invoke-Scalar $conn "SELECT Count(*) FROM [出走馬T] WHERE $base")
        valid_races=[int64](Invoke-Scalar $conn "SELECT Count(*) FROM (SELECT [競走コード] FROM [出走馬T] WHERE $base GROUP BY [競走コード]) AS Q")
        valid_min_date=(Invoke-Scalar $conn "SELECT Min([年月日]) FROM [出走馬T] WHERE $base")
        valid_max_date=(Invoke-Scalar $conn "SELECT Max([年月日]) FROM [出走馬T] WHERE $base")
        zero_finish_rows=[int64](Invoke-Scalar $conn "SELECT Count(*) FROM [出走馬T] WHERE [年月日] >= #1986-01-01# AND [年月日] <= #$cutoffLiteral# AND [確定着順]=0")
        sentinel_date_rows=[int64](Invoke-Scalar $conn "SELECT Count(*) FROM [出走馬T] WHERE [年月日] < #1986-01-01#")
        future_rows=[int64](Invoke-Scalar $conn "SELECT Count(*) FROM [出走馬T] WHERE [年月日] > #$cutoffLiteral#")
        positive_win_payout_rows=[int64](Invoke-Scalar $conn "SELECT Count(*) FROM [出走馬T] WHERE $base AND [単勝配当] > 0")
        positive_place_payout_rows=[int64](Invoke-Scalar $conn "SELECT Count(*) FROM [出走馬T] WHERE $base AND [複勝配当] > 0")
    }

    $rankFields=@(
        '予想タイム指数順位',
        '馬券評価順位',
        '得点V1順位',
        '得点V2順位',
        'デフォルト得点順位',
        '得点V3順位'
    )

    $rankResults=[ordered]@{}
    foreach($field in $rankFields){
        $positions=[ordered]@{}
        foreach($pos in 1..4){
            $where="$base AND [$field]=$pos"
            $positions["rank_$pos"]=Get-MetricSet -Connection $conn -Where $where
        }
        $rankResults[$field]=$positions
    }

    $market=[ordered]@{}
    foreach($pos in 1..4){
        $market["popularity_$pos"]=Get-MetricSet -Connection $conn -Where "$base AND [単勝人気]=$pos"
    }

    $result=[ordered]@{
        mission='BAOZ-BASELINE-001'
        probe='BAOZ-PROBE-005'
        created_at=(Get-Date).ToString('yyyy-MM-ddTHH:mm:sszzz')
        safety=[ordered]@{
            read_only=$true
            aggregate_only=$true
            horse_rows_output=$false
            baoz_modified=$false
        }
        assumptions=[ordered]@{
            valid_date_start='1986-01-01'
            cutoff_date=$cutoffLiteral
            valid_finish='1..28'
            return_index_denominator_yen_per_bet=100
            note='Return index is provisional until BaoZ payout-unit semantics are explicitly confirmed.'
        }
        population=$population
        ranking_definitions=$rankResults
        market_popularity=$market
    }

    if(-not $OutputPath){
        $outDir=Join-Path $env:TEMP 'JIZO\BAOZ-BASELINE-001'
        New-Item -ItemType Directory -Path $outDir -Force | Out-Null
        $OutputPath=Join-Path $outDir 'baoz_probe_005_rank_baseline.json'
    }

    $result | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $OutputPath -Encoding utf8

    Write-Host ''
    Write-Host '============================================================' -ForegroundColor Cyan
    Write-Host ' BAOZ-PROBE-005 — RANK BASELINE' -ForegroundColor Cyan
    Write-Host '============================================================' -ForegroundColor Cyan
    Write-Host ("Cutoff date         : {0}" -f $population.cutoff_date)
    Write-Host ("Valid runner rows   : {0}" -f $population.valid_runner_rows)
    Write-Host ("Valid races         : {0}" -f $population.valid_races)
    Write-Host ("Valid date range    : {0} .. {1}" -f $population.valid_min_date,$population.valid_max_date)
    Write-Host ("Zero-finish rows    : {0}" -f $population.zero_finish_rows)
    Write-Host ("Sentinel-date rows  : {0}" -f $population.sentinel_date_rows)
    Write-Host ("Future rows         : {0}" -f $population.future_rows)
    Write-Host ''

    foreach($field in $rankFields){
        Write-Host ("--- {0} ---" -f $field) -ForegroundColor Yellow
        foreach($pos in 1..4){
            $m=$rankResults[$field]["rank_$pos"]
            Write-Host (
                "R{0}: n={1} win={2:P2} top2={3:P2} top3={4:P2} winIdx={5} placeIdx={6}" -f
                $pos,$m.starts,$m.win_rate,$m.top2_rate,$m.top3_rate,$m.win_return_index_pct,$m.place_return_index_pct
            )
        }
        Write-Host ''
    }

    Write-Host '--- MARKET POPULARITY REFERENCE ---' -ForegroundColor Yellow
    foreach($pos in 1..4){
        $m=$market["popularity_$pos"]
        Write-Host (
            "P{0}: n={1} win={2:P2} top2={3:P2} top3={4:P2} winIdx={5} placeIdx={6}" -f
            $pos,$m.starts,$m.win_rate,$m.top2_rate,$m.top3_rate,$m.win_return_index_pct,$m.place_return_index_pct
        )
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
