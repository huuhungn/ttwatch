# Đóng gói thành một thư mục chạy được bằng PyInstaller.
# Chạy: powershell -File build.ps1
# Cần: .venv đã cài requirements.txt và `uv` trong PATH. PyInstaller được cài riêng vào venv
# (không nằm trong requirements.txt vì chỉ cần khi đóng gói).
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"

# Thăm dò bằng lệnh native: tạm hạ ErrorActionPreference vì PowerShell 5.1 coi stderr là lỗi.
$ErrorActionPreference = "Continue"
& $py -c "import PyInstaller" 2>$null
$have = ($LASTEXITCODE -eq 0)
$ErrorActionPreference = "Stop"
if (-not $have) {
    uv pip install --python $py pyinstaller
    if ($LASTEXITCODE -ne 0) { throw "Không cài được PyInstaller" }
}

& $py -m PyInstaller --noconfirm --clean --windowed --name TheoDoiKenhTiktok `
    --add-data "static;static" `
    --collect-submodules uvicorn --collect-submodules pystray `
    app.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller thất bại" }

Write-Host "Xong: dist\TheoDoiKenhTiktok\TheoDoiKenhTiktok.exe"
Write-Host "Trình duyệt: tool dùng Edge/Chrome có sẵn của máy; nếu không có, cần chạy 'playwright install chromium' trên máy đích."
