# Windows aggregate gate: host tests, M0 compile, MCU simulator, official USB
# stack compile, M2 link/no-Burst audit, and M3 compile/static audits. It never
# opens a COM port, flashes firmware, or starts a Burst.
$ErrorActionPreference = 'Stop'

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$expectedEnvironment = (Resolve-Path (Join-Path $repositoryRoot '.venv')).Path
if (-not $env:VIRTUAL_ENV -or $env:VIRTUAL_ENV -ne $expectedEnvironment) {
    throw "activate the repository .venv first: . .\.venv\Scripts\Activate.ps1"
}

# Keep pytest temporary files on an ASCII-safe repository path. This avoids
# Windows PowerShell/Python code-page corruption when the user profile contains
# non-ASCII characters, while keeping all generated data under ignored build/.
$pytestBaseTemp = Join-Path $repositoryRoot "firmware\build\pytest-$PID"
$pytestParent = Split-Path -Parent $pytestBaseTemp
New-Item -ItemType Directory -Path $pytestParent -Force | Out-Null
& (Join-Path $expectedEnvironment 'Scripts\python.exe') -m pytest --basetemp $pytestBaseTemp
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
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& (Join-Path $PSScriptRoot 'build-firmware-m3.ps1')
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& (Join-Path $PSScriptRoot 'test-m3-loopback-safety.ps1')
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& (Join-Path $PSScriptRoot 'test-m3-acquisition-static.ps1')
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& (Join-Path $PSScriptRoot 'build-firmware-m3-adc-dma-diagnostic.ps1')
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& (Join-Path $PSScriptRoot 'test-m3-adc-dma-diagnostic-static.ps1')
