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

function Invoke-Scalar {
    param([Parameter(Mandatory)]$Connection,[Parameter(Mandatory)][string]$Sql)
    $rs=$null
    try{
        $rs=$Connection.Execute($Sql)
        if($rs.EOF){return $null}
        $v=$rs.Fields.Item(0).Value
        if($v -is [DBNull]){return $null}
        return $v
    }finally{
        if($rs){
            try{$rs.Close()}catch{}
            try{[void][Runtime.InteropServices.Marshal]::ReleaseComObject($rs)}catch{}
        }
    }
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

if(-not $BaoZPath){
    Write-Host 'BaoZ active DB root: auto-discovery...' -ForegroundColor DarkGray
    $BaoZPath=Find-BaoZRoot
}
$BaoZPath=(Resolve-Path -LiteralPath $BaoZPath).Path
$db=Join-Path $BaoZPath 'DB\BaoZ.mdb'

$opened=Open-ReadOnlyConnection -Path $db
$conn=$opened.Connection

try{
    $cutoff=$CutoffDate.ToString('yyyy-MM-dd')

    $future=[ordered]@{
        runner_rows=[int64](Invoke-Scalar $conn "SELECT Count(*) FROM [出走馬T] WHERE [年月日] > #$cutoff#")
        rank_nonnull=[int64](Invoke-Scalar $conn "SELECT Count(*) FROM [出走馬T] WHERE [年月日] > #$cutoff# AND [馬券評価順位] Is Not Null")
        rank1_rows=[int64](Invoke-Scalar $conn "SELECT Count(*) FROM [出走馬T] WHERE [年月日] > #$cutoff# AND [馬券評価順位]=1")
        score_nonnull=[int64](Invoke-Scalar $conn "SELECT Count(*) FROM [出走馬T] WHERE [年月日] > #$cutoff# AND [得点] Is Not Null")
        finish_zero=[int64](Invoke-Scalar $conn "SELECT Count(*) FROM [出走馬T] WHERE [年月日] > #$cutoff# AND ([確定着順]=0 OR [確定着順] Is Null)")
        finish_zero_rank_nonnull=[int64](Invoke-Scalar $conn "SELECT Count(*) FROM [出走馬T] WHERE [年月日] > #$cutoff# AND ([確定着順]=0 OR [確定着順] Is Null) AND [馬券評価順位] Is Not Null")
    }

    $unresolvedPast=[ordered]@{
        rows=[int64](Invoke-Scalar $conn "SELECT Count(*) FROM [出走馬T] WHERE [年月日] Between #2012-01-01# And #$cutoff# AND ([確定着順]=0 OR [確定着順] Is Null)")
        rank_nonnull=[int64](Invoke-Scalar $conn "SELECT Count(*) FROM [出走馬T] WHERE [年月日] Between #2012-01-01# And #$cutoff# AND ([確定着順]=0 OR [確定着順] Is Null) AND [馬券評価順位] Is Not Null")
        rank1_rows=[int64](Invoke-Scalar $conn "SELECT Count(*) FROM [出走馬T] WHERE [年月日] Between #2012-01-01# And #$cutoff# AND ([確定着順]=0 OR [確定着順] Is Null) AND [馬券評価順位]=1")
    }

    $creationRelation=Invoke-Rows $conn @"
SELECT
  Sum(IIf([データ作成年月日] < [年月日],1,0)) AS BeforeRace,
  Sum(IIf([データ作成年月日] = [年月日],1,0)) AS SameDay,
  Sum(IIf([データ作成年月日] > [年月日],1,0)) AS AfterRace,
  Sum(IIf([データ作成年月日] Is Null,1,0)) AS MissingCreation,
  Min([データ作成年月日]) AS MinCreation,
  Max([データ作成年月日]) AS MaxCreation
FROM [出走馬T]
WHERE [年月日] Between #2012-01-01# And #$cutoff#
  AND [馬券評価順位] Is Not Null
"@ | Select-Object -First 1

    $creationByYear=Invoke-Rows $conn @"
SELECT Year([年月日]) AS Y,
       Count(*) AS N,
       Sum(IIf([データ作成年月日] < [年月日],1,0)) AS BeforeRace,
       Sum(IIf([データ作成年月日] = [年月日],1,0)) AS SameDay,
       Sum(IIf([データ作成年月日] > [年月日],1,0)) AS AfterRace
FROM [出走馬T]
WHERE [年月日] Between #2012-01-01# And #$cutoff#
  AND [馬券評価順位] Is Not Null
GROUP BY Year([年月日])
ORDER BY Year([年月日])
"@

    $cs=[ordered]@{
        rows=[int64](Invoke-Scalar $conn "SELECT Count(*) FROM [CS]")
        min_cs_date=(Invoke-Scalar $conn "SELECT Min([CS月日]) FROM [CS]")
        max_cs_date=(Invoke-Scalar $conn "SELECT Max([CS月日]) FROM [CS]")
        joined_runner_rows=[int64](Invoke-Scalar $conn "SELECT Count(*) FROM [CS] AS C INNER JOIN [出走馬T] AS S ON C.[競走コード]=S.[競走コード] AND C.[馬番]=S.[馬番]")
        joined_rank_nonnull=[int64](Invoke-Scalar $conn "SELECT Count(*) FROM [CS] AS C INNER JOIN [出走馬T] AS S ON C.[競走コード]=S.[競走コード] AND C.[馬番]=S.[馬番] WHERE S.[馬券評価順位] Is Not Null")
        cs_before_race=[int64](Invoke-Scalar $conn "SELECT Count(*) FROM [CS] AS C INNER JOIN [出走馬T] AS S ON C.[競走コード]=S.[競走コード] AND C.[馬番]=S.[馬番] WHERE C.[CS月日] < S.[年月日]")
        cs_same_day=[int64](Invoke-Scalar $conn "SELECT Count(*) FROM [CS] AS C INNER JOIN [出走馬T] AS S ON C.[競走コード]=S.[競走コード] AND C.[馬番]=S.[馬番] WHERE C.[CS月日] = S.[年月日]")
        cs_after_race=[int64](Invoke-Scalar $conn "SELECT Count(*) FROM [CS] AS C INNER JOIN [出走馬T] AS S ON C.[競走コード]=S.[競走コード] AND C.[馬番]=S.[馬番] WHERE C.[CS月日] > S.[年月日]")
    }

    $cr=[ordered]@{
        rows=[int64](Invoke-Scalar $conn "SELECT Count(*) FROM [CR]")
        min_cr_date=(Invoke-Scalar $conn "SELECT Min([CR月日]) FROM [CR]")
        max_cr_date=(Invoke-Scalar $conn "SELECT Max([CR月日]) FROM [CR]")
        joined_races=[int64](Invoke-Scalar $conn "SELECT Count(*) FROM [CR] AS C INNER JOIN [レースT] AS R ON C.[競走コード]=R.[競走コード]")
        cr_before_race=[int64](Invoke-Scalar $conn "SELECT Count(*) FROM [CR] AS C INNER JOIN [レースT] AS R ON C.[競走コード]=R.[競走コード] WHERE C.[CR月日] < R.[月日]")
        cr_same_day=[int64](Invoke-Scalar $conn "SELECT Count(*) FROM [CR] AS C INNER JOIN [レースT] AS R ON C.[競走コード]=R.[競走コード] WHERE C.[CR月日] = R.[月日]")
        cr_after_race=[int64](Invoke-Scalar $conn "SELECT Count(*) FROM [CR] AS C INNER JOIN [レースT] AS R ON C.[競走コード]=R.[競走コード] WHERE C.[CR月日] > R.[月日]")
    }

    $result=[ordered]@{
        mission='BAOZ-BASELINE-001'
        probe='BAOZ-PROBE-014'
        created_at=(Get-Date).ToString('yyyy-MM-ddTHH:mm:sszzz')
        safety=[ordered]@{
            read_only=$true
            aggregate_only=$true
            horse_rows_output=$false
            baoz_modified=$false
        }
        future_pre_result_evidence=$future
        unresolved_past=$unresolvedPast
        source_creation_vs_race=$creationRelation
        source_creation_by_year=$creationByYear
        cs_table=$cs
        cr_table=$cr
        interpretation_note='This probe can establish pre-result capability and date relationships, but cannot by itself prove that every historical rank was frozen contemporaneously rather than recomputed later.'
    }

    if(-not $OutputPath){
        $outDir=Join-Path $env:TEMP 'JIZO\BAOZ-BASELINE-001'
        New-Item -ItemType Directory -Path $outDir -Force | Out-Null
        $OutputPath=Join-Path $outDir 'baoz_probe_014_temporal_integrity.json'
    }
    $result | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $OutputPath -Encoding utf8

    Write-Host ''
    Write-Host '============================================================' -ForegroundColor Cyan
    Write-Host ' BAOZ-PROBE-014 — TEMPORAL INTEGRITY' -ForegroundColor Cyan
    Write-Host '============================================================' -ForegroundColor Cyan

    Write-Host '--- FUTURE / PRE-RESULT EVIDENCE ---' -ForegroundColor Yellow
    foreach($k in $future.Keys){ Write-Host ("{0,-28} {1}" -f $k,$future[$k]) }

    Write-Host ''
    Write-Host '--- UNRESOLVED PAST ---' -ForegroundColor Yellow
    foreach($k in $unresolvedPast.Keys){ Write-Host ("{0,-28} {1}" -f $k,$unresolvedPast[$k]) }

    Write-Host ''
    Write-Host '--- SOURCE CREATION vs RACE DATE ---' -ForegroundColor Yellow
    $creationRelation | Format-List | Out-String -Width 140 | Write-Host

    Write-Host '--- SOURCE CREATION BY YEAR ---' -ForegroundColor Yellow
    $creationByYear |
        Format-Table Y,N,BeforeRace,SameDay,AfterRace -AutoSize |
        Out-String -Width 150 |
        Write-Host

    Write-Host '--- CS TABLE ---' -ForegroundColor Yellow
    foreach($k in $cs.Keys){ Write-Host ("{0,-28} {1}" -f $k,$cs[$k]) }

    Write-Host ''
    Write-Host '--- CR TABLE ---' -ForegroundColor Yellow
    foreach($k in $cr.Keys){ Write-Host ("{0,-28} {1}" -f $k,$cr[$k]) }

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
