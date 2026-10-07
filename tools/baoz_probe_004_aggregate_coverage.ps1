[CmdletBinding()]
param(
    [string]$BaoZPath = '',
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
        $conn = $null
        try {
            $conn = New-Object -ComObject ADODB.Connection
            $conn.ConnectionTimeout = 5
            $conn.CommandTimeout = 30
            $conn.Open("Provider=$provider;Data Source=$Path;Mode=Read;")
            return [pscustomobject]@{ Connection=$conn; Provider=$provider }
        }
        catch {
            if ($conn) {
                try { $conn.Close() } catch {}
                try { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($conn) } catch {}
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
        if ($rs.EOF) { return $null }
        return $rs.Fields.Item(0).Value
    }
    finally {
        if ($rs) {
            try { $rs.Close() } catch {}
            try { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($rs) } catch {}
        }
    }
}

function Get-FieldCoverage {
    param(
        [Parameter(Mandatory)]$Connection,
        [Parameter(Mandatory)][string]$Table,
        [Parameter(Mandatory)][string[]]$Fields
    )

    $out=[ordered]@{}
    foreach($field in $Fields) {
        try {
            $sql="SELECT Count(*) FROM [$Table] WHERE [$field] Is Not Null"
            $out[$field]=[int64](Invoke-Scalar -Connection $Connection -Sql $sql)
        }
        catch {
            $out[$field]=$null
        }
    }
    return $out
}

function Inspect-TableAggregate {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Table,
        [string]$DateField='',
        [string[]]$CoverageFields=@(),
        [string[]]$RankFields=@()
    )

    $opened=Open-ReadOnlyConnection -Path $Path
    $conn=$opened.Connection
    try {
        $rowCount=[int64](Invoke-Scalar -Connection $conn -Sql "SELECT Count(*) FROM [$Table]")

        $minDate=$null
        $maxDate=$null
        if($DateField) {
            try { $minDate=Invoke-Scalar -Connection $conn -Sql "SELECT Min([$DateField]) FROM [$Table]" } catch {}
            try { $maxDate=Invoke-Scalar -Connection $conn -Sql "SELECT Max([$DateField]) FROM [$Table]" } catch {}
        }

        $coverage=Get-FieldCoverage -Connection $conn -Table $Table -Fields $CoverageFields
        $rank1=[ordered]@{}
        foreach($field in $RankFields) {
            try {
                $rank1[$field]=[int64](Invoke-Scalar -Connection $conn -Sql "SELECT Count(*) FROM [$Table] WHERE [$field]=1")
            }
            catch {
                $rank1[$field]=$null
            }
        }

        $raceCount=$null
        try {
            $raceCount=[int64](Invoke-Scalar -Connection $conn -Sql "SELECT Count(*) FROM (SELECT [競走コード] FROM [$Table] GROUP BY [競走コード]) AS Q")
        }
        catch {}

        return [ordered]@{
            provider=$opened.Provider
            row_count=$rowCount
            race_count=$raceCount
            min_date=$minDate
            max_date=$maxDate
            coverage=$coverage
            rank1_counts=$rank1
            error=$null
        }
    }
    catch {
        return [ordered]@{
            provider=$opened.Provider
            row_count=$null
            race_count=$null
            min_date=$null
            max_date=$null
            coverage=[ordered]@{}
            rank1_counts=[ordered]@{}
            error=$_.Exception.Message
        }
    }
    finally {
        try { $conn.Close() } catch {}
        try { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($conn) } catch {}
    }
}

if(-not $BaoZPath) {
    Write-Host 'BaoZ active DB root: auto-discovery...' -ForegroundColor DarkGray
    $BaoZPath=Find-BaoZRoot
}
$BaoZPath=(Resolve-Path -LiteralPath $BaoZPath).Path

