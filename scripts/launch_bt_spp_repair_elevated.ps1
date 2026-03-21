param(
    [string]$PreferredPort = "COM11",
    [string]$LogPath = ""
)

$ErrorActionPreference = "Stop"

function Test-IsAdmin {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if (-not $LogPath) {
    $LogPath = Join-Path $root "_tmp\\bt_repair_elevated.txt"
}
$LogPath = [System.IO.Path]::GetFullPath($LogPath)
New-Item -ItemType Directory -Force -Path (Split-Path $LogPath) | Out-Null

if (-not (Test-IsAdmin)) {
    $args = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", "`"$PSCommandPath`"",
        "-PreferredPort", $PreferredPort,
        "-LogPath", "`"$LogPath`""
    )
    Start-Process powershell -Verb RunAs -ArgumentList $args -Wait
    exit $LASTEXITCODE
}

Set-Location $root
$env:PYTHONUNBUFFERED = "1"
$cmd = @(
    "python",
    "scripts\\bt_spp_recovery.py",
    "--preferred-port", $PreferredPort,
    "--attempt-soft-repair"
)

if (Test-Path $LogPath) {
    Remove-Item $LogPath -Force
}
& $cmd[0] $cmd[1] $cmd[2] $cmd[3] $cmd[4] *> $LogPath
exit $LASTEXITCODE
