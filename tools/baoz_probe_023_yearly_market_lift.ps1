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

function Get-Metrics {
    param(
        [Parameter(Mandatory)]$Connection,
        [Parameter(Mandatory)][int]$Year,
        [Parameter(Mandatory)][bool]$SelectedOnly
    )

    $end = if($Year -eq 2026){'#2026-10-08#'} else {"#$Year-12-31#"}
    $selectedClause = if($SelectedOnly){'AND S.[馬券評価順位]=1'}else{''}

    $sql=@"
SELECT
  Count(*) AS N,
  Sum(IIf(S.[確定着順]=1,1,0)) AS W,
  Sum(IIf(S.[確定着順] Between 1 And 3,1,0)) AS T3,
  Avg(S.[単勝オッズ]) AS AvgOdds,
  Avg(IIf(S.[単勝オッズ]>=1,1/S.[単勝オッズ],Null)) AS AvgImplied
FROM [出走馬T] AS S INNER JOIN [レースT] AS R
  ON S.[競走コード]=R.[競走コード]
WHERE S.[年月日] Between #$Year-01-01# And $end
  AND S.[確定着順] Between 1 And 28
  AND S.[馬番] > 0
  AND S.[単勝人気] Between 7 And 9
  AND R.[トラック種別コード]=1
  $selectedClause
"@

    $r=Invoke-Row $Connection $sql
    $n=[int64]$r.N
    $w=[int64]$r.W
    $t3=[int64]$r.T3

    return [pscustomobject]@{
        n=$n
        wins=$w
        top3=$t3
        win_rate=if($n){[double]$w/$n}else{$null}
        top3_rate=if($n){[double]$t3/$n}else{$null}
        avg_odds=if($null -ne $r.AvgOdds){[double]$r.AvgOdds}else{$null}
        avg_implied=if($null -ne $r.AvgImplied){[double]$r.AvgImplied}else{$null}
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
    $rows=@()

    foreach($year in 2019..2026){
        $base=Get-Metrics -Connection $conn -Year $year -SelectedOnly $false
        $sel=Get-Metrics -Connection $conn -Year $year -SelectedOnly $true

        $winLift=$null
        $top3Lift=$null
        if($base.win_rate -gt 0){$winLift=$sel.win_rate/$base.win_rate}
        if($base.top3_rate -gt 0){$top3Lift=$sel.top3_rate/$base.top3_rate}

        $rows += [pscustomobject]@{
            year=$year
            base_n=$base.n
            base_wins=$base.wins
            base_win_rate=$base.win_rate
            base_top3_rate=$base.top3_rate
            selected_n=$sel.n
            selected_wins=$sel.wins
            selected_win_rate=$sel.win_rate
            selected_top3_rate=$sel.top3_rate
            win_lift=$winLift
            top3_lift=$top3Lift
            selected_avg_odds=$sel.avg_odds
            selected_avg_implied=$sel.avg_implied
            selected_cal_gap_pp=if($null -ne $sel.avg_implied -and $null -ne $sel.win_rate){($sel.win_rate-$sel.avg_implied)*100}else{$null}
            base_cal_gap_pp=if($null -ne $base.avg_implied -and $null -ne $base.win_rate){($base.win_rate-$base.avg_implied)*100}else{$null}
        }
    }

    $pre=@($rows | Where-Object {$_.year -le 2023})
    $post=@($rows | Where-Object {$_.year -ge 2024})

    function Weighted-Lift {
        param($Items,[string]$Which)
        $bn=($Items | Measure-Object base_n -Sum).Sum
        $bw=($Items | Measure-Object base_wins -Sum).Sum
        $sn=($Items | Measure-Object selected_n -Sum).Sum
        $sw=($Items | Measure-Object selected_wins -Sum).Sum
        $br=if($bn){$bw/$bn}else{$null}
        $sr=if($sn){$sw/$sn}else{$null}
        [pscustomobject]@{
            label=$Which
            base_n=$bn
            base_wins=$bw
            base_win_rate=$br
            selected_n=$sn
            selected_wins=$sw
            selected_win_rate=$sr
            win_lift=if($br -gt 0){$sr/$br}else{$null}
        }
    }

    $summary=@(
        Weighted-Lift $pre '2019-2023'
        Weighted-Lift $post '2024-2026'
    )

    $result=[ordered]@{
        mission='BAOZ-BASELINE-001'
        probe='BAOZ-PROBE-023'
        created_at=(Get-Date).ToString('yyyy-MM-ddTHH:mm:sszzz')
        safety=[ordered]@{
            read_only=$true
            aggregate_only=$true
            horse_rows_output=$false
            baoz_modified=$false
        }
        target='Yearly market-relative lift for BaoZ rank1 within P7-9 dirt'
        yearly=$rows
        weighted_period_summary=$summary
        interpretation_note='Base is all P7-9 dirt runners. Selected is the 馬券評価順位=1 subset. Win lift >1 means BaoZ selection beats the raw market-segment win rate; changes in lift measure model-relative selection strength.'
    }

    if(-not $OutputPath){
        $outDir=Join-Path $env:TEMP 'JIZO\BAOZ-BASELINE-001'
        New-Item -ItemType Directory -Path $outDir -Force | Out-Null
        $OutputPath=Join-Path $outDir 'baoz_probe_023_yearly_market_lift.json'
    }
    $result | ConvertTo-Json -Depth 14 | Set-Content -LiteralPath $OutputPath -Encoding utf8

    Write-Host ''
    Write-Host '============================================================' -ForegroundColor Cyan
    Write-Host ' BAOZ-PROBE-023 — YEARLY MARKET-RELATIVE LIFT' -ForegroundColor Cyan
    Write-Host '============================================================' -ForegroundColor Cyan

    Write-Host '--- YEARLY ---' -ForegroundColor Yellow
    foreach($r in $rows){
        Write-Host ("{0}: base {1}/{2}={3:N3}% | selected {4}/{5}={6:N3}% | lift={7:N3}x | top3Lift={8:N3}x | implied={9:N3}% | calGap={10:N3}pt" -f
            $r.year,
            $r.base_wins,$r.base_n,($r.base_win_rate*100),
            $r.selected_wins,$r.selected_n,($r.selected_win_rate*100),
            $r.win_lift,$r.top3_lift,($r.selected_avg_implied*100),$r.selected_cal_gap_pp)
    }

    Write-Host ''
    Write-Host '--- WEIGHTED PERIOD SUMMARY ---' -ForegroundColor Yellow
    foreach($s in $summary){
        Write-Host ("{0}: base {1}/{2}={3:N3}% | selected {4}/{5}={6:N3}% | lift={7:N3}x" -f
            $s.label,
            $s.base_wins,$s.base_n,($s.base_win_rate*100),
            $s.selected_wins,$s.selected_n,($s.selected_win_rate*100),
            $s.win_lift)
    }

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
