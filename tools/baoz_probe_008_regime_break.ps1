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

function Add-ReturnMetrics {
    param([Parameter(Mandatory)]$Row)

    $n=[int64]$Row.N
    $wr=if($null -eq $Row.WR){0}else{[double]$Row.WR}
    $pr=if($null -eq $Row.PR){0}else{[double]$Row.PR}
    $wins=[int64]$Row.W
    $top3=[int64]$Row.T3

    return [pscustomobject]@{
        key=$Row.K
        n=$n
        wins=$wins
        win_rate=if($n){[math]::Round($wins/$n,6)}else{$null}
        top3_rate=if($n){[math]::Round($top3/$n,6)}else{$null}
        win_index_pct=if($n){[math]::Round(($wr/($n*100))*100,3)}else{$null}
        place_index_pct=if($n){[math]::Round(($pr/($n*100))*100,3)}else{$null}
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

try {
    $cutoff=$CutoffDate.ToString('yyyy-MM-dd')
    $base="(S.[年月日] >= #1986-01-01# AND S.[年月日] <= #$cutoff# AND S.[確定着順] Between 1 And 28 AND S.[馬番] > 0)"
    $focus="$base AND S.[馬券評価順位]=1 AND S.[単勝人気] >= 7"

    $rankFields=@(
        '予想タイム指数順位',
        '馬券評価順位',
        '得点V1順位',
        '得点V2順位',
        'デフォルト得点順位',
        '得点V3順位'
    )

    $coverage=@()
    foreach($field in $rankFields){
        $first=Invoke-Scalar $conn "SELECT Min([年月日]) FROM [出走馬T] WHERE [年月日] >= #1986-01-01# AND [年月日] <= #$cutoff# AND [$field] Is Not Null"
        $first1=Invoke-Scalar $conn "SELECT Min([年月日]) FROM [出走馬T] WHERE [年月日] >= #1986-01-01# AND [年月日] <= #$cutoff# AND [$field]=1"
        $last=Invoke-Scalar $conn "SELECT Max([年月日]) FROM [出走馬T] WHERE [年月日] >= #1986-01-01# AND [年月日] <= #$cutoff# AND [$field] Is Not Null"
        $coverage += [pscustomobject]@{
            rank=$field
            first_nonnull=$first
            first_rank1=$first1
            last_nonnull=$last
        }
    }

    $joinBase="FROM [出走馬T] AS S INNER JOIN [レースT] AS R ON S.[競走コード]=R.[競走コード] WHERE $focus"

    function Get-Segment {
        param(
            [Parameter(Mandatory)][string]$Expr,
            [Parameter(Mandatory)][string]$Alias
        )
        $sql=@"
SELECT $Expr AS K,
       Count(*) AS N,
       Sum(IIf(S.[確定着順]=1,1,0)) AS W,
       Sum(IIf(S.[確定着順] Between 1 And 3,1,0)) AS T3,
       Sum(S.[単勝配当]) AS WR,
       Sum(S.[複勝配当]) AS PR
$joinBase
GROUP BY $Expr
ORDER BY Count(*) DESC
"@
        $rows=Invoke-Rows $conn $sql
        return @($rows | ForEach-Object { Add-ReturnMetrics $_ })
    }

    $segments=[ordered]@{
        organizer=Get-Segment 'R.[主催者コード]' 'organizer'
        track_type=Get-Segment 'R.[トラック種別コード]' 'track_type'
        venue=Get-Segment 'R.[場コード]' 'venue'
        field_size=Get-Segment 'IIf(R.[頭数]<=9,"<=9",IIf(R.[頭数]<=12,"10-12",IIf(R.[頭数]<=15,"13-15","16+")))' 'field_size'
        year=Get-Segment 'Year(S.[年月日])' 'year'
    }

    $recentSql=@"
SELECT R.[主催者コード] AS Organizer,
       Year(S.[年月日]) AS Y,
       Count(*) AS N,
       Sum(IIf(S.[確定着順]=1,1,0)) AS W,
       Sum(IIf(S.[確定着順] Between 1 And 3,1,0)) AS T3,
       Sum(S.[単勝配当]) AS WR,
       Sum(S.[複勝配当]) AS PR
FROM [出走馬T] AS S INNER JOIN [レースT] AS R ON S.[競走コード]=R.[競走コード]
WHERE $focus AND S.[年月日] >= #2020-01-01#
GROUP BY R.[主催者コード], Year(S.[年月日])
ORDER BY Year(S.[年月日]), R.[主催者コード]
"@
    $recentRows=Invoke-Rows $conn $recentSql
    $recentOrganizerYear=@()
    foreach($r in $recentRows){
        $n=[int64]$r.N
        $wr=if($null -eq $r.WR){0}else{[double]$r.WR}
        $pr=if($null -eq $r.PR){0}else{[double]$r.PR}
        $recentOrganizerYear += [pscustomobject]@{
            year=[int]$r.Y
            organizer=$r.Organizer
            n=$n
            win_rate=if($n){[math]::Round(([double]$r.W/$n),6)}else{$null}
            top3_rate=if($n){[math]::Round(([double]$r.T3/$n),6)}else{$null}
            win_index_pct=if($n){[math]::Round(($wr/($n*100))*100,3)}else{$null}
            place_index_pct=if($n){[math]::Round(($pr/($n*100))*100,3)}else{$null}
        }
    }

    $oddsScale=[ordered]@{
        all_min=(Invoke-Scalar $conn "SELECT Min([単勝オッズ]) FROM [出走馬T] WHERE [年月日] >= #1986-01-01# AND [年月日] <= #$cutoff# AND [単勝人気] > 0 AND [単勝オッズ] > 0")
        all_max=(Invoke-Scalar $conn "SELECT Max([単勝オッズ]) FROM [出走馬T] WHERE [年月日] >= #1986-01-01# AND [年月日] <= #$cutoff# AND [単勝人気] > 0")
        p1_avg=(Invoke-Scalar $conn "SELECT Avg([単勝オッズ]) FROM [出走馬T] WHERE [年月日] >= #1986-01-01# AND [年月日] <= #$cutoff# AND [単勝人気]=1")
        p7_9_avg=(Invoke-Scalar $conn "SELECT Avg([単勝オッズ]) FROM [出走馬T] WHERE [年月日] >= #1986-01-01# AND [年月日] <= #$cutoff# AND [単勝人気] Between 7 And 9")
        p13plus_avg=(Invoke-Scalar $conn "SELECT Avg([単勝オッズ]) FROM [出走馬T] WHERE [年月日] >= #1986-01-01# AND [年月日] <= #$cutoff# AND [単勝人気] >= 13")
    }

    $result=[ordered]@{
        mission='BAOZ-BASELINE-001'
        probe='BAOZ-PROBE-008'
        created_at=(Get-Date).ToString('yyyy-MM-ddTHH:mm:sszzz')
        safety=[ordered]@{
            read_only=$true
            aggregate_only=$true
            horse_rows_output=$false
            baoz_modified=$false
        }
        rank_coverage=$coverage
        focus_rule='馬券評価順位=1 AND 単勝人気>=7'
        segments=$segments
        recent_organizer_by_year=$recentOrganizerYear
        odds_scale_sanity=$oddsScale
    }

    if(-not $OutputPath){
        $outDir=Join-Path $env:TEMP 'JIZO\BAOZ-BASELINE-001'
        New-Item -ItemType Directory -Path $outDir -Force | Out-Null
        $OutputPath=Join-Path $outDir 'baoz_probe_008_regime_break.json'
    }
    $result | ConvertTo-Json -Depth 16 | Set-Content -LiteralPath $OutputPath -Encoding utf8

    Write-Host ''
    Write-Host '============================================================' -ForegroundColor Cyan
    Write-Host ' BAOZ-PROBE-008 — REGIME BREAK' -ForegroundColor Cyan
    Write-Host '============================================================' -ForegroundColor Cyan

    Write-Host '--- RANK COVERAGE ---' -ForegroundColor Yellow
    $coverage | Format-Table rank,first_nonnull,first_rank1,last_nonnull -AutoSize | Out-String -Width 180 | Write-Host

    foreach($name in @('organizer','track_type','field_size','venue')){
        Write-Host ("--- {0} ---" -f $name.ToUpper()) -ForegroundColor Yellow
        $segments[$name] |
            Select-Object -First 20 |
            Format-Table key,n,win_rate,top3_rate,win_index_pct,place_index_pct -AutoSize |
            Out-String -Width 160 |
            Write-Host
    }

    Write-Host '--- RECENT ORGANIZER x YEAR ---' -ForegroundColor Yellow
    $recentOrganizerYear |
        Format-Table year,organizer,n,win_rate,top3_rate,win_index_pct,place_index_pct -AutoSize |
        Out-String -Width 180 |
        Write-Host

    Write-Host '--- ODDS SCALE SANITY ---' -ForegroundColor Yellow
    foreach($k in $oddsScale.Keys){
        Write-Host ("{0,-18} {1}" -f $k,$oddsScale[$k])
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
