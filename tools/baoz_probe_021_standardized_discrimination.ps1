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

function Get-PooledSD {
    param($N1,$SD1,$N2,$SD2)
    if($null -eq $SD1 -or $null -eq $SD2){return $null}
    $n1=[double]$N1; $n2=[double]$N2
    if($n1 -lt 2 -or $n2 -lt 2){return $null}
    $v=((($n1-1)*[math]::Pow([double]$SD1,2))+(($n2-1)*[math]::Pow([double]$SD2,2)))/($n1+$n2-2)
    if($v -le 0){return $null}
    return [math]::Sqrt($v)
}

function Get-Stats {
    param(
        [Parameter(Mandatory)]$Connection,
        [Parameter(Mandatory)][string]$Feature,
        [Parameter(Mandatory)][string]$PeriodWhere
    )

    $sql=@"
SELECT
  Count(S.[$Feature]) AS NAll,
  Avg(S.[$Feature]) AS AvgAll,
  StDev(S.[$Feature]) AS SDAll,
  Sum(IIf(S.[確定着順]=1,1,0)) AS NWin,
  Avg(IIf(S.[確定着順]=1,S.[$Feature],Null)) AS AvgWin,
  StDev(IIf(S.[確定着順]=1,S.[$Feature],Null)) AS SDWin,
  Sum(IIf(S.[確定着順]<>1,1,0)) AS NNonWin,
  Avg(IIf(S.[確定着順]<>1,S.[$Feature],Null)) AS AvgNonWin,
  StDev(IIf(S.[確定着順]<>1,S.[$Feature],Null)) AS SDNonWin
FROM [出走馬T] AS S INNER JOIN [レースT] AS R
  ON S.[競走コード]=R.[競走コード]
WHERE S.[確定着順] Between 1 And 28
  AND S.[馬番] > 0
  AND S.[馬券評価順位]=1
  AND S.[単勝人気] Between 7 And 9
  AND R.[トラック種別コード]=1
  AND $PeriodWhere
  AND S.[$Feature] Is Not Null
"@
    return Invoke-Row $Connection $sql
}

