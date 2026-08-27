# Compiles TI's official CDC C4 example with the pinned MSP430 toolchain to
# prove the vendor USB sources used by M2 remain build-compatible.
$ErrorActionPreference = 'Stop'

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$compilerRoot = Join-Path $repositoryRoot '.tools\msp430-gcc\msp430-gcc-9.3.1.11_win64'
$supportRoot = Join-Path $repositoryRoot '.tools\msp430-support\msp430-gcc-support-files'
$packageRoot = Join-Path $repositoryRoot '.tools\msp430-usb\MSP430USBDevelopersPackage_5_20_06_03\MSP430_USB_Software\MSP430_USB_API'
$usbBase = $packageRoot
$exampleRoot = Join-Path $usbBase 'examples\CDC_virtualCOMport\C4_PacketProtocol'
$driverlib = Join-Path $usbBase 'driverlib\MSP430F5xx_6xx'
$apiRoot = Join-Path $usbBase 'USB_API'
$compiler = Join-Path $compilerRoot 'bin\msp430-elf-gcc.exe'
$sizeTool = Join-Path $compilerRoot 'bin\msp430-elf-size.exe'
$outputDirectory = Join-Path $repositoryRoot 'firmware\build\ti-usb-smoke'
$output = Join-Path $outputDirectory 'C4_PacketProtocol.elf'

foreach ($requiredPath in @($compiler, (Join-Path $apiRoot 'msp430USB.ld'), $exampleRoot)) {
    if (-not (Test-Path -LiteralPath $requiredPath)) {
        throw "required TI USB build input is missing: $requiredPath"
    }
}

New-Item -ItemType Directory -Force -Path $outputDirectory | Out-Null

$sources = @(
    (Join-Path $exampleRoot 'system_pre_init.c'),
    (Join-Path $exampleRoot 'hal.c'),
    (Join-Path $exampleRoot 'main.c'),
    (Join-Path $exampleRoot 'USB_config\UsbIsr.c'),
    (Join-Path $exampleRoot 'USB_config\descriptors.c'),
    (Join-Path $exampleRoot 'USB_app\usbConstructs.c'),
    (Join-Path $exampleRoot 'USB_app\usbEventHandling.c'),
    (Join-Path $apiRoot 'USB_PHDC_API\UsbPHDC.c'),
    (Join-Path $apiRoot 'USB_HID_API\UsbHid.c'),
    (Join-Path $apiRoot 'USB_HID_API\UsbHidReq.c'),
    (Join-Path $apiRoot 'USB_CDC_API\UsbCdc.c'),
    (Join-Path $apiRoot 'USB_Common\usb.c'),
    (Join-Path $apiRoot 'USB_Common\usbdma.c'),
    (Join-Path $apiRoot 'USB_MSC_API\UsbMscScsi.c'),
    (Join-Path $apiRoot 'USB_MSC_API\UsbMscStateMachine.c'),
    (Join-Path $apiRoot 'USB_MSC_API\UsbMscReq.c')
)
$sources += Get-ChildItem -LiteralPath $driverlib -Filter '*.c' | Select-Object -ExpandProperty FullName

$arguments = @(
    "-I$(Join-Path $supportRoot 'include')",
    "-I$usbBase",
    "-I$driverlib",
    "-I$exampleRoot",
    "-I$(Join-Path $exampleRoot 'USB_config')",
    "-I$apiRoot",
    '-D__MSP430F5529__',
    '-DDEPRECATED',
    '-mmcu=msp430f5529',
    '-Os',
    '-fdata-sections',
    '-ffunction-sections',
    '-fcommon',
    '-w',
    "-L$(Join-Path $supportRoot 'include')",
    "-T$(Join-Path $apiRoot 'msp430USB.ld')",
    "-T$(Join-Path $supportRoot 'include\msp430f5529.ld')",
    '-Wl,--gc-sections'
) + $sources + @('-o', $output)

& $compiler @arguments
if ($LASTEXITCODE -ne 0) {
    throw "TI USB stack smoke build failed: $LASTEXITCODE"
}
& $sizeTool $output
if ($LASTEXITCODE -ne 0) {
    throw "TI USB stack smoke size failed: $LASTEXITCODE"
}

Write-Host "TI official C4 USB CDC stack smoke build: PASS ($output)"
