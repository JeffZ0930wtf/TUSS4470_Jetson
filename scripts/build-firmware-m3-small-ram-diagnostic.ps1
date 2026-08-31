# Builds a no-acquisition M3 image with a one-word placeholder waveform. It is
# used only to distinguish startup RAM pressure from M3 main-loop behavior.
$ErrorActionPreference = 'Stop'

& (Join-Path $PSScriptRoot 'build-firmware-m2.ps1') -M3SmallRamDiagnostic
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
