# Release gate: the packaged folder must never carry a user's database, browser profile or update leftovers.
param(
    [Parameter(Mandatory)]
    [string]$Path
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path -LiteralPath $Path).Path
if (!(Test-Path -LiteralPath (Join-Path $root 'ttwatch.exe'))) {
    throw "Release gate failed: missing ttwatch.exe in $root"
}

$badFiles = Get-ChildItem -LiteralPath $root -Recurse -File -Force -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -match '\.(db|sqlite|sqlite3)(-wal|-shm)?$' -or $_.Name -in 'app.lock', 'app.pid', 'log.txt' }
$badDirs = Get-ChildItem -LiteralPath $root -Recurse -Directory -Force -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -in 'TheoDoiKenhTiktok_data', 'browser_data', '.update', '.omc' }
$found = @($badFiles) + @($badDirs)
if ($found.Count -gt 0) {
    throw "Release gate failed: user data in the package: $($found.FullName -join ', ')"
}
Write-Host "Release gate passed: $root"
