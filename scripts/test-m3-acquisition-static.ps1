# Structural acceptance gate for the fixed M3 ADC/DMA path. It verifies the
# one-buffer 2048-point layout and 64-sample hardware pretrigger counter; it
# does not claim analog accuracy or execute a Burst.
$ErrorActionPreference = 'Stop'

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$capturePath = Join-Path $repositoryRoot 'firmware\src\usac_m3_capture.c'
$captureHeaderPath = Join-Path $repositoryRoot 'firmware\include\usac_m3_capture.h'
$platformPath = Join-Path $repositoryRoot 'firmware\src\usac_platform_m3_msp430.c'
$streamPath = Join-Path $repositoryRoot 'firmware\src\usac_m3_capture_stream.c'
$streamHeaderPath = Join-Path $repositoryRoot 'firmware\include\usac_m3_capture_stream.h'
$txPath = Join-Path $repositoryRoot 'firmware\src\usac_m3_capture_tx.c'
$txHeaderPath = Join-Path $repositoryRoot 'firmware\include\usac_m3_capture_tx.h'
$mainPath = Join-Path $repositoryRoot 'firmware\src\m2_main.c'
$usbDescriptorPath = Join-Path $repositoryRoot 'firmware\build\m3\generated\USB_config\descriptors.h'
$elfPath = Join-Path $repositoryRoot 'firmware\build\m3\usac-m3-acceptance.elf'
$compilerRoot = Join-Path $repositoryRoot '.tools\msp430-gcc\msp430-gcc-9.3.1.11_win64'
$sizeTool = Join-Path $compilerRoot 'bin\msp430-elf-size.exe'
$nmTool = Join-Path $compilerRoot 'bin\msp430-elf-nm.exe'
foreach ($required in @($capturePath, $captureHeaderPath, $platformPath, $streamPath, $streamHeaderPath, $txPath, $txHeaderPath, $mainPath, $usbDescriptorPath, $elfPath, $sizeTool, $nmTool)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "M3 acquisition source is missing: $required"
    }
}

$capture = (Get-Content -Raw -LiteralPath $captureHeaderPath) + "`n" +
    (Get-Content -Raw -LiteralPath $capturePath)
$platform = Get-Content -Raw -LiteralPath $platformPath
$allSource = $capture + "`n" + $platform
$stream = (Get-Content -Raw -LiteralPath $streamHeaderPath) + "`n" +
    (Get-Content -Raw -LiteralPath $streamPath)
$tx = (Get-Content -Raw -LiteralPath $txHeaderPath) + "`n" +
    (Get-Content -Raw -LiteralPath $txPath)
