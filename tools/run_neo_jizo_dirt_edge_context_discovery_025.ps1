[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$Commit = '640611f9e2c9f7477360aa489d785ac05f9bbbac'
$Url = "https://raw.githubusercontent.com/umanari1919/umanari-keiba/$Commit/tools/neo_jizo_dirt_edge_context_discovery_025.py"
$Dir = Join-Path $env:TEMP 'JIZO\NEO-JIZO-DIRT-EDGE-025'
$Py = Join-Path $Dir 'neo_jizo_dirt_edge_context_discovery_025.py'

New-Item -ItemType Directory -Force -Path $Dir | Out-Null
Invoke-RestMethod $Url -OutFile $Py

$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    throw 'python command was not found.'
}

& $python.Source $Py --host 127.0.0.1 --port 5433 --db mykeibadb
if ($LASTEXITCODE -ne 0) {
    throw "NEO-JIZO-DIRT-EDGE-025 discovery failed with exit code $LASTEXITCODE"
}
