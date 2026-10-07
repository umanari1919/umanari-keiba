[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# This launcher never attempts a PostgreSQL connection.
# It only reads the existing CORE-010 CSV and split sidecars.
$Commit = '01bbe1b74b7e0cc7b0b99802d9387d17bebf0ba5'
$Url = "https://raw.githubusercontent.com/umanari1919/umanari-keiba/$Commit/tools/neo_jizo_core010_offline_evaluation_025.py"
$Dir = Join-Path $env:TEMP 'JIZO\NEO-JIZO-DIRT-EDGE-025'
$Py = Join-Path $Dir 'neo_jizo_core010_offline_evaluation_025.py'

New-Item -ItemType Directory -Force -Path $Dir | Out-Null
Invoke-RestMethod $Url -OutFile $Py

$Python = Get-Command python -ErrorAction Stop
& $Python.Source $Py
if ($LASTEXITCODE -ne 0) {
    throw "NEO JIZO CORE-010 offline evaluation stopped with exit code $LASTEXITCODE."
}
