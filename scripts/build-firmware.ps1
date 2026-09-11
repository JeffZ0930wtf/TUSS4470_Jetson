# Builds the production acquisition firmware from first-party sources plus
# TI's official USB stack. Generated vendor copies live under ignored
# firmware/build. This script compiles only; it never flashes or opens serial.

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
$imageName = 'tuss4470-acquisition-fw-0.2.0.2'
$buildDirectory = Join-Path $repositoryRoot 'firmware\build\release'
$generatedDirectory = Join-Path $buildDirectory 'generated'
$generatedUsbConfig = Join-Path $generatedDirectory 'USB_config'
$generatedApiRoot = Join-Path $generatedDirectory 'USB_API'
$output = Join-Path $buildDirectory "$imageName.elf"
$mapFile = Join-Path $buildDirectory "$imageName.map"
$disassembly = Join-Path $buildDirectory "$imageName.disassembly.txt"
$utf8WithoutBom = New-Object System.Text.UTF8Encoding($false)

foreach ($requiredPath in @($compiler, $sizeTool, $objdump, (Join-Path $apiRoot 'msp430USB.ld'), (Join-Path $exampleRoot 'USB_config\descriptors.h'))) {
    if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
        throw "required firmware build input is missing: $requiredPath"
    }
}

New-Item -ItemType Directory -Force -Path $generatedUsbConfig | Out-Null
New-Item -ItemType Directory -Force -Path $generatedApiRoot | Out-Null
Copy-Item -LiteralPath (Join-Path $exampleRoot 'USB_config\descriptors.h') -Destination $generatedUsbConfig -Force
Copy-Item -LiteralPath (Join-Path $exampleRoot 'USB_config\descriptors.c') -Destination $generatedUsbConfig -Force
Copy-Item -LiteralPath (Join-Path $exampleRoot 'USB_config\UsbIsr.c') -Destination $generatedUsbConfig -Force
Copy-Item -Path (Join-Path $apiRoot '*') -Destination $generatedApiRoot -Recurse -Force

$descriptorHeader = Join-Path $generatedUsbConfig 'descriptors.h'
# TI's CDC example uses DMA0 for endpoint copies, while acquisition reserves DMA0/DMA1
# for ADC samples and the pretrigger counter. The official 0xFF setting keeps
# USB on its byte-copy fallback so a response cannot inherit acquisition DMA state.
$headerText = (Get-Content -Raw -LiteralPath $descriptorHeader).
    Replace('#define USB_SUPPORT_SELF_POWERED 0x80', '#define USB_SUPPORT_SELF_POWERED 0x00').
    Replace('#define USB_DMA_CHAN           DMA_CHANNEL_0', '#define USB_DMA_CHAN           0xFF')
if ($headerText -notmatch '#define USB_SUPPORT_SELF_POWERED 0x00') { throw 'failed to generate bus-powered USB descriptor configuration' }
if ($headerText -notmatch '#define USB_DMA_CHAN\s+0xFF') {
    throw 'failed to reserve DMA0 and DMA1 exclusively for acquisition'
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
$projectSources += Join-Path $repositoryRoot 'firmware\src\usac_acquisition_platform_msp430.c'
foreach ($source in $projectSources) {
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { throw "firmware project source is missing: $source" }
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
$projectCompileArguments += '-DUSAC_ENABLE_LOOPBACK'
$projectCompileArguments += '-DUSAC_ENABLE_ACQUISITION'
foreach ($source in $projectSources) {
    $objectName = ([System.IO.Path]::GetFileNameWithoutExtension($source)) + '.o'
    $objectPath = Join-Path $projectObjectDirectory $objectName
    & $compiler @projectCompileArguments '-c' $source '-o' $objectPath
    if ($LASTEXITCODE -ne 0) { throw "firmware project warning-clean compile failed: $source" }
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
$arguments += '-DUSAC_ENABLE_LOOPBACK'
$arguments += '-DUSAC_ENABLE_ACQUISITION'
$arguments += $sources + @('-o', $output)

& $compiler @arguments
if ($LASTEXITCODE -ne 0) { throw "production firmware build failed: $LASTEXITCODE" }
& $sizeTool $output
if ($LASTEXITCODE -ne 0) { throw "production firmware size failed: $LASTEXITCODE" }
& $objdump '-d' '-S' $output | Set-Content -LiteralPath $disassembly -Encoding UTF8
if ($LASTEXITCODE -ne 0) { throw "production firmware disassembly failed: $LASTEXITCODE" }
Write-Host "Production acquisition firmware compiled without flashing: $output"
