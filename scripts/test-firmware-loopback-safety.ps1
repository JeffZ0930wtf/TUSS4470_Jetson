# Static safety gate for the production loopback path. It proves that the
# linked path uses pin38/TA0CCR4, has a finite timeout, and restores
# IO2 high; physical loopback behavior is verified only after flashing.
$ErrorActionPreference = 'Stop'

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$platformPath = Join-Path $repositoryRoot 'firmware\src\usac_acquisition_platform_msp430.c'
$mainPath = Join-Path $repositoryRoot 'firmware\src\main.c'
$elf = Join-Path $repositoryRoot 'firmware\build\release\tuss4470-acquisition-fw-0.2.0.2.elf'

foreach ($required in @($platformPath, $mainPath, $elf)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "firmware loopback safety input is missing: $required"
    }
}

$platform = Get-Content -Raw -LiteralPath $platformPath
$main = Get-Content -Raw -LiteralPath $mainPath
$requiredPatterns = @(
    @{ Pattern = 'P1DIR\s*&=\s*\(uint8_t\)~LOOPBACK_CAPTURE_BIT'; Label = 'pin38 remains input' },
    @{ Pattern = 'P1REN\s*&=\s*\(uint8_t\)~LOOPBACK_CAPTURE_BIT'; Label = 'pin38 pull resistor disabled' },
    @{ Pattern = 'TA0CCTL4\s*=\s*CM_2\s*\|\s*CCIS_0\s*\|\s*SCS\s*\|\s*CAP'; Label = 'TA0CCR4 falling-edge capture' },
    @{ Pattern = '#define\s+LOOPBACK_TIMEOUT_TICKS\s+2400u'; Label = '100 us SMCLK timeout' },
    @{ Pattern = 'index\s*<\s*USAC_LOOPBACK_EDGE_COUNT'; Label = 'finite eight-edge loop' },
    @{ Pattern = 'while\s*\(\(TA0CCTL4\s*&\s*CCIFG\)\s*==\s*0u\)[\s\S]*?TA0CCTL4\s*&=\s*\(uint16_t\)~\(CCIFG\s*\|\s*COV\);[\s\S]*?for\s*\(index\s*=\s*0u'; Label = 'one startup edge discarded before eight evidence edges' },
    @{ Pattern = 'TA2CTL\s*=\s*TACLR;[\s\S]*?P2SEL\s*&=[\s\S]*?P2OUT\s*\|=\s*TUSS_IO2_BIT'; Label = 'timer stop and GPIO-high restore' },
    @{ Pattern = 'tuss4470_force_safe\(bus\)[\s\S]*?read_safety_snapshot'; Label = 'pre-test Standby/Hi-Z gate' },
    @{ Pattern = 'restore_io2_high_and_stop_timers\(\);[\s\S]*?tuss4470_force_safe\(bus\)'; Label = 'post-test safe closure' }
)
foreach ($check in $requiredPatterns) {
    if ($platform -notmatch $check.Pattern) {
        throw "firmware loopback safety invariant missing: $($check.Label)"
    }
}
$captureArm = $platform.IndexOf('TA0CCTL4 = CM_2 | CCIS_0 | SCS | CAP;')
$startTickRead = $platform.IndexOf('start_tick = TA0R;', $captureArm)
$preStartFlagClear = $platform.IndexOf(
    'TA0CCTL4 &= (uint16_t)~(CCIFG | COV);', $captureArm)
if (($captureArm -lt 0) -or ($startTickRead -lt 0) -or
    ($preStartFlagClear -lt 0) -or ($preStartFlagClear -gt $startTickRead)) {
    throw 'loopback must clear stale TA0CCR4 flags after arming capture and before starting evidence timing'
}
$settlingStart = $platform.IndexOf('Switching a pin from GPIO to OUTMOD_7')
$evidenceLoop = $platform.IndexOf(
    'for (index = 0u; index < USAC_LOOPBACK_EDGE_COUNT;', $settlingStart)
if (($settlingStart -lt 0) -or ($evidenceLoop -lt 0)) {
    throw 'loopback settling/evidence phase boundary is missing'
}
$settlingBlock = $platform.Substring($settlingStart, $evidenceLoop - $settlingStart)
if ($settlingBlock -match 'USAC_LOOPBACK_COV_SEEN') {
    throw 'COV from the explicitly discarded startup phase must not contaminate evidence flags'
}
if ($settlingBlock -notmatch 'TA0CCR4') {
    throw 'discarded startup capture must read TA0CCR4 before the next capture'
}
if ($platform -match 'P2OUT\s*&=\s*[^;]*TUSS_IO2_BIT') {
    throw 'loopback must not drive IO2 low through a GPIO write'
}
if ($main -notmatch '#ifdef\s+USAC_ENABLE_LOOPBACK[\s\S]*?run_io2_loopback\s*=\s*usac_platform_run_io2_loopback') {
    throw 'loopback callback is not isolated behind its compile-time gate'
}

Write-Host 'Firmware loopback static safety audit: PASS (no flashing)'
