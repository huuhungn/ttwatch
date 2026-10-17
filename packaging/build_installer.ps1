# Build the Setup.exe from dist\ttwatch (run build.ps1 first). Needs Inno Setup 6: winget install JRSoftware.InnoSetup
# -Version overrides version.py; the smoke test uses it to build an "older" installer from the same files.
param([string]$Version = '')

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$py = Join-Path $root '.venv\Scripts\python.exe'
if (!(Test-Path -LiteralPath $py)) { $py = 'python' }
if (!$Version) { $Version = (& $py -c "from version import __version__; print(__version__)").Trim() }

$app = Join-Path $root 'dist\ttwatch'
& (Join-Path $PSScriptRoot 'assert_clean_package.ps1') -Path $app

$iscc = @(
    (Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe'),
    (Join-Path $env:ProgramFiles 'Inno Setup 6\ISCC.exe'),
    (Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 6\ISCC.exe')
) | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -First 1
if (!$iscc) { throw 'Inno Setup 6 is required: winget install --id JRSoftware.InnoSetup --exact' }

& $iscc "/DMyAppVersion=$Version" (Join-Path $PSScriptRoot 'ttwatch.iss')
if ($LASTEXITCODE) { throw "Inno Setup failed with exit code $LASTEXITCODE" }

$setup = Join-Path $root "dist\installer\ttwatch-v$Version-Setup.exe"
if (!(Test-Path -LiteralPath $setup)) { throw "Installer was not created: $setup" }
$hash = (Get-FileHash $setup -Algorithm SHA256).Hash.ToLower()
"$hash  $(Split-Path -Leaf $setup)" | Out-File -Encoding ascii "$setup.sha256"
Write-Host "$setup  sha256=$hash"
