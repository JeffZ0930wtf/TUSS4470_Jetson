# Runs only the lease scheduler in the MSP430 simulator. Keeping this test
# small makes the safety gate deterministic and avoids involving USB/hardware.
$ErrorActionPreference = 'Stop'

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$compilerRoot = Join-Path $repositoryRoot '.tools\msp430-gcc\msp430-gcc-9.3.1.11_win64'
$supportRoot = Join-Path $repositoryRoot '.tools\msp430-support\msp430-gcc-support-files'
$compiler = Join-Path $compilerRoot 'bin\msp430-elf-gcc.exe'
$debugger = Join-Path $compilerRoot 'bin\msp430-elf-gdb.exe'
$buildDirectory = Join-Path $repositoryRoot 'firmware\build\tests'
$testBinary = Join-Path $buildDirectory 'test_capture_schedule.elf'

New-Item -ItemType Directory -Force -Path $buildDirectory | Out-Null
& $compiler `
    "-I$(Join-Path $repositoryRoot 'firmware\include')" `
    "-I$(Join-Path $supportRoot 'include')" `
    "-L$(Join-Path $supportRoot 'include')" `
    '-mmcu=msp430f5529' '-std=c11' '-g' '-Wall' '-Wextra' '-Werror' `
    (Join-Path $repositoryRoot 'firmware\tests\test_capture_schedule.c') `
    (Join-Path $repositoryRoot 'firmware\src\usac_capture_schedule.c') `
    '-o' $testBinary
if ($LASTEXITCODE -ne 0) { throw "capture scheduler compile failed: $LASTEXITCODE" }

$gdbScript = Join-Path $repositoryRoot 'firmware\tests\msp430-sim-test.gdb'
$savedErrorPreference = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
$testOutput = (& $debugger '-batch' '-x' $gdbScript $testBinary 2>&1) -join "`n"
$gdbExitCode = $LASTEXITCODE
$ErrorActionPreference = $savedErrorPreference
if ($gdbExitCode -ne 0) { throw "capture scheduler debugger failed: $gdbExitCode`n$testOutput" }
if ($testOutput -notmatch 'USAC_TEST_RESULT=(-?\d+)') {
    throw "capture scheduler did not report a result`n$testOutput"
}
if ([int]$Matches[1] -ne 0) {
    throw "capture scheduler failed at source line $($Matches[1])`n$testOutput"
}
Write-Host 'Firmware periodic lease scheduler: PASS'
