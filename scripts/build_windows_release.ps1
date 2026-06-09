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

pyinstaller --noconfirm --clean --name PlotterPDF_GUI --windowed --paths . --collect-all PySide6 plotter_app\app_entry.py
pyinstaller --noconfirm --clean --name plotter-pdf --console --paths . src\cli_main.py
pyinstaller --noconfirm --clean --name plotter-pdf-self-check --console --paths . src\plotter_backend\jobs\self_check_cli.py

$bundle = Join-Path $root "dist\PlotterPDF"
New-Item -ItemType Directory -Force -Path $bundle | Out-Null
Copy-Item -Recurse -Force -LiteralPath "dist\PlotterPDF_GUI" -Destination (Join-Path $bundle "PlotterPDF_GUI.runtime")
Copy-Item -Force -LiteralPath "dist\PlotterPDF_GUI\PlotterPDF_GUI.exe" -Destination (Join-Path $bundle "PlotterPDF_GUI.exe")
Copy-Item -Force -LiteralPath "dist\plotter-pdf\plotter-pdf.exe" -Destination (Join-Path $bundle "plotter-pdf.exe")
Copy-Item -Force -LiteralPath "dist\plotter-pdf-self-check\plotter-pdf-self-check.exe" -Destination (Join-Path $bundle "plotter-pdf-self-check.exe")
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

$zip = Join-Path $root ("dist\plotter_pdf_windows_{0}.zip" -f $Version)
if (Test-Path $zip) { Remove-Item -Force -LiteralPath $zip }
Compress-Archive -Path (Join-Path $bundle "*") -DestinationPath $zip
Write-Host "Windows bundle ready: $zip"
