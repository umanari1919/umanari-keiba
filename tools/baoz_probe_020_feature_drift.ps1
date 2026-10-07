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

function Get-ColumnNames {
    param([Parameter(Mandatory)]$Connection,[Parameter(Mandatory)][string]$Table)
    $schema=$null; $names=@()
    try{
        $schema=$Connection.OpenSchema(4)
        while(-not $schema.EOF){
            if([string]$schema.Fields.Item('TABLE_NAME').Value -eq $Table){
                $names += [string]$schema.Fields.Item('COLUMN_NAME').Value
            }
            $schema.MoveNext()
        }
        return @($names)
    }finally{
        if($schema){
            try{$schema.Close()}catch{}
            try{[void][Runtime.InteropServices.Marshal]::ReleaseComObject($schema)}catch{}
        }
    }
}

function Get-FeatureStats {
    param(
        [Parameter(Mandatory)]$Connection,
        [Parameter(Mandatory)][string]$Feature,
        [Parameter(Mandatory)][string]$PeriodWhere
    )

    $sql=@"
SELECT
  Count([$Feature]) AS N,
  Avg([$Feature]) AS AvgAll,
  Min([$Feature]) AS MinAll,
  Max([$Feature]) AS MaxAll,
  Avg(IIf([確定着順]=1,[$Feature],Null)) AS AvgWin,
  Avg(IIf([確定着順] Between 1 And 3,[$Feature],Null)) AS AvgTop3,
  Avg(IIf([確定着順]<>1,[$Feature],Null)) AS AvgNonWin
FROM [出走馬T]
WHERE [年月日] Between #2012-01-01# And #2026-10-08#
  AND [確定着順] Between 1 And 28
  AND [馬番] > 0
  AND [馬券評価順位]=1
  AND [単勝人気] Between 7 And 9
  AND [トラック種別コード]=1
  AND $PeriodWhere
  AND [$Feature] Is Not Null
"@
    return Invoke-Row $Connection $sql
}

if(-not $BaoZPath){
    Write-Host 'BaoZ active DB root: auto-discovery...' -ForegroundColor DarkGray
    $BaoZPath=Find-BaoZRoot
}
$BaoZPath=(Resolve-Path -LiteralPath $BaoZPath).Path
$db=Join-Path $BaoZPath 'DB\BaoZ.ex.mdb'

$opened=Open-ReadOnlyConnection -Path $db
$conn=$opened.Connection

try{
    $cols=Get-ColumnNames $conn '出走馬T'

    $wanted=@(
        '予想タイム指数',
        'デフォルト得点',
        '得点',
        '血統距離評価',
        '血統トラック評価',
        '血統成長力評価',
        '血統総合評価',
        '血統距離評価B',
        '血統トラック評価B',
        '血統成長力評価B',
        '血統総合評価B',
        '先行指数',
        '騎手評価',
        '調教師評価',
        '枠順評価',
        '脚質評価',
        '距離増減',
        'タイム指数上昇係数',
        'タイム指数回帰推定値',
        'タイム指数回帰標準偏差',
        '騎手ランキング',
        '調教師ランキング',
        '得点V1',
        '得点V2',
        '得点V3'
    ) | Where-Object { $cols -contains $_ }

    $before='[年月日] Between #2019-01-01# And #2023-12-31#'
    $after='[年月日] Between #2024-01-01# And #2026-10-08#'

    $rows=@()
    foreach($feature in $wanted){
        try{
            $a=Get-FeatureStats $conn $feature $before
            $b=Get-FeatureStats $conn $feature $after

            $rows += [pscustomobject]@{
                feature=$feature
                before_n=$a.N
                before_avg=$a.AvgAll
                before_avg_win=$a.AvgWin
                before_avg_top3=$a.AvgTop3
                before_avg_nonwin=$a.AvgNonWin
                after_n=$b.N
                after_avg=$b.AvgAll
                after_avg_win=$b.AvgWin
                after_avg_top3=$b.AvgTop3
                after_avg_nonwin=$b.AvgNonWin
                delta_avg=if($null -ne $a.AvgAll -and $null -ne $b.AvgAll){[double]$b.AvgAll-[double]$a.AvgAll}else{$null}
                before_win_sep=if($null -ne $a.AvgWin -and $null -ne $a.AvgNonWin){[double]$a.AvgWin-[double]$a.AvgNonWin}else{$null}
                after_win_sep=if($null -ne $b.AvgWin -and $null -ne $b.AvgNonWin){[double]$b.AvgWin-[double]$b.AvgNonWin}else{$null}
                sep_change=if($null -ne $a.AvgWin -and $null -ne $a.AvgNonWin -and $null -ne $b.AvgWin -and $null -ne $b.AvgNonWin){
                    ([double]$b.AvgWin-[double]$b.AvgNonWin)-([double]$a.AvgWin-[double]$a.AvgNonWin)
                }else{$null}
            }
        }catch{
            $rows += [pscustomobject]@{
                feature=$feature
                error=$_.Exception.Message
            }
        }
    }

    $result=[ordered]@{
        mission='BAOZ-BASELINE-001'
        probe='BAOZ-PROBE-020'
        created_at=(Get-Date).ToString('yyyy-MM-ddTHH:mm:sszzz')
        safety=[ordered]@{
            read_only=$true
            aggregate_only=$true
            horse_rows_output=$false
            baoz_modified=$false
        }
        population='馬券評価順位=1 x popularity 7-9 x dirt'
        comparison=[ordered]@{
            before='2019-2023'
            after='2024-2026-10-08'
        }
        feature_stats=$rows
        interpretation_note='Feature-average drift identifies composition change. Winner-vs-nonwinner separation change identifies whether a feature lost discriminative usefulness inside this selected population. Neither is causal proof.'
    }

    if(-not $OutputPath){
        $outDir=Join-Path $env:TEMP 'JIZO\BAOZ-BASELINE-001'
        New-Item -ItemType Directory -Path $outDir -Force | Out-Null
        $OutputPath=Join-Path $outDir 'baoz_probe_020_feature_drift.json'
    }
    $result | ConvertTo-Json -Depth 14 | Set-Content -LiteralPath $OutputPath -Encoding utf8

    Write-Host ''
    Write-Host '============================================================' -ForegroundColor Cyan
    Write-Host ' BAOZ-PROBE-020 — P7-9 DIRT FEATURE DRIFT' -ForegroundColor Cyan
    Write-Host '============================================================' -ForegroundColor Cyan

    $ok=@($rows | Where-Object { -not ($_.PSObject.Properties.Name -contains 'error') })

    Write-Host '--- FEATURE COMPOSITION / WINNER SEPARATION ---' -ForegroundColor Yellow
    $ok |
        Select-Object feature,before_avg,after_avg,delta_avg,before_win_sep,after_win_sep,sep_change |
        Format-Table -AutoSize |
        Out-String -Width 210 |
        Write-Host

    $errors=@($rows | Where-Object { $_.PSObject.Properties.Name -contains 'error' })
    if($errors.Count -gt 0){
        Write-Host '--- FEATURE ERRORS ---' -ForegroundColor DarkYellow
        $errors | Format-Table feature,error -AutoSize | Out-String -Width 180 | Write-Host
    }

    Write-Host ("Features checked    : {0}" -f $wanted.Count)
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
