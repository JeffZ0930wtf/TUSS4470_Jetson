# Programs only the no-acquisition M3 startup diagnostic. The image preserves
# M3 RAM/main-loop changes but its loopback and capture callbacks fail closed.
param(
    [switch]$ExternalVpwrOffConfirmed
)

$ErrorActionPreference = 'Stop'

if (-not $ExternalVpwrOffConfirmed) {
    throw 'Refusing to flash: turn external VPWR off and pass -ExternalVpwrOffConfirmed.'
}

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$image = Join-Path $repositoryRoot `
    'firmware\build\m3-startup-diagnostic\usac-m3-startup-diagnostic-no-acquisition.elf'
$uniflashRoot = Join-Path $repositoryRoot '.tools\uniflash-ascii'
$tiAppData = Join-Path $repositoryRoot '.tools\ti-appdata'
$dslite = Join-Path $uniflashRoot 'ccs_base\DebugServer\bin\DSLite.exe'
$targetConfig = Join-Path $uniflashRoot 'user_files\configs\MSP430F5529.ccxml'
$settings = Join-Path $uniflashRoot 'user_files\settings\generated.ufsettings'

foreach ($required in @($image, $dslite, $targetConfig, $settings)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "required diagnostic flash input is missing: $required"
    }
}

New-Item -ItemType Directory -Force -Path $tiAppData | Out-Null
$env:TI_APPDATA_DIR = $tiAppData

Write-Host 'M3 startup diagnostic flash: external VPWR confirmed OFF.'
Write-Host "Image: $image"
Write-Host 'Acquisition callbacks fail closed; no serial command is issued.'

Push-Location $uniflashRoot
try {
    & $dslite flash '-c' $targetConfig '-l' $settings '-e' '-f' '-v' $image
    if ($LASTEXITCODE -ne 0) {
        throw "TI DSLite diagnostic flash/verify failed with exit code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}

Write-Host 'M3 startup diagnostic flash and verify: PASS'
