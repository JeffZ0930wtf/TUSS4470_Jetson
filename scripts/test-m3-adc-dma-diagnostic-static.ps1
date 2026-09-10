# Static safety gate for the one-time no-Burst ADC/DMA diagnostic image.
$ErrorActionPreference = 'Stop'

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$buildScript = Get-Content -Raw -LiteralPath (Join-Path $PSScriptRoot 'build-firmware-m2.ps1')
$platform = Get-Content -Raw -LiteralPath (Join-Path $repositoryRoot 'firmware\src\usac_acquisition_platform_msp430.c')
$flashPath = Join-Path $PSScriptRoot 'flash-firmware-m3-adc-dma-diagnostic.ps1'
$elfPath = Join-Path $repositoryRoot 'firmware\build\m3-adc-dma-diagnostic\usac-m3-adc-dma-diagnostic-no-burst.elf'

$checks = @(
    @{ Text = $buildScript; Pattern = '\[switch\]\$M3AdcDmaDiagnostic'; Label = 'dedicated build switch' },
    @{ Text = $buildScript; Pattern = 'USAC_ADC_DMA_DIAGNOSTIC'; Label = 'diagnostic compile definition' },
    @{ Text = $platform; Pattern = '#ifdef\s+USAC_ADC_DMA_DIAGNOSTIC'; Label = 'compile-time isolation' },
    @{ Text = $platform; Pattern = 'ADC12SHS_0'; Label = 'software ADC trigger source' },
    @{ Text = $platform; Pattern = 'ADC12CONSEQ_0'; Label = 'single-conversion diagnostic mode' },
    @{ Text = $platform; Pattern = 'ADC12ENC\s*\|\s*ADC12SC'; Label = 'explicit diagnostic conversion start' },
    @{ Text = $platform; Pattern = 'ADC12IFG\s*&\s*ADC12IFG0'; Label = 'direct ADC completion polling' },
    @{ Text = $platform; Pattern = 'DMACTL0\s*=\s*DMA0TSEL_0'; Label = 'software-request DMA trigger selection' },
    @{ Text = $platform; Pattern = 'DMA0SZ\s*=\s*1u'; Label = 'one-word DMA diagnostic transfer' },
    @{ Text = $platform; Pattern = 'DMA0CTL\s*\|=\s*DMAREQ'; Label = 'explicit DMA software request' },
    @{ Text = $platform; Pattern = 'DMA0CTL\s*&\s*DMAIFG'; Label = 'DMA completion polling' },
    @{ Text = $platform; Pattern = 'report->captured_samples\s*=\s*dma_completed'; Label = 'DMA completion evidence' },
    @{ Text = $platform; Pattern = 'report->dma_remaining\s*=\s*g_usac_capture_waveform\[0\]'; Label = 'DMA target value evidence' }
)
foreach ($check in $checks) {
    if ($check.Text -notmatch $check.Pattern) {
        throw "M3 ADC/DMA diagnostic invariant missing: $($check.Label)"
    }
}

$diagnosticBranch = [regex]::Match(
    $platform,
    '#ifdef\s+USAC_ADC_DMA_DIAGNOSTIC(?<body>[\s\S]*?)#else').Groups['body'].Value
if ([string]::IsNullOrWhiteSpace($diagnosticBranch)) {
    throw 'unable to isolate M3 ADC/DMA diagnostic branch'
}
if ($diagnosticBranch -match '\bTB0' -or
    $diagnosticBranch -match '\bTA2' -or
    $diagnosticBranch -match 'P2SEL' -or
    $diagnosticBranch -match '\bDMA[12]') {
    throw 'DMAREQ diagnostic branch configures a timer, IO2, or a second DMA channel'
}
if ($diagnosticBranch -match 'DMA0SZ\s*==\s*0u') {
    throw 'DMAREQ diagnostic incorrectly expects DMA0SZ to remain zero after completion'
}
if (-not (Test-Path -LiteralPath $flashPath -PathType Leaf)) {
    throw 'dedicated ADC/DMA diagnostic flash script is missing'
}
$flash = Get-Content -Raw -LiteralPath $flashPath
if ($flash -notmatch 'ExternalVpwrOffConfirmed' -or
    $flash -notmatch 'no serial command or Burst') {
    throw 'ADC/DMA diagnostic flash script lacks its hardware safety gate'
}
if (-not (Test-Path -LiteralPath $elfPath -PathType Leaf)) {
    throw "ADC/DMA diagnostic image is missing: $elfPath"
}

Write-Host 'M3 no-Burst DMAREQ diagnostic static audit: PASS (no hardware access)'
