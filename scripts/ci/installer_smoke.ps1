# Installer smoke test: fresh install, upgrade over a running copy, uninstall. Destructive on purpose
# (it installs into the real per-user locations), so it only runs on an ephemeral GitHub Actions runner.
param(
    [Parameter(Mandatory)][string]$OldInstaller,
    [Parameter(Mandatory)][string]$OldVersion,
    [Parameter(Mandatory)][string]$NewInstaller,
    [Parameter(Mandatory)][string]$NewVersion
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if ($env:GITHUB_ACTIONS -ne 'true') { throw 'This destructive installer smoke test only runs on a GitHub Actions runner.' }

$appId = '{48F3A59C-4F54-46F3-95DA-C3C43E3A4F25}'
$uninstallKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\${appId}_is1"
$runKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
$expectedDir = Join-Path $env:LOCALAPPDATA 'Programs\ttwatch'
$startMenu = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\ttwatch.lnk'

# A silent run must not open pages, show a tray icon or reach GitHub for an update.
$env:NO_OPEN = '1'
$env:NO_TRAY = '1'
$env:TTWATCH_UPDATE_API = 'http://127.0.0.1:9'

function Assert($ok, $message) { if (-not $ok) { throw "FAILED: $message" } else { Write-Host "ok: $message" } }

function Install($installer) {
    $p = Start-Process $installer -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART' -PassThru -Wait
    Assert ($p.ExitCode -eq 0) "installer $(Split-Path -Leaf $installer) exits 0 (got $($p.ExitCode))"
}

function Find-Ping() {
    foreach ($port in 8765..8774) {
        try {
            $r = Invoke-RestMethod "http://127.0.0.1:$port/api/ping" -TimeoutSec 2
            if ($r.app -eq 'theo-doi-kenh-tiktok') { return $r }
        } catch {}
    }
    return $null
}

function Wait-Ping() {
    # Up to 120 s (240 x 0.5 s): a slow runner took 21 s to start the app once, and the first start also creates the database.
    for ($i = 0; $i -lt 240; $i++) {
        $r = Find-Ping
        if ($r) { return $r }
        Start-Sleep -Milliseconds 500
    }
    throw 'The installed app did not answer /api/ping.'
}

function Wait-Until([scriptblock]$cond, [int]$seconds, $what) {
    for ($i = 0; $i -lt $seconds * 2; $i++) {
        if (& $cond) { return }
        Start-Sleep -Milliseconds 500
    }
    throw "Timed out waiting for: $what"
}

$installDir = $null
try {
    # 1. Fresh install of the older build into the default folder.
    Install $OldInstaller
    $installDir = (Get-ItemProperty -LiteralPath $uninstallKey).InstallLocation.TrimEnd('\')
    Assert ($installDir -eq $expectedDir) "default folder is $expectedDir (got $installDir)"
    $exe = Join-Path $installDir 'ttwatch.exe'
    Assert (Test-Path $exe) 'ttwatch.exe is installed'
    Assert (Test-Path $startMenu) 'Start Menu shortcut exists'
    Assert ((Get-ItemProperty -LiteralPath $uninstallKey).DisplayVersion -eq $OldVersion) "uninstall entry shows $OldVersion"

    # 2. Run it, give it user data and a stale runtime file, and leave it running for the upgrade.
    Start-Process $exe -WorkingDirectory $installDir | Out-Null
    # Both installers carry the same binary, so /api/ping reports the same version for both; only the uninstall entry differs.
    Assert ($null -ne (Wait-Ping)) 'the installed app answers /api/ping'
    $data = Join-Path $installDir 'TheoDoiKenhTiktok_data'
    Assert (Test-Path (Join-Path $data 'data.db')) 'the app created its database beside the exe'
    Set-Content -Path (Join-Path $data 'marker.txt') -Value 'keep me'
    Set-Content -Path (Join-Path $installDir '_internal\stale-runtime.dll') -Value 'left by an older runtime'
    # A fresh runner profile may not have the Run key yet (the first release run for v0.4.0 failed on that): create it only when missing.
    if (-not (Test-Path $runKey)) { New-Item -Path $runKey | Out-Null }
    New-ItemProperty -Path $runKey -Name ttwatch -Value "`"$exe`" --background" -PropertyType String -Force | Out-Null

    # 3. Install the newer build over the running one.
    Install $NewInstaller
    Assert ((Get-ItemProperty -LiteralPath $uninstallKey).DisplayVersion -eq $NewVersion) "uninstall entry shows $NewVersion"
    Assert ((Get-ItemProperty -LiteralPath $uninstallKey).InstallLocation.TrimEnd('\') -eq $installDir) 'same install folder after upgrade'
    Assert (-not (Test-Path (Join-Path $installDir '_internal\stale-runtime.dll'))) 'stale runtime file was cleared'
    Assert ((Get-Content (Join-Path $data 'marker.txt')) -eq 'keep me') 'user data survived the upgrade'
    Assert (Test-Path (Join-Path $data 'data.db')) 'database survived the upgrade'
    Wait-Until { -not (Find-Ping) } 30 'the old running copy to be closed by Setup'
    Start-Process $exe -WorkingDirectory $installDir | Out-Null
    Assert ($null -ne (Wait-Ping)) 'the upgraded app starts and answers /api/ping'

    # 3b. Apply an in-app update to the installed copy with the real helper script from updater.py: it must swap the
    # program files in place, keep the data and Setup's uninstaller, and restart the app (the zip updates installed copies too).
    $work = Join-Path ([IO.Path]::GetTempPath()) "ttwatch-apply-$([guid]::NewGuid().ToString('N'))"
    $newDir = Join-Path $work 'new'
    New-Item -ItemType Directory -Path $newDir | Out-Null
    $applyScript = Join-Path $work 'apply-update.ps1'
    $repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
    python -c "import sys; sys.path.insert(0, sys.argv[1]); import updater; open(sys.argv[2], 'w', encoding='utf-8-sig').write(updater.APPLY_SCRIPT)" $repoRoot $applyScript
    Assert (Test-Path $applyScript) 'apply-update.ps1 was taken from updater.py'
    Copy-Item $exe $newDir
    Copy-Item (Join-Path $installDir '_internal') (Join-Path $newDir '_internal') -Recurse
    Set-Content -Path (Join-Path $newDir '_internal\delivered-by-update.txt') -Value 'new'
    Set-Content -Path (Join-Path $installDir '_internal\removed-by-update.txt') -Value 'old'
    $result = Join-Path $data 'update-result.json'
    Remove-Item -LiteralPath $result -Force -ErrorAction SilentlyContinue
    $running = Get-Process ttwatch | Where-Object { $_.Path -and $_.Path.StartsWith($installDir, [StringComparison]::OrdinalIgnoreCase) } | Select-Object -First 1
    Assert ($null -ne $running) 'the installed app is running before the update'
    $helperArgs = @('-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-WindowStyle', 'Hidden', '-File', $applyScript,
        '-ProcessId', $running.Id, '-InstallDir', $installDir, '-NewDir', $newDir, '-ExeName', 'ttwatch.exe',
        '-ResultFile', $result, '-Version', '9.9.9', '-BrowserDir', (Join-Path $data 'browser_data'), '-Silent', '1') |
        ForEach-Object { if ("$_" -match '\s') { "`"$_`"" } else { "$_" } }
    Start-Process (Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe') -ArgumentList $helperArgs -WindowStyle Hidden
    # The real app exits right after launching the helper; the helper waits for that.
    foreach ($port in 8765..8774) {
        try { Invoke-RestMethod -Method Post "http://127.0.0.1:$port/api/shutdown" -TimeoutSec 2 | Out-Null } catch {}
    }
    Wait-Until { Test-Path -LiteralPath $result } 120 'the update helper to write its result'
    $outcome = Get-Content -LiteralPath $result -Raw | ConvertFrom-Json
    Assert ($outcome.ok -eq $true) "the update was applied (helper said: $($outcome.message))"
    Assert (Test-Path (Join-Path $installDir '_internal\delivered-by-update.txt')) 'new program files are in place'
    Assert (-not (Test-Path (Join-Path $installDir '_internal\removed-by-update.txt'))) 'old program files are gone'
    Assert (Test-Path (Join-Path $installDir 'unins000.exe')) "Setup's uninstaller survived the update"
    Assert ((Get-Content (Join-Path $data 'marker.txt')) -eq 'keep me') 'user data survived the update'
    Assert (Test-Path (Join-Path $data 'data.db')) 'database survived the update'
    Assert ($null -ne (Wait-Ping)) 'the app restarted by the update helper answers /api/ping'
    Wait-Until { -not (Test-Path (Join-Path $installDir '.update')) } 30 'the helper to clean up .update'
    Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue

    # 4. Uninstall while it runs: program files go, data and everything the user made stay.
    $uninstaller = Join-Path $installDir 'unins000.exe'
    Assert (Test-Path $uninstaller) 'uninstaller exists'
    Start-Process $uninstaller -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART' | Out-Null
    # unins000.exe hands over to a temporary copy and returns at once, so wait for the effect.
    Wait-Until { -not (Test-Path -LiteralPath $uninstallKey) } 90 'the uninstall entry to disappear'
    Wait-Until { -not (Test-Path (Join-Path $installDir '_internal')) } 60 'the runtime folder to be removed'
    Assert (-not (Test-Path $exe)) 'ttwatch.exe is removed'
    Assert (-not (Find-Ping)) 'the app is no longer running'
    Assert (-not (Test-Path $startMenu)) 'Start Menu shortcut is removed'
    Assert (-not (Get-ItemProperty -Path $runKey -Name ttwatch -ErrorAction SilentlyContinue)) 'the Start-with-Windows entry is removed'
    Assert ((Get-Content (Join-Path $data 'marker.txt')) -eq 'keep me') 'user data survived the uninstall'
    Assert (Test-Path (Join-Path $data 'data.db')) 'database survived the uninstall'
    Write-Host 'Installer smoke test passed.'
} finally {
    if (Find-Ping) {
        foreach ($port in 8765..8774) {
            try { Invoke-RestMethod -Method Post "http://127.0.0.1:$port/api/shutdown" -TimeoutSec 2 | Out-Null } catch {}
        }
    }
    Get-Process ttwatch -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
}
