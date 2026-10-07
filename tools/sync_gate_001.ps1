#Requires -Version 7.2
[CmdletBinding()]
param(
    [string]$RepoPath = '',
    [string]$CanonicalRepo = 'https://github.com/umanari1919/umanari-keiba.git',
    [string]$CanonicalBranch = 'main',
    [string]$OutputDir = '',
    [switch]$SelfTest
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Redact-SensitiveText {
    param([AllowNull()][string]$Text)
    if ($null -eq $Text) { return '' }
    $value = $Text
    $value = $value -replace 'https://[^/\s]+@github\.com', 'https://***@github.com'
    $value = $value -replace '(ghp_|github_pat_)[A-Za-z0-9_]+', '$1***'
    return $value
}

function Invoke-GitText {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string[]]$Arguments,
        [switch]$AllowFailure
    )

    # Use a command-scoped safe.directory exception so repositories created by
    # Codex/Agent sandbox accounts can be audited without modifying global Git config.
    $output = & git -c "safe.directory=$Path" -C $Path @Arguments 2>&1
    $code = $LASTEXITCODE
    $text = (($output | ForEach-Object { "$_" }) -join "`n").TrimEnd()

    if ($code -ne 0 -and -not $AllowFailure) {
        throw "git $($Arguments -join ' ') failed with exit code $code.`n$(Redact-SensitiveText $text)"
    }

    [pscustomobject]@{
        Code = $code
        Text = (Redact-SensitiveText $text)
    }
}