function To-Effect {
    param($Stats)
    if(-not $Stats){return $null}
    $pooled=Get-PooledSD $Stats.NWin $Stats.SDWin $Stats.NNonWin $Stats.SDNonWin
    $d=$null
    if($null -ne $pooled -and $pooled -ne 0 -and $null -ne $Stats.AvgWin -and $null -ne $Stats.AvgNonWin){
        $d=([double]$Stats.AvgWin-[double]$Stats.AvgNonWin)/$pooled
    }
    return [pscustomobject]@{
        n_all=[int64]$Stats.NAll
        avg_all=$Stats.AvgAll
        sd_all=$Stats.SDAll
        n_win=[int64]$Stats.NWin
        avg_win=$Stats.AvgWin
        sd_win=$Stats.SDWin
        n_nonwin=[int64]$Stats.NNonWin
        avg_nonwin=$Stats.AvgNonWin
        sd_nonwin=$Stats.SDNonWin
        pooled_sd=$pooled
        effect_d=$d
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
    $cols=Get-ColumnNames $conn '出走馬T'
    $features=@(
        '予想タイム指数','デフォルト得点','得点',
        '血統距離評価','血統トラック評価','血統成長力評価','血統総合評価',
        '血統距離評価B','血統トラック評価B','血統成長力評価B','血統総合評価B',
        '先行指数','騎手評価','調教師評価','枠順評価','脚質評価','距離増減',
        'タイム指数上昇係数','タイム指数回帰推定値','タイム指数回帰標準偏差',
        '騎手ランキング','調教師ランキング','得点V1','得点V2','得点V3'
    ) | Where-Object { $cols -contains $_ }

    $beforeWhere='S.[年月日] Between #2019-01-01# And #2023-12-31#'
    $afterWhere='S.[年月日] Between #2024-01-01# And #2026-10-08#'

    $effects=@()
    foreach($feature in $features){
        try{
            $before=To-Effect (Get-Stats $conn $feature $beforeWhere)
            $after=To-Effect (Get-Stats $conn $feature $afterWhere)

            $compositionZ=$null
            if($null -ne $before.sd_all -and $null -ne $after.sd_all){
                $den=[math]::Sqrt(([math]::Pow([double]$before.sd_all,2)+[math]::Pow([double]$after.sd_all,2))/2)
                if($den -gt 0){
                    $compositionZ=([double]$after.avg_all-[double]$before.avg_all)/$den
                }
            }

            $effects += [pscustomobject]@{
                feature=$feature
                before_n=$before.n_all
                before_wins=$before.n_win
                before_d=$before.effect_d
                after_n=$after.n_all
                after_wins=$after.n_win
                after_d=$after.effect_d
                abs_before_d=if($null -ne $before.effect_d){[math]::Abs([double]$before.effect_d)}else{$null}
                abs_after_d=if($null -ne $after.effect_d){[math]::Abs([double]$after.effect_d)}else{$null}
                discrimination_change=if($null -ne $before.effect_d -and $null -ne $after.effect_d){
                    [math]::Abs([double]$after.effect_d)-[math]::Abs([double]$before.effect_d)
                }else{$null}
                signed_effect_change=if($null -ne $before.effect_d -and $null -ne $after.effect_d){
                    [double]$after.effect_d-[double]$before.effect_d
                }else{$null}
                direction_flip=if($null -ne $before.effect_d -and $null -ne $after.effect_d){
                    ([math]::Sign([double]$before.effect_d) -ne [math]::Sign([double]$after.effect_d))
                }else{$false}
                composition_shift_z=$compositionZ
            }
        }catch{
            $effects += [pscustomobject]@{
                feature=$feature
                error=$_.Exception.Message
            }
        }
    }

    $valid=@($effects | Where-Object { -not ($_.PSObject.Properties.Name -contains 'error') })
    $topChanged=@(
        $valid |
        Where-Object { $null -ne $_.discrimination_change } |
        Sort-Object { [math]::Abs([double]$_.discrimination_change) } -Descending |
        Select-Object -First 10
    )
    $yearFeatures=@($topChanged | ForEach-Object {$_.feature} | Sort-Object -Unique)

    $yearly=@()
    foreach($feature in $yearFeatures){
        foreach($year in 2019..2026){
            $endDate=if($year -eq 2026){'#2026-10-08#'}else{"#$year-12-31#"}
            $where="S.[年月日] Between #$year-01-01# And $endDate"
            try{
                $st=To-Effect (Get-Stats $conn $feature $where)
                $yearly += [pscustomobject]@{
                    feature=$feature
                    year=$year
                    n=$st.n_all
                    wins=$st.n_win
                    effect_d=$st.effect_d
                    avg_all=$st.avg_all
                }
            }catch{
                $yearly += [pscustomobject]@{
                    feature=$feature
                    year=$year
                    error=$_.Exception.Message
                }
            }
        }
    }

    $result=[ordered]@{
        mission='BAOZ-BASELINE-001'
        probe='BAOZ-PROBE-021'
        created_at=(Get-Date).ToString('yyyy-MM-ddTHH:mm:sszzz')
        safety=[ordered]@{
            read_only=$true
            aggregate_only=$true
            horse_rows_output=$false
            baoz_modified=$false
        }
        population='馬券評価順位=1 x popularity 7-9 x dirt'
        standardized_effects=$effects
        top_changed_features=$topChanged
        yearly_top_changed=$yearly
        interpretation_note='effect_d is standardized winner-minus-nonwinner separation. Absolute effect size measures discrimination, not causal importance. Sign direction depends on feature semantics. Winner samples are small and yearly estimates may be noisy.'
    }

    if(-not $OutputPath){
        $outDir=Join-Path $env:TEMP 'JIZO\BAOZ-BASELINE-001'
        New-Item -ItemType Directory -Path $outDir -Force | Out-Null
        $OutputPath=Join-Path $outDir 'baoz_probe_021_standardized_discrimination.json'
    }
    $result | ConvertTo-Json -Depth 16 | Set-Content -LiteralPath $OutputPath -Encoding utf8

    Write-Host ''
    Write-Host '============================================================' -ForegroundColor Cyan
    Write-Host ' BAOZ-PROBE-021 — STANDARDIZED DISCRIMINATION' -ForegroundColor Cyan
    Write-Host '============================================================' -ForegroundColor Cyan

    Write-Host '--- ALL FEATURES ---' -ForegroundColor Yellow
    $valid |
        Sort-Object discrimination_change |
        Select-Object feature,before_n,before_wins,before_d,after_n,after_wins,after_d,discrimination_change,direction_flip,composition_shift_z |
        Format-Table -AutoSize |
        Out-String -Width 220 |
        Write-Host

    Write-Host '--- TOP ABSOLUTE DISCRIMINATION CHANGES / YEARLY ---' -ForegroundColor Yellow
    $yearly |
        Format-Table feature,year,n,wins,effect_d,avg_all -AutoSize |
        Out-String -Width 180 |
        Write-Host

    $errors=@($effects | Where-Object { $_.PSObject.Properties.Name -contains 'error' })
    if($errors.Count -gt 0){
        Write-Host '--- ERRORS ---' -ForegroundColor DarkYellow
        $errors | Format-Table feature,error -AutoSize | Out-String -Width 180 | Write-Host
    }

    Write-Host ("Features checked    : {0}" -f $features.Count)
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
