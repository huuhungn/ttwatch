# Package the app as a runnable folder with PyInstaller.
# Run: powershell -File build.ps1
# Needs: a .venv with requirements.txt installed and `uv` on PATH. PyInstaller is installed
# into the venv separately (not in requirements.txt because it is only needed for packaging).
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"

# Probe with a native command: temporarily lower ErrorActionPreference because PowerShell 5.1 treats stderr as an error.
$ErrorActionPreference = "Continue"
& $py -c "import PyInstaller" 2>$null
$have = ($LASTEXITCODE -eq 0)
$ErrorActionPreference = "Stop"
if (-not $have) {
    uv pip install --python $py pyinstaller
    if ($LASTEXITCODE -ne 0) { throw "Could not install PyInstaller" }
}

& $py -m PyInstaller --noconfirm --clean --windowed --name ttwatch `
    --add-data "static;static" `
    --collect-submodules uvicorn --collect-submodules pystray `
    app.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

Write-Host "Done: dist\ttwatch\ttwatch.exe"
Write-Host "Browser: the tool uses the Edge/Chrome already on the machine; if there is none, run 'playwright install chromium' on the target machine."
