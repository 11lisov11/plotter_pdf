param(
    [string]$Version = "dev"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

python -m pip install --upgrade pip
pip install -r requirements-build.txt

if (Test-Path dist) { Remove-Item -Recurse -Force -LiteralPath dist }
if (Test-Path build) { Remove-Item -Recurse -Force -LiteralPath build }

$pyInstallerDist = Join-Path $root "build\pyinstaller_dist"
$pyInstallerWork = Join-Path $root "build\pyinstaller_work"
$specDir = Join-Path $root "build\specs"
New-Item -ItemType Directory -Force -Path $pyInstallerDist | Out-Null
New-Item -ItemType Directory -Force -Path $pyInstallerWork | Out-Null
New-Item -ItemType Directory -Force -Path $specDir | Out-Null

$coreHiddenImports = @(
    "--hidden-import", "serial",
    "--hidden-import", "serial.tools.list_ports",
    "--hidden-import", "fitz",
    "--hidden-import", "numpy",
    "--hidden-import", "PIL"
)
$photoHiddenImports = @(
    "--hidden-import", "cv2",
    "--hidden-import", "HersheyFonts"
)

pyinstaller --noconfirm --clean --onefile --name PlotterPDF_GUI --windowed --paths . --distpath $pyInstallerDist --workpath $pyInstallerWork --specpath $specDir --hidden-import PySide6.QtCore --hidden-import PySide6.QtGui --hidden-import PySide6.QtWidgets plotter_app\app_entry.py
pyinstaller --noconfirm --clean --onefile --name plotter-pdf --console --paths . --distpath $pyInstallerDist --workpath $pyInstallerWork --specpath $specDir @coreHiddenImports @photoHiddenImports src\cli_main.py
pyinstaller --noconfirm --clean --onefile --name plotter-pdf-self-check --console --paths . --distpath $pyInstallerDist --workpath $pyInstallerWork --specpath $specDir @coreHiddenImports src\plotter_backend\jobs\self_check_cli.py

$bundle = Join-Path $root "dist\PlotterPDF"
New-Item -ItemType Directory -Force -Path $bundle | Out-Null
Copy-Item -Force -LiteralPath (Join-Path $pyInstallerDist "PlotterPDF_GUI.exe") -Destination (Join-Path $bundle "PlotterPDF_GUI.exe")
Copy-Item -Force -LiteralPath (Join-Path $pyInstallerDist "plotter-pdf.exe") -Destination (Join-Path $bundle "plotter-pdf.exe")
Copy-Item -Force -LiteralPath (Join-Path $pyInstallerDist "plotter-pdf-self-check.exe") -Destination (Join-Path $bundle "plotter-pdf-self-check.exe")
Copy-Item -Recurse -Force -LiteralPath "config" -Destination (Join-Path $bundle "config")
if (Test-Path examples) {
    Copy-Item -Recurse -Force -LiteralPath "examples" -Destination (Join-Path $bundle "examples")
} else {
    New-Item -ItemType Directory -Force -Path (Join-Path $bundle "examples") | Out-Null
}
@"
PlotterPDF Windows bundle

Start here:
- PlotterPDF_GUI.exe launches the GUI.
- plotter-pdf.exe --help shows CLI usage.
- plotter-pdf-self-check.exe checks the local environment.

Before real hardware draw, run self-check and verify COM port, pen-up state, sheet fixation, and clear work area.
"@ | Set-Content -Encoding UTF8 -LiteralPath (Join-Path $bundle "README_START_HERE.md")

$expectedBundleFiles = @(
    (Join-Path $bundle "PlotterPDF_GUI.exe"),
    (Join-Path $bundle "plotter-pdf.exe"),
    (Join-Path $bundle "plotter-pdf-self-check.exe"),
    (Join-Path $bundle "config"),
    (Join-Path $bundle "examples"),
    (Join-Path $bundle "examples\simple_square.svg"),
    (Join-Path $bundle "examples\README_examples.md"),
    (Join-Path $bundle "README_START_HERE.md")
)
foreach ($path in $expectedBundleFiles) {
    if (-not (Test-Path -LiteralPath $path)) {
        throw "Missing expected bundle path: $path"
    }
}

$zip = Join-Path $root ("dist\plotter_pdf_windows_{0}.zip" -f $Version)
if (Test-Path $zip) { Remove-Item -Force -LiteralPath $zip }
Compress-Archive -Path $bundle -DestinationPath $zip
Write-Host "Windows bundle ready: $zip"
