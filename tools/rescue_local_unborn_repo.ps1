#Requires -Version 7.2
[CmdletBinding()]
param(
    [string]$SourcePath = '',
    [string]$CanonicalRepo = 'https://github.com/umanari1919/umanari-keiba.git',
    [string]$BranchName = 'rescue/neo-jizo-local-20261007',
    [switch]$NoPush,
    [switch]$SelfTest
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Invoke-GitText {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string[]]$Arguments,
        [switch]$AllowFailure
    )

    $output = & git -c "safe.directory=$Path" -C $Path @Arguments 2>&1
    $code = $LASTEXITCODE
    $text = (($output | ForEach-Object { "$_" }) -join [Environment]::NewLine).TrimEnd()
    if ($code -ne 0 -and -not $AllowFailure) {
        throw "git $($Arguments -join ' ') failed with exit code $code.`n$text"
    }
    [pscustomobject]@{ Code = $code; Text = $text }
}

function Resolve-SourcePath {
    param([string]$RequestedPath)

    $candidates = @()
    if ($RequestedPath) { $candidates += $RequestedPath }
    if ($env:NEO_JIZO_KEIBA_ROOT) { $candidates += $env:NEO_JIZO_KEIBA_ROOT }
    if ($env:USERPROFILE) {
        $candidates += (Join-Path $env:USERPROFILE 'Documents/Codex/2026-10-06/new-chat/neo-jizo-keiba')
    }

    foreach ($candidate in ($candidates | Select-Object -Unique)) {
        if (-not $candidate) { continue }
        if (-not (Test-Path -LiteralPath $candidate -PathType Container)) { continue }
        $resolved = (Resolve-Path -LiteralPath $candidate).Path
        $probe = Invoke-GitText -Path $resolved -Arguments @('rev-parse', '--is-inside-work-tree') -AllowFailure
        if ($probe.Code -eq 0 -and $probe.Text.Trim() -eq 'true') { return $resolved }
    }

    throw 'Source neo-jizo-keiba Git repository was not found.'
}

function Get-RelativeUnixPath {
    param([string]$Root, [string]$FullName)
    return ([IO.Path]::GetRelativePath($Root, $FullName) -replace '\\', '/')
}

function Test-ExcludedPath {
    param([string]$RelativePath)
    return ($RelativePath -match '(^|/)(\.git|\.venv|venv|node_modules|data|artifacts|backups|__pycache__|\.pytest_cache)(/|$)')
}

function Test-AllowedFile {
    param([IO.FileInfo]$File, [string]$RelativePath)

    if (Test-ExcludedPath -RelativePath $RelativePath) { return $false }
    if ($File.Extension.ToLowerInvariant() -in @('.bak', '.lnk', '.db', '.sqlite', '.sqlite3', '.parquet', '.feather', '.pickle', '.pkl')) { return $false }

    if ($RelativePath -in @('.gitignore', '.python-version', 'uv.lock')) { return $true }

    $allowed = @(
        '.py', '.ps1', '.psm1', '.cmd', '.bat', '.sql', '.toml', '.yml', '.yaml',
        '.json', '.md', '.txt', '.html', '.css', '.js', '.ts', '.tsx', '.jsx'
    )
    return ($File.Extension.ToLowerInvariant() -in $allowed)
}

function Get-FileSizeLimitBytes {
    param([IO.FileInfo]$File, [string]$RelativePath)

    if ($RelativePath -eq 'uv.lock') { return 5MB }

    switch ($File.Extension.ToLowerInvariant()) {
        '.json' { return 512KB }
        '.cmd'  { return 256KB }
        '.bat'  { return 256KB }
        '.html' { return 2MB }
        '.css'  { return 2MB }
        '.js'   { return 2MB }
        '.ts'   { return 2MB }
        '.tsx'  { return 2MB }
        '.jsx'  { return 2MB }
        '.py'   { return 2MB }
        '.ps1'  { return 2MB }
        '.psm1' { return 2MB }
        '.sql'  { return 2MB }
        '.toml' { return 1MB }
        '.yml'  { return 1MB }
        '.yaml' { return 1MB }
        '.md'   { return 2MB }
        '.txt'  { return 2MB }
        default { return 1MB }
    }
}

function Get-RescuePriority {
    param([string]$RelativePath, [IO.FileInfo]$File)

    if ($RelativePath -match '^(src|tests)/') { return 0 }
    if ($RelativePath -in @('.gitignore', '.python-version', 'pyproject.toml', 'README.md', 'AGENTS.md', 'HANDOVER.md', 'HANDOVER_ACTIVE.md', 'uv.lock')) { return 1 }
    if ($RelativePath -match '^docs/') { return 2 }
    if ($RelativePath -match '^web/') { return 3 }
    if ($File.Extension.ToLowerInvariant() -in @('.json', '.cmd', '.bat')) { return 5 }
    return 4
}

