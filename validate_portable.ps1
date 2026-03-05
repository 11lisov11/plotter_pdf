param(
    [string]$ZipPath = "dist\PlotterStudio-portable.zip",
    [int]$StartupWaitSeconds = 6
)

$ErrorActionPreference = "Stop"

if (!(Test-Path $ZipPath)) {
    throw "Portable zip not found: $ZipPath"
}

$tempRoot = Join-Path $env:TEMP ("plotter_portable_validate_" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $tempRoot | Out-Null

try {
    Expand-Archive -Path $ZipPath -DestinationPath $tempRoot -Force

    $exe = Get-ChildItem -Path $tempRoot -Recurse -File -Filter "PlotterStudio.exe" | Select-Object -First 1
    if ($null -eq $exe) {
        throw "PlotterStudio.exe not found after archive extraction."
    }

    Write-Host "Portable validation: launching $($exe.FullName)"
    $proc = Start-Process -FilePath $exe.FullName -PassThru
    Start-Sleep -Seconds ([Math]::Max(1, $StartupWaitSeconds))

    if ($proc.HasExited) {
        if ($proc.ExitCode -ne 0) {
            throw "Portable executable exited early with code $($proc.ExitCode)."
        }
        Write-Host "Portable validation: process exited quickly with code 0."
    } else {
        Write-Host "Portable validation: process started successfully, terminating smoke instance."
        Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
    }

    Write-Host "Portable validation: PASS"
}
finally {
    Remove-Item -Path $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
}

