[CmdletBinding()]
param(
    [string]$BaoZPath = '',
    [string]$OutputPath = '',
    [switch]$NoSchema
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Resolve-BaoZRootFromFile {
    param([Parameter(Mandatory)][string]$FilePath)

    $dir = Split-Path -Parent $FilePath
    if (-not $dir) { return $null }

    $current = Get-Item -LiteralPath $dir -ErrorAction SilentlyContinue
    for ($i = 0; $i -lt 6 -and $current; $i++) {
        if ($current.Name -ieq 'BaoZ') {
            return $current.FullName
        }
        $current = $current.Parent
    }

    return $dir
}

function Find-BaoZMarker {
    param(
        [Parameter(Mandatory)][string]$Root,
        [int]$Depth = 4
    )

    if (-not (Test-Path -LiteralPath $Root -PathType Container)) {
        return $null
    }

    $names = @('BaoZ.mdb', 'BaoZ.MDB', 'BaoZ.bzi', 'BaoZ.BZI')
    foreach ($name in $names) {
        try {
            $hit = Get-ChildItem -LiteralPath $Root -Filter $name -File -Recurse -Depth $Depth -ErrorAction SilentlyContinue |
                Select-Object -First 1
            if ($hit) {
                return (Resolve-BaoZRootFromFile -FilePath $hit.FullName)
            }
        }
        catch {}
    }

    return $null
}

function Get-DefaultBaoZPath {
    $directCandidates = New-Object System.Collections.Generic.List[string]

    function Add-Candidate {
        param([string]$Path)
        if ([string]::IsNullOrWhiteSpace($Path)) { return }
        try {
            $full = [Environment]::ExpandEnvironmentVariables($Path.Trim('"'))
            if ($full -and -not $directCandidates.Contains($full)) {
                [void]$directCandidates.Add($full)
            }
        }
        catch {}
    }

    # 1) Standard user folders.
    Add-Candidate ([Environment]::GetFolderPath('MyDocuments'))
    Add-Candidate (Join-Path $env:USERPROFILE 'Documents')
    if ($env:OneDrive) {
        Add-Candidate (Join-Path $env:OneDrive 'Documents')
    }
    if ($env:OneDriveConsumer) {
        Add-Candidate (Join-Path $env:OneDriveConsumer 'Documents')
    }
    Add-Candidate (Join-Path $env:USERPROFILE 'Desktop')
    Add-Candidate $env:LOCALAPPDATA
    Add-Candidate $env:APPDATA
    Add-Candidate $env:PROGRAMDATA

    # 2) Common direct install/data locations.
    Add-Candidate 'C:\BaoZ'
    Add-Candidate 'D:\BaoZ'
    Add-Candidate 'C:\BAOZ'
    Add-Candidate 'D:\BAOZ'
    Add-Candidate ([Environment]::GetEnvironmentVariable('ProgramFiles'))
    Add-Candidate ([Environment]::GetEnvironmentVariable('ProgramFiles(x86)'))

    # 3) Running BaoZ-related process paths.
    try {
        Get-Process -ErrorAction SilentlyContinue |
            Where-Object { $_.ProcessName -match '(?i)baoz|馬王' } |
            ForEach-Object {
                try {
                    if ($_.Path) {
                        Add-Candidate (Split-Path -Parent $_.Path)
                    }
                }
                catch {}
            }
    }
    catch {}

    # 4) Start-menu/Desktop shortcuts.
    try {
        $shortcutRoots = @(
            [Environment]::GetFolderPath('Desktop'),
            [Environment]::GetFolderPath('CommonDesktopDirectory'),
            [Environment]::GetFolderPath('StartMenu'),
            [Environment]::GetFolderPath('CommonStartMenu')
        ) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }

        $shell = New-Object -ComObject WScript.Shell
        foreach ($root in $shortcutRoots) {
            Get-ChildItem -LiteralPath $root -Filter '*.lnk' -File -Recurse -Depth 5 -ErrorAction SilentlyContinue |
                Where-Object { $_.Name -match '(?i)baoz|馬王' } |
                ForEach-Object {
                    try {
                        $target = $shell.CreateShortcut($_.FullName).TargetPath
                        if ($target) {
                            Add-Candidate (Split-Path -Parent $target)
                        }
                    }
                    catch {}
                }
        }
        try { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($shell) } catch {}
    }
    catch {}

    # 5) Installed-app registry entries. Values only; no keys/secrets are exported.
    $uninstallRoots = @(
        'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*',
        'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*',
        'HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*'
    )
    foreach ($root in $uninstallRoots) {
        try {
            Get-ItemProperty $root -ErrorAction SilentlyContinue |
                Where-Object { $_.DisplayName -match '(?i)baoz|馬王' } |
                ForEach-Object {
                    if ($_.InstallLocation) {
                        Add-Candidate $_.InstallLocation
                    }
                    if ($_.DisplayIcon) {
                        $icon = ([string]$_.DisplayIcon -split ',')[0].Trim('"')
                        if ($icon) {
                            Add-Candidate (Split-Path -Parent $icon)
                        }
                    }
                }
        }
        catch {}
    }

    # 6) Inspect candidates with a bounded search.
    foreach ($candidate in $directCandidates) {
        $found = Find-BaoZMarker -Root $candidate -Depth 4
        if ($found) {
            return (Resolve-Path -LiteralPath $found).Path
        }
    }

    # 7) Last-resort bounded drive-root search. Avoid a whole-disk crawl.
    foreach ($drive in @('C:\', 'D:\')) {
        if (-not (Test-Path -LiteralPath $drive)) { continue }
        try {
            $named = Get-ChildItem -LiteralPath $drive -Directory -Filter 'BaoZ' -Recurse -Depth 4 -ErrorAction SilentlyContinue |
                Select-Object -First 10
            foreach ($dir in $named) {
                $found = Find-BaoZMarker -Root $dir.FullName -Depth 4
                if ($found) {
                    return (Resolve-Path -LiteralPath $found).Path
                }
            }
        }
        catch {}
    }

    throw @"
BaoZ data folder was not found automatically.
The probe searched Documents/OneDrive, running processes, shortcuts,
installed-app registry locations, common install folders, and bounded C:/D: roots.
No BaoZ files were modified.
"@
}

function Test-ComProgId {
    param([Parameter(Mandatory)][string]$ProgId)

    try {
        $type = [type]::GetTypeFromProgID($ProgId, $true)
        return [bool]$type
    }
    catch {
        return $false
    }
}

function Get-MdbSchema {
    param([Parameter(Mandatory)][string]$Path)

    $providers = @(
        'Microsoft.ACE.OLEDB.16.0',
        'Microsoft.ACE.OLEDB.12.0',
        'Microsoft.Jet.OLEDB.4.0'
    )

    $connection = $null
    $providerUsed = $null
    $lastError = $null

    foreach ($provider in $providers) {
        try {
            $connection = New-Object -ComObject ADODB.Connection
            $connection.ConnectionTimeout = 5
            $connection.CommandTimeout = 10
            $connection.Open("Provider=$provider;Data Source=$Path;Mode=Read;")
            $providerUsed = $provider
            break
        }
        catch {
            $lastError = $_.Exception.Message
            if ($connection) {
                try { $connection.Close() } catch {}
                try { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($connection) } catch {}
            }
            $connection = $null
        }
    }

    if (-not $connection) {
        return [ordered]@{
            provider = $null
            opened = $false
            error = $lastError
            tables = @()
        }
    }

    $tables = @()
    $recordset = $null

    try {
        # 20 = adSchemaTables. Schema only; no user rows are read.
        $recordset = $connection.OpenSchema(20)
        while (-not $recordset.EOF) {
            $tableName = [string]$recordset.Fields.Item('TABLE_NAME').Value
            $tableType = [string]$recordset.Fields.Item('TABLE_TYPE').Value
            if ($tableType -eq 'TABLE' -and $tableName -notmatch '^MSys') {
                $tables += [ordered]@{
                    name = $tableName
                    type = $tableType
                }
            }
            $recordset.MoveNext()
        }
    }
    finally {
        if ($recordset) {
            try { $recordset.Close() } catch {}
            try { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($recordset) } catch {}
        }
        try { $connection.Close() } catch {}
        try { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($connection) } catch {}
    }

    return [ordered]@{
        provider = $providerUsed
        opened = $true
        error = $null
        tables = @($tables | Sort-Object name)
    }
}

if (-not $BaoZPath) {
    Write-Host 'BaoZ path: auto-discovery...' -ForegroundColor DarkGray
    $BaoZPath = Get-DefaultBaoZPath
}
$BaoZPath = (Resolve-Path -LiteralPath $BaoZPath).Path

if (-not $OutputPath) {
    $outDir = Join-Path $env:TEMP 'JIZO\BAOZ-BASELINE-001'
    New-Item -ItemType Directory -Path $outDir -Force | Out-Null
    $OutputPath = Join-Path $outDir 'baoz_probe_001.json'
}

$files = @(
    Get-ChildItem -LiteralPath $BaoZPath -File -Recurse -ErrorAction Stop |
        Where-Object {
            $_.Extension -in @('.MDB', '.mdb', '.bzi', '.BZI') -and
            $_.FullName.Length -lt 1000
        } |
        Sort-Object FullName
)

$mdbs = @($files | Where-Object { $_.Extension -ieq '.mdb' })

$relativeFiles = foreach ($file in $files) {
    $relative = [IO.Path]::GetRelativePath($BaoZPath, $file.FullName)
    [ordered]@{
        relative_path = $relative
        extension = $file.Extension
        size_bytes = $file.Length
        last_write_time = $file.LastWriteTime.ToString('yyyy-MM-ddTHH:mm:ss')
    }
}

$schemas = @()
if (-not $NoSchema) {
    foreach ($mdb in $mdbs) {
        $relative = [IO.Path]::GetRelativePath($BaoZPath, $mdb.FullName)
        $schema = Get-MdbSchema -Path $mdb.FullName
        $schemas += [ordered]@{
            relative_path = $relative
            provider = $schema.provider
            opened = $schema.opened
            error = $schema.error
            tables = $schema.tables
        }
    }
}

$result = [ordered]@{
    mission = 'BAOZ-BASELINE-001'
    probe = 'BAOZ-PROBE-001'
    created_at = (Get-Date).ToString('yyyy-MM-ddTHH:mm:sszzz')
    safety = [ordered]@{
        read_only = $true
        row_data_read = $false
        service_keys_read = $false
        baoz_files_modified = $false
    }
    environment = [ordered]@{
        os_64bit = [Environment]::Is64BitOperatingSystem
        process_64bit = [Environment]::Is64BitProcess
        powershell = $PSVersionTable.PSVersion.ToString()
        jvlink_com_registered = (Test-ComProgId 'JVDTLab.JVLink')
        nvlink_com_registered = (
            (Test-ComProgId 'NVDTLabLib.NVLink') -or
            (Test-ComProgId 'NVDTLab.NVLink')
        )
    }
    baoz = [ordered]@{
        path_redacted = '<BaoZ>'
        file_count = $relativeFiles.Count
        mdb_count = $mdbs.Count
        files = @($relativeFiles)
        schemas = @($schemas)
    }
}

$json = $result | ConvertTo-Json -Depth 12
$parent = Split-Path -Parent $OutputPath
if ($parent) {
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
}
Set-Content -LiteralPath $OutputPath -Value $json -Encoding utf8

Write-Host ''
Write-Host '============================================================' -ForegroundColor Cyan
Write-Host ' BAOZ-PROBE-001 COMPLETE' -ForegroundColor Cyan
Write-Host '============================================================' -ForegroundColor Cyan
Write-Host ("BaoZ location found  : YES")
Write-Host ("BaoZ files          : {0}" -f $relativeFiles.Count)
Write-Host ("MDB files           : {0}" -f $mdbs.Count)
Write-Host ("JV-Link COM         : {0}" -f $result.environment.jvlink_com_registered)
Write-Host ("UmaConn COM         : {0}" -f $result.environment.nvlink_com_registered)
Write-Host ("Row data read       : {0}" -f $result.safety.row_data_read)
Write-Host ("BaoZ files modified : {0}" -f $result.safety.baoz_files_modified)
Write-Host ("Output              : {0}" -f $OutputPath)
Write-Host '============================================================'
