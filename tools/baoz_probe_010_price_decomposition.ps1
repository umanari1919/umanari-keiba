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
            if ($hit) { return (Split-Path -Parent (Split-Path -Parent $hit.FullName)) }
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

function Invoke-Rows {
    param(
        [Parameter(Mandatory)]$Connection,
        [Parameter(Mandatory)][string]$Sql
    )
    $rs=$null; $rows=@()
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

function Get-Summary {
    param(
        [Parameter(Mandatory)]$Connection,
        [Parameter(Mandatory)][string]$Where
    )
    $sql=@"
SELECT Count(*) AS N,
       Sum(IIf([確定着順]=1,1,0)) AS W,
       Sum(IIf([確定着順] Between 1 And 3,1,0)) AS T3,
       Avg(IIf([単勝オッズ]>=1,[単勝オッズ],Null)) AS AvgOdds,
       Avg(IIf([確定着順]=1 And [単勝オッズ]>=1,[単勝オッズ],Null)) AS AvgWinnerOdds,
       Avg(IIf([確定着順]=1 And [単勝配当]>0,[単勝配当],Null)) AS AvgWinnerPayout,
       Sum([単勝配当]) AS WinReturn,
       Avg(IIf([単勝オッズ]>=1,1/[単勝オッズ],Null)) AS AvgImpliedProb
FROM [出走馬T]
WHERE $Where
"@
    $r=(Invoke-Rows $Connection $sql | Select-Object -First 1)
    if(-not $r){return $null}

    $n=[int64]$r.N
    $w=[int64]$r.W
    $ret=if($null -eq $r.WinReturn){0}else{[double]$r.WinReturn}

    return [ordered]@{
        n=$n
        wins=$w
        win_rate=if($n){[math]::Round($w/$n,6)}else{$null}
        top3_rate=if($n){[math]::Round(([double]$r.T3/$n),6)}else{$null}
        avg_odds=if($null -ne $r.AvgOdds){[math]::Round([double]$r.AvgOdds,3)}else{$null}
        avg_winner_odds=if($null -ne $r.AvgWinnerOdds){[math]::Round([double]$r.AvgWinnerOdds,3)}else{$null}
        avg_winner_payout=if($null -ne $r.AvgWinnerPayout){[math]::Round([double]$r.AvgWinnerPayout,2)}else{$null}
        avg_implied_probability=if($null -ne $r.AvgImpliedProb){[math]::Round([double]$r.AvgImpliedProb,6)}else{$null}
        return_index_pct=if($n){[math]::Round(($ret/($n*100))*100,3)}else{$null}
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
    $valid="([年月日] >= #2012-01-01# AND [年月日] <= #$cutoff# AND [確定着順] Between 1 And 28 AND [馬番] > 0 AND [馬券評価順位]=1)"
    $periods=[ordered]@{
        '2019-2023'='[年月日] Between #2019-01-01# And #2023-12-31#'
        '2024-2026'="[年月日] Between #2024-01-01# And #$cutoff#"
    }
    $groups=[ordered]@{
        'ALL'='[単勝人気] >= 1'
        'P1'='[単勝人気]=1'
        'P2-3'='[単勝人気] Between 2 And 3'
        'P4-6'='[単勝人気] Between 4 And 6'
        'P7+'='[単勝人気] >= 7'
        'P7-9'='[単勝人気] Between 7 And 9'
        'P10-12'='[単勝人気] Between 10 And 12'
        'P13+'='[単勝人気] >= 13'
    }

    $summary=[ordered]@{}
    foreach($period in $periods.Keys){
        $summary[$period]=[ordered]@{}
        foreach($group in $groups.Keys){
            $summary[$period][$group]=Get-Summary $conn "$valid AND $($periods[$period]) AND $($groups[$group])"
        }
    }

    $oddsBands=[ordered]@{
        '1-4.9'='[単勝オッズ] >= 1 AND [単勝オッズ] < 5'
        '5-9.9'='[単勝オッズ] >= 5 AND [単勝オッズ] < 10'
        '10-19.9'='[単勝オッズ] >= 10 AND [単勝オッズ] < 20'
        '20-39.9'='[単勝オッズ] >= 20 AND [単勝オッズ] < 40'
        '40-79.9'='[単勝オッズ] >= 40 AND [単勝オッズ] < 80'
        '80-159.9'='[単勝オッズ] >= 80 AND [単勝オッズ] < 160'
        '160+'='[単勝オッズ] >= 160'
    }

    $oddsComparison=[ordered]@{}
    foreach($period in $periods.Keys){
        $oddsComparison[$period]=[ordered]@{}
        foreach($band in $oddsBands.Keys){
            $oddsComparison[$period][$band]=Get-Summary $conn "$valid AND $($periods[$period]) AND [単勝人気] >= 7 AND $($oddsBands[$band])"
        }
    }

    $yearly=[ordered]@{}
    foreach($year in 2019..2026){
        $yearStart=("{0}-01-01" -f $year)
        $yearEnd=if($year -eq 2026){'2026-10-08'}else{("{0}-12-31" -f $year)}
        $yearly["$year"]=Get-Summary $conn "$valid AND [年月日] Between #$yearStart# And #$yearEnd# AND [単勝人気] >= 7"
    }

    $result=[ordered]@{
        mission='BAOZ-BASELINE-001'
        probe='BAOZ-PROBE-010'
        created_at=(Get-Date).ToString('yyyy-MM-ddTHH:mm:sszzz')
        safety=[ordered]@{
            read_only=$true
            aggregate_only=$true
            horse_rows_output=$false
            baoz_modified=$false
        }
        target='price-vs-accuracy decomposition for 馬券評価順位=1'
        summary=$summary
        p7plus_odds_bands=$oddsComparison
        p7plus_yearly=$yearly
    }

    if(-not $OutputPath){
        $outDir=Join-Path $env:TEMP 'JIZO\BAOZ-BASELINE-001'
        New-Item -ItemType Directory -Path $outDir -Force | Out-Null
        $OutputPath=Join-Path $outDir 'baoz_probe_010_price_decomposition.json'
    }
    $result | ConvertTo-Json -Depth 14 | Set-Content -LiteralPath $OutputPath -Encoding utf8

    Write-Host ''
    Write-Host '============================================================' -ForegroundColor Cyan
    Write-Host ' BAOZ-PROBE-010 — PRICE DECOMPOSITION' -ForegroundColor Cyan
    Write-Host '============================================================' -ForegroundColor Cyan

    foreach($group in $groups.Keys){
        $a=$summary['2019-2023'][$group]
        $b=$summary['2024-2026'][$group]
        Write-Host ("--- {0} ---" -f $group) -ForegroundColor Yellow
        Write-Host ("2019-23 n={0} win={1:P2} top3={2:P2} avgOdds={3} avgWinPayout={4} implied={5:P2} retIdx={6}" -f $a.n,$a.win_rate,$a.top3_rate,$a.avg_odds,$a.avg_winner_payout,$a.avg_implied_probability,$a.return_index_pct)
        Write-Host ("2024-26 n={0} win={1:P2} top3={2:P2} avgOdds={3} avgWinPayout={4} implied={5:P2} retIdx={6}" -f $b.n,$b.win_rate,$b.top3_rate,$b.avg_odds,$b.avg_winner_payout,$b.avg_implied_probability,$b.return_index_pct)
        Write-Host ''
    }

    Write-Host '--- P7+ ODDS BANDS ---' -ForegroundColor Yellow
    foreach($band in $oddsBands.Keys){
        $a=$oddsComparison['2019-2023'][$band]
        $b=$oddsComparison['2024-2026'][$band]
        Write-Host ("{0,-10} before n={1,5} win={2,7:P2} ret={3,7} | after n={4,5} win={5,7:P2} ret={6,7}" -f $band,$a.n,$a.win_rate,$a.return_index_pct,$b.n,$b.win_rate,$b.return_index_pct)
    }

    Write-Host ''
    Write-Host '--- P7+ YEARLY ---' -ForegroundColor Yellow
    foreach($year in $yearly.Keys){
        $m=$yearly[$year]
        Write-Host ("{0}: n={1,5} win={2,7:P2} top3={3,7:P2} avgOdds={4,8} avgWinPayout={5,8} retIdx={6,7}" -f $year,$m.n,$m.win_rate,$m.top3_rate,$m.avg_odds,$m.avg_winner_payout,$m.return_index_pct)
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
