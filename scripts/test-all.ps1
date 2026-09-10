# Windows aggregate gate: host tests, web tests, the production firmware build,
# MCU simulator tests, and retained static hardware-safety audits. It never
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

node (Join-Path $repositoryRoot 'packages\usac_runtime\tests\test_web_app.cjs')
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& (Join-Path $PSScriptRoot 'build-firmware.ps1')
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& (Join-Path $PSScriptRoot 'test-firmware-unit.ps1')
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& (Join-Path $PSScriptRoot 'test-ti-usb-stack-build.ps1')
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& (Join-Path $PSScriptRoot 'test-firmware-safety.ps1')
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& (Join-Path $PSScriptRoot 'test-firmware-loopback-safety.ps1')
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& (Join-Path $PSScriptRoot 'test-firmware-acquisition-static.ps1')
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& (Join-Path $PSScriptRoot 'test-firmware-timer-ownership.ps1')
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& (Join-Path $PSScriptRoot 'test-firmware-burst-plan.ps1')
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& (Join-Path $PSScriptRoot 'test-firmware-capture-schedule.ps1')
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& (Join-Path $PSScriptRoot 'test-firmware-app.ps1')
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