function Test-GitRepo {
    param([Parameter(Mandatory)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) { return $false }
    $inside = Invoke-GitText -Path $Path -Arguments @('rev-parse', '--is-inside-work-tree') -AllowFailure
    return ($inside.Code -eq 0 -and $inside.Text.Trim() -eq 'true')
}

function Get-RepoRemoteText {
    param([Parameter(Mandatory)][string]$Path)
    if (-not (Test-GitRepo -Path $Path)) { return '' }
    return (Invoke-GitText -Path $Path -Arguments @('remote', '-v') -AllowFailure).Text
}

function Resolve-NeoJizoRepo {
    param([string]$RequestedPath)

    $candidates = [System.Collections.Generic.List[string]]::new()

    if ($RequestedPath) { $candidates.Add($RequestedPath) }
    if ($env:NEO_JIZO_KEIBA_ROOT) { $candidates.Add($env:NEO_JIZO_KEIBA_ROOT) }

    $candidates.Add((Join-Path $HOME 'Documents/Codex/2026-10-06/new-chat/neo-jizo-keiba'))
    if ($env:USERPROFILE) {
        $candidates.Add((Join-Path $env:USERPROFILE 'Documents/Codex/2026-10-06/new-chat/neo-jizo-keiba'))
        $candidates.Add((Join-Path $env:USERPROFILE 'Downloads/THE-JOCKEY-RESEARCH'))
    }

    foreach ($known in @('C:\dev\The-JOCKEY','C:\dev\THE-JOCKEY','D:\keiba_ai','D:\THE-JOCKEY-RESEARCH','D:\The-JOCKEY')) {
        $candidates.Add($known)
    }

    $valid = [System.Collections.Generic.List[string]]::new()
    $nonGitNamed = [System.Collections.Generic.List[string]]::new()

    foreach ($candidate in ($candidates | Select-Object -Unique)) {
        if (-not $candidate) { continue }
        if (-not (Test-Path -LiteralPath $candidate -PathType Container)) { continue }

        $resolved = (Resolve-Path -LiteralPath $candidate).Path
        if (Test-GitRepo -Path $resolved) {
            $valid.Add($resolved)
        }
        elseif ((Split-Path -Leaf $resolved) -match 'neo-jizo-keiba|the-jockey|keiba_ai') {
            $nonGitNamed.Add($resolved)
        }
    }

    $searchRoots = [System.Collections.Generic.List[string]]::new()
    if ($env:USERPROFILE) {
        $searchRoots.Add((Join-Path $env:USERPROFILE 'Documents/Codex'))
        $searchRoots.Add((Join-Path $env:USERPROFILE 'Downloads'))
    }
    $searchRoots.Add('C:\dev')

    foreach ($root in ($searchRoots | Select-Object -Unique)) {
        if (-not (Test-Path -LiteralPath $root -PathType Container)) { continue }
        try {
            Get-ChildItem -LiteralPath $root -Directory -Filter '.git' -Recurse -Depth 8 -Force -ErrorAction SilentlyContinue |
                ForEach-Object {
                    $parent = $_.Parent.FullName
                    if ($parent -and -not $valid.Contains($parent)) {
                        $valid.Add($parent)
                    }
                }
        }
        catch {
        }
    }

    $valid = @($valid | Select-Object -Unique)

    if ($RequestedPath) {
        $requestedResolved = if (Test-Path -LiteralPath $RequestedPath -PathType Container) {
            (Resolve-Path -LiteralPath $RequestedPath).Path
        } else { $null }
        if ($requestedResolved -and (Test-GitRepo -Path $requestedResolved)) {
            return $requestedResolved
        }
    }

    $remoteMatches = @()
    foreach ($repo in $valid) {
        $remoteText = Get-RepoRemoteText -Path $repo
        if ($remoteText -match 'github\.com[/:]umanari1919/umanari-keiba(?:\.git)?') {
            $remoteMatches += $repo
        }
    }
    if ($remoteMatches.Count -eq 1) {
        return $remoteMatches[0]
    }

    $named = @($valid | Where-Object { (Split-Path -Leaf $_) -ieq 'neo-jizo-keiba' })
    if ($named.Count -eq 1) {
        return $named[0]
    }

    $lines = [System.Collections.Generic.List[string]]::new()
    $lines.Add('neo-jizo-keiba Git repository could not be selected safely.')
    if ($nonGitNamed.Count -gt 0) {
        $lines.Add('')
        $lines.Add('Named project folders found, but they are not Git repositories:')
        foreach ($p0 in ($nonGitNamed | Select-Object -Unique | Select-Object -First 10)) {
            $lines.Add("  NON_GIT  $p0")
        }
    }
    if ($valid.Count -gt 0) {
        $lines.Add('')
        $lines.Add('Git repositories discovered:')
        foreach ($repo in ($valid | Select-Object -First 20)) {
            $remote = Get-RepoRemoteText -Path $repo
            $firstRemote = @($remote.Split([Environment]::NewLine) | Where-Object { $_ } | Select-Object -First 1)
            if ($firstRemote.Count -eq 0) { $firstRemote = @('(no remote)') }
            $lines.Add("  GIT      $repo")
            $lines.Add("           $($firstRemote[0])")
        }
    }
    $lines.Add('')
    $lines.Add('Re-run with -RepoPath only if a repository must be selected explicitly.')

    throw ($lines -join [Environment]::NewLine)
}

function Get-GitRelation {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Remote,
        [Parameter(Mandatory)][string]$Branch
    )

    $headProbe = Invoke-GitText -Path $Path -Arguments @('rev-parse', '--verify', 'HEAD') -AllowFailure
    $hasLocalHead = ($headProbe.Code -eq 0 -and [bool]$headProbe.Text.Trim())
    $head = if ($hasLocalHead) { $headProbe.Text.Trim() } else { '(unborn)' }

    # Metadata/object fetch only. No checkout, reset, clean, merge, rebase, or working-tree write.
    Invoke-GitText -Path $Path -Arguments @('fetch', '--no-tags', '--quiet', $Remote, $Branch) | Out-Null
    $canonical = (Invoke-GitText -Path $Path -Arguments @('rev-parse', 'FETCH_HEAD')).Text.Trim()

    if (-not $hasLocalHead) {
        return [pscustomobject]@{
            LocalHead = $head
            CanonicalHead = $canonical
            Relation = 'unborn'
            AheadBy = 0
            BehindBy = $null
        }
    }

    $relation = 'unrelated'
    if ($head -eq $canonical) {
        $relation = 'same'
    }
    else {
        $canonicalIsAncestor = Invoke-GitText -Path $Path -Arguments @('merge-base', '--is-ancestor', $canonical, $head) -AllowFailure
        $headIsAncestor = Invoke-GitText -Path $Path -Arguments @('merge-base', '--is-ancestor', $head, $canonical) -AllowFailure

        if ($canonicalIsAncestor.Code -eq 0) {
            $relation = 'ahead'
        }
        elseif ($headIsAncestor.Code -eq 0) {
            $relation = 'behind'
        }
        else {
            $mergeBase = Invoke-GitText -Path $Path -Arguments @('merge-base', $head, $canonical) -AllowFailure
            if ($mergeBase.Code -eq 0 -and $mergeBase.Text.Trim()) {
                $relation = 'diverged'
            }
        }
    }

    $counts = Invoke-GitText -Path $Path -Arguments @('rev-list', '--left-right', '--count', "$head...$canonical") -AllowFailure
    $aheadBy = $null
    $behindBy = $null
    if ($counts.Code -eq 0) {
        $parts = @($counts.Text.Trim() -split '\s+' | Where-Object { $_ })
        if ($parts.Count -eq 2) {
            $aheadBy = [int]$parts[0]
            $behindBy = [int]$parts[1]
        }
    }

    [pscustomobject]@{
        LocalHead = $head
        CanonicalHead = $canonical
        Relation = $relation
        AheadBy = $aheadBy
        BehindBy = $behindBy
    }
}

