# Compiles pure first-party firmware logic for the MSP430 simulator and uses a
# scripted GDB completion breakpoint; it does not connect to physical hardware.
$ErrorActionPreference = 'Stop'

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$compilerRoot = Join-Path $repositoryRoot '.tools\msp430-gcc\msp430-gcc-9.3.1.11_win64'
$supportRoot = Join-Path $repositoryRoot '.tools\msp430-support\msp430-gcc-support-files'
$compiler = Join-Path $compilerRoot 'bin\msp430-elf-gcc.exe'
$debugger = Join-Path $compilerRoot 'bin\msp430-elf-gdb.exe'
$buildDirectory = Join-Path $repositoryRoot 'firmware\build\tests'
$testBinary = Join-Path $buildDirectory 'test_m2_core.elf'

New-Item -ItemType Directory -Force -Path $buildDirectory | Out-Null

& $compiler `
    "-I$(Join-Path $repositoryRoot 'firmware\include')" `
    "-I$(Join-Path $supportRoot 'include')" `
    "-L$(Join-Path $supportRoot 'include')" `
    '-mmcu=msp430f5529' `
    '-std=c11' `
    '-g' `
    '-Wall' `
    '-Wextra' `
    '-Werror' `
    (Join-Path $repositoryRoot 'firmware\tests\test_m2_core.c') `
    (Join-Path $repositoryRoot 'firmware\src\usac_m2_core.c') `
    (Join-Path $repositoryRoot 'firmware\src\tuss4470_profile.c') `
    (Join-Path $repositoryRoot 'firmware\src\tuss4470_configurator.c') `
    (Join-Path $repositoryRoot 'firmware\src\usac_platform_msp430.c') `
    (Join-Path $repositoryRoot 'firmware\src\usac_mcu_protocol.c') `
    (Join-Path $repositoryRoot 'firmware\src\usac_identity.c') `
    (Join-Path $repositoryRoot 'firmware\src\usac_sha256.c') `
    (Join-Path $repositoryRoot 'firmware\src\usac_config_v2.c') `
    (Join-Path $repositoryRoot 'firmware\src\usac_m2_app.c') `
    (Join-Path $repositoryRoot 'firmware\src\usac_dtr_gate.c') `
    (Join-Path $repositoryRoot 'firmware\src\usac_tx_gate.c') `
    '-o' $testBinary
if ($LASTEXITCODE -ne 0) { throw "firmware unit-test compile failed: $LASTEXITCODE" }

$gdbScript = Join-Path $repositoryRoot 'firmware\tests\msp430-sim-test.gdb'
$testOutput = (& $debugger '-batch' '-x' $gdbScript $testBinary 2>&1) -join "`n"
if ($LASTEXITCODE -ne 0) { throw "firmware simulator debugger failed: $LASTEXITCODE`n$testOutput" }
if ($testOutput -notmatch 'USAC_TEST_RESULT=(-?\d+)') {
    throw "firmware simulator did not report a test result`n$testOutput"
}
$testResult = [int]$Matches[1]
if ($testResult -ne 0) {
    throw "firmware unit test failed at source line $testResult`n$testOutput"
}

Write-Host 'MSP430 simulator unit tests: PASS'
