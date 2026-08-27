$ErrorActionPreference = 'Stop'

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$expectedEnvironment = (Resolve-Path (Join-Path $repositoryRoot '.venv')).Path
if (-not $env:VIRTUAL_ENV -or $env:VIRTUAL_ENV -ne $expectedEnvironment) {
    throw "activate the repository .venv first: . .\.venv\Scripts\Activate.ps1"
}

& (Join-Path $expectedEnvironment 'Scripts\python.exe') -m pytest
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& (Join-Path $PSScriptRoot 'build-firmware.ps1')
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& (Join-Path $PSScriptRoot 'test-firmware-unit.ps1')
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& (Join-Path $PSScriptRoot 'test-ti-usb-stack-build.ps1')
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& (Join-Path $PSScriptRoot 'build-firmware-m2.ps1')
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& (Join-Path $PSScriptRoot 'test-m2-safety.ps1')