$main = Get-Content -Raw -LiteralPath $mainPath
$usbDescriptor = Get-Content -Raw -LiteralPath $usbDescriptorPath
if (($allSource | Select-String -AllMatches -Pattern 'g_usac_m3_waveform\s*\[\s*USAC_M3_SAMPLE_COUNT\s*\]').Matches.Count -ne 2) {
    throw 'waveform buffer must have exactly one extern declaration and one definition'
}
$requiredPatterns = @(
    @{ Pattern = '#define\s+USAC_M3_SAMPLE_COUNT\s+2048u'; Label = '2048 sample constant' },
    @{ Pattern = '#define\s+USAC_M3_PRETRIGGER_COUNT\s+64u'; Label = '64 sample pretrigger constant' },
    @{ Pattern = 'g_usac_m3_waveform\s*\[\s*USAC_M3_SAMPLE_COUNT\s*\]\s*__attribute__\s*\(\(section\("\.noinit"\)\)\)'; Label = 'DMA waveform bypasses pre-main BSS clearing' },
    @{ Pattern = 'P6SEL\s*\|=\s*BIT0'; Label = 'P6.0/A0 analog input' },
    @{ Pattern = 'ADC12SHS_3'; Label = 'TB0.1 ADC trigger' },
    @{ Pattern = 'TB0CCR0\s*=\s*\(uint16_t\)\(sample_interval_ticks\s*-\s*1u\)'; Label = 'Timer_B period equals one sample interval' },
    @{ Pattern = 'TB0CCR1\s*=\s*1u'; Label = 'TB0.1 compare creates an early trigger edge' },
    @{ Pattern = 'TB0CCTL1\s*=\s*OUTMOD_3'; Label = 'TB0.1 set-reset pulse mode' },
    @{ Pattern = 'ADC12SSEL_3\s*\|\s*ADC12DIV_5'; Label = '4 MHz ADC12 clock' },
    @{ Pattern = 'static\s+uint8_t\s+prepare_adc_dma_capture_path\s*\('; Label = 'repeatable ADC DMA preparation helper' },
    @{ Pattern = 'DMA0CTL\s*=\s*0u[\s\S]*?DMA1CTL\s*=\s*0u[\s\S]*?DMACTL0\s*=\s*0u[\s\S]*?ADC12CTL0\s*=\s*0u[\s\S]*?ADC12IE\s*=\s*0u[\s\S]*?ADC12IFG\s*=\s*0u'; Label = 'ADC and DMA return to a fully disabled idle state before rearm' },
    @{ Pattern = 'while\s*\(\(ADC12CTL1\s*&\s*ADC12BUSY\)\s*!=\s*0u\)'; Label = 'ADC idle is observed before selecting the DMA trigger' },
    @{ Pattern = 'DMACTL4\s*=\s*DMARMWDIS'; Label = 'F5529 DMA4 erratum protection for 20-bit address writes' },
    @{ Pattern = 'TB0CCR2\s*=\s*111u'; Label = 'DMA trigger compare is fixed at tick 111' },
    @{ Pattern = 'TB0CCTL2\s*=\s*0u'; Label = 'TB0CCR2 interrupt stays disabled for DMA triggering' },
    @{ Pattern = 'DMACTL0\s*=\s*DMA0TSEL_8\s*\|\s*DMA1TSEL_8'; Label = 'DMA0 and DMA1 use the independent TB0CCR2 trigger' },
    @{ Pattern = 'stop_capture_hardware[\s\S]*?TB0CCTL2\s*=\s*0u[\s\S]*?TB0CCR2\s*=\s*0u'; Label = 'capture stop clears the TB0CCR2 trigger state' },
    @{ Pattern = 'DMA0SZ\s*=\s*USAC_M3_SAMPLE_COUNT'; Label = 'DMA0 exact full-waveform count' },
    @{ Pattern = 'DMA1SZ\s*=\s*USAC_M3_PRETRIGGER_COUNT'; Label = 'DMA1 hardware pretrigger count' },
    @{ Pattern = 'DMA0DA[\s\S]*?g_usac_m3_waveform'; Label = 'DMA0 writes directly to unique waveform buffer' },
    @{ Pattern = 'DMA1DA[\s\S]*?pretrigger_sink'; Label = 'DMA1 counts without a second sample buffer' },
    @{ Pattern = 'case\s+DMAIV_DMA1IFG:[\s\S]*?TA2CTL\s*=\s*TASSEL_2\s*\|\s*MC_1\s*\|\s*TACLR'; Label = 'DMA1 completion starts finite Burst timer' },
    @{ Pattern = 'capture_dma0_completed\s*=\s*0u'; Label = 'DMA0 completion evidence reset before capture' },
    @{ Pattern = 'case\s+DMAIV_DMA0IFG:[\s\S]*?capture_dma0_completed\s*=\s*1u[\s\S]*?capture_complete\s*=\s*1u'; Label = 'DMA0 ISR records exact completion evidence' },
    @{ Pattern = 'if\s*\(capture_dma0_completed\s*!=\s*0u\)[\s\S]*?report->dma_remaining\s*=\s*0u[\s\S]*?report->captured_samples\s*=\s*USAC_M3_SAMPLE_COUNT'; Label = 'completed DMA block reports 2048 samples and zero remaining' }
)
foreach ($check in $requiredPatterns) {
    if ($allSource -notmatch $check.Pattern) {
        throw "M3 acquisition invariant missing: $($check.Label)"
    }
}
if ($allSource -match 'ADC12SHS_2' -or
    $allSource -match 'TB0CCTL0\s*=\s*OUTMOD_4') {
    throw 'obsolete TB0.0 ADC trigger path is still present'
}
if ($allSource -match 'DMA0TSEL_24\s*\|\s*DMA1TSEL_24') {
    throw 'ADC12IFG is still configured as the repeated-capture DMA trigger'
}
if ($allSource -match '(?i)interpolat|repeat_last|fill_missing') {
    throw 'M3 acquisition source contains a forbidden sample synthesis path'
}
if ($allSource -match 'report->captured_samples\s*=\s*\(uint16_t\)\(USAC_M3_SAMPLE_COUNT\s*-\s*DMA0SZ\)\s*;\s*report->trigger_sample_index') {
    throw 'completed M3 capture still derives success count from reloaded DMA0SZ'
}

