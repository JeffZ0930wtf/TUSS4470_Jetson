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
$buildDirectory = Join-Path $repositoryRoot 'firmware\build\m2'
$generatedDirectory = Join-Path $buildDirectory 'generated'
$generatedUsbConfig = Join-Path $generatedDirectory 'USB_config'
$generatedApiRoot = Join-Path $generatedDirectory 'USB_API'
$output = Join-Path $buildDirectory 'usac-m2-no-burst.elf'
$mapFile = Join-Path $buildDirectory 'usac-m2-no-burst.map'
$disassembly = Join-Path $buildDirectory 'usac-m2-no-burst.disassembly.txt'

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
$headerText = (Get-Content -Raw -LiteralPath $descriptorHeader).Replace('#define USB_SUPPORT_SELF_POWERED 0x80', '#define USB_SUPPORT_SELF_POWERED 0x00')
if ($headerText -notmatch '#define USB_SUPPORT_SELF_POWERED 0x00') { throw 'failed to generate bus-powered USB descriptor configuration' }
Set-Content -LiteralPath $descriptorHeader -Value $headerText -Encoding utf8NoBOM

$generatedUsbCore = Join-Path $generatedApiRoot 'USB_Common\usb.c'
$usbCoreText = (Get-Content -Raw -LiteralPath $generatedUsbCore).Replace('abramSerialStringDescriptor[34]', 'abramSerialStringDescriptor[66]')
if ($usbCoreText -notmatch 'abramSerialStringDescriptor\[66\]') { throw 'failed to enlarge TI USB serial descriptor buffer' }
Set-Content -LiteralPath $generatedUsbCore -Value $usbCoreText -Encoding utf8NoBOM

$projectSources = @(
    (Join-Path $repositoryRoot 'firmware\src\m2_main.c'),
    (Join-Path $repositoryRoot 'firmware\src\m2_usb_events.c'),
    (Join-Path $repositoryRoot 'firmware\src\usac_m2_core.c'),
    (Join-Path $repositoryRoot 'firmware\src\tuss4470_profile.c'),
    (Join-Path $repositoryRoot 'firmware\src\tuss4470_configurator.c'),
    (Join-Path $repositoryRoot 'firmware\src\usac_platform_msp430.c'),
    (Join-Path $repositoryRoot 'firmware\src\usac_mcu_protocol.c'),
    (Join-Path $repositoryRoot 'firmware\src\usac_identity.c'),
    (Join-Path $repositoryRoot 'firmware\src\usac_sha256.c'),
    (Join-Path $repositoryRoot 'firmware\src\usac_config_v2.c'),
    (Join-Path $repositoryRoot 'firmware\src\usac_m2_app.c'),
    (Join-Path $repositoryRoot 'firmware\src\usac_dtr_gate.c'),
    (Join-Path $repositoryRoot 'firmware\src\usac_tx_gate.c')
)
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
) + $sources + @('-o', $output)

& $compiler @arguments
if ($LASTEXITCODE -ne 0) { throw "M2 firmware build failed: $LASTEXITCODE" }
& $sizeTool $output
if ($LASTEXITCODE -ne 0) { throw "M2 firmware size failed: $LASTEXITCODE" }
& $objdump '-d' '-S' $output | Set-Content -LiteralPath $disassembly -Encoding utf8NoBOM
if ($LASTEXITCODE -ne 0) { throw "M2 disassembly failed: $LASTEXITCODE" }
Write-Host "M2 no-Burst firmware compiled without flashing: $output"
