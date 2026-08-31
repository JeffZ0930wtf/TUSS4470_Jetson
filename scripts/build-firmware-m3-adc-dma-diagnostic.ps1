# Builds the one-time software-triggered ADC/DMA diagnostic. Its capture path
# never configures Timer_B or IO2, so it cannot generate an ultrasonic Burst.
$ErrorActionPreference = 'Stop'

& (Join-Path $PSScriptRoot 'build-firmware-m2.ps1') -M3AdcDmaDiagnostic
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
