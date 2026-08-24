$ErrorActionPreference = 'Stop'

$repositoryRoot = Split-Path -Parent $PSScriptRoot

function Resolve-CommandPath([string[]]$Candidates) {
    foreach ($candidate in $Candidates) {
        $command = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($command) { return $command.Source }
    }
    return $null
}

function Invoke-Version([string]$Executable, [string[]]$Arguments) {
    if (-not $Executable -or -not (Test-Path -LiteralPath $Executable -PathType Leaf)) {
        return ''
    }
    $output = & $Executable @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) { return "version probe failed ($LASTEXITCODE)" }
    return ($output | Select-Object -First 1).ToString().Trim()
}

$git = Resolve-CommandPath @('git')
$projectPython = Join-Path $repositoryRoot '.venv\Scripts\python.exe'
$uvOnPath = Resolve-CommandPath @('uv')
$localUv = Join-Path $repositoryRoot '.tools\uv\uv.exe'
$uv = if ($uvOnPath) { $uvOnPath } else { $localUv }
$compilerRoot = if ($env:MSP430_GCC_ROOT) {
    $env:MSP430_GCC_ROOT
} else {
    Join-Path $repositoryRoot '.tools\msp430-gcc\msp430-gcc-9.3.1.11_win64'
}
$supportRoot = if ($env:MSP430_SUPPORT_ROOT) {
    $env:MSP430_SUPPORT_ROOT
} else {
    Join-Path $repositoryRoot '.tools\msp430-support\msp430-gcc-support-files'
}
$compiler = Join-Path $compilerRoot 'bin\msp430-elf-gcc.exe'
$supportHeader = Join-Path $supportRoot 'include\msp430.h'
$docker = Resolve-CommandPath @('docker')
$flasher = Resolve-CommandPath @('MSP430Flasher', 'dslite')
$usbCdcDevice = $null
$usbCdcVersion = ''
$usbCdcPath = ''
if (Get-Command Get-PnpDevice -ErrorAction SilentlyContinue) {
    $usbCdcDevice = Get-PnpDevice -PresentOnly -ErrorAction SilentlyContinue |
        Where-Object {
            $_.InstanceId -match 'VID_0451' -or
            $_.FriendlyName -match 'MSP430|Texas Instruments|TUSS4470|LaunchPad'
        } |
        Select-Object -First 1
    if ($usbCdcDevice) {
        $signedDriver = Get-CimInstance Win32_PnPSignedDriver -ErrorAction SilentlyContinue |
            Where-Object { $_.DeviceID -eq $usbCdcDevice.InstanceId } |
            Select-Object -First 1
        if ($signedDriver) {
            $usbCdcVersion = $signedDriver.DriverVersion
            $usbCdcPath = $signedDriver.InfName
        } else {
            $usbCdcPath = $usbCdcDevice.InstanceId
        }
    }
}

$results = @(
    [pscustomobject]@{ Tool = 'git'; Required = $true; Available = [bool]$git; Version = Invoke-Version $git @('--version'); Path = $git },
    [pscustomobject]@{ Tool = 'project-python'; Required = $true; Available = Test-Path $projectPython -PathType Leaf; Version = Invoke-Version $projectPython @('--version'); Path = $projectPython },
    [pscustomobject]@{ Tool = 'uv'; Required = $true; Available = Test-Path $uv -PathType Leaf; Version = Invoke-Version $uv @('--version'); Path = $uv },
    [pscustomobject]@{ Tool = 'msp430-elf-gcc'; Required = $true; Available = Test-Path $compiler -PathType Leaf; Version = Invoke-Version $compiler @('--version'); Path = $compiler },
    [pscustomobject]@{ Tool = 'msp430-support'; Required = $true; Available = Test-Path $supportHeader -PathType Leaf; Version = '1.212'; Path = $supportHeader },
    [pscustomobject]@{ Tool = 'docker-desktop'; Required = $false; Available = [bool]$docker; Version = Invoke-Version $docker @('--version'); Path = $docker },
    [pscustomobject]@{ Tool = 'msp430-flasher'; Required = $false; Available = [bool]$flasher; Version = Invoke-Version $flasher @('--version'); Path = $flasher },
    [pscustomobject]@{ Tool = 'usb-cdc-device'; Required = $false; Available = [bool]$usbCdcDevice; Version = $usbCdcVersion; Path = $usbCdcPath }
)

$results | Format-Table -AutoSize

$missingRequired = @($results | Where-Object { $_.Required -and -not $_.Available })
if ($missingRequired.Count -gt 0) {
    Write-Error "missing required Windows M0 tools: $($missingRequired.Tool -join ', ')"
    exit 1
}

Write-Host 'Optional Docker, flashing, and connected USB CDC device checks do not block the Windows M0 role.'
Write-Host 'M0 never invokes a flashing tool.'
