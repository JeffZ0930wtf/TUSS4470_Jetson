# Programs only the fixed M2 no-Burst ELF through TI DSLite. The explicit VPWR
# confirmation prevents programming while the TUSS4470 external rail is active.
param(
    [switch]$ExternalVpwrOffConfirmed
)

$ErrorActionPreference = 'Stop'

if (-not $ExternalVpwrOffConfirmed) {
    throw 'Refusing to flash: turn external VPWR off and pass -ExternalVpwrOffConfirmed.'
}

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$image = Join-Path $repositoryRoot 'firmware\build\m2\usac-m2-no-burst.elf'
$documentsRoot = [Environment]::GetFolderPath('MyDocuments')
$installedUniflashRoot = Join-Path $documentsRoot `
    'Texas Instruments\TUSS Generation III\TUSS44x0\UNIFLASH'
$uniflashRoot = Join-Path $repositoryRoot '.tools\uniflash-ascii'
$tiAppData = Join-Path $repositoryRoot '.tools\ti-appdata'

if (Test-Path -LiteralPath $uniflashRoot) {
    $link = Get-Item -LiteralPath $uniflashRoot -Force
    if (($link.LinkType -ne 'Junction') -or
        ($link.Target -notcontains $installedUniflashRoot)) {
        throw "unexpected existing ASCII UniFlash path: $uniflashRoot"
    }
}
else {
    New-Item -ItemType Junction -Path $uniflashRoot `
        -Target $installedUniflashRoot | Out-Null
}

$dslite = Join-Path $uniflashRoot 'ccs_base\DebugServer\bin\DSLite.exe'
$targetConfig = Join-Path $uniflashRoot 'user_files\configs\MSP430F5529.ccxml'
$settings = Join-Path $uniflashRoot 'user_files\settings\generated.ufsettings'

foreach ($required in @($image, $dslite, $targetConfig, $settings)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "required flash input is missing: $required"
    }
}

New-Item -ItemType Directory -Force -Path $tiAppData | Out-Null
$env:TI_APPDATA_DIR = $tiAppData

Write-Host 'M2 controlled flash: external VPWR confirmed OFF.'
Write-Host "Target: MSP430F5529"
Write-Host "Image:  $image"
Write-Host 'This image has no Burst-capable command path.'
Write-Host "UniFlash ASCII entry: $uniflashRoot"

Push-Location $uniflashRoot
try {
    & $dslite flash `
        '-c' $targetConfig `
        '-l' $settings `
        '-e' '-f' '-v' `
        $image
    if ($LASTEXITCODE -ne 0) {
        throw "TI DSLite flash/verify failed with exit code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}

Write-Host 'M2 flash and verify: PASS'