$targets=@(
    [pscustomobject]@{
        label='active_runner_ex'
        relative='DB\BaoZ.ex.mdb'
        table='出走馬T'
        date='年月日'
        coverage=@(
            '競走コード','馬番','血統登録番号','予想タイム指数','予想タイム指数順位',
            'デフォルト得点','得点','馬券評価順位','得点V1','得点V2','得点V3',
            '得点V1順位','得点V2順位','デフォルト得点順位','得点V3順位',
            '単勝オッズ','単勝人気','単勝配当','複勝配当','入線順位','確定着順'
        )
        ranks=@('予想タイム指数順位','馬券評価順位','得点V1順位','得点V2順位','デフォルト得点順位','得点V3順位')
    },
    [pscustomobject]@{
        label='prediction_runner'
        relative='DB\BaoZ.mdb'
        table='出走馬T'
        date='年月日'
        coverage=@(
            '競走コード','馬番','血統登録番号','予想タイム指数','予想タイム指数順位',
            'デフォルト得点','得点','馬券評価順位','得点V1','得点V2','得点V3',
            '得点V1順位','得点V2順位','デフォルト得点順位','得点V3順位',
            '単勝オッズ','単勝人気','単勝配当','複勝配当','入線順位','確定着順'
        )
        ranks=@('予想タイム指数順位','馬券評価順位','得点V1順位','得点V2順位','デフォルト得点順位','得点V3順位')
    },
    [pscustomobject]@{
        label='master_runner'
        relative='DB\MasterDB\BaoZ-SE.mdb'
        table='出走馬マスタ'
        date='開催年月日'
        coverage=@('競走コード','馬番','血統登録番号','単勝オッズ','単勝人気順','入線順位','確定着順')
        ranks=@('単勝人気順')
    },
    [pscustomobject]@{
        label='race_prediction'
        relative='DB\BaoZ.mdb'
        table='レースT'
        date='月日'
        coverage=@('競走コード','予想計算済み','予想勝ち指数','予想決着指数','波乱度','頭数')
        ranks=@()
    }
)

$results=@()
foreach($target in $targets) {
    $path=Join-Path $BaoZPath $target.relative
    if(-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        $results += [ordered]@{
            label=$target.label
            relative_path=$target.relative
            table=$target.table
            stats=[ordered]@{error='FILE_NOT_FOUND'}
        }
        continue
    }

    $stats=Inspect-TableAggregate -Path $path -Table $target.table -DateField $target.date -CoverageFields $target.coverage -RankFields $target.ranks
    $results += [ordered]@{
        label=$target.label
        relative_path=$target.relative
        table=$target.table
        stats=$stats
    }
}

if(-not $OutputPath) {
    $outDir=Join-Path $env:TEMP 'JIZO\BAOZ-BASELINE-001'
    New-Item -ItemType Directory -Path $outDir -Force | Out-Null
    $OutputPath=Join-Path $outDir 'baoz_probe_004_aggregate_coverage.json'
}

$result=[ordered]@{
    mission='BAOZ-BASELINE-001'
    probe='BAOZ-PROBE-004'
    created_at=(Get-Date).ToString('yyyy-MM-ddTHH:mm:sszzz')
    safety=[ordered]@{
        aggregate_queries_only=$true
        horse_level_rows_output=$false
        modifies_baoz=$false
        reads_service_keys=$false
    }
    targets=@($results)
}

$result | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $OutputPath -Encoding utf8

Write-Host ''
Write-Host '============================================================' -ForegroundColor Cyan
Write-Host ' BAOZ-PROBE-004 — AGGREGATE COVERAGE' -ForegroundColor Cyan
Write-Host '============================================================' -ForegroundColor Cyan

foreach($item in $results) {
    $s=$item.stats
    Write-Host ("--- {0} :: {1} / {2} ---" -f $item.label,$item.relative_path,$item.table) -ForegroundColor Yellow
    if($s.error) {
        Write-Host ("ERROR              : {0}" -f $s.error)
        continue
    }
    Write-Host ("Rows               : {0}" -f $s.row_count)
    Write-Host ("Distinct races     : {0}" -f $s.race_count)
    Write-Host ("Date range         : {0} .. {1}" -f $s.min_date,$s.max_date)

    Write-Host 'Coverage:'
    foreach($key in $s.coverage.Keys) {
        Write-Host ("  {0,-18} {1}" -f $key,$s.coverage[$key])
    }

    if($s.rank1_counts.Count -gt 0) {
        Write-Host 'Rank=1 counts:'
        foreach($key in $s.rank1_counts.Keys) {
            Write-Host ("  {0,-18} {1}" -f $key,$s.rank1_counts[$key])
        }
    }
    Write-Host ''
}

Write-Host ("Aggregate only      : {0}" -f $result.safety.aggregate_queries_only)
Write-Host ("Horse rows output   : {0}" -f $result.safety.horse_level_rows_output)
Write-Host ("BaoZ modified       : {0}" -f $result.safety.modifies_baoz)
Write-Host ("Output              : {0}" -f $OutputPath)
Write-Host '============================================================'
