param(
    [switch]$NoClean
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$venvPath = Join-Path $root ".venv"
if (-not (Test-Path $venvPath)) {
    py -3 -m venv $venvPath
}

$python = Join-Path $venvPath "Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "Python virtual environment not found: $python"
}

& $python -m pip install --upgrade pip
& $python -m pip install -r requirements.txt pyinstaller

if (-not $NoClean) {
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue (Join-Path $root "build")
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue (Join-Path $root "dist")
    Remove-Item -Force -ErrorAction SilentlyContinue (Join-Path $root "PlotterStudio.spec")
}

$iconPath = Join-Path $root "plotter_studio\assets\icon.ico"
$pyArgs = @(
    "-m", "PyInstaller",
    "--noconsole",
    "--onefile",
    "--name", "PlotterStudio",
    "--icon", $iconPath,
    "--hidden-import", "xml",
    "--hidden-import", "xml.etree",
    "--hidden-import", "xml.etree.ElementTree",
    "--add-data", "src;src",
    "--add-data", "config;config",
    "--add-data", "data;data",
    "--add-data", "plotter_studio/assets;plotter_studio/assets",
    "main.py"
)

& $python $pyArgs
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller build failed."
}

$distDir = Join-Path $root "dist"
$portableDir = Join-Path $distDir "PlotterStudio-portable"
New-Item -ItemType Directory -Force $portableDir | Out-Null

Copy-Item (Join-Path $distDir "PlotterStudio.exe") $portableDir -Force
Copy-Item (Join-Path $root "README.md") $portableDir -Force
if (Test-Path (Join-Path $root "config\PLOTTER_CONTROL_RULES.md")) {
    Copy-Item (Join-Path $root "config\PLOTTER_CONTROL_RULES.md") $portableDir -Force
}

$zipPath = Join-Path $distDir "PlotterStudio-portable.zip"
if (Test-Path $zipPath) {
    Remove-Item -Force $zipPath
}
Compress-Archive -Path (Join-Path $portableDir "*") -DestinationPath $zipPath -Force

Write-Host ""
Write-Host "Build complete."
Write-Host "EXE: $distDir\PlotterStudio.exe"
Write-Host "ZIP: $zipPath"
