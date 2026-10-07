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

function Get-SegmentRows {
    param(
        [Parameter(Mandatory)]$Connection,
        [Parameter(Mandatory)][string]$Expr,
        [Parameter(Mandatory)][string]$PeriodWhere
    )

    $sql=@"
SELECT $Expr AS K,
       Count(*) AS N,
       Sum(IIf(S.[確定着順]=1,1,0)) AS W,
       Sum(IIf(S.[確定着順] Between 1 And 2,1,0)) AS T2,
       Sum(IIf(S.[確定着順] Between 1 And 3,1,0)) AS T3,
       Avg(S.[単勝人気]) AS AvgPop
FROM [出走馬T] AS S INNER JOIN [レースT] AS R
  ON S.[競走コード]=R.[競走コード]
WHERE S.[年月日] >= #2012-01-01#
  AND S.[年月日] <= #2026-10-08#
  AND S.[確定着順] Between 1 And 28
  AND S.[馬番] > 0
  AND S.[馬券評価順位]=1
  AND S.[単勝人気] >= 7
  AND $PeriodWhere
GROUP BY $Expr
"@
    $rows=Invoke-Rows $Connection $sql
    $out=@()
    foreach($r in $rows){
        $n=[int64]$r.N
        $out += [pscustomobject]@{
            key=[string]$r.K
            n=$n
            wins=[int64]$r.W
            win_rate=if($n){[math]::Round(([double]$r.W/$n),6)}else{$null}
            top2_rate=if($n){[math]::Round(([double]$r.T2/$n),6)}else{$null}
            top3_rate=if($n){[math]::Round(([double]$r.T3/$n),6)}else{$null}
            avg_popularity=if($null -ne $r.AvgPop){[math]::Round([double]$r.AvgPop,3)}else{$null}
        }
    }
    return @($out)
}

function Merge-Contribution {
    param($Before,$After,[int]$MinN=30)

    $keys=@($Before.key + $After.key | Sort-Object -Unique)
    $rows=@()
    foreach($key in $keys){
        $a=$Before | Where-Object {$_.key -eq $key} | Select-Object -First 1
        $b=$After  | Where-Object {$_.key -eq $key} | Select-Object -First 1
        $an=if($a){[int64]$a.n}else{0}
        $bn=if($b){[int64]$b.n}else{0}
        if($an -lt $MinN -and $bn -lt $MinN){continue}

        $expected=$null
        $deficit=$null
        if($a -and $b){
            $expected=[double]$a.win_rate * [double]$bn
            $deficit=[double]$b.wins - $expected
        }

        $rows += [pscustomobject]@{
            key=$key
            before_n=$an
            before_win=if($a){$a.win_rate}else{$null}
            before_top3=if($a){$a.top3_rate}else{$null}
            before_avg_pop=if($a){$a.avg_popularity}else{$null}
            after_n=$bn
            after_wins=if($b){$b.wins}else{$null}
            after_win=if($b){$b.win_rate}else{$null}
            after_top3=if($b){$b.top3_rate}else{$null}
            after_avg_pop=if($b){$b.avg_popularity}else{$null}
            delta_win=if($a -and $b){[math]::Round($b.win_rate-$a.win_rate,6)}else{$null}
            delta_top3=if($a -and $b){[math]::Round($b.top3_rate-$a.top3_rate,6)}else{$null}
            expected_after_wins_at_old_rate=if($null -ne $expected){[math]::Round($expected,2)}else{$null}
            win_deficit_vs_old_rate=if($null -ne $deficit){[math]::Round($deficit,2)}else{$null}
        }
    }
    return @($rows | Sort-Object win_deficit_vs_old_rate)
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

    $dims=[ordered]@{
        organizer='CStr(R.[主催者コード])'
        venue='CStr(R.[場コード]) & ":" & IIf(IsNull(R.[場名]),"",R.[場名])'
        track_type='CStr(R.[トラック種別コード])'
        field_size='IIf(R.[頭数]<=9,"<=9",IIf(R.[頭数]<=12,"10-12",IIf(R.[頭数]<=15,"13-15","16+")))'
        popularity='IIf(S.[単勝人気]<=9,"P7-9",IIf(S.[単勝人気]<=12,"P10-12","P13+"))'
        race_condition='CStr(R.[競走条件コード])'
        grade='CStr(R.[グレードコード])'
    }

    $comparisons=[ordered]@{}
    foreach($name in $dims.Keys){
        $a=Get-SegmentRows -Connection $conn -Expr $dims[$name] -PeriodWhere $before
        $b=Get-SegmentRows -Connection $conn -Expr $dims[$name] -PeriodWhere $after
        $comparisons[$name]=Merge-Contribution -Before $a -After $b -MinN 30
    }

    $overallBefore=Get-SegmentRows $conn '"ALL"' $before | Select-Object -First 1
    $overallAfter=Get-SegmentRows $conn '"ALL"' $after | Select-Object -First 1
    $overallExpected=[double]$overallBefore.win_rate * [double]$overallAfter.n
    $overallDeficit=[double]$overallAfter.wins - $overallExpected

    $result=[ordered]@{
        mission='BAOZ-BASELINE-001'
        probe='BAOZ-PROBE-011'
        created_at=(Get-Date).ToString('yyyy-MM-ddTHH:mm:sszzz')
        safety=[ordered]@{
            read_only=$true
            aggregate_only=$true
            horse_rows_output=$false
            baoz_modified=$false
        }
        target='P7+ rank-1 accuracy-decay decomposition'
        comparison=[ordered]@{
            before='2019-2023'
            after='2024-2026-10-08'
            overall_before=$overallBefore
            overall_after=$overallAfter
            expected_after_wins_at_old_rate=[math]::Round($overallExpected,2)
            observed_after_wins=[int64]$overallAfter.wins
            total_win_deficit_vs_old_rate=[math]::Round($overallDeficit,2)
        }
        segment_contributions=$comparisons
    }

    if(-not $OutputPath){
        $outDir=Join-Path $env:TEMP 'JIZO\BAOZ-BASELINE-001'
        New-Item -ItemType Directory -Path $outDir -Force | Out-Null
        $OutputPath=Join-Path $outDir 'baoz_probe_011_accuracy_decay.json'
    }
    $result | ConvertTo-Json -Depth 14 | Set-Content -LiteralPath $OutputPath -Encoding utf8

    Write-Host ''
    Write-Host '============================================================' -ForegroundColor Cyan
    Write-Host ' BAOZ-PROBE-011 — ACCURACY DECAY' -ForegroundColor Cyan
    Write-Host '============================================================' -ForegroundColor Cyan
    Write-Host ("Before win rate     : {0:P2}" -f $overallBefore.win_rate)
    Write-Host ("After win rate      : {0:P2}" -f $overallAfter.win_rate)
    Write-Host ("After observations  : {0}" -f $overallAfter.n)
    Write-Host ("Expected wins       : {0}" -f [math]::Round($overallExpected,2))
    Write-Host ("Observed wins       : {0}" -f $overallAfter.wins)
    Write-Host ("Win deficit         : {0}" -f [math]::Round($overallDeficit,2))
    Write-Host ''

    foreach($name in @('popularity','organizer','track_type','field_size','venue','race_condition','grade')){
        Write-Host ("--- {0} CONTRIBUTION ---" -f $name.ToUpper()) -ForegroundColor Yellow
        $comparisons[$name] |
            Select-Object -First 25 |
            Format-Table key,before_n,before_win,after_n,after_win,delta_win,expected_after_wins_at_old_rate,after_wins,win_deficit_vs_old_rate -AutoSize |
            Out-String -Width 220 |
            Write-Host
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
