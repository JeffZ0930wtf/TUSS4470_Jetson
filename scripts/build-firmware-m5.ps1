# Builds the M5 first-version image but never invokes TI DSLite or a serial port.
$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot 'build-firmware-m2.ps1') -EnableM5
