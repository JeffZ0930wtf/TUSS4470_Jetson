# Builds the fixed M2 no-Burst image from first-party sources plus TI's official
# USB stack. Generated vendor copies live under ignored firmware/build.
param(
    [switch]$EnableM5,
    [switch]$EnableM3Loopback,
    [switch]$M3AdcDmaDiagnostic,
    [switch]$M3StartupDiagnostic,
    [switch]$M3SmallRamDiagnostic
)

$ErrorActionPreference = 'Stop'

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$compilerRoot = Join-Path $repositoryRoot '.tools\msp430-gcc\msp430-gcc-9.3.1.11_win64'
$supportRoot = Join-Path $repositoryRoot '.tools\msp430-support\msp430-gcc-support-files'
$usbBase = Join-Path $repositoryRoot '.tools\msp430-usb\MSP430USBDevelopersPackage_5_20_06_03\MSP430_USB_Software\MSP430_USB_API'
$exampleRoot = Join-Path $usbBase 'examples\CDC_virtualCOMport\C4_PacketProtocol'
$apiRoot = Join-Path $usbBase 'USB_API'
$driverlib = Join-Path $usbBase 'driverlib\MSP430F5xx_6xx'
$compiler = Join-Path $compilerRoot 'bin\msp430-elf-gcc.exe'
$sizeTool = Join-Path $compilerRoot 'bin\msp430-elf-size.exe'
$objdump = Join-Path $compilerRoot 'bin\msp430-elf-objdump.exe'
$m3MainEnabled = $EnableM5 -or $EnableM3Loopback -or $M3AdcDmaDiagnostic -or
    $M3StartupDiagnostic -or $M3SmallRamDiagnostic
if ((@($EnableM5, $EnableM3Loopback, $M3AdcDmaDiagnostic, $M3StartupDiagnostic, $M3SmallRamDiagnostic) |
        Where-Object { $_ }).Count -gt 1) {
    throw 'M3 acceptance and diagnostic platforms are mutually exclusive.'
}
$milestone = if ($EnableM5) {
    'm5'
} elseif ($EnableM3Loopback) {
    'm3'
} elseif ($M3AdcDmaDiagnostic) {
    'm3-adc-dma-diagnostic'
} elseif ($M3StartupDiagnostic) {
    'm3-startup-diagnostic'
} elseif ($M3SmallRamDiagnostic) {
    'm3-small-ram-diagnostic'
} else {
    'm2'
}
$imageName = if ($EnableM5) {
    'usac-m5-first-version'
} elseif ($EnableM3Loopback) {
    'usac-m3-acceptance'
} elseif ($M3AdcDmaDiagnostic) {
    'usac-m3-adc-dma-diagnostic-no-burst'
} elseif ($M3StartupDiagnostic) {
    'usac-m3-startup-diagnostic-no-acquisition'
} elseif ($M3SmallRamDiagnostic) {
    'usac-m3-small-ram-diagnostic-no-acquisition'
} else {
    'usac-m2-no-burst'
}
$buildDirectory = Join-Path $repositoryRoot "firmware\build\$milestone"
$generatedDirectory = Join-Path $buildDirectory 'generated'
$generatedUsbConfig = Join-Path $generatedDirectory 'USB_config'
$generatedApiRoot = Join-Path $generatedDirectory 'USB_API'
$output = Join-Path $buildDirectory "$imageName.elf"
$mapFile = Join-Path $buildDirectory "$imageName.map"
$disassembly = Join-Path $buildDirectory "$imageName.disassembly.txt"
$utf8WithoutBom = New-Object System.Text.UTF8Encoding($false)

foreach ($requiredPath in @($compiler, $sizeTool, $objdump, (Join-Path $apiRoot 'msp430USB.ld'), (Join-Path $exampleRoot 'USB_config\descriptors.h'))) {
    if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
        throw "required M2 build input is missing: $requiredPath"
    }
}

New-Item -ItemType Directory -Force -Path $generatedUsbConfig | Out-Null
New-Item -ItemType Directory -Force -Path $generatedApiRoot | Out-Null
Copy-Item -LiteralPath (Join-Path $exampleRoot 'USB_config\descriptors.h') -Destination $generatedUsbConfig -Force
Copy-Item -LiteralPath (Join-Path $exampleRoot 'USB_config\descriptors.c') -Destination $generatedUsbConfig -Force
Copy-Item -LiteralPath (Join-Path $exampleRoot 'USB_config\UsbIsr.c') -Destination $generatedUsbConfig -Force
Copy-Item -Path (Join-Path $apiRoot '*') -Destination $generatedApiRoot -Recurse -Force

