# Builds the M3 acceptance image with finite IO2 loopback and one-shot capture.
# This script compiles only; flashing and Burst remain separate user gates.
$ErrorActionPreference = 'Stop'

& (Join-Path $PSScriptRoot 'build-firmware-m2.ps1') -EnableM3Loopback
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