function Test-SecretRisk {
    param([IO.FileInfo]$File, [string]$RelativePath)

    if ($RelativePath -match '(?i)(^|/)(\.env($|\.)|.*secret.*|.*credential.*|id_rsa|id_ed25519|.*\.pem$|.*\.key$)') {
        return $true
    }

    if ($File.Length -gt 2MB) { return $false }

    try {
        $text = Get-Content -LiteralPath $File.FullName -Raw -ErrorAction Stop
    }
    catch {
        return $false
    }

    $patterns = @(
        '-----BEGIN (?:RSA |OPENSSH |EC |DSA )?PRIVATE KEY-----',
        'github_pat_[A-Za-z0-9_]{20,}',
        'ghp_[A-Za-z0-9]{20,}',
        'sk-[A-Za-z0-9_-]{20,}',
        '(?i)OPENAI_API_KEY\s*=\s*[^\s]+'
    )
    foreach ($pattern in $patterns) {
        if ($text -match $pattern) { return $true }
    }
    return $false
}

function New-RescueManifest {
    param(
        [string]$Source,
        [string]$WorkPath,
        [string]$Branch,
        [object[]]$Included,
        [object[]]$Conflicts,
        [string[]]$Same,
        [object[]]$Excluded,
        [string[]]$SecretRisk
    )

    $manifestDir = Join-Path $WorkPath 'rescue_manifest'
    New-Item -ItemType Directory -Force -Path $manifestDir | Out-Null

    $payload = [pscustomobject]@{
        mission = 'RESCUE-IMPORT-001'
        generated_at = (Get-Date).ToString('o')
        source_path = $Source
        branch = $Branch
        included_count = @($Included).Count
        conflict_count = @($Conflicts).Count
        same_count = @($Same).Count
        excluded_count = @($Excluded).Count
        secret_risk_count = @($SecretRisk).Count
        included = @($Included)
        conflicts = @($Conflicts)
        same = @($Same)
        excluded = @($Excluded)
        secret_risk_paths = @($SecretRisk)
    }

    $jsonPath = Join-Path $manifestDir 'RESCUE-IMPORT-001.json'
    ConvertTo-Json -InputObject $payload -Depth 8 | Set-Content -LiteralPath $jsonPath -Encoding utf8

    $md = @(
        '# RESCUE-IMPORT-001',
        '',
        "Generated: $($payload.generated_at)",
        '',
        "- Included: $($payload.included_count)",
        "- Conflicts preserved: $($payload.conflict_count)",
        "- Same skipped: $($payload.same_count)",
        "- Excluded: $($payload.excluded_count)",
        "- Secret-risk excluded: $($payload.secret_risk_count)",
        '',
        'Local conflicting versions are stored under `rescue_local_conflicts/` and do not overwrite canonical files.'
    )
    $md -join [Environment]::NewLine | Set-Content -LiteralPath (Join-Path $manifestDir 'RESCUE-IMPORT-001.md') -Encoding utf8
}

