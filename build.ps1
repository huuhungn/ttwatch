# Đóng gói thành một thư mục chạy được bằng PyInstaller (chưa được kiểm chứng trên máy sạch).
# Chạy: powershell -File build.ps1
# Cần: .venv đã cài requirements.txt; PyInstaller cài riêng vào venv (không nằm trong requirements).
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$py = ".venv\Scripts\python.exe"
& $py -m pip --version *> $null
if ($LASTEXITCODE -ne 0) { uv pip install --python $py pyinstaller } else { & $py -m pip install pyinstaller }

& $py -m PyInstaller --noconfirm --clean --windowed --name TheoDoiKenhTiktok `
    --add-data "static;static" `
    --collect-submodules uvicorn --collect-submodules pystray `
    app.py

Write-Host "Xong: dist\TheoDoiKenhTiktok\TheoDoiKenhTiktok.exe"
Write-Host "Trình duyệt: tool dùng Edge/Chrome có sẵn của máy; nếu không có, cần chạy 'playwright install chromium' trên máy đích."
