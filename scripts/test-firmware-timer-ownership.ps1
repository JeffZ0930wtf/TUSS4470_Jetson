# Firmware TA1 ownership regression gate. TI's USB_init() uses TA1 to detect the
# XT2 frequency and leaves the timer configured for SMCLK. The application
# must reclaim TA1 only after USB_setup() returns, otherwise lease time runs
# hundreds of times too fast on every fresh boot.
$ErrorActionPreference = 'Stop'

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$mainSource = Join-Path $repositoryRoot 'firmware\src\main.c'
$main = Get-Content -Raw -LiteralPath $mainSource
$mainEntryIndex = $main.IndexOf('int main(void)')
if ($mainEntryIndex -lt 0) {
    throw 'firmware timer ownership: main entry point is missing'
}

$mainEntry = $main.Substring($mainEntryIndex)
$usbSetupIndex = $mainEntry.IndexOf('USB_setup(FALSE, TRUE)')
$timerInitIndex = $mainEntry.IndexOf('initialize_frame_timeout_timer()')
if (($usbSetupIndex -lt 0) -or ($timerInitIndex -lt 0)) {
    throw 'firmware timer ownership: USB or application timer initialization is missing'
}
if ($timerInitIndex -lt $usbSetupIndex) {
    throw 'firmware timer ownership: TA1 must be initialized after TI USB_setup() releases it'
}

Write-Host 'Firmware TA1 ownership audit: PASS'
