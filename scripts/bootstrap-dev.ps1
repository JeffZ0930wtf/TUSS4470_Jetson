# Creates the repository-local Windows Python environment from the locked
# dependency set. Tool downloads stay under .tools and never modify host Python.
$ErrorActionPreference = 'Stop'

$repositoryRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repositoryRoot

# Keep managed Python and package cache on an ASCII-safe, repository-local
# path. This also prevents worktrees from depending on another Windows user's
# global uv directory or its permissions.
$env:UV_PYTHON_INSTALL_DIR = Join-Path $repositoryRoot '.tools\uv-python'
$env:UV_CACHE_DIR = Join-Path $repositoryRoot '.tools\uv-cache'
New-Item -ItemType Directory -Path $env:UV_PYTHON_INSTALL_DIR -Force | Out-Null
New-Item -ItemType Directory -Path $env:UV_CACHE_DIR -Force | Out-Null

$uvCommand = Get-Command uv -ErrorAction SilentlyContinue
$localUv = Join-Path $repositoryRoot '.tools\uv\uv.exe'
$uvExecutable = if ($uvCommand) {
    $uvCommand.Source
} elseif (Test-Path -LiteralPath $localUv -PathType Leaf) {
    $localUv
} else {
    $null
}
if (-not $uvExecutable) {
    throw @'
uv is required but was not found on PATH.
Install the pinned project version from the official Astral release:
https://github.com/astral-sh/uv/releases/tag/0.12.5
Then open a new PowerShell terminal and run this script again.
'@
}

$uvVersion = (& $uvExecutable --version)
if ($uvVersion -notmatch '^uv 0\.12\.5\b') {
    throw "uv 0.12.5 is required; found: $uvVersion"
}

# Reproducible equivalent: uv sync --frozen --extra dev
& $uvExecutable sync --frozen --extra dev
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$activationScript = Join-Path $repositoryRoot '.venv\Scripts\Activate.ps1'
if (-not (Test-Path -LiteralPath $activationScript)) {
    throw "virtual environment activation script is missing: $activationScript"
}

Write-Host 'Development environment is synchronized.'
Write-Host 'Activate it in the current terminal with:'
Write-Host '  . .\.venv\Scripts\Activate.ps1'