function Get-KeywordEvidence {
    param([Parameter(Mandatory)][string]$Path)

    # git grep cannot see untracked files and an unborn repository may contain only
    # untracked work. Scan likely source/document files directly, excluding bulky dirs.
    $matches = [System.Collections.Generic.List[string]]::new()
    $collect = [System.Collections.Generic.List[string]]::new()
    $allowedExtensions = @('.py', '.ps1', '.psm1', '.md', '.txt', '.json', '.toml', '.yml', '.yaml', '.sql', '.csv', '.tsv')

    try {
        Get-ChildItem -LiteralPath $Path -File -Recurse -Depth 8 -ErrorAction SilentlyContinue |
            Where-Object {
                $_.FullName -notmatch '[\\/](\.git|\.venv|venv|node_modules|data|artifacts|backups|\.pytest_cache|__pycache__)[\\/]' -and
                $allowedExtensions -contains $_.Extension.ToLowerInvariant()
            } |
            ForEach-Object {
                $file = $_
                $rel = $file.FullName.Substring($Path.Length).TrimStart('\', '/')
                if ($file.Name -eq 'collect_training.py') {
                    $collect.Add($rel)
                }
                try {
                    Select-String -LiteralPath $file.FullName -Pattern 'jockey-25', '3目標', '調教48' -SimpleMatch -ErrorAction SilentlyContinue |
                        Select-Object -First 20 |
                        ForEach-Object {
                            $matches.Add(('{0}:{1}:{2}' -f $rel, $_.LineNumber, $_.Line.Trim()))
                        }
                }
                catch {
                }
            }
    }
    catch {
        $matches.Add("SCAN_ERROR: $($_.Exception.Message)")
    }

    [pscustomobject]@{
        KeywordMatches = @($matches | Select-Object -First 200)
        CollectTrainingFiles = @($collect | Select-Object -Unique)
    }
}

function Write-SyncReport {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Remote,
        [Parameter(Mandatory)][string]$Branch,
        [AllowEmptyString()][string]$Destination = ''
    )

    $relation = Get-GitRelation -Path $Path -Remote $Remote -Branch $Branch
    $currentBranch = (Invoke-GitText -Path $Path -Arguments @('branch', '--show-current')).Text.Trim()
    if (-not $currentBranch) { $currentBranch = '(detached HEAD)' }

    $status = (Invoke-GitText -Path $Path -Arguments @('status', '--porcelain=v1', '--untracked-files=all')).Text
    $remotes = (Invoke-GitText -Path $Path -Arguments @('remote', '-v')).Text
    $origin = (Invoke-GitText -Path $Path -Arguments @('remote', 'get-url', 'origin') -AllowFailure).Text

    $statusLines = @($status -split "`n" | Where-Object { $_ })
    $untracked = @($statusLines | Where-Object { $_ -like '?? *' } | ForEach-Object { $_.Substring(3) })
    $trackedChanges = @($statusLines | Where-Object { $_ -notlike '?? *' })

    $evidence = Get-KeywordEvidence -Path $Path

    if ($relation.Relation -eq 'unborn') {
        $localOnlyLog = ''
        $canonicalOnlyLog = (Invoke-GitText -Path $Path -Arguments @(
            'log', '--oneline', '--decorate', '--max-count=30',
            $relation.CanonicalHead
        ) -AllowFailure).Text
    }
    else {
        $localOnlyLog = (Invoke-GitText -Path $Path -Arguments @(
            'log', '--oneline', '--decorate', '--max-count=30',
            "$($relation.CanonicalHead)..$($relation.LocalHead)"
        ) -AllowFailure).Text

        $canonicalOnlyLog = (Invoke-GitText -Path $Path -Arguments @(
            'log', '--oneline', '--decorate', '--max-count=30',
            "$($relation.LocalHead)..$($relation.CanonicalHead)"
        ) -AllowFailure).Text
    }

    $timestamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    if (-not $Destination) {
        $Destination = Join-Path ([IO.Path]::GetTempPath()) 'neo-jizo-sync-gate'
    }
    New-Item -ItemType Directory -Force -Path $Destination | Out-Null

    $jsonPath = Join-Path $Destination "SYNC-GATE-001-$timestamp.json"
    $mdPath = Join-Path $Destination "SYNC-GATE-001-$timestamp.md"

    $payload = [ordered]@{
        mission = 'SYNC-GATE-001'
        generated_at = (Get-Date).ToString('o')
        repo_path = $Path
        branch = $currentBranch
        local_head = $relation.LocalHead
        canonical_repo = $Remote
        canonical_branch = $Branch
        canonical_head = $relation.CanonicalHead
        relation = $relation.Relation
        ahead_by = $relation.AheadBy
        behind_by = $relation.BehindBy
        origin = (Redact-SensitiveText $origin)
        remotes = @((Redact-SensitiveText $remotes) -split "`n" | Where-Object { $_ })
        tracked_changes = $trackedChanges
        untracked_files = $untracked
        keyword_matches = $evidence.KeywordMatches
        collect_training_files = $evidence.CollectTrainingFiles
        local_only_commits = @($localOnlyLog -split "`n" | Where-Object { $_ })
        canonical_only_commits = @($canonicalOnlyLog -split "`n" | Where-Object { $_ })
    }

    $jsonPayload = [pscustomobject]@{
        mission = [string]$payload.mission
        generated_at = [string]$payload.generated_at
        repo_path = [string]$payload.repo_path
        branch = [string]$payload.branch
        local_head = [string]$payload.local_head
        canonical_repo = [string]$payload.canonical_repo
        canonical_branch = [string]$payload.canonical_branch
        canonical_head = [string]$payload.canonical_head
        relation = [string]$payload.relation
        ahead_by = $payload.ahead_by
        behind_by = $payload.behind_by
        origin = [string]$payload.origin
        remotes = [string[]]@($payload.remotes)
        tracked_changes = [string[]]@($payload.tracked_changes)
        untracked_files = [string[]]@($payload.untracked_files)
        keyword_matches = [string[]]@($payload.keyword_matches)
        collect_training_files = [string[]]@($payload.collect_training_files)
        local_only_commits = [string[]]@($payload.local_only_commits)
        canonical_only_commits = [string[]]@($payload.canonical_only_commits)
    }

    $jsonWritten = $false
    try {
        ConvertTo-Json -InputObject $jsonPayload -Depth 6 |
            Set-Content -LiteralPath $jsonPath -Encoding utf8
        $jsonWritten = $true
    }
    catch {
        # JSON is a convenience artifact. Do not abort the audit after the core
        # Git/file inspection succeeded; preserve the error in a text fallback.
        $jsonErrorPath = "$jsonPath.error.txt"
        ("JSON_WRITE_FAILED: " + $_.Exception.Message) |
            Set-Content -LiteralPath $jsonErrorPath -Encoding utf8
    }

    function LinesOrNone {
        param([object[]]$Lines)
        if (-not $Lines -or $Lines.Count -eq 0) { return @('- (none)') }
        return @($Lines | ForEach-Object { "- $_" })
    }

    $md = @(
        '# SYNC-GATE-001 Local Audit',
        '',
        "- Generated: $($payload.generated_at)",
        "- Repo: $Path",
        "- Branch: $currentBranch",
        "- Local HEAD: $($relation.LocalHead)",
        "- Canonical: $Remote#$Branch",
        "- Canonical HEAD: $($relation.CanonicalHead)",
        "- Relation: **$($relation.Relation)**",
        "- Ahead / Behind: $($relation.AheadBy) / $($relation.BehindBy)",
        '',
        '## Tracked changes',
        ''
    )
    $md += LinesOrNone $trackedChanges
    $md += @('', '## Untracked files', '')
    $md += LinesOrNone $untracked
    $md += @('', '## jockey-25 / 3目標 / 調教48 evidence', '')
    $md += LinesOrNone $evidence.KeywordMatches
    $md += @('', '## collect_training.py', '')
    $md += LinesOrNone $evidence.CollectTrainingFiles
    $md += @('', '## Local-only commits (max 30)', '')
    $md += LinesOrNone @($localOnlyLog -split "`n" | Where-Object { $_ })
    $md += @('', '## Canonical-only commits (max 30)', '')
    $md += LinesOrNone @($canonicalOnlyLog -split "`n" | Where-Object { $_ })
    $md += @(
        '',
        '## Safety',
        '',
        '- No checkout',
        '- No reset',
        '- No clean',
        '- No merge/rebase',
        '- No database access',
        '- No service stop',
        '- No file deletion',
        '- Only a Git fetch is used to obtain the canonical commit object; the working tree is not changed.'
    )

    $md -join "`n" | Set-Content -LiteralPath $mdPath -Encoding utf8

    [pscustomobject]@{
        Payload = $payload
        JsonPath = if ($jsonWritten) { $jsonPath } else { $null }
        MarkdownPath = $mdPath
    }
}

