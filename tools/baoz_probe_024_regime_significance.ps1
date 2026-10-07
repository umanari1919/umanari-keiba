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

function Get-Counts {
    param(
        [Parameter(Mandatory)]$Connection,
        [Parameter(Mandatory)][string]$PeriodWhere,
        [Parameter(Mandatory)][bool]$SelectedOnly
    )

    $selectedClause=if($SelectedOnly){'AND S.[馬券評価順位]=1'}else{''}

    $sql=@"
SELECT Count(*) AS N,
       Sum(IIf(S.[確定着順]=1,1,0)) AS W
FROM [出走馬T] AS S INNER JOIN [レースT] AS R
  ON S.[競走コード]=R.[競走コード]
WHERE S.[確定着順] Between 1 And 28
  AND S.[馬番] > 0
  AND S.[単勝人気] Between 7 And 9
  AND R.[トラック種別コード]=1
  AND $PeriodWhere
  $selectedClause
"@
    $r=Invoke-Row $Connection $sql
    return [pscustomobject]@{
        n=[int64]$r.N
        w=[int64]$r.W
        rate=if([int64]$r.N -gt 0){[double]$r.W/[double]$r.N}else{$null}
    }
}

function Normal-TwoSidedP {
    param([double]$Z)
    # Abramowitz-Stegun approximation to normal CDF.
    $x=[math]::Abs($Z)
    $t=1.0/(1.0+0.2316419*$x)
    $d=0.3989422804014327*[math]::Exp(-0.5*$x*$x)
    $prob=1.0-$d*$t*(0.319381530+$t*(-0.356563782+$t*(1.781477937+$t*(-1.821255978+$t*1.330274429))))
    $tail=1.0-$prob
    return 2.0*$tail
}

function Two-Proportion-Test {
    param($A,$B)
    $p1=$A.rate; $p2=$B.rate
    $p=([double]$A.w+[double]$B.w)/([double]$A.n+[double]$B.n)
    $se=[math]::Sqrt($p*(1-$p)*(1/[double]$A.n+1/[double]$B.n))
    $z=($p1-$p2)/$se
    return [pscustomobject]@{
        rate_a=$p1
        rate_b=$p2
        diff_pp=($p1-$p2)*100
        z=$z
        p_two_sided=(Normal-TwoSidedP $z)
    }
}

