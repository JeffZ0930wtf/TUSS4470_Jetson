[CmdletBinding()]
param(
    [switch]$ExternalVpwr7VConfirmed,
    [string]$JetsonHost = '172.20.149.177',
    [string]$JetsonUser = 'yizhouzhao',
    [string]$IdentityFile = (Join-Path ([Environment]::GetFolderPath('UserProfile')) '.ssh\tuss4470_jetson_ed25519'),
    [string]$RemoteRepository = '/home/yizhouzhao/workspace/TUSS4470_software',
    [ValidateRange(1, 65535)][int]$LocalPort = 18080,
    [ValidateRange(1, 65535)][int]$RemotePort = 8000,
    [ValidateRange(1, 300)][int]$ReadyTimeoutSeconds = 30,
    [string]$SshExecutable = 'ssh.exe',
    [string]$RuntimeDirectory = 'D:\Desktop\TUSS4470_data\runtime',
    [switch]$NoBrowser
)

# This Windows entry point owns only remote invocation, port forwarding, and
# opening the local browser. Core and Bridge are always started by the Jetson
# script so their deployment behavior has one implementation.
$ErrorActionPreference = 'Stop'

if (-not $ExternalVpwr7VConfirmed) {
    throw 'Refusing real-device startup without -ExternalVpwr7VConfirmed.'
}
if (-not (Test-Path -LiteralPath $IdentityFile -PathType Leaf)) {
    throw "SSH identity file was not found: $IdentityFile"
}
$sshCommand = Get-Command $SshExecutable -ErrorAction SilentlyContinue
if ($null -eq $sshCommand) {
    throw "SSH executable was not found: $SshExecutable"
}

function Test-UsacJetsonEndpoint {
    param([Parameter(Mandatory)][string]$BaseUrl)

    try {
        $root = $BaseUrl.TrimEnd('/')
        $health = Invoke-RestMethod -Uri "$root/api/v1/health" -TimeoutSec 2
        $device = Invoke-RestMethod -Uri "$root/api/v1/device" -TimeoutSec 2
        return (
            $health.status -eq 'ok' -and
            $device.backend -eq 'BRIDGE' -and
            $device.connected -eq $true
        )
    }
    catch {
        return $false
    }
}

function ConvertTo-PosixSingleQuoted {
    param([Parameter(Mandatory)][string]$Value)

    if ($Value.Contains("'")) {
        throw 'RemoteRepository cannot contain a single quote.'
    }
    return "'" + $Value + "'"
}

$destination = "$JetsonUser@$JetsonHost"
$remoteDirectory = ConvertTo-PosixSingleQuoted -Value $RemoteRepository
$remoteCommand = "cd $remoteDirectory && ./scripts/start-jetson.sh --confirm-external-vpwr-7v"
$commonSshArguments = @(
    '-i', $IdentityFile,
    '-o', 'BatchMode=yes',
    '-o', 'ConnectTimeout=10'
)

Write-Host "Starting the Jetson deployment on $destination ..."
& $sshCommand.Source @commonSshArguments $destination $remoteCommand
if ($LASTEXITCODE -ne 0) {
    throw "Jetson startup failed over SSH with exit code $LASTEXITCODE."
}

$localUrl = "http://127.0.0.1:${LocalPort}/"
$newTunnel = $null
if (Test-UsacJetsonEndpoint -BaseUrl $localUrl) {
    Write-Host "Reusing the existing SSH tunnel at $localUrl"
}
else {
    New-Item -ItemType Directory -Force -Path $RuntimeDirectory | Out-Null
    $forward = "127.0.0.1:${LocalPort}:127.0.0.1:${RemotePort}"
    $tunnelArguments = @(
        $commonSshArguments
        '-o', 'ExitOnForwardFailure=yes',
        '-o', 'ServerAliveInterval=30',
        '-o', 'ServerAliveCountMax=3',
        '-N', '-L', $forward,
        $destination
    )
    $startParameters = @{
        FilePath = $sshCommand.Source
        ArgumentList = $tunnelArguments
        WindowStyle = 'Hidden'
        PassThru = $true
    }
    $newTunnel = Start-Process @startParameters

    $deadline = [DateTime]::UtcNow.AddSeconds($ReadyTimeoutSeconds)
    while ([DateTime]::UtcNow -lt $deadline) {
        if ($newTunnel.HasExited) {
            throw "SSH tunnel exited before becoming ready (exit code $($newTunnel.ExitCode))."
        }
        if (Test-UsacJetsonEndpoint -BaseUrl $localUrl) {
            break
        }
        Start-Sleep -Milliseconds 250
    }
    if (-not (Test-UsacJetsonEndpoint -BaseUrl $localUrl)) {
        if (-not $newTunnel.HasExited) {
            Stop-Process -Id $newTunnel.Id -Force
        }
        throw "SSH tunnel did not become ready within $ReadyTimeoutSeconds seconds."
    }
    $pidFile = Join-Path $RuntimeDirectory 'jetson-ssh-tunnel.pid'
    Set-Content -LiteralPath $pidFile -Value $newTunnel.Id -Encoding ascii
    Write-Host "SSH tunnel ready at $localUrl (PID $($newTunnel.Id); PID file $pidFile)"
}

if (-not $NoBrowser) {
    Start-Process $localUrl
    Write-Host 'Windows browser open requested.'
}
Write-Host "Jetson Web console ready: $localUrl"