function Invoke-SelfTest {
    $gitVersion = & git --version
    if ($LASTEXITCODE -ne 0) { throw 'git is required for self-test.' }

    $root = Join-Path ([IO.Path]::GetTempPath()) "sync-gate-selftest-$([guid]::NewGuid().ToString('N'))"
    New-Item -ItemType Directory -Force -Path $root | Out-Null

    try {
        $canonical = Join-Path $root 'canonical'
        & git init -b main $canonical | Out-Null
        & git -C $canonical config user.email 'sync-gate@example.invalid'
        & git -C $canonical config user.name 'SYNC GATE SELFTEST'
        'A' | Set-Content -LiteralPath (Join-Path $canonical 'seed.txt') -Encoding utf8
        & git -C $canonical add seed.txt
        & git -C $canonical commit -m 'A' | Out-Null

        $same = Join-Path $root 'same'
        & git clone -q $canonical $same
        $safeProbe = Invoke-GitText -Path $same -Arguments @('rev-parse', 'HEAD')
        if ($safeProbe.Code -ne 0 -or -not $safeProbe.Text.Trim()) {
            throw 'Command-scoped safe.directory probe failed.'
        }
        $resolvedSame = Resolve-NeoJizoRepo -RequestedPath $same
        if ((Resolve-Path -LiteralPath $resolvedSame).Path -ne (Resolve-Path -LiteralPath $same).Path) {
            throw 'Explicit repository resolution failed.'
        }
        $rSame = Get-GitRelation -Path $same -Remote $canonical -Branch 'main'
        if ($rSame.Relation -ne 'same') { throw "Expected same, got $($rSame.Relation)" }

        $report = Write-SyncReport -Path $same -Remote $canonical -Branch 'main' -Destination ''
        if (-not $report.JsonPath -or -not (Test-Path -LiteralPath $report.JsonPath -PathType Leaf)) {
            throw 'Expected JSON report for empty Destination.'
        }
        $parsedReport = Get-Content -LiteralPath $report.JsonPath -Raw | ConvertFrom-Json
        if ($parsedReport.relation -ne 'same') {
            throw 'Expected JSON report relation=same.'
        }
        if (-not (Test-Path -LiteralPath $report.MarkdownPath -PathType Leaf)) {
            throw 'Expected Markdown report for empty Destination.'
        }

        $ahead = Join-Path $root 'ahead'
        & git clone -q $canonical $ahead
        & git -C $ahead config user.email 'sync-gate@example.invalid'
        & git -C $ahead config user.name 'SYNC GATE SELFTEST'
        'B' | Set-Content -LiteralPath (Join-Path $ahead 'local.txt') -Encoding utf8
        & git -C $ahead add local.txt
        & git -C $ahead commit -m 'B-local' | Out-Null
        $rAhead = Get-GitRelation -Path $ahead -Remote $canonical -Branch 'main'
        if ($rAhead.Relation -ne 'ahead') { throw "Expected ahead, got $($rAhead.Relation)" }

        'C' | Set-Content -LiteralPath (Join-Path $canonical 'canonical.txt') -Encoding utf8
        & git -C $canonical add canonical.txt
        & git -C $canonical commit -m 'C-canonical' | Out-Null

        $rBehind = Get-GitRelation -Path $same -Remote $canonical -Branch 'main'
        if ($rBehind.Relation -ne 'behind') { throw "Expected behind, got $($rBehind.Relation)" }

        $rDiverged = Get-GitRelation -Path $ahead -Remote $canonical -Branch 'main'
        if ($rDiverged.Relation -ne 'diverged') { throw "Expected diverged, got $($rDiverged.Relation)" }

        $unrelated = Join-Path $root 'unrelated'
        & git init -b main $unrelated | Out-Null
        & git -C $unrelated config user.email 'sync-gate@example.invalid'
        & git -C $unrelated config user.name 'SYNC GATE SELFTEST'
        'X' | Set-Content -LiteralPath (Join-Path $unrelated 'x.txt') -Encoding utf8
        & git -C $unrelated add x.txt
        & git -C $unrelated commit -m 'X' | Out-Null
        $rUnrelated = Get-GitRelation -Path $unrelated -Remote $canonical -Branch 'main'
        if ($rUnrelated.Relation -ne 'unrelated') { throw "Expected unrelated, got $($rUnrelated.Relation)" }

        $unborn = Join-Path $root 'unborn'
        & git init -b main $unborn | Out-Null
        'jockey-25 3目標 調教48' | Set-Content -LiteralPath (Join-Path $unborn 'notes.md') -Encoding utf8
        New-Item -ItemType Directory -Force -Path (Join-Path $unborn 'src') | Out-Null
        '# test' | Set-Content -LiteralPath (Join-Path $unborn 'src/collect_training.py') -Encoding utf8
        $rUnborn = Get-GitRelation -Path $unborn -Remote $canonical -Branch 'main'
        if ($rUnborn.Relation -ne 'unborn') { throw "Expected unborn, got $($rUnborn.Relation)" }
        $eUnborn = Get-KeywordEvidence -Path $unborn
        if ($eUnborn.KeywordMatches.Count -lt 1) { throw 'Expected keyword evidence in unborn repo.' }
        if ($eUnborn.CollectTrainingFiles.Count -ne 1) { throw 'Expected collect_training.py in unborn repo.' }

        Write-Host "SYNC-GATE-001 self-test PASS ($gitVersion)"
        Write-Host 'same / ahead / behind / diverged / unrelated / unborn: PASS'
    }
    finally {
        Remove-Item -LiteralPath $root -Recurse -Force -ErrorAction SilentlyContinue
    }
}