if ($stream -match 'USAC_M3_CAPTURE_CHUNK_MAX' -or
    $stream -match 'usac_m3_capture_stream_next') {
    throw 'CAPTURE_DATA frame source still exposes advancing 64-byte application chunks'
}
if ($stream -notmatch 'stream->samples\s*=\s*samples' -or
    $stream -notmatch '\(const uint8_t \*\)stream->samples') {
    throw 'CAPTURE_DATA does not stream directly from the unique waveform buffer'
}
if ($tx -notmatch 'USAC_M3_TX_START_BUSY[\s\S]*?USAC_M3_TX_READY' -or
    $tx -notmatch 'usac_m3_capture_tx_on_send_completed[\s\S]*?usac_m3_capture_stream_commit') {
    throw 'transport-neutral capture session does not retain BUSY or commit on completion'
}
if ($main -notmatch 'usac_m3_capture_tx_peek[\s\S]*?USBCDC_sendData') {
    throw 'M3 main loop does not send the stable segment exposed by the TX session'
}
if ($main -notmatch 'USBCDC_INTERFACE_BUSY_ERROR[\s\S]*?USAC_M3_TX_START_BUSY') {
    throw 'TI CDC BUSY is not mapped to a non-advancing TX result'
}
if ($main -notmatch 'g_usac_usb_send_complete[\s\S]*?USAC_M3_TX_IN_FLIGHT[\s\S]*?usac_m3_capture_tx_on_send_completed') {
    throw 'USB completion does not commit exactly the capture segment in flight'
}
if ($usbDescriptor -notmatch '#define\s+USB_DMA_CHAN\s+0xFF') {
    throw 'TI USB CDC must use its CPU-copy path so DMA0/DMA1 remain exclusive to M3 acquisition'
}

$sizeOutput = (& $sizeTool $elfPath 2>&1) -join "`n"
if ($LASTEXITCODE -ne 0 -or $sizeOutput -notmatch '(?m)^\s*(\d+)\s+(\d+)\s+(\d+)') {
    throw "unable to inspect M3 image size`n$sizeOutput"
}
$staticRam = [int]$Matches[2] + [int]$Matches[3]
if ($staticRam -gt 7168) {
    throw "M3 static RAM exceeds guard limit: $staticRam B"
}
$symbols = (& $nmTool '-S' $elfPath 2>&1) -join "`n"
$usbDmaSymbols = [regex]::Matches($symbols, '(?m)\bmemcpyDMA(?:[012])?$')
if ($usbDmaSymbols.Count -ne 0) {
    throw 'M3 ELF still contains TI USB DMA copy code that can collide with acquisition DMA0/DMA1'
}
$waveformMatches = [regex]::Matches($symbols, '(?m)^\S+\s+00001000\s+[Bb]\s+g_usac_m3_waveform$')
if ($waveformMatches.Count -ne 1) {
    throw 'M3 ELF must contain exactly one 4096-byte g_usac_m3_waveform symbol'
}

Write-Host "M3 acquisition static audit: PASS (static_ram=$staticRam B, one 4096 B waveform; no hardware access)"