function Invoke-RescueImport {
    param(
        [string]$Source,
        [string]$Remote,
        [string]$RequestedBranch,
        [switch]$SkipPush
    )

    $sourceResolved = Resolve-SourcePath -RequestedPath $Source

    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $work = Join-Path ([IO.Path]::GetTempPath()) "neo-jizo-rescue-import-$stamp-$([guid]::NewGuid().ToString('N').Substring(0,8))"
    & git clone --quiet --no-tags $Remote $work
    if ($LASTEXITCODE -ne 0) { throw 'Failed to clone canonical repository.' }

    $branch = $RequestedBranch
    $existing = Invoke-GitText -Path $work -Arguments @('ls-remote', '--heads', 'origin', "refs/heads/$branch") -AllowFailure
    if ($existing.Code -eq 0 -and $existing.Text.Trim()) {
        $branch = "$RequestedBranch-$stamp"
    }
    Invoke-GitText -Path $work -Arguments @('checkout', '-b', $branch) | Out-Null

    $files = @(
        Get-ChildItem -LiteralPath $sourceResolved -File -Recurse -Depth 12 -ErrorAction SilentlyContinue |
            ForEach-Object {
                $rel0 = Get-RelativeUnixPath -Root $sourceResolved -FullName $_.FullName
                [pscustomobject]@{
                    File = $_
                    RelativePath = $rel0
                    Priority = Get-RescuePriority -RelativePath $rel0 -File $_
                }
            } |
            Sort-Object Priority, @{ Expression = { $_.File.Length } }, RelativePath
    )
    $included = [System.Collections.Generic.List[object]]::new()
    $conflicts = [System.Collections.Generic.List[object]]::new()
    $same = [System.Collections.Generic.List[string]]::new()
    $excluded = [System.Collections.Generic.List[object]]::new()
    $secretRisk = [System.Collections.Generic.List[string]]::new()
    [long]$totalBytes = 0

    foreach ($item in $files) {
        $file = $item.File
        $rel = $item.RelativePath

        if (-not (Test-AllowedFile -File $file -RelativePath $rel)) {
            $excluded.Add([pscustomobject]@{ path = $rel; reason = 'NOT_ALLOWLISTED'; bytes = [long]$file.Length })
            continue
        }

        $limit = Get-FileSizeLimitBytes -File $file -RelativePath $rel
        if ($file.Length -gt $limit) {
            $excluded.Add([pscustomobject]@{ path = $rel; reason = 'FILE_TOO_LARGE_FOR_TYPE'; bytes = [long]$file.Length })
            continue
        }
        if (Test-SecretRisk -File $file -RelativePath $rel) {
            $secretRisk.Add($rel)
            $excluded.Add([pscustomobject]@{ path = $rel; reason = 'SECRET_RISK'; bytes = [long]$file.Length })
            continue
        }

        if (($totalBytes + $file.Length) -gt 80MB) {
            $excluded.Add([pscustomobject]@{ path = $rel; reason = 'TOTAL_BUDGET_EXCEEDED'; bytes = [long]$file.Length })
            continue
        }
        $totalBytes += $file.Length

        $destRel = $rel
        $destPath = Join-Path $work ($destRel -replace '/', [IO.Path]::DirectorySeparatorChar)

        if (Test-Path -LiteralPath $destPath -PathType Leaf) {
            $localHash = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash
            $canonicalHash = (Get-FileHash -LiteralPath $destPath -Algorithm SHA256).Hash
            if ($localHash -eq $canonicalHash) {
                $same.Add($rel)
                continue
            }
            $destRel = "rescue_local_conflicts/$rel"
            $destPath = Join-Path $work ($destRel -replace '/', [IO.Path]::DirectorySeparatorChar)
            $conflicts.Add([pscustomobject]@{ source = $rel; preserved_as = $destRel })
        }
        elseif ($rel -match '^HANDOVER\.before-') {
            $name = [IO.Path]::GetFileName($rel)
            $destRel = "rescue_snapshot/handover_history/$name"
            $destPath = Join-Path $work ($destRel -replace '/', [IO.Path]::DirectorySeparatorChar)
        }

        $parent = Split-Path -Parent $destPath
        if ($parent) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
        Copy-Item -LiteralPath $file.FullName -Destination $destPath -Force
        $included.Add([pscustomobject]@{
            source = $rel
            destination = $destRel
            bytes = [long]$file.Length
            sha256 = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash
        })
    }

    New-RescueManifest -Source $sourceResolved -WorkPath $work -Branch $branch `
        -Included @($included) -Conflicts @($conflicts) -Same @($same) -Excluded @($excluded) -SecretRisk @($secretRisk)

    Invoke-GitText -Path $work -Arguments @('config', 'user.name', 'NEO JIZO Rescue Bot') | Out-Null
    Invoke-GitText -Path $work -Arguments @('config', 'user.email', 'neo-jizo-rescue@example.invalid') | Out-Null
    Invoke-GitText -Path $work -Arguments @('add', '-A') | Out-Null

    $status = (Invoke-GitText -Path $work -Arguments @('status', '--porcelain=v1')).Text
    if (-not $status.Trim()) { throw 'No rescue changes were produced.' }

    Invoke-GitText -Path $work -Arguments @('commit', '-m', 'rescue: preserve local unborn NEO JIZO worktree') | Out-Null
    $commit = (Invoke-GitText -Path $work -Arguments @('rev-parse', 'HEAD')).Text.Trim()

    $pushStatus = 'SKIPPED'
    $pushError = ''
    if (-not $SkipPush) {
        $push = Invoke-GitText -Path $work -Arguments @('push', '-u', 'origin', $branch) -AllowFailure
        if ($push.Code -eq 0) {
            $pushStatus = 'SUCCESS'
        }
        else {
            $pushStatus = 'FAILED'
            $pushError = $push.Text
        }
    }

    [pscustomobject]@{
        Source = $sourceResolved
        WorkPath = $work
        Branch = $branch
        Commit = $commit
        Included = @($included).Count
        Conflicts = @($conflicts).Count
        Same = @($same).Count
        Excluded = @($excluded).Count
        SecretRisk = @($secretRisk).Count
        IncludedBytes = $totalBytes
        PushStatus = $pushStatus
        PushError = $pushError
    }
}

function Invoke-SelfTest {
    $root = Join-Path ([IO.Path]::GetTempPath()) "rescue-import-selftest-$([guid]::NewGuid().ToString('N'))"
    New-Item -ItemType Directory -Force -Path $root | Out-Null
    try {
        $canonical = Join-Path $root 'canonical'
        & git init -q -b main $canonical
        & git -C $canonical config user.name 'SELFTEST'
        & git -C $canonical config user.email 'selftest@example.invalid'
        'canonical' | Set-Content -LiteralPath (Join-Path $canonical 'README.md') -Encoding utf8
        & git -C $canonical add README.md
        & git -C $canonical commit -q -m 'seed'

        $source = Join-Path $root 'source'
        & git init -q -b main $source
        New-Item -ItemType Directory -Force -Path (Join-Path $source 'src') | Out-Null
        New-Item -ItemType Directory -Force -Path (Join-Path $source 'web') | Out-Null
        'print("new")' | Set-Content -LiteralPath (Join-Path $source 'src/new.py') -Encoding utf8
        'local' | Set-Content -LiteralPath (Join-Path $source 'README.md') -Encoding utf8
        'echo ok' | Set-Content -LiteralPath (Join-Path $source 'web/start.cmd') -Encoding utf8
        'backup' | Set-Content -LiteralPath (Join-Path $source 'old.bak') -Encoding utf8
        ('x' * 700KB) | Set-Content -LiteralPath (Join-Path $source 'generated.json') -Encoding utf8

        $result = Invoke-RescueImport -Source $source -Remote $canonical -RequestedBranch 'rescue/selftest' -SkipPush
        if ($result.Included -lt 3) { throw 'Expected at least 3 included files.' }
        if ($result.Conflicts -ne 1) { throw "Expected 1 conflict, got $($result.Conflicts)." }
        if (-not (Test-Path -LiteralPath (Join-Path $result.WorkPath 'src/new.py'))) { throw 'Missing rescued src/new.py.' }
        if (-not (Test-Path -LiteralPath (Join-Path $result.WorkPath 'rescue_local_conflicts/README.md'))) { throw 'Missing preserved README conflict.' }
        if (Test-Path -LiteralPath (Join-Path $result.WorkPath 'old.bak')) { throw 'Backup file should not be rescued.' }
        if (Test-Path -LiteralPath (Join-Path $result.WorkPath 'generated.json')) { throw 'Oversized JSON should not be rescued.' }
        if (-not (Test-Path -LiteralPath (Join-Path $result.WorkPath 'rescue_manifest/RESCUE-IMPORT-001.json'))) { throw 'Missing rescue manifest.' }

        Write-Host 'RESCUE-IMPORT-001 self-test PASS'
    }
    finally {
        Remove-Item -LiteralPath $root -Recurse -Force -ErrorAction SilentlyContinue
    }
}

if ($SelfTest) {
    Invoke-SelfTest
    exit 0
}

$resolvedSource = Resolve-SourcePath -RequestedPath $SourcePath
$result = Invoke-RescueImport -Source $resolvedSource -Remote $CanonicalRepo -RequestedBranch $BranchName -SkipPush:$NoPush

Write-Host ''
Write-Host '============================================================' -ForegroundColor Cyan
Write-Host ' RESCUE-IMPORT-001 COMPLETE' -ForegroundColor Cyan
Write-Host '============================================================' -ForegroundColor Cyan
Write-Host "Source         : $($result.Source)"
Write-Host "Branch         : $($result.Branch)"
Write-Host "Commit         : $($result.Commit)"
Write-Host "Included       : $($result.Included)"
Write-Host "Conflicts saved: $($result.Conflicts)"
Write-Host "Same skipped   : $($result.Same)"
Write-Host "Excluded       : $($result.Excluded)"
Write-Host "Secret risks   : $($result.SecretRisk)"
Write-Host "Included MB    : $([math]::Round($result.IncludedBytes / 1MB, 2))"
Write-Host "Push           : $($result.PushStatus)"
Write-Host "Temp clone     : $($result.WorkPath)"
if ($result.PushStatus -eq 'FAILED') {
    Write-Host 'Push failed. The committed rescue clone is preserved locally.' -ForegroundColor Yellow
    Write-Host $result.PushError -ForegroundColor Yellow
}
Write-Host ''
Write-Host 'Original neo-jizo-keiba working tree was not modified.' -ForegroundColor Green