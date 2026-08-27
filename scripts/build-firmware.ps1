# Compiles the M0 reset-safe skeleton only. This script never invokes a flash
# utility and resolves the official MSP430 toolchain from environment or .tools.
$ErrorActionPreference = 'Stop'

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$localCompilerRoot = Join-Path $repositoryRoot '.tools\msp430-gcc\msp430-gcc-9.3.1.11_win64'
$localSupportRoot = Join-Path $repositoryRoot '.tools\msp430-support\msp430-gcc-support-files'
$compilerRoot = if ($env:MSP430_GCC_ROOT) { $env:MSP430_GCC_ROOT } else { $localCompilerRoot }
$supportRoot = if ($env:MSP430_SUPPORT_ROOT) { $env:MSP430_SUPPORT_ROOT } else { $localSupportRoot }
$compiler = Join-Path $compilerRoot 'bin\msp430-elf-gcc.exe'
$sizeTool = Join-Path $compilerRoot 'bin\msp430-elf-size.exe'
$supportInclude = Join-Path $supportRoot 'include'

foreach ($requiredPath in @($compiler, $sizeTool, (Join-Path $supportInclude 'msp430.h'))) {
    if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
        throw "required MSP430 toolchain file is missing: $requiredPath"
    }
}

$buildDirectory = Join-Path $repositoryRoot 'firmware\build'
$source = Join-Path $repositoryRoot 'firmware\src\main.c'
$output = Join-Path $buildDirectory 'm0-safe.elf'
New-Item -ItemType Directory -Force -Path $buildDirectory | Out-Null

$arguments = @(
    "-I$supportInclude",
    "-L$supportInclude",
    '-mmcu=msp430f5529',
    '-Os',
    '-std=c11',
    '-Wall',
    '-Wextra',
    '-Werror',
    $source,
    '-o',
    $output
)

& $compiler @arguments
if ($LASTEXITCODE -ne 0) {
    throw "MSP430 firmware build failed with exit code $LASTEXITCODE"
}

& $sizeTool $output
if ($LASTEXITCODE -ne 0) {
    throw "msp430-elf-size failed with exit code $LASTEXITCODE"
}

Write-Host "Safe M0 firmware compiled without flashing: $output"