$descriptorHeader = Join-Path $generatedUsbConfig 'descriptors.h'
# TI's CDC example uses DMA0 for endpoint copies, while M3 reserves DMA0/DMA1
# for ADC samples and the pretrigger counter. The official 0xFF setting keeps
# USB on its byte-copy fallback so a response cannot inherit acquisition DMA state.
$headerText = (Get-Content -Raw -LiteralPath $descriptorHeader).
    Replace('#define USB_SUPPORT_SELF_POWERED 0x80', '#define USB_SUPPORT_SELF_POWERED 0x00').
    Replace('#define USB_DMA_CHAN           DMA_CHANNEL_0', '#define USB_DMA_CHAN           0xFF')
if ($headerText -notmatch '#define USB_SUPPORT_SELF_POWERED 0x00') { throw 'failed to generate bus-powered USB descriptor configuration' }
if ($headerText -notmatch '#define USB_DMA_CHAN\s+0xFF') {
    throw 'failed to reserve DMA0 and DMA1 exclusively for M3 acquisition'
}
[System.IO.File]::WriteAllText($descriptorHeader, $headerText, $utf8WithoutBom)

$generatedUsbCore = Join-Path $generatedApiRoot 'USB_Common\usb.c'
$usbCoreText = (Get-Content -Raw -LiteralPath $generatedUsbCore).Replace('abramSerialStringDescriptor[34]', 'abramSerialStringDescriptor[66]')
if ($usbCoreText -notmatch 'abramSerialStringDescriptor\[66\]') { throw 'failed to enlarge TI USB serial descriptor buffer' }
[System.IO.File]::WriteAllText($generatedUsbCore, $usbCoreText, $utf8WithoutBom)

$projectSources = @(
    (Join-Path $repositoryRoot 'firmware\src\main.c'),
    (Join-Path $repositoryRoot 'firmware\src\usb_events.c'),
    (Join-Path $repositoryRoot 'firmware\src\usac_firmware_core.c'),
    (Join-Path $repositoryRoot 'firmware\src\usac_loopback.c'),
    (Join-Path $repositoryRoot 'firmware\src\usac_capture.c'),
    (Join-Path $repositoryRoot 'firmware\src\usac_capture_stream.c'),
    (Join-Path $repositoryRoot 'firmware\src\usac_capture_tx.c'),
    (Join-Path $repositoryRoot 'firmware\src\tuss4470_profile.c'),
    (Join-Path $repositoryRoot 'firmware\src\tuss4470_configurator.c'),
    (Join-Path $repositoryRoot 'firmware\src\usac_platform_msp430.c'),
    (Join-Path $repositoryRoot 'firmware\src\usac_mcu_protocol.c'),
    (Join-Path $repositoryRoot 'firmware\src\usac_identity.c'),
    (Join-Path $repositoryRoot 'firmware\src\usac_sha256.c'),
    (Join-Path $repositoryRoot 'firmware\src\usac_config_v2.c'),
    (Join-Path $repositoryRoot 'firmware\src\usac_firmware_app.c'),
    (Join-Path $repositoryRoot 'firmware\src\usac_dtr_gate.c'),
    (Join-Path $repositoryRoot 'firmware\src\usac_tx_gate.c'),
    (Join-Path $repositoryRoot 'firmware\src\usac_capture_schedule.c'),
    (Join-Path $repositoryRoot 'firmware\src\usac_burst_plan.c')
)
if ($M3SmallRamDiagnostic) {
    # The small-RAM diagnostic supplies a fail-closed report stub and must not
    # link the production translation unit that owns the 4096-byte buffer.
    $productionCaptureSource = Join-Path $repositoryRoot 'firmware\src\usac_capture.c'
    $projectSources = @($projectSources | Where-Object { $_ -ne $productionCaptureSource })
}
if ($EnableM5 -or $EnableM3Loopback -or $M3AdcDmaDiagnostic) {
    $projectSources += Join-Path $repositoryRoot 'firmware\src\usac_acquisition_platform_msp430.c'
} elseif ($M3StartupDiagnostic) {
    $projectSources += Join-Path $repositoryRoot 'firmware\tests\m3_platform_startup_stub.c'
} elseif ($M3SmallRamDiagnostic) {
    $projectSources += Join-Path $repositoryRoot 'firmware\tests\m3_platform_small_ram_stub.c'
}
foreach ($source in $projectSources) {
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { throw "M2 project source is missing: $source" }
}