function Selection-OddsRatio {
    param($Base,$Selected)

    $nonN=$Base.n-$Selected.n
    $nonW=$Base.w-$Selected.w

    $a=[double]$Selected.w
    $b=[double]($Selected.n-$Selected.w)
    $c=[double]$nonW
    $d=[double]($nonN-$nonW)

    $or=($a/$b)/($c/$d)
    $se=[math]::Sqrt(1/$a+1/$b+1/$c+1/$d)

    return [pscustomobject]@{
        selected_wins=[int64]$a
        selected_losses=[int64]$b
        nonselected_wins=[int64]$c
        nonselected_losses=[int64]$d
        odds_ratio=$or
        log_or_se=$se
        ci95_low=[math]::Exp([math]::Log($or)-1.96*$se)
        ci95_high=[math]::Exp([math]::Log($or)+1.96*$se)
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
    $beforeWhere='S.[年月日] Between #2019-01-01# And #2023-12-31#'
    $afterWhere='S.[年月日] Between #2024-01-01# And #2026-10-08#'

    $preBase=Get-Counts $conn $beforeWhere $false
    $preSel=Get-Counts $conn $beforeWhere $true
    $postBase=Get-Counts $conn $afterWhere $false
    $postSel=Get-Counts $conn $afterWhere $true

    $selectedChange=Two-Proportion-Test $preSel $postSel
    $baseChange=Two-Proportion-Test $preBase $postBase

    $preOR=Selection-OddsRatio $preBase $preSel
    $postOR=Selection-OddsRatio $postBase $postSel

    $ratio=$postOR.odds_ratio/$preOR.odds_ratio
    $ratioSE=[math]::Sqrt([math]::Pow($preOR.log_or_se,2)+[math]::Pow($postOR.log_or_se,2))
    $ratioZ=[math]::Log($ratio)/$ratioSE
    $ratioP=Normal-TwoSidedP $ratioZ

    $interaction=[pscustomobject]@{
        pre_selection_or=$preOR.odds_ratio
        pre_ci95_low=$preOR.ci95_low
        pre_ci95_high=$preOR.ci95_high
        post_selection_or=$postOR.odds_ratio
        post_ci95_low=$postOR.ci95_low
        post_ci95_high=$postOR.ci95_high
        post_pre_or_ratio=$ratio
        ratio_ci95_low=[math]::Exp([math]::Log($ratio)-1.96*$ratioSE)
        ratio_ci95_high=[math]::Exp([math]::Log($ratio)+1.96*$ratioSE)
        z=$ratioZ
        p_two_sided=$ratioP
    }

    $result=[ordered]@{
        mission='BAOZ-BASELINE-001'
        probe='BAOZ-PROBE-024'
        created_at=(Get-Date).ToString('yyyy-MM-ddTHH:mm:sszzz')
        safety=[ordered]@{
            read_only=$true
            aggregate_only=$true
            horse_rows_output=$false
            baoz_modified=$false
        }
        population='P7-9 dirt'
        periods=[ordered]@{
            before='2019-2023'
            after='2024-2026-10-08'
        }
        counts=[ordered]@{
            pre_base=$preBase
            pre_selected=$preSel
            post_base=$postBase
            post_selected=$postSel
        }
        selected_rate_change=$selectedChange
        base_rate_change=$baseChange
        selection_odds_ratio_before=$preOR
        selection_odds_ratio_after=$postOR
        interaction_change=$interaction
        interpretation_note='The interaction compares BaoZ selection odds advantage vs non-selected runners across periods. A ratio below 1 with CI excluding 1 supports model-relative degradation beyond market-segment change. Normal approximations are used; this is an aggregate diagnostic, not a causal model.'
    }

    if(-not $OutputPath){
        $outDir=Join-Path $env:TEMP 'JIZO\BAOZ-BASELINE-001'
        New-Item -ItemType Directory -Path $outDir -Force | Out-Null
        $OutputPath=Join-Path $outDir 'baoz_probe_024_regime_significance.json'
    }
    $result | ConvertTo-Json -Depth 14 | Set-Content -LiteralPath $OutputPath -Encoding utf8

    Write-Host ''
    Write-Host '============================================================' -ForegroundColor Cyan
    Write-Host ' BAOZ-PROBE-024 — REGIME SIGNIFICANCE' -ForegroundColor Cyan
    Write-Host '============================================================' -ForegroundColor Cyan

    Write-Host '--- SELECTED RATE CHANGE ---' -ForegroundColor Yellow
    Write-Host ("2019-23: {0}/{1} = {2:N3}%" -f $preSel.w,$preSel.n,($preSel.rate*100))
    Write-Host ("2024-26: {0}/{1} = {2:N3}%" -f $postSel.w,$postSel.n,($postSel.rate*100))
    Write-Host ("difference={0:N3}pt z={1:N3} p={2:N6}" -f $selectedChange.diff_pp,$selectedChange.z,$selectedChange.p_two_sided)

    Write-Host ''
    Write-Host '--- BASE MARKET-SEGMENT RATE CHANGE ---' -ForegroundColor Yellow
    Write-Host ("2019-23: {0}/{1} = {2:N3}%" -f $preBase.w,$preBase.n,($preBase.rate*100))
    Write-Host ("2024-26: {0}/{1} = {2:N3}%" -f $postBase.w,$postBase.n,($postBase.rate*100))
    Write-Host ("difference={0:N3}pt z={1:N3} p={2:N6}" -f $baseChange.diff_pp,$baseChange.z,$baseChange.p_two_sided)

    Write-Host ''
    Write-Host '--- SELECTION ADVANTAGE vs NON-SELECTED ---' -ForegroundColor Yellow
    Write-Host ("2019-23 OR={0:N3} 95%CI [{1:N3},{2:N3}]" -f $preOR.odds_ratio,$preOR.ci95_low,$preOR.ci95_high)
    Write-Host ("2024-26 OR={0:N3} 95%CI [{1:N3},{2:N3}]" -f $postOR.odds_ratio,$postOR.ci95_low,$postOR.ci95_high)
    Write-Host ("post/pre OR ratio={0:N3} 95%CI [{1:N3},{2:N3}] z={3:N3} p={4:N6}" -f
        $interaction.post_pre_or_ratio,$interaction.ratio_ci95_low,$interaction.ratio_ci95_high,$interaction.z,$interaction.p_two_sided)

    Write-Host ''
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
