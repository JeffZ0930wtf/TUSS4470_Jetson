# Compiles and runs M5 command/lease semantics in the MSP430 simulator only.
$ErrorActionPreference = 'Stop'

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$compilerRoot = Join-Path $repositoryRoot '.tools\msp430-gcc\msp430-gcc-9.3.1.11_win64'
$supportRoot = Join-Path $repositoryRoot '.tools\msp430-support\msp430-gcc-support-files'
$compiler = Join-Path $compilerRoot 'bin\msp430-elf-gcc.exe'
$debugger = Join-Path $compilerRoot 'bin\msp430-elf-gdb.exe'
$buildDirectory = Join-Path $repositoryRoot 'firmware\build\tests'
$testBinary = Join-Path $buildDirectory 'test_m5_app.elf'

New-Item -ItemType Directory -Force -Path $buildDirectory | Out-Null
$sources = @(
    'firmware/tests/test_firmware_app.c',
    'firmware/src/usac_firmware_app.c',
    'firmware/src/usac_firmware_core.c',
    'firmware/src/usac_capture_schedule.c',
    'firmware/src/usac_mcu_protocol.c',
    'firmware/src/usac_config_v2.c',
    'firmware/src/usac_sha256.c',
    'firmware/src/usac_identity.c',
    'firmware/src/tuss4470_profile.c',
    'firmware/src/tuss4470_configurator.c',
    'firmware/src/usac_loopback.c',
    'firmware/src/usac_capture.c'
    'firmware/src/usac_capture_stream.c'
) | ForEach-Object { Join-Path $repositoryRoot $_ }
& $compiler `
    "-I$(Join-Path $repositoryRoot 'firmware\include')" `
    "-I$(Join-Path $supportRoot 'include')" `
    "-L$(Join-Path $supportRoot 'include')" `
    '-DUSAC_ENABLE_ACQUISITION' '-mmcu=msp430f5529' '-std=c11' '-g' `
    '-Wall' '-Wextra' '-Werror' @sources '-o' $testBinary
if ($LASTEXITCODE -ne 0) { throw "M5 app compile failed: $LASTEXITCODE" }

$gdbScript = Join-Path $repositoryRoot 'firmware\tests\msp430-sim-test.gdb'
$savedErrorPreference = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
$testOutput = (& $debugger '-batch' '-x' $gdbScript $testBinary 2>&1) -join "`n"
$gdbExitCode = $LASTEXITCODE
$ErrorActionPreference = $savedErrorPreference
if ($gdbExitCode -ne 0) { throw "M5 app debugger failed: $gdbExitCode`n$testOutput" }
if ($testOutput -notmatch 'USAC_TEST_RESULT=(-?\d+)') {
    throw "M5 app did not report a result`n$testOutput"
}
if ([int]$Matches[1] -ne 0) {
    throw "M5 app failed at source line $($Matches[1])`n$testOutput"
}
Write-Host 'M5 command and lease application: PASS'
