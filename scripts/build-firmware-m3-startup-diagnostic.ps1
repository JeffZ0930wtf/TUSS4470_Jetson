# Builds a temporary no-acquisition M3 image used only to isolate USB startup
# failures. It retains M3 RAM/main-loop changes but has no timer/DMA/Burst ISR.
$ErrorActionPreference = 'Stop'

& (Join-Path $PSScriptRoot 'build-firmware-m2.ps1') -M3StartupDiagnostic
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
