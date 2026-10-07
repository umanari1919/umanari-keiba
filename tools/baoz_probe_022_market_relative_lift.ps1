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
        [Parameter(Mandatory)][string]$PeriodWhere,
        [Parameter(Mandatory)][string]$GroupWhere,
        [Parameter(Mandatory)][bool]$SelectedOnly
    )

    $selectedClause=if($SelectedOnly){'AND S.[馬券評価順位]=1'}else{''}

    $sql=@"
SELECT
  Count(*) AS N,
  Sum(IIf(S.[確定着順]=1,1,0)) AS W,
  Sum(IIf(S.[確定着順] Between 1 And 3,1,0)) AS T3,
  Avg(S.[単勝オッズ]) AS AvgOdds,
  Avg(IIf(S.[単勝オッズ]>=1,1/S.[単勝オッズ],Null)) AS AvgImplied
FROM [出走馬T] AS S INNER JOIN [レースT] AS R
  ON S.[競走コード]=R.[競走コード]
WHERE S.[確定着順] Between 1 And 28
  AND S.[馬番] > 0
  AND S.[単勝人気] Between 7 And 9
  AND R.[トラック種別コード]=1
  AND $PeriodWhere
  AND $GroupWhere
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

function Compare-SelectedToBase {
    param($Base,$Selected)

    $winLift=$null
    $top3Lift=$null
    if($Base.win_rate -gt 0){$winLift=$Selected.win_rate/$Base.win_rate}
    if($Base.top3_rate -gt 0){$top3Lift=$Selected.top3_rate/$Base.top3_rate}

    return [pscustomobject]@{
        base_n=$Base.n
        base_win=$Base.win_rate
        base_top3=$Base.top3_rate
        base_avg_odds=$Base.avg_odds
        base_implied=$Base.avg_implied
        selected_n=$Selected.n
        selected_win=$Selected.win_rate
        selected_top3=$Selected.top3_rate
        selected_avg_odds=$Selected.avg_odds
        selected_implied=$Selected.avg_implied
        win_lift=$winLift
        top3_lift=$top3Lift
        win_excess_pp=if($null -ne $Base.win_rate -and $null -ne $Selected.win_rate){($Selected.win_rate-$Base.win_rate)*100}else{$null}
        selected_calibration_gap_pp=if($null -ne $Selected.avg_implied -and $null -ne $Selected.win_rate){($Selected.win_rate-$Selected.avg_implied)*100}else{$null}
        base_calibration_gap_pp=if($null -ne $Base.avg_implied -and $null -ne $Base.win_rate){($Base.win_rate-$Base.avg_implied)*100}else{$null}
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
    $before='S.[年月日] Between #2019-01-01# And #2023-12-31#'
    $after='S.[年月日] Between #2024-01-01# And #2026-10-08#'

    $groups=[ordered]@{
        'ALL'='1=1'
        'P7'='S.[単勝人気]=7'
        'P8'='S.[単勝人気]=8'
        'P9'='S.[単勝人気]=9'
        'ORG1'='R.[主催者コード]=1'
        'ORG2'='R.[主催者コード]=2'
        'ODDS<10'='S.[単勝オッズ] < 10'
        'ODDS10-19.9'='S.[単勝オッズ] >= 10 AND S.[単勝オッズ] < 20'
        'ODDS20-39.9'='S.[単勝オッズ] >= 20 AND S.[単勝オッズ] < 40'
        'ODDS40-79.9'='S.[単勝オッズ] >= 40 AND S.[単勝オッズ] < 80'
        'ODDS80+'='S.[単勝オッズ] >= 80'
    }

    $rows=@()

    foreach($name in $groups.Keys){
        $g=$groups[$name]

        $bb=Get-Metrics $conn $before $g $false
        $bs=Get-Metrics $conn $before $g $true
        $ab=Get-Metrics $conn $after $g $false
        $as=Get-Metrics $conn $after $g $true

        $bcmp=Compare-SelectedToBase $bb $bs
        $acmp=Compare-SelectedToBase $ab $as

        $rows += [pscustomobject]@{
            group=$name

            before_base_n=$bcmp.base_n
            before_base_win=$bcmp.base_win
            before_selected_n=$bcmp.selected_n
            before_selected_win=$bcmp.selected_win
            before_win_lift=$bcmp.win_lift
            before_top3_lift=$bcmp.top3_lift
            before_selected_implied=$bcmp.selected_implied
            before_selected_cal_gap_pp=$bcmp.selected_calibration_gap_pp

            after_base_n=$acmp.base_n
            after_base_win=$acmp.base_win
            after_selected_n=$acmp.selected_n
            after_selected_win=$acmp.selected_win
            after_win_lift=$acmp.win_lift
            after_top3_lift=$acmp.top3_lift
            after_selected_implied=$acmp.selected_implied
            after_selected_cal_gap_pp=$acmp.selected_calibration_gap_pp

            lift_change=if($null -ne $bcmp.win_lift -and $null -ne $acmp.win_lift){$acmp.win_lift-$bcmp.win_lift}else{$null}
            selected_win_change_pp=if($null -ne $bcmp.selected_win -and $null -ne $acmp.selected_win){($acmp.selected_win-$bcmp.selected_win)*100}else{$null}
            base_win_change_pp=if($null -ne $bcmp.base_win -and $null -ne $acmp.base_win){($acmp.base_win-$bcmp.base_win)*100}else{$null}
        }
    }

    $result=[ordered]@{
        mission='BAOZ-BASELINE-001'
        probe='BAOZ-PROBE-022'
        created_at=(Get-Date).ToString('yyyy-MM-ddTHH:mm:sszzz')
        safety=[ordered]@{
            read_only=$true
            aggregate_only=$true
            horse_rows_output=$false
            baoz_modified=$false
        }
        target='Market-relative lift for BaoZ rank1 within P7-9 dirt'
        comparison=[ordered]@{
            before='2019-2023'
            after='2024-2026-10-08'
        }
        groups=$rows
        interpretation_note='Base population is all P7-9 dirt runners in the same period/group. Selected population is the subset with 馬券評価順位=1. A falling lift indicates BaoZ-specific selection degradation relative to the market segment, while similar lift with both rates falling suggests environment/market-segment difficulty.'
    }

    if(-not $OutputPath){
        $outDir=Join-Path $env:TEMP 'JIZO\BAOZ-BASELINE-001'
        New-Item -ItemType Directory -Path $outDir -Force | Out-Null
        $OutputPath=Join-Path $outDir 'baoz_probe_022_market_relative_lift.json'
    }
    $result | ConvertTo-Json -Depth 14 | Set-Content -LiteralPath $OutputPath -Encoding utf8

    Write-Host ''
    Write-Host '============================================================' -ForegroundColor Cyan
    Write-Host ' BAOZ-PROBE-022 — MARKET-RELATIVE LIFT' -ForegroundColor Cyan
    Write-Host '============================================================' -ForegroundColor Cyan
    Write-Host '--- SELECTED vs ALL P7-9 DIRT RUNNERS ---' -ForegroundColor Yellow

    $rows |
        Select-Object group,
            before_base_n,before_base_win,before_selected_n,before_selected_win,before_win_lift,
            after_base_n,after_base_win,after_selected_n,after_selected_win,after_win_lift,
            lift_change,base_win_change_pp,selected_win_change_pp |
        Format-Table -AutoSize |
        Out-String -Width 240 |
        Write-Host

    Write-Host ''
    Write-Host '--- CALIBRATION / IMPLIED PROBABILITY ---' -ForegroundColor Yellow
    $rows |
        Select-Object group,
            before_selected_implied,before_selected_win,before_selected_cal_gap_pp,
            after_selected_implied,after_selected_win,after_selected_cal_gap_pp |
        Format-Table -AutoSize |
        Out-String -Width 190 |
        Write-Host

    Write-Host ("Groups checked      : {0}" -f $rows.Count)
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