$projectObjectDirectory = Join-Path $buildDirectory 'project-objects'
New-Item -ItemType Directory -Force -Path $projectObjectDirectory | Out-Null
$projectCompileArguments = @(
    "-I$(Join-Path $supportRoot 'include')", "-I$(Join-Path $repositoryRoot 'firmware\include')",
    "-isystem$generatedDirectory", "-isystem$generatedUsbConfig", "-isystem$usbBase", "-isystem$driverlib",
    "-isystem$exampleRoot", "-isystem$(Join-Path $exampleRoot 'USB_app')", "-isystem$apiRoot",
    '-D__MSP430F5529__', '-DDEPRECATED', '-mmcu=msp430f5529', '-Os', '-std=c11',
    '-Wall', '-Wextra', '-Werror', "-L$(Join-Path $supportRoot 'include')"
)
if ($m3MainEnabled) {
    $projectCompileArguments += '-DUSAC_ENABLE_LOOPBACK'
}
if ($EnableM5) {
    $projectCompileArguments += '-DUSAC_ENABLE_ACQUISITION'
}
if ($M3AdcDmaDiagnostic) {
    $projectCompileArguments += '-DUSAC_ADC_DMA_DIAGNOSTIC'
}
foreach ($source in $projectSources) {
    $objectName = ([System.IO.Path]::GetFileNameWithoutExtension($source)) + '.o'
    $objectPath = Join-Path $projectObjectDirectory $objectName
    & $compiler @projectCompileArguments '-c' $source '-o' $objectPath
    if ($LASTEXITCODE -ne 0) { throw "M2 project warning-clean compile failed: $source" }
}

$sources = $projectSources + @(
    (Join-Path $generatedUsbConfig 'UsbIsr.c'),
    (Join-Path $generatedUsbConfig 'descriptors.c'),
    (Join-Path $exampleRoot 'USB_app\usbConstructs.c'),
    (Join-Path $apiRoot 'USB_PHDC_API\UsbPHDC.c'),
    (Join-Path $apiRoot 'USB_HID_API\UsbHid.c'),
    (Join-Path $apiRoot 'USB_HID_API\UsbHidReq.c'),
    (Join-Path $apiRoot 'USB_CDC_API\UsbCdc.c'),
    $generatedUsbCore,
    (Join-Path $apiRoot 'USB_Common\usbdma.c'),
    (Join-Path $apiRoot 'USB_MSC_API\UsbMscScsi.c'),
    (Join-Path $apiRoot 'USB_MSC_API\UsbMscStateMachine.c'),
    (Join-Path $apiRoot 'USB_MSC_API\UsbMscReq.c')
)
$sources += Get-ChildItem -LiteralPath $driverlib -Filter '*.c' | Select-Object -ExpandProperty FullName

$arguments = @(
    "-I$(Join-Path $supportRoot 'include')", "-I$(Join-Path $repositoryRoot 'firmware\include')", "-I$generatedDirectory", "-I$generatedUsbConfig",
    "-I$usbBase", "-I$driverlib", "-I$exampleRoot", "-I$(Join-Path $exampleRoot 'USB_app')", "-I$apiRoot",
    '-D__MSP430F5529__', '-DDEPRECATED', '-mmcu=msp430f5529', '-Os', '-std=c11',
    '-fdata-sections', '-ffunction-sections', '-fcommon', '-w', "-L$(Join-Path $supportRoot 'include')",
    "-T$(Join-Path $apiRoot 'msp430USB.ld')", "-T$(Join-Path $supportRoot 'include\msp430f5529.ld')",
    '-Wl,--gc-sections', "-Wl,-Map=$mapFile"
)
if ($m3MainEnabled) {
    $arguments += '-DUSAC_ENABLE_LOOPBACK'
}
if ($EnableM5) {
    $arguments += '-DUSAC_ENABLE_ACQUISITION'
}
if ($M3AdcDmaDiagnostic) {
    $arguments += '-DUSAC_ADC_DMA_DIAGNOSTIC'
}
$arguments += $sources + @('-o', $output)

& $compiler @arguments
if ($LASTEXITCODE -ne 0) { throw "$milestone firmware build failed: $LASTEXITCODE" }
& $sizeTool $output
if ($LASTEXITCODE -ne 0) { throw "$milestone firmware size failed: $LASTEXITCODE" }
& $objdump '-d' '-S' $output | Set-Content -LiteralPath $disassembly -Encoding UTF8
if ($LASTEXITCODE -ne 0) { throw "$milestone disassembly failed: $LASTEXITCODE" }
if ($EnableM5) {
    Write-Host "M5 first-version firmware compiled without flashing: $output"
} elseif ($EnableM3Loopback) {
    Write-Host "M3 acceptance firmware compiled without flashing: $output"
} elseif ($M3AdcDmaDiagnostic) {
    Write-Host "M3 no-Burst ADC/DMA diagnostic compiled without flashing: $output"
} elseif ($M3StartupDiagnostic) {
    Write-Host "M3 no-acquisition startup diagnostic compiled without flashing: $output"
} elseif ($M3SmallRamDiagnostic) {
    Write-Host "M3 small-RAM no-acquisition diagnostic compiled without flashing: $output"
} else {
    Write-Host "M2 no-Burst firmware compiled without flashing: $output"
}