if ($SelfTest) {
    Invoke-SelfTest
    exit 0
}

$resolvedRepo = Resolve-NeoJizoRepo -RequestedPath $RepoPath
$result = Write-SyncReport -Path $resolvedRepo -Remote $CanonicalRepo -Branch $CanonicalBranch -Destination $OutputDir

Write-Host ''
Write-Host '============================================================' -ForegroundColor Cyan
Write-Host ' SYNC-GATE-001 COMPLETE' -ForegroundColor Cyan
Write-Host '============================================================' -ForegroundColor Cyan
Write-Host "Repo           : $resolvedRepo"
Write-Host "Relation       : $($result.Payload.relation)"
Write-Host "Local HEAD     : $($result.Payload.local_head)"
Write-Host "Canonical HEAD : $($result.Payload.canonical_head)"
Write-Host "Ahead / Behind : $($result.Payload.ahead_by) / $($result.Payload.behind_by)"
Write-Host "Tracked changes: $($result.Payload.tracked_changes.Count)"
Write-Host "Untracked files: $($result.Payload.untracked_files.Count)"
Write-Host "Keyword hits   : $($result.Payload.keyword_matches.Count)"
Write-Host "collect_training.py: $($result.Payload.collect_training_files.Count)"
Write-Host ''
Write-Host "Markdown report: $($result.MarkdownPath)"
Write-Host "JSON report    : $(if ($result.JsonPath) { $result.JsonPath } else { '(not written; Markdown report is authoritative)' })"
Write-Host ''
Write-Host 'No checkout/reset/clean/merge/rebase/DB access/service stop/file deletion was performed.' -ForegroundColor Green
