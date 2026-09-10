# Static reset-safe gate for the production image. It checks the base platform
# and protocol core that remain active before acquisition is authorized.
$ErrorActionPreference = 'Stop'

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$mainSource = Join-Path $repositoryRoot 'firmware\src\main.c'
$platformSource = Join-Path $repositoryRoot 'firmware\src\usac_platform_msp430.c'
$coreSource = Join-Path $repositoryRoot 'firmware\src\usac_firmware_core.c'
$appSource = Join-Path $repositoryRoot 'firmware\src\usac_firmware_app.c'
$elf = Join-Path $repositoryRoot 'firmware\build\release\tuss4470-acquisition-fw-0.2.0.2.elf'
$compilerRoot = Join-Path $repositoryRoot '.tools\msp430-gcc\msp430-gcc-9.3.1.11_win64'
$sizeTool = Join-Path $compilerRoot 'bin\msp430-elf-size.exe'

foreach ($required in @($mainSource, $platformSource, $coreSource, $appSource, $elf, $sizeTool)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "firmware safety input is missing: $required"
    }
}

$main = Get-Content -Raw -LiteralPath $mainSource
$platform = Get-Content -Raw -LiteralPath $platformSource
$core = Get-Content -Raw -LiteralPath $coreSource
$app = Get-Content -Raw -LiteralPath $appSource

$requiredPatterns = @(
    @{ Text = $main; Pattern = '#define\s+USAC_USB_DETACH_CYCLES\s+14400000ul'; Label = '600 ms USB detach at 24 MHz' },
    @{ Text = $main; Pattern = 'UCS_initFLLSettle\(24000u,\s*6u\)'; Label = '24 MHz XT2-referenced FLL ratio' },
    @{ Text = $main; Pattern = 'UCS_XT2CLK_SELECT'; Label = 'XT2 FLL reference' },
    @{ Text = $main; Pattern = 'GPIO_setAsPeripheralModuleFunctionOutputPin\([\s\S]*?GPIO_PORT_P5,[\s\S]*?GPIO_PIN2\s*\|\s*GPIO_PIN3\)[\s\S]*?UCS_turnOnXT2WithTimeout'; Label = 'XT2 pins mapped before oscillator start' },
    @{ Text = $main; Pattern = 'usac_firmware_clock_faults_safe\(\(uint8_t\)UCSCTL7\)'; Label = 'DCO and XT2 clock fault gate' },
    @{ Text = $platform; Pattern = 'P2OUT\s*\|=\s*\(TUSS_IO2_BIT\s*\|\s*TUSS_NCS_BIT\)'; Label = 'IO2/NCS latch high before direction' },
    @{ Text = $platform; Pattern = 'TA2CTL\s*=\s*TACLR'; Label = 'Burst timer stopped' },
    @{ Text = $platform; Pattern = 'UCB0BR0\s*=\s*24u'; Label = '1 MHz SPI divider at 24 MHz SMCLK' },
    @{ Text = $platform; Pattern = 'UCB0BR1\s*=\s*0u'; Label = 'SPI divider high byte zero' },
    @{ Text = $platform; Pattern = 'TB0CTL\s*=\s*TBCLR'; Label = 'ADC timer stopped' },
    @{ Text = $core; Pattern = 'uint8_t\s+usac_firmware_core_burst_permitted[\s\S]*?return\s+0u;'; Label = 'base-core compile-time Burst denial' },
    @{ Text = $app; Pattern = 'USAC_MESSAGE_CAPTURE_ONCE[\s\S]*?USAC_ERROR_INVALID_STATE'; Label = 'CAPTURE_ONCE rejected without acquisition support' }
)
foreach ($check in $requiredPatterns) {
    if ($check.Text -notmatch $check.Pattern) {
        throw "firmware safety invariant missing: $($check.Label)"
    }
}

if ($platform -match 'P2OUT\s*&=\s*[^;]*TUSS_IO2_BIT') {
    throw 'firmware safety violation: base platform contains an IO2 low-going GPIO write'
}
if ($platform -match 'P2SEL\s*\|=\s*[^;]*TUSS_IO2_BIT') {
    throw 'firmware safety violation: base platform connects IO2 to a timer peripheral'
}
if ($main -match 'TA2CTL\s*=\s*[^;]*(MC_1|MC_2|MC_3)') {
    throw 'firmware safety violation: main starts the Burst timer directly'
}

$sizeOutput = (& $sizeTool $elf 2>&1) -join "`n"
if ($LASTEXITCODE -ne 0) {
    throw "unable to inspect firmware image size`n$sizeOutput"
}
$sizeLine = ($sizeOutput -split "`r?`n" | Where-Object { $_ -match '^\s*\d+\s+\d+\s+\d+' } | Select-Object -Last 1)
if (-not $sizeLine -or $sizeLine -notmatch '^\s*(\d+)\s+(\d+)\s+(\d+)') {
    throw "unable to parse firmware image size`n$sizeOutput"
}
$textBytes = [int]$Matches[1]
$dataBytes = [int]$Matches[2]
$bssBytes = [int]$Matches[3]
$ramBytes = $dataBytes + $bssBytes
if ($textBytes -gt 120000) { throw "firmware image text exceeds guard limit: $textBytes B" }
if ($ramBytes -gt 7168) { throw "firmware static RAM exceeds guard limit: $ramBytes B" }

Write-Host "Firmware reset-safe audit: PASS (text=$textBytes B, static_ram=$ramBytes B)"
