# Programs only the no-Burst software-triggered ADC/DMA diagnostic image.
param(
    [switch]$ExternalVpwrOffConfirmed
)

$ErrorActionPreference = 'Stop'

if (-not $ExternalVpwrOffConfirmed) {
    throw 'Refusing to flash: turn external VPWR off and pass -ExternalVpwrOffConfirmed.'
}

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$image = Join-Path $repositoryRoot `
    'firmware\build\m3-adc-dma-diagnostic\usac-m3-adc-dma-diagnostic-no-burst.elf'
$uniflashRoot = Join-Path $repositoryRoot '.tools\uniflash-ascii'
$tiAppData = Join-Path $repositoryRoot '.tools\ti-appdata'
$dslite = Join-Path $uniflashRoot 'ccs_base\DebugServer\bin\DSLite.exe'
$targetConfig = Join-Path $uniflashRoot 'user_files\configs\MSP430F5529.ccxml'
$settings = Join-Path $uniflashRoot 'user_files\settings\generated.ufsettings'

foreach ($required in @($image, $dslite, $targetConfig, $settings)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "required ADC/DMA diagnostic flash input is missing: $required"
    }
}

New-Item -ItemType Directory -Force -Path $tiAppData | Out-Null
$env:TI_APPDATA_DIR = $tiAppData

Write-Host 'M3 ADC/DMA diagnostic flash: external VPWR confirmed OFF.'
Write-Host "Image: $image"
Write-Host 'The flash script sends no serial command or Burst.'

Push-Location $uniflashRoot
try {
    & $dslite flash '-c' $targetConfig '-l' $settings '-e' '-f' '-v' $image
    if ($LASTEXITCODE -ne 0) {
        throw "TI DSLite ADC/DMA diagnostic flash/verify failed with exit code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}

Write-Host 'M3 ADC/DMA diagnostic flash and verify: PASS'
